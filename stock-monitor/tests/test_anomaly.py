from datetime import datetime, timedelta, timezone
from streaming.anomaly import AnomalyDetector
from streaming.tick_buffer import TickBuffer


TIERS = [("low", 0.005), ("medium", 0.01), ("high", 0.03)]

_BASE = datetime(2026, 4, 19, 14, 30, 0, tzinfo=timezone.utc)


def _ts(s=0): return _BASE + timedelta(seconds=s)


def _setup():
    tb = TickBuffer(max_age_sec=900)
    tb.set_open("NVDA", 100.0, _ts(0))
    tb.update("NVDA", 100.0, _ts(0))
    det = AnomalyDetector(buffer=tb, tiers=TIERS, cooldown_sec=300)
    return tb, det


def test_no_signal_below_lowest_tier():
    tb, det = _setup()
    tb.update("NVDA", 100.3, _ts(65))
    assert det.feed("NVDA", 100.3, _ts(65)) == []


def test_medium_tier_up_requires_both_anchors_same_direction():
    tb, det = _setup()
    tb.update("NVDA", 101.2, _ts(65))
    sigs = det.feed("NVDA", 101.2, _ts(65))
    tiers = [s.tier for s in sigs]
    assert "medium" in tiers and "low" in tiers and "high" not in tiers
    assert all(s.direction == "up" for s in sigs)


def test_split_direction_is_rejected():
    tb, det = _setup()
    tb.update("NVDA", 101.0, _ts(5))
    sigs = det.feed("NVDA", 101.0, _ts(65))
    assert sigs == []


def test_cooldown_suppresses_same_tier_within_window():
    tb, det = _setup()
    tb.update("NVDA", 101.2, _ts(65))
    first = det.feed("NVDA", 101.2, _ts(65))
    assert len(first) >= 1
    tb.update("NVDA", 101.3, _ts(120))
    second = det.feed("NVDA", 101.3, _ts(120))
    tiers = {s.tier for s in second}
    assert "medium" not in tiers and "low" not in tiers


def test_higher_tier_fires_even_during_lower_cooldown():
    tb, det = _setup()
    tb.update("NVDA", 101.2, _ts(65))
    det.feed("NVDA", 101.2, _ts(65))
    tb.update("NVDA", 104.0, _ts(90))
    sigs = det.feed("NVDA", 104.0, _ts(90))
    assert "high" in {s.tier for s in sigs}
