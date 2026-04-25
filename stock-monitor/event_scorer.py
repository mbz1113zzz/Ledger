from config import EARNINGS_SURPRISE_HIGH_PCT, HIGH_KEYWORDS
from sources.base import Event


def score(event: Event) -> str:
    if event.event_type == "earnings_published":
        surprise = event.raw.get("surprise_pct") if event.raw else None
        if surprise is not None and abs(surprise) >= EARNINGS_SURPRISE_HIGH_PCT:
            return "high"
        return "medium"
    if event.event_type in ("filing_8k", "earnings", "price_alert", "analyst", "insider"):
        return "high"
    if event.event_type == "news":
        text = (event.title + " " + (event.summary or "")).lower()
        if any(kw in text for kw in HIGH_KEYWORDS):
            return "high"
        return "medium"
    if event.event_type == "sentiment":
        return "medium"
    return "low"
