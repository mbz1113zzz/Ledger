import importlib


def test_ibkr_defaults(monkeypatch):
    monkeypatch.delenv("IBKR_ENABLED", raising=False)
    monkeypatch.delenv("IBKR_PORT", raising=False)
    monkeypatch.delenv("IBKR_STARTUP_TIMEOUT_SEC", raising=False)
    import config
    importlib.reload(config)
    assert config.IBKR_ENABLED is True
    assert config.IBKR_HOST == "127.0.0.1"
    assert config.IBKR_PORT == 7497
    assert config.IBKR_CLIENT_ID == 42
    assert config.IBKR_STARTUP_TIMEOUT_SEC == 5.0


def test_finnhub_research_sources_default_off(monkeypatch):
    monkeypatch.delenv("FINNHUB_ENABLE_ANALYST", raising=False)
    monkeypatch.delenv("FINNHUB_ENABLE_SENTIMENT", raising=False)
    import config
    importlib.reload(config)
    assert config.FINNHUB_ENABLE_ANALYST is False
    assert config.FINNHUB_ENABLE_SENTIMENT is False


def test_anomaly_tiers_are_sorted_ascending():
    import config
    importlib.reload(config)
    pcts = [p for _, p in config.ANOMALY_TIERS]
    assert pcts == sorted(pcts)
    assert {name for name, _ in config.ANOMALY_TIERS} == {"low", "medium", "high"}


def test_smc_structure_tf_defaults():
    import config
    importlib.reload(config)
    assert config.SMC_STRUCTURE_TF == "5m"
    assert config.SMC_ENTRY_TF == "1m"
    assert config.SMC_FRACTAL_WINDOW == 5
