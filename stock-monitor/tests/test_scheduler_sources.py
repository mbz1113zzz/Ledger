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
