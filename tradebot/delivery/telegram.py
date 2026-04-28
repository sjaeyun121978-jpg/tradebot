import json
import time
import requests
from tradebot.config.settings import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_MIN_INTERVAL_SEC

_last_telegram_sent_at = 0.0


def _wait_rate_limit():
    global _last_telegram_sent_at
    elapsed = time.time() - _last_telegram_sent_at
    if elapsed < TELEGRAM_MIN_INTERVAL_SEC:
        time.sleep(TELEGRAM_MIN_INTERVAL_SEC - elapsed)


def _escape_html(text: str) -> str:
    """HTML 특수문자 이스케이프 (parse_mode=HTML 사용 시)"""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


def send_message(text: str, chat_id: str = None, parse_mode: str = "HTML") -> bool:
    global _last_telegram_sent_at
    chat_id = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_TOKEN or not chat_id:
        print("[WARN] TELEGRAM_TOKEN/TG_BOT_TOKEN 또는 TELEGRAM_CHAT_ID/TG_CHAT_ID 없음", flush=True)
        print(text, flush=True)
        return False
    _wait_rate_limit()
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        r = requests.post(url, data=payload, timeout=10)
        _last_telegram_sent_at = time.time()
        if r.status_code != 200:
            # HTML 파싱 오류 시 plain text로 재시도
            if parse_mode == "HTML" and "parse_mode" in str(r.text):
                payload.pop("parse_mode", None)
                r2 = requests.post(url, data=payload, timeout=10)
                if r2.status_code == 200:
                    return True
            print(f"[TELEGRAM ERROR] {r.status_code} {r.text}", flush=True)
            return False
        return True
    except Exception as e:
        print(f"[TELEGRAM SEND ERROR] {e}", flush=True)
        return False


def send_photo(
    image_bytes: bytes,
    caption: str = "",
    chat_id: str = None,
    parse_mode: str = None,   # STEP 카드는 None (plain text 기본)
) -> bool:
    """
    STEP 카드 이미지 전송.
    parse_mode 기본값 None — HTML 파싱 오류 방지.
    caption은 plain text로만 사용 권장.
    """
    global _last_telegram_sent_at
    chat_id = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_TOKEN or not chat_id:
        print("[WARN] 토큰/채팅ID 없음 — 이미지 전송 불가", flush=True)
        return False
    _wait_rate_limit()
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    payload: dict = {"chat_id": chat_id}
    if caption:
        # caption을 plain text로 안전하게 전달
        plain = str(caption)
        payload["caption"] = plain
    if parse_mode:
        payload["parse_mode"] = parse_mode
    files = {"photo": ("card.png", image_bytes, "image/png")}
    try:
        r = requests.post(url, data=payload, files=files, timeout=20)
        _last_telegram_sent_at = time.time()
        if r.status_code != 200:
            print(f"[PHOTO ERROR] {r.status_code} {r.text}", flush=True)
            return False
        return True
    except Exception as e:
        print(f"[PHOTO SEND ERROR] {e}", flush=True)
        return False


def send_album(image_bytes_list: list, caption: str = "", chat_id: str = None) -> bool:
    """Send Telegram media group. caption은 plain text로 전달."""
    global _last_telegram_sent_at
    chat_id = chat_id or TELEGRAM_CHAT_ID
    if not image_bytes_list:
        return False
    if len(image_bytes_list) == 1:
        return send_photo(image_bytes_list[0], caption=caption, chat_id=chat_id)
    if not TELEGRAM_TOKEN or not chat_id:
        print("[WARN] 토큰/채팅ID 없음 — 앨범 전송 불가", flush=True)
        return False
    _wait_rate_limit()
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMediaGroup"
    media = []
    files = {}
    plain_caption = str(caption) if caption else ""
    for i, img in enumerate(image_bytes_list):
        key = f"photo{i}"
        item: dict = {"type": "photo", "media": f"attach://{key}"}
        if i == 0 and plain_caption:
            item["caption"] = plain_caption
            # parse_mode 제거 — plain text
        media.append(item)
        files[key] = (f"card{i}.png", img, "image/png")
    payload = {"chat_id": chat_id, "media": json.dumps(media, ensure_ascii=False)}
    try:
        r = requests.post(url, data=payload, files=files, timeout=30)
        _last_telegram_sent_at = time.time()
        if r.status_code != 200:
            print(f"[ALBUM ERROR] {r.status_code} {r.text}", flush=True)
            return False
        return True
    except Exception as e:
        print(f"[ALBUM SEND ERROR] {e}", flush=True)
        return False


# legacy aliases
send_telegram_message = send_message
send_telegram_photo   = send_photo
send_telegram_album   = send_album
