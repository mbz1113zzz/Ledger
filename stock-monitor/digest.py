"""Daily digest: aggregate last 24h high/medium events and push as one message."""
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from pushers import PushHub
from sources.base import Event
from storage import Storage

log = logging.getLogger(__name__)

TYPE_LABEL = {
    "filing_8k": "8-K",
    "earnings": "财报",
    "analyst": "分析师",
    "insider": "内部人",
    "price_alert": "异动",
    "sentiment": "舆情",
    "news": "新闻",
}


def build_digest(events: list[Event], *, now: datetime) -> tuple[str, str]:
    """Returns (title, body). Empty body if no events."""
    date_str = now.strftime("%m-%d")
    if not events:
        return (f"📊 早报 {date_str}", "过去 24 小时无重要事件。")

    by_ticker: dict[str, list[Event]] = defaultdict(list)
    for e in events:
        by_ticker[e.ticker].append(e)

    high_total = sum(1 for e in events if e.importance == "high")
    title = f"📊 早报 {date_str} · {len(by_ticker)} 票 · {high_total} 高优"

    lines: list[str] = []
    for ticker in sorted(by_ticker.keys()):
        evs = by_ticker[ticker]
        evs.sort(key=lambda e: (e.importance != "high", -e.published_at.timestamp()))
        lines.append(f"【{ticker}】{len(evs)} 条")
        for e in evs[:5]:
            marker = "🔴" if e.importance == "high" else "🟡"
            label = TYPE_LABEL.get(e.event_type, e.event_type)
            time_str = e.published_at.strftime("%H:%M")
            summary = e.summary_cn or ""
            line = f"  {marker} [{label} {time_str}] {e.title}"
            if summary:
                line += f"\n      └ {summary}"
            lines.append(line)
        if len(evs) > 5:
            lines.append(f"  … 另 {len(evs) - 5} 条")
        lines.append("")
    return title, "\n".join(lines).rstrip()


async def send_digest(
    storage: Storage,
    push_hub: PushHub,
    *,
    lookback_hours: int = 24,
    min_importance: str = "medium",
    now: datetime | None = None,
) -> int:
    """Query recent events and broadcast a digest. Returns event count."""
    if not push_hub.enabled:
        log.info("digest skipped: no push channels enabled")
        return 0
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=lookback_hours)
    events = storage.query_since(since, min_importance=min_importance)
    title, body = build_digest(events, now=now)
    await push_hub.broadcast_text(title, body)
    log.info("digest sent: %d events", len(events))
    return len(events)
