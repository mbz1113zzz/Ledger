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
