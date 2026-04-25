from datetime import datetime, timedelta, timezone

import pytest

import config
from paper.earnings_reaction import backfill_earnings_reactions
from paper.pricing import PriceBook
from sources.base import Event
from storage import Storage


def _seed_published_row(s, *, ticker="AAPL", mark_at_publish=100.0, detected_at=None):
    detected_at = detected_at or datetime(2026, 4, 30, 20, 5, tzinfo=timezone.utc)
    s.upsert_earnings(
        ticker=ticker, scheduled_date="2026-04-30", scheduled_hour="amc",
        eps_estimate=1.0, eps_actual=None, rev_estimate=1.0, rev_actual=None,
        status="scheduled", updated_at=detected_at,
    )
    s.transition_to_published(
        ticker=ticker, scheduled_date="2026-04-30",
        eps_actual=1.05, rev_actual=None,
        surprise_pct=0.05, mark_at_publish_price=mark_at_publish,
        detected_publish_at=detected_at,
    )
    ev = Event(
        source="finnhub", external_id=f"{ticker}-earnings-published-2026-04-30",
        ticker=ticker, event_type="earnings_published",
        title=f"{ticker} earnings", summary="initial",
        url=None, published_at=detected_at, raw={},
    )
    inserted, eid = s.insert_with_id(ev)
    s.set_published_event_id(ticker, "2026-04-30", eid)
    return s.get_earnings(ticker, "2026-04-30"), eid


@pytest.mark.asyncio
async def test_skips_rows_before_delay(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EARNINGS_REACTION_BACKFILL_DELAY_MIN", 30)
    s = Storage(str(tmp_path / "t.db")); s.init_schema()
    detected = datetime(2026, 4, 30, 20, 5, tzinfo=timezone.utc)
    _seed_published_row(s, detected_at=detected)
    pricing = PriceBook(); pricing.update("AAPL", 105.0, detected + timedelta(minutes=10))
    now = detected + timedelta(minutes=20)
    await backfill_earnings_reactions(s, pricing, now=now)
    row = s.get_earnings("AAPL", "2026-04-30")
    assert row["status"] == "published_pending_reaction"
    assert row["reaction_pct_30m"] is None


@pytest.mark.asyncio
async def test_writes_reaction_after_delay(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EARNINGS_REACTION_BACKFILL_DELAY_MIN", 30)
    monkeypatch.setattr(config, "EARNINGS_REACTION_BACKFILL_TIMEOUT_HOURS", 6)
    s = Storage(str(tmp_path / "t.db")); s.init_schema()
    detected = datetime(2026, 4, 30, 20, 5, tzinfo=timezone.utc)
    row, eid = _seed_published_row(s, mark_at_publish=100.0, detected_at=detected)
    pricing = PriceBook(); pricing.update("AAPL", 103.2, detected + timedelta(minutes=35))
    now = detected + timedelta(minutes=35)
    await backfill_earnings_reactions(s, pricing, now=now)
    row = s.get_earnings("AAPL", "2026-04-30")
    assert row["status"] == "reacted"
    assert abs(row["reaction_pct_30m"] - 0.032) < 1e-6
    summary = s._conn.execute("SELECT summary FROM events WHERE id=?", (eid,)).fetchone()["summary"]
    assert "30m 反应" in summary or "+3.2%" in summary


@pytest.mark.asyncio
async def test_no_pricing_skips_then_force_stales_after_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EARNINGS_REACTION_BACKFILL_DELAY_MIN", 30)
    monkeypatch.setattr(config, "EARNINGS_REACTION_BACKFILL_TIMEOUT_HOURS", 6)
    s = Storage(str(tmp_path / "t.db")); s.init_schema()
    detected = datetime(2026, 4, 30, 20, 5, tzinfo=timezone.utc)
    _seed_published_row(s, mark_at_publish=None, detected_at=detected)
    empty_pricing = PriceBook()

    await backfill_earnings_reactions(s, empty_pricing, now=detected + timedelta(hours=2))
    assert s.get_earnings("AAPL", "2026-04-30")["status"] == "published_pending_reaction"

    await backfill_earnings_reactions(s, empty_pricing, now=detected + timedelta(hours=7))
    row = s.get_earnings("AAPL", "2026-04-30")
    assert row["status"] == "reacted"
    assert row["reaction_pct_30m"] is None


@pytest.mark.asyncio
async def test_only_processes_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EARNINGS_REACTION_BACKFILL_DELAY_MIN", 30)
    s = Storage(str(tmp_path / "t.db")); s.init_schema()
    detected = datetime(2026, 4, 30, 20, 5, tzinfo=timezone.utc)
    _seed_published_row(s, ticker="AAPL", detected_at=detected)
    s.set_earnings_status(s.get_earnings("AAPL", "2026-04-30")["id"], "reacted")
    pricing = PriceBook(); pricing.update("AAPL", 200.0, detected + timedelta(minutes=35))
    await backfill_earnings_reactions(s, pricing, now=detected + timedelta(minutes=35))
    row = s.get_earnings("AAPL", "2026-04-30")
    assert row["reaction_pct_30m"] is None
