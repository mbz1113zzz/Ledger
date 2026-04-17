from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from sources.yfinance_source import YfinanceSource


@pytest.mark.asyncio
async def test_fetch_returns_earnings_event():
    src = YfinanceSource()
    fake_ticker = MagicMock()
    fake_ticker.calendar = {"Earnings Date": [date(2026, 5, 1)]}
    with patch("sources.yfinance_source.yf.Ticker", return_value=fake_ticker):
        events = await src.fetch(["EOSE"])
    assert len(events) == 1
    e = events[0]
    assert e.event_type == "earnings"
    assert e.ticker == "EOSE"
    assert "2026-05-01" in e.external_id


@pytest.mark.asyncio
async def test_missing_calendar_returns_empty():
    src = YfinanceSource()
    fake_ticker = MagicMock()
    fake_ticker.calendar = {}
    with patch("sources.yfinance_source.yf.Ticker", return_value=fake_ticker):
        events = await src.fetch(["EOSE"])
    assert events == []


@pytest.mark.asyncio
async def test_exception_is_swallowed_per_ticker():
    src = YfinanceSource()
    with patch("sources.yfinance_source.yf.Ticker", side_effect=RuntimeError("boom")):
        events = await src.fetch(["EOSE"])
    assert events == []
