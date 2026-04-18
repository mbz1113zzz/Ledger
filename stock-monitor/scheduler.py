import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

import config
from digest import send_digest
from enricher import Enricher
from pipeline import Pipeline
from pushers import BarkPusher, FeishuPusher, PushHub, TelegramPusher
from sources.analyst import AnalystSource
from sources.finnhub import FinnhubSource
from sources.price_alerts import PriceAlertSource
from sources.sec_edgar import SecEdgarSource
from sources.sentiment import SentimentSource
from storage import Storage

log = logging.getLogger(__name__)


def build_enricher() -> Enricher:
    return Enricher(
        api_key=config.ANTHROPIC_API_KEY,
        model=config.ENRICH_MODEL,
        only_high=config.ENRICH_ONLY_HIGH,
    )


def build_push_hub() -> PushHub:
    return PushHub([
        TelegramPusher(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID),
        BarkPusher(config.BARK_URL),
        FeishuPusher(config.FEISHU_WEBHOOK),
    ])


def build_pipeline(
    storage: Storage,
    notifier,
    tickers: list[str],
    sec_source: SecEdgarSource,
    enricher: Enricher,
    push_hub: PushHub,
) -> Pipeline:
    sources = [
        FinnhubSource(api_key=config.FINNHUB_API_KEY),
        sec_source,
        AnalystSource(api_key=config.FINNHUB_API_KEY),
        SentimentSource(api_key=config.FINNHUB_API_KEY),
    ]
    return Pipeline(
        sources=sources, storage=storage, notifier=notifier, tickers=tickers,
        enricher=enricher, push_hub=push_hub,
    )


def build_price_pipeline(
    storage: Storage,
    notifier,
    tickers: list[str],
    push_hub: PushHub,
) -> Pipeline:
    sources = [
        PriceAlertSource(
            api_key=config.FINNHUB_API_KEY,
            threshold_pct=config.PRICE_ALERT_THRESHOLD_PCT,
        ),
    ]
    return Pipeline(
        sources=sources, storage=storage, notifier=notifier, tickers=tickers,
        push_hub=push_hub,
    )


def start_scheduler(
    pipeline: Pipeline, price_pipeline: Pipeline, storage: Storage,
    push_hub: PushHub | None = None,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        pipeline.run_once,
        IntervalTrigger(minutes=config.FINNHUB_INTERVAL_MINUTES),
        id="poll_sources",
        next_run_time=None,
    )
    scheduler.add_job(
        price_pipeline.run_once,
        IntervalTrigger(minutes=config.PRICE_POLL_INTERVAL_MINUTES),
        id="poll_prices",
        next_run_time=None,
    )
    scheduler.add_job(
        lambda: storage.cleanup(config.RETAIN_DAYS),
        CronTrigger(hour=config.EARNINGS_CALENDAR_HOUR, minute=config.EARNINGS_CALENDAR_MINUTE),
        id="daily_cleanup",
    )
    if config.DIGEST_ENABLED and push_hub is not None:
        scheduler.add_job(
            lambda: send_digest(storage, push_hub,
                                lookback_hours=config.DIGEST_LOOKBACK_HOURS),
            CronTrigger(hour=config.DIGEST_HOUR, minute=config.DIGEST_MINUTE),
            id="daily_digest",
        )
    scheduler.start()
    log.info("scheduler started")
    return scheduler
