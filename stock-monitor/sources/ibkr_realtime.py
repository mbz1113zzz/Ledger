from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable

from ib_insync import IB, Stock

log = logging.getLogger(__name__)


class IbkrClient:
    def __init__(self, host: str, port: int, client_id: int,
                 max_backoff_sec: int = 60):
        self._host = host
        self._port = port
        self._client_id = client_id
        self._max_backoff = max_backoff_sec
        self._ib = IB()
        self._tick_handles: dict[str, object] = {}
        self._bar_handles: dict[str, object] = {}
        self._on_tick: Callable[[str, float, datetime], None] | None = None
        self._on_bar: Callable[[str, dict], None] | None = None

    def on_tick(self, cb: Callable[[str, float, datetime], None]) -> None:
        self._on_tick = cb

    def on_bar(self, cb: Callable[[str, dict], None]) -> None:
        self._on_bar = cb

    async def connect(self) -> None:
        await self._ib.connectAsync(host=self._host, port=self._port,
                                    clientId=self._client_id)

    async def connect_with_retry(self, max_attempts: int = 1_000_000) -> None:
        delay = 1
        attempt = 0
        while attempt < max_attempts:
            try:
                await self._ib.connectAsync(host=self._host, port=self._port,
                                            clientId=self._client_id)
                return
            except Exception as e:
                attempt += 1
                if attempt >= max_attempts:
                    raise
                log.warning("IBKR connect failed (%s); retry in %ds", e, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._max_backoff)

    def subscribe(self, ticker: str) -> None:
        if ticker in self._tick_handles:
            return
        contract = Stock(ticker, "SMART", "USD")
        tick_handle = self._ib.reqMktData(contract, "", False, False)
        bar_handle = self._ib.reqRealTimeBars(contract, 5, "TRADES", False)
        self._tick_handles[ticker] = tick_handle
        self._bar_handles[ticker] = bar_handle
        if hasattr(tick_handle, "updateEvent"):
            tick_handle.updateEvent += lambda t: self._handle_tick(ticker, t)
        if hasattr(bar_handle, "updateEvent"):
            bar_handle.updateEvent += lambda bars, has_new: self._handle_bar(ticker, bars, has_new)

    def unsubscribe(self, ticker: str) -> None:
        if ticker in self._tick_handles:
            self._ib.cancelMktData(self._tick_handles.pop(ticker))
        if ticker in self._bar_handles:
            self._ib.cancelRealTimeBars(self._bar_handles.pop(ticker))

    def set_tickers(self, tickers: list[str]) -> None:
        cur = set(self._tick_handles.keys())
        want = set(tickers)
        for t in cur - want:
            self.unsubscribe(t)
        for t in want - cur:
            self.subscribe(t)

    def _handle_tick(self, ticker: str, ticker_obj) -> None:
        price = getattr(ticker_obj, "last", None) or getattr(ticker_obj, "close", None)
        if price is None or self._on_tick is None:
            return
        self._on_tick(ticker, float(price), datetime.now(timezone.utc))

    def _handle_bar(self, ticker: str, bars, has_new: bool) -> None:
        if not has_new or not bars or self._on_bar is None:
            return
        b = bars[-1]
        ts = b.time
        if getattr(ts, "tzinfo", None) is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)
        self._on_bar(ticker, {
            "ts": ts, "o": float(b.open_), "h": float(b.high),
            "l": float(b.low), "c": float(b.close), "v": float(b.volume),
        })

    async def disconnect(self) -> None:
        if self._ib.isConnected():
            self._ib.disconnect()
