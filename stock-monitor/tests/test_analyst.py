from unittest.mock import AsyncMock, patch

import pytest

from sources.analyst import AnalystSource


SAMPLE = [
    {
        "symbol": "NVDA",
        "company": "Goldman Sachs",
        "fromGrade": "Hold",
        "toGrade": "Buy",
        "action": "up",
        "gradeTime": "2026-04-15",
    },
    {
        "symbol": "NVDA",
        "company": "Morgan Stanley",
        "fromGrade": "",
        "toGrade": "Overweight",
        "action": "init",
        "gradeTime": "2026-04-14",
    },
]


@pytest.mark.asyncio
async def test_disabled_without_api_key():
    src = AnalystSource(api_key="")
    events = await src.fetch(["NVDA"])
    assert events == []


@pytest.mark.asyncio
async def test_fetch_parses_upgrade():
    src = AnalystSource(api_key="k")
    with patch.object(src, "_get", new=AsyncMock(return_value=SAMPLE)):
        events = await src.fetch(["NVDA"])
    assert len(events) == 2
    assert all(e.event_type == "analyst" for e in events)
    assert events[0].ticker == "NVDA"
    assert "上调" in events[0].title
    assert "持有 → 买入" in events[0].title
    assert "Goldman Sachs" in events[0].title


@pytest.mark.asyncio
async def test_init_coverage_title():
    src = AnalystSource(api_key="k")
    with patch.object(src, "_get", new=AsyncMock(return_value=[SAMPLE[1]])):
        events = await src.fetch(["NVDA"])
    assert len(events) == 1
    assert "首次覆盖" in events[0].title
    assert "增持" in events[0].title


@pytest.mark.asyncio
async def test_bad_date_skipped():
    src = AnalystSource(api_key="k")
    bad = [{**SAMPLE[0], "gradeTime": "not-a-date"}]
    with patch.object(src, "_get", new=AsyncMock(return_value=bad)):
        events = await src.fetch(["NVDA"])
    assert events == []


@pytest.mark.asyncio
async def test_api_failure_doesnt_crash():
    src = AnalystSource(api_key="k")
    async def boom(*a, **kw): raise RuntimeError("fail")
    with patch.object(src, "_get", new=boom):
        events = await src.fetch(["NVDA"])
    assert events == []
