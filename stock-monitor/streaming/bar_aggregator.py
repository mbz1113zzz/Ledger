from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from smc.types import Candle

_TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900}


def _bucket(ts: datetime, seconds: int) -> datetime:
    epoch = int(ts.timestamp())
    bkt = epoch - (epoch % seconds)
    return datetime.fromtimestamp(bkt, tz=timezone.utc)


class BarAggregator:
    def __init__(self, tfs: tuple[str, ...] = ("1m", "5m")):
        self._tfs = tfs
        self._open: dict[tuple[str, str], dict] = {}
        self._cb: Callable[[str, Candle], None] | None = None

    def on_closed(self, cb: Callable[[str, Candle], None]) -> None:
        self._cb = cb

    def feed(self, ticker: str, bar: dict) -> None:
        for tf in self._tfs:
            sec = _TF_SECONDS[tf]
            bkt = _bucket(bar["ts"], sec)
            key = (ticker, tf)
            cur = self._open.get(key)
            if cur is None:
                self._open[key] = self._new_bucket(bkt, bar)
                continue
            if cur["ts"] == bkt:
                cur["h"] = max(cur["h"], bar["h"])
                cur["l"] = min(cur["l"], bar["l"])
                cur["c"] = bar["c"]
                cur["v"] += bar["v"]
            else:
                self._emit(ticker, tf, cur)
                self._open[key] = self._new_bucket(bkt, bar)

    def _new_bucket(self, ts: datetime, bar: dict) -> dict:
        return {"ts": ts, "o": bar["o"], "h": bar["h"], "l": bar["l"],
                "c": bar["c"], "v": bar["v"]}

    def _emit(self, ticker: str, tf: str, cur: dict) -> None:
        if self._cb is None:
            return
        self._cb(ticker, Candle(ts=cur["ts"], tf=tf, o=cur["o"], h=cur["h"],
                                 l=cur["l"], c=cur["c"], v=cur["v"]))
