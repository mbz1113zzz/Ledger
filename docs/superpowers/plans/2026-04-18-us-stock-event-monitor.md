# 美股事件监控系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a locally-run web dashboard that monitors user-defined US stock tickers for news, SEC 8-K filings, and upcoming earnings, with real-time browser notifications for high-importance events.

**Architecture:** FastAPI backend polls 3 data sources (Finnhub, SEC EDGAR, yfinance) via APScheduler, dedupes and scores events, persists to SQLite, and streams new events to a vanilla-JS dashboard via Server-Sent Events.

**Tech Stack:** Python 3.10+, FastAPI, APScheduler, httpx, yfinance, SQLite, vanilla HTML/JS, Web Notifications API, pytest.

**Spec:** [docs/superpowers/specs/2026-04-18-us-stock-event-monitor-design.md](../specs/2026-04-18-us-stock-event-monitor-design.md)

---

## Task 1: Project Scaffolding

**Files:**
- Create: `stock-monitor/requirements.txt`
- Create: `stock-monitor/config.py`
- Create: `stock-monitor/watchlist.json`
- Create: `stock-monitor/sources/__init__.py`
- Create: `stock-monitor/tests/__init__.py`
- Create: `stock-monitor/web/__init__.py`
- Create: `stock-monitor/web/static/.gitkeep`
- Create: `stock-monitor/data/.gitkeep`

- [ ] **Step 1: Create directory layout**

```bash
cd /Users/mabizheng/Desktop/美股
mkdir -p stock-monitor/sources stock-monitor/tests stock-monitor/web/static stock-monitor/data
touch stock-monitor/sources/__init__.py stock-monitor/tests/__init__.py stock-monitor/web/__init__.py
touch stock-monitor/web/static/.gitkeep stock-monitor/data/.gitkeep
```

- [ ] **Step 2: Write `requirements.txt`**

```
fastapi==0.115.0
uvicorn[standard]==0.32.0
apscheduler==3.10.4
httpx==0.27.2
yfinance==0.2.44
python-dotenv==1.0.1
pytest==8.3.3
pytest-asyncio==0.24.0
```

- [ ] **Step 3: Write `config.py`**

```python
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT.parent / ".env")

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
FINNHUB_INTERVAL_MINUTES = 5
SEC_INTERVAL_MINUTES = 5
EARNINGS_CALENDAR_HOUR = 0  # run at 00:05 local time
EARNINGS_CALENDAR_MINUTE = 5
DB_PATH = str(ROOT / "data" / "events.db")
WATCHLIST_PATH = str(ROOT / "watchlist.json")
RETAIN_DAYS = 30
PORT = 8000
SEC_USER_AGENT = "stock-monitor research@example.com"  # SEC requires a UA
HIGH_KEYWORDS = [
    "acquisition", "merger", "fda approval", "guidance",
    "ceo", "resign", "bankruptcy", "dividend", "buyback",
    "downgrade", "upgrade", "investigation",
]
```

- [ ] **Step 4: Write `watchlist.json`**

```json
{
  "tickers": ["EOSE", "MDB", "NVDA"]
}
```

- [ ] **Step 5: Create venv and install deps**

```bash
cd /Users/mabizheng/Desktop/美股/stock-monitor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Expected: All packages install without error.

- [ ] **Step 6: Commit**

```bash
cd /Users/mabizheng/Desktop/美股
git init 2>/dev/null || true
git add stock-monitor/requirements.txt stock-monitor/config.py stock-monitor/watchlist.json \
  stock-monitor/sources/__init__.py stock-monitor/tests/__init__.py stock-monitor/web/__init__.py \
  stock-monitor/web/static/.gitkeep stock-monitor/data/.gitkeep .gitignore
git commit -m "chore: scaffold stock-monitor project"
```

---

## Task 2: Event Data Structure and Source Base Class

**Files:**
- Create: `stock-monitor/sources/base.py`
- Create: `stock-monitor/tests/test_base.py`

- [ ] **Step 1: Write failing test**

```python
# stock-monitor/tests/test_base.py
from datetime import datetime, timezone
from sources.base import Event


def test_event_has_required_fields():
    e = Event(
        source="finnhub",
        external_id="abc123",
        ticker="EOSE",
        event_type="news",
        title="EOSE announces new contract",
        summary="Details...",
        url="https://example.com/1",
        published_at=datetime.now(timezone.utc),
        raw={"foo": "bar"},
    )
    assert e.importance == "low"
    assert e.ticker == "EOSE"


def test_event_importance_can_be_overridden():
    e = Event(
        source="sec_edgar",
        external_id="0001-22",
        ticker="MDB",
        event_type="filing_8k",
        title="MDB 8-K",
        summary=None,
        url=None,
        published_at=datetime.now(timezone.utc),
        raw={},
        importance="high",
    )
    assert e.importance == "high"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/mabizheng/Desktop/美股/stock-monitor
source .venv/bin/activate
PYTHONPATH=. pytest tests/test_base.py -v
```

Expected: `ModuleNotFoundError: No module named 'sources.base'`

- [ ] **Step 3: Implement `sources/base.py`**

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Event:
    source: str
    external_id: str
    ticker: str
    event_type: str  # "news" | "filing_8k" | "earnings"
    title: str
    summary: str | None
    url: str | None
    published_at: datetime
    raw: dict[str, Any] = field(default_factory=dict)
    importance: str = "low"  # "high" | "medium" | "low"


class Source(ABC):
    name: str = ""

    @abstractmethod
    async def fetch(self, tickers: list[str]) -> list[Event]:
        """Fetch new events for the given tickers. Implementations must return
        events without applying importance scoring (that's the scorer's job)."""
```

- [ ] **Step 4: Run test to verify it passes**

```bash
PYTHONPATH=. pytest tests/test_base.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add stock-monitor/sources/base.py stock-monitor/tests/test_base.py
git commit -m "feat: add Event dataclass and Source base class"
```

