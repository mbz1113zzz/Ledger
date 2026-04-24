import logging
from datetime import datetime, timezone

from deduplicator import Deduplicator
from enricher import Enricher
from event_scorer import score
from notifier import Notifier
from pushers import PushHub
from sources.base import Event, Source, serialize_event
from storage import Storage

log = logging.getLogger(__name__)


class Pipeline:
    def __init__(
        self,
        sources: list[Source],
        storage: Storage,
        notifier: Notifier,
        tickers: list[str],
        enricher: Enricher | None = None,
        push_hub: PushHub | None = None,
    ):
        self._sources = sources
        self._storage = storage
        self._notifier = notifier
        self._tickers = tickers
        self._dedup = Deduplicator(storage)
        self._enricher = enricher
        self._push_hub = push_hub
        self.last_run_at: datetime | None = None
        self.last_run_inserted: int = 0

    @property
    def sources(self) -> list[Source]:
        return self._sources

    @property
    def enricher(self) -> Enricher | None:
        return self._enricher

    def set_tickers(self, tickers: list[str]) -> None:
        self._tickers = tickers

    async def run_once(self) -> int:
        all_events: list[Event] = []
        for src in self._sources:
            try:
                events = await src.fetch(self._tickers)
                all_events.extend(events)
            except Exception as e:
                log.exception("source %s failed: %s", src.name, e)
        fresh = self._dedup.filter_new(all_events)
        for ev in fresh:
            ev.importance = score(ev)

        if self._enricher and self._enricher.enabled:
            await self._enricher.enrich(fresh)

        inserted = 0
        for ev in fresh:
            if self._storage.insert(ev):
                inserted += 1
                await self._notifier.publish(serialize_event(ev))
                if ev.importance == "high" and self._push_hub and self._push_hub.enabled:
                    try:
                        await self._push_hub.broadcast(ev)
                    except Exception as e:
                        log.warning("push broadcast failed: %s", e)
        self.last_run_at = datetime.now(timezone.utc)
        self.last_run_inserted = inserted
        log.info("pipeline inserted %d events", inserted)
        return inserted
