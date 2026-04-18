import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

import config
from backtest import YahooPriceFetcher, run_backtest
from digest import build_digest, send_digest
from datetime import datetime, timedelta, timezone
from notifier import Notifier
from pipeline import Pipeline
from pushers import PushHub
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
    push_hub: PushHub,
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

    @router.get("/api/digest")
    async def preview_digest(hours: int = 24):
        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=hours)
        events = storage.query_since(since, min_importance="medium")
        title, body = build_digest(events, now=now)
        return {"title": title, "body": body, "count": len(events)}

    @router.post("/api/digest/send")
    async def trigger_digest(hours: int = 24):
        if not push_hub.enabled:
            raise HTTPException(status_code=400, detail="no push channels configured")
        count = await send_digest(storage, push_hub, lookback_hours=hours)
        return {"status": "sent", "count": count}

    @router.get("/api/backtest")
    async def backtest(ticker: str, event_type: str = "filing_8k",
                        lookback_days: int = 365):
        fetcher = YahooPriceFetcher()
        return await run_backtest(
            storage, fetcher,
            ticker=ticker, event_type=event_type,
            lookback_days=lookback_days,
        )

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
