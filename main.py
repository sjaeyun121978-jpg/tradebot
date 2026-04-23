import asyncio
import re
import os
import json
import base64
import hashlib
import hmac
import time
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
BYBIT_API_KEY = os.environ.get("BYBIT_API_KEY")
BYBIT_API_SECRET = os.environ.get("BYBIT_API_SECRET")

CHANNEL_IDS = [-1003332441222, -1002931696159, "godofcandle"]
INFO_KEYWORDS = ["오더북","매물대","히트맵","체결","위험","유효하지 않음","지지","저항","돌파","이탈","롱","숏","청산","펀딩","미결제약정","파동","엘리엇","추세","채널","다이버전스"]
GAEDWAEJI_KEYWORDS = ["일봉","주봉","월봉","시나리오","1안","2안","3안","전고"]

# ===== Bybit API =====
def bybit_request(method, endpoint, params={}):
    base_url = "https://api.bybit.com"
    ts = str(int(time.time() * 1000))
    recv_window = "5000"
    if method == "GET":
        query = "&".join([f"{k}={v}" for k, v in sorted(params.items())])
        sign_str = ts + BYBIT_API_KEY + recv_window + query
    else:
        body = json.dumps(params)
        sign_str = ts + BYBIT_API_KEY + recv_window + body
    signature = hmac.new(BYBIT_API_SECRET.encode(), sign_str.encode(), hashlib.sha256).hexdigest()
    headers = {
        "X-BAPI-API-KEY": BYBIT_API_KEY,
        "X-BAPI-TIMESTAMP": ts,
        "X-BAPI-SIGN": signature,
        "X-BAPI-RECV-WINDOW": recv_window,
        "Content-Type": "application/json"
    }
    url = base_url + endpoint
    if method == "GET":
        r = requests.get(url, headers=headers, params=params, timeout=10)
    else:
        r = requests.post(url, headers=headers, data=json.dumps(params), timeout=10)
    return r.json()

def get_current_price(symbol):
    try:
        symbol_upper = symbol.upper() + "USDT"
        url = f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={symbol_upper}"
        r = requests.get(url, timeout=5)
        data = r.json()
        if data.get("retCode") == 0:
            items = data.get("result", {}).get("list", [])
            if items:
                return float(items[0]["lastPrice"])
        return None
    except Exception as e:
        print(f"가격 조회 실패: {e}")
        return None

def get_candles(symbol, interval="15", limit=20):
    try:
        symbol_upper = symbol.upper() + "USDT"
        url = f"https://api.bybit.com/v5/market/kline?category=linear&symbol={symbol_upper}&interval={interval}&limit={limit}"
        r = requests.get(url, timeout=5)
        data = r.json()
        if data.get("retCode") == 0:
            return data.get("result", {}).get("list", [])
        return []
    except:
        return []

def place_order(symbol, side, qty, leverage, order_type="Market", price=None, take_profit=None, stop_loss=None):
    try:
        symbol_upper = symbol.upper() + "USDT"
        # 레버리지 설정
        bybit_request("POST", "/v5/position/set-leverage", {
            "category": "linear",
            "symbol": symbol_upper,
            "buyLeverage": str(leverage),
            "sellLeverage": str(leverage)
        })
        params = {
            "category": "linear",
            "symbol": symbol_upper,
            "side": side,
            "orderType": order_type,
            "qty": str(qty),
            "timeInForce": "GTC" if order_type == "Limit" else "IOC",
        }
        if price:
            params["price"] = str(price)
        if take_profit:
            params["takeProfit"] = str(take_profit)
        if stop_loss:
            params["stopLoss"] = str(stop_loss)
        result = bybit_request("POST", "/v5/order/create", params)
        return result
    except Exception as e:
        print(f"주문 실패: {e}")
        return None

def analyze_for_trading(symbol, text, current_price, candles):
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY, timeout=30.0)
        candle_summary = ""
        if candles:
            recent = candles[:5]
            for c in recent:
                candle_summary += f"시가:{c[1]} 고가:{c[2]} 저가:{c[3]} 종가:{c[4]} 거래량:{c[5]}\n"
        result = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": f"""
당신은 전문 암호화폐 트레이더입니다.
코인: {symbol}
현재가: {current_price}
게시물 내용: {text}
최근 15분봉 캔들 (최신순):
{candle_summary}

