import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from notifier import Notifier
from pipeline import Pipeline
from storage import Storage
from watchlist_manager import WatchlistError, WatchlistManager


class TickerPayload(BaseModel):
    ticker: str


STATIC_DIR = Path(__file__).parent / "static"


def build_router(
    storage: Storage,
    notifier: Notifier,
    watchlist: WatchlistManager,
    pipeline: Pipeline,
    price_pipeline: Pipeline,
) -> APIRouter:
    router = APIRouter()

    @router.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    @router.get("/api/events")
    async def list_events(
        importance: str | None = None,
        ticker: str | None = None,
        limit: int = 200,
    ):
        events = storage.query(importance=importance, ticker=ticker, limit=limit)
        out = []
        for e in events:
            d = asdict(e)
            d["published_at"] = e.published_at.isoformat()
            d.pop("raw", None)
            out.append(d)
        return {"events": out}

    @router.get("/api/watchlist")
    async def get_watchlist():
        return {"tickers": watchlist.tickers()}

    @router.post("/api/watchlist")
    async def add_ticker(payload: TickerPayload):
        try:
            t = watchlist.add(payload.ticker)
        except WatchlistError as e:
            raise HTTPException(status_code=400, detail=str(e))
        pipeline.set_tickers(watchlist.tickers())
        price_pipeline.set_tickers(watchlist.tickers())
        asyncio.create_task(pipeline.run_once())
        asyncio.create_task(price_pipeline.run_once())
        return {"tickers": watchlist.tickers(), "added": t}

    @router.delete("/api/watchlist/{ticker}")
    async def remove_ticker(ticker: str):
        try:
            t = watchlist.remove(ticker)
        except WatchlistError as e:
            raise HTTPException(status_code=400, detail=str(e))
        pipeline.set_tickers(watchlist.tickers())
        price_pipeline.set_tickers(watchlist.tickers())
        return {"tickers": watchlist.tickers(), "removed": t}

    @router.get("/healthz")
    async def health():
        return {"status": "ok"}

    @router.post("/api/refresh")
    async def refresh():
        asyncio.create_task(pipeline.run_once())
        asyncio.create_task(price_pipeline.run_once())
        return {"status": "scheduled"}

    @router.get("/stream")
    async def stream(request: Request):
        queue = await notifier.subscribe()

        async def gen():
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                        yield f"data: {json.dumps(payload)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
            finally:
                await notifier.unsubscribe(queue)

        return StreamingResponse(gen(), media_type="text/event-stream")

    return router
