import uuid
from datetime import datetime

from sheets import save_to_sheets


SIGNAL_SHEET_NAME = "신호기록"


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create_signal_id(symbol, signal, entry_level):
    short_uuid = str(uuid.uuid4())[:8]
    return f"{symbol}_{signal}_{entry_level}_{short_uuid}"


def record_signal(
    symbol,
    signal,
    entry_level,
    price,
    score,
    stop_loss,
    tp1,
    tp2,
    detail,
    raw_message
):
    """
    알림 발생 시 Google Sheets에 자동 기록
    """

    signal_id = create_signal_id(symbol, signal, entry_level)

    row = [
        signal_id,
        now_str(),
        symbol,
        signal,
        entry_level,
        price,
        score,
        stop_loss,
        tp1,
        tp2,
        detail,
        raw_message,
        "대기",
        "",
        "",
        "",
        "",
    ]

    save_to_sheets(SIGNAL_SHEET_NAME, row)

    return signal_id
