from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config
from storage import Storage

_ET = ZoneInfo("America/New_York")

# Anchor (ET hour, minute) per Finnhub `hour` field. NULL falls back to AMC,
# which is the most common case and the most conservative for blackout.
_HOUR_ANCHOR = {
    "bmo": (9, 0),
    "amc": (16, 30),
    "dmh": (12, 0),
    None:  (16, 30),
}


def in_earnings_blackout(
    storage: Storage, ticker: str, ts: datetime,
) -> tuple[bool, str | None]:
    """Return (blocked, reason).

    `ts` may be in any tz-aware datetime; comparison is done in ET. Returns
    True iff there exists a non-stale earnings_calendar row for `ticker`
    whose ET anchor falls inside [ts - BEFORE_MIN, ts + AFTER_MIN].
    """
    if not config.EARNINGS_BLACKOUT_ENABLED:
        return False, None
    ts_et = ts.astimezone(_ET)

    pad_days = max(2, (config.EARNINGS_BLACKOUT_BEFORE_MIN + config.EARNINGS_BLACKOUT_AFTER_MIN) // 1440 + 2)
    earliest = (ts_et - timedelta(days=pad_days)).date().isoformat()
    latest = (ts_et + timedelta(days=pad_days)).date().isoformat()

    rows = storage.find_earnings_in_range(ticker, earliest, latest)
    for row in rows:
        if row["status"] == "stale":
            continue
        anchor = _row_anchor_et(row)
        before_start = anchor - timedelta(minutes=config.EARNINGS_BLACKOUT_BEFORE_MIN)
        after_end = anchor + timedelta(minutes=config.EARNINGS_BLACKOUT_AFTER_MIN)
        if before_start <= ts_et <= after_end:
            hour_label = row["scheduled_hour"] or "?"
            reason = f"earnings_blackout:{ticker}@{row['scheduled_date']}/{hour_label}"
            return True, reason
    return False, None


def _row_anchor_et(row: dict) -> datetime:
    h, m = _HOUR_ANCHOR[row["scheduled_hour"]]
    d = datetime.fromisoformat(row["scheduled_date"]).date()
    return datetime(d.year, d.month, d.day, h, m, tzinfo=_ET)
