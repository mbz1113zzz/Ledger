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


def _event(eid: str) -> Event:
    return Event(
        source="finnhub", external_id=eid, ticker="EOSE",
        event_type="news", title="t", summary=None, url=None,
        published_at=datetime.now(timezone.utc), raw={},
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
