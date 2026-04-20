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
