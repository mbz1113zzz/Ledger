import logging
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import config
from notifier import Notifier
from paper.broker import PaperBroker
from paper.execution import ExecutionModeController
from paper.ledger import Ledger
from paper.pricing import PriceBook
from paper.strategy import SmcLongStrategy
from scheduler import (
    build_enricher,
    build_pipeline,
    build_price_pipeline,
    build_push_hub,
    start_scheduler,
)
from sources.sec_edgar import SecEdgarSource
from storage import Storage
from streaming.runner import build_runner_if_enabled
from watchlist_manager import WatchlistManager
from web.routes import build_router


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage: Storage = app.state.storage
    storage.init_schema()
    storage.cleanup(config.RETAIN_DAYS)
    app.state.paper_broker.ledger.snapshot(datetime.now(timezone.utc))
    pipeline = app.state.pipeline
    price_pipeline = app.state.price_pipeline

    scheduler = start_scheduler(
        pipeline,
        price_pipeline,
        storage,
        push_hub=app.state.push_hub,
        paper_broker=app.state.paper_broker,
    )
    app.state.scheduler = scheduler
    app.state.startup_sync_task = None
    app.state.startup_sync_meta = {
        "started_at": None,
        "finished_at": None,
        "duration_ms": None,
        "status": "idle",
        "error": None,
    }

    watchlist: WatchlistManager = app.state.watchlist
    runner = build_runner_if_enabled(
        storage=storage, notifier=app.state.notifier,
        push_hub=app.state.push_hub, tickers=watchlist.tickers(),
        paper_broker=app.state.paper_broker,
    )
    app.state.streaming_runner = runner
    if runner is not None:
        try:
            await runner.start()
            log.info("streaming runner started (IBKR)")
        except Exception as e:
            log.warning("streaming runner start failed: %s", e)

    async def initial_sync():
        sec_source: SecEdgarSource = app.state.sec_source
        t0 = datetime.now(timezone.utc)
        app.state.startup_sync_meta = {
            "started_at": t0.isoformat(),
            "finished_at": None,
            "duration_ms": None,
            "status": "running",
            "error": None,
        }
        try:
            await sec_source.load_ticker_map()
            await pipeline.run_once()
            await price_pipeline.run_once()
            done = datetime.now(timezone.utc)
            app.state.startup_sync_meta = {
                "started_at": t0.isoformat(),
                "finished_at": done.isoformat(),
                "duration_ms": round((done - t0).total_seconds() * 1000, 2),
                "status": "ok",
                "error": None,
            }
        except Exception as e:
            done = datetime.now(timezone.utc)
            app.state.startup_sync_meta = {
                "started_at": t0.isoformat(),
                "finished_at": done.isoformat(),
                "duration_ms": round((done - t0).total_seconds() * 1000, 2),
                "status": "error",
                "error": str(e),
            }
            log.exception("initial pipeline run failed: %s", e)

    app.state.startup_sync_task = asyncio.create_task(initial_sync())
    log.info("startup complete on port %d", config.PORT)
    yield
    startup_task = app.state.startup_sync_task
    if startup_task is not None and not startup_task.done():
        startup_task.cancel()
    if runner is not None:
        try:
            await runner.stop()
        except Exception:
            pass
    scheduler.shutdown()


def create_app() -> FastAPI:
    storage = Storage(config.DB_PATH)
    storage.init_schema()
    notifier = Notifier()
    watchlist = WatchlistManager(config.WATCHLIST_PATH)
    sec_source = SecEdgarSource()
    enricher = build_enricher()
    push_hub = build_push_hub()
    prices = PriceBook()
    pipeline = build_pipeline(
        storage, notifier, watchlist.tickers(), sec_source, enricher, push_hub,
        pricing=prices,
    )
    price_pipeline = build_price_pipeline(
        storage, notifier, watchlist.tickers(), push_hub,
    )
    ledger = Ledger(storage, initial_cash=config.PAPER_INITIAL_CASH)
    strategy = SmcLongStrategy(
        max_position_pct=config.PAPER_MAX_POSITION_PCT,
        max_risk_per_trade_pct=config.PAPER_MAX_RISK_PER_TRADE_PCT,
    )
    paper_broker = PaperBroker(
        ledger=ledger,
        strategy=strategy,
        prices=prices,
        max_hold_min=config.PAPER_MAX_HOLD_MIN,
        break_even_enabled=config.PAPER_BREAK_EVEN_ENABLED,
        break_even_r=config.PAPER_BREAK_EVEN_R,
        max_positions=config.PAPER_MAX_POSITIONS,
        max_day_drawdown_pct=config.PAPER_MAX_DAY_DRAWDOWN_PCT,
        max_gross_exposure_pct=config.PAPER_MAX_GROSS_EXPOSURE_PCT,
        max_open_risk_pct=config.PAPER_MAX_OPEN_RISK_PCT,
        slippage_bps=config.PAPER_SLIPPAGE_BPS,
        commission_per_share=config.PAPER_COMMISSION_PER_SHARE,
        commission_min=config.PAPER_COMMISSION_MIN,
        notifier=notifier,
        push_hub=push_hub,
    )
    execution = ExecutionModeController(
        storage=storage,
        initial_mode=config.EXECUTION_MODE,
        live_trading_enabled=config.LIVE_TRADING_ENABLED,
        live_execution_available=config.LIVE_EXECUTION_IMPLEMENTED,
        min_closed_trades=config.LIVE_READINESS_MIN_CLOSED_TRADES,
        min_win_rate_pct=config.LIVE_READINESS_MIN_WIN_RATE_PCT,
        min_avg_rr=config.LIVE_READINESS_MIN_AVG_RR,
    )
    notifier._execution_controller = execution

    app = FastAPI(title="Stock Event Monitor", lifespan=lifespan)
    app.state.storage = storage
    app.state.notifier = notifier
    app.state.watchlist = watchlist
    app.state.sec_source = sec_source
    app.state.pipeline = pipeline
    app.state.price_pipeline = price_pipeline
    app.state.push_hub = push_hub
    app.state.paper_broker = paper_broker
    app.state.execution = execution
    app.state.streaming_runner = None
    app.state.startup_sync_task = None
    app.state.startup_sync_meta = {
        "started_at": None,
        "finished_at": None,
        "duration_ms": None,
        "status": "idle",
        "error": None,
    }

    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "web" / "static"), name="static")
    app.include_router(
        build_router(
            storage, notifier, watchlist, pipeline, price_pipeline, push_hub, paper_broker
        )
    )
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=config.PORT, reload=False)
