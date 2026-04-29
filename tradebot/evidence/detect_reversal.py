from tradebot.step.utils import num, text

def detect_reversal(data: dict) -> dict:
    reasons = []
    long = short = 0.0
    div = text(data, "divergence", "rsi_divergence", default="").upper()
    cci_div = text(data, "cci_divergence", default="").upper()
    rsi = num(data, "rsi", default=50)
    cci = num(data, "cci", default=0)
    if div == "BULLISH_DIV" or cci_div == "BULLISH_DIV": long += 30; reasons.append("상승 다이버전스")
    if div == "BEARISH_DIV" or cci_div == "BEARISH_DIV": short += 30; reasons.append("하락 다이버전스")
    if 30 <= rsi <= 45 and cci > -120: long += 10
    if 55 <= rsi <= 70 and cci < 120: short += 10
    direction = "LONG" if long > short else ("SHORT" if short > long else "NEUTRAL")
    return {"score": max(long, short), "long_score": long, "short_score": short, "direction": direction, "reasons": reasons, "warnings": [], "raw": {}}
