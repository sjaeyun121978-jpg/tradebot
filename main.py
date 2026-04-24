import asyncio

from bybit_client import get_current_price, get_candles
from indicators import calculate_indicators
from telegram_utils import send_telegram_message
from scheduler import hourly_fact_analysis_loop
from structure_analyzer import analyze_market_structure
from entry_timing import judge_entry_timing


SYMBOLS = ["ETH", "BTC"]

last_signal = {
    "ETH": None,
    "BTC": None
}


async def condition_monitor_loop():
    while True:
        try:
            for symbol in SYMBOLS:
                price = await asyncio.to_thread(get_current_price, symbol)

                candles_15m = await asyncio.to_thread(get_candles, symbol, "15", 100)
                candles_1h = await asyncio.to_thread(get_candles, symbol, "60", 100)
                candles_4h = await asyncio.to_thread(get_candles, symbol, "240", 100)
                candles_1d = await asyncio.to_thread(get_candles, symbol, "D", 100)

                indicators = await asyncio.to_thread(calculate_indicators, candles_15m)

                if not price or not indicators:
                    continue

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


async def main():
    send_telegram_message(
        "🚀 모듈분리 봇 시작\n"
        "ETH/BTC 정시 분석 + 실전 타점 감시 활성화"
    )

    asyncio.create_task(hourly_fact_analysis_loop("ETH"))
    asyncio.create_task(hourly_fact_analysis_loop("BTC"))

    asyncio.create_task(condition_monitor_loop())

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
