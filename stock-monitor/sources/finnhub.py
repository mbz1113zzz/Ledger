import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from sources.base import Event, Source

log = logging.getLogger(__name__)


class FinnhubSource(Source):
    name = "finnhub"
    BASE_URL = "https://finnhub.io/api/v1"

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def _get(self, path: str, params: dict) -> Any:
        params = {**params, "token": self._api_key}
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{self.BASE_URL}{path}", params=params)
            resp.raise_for_status()
            return resp.json()

    async def fetch(self, tickers: list[str]) -> list[Event]:
        if not self._api_key:
            log.warning("Finnhub API key not set; skipping")
            return []
        today = datetime.now(timezone.utc).date()
        since = (today - timedelta(days=1)).isoformat()
        until = today.isoformat()
        events: list[Event] = []
        for ticker in tickers:
            try:
                data = await self._get(
                    "/company-news",
                    {"symbol": ticker, "from": since, "to": until},
                )
            except Exception as e:
                log.warning("finnhub fetch failed for %s: %s", ticker, e)
                continue
            for item in data or []:
                ev = self._parse(item, ticker)
                if ev:
                    events.append(ev)
        return events

    def _parse(self, item: dict, ticker: str) -> Event | None:
        try:
            ts = item["datetime"]
            return Event(
                source=self.name,
                external_id=str(item["id"]),
                ticker=ticker,
                event_type="news",
                title=item["headline"],
                summary=item.get("summary") or None,
                url=item.get("url"),
                published_at=datetime.fromtimestamp(ts, tz=timezone.utc),
                raw=item,
            )
        except (KeyError, TypeError) as e:
            log.debug("skipping malformed finnhub item: %s", e)
            return None
