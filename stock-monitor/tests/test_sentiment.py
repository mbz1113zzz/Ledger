from unittest.mock import AsyncMock, patch

import pytest

from sources.sentiment import SentimentSource


def _resp(buzz, weekly_avg, bullish=0.6, articles_week=70):
    return {
        "buzz": {
            "buzz": buzz,
            "weeklyAverage": weekly_avg,
            "articlesInLastWeek": articles_week,
        },
        "sentiment": {"bullishPercent": bullish},
    }


@pytest.mark.asyncio
async def test_disabled_without_api_key():
    src = SentimentSource(api_key="")
    assert await src.fetch(["NVDA"]) == []


@pytest.mark.asyncio
async def test_spike_emits_event():
    src = SentimentSource(api_key="k")
    with patch.object(src, "_get", new=AsyncMock(return_value=_resp(30, 10))):
        events = await src.fetch(["NVDA"])
    assert len(events) == 1
    ev = events[0]
    assert ev.event_type == "sentiment"
    assert ev.ticker == "NVDA"
    assert "舆情放量" in ev.title
    assert "偏多" in ev.title
    assert ev.raw["ratio"] == pytest.approx(3.0)


@pytest.mark.asyncio
async def test_no_spike_returns_empty():
    src = SentimentSource(api_key="k")
    with patch.object(src, "_get", new=AsyncMock(return_value=_resp(12, 10))):
        events = await src.fetch(["NVDA"])
    assert events == []


@pytest.mark.asyncio
async def test_low_buzz_ignored():
    src = SentimentSource(api_key="k")
    with patch.object(src, "_get", new=AsyncMock(return_value=_resp(3, 1))):
        events = await src.fetch(["NVDA"])
    assert events == []


@pytest.mark.asyncio
async def test_bearish_polarity_label():
    src = SentimentSource(api_key="k")
    with patch.object(src, "_get",
                      new=AsyncMock(return_value=_resp(30, 10, bullish=0.3))):
        events = await src.fetch(["NVDA"])
    assert "偏空" in events[0].title


@pytest.mark.asyncio
async def test_api_failure_doesnt_crash():
    src = SentimentSource(api_key="k")
    async def boom(*a, **kw): raise RuntimeError("fail")
    with patch.object(src, "_get", new=boom):
        events = await src.fetch(["NVDA"])
    assert events == []
