import importlib
import json
import tempfile

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
    watch.write(json.dumps({"tickers": ["NVDA"]}).encode())
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


def test_diagnostics_route_returns_startup_sources_and_pipeline_data(client):
    r = client.get("/api/diagnostics")
    assert r.status_code == 200
    body = r.json()
    assert "startup" in body
    assert "sources" in body
    assert "news_pipeline" in body
    assert isinstance(body["sources"], list)
    assert body["startup"]["status"] in {"idle", "running", "ok"}
    assert body["news_pipeline"]["ticker_count"] == 1
    assert body["news_pipeline"]["tickers"] == ["NVDA"]
    assert "ibkr" in body
    assert "execution" in body
    assert body["sources"]
    assert "request_count" in body["sources"][0]
