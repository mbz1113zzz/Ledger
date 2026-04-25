# Earnings Realtime — Design Spec

Date: 2026-04-25
Status: Approved (brainstorm complete)
Scope: Sub-project A of the next-step roadmap. Sub-projects B (paper
trading) and C (frontend) are deferred and will get their own specs.

## 1. Goal

Close two gaps in earnings handling:

1. **Result data is missing.** Today the system only emits a calendar
   notice ("AAPL 财报 2026-04-30 盘后"). When the company reports, EPS,
   revenue, surprise, and post-release price reaction are not surfaced.
2. **SMC has no earnings awareness.** Paper trading will happily open
   SMC entries on a ticker minutes before its earnings call.

Outcome:

- An `earnings_published` event with EPS / revenue / surprise % and a
  30-minute price reaction snapshot embedded in the summary.
- A configurable blackout window that prevents SMC paper entries near
  earnings.

## 2. User-Facing Decisions (settled in brainstorm)

| Topic | Decision |
|---|---|
| Use case | (1) push notification + (3) SMC entry filter |
| Push policy | Tiered: surprise ≥ 5% → high; otherwise medium |
| Reaction snapshot | Embedded in `earnings_published.summary`, late-write at +30 min |
| Blackout window | Configurable env vars; default = ET-day + next pre-market |
| Storage approach | Dedicated `earnings_calendar` table (Approach B) |
| Reject behavior | Blocked SMC entries emit `execution_intent` rejected |
| Late-write fallback | If pricing unavailable >6 h, write NULL reaction and force `reacted` |

## 3. Architecture

```
Finnhub /calendar/earnings  ─→  FinnhubSource.fetch
                                    │ upsert
                                    ↓
                            earnings_calendar table
                                    │ status transitions
                ┌───────────────────┼─────────────────────┐
                ↓                   ↓                     ↓
         emit earnings        emit earnings_         scheduler job
         _scheduled           published              backfill_reactions
         (existing)           (new)                  (every 5 min)
                                                        │
                                                        ↓
                                              update events.summary
                                              with reaction_pct_30m
```

### New / changed components

- **New table** `earnings_calendar` — state machine + last-seen snapshot
- **`sources/finnhub.py`** — `_parse_earnings` → `_on_earnings_row`:
  upserts the row and detects status transitions
- **`storage.py`** — new methods:
  `upsert_earnings`, `get_earnings`, `find_earnings_in_range`,
  `transition_to_published`, `update_earnings_reaction`, `set_status`,
  `update_event_summary` (sole append-only exception, by `id` only)
- **`paper/earnings_gate.py`** — single gatekeeper
  `in_earnings_blackout(storage, ticker, ts) -> (bool, reason | None)`
- **`paper/strategy.py`** — call gate before opening SMC entries; on
  block, emit `execution_intent` rejected
- **`event_scorer.py`** — score `earnings_published` by surprise %
- **`scheduler.py`** — register `backfill_earnings_reactions` job (5 min)
  and a daily `mark_stale_earnings` job
- **`web/routes.py`** — `GET /api/earnings/upcoming` (interface only;
  UI consumption deferred to sub-project C)

### Unchanged

- `events` table stays append-only except for the `update_event_summary`
  helper, which only mutates the `summary` column on a row identified
  by `id` (no row insert/delete).
- `Pipeline`, `Notifier`, `PushHub` are not touched.
- The existing `earnings` event (scheduled notice, importance=low) keeps
  its current behavior.

## 4. Data Model

