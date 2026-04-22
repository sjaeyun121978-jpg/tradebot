import asyncio
import re
import os
import json
import base64
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
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_KEY")
SESSION_STRING = os.environ.get("SESSION_STRING")
GOOGLE_SHEETS_KEY = os.environ.get("GOOGLE_SHEETS_KEY")
GOOGLE_SHEETS_ID = os.environ.get("GOOGLE_SHEETS_ID")

CHANNEL_IDS = [-1003332441222, -1002931696159, "godofcandle"]

INFO_KEYWORDS = ["오더북","매물대","히트맵","체결","위험","유효하지 않음","지지","저항","돌파","이탈","롱","숏","청산","펀딩","미결제약정","파동","엘리엇","추세","채널","다이버전스"]
GAEDWAEJI_KEYWORDS = ["일봉","주봉","월봉","시나리오","1안","2안","3안","전고"]

def get_current_price(symbol):
    try:
        symbol_lower = symbol.lower()
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={symbol_lower}&vs_currencies=usd"
        r = requests.get(url, timeout=5)
        data = r.json()
        if symbol_lower in data:
            return data[symbol_lower]["usd"]
        # 심볼로 검색
        search_url = f"https://api.coingecko.com/api/v3/search?query={symbol}"
        r2 = requests.get(search_url, timeout=5)
        results = r2.json().get("coins", [])
        if results:
            coin_id = results[0]["id"]
            url2 = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
            r3 = requests.get(url2, timeout=5)
            data2 = r3.json()
            if coin_id in data2:
                return data2[coin_id]["usd"]
        return None
    except Exception as e:
        print(f"가격 조회 실패: {e}")
        return None

def get_sheets_client():
    try:
        key_data = json.loads(GOOGLE_SHEETS_KEY)
        scopes = ["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/drive"]
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
    requests.post(url, data={"chat_id": chat_id or CHAT_ID, "text": msg, "parse_mode": "HTML"})

def is_info_message(text):
    return any(kw in text for kw in INFO_KEYWORDS)

def is_gaedwaeji_message(text):
    return any(kw in text for kw in GAEDWAEJI_KEYWORDS)

def analyze_image(image_bytes, caption=""):
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        image_data = base64.standard_b64encode(image_bytes).decode("utf-8")
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data}},
            {"type": "text", "text": f"당신은 전문 암호화폐 트레이더입니다.\n차트 이미지를 분석하세요.\n캡션: {caption}\n\n아래 형식으로만 답해:\n코인:\n시간봉:\n패턴:\n현재위치:\n판단: 상승우세 또는 하락우세 또는 중립관망\n대응: 지금진입 또는 손절필요 또는 관망대기\n핵심근거: 한줄\n주의: 한줄"}
        ]
        result = client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=500, messages=[{"role":"user","content":content}])
        return result.content[0].text
    except Exception as e:
        print(f"이미지 분석 실패: {e}")
        return None

def analyze_stock(ticker, comment, current_price=None):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    price_info = f"현재가: ${current_price}" if current_price else "현재가: 조회 실패"
    result = client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=400,
        messages=[{"role":"user","content":f"종목: {ticker}\n{price_info}\n코멘트: {comment}\n\n현재가 기준으로 아래 형식으로만 답해:\n판단: 지금진입가능 또는 눌림대기 또는 진입금지\n진입가:\n손절가:\n1차타깃:\n2차타깃:\n손익비:\n핵심: 한줄요약\n주의: 한줄주의사항"}])
    return result.content[0].text

def analyze_info(text):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    result = client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=500,
        messages=[{"role":"user","content":f"당신은 전문 암호화폐 트레이더입니다.\n메시지:\n{text}\n\n아래 형식으로만 답해:\n코인:\n상황: 한줄요약\n판단: 상승우세 또는 하락우세 또는 중립관망\n대응: 지금진입 또는 손절필요 또는 관망대기\n핵심근거: 기술적 근거 한줄\n주의사항: 한줄"}])
    return result.content[0].text

def analyze_gaedwaeji(text):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    result = client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=600,
        messages=[{"role":"user","content":f"당신은 전문 암호화폐 트레이더입니다.\n개돼지기법 기준 시나리오:\n{text}\n\n아래 형식으로만 답해:\n코인:\n시간봉:\n기준일:\n1안:\n2안:\n3안:\n핵심방향:\n전고A:\n주의:"}])
    return result.content[0].text

def format_stock_msg(ticker, result, current_price=None):
    판단아이콘 = "🟢" if "지금진입가능" in result else "🟡" if "눌림대기" in result else "🔴"
    price_str = f"💰 현재가: ${current_price}\n" if current_price else ""
    lines = result.strip().split('\n')
    msg = f"⚡ <b>{ticker}</b>\n{price_str}\n"
    for line in lines:
        if "판단:" in line: msg += f"{판단아이콘} {line.split(':')[1].strip()}\n\n"
        elif "진입가:" in line: msg += f"진입: {line.split(':')[1].strip()}\n"
        elif "손절가:" in line: msg += f"손절: {line.split(':')[1].strip()}\n"
        elif "1차타깃:" in line: msg += f"1차: {line.split(':')[1].strip()}\n"
        elif "2차타깃:" in line: msg += f"2차: {line.split(':')[1].strip()}\n"
        elif "손익비:" in line: msg += f"손익비: {line.split(':')[1].strip()}\n"
        elif "핵심:" in line: msg += f"\n📌 {line.split(':')[1].strip()}\n"
        elif "주의:" in line: msg += f"⚠️ {line.split(':')[1].strip()}\n"
    return msg

