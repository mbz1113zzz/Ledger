from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime

from notifier import Notifier
from pushers import PushHub
from sources.base import Event
from storage import Storage
from streaming.anomaly import AnomalySignal
from smc.types import SmcSignal, StructureEvent

log = logging.getLogger(__name__)

_TIER_IMPORTANCE = {"low": "low", "medium": "medium", "high": "high"}


def _minute_bucket(ts: datetime) -> str:
    return ts.strftime("%Y%m%d%H%M")


def _serializable_asdict(obj) -> dict:
    d = asdict(obj)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


def _ref_meta(ref) -> dict:
    if ref is None:
        return {}
    try:
        return _serializable_asdict(ref)
    except Exception:
        return {}


class SignalRouter:
    def __init__(self, storage: Storage, notifier: Notifier,
                 push_hub: PushHub | None):
        self._s = storage
        self._n = notifier
        self._p = push_hub

    async def on_anomaly(self, sig: AnomalySignal) -> None:
        ext = f"ibkr:anom:{sig.ticker}:{sig.tier}:{_minute_bucket(sig.ts)}"
        if self._s.exists("ibkr", ext):
            return
        title = (f"{sig.ticker} {sig.direction}{abs(sig.pct_open)*100:.2f}% "
                 f"(1m {abs(sig.pct_1m)*100:.2f}%)")
        ev = Event(
            source="ibkr", external_id=ext, ticker=sig.ticker,
            event_type="price_alert", title=title,
            summary=f"anomaly {sig.tier} {sig.direction}",
            url=None, published_at=sig.ts, raw=_serializable_asdict(sig),
            importance=_TIER_IMPORTANCE[sig.tier], summary_cn=None,
        )
        if self._s.insert(ev):
            await self._n.publish(self._serialize(ev))
            if ev.importance == "high" and self._p and self._p.enabled:
                try:
                    await self._p.broadcast(ev)
                except Exception as e:
                    log.warning("push failed: %s", e)

    async def on_structure(self, ev: StructureEvent, tf: str) -> None:
        self._s.insert_smc_structure(
            ticker=ev.ticker, tf=tf, kind=ev.kind, price=ev.price, ts=ev.ts,
            ref_id=None, meta=_ref_meta(ev.ref),
        )
        await self._n.publish({
            "type": "structure", "ticker": ev.ticker, "tf": tf,
            "kind": ev.kind, "price": ev.price, "ts": ev.ts.isoformat(),
        })

    async def on_smc_signal(self, sig: SmcSignal) -> int | None:
        ext = f"ibkr:smc:{sig.ticker}:{sig.reason}:{_minute_bucket(sig.ts)}"
        ev = Event(
            source="ibkr",
            external_id=ext,
            ticker=sig.ticker,
            event_type="smc_entry",
            title=f"{sig.ticker} SMC {sig.side} {sig.reason}",
            summary=f"side={sig.side} entry={sig.entry:.2f} sl={sig.sl:.2f} tp={sig.tp:.2f}",
            url=None,
            published_at=sig.ts,
            raw=_serializable_asdict(sig),
            importance="high",
            summary_cn=None,
        )
        inserted, event_id = self._s.insert_with_id(ev)
        if inserted:
            await self._n.publish(self._serialize(ev))
        return event_id

    async def on_execution_intent(self, sig: SmcSignal, *, mode: str, status: str, note: str) -> int | None:
        ext = f"ibkr:exec:{sig.ticker}:{mode}:{status}:{_minute_bucket(sig.ts)}"
        ev = Event(
            source="system",
            external_id=ext,
            ticker=sig.ticker,
            event_type="execution_intent",
            title=f"{sig.ticker} execution {mode} {status}",
            summary=note,
            url=None,
            published_at=sig.ts,
            raw={
                **_serializable_asdict(sig),
                "mode": mode,
                "status": status,
                "note": note,
            },
            importance="high",
            summary_cn=None,
        )
        inserted, event_id = self._s.insert_with_id(ev)
        if inserted:
            await self._n.publish(self._serialize(ev))
        return event_id

    @staticmethod
    def _serialize(ev: Event) -> dict:
        d = asdict(ev)
        d["published_at"] = ev.published_at.isoformat()
        d.pop("raw", None)
        return d
