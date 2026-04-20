from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from notifier import Notifier
from paper.broker import PaperBroker
from pushers import PushHub
from storage import Storage
from streaming.anomaly import AnomalyDetector
from streaming.bar_aggregator import BarAggregator
from streaming.signal_router import SignalRouter
from streaming.tick_buffer import TickBuffer
from smc.engine import SmcEngine
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
                 entry_tf: str = "1m",
                 fractal_window: int = 5,
                 startup_timeout_sec: float = 5.0,
                 smc_max_risk_pct: float = 0.015,
                 smc_min_rr: float = 2.0,
                 smc_tick_size: float = 0.01,
                 paper_broker: PaperBroker | None = None):
        self._client = client
        self._storage = storage
        self._notifier = notifier
        self._push = push_hub
        self._tickers = list(tickers)
        self._structure_tf = structure_tf
        self._entry_tf = entry_tf
        self._fractal_window = fractal_window
        self._startup_timeout_sec = startup_timeout_sec
        self._buf = TickBuffer(max_age_sec=900)
        self._detector = AnomalyDetector(self._buf, tiers, cooldown_sec)
        self._aggregator = BarAggregator(tfs=(entry_tf, structure_tf))
        self._router = SignalRouter(storage, notifier, push_hub)
        self._structure: dict[str, StructureTracker] = {}
        self._obs: dict[str, OrderBlockIndex] = {}
        self._liq: dict[str, LiquidityPoolIndex] = {}
        self._engines: dict[str, SmcEngine] = {}
        self._paper_broker = paper_broker
        self._smc_max_risk_pct = smc_max_risk_pct
        self._smc_min_rr = smc_min_rr
        self._smc_tick_size = smc_tick_size
        self._loop: asyncio.AbstractEventLoop | None = None
        self._aggregator.on_closed(self._on_candle_closed_sync)

    def _smc_for(self, ticker: str) -> tuple[StructureTracker, OrderBlockIndex, LiquidityPoolIndex, SmcEngine]:
        if ticker not in self._structure:
            self._structure[ticker] = StructureTracker(ticker, self._fractal_window)
            self._obs[ticker] = OrderBlockIndex(ticker)
            self._liq[ticker] = LiquidityPoolIndex(ticker)
            self._engines[ticker] = SmcEngine(
                ticker=ticker,
                entry_tf=self._entry_tf,
                max_risk_pct=self._smc_max_risk_pct,
                min_rr=self._smc_min_rr,
                tick_size=self._smc_tick_size,
            )
        return (
            self._structure[ticker],
            self._obs[ticker],
            self._liq[ticker],
            self._engines[ticker],
        )

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._client.on_tick(self._tick_bridge)
        self._client.on_bar(self._bar_bridge)
        try:
            await asyncio.wait_for(
                self._client.connect_with_retry(),
                timeout=self._startup_timeout_sec,
            )
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
        self._submit_coro(self.on_tick(ticker, price, ts))

    def _bar_bridge(self, ticker: str, bar: dict) -> None:
        self._submit_coro(self.on_bar(ticker, bar))

    async def on_tick(self, ticker: str, price: float, ts: datetime) -> None:
        if self._buf.open_price(ticker) is None:
            self._buf.set_open(ticker, price, ts)
        self._buf.update(ticker, price, ts)
        for sig in self._detector.feed(ticker, price, ts):
            await self._router.on_anomaly(sig)
        if self._paper_broker is not None:
            await self._paper_broker.on_tick(ticker, price, ts)

    async def on_bar(self, ticker: str, bar: dict) -> None:
        self._aggregator.feed(ticker, bar)

    def _on_candle_closed_sync(self, ticker: str, candle: Candle) -> None:
        self._submit_coro(self._on_candle_closed(ticker, candle))

    async def _on_candle_closed(self, ticker: str, candle: Candle) -> None:
        st, obs, liq, engine = self._smc_for(ticker)
        if candle.tf == self._structure_tf:
            events = st.on_candle(candle)
            for ev in events:
                if ev.kind in ("swing_high", "swing_low"):
                    liq.on_swing(ev.ref)
            obs.on_candle(candle)
            events.extend(liq.on_candle(candle))
            pending_highs = [pool.price for pool in liq.pending() if pool.side == "high"]
            for ev in events:
                new_obs = []
                if ev.kind in ("bos_up", "bos_down", "choch_up", "choch_down"):
                    new_obs = obs.on_structure_event(ev)
                    for ob in new_obs:
                        await self._router.on_structure(
                            StructureEvent(
                                ts=candle.ts, ticker=ticker,
                                kind=("ob_bull" if ob.kind == "bull" else "ob_bear"),
                                price=(ob.low + ob.high) / 2, ref=ob),
                            tf=candle.tf,
                        )
                engine.on_structure_event(ev, trend=st.trend, new_obs=new_obs)
                await self._router.on_structure(ev, tf=candle.tf)
            return

        if candle.tf != self._entry_tf:
            return
        pending_highs = [pool.price for pool in liq.pending() if pool.side == "high"]
        pending_lows = [pool.price for pool in liq.pending() if pool.side == "low"]
        for sig in engine.on_entry_candle(
            candle,
            pending_high_prices=pending_highs,
            pending_low_prices=pending_lows,
        ):
            signal_id = await self._router.on_smc_signal(sig)
            if self._paper_broker is not None:
                await self._paper_broker.on_smc_signal(sig, signal_id=signal_id)

    async def stop(self) -> None:
        try:
            await self._client.disconnect()
        except Exception:
            pass

    def _submit_coro(self, coro) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            coro.close()
            return
        try:
            if asyncio.get_running_loop() is loop:
                loop.create_task(coro)
                return
        except RuntimeError:
            pass
        try:
            asyncio.run_coroutine_threadsafe(coro, loop)
        except RuntimeError:
            coro.close()


def build_runner_if_enabled(*, storage, notifier, push_hub, tickers, paper_broker=None):
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
        entry_tf=config.SMC_ENTRY_TF,
        fractal_window=config.SMC_FRACTAL_WINDOW,
        startup_timeout_sec=config.IBKR_STARTUP_TIMEOUT_SEC,
        smc_max_risk_pct=config.SMC_MAX_RISK_PCT,
        smc_min_rr=config.SMC_MIN_RR,
        smc_tick_size=config.SMC_TICK_SIZE,
        paper_broker=paper_broker,
    )
