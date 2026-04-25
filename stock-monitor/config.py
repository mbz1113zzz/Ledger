import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT.parent / ".env")

FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
FINNHUB_INTERVAL_MINUTES = 5
FINNHUB_ENABLE_NEWS = os.getenv("FINNHUB_ENABLE_NEWS", "1") == "1"
FINNHUB_ENABLE_EARNINGS = os.getenv("FINNHUB_ENABLE_EARNINGS", "1") == "1"
FINNHUB_ENABLE_ANALYST = os.getenv("FINNHUB_ENABLE_ANALYST", "0") == "1"
FINNHUB_ENABLE_SENTIMENT = os.getenv("FINNHUB_ENABLE_SENTIMENT", "0") == "1"
SEC_INTERVAL_MINUTES = 5
PRICE_POLL_INTERVAL_MINUTES = 2
PRICE_ALERT_THRESHOLD_PCT = 3.0
EARNINGS_CALENDAR_HOUR = 0  # run at 00:05 local time
EARNINGS_CALENDAR_MINUTE = 5
DB_PATH = os.getenv("DB_PATH", str(ROOT / "data" / "events.db"))
WATCHLIST_PATH = os.getenv("WATCHLIST_PATH", str(ROOT / "watchlist.json"))
RETAIN_DAYS = 30
BACKUP_ENABLED = os.getenv("BACKUP_ENABLED", "1") == "1"
BACKUP_HOUR = int(os.getenv("BACKUP_HOUR", "3"))  # local time
BACKUP_MINUTE = int(os.getenv("BACKUP_MINUTE", "30"))
BACKUP_KEEP_DAYS = int(os.getenv("BACKUP_KEEP_DAYS", "14"))
PORT = 8000
SEC_USER_AGENT = "stock-monitor research@example.com"  # SEC requires a UA
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
ENRICH_PROVIDER = os.getenv(
    "ENRICH_PROVIDER",
    "deepseek" if os.getenv("DEEPSEEK_API_KEY") else "anthropic",
).lower()
ENRICH_MODEL = os.getenv(
    "ENRICH_MODEL",
    "deepseek-chat" if ENRICH_PROVIDER == "deepseek" else "claude-haiku-4-5-20251001",
)
ENRICH_ONLY_HIGH = os.getenv("ENRICH_ONLY_HIGH", "1") == "1"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
BARK_URL = os.getenv("BARK_URL", "")
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK", "")

DIGEST_ENABLED = os.getenv("DIGEST_ENABLED", "1") == "1"
DIGEST_HOUR = int(os.getenv("DIGEST_HOUR", "13"))  # 13:00 UTC = 09:00 EDT pre-open
DIGEST_MINUTE = int(os.getenv("DIGEST_MINUTE", "0"))
DIGEST_LOOKBACK_HOURS = int(os.getenv("DIGEST_LOOKBACK_HOURS", "24"))

# IBKR realtime
IBKR_ENABLED = os.getenv("IBKR_ENABLED", "1") == "1"
IBKR_HOST = os.getenv("IBKR_HOST", "127.0.0.1")
IBKR_PORT = int(os.getenv("IBKR_PORT", "7497"))
IBKR_CLIENT_ID = int(os.getenv("IBKR_CLIENT_ID", "42"))
IBKR_STARTUP_TIMEOUT_SEC = float(os.getenv("IBKR_STARTUP_TIMEOUT_SEC", "5"))

# Tiered anomaly detection (independent alert channel)
ANOMALY_TIERS = [("low", 0.005), ("medium", 0.01), ("high", 0.03)]
ANOMALY_COOLDOWN_SEC = 300

# SMC
SMC_STRUCTURE_TF = "5m"
SMC_ENTRY_TF = "1m"
SMC_FRACTAL_WINDOW = 5
SMC_OB_MAX_AGE_MIN = 120
SMC_MAX_RISK_PCT = float(os.getenv("SMC_MAX_RISK_PCT", "0.015"))
SMC_MIN_RR = float(os.getenv("SMC_MIN_RR", "2.0"))
SMC_TICK_SIZE = float(os.getenv("SMC_TICK_SIZE", "0.01"))

