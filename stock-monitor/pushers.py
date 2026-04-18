"""Multi-channel push notifiers for high-importance events.

Each pusher is optional and silently skipped when its credentials are absent.
Supports Telegram, Bark (iOS), and Feishu (Lark) incoming webhooks.
"""
import asyncio
import logging
from abc import ABC, abstractmethod
from urllib.parse import quote

import httpx

from sources.base import Event

log = logging.getLogger(__name__)


def format_message(ev: Event) -> tuple[str, str]:
    """(title, body) plain-text."""
    title = f"[{ev.ticker}] {ev.title}"
    lines = []
    if ev.summary_cn:
        lines.append(ev.summary_cn)
    elif ev.summary:
        lines.append(ev.summary[:200])
    lines.append(f"{ev.source} · {ev.event_type} · {ev.published_at:%Y-%m-%d %H:%M}")
    if ev.url:
        lines.append(ev.url)
    return title, "\n".join(lines)


class Pusher(ABC):
    name: str = ""

    @property
    @abstractmethod
    def enabled(self) -> bool: ...

    @abstractmethod
    async def push(self, client: httpx.AsyncClient, ev: Event) -> None: ...

    async def push_text(self, client: httpx.AsyncClient, title: str, body: str) -> None:
        raise NotImplementedError


class TelegramPusher(Pusher):
    name = "telegram"

    def __init__(self, bot_token: str, chat_id: str):
        self._token = bot_token
        self._chat = chat_id

    @property
    def enabled(self) -> bool:
        return bool(self._token and self._chat)

    async def push(self, client: httpx.AsyncClient, ev: Event) -> None:
        title, body = format_message(ev)
        await self.push_text(client, title, body)

    async def push_text(self, client: httpx.AsyncClient, title: str, body: str) -> None:
        text = f"*{title}*\n{body}"
        resp = await client.post(
            f"https://api.telegram.org/bot{self._token}/sendMessage",
            json={"chat_id": self._chat, "text": text, "parse_mode": "Markdown",
                  "disable_web_page_preview": True},
        )
        resp.raise_for_status()


class BarkPusher(Pusher):
    """Bark iOS push. Pass the full device URL like https://api.day.app/<KEY>."""
    name = "bark"

    def __init__(self, base_url: str):
        self._base = base_url.rstrip("/") if base_url else ""

    @property
    def enabled(self) -> bool:
        return bool(self._base)

    async def push(self, client: httpx.AsyncClient, ev: Event) -> None:
        title, body = format_message(ev)
        await self.push_text(client, title, body)

    async def push_text(self, client: httpx.AsyncClient, title: str, body: str) -> None:
        url = f"{self._base}/{quote(title)}/{quote(body)}"
        resp = await client.get(url, params={"group": "stock-monitor"})
        resp.raise_for_status()


class FeishuPusher(Pusher):
    """Feishu/Lark incoming webhook (text message)."""
    name = "feishu"

    def __init__(self, webhook_url: str):
        self._url = webhook_url

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    async def push(self, client: httpx.AsyncClient, ev: Event) -> None:
        title, body = format_message(ev)
        await self.push_text(client, title, body)

    async def push_text(self, client: httpx.AsyncClient, title: str, body: str) -> None:
        text = f"{title}\n{body}"
        resp = await client.post(
            self._url,
            json={"msg_type": "text", "content": {"text": text}},
        )
        resp.raise_for_status()


class PushHub:
    def __init__(self, pushers: list[Pusher]):
        self._pushers = [p for p in pushers if p.enabled]
        if self._pushers:
            log.info("push channels enabled: %s",
                     ",".join(p.name for p in self._pushers))

    @property
    def enabled(self) -> bool:
        return bool(self._pushers)

    async def broadcast(self, ev: Event) -> None:
        if not self._pushers:
            return
        async with httpx.AsyncClient(timeout=8.0) as client:
            async def one(p: Pusher):
                try:
                    await p.push(client, ev)
                except Exception as e:
                    log.warning("pusher %s failed: %s", p.name, e)
            await asyncio.gather(*(one(p) for p in self._pushers))

    async def broadcast_text(self, title: str, body: str) -> None:
        if not self._pushers:
            return
        async with httpx.AsyncClient(timeout=15.0) as client:
            async def one(p: Pusher):
                try:
                    await p.push_text(client, title, body)
                except Exception as e:
                    log.warning("pusher %s text failed: %s", p.name, e)
            await asyncio.gather(*(one(p) for p in self._pushers))