---

## Task 3: SQLite Storage Layer

**Files:**
- Create: `stock-monitor/storage.py`
- Create: `stock-monitor/tests/test_storage.py`

- [ ] **Step 1: Write failing test**

```python
# stock-monitor/tests/test_storage.py
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from sources.base import Event
from storage import Storage


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    s = Storage(str(tmp_path / "test.db"))
    s.init_schema()
    return s


def _make_event(external_id: str = "id1", importance: str = "low") -> Event:
    return Event(
        source="finnhub",
        external_id=external_id,
        ticker="EOSE",
        event_type="news",
        title="Title",
        summary="Summary",
        url="https://example.com",
        published_at=datetime(2026, 4, 18, 12, 0, tzinfo=timezone.utc),
        raw={"k": "v"},
        importance=importance,
    )


def test_insert_and_query(storage):
    storage.insert(_make_event())
    events = storage.query(limit=10)
    assert len(events) == 1
    assert events[0].external_id == "id1"


def test_insert_duplicate_is_ignored(storage):
    storage.insert(_make_event())
    storage.insert(_make_event())  # same external_id + source
    assert len(storage.query(limit=10)) == 1


def test_exists_check(storage):
    assert storage.exists("finnhub", "id1") is False
    storage.insert(_make_event())
    assert storage.exists("finnhub", "id1") is True


def test_query_filters_by_importance(storage):
    storage.insert(_make_event(external_id="a", importance="high"))
    storage.insert(_make_event(external_id="b", importance="low"))
    high = storage.query(importance="high")
    assert len(high) == 1
    assert high[0].external_id == "a"


def test_query_filters_by_ticker(storage):
    e1 = _make_event(external_id="a")
    e2 = _make_event(external_id="b")
    e2.ticker = "MDB"
    storage.insert(e1)
    storage.insert(e2)
    assert len(storage.query(ticker="EOSE")) == 1
    assert len(storage.query(ticker="MDB")) == 1


def test_cleanup_old_events(storage):
    old = _make_event(external_id="old")
    storage.insert(old)
    # Force created_at far in the past
    storage._conn.execute(
        "UPDATE events SET created_at = datetime('now', '-60 days') WHERE external_id='old'"
    )
    storage._conn.commit()
    storage.insert(_make_event(external_id="new"))
    storage.cleanup(retain_days=30)
    remaining = storage.query(limit=10)
    assert len(remaining) == 1
    assert remaining[0].external_id == "new"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=. pytest tests/test_storage.py -v
```

Expected: `ModuleNotFoundError: No module named 'storage'`

- [ ] **Step 3: Implement `storage.py`**

```python
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from sources.base import Event


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    event_type TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    url TEXT,
    published_at TIMESTAMP NOT NULL,
    importance TEXT NOT NULL,
    raw_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_ticker_time ON events(ticker, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_importance_time ON events(importance, published_at DESC);
"""


class Storage:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def init_schema(self) -> None:
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def exists(self, source: str, external_id: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM events WHERE source=? AND external_id=? LIMIT 1",
            (source, external_id),
        )
        return cur.fetchone() is not None

    def insert(self, event: Event) -> bool:
        """Returns True if inserted, False if duplicate."""
        try:
            self._conn.execute(
                """INSERT INTO events
                   (source, external_id, ticker, event_type, title, summary, url,
                    published_at, importance, raw_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.source,
                    event.external_id,
                    event.ticker,
                    event.event_type,
                    event.title,
                    event.summary,
                    event.url,
                    event.published_at.isoformat(),
                    event.importance,
                    json.dumps(event.raw),
                ),
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def query(
        self,
        *,
        importance: str | None = None,
        ticker: str | None = None,
        limit: int = 100,
    ) -> list[Event]:
        sql = "SELECT * FROM events WHERE 1=1"
        params: list = []
        if importance:
            sql += " AND importance = ?"
            params.append(importance)
        if ticker:
            sql += " AND ticker = ?"
            params.append(ticker)
        sql += " ORDER BY published_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_event(r) for r in rows]

    def cleanup(self, retain_days: int) -> int:
        cur = self._conn.execute(
            f"DELETE FROM events WHERE created_at < datetime('now', '-{int(retain_days)} days')"
        )
        self._conn.commit()
        return cur.rowcount

    def _row_to_event(self, row: sqlite3.Row) -> Event:
        return Event(
            source=row["source"],
            external_id=row["external_id"],
            ticker=row["ticker"],
            event_type=row["event_type"],
            title=row["title"],
            summary=row["summary"],
            url=row["url"],
            published_at=datetime.fromisoformat(row["published_at"]),
            raw=json.loads(row["raw_json"] or "{}"),
            importance=row["importance"],
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=. pytest tests/test_storage.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add stock-monitor/storage.py stock-monitor/tests/test_storage.py
git commit -m "feat: add SQLite storage layer with dedup, filtering, cleanup"
```

---

## Task 4: Watchlist Manager

**Files:**
- Create: `stock-monitor/watchlist_manager.py`
- Create: `stock-monitor/tests/test_watchlist_manager.py`

- [ ] **Step 1: Write failing test**

