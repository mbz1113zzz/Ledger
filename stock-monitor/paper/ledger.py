from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from smc.types import SmcSignal
from storage import Storage


@dataclass(slots=True)
class Position:
    ticker: str
    side: str
    qty: int
    entry_price: float
    entry_ts: datetime
    sl: float
    tp: float
    reason: str
    signal_id: int | None = None
    mark_price: float | None = None

    @property
    def risk_per_share(self) -> float:
        return (self.entry_price - self.sl) if self.side == "long" else (self.sl - self.entry_price)

    def market_value(self) -> float:
        px = self.mark_price if self.mark_price is not None else self.entry_price
        return self.qty * px if self.side == "long" else -self.qty * px

    def unrealized_pnl(self) -> float:
        if self.mark_price is None:
            return 0.0
        if self.side == "long":
            return (self.mark_price - self.entry_price) * self.qty
        return (self.entry_price - self.mark_price) * self.qty


class Ledger:
    def __init__(self, storage: Storage, initial_cash: float = 10_000.0):
        self._storage = storage
        last = storage.last_paper_equity()
        self.cash = float(last["cash"]) if last is not None else float(initial_cash)
        self._positions: dict[str, Position] = {}
        for row in storage.list_paper_positions():
            self._positions[row["ticker"]] = Position(
                ticker=row["ticker"],
                side=row.get("side", "long"),
                qty=int(row["qty"]),
                entry_price=float(row["entry_price"]),
                entry_ts=datetime.fromisoformat(row["entry_ts"]),
                sl=float(row["sl"]),
                tp=float(row["tp"]),
                reason=row["reason"],
                signal_id=row["signal_id"],
                mark_price=float(row["mark_price"]),
            )

    def positions(self) -> list[Position]:
        return list(self._positions.values())

    def position_for(self, ticker: str) -> Position | None:
        return self._positions.get(ticker)

    def positions_value(self) -> float:
        return sum(pos.market_value() for pos in self._positions.values())

    def equity_now(self) -> float:
        return self.cash + self.positions_value()

    def snapshot(self, ts: datetime) -> dict:
        positions_value = self.positions_value()
        equity = self.cash + positions_value
        self._storage.record_paper_equity(
            ts=ts, cash=self.cash, positions_value=positions_value, equity=equity
        )
        return {
            "ts": ts.isoformat(),
            "cash": round(self.cash, 4),
            "positions_value": round(positions_value, 4),
            "equity": round(equity, 4),
        }

    def open_position(
        self, signal: SmcSignal, *, qty: int, signal_id: int | None = None
    ) -> Position | None:
        if qty <= 0 or signal.ticker in self._positions:
            return None
        cost = qty * signal.entry
        if signal.side == "long" and cost > self.cash:
            return None
        if signal.side == "long":
            self.cash -= cost
        else:
            self.cash += cost
        pos = Position(
            ticker=signal.ticker,
            side=signal.side,
            qty=qty,
            entry_price=signal.entry,
            entry_ts=signal.ts,
            sl=signal.sl,
            tp=signal.tp,
            reason=signal.reason,
            signal_id=signal_id,
            mark_price=signal.entry,
        )
        self._positions[signal.ticker] = pos
        self._storage.upsert_paper_position(
            ticker=pos.ticker,
            side=pos.side,
            qty=pos.qty,
            entry_price=pos.entry_price,
            entry_ts=pos.entry_ts,
            sl=pos.sl,
            tp=pos.tp,
            reason=pos.reason,
            signal_id=pos.signal_id,
            mark_price=pos.mark_price or pos.entry_price,
            updated_at=signal.ts,
        )
        self._storage.insert_paper_trade(
            ts=signal.ts,
            ticker=signal.ticker,
            side="buy" if signal.side == "long" else "sell",
            qty=qty,
            price=signal.entry,
            reason=signal.reason,
            signal_id=signal_id,
        )
        self.snapshot(signal.ts)
        return pos

    def mark_price(self, ticker: str, price: float, ts: datetime) -> Position | None:
        pos = self._positions.get(ticker)
        if pos is None:
            return None
        pos.mark_price = price
        self._storage.upsert_paper_position(
            ticker=pos.ticker,
            side=pos.side,
            qty=pos.qty,
            entry_price=pos.entry_price,
            entry_ts=pos.entry_ts,
            sl=pos.sl,
            tp=pos.tp,
            reason=pos.reason,
            signal_id=pos.signal_id,
            mark_price=price,
            updated_at=ts,
        )
        return pos

    def update_stop(self, ticker: str, *, sl: float, ts: datetime) -> Position | None:
        pos = self._positions.get(ticker)
        if pos is None:
            return None
        pos.sl = sl
        self._storage.upsert_paper_position(
            ticker=pos.ticker,
            side=pos.side,
            qty=pos.qty,
            entry_price=pos.entry_price,
            entry_ts=pos.entry_ts,
            sl=pos.sl,
            tp=pos.tp,
            reason=pos.reason,
            signal_id=pos.signal_id,
            mark_price=pos.mark_price if pos.mark_price is not None else pos.entry_price,
            updated_at=ts,
        )
        return pos

    def close_position(self, ticker: str, *, price: float, ts: datetime, reason: str) -> dict | None:
        pos = self._positions.pop(ticker, None)
        if pos is None:
            return None
        notional = pos.qty * price
        if pos.side == "long":
            pnl = (price - pos.entry_price) * pos.qty
            rr = ((price - pos.entry_price) / pos.risk_per_share) if pos.risk_per_share > 0 else None
            self.cash += notional
        else:
            pnl = (pos.entry_price - price) * pos.qty
            rr = ((pos.entry_price - price) / pos.risk_per_share) if pos.risk_per_share > 0 else None
            self.cash -= notional
        self._storage.delete_paper_position(ticker)
        self._storage.insert_paper_trade(
            ts=ts,
            ticker=ticker,
            side="sell" if pos.side == "long" else "buy",
            qty=pos.qty,
            price=price,
            reason=reason,
            pnl=pnl,
            signal_id=pos.signal_id,
            rr=rr,
        )
        snap = self.snapshot(ts)
        return {
            "ticker": ticker,
            "side": pos.side,
            "qty": pos.qty,
            "entry_price": pos.entry_price,
            "exit_price": price,
            "reason": reason,
            "pnl": pnl,
            "rr": rr,
            "ts": ts.isoformat(),
            "equity": snap["equity"],
        }

    def positions_payload(self) -> list[dict]:
        out = []
        for pos in self.positions():
            d = asdict(pos)
            d["entry_ts"] = pos.entry_ts.isoformat()
            d["market_value"] = round(pos.market_value(), 4)
            d["unrealized_pnl"] = round(pos.unrealized_pnl(), 4)
            out.append(d)
        return out
