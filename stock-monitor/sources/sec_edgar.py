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
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=20.0,
                headers={"User-Agent": SEC_USER_AGENT},
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    async def _get(self, url: str) -> Any:
        resp = await self._get_client().get(url)
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
            events.extend(self._parse_filings(data, ticker, cik))
        return events

    def _parse_filings(self, data: dict, ticker: str, cik: str) -> list[Event]:
        try:
            recent = data["filings"]["recent"]
            n = len(recent["accessionNumber"])
        except (KeyError, TypeError):
            return []
        out: list[Event] = []
        for i in range(n):
            form = recent["form"][i]
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
            primary_doc = recent["primaryDocument"][i]
            url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{no_dash}/{primary_doc}"
            items_field = (recent.get("items") or [""] * n)[i] or ""

            if form == "8-K":
                items = [x.strip() for x in items_field.split(",") if x.strip()]
                item_labels = [ITEM_LABELS.get(code, code) for code in items]
                title = f"{ticker} 8-K"
                if item_labels:
                    title += " · " + " / ".join(item_labels)
                out.append(Event(
                    source=self.name,
                    external_id=accession,
                    ticker=ticker,
                    event_type="filing_8k",
                    title=title,
                    summary=recent.get("primaryDocDescription", [""] * n)[i] or None,
                    url=url,
                    published_at=pub,
                    raw={"accession": accession, "cik": cik, "date": date_str,
                         "items": items},
                ))
            elif form in ("4", "4/A"):
                out.append(Event(
                    source=self.name,
                    external_id=accession,
                    ticker=ticker,
                    event_type="insider",
                    title=f"{ticker} 内部人交易 (Form {form})",
                    summary=None,
                    url=url,
                    published_at=pub,
                    raw={"accession": accession, "cik": cik, "date": date_str,
                         "form": form},
                ))
        return out


ITEM_LABELS = {
    "1.01": "重大合同", "1.02": "合同终止", "1.03": "破产或接管",
    "2.01": "完成资产收购/处置", "2.02": "业绩披露", "2.03": "重大直接财务义务",
    "2.04": "触发加速偿债", "2.05": "退出成本", "2.06": "资产减值",
    "3.01": "退市通知", "3.02": "定向增发", "3.03": "权利变更",
    "4.01": "更换会计师", "4.02": "财报不可依赖",
    "5.01": "控制权变更", "5.02": "高管/董事变动", "5.03": "章程修订",
    "5.04": "401k计划暂停", "5.05": "道德准则豁免", "5.07": "股东投票结果",
    "5.08": "股东会日期",
    "7.01": "Reg FD 披露", "8.01": "其他重大事件",
    "9.01": "财务报表与附件",
}