```python
# stock-monitor/tests/test_watchlist_manager.py
import json
from pathlib import Path

import pytest

from watchlist_manager import WatchlistManager, WatchlistError


def test_load_valid_watchlist(tmp_path: Path):
    p = tmp_path / "wl.json"
    p.write_text(json.dumps({"tickers": ["EOSE", "MDB"]}))
    wm = WatchlistManager(str(p))
    assert wm.tickers() == ["EOSE", "MDB"]


def test_tickers_are_uppercased(tmp_path: Path):
    p = tmp_path / "wl.json"
    p.write_text(json.dumps({"tickers": ["eose", "mdb"]}))
    wm = WatchlistManager(str(p))
    assert wm.tickers() == ["EOSE", "MDB"]


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(WatchlistError):
        WatchlistManager(str(tmp_path / "nope.json"))


def test_invalid_schema_raises(tmp_path: Path):
    p = tmp_path / "wl.json"
    p.write_text(json.dumps({"foo": "bar"}))
    with pytest.raises(WatchlistError):
        WatchlistManager(str(p))


def test_empty_tickers_raises(tmp_path: Path):
    p = tmp_path / "wl.json"
    p.write_text(json.dumps({"tickers": []}))
    with pytest.raises(WatchlistError):
        WatchlistManager(str(p))
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=. pytest tests/test_watchlist_manager.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `watchlist_manager.py`**

```python
import json
from pathlib import Path


class WatchlistError(Exception):
    pass


class WatchlistManager:
    def __init__(self, path: str):
        self._path = Path(path)
        if not self._path.exists():
            raise WatchlistError(f"Watchlist file not found: {path}")
        try:
            data = json.loads(self._path.read_text())
        except json.JSONDecodeError as e:
            raise WatchlistError(f"Invalid JSON in watchlist: {e}") from e
        if not isinstance(data, dict) or "tickers" not in data:
            raise WatchlistError("Watchlist must be an object with a 'tickers' key")
        tickers = data["tickers"]
        if not isinstance(tickers, list) or not tickers:
            raise WatchlistError("'tickers' must be a non-empty list")
        self._tickers = [str(t).upper() for t in tickers]

    def tickers(self) -> list[str]:
        return list(self._tickers)
```

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=. pytest tests/test_watchlist_manager.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add stock-monitor/watchlist_manager.py stock-monitor/tests/test_watchlist_manager.py
git commit -m "feat: add watchlist manager with validation"
```

---

## Task 5: Event Scorer

**Files:**
- Create: `stock-monitor/event_scorer.py`
- Create: `stock-monitor/tests/test_scorer.py`

- [ ] **Step 1: Write failing test**

```python
# stock-monitor/tests/test_scorer.py
from datetime import datetime, timezone

from event_scorer import score
from sources.base import Event


def _event(event_type: str, title: str = "", summary: str = "") -> Event:
    return Event(
        source="x",
        external_id="1",
        ticker="EOSE",
        event_type=event_type,
        title=title,
        summary=summary,
        url=None,
        published_at=datetime.now(timezone.utc),
        raw={},
    )


def test_8k_is_high():
    assert score(_event("filing_8k")) == "high"


def test_earnings_is_high():
    assert score(_event("earnings")) == "high"


def test_news_with_high_keyword_is_high():
    e = _event("news", title="Company announces FDA approval for drug X")
    assert score(e) == "high"


def test_news_keyword_in_summary():
    e = _event("news", title="Update", summary="The CEO announced a buyback.")
    assert score(e) == "high"


def test_news_without_keyword_is_medium():
    assert score(_event("news", title="Routine trading update")) == "medium"


def test_unknown_type_is_low():
    assert score(_event("other")) == "low"


def test_case_insensitive_matching():
    assert score(_event("news", title="FDA APPROVAL granted")) == "high"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=. pytest tests/test_scorer.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `event_scorer.py`**

```python
from config import HIGH_KEYWORDS
from sources.base import Event


def score(event: Event) -> str:
    if event.event_type in ("filing_8k", "earnings"):
        return "high"
    if event.event_type == "news":
        text = (event.title + " " + (event.summary or "")).lower()
        if any(kw in text for kw in HIGH_KEYWORDS):
            return "high"
        return "medium"
    return "low"
```

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=. pytest tests/test_scorer.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add stock-monitor/event_scorer.py stock-monitor/tests/test_scorer.py
git commit -m "feat: add importance scoring for events"
```

---

## Task 6: Deduplicator

**Files:**
- Create: `stock-monitor/deduplicator.py`
- Create: `stock-monitor/tests/test_deduplicator.py`

- [ ] **Step 1: Write failing test**

```python
# stock-monitor/tests/test_deduplicator.py
from datetime import datetime, timezone
from pathlib import Path

import pytest

from deduplicator import Deduplicator
from sources.base import Event
from storage import Storage


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    s = Storage(str(tmp_path / "t.db"))
    s.init_schema()
    return s


def _event(eid: str) -> Event:
    return Event(
        source="finnhub", external_id=eid, ticker="EOSE",
        event_type="news", title="t", summary=None, url=None,
        published_at=datetime.now(timezone.utc), raw={},
    )


def test_filter_removes_already_stored(storage):
    storage.insert(_event("a"))
    dedup = Deduplicator(storage)
    result = dedup.filter_new([_event("a"), _event("b")])
    assert [e.external_id for e in result] == ["b"]


def test_filter_empty(storage):
    dedup = Deduplicator(storage)
    assert dedup.filter_new([]) == []


def test_filter_within_batch_duplicates(storage):
    dedup = Deduplicator(storage)
    result = dedup.filter_new([_event("a"), _event("a")])
    assert len(result) == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=. pytest tests/test_deduplicator.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `deduplicator.py`**

```python
from sources.base import Event
from storage import Storage


class Deduplicator:
    def __init__(self, storage: Storage):
        self._storage = storage

    def filter_new(self, events: list[Event]) -> list[Event]:
        seen: set[tuple[str, str]] = set()
        result: list[Event] = []
        for e in events:
            key = (e.source, e.external_id)
            if key in seen:
                continue
            if self._storage.exists(e.source, e.external_id):
                continue
            seen.add(key)
            result.append(e)
        return result
```

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=. pytest tests/test_deduplicator.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add stock-monitor/deduplicator.py stock-monitor/tests/test_deduplicator.py
git commit -m "feat: add deduplicator with intra-batch + persisted checks"
```

---

## Task 7: Finnhub News Source

**Files:**
- Create: `stock-monitor/sources/finnhub.py`
- Create: `stock-monitor/tests/test_finnhub.py`

