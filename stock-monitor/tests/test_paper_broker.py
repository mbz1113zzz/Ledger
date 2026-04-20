import tempfile
from datetime import datetime, timedelta, timezone

from paper.broker import PaperBroker
from paper.ledger import Ledger
from paper.pricing import PriceBook
from paper.strategy import SmcLongStrategy
from smc.types import SmcSignal
from storage import Storage


def _storage():
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    s = Storage(tmp.name)
    s.init_schema()
    return s


def _signal(reason: str = "smc_bos_ob") -> SmcSignal:
    return SmcSignal(
        ts=datetime(2026, 4, 19, 14, 30, tzinfo=timezone.utc),
        ticker="NVDA",
        entry=100.0,
        sl=99.0,
        tp=102.0,
        reason=reason,
    )


async def test_on_signal_opens_position_and_records_trade():
    storage = _storage()
    broker = PaperBroker(
        ledger=Ledger(storage),
        strategy=SmcLongStrategy(),
        prices=PriceBook(),
        max_hold_min=60,
    )
    opened = await broker.on_smc_signal(_signal(), signal_id=7)
    assert opened is not None
    positions = broker.ledger.positions_payload()
    assert len(positions) == 1
    trades = storage.list_paper_trades()
    assert trades[0]["side"] == "buy"
    assert trades[0]["signal_id"] == 7


async def test_take_profit_exit_records_sell_and_clears_position():
    storage = _storage()
    broker = PaperBroker(
        ledger=Ledger(storage),
        strategy=SmcLongStrategy(),
        prices=PriceBook(),
        max_hold_min=60,
    )
    await broker.on_smc_signal(_signal())
    closed = await broker.on_tick("NVDA", 102.5,
                                  datetime(2026, 4, 19, 14, 35, tzinfo=timezone.utc))
    assert len(closed) == 1
    assert closed[0]["reason"] == "tp"
    assert broker.ledger.positions_payload() == []
    trades = storage.list_paper_trades(limit=10)
    assert [t["side"] for t in trades[:2]] == ["sell", "buy"]


async def test_timeout_exit_closes_position_after_max_hold():
    storage = _storage()
    broker = PaperBroker(
        ledger=Ledger(storage),
        strategy=SmcLongStrategy(),
        prices=PriceBook(),
        max_hold_min=60,
    )
    sig = _signal()
    await broker.on_smc_signal(sig)
    closed = await broker.on_tick("NVDA", 100.5, sig.ts + timedelta(minutes=61))
    assert len(closed) == 1
    assert closed[0]["reason"] == "timeout"


async def test_eod_close_flattens_open_positions():
    storage = _storage()
    broker = PaperBroker(
        ledger=Ledger(storage),
        strategy=SmcLongStrategy(),
        prices=PriceBook(),
        max_hold_min=60,
    )
    await broker.on_smc_signal(_signal())
    closed = await broker.handle_eod_close(datetime(2026, 4, 19, 19, 50, tzinfo=timezone.utc))
    assert len(closed) == 1
    assert closed[0]["reason"] == "eod"


async def test_break_even_stop_moves_to_entry_and_exits_flat():
    storage = _storage()
    broker = PaperBroker(
        ledger=Ledger(storage),
        strategy=SmcLongStrategy(),
        prices=PriceBook(),
        max_hold_min=60,
        break_even_enabled=True,
        break_even_r=1.0,
    )
    await broker.on_smc_signal(_signal())
    await broker.on_tick("NVDA", 101.1, datetime(2026, 4, 19, 14, 32, tzinfo=timezone.utc))
    closed = await broker.on_tick("NVDA", 100.0, datetime(2026, 4, 19, 14, 33, tzinfo=timezone.utc))
    assert len(closed) == 1
    assert closed[0]["reason"] == "be"
    assert round(closed[0]["pnl"], 4) == 0.0


class _FakeNotifier:
    def __init__(self):
        self.events = []

    async def publish(self, payload):
        self.events.append(payload)


class _FakeHub:
    enabled = True

    def __init__(self):
        self.texts = []

    async def broadcast_text(self, title, body):
        self.texts.append((title, body))


async def test_open_and_close_publish_notifications():
    storage = _storage()
    notifier = _FakeNotifier()
    hub = _FakeHub()
    broker = PaperBroker(
        ledger=Ledger(storage), strategy=SmcLongStrategy(),
        prices=PriceBook(), max_hold_min=60,
        notifier=notifier, push_hub=hub,
    )
    await broker.on_smc_signal(_signal())
    await broker.on_tick("NVDA", 102.5,
                          datetime(2026, 4, 19, 14, 35, tzinfo=timezone.utc))
    # Let scheduled publish tasks run
    import asyncio as _a
    await _a.sleep(0)
    await _a.sleep(0)
    actions = [e["action"] for e in notifier.events]
    assert "open" in actions and "close" in actions
    # tp close should produce a push
    assert any("CLOSE tp" in t[0] for t in hub.texts)
    assert any("OPEN long" in t[0] for t in hub.texts)


async def test_max_positions_gate_blocks_additional_opens():
    storage = _storage()
    broker = PaperBroker(
        ledger=Ledger(storage), strategy=SmcLongStrategy(),
        prices=PriceBook(), max_hold_min=60, max_positions=1,
    )
    await broker.on_smc_signal(_signal())
    sig2 = SmcSignal(
        ts=datetime(2026, 4, 19, 14, 31, tzinfo=timezone.utc),
        ticker="TSLA", entry=200.0, sl=198.0, tp=204.0, reason="smc_bos_ob",
    )
    opened = await broker.on_smc_signal(sig2)
    assert opened is None
    assert len(broker.ledger.positions_payload()) == 1


async def test_day_drawdown_circuit_breaker_halts_new_entries():
    storage = _storage()
    ts = datetime(2026, 4, 19, 14, 0, tzinfo=timezone.utc)
    # Seed day-start equity at 10_000, then force a big drawdown snapshot.
    storage.record_paper_equity(ts=ts, cash=10_000, positions_value=0, equity=10_000)
    storage.record_paper_equity(
        ts=ts.replace(hour=14, minute=30), cash=9_600, positions_value=0, equity=9_600,
    )
    broker = PaperBroker(
        ledger=Ledger(storage), strategy=SmcLongStrategy(),
        prices=PriceBook(), max_hold_min=60, max_day_drawdown_pct=0.03,
    )
    opened = await broker.on_smc_signal(_signal())
    assert opened is None


async def test_short_signal_opens_and_takes_profit():
    storage = _storage()
    broker = PaperBroker(
        ledger=Ledger(storage),
        strategy=SmcLongStrategy(),
        prices=PriceBook(),
        max_hold_min=60,
    )
    sig = SmcSignal(
        ts=datetime(2026, 4, 19, 14, 30, tzinfo=timezone.utc),
        ticker="TSLA",
        entry=100.0,
        sl=101.0,
        tp=98.0,
        side="short",
        reason="smc_bos_ob_short",
    )
    opened = await broker.on_smc_signal(sig, signal_id=9)
    assert opened is not None
    assert opened["side"] == "short"
    closed = await broker.on_tick("TSLA", 97.8, datetime(2026, 4, 19, 14, 35, tzinfo=timezone.utc))
    assert len(closed) == 1
    assert closed[0]["reason"] == "tp"
    assert closed[0]["pnl"] > 0