아래 형식으로만 답해:
진입여부: 즉시진입 또는 눌림대기
레버리지: 10 또는 5
진입가: (즉시진입이면 현재가, 눌림대기면 목표 눌림가)
목표가: (게시물 기준)
손절가: (진입가 기준 -3% 이내)
근거: 한줄
"""}])
        return result.content[0].text
    except Exception as e:
        print(f"매매 분석 실패: {e}")
        return None

def execute_auto_trade(symbol, analysis, current_price):
    try:
        lines = analysis.strip().split('\n')
        data = {}
        for line in lines:
            if ':' in line:
                k, v = line.split(':', 1)
                data[k.strip()] = v.strip()

        entry_type = data.get("진입여부", "")
        leverage = int(data.get("레버리지", "5"))
        entry_price = float(data.get("진입가", current_price))
        target_price = float(data.get("목표가", entry_price * 1.05))
        stop_loss = float(data.get("손절가", entry_price * 0.97))

        # $5 고정 진입 금액
        usdt_amount = 5
        qty = round(usdt_amount * leverage / entry_price, 3)

        if entry_type == "즉시진입":
            result = place_order(
                symbol=symbol,
                side="Buy",
                qty=qty,
                leverage=leverage,
                order_type="Market",
                take_profit=target_price,
                stop_loss=stop_loss
            )
            order_type_str = "시장가 즉시진입"
        else:
            result = place_order(
                symbol=symbol,
                side="Buy",
                qty=qty,
                leverage=leverage,
                order_type="Limit",
                price=entry_price,
                take_profit=target_price,
                stop_loss=stop_loss
            )
            order_type_str = f"지정가 눌림 {entry_price}"

        if result and result.get("retCode") == 0:
            return True, order_type_str, entry_price, target_price, stop_loss, leverage, qty
        else:
            return False, str(result), 0, 0, 0, 0, 0
    except Exception as e:
        print(f"자동매매 실행 실패: {e}")
        return False, str(e), 0, 0, 0, 0, 0

# ===== Google Sheets =====
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

# ===== Telegram =====
def send_telegram(msg, chat_id=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": chat_id or CHAT_ID, "text": msg, "parse_mode": "HTML"})

# ===== 분석 함수들 =====
def is_info_message(text):
    return any(kw in text for kw in INFO_KEYWORDS)

def is_gaedwaeji_message(text):
    return any(kw in text for kw in GAEDWAEJI_KEYWORDS)

def analyze_image(image_bytes, caption=""):
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY, timeout=30.0)
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
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY, timeout=30.0)
    price_info = f"현재가: ${current_price}" if current_price else "현재가: 조회 실패"
    result = client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=400,
        messages=[{"role":"user","content":f"종목: {ticker}\n{price_info}\n코멘트: {comment}\n\n현재가 기준으로 아래 형식으로만 답해:\n판단: 지금진입가능 또는 눌림대기 또는 진입금지\n진입가:\n손절가:\n1차타깃:\n2차타깃:\n손익비:\n핵심: 한줄요약\n주의: 한줄주의사항"}])
    return result.content[0].text

def analyze_info(text):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY, timeout=30.0)
    result = client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=500,
        messages=[{"role":"user","content":f"당신은 전문 암호화폐 트레이더입니다.\n메시지:\n{text}\n\n아래 형식으로만 답해:\n코인:\n상황: 한줄요약\n판단: 상승우세 또는 하락우세 또는 중립관망\n대응: 지금진입 또는 손절필요 또는 관망대기\n핵심근거: 기술적 근거 한줄\n주의사항: 한줄"}])
    return result.content[0].text

def analyze_gaedwaeji(text):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY, timeout=30.0)
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
    send_telegram("✅ 모니터링 시작! 멍꼴단+캔들의신 감시 중... 자동매매 활성화")

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
            send_telegram(f"🔍 {ticker} 분석 중...")
            current_price = get_current_price(ticker)
            candles = get_candles(ticker)
            result = analyze_stock(ticker, text, current_price)
            send_telegram(format_stock_msg(ticker, result, current_price))
            save_to_sheets("급등주", [now, ticker, str(current_price), result])

            # 자동매매 실행
            if current_price:
                send_telegram(f"🤖 {ticker} 자동매매 분석 중...")
                trade_analysis = analyze_for_trading(ticker, text, current_price, candles)
                if trade_analysis:
                    success, order_type, entry, target, sl, lev, qty = execute_auto_trade(ticker, trade_analysis, current_price)
                    if success:
                        msg = f"✅ <b>자동매매 체결</b>\n\n"
                        msg += f"🪙 {ticker}\n"
                        msg += f"📋 {order_type}\n"
                        msg += f"💰 진입가: {entry}\n"
                        msg += f"🎯 목표가: {target}\n"
                        msg += f"🛑 손절가: {sl}\n"
                        msg += f"⚡ 레버리지: {lev}배\n"
                        msg += f"📦 수량: {qty}\n"
                        send_telegram(msg)
                        save_to_sheets("자동매매", [now, ticker, str(entry), str(target), str(sl), str(lev), str(qty)])
                    else:
                        send_telegram(f"❌ 자동매매 실패: {order_type}")

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

    @client.on(events.NewMessage(pattern='/매매현황'))
    async def trade_status_handler(event):
        rows = get_recent_records("자동매매", 5)
        if not rows:
            await event.respond("📭 자동매매 내역 없음")
            return
        msg = "📊 <b>최근 자동매매 내역</b>\n\n"
        for row in rows:
            if row:
                msg += f"📅 {row[0]} | {row[1]}\n진입:{row[2]} 목표:{row[3]} 손절:{row[4]}\n레버:{row[5]}배\n\n"
        send_telegram(msg, event.chat_id)

    await client.run_until_disconnected()

try:
    asyncio.run(main())
except Exception as e:
    print(f"에러 발생: {e}")
    import traceback
    traceback.print_exc()
