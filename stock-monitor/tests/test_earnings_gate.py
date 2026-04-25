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
    ts = datetime(2026, 4, 30, 14, 0, tzinfo=_ET)
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
    assert "?" in reason


def test_utc_input_converted_to_et(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_ENABLED", True)
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_BEFORE_MIN", 990)
    monkeypatch.setattr(config, "EARNINGS_BLACKOUT_AFTER_MIN", 1080)
    s = _storage(tmp_path)
    _seed(s, date="2026-04-30", hour="amc")
    # 2026-04-30 18:00 UTC = 14:00 ET (DST)
    ts_utc = datetime(2026, 4, 30, 18, 0, tzinfo=timezone.utc)
    blocked, _ = in_earnings_blackout(s, "AAPL", ts_utc)
    assert blocked is True
