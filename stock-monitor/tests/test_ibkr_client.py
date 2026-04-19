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
