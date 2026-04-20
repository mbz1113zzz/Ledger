from __future__ import annotations

from dataclasses import dataclass
from math import floor

from smc.types import SmcSignal


@dataclass(slots=True)
class SmcLongStrategy:
    max_position_pct: float = 0.20
    max_risk_per_trade_pct: float = 0.01

    def size_for_signal(self, signal: SmcSignal, *, equity: float, cash: float) -> int:
        risk_per_share = signal.risk_per_share()
        if equity <= 0 or cash <= 0 or signal.entry <= 0 or risk_per_share <= 0:
            return 0
        max_position_value = equity * self.max_position_pct
        max_risk = equity * self.max_risk_per_trade_pct
        qty_by_risk = floor(max_risk / risk_per_share)
        qty_by_cap = floor(max_position_value / signal.entry)
        qty_by_cash = floor(cash / signal.entry)
        return max(0, min(qty_by_risk, qty_by_cap, qty_by_cash))
