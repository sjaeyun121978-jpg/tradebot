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
# 설정
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
def send_telegram(msg: str):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print(f"텔레그램 전송 실패: {e}")

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
# 급등 판단 로직
# =========================
def classify_trade(symbol):
    candles = get_candles(symbol, "1", 30)
    if not candles:
        return "SKIP", None

    df = pd.DataFrame(candles, columns=["time", "open", "high", "low", "close", "volume", "turnover"])
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

        requests.post(url, json=data, timeout=10)

        send_telegram(f"실주문 완료\n{symbol}\n{trade_type}")

    except Exception as e:
        send_telegram(f"주문 실패: {e}")

# =========================
# 채널/메시지 분류
# =========================
def normalize_text(text: str) -> str:
    return (text or "").strip()

def extract_chat_title(event) -> str:
    try:
        if hasattr(event.chat, "title") and event.chat.title:
            return str(event.chat.title)
        if hasattr(event.chat, "username") and event.chat.username:
            return str(event.chat.username)
        return ""
    except:
        return ""

def is_candle_view_source(chat_title: str, text: str) -> bool:
    source_hit = ("캔들의 신" in chat_title) or ("캔들의신" in chat_title)
    text_hit = any(keyword in text for keyword in [
        "가격이 상승하는것이 중요하지 않습니다",
        "어떤 형태로 상승이 나오고 있는가",
        "추세파동",
        "임펄스",
        "조정파",
        "이 다음 고점을 뚫을때"
    ])
    return source_hit or text_hit

def is_signal_message(text: str) -> bool:
    return re.search(r'#([A-Za-z]{2,10})', text) is not None

# =========================
# 캔들의신 관점 해석 로직
# =========================
def analyze_candle_view(text: str) -> dict:
    """
    캔들의신 관점 메시지를 자동매매와 분리하여
    '현재 판단 / 의도 / 리스크 / 확인조건 / 실전번역' 형태로 해석
    """
    result = {
        "원문요약": "",
        "현재판단": "",
        "핵심의도": "",
        "리스크": "",
        "확인조건": "",
        "실전번역": ""
    }

    # 1. 원문 요약
    if "중요하지 않습니다" in text and "형태" in text:
        result["원문요약"] = "단순 상승 여부보다 상승의 질과 구조가 중요하다는 관점"
    elif "추세파동" in text:
        result["원문요약"] = "현재 움직임을 추세파동으로 볼 수 있는지 검증하라는 관점"
    else:
        result["원문요약"] = "현재 시장 구조를 바로 단정하지 말고 조건 확인 후 판단하라는 관점"

    # 2. 현재 판단
    if "추세파동의 성격" in text and ("어렵" in text or "어렵기" in text):
        result["현재판단"] = "아직 추세 상승/하락 확정 구간이 아님"
    elif "리스크가 존재" in text:
        result["현재판단"] = "방향은 남아있지만 주요 저항/리스크 구간에 위치"
    elif "임펄스" in text and "조정파" in text:
        result["현재판단"] = "다음 움직임의 형태가 확정되기 전까지는 중립 해석이 적절"
    else:
        result["현재판단"] = "현재 메시지는 방향 단정보다 구조 확인을 우선하라는 의미"

    # 3. 핵심 의도
    if "이 다음 고점을 뚫을때" in text or "다음 고점을 뚫을때" in text:
        result["핵심의도"] = "다음 고점 돌파가 나와도 그 돌파의 질을 확인하라는 뜻"
    elif "리스크" in text:
        result["핵심의도"] = "현재 위치에서는 추격보다 리스크 관리가 더 중요하다는 뜻"
    else:
        result["핵심의도"] = "지금 당장 진입보다 조건 확인과 구조 해석을 우선하라는 뜻"

    # 4. 리스크
    range_match = re.search(r'\((\d+[\~\-]\d+)\)', text)
    if range_match:
        result["리스크"] = f"{range_match.group(1)} 구간은 여전히 리스크 구간"
    elif "리스크" in text:
        result["리스크"] = "현재 구간은 실패 시 되밀림 가능성이 존재"
    else:
        result["리스크"] = "확정되지 않은 구간에서의 추격 진입은 위험"

    # 5. 확인 조건
    conditions = []
    if "고점" in text and ("뚫" in text or "돌파" in text):
        conditions.append("다음 고점 돌파 여부")
    if "임펄스" in text:
        conditions.append("돌파 시 임펄스성 강한 캔들/거래량 동반 여부")
    if "조정파" in text:
        conditions.append("돌파가 조정파 형태인지 여부")
    if not conditions:
        conditions.append("다음 방향성 확인 전까지 추가 구조 확인 필요")
    result["확인조건"] = " / ".join(conditions)

    # 6. 실전 번역
    if "임펄스" in text and "조정파" in text:
        result["실전번역"] = "지금은 추격 진입보다, 다음 돌파가 강한 추세 돌파인지 확인 후 판단"
    elif "추세파동의 성격" in text and ("어렵" in text or "어렵기" in text):
        result["실전번역"] = "방향 확정 전 구간으로 보고 관망 또는 매우 보수적 대응이 적절"
    else:
        result["실전번역"] = "현재는 관점 공유 단계이며, 매매 신호로 바로 해석하지 않는 것이 맞음"

    return result

def format_candle_view_message(title: str, analysis: dict) -> str:
    return (
        f"📘 캔들의신 관점 해석\n\n"
        f"채널: {title}\n\n"
        f"1) 원문 요약\n{analysis['원문요약']}\n\n"
        f"2) 현재 판단\n{analysis['현재판단']}\n\n"
        f"3) 핵심 의도\n{analysis['핵심의도']}\n\n"
        f"4) 리스크\n{analysis['리스크']}\n\n"
        f"5) 확인 조건\n{analysis['확인조건']}\n\n"
        f"6) 실전 번역\n{analysis['실전번역']}"
    )

# =========================
# 메인
# =========================
async def main():
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()

    send_telegram("🚀 자동매매/관점해석 봇 시작")

    @client.on(events.NewMessage)
    async def handler(event):
        text = normalize_text(event.message.text or "")
        if not text:
            return

        chat_title = extract_chat_title(event)

        # =====================================
        # 1. 캔들의신 관점 메시지 처리 (자동매매와 완전 분리)
        # =====================================
        if is_candle_view_source(chat_title, text):
            analysis = analyze_candle_view(text)
            message = format_candle_view_message(chat_title or "캔들의신", analysis)
            send_telegram(message)
            return

        # =====================================
        # 2. 급등주/해시태그 신호 메시지 처리
        # =====================================
        if not is_signal_message(text):
            return

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
