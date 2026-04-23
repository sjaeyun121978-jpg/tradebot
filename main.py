import asyncio
import re
import os
import json
import time
import base64
import hashlib
import hmac
from datetime import datetime
from typing import Optional, List, Dict, Any

import requests
import pandas as pd
import ta
import anthropic
import gspread
from google.oauth2.service_account import Credentials
from telethon import TelegramClient, events
from telethon.sessions import StringSession

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

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_KEY")
GOOGLE_SHEETS_KEY = os.environ.get("GOOGLE_SHEETS_KEY")
GOOGLE_SHEETS_ID = os.environ.get("GOOGLE_SHEETS_ID")

# =========================
# 설정
# =========================
ENABLE_AUTO_TRADE = False   # 처음엔 False
DRY_RUN = True              # 반드시 True로 시작

USDT_PER_TRADE = 5
MAX_LEVERAGE = 5

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_TIMEOUT = 30.0

# 중복 진입 방지
last_trade_time: Dict[str, float] = {}

# 정보성 키워드
INFO_KEYWORDS = [
    "오더북", "매물대", "히트맵", "체결", "위험", "지지", "저항", "돌파", "이탈",
    "롱", "숏", "청산", "펀딩", "미결제약정", "파동", "엘리엇", "추세", "채널", "다이버전스"
]

# 개돼지기법 키워드
GAEDWAEJI_KEYWORDS = [
    "일봉", "주봉", "월봉", "시나리오", "1안", "2안", "3안", "전고"
]

# =========================
# 공통 유틸
# =========================
def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def send_telegram(msg: str, chat_id: Optional[str] = None):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(
            url,
            data={"chat_id": chat_id or CHAT_ID, "text": msg},
            timeout=10
        )
    except Exception as e:
        print(f"텔레그램 전송 실패: {e}")


async def run_blocking(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


def normalize_text(text: str) -> str:
    return (text or "").strip()


def extract_chat_title(event) -> str:
    try:
        if getattr(event.chat, "title", None):
            return str(event.chat.title)
        if getattr(event.chat, "username", None):
            return str(event.chat.username)
        return ""
    except Exception:
        return ""


def is_signal_message(text: str) -> bool:
    return re.search(r'#([A-Za-z]{2,10})', text) is not None


def is_info_message(text: str) -> bool:
    return any(keyword in text for keyword in INFO_KEYWORDS)


def is_gaedwaeji_message(text: str) -> bool:
    return any(keyword in text for keyword in GAEDWAEJI_KEYWORDS)


def is_candle_view_source(chat_title: str, text: str) -> bool:
    text_no_space = text.replace(" ", "")
    name_hit = ("캔들의 신" in (chat_title or "")) or ("캔들의신" in (chat_title or ""))
    keyword_hit = any(keyword in text_no_space for keyword in [
        "상승하는것이중요하지않습니다",
        "형태로상승",
        "추세파동",
        "임펄스",
        "조정파",
        "고점을뚫을때",
        "고점뚫을때",
        "관점"
    ])
    return name_hit or keyword_hit


# =========================
# Claude API
# =========================
def get_anthropic_client():
    if not ANTHROPIC_KEY:
        raise ValueError("ANTHROPIC_KEY 환경변수가 없습니다.")
    return anthropic.Anthropic(api_key=ANTHROPIC_KEY, timeout=CLAUDE_TIMEOUT)


def call_claude(prompt: str) -> str:
    client = get_anthropic_client()
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text


def call_claude_vision(image_bytes: bytes, prompt: str) -> str:
    client = get_anthropic_client()
    image_data = base64.standard_b64encode(image_bytes).decode("utf-8")

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=800,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": image_data
                    }
                },
                {
                    "type": "text",
                    "text": prompt
                }
            ]
        }]
    )
    return response.content[0].text


