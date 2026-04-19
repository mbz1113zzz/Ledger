import importlib


def test_ibkr_defaults(monkeypatch):
    monkeypatch.delenv("IBKR_ENABLED", raising=False)
    monkeypatch.delenv("IBKR_PORT", raising=False)
    import config
    importlib.reload(config)
    assert config.IBKR_ENABLED is True
    assert config.IBKR_HOST == "127.0.0.1"
    assert config.IBKR_PORT == 7497
    assert config.IBKR_CLIENT_ID == 42


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
