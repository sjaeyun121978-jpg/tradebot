import uuid
from datetime import datetime

from sheets import save_to_sheets


SHEET_NAME = "신호기록"


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def generate_id(symbol, signal, level):
    return f"{symbol}_{signal}_{level}_{str(uuid.uuid4())[:8]}"


def record_signal(
    symbol,
    signal,
    level=None,
    entry_level=None,
    price=None,
    score=None,
    stop_loss=None,
    tp1=None,
    tp2=None,
    detail="",
    raw_message=""
):
    final_level = level if level is not None else entry_level
    signal_id = generate_id(symbol, signal, final_level)

    row = [
        signal_id,
        now_str(),
        symbol,
        signal,
        final_level,
        price,
        score,
        stop_loss,
        tp1,
        tp2,
        detail,
        raw_message,
        "WAIT",
        "",
        "",
        "",
        "",
    ]

    save_to_sheets(SHEET_NAME, row)

    return signal_id
