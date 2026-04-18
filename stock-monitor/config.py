import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT.parent / ".env")

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
FINNHUB_INTERVAL_MINUTES = 5
SEC_INTERVAL_MINUTES = 5
PRICE_POLL_INTERVAL_MINUTES = 2
PRICE_ALERT_THRESHOLD_PCT = 3.0
EARNINGS_CALENDAR_HOUR = 0  # run at 00:05 local time
EARNINGS_CALENDAR_MINUTE = 5
DB_PATH = str(ROOT / "data" / "events.db")
WATCHLIST_PATH = str(ROOT / "watchlist.json")
RETAIN_DAYS = 30
PORT = 8000
SEC_USER_AGENT = "stock-monitor research@example.com"  # SEC requires a UA
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ENRICH_MODEL = os.getenv("ENRICH_MODEL", "claude-haiku-4-5-20251001")
ENRICH_ONLY_HIGH = os.getenv("ENRICH_ONLY_HIGH", "1") == "1"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
BARK_URL = os.getenv("BARK_URL", "")
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK", "")

HIGH_KEYWORDS = [
    "acquisition", "merger", "fda approval", "guidance",
    "ceo", "resign", "bankruptcy", "dividend", "buyback",
    "downgrade", "upgrade", "investigation",
]