- [ ] **Step 1: Write failing test**

```python
# stock-monitor/tests/test_finnhub.py
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from sources.finnhub import FinnhubSource


SAMPLE_RESPONSE = [
    {
        "id": 12345,
        "headline": "EOSE wins major contract",
        "summary": "Details of the contract...",
        "url": "https://example.com/a",
        "datetime": 1744977600,  # 2025-04-18 12:00 UTC
        "related": "EOSE",
    },
    {
        "id": 12346,
        "headline": "Market update",
        "summary": "",
        "url": "https://example.com/b",
        "datetime": 1744981200,
        "related": "EOSE",
    },
]


@pytest.mark.asyncio
async def test_fetch_returns_events():
    src = FinnhubSource(api_key="fake")
    with patch.object(src, "_get", new=AsyncMock(return_value=SAMPLE_RESPONSE)):
        events = await src.fetch(["EOSE"])
    assert len(events) == 2
    assert events[0].source == "finnhub"
    assert events[0].external_id == "12345"
    assert events[0].ticker == "EOSE"
    assert events[0].event_type == "news"
    assert events[0].title == "EOSE wins major contract"
    assert events[0].published_at == datetime.fromtimestamp(1744977600, tz=timezone.utc)


@pytest.mark.asyncio
async def test_fetch_skips_malformed_entries():
    bad = [{"headline": "missing id"}]
    src = FinnhubSource(api_key="fake")
    with patch.object(src, "_get", new=AsyncMock(return_value=bad)):
        events = await src.fetch(["EOSE"])
    assert events == []


@pytest.mark.asyncio
async def test_empty_api_key_returns_empty():
    src = FinnhubSource(api_key="")
    events = await src.fetch(["EOSE"])
    assert events == []


@pytest.mark.asyncio
async def test_http_error_returns_empty_for_that_ticker():
    src = FinnhubSource(api_key="fake")
    async def raise_err(*a, **kw):
        raise RuntimeError("boom")
    with patch.object(src, "_get", new=AsyncMock(side_effect=raise_err)):
        events = await src.fetch(["EOSE"])
    assert events == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=. pytest tests/test_finnhub.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `sources/finnhub.py`**

```python
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from sources.base import Event, Source

log = logging.getLogger(__name__)


class FinnhubSource(Source):
    name = "finnhub"
    BASE_URL = "https://finnhub.io/api/v1"

    def __init__(self, api_key: str):
        self._api_key = api_key

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
        since = (today - timedelta(days=1)).isoformat()
        until = today.isoformat()
        events: list[Event] = []
        for ticker in tickers:
            try:
                data = await self._get(
                    "/company-news",
                    {"symbol": ticker, "from": since, "to": until},
                )
            except Exception as e:
                log.warning("finnhub fetch failed for %s: %s", ticker, e)
                continue
            for item in data or []:
                ev = self._parse(item, ticker)
                if ev:
                    events.append(ev)
        return events

    def _parse(self, item: dict, ticker: str) -> Event | None:
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
            log.debug("skipping malformed finnhub item: %s", e)
            return None
```

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=. pytest tests/test_finnhub.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add stock-monitor/sources/finnhub.py stock-monitor/tests/test_finnhub.py
git commit -m "feat: add Finnhub company-news source"
```

---

## Task 8: SEC EDGAR 8-K Source

**Files:**
- Create: `stock-monitor/sources/sec_edgar.py`
- Create: `stock-monitor/tests/test_sec_edgar.py`

- [ ] **Step 1: Write failing test**

```python
# stock-monitor/tests/test_sec_edgar.py
from unittest.mock import AsyncMock, patch

import pytest

from sources.sec_edgar import SecEdgarSource


TICKER_MAP_RESPONSE = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 1730168, "ticker": "EOSE", "title": "EOS Energy Enterprises"},
}

SUBMISSIONS_RESPONSE = {
    "cik": "0001730168",
    "filings": {
        "recent": {
            "accessionNumber": ["0001-25-000001", "0001-25-000002"],
            "form":            ["8-K",              "10-Q"],
            "filingDate":      ["2026-04-17",       "2026-04-10"],
            "primaryDocument": ["doc1.htm",         "doc2.htm"],
            "primaryDocDescription": ["8-K filing", "10-Q filing"],
        }
    },
}


@pytest.mark.asyncio
async def test_fetch_returns_only_8k():
    src = SecEdgarSource()
    src._ticker_to_cik = {"EOSE": "0001730168"}
    with patch.object(src, "_get", new=AsyncMock(return_value=SUBMISSIONS_RESPONSE)):
        events = await src.fetch(["EOSE"])
    assert len(events) == 1
    assert events[0].event_type == "filing_8k"
    assert events[0].external_id == "0001-25-000001"
    assert events[0].ticker == "EOSE"
    assert "sec.gov" in events[0].url


@pytest.mark.asyncio
async def test_unknown_ticker_skipped():
    src = SecEdgarSource()
    src._ticker_to_cik = {}
    events = await src.fetch(["ZZZZ"])
    assert events == []


@pytest.mark.asyncio
async def test_load_ticker_map_parses_response():
    src = SecEdgarSource()
    with patch.object(src, "_get", new=AsyncMock(return_value=TICKER_MAP_RESPONSE)):
        await src.load_ticker_map()
    assert src._ticker_to_cik["AAPL"] == "0000320193"
    assert src._ticker_to_cik["EOSE"] == "0001730168"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=. pytest tests/test_sec_edgar.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `sources/sec_edgar.py`**

```python
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
```

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=. pytest tests/test_sec_edgar.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add stock-monitor/sources/sec_edgar.py stock-monitor/tests/test_sec_edgar.py
git commit -m "feat: add SEC EDGAR 8-K filings source"
```

---

## Task 9: yfinance Earnings Calendar Source

