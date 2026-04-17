import json
from pathlib import Path


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
