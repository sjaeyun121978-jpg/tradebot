# telegram_utils.py

import requests
from tradebot.config.settings import TELEGRAM_TOKEN as TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


# ─────────────────────────────────────────────
# 텍스트 전송 (기존 유지)
# ─────────────────────────────────────────────

def send_telegram_message(text: str, chat_id: str = None):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id or TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
        }
        response = requests.post(url, data=payload, timeout=10)
        if response.status_code != 200:
            print(f"[텔레그램 전송 실패] {response.text}")
    except Exception as e:
        print(f"[텔레그램 오류] {e}")


# ─────────────────────────────────────────────
# 이미지 1장 전송
# ─────────────────────────────────────────────

def send_telegram_photo(image_bytes: bytes, caption: str = "", chat_id: str = None):
    """
    PNG bytes를 텔레그램 사진으로 전송
    chart_renderer.render_radar_card() 반환값을 그대로 넣으면 됨
    """
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        payload = {
            "chat_id": chat_id or TELEGRAM_CHAT_ID,
            "caption": caption,
            "parse_mode": "HTML",
        }
        files = {"photo": ("card.png", image_bytes, "image/png")}
        response = requests.post(url, data=payload, files=files, timeout=20)
        if response.status_code != 200:
            print(f"[이미지 전송 실패] {response.text}")
    except Exception as e:
        print(f"[이미지 전송 오류] {e}")


# ─────────────────────────────────────────────
# 이미지 2장 앨범 전송 (ETH + BTC)
# ─────────────────────────────────────────────

def send_telegram_album(image_bytes_list: list, chat_id: str = None):
    """
    이미지 여러 장을 텔레그램 앨범(묶음)으로 전송
    image_bytes_list: [eth_png_bytes, btc_png_bytes]

    사용 예:
        eth_png = render_radar_card(eth_sig, eth_candles)
        btc_png = render_radar_card(btc_sig, btc_candles)
        send_telegram_album([eth_png, btc_png])
    """
    try:
        import json
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMediaGroup"

        media = []
        files = {}
        for i, img_bytes in enumerate(image_bytes_list):
            key = f"photo{i}"
            media.append({
                "type":  "photo",
                "media": f"attach://{key}",
            })
            files[key] = (f"card{i}.png", img_bytes, "image/png")

        payload = {
            "chat_id": chat_id or TELEGRAM_CHAT_ID,
            "media":   json.dumps(media),
        }
        response = requests.post(url, data=payload, files=files, timeout=30)
        if response.status_code != 200:
            print(f"[앨범 전송 실패] {response.text}")
    except Exception as e:
        print(f"[앨범 전송 오류] {e}")


# ─────────────────────────────────────────────
# 진입레이더 통합 전송 (메인에서 호출)
# ─────────────────────────────────────────────

def send_radar_cards(signals: list, candles_map: dict, chat_id: str = None):
    """
    진입레이더 카드 이미지 생성 후 앨범 전송

    signals:     [eth_sig, btc_sig]  ← structure_analyzer.analyze() 결과
    candles_map: {
        "ETHUSDT": {"15m": [...], "1h": [...], ...},
        "BTCUSDT": {"15m": [...], "1h": [...], ...},
    }

    사용 예 (main.py 또는 scheduler):
        from tradebot.delivery.telegram_legacy import send_radar_cards
        send_radar_cards(
            signals=[eth_result, btc_result],
            candles_map={
                "ETHUSDT": eth_candles,
                "BTCUSDT": btc_candles,
            }
        )
    """
    try:
        from chart_renderer import render_radar_card

        images = []
        for sig in signals:
            symbol  = sig.get("symbol", "")
            candles = candles_map.get(symbol, {}).get("15m", [])
            png     = render_radar_card(sig, candles)
            images.append(png)

        if len(images) == 1:
            send_telegram_photo(images[0], chat_id=chat_id)
        elif len(images) >= 2:
            send_telegram_album(images, chat_id=chat_id)

    except Exception as e:
        print(f"[레이더 카드 전송 오류] {e}")
