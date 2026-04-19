from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Deque


@dataclass(slots=True)
class _Tick:
    ts: datetime
    price: float


class TickBuffer:
    def __init__(self, max_age_sec: int = 900):
        self._max_age = timedelta(seconds=max_age_sec)
        self._data: dict[str, Deque[_Tick]] = {}
        self._opens: dict[str, tuple[datetime, float]] = {}

    def set_open(self, ticker: str, price: float, ts: datetime) -> None:
        self._opens[ticker] = (ts, price)

    def open_price(self, ticker: str) -> float | None:
        rec = self._opens.get(ticker)
        return rec[1] if rec else None

    def update(self, ticker: str, price: float, ts: datetime) -> None:
        dq = self._data.setdefault(ticker, deque())
        dq.append(_Tick(ts, price))
        cutoff = ts - self._max_age
        while dq and dq[0].ts < cutoff:
            dq.popleft()

    def last_price(self, ticker: str) -> float | None:
        dq = self._data.get(ticker)
        return dq[-1].price if dq else None

    def price_ago(
        self, ticker: str, *, seconds: int, now: datetime | None = None
    ) -> float | None:
        dq = self._data.get(ticker)
        if not dq:
            return None
        now = now or dq[-1].ts
        target = now - timedelta(seconds=seconds)
        for tick in reversed(dq):
            if tick.ts <= target:
                return tick.price
        return None
