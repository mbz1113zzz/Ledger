from datetime import datetime, timezone
from smc.types import Candle
from streaming.bar_aggregator import BarAggregator


def _ts(m=0, s=0):
    return datetime(2026, 4, 19, 14, m, s, tzinfo=timezone.utc)


def _bar(m, s, o, h, l, c, v=100):
    return {"ts": _ts(m, s), "o": o, "h": h, "l": l, "c": c, "v": v}


def test_closes_1m_bar_when_minute_advances():
    agg = BarAggregator(tfs=("1m",))
    closed = []
    agg.on_closed(lambda tkr, cd: closed.append(cd))
    for i in range(12):
        agg.feed("NVDA", _bar(0, i * 5, 100, 101, 99, 100 + (i % 2)))
    assert len(closed) == 0
    agg.feed("NVDA", _bar(1, 0, 100, 100, 100, 100))
    assert len(closed) == 1
    cd = closed[0]
    assert isinstance(cd, Candle)
    assert cd.tf == "1m"
    assert cd.ts == _ts(0, 0)
    assert cd.o == 100
    assert cd.h == 101
    assert cd.l == 99


def test_aggregates_to_5m():
    agg = BarAggregator(tfs=("1m", "5m"))
    got = []
    agg.on_closed(lambda tkr, cd: got.append(cd))
    for minute in range(6):
        for s in range(0, 60, 5):
            agg.feed("NVDA", _bar(minute, s, 100, 101, 99, 100))
    agg.feed("NVDA", _bar(6, 0, 100, 100, 100, 100))
    tfs = [c.tf for c in got]
    assert tfs.count("1m") == 6
    assert tfs.count("5m") == 1
    five = next(c for c in got if c.tf == "5m")
    assert five.ts == _ts(0, 0)


def test_ticker_isolation():
    agg = BarAggregator(tfs=("1m",))
    got = []
    agg.on_closed(lambda tkr, cd: got.append((tkr, cd)))
    agg.feed("NVDA", _bar(0, 0, 100, 100, 100, 100))
    agg.feed("TSLA", _bar(0, 0, 200, 200, 200, 200))
    agg.feed("NVDA", _bar(1, 0, 100, 100, 100, 100))
    agg.feed("TSLA", _bar(1, 0, 200, 200, 200, 200))
    assert len(got) == 2
    tickers = {t for t, _ in got}
    assert tickers == {"NVDA", "TSLA"}


def test_callback_receives_ticker():
    agg = BarAggregator(tfs=("1m",))
    got = []
    agg.on_closed(lambda ticker, cd: got.append((ticker, cd)))
    agg.feed("NVDA", _bar(0, 0, 100, 100, 100, 100))
    agg.feed("NVDA", _bar(1, 0, 100, 100, 100, 100))
    assert got[0][0] == "NVDA"
