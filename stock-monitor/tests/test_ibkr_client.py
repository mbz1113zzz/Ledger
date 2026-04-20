from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sources.ibkr_realtime import IbkrClient


async def test_connect_calls_ib_connect_async():
    fake_ib = MagicMock()
    fake_ib.connectAsync = AsyncMock()
    fake_ib.isConnected = MagicMock(return_value=True)
    with patch("sources.ibkr_realtime.IB", return_value=fake_ib):
        client = IbkrClient(host="127.0.0.1", port=7497, client_id=42)
        await client.connect()
    fake_ib.connectAsync.assert_awaited_once_with(
        host="127.0.0.1", port=7497, clientId=42
    )


async def test_subscribe_ticker_calls_reqmktdata_and_realtime_bars():
    fake_ib = MagicMock()
    fake_ib.connectAsync = AsyncMock()
    fake_ib.isConnected = MagicMock(return_value=True)
    fake_ib.reqMktData = MagicMock(return_value=MagicMock())
    fake_ib.reqRealTimeBars = MagicMock(return_value=MagicMock())
    with patch("sources.ibkr_realtime.IB", return_value=fake_ib):
        with patch("sources.ibkr_realtime.Stock") as stock:
            stock.return_value = "nvda_contract"
            client = IbkrClient(host="127.0.0.1", port=7497, client_id=42)
            await client.connect()
            client.subscribe("NVDA")
    fake_ib.reqMktData.assert_called_once()
    fake_ib.reqRealTimeBars.assert_called_once()


async def test_unsubscribe_cancels_both_streams():
    fake_ib = MagicMock()
    fake_ib.connectAsync = AsyncMock()
    fake_ib.isConnected = MagicMock(return_value=True)
    fake_ib.reqMktData = MagicMock(return_value="tick_handle")
    fake_ib.reqRealTimeBars = MagicMock(return_value="bar_handle")
    fake_ib.cancelMktData = MagicMock()
    fake_ib.cancelRealTimeBars = MagicMock()
    with patch("sources.ibkr_realtime.IB", return_value=fake_ib):
        with patch("sources.ibkr_realtime.Stock", return_value="nvda"):
            client = IbkrClient(host="127.0.0.1", port=7497, client_id=42)
            await client.connect()
            client.subscribe("NVDA")
            client.unsubscribe("NVDA")
    fake_ib.cancelMktData.assert_called_once()
    fake_ib.cancelRealTimeBars.assert_called_once()


async def test_reconnect_uses_exponential_backoff(monkeypatch):
    sleeps = []

    async def fake_sleep(t):
        sleeps.append(t)

    call_count = {"n": 0}

    async def connect_async(**kw):
        call_count["n"] += 1
        if call_count["n"] < 4:
            raise ConnectionError("nope")

    fake_ib = MagicMock()
    fake_ib.connectAsync = AsyncMock(side_effect=connect_async)
    fake_ib.isConnected = MagicMock(return_value=False)
    monkeypatch.setattr("sources.ibkr_realtime.asyncio.sleep", fake_sleep)
    with patch("sources.ibkr_realtime.IB", return_value=fake_ib):
        client = IbkrClient(host="127.0.0.1", port=7497, client_id=42,
                            max_backoff_sec=10)
        await client.connect_with_retry(max_attempts=4)
    assert sleeps == [1, 2, 4]
    assert call_count["n"] == 4


def test_handle_tick_falls_back_to_marketPrice_when_last_missing():
    got = []
    client = IbkrClient(host="x", port=1, client_id=1)
    client.on_tick(lambda t, p, ts: got.append((t, p)))
    # `last` is NaN (ib_insync default for no trades yet), marketPrice has value
    obj = SimpleNamespace(last=float("nan"), marketPrice=123.45, close=None)
    client._handle_tick("NVDA", obj)
    assert got == [("NVDA", 123.45)]


def test_handle_tick_tolerates_all_missing():
    client = IbkrClient(host="x", port=1, client_id=1)
    called = []
    client.on_tick(lambda t, p, ts: called.append((t, p)))
    obj = SimpleNamespace(last=None, marketPrice=None, close=None, bid=None, ask=None)
    client._handle_tick("NVDA", obj)  # should not raise
    assert called == []


def test_handle_bar_accepts_open_instead_of_open_():
    import datetime as dt
    got = []
    client = IbkrClient(host="x", port=1, client_id=1)
    client.on_bar(lambda t, b: got.append((t, b)))
    bar = SimpleNamespace(
        time=dt.datetime(2026, 4, 20, 14, 30, 0),
        # open (no trailing underscore) — future ib_insync variant
        open=10.0, high=11.0, low=9.5, close=10.5, volume=100,
    )
    client._handle_bar("NVDA", [bar], True)
    assert len(got) == 1
    assert got[0][1]["o"] == 10.0
