from datetime import datetime, timezone
from sources.base import Event


def test_event_has_required_fields():
    e = Event(
        source="finnhub",
        external_id="abc123",
        ticker="EOSE",
        event_type="news",
        title="EOSE announces new contract",
        summary="Details...",
        url="https://example.com/1",
        published_at=datetime.now(timezone.utc),
        raw={"foo": "bar"},
    )
    assert e.importance == "low"
    assert e.ticker == "EOSE"


def test_event_importance_can_be_overridden():
    e = Event(
        source="sec_edgar",
        external_id="0001-22",
        ticker="MDB",
        event_type="filing_8k",
        title="MDB 8-K",
        summary=None,
        url=None,
        published_at=datetime.now(timezone.utc),
        raw={},
        importance="high",
    )
    assert e.importance == "high"
