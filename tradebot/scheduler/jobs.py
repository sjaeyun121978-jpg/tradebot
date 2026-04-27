from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

last_hourly_sent = None
last_radar_sent = None


def now_kst():
    return datetime.now(KST)


def run_scheduler(symbol, candles_by_tf):
    global last_hourly_sent, last_radar_sent

    now = now_kst()

    # 🕐 1H 브리핑 (정시 + 1분 유예)
    if now.minute <= 1:
        if last_hourly_sent != now.hour:
            run_hourly(symbol, candles_by_tf)
            last_hourly_sent = now.hour

    # 📡 진입레이더 (15분 기준)
    if now.minute % 15 == 0:
        key = f"{now.hour}:{now.minute}"
        if last_radar_sent != key:
            run_radar(symbol, candles_by_tf)
            last_radar_sent = key


def run_hourly(symbol, candles_by_tf):
    from tradebot.messages.hourly_payload import build_hourly_payload
    from tradebot.render.hourly_card import render_hourly_dashboard_card
    from tradebot.delivery.telegram import send_photo

    payload = build_hourly_payload(symbol, candles_by_tf)
    img = render_hourly_dashboard_card(payload)

    send_photo(img)


def run_radar(symbol, candles_by_tf):
    from tradebot.messages.radar_payload import build_radar_payload
    from tradebot.render.radar_card import render_radar_card
    from tradebot.delivery.telegram import send_photo

    payload = build_radar_payload(symbol, candles_by_tf)
    img = render_radar_card(payload)

    send_photo(img)
