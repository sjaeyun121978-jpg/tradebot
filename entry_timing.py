def judge_entry_timing(symbol, price, indicators):
    """
    실전 타점 판단 (최종)
    """

    if not price or not indicators:
        return None

    rsi = indicators.get("rsi")
    cci = indicators.get("cci")
    vol = indicators.get("volume_ratio")
    ema20 = indicators.get("ema20")
    ema50 = indicators.get("ema50")

    if None in [rsi, cci, vol, ema20, ema50]:
        return None

    # =========================
    # 거래량 필터
    # =========================
    if vol < 1.2:
        return None

    # =========================
    # EMA 애매 구간 차단
    # =========================
    if min(ema20, ema50) < price < max(ema20, ema50):
        return None

    # =========================
    # 롱 조건
    # =========================
    if (
        price > ema20
        and rsi >= 50
        and cci > 0
    ):
        return {
            "signal": "LONG",
            "type": "기본",
            "message": (
                f"🟢 {symbol} 롱 진입\n"
                f"현재가: {price}\n"
                f"RSI: {rsi}\n"
                f"CCI: {cci}\n"
                f"거래량: {vol}"
            )
        }

    # =========================
    # 숏 조건
    # =========================
    if (
        price < ema20
        and rsi <= 45
        and cci < 0
    ):
        return {
            "signal": "SHORT",
            "type": "기본",
            "message": (
                f"🔴 {symbol} 숏 진입\n"
                f"현재가: {price}\n"
                f"RSI: {rsi}\n"
                f"CCI: {cci}\n"
                f"거래량: {vol}"
            )
        }

    return None
