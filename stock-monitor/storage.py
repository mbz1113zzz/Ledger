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
    summary_cn TEXT,
    raw_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_ticker_time ON events(ticker, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_importance_time ON events(importance, published_at DESC);

CREATE TABLE IF NOT EXISTS smc_structure (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TIMESTAMP NOT NULL,
    ticker TEXT NOT NULL,
    tf TEXT NOT NULL,
    kind TEXT NOT NULL,
    price REAL NOT NULL,
    ref_id INTEGER,
    meta_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_smc_ticker_ts ON smc_structure(ticker, ts DESC);
"""


class Storage:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def init_schema(self) -> None:
        # WAL mode: readers never block writers; enables concurrent access
        # between the scheduler thread and FastAPI request threads.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(SCHEMA)
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(events)").fetchall()}
        if "summary_cn" not in cols:
            self._conn.execute("ALTER TABLE events ADD COLUMN summary_cn TEXT")
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
                    published_at, importance, summary_cn, raw_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    event.summary_cn,
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

    def query_since(self, since: datetime, *, min_importance: str = "medium") -> list[Event]:
        rank = {"low": 0, "medium": 1, "high": 2}
        min_rank = rank.get(min_importance, 1)
        allowed = [k for k, v in rank.items() if v >= min_rank]
        placeholders = ",".join(["?"] * len(allowed))
        sql = (
            f"SELECT * FROM events WHERE published_at >= ? "
            f"AND importance IN ({placeholders}) "
            "ORDER BY ticker ASC, published_at DESC"
        )
        rows = self._conn.execute(sql, [since.isoformat(), *allowed]).fetchall()
        return [self._row_to_event(r) for r in rows]

    def cleanup(self, retain_days: int) -> int:
        cur = self._conn.execute(
            f"DELETE FROM events WHERE created_at < datetime('now', '-{int(retain_days)} days')"
        )
        self._conn.commit()
        return cur.rowcount

    def insert_smc_structure(
        self, *, ticker: str, tf: str, kind: str, price: float,
        ts: datetime, ref_id: int | None = None, meta: dict | None = None,
    ) -> int:
        cur = self._conn.execute(
            """INSERT INTO smc_structure (ts, ticker, tf, kind, price, ref_id, meta_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (ts.isoformat(), ticker, tf, kind, price, ref_id,
             json.dumps(meta or {})),
        )
        self._conn.commit()
        return cur.lastrowid

    def query_smc_structure(
        self, *, ticker: str | None = None, kind: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        sql = "SELECT * FROM smc_structure WHERE 1=1"
        params: list = []
        if ticker:
            sql += " AND ticker = ?"
            params.append(ticker)
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["meta"] = json.loads(d.pop("meta_json") or "{}")
            out.append(d)
        return out

    def _row_to_event(self, row: sqlite3.Row) -> Event:
        keys = row.keys()
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
            summary_cn=row["summary_cn"] if "summary_cn" in keys else None,
        )
