import tempfile
from datetime import datetime, timezone

from storage import Storage


def _storage():
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    s = Storage(tmp.name)
    s.init_schema()
    return s


def test_paper_position_trade_and_equity_roundtrip():
    s = _storage()
    ts = datetime(2026, 4, 19, 14, 30, tzinfo=timezone.utc)
    s.upsert_paper_position(
        ticker="NVDA",
        qty=10,
        entry_price=100.0,
        entry_ts=ts,
        sl=99.0,
        tp=102.0,
        reason="smc_bos_ob",
        signal_id=3,
        mark_price=101.0,
        updated_at=ts,
    )
    s.insert_paper_trade(
        ts=ts,
        ticker="NVDA",
        side="buy",
        qty=10,
        price=100.0,
        reason="smc_bos_ob",
        signal_id=3,
    )
    s.record_paper_equity(ts=ts, cash=9000.0, positions_value=1010.0, equity=10010.0)
    assert s.list_paper_positions()[0]["ticker"] == "NVDA"
    assert s.list_paper_trades()[0]["reason"] == "smc_bos_ob"
    assert s.last_paper_equity()["equity"] == 10010.0
