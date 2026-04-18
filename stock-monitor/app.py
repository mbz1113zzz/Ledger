import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import config
from notifier import Notifier
from scheduler import (
    build_enricher,
    build_pipeline,
    build_price_pipeline,
    build_push_hub,
    start_scheduler,
)
from sources.sec_edgar import SecEdgarSource
from storage import Storage
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

    sec_source: SecEdgarSource = app.state.sec_source
    await sec_source.load_ticker_map()

    pipeline = app.state.pipeline
    price_pipeline = app.state.price_pipeline
    try:
        await pipeline.run_once()
        await price_pipeline.run_once()
    except Exception as e:
        log.exception("initial pipeline run failed: %s", e)

    scheduler = start_scheduler(pipeline, price_pipeline, storage)
    app.state.scheduler = scheduler

    log.info("startup complete on port %d", config.PORT)
    yield
    scheduler.shutdown()


def create_app() -> FastAPI:
    storage = Storage(config.DB_PATH)
    notifier = Notifier()
    watchlist = WatchlistManager(config.WATCHLIST_PATH)
    sec_source = SecEdgarSource()
    enricher = build_enricher()
    push_hub = build_push_hub()
    pipeline = build_pipeline(
        storage, notifier, watchlist.tickers(), sec_source, enricher, push_hub,
    )
    price_pipeline = build_price_pipeline(
        storage, notifier, watchlist.tickers(), push_hub,
    )

    app = FastAPI(title="Stock Event Monitor", lifespan=lifespan)
    app.state.storage = storage
    app.state.notifier = notifier
    app.state.watchlist = watchlist
    app.state.sec_source = sec_source
    app.state.pipeline = pipeline
    app.state.price_pipeline = price_pipeline

    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "web" / "static"), name="static")
    app.include_router(build_router(storage, notifier, watchlist, pipeline, price_pipeline))
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=config.PORT, reload=False)
