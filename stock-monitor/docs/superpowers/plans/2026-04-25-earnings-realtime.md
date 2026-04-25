# Earnings Realtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface real EPS / revenue / surprise / +30m reaction for published earnings, and gate SMC paper entries with a configurable blackout window — per [`docs/superpowers/specs/2026-04-25-earnings-realtime-design.md`](../specs/2026-04-25-earnings-realtime-design.md).

**Architecture:** New `earnings_calendar` table holds the lifecycle (scheduled → published_pending_reaction → reacted | stale). Finnhub source upserts rows and emits `earnings_published` events on the scheduled→published transition. A scheduler-driven backfill job writes the +30m price reaction. A single `paper/earnings_gate.py` function blocks SMC entries inside the configured window.

**Tech Stack:** Python 3.11+, SQLite (project's existing `Storage` wrapper), httpx (existing), APScheduler (existing), pytest with `asyncio_mode=auto`.

**Spec deviations to track:**
1. Spec §8 references `pricing.price_at_or_before(...)` — replaced by snapshotting the price into `earnings_calendar.mark_at_publish_price` at transition time. Adds one column. Reason: existing `PriceBook` has no historical lookup; snapshot-at-transition is simpler and equivalent.
2. Spec §6 says scheduled `earnings` event becomes `low` importance. **Plan preserves the current `high` importance** to avoid silently demoting an already-shipping notification. Only the new `earnings_published` event uses the tiered rule.

---

## File Structure

**Created:**
- `paper/earnings_gate.py` — single blackout gate function
- `paper/earnings_reaction.py` — backfill job (kept in `paper/` since it depends on `PriceBook`)
- `tests/test_earnings_calendar_storage.py`
- `tests/test_earnings_gate.py`
- `tests/test_earnings_reaction_backfill.py`

**Modified:**
- `storage.py` — schema + earnings methods
- `config.py` — 6 new env vars
- `event_scorer.py` — `earnings_published` scoring
- `sources/finnhub.py` — calendar-aware earnings flow
- `paper/broker.py` — earnings-gate call in `on_smc_signal` and `_fill_pending_entry`
- `app.py` — wire storage into FinnhubSource
- `scheduler.py` — register backfill + stale-sweep jobs
- `web/routes.py` — `GET /api/earnings/upcoming`
- `.env.example` — document new vars
- `tests/test_finnhub.py` — new test cases
- `tests/test_paper_broker.py` — new test cases
- `tests/test_scorer.py` — new test cases (note: existing file is named `test_scorer.py`, not `test_event_scorer.py`)

---

## Task 1: Storage schema for `earnings_calendar`

**Files:**
- Modify: `storage.py` (SCHEMA constant + `init_schema`)
- Test: `tests/test_earnings_calendar_storage.py` (new)

- [ ] **Step 1: Write the failing test for schema creation**

Create `tests/test_earnings_calendar_storage.py`:

```python
from storage import Storage


def _storage(tmp_path):
    s = Storage(str(tmp_path / "test.db"))
    s.init_schema()
    return s


def test_earnings_calendar_table_created(tmp_path):
    s = _storage(tmp_path)
    cur = s._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='earnings_calendar'"
    )
    assert cur.fetchone() is not None


def test_earnings_calendar_has_required_columns(tmp_path):
    s = _storage(tmp_path)
    cols = {r["name"] for r in s._conn.execute("PRAGMA table_info(earnings_calendar)").fetchall()}
    expected = {
        "id", "ticker", "scheduled_date", "scheduled_hour",
        "eps_estimate", "eps_actual", "rev_estimate", "rev_actual",
        "surprise_pct", "reaction_pct_30m", "mark_at_publish_price",
        "status", "published_event_id", "detected_publish_at", "updated_at",
    }
    assert expected.issubset(cols)


def test_earnings_calendar_unique_ticker_date(tmp_path):
    import sqlite3
    s = _storage(tmp_path)
    s._conn.execute(
        "INSERT INTO earnings_calendar (ticker, scheduled_date, status, updated_at) "
        "VALUES (?, ?, 'scheduled', '2026-04-25T00:00:00+00:00')",
        ("AAPL", "2026-04-30"),
    )
    s._conn.commit()
    try:
        s._conn.execute(
            "INSERT INTO earnings_calendar (ticker, scheduled_date, status, updated_at) "
            "VALUES (?, ?, 'scheduled', '2026-04-25T00:00:00+00:00')",
            ("AAPL", "2026-04-30"),
        )
        s._conn.commit()
        assert False, "expected IntegrityError"
    except sqlite3.IntegrityError:
        pass
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_earnings_calendar_storage.py -v
```
Expected: FAIL — table does not exist.

- [ ] **Step 3: Add the table to SCHEMA**

In `storage.py`, append to the `SCHEMA` constant (before the closing `"""`):

```sql

CREATE TABLE IF NOT EXISTS earnings_calendar (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    scheduled_date TEXT NOT NULL,
    scheduled_hour TEXT,
    eps_estimate REAL,
    eps_actual REAL,
    rev_estimate REAL,
    rev_actual REAL,
    surprise_pct REAL,
    reaction_pct_30m REAL,
    mark_at_publish_price REAL,
    status TEXT NOT NULL,
    published_event_id INTEGER,
    detected_publish_at TIMESTAMP,
    updated_at TIMESTAMP NOT NULL,
    UNIQUE(ticker, scheduled_date)
);
CREATE INDEX IF NOT EXISTS idx_earnings_status_date ON earnings_calendar(status, scheduled_date);
CREATE INDEX IF NOT EXISTS idx_earnings_ticker_date ON earnings_calendar(ticker, scheduled_date);
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_earnings_calendar_storage.py -v
```
Expected: PASS.

- [ ] **Step 5: Run full suite to make sure nothing broke**

```bash
pytest -x -q
```
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add storage.py tests/test_earnings_calendar_storage.py
git commit -m "feat(storage): add earnings_calendar table"
```

---

## Task 2: Storage methods — upsert / get / range query

**Files:**
- Modify: `storage.py` — add methods
- Test: `tests/test_earnings_calendar_storage.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_earnings_calendar_storage.py`:

```python
from datetime import datetime, timezone


def test_upsert_earnings_inserts_new_row(tmp_path):
    s = _storage(tmp_path)
    now = datetime(2026, 4, 25, 12, 0, tzinfo=timezone.utc)
    s.upsert_earnings(
        ticker="AAPL", scheduled_date="2026-04-30", scheduled_hour="amc",
        eps_estimate=1.42, eps_actual=None,
        rev_estimate=120e9, rev_actual=None,
        status="scheduled", updated_at=now,
    )
    row = s.get_earnings("AAPL", "2026-04-30")
    assert row is not None
    assert row["ticker"] == "AAPL"
    assert row["scheduled_hour"] == "amc"
    assert row["eps_estimate"] == 1.42
    assert row["eps_actual"] is None
    assert row["status"] == "scheduled"


def test_upsert_earnings_updates_estimates_in_place(tmp_path):
    s = _storage(tmp_path)
    now = datetime(2026, 4, 25, 12, 0, tzinfo=timezone.utc)
    s.upsert_earnings(
        ticker="AAPL", scheduled_date="2026-04-30", scheduled_hour="amc",
        eps_estimate=1.42, eps_actual=None, rev_estimate=120e9, rev_actual=None,
        status="scheduled", updated_at=now,
    )
    later = datetime(2026, 4, 26, 0, 0, tzinfo=timezone.utc)
    s.upsert_earnings(
        ticker="AAPL", scheduled_date="2026-04-30", scheduled_hour="amc",
        eps_estimate=1.45, eps_actual=None, rev_estimate=121e9, rev_actual=None,
        status="scheduled", updated_at=later,
    )
    row = s.get_earnings("AAPL", "2026-04-30")
    assert row["eps_estimate"] == 1.45
    assert row["rev_estimate"] == 121e9


def test_get_earnings_missing_returns_none(tmp_path):
    s = _storage(tmp_path)
    assert s.get_earnings("NONE", "2026-04-30") is None


def test_find_earnings_in_range_filters_ticker_and_date(tmp_path):
    s = _storage(tmp_path)
    now = datetime(2026, 4, 25, 0, 0, tzinfo=timezone.utc)
    for date in ("2026-04-28", "2026-04-30", "2026-05-05"):
        s.upsert_earnings(
            ticker="AAPL", scheduled_date=date, scheduled_hour="amc",
            eps_estimate=1.0, eps_actual=None, rev_estimate=1.0, rev_actual=None,
            status="scheduled", updated_at=now,
        )
    s.upsert_earnings(
        ticker="MSFT", scheduled_date="2026-04-30", scheduled_hour="amc",
        eps_estimate=1.0, eps_actual=None, rev_estimate=1.0, rev_actual=None,
        status="scheduled", updated_at=now,
    )
    rows = s.find_earnings_in_range("AAPL", "2026-04-29", "2026-05-01")
    dates = sorted(r["scheduled_date"] for r in rows)
    assert dates == ["2026-04-30"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_earnings_calendar_storage.py -v
```
Expected: FAIL — methods do not exist.

- [ ] **Step 3: Implement the methods**

Add to `storage.py` (after the existing earnings/event methods, e.g. after `query_since`):

```python
    def upsert_earnings(
        self,
        *,
        ticker: str,
        scheduled_date: str,
        scheduled_hour: str | None,
        eps_estimate: float | None,
        eps_actual: float | None,
        rev_estimate: float | None,
        rev_actual: float | None,
        status: str,
        updated_at: datetime,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO earnings_calendar
                (ticker, scheduled_date, scheduled_hour,
                 eps_estimate, eps_actual, rev_estimate, rev_actual,
                 status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker, scheduled_date) DO UPDATE SET
                scheduled_hour = excluded.scheduled_hour,
                eps_estimate   = excluded.eps_estimate,
                rev_estimate   = excluded.rev_estimate,
                updated_at     = excluded.updated_at
            """,
            (
                ticker, scheduled_date, scheduled_hour,
                eps_estimate, eps_actual, rev_estimate, rev_actual,
                status, updated_at.isoformat(),
            ),
        )
        self._conn.commit()

    def get_earnings(self, ticker: str, scheduled_date: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM earnings_calendar WHERE ticker=? AND scheduled_date=?",
            (ticker, scheduled_date),
        ).fetchone()
        return dict(row) if row is not None else None

    def find_earnings_in_range(
        self, ticker: str, date_from: str, date_to: str,
    ) -> list[dict]:
        rows = self._conn.execute(
            """SELECT * FROM earnings_calendar
               WHERE ticker = ? AND scheduled_date BETWEEN ? AND ?
               ORDER BY scheduled_date ASC""",
            (ticker, date_from, date_to),
        ).fetchall()
        return [dict(r) for r in rows]
```

Note: the upsert intentionally does NOT update `eps_actual`, `rev_actual`, or `status` on conflict — those transitions are handled by `transition_to_published` (Task 3) and `set_earnings_status` (Task 3) so semantics stay clear.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_earnings_calendar_storage.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add storage.py tests/test_earnings_calendar_storage.py
git commit -m "feat(storage): upsert/get/range methods for earnings calendar"
```

---

## Task 3: Storage methods — transitions and event-summary update

**Files:**
- Modify: `storage.py`
- Test: `tests/test_earnings_calendar_storage.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_earnings_calendar_storage.py`:

```python
from datetime import datetime, timezone

from sources.base import Event


def _seed_scheduled(s, ticker="AAPL", date="2026-04-30"):
    now = datetime(2026, 4, 25, 0, 0, tzinfo=timezone.utc)
    s.upsert_earnings(
        ticker=ticker, scheduled_date=date, scheduled_hour="amc",
        eps_estimate=1.42, eps_actual=None,
        rev_estimate=120e9, rev_actual=None,
        status="scheduled", updated_at=now,
    )
    return s.get_earnings(ticker, date)


def test_transition_to_published_sets_actuals_and_surprise(tmp_path):
    s = _storage(tmp_path)
    _seed_scheduled(s)
    detected = datetime(2026, 4, 30, 20, 5, tzinfo=timezone.utc)
    s.transition_to_published(
        ticker="AAPL", scheduled_date="2026-04-30",
        eps_actual=1.50, rev_actual=125e9,
        surprise_pct=(1.50 - 1.42) / abs(1.42),
        mark_at_publish_price=187.4,
        detected_publish_at=detected,
    )
    row = s.get_earnings("AAPL", "2026-04-30")
    assert row["status"] == "published_pending_reaction"
    assert row["eps_actual"] == 1.50
    assert row["rev_actual"] == 125e9
    assert abs(row["surprise_pct"] - 0.0563) < 0.001
    assert row["mark_at_publish_price"] == 187.4
    assert row["detected_publish_at"] is not None


def test_set_published_event_id_links_event(tmp_path):
    s = _storage(tmp_path)
    _seed_scheduled(s)
    s.transition_to_published(
        ticker="AAPL", scheduled_date="2026-04-30",
        eps_actual=1.50, rev_actual=None, surprise_pct=None,
        mark_at_publish_price=None,
        detected_publish_at=datetime(2026, 4, 30, 20, 5, tzinfo=timezone.utc),
    )
    s.set_published_event_id("AAPL", "2026-04-30", 999)
    row = s.get_earnings("AAPL", "2026-04-30")
    assert row["published_event_id"] == 999


def test_update_earnings_reaction_writes_pct(tmp_path):
    s = _storage(tmp_path)
    _seed_scheduled(s)
    s.transition_to_published(
        ticker="AAPL", scheduled_date="2026-04-30",
        eps_actual=1.50, rev_actual=None, surprise_pct=None,
        mark_at_publish_price=100.0,
        detected_publish_at=datetime(2026, 4, 30, 20, 5, tzinfo=timezone.utc),
    )
    row_id = s.get_earnings("AAPL", "2026-04-30")["id"]
    s.update_earnings_reaction(row_id, 0.0321)
    row = s.get_earnings("AAPL", "2026-04-30")
    assert abs(row["reaction_pct_30m"] - 0.0321) < 1e-6


def test_update_earnings_reaction_accepts_none(tmp_path):
    s = _storage(tmp_path)
    _seed_scheduled(s)
    s.transition_to_published(
        ticker="AAPL", scheduled_date="2026-04-30",
        eps_actual=1.50, rev_actual=None, surprise_pct=None,
        mark_at_publish_price=None,
        detected_publish_at=datetime(2026, 4, 30, 20, 5, tzinfo=timezone.utc),
    )
    row_id = s.get_earnings("AAPL", "2026-04-30")["id"]
    s.update_earnings_reaction(row_id, None)
    row = s.get_earnings("AAPL", "2026-04-30")
    assert row["reaction_pct_30m"] is None


def test_set_earnings_status_terminal(tmp_path):
    s = _storage(tmp_path)
    _seed_scheduled(s)
    row_id = s.get_earnings("AAPL", "2026-04-30")["id"]
    s.set_earnings_status(row_id, "stale")
    assert s.get_earnings("AAPL", "2026-04-30")["status"] == "stale"


def test_list_earnings_by_status(tmp_path):
    s = _storage(tmp_path)
    _seed_scheduled(s, ticker="AAPL", date="2026-04-30")
    _seed_scheduled(s, ticker="MSFT", date="2026-04-30")
    s.transition_to_published(
        ticker="AAPL", scheduled_date="2026-04-30",
        eps_actual=1.50, rev_actual=None, surprise_pct=None,
        mark_at_publish_price=100.0,
        detected_publish_at=datetime(2026, 4, 30, 20, 5, tzinfo=timezone.utc),
    )
    pending = s.list_earnings_by_status("published_pending_reaction")
    assert len(pending) == 1
    assert pending[0]["ticker"] == "AAPL"


def test_mark_stale_scheduled_before_date(tmp_path):
    s = _storage(tmp_path)
    _seed_scheduled(s, ticker="OLD", date="2026-01-01")
    _seed_scheduled(s, ticker="NEW", date="2026-12-01")
    n = s.mark_stale_scheduled_before("2026-04-18")
    assert n == 1
    assert s.get_earnings("OLD", "2026-01-01")["status"] == "stale"
    assert s.get_earnings("NEW", "2026-12-01")["status"] == "scheduled"


def test_update_event_summary(tmp_path):
    s = _storage(tmp_path)
    ev = Event(
        source="finnhub", external_id="x-1", ticker="AAPL",
        event_type="earnings_published", title="t", summary="old",
        url=None,
        published_at=datetime(2026, 4, 30, 20, 5, tzinfo=timezone.utc),
        importance="high",
    )
    inserted, eid = s.insert_with_id(ev)
    assert inserted and eid is not None
    s.update_event_summary(eid, "new summary")
    row = s._conn.execute("SELECT summary FROM events WHERE id=?", (eid,)).fetchone()
    assert row["summary"] == "new summary"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_earnings_calendar_storage.py -v
```
Expected: FAIL — methods do not exist.

- [ ] **Step 3: Implement the methods**

Add to `storage.py`, immediately after the methods added in Task 2:

```python
    def transition_to_published(
        self,
        *,
        ticker: str,
        scheduled_date: str,
        eps_actual: float | None,
        rev_actual: float | None,
        surprise_pct: float | None,
        mark_at_publish_price: float | None,
        detected_publish_at: datetime,
    ) -> None:
        self._conn.execute(
            """UPDATE earnings_calendar
               SET status='published_pending_reaction',
                   eps_actual=?, rev_actual=?, surprise_pct=?,
                   mark_at_publish_price=?,
                   detected_publish_at=?, updated_at=?
               WHERE ticker=? AND scheduled_date=?""",
            (
                eps_actual, rev_actual, surprise_pct,
                mark_at_publish_price,
                detected_publish_at.isoformat(),
                detected_publish_at.isoformat(),
                ticker, scheduled_date,
            ),
        )
        self._conn.commit()

    def set_published_event_id(self, ticker: str, scheduled_date: str, event_id: int) -> None:
        self._conn.execute(
            "UPDATE earnings_calendar SET published_event_id=? WHERE ticker=? AND scheduled_date=?",
            (event_id, ticker, scheduled_date),
        )
        self._conn.commit()

    def update_earnings_reaction(self, row_id: int, reaction_pct: float | None) -> None:
        self._conn.execute(
            "UPDATE earnings_calendar SET reaction_pct_30m=? WHERE id=?",
            (reaction_pct, row_id),
        )
        self._conn.commit()

    def set_earnings_status(self, row_id: int, status: str) -> None:
        self._conn.execute(
            "UPDATE earnings_calendar SET status=? WHERE id=?",
            (status, row_id),
        )
        self._conn.commit()

    def list_earnings_by_status(self, status: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM earnings_calendar WHERE status=? ORDER BY scheduled_date ASC",
            (status,),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_stale_scheduled_before(self, before_date: str) -> int:
        cur = self._conn.execute(
            """UPDATE earnings_calendar
               SET status='stale'
               WHERE status='scheduled' AND scheduled_date < ?""",
            (before_date,),
        )
        self._conn.commit()
        return cur.rowcount

    def update_event_summary(self, event_id: int, summary: str) -> None:
        """Mutate the summary column of a single events row.

        This is the sole append-only exception in the events table — used by
        the earnings reaction backfill to enrich a published event 30 minutes
        after the fact. Identified by id only; raw and other fields are
        untouched.
        """
        self._conn.execute(
            "UPDATE events SET summary=? WHERE id=?",
            (summary, event_id),
        )
        self._conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_earnings_calendar_storage.py -v
```
Expected: all pass.

- [ ] **Step 5: Run full suite**

```bash
pytest -x -q
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add storage.py tests/test_earnings_calendar_storage.py
git commit -m "feat(storage): earnings transitions, status, stale sweep, event summary update"
```

---

## Task 4: Configuration variables

**Files:**
- Modify: `config.py`

- [ ] **Step 1: Add the env vars**

Append to `config.py` (after the existing `# Paper broker` block):

```python

# Earnings calendar
EARNINGS_BLACKOUT_ENABLED = os.getenv("EARNINGS_BLACKOUT_ENABLED", "1") == "1"
EARNINGS_BLACKOUT_BEFORE_MIN = int(os.getenv("EARNINGS_BLACKOUT_BEFORE_MIN", "990"))   # 16h30m — covers ET-day for AMC
EARNINGS_BLACKOUT_AFTER_MIN = int(os.getenv("EARNINGS_BLACKOUT_AFTER_MIN", "1080"))    # 18h — covers next pre-market
EARNINGS_SURPRISE_HIGH_PCT = float(os.getenv("EARNINGS_SURPRISE_HIGH_PCT", "0.05"))    # 5%
EARNINGS_REACTION_BACKFILL_DELAY_MIN = int(os.getenv("EARNINGS_REACTION_BACKFILL_DELAY_MIN", "30"))
EARNINGS_REACTION_BACKFILL_TIMEOUT_HOURS = int(os.getenv("EARNINGS_REACTION_BACKFILL_TIMEOUT_HOURS", "6"))
EARNINGS_STALE_LOOKBACK_DAYS = int(os.getenv("EARNINGS_STALE_LOOKBACK_DAYS", "7"))
```

- [ ] **Step 2: Verify config imports cleanly**

```bash
python -c "import config; print(config.EARNINGS_BLACKOUT_BEFORE_MIN)"
```
Expected: `990`.

- [ ] **Step 3: Run full suite**

```bash
pytest -x -q
```
Expected: all pass (no new tests yet).

- [ ] **Step 4: Commit**

```bash
git add config.py
git commit -m "feat(config): earnings blackout and backfill knobs"
```

---

## Task 5: Event scorer — `earnings_published` tier

**Files:**
- Modify: `event_scorer.py`
- Test: `tests/test_scorer.py`

- [ ] **Step 1: Write failing tests**

Read the existing `tests/test_scorer.py` first to match its style, then append:

```python
from datetime import datetime, timezone

import config
from event_scorer import score
from sources.base import Event


def _ev(*, surprise=None, importance="low"):
    return Event(
        source="finnhub", external_id="x", ticker="AAPL",
        event_type="earnings_published",
        title="AAPL EPS", summary=f"surprise={surprise}",
        url=None,
        published_at=datetime(2026, 4, 30, 20, 5, tzinfo=timezone.utc),
        raw={"surprise_pct": surprise} if surprise is not None else {},
        importance=importance,
    )


def test_earnings_published_high_when_surprise_above_threshold():
    assert score(_ev(surprise=0.07)) == "high"


def test_earnings_published_high_when_negative_surprise_above_threshold():
    assert score(_ev(surprise=-0.08)) == "high"


def test_earnings_published_medium_when_surprise_below_threshold():
    assert score(_ev(surprise=0.02)) == "medium"


def test_earnings_published_medium_when_surprise_unknown():
    assert score(_ev(surprise=None)) == "medium"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_scorer.py -v
```
Expected: FAIL — `earnings_published` is not in the recognized types and falls through to `"low"`.

- [ ] **Step 3: Update the scorer**

Modify `event_scorer.py` to:

```python
from config import EARNINGS_SURPRISE_HIGH_PCT, HIGH_KEYWORDS
from sources.base import Event


def score(event: Event) -> str:
    if event.event_type == "earnings_published":
        surprise = event.raw.get("surprise_pct") if event.raw else None
        if surprise is not None and abs(surprise) >= EARNINGS_SURPRISE_HIGH_PCT:
            return "high"
        return "medium"
    if event.event_type in ("filing_8k", "earnings", "price_alert", "analyst", "insider"):
        return "high"
    if event.event_type == "news":
        text = (event.title + " " + (event.summary or "")).lower()
        if any(kw in text for kw in HIGH_KEYWORDS):
            return "high"
        return "medium"
    if event.event_type == "sentiment":
        return "medium"
    return "low"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_scorer.py -v
```
Expected: PASS.

- [ ] **Step 5: Run full suite**

```bash
pytest -x -q
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add event_scorer.py tests/test_scorer.py
git commit -m "feat(scorer): tiered importance for earnings_published events"
```

---

## Task 6: Earnings blackout gate

**Files:**
- Create: `paper/earnings_gate.py`
- Test: `tests/test_earnings_gate.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/test_earnings_gate.py`:

```python
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import config
from paper.earnings_gate import in_earnings_blackout
from storage import Storage

_ET = ZoneInfo("America/New_York")


def _storage(tmp_path):
    s = Storage(str(tmp_path / "test.db"))
    s.init_schema()
    return s


def _seed(s, *, ticker="AAPL", date, hour, status="scheduled"):
    s.upsert_earnings(
        ticker=ticker, scheduled_date=date, scheduled_hour=hour,
        eps_estimate=1.0, eps_actual=None, rev_estimate=1.0, rev_actual=None,
        status=status, updated_at=datetime(2026, 4, 25, 0, 0, tzinfo=timezone.utc),
    )


def test_disabled_returns_false(tmp_path, monkeypatch):
    s = _storage(tmp_path)
    _seed(s, date="2026-04-30", hour="amc")
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_ENABLED", False)
    ts = datetime(2026, 4, 30, 14, 0, tzinfo=_ET)
    blocked, reason = in_earnings_blackout(s, "AAPL", ts)
    assert blocked is False
    assert reason is None


def test_no_earnings_returns_false(tmp_path):
    s = _storage(tmp_path)
    ts = datetime(2026, 4, 30, 14, 0, tzinfo=_ET)
    blocked, reason = in_earnings_blackout(s, "AAPL", ts)
    assert blocked is False


def test_amc_blocks_same_day_afternoon(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_ENABLED", True)
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_BEFORE_MIN", 990)
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_AFTER_MIN", 1080)
    s = _storage(tmp_path)
    _seed(s, date="2026-04-30", hour="amc")
    ts = datetime(2026, 4, 30, 14, 0, tzinfo=_ET)   # before AMC anchor 16:30
    blocked, reason = in_earnings_blackout(s, "AAPL", ts)
    assert blocked is True
    assert "earnings_blackout:AAPL@2026-04-30/amc" in reason


def test_amc_blocks_next_day_premarket(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_ENABLED", True)
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_BEFORE_MIN", 990)
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_AFTER_MIN", 1080)
    s = _storage(tmp_path)
    _seed(s, date="2026-04-30", hour="amc")
    ts = datetime(2026, 5, 1, 8, 0, tzinfo=_ET)
    blocked, _ = in_earnings_blackout(s, "AAPL", ts)
    assert blocked is True


def test_amc_allows_two_days_later(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_ENABLED", True)
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_BEFORE_MIN", 990)
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_AFTER_MIN", 1080)
    s = _storage(tmp_path)
    _seed(s, date="2026-04-30", hour="amc")
    ts = datetime(2026, 5, 2, 11, 0, tzinfo=_ET)
    blocked, _ = in_earnings_blackout(s, "AAPL", ts)
    assert blocked is False


def test_bmo_blocks_premarket(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_ENABLED", True)
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_BEFORE_MIN", 990)
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_AFTER_MIN", 1080)
    s = _storage(tmp_path)
    _seed(s, date="2026-04-30", hour="bmo")
    ts = datetime(2026, 4, 30, 6, 0, tzinfo=_ET)
    blocked, _ = in_earnings_blackout(s, "AAPL", ts)
    assert blocked is True


def test_dmh_blocks_full_session(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_ENABLED", True)
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_BEFORE_MIN", 990)
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_AFTER_MIN", 1080)
    s = _storage(tmp_path)
    _seed(s, date="2026-04-30", hour="dmh")
    ts = datetime(2026, 4, 30, 13, 0, tzinfo=_ET)
    blocked, _ = in_earnings_blackout(s, "AAPL", ts)
    assert blocked is True


def test_stale_status_does_not_block(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_ENABLED", True)
    s = _storage(tmp_path)
    _seed(s, date="2026-04-30", hour="amc", status="stale")
    ts = datetime(2026, 4, 30, 14, 0, tzinfo=_ET)
    blocked, _ = in_earnings_blackout(s, "AAPL", ts)
    assert blocked is False


def test_unknown_hour_falls_back_to_amc(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_ENABLED", True)
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_BEFORE_MIN", 990)
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_AFTER_MIN", 1080)
    s = _storage(tmp_path)
    _seed(s, date="2026-04-30", hour=None)
    ts = datetime(2026, 4, 30, 14, 0, tzinfo=_ET)
    blocked, reason = in_earnings_blackout(s, "AAPL", ts)
    assert blocked is True
    assert "?" in reason   # hour rendered as "?"


def test_utc_input_converted_to_et(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_ENABLED", True)
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_BEFORE_MIN", 990)
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_AFTER_MIN", 1080)
    s = _storage(tmp_path)
    _seed(s, date="2026-04-30", hour="amc")
    # 2026-04-30 18:00 UTC = 14:00 ET (DST in effect)
    ts_utc = datetime(2026, 4, 30, 18, 0, tzinfo=timezone.utc)
    blocked, _ = in_earnings_blackout(s, "AAPL", ts_utc)
    assert blocked is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_earnings_gate.py -v
```
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the gate**

Create `paper/earnings_gate.py`:

```python
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

    # Conservative date window: anchor could be up to (BEFORE+AFTER) minutes
    # away from ts on either side; padding ±2 days is plenty given default
    # ~18 h windows.
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_earnings_gate.py -v
```
Expected: PASS.

- [ ] **Step 5: Run full suite**

```bash
pytest -x -q
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add paper/earnings_gate.py tests/test_earnings_gate.py
git commit -m "feat(paper): earnings blackout gate"
```

---

## Task 7: PaperBroker integration with the gate

**Files:**
- Modify: `paper/ledger.py` — expose a public `storage` property
- Modify: `paper/broker.py` — call the gate in `on_smc_signal` and `_fill_pending_entry`
- Test: `tests/test_paper_broker.py`

The broker already has `self._ledger`. Rather than thread `storage` through a new constructor kwarg (which would touch every test), expose `Ledger.storage` as a public property and let the broker reach `self._ledger.storage`.

- [ ] **Step 1: Expose storage on Ledger**

In `paper/ledger.py`, just below `__init__`, add:

```python
    @property
    def storage(self):
        return self._storage
```

(Find the right insertion point by scanning for the existing `def positions(self)` method — put the property right above it.)

- [ ] **Step 2: Write failing tests**

Read the top of `tests/test_paper_broker.py` so the new tests match its style (no `pytest.mark.asyncio` needed because of `asyncio_mode = auto`). Append:

```python
import config
from paper.broker import PaperBroker
from paper.ledger import Ledger
from paper.pricing import PriceBook
from paper.strategy import SmcLongStrategy
from smc.types import SmcSignal


def _signal_at(ts):
    return SmcSignal(ts=ts, ticker="AAPL", entry=100.0, sl=99.0, tp=102.0, reason="smc_bos_ob")


async def test_on_smc_signal_blocked_by_earnings_blackout(monkeypatch):
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_ENABLED", True)
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_BEFORE_MIN", 990)
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_AFTER_MIN", 1080)
    storage = _storage()
    storage.upsert_earnings(
        ticker="AAPL", scheduled_date="2026-04-30", scheduled_hour="amc",
        eps_estimate=1.0, eps_actual=None, rev_estimate=1.0, rev_actual=None,
        status="scheduled",
        updated_at=datetime(2026, 4, 25, 0, 0, tzinfo=timezone.utc),
    )
    broker = PaperBroker(
        ledger=Ledger(storage),
        strategy=SmcLongStrategy(),
        prices=PriceBook(),
        max_hold_min=60,
        slippage_bps=0.0,
        commission_per_share=0.0,
        commission_min=0.0,
    )
    ts = datetime(2026, 4, 30, 18, 0, tzinfo=timezone.utc)   # 14:00 ET, inside AMC blackout
    sig = _signal_at(ts)
    result = await broker.on_smc_signal(sig, signal_id=1)
    assert result is None
    assert "AAPL" not in broker._pending_entries


async def test_on_smc_signal_proceeds_when_no_earnings(monkeypatch):
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_ENABLED", True)
    storage = _storage()
    broker = PaperBroker(
        ledger=Ledger(storage),
        strategy=SmcLongStrategy(),
        prices=PriceBook(),
        max_hold_min=60,
        slippage_bps=0.0,
        commission_per_share=0.0,
        commission_min=0.0,
    )
    ts = datetime(2026, 4, 30, 18, 0, tzinfo=timezone.utc)
    result = await broker.on_smc_signal(_signal_at(ts), signal_id=1)
    assert result is not None
    assert result["status"] == "queued"
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/test_paper_broker.py -v -k "earnings"
```
Expected: FAIL — gate not wired in.

- [ ] **Step 4: Wire the gate into PaperBroker**

In `paper/broker.py`:

1. Add import at top:
```python
from paper.earnings_gate import in_earnings_blackout
```

2. In `on_smc_signal`, **after** the existing `_check_risk_gate(...)` block and **before** the `self._pending_entries[signal.ticker] = ...` line, add:
```python
        blocked, reason = in_earnings_blackout(
            self._ledger.storage, signal.ticker, signal.ts
        )
        if blocked:
            log.info("paper signal for %s blocked by earnings: %s", signal.ticker, reason)
            return None
```

3. In `_fill_pending_entry`, immediately after the existing risk-gate block and before computing `qty`, add:
```python
        blocked, reason = in_earnings_blackout(
            self._ledger.storage, signal.ticker, ts
        )
        if blocked:
            log.info("paper pending entry for %s canceled by earnings: %s", signal.ticker, reason)
            self._pending_entries.pop(ticker, None)
            return None
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_paper_broker.py -v -k "earnings"
```
Expected: PASS.

- [ ] **Step 6: Run full suite**

```bash
pytest -x -q
```
Expected: all pass — no other test should break since the gate returns False (allow) when there are no earnings rows.

- [ ] **Step 7: Commit**

```bash
git add paper/ledger.py paper/broker.py tests/test_paper_broker.py
git commit -m "feat(paper): block SMC entries during earnings blackout"
```

---

## Task 8: Finnhub source — calendar-aware earnings flow

**Files:**
- Modify: `sources/finnhub.py`
- Modify: `app.py` (pass storage into FinnhubSource)
- Test: `tests/test_finnhub.py`

- [ ] **Step 1: Write failing tests**

Read `tests/test_finnhub.py` to learn its mocking pattern. The existing tests mock `_get` directly. Add tests that exercise three scenarios:

```python
@pytest.mark.asyncio
async def test_earnings_first_seen_with_actual_lands_in_reacted_no_event(monkeypatch, tmp_path):
    """Bootstrap quiet period: first poll sees epsActual already populated."""
    storage = Storage(str(tmp_path / "test.db"))
    storage.init_schema()
    src = FinnhubSource(api_key="x", enable_news=False, storage=storage)

    async def fake_get(path, params):
        if path == "/calendar/earnings":
            return {"earningsCalendar": [{
                "symbol": "AAPL", "date": "2026-04-25", "hour": "amc",
                "epsEstimate": 1.40, "epsActual": 1.50,
                "revenueEstimate": 100e9, "revenueActual": 105e9,
            }]}
        return None
    monkeypatch.setattr(src, "_get", fake_get)

    events = await src.fetch(["AAPL"])
    types = [e.event_type for e in events]
    assert "earnings_published" not in types     # bootstrap: silent
    row = storage.get_earnings("AAPL", "2026-04-25")
    assert row["status"] == "reacted"
    assert row["eps_actual"] == 1.50


@pytest.mark.asyncio
async def test_earnings_scheduled_then_published_emits_event(monkeypatch, tmp_path):
    storage = Storage(str(tmp_path / "test.db"))
    storage.init_schema()
    src = FinnhubSource(api_key="x", enable_news=False, storage=storage)

    payload_scheduled = {"earningsCalendar": [{
        "symbol": "AAPL", "date": "2026-04-30", "hour": "amc",
        "epsEstimate": 1.42, "epsActual": None,
        "revenueEstimate": 120e9, "revenueActual": None,
    }]}
    payload_published = {"earningsCalendar": [{
        "symbol": "AAPL", "date": "2026-04-30", "hour": "amc",
        "epsEstimate": 1.42, "epsActual": 1.55,
        "revenueEstimate": 120e9, "revenueActual": 125e9,
    }]}
    state = {"call": 0}

    async def fake_get(path, params):
        if path != "/calendar/earnings":
            return None
        state["call"] += 1
        return payload_scheduled if state["call"] == 1 else payload_published
    monkeypatch.setattr(src, "_get", fake_get)

    first = await src.fetch(["AAPL"])
    assert any(e.event_type == "earnings" for e in first)
    second = await src.fetch(["AAPL"])
    pubs = [e for e in second if e.event_type == "earnings_published"]
    assert len(pubs) == 1
    assert pubs[0].raw["surprise_pct"] is not None
    assert abs(pubs[0].raw["surprise_pct"] - (1.55 - 1.42) / 1.42) < 1e-6
    row = storage.get_earnings("AAPL", "2026-04-30")
    assert row["status"] == "published_pending_reaction"


@pytest.mark.asyncio
async def test_earnings_estimate_only_change_does_not_change_status(monkeypatch, tmp_path):
    storage = Storage(str(tmp_path / "test.db"))
    storage.init_schema()
    src = FinnhubSource(api_key="x", enable_news=False, storage=storage)

    payloads = [
        {"earningsCalendar": [{
            "symbol": "AAPL", "date": "2026-04-30", "hour": "amc",
            "epsEstimate": 1.42, "epsActual": None,
            "revenueEstimate": 120e9, "revenueActual": None,
        }]},
        {"earningsCalendar": [{
            "symbol": "AAPL", "date": "2026-04-30", "hour": "amc",
            "epsEstimate": 1.45, "epsActual": None,         # estimate revised
            "revenueEstimate": 121e9, "revenueActual": None,
        }]},
    ]
    state = {"call": 0}

    async def fake_get(path, params):
        if path != "/calendar/earnings":
            return None
        state["call"] += 1
        return payloads[state["call"] - 1]
    monkeypatch.setattr(src, "_get", fake_get)

    await src.fetch(["AAPL"])
    await src.fetch(["AAPL"])
    row = storage.get_earnings("AAPL", "2026-04-30")
    assert row["status"] == "scheduled"
    assert row["eps_estimate"] == 1.45
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_finnhub.py -v -k earnings
```
Expected: FAIL.

- [ ] **Step 3: Update FinnhubSource**

In `sources/finnhub.py`:

1. Update constructor signature:
```python
def __init__(
    self,
    api_key: str,
    *,
    enable_news: bool = True,
    enable_earnings: bool = True,
    storage=None,
):
    self._api_key = api_key
    self._enable_news = enable_news
    self._enable_earnings = enable_earnings
    self._storage = storage
    # ...existing health setup
```

2. Replace `_parse_earnings` with the new flow. Delete the old method body and add:

```python
def _on_earnings_row(self, item: dict, ticker: str) -> Event | None:
    """Upsert into earnings_calendar and emit the right event.

    Returns the Event to publish (or None for noise / bootstrap rows).
    """
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

    # Build the title used by both event types — same shape as before for the
    # scheduled case, slightly enriched for published.
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
        # First time we see this row.
        if eps_actual is None:
            # Pure scheduled — emit the existing earnings event.
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

    # Row exists. Two cases: estimate-only change, or scheduled→published.
    if existing["status"] == "scheduled" and eps_actual is not None:
        surprise = None
        if eps_estimate not in (None, 0) and eps_actual is not None:
            surprise = (eps_actual - eps_estimate) / abs(eps_estimate)
        # mark_at_publish_price is filled by the reaction job from PriceBook
        # at the moment of detection — see Task 9. We pass None here.
        self._storage.transition_to_published(
            ticker=ticker, scheduled_date=date_str,
            eps_actual=eps_actual, rev_actual=rev_actual,
            surprise_pct=surprise,
            mark_at_publish_price=None,
            detected_publish_at=now,
        )
        title = f"{ticker} 财报已公布 {date_str}"
        if hour_label:
            title += f" {hour_label}"
        summary_bits = [
            f"EPS {eps_actual:.2f} vs {eps_estimate:.2f}" if eps_estimate is not None else f"EPS {eps_actual:.2f}",
        ]
        if surprise is not None:
            summary_bits.append(f"({surprise:+.1%})")
        if rev_actual is not None and rev_estimate is not None:
            summary_bits.append(f"营收 {rev_actual/1e9:.2f}B vs {rev_estimate/1e9:.2f}B")
        summary = "; ".join(summary_bits)
        return Event(
            source=self.name,
            external_id=f"{ticker}-earnings-published-{date_str}",
            ticker=ticker, event_type="earnings_published", title=title,
            summary=summary, url=None, published_at=now,
            raw={**item, "surprise_pct": surprise},
        )

    # Otherwise (already published or terminal): only refresh estimates.
    if existing["status"] == "scheduled":
        self._storage.upsert_earnings(
            ticker=ticker, scheduled_date=date_str, scheduled_hour=hour,
            eps_estimate=eps_estimate, eps_actual=None,
            rev_estimate=rev_estimate, rev_actual=None,
            status="scheduled", updated_at=now,
        )
    return None
```

3. Replace the call site in `fetch()`:
```python
for item in (data or {}).get("earningsCalendar") or []:
    ev = self._on_earnings_row(item, ticker)
    if ev:
        events.append(ev)
```

4. After the source is wired into `Pipeline`, the published event flows through the existing insert path. Pipeline's `insert_with_id` returns the event id; we need that to back-link via `set_published_event_id`. Pipeline already swallows it. To avoid changing Pipeline, do the back-link inside the source: after building the event, also remember the (ticker, date) → event so storage gets the id later.

   Simplest: have `Pipeline` look up by `(source, external_id)` after insertion, OR in this source after Pipeline inserts (we don't run yet), so we'll **wire the link from the source by inspecting storage post-insert** in the same `fetch` pass. Add at the end of `fetch()` (after returning events would not work — do it inline before yielding):

   Actually, the cleanest hook is: after the published event is inserted by Pipeline, Pipeline already calls `_serialize_event` and notifier. We can either:

   - Option A: in `_on_earnings_row`, immediately after building the event, **insert it into storage ourselves** (calling `storage.insert_with_id`) and call `set_published_event_id`. This duplicates Pipeline's insert. Pipeline will then re-attempt insert and dedup on `(source, external_id)`, returning False with the same id — safe.
   - Option B: refactor Pipeline to give sources a callback.

   Pick **Option A**. Add inside the published branch of `_on_earnings_row`, after building the Event but before returning:

```python
        ev = Event(...)
        inserted, ev_id = self._storage.insert_with_id(ev)
        if ev_id is not None:
            self._storage.set_published_event_id(ticker, date_str, ev_id)
        return ev   # Pipeline will re-attempt insert and dedup harmlessly.
```

5. Update `app.py` where `FinnhubSource(...)` is instantiated to pass `storage=storage`.

- [ ] **Step 4: Run new tests to verify they pass**

```bash
pytest tests/test_finnhub.py -v -k earnings
```
Expected: PASS.

- [ ] **Step 5: Run full suite**

```bash
pytest -x -q
```
Expected: all pass. The pre-existing earnings tests in `test_finnhub.py` should still pass because the storage-less branch preserves the old behavior.

- [ ] **Step 6: Commit**

```bash
git add sources/finnhub.py app.py tests/test_finnhub.py
git commit -m "feat(finnhub): emit earnings_published on actual results, persist calendar"
```

---

## Task 9: Reaction backfill job

**Files:**
- Create: `paper/earnings_reaction.py`
- Modify: `sources/finnhub.py` (snapshot price at transition)
- Modify: `paper/broker.py` (expose `pricing` for the job; already an attribute, may need a getter)
- Test: `tests/test_earnings_reaction_backfill.py` (new)

- [ ] **Step 1: Snapshot price at transition**

The published event needs `mark_at_publish_price` set. Modify `sources/finnhub.py` `__init__` to also accept an optional `pricing` argument:

```python
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
    # ...existing health setup
```

Inside the published-transition branch in `_on_earnings_row`, replace the `mark_at_publish_price=None` with:

```python
        mark_at_publish = self._pricing.latest(ticker) if self._pricing is not None else None
        self._storage.transition_to_published(
            ...
            mark_at_publish_price=mark_at_publish,
            ...
        )
```

Update `app.py` to pass `pricing=paper_broker.pricing` (or whatever attribute exposes the `PriceBook`) into `FinnhubSource(...)`. If `pricing` is private (`_prices`), add a public property to `PaperBroker`:

```python
@property
def pricing(self):
    return self._prices
```

- [ ] **Step 2: Write failing tests**

Create `tests/test_earnings_reaction_backfill.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

import config
from paper.earnings_reaction import backfill_earnings_reactions
from paper.pricing import PriceBook
from sources.base import Event
from storage import Storage


def _seed_published_row(s, *, ticker="AAPL", mark_at_publish=100.0, detected_at=None):
    detected_at = detected_at or datetime(2026, 4, 30, 20, 5, tzinfo=timezone.utc)
    s.upsert_earnings(
        ticker=ticker, scheduled_date="2026-04-30", scheduled_hour="amc",
        eps_estimate=1.0, eps_actual=None, rev_estimate=1.0, rev_actual=None,
        status="scheduled", updated_at=detected_at,
    )
    s.transition_to_published(
        ticker=ticker, scheduled_date="2026-04-30",
        eps_actual=1.05, rev_actual=None,
        surprise_pct=0.05, mark_at_publish_price=mark_at_publish,
        detected_publish_at=detected_at,
    )
    ev = Event(
        source="finnhub", external_id=f"{ticker}-earnings-published-2026-04-30",
        ticker=ticker, event_type="earnings_published",
        title=f"{ticker} earnings", summary="initial",
        url=None, published_at=detected_at, raw={},
    )
    inserted, eid = s.insert_with_id(ev)
    s.set_published_event_id(ticker, "2026-04-30", eid)
    return s.get_earnings(ticker, "2026-04-30"), eid


@pytest.mark.asyncio
async def test_skips_rows_before_delay(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EARNINGS_REACTION_BACKFILL_DELAY_MIN", 30)
    s = Storage(str(tmp_path / "t.db")); s.init_schema()
    detected = datetime(2026, 4, 30, 20, 5, tzinfo=timezone.utc)
    _seed_published_row(s, detected_at=detected)
    pricing = PriceBook(); pricing.update("AAPL", 105.0, detected + timedelta(minutes=10))
    now = detected + timedelta(minutes=20)
    await backfill_earnings_reactions(s, pricing, now=now)
    row = s.get_earnings("AAPL", "2026-04-30")
    assert row["status"] == "published_pending_reaction"
    assert row["reaction_pct_30m"] is None


@pytest.mark.asyncio
async def test_writes_reaction_after_delay(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EARNINGS_REACTION_BACKFILL_DELAY_MIN", 30)
    monkeypatch.setattr(config, "EARNINGS_REACTION_BACKFILL_TIMEOUT_HOURS", 6)
    s = Storage(str(tmp_path / "t.db")); s.init_schema()
    detected = datetime(2026, 4, 30, 20, 5, tzinfo=timezone.utc)
    row, eid = _seed_published_row(s, mark_at_publish=100.0, detected_at=detected)
    pricing = PriceBook(); pricing.update("AAPL", 103.2, detected + timedelta(minutes=35))
    now = detected + timedelta(minutes=35)
    await backfill_earnings_reactions(s, pricing, now=now)
    row = s.get_earnings("AAPL", "2026-04-30")
    assert row["status"] == "reacted"
    assert abs(row["reaction_pct_30m"] - 0.032) < 1e-6
    summary = s._conn.execute("SELECT summary FROM events WHERE id=?", (eid,)).fetchone()["summary"]
    assert "30m 反应" in summary or "+3.2%" in summary


@pytest.mark.asyncio
async def test_no_pricing_skips_then_force_stales_after_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EARNINGS_REACTION_BACKFILL_DELAY_MIN", 30)
    monkeypatch.setattr(config, "EARNINGS_REACTION_BACKFILL_TIMEOUT_HOURS", 6)
    s = Storage(str(tmp_path / "t.db")); s.init_schema()
    detected = datetime(2026, 4, 30, 20, 5, tzinfo=timezone.utc)
    _seed_published_row(s, mark_at_publish=None, detected_at=detected)
    empty_pricing = PriceBook()

    # Within timeout: skip, status unchanged.
    await backfill_earnings_reactions(s, empty_pricing, now=detected + timedelta(hours=2))
    assert s.get_earnings("AAPL", "2026-04-30")["status"] == "published_pending_reaction"

    # After timeout: force reacted, reaction NULL.
    await backfill_earnings_reactions(s, empty_pricing, now=detected + timedelta(hours=7))
    row = s.get_earnings("AAPL", "2026-04-30")
    assert row["status"] == "reacted"
    assert row["reaction_pct_30m"] is None


@pytest.mark.asyncio
async def test_only_processes_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EARNINGS_REACTION_BACKFILL_DELAY_MIN", 30)
    s = Storage(str(tmp_path / "t.db")); s.init_schema()
    detected = datetime(2026, 4, 30, 20, 5, tzinfo=timezone.utc)
    _seed_published_row(s, ticker="AAPL", detected_at=detected)
    # Mark AAPL as already reacted
    s.set_earnings_status(s.get_earnings("AAPL", "2026-04-30")["id"], "reacted")
    pricing = PriceBook(); pricing.update("AAPL", 200.0, detected + timedelta(minutes=35))
    await backfill_earnings_reactions(s, pricing, now=detected + timedelta(minutes=35))
    row = s.get_earnings("AAPL", "2026-04-30")
    assert row["reaction_pct_30m"] is None   # untouched
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/test_earnings_reaction_backfill.py -v
```
Expected: FAIL — module does not exist.

- [ ] **Step 4: Implement the backfill job**

Create `paper/earnings_reaction.py`:

```python
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
            continue   # try again next sweep

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
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_earnings_reaction_backfill.py -v
```
Expected: PASS.

- [ ] **Step 6: Run full suite**

```bash
pytest -x -q
```
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add paper/earnings_reaction.py sources/finnhub.py paper/broker.py app.py tests/test_earnings_reaction_backfill.py
git commit -m "feat(paper): +30m earnings reaction backfill job"
```

---

## Task 10: Scheduler registration

**Files:**
- Modify: `scheduler.py`
- Modify: `app.py` (pass `storage` and `paper_broker.pricing` so the job has its dependencies)
- Test: existing `tests/test_scheduler_sources.py` covers job registration; add a small assertion test

- [ ] **Step 1: Read scheduler.py**

Open `scheduler.py` and locate the `build_scheduler(...)` function. Identify how existing jobs (e.g. cleanup) are registered.

- [ ] **Step 2: Write a failing test**

Append to `tests/test_scheduler_sources.py`:

```python
def test_earnings_backfill_job_registered():
    # Build a scheduler without starting it and confirm the job IDs we expect.
    from scheduler import build_scheduler
    storage = _Storage()                # use existing helper from this file
    sched = build_scheduler(
        pipeline=_NoopPipeline(),
        price_pipeline=_NoopPipeline(),
        storage=storage,
        notifier=None, push_hub=None, paper_broker=_NoopPaperBroker(),
    )
    job_ids = {j.id for j in sched.get_jobs()}
    assert "earnings_reaction_backfill" in job_ids
    assert "earnings_stale_sweep" in job_ids
```

If existing helpers (`_NoopPipeline`, `_NoopPaperBroker`) don't exist in `tests/test_scheduler_sources.py`, follow the file's actual fixture pattern — read the file first.

- [ ] **Step 3: Run test to verify it fails**

```bash
pytest tests/test_scheduler_sources.py::test_earnings_backfill_job_registered -v
```
Expected: FAIL — jobs not registered.

- [ ] **Step 4: Register the jobs**

In `scheduler.py`:

1. Add imports at the top:
```python
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta, timezone

from paper.earnings_reaction import backfill_earnings_reactions
import config
```
(Import only what's not already imported.)

2. Inside `build_scheduler`, after the existing daily cleanup block:

```python
    if paper_broker is not None:
        scheduler.add_job(
            lambda: backfill_earnings_reactions(storage, paper_broker.pricing),
            IntervalTrigger(minutes=5),
            id="earnings_reaction_backfill",
            next_run_time=None,
        )

    def _stale_sweep():
        cutoff = (datetime.now(timezone.utc).date()
                  - timedelta(days=config.EARNINGS_STALE_LOOKBACK_DAYS)).isoformat()
        n = storage.mark_stale_scheduled_before(cutoff)
        if n:
            log.info("earnings stale sweep: marked %d rows stale", n)

    scheduler.add_job(
        _stale_sweep,
        CronTrigger(hour=0, minute=10),
        id="earnings_stale_sweep",
    )
```

3. Confirm `paper_broker.pricing` is a public attribute. If not, expose one in `paper/broker.py`:
```python
@property
def pricing(self):
    return self._prices
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_scheduler_sources.py -v
```
Expected: all pass.

- [ ] **Step 6: Run full suite**

```bash
pytest -x -q
```
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add scheduler.py paper/broker.py tests/test_scheduler_sources.py
git commit -m "feat(scheduler): register earnings reaction backfill and stale sweep"
```

---

## Task 11: API endpoint `GET /api/earnings/upcoming`

**Files:**
- Modify: `web/routes.py`
- Modify: `storage.py` (add a small list method)
- Test: extend `tests/test_diagnostics_route.py` or create `tests/test_earnings_route.py`

- [ ] **Step 1: Add the storage method (test-first)**

Append to `tests/test_earnings_calendar_storage.py`:

```python
def test_list_upcoming_earnings(tmp_path):
    s = _storage(tmp_path)
    now = datetime(2026, 4, 25, 0, 0, tzinfo=timezone.utc)
    for date in ("2026-04-26", "2026-04-30", "2026-05-15"):
        s.upsert_earnings(
            ticker="AAPL", scheduled_date=date, scheduled_hour="amc",
            eps_estimate=1.0, eps_actual=None, rev_estimate=1.0, rev_actual=None,
            status="scheduled", updated_at=now,
        )
    rows = s.list_upcoming_earnings("2026-04-27", "2026-05-10")
    dates = [r["scheduled_date"] for r in rows]
    assert dates == ["2026-04-30"]
```

Run; expect FAIL.

In `storage.py` add:
```python
    def list_upcoming_earnings(self, date_from: str, date_to: str) -> list[dict]:
        rows = self._conn.execute(
            """SELECT * FROM earnings_calendar
               WHERE scheduled_date BETWEEN ? AND ?
                 AND status != 'stale'
               ORDER BY scheduled_date ASC, ticker ASC""",
            (date_from, date_to),
        ).fetchall()
        return [dict(r) for r in rows]
```

Run tests; expect PASS.

- [ ] **Step 2: Add the route (test-first)**

Create `tests/test_earnings_route.py` that reuses the same `client` fixture pattern as `tests/test_diagnostics_route.py`:

```python
import importlib
import json
import tempfile
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


class _DummyScheduler:
    def shutdown(self):
        pass


@pytest.fixture
def client(monkeypatch):
    async def _noop_async(*args, **kwargs):
        return None

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    watch = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    watch.write(json.dumps({"tickers": ["AAPL"]}).encode())
    watch.close()
    monkeypatch.setenv("DB_PATH", tmp.name)
    monkeypatch.setenv("WATCHLIST_PATH", watch.name)
    monkeypatch.setenv("IBKR_ENABLED", "0")
    import config
    importlib.reload(config)
    import app as app_module
    importlib.reload(app_module)
    monkeypatch.setattr(app_module, "start_scheduler", lambda *args, **kwargs: _DummyScheduler())
    monkeypatch.setattr(app_module, "build_runner_if_enabled", lambda **kwargs: None)
    app_module.app.state.sec_source.load_ticker_map = _noop_async
    app_module.app.state.pipeline.run_once = _noop_async
    app_module.app.state.price_pipeline.run_once = _noop_async
    # Seed an upcoming earnings row directly via the live storage handle.
    app_module.app.state.storage.upsert_earnings(
        ticker="AAPL", scheduled_date="2026-05-01", scheduled_hour="amc",
        eps_estimate=1.0, eps_actual=None, rev_estimate=1.0, rev_actual=None,
        status="scheduled",
        updated_at=datetime(2026, 4, 25, 0, 0, tzinfo=timezone.utc),
    )
    c = TestClient(app_module.app)
    with c:
        yield c


def test_upcoming_earnings_returns_list(client):
    resp = client.get("/api/earnings/upcoming?from=2026-04-30&to=2026-05-05")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert any(r["ticker"] == "AAPL" and r["scheduled_date"] == "2026-05-01" for r in body)


def test_upcoming_earnings_excludes_stale(client):
    app_module = __import__("app")
    app_module.app.state.storage.upsert_earnings(
        ticker="OLD", scheduled_date="2026-01-01", scheduled_hour="amc",
        eps_estimate=1.0, eps_actual=None, rev_estimate=1.0, rev_actual=None,
        status="scheduled",
        updated_at=datetime(2025, 12, 1, 0, 0, tzinfo=timezone.utc),
    )
    app_module.app.state.storage.mark_stale_scheduled_before("2026-04-25")
    resp = client.get("/api/earnings/upcoming?from=2025-12-01&to=2026-12-31")
    body = resp.json()
    assert all(r["ticker"] != "OLD" for r in body)
```

This requires `app.state.storage` to be exposed by `app.py`. Check `app.py` — if `storage` is set on `app.state` already (it is, used by other routes), no change needed. If not, add `app.state.storage = storage` in `create_app`.

Run; expect FAIL — endpoint not registered.

- [ ] **Step 3: Implement the route**

Locate the `build_router(...)` function in `web/routes.py`. Add:

```python
    @router.get("/api/earnings/upcoming")
    def upcoming_earnings(
        from_: str | None = Query(None, alias="from"),
        to: str | None = None,
    ):
        from datetime import datetime, timezone, timedelta
        today = datetime.now(timezone.utc).date()
        date_from = from_ or today.isoformat()
        date_to = to or (today + timedelta(days=14)).isoformat()
        return storage.list_upcoming_earnings(date_from, date_to)
```

Make sure `Query` is imported from `fastapi`. If `storage` isn't already in scope inside `build_router`, follow the existing convention (it's likely captured by closure).

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_earnings_route.py tests/test_earnings_calendar_storage.py -v
```
Expected: PASS.

- [ ] **Step 5: Run full suite**

```bash
pytest -x -q
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add web/routes.py storage.py tests/test_earnings_route.py tests/test_earnings_calendar_storage.py
git commit -m "feat(api): GET /api/earnings/upcoming"
```

---

## Task 12: Document new env vars

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Append the new section**

Append to `.env.example` (after the Paper broker block):

```bash

# ---------- Earnings calendar ----------
EARNINGS_BLACKOUT_ENABLED=1
EARNINGS_BLACKOUT_BEFORE_MIN=990     # 16h30m — covers ET-day for AMC reports
EARNINGS_BLACKOUT_AFTER_MIN=1080     # 18h — covers next pre-market
EARNINGS_SURPRISE_HIGH_PCT=0.05      # 5% — threshold for high-importance push
EARNINGS_REACTION_BACKFILL_DELAY_MIN=30
EARNINGS_REACTION_BACKFILL_TIMEOUT_HOURS=6
EARNINGS_STALE_LOOKBACK_DAYS=7
```

- [ ] **Step 2: Run full suite one last time**

```bash
pytest -x -q
```
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add .env.example
git commit -m "docs: document earnings env vars"
```

---

## Task 13: Manual smoke check

- [ ] **Step 1: Start the app**

```bash
python app.py
```

- [ ] **Step 2: Hit the new endpoint**

```bash
curl 'http://127.0.0.1:8000/api/earnings/upcoming?from=2026-04-25&to=2026-05-15' | head -50
```

Expected: a JSON list (possibly empty if no earnings yet polled).

- [ ] **Step 3: Inspect the diagnostics page**

Open http://127.0.0.1:8000/ — the existing diagnostics modal should still render and `finnhub:earnings` health should be visible.

- [ ] **Step 4: Stop the app**

```bash
# Find the PID via lsof, kill it
lsof -ti:8000 | xargs kill
```

- [ ] **Step 5: Push everything**

```bash
git push
```
