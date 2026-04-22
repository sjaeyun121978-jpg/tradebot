import asyncio
import re
import os
import requests
import anthropic
from telethon import TelegramClient, events
from telethon.sessions import StringSession

API_ID = 29053680
API_HASH = "3a70519636127aafe34f7cb61e8bea1c"
BOT_TOKEN = "8664715398:AAH79xEFTw3P0oMRWUXVUVXkPVWvkQsu69k"
CHAT_ID = "5393720278"
ANTHROPIC_KEY = "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"
SESSION_STRING = os.environ.get("SESSION_STRING")

CHANNEL_IDS = [-1003332441222, -1002931696159]

# 정보성 메시지 감지 키워드
INFO_KEYWORDS = [
    "오더북", "매물대", "히트맵", "체결", "위험",
    "유효하지 않음", "지지", "저항", "돌파", "이탈",
    "롱", "숏", "청산", "펀딩", "미결제약정",
    "파동", "엘리엇", "추세", "채널", "다이버전스"
]

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "HTML"
    })

def is_info_message(text):
    """정보성 메시지 여부 판단"""
    return any(kw in text for kw in INFO_KEYWORDS)

def analyze_stock(ticker, comment):
    """급등주 분석 - 기존 로직"""
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
    """정보성 메시지 기술적 분석"""
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    result = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{"role": "user", "content": f"""
당신은 전문 암호화폐 트레이더입니다.
아래 정보성 메시지를 분석하여 판단하세요.

분석 기준:
- 엘리엇 파동 이론
- 지지/저항 레벨
- 오더북 매물대 변화
- 캔들 패턴
- 추세 방향
- 과거 유사 패턴

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

def format_stock_msg(ticker, result):
    """급등주 알림 포맷 - 기존"""
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
        elif "주의:" in line:
            msg += f"⚠️ {line.split(':')[1].strip()}\n"
    return msg

def format_info_msg(result):
    """정보성 분석 알림 포맷"""
    lines = result.strip().split('\n')
    판단아이콘 = "🟢" if "상승우세" in result else "🔴" if "하락우세" in result else "🟡"
    대응아이콘 = "⚡" if "지금진입" in result else "🚨" if "손절필요" in result else "👀"

    msg = f"📊 <b>시장 정보 분석</b>\n\n"
    for line in lines:
        if not line.strip():
            continue
        if "코인:" in line:
            msg += f"🪙 {line.split(':')[1].strip()}\n"
        elif "상황:" in line:
            msg += f"📌 {line.split(':')[1].strip()}\n\n"
        elif "판단:" in line:
            msg += f"{판단아이콘} 판단: {line.split(':')[1].strip()}\n"
        elif "대응:" in line:
            msg += f"{대응아이콘} 대응: {line.split(':')[1].strip()}\n\n"
        elif "핵심근거:" in line:
            msg += f"🔍 근거: {line.split(':')[1].strip()}\n"
        elif "주의사항:" in line:
            msg += f"⚠️ 주의: {line.split(':')[1].strip()}\n"
    return msg

async def main():
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    send_telegram("✅ 모니터링 시작! 멍꼴단 감시 중...")

    @client.on(events.NewMessage(chats=CHANNEL_IDS))
    async def handler(event):
        text = event.message.text
        if not text:
            return

        # 분기 1: 정보성 메시지 (오더북/매물대 등)
        if is_info_message(text):
            send_telegram("🔍 시장 정보 분석 중...")
            result = analyze_info(text)
            send_telegram(format_info_msg(result))
            return

        # 분기 2: 급등주 해시태그 메시지
        match = re.search(r'#([A-Za-z가-힣]{2,15})', text)
        if match:
            ticker = match.group(1)
            send_telegram(f"🔍 {ticker} 분석 중...")
            result = analyze_stock(ticker, text)
            send_telegram(format_stock_msg(ticker, result))

    await client.run_until_disconnected()

asyncio.run(main())
