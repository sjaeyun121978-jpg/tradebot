from tradebot.step.utils import num, text, boolv, candle_ratios, getv, vol_ratio

def detect_distribution(data: dict) -> dict:
    score, reasons = 0.0, []
    price = num(data, "current_price", "price", "close")
    resistance = num(data, "resistance")
    cr = candle_ratios(data)
    if boolv(data, "is_range") and text(data, "range_pos").upper() == "TOP": score += 20; reasons.append("박스 상단")
    if resistance and price and 0 < (resistance-price)/price < 0.015: score += 15; reasons.append("저항선 근접")
    if cr["upper_wick"] > 0.35: score += 20; reasons.append("윗꼬리 분산")
    vr = vol_ratio(data)
    if vr >= 1.1 and cr["close"] <= cr["open"] * 1.002: score += 20; reasons.append("거래량 증가 + 상승 제한")
    trades = getv(data, "trades", default={}) or {}
    if isinstance(trades, dict) and trades.get("cvd_signal") == "BEARISH": score += 15; reasons.append("CVD 매도 우세")
    return {"score": min(score,100), "direction": "SHORT", "reasons": reasons, "warnings": [], "raw": {}}
