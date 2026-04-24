
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
from analyzers import (
    analyze_info,
    analyze_gaedwaeji,
    analyze_candle_view,
    analyze_fact,
)
from trade_logic import classify_trade, execute_trade
from sheets import save_to_sheets, get_recent_records
from scheduler import hourly_fact_analysis_loop

# =========================
# 🔥 감시 채널 제한 (여기에 네 채널만 넣어라)
# =========================
MONITOR_CHATS = [
    # 예시:
    # -1001234567890,
    # "channel_username",
]

INFO_KEYWORDS = [
    "오더북", "매물대", "히트맵", "체결", "위험", "지지", "저항", "돌파", "이탈",
    "롱", "숏", "청산", "펀딩", "미결제약정", "파동", "엘리엇", "추세", "채널", "다이버전스"
]

GAEDWAEJI_KEYWORDS = [
    "일봉", "주봉", "월봉", "시나리오", "1안", "2안", "3안", "전고"
]

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

def is_info_message(text):
    return any(keyword in text for keyword in INFO_KEYWORDS)

def is_gaedwaeji_message(text):
    return any(keyword in text for keyword in GAEDWAEJI_KEYWORDS)

def is_candle_view_message(chat_title, text):
    text_no_space = text.replace(" ", "")

    title_hit = (
        "캔들의 신" in (chat_title or "")
        or "캔들의신" in (chat_title or "")
    )

    keyword_hit = any(keyword in text_no_space for keyword in [
        "상승하는것이중요하지않습니다",
        "형태로상승",
        "추세파동",
        "임펄스",
        "조정파",
        "고점을뚫을때",
        "고점뚫을때",
        "관점",
    ])

    return title_hit or keyword_hit

def extract_symbol(text):
    match = re.search(r"#([A-Za-z]{2,10})", text)
    if not match:
        return None
    return match.group(1).upper()

async def main():
    client = TelegramClient(
        StringSession(SESSION_STRING),
        TG_API_ID,
        TG_API_HASH
    )

    await client.start()

    send_telegram_message(
        "🚀 모듈분리 봇 시작\n"
        f"ENABLE_AUTO_TRADE={ENABLE_AUTO_TRADE}\n"
        "1시간 자동 팩트기반구조분석 활성화"
    )

    asyncio.create_task(hourly_fact_analysis_loop("ETH"))

    @client.on(events.NewMessage(pattern=r"^/복기$"))
    async def bokgi_handler(event):
        rows = await run_blocking(get_recent_records, "개돼지기준", 3)

        if not rows:
            await event.respond("📭 저장된 개돼지기준 없음")
            return

        msg = "📋 최근 개돼지기준 3개\n\n"
        for row in rows:
            msg += " | ".join(row) + "\n\n"

        await event.respond(msg)

    @client.on(events.NewMessage(pattern=r"^/매매현황$"))
    async def trade_status_handler(event):
        rows = await run_blocking(get_recent_records, "자동매매", 5)

        if not rows:
            await event.respond("📭 자동매매 내역 없음")
            return

        msg = "📊 최근 자동매매 5개\n\n"
        for row in rows:
            msg += " | ".join(row) + "\n\n"

        await event.respond(msg)

    # =========================
    # 🔥 핵심 수정된 부분
    # =========================
    @client.on(events.NewMessage(chats=MONITOR_CHATS))
    async def handler(event):

        # ✅ 봇이 보낸 메시지 무시 (무한루프 차단)
        if event.out:
            return

        text = event.message.text or ""
        text = text.strip()

        if not text:
            return

        if text.startswith("/"):
            return

        chat_title = extract_chat_title(event)
        now = now_str()

        # =========================
        # 1. 이미지
        # =========================
        if event.message.photo:
            send_telegram_message("📸 이미지 메시지 감지됨 (추후 분석 연결 예정)")
            return

        # =========================
        # 2. 캔들의신
        # =========================
        if is_candle_view_message(chat_title, text):
            result = await run_blocking(analyze_candle_view, text)

            send_telegram_message(
                f"📘 캔들의신 관점 해석\n"
                f"채널: {chat_title}\n\n"
                f"{result}"
            )

            await run_blocking(
                save_to_sheets,
                "캔들의신해석",
                [now, chat_title, text[:200], result]
            )
            return

        # =========================
        # 3. 개돼지
        # =========================
        if is_gaedwaeji_message(text):
            send_telegram_message("🐷 개돼지기법 분석 시작")

            result = await run_blocking(analyze_gaedwaeji, text)

            send_telegram_message(result)

            await run_blocking(
                save_to_sheets,
                "개돼지기준",
                [now, chat_title, text[:200], result]
            )
            return

        # =========================
        # 4. 정보
        # =========================
        if is_info_message(text):
            send_telegram_message("📊 정보성 메시지 분석 시작")

            result = await run_blocking(analyze_info, text)

            send_telegram_message(result)

            await run_blocking(
                save_to_sheets,
                "정보분석",
                [now, chat_title, text[:200], result]
            )
            return

        # =========================
        # 5. 급등주
        # =========================
        symbol = extract_symbol(text)

        if not symbol:
            return

        send_telegram_message(f"⚡ {symbol} 급등주 분석 시작")

        price = await run_blocking(get_current_price, symbol)
        candles = await run_blocking(get_candles, symbol, "15", 60)
        indicators = await run_blocking(calculate_indicators, candles)

        fact_result = await run_blocking(
            analyze_fact,
            symbol,
            price,
            indicators
        )

        send_telegram_message(
            f"📊 {symbol} 팩트기반구조분석\n"
            f"현재가: {price}\n\n"
            f"{fact_result}"
        )

        await run_blocking(
            save_to_sheets,
            "급등주",
            [now, symbol, price, fact_result]
        )

        trade_type, entry_price = await run_blocking(classify_trade, symbol)

        if trade_type == "SKIP":
            send_telegram_message(f"{symbol} → 진입 안함")
            return

        send_telegram_message(f"{symbol} → {trade_type}")

        if ENABLE_AUTO_TRADE:
            await run_blocking(execute_trade, symbol, trade_type, entry_price)

            await run_blocking(
                save_to_sheets,
                "자동매매",
                [now, symbol, trade_type, entry_price]
            )

    await client.run_until_disconnected()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"[메인 실행 오류] {e}")
