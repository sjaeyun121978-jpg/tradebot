import asyncio
import re
from datetime import datetime

from telethon import TelegramClient, events
from telethon.sessions import StringSession

from config import TG_API_ID, TG_API_HASH, SESSION_STRING, ENABLE_AUTO_TRADE
from telegram_utils import send_telegram_message
from bybit_client import get_current_price, get_candles
from indicators import calculate_indicators
from structure_analyzer import analyze_market_structure
from entry_timing import judge_entry_timing
from analyzers import analyze_info, analyze_gaedwaeji, analyze_candle_view, analyze_fact
from trade_logic import classify_trade, execute_trade
from sheets import save_to_sheets, get_recent_records
from scheduler import hourly_fact_analysis_loop


SYMBOLS = ["ETH", "BTC"]

INFO_KEYWORDS = [
    "오더북", "매물대", "히트맵", "체결", "위험", "지지", "저항", "돌파", "이탈",
    "롱", "숏", "청산", "펀딩", "미결제약정", "파동", "엘리엇", "추세", "채널", "다이버전스"
]

GAEDWAEJI_KEYWORDS = ["일봉", "주봉", "월봉", "시나리오", "1안", "2안", "3안", "전고"]

BOT_IGNORE_KEYWORDS = [
    "모듈분리 봇 시작", "봇 시작", "정시 팩트기반구조분석", "실전 타점 알림",
    "즉시 조건 알림", "조건 감시 오류", "급등주 AI 분석 시작"
]

last_signal = {"ETH": None, "BTC": None}


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


async def run_blocking(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


def extract_chat_title(event):
    try:
        return str(getattr(event.chat, "title", None) or getattr(event.chat, "username", None) or "")
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
            "상승하는것이중요하지않습니다", "형태로상승", "추세파동",
            "임펄스", "조정파", "고점을뚫을때", "고점뚫을때", "관점"
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

                timing = judge_entry_timing(symbol, price, indicators)

                if timing:
                    signal_key = f"{timing['signal']}_{timing['type']}"

                    if last_signal[symbol] != signal_key:
                        send_telegram_message(
                            f"🚨 {symbol} 실전 타점 알림\n\n"
                            f"{timing['message']}\n\n"
                            f"※ 자동진입 아님. 확인용 알림."
                        )
                        last_signal[symbol] = signal_key
                else:
                    last_signal[symbol] = None

        except Exception as e:
            send_telegram_message(f"❌ 조건 감시 오류: {e}")

        await asyncio.sleep(10)


async def analyze_geupdeungju(symbol, chat_title, source_text):
    now = now_str()
    send_telegram_message(f"⚡ {symbol} 급등주 AI 분석 시작")

    price, indicators = await build_indicators_with_structure(symbol)

    if not price or not indicators:
        send_telegram_message(f"❌ {symbol} 데이터 부족으로 분석 실패")
        return

    result = await run_blocking(analyze_fact, symbol, price, indicators)

    send_telegram_message(
        f"📊 {symbol} 급등주 분석\n"
        f"채널: {chat_title}\n"
        f"현재가: {price}\n\n"
        f"{result}"
    )

    await run_blocking(
        save_to_sheets,
        "급등주",
        [now, chat_title, symbol, price, source_text[:200], result]
    )

    trade_type, entry_price = await run_blocking(classify_trade, symbol)

    if trade_type == "SKIP":
        send_telegram_message(f"{symbol} → 자동매매 진입 안함")
        return

    send_telegram_message(f"{symbol} → {trade_type}")

    if ENABLE_AUTO_TRADE:
        await run_blocking(execute_trade, symbol, trade_type, entry_price)
        await run_blocking(save_to_sheets, "자동매매", [now, symbol, trade_type, entry_price])


async def main():
    client = TelegramClient(StringSession(SESSION_STRING), TG_API_ID, TG_API_HASH)
    await client.start()

    send_telegram_message(
        "🚀 봇 시작\n"
        f"ENABLE_AUTO_TRADE={ENABLE_AUTO_TRADE}\n"
        "정시 분석 + 타점 감시 + 채널 분석 활성화"
    )

    asyncio.create_task(hourly_fact_analysis_loop("ETH"))
    asyncio.create_task(hourly_fact_analysis_loop("BTC"))
    asyncio.create_task(condition_monitor_loop())

    @client.on(events.NewMessage(pattern=r"^/복기$"))
    async def bokgi_handler(event):
        rows = await run_blocking(get_recent_records, "개돼지기준", 3)
        await event.respond("📭 저장된 개돼지기준 없음" if not rows else "\n\n".join(" | ".join(r) for r in rows))

    @client.on(events.NewMessage(pattern=r"^/매매현황$"))
    async def trade_status_handler(event):
        rows = await run_blocking(get_recent_records, "자동매매", 5)
        await event.respond("📭 자동매매 내역 없음" if not rows else "\n\n".join(" | ".join(r) for r in rows))

    @client.on(events.NewMessage)
    async def handler(event):
        try:
            if event.out:
                return

            text = (event.message.text or "").strip()

            if not text or text.startswith("/") or is_bot_message(text):
                return

            chat_title = extract_chat_title(event)
            now = now_str()

            if is_candle_view_message(chat_title, text):
                result = await run_blocking(analyze_candle_view, text)
                send_telegram_message(f"📘 캔들의신 관점 해석\n채널: {chat_title}\n\n{result}")
                await run_blocking(save_to_sheets, "캔들의신해석", [now, chat_title, text[:200], result])
                return

            if is_gaedwaeji_message(text):
                result = await run_blocking(analyze_gaedwaeji, text)
                send_telegram_message(f"🐷 개돼지기법 시나리오 분석\n채널: {chat_title}\n\n{result}")
                await run_blocking(save_to_sheets, "개돼지기준", [now, chat_title, text[:200], result])
                return

            if is_info_message(text):
                result = await run_blocking(analyze_info, text)
                send_telegram_message(f"📊 정보성 메시지 분석\n채널: {chat_title}\n\n{result}")
                await run_blocking(save_to_sheets, "정보분석", [now, chat_title, text[:200], result])
                return

            symbol = extract_symbol(text)

            if symbol:
                await analyze_geupdeungju(symbol, chat_title, text)

        except Exception as e:
            send_telegram_message(f"❌ 채널 메시지 처리 오류: {e}")

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
