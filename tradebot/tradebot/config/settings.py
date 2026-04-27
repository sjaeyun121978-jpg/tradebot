import os
from datetime import timezone, timedelta

KST = timezone(timedelta(hours=9))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("TG_BOT_TOKEN") or ""
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TG_CHAT_ID") or ""

ANTHROPIC_KEY = os.getenv("ANTHROPIC_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
CLAUDE_TIMEOUT = float(os.getenv("CLAUDE_TIMEOUT", "30.0"))

BYBIT_BASE_URL = os.getenv("BYBIT_BASE_URL", "https://api.bybit.com")
BYBIT_CATEGORY = os.getenv("BYBIT_CATEGORY", "linear")
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "")

SYMBOLS = [s.strip().upper() for s in os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT").split(",") if s.strip()]

LOOP_SLEEP_SEC = int(os.getenv("LOOP_SLEEP_SEC", "20"))
PRICE_SKIP_THRESHOLD = float(os.getenv("PRICE_SKIP_THRESHOLD", "0.0008"))
SAME_ALERT_COOLDOWN_SEC = int(os.getenv("SAME_ALERT_COOLDOWN_SEC", "900"))
TELEGRAM_MIN_INTERVAL_SEC = float(os.getenv("TELEGRAM_MIN_INTERVAL_SEC", "1.2"))
MAX_LOOP_ERROR_COUNT = int(os.getenv("MAX_LOOP_ERROR_COUNT", "10"))
ENABLE_SHEETS = os.getenv("ENABLE_SHEETS", "false").lower() == "true"

ENTRY_ANALYSIS_INTERVAL_SEC = int(os.getenv("ENTRY_ANALYSIS_INTERVAL_SEC", "60"))
INFO_ANALYSIS_INTERVAL_SEC = int(os.getenv("INFO_ANALYSIS_INTERVAL_SEC", "300"))

CANDLE_TTL = {
    "15m": 60,
    "30m": 90,
    "1h": 180,
    "4h": 600,
    "1d": 1800,
    "1w": 3600,
}

BYBIT_INTERVAL_MAP = {
    "1m": "1",
    "3m": "3",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "4h": "240",
    "1d": "D",
    "1w": "W",
}

ENABLE_AUTO_TRADE = os.getenv("ENABLE_AUTO_TRADE", "false").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
USDT_PER_TRADE = float(os.getenv("USDT_PER_TRADE", "5"))
MAX_LEVERAGE = int(os.getenv("MAX_LEVERAGE", "5"))
