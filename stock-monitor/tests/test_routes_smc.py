import importlib
import json
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock

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
    watch.write(json.dumps({"tickers": ["NVDA", "TSLA"]}).encode())
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
    c = TestClient(app_module.app)
    with c:
        yield c


def test_smc_structure_returns_recent_events(client):
    import app as am
    s = am.app.state.storage
    s.insert_smc_structure(
        ticker="NVDA", tf="5m", kind="bos_up", price=105.0,
        ts=datetime(2026, 4, 19, 14, 30, tzinfo=timezone.utc),
        ref_id=None, meta={"trend": "up"},
    )
    r = client.get("/api/smc/structure?ticker=NVDA")
    assert r.status_code == 200
    body = r.json()
    assert body["events"][0]["kind"] == "bos_up"


def test_paper_routes_return_positions_trades_and_equity(client):
    import app as am

    broker = am.app.state.paper_broker
    s = am.app.state.storage
    ts = datetime(2026, 4, 19, 14, 30, tzinfo=timezone.utc)
    s.record_paper_equity(ts=ts, cash=10_000.0, positions_value=0.0, equity=10_000.0)
    broker.ledger.snapshot(ts)

    r1 = client.get("/api/paper/positions")
    r2 = client.get("/api/paper/trades")
    r3 = client.get("/api/paper/equity")

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 200
    assert "positions" in r1.json()
    assert "trades" in r2.json()
    assert "equity" in r3.json()
    r4 = client.get("/api/paper/stats")
    assert r4.status_code == 200
    assert "rows" in r4.json()


def test_watchlist_mutation_updates_streaming_runner(client):
    import app as am

    fake_runner = MagicMock()
    am.app.state.streaming_runner = fake_runner
    r = client.post("/api/watchlist", json={"ticker": "AAPL"})
    assert r.status_code == 200
    fake_runner.set_tickers.assert_called()

    r2 = client.delete("/api/watchlist/AAPL")
    assert r2.status_code == 200
    assert fake_runner.set_tickers.call_count >= 2


def test_paper_review_route_returns_markdown_payload(client):
    import app as am

    broker = am.app.state.paper_broker
    ts = datetime(2026, 4, 19, 14, 30, tzinfo=timezone.utc)
    sig = type("Sig", (), {
        "ts": ts, "ticker": "NVDA", "reason": "smc_bos_ob",
        "entry": 100.0, "sl": 99.0, "tp": 102.0,
    })()
    am.app.state.storage.insert_paper_trade(
        ts=ts, ticker="NVDA", side="buy", qty=20, price=100.0,
        reason="smc_bos_ob", signal_id=1,
    )
    broker.ledger.snapshot(ts)
    am.app.state.storage.insert_paper_trade(
        ts=ts.replace(hour=15), ticker="NVDA", side="sell", qty=20, price=102.0,
        reason="tp", pnl=40.0, signal_id=1, rr=2.0,
    )
    broker.ledger.snapshot(ts.replace(hour=15))
    r = client.get("/api/paper/review?date=2026-04-19")
    assert r.status_code == 200
    body = r.json()
    assert body["date"] == "2026-04-19"
    assert "Daily Review" in body["body"]


def test_chart_route_returns_candles_structures_and_trades(client, monkeypatch):
    import app as am
    import backtest as backtest_module

    async def fake_chart_candles(self, ticker, start, end, interval="5m"):
        return [
            {"ts": "2026-04-19T14:30:00+00:00", "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5, "v": 1000.0},
            {"ts": "2026-04-19T14:35:00+00:00", "o": 100.5, "h": 102.0, "l": 100.0, "c": 101.5, "v": 900.0},
        ]

    monkeypatch.setattr(backtest_module.YahooPriceFetcher, "chart_candles", fake_chart_candles)
    s = am.app.state.storage
    ts = datetime(2026, 4, 19, 14, 35, tzinfo=timezone.utc)
    s.insert_smc_structure(
        ticker="NVDA", tf="5m", kind="bos_up", price=101.2,
        ts=ts, ref_id=None, meta={}
    )
    s.insert_paper_trade(
        ts=ts, ticker="NVDA", side="buy", qty=10, price=101.5,
        reason="smc_bos_ob", signal_id=8,
    )
    s.record_paper_equity(ts=ts, cash=9000.0, positions_value=1015.0, equity=10015.0)
    r = client.get("/api/chart?ticker=NVDA&interval=5m&range_days=5")
    assert r.status_code == 200
    body = r.json()
    assert len(body["candles"]) == 2
    assert body["structures"][0]["kind"] == "bos_up"
    assert body["trades"][0]["side"] == "buy"
    assert body["equity"][0]["equity"] == 10015.0
