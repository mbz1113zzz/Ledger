import importlib
import json
import tempfile
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


class _DummyScheduler:
    def shutdown(self):
        pass


@pytest.fixture
def client(monkeypatch):
    async def _noop_async(*args, **kwargs):
        return None

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    watch = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    watch.write(json.dumps({"tickers": ["AAPL"]}).encode())
    watch.close()
    monkeypatch.setenv("DB_PATH", tmp.name)
    monkeypatch.setenv("WATCHLIST_PATH", watch.name)
    monkeypatch.setenv("IBKR_ENABLED", "0")
    import config
    importlib.reload(config)
    import app as app_module
    importlib.reload(app_module)
    monkeypatch.setattr(app_module, "start_scheduler", lambda *args, **kwargs: _DummyScheduler())
    monkeypatch.setattr(app_module, "build_runner_if_enabled", lambda **kwargs: None)
    app_module.app.state.sec_source.load_ticker_map = _noop_async
    app_module.app.state.pipeline.run_once = _noop_async
    app_module.app.state.price_pipeline.run_once = _noop_async
    # Seed an upcoming earnings row directly via the live storage handle.
    app_module.app.state.storage.upsert_earnings(
        ticker="AAPL", scheduled_date="2026-05-01", scheduled_hour="amc",
        eps_estimate=1.0, eps_actual=None, rev_estimate=1.0, rev_actual=None,
        status="scheduled",
        updated_at=datetime(2026, 4, 25, 0, 0, tzinfo=timezone.utc),
    )
    c = TestClient(app_module.app)
    with c:
        yield c


def test_upcoming_earnings_returns_list(client):
    resp = client.get("/api/earnings/upcoming?from=2026-04-30&to=2026-05-05")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert any(r["ticker"] == "AAPL" and r["scheduled_date"] == "2026-05-01" for r in body)


def test_upcoming_earnings_excludes_stale(client):
    import app as app_module
    app_module.app.state.storage.upsert_earnings(
        ticker="OLD", scheduled_date="2026-01-01", scheduled_hour="amc",
        eps_estimate=1.0, eps_actual=None, rev_estimate=1.0, rev_actual=None,
        status="scheduled",
        updated_at=datetime(2025, 12, 1, 0, 0, tzinfo=timezone.utc),
    )
    app_module.app.state.storage.mark_stale_scheduled_before("2026-04-25")
    resp = client.get("/api/earnings/upcoming?from=2025-12-01&to=2026-12-31")
    body = resp.json()
    assert all(r["ticker"] != "OLD" for r in body)
