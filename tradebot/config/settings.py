import os
from datetime import timezone, timedelta

KST = timezone(timedelta(hours=9))


def env_bool(name, default=False):
    return os.getenv(name, str(default).lower()).strip().lower() in ("1", "true", "yes", "y", "on")


TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN") or os.getenv("TG_BOT_TOKEN") or ""
TELEGRAM_CHAT_ID  = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TG_CHAT_ID") or ""

ANTHROPIC_KEY  = os.getenv("ANTHROPIC_KEY", "")
CLAUDE_MODEL   = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
CLAUDE_TIMEOUT = float(os.getenv("CLAUDE_TIMEOUT", "30.0"))

BYBIT_BASE_URL   = os.getenv("BYBIT_BASE_URL", "https://api.bybit.com")
BYBIT_CATEGORY   = os.getenv("BYBIT_CATEGORY", "linear")
BYBIT_API_KEY    = os.getenv("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "")

SYMBOLS = [s.strip().upper() for s in os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT").split(",") if s.strip()]

LOOP_SLEEP_SEC            = int(os.getenv("LOOP_SLEEP_SEC",            "20"))
PRICE_SKIP_THRESHOLD      = float(os.getenv("PRICE_SKIP_THRESHOLD",    "0.0003"))
SAME_ALERT_COOLDOWN_SEC   = int(os.getenv("SAME_ALERT_COOLDOWN_SEC",   "900"))
TELEGRAM_MIN_INTERVAL_SEC = float(os.getenv("TELEGRAM_MIN_INTERVAL_SEC", "1.2"))
MAX_LOOP_ERROR_COUNT      = int(os.getenv("MAX_LOOP_ERROR_COUNT",      "10"))

# ── 기능 스위치 ─────────────────────────────────
ENABLE_SHEETS           = env_bool("ENABLE_SHEETS",           False)
ENABLE_ENTRY_RADAR      = env_bool("ENABLE_ENTRY_RADAR",      True)
ENABLE_HOURLY_DASHBOARD = env_bool("ENABLE_HOURLY_DASHBOARD", True)
ENABLE_DAILY_BRIEFING   = env_bool("ENABLE_DAILY_BRIEFING",   True)
ENABLE_PRE_REAL         = env_bool("ENABLE_PRE_REAL",         True)
ENABLE_INFO_ANALYSIS    = env_bool("ENABLE_INFO_ANALYSIS",    False)
ENABLE_MARKET_STATE     = env_bool("ENABLE_MARKET_STATE",     True)
ENABLE_ENTRY_FILTER     = env_bool("ENABLE_ENTRY_FILTER",     True)
ENABLE_SCENARIO         = env_bool("ENABLE_SCENARIO",         True)

# ── 레거시 journal 호환 ──────────────────────────
ENABLE_TRADE_JOURNAL        = env_bool("ENABLE_TRADE_JOURNAL",    True)
ENABLE_JOURNAL_UPDATE       = env_bool("ENABLE_JOURNAL_UPDATE",   True)
JOURNAL_UPDATE_INTERVAL_SEC = int(os.getenv("JOURNAL_UPDATE_INTERVAL_SEC", "3600"))

# ── 복기 시스템 v9 ──────────────────────────────
ENABLE_JOURNAL       = env_bool("ENABLE_JOURNAL",       True)
JOURNAL_STORAGE      = os.getenv("JOURNAL_STORAGE",     "csv")
JOURNAL_DIR          = os.getenv("JOURNAL_DIR",         "data/journal")
JOURNAL_SIGNAL_FILE  = os.getenv("JOURNAL_SIGNAL_FILE", "signals.csv")
JOURNAL_SUMMARY_FILE = os.getenv("JOURNAL_SUMMARY_FILE","journal_summary.csv")
JOURNAL_EXPIRE_HOURS = int(os.getenv("JOURNAL_EXPIRE_HOURS",  "24"))
JOURNAL_MIN_RR       = float(os.getenv("JOURNAL_MIN_RR",      "1.5"))
JOURNAL_TRACK_15M    = env_bool("JOURNAL_TRACK_15M", True)
JOURNAL_TRACK_1H     = env_bool("JOURNAL_TRACK_1H",  True)
JOURNAL_TRACK_4H     = env_bool("JOURNAL_TRACK_4H",  True)
JOURNAL_TRACK_24H    = env_bool("JOURNAL_TRACK_24H", True)

# ── Google Sheets 연동 (신규 v10) ────────────────
ENABLE_GOOGLE_SHEETS         = env_bool("ENABLE_GOOGLE_SHEETS",         False)
GOOGLE_SHEET_ID              = os.getenv("GOOGLE_SHEET_ID",             "")
GOOGLE_SERVICE_ACCOUNT_JSON  = (
    os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    or os.getenv("GOOGLE_SHEETS_KEY")
    or ""
)
GOOGLE_SHEET_SIGNALS_TAB     = os.getenv("GOOGLE_SHEET_SIGNALS_TAB",    "signals")
GOOGLE_SHEET_SUMMARY_TAB     = os.getenv("GOOGLE_SHEET_SUMMARY_TAB",    "summary")

# ── 일일 리포트 자동 전송 ────────────────────────
ENABLE_DAILY_JOURNAL_REPORT  = env_bool("ENABLE_DAILY_JOURNAL_REPORT",  True)
DAILY_JOURNAL_REPORT_HOUR    = int(os.getenv("DAILY_JOURNAL_REPORT_HOUR",   "23"))
DAILY_JOURNAL_REPORT_MINUTE  = int(os.getenv("DAILY_JOURNAL_REPORT_MINUTE", "50"))

# 신호 간격
ENTRY_ANALYSIS_INTERVAL_SEC = int(os.getenv("ENTRY_ANALYSIS_INTERVAL_SEC", "30"))
INFO_ANALYSIS_INTERVAL_SEC  = int(os.getenv("INFO_ANALYSIS_INTERVAL_SEC",  "300"))

CANDLE_TTL = {
    "15m": 60,  "30m": 90,  "1h": 180,
    "4h": 600,  "1d": 1800, "1w": 3600,
}
BYBIT_INTERVAL_MAP = {
    "1m": "1",  "3m": "3",  "5m": "5",  "15m": "15",
    "30m": "30","1h": "60", "4h": "240","1d": "D",  "1w": "W",
}

# ── 전략 어드바이저 (v11 신규) ───────────────────
ENABLE_STRATEGY_ADVISOR    = env_bool("ENABLE_STRATEGY_ADVISOR",  True)
ADVISOR_MIN_SIGNALS        = int(os.getenv("ADVISOR_MIN_SIGNALS",   "50"))
ADVISOR_RECENT_DAYS        = int(os.getenv("ADVISOR_RECENT_DAYS",   "7"))
ADVISOR_REPORT_HOUR        = int(os.getenv("ADVISOR_REPORT_HOUR",   "23"))
ADVISOR_REPORT_MINUTE      = int(os.getenv("ADVISOR_REPORT_MINUTE", "55"))
ADVISOR_TELEGRAM           = env_bool("ADVISOR_TELEGRAM",           True)

# 추천 임계값
THRESH_LONG_WINRATE_LOW    = float(os.getenv("THRESH_LONG_WINRATE_LOW",  "0.45"))
THRESH_SHORT_WINRATE_LOW   = float(os.getenv("THRESH_SHORT_WINRATE_LOW", "0.45"))
THRESH_RANGE_SL_HIGH       = float(os.getenv("THRESH_RANGE_SL_HIGH",     "0.50"))
THRESH_LOW_RR              = float(os.getenv("THRESH_LOW_RR",            "1.5"))
THRESH_TP1_RATE_GOOD       = float(os.getenv("THRESH_TP1_RATE_GOOD",     "0.55"))
ENABLE_AUTO_TRADE = env_bool("ENABLE_AUTO_TRADE", False)
DRY_RUN           = env_bool("DRY_RUN", True)
USDT_PER_TRADE    = float(os.getenv("USDT_PER_TRADE", "5"))
MAX_LEVERAGE      = int(os.getenv("MAX_LEVERAGE", "5"))
