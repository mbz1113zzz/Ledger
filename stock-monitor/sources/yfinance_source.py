import asyncio
import logging
from datetime import date, datetime, time, timezone

import yfinance as yf

from sources.base import Event, Source

log = logging.getLogger(__name__)


class YfinanceSource(Source):
    name = "yfinance"

    async def fetch(self, tickers: list[str]) -> list[Event]:
        return await asyncio.to_thread(self._fetch_sync, tickers)

    def _fetch_sync(self, tickers: list[str]) -> list[Event]:
        events: list[Event] = []
        for ticker in tickers:
            try:
                t = yf.Ticker(ticker)
                cal = t.calendar or {}
                dates = cal.get("Earnings Date") or []
                for d in dates:
                    ev = self._make_event(ticker, d)
                    if ev:
                        events.append(ev)
            except Exception as e:
                log.warning("yfinance fetch failed for %s: %s", ticker, e)
                continue
        return events

    def _make_event(self, ticker: str, d) -> Event | None:
        if isinstance(d, datetime):
            d = d.date()
        if not isinstance(d, date):
            return None
        pub = datetime.combine(d, time(0, 0), tzinfo=timezone.utc)
        return Event(
            source=self.name,
            external_id=f"{ticker}-earnings-{d.isoformat()}",
            ticker=ticker,
            event_type="earnings",
            title=f"{ticker} earnings scheduled {d.isoformat()}",
            summary=None,
            url=None,
            published_at=pub,
            raw={"date": d.isoformat()},
        )
