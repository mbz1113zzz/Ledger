from datetime import datetime, timezone

from paper.strategy import SmcLongStrategy
from smc.types import SmcSignal


def _signal() -> SmcSignal:
    return SmcSignal(
        ts=datetime(2026, 4, 19, 14, 30, tzinfo=timezone.utc),
        ticker="NVDA",
        entry=100.0,
        sl=99.0,
        tp=102.0,
        reason="smc_bos_ob",
    )


def test_position_sizing_is_risk_first():
    strategy = SmcLongStrategy(max_position_pct=0.20, max_risk_per_trade_pct=0.01)
    qty = strategy.size_for_signal(_signal(), equity=10_000.0, cash=10_000.0)
    assert qty == 20


def test_position_sizing_returns_zero_when_cash_is_insufficient():
    strategy = SmcLongStrategy()
    qty = strategy.size_for_signal(_signal(), equity=10_000.0, cash=50.0)
    assert qty == 0


def test_position_sizing_supports_short_signal():
    strategy = SmcLongStrategy(max_position_pct=0.20, max_risk_per_trade_pct=0.01)
    sig = SmcSignal(
        ts=datetime(2026, 4, 19, 14, 30, tzinfo=timezone.utc),
        ticker="TSLA",
        entry=100.0,
        sl=101.0,
        tp=98.0,
        side="short",
        reason="smc_bos_ob_short",
    )
    qty = strategy.size_for_signal(sig, equity=10_000.0, cash=10_000.0)
    assert qty == 20
