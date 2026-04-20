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

CREATE TABLE IF NOT EXISTS paper_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TIMESTAMP NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    qty INTEGER NOT NULL,
    price REAL NOT NULL,
    reason TEXT NOT NULL,
    pnl REAL,
    signal_id INTEGER,
    rr REAL
);
CREATE INDEX IF NOT EXISTS idx_paper_trades_ts ON paper_trades(ts DESC);
CREATE INDEX IF NOT EXISTS idx_paper_trades_ticker_ts ON paper_trades(ticker, ts DESC);

CREATE TABLE IF NOT EXISTS paper_equity (
    ts TIMESTAMP PRIMARY KEY,
    cash REAL NOT NULL,
    positions_value REAL NOT NULL,
    equity REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_positions (
    ticker TEXT PRIMARY KEY,
    side TEXT NOT NULL DEFAULT 'long',
    qty INTEGER NOT NULL,
    entry_price REAL NOT NULL,
    entry_ts TIMESTAMP NOT NULL,
    sl REAL NOT NULL,
    tp REAL NOT NULL,
    reason TEXT NOT NULL,
    signal_id INTEGER,
    mark_price REAL NOT NULL,
    updated_at TIMESTAMP NOT NULL
);
"""


class Storage:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    @property
    def db_path(self) -> str:
        return self._db_path

    def backup_to(self, dest_path: str) -> str:
        """Create a hot copy of the database using SQLite's online backup API.

        Works while the app continues to read/write (WAL-friendly). Returns the
        absolute path of the backup file that was written.
        """
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Use a fresh dest connection so we don't alter our main connection.
        with sqlite3.connect(str(dest)) as dest_conn:
            self._conn.backup(dest_conn)
        return str(dest.resolve())

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
        pos_cols = {
            r["name"] for r in self._conn.execute("PRAGMA table_info(paper_positions)").fetchall()
        }
        if pos_cols and "side" not in pos_cols:
            self._conn.execute(
                "ALTER TABLE paper_positions ADD COLUMN side TEXT NOT NULL DEFAULT 'long'"
            )
        self._conn.commit()

    def exists(self, source: str, external_id: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM events WHERE source=? AND external_id=? LIMIT 1",
            (source, external_id),
        )
        return cur.fetchone() is not None

    def insert(self, event: Event) -> bool:
        """Returns True if inserted, False if duplicate."""
        inserted, _ = self.insert_with_id(event)
        return inserted

    def insert_with_id(self, event: Event) -> tuple[bool, int | None]:
        """Returns (inserted, id). On duplicates, returns (False, existing_id)."""
        try:
            cur = self._conn.execute(
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
            return True, cur.lastrowid
        except sqlite3.IntegrityError:
            return False, self.get_event_id(event.source, event.external_id)

    def get_event_id(self, source: str, external_id: str) -> int | None:
        row = self._conn.execute(
            "SELECT id FROM events WHERE source=? AND external_id=? LIMIT 1",
            (source, external_id),
        ).fetchone()
        return int(row["id"]) if row is not None else None

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

    def upsert_paper_position(
        self,
        *,
        ticker: str,
        side: str = "long",
        qty: int,
        entry_price: float,
        entry_ts: datetime,
        sl: float,
        tp: float,
        reason: str,
        signal_id: int | None,
        mark_price: float,
        updated_at: datetime,
    ) -> None:
        self._conn.execute(
            """INSERT INTO paper_positions
               (ticker, side, qty, entry_price, entry_ts, sl, tp, reason, signal_id, mark_price, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(ticker) DO UPDATE SET
                 side=excluded.side,
                 qty=excluded.qty,
                 entry_price=excluded.entry_price,
                 entry_ts=excluded.entry_ts,
                 sl=excluded.sl,
                 tp=excluded.tp,
                 reason=excluded.reason,
                 signal_id=excluded.signal_id,
                 mark_price=excluded.mark_price,
                 updated_at=excluded.updated_at
            """,
            (
                ticker,
                side,
                qty,
                entry_price,
                entry_ts.isoformat(),
                sl,
                tp,
                reason,
                signal_id,
                mark_price,
                updated_at.isoformat(),
            ),
        )
        self._conn.commit()

    def delete_paper_position(self, ticker: str) -> None:
        self._conn.execute("DELETE FROM paper_positions WHERE ticker=?", (ticker,))
        self._conn.commit()

    def list_paper_positions(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM paper_positions ORDER BY updated_at DESC, ticker ASC"
        ).fetchall()
        out = []
        for row in rows:
            d = dict(row)
            out.append(d)
        return out

    def insert_paper_trade(
        self,
        *,
        ts: datetime,
        ticker: str,
        side: str,
        qty: int,
        price: float,
        reason: str,
        pnl: float | None = None,
        signal_id: int | None = None,
        rr: float | None = None,
    ) -> int:
        cur = self._conn.execute(
            """INSERT INTO paper_trades
               (ts, ticker, side, qty, price, reason, pnl, signal_id, rr)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ts.isoformat(),
                ticker,
                side,
                qty,
                price,
                reason,
                pnl,
                signal_id,
                rr,
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def list_paper_trades(
        self, *, ticker: str | None = None, limit: int = 200
    ) -> list[dict]:
        sql = "SELECT * FROM paper_trades WHERE 1=1"
        params: list = []
        if ticker:
            sql += " AND ticker = ?"
            params.append(ticker)
        sql += " ORDER BY ts DESC, id DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def record_paper_equity(
        self, *, ts: datetime, cash: float, positions_value: float, equity: float
    ) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO paper_equity (ts, cash, positions_value, equity)
               VALUES (?, ?, ?, ?)""",
            (ts.isoformat(), cash, positions_value, equity),
        )
        self._conn.commit()

    def list_paper_equity(self, limit: int = 200) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM paper_equity ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def last_paper_equity(self) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM paper_equity ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row is not None else None

    def first_paper_equity_on_or_after(self, ts: datetime) -> dict | None:
        """Earliest equity snapshot on or after `ts` (used as day-open baseline)."""
        row = self._conn.execute(
            "SELECT * FROM paper_equity WHERE ts >= ? ORDER BY ts ASC LIMIT 1",
            (ts.isoformat(),),
        ).fetchone()
        return dict(row) if row is not None else None

    def last_paper_equity_before(self, ts: datetime) -> dict | None:
        """Latest equity snapshot strictly before `ts` (previous-session close)."""
        row = self._conn.execute(
            "SELECT * FROM paper_equity WHERE ts < ? ORDER BY ts DESC LIMIT 1",
            (ts.isoformat(),),
        ).fetchone()
        return dict(row) if row is not None else None

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
