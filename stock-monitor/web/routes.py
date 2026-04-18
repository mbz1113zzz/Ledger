import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, StreamingResponse

from notifier import Notifier
from storage import Storage
from watchlist_manager import WatchlistManager


STATIC_DIR = Path(__file__).parent / "static"


def build_router(
    storage: Storage, notifier: Notifier, watchlist: WatchlistManager
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

    @router.get("/healthz")
    async def health():
        return {"status": "ok"}

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
