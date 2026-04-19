import importlib
import tempfile
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    monkeypatch.setenv("DB_PATH", tmp.name)
    import config
    importlib.reload(config)
    import app as app_module
    importlib.reload(app_module)
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
