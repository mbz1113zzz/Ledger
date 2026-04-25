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
