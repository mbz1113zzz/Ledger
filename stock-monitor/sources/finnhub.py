import logging
import time as time_module
from datetime import datetime, time, timedelta, timezone
from typing import Any

import httpx

from sources.base import Event, Source
from sources.health import SourceHealth

log = logging.getLogger(__name__)


class _CombinedSourceHealth:
    def __init__(self, source_name: str, **components: SourceHealth):
        self._name = source_name
        self._components = components

    @property
    def disabled(self) -> bool:
        return bool(self._components) and all(h.disabled for h in self._components.values())

    @property
    def reason(self) -> str | None:
        for health in self._components.values():
            if health.disabled and health.reason:
                return health.reason
        for health in self._components.values():
            if health.reason:
                return health.reason
        return None

    @property
    def last_status(self) -> int | None:
        for health in self._components.values():
            if health.disabled and health.last_status is not None:
                return health.last_status
        for health in self._components.values():
            if health.last_status is not None:
                return health.last_status
        return None

    def snapshot(self) -> dict:
        snaps = {name: health.snapshot() for name, health in self._components.items()}
        last_successes = [snap["last_success_at"] for snap in snaps.values() if snap["last_success_at"]]
        last_errors = [snap["last_error_at"] for snap in snaps.values() if snap["last_error_at"]]
        degraded = [
            name for name, snap in snaps.items()
            if snap["disabled"] or snap["reason"] is not None
        ]
        active = [name for name, snap in snaps.items() if not snap["disabled"]]
        latest_duration = None
        latest_seen = ""
        for snap in snaps.values():
            candidate = max(
                [ts for ts in (snap["last_error_at"], snap["last_success_at"]) if ts],
                default="",
            )
            if candidate >= latest_seen:
                latest_seen = candidate
                latest_duration = snap["last_duration_ms"]
        return {
            "name": self._name,
            "disabled": self.disabled,
            "reason": self.reason,
            "last_status": self.last_status,
            "request_count": sum(snap["request_count"] for snap in snaps.values()),
            "success_count": sum(snap["success_count"] for snap in snaps.values()),
            "error_count": sum(snap["error_count"] for snap in snaps.values()),
            "consecutive_4xx": max((snap["consecutive_4xx"] for snap in snaps.values()), default=0),
            "last_duration_ms": latest_duration,
            "last_success_at": max(last_successes, default=None),
            "last_error_at": max(last_errors, default=None),
            "active_endpoints": active,
            "degraded_endpoints": degraded,
            "partially_disabled": bool(degraded) and not self.disabled,
            "components": snaps,
        }


