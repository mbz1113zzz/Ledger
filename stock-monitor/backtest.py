"""Event impact backtest.

For each past event of a given (ticker, event_type), compute price change at
+1/+3/+7 trading days vs the event day close. Reports mean/median/positive rate.
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

import httpx

from storage import Storage

log = logging.getLogger(__name__)


class PriceFetcher(Protocol):
    async def daily_closes(
        self, ticker: str, start: date, end: date
    ) -> dict[date, float]: ...


class YahooPriceFetcher:
    """Unofficial Yahoo Finance chart API — no key, daily closes."""
    BASE = "https://query1.finance.yahoo.com/v8/finance/chart"

    async def daily_closes(
        self, ticker: str, start: date, end: date
    ) -> dict[date, float]:
        p1 = int(datetime.combine(start, datetime.min.time(), timezone.utc).timestamp())
        p2 = int(datetime.combine(end, datetime.min.time(), timezone.utc).timestamp())
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                f"{self.BASE}/{ticker}",
                params={"period1": p1, "period2": p2, "interval": "1d"},
                headers={"User-Agent": "Mozilla/5.0"},
            )
            r.raise_for_status()
            data = r.json()
        result: dict[date, float] = {}
        try:
            chart = data["chart"]["result"][0]
            ts = chart["timestamp"]
            closes = chart["indicators"]["quote"][0]["close"]
        except (KeyError, IndexError, TypeError):
            return result
        for t, c in zip(ts, closes):
            if c is None:
                continue
            d = datetime.fromtimestamp(t, tz=timezone.utc).date()
            result[d] = float(c)
        return result


@dataclass
class WindowStats:
    window: int
    n: int
    mean_pct: float
    median_pct: float
    positive_rate: float


def _nearest_close_on_or_before(closes: dict[date, float], d: date) -> float | None:
    for i in range(6):
        hit = closes.get(d - timedelta(days=i))
        if hit is not None:
            return hit
    return None


def _nearest_close_on_or_after(closes: dict[date, float], d: date) -> float | None:
    for i in range(10):
        hit = closes.get(d + timedelta(days=i))
        if hit is not None:
            return hit
    return None


def compute_stats(
    event_dates: list[date],
    closes: dict[date, float],
    windows: list[int],
) -> list[WindowStats]:
    out: list[WindowStats] = []
    for w in windows:
        returns: list[float] = []
        for ed in event_dates:
            base = _nearest_close_on_or_before(closes, ed)
            fwd = _nearest_close_on_or_after(closes, ed + timedelta(days=w))
            if base is None or fwd is None or base == 0:
                continue
            returns.append((fwd - base) / base * 100)
        if not returns:
            out.append(WindowStats(window=w, n=0, mean_pct=0.0,
                                   median_pct=0.0, positive_rate=0.0))
            continue
        returns_sorted = sorted(returns)
        mid = len(returns_sorted) // 2
        median = (
            returns_sorted[mid] if len(returns_sorted) % 2
            else (returns_sorted[mid - 1] + returns_sorted[mid]) / 2
        )
        out.append(WindowStats(
            window=w, n=len(returns),
            mean_pct=sum(returns) / len(returns),
            median_pct=median,
            positive_rate=sum(1 for r in returns if r > 0) / len(returns),
        ))
    return out


async def run_backtest(
    storage: Storage,
    fetcher: PriceFetcher,
    *,
    ticker: str,
    event_type: str,
    windows: list[int] | None = None,
    lookback_days: int = 365,
) -> dict:
    windows = windows or [1, 3, 7]
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    rows = storage.query_since(since, min_importance="low")
    events = [
        e for e in rows
        if e.ticker.upper() == ticker.upper() and e.event_type == event_type
    ]
    if not events:
        return {"ticker": ticker, "event_type": event_type,
                "n_events": 0, "windows": []}
    event_dates = [e.published_at.date() for e in events]
    start = min(event_dates) - timedelta(days=5)
    end = max(event_dates) + timedelta(days=max(windows) + 10)
    try:
        closes = await fetcher.daily_closes(ticker, start, end)
    except Exception as e:
        log.warning("price fetch failed for %s: %s", ticker, e)
        closes = {}
    stats = compute_stats(event_dates, closes, windows)
    return {
        "ticker": ticker,
        "event_type": event_type,
        "n_events": len(events),
        "windows": [
            {"window": s.window, "n": s.n, "mean_pct": round(s.mean_pct, 2),
             "median_pct": round(s.median_pct, 2),
             "positive_rate": round(s.positive_rate, 2)}
            for s in stats
        ],
    }
