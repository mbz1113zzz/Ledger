from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from backtest import compute_stats, run_backtest
from sources.base import Event
from storage import Storage


def _closes(pairs: list[tuple[str, float]]) -> dict[date, float]:
    return {date.fromisoformat(d): p for d, p in pairs}


def test_compute_stats_simple_uptrend():
    closes = _closes([
        ("2026-04-10", 100.0),
        ("2026-04-13", 101.0),
        ("2026-04-14", 103.0),
        ("2026-04-17", 106.0),
    ])
    # Event on 04-10, +3 day target (04-13)
    stats = compute_stats([date(2026, 4, 10)], closes, [3, 7])
    assert stats[0].window == 3
    assert stats[0].n == 1
    assert stats[0].mean_pct == pytest.approx(1.0, abs=0.01)
    assert stats[0].positive_rate == 1.0
    assert stats[1].window == 7
    assert stats[1].mean_pct == pytest.approx(6.0, abs=0.01)


def test_compute_stats_handles_missing_prices():
    closes = _closes([("2026-04-10", 100.0)])
    stats = compute_stats([date(2026, 4, 10)], closes, [3])
    assert stats[0].n == 0
    assert stats[0].mean_pct == 0.0


def test_compute_stats_weekend_skew():
    # Event on Friday; +1d target lands on Sat — should grab Monday close
    closes = _closes([
        ("2026-04-17", 100.0),  # Friday
        ("2026-04-20", 104.0),  # Monday
    ])
    stats = compute_stats([date(2026, 4, 17)], closes, [1])
    assert stats[0].n == 1
    assert stats[0].mean_pct == pytest.approx(4.0, abs=0.01)


def test_compute_stats_mixed_returns():
    closes = _closes([
        ("2026-04-01", 100.0), ("2026-04-02", 105.0),
        ("2026-04-05", 100.0), ("2026-04-06", 97.0),
    ])
    stats = compute_stats(
        [date(2026, 4, 1), date(2026, 4, 5)], closes, [1]
    )
    assert stats[0].n == 2
    assert stats[0].positive_rate == 0.5
    assert stats[0].mean_pct == pytest.approx(1.0, abs=0.01)


def _event(ticker, etype, when):
    return Event(
        source="sec_edgar", external_id=f"{ticker}-{when.isoformat()}",
        ticker=ticker, event_type=etype, title=f"{ticker} {etype}",
        summary=None, url=None, published_at=when, raw={}, importance="high",
    )


@pytest.mark.asyncio
async def test_run_backtest_empty_when_no_events(tmp_path: Path):
    s = Storage(str(tmp_path / "t.db"))
    s.init_schema()

    class NoFetch:
        async def daily_closes(self, *a, **kw): return {}

    out = await run_backtest(s, NoFetch(), ticker="NVDA",
                              event_type="filing_8k")
    assert out["n_events"] == 0
    assert out["windows"] == []


@pytest.mark.asyncio
async def test_run_backtest_end_to_end(tmp_path: Path):
    s = Storage(str(tmp_path / "t.db"))
    s.init_schema()
    when = datetime(2026, 4, 10, 14, 0, tzinfo=timezone.utc)
    s.insert(_event("NVDA", "filing_8k", when))

    class FakeFetcher:
        async def daily_closes(self, ticker, start, end):
            return {
                date(2026, 4, 10): 100.0,
                date(2026, 4, 13): 102.0,
                date(2026, 4, 17): 108.0,
            }

    out = await run_backtest(s, FakeFetcher(), ticker="NVDA",
                              event_type="filing_8k", windows=[3, 7])
    assert out["n_events"] == 1
    assert out["ticker"] == "NVDA"
    assert len(out["windows"]) == 2
    w3 = next(w for w in out["windows"] if w["window"] == 3)
    assert w3["mean_pct"] == 2.0
