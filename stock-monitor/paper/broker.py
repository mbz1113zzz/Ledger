from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from paper.ledger import Ledger
from paper.pricing import PriceBook
from paper.strategy import SmcLongStrategy
from smc.types import SmcSignal

log = logging.getLogger(__name__)


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
        max_positions: int = 5,
        max_day_drawdown_pct: float = 0.03,
        notifier=None,
        push_hub=None,
    ):
        self._ledger = ledger
        self._strategy = strategy
        self._prices = prices
        self._max_hold_sec = max_hold_min * 60
        self._break_even_enabled = break_even_enabled
        self._break_even_r = break_even_r
        self._max_positions = max(1, int(max_positions))
        self._max_day_drawdown = abs(float(max_day_drawdown_pct))
        self._notifier = notifier
        self._push_hub = push_hub
        # When circuit breaker trips we stop opening new positions for the day
        # but still manage existing ones.
        self._halted_day: str | None = None

    @property
    def ledger(self) -> Ledger:
        return self._ledger

    # ----- risk gates -----

    def _check_risk_gate(self, now: datetime) -> str | None:
        """Return a human-readable reason if a new entry should be blocked."""
        day_key = now.astimezone(timezone.utc).date().isoformat()
        if self._halted_day == day_key:
            return "day halted"
        if len(self._ledger.positions()) >= self._max_positions:
            return f"max_positions={self._max_positions} reached"
        dd = self._ledger.day_pnl_pct(now)
        if dd <= -self._max_day_drawdown:
            self._halted_day = day_key
            log.warning("paper broker halted: day_pnl=%.2f%% <= -%.2f%%",
                        dd * 100, self._max_day_drawdown * 100)
            self._emit_event({
                "type": "paper",
                "action": "halt",
                "ts": now.isoformat(),
                "day_pnl_pct": round(dd, 4),
                "reason": "day_drawdown",
            }, push_text=("Paper trading halted",
                          f"Day PnL {dd*100:.2f}% breached "
                          f"-{self._max_day_drawdown*100:.2f}% cap"))
            return "day drawdown cap"
        return None

    # ----- event emission -----

    def _emit_event(self, payload: dict, *, push_text: tuple[str, str] | None = None) -> None:
        """Publish to in-process SSE and optionally broadcast to push channels.

        Fire-and-forget: we never let notification failures affect trading.
        """
        if self._notifier is not None:
            try:
                asyncio.create_task(self._notifier.publish(payload))
            except RuntimeError:
                # No running loop (e.g. called from a sync test context)
                pass
            except Exception as e:
                log.exception("notifier publish failed: %s", e)
        if push_text is not None and self._push_hub is not None \
                and getattr(self._push_hub, "enabled", False):
            title, body = push_text
            try:
                asyncio.create_task(self._push_hub.broadcast_text(title, body))
            except RuntimeError:
                pass
            except Exception as e:
                log.exception("push broadcast failed: %s", e)

    @staticmethod
    def _fmt_open(pos_dict: dict) -> tuple[str, str]:
        t = pos_dict["ticker"]
        return (
            f"[{t}] paper OPEN {pos_dict['side']}",
            f"qty={pos_dict['qty']} @ {pos_dict['entry']:.4f} "
            f"reason={pos_dict.get('reason','')}",
        )

    @staticmethod
    def _fmt_close(closed: dict) -> tuple[str, str]:
        t = closed["ticker"]
        pnl = closed.get("pnl") or 0.0
        rr = closed.get("rr")
        rr_txt = f" R={rr:.2f}" if isinstance(rr, (int, float)) else ""
        return (
            f"[{t}] paper CLOSE {closed.get('reason','')}",
            f"{closed['side']} {closed['qty']} exit={closed['exit_price']:.4f} "
            f"pnl={pnl:+.2f}{rr_txt}",
        )

    # ----- trading -----

    async def on_smc_signal(self, signal: SmcSignal, *, signal_id: int | None = None) -> dict | None:
        if self._ledger.position_for(signal.ticker) is not None:
            return None
        blocked = self._check_risk_gate(signal.ts)
        if blocked is not None:
            log.info("paper signal for %s blocked: %s", signal.ticker, blocked)
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
        result = {
            "ticker": pos.ticker,
            "qty": pos.qty,
            "entry": pos.entry_price,
            "side": pos.side,
            "reason": pos.reason,
            "sl": pos.sl,
            "tp": pos.tp,
        }
        payload = {
            "type": "paper",
            "action": "open",
            "ts": signal.ts.isoformat(),
            **result,
        }
        self._emit_event(payload, push_text=self._fmt_open(result))
        return result

    def _emit_close(self, closed: dict) -> None:
        reason = closed.get("reason")
        payload = {"type": "paper", "action": "close", **closed}
        # Push only on decisive exits to avoid spam from break-even scratches.
        push = None
        if reason in {"tp", "sl", "eod"}:
            push = self._fmt_close(closed)
        self._emit_event(payload, push_text=push)

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
        closed: dict | None = None
        if pos.side == "long":
            if price <= pos.sl:
                reason = "be" if pos.sl >= pos.entry_price else "sl"
                closed = self._ledger.close_position(ticker, price=price, ts=ts, reason=reason)
            elif price >= pos.tp:
                closed = self._ledger.close_position(ticker, price=price, ts=ts, reason="tp")
        else:
            if price >= pos.sl:
                reason = "be" if pos.sl <= pos.entry_price else "sl"
                closed = self._ledger.close_position(ticker, price=price, ts=ts, reason=reason)
            elif price <= pos.tp:
                closed = self._ledger.close_position(ticker, price=price, ts=ts, reason="tp")
        if closed is None:
            hold_sec = (ts - pos.entry_ts).total_seconds()
            if hold_sec >= self._max_hold_sec:
                closed = self._ledger.close_position(ticker, price=price, ts=ts, reason="timeout")
        if closed is not None:
            self._emit_close(closed)
            return [closed]
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
                self._emit_close(closed)
                out.append(closed)
        if not out:
            self._ledger.snapshot(ts)
        # Reset daily halt at EOD so next session starts clean.
        self._halted_day = None
        return out
