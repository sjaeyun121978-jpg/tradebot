import asyncio
import re
import os
import json
import time
import requests
import pandas as pd
import ta
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from datetime import datetime

# =========================
# 환경변수
# =========================
API_ID = int(os.environ.get("TG_API_ID"))
API_HASH = os.environ.get("TG_API_HASH")
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
CHAT_ID = os.environ.get("TG_CHAT_ID")

SESSION_STRING = os.environ.get("SESSION_STRING")

BYBIT_API_KEY = os.environ.get("BYBIT_API_KEY")
BYBIT_API_SECRET = os.environ.get("BYBIT_API_SECRET")

# =========================
# 설정 (핵심)
# =========================
ENABLE_AUTO_TRADE = False   # 처음엔 False
DRY_RUN = True              # 반드시 True로 시작

USDT_PER_TRADE = 5
MAX_LEVERAGE = 5

# 중복 진입 방지
last_trade_time = {}

# =========================
# 텔레그램 전송
# =========================
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

# =========================
# Bybit 가격 조회
# =========================
def get_current_price(symbol):
    try:
        url = f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={symbol}USDT"
        r = requests.get(url, timeout=5).json()
        return float(r["result"]["list"][0]["lastPrice"])
    except:
        return None

# =========================
# 캔들 조회
# =========================
def get_candles(symbol, interval="1", limit=50):
    try:
        url = f"https://api.bybit.com/v5/market/kline?category=linear&symbol={symbol}USDT&interval={interval}&limit={limit}"
        r = requests.get(url, timeout=5).json()
        return r["result"]["list"]
    except:
        return []

# =========================
# 급등 판단 로직 (핵심)
# =========================
def classify_trade(symbol):

    candles = get_candles(symbol, "1", 30)
    if not candles:
        return "SKIP", None

    df = pd.DataFrame(candles, columns=["time","open","high","low","close","volume","turnover"])
    df = df.iloc[::-1].astype(float)

    price = df["close"].iloc[-1]
    prev_price = df["close"].iloc[-3]

    change = (price - prev_price) / prev_price * 100
    volume_spike = df["volume"].iloc[-1] / df["volume"].mean()

    # =========================
    # 분기 로직
    # =========================

    if change > 2 and volume_spike > 2:
        return "MARKET_LONG", price

    if change > 2 and volume_spike < 2:
        pullback_price = price * 0.98
        return "LIMIT_LONG", pullback_price

    return "SKIP", None

# =========================
# 주문 (DRY_RUN 포함)
# =========================
def execute_trade(symbol, trade_type, price):

    now = time.time()

    # 중복 방지 (3분)
    if symbol in last_trade_time:
        if now - last_trade_time[symbol] < 180:
            return

    last_trade_time[symbol] = now

    qty = round((USDT_PER_TRADE * MAX_LEVERAGE) / price, 3)

    if DRY_RUN:
        send_telegram(f"[DRY RUN]\n{symbol}\n{trade_type}\n진입가: {price}\n수량: {qty}")
        return

    # 실제 주문
    try:
        url = "https://api.bybit.com/v5/order/create"

        data = {
            "category": "linear",
            "symbol": f"{symbol}USDT",
            "side": "Buy",
            "orderType": "Market" if trade_type == "MARKET_LONG" else "Limit",
            "qty": str(qty)
        }

        if trade_type == "LIMIT_LONG":
            data["price"] = str(price)

        requests.post(url, json=data)

        send_telegram(f"실주문 완료\n{symbol}\n{trade_type}")

    except Exception as e:
        send_telegram(f"주문 실패: {e}")

# =========================
# 메인
# =========================
async def main():
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()

    send_telegram("🚀 자동매매 봇 시작")

    @client.on(events.NewMessage)
    async def handler(event):
        text = event.message.text or ""

        match = re.search(r'#([A-Za-z]{2,10})', text)
        if not match:
            return

        symbol = match.group(1).upper()

        send_telegram(f"{symbol} 분석 시작")

        trade_type, price = classify_trade(symbol)

        if trade_type == "SKIP":
            send_telegram(f"{symbol} → 진입 안함")
            return

        send_telegram(f"{symbol} → {trade_type}")

        if ENABLE_AUTO_TRADE:
            execute_trade(symbol, trade_type, price)

    await client.run_until_disconnected()

# =========================
# 실행
# =========================
try:
    asyncio.run(main())
except Exception as e:
    print(e)
