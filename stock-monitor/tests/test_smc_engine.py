from datetime import datetime, timezone

from smc.engine import SmcEngine
from smc.types import Candle, OrderBlock, StructureEvent


def _ts(minute: int) -> datetime:
    return datetime(2026, 4, 19, 14, minute, tzinfo=timezone.utc)


def _c(minute: int, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(ts=_ts(minute), tf="1m", o=o, h=h, l=l, c=c, v=1000)


def _bull_ob() -> OrderBlock:
    return OrderBlock(ts=_ts(5), ticker="NVDA", kind="bull",
                      low=100.0, high=101.0, bar_idx=1)


def test_choch_setup_emits_signal_on_retest():
    engine = SmcEngine(ticker="NVDA", tick_size=0.01)
    engine.on_structure_event(
        StructureEvent(ts=_ts(10), ticker="NVDA", kind="liq_sweep_low", price=99.0, ref=None),
        trend="none",
    )
    engine.on_structure_event(
        StructureEvent(ts=_ts(15), ticker="NVDA", kind="choch_up", price=103.0, ref=None),
        trend="up",
        new_obs=[_bull_ob()],
    )
    sigs = engine.on_entry_candle(_c(20, 102.0, 102.0, 100.5, 101.2), pending_high_prices=[108.0])
    assert len(sigs) == 1
    assert sigs[0].reason == "smc_choch_ob"
    assert sigs[0].side == "long"
    assert sigs[0].entry == 101.2
    assert sigs[0].sl == 99.99
    assert sigs[0].tp >= sigs[0].entry + 2 * (sigs[0].entry - sigs[0].sl)


def test_bos_setup_emits_signal_when_trend_is_up():
    engine = SmcEngine(ticker="NVDA")
    engine.on_structure_event(
        StructureEvent(ts=_ts(10), ticker="NVDA", kind="liq_sweep_low", price=99.0, ref=None),
        trend="down",
    )
    engine.on_structure_event(
        StructureEvent(ts=_ts(15), ticker="NVDA", kind="bos_up", price=104.0, ref=None),
        trend="up",
        new_obs=[_bull_ob()],
    )
    sigs = engine.on_entry_candle(_c(20, 102.0, 102.2, 100.8, 101.4), pending_high_prices=[106.0])
    assert len(sigs) == 1
    assert sigs[0].reason == "smc_bos_ob"


def test_large_risk_signal_is_filtered_out():
    engine = SmcEngine(ticker="NVDA", max_risk_pct=0.015)
    engine.on_structure_event(
        StructureEvent(ts=_ts(10), ticker="NVDA", kind="liq_sweep_low", price=90.0, ref=None),
        trend="none",
    )
    engine.on_structure_event(
        StructureEvent(ts=_ts(15), ticker="NVDA", kind="choch_up", price=105.0, ref=None),
        trend="up",
        new_obs=[OrderBlock(ts=_ts(5), ticker="NVDA", kind="bull",
                            low=95.0, high=100.0, bar_idx=1)],
    )
    sigs = engine.on_entry_candle(_c(20, 101.0, 101.0, 99.0, 100.0), pending_high_prices=[120.0])
    assert sigs == []


def test_single_sweep_is_consumed_by_first_matching_structure_event():
    engine = SmcEngine(ticker="NVDA")
    engine.on_structure_event(
        StructureEvent(ts=_ts(10), ticker="NVDA", kind="liq_sweep_low", price=99.0, ref=None),
        trend="down",
    )
    engine.on_structure_event(
        StructureEvent(ts=_ts(15), ticker="NVDA", kind="bos_up", price=104.0, ref=None),
        trend="up",
        new_obs=[_bull_ob()],
    )
    engine.on_structure_event(
        StructureEvent(ts=_ts(16), ticker="NVDA", kind="bos_up", price=105.0, ref=None),
        trend="up",
        new_obs=[_bull_ob()],
    )
    sigs = engine.on_entry_candle(_c(20, 102.0, 102.2, 100.8, 101.4), pending_high_prices=[106.0])
    assert len(sigs) == 1


def test_short_setup_emits_short_signal_on_bearish_retest():
    engine = SmcEngine(ticker="TSLA", tick_size=0.01)
    bear_ob = OrderBlock(ts=_ts(5), ticker="TSLA", kind="bear",
                         low=100.0, high=101.0, bar_idx=1)
    engine.on_structure_event(
        StructureEvent(ts=_ts(10), ticker="TSLA", kind="liq_sweep_high", price=103.0, ref=None),
        trend="up",
    )
    engine.on_structure_event(
        StructureEvent(ts=_ts(15), ticker="TSLA", kind="choch_down", price=99.0, ref=None),
        trend="down",
        new_obs=[bear_ob],
    )
    sigs = engine.on_entry_candle(
        _c(20, 99.5, 100.8, 99.2, 100.0),
        pending_low_prices=[96.0],
    )
    assert len(sigs) == 1
    assert sigs[0].side == "short"
    assert sigs[0].reason == "smc_choch_ob_short"
    assert sigs[0].sl == 101.01
    assert sigs[0].tp <= 98.0
