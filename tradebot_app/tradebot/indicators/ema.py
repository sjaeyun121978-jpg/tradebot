def ema_values(values, period):
    values = [float(v) for v in values or []]
    if not values:
        return []
    k = 2 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out

def calculate_ema(candles, period):
    closes = [float(c.get("close", 0)) for c in candles or []]
    vals = ema_values(closes, period)
    return round(vals[-1], 4) if vals else 0.0
