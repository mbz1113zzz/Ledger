from datetime import datetime, timezone
from pathlib import Path

import pytest

from pipeline import Pipeline
from notifier import Notifier
from sources.base import Event, Source
from storage import Storage


class FakeSource(Source):
    name = "fake"

    def __init__(self, events: list[Event]):
        self._events = events

    async def fetch(self, tickers: list[str]) -> list[Event]:
        return self._events


def _event(eid: str, etype: str = "news", title: str = "t") -> Event:
    return Event(
        source="fake", external_id=eid, ticker="EOSE",
        event_type=etype, title=title, summary=None, url=None,
        published_at=datetime.now(timezone.utc), raw={},
    )


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    s = Storage(str(tmp_path / "p.db"))
    s.init_schema()
    return s


@pytest.mark.asyncio
async def test_pipeline_stores_scored_new_events(storage):
    notifier = Notifier()
    queue = await notifier.subscribe()
    src = FakeSource([_event("a", "filing_8k", "8-K")])
    pipe = Pipeline(sources=[src], storage=storage, notifier=notifier, tickers=["EOSE"])
    n = await pipe.run_once()
    assert n == 1
    stored = storage.query()
    assert len(stored) == 1
    assert stored[0].importance == "high"
    payload = await queue.get()
    assert payload["external_id"] == "a"
    assert payload["importance"] == "high"


@pytest.mark.asyncio
async def test_pipeline_skips_duplicates(storage):
    notifier = Notifier()
    src = FakeSource([_event("a"), _event("a")])
    pipe = Pipeline(sources=[src], storage=storage, notifier=notifier, tickers=["EOSE"])
    assert await pipe.run_once() == 1
    assert await pipe.run_once() == 0
