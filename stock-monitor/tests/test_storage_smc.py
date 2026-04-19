import tempfile
from datetime import datetime, timezone
from storage import Storage


def _mk():
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    s = Storage(tmp.name)
    s.init_schema()
    return s


def test_insert_and_query_smc_structure():
    s = _mk()
    ts = datetime(2026, 4, 19, 14, 30, tzinfo=timezone.utc)
    s.insert_smc_structure(
        ticker="NVDA", tf="5m", kind="bos_up", price=105.5, ts=ts,
        ref_id=None, meta={"trend": "up"},
    )
    rows = s.query_smc_structure(ticker="NVDA", limit=10)
    assert len(rows) == 1
    assert rows[0]["kind"] == "bos_up"
    assert rows[0]["price"] == 105.5
    assert rows[0]["meta"] == {"trend": "up"}


def test_query_filters_by_ticker_and_kind():
    s = _mk()
    ts = datetime(2026, 4, 19, 14, 30, tzinfo=timezone.utc)
    for i, (t, k) in enumerate([("NVDA", "bos_up"), ("TSLA", "bos_down"),
                                ("NVDA", "ob_bull")]):
        s.insert_smc_structure(ticker=t, tf="5m", kind=k, price=100+i,
                               ts=ts, ref_id=None, meta={})
    rows = s.query_smc_structure(ticker="NVDA", kind="ob_bull", limit=10)
    assert [r["kind"] for r in rows] == ["ob_bull"]
