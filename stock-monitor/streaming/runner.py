from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from notifier import Notifier
from pushers import PushHub
from storage import Storage
from streaming.anomaly import AnomalyDetector
from streaming.bar_aggregator import BarAggregator
from streaming.signal_router import SignalRouter
from streaming.tick_buffer import TickBuffer
from smc.liquidity import LiquidityPoolIndex
from smc.order_block import OrderBlockIndex
from smc.structure import StructureTracker
from smc.types import Candle, StructureEvent

log = logging.getLogger(__name__)


class StreamingRunner:
    def __init__(self, *, client, storage: Storage, notifier: Notifier,
                 push_hub: PushHub | None, tickers: list[str],
                 tiers: list[tuple[str, float]],
                 cooldown_sec: int = 300,
                 structure_tf: str = "5m",
                 fractal_window: int = 5):
        self._client = client
        self._storage = storage
        self._notifier = notifier
        self._push = push_hub
        self._tickers = list(tickers)
        self._structure_tf = structure_tf
        self._fractal_window = fractal_window
        self._buf = TickBuffer(max_age_sec=900)
        self._detector = AnomalyDetector(self._buf, tiers, cooldown_sec)
        self._aggregator = BarAggregator(tfs=("1m", structure_tf))
        self._router = SignalRouter(storage, notifier, push_hub)
        self._structure: dict[str, StructureTracker] = {}
        self._obs: dict[str, OrderBlockIndex] = {}
        self._liq: dict[str, LiquidityPoolIndex] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._aggregator.on_closed(self._on_candle_closed_sync)

    def _smc_for(self, ticker: str) -> tuple[StructureTracker, OrderBlockIndex, LiquidityPoolIndex]:
        if ticker not in self._structure:
            self._structure[ticker] = StructureTracker(ticker, self._fractal_window)
            self._obs[ticker] = OrderBlockIndex(ticker)
            self._liq[ticker] = LiquidityPoolIndex(ticker)
        return self._structure[ticker], self._obs[ticker], self._liq[ticker]

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._client.on_tick(self._tick_bridge)
        self._client.on_bar(self._bar_bridge)
        try:
            await self._client.connect_with_retry()
            self._client.set_tickers(self._tickers)
        except Exception as e:
            log.warning("IBKR start failed: %s (running without live data)", e)

    def set_tickers(self, tickers: list[str]) -> None:
        self._tickers = list(tickers)
        try:
            self._client.set_tickers(self._tickers)
        except Exception as e:
            log.warning("set_tickers failed: %s", e)

    def _tick_bridge(self, ticker: str, price: float, ts: datetime) -> None:
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self.on_tick(ticker, price, ts), self._loop)

    def _bar_bridge(self, ticker: str, bar: dict) -> None:
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self.on_bar(ticker, bar), self._loop)

    async def on_tick(self, ticker: str, price: float, ts: datetime) -> None:
        if self._buf.open_price(ticker) is None:
            self._buf.set_open(ticker, price, ts)
        self._buf.update(ticker, price, ts)
        for sig in self._detector.feed(ticker, price, ts):
            await self._router.on_anomaly(sig)

    async def on_bar(self, ticker: str, bar: dict) -> None:
        self._aggregator.feed(ticker, bar)

    def _on_candle_closed_sync(self, ticker: str, candle: Candle) -> None:
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(
            self._on_candle_closed(ticker, candle), self._loop
        )

    async def _on_candle_closed(self, ticker: str, candle: Candle) -> None:
        if candle.tf != self._structure_tf:
            return
        st, obs, liq = self._smc_for(ticker)
        events = st.on_candle(candle)
        for ev in events:
            if ev.kind in ("swing_high", "swing_low"):
                liq.on_swing(ev.ref)
        obs.on_candle(candle)
        events.extend(liq.on_candle(candle))
        for ev in events:
            if ev.kind in ("bos_up", "bos_down", "choch_up", "choch_down"):
                for ob in obs.on_structure_event(ev):
                    await self._router.on_structure(
                        StructureEvent(
                            ts=candle.ts, ticker=ticker,
                            kind=("ob_bull" if ob.kind == "bull" else "ob_bear"),
                            price=(ob.low + ob.high) / 2, ref=ob),
                        tf=candle.tf,
                    )
            await self._router.on_structure(ev, tf=candle.tf)

    async def stop(self) -> None:
        try:
            await self._client.disconnect()
        except Exception:
            pass


def build_runner_if_enabled(*, storage, notifier, push_hub, tickers):
    import config
    if not config.IBKR_ENABLED:
        return None
    from sources.ibkr_realtime import IbkrClient
    client = IbkrClient(host=config.IBKR_HOST, port=config.IBKR_PORT,
                        client_id=config.IBKR_CLIENT_ID)
    return StreamingRunner(
        client=client, storage=storage, notifier=notifier, push_hub=push_hub,
        tickers=tickers, tiers=config.ANOMALY_TIERS,
        cooldown_sec=config.ANOMALY_COOLDOWN_SEC,
        structure_tf=config.SMC_STRUCTURE_TF,
        fractal_window=config.SMC_FRACTAL_WINDOW,
    )