# =========================
# Bybit API
# =========================
def _bybit_headers(payload: str = "") -> Dict[str, str]:
    ts = str(int(time.time() * 1000))
    recv_window = "5000"
    sign_str = ts + BYBIT_API_KEY + recv_window + payload
    signature = hmac.new(
        BYBIT_API_SECRET.encode(),
        sign_str.encode(),
        hashlib.sha256
    ).hexdigest()

    return {
        "X-BAPI-API-KEY": BYBIT_API_KEY,
        "X-BAPI-TIMESTAMP": ts,
        "X-BAPI-SIGN": signature,
        "X-BAPI-RECV-WINDOW": recv_window,
        "Content-Type": "application/json"
    }


def get_current_price(symbol: str):
    try:
        url = f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={symbol}USDT"
        r = requests.get(url, timeout=5).json()
        return float(r["result"]["list"][0]["lastPrice"])
    except Exception:
        return None


def get_candles(symbol: str, interval: str = "1", limit: int = 50):
    try:
        url = f"https://api.bybit.com/v5/market/kline?category=linear&symbol={symbol}USDT&interval={interval}&limit={limit}"
        r = requests.get(url, timeout=5).json()
        return r["result"]["list"]
    except Exception:
        return []


def calculate_indicators(symbol: str) -> Optional[Dict[str, Any]]:
    candles = get_candles(symbol, "15", 60)
    if not candles:
        return None

    try:
        df = pd.DataFrame(
            candles,
            columns=["time", "open", "high", "low", "close", "volume", "turnover"]
        )
        df = df.iloc[::-1].reset_index(drop=True)

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        # RSI
        df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi()

        # MACD
        macd = ta.trend.MACD(df["close"])
        df["macd"] = macd.macd()
        df["macd_signal"] = macd.macd_signal()
        df["macd_diff"] = macd.macd_diff()

        # 볼린저밴드
        bb = ta.volatility.BollingerBands(df["close"], window=20)
        df["bb_upper"] = bb.bollinger_hband()
        df["bb_lower"] = bb.bollinger_lband()
        df["bb_mid"] = bb.bollinger_mavg()

        # EMA
        df["ema20"] = ta.trend.EMAIndicator(df["close"], window=20).ema_indicator()
        df["ema50"] = ta.trend.EMAIndicator(df["close"], window=50).ema_indicator()

        # 거래량 평균
        df["vol_ma20"] = df["volume"].rolling(window=20).mean()

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        return {
            "rsi": round(float(latest["rsi"]), 2),
            "macd": round(float(latest["macd"]), 4),
            "macd_signal": round(float(latest["macd_signal"]), 4),
            "macd_diff": round(float(latest["macd_diff"]), 4),
            "macd_cross": "골든크로스" if latest["macd_diff"] > 0 and prev["macd_diff"] <= 0 else "데드크로스" if latest["macd_diff"] < 0 and prev["macd_diff"] >= 0 else "없음",
            "bb_upper": round(float(latest["bb_upper"]), 4),
            "bb_lower": round(float(latest["bb_lower"]), 4),
            "bb_mid": round(float(latest["bb_mid"]), 4),
            "ema20": round(float(latest["ema20"]), 4),
            "ema50": round(float(latest["ema50"]), 4),
            "ema_cross": "정배열" if latest["ema20"] > latest["ema50"] else "역배열",
            "vol_ratio": round(float(latest["volume"]) / float(latest["vol_ma20"]), 2) if float(latest["vol_ma20"]) > 0 else 0,
            "close": round(float(latest["close"]), 4),
            "high": round(float(latest["high"]), 4),
            "low": round(float(latest["low"]), 4),
        }
    except Exception:
        return None


