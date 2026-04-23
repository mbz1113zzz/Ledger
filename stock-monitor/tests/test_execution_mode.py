import tempfile
from datetime import datetime, timezone

from paper.execution import ExecutionModeController
from storage import Storage


def _storage():
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    s = Storage(tmp.name)
    s.init_schema()
    return s


def test_live_mode_is_blocked_without_readiness_and_live_lane():
    storage = _storage()
    ctrl = ExecutionModeController(storage=storage, initial_mode="paper")
    ok, body = ctrl.set_mode("live")
    assert ok is False
    assert body["error"] == "live mode is locked"
    assert body["readiness"]["blockers"]


def test_dry_live_mode_switches_without_live_readiness():
    storage = _storage()
    ctrl = ExecutionModeController(storage=storage, initial_mode="paper")
    ok, body = ctrl.set_mode("dry_live")
    assert ok is True
    assert body["mode"] == "dry_live"


def test_live_mode_unlocks_when_thresholds_are_met():
    storage = _storage()
    for idx in range(5):
        ts = datetime(2026, 4, 19, 14, idx, tzinfo=timezone.utc)
        storage.insert_paper_trade(
            ts=ts,
            ticker="NVDA",
            side="buy",
            qty=10,
            price=100.0,
            reason="smc_bos_ob",
            signal_id=idx,
        )
        storage.insert_paper_trade(
            ts=ts.replace(minute=idx + 10),
            ticker="NVDA",
            side="sell",
            qty=10,
            price=102.0,
            reason="tp",
            pnl=20.0,
            signal_id=idx,
            rr=2.0,
        )
    ctrl = ExecutionModeController(
        storage=storage,
        initial_mode="paper",
        live_trading_enabled=True,
        live_execution_available=True,
        min_closed_trades=5,
        min_win_rate_pct=50.0,
        min_avg_rr=1.0,
    )
    ok, body = ctrl.set_mode("live")
    assert ok is True
    assert body["mode"] == "live"
