import time
import pandas as pd

from config import USDT_PER_TRADE, MAX_LEVERAGE, DRY_RUN
from bybit_client import get_candles
from telegram_utils import send_telegram_message


last_trade_time = {}


def classify_trade(symbol):
    candles = get_candles(symbol, "1", 30)

    if not candles:
        return "SKIP", None

    try:
        df = pd.DataFrame(
            candles,
            columns=["time", "open", "high", "low", "close", "volume", "turnover"]
        )

        df = df.iloc[::-1].astype(float)

        price = df["close"].iloc[-1]
        prev_price = df["close"].iloc[-3]

        change = (price - prev_price) / prev_price * 100
        volume_spike = df["volume"].iloc[-1] / df["volume"].mean()

        if change > 2 and volume_spike > 2:
            return "MARKET_LONG", price

        if change > 2 and volume_spike < 2:
            pullback_price = price * 0.98
            return "LIMIT_LONG", pullback_price

        return "SKIP", None

    except Exception as e:
        print(f"[자동매매 판단 실패] {e}")
        return "SKIP", None


def execute_trade(symbol, trade_type, price):
    now = time.time()

    if symbol in last_trade_time:
        if now - last_trade_time[symbol] < 180:
            send_telegram_message(f"{symbol} → 중복 진입 방지로 스킵")
            return

    last_trade_time[symbol] = now

    qty = round((USDT_PER_TRADE * MAX_LEVERAGE) / price, 3)

    if DRY_RUN:
        send_telegram_message(
            f"[DRY RUN]\n"
            f"{symbol}\n"
            f"{trade_type}\n"
            f"진입가: {price}\n"
            f"수량: {qty}"
        )
        return

    send_telegram_message(
        f"[실주문 준비]\n"
        f"{symbol}\n"
        f"{trade_type}\n"
        f"진입가: {price}\n"
        f"수량: {qty}\n\n"
        f"주의: 현재 trade_logic.py는 실제 Bybit 주문 실행 전 단계입니다."
    )
