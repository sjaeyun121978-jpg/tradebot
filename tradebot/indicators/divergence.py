def _pivot_lows(rows, n=5):
    out = []
    for i in range(2, len(rows)-2):
        low = float(rows[i].get("low", 0))
        if low <= float(rows[i-1].get("low", 0)) and low <= float(rows[i+1].get("low", 0)):
            out.append((i, low))
    return out[-n:]

def _pivot_highs(rows, n=5):
    out = []
    for i in range(2, len(rows)-2):
        high = float(rows[i].get("high", 0))
        if high >= float(rows[i-1].get("high", 0)) and high >= float(rows[i+1].get("high", 0)):
            out.append((i, high))
    return out[-n:]

def detect_divergence(candles, rsi_value=50.0, cci_value=0.0):
    rows = candles or []
    if len(rows) < 30:
        return {"divergence": "NONE", "rsi_divergence": "NONE", "cci_divergence": "NONE"}
    lows = _pivot_lows(rows)
    highs = _pivot_highs(rows)
    # 단순형: 최근 가격 저점 갱신 + RSI/CCI 회복 구간이면 상승 다이버전스 후보
    if len(lows) >= 2 and lows[-1][1] < lows[-2][1] and (rsi_value > 35 or cci_value > -100):
        return {"divergence": "BULLISH_DIV", "rsi_divergence": "BULLISH_DIV", "cci_divergence": "BULLISH_DIV" if cci_value > -100 else "NONE"}
    if len(highs) >= 2 and highs[-1][1] > highs[-2][1] and (rsi_value < 65 or cci_value < 100):
        return {"divergence": "BEARISH_DIV", "rsi_divergence": "BEARISH_DIV", "cci_divergence": "BEARISH_DIV" if cci_value < 100 else "NONE"}
    return {"divergence": "NONE", "rsi_divergence": "NONE", "cci_divergence": "NONE"}