class FinnhubSource(Source):
    name = "finnhub"
    BASE_URL = "https://finnhub.io/api/v1"
    EARNINGS_LOOKAHEAD_DAYS = 90

    def __init__(
        self,
        api_key: str,
        *,
        enable_news: bool = True,
        enable_earnings: bool = True,
        storage=None,
        pricing=None,
    ):
        self._api_key = api_key
        self._enable_news = enable_news
        self._enable_earnings = enable_earnings
        self._storage = storage
        self._pricing = pricing
        self._news_health = SourceHealth(f"{self.name}:news")
        self._earnings_health = SourceHealth(f"{self.name}:earnings")
        self._health = _CombinedSourceHealth(
            self.name,
            news=self._news_health,
            earnings=self._earnings_health,
        )

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
            if self._enable_news and not self._news_health.disabled:
                t0 = time_module.perf_counter()
                try:
                    data = await self._get(
                        "/company-news",
                        {"symbol": ticker, "from": news_since, "to": news_until},
                    )
                    self._news_health.record_success(
                        duration_ms=(time_module.perf_counter() - t0) * 1000
                    )
                    for item in data or []:
                        ev = self._parse_news(item, ticker)
                        if ev:
                            events.append(ev)
                except httpx.TimeoutException as e:
                    self._news_health.record_timeout(
                        duration_ms=(time_module.perf_counter() - t0) * 1000,
                    )
                    log.warning("finnhub news timed out for %s: %s", ticker, e)
                except httpx.HTTPStatusError as e:
                    self._news_health.record_http_error(
                        e.response.status_code,
                        duration_ms=(time_module.perf_counter() - t0) * 1000,
                    )
                    log.warning("finnhub news failed for %s: %s", ticker, e)
                except Exception as e:
                    self._news_health.record_error(
                        reason="upstream_error",
                        duration_ms=(time_module.perf_counter() - t0) * 1000,
                    )
                    log.warning("finnhub news failed for %s: %s", ticker, e)

            if self._enable_earnings and not self._earnings_health.disabled:
                t0 = time_module.perf_counter()
                try:
                    data = await self._get(
                        "/calendar/earnings",
                        {"symbol": ticker, "from": today.isoformat(), "to": earnings_until},
                    )
                    self._earnings_health.record_success(
                        duration_ms=(time_module.perf_counter() - t0) * 1000
                    )
                    for item in (data or {}).get("earningsCalendar") or []:
                        ev = self._on_earnings_row(item, ticker)
                        if ev:
                            events.append(ev)
                except httpx.TimeoutException as e:
                    self._earnings_health.record_timeout(
                        duration_ms=(time_module.perf_counter() - t0) * 1000,
                    )
                    log.warning("finnhub earnings timed out for %s: %s", ticker, e)
                except httpx.HTTPStatusError as e:
                    self._earnings_health.record_http_error(
                        e.response.status_code,
                        duration_ms=(time_module.perf_counter() - t0) * 1000,
                    )
                    log.warning("finnhub earnings failed for %s: %s", ticker, e)
                except Exception as e:
                    self._earnings_health.record_error(
                        reason="upstream_error",
                        duration_ms=(time_module.perf_counter() - t0) * 1000,
                    )
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

    def _on_earnings_row(self, item: dict, ticker: str) -> Event | None:
        try:
            date_str = item["date"]
        except (KeyError, TypeError):
            return None

        eps_estimate = item.get("epsEstimate")
        eps_actual = item.get("epsActual")
        rev_estimate = item.get("revenueEstimate")
        rev_actual = item.get("revenueActual")
        hour = item.get("hour") or None
        now = datetime.now(timezone.utc)

        hour_label = {"bmo": "盘前", "amc": "盘后", "dmh": "盘中"}.get(hour or "", "")

        if self._storage is None:
            # Storage-less mode (legacy / unit tests that don't care about the
            # calendar table) — fall back to the old scheduled-only behavior.
            try:
                pub = datetime.combine(
                    datetime.strptime(date_str, "%Y-%m-%d").date(),
                    time(0, 0),
                    tzinfo=timezone.utc,
                )
            except (ValueError, TypeError):
                return None
            title = f"{ticker} 财报 {date_str}"
            if hour_label:
                title += f" {hour_label}"
            return Event(
                source=self.name,
                external_id=f"{ticker}-earnings-{date_str}",
                ticker=ticker, event_type="earnings", title=title,
                summary=None, url=None, published_at=pub, raw=item,
            )

        existing = self._storage.get_earnings(ticker, date_str)

        if existing is None:
            if eps_actual is None:
                self._storage.upsert_earnings(
                    ticker=ticker, scheduled_date=date_str, scheduled_hour=hour,
                    eps_estimate=eps_estimate, eps_actual=None,
                    rev_estimate=rev_estimate, rev_actual=None,
                    status="scheduled", updated_at=now,
                )
                try:
                    pub = datetime.combine(
                        datetime.strptime(date_str, "%Y-%m-%d").date(),
                        time(0, 0),
                        tzinfo=timezone.utc,
                    )
                except (ValueError, TypeError):
                    return None
                title = f"{ticker} 财报 {date_str}"
                if hour_label:
                    title += f" {hour_label}"
                return Event(
                    source=self.name,
                    external_id=f"{ticker}-earnings-{date_str}",
                    ticker=ticker, event_type="earnings", title=title,
                    summary=None, url=None, published_at=pub, raw=item,
                )
            # Bootstrap: actual is already populated. Land directly in `reacted`
            # without re-broadcasting historical earnings.
            self._storage.upsert_earnings(
                ticker=ticker, scheduled_date=date_str, scheduled_hour=hour,
                eps_estimate=eps_estimate, eps_actual=eps_actual,
                rev_estimate=rev_estimate, rev_actual=rev_actual,
                status="reacted", updated_at=now,
            )
            return None

        if existing["status"] == "scheduled" and eps_actual is not None:
            surprise = None
            if eps_estimate not in (None, 0) and eps_actual is not None:
                surprise = (eps_actual - eps_estimate) / abs(eps_estimate)
            mark_at_publish = self._pricing.latest(ticker) if self._pricing is not None else None
            self._storage.transition_to_published(
                ticker=ticker, scheduled_date=date_str,
                eps_actual=eps_actual, rev_actual=rev_actual,
                surprise_pct=surprise,
                mark_at_publish_price=mark_at_publish,
                detected_publish_at=now,
            )
            title = f"{ticker} 财报已公布 {date_str}"
            if hour_label:
                title += f" {hour_label}"
            summary_bits = []
            if eps_actual is not None and eps_estimate is not None:
                summary_bits.append(f"EPS {eps_actual:.2f} vs {eps_estimate:.2f}")
            elif eps_actual is not None:
                summary_bits.append(f"EPS {eps_actual:.2f}")
            if surprise is not None:
                summary_bits.append(f"({surprise:+.1%})")
            if rev_actual is not None and rev_estimate is not None:
                summary_bits.append(f"Revenue {rev_actual/1e9:.2f}B vs {rev_estimate/1e9:.2f}B")
            summary = "; ".join(summary_bits)
            ev = Event(
                source=self.name,
                external_id=f"{ticker}-earnings-published-{date_str}",
                ticker=ticker, event_type="earnings_published", title=title,
                summary=summary, url=None, published_at=now,
                raw={**item, "surprise_pct": surprise},
            )
            # Insert immediately so we can back-link the published_event_id.
            # Pipeline will re-attempt insert and dedup harmlessly on the
            # (source, external_id) UNIQUE constraint.
            inserted, ev_id = self._storage.insert_with_id(ev)
            if ev_id is not None:
                self._storage.set_published_event_id(ticker, date_str, ev_id)
            return ev

        # Existing row, status='scheduled' but still no actual — refresh estimates.
        if existing["status"] == "scheduled":
            self._storage.upsert_earnings(
                ticker=ticker, scheduled_date=date_str, scheduled_hour=hour,
                eps_estimate=eps_estimate, eps_actual=None,
                rev_estimate=rev_estimate, rev_actual=None,
                status="scheduled", updated_at=now,
            )
        return None
