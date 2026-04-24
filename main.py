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
from sheets import save_to_sheets
from scheduler import hourly_fact_analysis_loop


SYMBOLS = ["ETH", "BTC"]

INFO_KEYWORDS = [
    "오더북","매물대","히트맵","체결","위험","지지","저항",
    "돌파","이탈","롱","숏","청산","펀딩","미결제약정",
    "파동","엘리엇","추세","채널","다이버전스"
]

GAEDWAEJI_KEYWORDS = [
    "일봉","주봉","월봉","시나리오","1안","2안","3안","전고"
]

BOT_IGNORE_KEYWORDS = [
    "모듈분리 봇 시작","봇 시작","정시 팩트기반구조분석",
    "실전 타점 알림","즉시 조건 알림","조건 감시 오류"
]

last_signal = {"ETH": None, "BTC": None}


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


async def run(func, *args):
    return await asyncio.to_thread(func, *args)


def extract_symbol(text):
    m = re.search(r"#([A-Za-z]{2,10})", text)
    return m.group(1).upper() if m else None


def is_bot(text):
    return any(k in text for k in BOT_IGNORE_KEYWORDS)


def is_info(text):
    return any(k in text for k in INFO_KEYWORDS)


def is_gaedwaeji(text):
    return any(k in text for k in GAEDWAEJI_KEYWORDS)


def is_candle(chat, text):
    t = text.replace(" ", "")
    return (
        "캔들의신" in chat or
        any(k in t for k in ["임펄스","조정파","추세파동","관점"])
    )


async def build(symbol):
    price = await run(get_current_price, symbol)

    c15 = await run(get_candles, symbol, "15", 100)
    c1h = await run(get_candles, symbol, "60", 100)
    c4h = await run(get_candles, symbol, "240", 100)
    c1d = await run(get_candles, symbol, "D", 100)

    ind = await run(calculate_indicators, c15)

    if not price or not ind:
        return price, None

    structure = await run(
        analyze_market_structure,
        {"15M": c15, "1H": c1h, "4H": c4h, "1D": c1d}
    )

    ind["structure"] = structure
    return price, ind


# =========================
# 실전 타점 감시
# =========================
async def monitor():
    while True:
        try:
            for s in SYMBOLS:
                price, ind = await build(s)
                if not price or not ind:
                    continue

                t = judge_entry_timing(s, price, ind)

                if t:
                    key = f"{t['signal']}_{t['type']}"
                    if last_signal[s] != key:
                        send_telegram_message(
                            f"🚨 {s} 실전 타점\n\n{t['message']}"
                        )
                        last_signal[s] = key
                else:
                    last_signal[s] = None

        except Exception as e:
            send_telegram_message(f"❌ 감시 오류: {e}")

        await asyncio.sleep(10)


# =========================
# 급등주 분석
# =========================
async def analyze_coin(symbol, chat, text):
    send_telegram_message(f"⚡ {symbol} 급등 감지")

    price, ind = await build(symbol)
    if not ind:
        return

    result = await run(analyze_fact, symbol, price, ind)

    send_telegram_message(
        f"📊 {symbol} 급등 분석\n채널:{chat}\n\n{result}"
    )

    trade, entry = await run(classify_trade, symbol)

    if trade != "SKIP" and ENABLE_AUTO_TRADE:
        await run(execute_trade, symbol, trade, entry)


# =========================
# 메인
# =========================
async def main():
    client = TelegramClient(
        StringSession(SESSION_STRING),
        TG_API_ID,
        TG_API_HASH
    )

    await client.start()

    send_telegram_message("🚀 시스템 풀가동")

    asyncio.create_task(hourly_fact_analysis_loop("ETH"))
    asyncio.create_task(hourly_fact_analysis_loop("BTC"))
    asyncio.create_task(monitor())

    @client.on(events.NewMessage)
    async def handler(event):
        try:
            if event.out:
                return

            text = (event.message.text or "").strip()
            if not text or text.startswith("/") or is_bot(text):
                return

            chat = str(getattr(event.chat, "title", ""))

            # 1️⃣ 캔들의신
            if is_candle(chat, text):
                r = await run(analyze_candle_view, text)
                send_telegram_message(f"📘 관점\n{r}")
                return

            # 2️⃣ 개돼지
            if is_gaedwaeji(text):
                r = await run(analyze_gaedwaeji, text)
                send_telegram_message(f"🐷 시나리오\n{r}")
                return

            # 3️⃣ ⭐ 급등주 (#심볼 우선)
            symbol = extract_symbol(text)
            if symbol:
                await analyze_coin(symbol, chat, text)
                return

            # 4️⃣ 정보성 (맨 마지막)
            if is_info(text):
                r = await run(analyze_info, text)
                send_telegram_message(f"📊 정보\n{r}")
                return

        except Exception as e:
            send_telegram_message(f"❌ 오류:{e}")

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
