from datetime import datetime, timezone
from pathlib import Path

import pytest

from digest import build_digest, send_digest
from pushers import PushHub
from sources.base import Event
from storage import Storage


def _ev(ticker, etype, title, imp="high", hour=14, summary_cn=None) -> Event:
    return Event(
        source="finnhub", external_id=f"{ticker}-{title}-{hour}", ticker=ticker,
        event_type=etype, title=title, summary=None, url=None,
        published_at=datetime(2026, 4, 18, hour, 0, tzinfo=timezone.utc),
        raw={}, importance=imp, summary_cn=summary_cn,
    )


def test_empty_digest():
    now = datetime(2026, 4, 19, 13, 0, tzinfo=timezone.utc)
    title, body = build_digest([], now=now)
    assert "04-19" in title
    assert "无重要事件" in body


def test_digest_groups_by_ticker_and_counts():
    now = datetime(2026, 4, 19, 13, 0, tzinfo=timezone.utc)
    events = [
        _ev("NVDA", "filing_8k", "NVDA 8-K", imp="high"),
        _ev("NVDA", "news", "NVDA news", imp="medium", hour=15),
        _ev("AAPL", "earnings", "AAPL earnings", imp="high"),
    ]
    title, body = build_digest(events, now=now)
    assert "2 票" in title
    assert "2 高优" in title
    assert "【AAPL】" in body
    assert "【NVDA】" in body
    assert "🔴" in body
    assert "🟡" in body


def test_digest_includes_summary_cn():
    now = datetime(2026, 4, 19, 13, 0, tzinfo=timezone.utc)
    events = [_ev("NVDA", "filing_8k", "NVDA 8-K", summary_cn="发布重大合作")]
    _, body = build_digest(events, now=now)
    assert "发布重大合作" in body


def test_digest_truncates_when_many_events():
    now = datetime(2026, 4, 19, 13, 0, tzinfo=timezone.utc)
    events = [_ev("NVDA", "news", f"item {i}", imp="medium", hour=i)
              for i in range(8)]
    _, body = build_digest(events, now=now)
    assert "另 3 条" in body


@pytest.mark.asyncio
async def test_send_digest_skips_when_no_channels(tmp_path: Path):
    s = Storage(str(tmp_path / "t.db"))
    s.init_schema()
    hub = PushHub([])
    count = await send_digest(s, hub)
    assert count == 0


@pytest.mark.asyncio
async def test_send_digest_broadcasts(tmp_path: Path):
    s = Storage(str(tmp_path / "t.db"))
    s.init_schema()
    s.insert(_ev("NVDA", "filing_8k", "recent 8K"))

    sent = []

    class Fake:
        name = "fake"
        enabled = True
        async def push(self, c, e): pass
        async def push_text(self, c, t, b): sent.append((t, b))

    hub = PushHub([Fake()])
    count = await send_digest(
        s,
        hub,
        lookback_hours=48,
        now=datetime(2026, 4, 19, 13, 0, tzinfo=timezone.utc),
    )
    assert count == 1
    assert len(sent) == 1
    assert "NVDA" in sent[0][1]


def test_storage_query_since_filters_importance(tmp_path: Path):
    s = Storage(str(tmp_path / "t.db"))
    s.init_schema()
    s.insert(_ev("NVDA", "news", "low item", imp="low"))
    s.insert(_ev("NVDA", "news", "med item", imp="medium"))
    s.insert(_ev("NVDA", "filing_8k", "hi item", imp="high"))
    since = datetime(2026, 4, 17, 0, 0, tzinfo=timezone.utc)
    out = s.query_since(since, min_importance="medium")
    titles = {e.title for e in out}
    assert titles == {"med item", "hi item"}
