import json
from pathlib import Path

import pytest

from watchlist_manager import WatchlistManager, WatchlistError


def test_load_valid_watchlist(tmp_path: Path):
    p = tmp_path / "wl.json"
    p.write_text(json.dumps({"tickers": ["EOSE", "MDB"]}))
    wm = WatchlistManager(str(p))
    assert wm.tickers() == ["EOSE", "MDB"]


def test_tickers_are_uppercased(tmp_path: Path):
    p = tmp_path / "wl.json"
    p.write_text(json.dumps({"tickers": ["eose", "mdb"]}))
    wm = WatchlistManager(str(p))
    assert wm.tickers() == ["EOSE", "MDB"]


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(WatchlistError):
        WatchlistManager(str(tmp_path / "nope.json"))


def test_invalid_schema_raises(tmp_path: Path):
    p = tmp_path / "wl.json"
    p.write_text(json.dumps({"foo": "bar"}))
    with pytest.raises(WatchlistError):
        WatchlistManager(str(p))


def test_empty_tickers_raises(tmp_path: Path):
    p = tmp_path / "wl.json"
    p.write_text(json.dumps({"tickers": []}))
    with pytest.raises(WatchlistError):
        WatchlistManager(str(p))
