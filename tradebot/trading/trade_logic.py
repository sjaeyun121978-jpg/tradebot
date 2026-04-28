import time
import pandas as pd

from tradebot.config.settings import USDT_PER_TRADE, MAX_LEVERAGE, DRY_RUN, ENABLE_AUTO_TRADE
from tradebot.data.bybit_client import get_candles
from tradebot.delivery.telegram import send_message as send_telegram_message


last_trade_time = {}


def _candles_to_dataframe(candles):
    if not candles:
        return pd.DataFrame()

    df = pd.DataFrame(candles)
    df = df.rename(columns={"open_time": "time"})

    required = ["time", "open", "high", "low", "close", "volume"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"missing candle columns: {missing}")

    df = df[required].copy()
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["close", "volume"])
    return df.sort_values("time")


def classify_trade(symbol):
    if not ENABLE_AUTO_TRADE:
        return "SKIP", None

    candles = get_candles(symbol, "1", 30)

    if not candles:
        return "SKIP", None

    try:
        df = _candles_to_dataframe(candles)
        if len(df) < 3:
            return "SKIP", None

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
    if not ENABLE_AUTO_TRADE:
        send_telegram_message(f"{symbol} → 자동매매 블록 비활성화 상태라 주문 실행 스킵")
        return

    if price is None or price <= 0:
        send_telegram_message(f"{symbol} → 유효하지 않은 가격으로 주문 실행 스킵: {price}")
        return

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
