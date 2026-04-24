import asyncio
import re
from datetime import datetime

from telethon import TelegramClient, events
from telethon.sessions import StringSession

from config import (
    TG_API_ID,
    TG_API_HASH,
    SESSION_STRING,
    ENABLE_AUTO_TRADE,
)

from telegram_utils import send_telegram_message
from bybit_client import get_current_price, get_candles
from indicators import calculate_indicators
from structure_analyzer import analyze_market_structure
from entry_timing import judge_entry_timing
from analyzers import (
    analyze_info,
    analyze_gaedwaeji,
    analyze_candle_view,
    analyze_fact,
)
from trade_logic import classify_trade, execute_trade
from sheets import save_to_sheets, get_recent_records
from scheduler import hourly_fact_analysis_loop


SYMBOLS = ["ETH", "BTC"]

INFO_KEYWORDS = [
    "오더북", "매물대", "히트맵", "체결", "위험", "지지", "저항", "돌파", "이탈",
    "롱", "숏", "청산", "펀딩", "미결제약정", "파동", "엘리엇", "추세", "채널", "다이버전스"
]

GAEDWAEJI_KEYWORDS = [
    "일봉", "주봉", "월봉", "시나리오", "1안", "2안", "3안", "전고"
]

BOT_IGNORE_KEYWORDS = [
    "모듈분리 봇 시작",
    "정시 팩트기반구조분석",
    "실전 타점 알림",
    "즉시 조건 알림",
    "팩트기반구조분석 실패",
    "조건 감시 오류",
    "정보성 메시지 분석 시작",
    "개돼지기법 분석 시작",
    "급등주 AI 분석 시작",
]

last_signal = {
    "ETH": None,
    "BTC": None,
}


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


async def run_blocking(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


def extract_chat_title(event):
    try:
        if getattr(event.chat, "title", None):
            return str(event.chat.title)
        if getattr(event.chat, "username", None):
            return str(event.chat.username)
        return ""
    except Exception:
        return ""


def extract_symbol(text):
    match = re.search(r"#([A-Za-z]{2,10})", text)
    if not match:
        return None
    return match.group(1).upper()


def is_bot_message(text):
    return any(keyword in text for keyword in BOT_IGNORE_KEYWORDS)


def is_info_message(text):
    return any(keyword in text for keyword in INFO_KEYWORDS)


def is_gaedwaeji_message(text):
    return any(keyword in text
