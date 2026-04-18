"""News sentiment spike detector using Finnhub /news-sentiment.

Emits an event when a ticker's daily buzz materially exceeds its weekly average.
One event per ticker per day.
"""
import logging
from datetime import datetime, time, timezone
from typing import Any

import httpx

from sources.base import Event, Source

log = logging.getLogger(__name__)


class SentimentSource(Source):
    name = "sentiment"
    BASE_URL = "https://finnhub.io/api/v1"
    SPIKE_RATIO = 2.0  # trigger when today's buzz >= 2x weekly average
    MIN_BUZZ = 5  # ignore tickers with too few mentions to be meaningful

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def _get(self, client: httpx.AsyncClient, ticker: str) -> Any:
        resp = await client.get(
            f"{self.BASE_URL}/news-sentiment",
            params={"symbol": ticker, "token": self._api_key},
        )
        resp.raise_for_status()
        return resp.json()

    async def fetch(self, tickers: list[str]) -> list[Event]:
        if not self._api_key:
            return []
        events: list[Event] = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            for ticker in tickers:
                try:
                    data = await self._get(client, ticker)
                except Exception as e:
                    log.warning("sentiment fetch failed for %s: %s", ticker, e)
                    continue
                ev = self._parse(data, ticker)
                if ev:
                    events.append(ev)
        return events

    def _parse(self, data: dict, ticker: str) -> Event | None:
        buzz = (data or {}).get("buzz") or {}
        weekly_avg = float(buzz.get("weeklyAverage") or 0)
        articles = float(buzz.get("articlesInLastWeek") or 0) / 7.0 \
            if buzz.get("articlesInLastWeek") else 0
        today_buzz = float(buzz.get("buzz") or 0)
        if today_buzz < self.MIN_BUZZ or weekly_avg <= 0:
            return None
        ratio = today_buzz / weekly_avg
        if ratio < self.SPIKE_RATIO:
            return None
        sentiment = (data.get("sentiment") or {})
        bullish = float(sentiment.get("bullishPercent") or 0)
        polarity = "偏多" if bullish >= 0.55 else ("偏空" if bullish <= 0.45 else "中性")
        today = datetime.now(timezone.utc).date()
        pub = datetime.combine(today, time(0, 0), tzinfo=timezone.utc)
        title = (
            f"{ticker} 舆情放量 ×{ratio:.1f} · {polarity}"
            f"（{int(today_buzz)} 篇 / 周均 {weekly_avg:.1f}）"
        )
        return Event(
            source=self.name,
            external_id=f"{ticker}-sentiment-{today.isoformat()}",
            ticker=ticker,
            event_type="sentiment",
            title=title,
            summary=None,
            url=None,
            published_at=pub,
            raw={"buzz": today_buzz, "weekly_avg": weekly_avg,
                 "ratio": ratio, "bullish_pct": bullish,
                 "articles_per_day": articles},
        )
