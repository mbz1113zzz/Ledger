from datetime import datetime, timezone
from pathlib import Path

import pytest

from deduplicator import Deduplicator
from sources.base import Event
from storage import Storage


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    s = Storage(str(tmp_path / "t.db"))
    s.init_schema()
    return s


def _event(eid: str, *, source: str = "finnhub", ticker: str = "EOSE",
           event_type: str = "news", title: str = "t",
           when: datetime | None = None) -> Event:
    return Event(
        source=source, external_id=eid, ticker=ticker,
        event_type=event_type, title=title, summary=None, url=None,
        published_at=when or datetime.now(timezone.utc), raw={},
    )


def test_filter_removes_already_stored(storage):
    storage.insert(_event("a"))
    dedup = Deduplicator(storage)
    result = dedup.filter_new([_event("a"), _event("b")])
    assert [e.external_id for e in result] == ["b"]


def test_filter_empty(storage):
    dedup = Deduplicator(storage)
    assert dedup.filter_new([]) == []


def test_filter_within_batch_duplicates(storage):
    dedup = Deduplicator(storage)
    result = dedup.filter_new([_event("a"), _event("a")])
    assert len(result) == 1


def test_cross_source_collapse_prefers_8k_over_news(storage):
    when = datetime(2026, 4, 17, 13, 0, tzinfo=timezone.utc)
    news = _event("n1", source="finnhub", event_type="news",
                  title="NVDA completes acquisition of AI startup company", when=when)
    filing = _event("s1", source="sec_edgar", event_type="filing_8k",
                    title="NVDA completes acquisition of AI startup", when=when)
    dedup = Deduplicator(storage)
    result = dedup.filter_new([news, filing])
    assert len(result) == 1
    assert result[0].event_type == "filing_8k"


def test_cross_source_keeps_distinct_topics(storage):
    when = datetime(2026, 4, 17, 13, 0, tzinfo=timezone.utc)
    a = _event("a", event_type="news", title="NVDA reports record quarterly earnings", when=when)
    b = _event("b", event_type="news", title="NVDA launches new Blackwell GPU platform", when=when)
    dedup = Deduplicator(storage)
    result = dedup.filter_new([a, b])
    assert len(result) == 2


def test_cross_source_different_days_not_collapsed(storage):
    day1 = datetime(2026, 4, 16, 13, 0, tzinfo=timezone.utc)
    day2 = datetime(2026, 4, 17, 13, 0, tzinfo=timezone.utc)
    a = _event("a", event_type="news", title="NVDA announces major acquisition", when=day1)
    b = _event("b", event_type="news", title="NVDA announces major acquisition", when=day2)
    dedup = Deduplicator(storage)
    result = dedup.filter_new([a, b])
    assert len(result) == 2