```sql
CREATE TABLE earnings_calendar (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker          TEXT    NOT NULL,
  scheduled_date  TEXT    NOT NULL,            -- 'YYYY-MM-DD' (ET-anchored)
  scheduled_hour  TEXT,                         -- 'bmo' | 'amc' | 'dmh' | NULL
  eps_estimate    REAL,
  eps_actual      REAL,
  rev_estimate    REAL,
  rev_actual      REAL,
  surprise_pct    REAL,                         -- (eps_actual - eps_estimate)/|eps_estimate|
  reaction_pct_30m REAL,                        -- (mark_now - mark_at_publish)/mark_at_publish
  status          TEXT    NOT NULL,             -- 'scheduled' | 'published_pending_reaction' | 'reacted' | 'stale'
  published_event_id INTEGER,                   -- FK to events.id (not enforced; matches project pattern)
  detected_publish_at TEXT,                     -- UTC ISO; baseline for +30m backfill
  updated_at      TEXT    NOT NULL,             -- UTC ISO
  UNIQUE(ticker, scheduled_date)
);

CREATE INDEX idx_earnings_status_date ON earnings_calendar(status, scheduled_date);
CREATE INDEX idx_earnings_ticker_date ON earnings_calendar(ticker, scheduled_date);
```

### Field semantics

- `scheduled_date` is **ET-anchored** so that AMC reports do not
  cross-night into the next UTC day.
- `surprise_pct` denominator is `eps_estimate`, sign preserved. NULL
  when `eps_estimate == 0` or missing.
- `reaction_pct_30m` baseline is the last known mark **at or before**
  `detected_publish_at`. Late-write only.
- Raw Finnhub payload is NOT persisted in this table — it already lives
  on the corresponding row in `events.raw`.

### Migration / first-run

- Table is created lazily on `Storage.init`.
- First poll upserts all rows in the 90-day lookahead window. Rows
  whose `epsActual` is already populated land directly in status
  `reacted` with no event emission. This is the **bootstrap quiet
  period** — historical reports do not retro-blast push channels.

## 5. State Machine

```
                  [first seen by Finnhub]
                            │
                            ▼
                   ┌────────────────┐
                   │   scheduled    │ ◀── re-upsert updates estimates
                   └───────┬────────┘
                           │ epsActual transitions NULL → number
                           ▼
        ┌──────────────────────────────────────┐
        │  published_pending_reaction          │ ─→ emit earnings_published
        │  - set surprise_pct                  │     importance by surprise %
        │  - set detected_publish_at = now_utc │     write published_event_id
        │  - set published_event_id            │
        └───────┬──────────────────────────────┘
                │ scheduler job: now ≥ detected_publish_at + 30m
                │ - read paper/pricing.last_price
                │ - compute reaction_pct_30m
                │ - update events.summary (append reaction)
                ▼
                   ┌────────────────┐
                   │    reacted     │  ◀── terminal
                   └────────────────┘

                   ┌────────────────┐
                   │     stale      │  ◀── scheduled_date < today - 7d
                   └────────────────┘       and still status='scheduled'
```

### Transition rules

