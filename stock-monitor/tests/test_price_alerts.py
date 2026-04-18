from unittest.mock import AsyncMock, patch

import pytest

from sources.price_alerts import PriceAlertSource


def _quote(c, pc):
    return {"c": c, "pc": pc, "o": pc, "h": c, "l": pc, "t": 0, "d": c - pc, "dp": 0}


@pytest.mark.asyncio
async def test_threshold_triggers_up():
    src = PriceAlertSource(api_key="k", threshold_pct=3.0)
    with patch.object(src, "_quote", new=AsyncMock(return_value=_quote(103.5, 100.0))):
        events = await src.fetch(["EOSE"])
    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == "price_alert"
    assert ev.ticker == "EOSE"
    assert "上涨" in ev.title and "3.50%" in ev.title
    assert ev.external_id.startswith("EOSE-up-")


@pytest.mark.asyncio
async def test_threshold_triggers_down():
    src = PriceAlertSource(api_key="k", threshold_pct=3.0)
    with patch.object(src, "_quote", new=AsyncMock(return_value=_quote(95.0, 100.0))):
        events = await src.fetch(["NVDA"])
    assert len(events) == 1
    assert "下跌" in events[0].title
    assert events[0].external_id.startswith("NVDA-down-")


@pytest.mark.asyncio
async def test_below_threshold_skipped():
    src = PriceAlertSource(api_key="k", threshold_pct=3.0)
    with patch.object(src, "_quote", new=AsyncMock(return_value=_quote(101.5, 100.0))):
        events = await src.fetch(["EOSE"])
    assert events == []


@pytest.mark.asyncio
async def test_empty_api_key_returns_empty():
    src = PriceAlertSource(api_key="", threshold_pct=3.0)
    events = await src.fetch(["EOSE"])
    assert events == []


@pytest.mark.asyncio
async def test_missing_price_fields_skipped():
    src = PriceAlertSource(api_key="k", threshold_pct=3.0)
    with patch.object(src, "_quote", new=AsyncMock(return_value={"c": 0, "pc": 0})):
        events = await src.fetch(["EOSE"])
    assert events == []


@pytest.mark.asyncio
async def test_failure_for_one_ticker_doesnt_block_others():
    src = PriceAlertSource(api_key="k", threshold_pct=3.0)
    call = {"n": 0}

    async def side(client, ticker):
        call["n"] += 1
        if ticker == "BAD":
            raise RuntimeError("boom")
        return _quote(110.0, 100.0)

    with patch.object(src, "_quote", new=side):
        events = await src.fetch(["BAD", "NVDA"])
    assert len(events) == 1
    assert events[0].ticker == "NVDA"
