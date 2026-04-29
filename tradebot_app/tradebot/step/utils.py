from __future__ import annotations

def getv(data: dict, *keys, default=None):
    if not isinstance(data, dict):
        return default
    for key in keys:
        if key in data and data.get(key) is not None:
            return data.get(key)
    return default

def num(data: dict, *keys, default=0.0) -> float:
    value = getv(data, *keys, default=default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)

def text(data: dict, *keys, default="") -> str:
    value = getv(data, *keys, default=default)
    return str(value) if value is not None else str(default)

def boolv(data: dict, *keys, default=False) -> bool:
    value = getv(data, *keys, default=default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "y", "on")
    return default

def clamp(value: float, low=0.0, high=100.0) -> float:
    return max(low, min(float(value), high))

def vol_ratio(data: dict) -> float:
    volume = num(data, "volume", default=0.0)
    avg_volume = num(data, "avg_volume", default=0.0)
    if avg_volume > 0:
        return volume / avg_volume
    return num(data, "volume_ratio", "vol_ratio", "volume_ma_ratio", "vol_ma_ratio", default=0.0)

def candle_ratios(data: dict) -> dict:
    price = num(data, "current_price", "price", "close", default=0.0)
    o = num(data, "open_15m", "open", default=price)
    h = num(data, "high_15m", "high", default=price)
    l = num(data, "low_15m", "low", default=price)
    c = num(data, "close_15m", "close", default=price)
    rng = h - l if h > l else 0.0001
    body = abs(c - o) / rng
    lower = (min(o, c) - l) / rng
    upper = (h - max(o, c)) / rng
    return {"open": o, "high": h, "low": l, "close": c, "body": body, "lower_wick": lower, "upper_wick": upper}
