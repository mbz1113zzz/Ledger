"""Daily SQLite backup helper.

Writes a hot copy of the database to `<db_dir>/backups/events-YYYY-MM-DD.db`
using SQLite's online backup API (safe while the app is running under WAL).
Old backups beyond `keep_days` are pruned.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from storage import Storage

log = logging.getLogger(__name__)


def _backup_dir(db_path: str) -> Path:
    return Path(db_path).resolve().parent / "backups"


def backup_database(storage: Storage, *, keep_days: int = 14,
                    now: datetime | None = None) -> str | None:
    """Run one backup + prune cycle. Returns the backup path, or None on error."""
    now = now or datetime.now(timezone.utc)
    backups = _backup_dir(storage.db_path)
    dest = backups / f"events-{now.date().isoformat()}.db"
    try:
        path = storage.backup_to(str(dest))
        log.info("sqlite backup written: %s", path)
    except Exception as e:
        log.exception("sqlite backup failed: %s", e)
        return None
    _prune_old_backups(backups, keep_days=keep_days, now=now)
    return path


def _prune_old_backups(backups: Path, *, keep_days: int, now: datetime) -> None:
    if not backups.exists():
        return
    cutoff = (now - timedelta(days=keep_days)).date()
    for p in backups.glob("events-*.db"):
        stem = p.stem.replace("events-", "")
        try:
            day = datetime.fromisoformat(stem).date()
        except ValueError:
            continue
        if day < cutoff:
            try:
                p.unlink()
                log.info("pruned old backup: %s", p.name)
            except OSError as e:
                log.warning("failed to prune %s: %s", p, e)
