import asyncio
import re
import os
import json
import requests
import anthropic
import gspread
from google.oauth2.service_account import Credentials
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from datetime import datetime

API_ID = 29053680
API_HASH = "3a70519636127aafe34f7cb61e8bea1c"
BOT_TOKEN = "8664715398:AAH79xEFTw3P0oMRWUXVUVXkPVWvkQsu69k"
CHAT_ID = "5393720278"
ANTHROPIC_KEY = "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"
SESSION_STRING = os.environ.get("SESSION_STRING")
GOOGLE_SHEETS_KEY = os.environ.get("GOOGLE_SHEETS_KEY")
GOOGLE_SHEETS_ID = os.environ.get("GOOGLE_SHEETS_ID")

CHANNEL_IDS = [-1003332441222, -1002931696159]

INFO_KEYWORDS = [
    "오더북", "매물대", "히트맵", "체결", "위험",
    "유효하지 않음", "지지", "저항", "돌파", "이탈",
    "롱", "숏", "청산", "펀딩", "미결제약정",
    "파동", "엘리엇", "추세", "채널", "다이버전스"
]

GAEDWAEJI_KEYWORDS = ["기준", "일봉", "주봉", "월봉", "시나리오", "1안", "2안", "3안", "전고"]

def get_sheets_client():
    try:
        key_data = json.loads(GOOGLE_SHEETS_KEY)
        scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(key_data, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        print(f"Sheets 연결 실패: {e}")
        return None

def save_to_sheets(sheet_name, data_row):
    try:
        gc = get_sheets_client()
        if not gc:
            return False
        sh = gc.open_by_key(GOOGLE_SHEETS_ID)
        try:
            ws = sh.worksheet(sheet_name)
        except:
            ws = sh.add_worksheet(title=sheet_name, rows=1000, cols=10)
        ws.append_row(data_row)
        return True
    except Exception as e:
        print(f"Sheets 저장 실패: {e}")
        return False

def get_recent_records(sheet_name, limit=5):
    try:
        gc = get_sheets_client()
        if not gc:
            return []
        sh = gc.open_by_key(GOOGLE_SHEETS_ID)
        ws = sh.worksheet(sheet_name)
        rows = ws.get_all_values()
        return rows[-limit:] if len(rows) > limit else rows
    except Exception as e:
        print(f"Sheets 조회 실패: {e}")
        return []

def send_telegram(msg, chat_id=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": chat_id or CHAT_ID,
        "text": msg,
        "parse_mode": "HTML"
    })

def is_info_message(text):
    return any(kw in text for kw in INFO_KEYWORDS)

def is_gaedwaeji_message(text):
    return any(kw in text for kw in GAEDWAEJI_KEYWORDS)

def analyze_stock(ticker, comment):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    result = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content": f"""
종목: {ticker}
코멘트: {comment}

아래 형식으로만 답해:
판단: 지금진입가능 또는 눌림대기 또는 진입금지
진입가:
손절가:
1차타깃:
2차타깃:
핵심: 한줄요약
주의: 한줄주의사항
"""}]
    )
    return result.content[0].text

def analyze_info(text):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    result = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{"role": "user", "content": f"""
당신은 전문 암호화폐 트레이더입니다.
아래 정보성 메시지를 분석하여 판단하세요.

메시지 내용:
{text}

아래 형식으로만 답해:
코인:
상황: 한줄요약
판단: 상승우세 또는 하락우세 또는 중립관망
대응: 지금진입 또는 손절필요 또는 관망대기
핵심근거: 기술적 근거 한줄
주의사항: 한줄
"""}]
    )
    return result.content[0].text

def analyze_gaedwaeji(text):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    result = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        messages=[{"role": "user", "content": f"""
당신은 전문 암호화폐 트레이더입니다.
아래는 개돼지기법 채널의 기준 시나리오 게시글입니다.

게시글:
{text}

아래 형식으로만 답해:
코인:
시간봉:
기준일:
1안:
2안:
3안:
핵심방향:
전고A:
주의:
"""}]
    )
    return result.content[0].text

def format_stock_msg(ticker, result):
    판단아이콘 = "🟢" if "지금진입가능" in result else "🟡" if "눌림대기" in result else "🔴"
    lines = result.strip().split('\n')
    msg = f"⚡ <b>{ticker}</b>\n\n"
    for line in lines:
        if "판단:" in line:
            msg += f"{판단아이콘} {line.split(':')[1].strip()}\n\n"
        elif "진입가:" in line:
            msg += f"진입: {line.split(':')[1].strip()}\n"
        elif "손절가:" in line:
            msg += f"손절: {line.split(':')[1].strip()}\n"
        elif "1차타깃:" in line:
            msg += f"1차: {line.split(':')[1].strip()}\n"
        elif "2차타깃:" in line:
            msg += f"2차: {line.split(':')[1].strip()}\n"
        elif "핵심:" in line:
            msg += f"\n📌 {line.split(':')[1].strip()}\n"
        el
