from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import config
from paper.pricing import PriceBook
from storage import Storage

log = logging.getLogger(__name__)


def _format_summary(row: dict, reaction: float | None) -> str:
    eps_actual = row.get("eps_actual")
    eps_est = row.get("eps_estimate")
    rev_actual = row.get("rev_actual")
    rev_est = row.get("rev_estimate")
    surprise = row.get("surprise_pct")

    bits = []
    if eps_actual is not None and eps_est is not None:
        bits.append(f"EPS {eps_actual:.2f} vs {eps_est:.2f}")
    elif eps_actual is not None:
        bits.append(f"EPS {eps_actual:.2f}")
    if surprise is not None:
        bits.append(f"({surprise:+.1%})")
    if rev_actual is not None and rev_est is not None:
        bits.append(f"营收 {rev_actual/1e9:.2f}B vs {rev_est/1e9:.2f}B")
    if reaction is not None:
        bits.append(f"30m 反应 {reaction:+.1%}")
    return "; ".join(bits)


async def backfill_earnings_reactions(
    storage: Storage, pricing: PriceBook, *, now: datetime | None = None,
) -> None:
    """Process all published_pending_reaction rows.

    For each row whose detected_publish_at is at least DELAY_MIN minutes
    in the past:
      - read latest mark for ticker; if absent and within TIMEOUT_HOURS,
        skip (will retry next sweep)
      - otherwise compute reaction_pct = (mark_now - mark_at_publish) /
        mark_at_publish (or None if either side is missing) and update
        the row + the linked events.summary; mark status='reacted'.
    """
    now = now or datetime.now(timezone.utc)
    delay = timedelta(minutes=config.EARNINGS_REACTION_BACKFILL_DELAY_MIN)
    timeout = timedelta(hours=config.EARNINGS_REACTION_BACKFILL_TIMEOUT_HOURS)
    for row in storage.list_earnings_by_status("published_pending_reaction"):
        try:
            detected = datetime.fromisoformat(row["detected_publish_at"])
        except (TypeError, ValueError):
            log.warning("earnings row %s has bad detected_publish_at; forcing reacted", row["id"])
            storage.set_earnings_status(row["id"], "reacted")
            continue
        elapsed = now - detected
        if elapsed < delay:
            continue

        mark_now = pricing.latest(row["ticker"])
        mark_pub = row.get("mark_at_publish_price")

        if (mark_now is None or mark_pub is None) and elapsed < timeout:
            continue

        reaction = None
        if mark_now is not None and mark_pub is not None and mark_pub > 0:
            reaction = (mark_now - mark_pub) / mark_pub

        storage.update_earnings_reaction(row["id"], reaction)
        if row.get("published_event_id"):
            storage.update_event_summary(
                row["published_event_id"],
                _format_summary(row, reaction),
            )
        storage.set_earnings_status(row["id"], "reacted")
