import tempfile
from datetime import datetime, timezone

from notifier import Notifier
from storage import Storage
from streaming.anomaly import AnomalySignal
from streaming.signal_router import SignalRouter
from smc.types import SmcSignal, StructureEvent


def _storage():
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    s = Storage(tmp.name)
    s.init_schema()
    return s


async def test_anomaly_persisted_and_published():
    s = _storage()
    n = Notifier()
    q = await n.subscribe()
    router = SignalRouter(storage=s, notifier=n, push_hub=None)
    sig = AnomalySignal(
        ts=datetime(2026, 4, 19, 14, 30, tzinfo=timezone.utc),
        ticker="NVDA", tier="medium", direction="up",
        price=101.2, pct_open=0.012, pct_1m=0.012,
    )
    await router.on_anomaly(sig)
    evs = s.query(ticker="NVDA", limit=10)
    assert len(evs) == 1
    assert evs[0].importance == "medium"
    assert evs[0].event_type == "price_alert"
    payload = q.get_nowait()
    assert payload["ticker"] == "NVDA"


async def test_duplicate_anomaly_in_same_minute_is_rejected():
    s = _storage()
    router = SignalRouter(storage=s, notifier=Notifier(), push_hub=None)
    sig = AnomalySignal(
        ts=datetime(2026, 4, 19, 14, 30, 10, tzinfo=timezone.utc),
        ticker="NVDA", tier="medium", direction="up",
        price=101.2, pct_open=0.012, pct_1m=0.012,
    )
    await router.on_anomaly(sig)
    sig2 = AnomalySignal(ts=sig.ts.replace(second=50),
                         ticker="NVDA", tier="medium", direction="up",
                         price=101.3, pct_open=0.013, pct_1m=0.013)
    await router.on_anomaly(sig2)
    assert len(s.query(ticker="NVDA", limit=10)) == 1


async def test_structure_event_persisted_to_smc_table():
    s = _storage()
    router = SignalRouter(storage=s, notifier=Notifier(), push_hub=None)
    ev = StructureEvent(ts=datetime(2026, 4, 19, 14, 30, tzinfo=timezone.utc),
                        ticker="NVDA", kind="bos_up", price=105.0, ref=None)
    await router.on_structure(ev, tf="5m")
    rows = s.query_smc_structure(ticker="NVDA")
    assert rows[0]["kind"] == "bos_up"


async def test_smc_signal_persisted_as_event():
    s = _storage()
    n = Notifier()
    q = await n.subscribe()
    router = SignalRouter(storage=s, notifier=n, push_hub=None)
    sig = SmcSignal(
        ts=datetime(2026, 4, 19, 14, 35, tzinfo=timezone.utc),
        ticker="NVDA",
        entry=100.0,
        sl=99.0,
        tp=102.0,
        reason="smc_bos_ob",
    )
    event_id = await router.on_smc_signal(sig)
    assert event_id is not None
    events = s.query(ticker="NVDA", limit=10)
    assert events[0].event_type == "smc_entry"
    payload = q.get_nowait()
    assert payload["event_type"] == "smc_entry"
