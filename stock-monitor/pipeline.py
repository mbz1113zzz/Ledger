import logging
from dataclasses import asdict

from deduplicator import Deduplicator
from event_scorer import score
from notifier import Notifier
from sources.base import Event, Source
from storage import Storage

log = logging.getLogger(__name__)


class Pipeline:
    def __init__(
        self,
        sources: list[Source],
        storage: Storage,
        notifier: Notifier,
        tickers: list[str],
    ):
        self._sources = sources
        self._storage = storage
        self._notifier = notifier
        self._tickers = tickers
        self._dedup = Deduplicator(storage)

    async def run_once(self) -> int:
        all_events: list[Event] = []
        for src in self._sources:
            try:
                events = await src.fetch(self._tickers)
                all_events.extend(events)
            except Exception as e:
                log.exception("source %s failed: %s", src.name, e)
        fresh = self._dedup.filter_new(all_events)
        inserted = 0
        for ev in fresh:
            ev.importance = score(ev)
            if self._storage.insert(ev):
                inserted += 1
                await self._notifier.publish(self._serialize(ev))
        log.info("pipeline inserted %d events", inserted)
        return inserted

    @staticmethod
    def _serialize(ev: Event) -> dict:
        d = asdict(ev)
        d["published_at"] = ev.published_at.isoformat()
        d.pop("raw", None)
        return d
