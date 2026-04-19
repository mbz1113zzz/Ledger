from datetime import datetime, timezone
from smc.liquidity import LiquidityPoolIndex
from smc.types import Candle, Swing


def _c(m, o, h, l, c):
    return Candle(ts=datetime(2026, 4, 19, 14, m, tzinfo=timezone.utc),
                  tf="5m", o=o, h=h, l=l, c=c, v=1000)


def test_swing_high_becomes_pool_then_swept():
    idx = LiquidityPoolIndex(ticker="NVDA")
    sw = Swing(ts=_c(0, 0, 0, 0, 0).ts, kind="swing_high", price=105.0, bar_idx=1)
    idx.on_swing(sw)
    assert any(p.side == "high" and p.status == "pending" for p in idx.pending())
    ev = idx.on_candle(_c(5, 104, 106, 103, 104))
    kinds = [e.kind for e in ev]
    assert "liq_sweep_high" in kinds


def test_close_above_pool_does_not_count_as_sweep():
    idx = LiquidityPoolIndex(ticker="NVDA")
    idx.on_swing(Swing(ts=_c(0, 0, 0, 0, 0).ts, kind="swing_high",
                       price=105.0, bar_idx=1))
    ev = idx.on_candle(_c(5, 104, 106, 103, 106))
    assert ev == []


def test_swing_low_sweep_fires_on_wick_below():
    idx = LiquidityPoolIndex(ticker="NVDA")
    idx.on_swing(Swing(ts=_c(0, 0, 0, 0, 0).ts, kind="swing_low",
                       price=95.0, bar_idx=1))
    ev = idx.on_candle(_c(5, 96, 97, 94, 96))
    kinds = [e.kind for e in ev]
    assert "liq_sweep_low" in kinds
