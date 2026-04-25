import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

import config
from backtest import YahooPriceFetcher, run_backtest
from digest import build_digest, send_digest
from datetime import datetime, timedelta, timezone
from notifier import Notifier
from paper.broker import PaperBroker
from paper.review import build_daily_review, build_win_rate_stats
from pipeline import Pipeline
from pushers import PushHub
from storage import Storage
from watchlist_manager import WatchlistError, WatchlistManager


class TickerPayload(BaseModel):
    ticker: str


class ExecutionModePayload(BaseModel):
    mode: str


STATIC_DIR = Path(__file__).parent / "static"


def build_router(
    storage: Storage,
    notifier: Notifier,
    watchlist: WatchlistManager,
    pipeline: Pipeline,
    price_pipeline: Pipeline,
    push_hub: PushHub,
    paper_broker: PaperBroker,
) -> APIRouter:
    router = APIRouter()

    @router.get("/")
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    @router.get("/events")
    async def events_page():
        return FileResponse(STATIC_DIR / "index.html")

    @router.get("/paper")
    async def paper_page():
        return FileResponse(STATIC_DIR / "paper.html")

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
    async def add_ticker(payload: TickerPayload, request: Request):
        try:
            t = watchlist.add(payload.ticker)
        except WatchlistError as e:
            raise HTTPException(status_code=400, detail=str(e))
        pipeline.set_tickers(watchlist.tickers())
        price_pipeline.set_tickers(watchlist.tickers())
        runner = getattr(request.app.state, "streaming_runner", None)
        if runner is not None:
            runner.set_tickers(watchlist.tickers())
        asyncio.create_task(pipeline.run_once())
        asyncio.create_task(price_pipeline.run_once())
        return {"tickers": watchlist.tickers(), "added": t}

    @router.delete("/api/watchlist/{ticker}")
    async def remove_ticker(ticker: str, request: Request):
        try:
            t = watchlist.remove(ticker)
        except WatchlistError as e:
            raise HTTPException(status_code=400, detail=str(e))
        pipeline.set_tickers(watchlist.tickers())
        price_pipeline.set_tickers(watchlist.tickers())
        runner = getattr(request.app.state, "streaming_runner", None)
        if runner is not None:
            runner.set_tickers(watchlist.tickers())
        return {"tickers": watchlist.tickers(), "removed": t}

    @router.get("/healthz")
    async def health():
        return {"status": "ok"}

    @router.get("/api/health")
    async def health_detail(request: Request):
        def src_status(s):
            h = getattr(s, "_health", None)
            if h is not None:
                if h.disabled:
                    return h.reason or "disabled"
                if h.reason:
                    return h.reason
            return "ok"

        sources = []
        for s in pipeline.sources:
            h = getattr(s, "_health", None)
            sources.append({
                "name": s.name,
                "group": "news",
                "status": src_status(s),
                "detail": getattr(h, "last_status", None),
            })
        for s in price_pipeline.sources:
            h = getattr(s, "_health", None)
            sources.append({
                "name": s.name,
                "group": "price",
                "status": src_status(s),
                "detail": getattr(h, "last_status", None),
            })

        enricher = pipeline.enricher
        return {
            "status": "ok",
            "sources": sources,
            "push_channels": [p.name for p in push_hub._pushers] if push_hub.enabled else [],
            "enricher_enabled": bool(enricher and enricher.enabled),
            "last_news_run": pipeline.last_run_at.isoformat() if pipeline.last_run_at else None,
            "last_news_inserted": pipeline.last_run_inserted,
            "last_price_run": price_pipeline.last_run_at.isoformat() if price_pipeline.last_run_at else None,
            "last_price_inserted": price_pipeline.last_run_inserted,
            "startup_sync_running": (
                (task := getattr(request.app.state, "startup_sync_task", None)) is not None
                and not task.done()
            ),
        }

    @router.get("/api/diagnostics")
    async def diagnostics(request: Request):
        def src_row(src, group: str):
            health = getattr(src, "_health", None)
            snap = health.snapshot() if health is not None else {}
            return {
                "name": src.name,
                "group": group,
                **snap,
            }

        runner = getattr(request.app.state, "streaming_runner", None)
        client = getattr(runner, "_client", None) if runner is not None else None
        ibkr = client.snapshot() if client is not None and hasattr(client, "snapshot") else None
        startup_meta = getattr(request.app.state, "startup_sync_meta", None) or {}
        startup_task = getattr(request.app.state, "startup_sync_task", None)
        execution = getattr(request.app.state, "execution", None)

        return {
            "startup": {
                **startup_meta,
                "running": bool(startup_task is not None and not startup_task.done()),
            },
            "news_pipeline": {
                "last_run_at": pipeline.last_run_at.isoformat() if pipeline.last_run_at else None,
                "last_run_inserted": pipeline.last_run_inserted,
                "ticker_count": len(watchlist.tickers()),
                "tickers": watchlist.tickers(),
            },
            "price_pipeline": {
                "last_run_at": price_pipeline.last_run_at.isoformat() if price_pipeline.last_run_at else None,
                "last_run_inserted": price_pipeline.last_run_inserted,
            },
            "sources": [
                *(src_row(src, "news") for src in pipeline.sources),
                *(src_row(src, "price") for src in price_pipeline.sources),
            ],
            "ibkr": ibkr,
            "execution": execution.snapshot() if execution is not None else None,
        }

    @router.get("/api/execution-mode")
    async def execution_mode(request: Request):
        execution = getattr(request.app.state, "execution", None)
        if execution is None:
            raise HTTPException(status_code=503, detail="execution controller unavailable")
        return execution.snapshot()

    @router.post("/api/execution-mode")
    async def set_execution_mode(payload: ExecutionModePayload, request: Request):
        execution = getattr(request.app.state, "execution", None)
        if execution is None:
            raise HTTPException(status_code=503, detail="execution controller unavailable")
        ok, body = execution.set_mode(payload.mode)
        if ok:
            if payload.mode == "live":
                canceled = paper_broker.cancel_pending_entries()
                body["pending_entries_canceled"] = canceled
            return body
        raise HTTPException(status_code=409, detail=body)

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

    _price_fetcher = YahooPriceFetcher()

    @router.get("/api/backtest")
    async def backtest(ticker: str, event_type: str = "filing_8k",
                        lookback_days: int = 365):
        return await run_backtest(
            storage, _price_fetcher,
            ticker=ticker, event_type=event_type,
            lookback_days=lookback_days,
        )

    @router.get("/api/smc/structure")
    async def smc_structure(ticker: str | None = None,
                            kind: str | None = None,
                            limit: int = 200):
        rows = storage.query_smc_structure(ticker=ticker, kind=kind, limit=limit)
        return {"events": rows}

    @router.get("/api/paper/positions")
    async def paper_positions():
        return {
            "positions": paper_broker.ledger.positions_payload(),
            "cash": round(paper_broker.ledger.cash, 4),
            "equity": round(paper_broker.ledger.equity_now(), 4),
        }

    @router.get("/api/paper/trades")
    async def paper_trades(ticker: str | None = None, limit: int = 200):
        return {"trades": storage.list_paper_trades(ticker=ticker, limit=limit)}

    @router.get("/api/paper/equity")
    async def paper_equity(limit: int = 200):
        return {"equity": storage.list_paper_equity(limit=limit)}

    @router.get("/api/paper/review")
    async def paper_review(date: str | None = None):
        payload = build_daily_review(storage, day_str=date)
        return {
            "title": payload.title,
            "body": payload.body,
            "date": payload.date,
            "trade_count": payload.trade_count,
            "pnl": payload.pnl,
        }

    @router.get("/api/paper/stats")
    async def paper_stats():
        return {"rows": build_win_rate_stats(storage)}

    @router.get("/api/chart")
    async def chart(
        ticker: str,
        interval: str = "5m",
        range_days: int = 5,
        limit: int = 240,
    ):
        allowed = {"5m", "15m", "1h", "1d"}
        if interval not in allowed:
            raise HTTPException(status_code=400, detail=f"unsupported interval: {interval}")
        if range_days < 1 or range_days > 365:
            raise HTTPException(status_code=400, detail="range_days must be between 1 and 365")

        now = datetime.now(timezone.utc)
        start = now - timedelta(days=range_days)
        candles = await _price_fetcher.chart_candles(
            ticker=ticker,
            start=start,
            end=now,
            interval=interval,
        )
        if limit > 0:
            candles = candles[-limit:]

        if candles:
            since = datetime.fromisoformat(candles[0]["ts"])
        else:
            since = start

        structures = [
            row for row in storage.query_smc_structure(ticker=ticker, limit=2000)
            if datetime.fromisoformat(row["ts"]) >= since
        ]
        structures.sort(key=lambda row: row["ts"])

        sweeps_high = {
            round(float(row["price"]), 4)
            for row in structures if row["kind"] == "liq_sweep_high"
        }
        sweeps_low = {
            round(float(row["price"]), 4)
            for row in structures if row["kind"] == "liq_sweep_low"
        }
        liquidity_levels = []
        seen_liq: set[tuple[str, float]] = set()
        for row in structures:
            if row["kind"] not in {"swing_high", "swing_low"}:
                continue
            side = "high" if row["kind"] == "swing_high" else "low"
            price_key = round(float(row["price"]), 4)
            swept = price_key in (sweeps_high if side == "high" else sweeps_low)
            key = (side, price_key)
            if key in seen_liq:
                continue
            seen_liq.add(key)
            liquidity_levels.append({
                "ts": row["ts"],
                "side": side,
                "price": row["price"],
                "active": not swept,
            })

        order_blocks = []
        for row in structures:
            if row["kind"] not in {"ob_bull", "ob_bear"}:
                continue
            meta = row.get("meta") or {}
            low_p = meta.get("low")
            high_p = meta.get("high")
            if low_p is None or high_p is None:
                continue
            order_blocks.append({
                "ts": row["ts"],
                "kind": row["kind"],
                "low": float(low_p),
                "high": float(high_p),
                "status": meta.get("status", "fresh"),
            })

        trades = [
            row for row in storage.list_paper_trades(ticker=ticker, limit=1000)
            if datetime.fromisoformat(row["ts"]) >= since
        ]
        trades.sort(key=lambda row: row["ts"])
        equity = [
            row for row in storage.list_paper_equity(limit=4000)
            if datetime.fromisoformat(row["ts"]) >= since
        ]
        equity.sort(key=lambda row: row["ts"])

        return {
            "ticker": ticker.upper(),
            "interval": interval,
            "range_days": range_days,
            "candles": candles,
            "structures": structures,
            "liquidity": liquidity_levels,
            "order_blocks": order_blocks,
            "trades": trades,
            "equity": equity,
        }

    @router.get("/api/earnings/upcoming")
    def upcoming_earnings(
        from_: str | None = Query(None, alias="from"),
        to: str | None = None,
    ):
        from datetime import datetime, timezone, timedelta
        today = datetime.now(timezone.utc).date()
        date_from = from_ or today.isoformat()
        date_to = to or (today + timedelta(days=14)).isoformat()
        return storage.list_upcoming_earnings(date_from, date_to)

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
