"""LLM-based enricher: Chinese TL;DR + (optional) importance re-scoring.

Gracefully no-op when ANTHROPIC_API_KEY is not configured.
"""
import asyncio
import logging
from typing import Any

import httpx

from sources.base import Event

log = logging.getLogger(__name__)

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

PROMPT = (
    "你是美股事件助理。用 1-2 句中文总结下面的事件，"
    "要点优先：涉及哪只股票、什么事、对股价可能的影响方向。"
    "严格控制在 60 字以内。只输出摘要本身，不要前缀或解释。\n\n"
    "Ticker: {ticker}\n"
    "Type: {event_type}\n"
    "Title: {title}\n"
    "Summary: {summary}"
)


class Enricher:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        only_high: bool = True,
        concurrency: int = 4,
    ):
        self._api_key = api_key
        self._model = model
        self._only_high = only_high
        self._sem = asyncio.Semaphore(concurrency)

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    async def enrich(self, events: list[Event]) -> list[Event]:
        if not self.enabled or not events:
            return events
        targets = [
            e for e in events
            if (not self._only_high or e.importance == "high")
            and e.event_type != "price_alert"
            and not e.summary_cn
        ]
        if not targets:
            return events
        async with httpx.AsyncClient(timeout=20.0) as client:
            await asyncio.gather(
                *(self._enrich_one(client, e) for e in targets),
                return_exceptions=True,
            )
        return events

    async def _enrich_one(self, client: httpx.AsyncClient, ev: Event) -> None:
        async with self._sem:
            try:
                text = await self._call(client, ev)
                ev.summary_cn = text
            except Exception as e:
                log.warning("enrich failed for %s/%s: %s", ev.source, ev.external_id, e)

    async def _call(self, client: httpx.AsyncClient, ev: Event) -> str:
        prompt = PROMPT.format(
            ticker=ev.ticker,
            event_type=ev.event_type,
            title=ev.title,
            summary=(ev.summary or "")[:800],
        )
        resp = await client.post(
            API_URL,
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": API_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": self._model,
                "max_tokens": 200,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        blocks = data.get("content") or []
        parts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
        return "".join(parts).strip()
