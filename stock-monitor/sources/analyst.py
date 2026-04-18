import logging
from datetime import datetime, time, timedelta, timezone
from typing import Any

import httpx

from sources.base import Event, Source

log = logging.getLogger(__name__)


GRADE_CN = {
    "buy": "买入", "strong buy": "强烈买入", "outperform": "跑赢大盘",
    "overweight": "增持", "hold": "持有", "neutral": "中性",
    "underperform": "跑输大盘", "underweight": "减持", "sell": "卖出",
    "strong sell": "强烈卖出",
}

ACTION_CN = {
    "up": "上调", "down": "下调", "maintain": "维持",
    "init": "首次覆盖", "reit": "重申", "target": "调整目标价",
}


class AnalystSource(Source):
    """Analyst upgrades/downgrades from Finnhub /stock/upgrade-downgrade."""

    name = "analyst"
    BASE_URL = "https://finnhub.io/api/v1"
    LOOKBACK_DAYS = 7

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def _get(self, client: httpx.AsyncClient, path: str, params: dict) -> Any:
        params = {**params, "token": self._api_key}
        resp = await client.get(f"{self.BASE_URL}{path}", params=params)
        resp.raise_for_status()
        return resp.json()

    async def fetch(self, tickers: list[str]) -> list[Event]:
        if not self._api_key:
            return []
        today = datetime.now(timezone.utc).date()
        since = (today - timedelta(days=self.LOOKBACK_DAYS)).isoformat()
        events: list[Event] = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            for ticker in tickers:
                try:
                    data = await self._get(
                        client,
                        "/stock/upgrade-downgrade",
                        {"symbol": ticker, "from": since, "to": today.isoformat()},
                    )
                except Exception as e:
                    log.warning("analyst fetch failed for %s: %s", ticker, e)
                    continue
                for item in data or []:
                    ev = self._parse(item, ticker)
                    if ev:
                        events.append(ev)
        return events

    def _parse(self, item: dict, ticker: str) -> Event | None:
        try:
            grade_time = item["gradeTime"]
            company = item.get("company") or "Unknown"
            from_g = (item.get("fromGrade") or "").strip()
            to_g = (item.get("toGrade") or "").strip()
            action = (item.get("action") or "").strip().lower()
        except (KeyError, TypeError):
            return None
        try:
            pub = datetime.combine(
                datetime.strptime(grade_time, "%Y-%m-%d").date(),
                time(0, 0),
                tzinfo=timezone.utc,
            )
        except (ValueError, TypeError):
            return None
        action_cn = ACTION_CN.get(action, action or "评级变动")
        from_cn = GRADE_CN.get(from_g.lower(), from_g)
        to_cn = GRADE_CN.get(to_g.lower(), to_g)
        if from_g and to_g and from_g.lower() != to_g.lower():
            change = f"{from_cn} → {to_cn}"
        elif to_g:
            change = to_cn
        else:
            change = "评级变动"
        title = f"{ticker} · {company} {action_cn}：{change}"
        return Event(
            source=self.name,
            external_id=f"{ticker}-{company}-{grade_time}-{to_g}".replace(" ", "_"),
            ticker=ticker,
            event_type="analyst",
            title=title,
            summary=None,
            url=None,
            published_at=pub,
            raw=item,
        )
