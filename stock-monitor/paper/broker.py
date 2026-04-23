from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from paper.ledger import Ledger
from paper.pricing import PriceBook
from paper.strategy import SmcLongStrategy
from smc.types import SmcSignal

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
_PUSH_TIMEOUT_SEC = 5.0


@dataclass(slots=True)
class PendingEntry:
    signal: SmcSignal
    signal_id: int | None = None


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
        max_gross_exposure_pct: float = 0.50,
        max_open_risk_pct: float = 0.03,
        slippage_bps: float = 5.0,
        commission_per_share: float = 0.005,
        commission_min: float = 1.0,
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
        self._max_gross_exposure_pct = abs(float(max_gross_exposure_pct))
        self._max_open_risk_pct = abs(float(max_open_risk_pct))
        self._slippage_bps = abs(float(slippage_bps))
        self._commission_per_share = max(0.0, float(commission_per_share))
        self._commission_min = max(0.0, float(commission_min))
        self._notifier = notifier
        self._push_hub = push_hub
        # When circuit breaker trips we stop opening new positions for the day
        # but still manage existing ones.
        self._halted_day: str | None = None
        # Strong refs to fire-and-forget notification tasks so the GC doesn't
        # eat them mid-flight and spam "Task was destroyed" warnings.
        self._pending_tasks: set[asyncio.Task] = set()
        self._pending_entries: dict[str, PendingEntry] = {}

    @property
    def ledger(self) -> Ledger:
        return self._ledger

    def has_open_positions(self) -> bool:
        return bool(self._ledger.positions())

    def cancel_pending_entries(self) -> int:
        count = len(self._pending_entries)
        self._pending_entries.clear()
        return count

    # ----- risk gates -----

    def _check_risk_gate(self, now: datetime) -> str | None:
        """Return a human-readable reason if a new entry should be blocked."""
        # Day is scoped to US/Eastern so the halt survives the UTC midnight
        # that falls mid-session in winter.
        day_key = now.astimezone(_ET).date().isoformat()
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

    def _check_portfolio_limits(self, signal: SmcSignal, qty: int) -> str | None:
        equity = self._ledger.equity_now()
        if equity <= 0:
            return "non_positive_equity"
        projected_open_risk = self._ledger.open_risk_amount() + qty * signal.risk_per_share()
        if projected_open_risk > equity * self._max_open_risk_pct:
            return "open_risk_cap"
        projected_gross_exposure = self._ledger.gross_exposure() + qty * signal.entry
        if projected_gross_exposure > equity * self._max_gross_exposure_pct:
            return "gross_exposure_cap"
        return None

    def _apply_slippage(self, *, price: float, side: str, action: str) -> float:
        if price <= 0 or self._slippage_bps <= 0:
            return price
        slip = price * (self._slippage_bps / 10_000.0)
        if action == "entry":
            return price + slip if side == "long" else max(0.0, price - slip)
        return max(0.0, price - slip) if side == "long" else price + slip

    def _commission(self, qty: int) -> float:
        if qty <= 0 or self._commission_per_share <= 0:
            return 0.0
        return max(self._commission_min, qty * self._commission_per_share)

    # ----- event emission -----

    def _track(self, coro, *, label: str) -> None:
        """Dispatch `coro` as a background task with retention + error logging."""
        try:
            task = asyncio.create_task(coro)
        except RuntimeError:
            # No running loop (sync test context) — drop quietly.
            coro.close()
            return
        self._pending_tasks.add(task)

        def _done(t: asyncio.Task, _label=label):
            self._pending_tasks.discard(t)
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                log.warning("paper notification [%s] failed: %r", _label, exc)

        task.add_done_callback(_done)

    async def _bounded_push(self, title: str, body: str) -> None:
        try:
            await asyncio.wait_for(
                self._push_hub.broadcast_text(title, body),
                timeout=_PUSH_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            log.warning("paper push timed out after %.1fs: %s", _PUSH_TIMEOUT_SEC, title)

    def _emit_event(self, payload: dict, *, push_text: tuple[str, str] | None = None) -> None:
        """Publish to in-process SSE and optionally broadcast to push channels.

        Fire-and-forget: we never let notification failures affect trading.
        """
        if self._notifier is not None:
            self._track(self._notifier.publish(payload), label="sse")
        if push_text is not None and self._push_hub is not None \
                and getattr(self._push_hub, "enabled", False):
            title, body = push_text
            self._track(self._bounded_push(title, body), label="push")

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
        if signal.ticker in self._pending_entries:
            return None
        blocked = self._check_risk_gate(signal.ts)
        if blocked is not None:
            log.info("paper signal for %s blocked: %s", signal.ticker, blocked)
            return None
        self._pending_entries[signal.ticker] = PendingEntry(signal=signal, signal_id=signal_id)
        return {
            "ticker": signal.ticker,
            "status": "queued",
            "side": signal.side,
            "reason": signal.reason,
            "signal_id": signal_id,
        }

    def _fill_pending_entry(self, ticker: str, price: float, ts: datetime) -> dict | None:
        pending = self._pending_entries.get(ticker)
        if pending is None:
            return None
        signal = pending.signal
        if ts <= signal.ts or self._ledger.position_for(ticker) is not None:
            return None
        self._pending_entries.pop(ticker, None)
        blocked = self._check_risk_gate(ts)
        if blocked is not None:
            log.info("paper pending entry for %s canceled: %s", ticker, blocked)
            return None
        fill_price = self._apply_slippage(price=price, side=signal.side, action="entry")
        filled_signal = replace(signal, ts=ts, entry=fill_price)
        qty = self._strategy.size_for_signal(
            filled_signal, equity=self._ledger.equity_now(), cash=self._ledger.cash
        )
        if qty <= 0:
            return None
        blocked = self._check_portfolio_limits(filled_signal, qty)
        if blocked is not None:
            log.info("paper pending entry for %s canceled: %s", ticker, blocked)
            return None
        fee = self._commission(qty)
        self._prices.update(signal.ticker, fill_price, ts)
        pos = self._ledger.open_position(
            filled_signal,
            qty=qty,
            signal_id=pending.signal_id,
            fee=fee,
        )
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
            "fee": fee,
        }
        payload = {
            "type": "paper",
            "action": "open",
            "ts": ts.isoformat(),
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
        opened = self._fill_pending_entry(ticker, price, ts)
        if opened is not None:
            return []
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
                closed = self._ledger.close_position(
                    ticker,
                    price=self._apply_slippage(price=price, side=pos.side, action="exit"),
                    ts=ts,
                    reason=reason,
                    fee=self._commission(pos.qty),
                )
            elif price >= pos.tp:
                closed = self._ledger.close_position(
                    ticker,
                    price=self._apply_slippage(price=price, side=pos.side, action="exit"),
                    ts=ts,
                    reason="tp",
                    fee=self._commission(pos.qty),
                )
        else:
            if price >= pos.sl:
                reason = "be" if pos.sl <= pos.entry_price else "sl"
                closed = self._ledger.close_position(
                    ticker,
                    price=self._apply_slippage(price=price, side=pos.side, action="exit"),
                    ts=ts,
                    reason=reason,
                    fee=self._commission(pos.qty),
                )
            elif price <= pos.tp:
                closed = self._ledger.close_position(
                    ticker,
                    price=self._apply_slippage(price=price, side=pos.side, action="exit"),
                    ts=ts,
                    reason="tp",
                    fee=self._commission(pos.qty),
                )
        if closed is None:
            hold_sec = (ts - pos.entry_ts).total_seconds()
            if hold_sec >= self._max_hold_sec:
                closed = self._ledger.close_position(
                    ticker,
                    price=self._apply_slippage(price=price, side=pos.side, action="exit"),
                    ts=ts,
                    reason="timeout",
                    fee=self._commission(pos.qty),
                )
        if closed is not None:
            self._emit_close(closed)
            return [closed]
        self._ledger.snapshot(ts)
        return []

    async def handle_eod_close(self, ts: datetime | None = None) -> list[dict]:
        ts = ts or datetime.now(timezone.utc)
        out = []
        self._pending_entries.clear()
        for pos in list(self._ledger.positions()):
            price = self._prices.latest(pos.ticker)
            if price is None:
                price = pos.mark_price if pos.mark_price is not None else pos.entry_price
            closed = self._ledger.close_position(
                pos.ticker,
                price=self._apply_slippage(price=price, side=pos.side, action="exit"),
                ts=ts,
                reason="eod",
                fee=self._commission(pos.qty),
            )
            if closed is not None:
                self._emit_close(closed)
                out.append(closed)
        if not out:
            self._ledger.snapshot(ts)
        # Reset daily halt at EOD so next session starts clean.
        self._halted_day = None
        return out
