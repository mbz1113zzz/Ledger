from sources.base import Event
from storage import Storage


class Deduplicator:
    def __init__(self, storage: Storage):
        self._storage = storage

    def filter_new(self, events: list[Event]) -> list[Event]:
        seen: set[tuple[str, str]] = set()
        result: list[Event] = []
        for e in events:
            key = (e.source, e.external_id)
            if key in seen:
                continue
            if self._storage.exists(e.source, e.external_id):
                continue
            seen.add(key)
            result.append(e)
        return result