# Paper broker
PAPER_ENABLED = os.getenv("PAPER_ENABLED", "1") == "1"
PAPER_INITIAL_CASH = float(os.getenv("PAPER_INITIAL_CASH", "10000"))
PAPER_MAX_POSITION_PCT = float(os.getenv("PAPER_MAX_POSITION_PCT", "0.20"))
PAPER_MAX_RISK_PER_TRADE_PCT = float(
    os.getenv("PAPER_MAX_RISK_PER_TRADE_PCT", "0.01")
)
PAPER_MAX_HOLD_MIN = int(os.getenv("PAPER_MAX_HOLD_MIN", "60"))
PAPER_BREAK_EVEN_ENABLED = os.getenv("PAPER_BREAK_EVEN_ENABLED", "1") == "1"
PAPER_BREAK_EVEN_R = float(os.getenv("PAPER_BREAK_EVEN_R", "1.0"))
PAPER_MAX_POSITIONS = int(os.getenv("PAPER_MAX_POSITIONS", "5"))
PAPER_MAX_DAY_DRAWDOWN_PCT = float(os.getenv("PAPER_MAX_DAY_DRAWDOWN_PCT", "0.03"))
PAPER_MAX_GROSS_EXPOSURE_PCT = float(os.getenv("PAPER_MAX_GROSS_EXPOSURE_PCT", "0.50"))
PAPER_MAX_OPEN_RISK_PCT = float(os.getenv("PAPER_MAX_OPEN_RISK_PCT", "0.03"))
PAPER_SLIPPAGE_BPS = float(os.getenv("PAPER_SLIPPAGE_BPS", "5"))
PAPER_COMMISSION_PER_SHARE = float(os.getenv("PAPER_COMMISSION_PER_SHARE", "0.005"))
PAPER_COMMISSION_MIN = float(os.getenv("PAPER_COMMISSION_MIN", "1.0"))
PAPER_EOD_HOUR_ET = int(os.getenv("PAPER_EOD_HOUR_ET", "15"))
PAPER_EOD_MINUTE_ET = int(os.getenv("PAPER_EOD_MINUTE_ET", "50"))
REVIEW_HOUR_ET = int(os.getenv("REVIEW_HOUR_ET", "16"))
REVIEW_MINUTE_ET = int(os.getenv("REVIEW_MINUTE_ET", "15"))

# Earnings calendar
EARNINGS_BLACKOUT_ENABLED = os.getenv("EARNINGS_BLACKOUT_ENABLED", "1") == "1"
EARNINGS_BLACKOUT_BEFORE_MIN = int(os.getenv("EARNINGS_BLACKOUT_BEFORE_MIN", "990"))   # 16h30m — covers ET-day for AMC
EARNINGS_BLACKOUT_AFTER_MIN = int(os.getenv("EARNINGS_BLACKOUT_AFTER_MIN", "1080"))    # 18h — covers next pre-market
EARNINGS_SURPRISE_HIGH_PCT = float(os.getenv("EARNINGS_SURPRISE_HIGH_PCT", "0.05"))    # 5%
EARNINGS_REACTION_BACKFILL_DELAY_MIN = int(os.getenv("EARNINGS_REACTION_BACKFILL_DELAY_MIN", "30"))
EARNINGS_REACTION_BACKFILL_TIMEOUT_HOURS = int(os.getenv("EARNINGS_REACTION_BACKFILL_TIMEOUT_HOURS", "6"))
EARNINGS_STALE_LOOKBACK_DAYS = int(os.getenv("EARNINGS_STALE_LOOKBACK_DAYS", "7"))

# Execution guardrails
EXECUTION_MODE = os.getenv("EXECUTION_MODE", "paper")
LIVE_TRADING_ENABLED = os.getenv("LIVE_TRADING_ENABLED", "0") == "1"
LIVE_EXECUTION_IMPLEMENTED = os.getenv("LIVE_EXECUTION_IMPLEMENTED", "0") == "1"
LIVE_READINESS_MIN_CLOSED_TRADES = int(os.getenv("LIVE_READINESS_MIN_CLOSED_TRADES", "20"))
LIVE_READINESS_MIN_WIN_RATE_PCT = float(os.getenv("LIVE_READINESS_MIN_WIN_RATE_PCT", "50"))
LIVE_READINESS_MIN_AVG_RR = float(os.getenv("LIVE_READINESS_MIN_AVG_RR", "1.0"))

HIGH_KEYWORDS = [
    "acquisition", "merger", "fda approval", "guidance",
    "ceo", "resign", "bankruptcy", "dividend", "buyback",
    "downgrade", "upgrade", "investigation",
]
