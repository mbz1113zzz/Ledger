import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backup import backup_database
from storage import Storage


def _storage():
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    s = Storage(tmp.name)
    s.init_schema()
    return s


def test_backup_writes_file_and_copies_data():
    s = _storage()
    s.record_paper_equity(
        ts=datetime(2026, 4, 19, 14, 0, tzinfo=timezone.utc),
        cash=10_000, positions_value=0, equity=10_000,
    )
    now = datetime(2026, 4, 20, 3, 30, tzinfo=timezone.utc)
    path = backup_database(s, keep_days=14, now=now)
    assert path is not None
    assert Path(path).exists()
    # Backup file is a valid SQLite db containing our row.
    with sqlite3.connect(path) as c:
        rows = c.execute("SELECT equity FROM paper_equity").fetchall()
    assert rows and rows[0][0] == 10_000


def test_backup_prunes_files_older_than_keep_days():
    s = _storage()
    now = datetime(2026, 4, 20, 3, 30, tzinfo=timezone.utc)
    backup_dir = Path(s.db_path).resolve().parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    # Seed a stale file (30 days old) that must be pruned.
    stale = backup_dir / f"events-{(now - timedelta(days=30)).date().isoformat()}.db"
    stale.write_bytes(b"")
    # And a recent one that must survive.
    recent = backup_dir / f"events-{(now - timedelta(days=2)).date().isoformat()}.db"
    recent.write_bytes(b"")
    backup_database(s, keep_days=14, now=now)
    assert not stale.exists()
    assert recent.exists()
