from tradebot.step.utils import num, text, candle_ratios, vol_ratio, boolv

def detect_trap(data: dict, direction: str = "NEUTRAL") -> dict:
    score, reasons = 0.0, []
    rsi = num(data, "rsi", default=50)
    cci = num(data, "cci", default=0)
    vr = vol_ratio(data)
    cr = candle_ratios(data)
    if vr < 0.7 and text(data, "trend_15m").upper() in ("UP", "DOWN"):
        score += 20; reasons.append("거래량 없는 이동")
    if boolv(data, "is_range") and text(data, "range_pos").upper() == "MIDDLE":
        score += 10; reasons.append("박스 중앙 노이즈")
    if direction == "LONG":
        if rsi > 72 or cci > 150: score += 15; reasons.append("롱 과열 추격")
        if cr["upper_wick"] > 0.35: score += 15; reasons.append("윗꼬리 위험")
        if text(data, "divergence", "rsi_divergence", default="").upper() == "BEARISH_DIV": score += 20; reasons.append("하락 다이버전스")
    elif direction == "SHORT":
        if rsi < 28 or cci < -150: score += 15; reasons.append("숏 과매도 추격")
        if cr["lower_wick"] > 0.35: score += 15; reasons.append("아래꼬리 위험")
        if text(data, "divergence", "rsi_divergence", default="").upper() == "BULLISH_DIV": score += 20; reasons.append("상승 다이버전스")
    return {"score": min(score,100), "direction": direction, "reasons": reasons, "warnings": reasons[:], "raw": {}}
