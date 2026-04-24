def judge_entry_timing(symbol, price, indicators):
    """
    트리거 v3
    구조 + 파동 + RSI 다이버전스 + CCI 다이버전스 + 지표 기반 타점 판단
    자동진입 아님. 텔레그램 알림용.
    """

    if not price or not indicators:
        return None

    rsi = indicators.get("rsi")
    rsi_div = indicators.get("rsi_divergence")
    cci = indicators.get("cci")
    cci_div = indicators.get("cci_divergence")
    vol = indicators.get("vol_ratio")
    ema20 = indicators.get("ema20")
    ema50 = indicators.get("ema50")
    structure = indicators.get("structure", {})

    if None in [rsi, cci, vol, ema20, ema50]:
        return None

    if symbol == "ETH":
        support_break = 2295
        resistance_break = 2315
        upper_invalid = 2320
        lower_invalid = 2290

    elif symbol == "BTC":
        support_break = 77000
        resistance_break = 78500
        upper_invalid = 78800
        lower_invalid = 76800

    else:
        return None

    # =========================
    # 구조 데이터 추출
    # =========================
    tf_15m = structure.get("15M", {})
    tf_1h = structure.get("1H", {})
    tf_4h = structure.get("4H", {})

    s15 = tf_15m.get("structure", "")
    s1h = tf_1h.get("structure", "")
    s4h = tf_4h.get("structure", "")

    w15 = tf_15m.get("wave", "")
    w1h = tf_1h.get("wave", "")
    w4h = tf_4h.get("wave", "")

    # =========================
    # 공통 필터
    # =========================
    volume_ok = vol >= 1.2
    strong_volume = vol >= 1.5

    bullish_div = (
        rsi_div == "상승 다이버전스"
        or cci_div == "상승 다이버전스"
    )

    bearish_div = (
        rsi_div == "하락 다이버전스"
        or cci_div == "하락 다이버전스"
    )

    strong_bullish_div = (
        rsi_div == "상승 다이버전스"
        and cci_div == "상승 다이버전스"
    )

    strong_bearish_div = (
        rsi_div == "하락 다이버전스"
        and cci_div == "하락 다이버전스"
    )

    lower_tf_bearish = (
        "LH/LL" in s15
        or "하락" in s15
        or "하락" in w15
    )

    lower_tf_bullish = (
        "HH/HL" in s15
        or "상승" in s15
        or "상승" in w15
    )

    mid_tf_bearish = (
        "LH/LL" in s1h
        or "하락" in s1h
        or "하락" in w1h
    )

    mid_tf_bullish = (
        "HH/HL" in s1h
        or "상승" in s1h
        or "상승" in w1h
    )

    high_tf_bearish = (
        "LH/LL" in s4h
        or "하락" in s4h
        or "하락" in w4h
    )

    high_tf_bullish = (
        "HH/HL" in s4h
        or "상승" in s4h
        or "상승" in w4h
    )

    # =========================
    # 충돌 필터
    # =========================
    if bullish_div and bearish_div:
        return None

    # =========================
    # 🔴 숏 타점 1
    # 지지 이탈 + 하락 구조 + 거래량
    # =========================
    if (
        price < support_break
        and volume_ok
        and rsi <= 40
        and price < ema20
        and price < ema50
        and (lower_tf_bearish or mid_tf_bearish)
        and not strong_bullish_div
    ):
        return {
            "signal": "SHORT",
            "type": "지지 이탈 숏",
            "message": (
                f"🔴 {symbol} 숏 타점 발생\n"
                f"유형: 지지 이탈 숏\n"
                f"현재가: {price}\n"
                f"거래량비율: {vol}\n"
                f"RSI: {rsi}\n"
                f"CCI: {cci}\n"
                f"RSI 다이버전스: {rsi_div}\n"
                f"CCI 다이버전스: {cci_div}\n\n"
                f"판단: 지지 이탈 + 하락 구조 + EMA 하단\n"
                f"행동: 숏 진입 검토\n"
                f"무효화: {support_break} 위 재진입"
            )
        }

    # =========================
    # 🔴 숏 타점 2
    # 하락 다이버전스 + 저항 반등 실패
    # =========================
    if (
        strong_bearish_div
        and strong_volume
        and price < ema20
        and price < ema50
        and rsi < 55
        and (lower_tf_bearish or mid_tf_bearish or high_tf_bearish)
    ):
        return {
            "signal": "SHORT",
            "type": "하락 다이버전스 숏",
            "message": (
                f"🔴 {symbol} 숏 타점 발생\n"
                f"유형: 하락 다이버전스 숏\n"
                f"현재가: {price}\n"
                f"거래량비율: {vol}\n"
                f"RSI: {rsi}\n"
                f"CCI: {cci}\n"
                f"RSI 다이버전스: {rsi_div}\n"
                f"CCI 다이버전스: {cci_div}\n\n"
                f"판단: RSI/CCI 하락 다이버전스 + EMA 저항\n"
                f"행동: 숏 진입 검토\n"
                f"무효화: {upper_invalid} 위 안착"
            )
        }

    # =========================
    # 🟢 롱 타점 1
    # 저항 돌파 + 상승 구조 + 거래량
    # =========================
    if (
        price > resistance_break
        and volume_ok
        and rsi >= 50
        and price > ema20
        and price > ema50
        and (lower_tf_bullish or mid_tf_bullish)
        and not strong_bearish_div
    ):
        return {
            "signal": "LONG",
            "type": "저항 돌파 롱",
            "message": (
                f"🟢 {symbol} 롱 타점 발생\n"
                f"유형: 저항 돌파 롱\n"
                f"현재가: {price}\n"
                f"거래량비율: {vol}\n"
                f"RSI: {rsi}\n"
                f"CCI: {cci}\n"
                f"RSI 다이버전스: {rsi_div}\n"
                f"CCI 다이버전스: {cci_div}\n\n"
                f"판단: 저항 돌파 + 상승 구조 + EMA 상단\n"
                f"행동: 롱 진입 검토\n"
                f"무효화: {resistance_break} 아래 재이탈"
            )
        }

    # =========================
    # 🟢 롱 타점 2
    # 상승 다이버전스 + 지지 반등
    # =========================
    if (
        strong_bullish_div
        and strong_volume
        and price > ema20
        and rsi >= 45
        and (lower_tf_bullish or mid_tf_bullish or not high_tf_bearish)
    ):
        return {
            "signal": "LONG",
            "type": "상승 다이버전스 롱",
            "message": (
                f"🟢 {symbol} 롱 타점 발생\n"
                f"유형: 상승 다이버전스 롱\n"
                f"현재가: {price}\n"
                f"거래량비율: {vol}\n"
                f"RSI: {rsi}\n"
                f"CCI: {cci}\n"
                f"RSI 다이버전스: {rsi_div}\n"
                f"CCI 다이버전스: {cci_div}\n\n"
                f"판단: RSI/CCI 상승 다이버전스 + EMA20 회복\n"
                f"행동: 롱 진입 검토\n"
                f"무효화: {lower_invalid} 아래 이탈"
            )
        }

    return None