**Files:**
- Create: `stock-monitor/sources/yfinance_source.py`
- Create: `stock-monitor/tests/test_yfinance_source.py`

- [ ] **Step 1: Write failing test**

```python
# stock-monitor/tests/test_yfinance_source.py
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from sources.yfinance_source import YfinanceSource


@pytest.mark.asyncio
async def test_fetch_returns_earnings_event():
    src = YfinanceSource()
    fake_ticker = MagicMock()
    fake_ticker.calendar = {"Earnings Date": [date(2026, 5, 1)]}
    with patch("sources.yfinance_source.yf.Ticker", return_value=fake_ticker):
        events = await src.fetch(["EOSE"])
    assert len(events) == 1
    e = events[0]
    assert e.event_type == "earnings"
    assert e.ticker == "EOSE"
    assert "2026-05-01" in e.external_id


@pytest.mark.asyncio
async def test_missing_calendar_returns_empty():
    src = YfinanceSource()
    fake_ticker = MagicMock()
    fake_ticker.calendar = {}
    with patch("sources.yfinance_source.yf.Ticker", return_value=fake_ticker):
        events = await src.fetch(["EOSE"])
    assert events == []


@pytest.mark.asyncio
async def test_exception_is_swallowed_per_ticker():
    src = YfinanceSource()
    with patch("sources.yfinance_source.yf.Ticker", side_effect=RuntimeError("boom")):
        events = await src.fetch(["EOSE"])
    assert events == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=. pytest tests/test_yfinance_source.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `sources/yfinance_source.py`**

```python
import asyncio
import logging
from datetime import date, datetime, time, timezone

import yfinance as yf

from sources.base import Event, Source

log = logging.getLogger(__name__)


class YfinanceSource(Source):
    name = "yfinance"

    async def fetch(self, tickers: list[str]) -> list[Event]:
        # yfinance is sync; run in thread
        return await asyncio.to_thread(self._fetch_sync, tickers)

    def _fetch_sync(self, tickers: list[str]) -> list[Event]:
        events: list[Event] = []
        for ticker in tickers:
            try:
                t = yf.Ticker(ticker)
                cal = t.calendar or {}
                dates = cal.get("Earnings Date") or []
                for d in dates:
                    ev = self._make_event(ticker, d)
                    if ev:
                        events.append(ev)
            except Exception as e:
                log.warning("yfinance fetch failed for %s: %s", ticker, e)
                continue
        return events

    def _make_event(self, ticker: str, d) -> Event | None:
        if isinstance(d, datetime):
            d = d.date()
        if not isinstance(d, date):
            return None
        pub = datetime.combine(d, time(0, 0), tzinfo=timezone.utc)
        return Event(
            source=self.name,
            external_id=f"{ticker}-earnings-{d.isoformat()}",
            ticker=ticker,
            event_type="earnings",
            title=f"{ticker} earnings scheduled {d.isoformat()}",
            summary=None,
            url=None,
            published_at=pub,
            raw={"date": d.isoformat()},
        )
```

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=. pytest tests/test_yfinance_source.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add stock-monitor/sources/yfinance_source.py stock-monitor/tests/test_yfinance_source.py
git commit -m "feat: add yfinance earnings calendar source"
```

---

## Task 10: SSE Notifier

**Files:**
- Create: `stock-monitor/notifier.py`
- Create: `stock-monitor/tests/test_notifier.py`

- [ ] **Step 1: Write failing test**

```python
# stock-monitor/tests/test_notifier.py
import asyncio

import pytest

from notifier import Notifier


@pytest.mark.asyncio
async def test_subscribe_and_publish():
    notifier = Notifier()
    queue = await notifier.subscribe()
    await notifier.publish({"title": "x"})
    item = await asyncio.wait_for(queue.get(), timeout=0.5)
    assert item == {"title": "x"}


@pytest.mark.asyncio
async def test_unsubscribe_stops_receiving():
    notifier = Notifier()
    queue = await notifier.subscribe()
    await notifier.unsubscribe(queue)
    await notifier.publish({"title": "x"})
    assert notifier.subscriber_count() == 0


@pytest.mark.asyncio
async def test_multiple_subscribers_all_receive():
    notifier = Notifier()
    q1 = await notifier.subscribe()
    q2 = await notifier.subscribe()
    await notifier.publish({"a": 1})
    assert (await asyncio.wait_for(q1.get(), 0.5)) == {"a": 1}
    assert (await asyncio.wait_for(q2.get(), 0.5)) == {"a": 1}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=. pytest tests/test_notifier.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `notifier.py`**

```python
import asyncio
from typing import Any


