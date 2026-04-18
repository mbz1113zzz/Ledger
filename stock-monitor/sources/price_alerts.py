import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from sources.base import Event, Source

log = logging.getLogger(__name__)


class PriceAlertSource(Source):
    """Emits an Event when |price - prev_close| / prev_close >= threshold."""

    name = "price_alert"
    BASE_URL = "https://finnhub.io/api/v1"

    def __init__(self, api_key: str, threshold_pct: float = 3.0):
        self._api_key = api_key
        self._threshold = threshold_pct

    async def _quote(self, client: httpx.AsyncClient, ticker: str) -> dict[str, Any] | None:
        resp = await client.get(
            f"{self.BASE_URL}/quote",
            params={"symbol": ticker, "token": self._api_key},
        )
        resp.raise_for_status()
        return resp.json() or None

    async def fetch(self, tickers: list[str]) -> list[Event]:
        if not self._api_key:
            return []
        events: list[Event] = []
        now = datetime.now(timezone.utc)
        day = now.strftime("%Y%m%d")
        async with httpx.AsyncClient(timeout=10.0) as client:
            for ticker in tickers:
                try:
                    q = await self._quote(client, ticker)
                except Exception as e:
                    log.warning("price quote failed for %s: %s", ticker, e)
                    continue
                if not q:
                    continue
                price = q.get("c")
                prev = q.get("pc")
                if not price or not prev:
                    continue
                pct = (price - prev) / prev * 100
                if abs(pct) < self._threshold:
                    continue
                direction = "up" if pct > 0 else "down"
                arrow = "↑" if pct > 0 else "↓"
                label = "上涨" if pct > 0 else "下跌"
                title = (
                    f"{ticker} {label} {arrow}{abs(pct):.2f}% "
                    f"(${prev:.2f} → ${price:.2f})"
                )
                events.append(Event(
                    source=self.name,
                    external_id=f"{ticker}-{direction}-{day}",
                    ticker=ticker,
                    event_type="price_alert",
                    title=title,
                    summary=f"前收 ${prev:.2f}，现价 ${price:.2f}，变动 {pct:+.2f}%",
                    url=None,
                    published_at=now,
                    raw=q,
                ))
        return events
