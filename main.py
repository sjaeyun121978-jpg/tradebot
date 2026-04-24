import asyncio
import re
import time
from datetime import datetime

from telethon import TelegramClient, events
from telethon.sessions import StringSession

from config import TG_API_ID, TG_API_HASH, SESSION_STRING, ENABLE_AUTO_TRADE
from telegram_utils import send_telegram_message
from bybit_client import get_current_price, get_candles
from indicators import calculate_indicators
from structure_analyzer import analyze_market_structure
from entry_timing import judge_entry_timing, get_entry_debug_status
from analyzers import analyze_info, analyze_gaedwaeji, analyze_candle_view, analyze_fact
from trade_logic import classify_trade, execute_trade
from sheets import save_to_sheets, get_recent_records
from scheduler import hourly_fact_analysis_loop


SYMBOLS = ["ETH", "BTC"]

INFO_KEYWORDS = [
    "오더북", "매물대", "히트맵", "체결", "위험", "지지", "저항",
    "돌파", "이탈", "롱", "숏", "청산", "펀딩", "미결제약정",
    "파동", "엘리엇", "추세", "채널", "다이버전스"
]

GAEDWAEJI_KEYWORDS = [
    "일봉", "주봉", "월봉", "시나리오", "1안", "2안", "3안", "전고"
]

BOT_IGNORE_KEYWORDS = [
    "모듈분리 봇 시작", "봇 시작", "정시 팩트기반구조분석",
    "실전 타점 알림", "즉시 조건 알림", "조건 감시 오류",
    "급등주 AI 분석 시작", "진입 레이더"
]

last_signal = {"ETH": None, "BTC": None}
last_debug_time = {"ETH": 0, "BTC": 0}
last_debug_score = {"ETH": 0, "BTC": 0}


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


async def run_blocking(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


def extract_chat_title(event):
    try:
        return str(
            getattr(event.chat, "title", None)
            or getattr(event.chat, "username", None)
            or ""
        )
    except Exception:
        return ""


def extract_symbol(text):
    match = re.search(r"#([A-Za-z]{2,10})", text)
    return match.group(1).upper() if match else None


def is_bot_message(text):
    return any(keyword in text for keyword in BOT_IGNORE_KEYWORDS)


def is_info_message(text):
    return any(keyword in text for keyword in INFO_KEYWORDS)


def is_gaedwaeji_message(text):
    return any(keyword in text for keyword in GAEDWAEJI_KEYWORDS)


def is_candle_view_message(chat_title, text):
    compact = text.replace(" ", "")
    return (
        "캔들의 신" in chat_title
        or "캔들의신" in chat_title
        or any(k in compact for k in [
            "상승하는것이중요하지않습니다",
            "형태로상승",
            "추세파동",
            "임펄스",
            "조정파",
            "관점"
        ])
    )


async def build_indicators_with_structure(symbol):
    price = await run_blocking(get_current_price, symbol)

    candles_15m = await run_blocking(get_candles, symbol, "15", 100)
    candles_1h = await run_blocking(get_candles, symbol, "60", 100)
    candles_4h = await run_blocking(get_candles, symbol, "240", 100)
    candles_1d = await run_blocking(get_candles, symbol, "D", 100)

    indicators = await run_blocking(calculate_indicators, candles_15m)

    if not price or not indicators:
        return price, None

    structure = await run_blocking(
        analyze_market_structure,
        {
            "15M": candles_15m,
            "1H": candles_1h,
            "4H": candles_4h,
            "1D": candles_1d,
        }
    )

    indicators["structure"] = structure
    return price, indicators


async def condition_monitor_loop():
    while True:
        try:
            for symbol in SYMBOLS:
                price, indicators = await build_indicators_with_structure(symbol)

                if not price or not indicators:
                    continue

                # ✅ 진입 신호
                timing = judge_entry_timing(symbol, price, indicators)

                if timing:
                    signal_key = f"{timing['signal']}_{timing['type']}"

                    if last_signal[symbol] != signal_key:
                        send_telegram_message(
                            f"🚨 {symbol} 실전 타점\n\n{timing['message']}"
                        )
                        last_signal[symbol] = signal_key
                    continue

                last_signal[symbol] = None

                # 🛰️ 레이더 (조건 진행률)
                debug = get_entry_debug_status(symbol, price, indicators)

                if debug:
                    now = time.time()
                    score = debug["score"]

                    if (
                        score >= 60
                        and (
                            now - last_debug_time[symbol] >= 300
                            or score >= last_debug_score[symbol] + 10
                        )
                    ):
                        send_telegram_message(
                            f"🛰️ {symbol} 진입 레이더\n\n"
                            f"방향: {debug['signal']}\n"
                            f"조건충족: {score}%\n"
                            f"가격: {price}\n\n"
                            f"{debug['detail']}"
                        )

                        last_debug_time[symbol] = now
                        last_debug_score[symbol] = score

        except Exception as e:
            send_telegram_message(f"❌ 조건 감시 오류: {e}")

        await asyncio.sleep(10)


async def analyze_geupdeungju(symbol, chat_title, text):
    send_telegram_message(f"⚡ {symbol} 급등주 분석 시작")

    price, indicators = await build_indicators_with_structure(symbol)

    if not price or not indicators:
        send_telegram_message("❌ 데이터 부족")
        return

    result = await run_blocking(analyze_fact, symbol, price, indicators)

    send_telegram_message(
        f"📊 {symbol} 분석\n\n현재가: {price}\n\n{result}"
    )


async def main():
    client = TelegramClient(
        StringSession(SESSION_STRING),
        TG_API_ID,
        TG_API_HASH
    )

    await client.start()

    send_telegram_message(
        f"🚀 봇 시작\nAUTO_TRADE={ENABLE_AUTO_TRADE}"
    )

    asyncio.create_task(hourly_fact_analysis_loop("ETH"))
    asyncio.create_task(hourly_fact_analysis_loop("BTC"))
    asyncio.create_task(condition_monitor_loop())

    @client.on(events.NewMessage)
    async def handler(event):
        try:
            if event.out:
                return

            text = (event.message.text or "").strip()

            if not text or text.startswith("/") or is_bot_message(text):
                return

            chat_title = extract_chat_title(event)

            # 캔들의신
            if is_candle_view_message(chat_title, text):
                result = await run_blocking(analyze_candle_view, text)
                send_telegram_message(f"📘 캔들 해석\n\n{result}")
                return

            # 개돼지
            if is_gaedwaeji_message(text):
                result = await run_blocking(analyze_gaedwaeji, text)
                send_telegram_message(f"🐷 시나리오 분석\n\n{result}")
                return

            # 코인 분석 (#BTC)
            symbol = extract_symbol(text)
            if symbol:
                await analyze_geupdeungju(symbol, chat_title, text)
                return

            # 일반 정보
            if is_info_message(text):
                result = await run_blocking(analyze_info, text)
                send_telegram_message(f"📊 정보 분석\n\n{result}")
                return

        except Exception as e:
            send_telegram_message(f"❌ 처리 오류: {e}")

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
