import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

import config
from paper.review import send_daily_review
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


def build_news_sources(sec_source: SecEdgarSource) -> list:
    sources = []
    if config.FINNHUB_ENABLE_NEWS or config.FINNHUB_ENABLE_EARNINGS:
        sources.append(
            FinnhubSource(
                api_key=config.FINNHUB_API_KEY,
                enable_news=config.FINNHUB_ENABLE_NEWS,
                enable_earnings=config.FINNHUB_ENABLE_EARNINGS,
            )
        )
    sources.append(sec_source)
    if config.FINNHUB_ENABLE_ANALYST:
        sources.append(AnalystSource(api_key=config.FINNHUB_API_KEY))
    if config.FINNHUB_ENABLE_SENTIMENT:
        sources.append(SentimentSource(api_key=config.FINNHUB_API_KEY))
    return sources


def build_enricher() -> Enricher:
    provider = config.ENRICH_PROVIDER
    api_key = (
        config.DEEPSEEK_API_KEY if provider == "deepseek" else config.ANTHROPIC_API_KEY
    )
    return Enricher(
        api_key=api_key,
        model=config.ENRICH_MODEL,
        provider=provider,
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
    sources = build_news_sources(sec_source)
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
    paper_broker=None,
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
            send_digest,
            CronTrigger(hour=config.DIGEST_HOUR, minute=config.DIGEST_MINUTE),
            id="daily_digest",
            kwargs={
                "storage": storage,
                "push_hub": push_hub,
                "lookback_hours": config.DIGEST_LOOKBACK_HOURS,
            },
        )
    if config.PAPER_ENABLED and paper_broker is not None:
        scheduler.add_job(
            paper_broker.handle_eod_close,
            CronTrigger(
                hour=config.PAPER_EOD_HOUR_ET,
                minute=config.PAPER_EOD_MINUTE_ET,
                timezone=ZoneInfo("America/New_York"),
            ),
            id="paper_eod_close",
        )
        if push_hub is not None:
            scheduler.add_job(
                send_daily_review,
                CronTrigger(
                    hour=config.REVIEW_HOUR_ET,
                    minute=config.REVIEW_MINUTE_ET,
                    timezone=ZoneInfo("America/New_York"),
                ),
                id="paper_daily_review",
                kwargs={"storage": storage, "push_hub": push_hub},
            )
    scheduler.start()
    log.info("scheduler started")
    return scheduler
