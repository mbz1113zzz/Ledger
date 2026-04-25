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
