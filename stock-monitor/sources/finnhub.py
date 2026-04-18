import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any

import httpx

from sources.base import Event, Source

log = logging.getLogger(__name__)


class FinnhubSource(Source):
    name = "finnhub"
    BASE_URL = "https://finnhub.io/api/v1"
    EARNINGS_LOOKAHEAD_DAYS = 30

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
        news_since = (today - timedelta(days=1)).isoformat()
        news_until = today.isoformat()
        earnings_until = (today + timedelta(days=self.EARNINGS_LOOKAHEAD_DAYS)).isoformat()
        events: list[Event] = []
        for ticker in tickers:
            try:
                data = await self._get(
                    "/company-news",
                    {"symbol": ticker, "from": news_since, "to": news_until},
                )
                for item in data or []:
                    ev = self._parse_news(item, ticker)
                    if ev:
                        events.append(ev)
            except Exception as e:
                log.warning("finnhub news failed for %s: %s", ticker, e)

            try:
                data = await self._get(
                    "/calendar/earnings",
                    {"symbol": ticker, "from": today.isoformat(), "to": earnings_until},
                )
                for item in (data or {}).get("earningsCalendar") or []:
                    ev = self._parse_earnings(item, ticker)
                    if ev:
                        events.append(ev)
            except Exception as e:
                log.warning("finnhub earnings failed for %s: %s", ticker, e)
        return events

    def _parse_news(self, item: dict, ticker: str) -> Event | None:
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
            log.debug("skipping malformed finnhub news: %s", e)
            return None

    def _parse_earnings(self, item: dict, ticker: str) -> Event | None:
        try:
            date_str = item["date"]
            pub = datetime.combine(
                datetime.strptime(date_str, "%Y-%m-%d").date(),
                time(0, 0),
                tzinfo=timezone.utc,
            )
        except (KeyError, ValueError, TypeError):
            return None
        hour_label = {"bmo": "盘前", "amc": "盘后", "dmh": "盘中"}.get(
            item.get("hour") or "", ""
        )
        title = f"{ticker} 财报 {date_str}"
        if hour_label:
            title += f" {hour_label}"
        return Event(
            source=self.name,
            external_id=f"{ticker}-earnings-{date_str}",
            ticker=ticker,
            event_type="earnings",
            title=title,
            summary=None,
            url=None,
            published_at=pub,
            raw=item,
        )
