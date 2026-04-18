from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from enricher import Enricher
from sources.base import Event


def _event(imp="high", etype="news", summary_cn=None) -> Event:
    return Event(
        source="finnhub", external_id="x", ticker="NVDA",
        event_type=etype, title="Big news", summary="details",
        url=None, published_at=datetime.now(timezone.utc),
        raw={}, importance=imp, summary_cn=summary_cn,
    )


@pytest.mark.asyncio
async def test_disabled_without_api_key():
    enr = Enricher(api_key="")
    assert not enr.enabled
    evs = [_event()]
    out = await enr.enrich(evs)
    assert out[0].summary_cn is None


@pytest.mark.asyncio
async def test_only_high_skips_medium():
    enr = Enricher(api_key="k", only_high=True)
    evs = [_event(imp="medium")]
    with patch.object(enr, "_call", new=AsyncMock(return_value="中文摘要")) as m:
        await enr.enrich(evs)
    assert m.call_count == 0
    assert evs[0].summary_cn is None


@pytest.mark.asyncio
async def test_enriches_high_event():
    enr = Enricher(api_key="k")
    ev = _event()
    with patch.object(enr, "_call", new=AsyncMock(return_value="NVDA 发布重大合作，可能利好股价。")):
        await enr.enrich([ev])
    assert ev.summary_cn == "NVDA 发布重大合作，可能利好股价。"


@pytest.mark.asyncio
async def test_price_alert_events_are_skipped():
    enr = Enricher(api_key="k")
    ev = _event(etype="price_alert")
    with patch.object(enr, "_call", new=AsyncMock(return_value="x")) as m:
        await enr.enrich([ev])
    assert m.call_count == 0


@pytest.mark.asyncio
async def test_already_enriched_skipped():
    enr = Enricher(api_key="k")
    ev = _event(summary_cn="已有摘要")
    with patch.object(enr, "_call", new=AsyncMock(return_value="new")) as m:
        await enr.enrich([ev])
    assert m.call_count == 0
    assert ev.summary_cn == "已有摘要"


@pytest.mark.asyncio
async def test_api_failure_doesnt_crash():
    enr = Enricher(api_key="k")
    ev = _event()
    async def boom(client, event):
        raise httpx.HTTPError("fail")
    with patch.object(enr, "_call", new=boom):
        await enr.enrich([ev])
    assert ev.summary_cn is None
