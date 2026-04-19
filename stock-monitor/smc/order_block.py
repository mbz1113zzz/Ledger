from __future__ import annotations

from datetime import timedelta
from typing import Literal

from smc.types import Candle, OrderBlock, StructureEvent


class OrderBlockIndex:
    def __init__(self, ticker: str, max_age_min: int = 120):
        self._ticker = ticker
        self._max_age = timedelta(minutes=max_age_min)
        self._bars: list[Candle] = []
        self._obs: list[OrderBlock] = []
        self._bar_idx = 0

    def on_candle(self, candle: Candle) -> None:
        self._bars.append(candle)
        self._bar_idx += 1
        for ob in self._obs:
            if ob.status == "invalidated":
                continue
            age = candle.ts - ob.ts
            if age > self._max_age and ob.status == "fresh":
                ob.invalidate()
                continue
            if ob.kind == "bull":
                if candle.c < ob.low:
                    ob.invalidate()
                elif ob.status == "fresh" and candle.l <= ob.high:
                    ob.mitigate()
            else:
                if candle.c > ob.high:
                    ob.invalidate()
                elif ob.status == "fresh" and candle.h >= ob.low:
                    ob.mitigate()

    def on_structure_event(self, ev: StructureEvent) -> list[OrderBlock]:
        if ev.kind not in ("bos_up", "bos_down", "choch_up", "choch_down"):
            return []
        is_up = ev.kind.endswith("_up")
        ob_kind: Literal["bull", "bear"] = "bull" if is_up else "bear"
        for cd in reversed(self._bars):
            opposing = (not cd.is_bullish()) if is_up else cd.is_bullish()
            if opposing:
                ob = OrderBlock(ts=cd.ts, ticker=self._ticker, kind=ob_kind,
                                low=cd.l, high=cd.h, bar_idx=self._bar_idx,
                                status="fresh")
                self._obs.append(ob)
                return [ob]
        return []

    def fresh_bull_obs(self) -> list[OrderBlock]:
        return [o for o in self._obs if o.kind == "bull" and o.status == "fresh"]

    def mitigated_bull_obs(self) -> list[OrderBlock]:
        return [o for o in self._obs if o.kind == "bull" and o.status == "mitigated"]

    def invalidated_bull_obs(self) -> list[OrderBlock]:
        return [o for o in self._obs if o.kind == "bull" and o.status == "invalidated"]

    @property
    def all_obs(self) -> list[OrderBlock]:
        return list(self._obs)
