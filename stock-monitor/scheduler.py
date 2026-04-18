import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

import config
from pipeline import Pipeline
from sources.finnhub import FinnhubSource
from sources.sec_edgar import SecEdgarSource
from storage import Storage

log = logging.getLogger(__name__)


def build_pipeline(
    storage: Storage, notifier, tickers: list[str], sec_source: SecEdgarSource
) -> Pipeline:
    sources = [
        FinnhubSource(api_key=config.FINNHUB_API_KEY),
        sec_source,
    ]
    return Pipeline(sources=sources, storage=storage, notifier=notifier, tickers=tickers)


def start_scheduler(pipeline: Pipeline, storage: Storage) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        pipeline.run_once,
        IntervalTrigger(minutes=config.FINNHUB_INTERVAL_MINUTES),
        id="poll_sources",
        next_run_time=None,
    )
    scheduler.add_job(
        lambda: storage.cleanup(config.RETAIN_DAYS),
        CronTrigger(hour=config.EARNINGS_CALENDAR_HOUR, minute=config.EARNINGS_CALENDAR_MINUTE),
        id="daily_cleanup",
    )
    scheduler.start()
    log.info("scheduler started")
    return scheduler
