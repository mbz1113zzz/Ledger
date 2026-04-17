import logging
from datetime import datetime, time, timezone
from typing import Any

import httpx

from config import SEC_USER_AGENT
from sources.base import Event, Source

log = logging.getLogger(__name__)

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


class SecEdgarSource(Source):
    name = "sec_edgar"

    def __init__(self):
        self._ticker_to_cik: dict[str, str] = {}

    async def _get(self, url: str) -> Any:
        headers = {"User-Agent": SEC_USER_AGENT}
        async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()

    async def load_ticker_map(self) -> None:
        try:
            data = await self._get(TICKERS_URL)
        except Exception as e:
            log.error("failed to load SEC ticker map: %s", e)
            return
        for entry in (data or {}).values():
            ticker = entry.get("ticker", "").upper()
            cik = entry.get("cik_str")
            if ticker and cik is not None:
                self._ticker_to_cik[ticker] = str(cik).zfill(10)

    async def fetch(self, tickers: list[str]) -> list[Event]:
        events: list[Event] = []
        for ticker in tickers:
            cik = self._ticker_to_cik.get(ticker.upper())
            if not cik:
                log.debug("no CIK for ticker %s", ticker)
                continue
            try:
                data = await self._get(f"https://data.sec.gov/submissions/CIK{cik}.json")
            except Exception as e:
                log.warning("sec fetch failed for %s: %s", ticker, e)
                continue
            events.extend(self._parse_8ks(data, ticker, cik))
        return events

    def _parse_8ks(self, data: dict, ticker: str, cik: str) -> list[Event]:
        try:
            recent = data["filings"]["recent"]
            n = len(recent["accessionNumber"])
        except (KeyError, TypeError):
            return []
        out: list[Event] = []
        for i in range(n):
            if recent["form"][i] != "8-K":
                continue
            accession = recent["accessionNumber"][i]
            date_str = recent["filingDate"][i]
            try:
                pub = datetime.combine(
                    datetime.strptime(date_str, "%Y-%m-%d").date(),
                    time(0, 0),
                    tzinfo=timezone.utc,
                )
            except ValueError:
                continue
            no_dash = accession.replace("-", "")
            url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{no_dash}/{recent['primaryDocument'][i]}"
            out.append(
                Event(
                    source=self.name,
                    external_id=accession,
                    ticker=ticker,
                    event_type="filing_8k",
                    title=f"{ticker} filed 8-K",
                    summary=recent.get("primaryDocDescription", [""] * n)[i] or None,
                    url=url,
                    published_at=pub,
                    raw={"accession": accession, "cik": cik, "date": date_str},
                )
            )
        return out
