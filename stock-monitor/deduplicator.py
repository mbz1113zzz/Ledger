import re

from sources.base import Event
from storage import Storage

# Higher value = higher priority when collapsing cross-source duplicates.
TYPE_PRIORITY = {
    "filing_8k": 5,
    "earnings": 4,
    "analyst": 3,
    "insider": 3,
    "price_alert": 2,
    "news": 1,
}

_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "is", "are",
    "as", "at", "by", "with", "from", "that", "this", "it", "its", "be", "was",
    "will", "has", "have", "had", "but", "not", "s", "says", "said", "inc",
    "corp", "co", "ltd",
}

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(title: str) -> set[str]:
    return {w for w in _WORD_RE.findall(title.lower()) if w not in _STOP and len(w) > 1}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class Deduplicator:
    SIMILARITY_THRESHOLD = 0.5

    def __init__(self, storage: Storage):
        self._storage = storage

    def filter_new(self, events: list[Event]) -> list[Event]:
        # 1. Exact (source, external_id) dedup + DB existence check.
        seen: set[tuple[str, str]] = set()
        stage1: list[Event] = []
        for e in events:
            key = (e.source, e.external_id)
            if key in seen:
                continue
            if self._storage.exists(e.source, e.external_id):
                continue
            seen.add(key)
            stage1.append(e)

        # 2. Cross-source collapse: within same ticker + calendar date, if two
        # events have >=50% title-token overlap, keep the one with higher
        # type priority (8-K > earnings > analyst/insider > price > news).
        by_bucket: dict[tuple[str, str], list[tuple[Event, set[str]]]] = {}
        kept: list[Event] = []
        for e in stage1:
            bucket = (e.ticker.upper(), e.published_at.date().isoformat())
            toks = _tokens(e.title)
            group = by_bucket.setdefault(bucket, [])
            dup_idx = -1
            for i, (other, other_toks) in enumerate(group):
                if _jaccard(toks, other_toks) >= self.SIMILARITY_THRESHOLD:
                    dup_idx = i
                    break
            if dup_idx < 0:
                group.append((e, toks))
                kept.append(e)
                continue
            other, _ = group[dup_idx]
            if TYPE_PRIORITY.get(e.event_type, 0) > TYPE_PRIORITY.get(other.event_type, 0):
                kept.remove(other)
                kept.append(e)
                group[dup_idx] = (e, toks)
        return kept
