def calculate_fibo_zone(candles, lookback=80):
    rows = (candles or [])[-lookback:]
    if len(rows) < 10:
        return {"fibo_level": 0.0, "fibo_zone": "NONE", "swing_high": 0.0, "swing_low": 0.0}
    high = max(float(c.get("high", 0)) for c in rows)
    low = min(float(c.get("low", 0)) for c in rows)
    close = float(rows[-1].get("close", 0))
    rng = high - low
    if rng <= 0:
        level = 0.0
    else:
        level = (high - close) / rng
    nearest = min([0.382, 0.5, 0.618, 0.786], key=lambda x: abs(x - level))
    return {"fibo_level": round(level, 3), "fibo_zone": str(nearest), "swing_high": high, "swing_low": low}
