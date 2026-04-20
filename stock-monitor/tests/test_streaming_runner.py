import tempfile
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from notifier import Notifier
from storage import Storage
from streaming.runner import StreamingRunner, build_runner_if_enabled


def _storage():
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    s = Storage(tmp.name)
    s.init_schema()
    return s


async def test_tick_triggers_anomaly_persist():
    s = _storage()
    n = Notifier()
    fake_client = MagicMock()
    fake_client.connect_with_retry = AsyncMock()
    fake_client.set_tickers = MagicMock()
    runner = StreamingRunner(
        client=fake_client, storage=s, notifier=n, push_hub=None,
        tickers=["NVDA"],
        tiers=[("medium", 0.01), ("high", 0.03)],
        cooldown_sec=300,
    )
    await runner.start()
    ts0 = datetime(2026, 4, 19, 14, 30, 0, tzinfo=timezone.utc)
    runner._buf.set_open("NVDA", 100.0, ts0)
    runner._buf.update("NVDA", 100.0, ts0)
    ts1 = datetime(2026, 4, 19, 14, 31, 5, tzinfo=timezone.utc)
    await runner.on_tick("NVDA", 101.2, ts1)
    evs = s.query(ticker="NVDA", limit=10)
    assert any(e.importance == "medium" for e in evs)


async def test_bar_feeds_smc_pipeline():
    s = _storage()
    fake_client = MagicMock()
    fake_client.connect_with_retry = AsyncMock()
    fake_client.set_tickers = MagicMock()
    runner = StreamingRunner(
        client=fake_client, storage=s, notifier=Notifier(), push_hub=None,
        tickers=["NVDA"],
        tiers=[("high", 0.03)],
        cooldown_sec=300,
    )
    await runner.start()
    base = datetime(2026, 4, 19, 14, 0, 0, tzinfo=timezone.utc)
    for minute in range(6):
        for sec in range(0, 60, 5):
            ts = base.replace(minute=minute, second=sec)
            await runner.on_bar("NVDA", {"ts": ts, "o": 100, "h": 101,
                                          "l": 99, "c": 100, "v": 100})
    ts = base.replace(minute=6, second=0)
    await runner.on_bar("NVDA", {"ts": ts, "o": 100, "h": 100,
                                 "l": 100, "c": 100, "v": 100})
    rows = s.query_smc_structure(ticker="NVDA")
    assert isinstance(rows, list)


async def test_runner_tolerates_ibkr_disabled(monkeypatch):
    import config
    monkeypatch.setattr(config, "IBKR_ENABLED", False)
    r = build_runner_if_enabled(storage=None, notifier=None, push_hub=None,
                                tickers=["NVDA"])
    assert r is None


async def test_start_times_out_when_ibkr_unavailable():
    s = _storage()
    async def hang_forever():
        await asyncio.sleep(60)

    fake_client = MagicMock()
    fake_client.connect_with_retry = AsyncMock(side_effect=hang_forever)
    fake_client.set_tickers = MagicMock()
    fake_client.on_tick = MagicMock()
    fake_client.on_bar = MagicMock()
    runner = StreamingRunner(
        client=fake_client, storage=s, notifier=Notifier(), push_hub=None,
        tickers=["NVDA"],
        tiers=[("high", 0.03)],
        cooldown_sec=300,
        startup_timeout_sec=0.01,
    )
    await runner.start()
    fake_client.set_tickers.assert_not_called()
