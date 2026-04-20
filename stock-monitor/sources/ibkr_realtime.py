from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable

from ib_insync import IB, Stock

log = logging.getLogger(__name__)


def _is_nan(x) -> bool:
    try:
        return x != x  # NaN is the only value not equal to itself
    except Exception:
        return False


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
        # Clear any stale handles from a previous (now-dead) session.
        # After reconnect we must re-request market data; the old Ticker/BarList
        # objects are tied to the defunct socket and stop emitting events.
        self._tick_handles.clear()
        self._bar_handles.clear()
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
        # ib_insync field name has varied across versions (last / marketPrice /
        # close); fall back through candidates and log once if all are missing.
        # NOTE: on older ib_insync, `marketPrice` is a bound method rather than
        # an attribute — skip callables. IBKR also emits `-1.0` as a sentinel
        # for "no trade yet" on some instruments; treat non-positive as absent.
        price = None
        for attr in ("last", "marketPrice", "close", "bid", "ask"):
            val = getattr(ticker_obj, attr, None)
            if val is None or callable(val) or _is_nan(val):
                continue
            try:
                v = float(val)
            except (TypeError, ValueError):
                continue
            if v <= 0:
                continue
            price = v
            break
        if price is None:
            if not getattr(self, "_warned_tick_fields", False):
                log.warning("IBKR tick has no usable price field for %s; obj=%r",
                            ticker, ticker_obj)
                self._warned_tick_fields = True
            return
        if self._on_tick is None:
            return
        try:
            self._on_tick(ticker, float(price), datetime.now(timezone.utc))
        except Exception as e:
            log.exception("tick callback failed for %s: %s", ticker, e)

    def _handle_bar(self, ticker: str, bars, has_new: bool) -> None:
        if not has_new or not bars or self._on_bar is None:
            return
        b = bars[-1]
        try:
            ts = b.time
            if getattr(ts, "tzinfo", None) is None:
                ts = ts.replace(tzinfo=timezone.utc)
            else:
                ts = ts.astimezone(timezone.utc)
            # ib_insync uses `open_` (trailing underscore) to avoid shadowing
            # the builtin, but future versions may normalize to `open`.
            o = getattr(b, "open_", None)
            if o is None:
                o = getattr(b, "open", None)
            payload = {
                "ts": ts, "o": float(o), "h": float(b.high),
                "l": float(b.low), "c": float(b.close),
                "v": float(getattr(b, "volume", 0) or 0),
            }
        except Exception as e:
            log.exception("bar parse failed for %s bar=%r: %s", ticker, b, e)
            return
        try:
            self._on_bar(ticker, payload)
        except Exception as e:
            log.exception("bar callback failed for %s: %s", ticker, e)

    def is_alive(self) -> bool:
        try:
            return bool(self._ib.isConnected())
        except Exception:
            return False

    async def disconnect(self) -> None:
        if self._ib.isConnected():
            self._ib.disconnect()
