from __future__ import annotations
from tradebot.data.bybit_client import collect_candles, get_current_price, collect_market_data
from tradebot.indicators import run_indicators

def _trend(candles, ema20, ema50):
    if not candles:
        return "SIDEWAYS"
    close = float(candles[-1].get("close", 0))
    if ema20 and ema50:
        if close > ema20 > ema50:
            return "UP"
        if close < ema20 < ema50:
            return "DOWN"
    # fallback: 최근 8봉 기울기
    if len(candles) >= 8:
        prev = float(candles[-8].get("close", close))
        diff = (close - prev) / prev if prev else 0
        if diff > 0.003:
            return "UP"
        if diff < -0.003:
            return "DOWN"
    return "SIDEWAYS"

def _range_pos(candles, price):
    rows = (candles or [])[-80:]
    if not rows or not price:
        return False, ""
    high = max(float(c.get("high", 0)) for c in rows)
    low = min(float(c.get("low", 0)) for c in rows)
    rng = high - low
    if rng <= 0:
        return False, ""
    p = (price - low) / rng
    if p <= 0.33:
        return True, "BOTTOM"
    if p >= 0.67:
        return True, "TOP"
    return True, "MIDDLE"

def _avg_volume(candles, n=30):
    rows = (candles or [])[-n:]
    if not rows:
        return 0.0
    return sum(float(c.get("volume", 0)) for c in rows) / len(rows)

def get_market_data(symbol: str) -> dict:
    candles = collect_candles(symbol)
    price = get_current_price(symbol)
    indicators = run_indicators(candles)
    market_extra = collect_market_data(symbol) or {}
    c15 = candles.get("15m") or []
    c1h = candles.get("1h") or []
    c4h = candles.get("4h") or []
    last = c15[-1] if c15 else {}
    rows = c1h[-80:] if c1h else c15[-80:]
    support = min(float(c.get("low", price)) for c in rows) if rows else 0.0
    resistance = max(float(c.get("high", price)) for c in rows) if rows else 0.0
    is_range, range_pos = _range_pos(rows, price)
    data = {
        "symbol": symbol,
        "current_price": price,
        "price": price,
        "open_15m": float(last.get("open", price) or price),
        "high_15m": float(last.get("high", price) or price),
        "low_15m": float(last.get("low", price) or price),
        "close_15m": float(last.get("close", price) or price),
        "open": float(last.get("open", price) or price),
        "high": float(last.get("high", price) or price),
        "low": float(last.get("low", price) or price),
        "close": float(last.get("close", price) or price),
        "volume": float(last.get("volume", 0) or 0),
        "avg_volume": _avg_volume(c15),
        "support": support,
        "resistance": resistance,
        "is_range": is_range,
        "range_pos": range_pos,
        "trend_15m": _trend(c15, indicators.get("ema20"), indicators.get("ema50")),
        "trend_1h": _trend(c1h, 0, 0),
        "trend_4h": _trend(c4h, 0, 0),
        "candles_by_tf": candles,
        **indicators,
        **market_extra,
    }
    avg = data.get("avg_volume") or 0
    data["volume_ratio"] = data["volume"] / avg if avg > 0 else 0.0
    data["above_ema20"] = bool(data["ema20"] and price > data["ema20"])
    data["below_ema20"] = bool(data["ema20"] and price < data["ema20"])
    return data