class Notifier:
    def __init__(self):
        self._subscribers: list[asyncio.Queue] = []
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self._subscribers.append(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        async with self._lock:
            if queue in self._subscribers:
                self._subscribers.remove(queue)

    async def publish(self, payload: dict[str, Any]) -> None:
        async with self._lock:
            targets = list(self._subscribers)
        for q in targets:
            await q.put(payload)

    def subscriber_count(self) -> int:
        return len(self._subscribers)
```

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=. pytest tests/test_notifier.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add stock-monitor/notifier.py stock-monitor/tests/test_notifier.py
git commit -m "feat: add in-memory SSE notifier for pub/sub"
```

---

## Task 11: Event Pipeline Orchestrator

**Files:**
- Create: `stock-monitor/pipeline.py`
- Create: `stock-monitor/tests/test_pipeline.py`

This task binds sources → dedup → scorer → storage → notifier.

- [ ] **Step 1: Write failing test**

```python
# stock-monitor/tests/test_pipeline.py
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pipeline import Pipeline
from notifier import Notifier
from sources.base import Event, Source
from storage import Storage


class FakeSource(Source):
    name = "fake"

    def __init__(self, events: list[Event]):
        self._events = events

    async def fetch(self, tickers: list[str]) -> list[Event]:
        return self._events


def _event(eid: str, etype: str = "news", title: str = "t") -> Event:
    return Event(
        source="fake", external_id=eid, ticker="EOSE",
        event_type=etype, title=title, summary=None, url=None,
        published_at=datetime.now(timezone.utc), raw={},
    )


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    s = Storage(str(tmp_path / "p.db"))
    s.init_schema()
    return s


@pytest.mark.asyncio
async def test_pipeline_stores_scored_new_events(storage):
    notifier = Notifier()
    queue = await notifier.subscribe()
    src = FakeSource([_event("a", "filing_8k", "8-K")])
    pipe = Pipeline(sources=[src], storage=storage, notifier=notifier, tickers=["EOSE"])
    n = await pipe.run_once()
    assert n == 1
    stored = storage.query()
    assert len(stored) == 1
    assert stored[0].importance == "high"
    payload = await queue.get()
    assert payload["external_id"] == "a"
    assert payload["importance"] == "high"


@pytest.mark.asyncio
async def test_pipeline_skips_duplicates(storage):
    notifier = Notifier()
    src = FakeSource([_event("a"), _event("a")])
    pipe = Pipeline(sources=[src], storage=storage, notifier=notifier, tickers=["EOSE"])
    assert await pipe.run_once() == 1
    assert await pipe.run_once() == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=. pytest tests/test_pipeline.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `pipeline.py`**

```python
import logging
from dataclasses import asdict

from deduplicator import Deduplicator
from event_scorer import score
from notifier import Notifier
from sources.base import Event, Source
from storage import Storage

log = logging.getLogger(__name__)


class Pipeline:
    def __init__(
        self,
        sources: list[Source],
        storage: Storage,
        notifier: Notifier,
        tickers: list[str],
    ):
        self._sources = sources
        self._storage = storage
        self._notifier = notifier
        self._tickers = tickers
        self._dedup = Deduplicator(storage)

    async def run_once(self) -> int:
        all_events: list[Event] = []
        for src in self._sources:
            try:
                events = await src.fetch(self._tickers)
                all_events.extend(events)
            except Exception as e:
                log.exception("source %s failed: %s", src.name, e)
        fresh = self._dedup.filter_new(all_events)
        inserted = 0
        for ev in fresh:
            ev.importance = score(ev)
            if self._storage.insert(ev):
                inserted += 1
                await self._notifier.publish(self._serialize(ev))
        log.info("pipeline inserted %d events", inserted)
        return inserted

    @staticmethod
    def _serialize(ev: Event) -> dict:
        d = asdict(ev)
        d["published_at"] = ev.published_at.isoformat()
        d.pop("raw", None)
        return d
```

- [ ] **Step 4: Run tests**

```bash
PYTHONPATH=. pytest tests/test_pipeline.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add stock-monitor/pipeline.py stock-monitor/tests/test_pipeline.py
git commit -m "feat: add event pipeline orchestrating sources, scoring, storage, notify"
```

---

## Task 12: Scheduler

**Files:**
- Create: `stock-monitor/scheduler.py`

This is glue code (no unit tests — tested via end-to-end manual check).

- [ ] **Step 1: Implement `scheduler.py`**

```python
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

import config
from pipeline import Pipeline
from sources.finnhub import FinnhubSource
from sources.sec_edgar import SecEdgarSource
from sources.yfinance_source import YfinanceSource
from storage import Storage

log = logging.getLogger(__name__)


def build_pipeline(
    storage: Storage, notifier, tickers: list[str], sec_source: SecEdgarSource
) -> Pipeline:
    sources = [
        FinnhubSource(api_key=config.FINNHUB_API_KEY),
        sec_source,
        YfinanceSource(),
    ]
    return Pipeline(sources=sources, storage=storage, notifier=notifier, tickers=tickers)


def start_scheduler(pipeline: Pipeline, storage: Storage) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        pipeline.run_once,
        IntervalTrigger(minutes=config.FINNHUB_INTERVAL_MINUTES),
        id="poll_sources",
        next_run_time=None,  # first run scheduled by caller via run_once()
    )
    scheduler.add_job(
        lambda: storage.cleanup(config.RETAIN_DAYS),
        CronTrigger(hour=config.EARNINGS_CALENDAR_HOUR, minute=config.EARNINGS_CALENDAR_MINUTE),
        id="daily_cleanup",
    )
    scheduler.start()
    log.info("scheduler started")
    return scheduler
```

- [ ] **Step 2: Commit**

```bash
git add stock-monitor/scheduler.py
git commit -m "feat: add APScheduler wiring for periodic polling and daily cleanup"
```

---

## Task 13: FastAPI Routes

**Files:**
- Create: `stock-monitor/web/routes.py`

- [ ] **Step 1: Implement `web/routes.py`**

```python
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, StreamingResponse

from notifier import Notifier
from storage import Storage
from watchlist_manager import WatchlistManager


STATIC_DIR = Path(__file__).parent / "static"


def build_router(
    storage: Storage, notifier: Notifier, watchlist: WatchlistManager
) -> APIRouter:
    router = APIRouter()

    @router.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    @router.get("/api/events")
    async def list_events(
        importance: str | None = None,
        ticker: str | None = None,
        limit: int = 200,
    ):
        events = storage.query(importance=importance, ticker=ticker, limit=limit)
        out = []
        for e in events:
            d = asdict(e)
            d["published_at"] = e.published_at.isoformat()
            d.pop("raw", None)
            out.append(d)
        return {"events": out}

    @router.get("/api/watchlist")
    async def get_watchlist():
        return {"tickers": watchlist.tickers()}

    @router.get("/healthz")
    async def health():
        return {"status": "ok"}

    @router.get("/stream")
    async def stream(request: Request):
        queue = await notifier.subscribe()

        async def gen():
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                        yield f"data: {json.dumps(payload)}\n\n"
                    except asyncio.TimeoutError:
                        # keepalive
                        yield ": ping\n\n"
            finally:
                await notifier.unsubscribe(queue)

        return StreamingResponse(gen(), media_type="text/event-stream")

    return router
