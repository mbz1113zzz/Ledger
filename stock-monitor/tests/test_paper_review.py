import tempfile
from datetime import datetime, timezone

from paper.review import build_daily_review, build_win_rate_stats
from storage import Storage


def _storage():
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    s = Storage(tmp.name)
    s.init_schema()
    return s


def test_daily_review_handles_empty_day():
    storage = _storage()
    payload = build_daily_review(
        storage,
        day_str="2026-04-19",
        now=datetime(2026, 4, 19, 20, 0, tzinfo=timezone.utc),
    )
    assert payload.date == "2026-04-19"
    assert "当日无已平仓交易" in payload.body


def test_daily_review_summarizes_closed_trade():
    storage = _storage()
    buy_ts = datetime(2026, 4, 19, 14, 30, tzinfo=timezone.utc)
    sell_ts = datetime(2026, 4, 19, 15, 0, tzinfo=timezone.utc)
    storage.insert_paper_trade(
        ts=buy_ts,
        ticker="NVDA",
        side="buy",
        qty=20,
        price=100.0,
        reason="smc_bos_ob",
        signal_id=11,
    )
    storage.insert_paper_trade(
        ts=sell_ts,
        ticker="NVDA",
        side="sell",
        qty=20,
        price=102.0,
        reason="tp",
        pnl=40.0,
        signal_id=11,
        rr=2.0,
    )
    storage.record_paper_equity(ts=buy_ts, cash=8000.0, positions_value=2000.0, equity=10000.0)
    storage.record_paper_equity(ts=sell_ts, cash=10040.0, positions_value=0.0, equity=10040.0)
    payload = build_daily_review(storage, day_str="2026-04-19")
    assert payload.trade_count == 1
    assert payload.pnl == 40.0
    assert "smc_bos_ob" in payload.body
    assert "| NVDA | 20 | 100.00 | 102.00 | smc_bos_ob | tp | 2.00 | +40.00 |" in payload.body


def test_win_rate_stats_groups_by_ticker_and_setup():
    storage = _storage()
    storage.insert_paper_trade(
        ts=datetime(2026, 4, 19, 14, 30, tzinfo=timezone.utc),
        ticker="NVDA",
        side="buy",
        qty=20,
        price=100.0,
        reason="smc_bos_ob",
        signal_id=11,
    )
    storage.insert_paper_trade(
        ts=datetime(2026, 4, 19, 15, 0, tzinfo=timezone.utc),
        ticker="NVDA",
        side="sell",
        qty=20,
        price=102.0,
        reason="tp",
        pnl=40.0,
        signal_id=11,
        rr=2.0,
    )
    storage.insert_paper_trade(
        ts=datetime(2026, 4, 19, 15, 10, tzinfo=timezone.utc),
        ticker="TSLA",
        side="sell",
        qty=10,
        price=200.0,
        reason="smc_bos_ob_short",
        signal_id=12,
    )
    storage.insert_paper_trade(
        ts=datetime(2026, 4, 19, 15, 20, tzinfo=timezone.utc),
        ticker="TSLA",
        side="buy",
        qty=10,
        price=202.0,
        reason="sl",
        pnl=-20.0,
        signal_id=12,
        rr=-1.0,
    )
    rows = build_win_rate_stats(storage)
    assert rows[0]["ticker"] == "NVDA"
    assert rows[0]["setup"] == "smc_bos_ob"
    assert rows[0]["win_rate_pct"] == 100.0
    assert any(row["setup"] == "smc_bos_ob_short" for row in rows)


def test_daily_review_does_not_pick_best_setup_below_min_sample():
    storage = _storage()
    buy_ts = datetime(2026, 4, 19, 14, 30, tzinfo=timezone.utc)
    sell_ts = datetime(2026, 4, 19, 15, 0, tzinfo=timezone.utc)
    storage.insert_paper_trade(
        ts=buy_ts,
        ticker="NVDA",
        side="buy",
        qty=20,
        price=100.0,
        reason="smc_bos_ob",
        signal_id=11,
    )
    storage.insert_paper_trade(
        ts=sell_ts,
        ticker="NVDA",
        side="sell",
        qty=20,
        price=102.0,
        reason="tp",
        pnl=40.0,
        signal_id=11,
        rr=2.0,
    )
    storage.record_paper_equity(ts=buy_ts, cash=8000.0, positions_value=2000.0, equity=10000.0)
    storage.record_paper_equity(ts=sell_ts, cash=10040.0, positions_value=0.0, equity=10040.0)
    payload = build_daily_review(storage, day_str="2026-04-19")
    assert "暂不评选最佳 setup" in payload.body
