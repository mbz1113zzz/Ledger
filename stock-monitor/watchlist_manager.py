import json
import re
from pathlib import Path


TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


class WatchlistError(Exception):
    pass


class WatchlistManager:
    def __init__(self, path: str):
        self._path = Path(path)
        if not self._path.exists():
            raise WatchlistError(f"Watchlist file not found: {path}")
        try:
            data = json.loads(self._path.read_text())
        except json.JSONDecodeError as e:
            raise WatchlistError(f"Invalid JSON in watchlist: {e}") from e
        if not isinstance(data, dict) or "tickers" not in data:
            raise WatchlistError("Watchlist must be an object with a 'tickers' key")
        tickers = data["tickers"]
        if not isinstance(tickers, list) or not tickers:
            raise WatchlistError("'tickers' must be a non-empty list")
        self._tickers = [str(t).upper() for t in tickers]

    def tickers(self) -> list[str]:
        return list(self._tickers)

    def add(self, ticker: str) -> str:
        t = (ticker or "").strip().upper()
        if not TICKER_RE.match(t):
            raise WatchlistError(f"Invalid ticker: {ticker!r}")
        if t in self._tickers:
            raise WatchlistError(f"{t} already in watchlist")
        self._tickers.append(t)
        self._save()
        return t

    def remove(self, ticker: str) -> str:
        t = (ticker or "").strip().upper()
        if t not in self._tickers:
            raise WatchlistError(f"{t} not in watchlist")
        if len(self._tickers) == 1:
            raise WatchlistError("cannot remove last ticker")
        self._tickers.remove(t)
        self._save()
        return t

    def _save(self) -> None:
        self._path.write_text(json.dumps({"tickers": self._tickers}, indent=2))
