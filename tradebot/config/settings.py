import os
from datetime import timezone, timedelta

KST = timezone(timedelta(hours=9))

def env_bool(name, default=False):
    return os.getenv(name, str(default).lower()).strip().lower() in ("1", "true", "yes", "y", "on")

TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN") or os.getenv("TG_BOT_TOKEN") or ""
TELEGRAM_CHAT_ID  = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TG_CHAT_ID") or ""
TELEGRAM_MIN_INTERVAL_SEC = float(os.getenv("TELEGRAM_MIN_INTERVAL_SEC", "1.2"))

BYBIT_BASE_URL   = os.getenv("BYBIT_BASE_URL", "https://api.bybit.com")
BYBIT_CATEGORY   = os.getenv("BYBIT_CATEGORY", "linear")
BYBIT_API_KEY    = os.getenv("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "")

SYMBOLS = [s.strip().upper() for s in os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT").split(",") if s.strip()]
LOOP_SLEEP_SEC = int(os.getenv("LOOP_SLEEP_SEC", "20"))
STEP_COOLDOWN_SEC = int(os.getenv("STEP_COOLDOWN_SEC", "300"))
STEP_RUN_ON_15M_CLOSE_ONLY = env_bool("STEP_RUN_ON_15M_CLOSE_ONLY", False)

# 운영 스위치: STEP 메시지만 ON, 나머지는 OFF
ENABLE_STEP_MESSAGE = env_bool("ENABLE_STEP_MESSAGE", True)
ENABLE_ENTRY_RADAR = False
ENABLE_1H_BRIEFING = False
ENABLE_HOURLY_DASHBOARD = False
ENABLE_DAILY_BRIEFING = False
ENABLE_WEEKLY_BRIEFING = False
ENABLE_GOOGLE_SHEET = False
ENABLE_GOOGLE_SHEETS = False
ENABLE_AUTO_TRADE = False
ENABLE_SHEETS = False
ENABLE_INFO_ANALYSIS = False
ENABLE_MARKET_STATE = False
ENABLE_ENTRY_FILTER = False
ENABLE_SCENARIO = False
ENABLE_TRADE_JOURNAL = False
ENABLE_JOURNAL_UPDATE = False
ENABLE_JOURNAL = False

CANDLE_TTL = {"15m": 60, "30m": 90, "1h": 180, "4h": 600, "1d": 1800, "1w": 3600}
BYBIT_INTERVAL_MAP = {"1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "4h": "240", "1d": "D", "1w": "W"}
