from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from sources.finnhub import FinnhubSource
from sources.health import SourceHealth
from storage import Storage


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


@pytest.mark.asyncio
async def test_earnings_first_seen_with_actual_lands_in_reacted_no_event(monkeypatch, tmp_path):
    """Bootstrap quiet period: first poll sees epsActual already populated."""
    storage = Storage(str(tmp_path / "test.db"))
    storage.init_schema()
    src = FinnhubSource(api_key="x", enable_news=False, storage=storage)

    async def fake_get(path, params):
        if path == "/calendar/earnings":
            return {"earningsCalendar": [{
                "symbol": "AAPL", "date": "2026-04-25", "hour": "amc",
                "epsEstimate": 1.40, "epsActual": 1.50,
                "revenueEstimate": 100e9, "revenueActual": 105e9,
            }]}
        return None
    monkeypatch.setattr(src, "_get", fake_get)

    events = await src.fetch(["AAPL"])
    types = [e.event_type for e in events]
    assert "earnings_published" not in types
    row = storage.get_earnings("AAPL", "2026-04-25")
    assert row["status"] == "reacted"
    assert row["eps_actual"] == 1.50


@pytest.mark.asyncio
async def test_earnings_scheduled_then_published_emits_event(monkeypatch, tmp_path):
    storage = Storage(str(tmp_path / "test.db"))
    storage.init_schema()
    src = FinnhubSource(api_key="x", enable_news=False, storage=storage)

    payload_scheduled = {"earningsCalendar": [{
        "symbol": "AAPL", "date": "2026-04-30", "hour": "amc",
        "epsEstimate": 1.42, "epsActual": None,
        "revenueEstimate": 120e9, "revenueActual": None,
    }]}
    payload_published = {"earningsCalendar": [{
        "symbol": "AAPL", "date": "2026-04-30", "hour": "amc",
        "epsEstimate": 1.42, "epsActual": 1.55,
        "revenueEstimate": 120e9, "revenueActual": 125e9,
    }]}
    state = {"call": 0}

    async def fake_get(path, params):
        if path != "/calendar/earnings":
            return None
        state["call"] += 1
        return payload_scheduled if state["call"] == 1 else payload_published
    monkeypatch.setattr(src, "_get", fake_get)

    first = await src.fetch(["AAPL"])
    assert any(e.event_type == "earnings" for e in first)
    second = await src.fetch(["AAPL"])
    pubs = [e for e in second if e.event_type == "earnings_published"]
    assert len(pubs) == 1
    assert pubs[0].raw["surprise_pct"] is not None
    assert abs(pubs[0].raw["surprise_pct"] - (1.55 - 1.42) / 1.42) < 1e-6
    row = storage.get_earnings("AAPL", "2026-04-30")
    assert row["status"] == "published_pending_reaction"


@pytest.mark.asyncio
async def test_earnings_estimate_only_change_does_not_change_status(monkeypatch, tmp_path):
    storage = Storage(str(tmp_path / "test.db"))
    storage.init_schema()
    src = FinnhubSource(api_key="x", enable_news=False, storage=storage)

    payloads = [
        {"earningsCalendar": [{
            "symbol": "AAPL", "date": "2026-04-30", "hour": "amc",
            "epsEstimate": 1.42, "epsActual": None,
            "revenueEstimate": 120e9, "revenueActual": None,
        }]},
        {"earningsCalendar": [{
            "symbol": "AAPL", "date": "2026-04-30", "hour": "amc",
            "epsEstimate": 1.45, "epsActual": None,
            "revenueEstimate": 121e9, "revenueActual": None,
        }]},
    ]
    state = {"call": 0}

    async def fake_get(path, params):
        if path != "/calendar/earnings":
            return None
        state["call"] += 1
        return payloads[state["call"] - 1]
    monkeypatch.setattr(src, "_get", fake_get)

    await src.fetch(["AAPL"])
    await src.fetch(["AAPL"])
    row = storage.get_earnings("AAPL", "2026-04-30")
    assert row["status"] == "scheduled"
    assert row["eps_estimate"] == 1.45
