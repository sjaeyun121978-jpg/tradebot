def calculate_cci(candles, period=20):
    rows = candles or []
    if len(rows) < period:
        return 0.0
    tps = []
    for c in rows:
        tps.append((float(c.get("high", 0)) + float(c.get("low", 0)) + float(c.get("close", 0))) / 3)
    recent = tps[-period:]
    ma = sum(recent) / period
    md = sum(abs(x - ma) for x in recent) / period
    if md == 0:
        return 0.0
    return round((recent[-1] - ma) / (0.015 * md), 2)
