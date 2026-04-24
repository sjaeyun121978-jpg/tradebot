
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def send_telegram_message(text: str, chat_id: str = None):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id or TELEGRAM_CHAT_ID,
            "text": text
        }

        response = requests.post(url, data=payload, timeout=10)

        if response.status_code != 200:
            print(f"[텔레그램 전송 실패] {response.text}")

    except Exception as e:
        print(f"[텔레그램 오류] {e}")
