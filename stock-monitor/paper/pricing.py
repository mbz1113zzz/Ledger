from __future__ import annotations

from datetime import datetime


class PriceBook:
    def __init__(self):
        self._prices: dict[str, tuple[float, datetime]] = {}

    def update(self, ticker: str, price: float, ts: datetime) -> None:
        self._prices[ticker] = (price, ts)

    def latest(self, ticker: str) -> float | None:
        item = self._prices.get(ticker)
        return item[0] if item is not None else None

    def as_dict(self) -> dict[str, dict]:
        return {
            ticker: {"price": price, "ts": ts.isoformat()}
            for ticker, (price, ts) in self._prices.items()
        }
