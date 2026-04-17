import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT.parent / ".env")

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
FINNHUB_INTERVAL_MINUTES = 5
SEC_INTERVAL_MINUTES = 5
EARNINGS_CALENDAR_HOUR = 0  # run at 00:05 local time
EARNINGS_CALENDAR_MINUTE = 5
DB_PATH = str(ROOT / "data" / "events.db")
WATCHLIST_PATH = str(ROOT / "watchlist.json")
RETAIN_DAYS = 30
PORT = 8000
SEC_USER_AGENT = "stock-monitor research@example.com"  # SEC requires a UA
HIGH_KEYWORDS = [
    "acquisition", "merger", "fda approval", "guidance",
    "ceo", "resign", "bankruptcy", "dividend", "buyback",
    "downgrade", "upgrade", "investigation",
]
