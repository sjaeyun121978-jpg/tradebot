from tradebot.step.utils import num, text, boolv, candle_ratios, getv, vol_ratio

def detect_accumulation(data: dict) -> dict:
    score, reasons = 0.0, []
    price = num(data, "current_price", "price", "close")
    support = num(data, "support")
    cr = candle_ratios(data)
    if boolv(data, "is_range") and text(data, "range_pos").upper() == "BOTTOM": score += 20; reasons.append("박스 하단")
    if support and price and 0 < (price-support)/price < 0.015: score += 15; reasons.append("지지선 근접")
    if cr["lower_wick"] > 0.35: score += 20; reasons.append("아래꼬리 흡수")
    vr = vol_ratio(data)
    if vr >= 1.1 and cr["close"] >= cr["open"] * 0.998: score += 20; reasons.append("거래량 증가 + 가격 방어")
    trades = getv(data, "trades", default={}) or {}
    if isinstance(trades, dict) and trades.get("cvd_signal") == "BULLISH": score += 15; reasons.append("CVD 매수 우세")
    return {"score": min(score,100), "direction": "LONG", "reasons": reasons, "warnings": [], "raw": {}}
