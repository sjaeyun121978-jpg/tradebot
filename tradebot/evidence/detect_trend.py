from tradebot.step.utils import num, text, candle_ratios

def detect_trend(data: dict) -> dict:
    reasons, warnings = [], []
    long = short = 0.0
    price = num(data, "current_price", "price", "close")
    ema20 = num(data, "ema20")
    ema50 = num(data, "ema50")
    trend15 = text(data, "trend_15m", default="SIDEWAYS").upper()
    trend1h = text(data, "trend_1h", default="SIDEWAYS").upper()
    cr = candle_ratios(data)
    if trend15 == "UP": long += 20; reasons.append("15M 상승 추세")
    if trend15 == "DOWN": short += 20; reasons.append("15M 하락 추세")
    if trend1h == "UP": long += 10
    if trend1h == "DOWN": short += 10
    if ema20 and price > ema20: long += 10; reasons.append("EMA20 상단")
    if ema20 and price < ema20: short += 10; reasons.append("EMA20 하단")
    if ema50 and price > ema50: long += 5
    if ema50 and price < ema50: short += 5
    if cr["close"] < cr["open"] and cr["body"] > 0.45: short += 10; reasons.append("강한 음봉")
    if cr["close"] > cr["open"] and cr["body"] > 0.45: long += 10; reasons.append("강한 양봉")
    direction = "LONG" if long > short + 5 else ("SHORT" if short > long + 5 else "NEUTRAL")
    return {"score": max(long, short), "long_score": long, "short_score": short, "direction": direction, "reasons": reasons, "warnings": warnings, "raw": {}}