def format_info_msg(result):
    lines = result.strip().split('\n')
    판단아이콘 = "🟢" if "상승우세" in result else "🔴" if "하락우세" in result else "🟡"
    대응아이콘 = "⚡" if "지금진입" in result else "🚨" if "손절필요" in result else "👀"
    msg = f"📊 <b>시장 정보 분석</b>\n\n"
    for line in lines:
        if not line.strip(): continue
        if "코인:" in line: msg += f"🪙 {line.split(':')[1].strip()}\n"
        elif "상황:" in line: msg += f"📌 {line.split(':')[1].strip()}\n\n"
        elif "판단:" in line: msg += f"{판단아이콘} 판단: {line.split(':')[1].strip()}\n"
        elif "대응:" in line: msg += f"{대응아이콘} 대응: {line.split(':')[1].strip()}\n\n"
        elif "핵심근거:" in line: msg += f"🔍 근거: {line.split(':')[1].strip()}\n"
        elif "주의사항:" in line: msg += f"⚠️ 주의: {line.split(':')[1].strip()}\n"
    return msg

def format_gaedwaeji_msg(result):
    msg = f"🐷 <b>개돼지기법 기준 분석</b>\n\n"
    lines = result.strip().split('\n')
    for line in lines:
        if not line.strip(): continue
        if "코인:" in line: msg += f"🪙 {line}\n"
        elif "시간봉:" in line: msg += f"⏱ {line}\n"
        elif "기준일:" in line: msg += f"📅 {line}\n\n"
        elif "1안:" in line: msg += f"1️⃣ {line}\n"
        elif "2안:" in line: msg += f"2️⃣ {line}\n"
        elif "3안:" in line: msg += f"3️⃣ {line}\n\n"
        elif "핵심방향:" in line: msg += f"🎯 {line}\n"
        elif "전고A:" in line: msg += f"📍 {line}\n"
        elif "주의:" in line: msg += f"⚠️ {line}\n"
    return msg

def format_image_msg(result):
    판단아이콘 = "🟢" if "상승우세" in result else "🔴" if "하락우세" in result else "🟡"
    대응아이콘 = "⚡" if "지금진입" in result else "🚨" if "손절필요" in result else "👀"
    msg = f"📈 <b>차트 이미지 분석</b>\n\n"
    lines = result.strip().split('\n')
    for line in lines:
        if not line.strip(): continue
        if "코인:" in line: msg += f"🪙 {line}\n"
        elif "시간봉:" in line: msg += f"⏱ {line}\n"
        elif "패턴:" in line: msg += f"📊 {line}\n"
        elif "현재위치:" in line: msg += f"📍 {line}\n\n"
        elif "판단:" in line: msg += f"{판단아이콘} {line}\n"
        elif "대응:" in line: msg += f"{대응아이콘} {line}\n\n"
        elif "핵심근거:" in line: msg += f"🔍 {line}\n"
        elif "주의:" in line: msg += f"⚠️ {line}\n"
    return msg

async def main():
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    send_telegram("✅ 모니터링 시작! 멍꼴단+캔들의신 감시 중...")

    @client.on(events.NewMessage(chats=CHANNEL_IDS))
    async def handler(event):
        text = event.message.text or ""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        if event.message.photo:
            send_telegram("📸 차트 이미지 분석 중...")
            image_bytes = await event.message.download_media(bytes)
            result = analyze_image(image_bytes, caption=text)
            if result:
                send_telegram(format_image_msg(result))
                save_to_sheets("이미지분석", [now, text[:100], result])
            return

        if not text:
            return

        if is_info_message(text):
            send_telegram("🔍 시장 정보 분석 중...")
            result = analyze_info(text)
            send_telegram(format_info_msg(result))
            save_to_sheets("정보분석", [now, text[:100], result])
            return

        if is_gaedwaeji_message(text):
            send_telegram("🐷 개돼지기법 기준 분석 중...")
            result = analyze_gaedwaeji(text)
            send_telegram(format_gaedwaeji_msg(result))
            save_to_sheets("개돼지기준", [now, text[:200], result])
            return

        match = re.search(r'#([A-Za-z가-힣]{2,15})', text)
        if match:
            ticker = match.group(1)
            send_telegram(f"🔍 {ticker} 실시간 가격 조회 중...")
            current_price = get_current_price(ticker)
            result = analyze_stock(ticker, text, current_price)
            send_telegram(format_stock_msg(ticker, result, current_price))
            save_to_sheets("급등주", [now, ticker, str(current_price), result])

    @client.on(events.NewMessage(pattern='/복기'))
    async def bokgi_handler(event):
        rows = get_recent_records("개돼지기준", 3)
        if not rows:
            await event.respond("📭 저장된 기준 없음")
            return
        msg = "📋 <b>최근 개돼지 기준</b>\n\n"
        for row in rows:
            if row:
                msg += f"📅 {row[0]}\n{row[2]}\n\n{'─'*20}\n\n"
        send_telegram(msg, event.chat_id)

    await client.run_until_disconnected()

try:
    asyncio.run(main())
except Exception as e:
    print(f"에러 발생: {e}")
    import traceback
    traceback.print_exc()
