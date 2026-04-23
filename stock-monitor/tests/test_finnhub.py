from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from sources.finnhub import FinnhubSource
from sources.health import SourceHealth


NEWS_RESPONSE = [
    {
        "id": 12345,
        "headline": "EOSE wins major contract",
        "summary": "Details of the contract...",
        "url": "https://example.com/a",
        "datetime": 1744977600,
        "related": "EOSE",
    },
    {
        "id": 12346,
        "headline": "Market update",
        "summary": "",
        "url": "https://example.com/b",
        "datetime": 1744981200,
        "related": "EOSE",
    },
]

EARNINGS_RESPONSE = {
    "earningsCalendar": [
        {
            "symbol": "EOSE",
            "date": "2026-05-08",
            "hour": "amc",
            "epsEstimate": -0.15,
            "revenueEstimate": 12000000,
        }
    ]
}


def _route(news=None, earnings=None):
    async def side_effect(path, params):
        if path == "/company-news":
            return news if news is not None else []
        if path == "/calendar/earnings":
            return earnings if earnings is not None else {"earningsCalendar": []}
        return None
    return side_effect


@pytest.mark.asyncio
async def test_fetch_returns_news_events():
    src = FinnhubSource(api_key="fake")
    with patch.object(src, "_get", new=AsyncMock(side_effect=_route(news=NEWS_RESPONSE))):
        events = await src.fetch(["EOSE"])
    news_events = [e for e in events if e.event_type == "news"]
    assert len(news_events) == 2
    assert news_events[0].source == "finnhub"
    assert news_events[0].external_id == "12345"
    assert news_events[0].ticker == "EOSE"
    assert news_events[0].title == "EOSE wins major contract"
    assert news_events[0].published_at == datetime.fromtimestamp(1744977600, tz=timezone.utc)


@pytest.mark.asyncio
async def test_fetch_returns_earnings_events():
    src = FinnhubSource(api_key="fake")
    with patch.object(src, "_get", new=AsyncMock(side_effect=_route(earnings=EARNINGS_RESPONSE))):
        events = await src.fetch(["EOSE"])
    earnings = [e for e in events if e.event_type == "earnings"]
    assert len(earnings) == 1
    ev = earnings[0]
    assert ev.source == "finnhub"
    assert ev.external_id == "EOSE-earnings-2026-05-08"
    assert ev.ticker == "EOSE"
    assert "2026-05-08" in ev.title
    assert "盘后" in ev.title


@pytest.mark.asyncio
async def test_fetch_skips_malformed_news():
    bad = [{"headline": "missing id"}]
    src = FinnhubSource(api_key="fake")
    with patch.object(src, "_get", new=AsyncMock(side_effect=_route(news=bad))):
        events = await src.fetch(["EOSE"])
    assert events == []


@pytest.mark.asyncio
async def test_empty_api_key_returns_empty():
    src = FinnhubSource(api_key="")
    events = await src.fetch(["EOSE"])
    assert events == []


@pytest.mark.asyncio
async def test_news_failure_doesnt_block_earnings():
    src = FinnhubSource(api_key="fake")

    async def side_effect(path, params):
        if path == "/company-news":
            raise RuntimeError("news boom")
        return EARNINGS_RESPONSE

    with patch.object(src, "_get", new=AsyncMock(side_effect=side_effect)):
        events = await src.fetch(["EOSE"])
    assert len(events) == 1
    assert events[0].event_type == "earnings"


@pytest.mark.asyncio
async def test_earnings_without_hour_still_parses():
    resp = {"earningsCalendar": [{"symbol": "EOSE", "date": "2026-05-08", "hour": ""}]}
    src = FinnhubSource(api_key="fake")
    with patch.object(src, "_get", new=AsyncMock(side_effect=_route(earnings=resp))):
        events = await src.fetch(["EOSE"])
    earnings = [e for e in events if e.event_type == "earnings"]
    assert len(earnings) == 1
    assert earnings[0].title.strip().endswith("2026-05-08")


@pytest.mark.asyncio
async def test_disabled_health_short_circuits_fetch():
    src = FinnhubSource(api_key="fake")
    for _ in range(SourceHealth.THRESHOLD):
        src._news_health.record_http_error(429)
        src._earnings_health.record_http_error(429)
    with patch.object(src, "_get", new=AsyncMock(side_effect=AssertionError("should not call"))):
        events = await src.fetch(["EOSE"])
    assert events == []


@pytest.mark.asyncio
async def test_news_disable_does_not_block_earnings_fetch():
    src = FinnhubSource(api_key="fake")
    for _ in range(SourceHealth.THRESHOLD):
        src._news_health.record_http_error(403)

    paths = []

    async def side_effect(path, params):
        paths.append(path)
        if path == "/calendar/earnings":
            return EARNINGS_RESPONSE
        return []

    with patch.object(src, "_get", new=AsyncMock(side_effect=side_effect)):
        events = await src.fetch(["EOSE"])
    earnings = [e for e in events if e.event_type == "earnings"]
    assert len(earnings) == 1
    assert paths == ["/calendar/earnings"]