```

- [ ] **Step 2: Commit**

```bash
git add stock-monitor/web/routes.py
git commit -m "feat: add FastAPI routes for events, watchlist, SSE stream"
```

---

## Task 14: Dashboard Static Assets

**Files:**
- Create: `stock-monitor/web/static/index.html`
- Create: `stock-monitor/web/static/style.css`
- Create: `stock-monitor/web/static/app.js`

- [ ] **Step 1: Write `index.html`**

```html
<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="UTF-8">
  <title>美股事件监控</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <header>
    <h1>美股事件监控</h1>
    <div class="controls">
      <span id="summary"></span>
      <label><input type="checkbox" id="notif-toggle"> 🔔 通知</label>
    </div>
  </header>
  <main>
    <aside>
      <h2>Watchlist</h2>
      <ul id="watchlist"></ul>
      <h2>重要性筛选</h2>
      <label><input type="checkbox" data-imp="high" checked> 🔴 高</label>
      <label><input type="checkbox" data-imp="medium" checked> 🟡 中</label>
      <label><input type="checkbox" data-imp="low"> 🟢 低</label>
    </aside>
    <section id="feed"></section>
  </main>
  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `style.css`**

```css
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, sans-serif; background: #0d1117; color: #c9d1d9; }
header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 24px; background: #161b22; border-bottom: 1px solid #21262d;
}
header h1 { font-size: 18px; }
.controls { display: flex; gap: 16px; align-items: center; font-size: 13px; }
main { display: grid; grid-template-columns: 220px 1fr; height: calc(100vh - 56px); }
aside { padding: 16px; background: #0d1117; border-right: 1px solid #21262d; }
aside h2 { font-size: 13px; margin: 12px 0 6px; color: #8b949e; text-transform: uppercase; }
aside ul { list-style: none; }
aside li { padding: 4px 0; font-size: 14px; }
aside label { display: block; font-size: 13px; padding: 4px 0; cursor: pointer; }
#feed { padding: 16px; overflow-y: auto; }
.card {
  background: #161b22; border-left: 4px solid #30363d; border-radius: 6px;
  padding: 12px 14px; margin-bottom: 10px; transition: background 1.5s;
}
.card.high { border-left-color: #f85149; }
.card.medium { border-left-color: #d29922; }
.card.low { border-left-color: #3fb950; }
.card.new { background: #1f6feb33; }
.card h3 { font-size: 14px; margin-bottom: 4px; }
.card .meta { font-size: 12px; color: #8b949e; }
.card a { color: #58a6ff; text-decoration: none; }
.card a:hover { text-decoration: underline; }
```

- [ ] **Step 3: Write `app.js`**

```javascript
const feed = document.getElementById('feed');
const summary = document.getElementById('summary');
const notifToggle = document.getElementById('notif-toggle');
const impChecks = document.querySelectorAll('aside input[data-imp]');

notifToggle.checked = localStorage.getItem('notif') === '1';
notifToggle.addEventListener('change', async () => {
  localStorage.setItem('notif', notifToggle.checked ? '1' : '0');
  if (notifToggle.checked && Notification.permission !== 'granted') {
    await Notification.requestPermission();
  }
});

impChecks.forEach(cb => cb.addEventListener('change', applyFilter));

function applyFilter() {
  const enabled = new Set(
    Array.from(impChecks).filter(c => c.checked).map(c => c.dataset.imp)
  );
  document.querySelectorAll('.card').forEach(el => {
    el.style.display = enabled.has(el.dataset.imp) ? '' : 'none';
  });
}

function formatTime(iso) {
  const d = new Date(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return '刚刚';
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`;
  return d.toLocaleDateString('zh-CN') + ' ' + d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

