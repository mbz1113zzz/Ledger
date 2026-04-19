from datetime import datetime, timezone
from smc.types import Candle, Swing, OrderBlock, LiquidityPool, StructureEvent, SmcSignal


def _ts(m=0): return datetime(2026, 4, 19, 14, m, tzinfo=timezone.utc)


def test_candle_range_and_direction():
    c = Candle(ts=_ts(), tf="5m", o=100, h=102, l=99, c=101, v=1000)
    assert c.range() == 3
    assert c.is_bullish() is True
    c2 = Candle(ts=_ts(), tf="5m", o=101, h=102, l=99, c=100, v=900)
    assert c2.is_bullish() is False


def test_swing_and_structure_event():
    s = Swing(ts=_ts(), kind="swing_high", price=105.0, bar_idx=10)
    ev = StructureEvent(ts=_ts(1), kind="bos_up", price=105.5, ticker="NVDA", ref=s)
    assert ev.kind == "bos_up"
    assert ev.ref is s


def test_order_block_contains_and_mitigation():
    ob = OrderBlock(ts=_ts(), ticker="NVDA", kind="bull",
                    low=100.0, high=101.0, bar_idx=3)
    assert ob.contains(100.5) is True
    assert ob.contains(101.5) is False
    assert ob.status == "fresh"
    ob.mitigate()
    assert ob.status == "mitigated"


def test_liquidity_pool_sweep():
    lp = LiquidityPool(ts=_ts(), ticker="NVDA", side="high", price=110.0)
    assert lp.status == "pending"
    lp.sweep(_ts(5))
    assert lp.status == "swept"
    assert lp.swept_at is not None


def test_smc_signal_rr():
    sig = SmcSignal(ts=_ts(), ticker="NVDA", reason="smc_bos_ob",
                    entry=100.0, sl=99.0, tp=102.0, ob_id=1)
    assert sig.rr() == 2.0
