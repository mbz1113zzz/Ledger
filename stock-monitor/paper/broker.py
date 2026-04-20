from __future__ import annotations

from datetime import datetime, timezone

from paper.ledger import Ledger
from paper.pricing import PriceBook
from paper.strategy import SmcLongStrategy
from smc.types import SmcSignal


class PaperBroker:
    def __init__(
        self,
        *,
        ledger: Ledger,
        strategy: SmcLongStrategy,
        prices: PriceBook,
        max_hold_min: int = 60,
        break_even_enabled: bool = True,
        break_even_r: float = 1.0,
    ):
        self._ledger = ledger
        self._strategy = strategy
        self._prices = prices
        self._max_hold_sec = max_hold_min * 60
        self._break_even_enabled = break_even_enabled
        self._break_even_r = break_even_r

    @property
    def ledger(self) -> Ledger:
        return self._ledger

    async def on_smc_signal(self, signal: SmcSignal, *, signal_id: int | None = None) -> dict | None:
        if self._ledger.position_for(signal.ticker) is not None:
            return None
        qty = self._strategy.size_for_signal(
            signal, equity=self._ledger.equity_now(), cash=self._ledger.cash
        )
        if qty <= 0:
            return None
        self._prices.update(signal.ticker, signal.entry, signal.ts)
        pos = self._ledger.open_position(signal, qty=qty, signal_id=signal_id)
        if pos is None:
            return None
        return {"ticker": pos.ticker, "qty": pos.qty, "entry": pos.entry_price, "side": pos.side}

    async def on_tick(self, ticker: str, price: float, ts: datetime) -> list[dict]:
        self._prices.update(ticker, price, ts)
        pos = self._ledger.mark_price(ticker, price, ts)
        if pos is None:
            return []
        if self._break_even_enabled:
            one_r = pos.risk_per_share * self._break_even_r
            if pos.side == "long" and pos.sl < pos.entry_price and price >= pos.entry_price + one_r:
                self._ledger.update_stop(ticker, sl=pos.entry_price, ts=ts)
                pos = self._ledger.position_for(ticker) or pos
            elif pos.side == "short" and pos.sl > pos.entry_price and price <= pos.entry_price - one_r:
                self._ledger.update_stop(ticker, sl=pos.entry_price, ts=ts)
                pos = self._ledger.position_for(ticker) or pos
        if pos.side == "long":
            if price <= pos.sl:
                reason = "be" if pos.sl >= pos.entry_price else "sl"
                closed = self._ledger.close_position(ticker, price=price, ts=ts, reason=reason)
                return [closed] if closed is not None else []
            if price >= pos.tp:
                closed = self._ledger.close_position(ticker, price=price, ts=ts, reason="tp")
                return [closed] if closed is not None else []
        else:
            if price >= pos.sl:
                reason = "be" if pos.sl <= pos.entry_price else "sl"
                closed = self._ledger.close_position(ticker, price=price, ts=ts, reason=reason)
                return [closed] if closed is not None else []
            if price <= pos.tp:
                closed = self._ledger.close_position(ticker, price=price, ts=ts, reason="tp")
                return [closed] if closed is not None else []
        hold_sec = (ts - pos.entry_ts).total_seconds()
        if hold_sec >= self._max_hold_sec:
            closed = self._ledger.close_position(ticker, price=price, ts=ts, reason="timeout")
            return [closed] if closed is not None else []
        self._ledger.snapshot(ts)
        return []

    async def handle_eod_close(self, ts: datetime | None = None) -> list[dict]:
        ts = ts or datetime.now(timezone.utc)
        out = []
        for pos in list(self._ledger.positions()):
            price = self._prices.latest(pos.ticker)
            if price is None:
                price = pos.mark_price if pos.mark_price is not None else pos.entry_price
            closed = self._ledger.close_position(pos.ticker, price=price, ts=ts, reason="eod")
            if closed is not None:
                out.append(closed)
        if not out:
            self._ledger.snapshot(ts)
        return out
