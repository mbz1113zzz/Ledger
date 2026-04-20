from __future__ import annotations

from dataclasses import dataclass

from smc.types import Candle, OrderBlock, SmcSignal, StructureEvent


@dataclass(slots=True)
class PendingSetup:
    reason: str
    ob: OrderBlock
    created_at: object


class SmcEngine:
    def __init__(
        self,
        *,
        ticker: str,
        entry_tf: str = "1m",
        max_risk_pct: float = 0.015,
        min_rr: float = 2.0,
        tick_size: float = 0.01,
    ):
        self._ticker = ticker
        self._entry_tf = entry_tf
        self._max_risk_pct = max_risk_pct
        self._min_rr = min_rr
        self._tick_size = tick_size
        self._last_sweep_low = None
        self._last_sweep_high = None
        self._pending: list[PendingSetup] = []

    def on_structure_event(
        self,
        ev: StructureEvent,
        *,
        trend: str,
        new_obs: list[OrderBlock] | None = None,
    ) -> None:
        self._pending = [p for p in self._pending if p.ob.status != "invalidated"]
        if ev.kind == "liq_sweep_low":
            self._last_sweep_low = ev.ts
            return
        if ev.kind == "liq_sweep_high":
            self._last_sweep_high = ev.ts
            return
        if self._last_sweep_low is None or self._last_sweep_low > ev.ts:
            if self._last_sweep_high is None or self._last_sweep_high > ev.ts:
                return
        bullish = [ob for ob in (new_obs or []) if ob.kind == "bull"]
        bearish = [ob for ob in (new_obs or []) if ob.kind == "bear"]
        if ev.kind == "choch_up" and bullish and self._last_sweep_low is not None:
            self._pending.append(PendingSetup("smc_choch_ob", bullish[0], ev.ts))
            self._last_sweep_low = None
        elif ev.kind == "bos_up" and trend == "up" and bullish and self._last_sweep_low is not None:
            self._pending.append(PendingSetup("smc_bos_ob", bullish[0], ev.ts))
            self._last_sweep_low = None
        elif ev.kind == "choch_down" and bearish and self._last_sweep_high is not None:
            self._pending.append(PendingSetup("smc_choch_ob_short", bearish[0], ev.ts))
            self._last_sweep_high = None
        elif ev.kind == "bos_down" and trend == "down" and bearish and self._last_sweep_high is not None:
            self._pending.append(PendingSetup("smc_bos_ob_short", bearish[0], ev.ts))
            self._last_sweep_high = None

    def on_entry_candle(
        self,
        candle: Candle,
        *,
        pending_high_prices: list[float] | None = None,
        pending_low_prices: list[float] | None = None,
    ) -> list[SmcSignal]:
        if candle.tf != self._entry_tf:
            return []
        out: list[SmcSignal] = []
        keep: list[PendingSetup] = []
        for setup in self._pending:
            ob = setup.ob
            if ob.status == "invalidated":
                continue
            touched = candle.l <= ob.high and candle.h >= ob.low
            if not touched:
                keep.append(setup)
                continue
            entry = candle.c
            side = "long" if ob.kind == "bull" else "short"
            if side == "long":
                sl = ob.low - self._tick_size
                risk = entry - sl
                if entry <= 0 or risk <= 0 or risk / entry > self._max_risk_pct:
                    continue
                tp = entry + self._min_rr * risk
                if pending_high_prices:
                    candidates = [price - self._tick_size for price in pending_high_prices if price > entry]
                    if candidates:
                        tp = max(tp, min(candidates))
            else:
                sl = ob.high + self._tick_size
                risk = sl - entry
                if entry <= 0 or risk <= 0 or risk / entry > self._max_risk_pct:
                    continue
                tp = entry - self._min_rr * risk
                if pending_low_prices:
                    candidates = [price + self._tick_size for price in pending_low_prices if price < entry]
                    if candidates:
                        tp = min(tp, max(candidates))
            sig = SmcSignal(
                ts=candle.ts,
                ticker=self._ticker,
                side=side,
                reason=setup.reason,
                entry=entry,
                sl=sl,
                tp=tp,
            )
            if sig.rr() < self._min_rr:
                continue
            ob.mitigate()
            out.append(sig)
        self._pending = keep
        return out
