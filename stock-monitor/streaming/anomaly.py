from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from streaming.tick_buffer import TickBuffer


@dataclass(slots=True)
class AnomalySignal:
    ts: datetime
    ticker: str
    tier: Literal["low", "medium", "high"]
    direction: Literal["up", "down"]
    price: float
    pct_open: float
    pct_1m: float


class AnomalyDetector:
    def __init__(
        self,
        buffer: TickBuffer,
        tiers: list[tuple[str, float]],
        cooldown_sec: int = 300,
    ):
        self._buf = buffer
        self._tiers = sorted(tiers, key=lambda t: t[1])
        self._cool = timedelta(seconds=cooldown_sec)
        self._last_fire: dict[tuple[str, str], datetime] = {}

    def feed(
        self, ticker: str, price: float, ts: datetime
    ) -> list[AnomalySignal]:
        open_p = self._buf.open_price(ticker)
        prev_1m = self._buf.price_ago(ticker, seconds=60, now=ts)
        if open_p is None or prev_1m is None:
            return []
        pct_open = (price - open_p) / open_p
        pct_1m = (price - prev_1m) / prev_1m
        if pct_open == 0 or pct_1m == 0:
            return []
        if (pct_open > 0) != (pct_1m > 0):
            return []
        direction = "up" if pct_open > 0 else "down"
        magnitude = min(abs(pct_open), abs(pct_1m))

        out: list[AnomalySignal] = []
        for name, thresh in self._tiers:
            if magnitude < thresh:
                continue
            last = self._last_fire.get((ticker, name))
            if last and ts - last < self._cool:
                continue
            out.append(AnomalySignal(
                ts=ts, ticker=ticker, tier=name, direction=direction,
                price=price, pct_open=pct_open, pct_1m=pct_1m,
            ))
            self._last_fire[(ticker, name)] = ts
        return out
