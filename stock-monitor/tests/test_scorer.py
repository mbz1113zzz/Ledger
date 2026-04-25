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


def _ep_ev(*, surprise=None, importance="low"):
    return Event(
        source="finnhub", external_id="x", ticker="AAPL",
        event_type="earnings_published",
        title="AAPL EPS", summary=f"surprise={surprise}",
        url=None,
        published_at=datetime(2026, 4, 30, 20, 5, tzinfo=timezone.utc),
        raw={"surprise_pct": surprise} if surprise is not None else {},
        importance=importance,
    )


def test_earnings_published_high_when_surprise_above_threshold():
    assert score(_ep_ev(surprise=0.07)) == "high"


def test_earnings_published_high_when_negative_surprise_above_threshold():
    assert score(_ep_ev(surprise=-0.08)) == "high"


def test_earnings_published_medium_when_surprise_below_threshold():
    assert score(_ep_ev(surprise=0.02)) == "medium"


def test_earnings_published_medium_when_surprise_unknown():
    assert score(_ep_ev(surprise=None)) == "medium"
