import asyncio

from bybit_client import get_current_price, get_candles
from indicators import calculate_indicators
from telegram_utils import send_telegram_message
from scheduler import hourly_fact_analysis_loop


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
                candles = await asyncio.to_thread(get_candles, symbol, "15", 60)
                indicators = await asyncio.to_thread(calculate_indicators, candles)

                if not price or not indicators:
                    continue

                rsi = indicators.get("rsi", 50)
                volume_ratio = indicators.get("vol_ratio", 0)

                signal = None

                if symbol == "ETH":
                    short_price = 2295
                    long_price = 2315
                else:
                    short_price = 77000
                    long_price = 78500

                # 🔴 숏 조건
                if (
                    volume_ratio >= 1.2
                    and price < short_price
                    and rsi <= 30
                ):
                    signal = "SHORT"

                # 🟢 롱 조건
                elif (
                    volume_ratio >= 1.2
                    and price > long_price
                    and rsi >= 50
                ):
                    signal = "LONG"

                if signal and last_signal[symbol] != signal:
                    send_telegram_message(
                        f"🚨 {symbol} 즉시 조건 알림\n"
                        f"현재가: {price}\n"
                        f"신호: {signal}\n"
                        f"거래량비율: {round(volume_ratio, 2)}\n\n"
                        f"※ 자동진입 아님. 확인용 알림."
                    )

                    last_signal[symbol] = signal

                if signal is None:
                    last_signal[symbol] = None

        except Exception as e:
            send_telegram_message(f"❌ 조건 감시 오류: {e}")

        await asyncio.sleep(10)


async def main():
    send_telegram_message("🚀 모듈분리 봇 시작\nETH/BTC 정시 분석 + 조건 감시 활성화")

    # 정시 분석
    asyncio.create_task(hourly_fact_analysis_loop("ETH"))
    asyncio.create_task(hourly_fact_analysis_loop("BTC"))

    # 실시간 조건 감시
    asyncio.create_task(condition_monitor_loop())

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
