from tradebot.indicators.ema import ema_values

def calculate_macd(candles, fast=12, slow=26, signal=9):
    closes = [float(c.get("close", 0)) for c in candles or []]
    if len(closes) < slow + signal:
        return {"macd": 0.0, "signal": 0.0, "hist": 0.0, "state": "NEUTRAL"}
    ef = ema_values(closes, fast)
    es = ema_values(closes, slow)
    n = min(len(ef), len(es))
    macd_line = [ef[-n+i] - es[-n+i] for i in range(n)]
    sig = ema_values(macd_line, signal)
    hist = macd_line[-1] - sig[-1] if sig else 0.0
    state = "BULLISH" if hist > 0 else ("BEARISH" if hist < 0 else "NEUTRAL")
    return {"macd": round(macd_line[-1], 5), "signal": round(sig[-1], 5), "hist": round(hist, 5), "state": state}
