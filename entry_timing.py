from indicators import calculate_indicators

def check_entry_timing(symbol, price, candles_15m, candles_1h, candles_4h):
    """
    실전 진입 타점 판단 (가짜 타점 제거 포함)
    """

    ind_15m = calculate_indicators(candles_15m)
    ind_1h = calculate_indicators(candles_1h)
    ind_4h = calculate_indicators(candles_4h)

    rsi_15 = ind_15m.get("rsi", 50)
    rsi_1h = ind_1h.get("rsi", 50)
    rsi_4h = ind_4h.get("rsi", 50)

    cci_15 = ind_15m.get("cci", 0)
    cci_1h = ind_1h.get("cci", 0)

    volume_ratio = ind_15m.get("volume_ratio", 0)

    ema20 = ind_15m.get("ema20", price)
    ema50 = ind_15m.get("ema50", price)

    divergence = ind_15m.get("divergence", None)

    # =========================
    # ❌ 1. 거래량 필터 (필수)
    # =========================
    if volume_ratio < 1.2:
        return None

    # =========================
    # ❌ 2. EMA 애매구간 차단
    # =========================
    if ema20 < price < ema50 or ema50 < price < ema20:
        return None

    # =========================
    # ❌ 3. 4H 방향 필터 (핵심)
    # =========================
    # 4H 하락 강하면 롱 금지
    if rsi_4h < 45:
        long_block = True
    else:
        long_block = False

    # 4H 상승 강하면 숏 금지
    if rsi_4h > 55:
        short_block = True
    else:
        short_block = False

    # =========================
    # ❌ 4. 다이버전스 충돌 필터
    # =========================
    # 상승 다이버인데 숏 → 차단
    if divergence == "bullish":
        short_block = True

    # 하락 다이버인데 롱 → 차단
    if divergence == "bearish":
        long_block = True

    # =========================
    # 🟢 롱 타점
    # =========================
    if (
        not long_block
        and price > ema20
        and rsi_15 >= 50
        and rsi_1h >= 50
        and cci_15 > 0
        and cci_1h > 0
    ):
        return {
            "signal": "LONG",
            "reason": "EMA20 상방 + RSI 상승 + CCI 양수 + 거래량 OK"
        }

    # =========================
    # 🔴 숏 타점
    # =========================
    if (
        not short_block
        and price < ema20
        and rsi_15 <= 45
        and rsi_1h <= 50
        and cci_15 < 0
        and cci_1h < 0
    ):
        return {
            "signal": "SHORT",
            "reason": "EMA20 하방 + RSI 하락 + CCI 음수 + 거래량 OK"
        }

    return None
