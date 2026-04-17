from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from sources.base import Event
from storage import Storage


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    s = Storage(str(tmp_path / "test.db"))
    s.init_schema()
    return s


def _make_event(external_id: str = "id1", importance: str = "low") -> Event:
    return Event(
        source="finnhub",
        external_id=external_id,
        ticker="EOSE",
        event_type="news",
        title="Title",
        summary="Summary",
        url="https://example.com",
        published_at=datetime(2026, 4, 18, 12, 0, tzinfo=timezone.utc),
        raw={"k": "v"},
        importance=importance,
    )


def test_insert_and_query(storage):
    storage.insert(_make_event())
    events = storage.query(limit=10)
    assert len(events) == 1
    assert events[0].external_id == "id1"


def test_insert_duplicate_is_ignored(storage):
    storage.insert(_make_event())
    storage.insert(_make_event())
    assert len(storage.query(limit=10)) == 1


def test_exists_check(storage):
    assert storage.exists("finnhub", "id1") is False
    storage.insert(_make_event())
    assert storage.exists("finnhub", "id1") is True


def test_query_filters_by_importance(storage):
    storage.insert(_make_event(external_id="a", importance="high"))
    storage.insert(_make_event(external_id="b", importance="low"))
    high = storage.query(importance="high")
    assert len(high) == 1
    assert high[0].external_id == "a"


def test_query_filters_by_ticker(storage):
    e1 = _make_event(external_id="a")
    e2 = _make_event(external_id="b")
    e2.ticker = "MDB"
    storage.insert(e1)
    storage.insert(e2)
    assert len(storage.query(ticker="EOSE")) == 1
    assert len(storage.query(ticker="MDB")) == 1


def test_cleanup_old_events(storage):
    old = _make_event(external_id="old")
    storage.insert(old)
    storage._conn.execute(
        "UPDATE events SET created_at = datetime('now', '-60 days') WHERE external_id='old'"
    )
    storage._conn.commit()
    storage.insert(_make_event(external_id="new"))
    storage.cleanup(retain_days=30)
    remaining = storage.query(limit=10)
    assert len(remaining) == 1
    assert remaining[0].external_id == "new"
