from datetime import datetime, timezone
from smc.order_block import OrderBlockIndex
from smc.types import Candle, StructureEvent


def _c(m, o, h, l, c):
    return Candle(ts=datetime(2026, 4, 19, 14, m, tzinfo=timezone.utc),
                  tf="5m", o=o, h=h, l=l, c=c, v=1000)


def test_bullish_ob_from_last_bearish_candle_before_bos_up():
    idx = OrderBlockIndex(ticker="NVDA", max_age_min=120)
    candles = [
        _c(0, 101, 101, 99, 100),
        _c(5, 100, 106, 100, 105),
        _c(10, 105, 108, 104, 107),
    ]
    for cd in candles:
        idx.on_candle(cd)
    ev = StructureEvent(ts=candles[-1].ts, ticker="NVDA",
                        kind="bos_up", price=107, ref=None)
    obs = idx.on_structure_event(ev)
    assert len(obs) == 1
    assert obs[0].kind == "bull"
    assert obs[0].low == 99
    assert obs[0].high == 101


def test_ob_mitigated_when_price_reenters_range():
    idx = OrderBlockIndex(ticker="NVDA", max_age_min=120)
    idx.on_candle(_c(0, 101, 101, 99, 100))
    idx.on_candle(_c(5, 100, 106, 100, 105))
    idx.on_structure_event(StructureEvent(ts=_c(5, 0, 0, 0, 0).ts,
                                          ticker="NVDA", kind="bos_up",
                                          price=105, ref=None))
    idx.on_candle(_c(10, 104, 104, 100, 100))
    assert len(idx.fresh_bull_obs()) == 0
    assert len(idx.mitigated_bull_obs()) == 1


def test_ob_invalidated_when_price_breaks_low():
    idx = OrderBlockIndex(ticker="NVDA", max_age_min=120)
    idx.on_candle(_c(0, 101, 101, 99, 100))
    idx.on_candle(_c(5, 100, 106, 100, 105))
    idx.on_structure_event(StructureEvent(ts=_c(5, 0, 0, 0, 0).ts,
                                          ticker="NVDA", kind="bos_up",
                                          price=105, ref=None))
    idx.on_candle(_c(10, 100, 100, 97, 98))
    assert len(idx.fresh_bull_obs()) == 0
    assert len(idx.invalidated_bull_obs()) == 1


def test_ob_expires_after_max_age():
    idx = OrderBlockIndex(ticker="NVDA", max_age_min=10)
    idx.on_candle(_c(0, 101, 101, 99, 100))
    idx.on_candle(_c(5, 100, 106, 100, 105))
    idx.on_structure_event(StructureEvent(ts=_c(5, 0, 0, 0, 0).ts,
                                          ticker="NVDA", kind="bos_up",
                                          price=105, ref=None))
    idx.on_candle(_c(30, 110, 112, 108, 111))
    assert len(idx.fresh_bull_obs()) == 0
    assert len(idx.invalidated_bull_obs()) == 1
