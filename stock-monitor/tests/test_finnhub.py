from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from sources.finnhub import FinnhubSource


SAMPLE_RESPONSE = [
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


@pytest.mark.asyncio
async def test_fetch_returns_events():
    src = FinnhubSource(api_key="fake")
    with patch.object(src, "_get", new=AsyncMock(return_value=SAMPLE_RESPONSE)):
        events = await src.fetch(["EOSE"])
    assert len(events) == 2
    assert events[0].source == "finnhub"
    assert events[0].external_id == "12345"
    assert events[0].ticker == "EOSE"
    assert events[0].event_type == "news"
    assert events[0].title == "EOSE wins major contract"
    assert events[0].published_at == datetime.fromtimestamp(1744977600, tz=timezone.utc)


@pytest.mark.asyncio
async def test_fetch_skips_malformed_entries():
    bad = [{"headline": "missing id"}]
    src = FinnhubSource(api_key="fake")
    with patch.object(src, "_get", new=AsyncMock(return_value=bad)):
        events = await src.fetch(["EOSE"])
    assert events == []


@pytest.mark.asyncio
async def test_empty_api_key_returns_empty():
    src = FinnhubSource(api_key="")
    events = await src.fetch(["EOSE"])
    assert events == []


@pytest.mark.asyncio
async def test_http_error_returns_empty_for_that_ticker():
    src = FinnhubSource(api_key="fake")
    async def raise_err(*a, **kw):
        raise RuntimeError("boom")
    with patch.object(src, "_get", new=AsyncMock(side_effect=raise_err)):
        events = await src.fetch(["EOSE"])
    assert events == []
