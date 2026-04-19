from datetime import datetime, timedelta, timezone
from streaming.tick_buffer import TickBuffer


_BASE = datetime(2026, 4, 19, 14, 30, 0, tzinfo=timezone.utc)
def _ts(s=0): return _BASE + timedelta(seconds=s)


def test_empty_buffer_returns_none():
    tb = TickBuffer(max_age_sec=900)
    assert tb.last_price("NVDA") is None
    assert tb.price_ago("NVDA", seconds=60) is None


def test_update_records_latest_and_open():
    tb = TickBuffer(max_age_sec=900)
    tb.set_open("NVDA", 100.0, _ts(0))
    tb.update("NVDA", 101.0, _ts(10))
    tb.update("NVDA", 102.0, _ts(20))
    assert tb.last_price("NVDA") == 102.0
    assert tb.open_price("NVDA") == 100.0


def test_price_ago_returns_closest_older():
    tb = TickBuffer(max_age_sec=900)
    tb.update("NVDA", 100.0, _ts(0))
    tb.update("NVDA", 101.0, _ts(30))
    tb.update("NVDA", 102.0, _ts(65))
    assert tb.price_ago("NVDA", seconds=60, now=_ts(65)) == 100.0


def test_price_ago_returns_none_if_insufficient_history():
    tb = TickBuffer(max_age_sec=900)
    tb.update("NVDA", 100.0, _ts(0))
    assert tb.price_ago("NVDA", seconds=60, now=_ts(10)) is None


def test_eviction_after_max_age():
    tb = TickBuffer(max_age_sec=60)
    tb.update("NVDA", 100.0, _ts(0))
    tb.update("NVDA", 101.0, _ts(90))
    assert tb.price_ago("NVDA", seconds=60, now=_ts(90)) is None
    assert tb.last_price("NVDA") == 101.0


def test_ticker_isolation():
    tb = TickBuffer(max_age_sec=900)
    tb.update("NVDA", 100.0, _ts(0))
    tb.update("TSLA", 200.0, _ts(0))
    assert tb.last_price("NVDA") == 100.0
    assert tb.last_price("TSLA") == 200.0