- `scheduled → published_pending_reaction` is **one-way**. Even if a
  later poll wipes `epsActual`, we do not regress (Finnhub revisions
  are rare and trust-but-don't-rebroadcast is safer).
- `published_pending_reaction → reacted` always happens after backfill,
  even when pricing data is unavailable (NULL reaction, status forced
  after `EARNINGS_REACTION_BACKFILL_TIMEOUT_HOURS`).
- `scheduled → stale` is set by a daily scheduler sweep.
- `stale` rows do not block SMC entries.

## 6. Event Generation Rules

| Event type | Trigger | Importance |
|---|---|---|
| `earnings` (existing) | First time we see a row in `scheduled` | low |
| `earnings_published` (new) | Transition `scheduled → published_pending_reaction` | high if `|surprise_pct| ≥ EARNINGS_SURPRISE_HIGH_PCT`, else medium |

Bootstrap rows that land directly in `reacted` (actual already populated
on first sight) emit **no event**.

`earnings_published.summary` initial form:
```
{ticker} EPS {actual} vs {estimate} ({surprise:+.1%}); rev {rev_actual} vs {rev_estimate}
```

After +30 min reaction backfill, summary becomes:
```
{ticker} EPS {actual} vs {estimate} ({surprise:+.1%}); rev {...}; 30m 反应 {reaction:+.1%}
```

`importance` is decided in `event_scorer.py` and frozen at insert time
(it is not re-scored when the summary is updated, to avoid breaking the
push-channel decision after the fact).

## 7. SMC Blackout Gate

Module: `paper/earnings_gate.py`

Public surface — **single function**:

```python
def in_earnings_blackout(
    storage: Storage,
    ticker: str,
    ts: datetime,                # any tz-aware datetime
) -> tuple[bool, str | None]:
    ...
```

ET-anchor table for converting `scheduled_hour` to a clock time:

| `scheduled_hour` | Anchor (ET) |
|---|---|
| `bmo` | 09:00 |
| `amc` | 16:30 |
| `dmh` | 12:00 |
| NULL  | 16:30 (fallback to AMC) |

Blackout interval: `[anchor − BEFORE_MIN, anchor + AFTER_MIN]` in ET.

Reason string format: `earnings_blackout:{ticker}@{date}/{hour|?}` —
used for `execution_intent` notes and logs.

### Integration in `paper/strategy.py`

Single call site, before opening any SMC paper entry:

```python
blocked, reason = in_earnings_blackout(self._storage, signal.ticker, signal.ts)
if blocked:
    log.info("paper skip entry: %s", reason)
    await self._signal_router.on_execution_intent(
        signal, mode="paper", status="rejected", note=reason,
    )
    return
```

## 8. Reaction Backfill Job

Run by `scheduler.py` every 5 minutes:

```python
async def backfill_earnings_reactions(storage, pricing):
    now = datetime.now(timezone.utc)
    rows = storage.list_earnings(status="published_pending_reaction")
    for row in rows:
        elapsed = now - parse(row["detected_publish_at"])
        if elapsed < timedelta(minutes=config.EARNINGS_REACTION_BACKFILL_DELAY_MIN):
            continue
        mark_now = pricing.last_price(row["ticker"])
        mark_pub = pricing.price_at_or_before(row["ticker"], row["detected_publish_at"])
        if (mark_now is None or mark_pub is None) and elapsed < timedelta(
            hours=config.EARNINGS_REACTION_BACKFILL_TIMEOUT_HOURS
        ):
            continue                     # try again next sweep
        reaction = (
            (mark_now - mark_pub) / mark_pub
            if mark_now is not None and mark_pub is not None and mark_pub > 0
            else None
        )
        storage.update_earnings_reaction(row["id"], reaction)
        storage.update_event_summary(row["published_event_id"], _format_summary(row, reaction))
        storage.set_status(row["id"], "reacted")
```

**Pricing source:** `paper/pricing.py` (existing IBKR-backed cache).
No fallback to yfinance — unreliable data is worse than NULL.

**Crash safety:** state lives entirely in `earnings_calendar`. After
restart the next sweep picks up where the previous one left off.

## 9. Configuration

Added to `config.py` and `.env.example`:

```python
EARNINGS_BLACKOUT_ENABLED = os.getenv("EARNINGS_BLACKOUT_ENABLED", "1") == "1"
EARNINGS_BLACKOUT_BEFORE_MIN = int(os.getenv("EARNINGS_BLACKOUT_BEFORE_MIN", "990"))   # 16h30m — covers ET-day for AMC
EARNINGS_BLACKOUT_AFTER_MIN  = int(os.getenv("EARNINGS_BLACKOUT_AFTER_MIN",  "1080"))  # 18 h — covers next pre-market
EARNINGS_SURPRISE_HIGH_PCT = float(os.getenv("EARNINGS_SURPRISE_HIGH_PCT", "0.05"))    # 5 %
EARNINGS_REACTION_BACKFILL_DELAY_MIN = int(
    os.getenv("EARNINGS_REACTION_BACKFILL_DELAY_MIN", "30")
)
EARNINGS_REACTION_BACKFILL_TIMEOUT_HOURS = int(
    os.getenv("EARNINGS_REACTION_BACKFILL_TIMEOUT_HOURS", "6")
)
```

Default windows expanded by hour-anchor:

| `scheduled_hour` | Anchor ET | Blackout window (ET) |
|---|---|---|
| amc | 16:30 | 00:00 same day → 10:30 next day (full ET day + next pre-market) |
| bmo | 09:00 | 16:30 prev day → 03:00 next day (covers pre-market + after-hours of report day) |
| dmh | 12:00 | 19:30 prev day → 06:00 next day |

## 10. Error Handling

| Scenario | Behavior |
|---|---|
| Finnhub returns 4xx repeatedly | `earnings` SourceHealth disables the sub-fetch; existing rows in `scheduled` remain queryable for the gate; backfill keeps working on already-published rows. |
| `epsActual` populated but `epsEstimate` missing | `surprise_pct = NULL`; importance = medium. |
| `epsEstimate == 0` | `surprise_pct = NULL` (avoid division by zero). |
| IBKR / pricing offline at backfill time | Skip; retry every 5 min for up to `EARNINGS_REACTION_BACKFILL_TIMEOUT_HOURS`, then NULL + status=`reacted`. |
| Same row re-detected in `published_pending_reaction` | No-op; transition is one-way. |
| Finnhub revises actual after we've published | Ignored. Logged at debug only. |
| Daily stale sweep runs before backfill | Stale only matches `status='scheduled'`; published-pending rows are immune. |

## 11. Testing Plan

### New test files

- `tests/test_earnings_calendar_storage.py` — upsert / unique
  constraint / status transitions / range queries / stale sweep.
- `tests/test_earnings_gate.py` — every hour anchor (bmo/amc/dmh/NULL),
  ET/UTC boundary, disabled flag, stale rows ignored, reason string
  format, window endpoint inclusivity.
- `tests/test_earnings_reaction_backfill.py` — pre-delay skip, normal
  late-write, no-pricing skip-then-force, status filter, summary format.

### Extended

- `tests/test_finnhub.py` — bootstrap-quiet, scheduled→published emits
  with correct importance, estimate-only updates do not change status,
  health-disabled short-circuits the calendar branch.
- `tests/test_paper_strategy.py` — entry rejected during blackout +
  emits `execution_intent` rejected; entry proceeds outside blackout.
- `tests/test_event_scorer.py` — three cases for `earnings_published`
  importance (high / medium / unknown).

### Coverage targets

- All state paths: bootstrap insert→reacted (no event), scheduled→
  published, published→reacted (with reaction), published→reacted
  (NULL after timeout), scheduled→stale.
- All 3 `scheduled_hour` values + NULL fallback.
- At least one ET/UTC boundary case.
- Failure paths: pricing unavailable, Finnhub partial outage.

## 12. Out of Scope (for sub-project A)

- Frontend rendering of upcoming earnings or reaction snapshots →
  sub-project C.
- Earnings transcript / call audio → not planned.
- Guidance text extraction from press releases → not planned.
- Live trading hooks (only paper is gated) → already gated by existing
  `EXECUTION_MODE` controls; live remains explicitly disabled.

## 13. Open Risks

| Risk | Mitigation |
|---|---|
| Finnhub free tier rate-limits on heavy watchlists | Existing `SourceHealth` 429 handling treats this as transient; calendar polling cadence stays at 5 min. |
| Same-day double earnings (rare: re-state) | `UNIQUE(ticker, scheduled_date)` collapses them; we lose the second event but log it. |
| ET DST transitions mid-blackout | `zoneinfo` handles DST natively; tested with one boundary case. |
| Bootstrap quiet period hides a real recent miss | Acceptable. Operator can manually inspect `earnings_calendar` if needed. |

## 14. Acceptance Criteria

- An `earnings_published` event appears in the events feed within ≤ 10
  minutes of Finnhub populating `epsActual`, with correct importance.
- 30 minutes after publish, the event's summary contains the reaction %
  (or remains stable without reaction text if pricing unavailable for
  6 h+).
- A paper SMC entry for ticker T at time `ts` is blocked iff there is
  a non-stale row in `earnings_calendar` whose anchor falls within
  `[ts − BEFORE, ts + AFTER]`.
- Blocked entries appear as `execution_intent` rejected events with a
  reason string identifying the offending earnings row.
- `pytest -x -q` passes, including the new and extended files listed
  in §11.
