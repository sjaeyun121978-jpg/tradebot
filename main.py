import asyncio
import re
import requests
import anthropic
from telethon import TelegramClient, events

API_ID = 29053680
API_HASH = "3a70519636127aafe34f7cb61e8bea1c"
BOT_TOKEN = "8664715398:AAH79xEFTw3P0oMRWUXVUVXkPVWvkQsu69k"
CHAT_ID = "5393720278"
ANTHROPIC_KEY = "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"

CHANNEL_IDS = [-1003332441222, -1002931696159]

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"})

def analyze(ticker, comment):
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

def format_msg(ticker, result):
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

async def main():
    client = TelegramClient('session', API_ID, API_HASH)
    await client.start()
    send_telegram("✅ 모니터링 시작! 멍꼴단 감시 중...")

    @client.on(events.NewMessage(chats=CHANNEL_IDS))
    async def handler(event):
        text = event.message.text
        if not text:
            return
        match = re.search(r'#([A-Z]{2,10})', text)
        if match:
            ticker = match.group(1)
            send_telegram(f"🔍 {ticker} 분석 중...")
            result = analyze(ticker, text)
            send_telegram(format_msg(ticker, result))

    await client.run_until_disconnected()

asyncio.run(main())
