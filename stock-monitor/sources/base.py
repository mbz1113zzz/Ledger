from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Event:
    source: str
    external_id: str
    ticker: str
    event_type: str  # "news" | "filing_8k" | "earnings"
    title: str
    summary: str | None
    url: str | None
    published_at: datetime
    raw: dict[str, Any] = field(default_factory=dict)
    importance: str = "low"  # "high" | "medium" | "low"
    summary_cn: str | None = None


def serialize_event(ev: Event) -> dict:
    """Convert an Event to a JSON-serializable dict for pub/sub broadcast.

    Drops ``raw`` (may contain non-serializable objects) and ISO-formats
    ``published_at``. Shared by Pipeline and SignalRouter so both surfaces
    publish identical payload shapes.
    """
    d = asdict(ev)
    d["published_at"] = ev.published_at.isoformat()
    d.pop("raw", None)
    return d


class Source(ABC):
    name: str = ""

    @abstractmethod
    async def fetch(self, tickers: list[str]) -> list[Event]:
        """Fetch new events for the given tickers. Implementations must return
        events without applying importance scoring (that's the scorer's job)."""
