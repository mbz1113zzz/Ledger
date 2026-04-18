from unittest.mock import AsyncMock, patch

import pytest

from sources.sec_edgar import SecEdgarSource


TICKER_MAP_RESPONSE = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 1730168, "ticker": "EOSE", "title": "EOS Energy Enterprises"},
}

SUBMISSIONS_RESPONSE = {
    "cik": "0001730168",
    "filings": {
        "recent": {
            "accessionNumber": ["0001-25-000001", "0001-25-000002"],
            "form":            ["8-K",              "10-Q"],
            "filingDate":      ["2026-04-17",       "2026-04-10"],
            "primaryDocument": ["doc1.htm",         "doc2.htm"],
            "primaryDocDescription": ["8-K filing", "10-Q filing"],
        }
    },
}


@pytest.mark.asyncio
async def test_fetch_returns_only_8k():
    src = SecEdgarSource()
    src._ticker_to_cik = {"EOSE": "0001730168"}
    with patch.object(src, "_get", new=AsyncMock(return_value=SUBMISSIONS_RESPONSE)):
        events = await src.fetch(["EOSE"])
    assert len(events) == 1
    assert events[0].event_type == "filing_8k"
    assert events[0].external_id == "0001-25-000001"
    assert events[0].ticker == "EOSE"
    assert "sec.gov" in events[0].url


@pytest.mark.asyncio
async def test_unknown_ticker_skipped():
    src = SecEdgarSource()
    src._ticker_to_cik = {}
    events = await src.fetch(["ZZZZ"])
    assert events == []


FORM4_RESPONSE = {
    "cik": "0001730168",
    "filings": {
        "recent": {
            "accessionNumber": ["0001-25-000010", "0001-25-000011"],
            "form":            ["4",               "4/A"],
            "filingDate":      ["2026-04-15",      "2026-04-14"],
            "primaryDocument": ["f4.xml",          "f4a.xml"],
            "primaryDocDescription": ["Form 4",    "Form 4/A"],
        }
    },
}


EIGHTK_WITH_ITEMS_RESPONSE = {
    "cik": "0001730168",
    "filings": {
        "recent": {
            "accessionNumber": ["0001-25-000020"],
            "form":            ["8-K"],
            "filingDate":      ["2026-04-17"],
            "primaryDocument": ["doc.htm"],
            "primaryDocDescription": ["8-K"],
            "items":           ["2.02,5.02"],
        }
    },
}


@pytest.mark.asyncio
async def test_fetch_parses_form4_as_insider():
    src = SecEdgarSource()
    src._ticker_to_cik = {"EOSE": "0001730168"}
    with patch.object(src, "_get", new=AsyncMock(return_value=FORM4_RESPONSE)):
        events = await src.fetch(["EOSE"])
    assert len(events) == 2
    assert all(e.event_type == "insider" for e in events)
    assert "内部人交易" in events[0].title
    assert events[0].raw["form"] == "4"
    assert events[1].raw["form"] == "4/A"


@pytest.mark.asyncio
async def test_8k_title_includes_chinese_item_labels():
    src = SecEdgarSource()
    src._ticker_to_cik = {"EOSE": "0001730168"}
    with patch.object(src, "_get", new=AsyncMock(return_value=EIGHTK_WITH_ITEMS_RESPONSE)):
        events = await src.fetch(["EOSE"])
    assert len(events) == 1
    t = events[0].title
    assert "8-K" in t
    assert "业绩披露" in t
    assert "高管/董事变动" in t
    assert events[0].raw["items"] == ["2.02", "5.02"]


@pytest.mark.asyncio
async def test_load_ticker_map_parses_response():
    src = SecEdgarSource()
    with patch.object(src, "_get", new=AsyncMock(return_value=TICKER_MAP_RESPONSE)):
        await src.load_ticker_map()
    assert src._ticker_to_cik["AAPL"] == "0000320193"
    assert src._ticker_to_cik["EOSE"] == "0001730168"