function renderCard(ev, isNew = false) {
  const el = document.createElement('div');
  el.className = `card ${ev.importance}${isNew ? ' new' : ''}`;
  el.dataset.imp = ev.importance;
  const dot = { high: '🔴', medium: '🟡', low: '🟢' }[ev.importance] || '⚪';
  const link = ev.url ? `<a href="${ev.url}" target="_blank">查看原文 ↗</a>` : '';
  el.innerHTML = `
    <h3>${dot} <strong>${ev.ticker}</strong> — ${escapeHtml(ev.title)}</h3>
    <div class="meta">${formatTime(ev.published_at)} · ${ev.source} · ${ev.event_type} ${link ? '· ' + link : ''}</div>
    ${ev.summary ? `<p class="summary">${escapeHtml(ev.summary)}</p>` : ''}
  `;
  if (isNew) setTimeout(() => el.classList.remove('new'), 2000);
  return el;
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

async function loadWatchlist() {
  const r = await fetch('/api/watchlist');
  const data = await r.json();
  document.getElementById('watchlist').innerHTML =
    data.tickers.map(t => `<li>${t}</li>`).join('');
}

async function loadHistory() {
  const r = await fetch('/api/events?limit=100');
  const data = await r.json();
  const highCount = data.events.filter(e => e.importance === 'high').length;
  summary.textContent = `今日 ${data.events.length} 条事件，其中 ${highCount} 条高重要性`;
  feed.innerHTML = '';
  data.events.forEach(e => feed.appendChild(renderCard(e)));
  applyFilter();
}

function connectStream() {
  const es = new EventSource('/stream');
  es.onmessage = (msg) => {
    const ev = JSON.parse(msg.data);
    feed.prepend(renderCard(ev, true));
    applyFilter();
    if (ev.importance === 'high' && notifToggle.checked
        && Notification.permission === 'granted') {
      new Notification(`${ev.ticker}: ${ev.title}`, { body: ev.summary || '' });
    }
  };
  es.onerror = () => {
    console.warn('SSE disconnected, will reconnect');
  };
}

(async () => {
  await loadWatchlist();
  await loadHistory();
  connectStream();
})();
```

- [ ] **Step 4: Commit**

```bash
git add stock-monitor/web/static/index.html stock-monitor/web/static/style.css stock-monitor/web/static/app.js
git commit -m "feat: add dashboard UI (HTML/CSS/JS with SSE client)"
```

---

## Task 15: Main App Entry

**Files:**
- Create: `stock-monitor/app.py`

- [ ] **Step 1: Implement `app.py`**

```python
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import config
from notifier import Notifier
from scheduler import build_pipeline, start_scheduler
from sources.sec_edgar import SecEdgarSource
from storage import Storage
from watchlist_manager import WatchlistManager
from web.routes import build_router


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage: Storage = app.state.storage
    storage.init_schema()
    storage.cleanup(config.RETAIN_DAYS)

    sec_source: SecEdgarSource = app.state.sec_source
    await sec_source.load_ticker_map()

    pipeline = app.state.pipeline
    # initial run
    try:
        await pipeline.run_once()
    except Exception as e:
        log.exception("initial pipeline run failed: %s", e)

    scheduler = start_scheduler(pipeline, storage)
    app.state.scheduler = scheduler

    log.info("startup complete on port %d", config.PORT)
    yield
    scheduler.shutdown()


def create_app() -> FastAPI:
    storage = Storage(config.DB_PATH)
    notifier = Notifier()
    watchlist = WatchlistManager(config.WATCHLIST_PATH)
    sec_source = SecEdgarSource()
    pipeline = build_pipeline(storage, notifier, watchlist.tickers(), sec_source)

    app = FastAPI(title="Stock Event Monitor", lifespan=lifespan)
    app.state.storage = storage
    app.state.notifier = notifier
    app.state.watchlist = watchlist
    app.state.sec_source = sec_source
    app.state.pipeline = pipeline

    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "web" / "static"), name="static")
    app.include_router(build_router(storage, notifier, watchlist))
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=config.PORT, reload=False)
```

- [ ] **Step 2: Run the full test suite**

```bash
cd /Users/mabizheng/Desktop/美股/stock-monitor
source .venv/bin/activate
PYTHONPATH=. pytest -v
```

Expected: All tests pass (roughly 30+ tests across 8 files).

- [ ] **Step 3: Commit**

```bash
git add stock-monitor/app.py
git commit -m "feat: add FastAPI app entry wiring everything together"
```

---

## Task 16: End-to-End Manual Verification

**Files:** none (manual test)

- [ ] **Step 1: Start the server**

```bash
cd /Users/mabizheng/Desktop/美股/stock-monitor
source .venv/bin/activate
PYTHONPATH=. python app.py
```

Expected logs:
```
[INFO] app: startup complete on port 8000
[INFO] scheduler: scheduler started
[INFO] pipeline: pipeline inserted N events
```

- [ ] **Step 2: Open dashboard**

In a browser: `http://localhost:8000`

Expected:
- Header shows "今日 N 条事件..."
- Left sidebar lists EOSE, MDB, NVDA
- Event cards display with 🔴/🟡/🟢 color borders
- Event metadata (time, source, type, link) renders correctly

- [ ] **Step 3: Verify API endpoints**

Run in a second terminal:
```bash
curl -s http://localhost:8000/healthz
curl -s http://localhost:8000/api/watchlist
curl -s "http://localhost:8000/api/events?limit=5" | head -c 500
```

Expected: All return valid JSON. `/api/events` returns event records.

- [ ] **Step 4: Verify SSE stream**

```bash
curl -N http://localhost:8000/stream
```

Expected: Connection stays open, keepalive `: ping` comments appear every ~15s. If a new event hits in the background, a `data: {...}` line appears.

- [ ] **Step 5: Verify browser notification**

- Toggle "🔔 通知" checkbox in dashboard → allow notification permission in browser prompt
- Wait for a high-importance event (or insert one manually via sqlite3 + trigger notifier publish if needed for test)
- Expected: Desktop notification appears with ticker + title

- [ ] **Step 6: Verify dedup**

- Stop and restart the server
- Expected: No duplicate events appear in the dashboard (check `SELECT COUNT(*), source, external_id FROM events GROUP BY source, external_id HAVING COUNT(*) > 1;` returns zero rows)

- [ ] **Step 7: Final commit**

```bash
cd /Users/mabizheng/Desktop/美股
git add docs/superpowers/plans/2026-04-18-us-stock-event-monitor.md
git commit -m "docs: add implementation plan for stock event monitor"
```

---

## Self-Review Checklist

- [x] Spec coverage: all 10 spec sections map to tasks
  - §2 tech stack → Task 1
  - §3 data flow → Tasks 11, 12
  - §4.1 directory → Task 1
  - §4.2 Event + Source → Task 2
  - §4.3 three sources → Tasks 7, 8, 9
  - §4.4 scorer → Task 5
  - §4.5 dedup → Task 6
  - §4.6 storage → Task 3
  - §4.7 SSE notifier → Task 10
  - §4.8 API routes → Task 13
  - §5 Dashboard UI → Task 14
  - §6 config → Task 1
  - §7 error handling → scattered through sources (exception swallowing), storage (INSERT OR IGNORE via UNIQUE), routes (SSE disconnect), watchlist
  - §8 testing → each source/module task has tests
  - §9 milestones → tasks ordered per M1–M6
  - §10 defaults → enforced in config.py and app.py

- [x] No "TBD", "TODO", or placeholder code — every step has runnable code or exact commands
- [x] Type consistency — `Event` fields used consistently (`external_id`, `event_type`, `importance`), `Source.fetch` signature matches across all three sources
- [x] Watchlist edit flow (file-based) matches spec §10
- [x] `importance` scoring runs in pipeline, not in sources (per §4.3 data flow)
