from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional


@dataclass(slots=True)
class Candle:
    ts: datetime
    tf: str
    o: float
    h: float
    l: float
    c: float
    v: float

    def range(self) -> float:
        return self.h - self.l

    def is_bullish(self) -> bool:
        return self.c > self.o


@dataclass(slots=True)
class Swing:
    ts: datetime
    kind: Literal["swing_high", "swing_low"]
    price: float
    bar_idx: int


@dataclass(slots=True)
class OrderBlock:
    ts: datetime
    ticker: str
    kind: Literal["bull", "bear"]
    low: float
    high: float
    bar_idx: int
    status: Literal["fresh", "mitigated", "invalidated"] = "fresh"

    def contains(self, price: float) -> bool:
        return self.low <= price <= self.high

    def mitigate(self) -> None:
        if self.status == "fresh":
            self.status = "mitigated"

    def invalidate(self) -> None:
        self.status = "invalidated"


@dataclass(slots=True)
class LiquidityPool:
    ts: datetime
    ticker: str
    side: Literal["high", "low"]
    price: float
    status: Literal["pending", "swept"] = "pending"
    swept_at: Optional[datetime] = None

    def sweep(self, ts: datetime) -> None:
        self.status = "swept"
        self.swept_at = ts


@dataclass(slots=True)
class StructureEvent:
    ts: datetime
    ticker: str
    kind: Literal[
        "swing_high", "swing_low",
        "bos_up", "bos_down",
        "choch_up", "choch_down",
        "ob_bull", "ob_bear",
        "liq_sweep_high", "liq_sweep_low",
    ]
    price: float
    ref: Optional[object] = None


@dataclass(slots=True)
class SmcSignal:
    ts: datetime
    ticker: str
    reason: Literal["smc_choch_ob", "smc_bos_ob"]
    entry: float
    sl: float
    tp: float
    ob_id: int | None = None

    def rr(self) -> float:
        risk = self.entry - self.sl
        reward = self.tp - self.entry
        return reward / risk if risk > 0 else 0.0