# =========================
# Google Sheets
# =========================
def get_sheets_client():
    try:
        if not GOOGLE_SHEETS_KEY or not GOOGLE_SHEETS_ID:
            return None

        key_data = json.loads(GOOGLE_SHEETS_KEY)
        scopes = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(key_data, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        print(f"Sheets 연결 실패: {e}")
        return None


def save_to_sheets(sheet_name: str, data_row: List[Any]) -> bool:
    try:
        gc = get_sheets_client()
        if not gc:
            return False

        sh = gc.open_by_key(GOOGLE_SHEETS_ID)
        try:
            ws = sh.worksheet(sheet_name)
        except Exception:
            ws = sh.add_worksheet(title=sheet_name, rows=1000, cols=20)

        ws.append_row([str(x) for x in data_row])
        return True
    except Exception as e:
        print(f"Sheets 저장 실패({sheet_name}): {e}")
        return False


def get_recent_records(sheet_name: str, limit: int = 5) -> List[List[str]]:
    try:
        gc = get_sheets_client()
        if not gc:
            return []

        sh = gc.open_by_key(GOOGLE_SHEETS_ID)
        ws = sh.worksheet(sheet_name)
        rows = ws.get_all_values()
        return rows[-limit:] if len(rows) > limit else rows
    except Exception as e:
        print(f"Sheets 조회 실패({sheet_name}): {e}")
        return []


# =========================
# 급등주 판단 로직
# =========================
def classify_trade(symbol: str):
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
# 주문
# =========================
def execute_trade(symbol: str, trade_type: str, price: float):
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

    try:
        body = {
            "category": "linear",
            "symbol": f"{symbol}USDT",
            "side": "Buy",
            "orderType": "Market" if trade_type == "MARKET_LONG" else "Limit",
            "qty": str(qty)
        }

        if trade_type == "LIMIT_LONG":
            body["price"] = str(price)

        payload = json.dumps(body, separators=(",", ":"))
        headers = _bybit_headers(payload)

        requests.post(
            "https://api.bybit.com/v5/order/create",
            headers=headers,
            data=payload,
            timeout=10
        )

        send_telegram(f"실주문 완료\n{symbol}\n{trade_type}")

    except Exception as e:
        send_telegram(f"주문 실패: {e}")


# =========================
# 캔들의신 관점 해석
# =========================
def analyze_candle_view(text: str) -> str:
    text_no_space = text.replace(" ", "")

    result = {
        "원문요약": "현재 시장 구조를 단정하지 말고 조건을 확인하라는 관점",
        "현재판단": "방향 확정 전 구간",
        "핵심의도": "지금 진입보다 구조 확인이 우선",
        "리스크": "확정되지 않은 구간에서의 추격 진입 위험",
        "확인조건": "다음 고점/저점 확인 필요",
        "실전번역": "지금은 관점 공유 단계이며, 매매 신호로 바로 해석하지 않는 것이 맞음"
    }

    if "상승하는것이중요하지않습니다" in text_no_space and "형태" in text_no_space:
        result["원문요약"] = "단순 상승 여부보다 상승의 질과 구조가 중요하다는 관점"

    if "추세파동" in text_no_space and ("어렵" in text_no_space or "어렵기" in text_no_space):
        result["현재판단"] = "아직 추세파동으로 확정하기 어려운 구간"
        result["실전번역"] = "방향 확정 전 구간으로 보고 관망 또는 보수적 대응이 적절"

    if "임펄스" in text_no_space and "조정파" in text_no_space:
        result["핵심의도"] = "다음 돌파가 강한 추세 돌파인지 약한 조정파인지 구분하라는 뜻"
        result["확인조건"] = "다음 고점 돌파 시 임펄스성 강한 캔들/거래량 동반 여부 확인"
        result["실전번역"] = "지금은 추격 진입보다, 다음 돌파의 질을 확인 후 판단"

    if "리스크" in text:
        result["리스크"] = "현재 구간은 실패 시 되밀림 가능성이 존재"

    range_match = re.search(r'(\d+\s*[\~\-]\s*\d+)', text)
    if range_match:
        result["리스크"] = f"{range_match.group(1)} 구간은 리스크 구간"

    return (
        "📘 캔들의신 관점 해석\n\n"
        f"1) 원문 요약\n{result['원문요약']}\n\n"
        f"2) 현재 판단\n{result['현재판단']}\n\n"
        f"3) 핵심 의도\n{result['핵심의도']}\n\n"
        f"4) 리스크\n{result['리스크']}\n\n"
        f"5) 확인 조건\n{result['확인조건']}\n\n"
        f"6) 실전 번역\n{result['실전번역']}"
    )


# =================
