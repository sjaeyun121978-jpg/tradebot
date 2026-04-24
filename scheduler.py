import asyncio
from datetime import datetime, timedelta

from bybit_client import get_current_price, get_candles
from indicators import calculate_indicators
from analyzers import analyze_fact
from telegram_utils import send_telegram_message
from sheets import save_to_sheets


DEFAULT_SYMBOL = "ETH"


def seconds_until_next_hour():
    now = datetime.now()
    next_hour = (now + timedelta(hours=1)).replace(
        minute=0,
        second=5,
        microsecond=0
    )
    return (next_hour - now).total_seconds()


async def hourly_fact_analysis_loop(symbol=DEFAULT_SYMBOL):
    while True:
        wait_seconds = seconds_until_next_hour()
        await asyncio.sleep(wait_seconds)

        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M")

            send_telegram_message(f"⏰ {symbol} 정시 팩트기반구조분석 시작")

            price = await asyncio.to_thread(get_current_price, symbol)
            candles = await asyncio.to_thread(get_candles, symbol, "15", 60)
            indicators = await asyncio.to_thread(calculate_indicators, candles)

            result = await asyncio.to_thread(analyze_fact, symbol, price, indicators)

            message = (
                f"📊 {symbol} 정시 팩트기반구조분석\n"
                f"시간: {now}\n"
                f"현재가: {price}\n\n"
                f"{result}"
            )

            send_telegram_message(message)

            await asyncio.to_thread(
                save_to_sheets,
                "팩트기반분석",
                [now, symbol, price, result]
            )

        except Exception as e:
            send_telegram_message(f"❌ {symbol} 정시 팩트기반구조분석 실패: {e}")
