from datetime import datetime, timezone

from event_scorer import score
from sources.base import Event


def _event(event_type: str, title: str = "", summary: str = "") -> Event:
    return Event(
        source="x",
        external_id="1",
        ticker="EOSE",
        event_type=event_type,
        title=title,
        summary=summary,
        url=None,
        published_at=datetime.now(timezone.utc),
        raw={},
    )


def test_8k_is_high():
    assert score(_event("filing_8k")) == "high"


def test_earnings_is_high():
    assert score(_event("earnings")) == "high"


def test_news_with_high_keyword_is_high():
    e = _event("news", title="Company announces FDA approval for drug X")
    assert score(e) == "high"


def test_news_keyword_in_summary():
    e = _event("news", title="Update", summary="The CEO announced a buyback.")
    assert score(e) == "high"


def test_news_without_keyword_is_medium():
    assert score(_event("news", title="Routine trading update")) == "medium"


def test_unknown_type_is_low():
    assert score(_event("other")) == "low"


def test_case_insensitive_matching():
    assert score(_event("news", title="FDA APPROVAL granted")) == "high"
