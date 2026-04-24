import asyncio
from bybit_client import get_current_price, get_candles
from indicators import calculate_indicators
from telegram_utils import send_telegram_message


SYMBOLS = ["ETH", "BTC"]

# 중복 알림 방지
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

                rsi = indicators.get("rsi", 50)
                volume_ratio = indicators.get("volume_ratio", 0)

                signal = None

                # 🔴 숏 조건
                if (
                    volume_ratio >= 1.2
                    and price < 2295 if symbol == "ETH" else price < 77000
                    and rsi <= 30
                ):
                    signal = "SHORT"

                # 🟢 롱 조건
                elif (
                    volume_ratio >= 1.2
                    and price > 2315 if symbol == "ETH" else price > 78500
                    and rsi >= 50
                ):
                    signal = "LONG"

                # 🚨 신호 발생 시
                if signal and last_signal[symbol] != signal:
                    message = (
                        f"🚨 {symbol} 즉시 조건 알림\n"
                        f"현재가: {price}\n"
                        f"신호: {signal}\n"
                        f"거래량비율: {round(volume_ratio,2)}\n\n"
                        f"※ 자동진입 아님. 확인용 알림."
                    )

                    send_telegram_message(message)

                    last_signal[symbol] = signal

        except Exception as e:
            send_telegram_message(f"❌ 조건 감시 오류: {e}")

        await asyncio.sleep(10)  # 10초마다 감시


async def main():
    await condition_monitor_loop()


if __name__ == "__main__":
    asyncio.run(main())
