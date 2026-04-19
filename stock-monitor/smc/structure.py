from __future__ import annotations

from collections import deque
from typing import Deque, Literal

from smc.types import Candle, StructureEvent, Swing


Trend = Literal["up", "down", "none"]


class StructureTracker:
    def __init__(self, ticker: str, fractal_window: int = 5):
        if fractal_window < 3 or fractal_window % 2 == 0:
            raise ValueError("fractal_window must be odd and >= 3")
        self._ticker = ticker
        self._w = fractal_window
        self._center_offset = fractal_window // 2
        self._bars: Deque[Candle] = deque(maxlen=fractal_window)
        self._bar_idx = 0
        self._swings: list[Swing] = []
        self._trend: Trend = "none"
        self._last_broken_high: float | None = None
        self._last_broken_low: float | None = None

    def on_candle(self, candle: Candle) -> list[StructureEvent]:
        out: list[StructureEvent] = []
        self._bars.append(candle)
        self._bar_idx += 1

        if len(self._bars) == self._w:
            center = self._bars[self._center_offset]
            if all(center.h > b.h for i, b in enumerate(self._bars) if i != self._center_offset):
                sw = Swing(ts=center.ts, kind="swing_high", price=center.h,
                           bar_idx=self._bar_idx - self._center_offset)
                self._swings.append(sw)
                out.append(StructureEvent(ts=candle.ts, ticker=self._ticker,
                                          kind="swing_high", price=center.h, ref=sw))
            if all(center.l < b.l for i, b in enumerate(self._bars) if i != self._center_offset):
                sw = Swing(ts=center.ts, kind="swing_low", price=center.l,
                           bar_idx=self._bar_idx - self._center_offset)
                self._swings.append(sw)
                out.append(StructureEvent(ts=candle.ts, ticker=self._ticker,
                                          kind="swing_low", price=center.l, ref=sw))

        last_high = self._last_unbroken("swing_high")
        last_low = self._last_unbroken("swing_low")
        if last_high is not None and candle.c > last_high.price:
            if self._trend == "down":
                out.append(StructureEvent(ts=candle.ts, ticker=self._ticker,
                                          kind="choch_up", price=candle.c, ref=last_high))
            else:
                out.append(StructureEvent(ts=candle.ts, ticker=self._ticker,
                                          kind="bos_up", price=candle.c, ref=last_high))
            self._trend = "up"
            self._last_broken_high = last_high.price
        if last_low is not None and candle.c < last_low.price:
            if self._trend == "up":
                out.append(StructureEvent(ts=candle.ts, ticker=self._ticker,
                                          kind="choch_down", price=candle.c, ref=last_low))
            else:
                out.append(StructureEvent(ts=candle.ts, ticker=self._ticker,
                                          kind="bos_down", price=candle.c, ref=last_low))
            self._trend = "down"
            self._last_broken_low = last_low.price
        return out

    def _last_unbroken(self, kind: str) -> Swing | None:
        for sw in reversed(self._swings):
            if sw.kind != kind:
                continue
            if kind == "swing_high" and self._last_broken_high is not None and sw.price <= self._last_broken_high:
                continue
            if kind == "swing_low" and self._last_broken_low is not None and sw.price >= self._last_broken_low:
                continue
            return sw
        return None

    @property
    def trend(self) -> Trend:
        return self._trend

    @property
    def swings(self) -> list[Swing]:
        return list(self._swings)
