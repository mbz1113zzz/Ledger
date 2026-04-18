from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest

from pushers import (
    BarkPusher, FeishuPusher, PushHub, TelegramPusher, format_message,
)
from sources.base import Event


def _event(**kw) -> Event:
    base = dict(
        source="finnhub", external_id="e1", ticker="NVDA",
        event_type="news", title="Big deal announced",
        summary="detailed english summary", url="https://example.com/a",
        published_at=datetime(2026, 4, 18, 9, 30, tzinfo=timezone.utc),
        raw={}, importance="high", summary_cn="中文概要",
    )
    base.update(kw)
    return Event(**base)


def test_format_message_prefers_cn():
    t, b = format_message(_event())
    assert "[NVDA]" in t and "Big deal" in t
    assert "中文概要" in b
    assert "https://example.com/a" in b


def test_pushers_disabled_when_config_missing():
    assert not TelegramPusher("", "").enabled
    assert not TelegramPusher("tok", "").enabled
    assert not BarkPusher("").enabled
    assert not FeishuPusher("").enabled


def test_pushers_enabled_when_configured():
    assert TelegramPusher("tok", "123").enabled
    assert BarkPusher("https://api.day.app/KEY").enabled
    assert FeishuPusher("https://open.feishu/hook").enabled


def test_hub_filters_disabled():
    hub = PushHub([TelegramPusher("", ""), BarkPusher("https://api.day.app/K")])
    assert hub.enabled
    assert len(hub._pushers) == 1


@pytest.mark.asyncio
async def test_hub_broadcasts_to_all_enabled(monkeypatch):
    calls = []

    class FakePusher:
        name = "fake"
        enabled = True
        async def push(self, client, ev):
            calls.append(ev.ticker)

    hub = PushHub([FakePusher(), FakePusher()])
    await hub.broadcast(_event())
    assert calls == ["NVDA", "NVDA"]


@pytest.mark.asyncio
async def test_hub_failure_one_channel_doesnt_break_others():
    good_calls = []

    class Good:
        name = "good"; enabled = True
        async def push(self, client, ev): good_calls.append(1)

    class Bad:
        name = "bad"; enabled = True
        async def push(self, client, ev): raise RuntimeError("boom")

    hub = PushHub([Bad(), Good()])
    await hub.broadcast(_event())
    assert good_calls == [1]


@pytest.mark.asyncio
async def test_empty_hub_is_noop():
    hub = PushHub([])
    assert not hub.enabled
    await hub.broadcast(_event())  # should not raise
