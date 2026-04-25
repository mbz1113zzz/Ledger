import importlib

from scheduler import build_news_sources
from sources.sec_edgar import SecEdgarSource


def test_default_pipeline_is_events_only(monkeypatch):
    monkeypatch.setenv("FINNHUB_ENABLE_NEWS", "1")
    monkeypatch.setenv("FINNHUB_ENABLE_EARNINGS", "1")
    monkeypatch.setenv("FINNHUB_ENABLE_ANALYST", "0")
    monkeypatch.setenv("FINNHUB_ENABLE_SENTIMENT", "0")
    import config
    import scheduler
    importlib.reload(config)
    importlib.reload(scheduler)

    names = [src.name for src in scheduler.build_news_sources(SecEdgarSource())]
    assert names == ["finnhub", "sec_edgar"]


def test_optional_research_sources_can_be_enabled(monkeypatch):
    monkeypatch.setenv("FINNHUB_ENABLE_ANALYST", "1")
    monkeypatch.setenv("FINNHUB_ENABLE_SENTIMENT", "1")
    import config
    import scheduler
    importlib.reload(config)
    importlib.reload(scheduler)

    names = [src.name for src in scheduler.build_news_sources(SecEdgarSource())]
    assert "analyst" in names
    assert "sentiment" in names


def test_earnings_scheduler_jobs_are_registered(monkeypatch):
    """Both earnings jobs should be registered regardless of paper_broker state."""
    import importlib
    from unittest.mock import MagicMock
    from scheduler import start_scheduler
    from storage import Storage

    storage = Storage(":memory:")
    pipeline = MagicMock()
    price_pipeline = MagicMock()
    paper_broker = MagicMock()
    paper_broker.pricing = MagicMock()

    import scheduler as sched_mod
    importlib.reload(sched_mod)

    scheduler_instance = sched_mod.start_scheduler(
        pipeline=pipeline,
        price_pipeline=price_pipeline,
        storage=storage,
        push_hub=None,
        paper_broker=paper_broker,
    )
    try:
        job_ids = {job.id for job in scheduler_instance.get_jobs()}
        assert "earnings_reaction_backfill" in job_ids
        assert "earnings_stale_sweep" in job_ids
    finally:
        scheduler_instance.shutdown(wait=False)
