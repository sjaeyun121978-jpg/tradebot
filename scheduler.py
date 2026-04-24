import asyncio
from datetime import datetime, timedelta

from bybit_client import get_current_price, get_candles
from indicators import calculate_indicators
from analyzers import analyze_fact
from telegram_utils import send_telegram_message
from sheets import save_to_sheets
from structure_analyzer import analyze_market_structure


DEFAULT_SYMBOL = "ETH"


def seconds_until_next_hour():
    now = datetime.now()

    next_hour = (now + timedelta(hours=1)).replace(
        minute=0,
        second=5,
        microsecond=0
    )

    return (next_hour - now).total_seconds()


async def run_once(symbol=DEFAULT_SYMBOL, mode="정시"):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    price = await asyncio.to_thread(get_current_price, symbol)

    candles_15m = await asyncio.to_thread(get_candles, symbol, "15", 100)
    candles_1h = await asyncio.to_thread(get_candles, symbol, "60", 100)
    candles_4h = await asyncio.to_thread(get_candles, symbol, "240", 100)
    candles_1d = await asyncio.to_thread(get_candles, symbol, "D", 100)

    indicators = await asyncio.to_thread(calculate_indicators, candles_15m)

    if indicators is None:
        indicators = {}

    structure = await asyncio.to_thread(
        analyze_market_structure,
        {
            "15M": candles_15m,
            "1H": candles_1h,
            "4H": candles_4h,
            "1D": candles_1d,
        }
    )

    indicators["structure"] = structure

    result = await asyncio.to_thread(
        analyze_fact,
        symbol,
        price,
        indicators
    )

    message = (
        f"📊 {symbol} {mode} 팩트기반구조분석\n"
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


async def hourly_fact_analysis_loop(symbol=DEFAULT_SYMBOL):
    while True:
        try:
            wait_seconds = seconds_until_next_hour()

            print(
                f"[스케줄러] {symbol} 다음 정시 분석까지 "
                f"{int(wait_seconds)}초 대기"
            )

            await asyncio.sleep(wait_seconds)

            print(f"[스케줄러] {symbol} 정시 분석 실행")

            await run_once(symbol, mode="정시")

            print(f"[스케줄러] {symbol} 정시 분석 완료")

        except Exception as e:
            error_msg = f"❌ {symbol} 정시 분석 오류: {e}"

            print(error_msg)

            try:
                send_telegram_message(error_msg)
            except Exception as telegram_error:
                print(f"[텔레그램 오류 전송 실패] {telegram_error}")

            await asyncio.sleep(60)
