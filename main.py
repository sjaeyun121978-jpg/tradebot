def judge_entry_timing(symbol, price, indicators):
    """
    조건 트리거 이후 실제 진입 타점 판단용
    자동진입 아님
    텔레그램 알림 판단용
    """

    if not price or not indicators:
        return None

    rsi = indicators.get("rsi")
    vol = indicators.get("vol_ratio")
    ema20 = indicators.get("ema20")
    ema50 = indicators.get("ema50")

    if rsi is None or vol is None or ema20 is None or ema50 is None:
        return None

    # =========================
    # ETH 기준 주요 구간
    # =========================
    if symbol == "ETH":
        support_break = 2295
        resistance_break = 2315
        upper_invalid = 2320
        lower_invalid = 2290

    # =========================
    # BTC 기준 주요 구간
    # =========================
    elif symbol == "BTC":
        support_break = 77000
        resistance_break = 78500
        upper_invalid = 78800
        lower_invalid = 76800

    else:
        return None

    # =========================
    # 공통 필터
    # =========================
    volume_ok = vol >= 1.2
    strong_volume = vol >= 1.5

    # =========================
    # 🔴 숏 타점 1
    # 지지 이탈형
    # =========================
    if (
        price < support_break
        and volume_ok
        and rsi <= 35
        and price < ema20
        and price < ema50
    ):
        return {
            "signal": "SHORT",
            "type": "지지 이탈 숏",
            "message": (
                f"🔴 {symbol} 숏 타점 발생\n"
                f"유형: 지지 이탈 숏\n"
                f"현재가: {price}\n"
                f"거래량비율: {vol}\n"
                f"RSI: {rsi}\n\n"
                f"판단: 지지 이탈 + EMA 하단 + 약세 RSI\n"
                f"행동: 숏 진입 검토\n"
                f"무효화: {support_break} 위 재진입"
            )
        }

    # =========================
    # 🔴 숏 타점 2
    # 저항 반등 실패형
    # =========================
    if (
        price < ema20
        and price < ema50
        and rsi < 50
        and strong_volume
    ):
        return {
            "signal": "SHORT",
            "type": "저항 반등 실패 숏",
            "message": (
                f"🔴 {symbol} 숏 타점 발생\n"
                f"유형: 저항 반등 실패 숏\n"
                f"현재가: {price}\n"
                f"거래량비율: {vol}\n"
                f"RSI: {rsi}\n\n"
                f"판단: EMA 저항 아래에서 반등 실패\n"
                f"행동: 숏 진입 검토\n"
                f"무효화: {upper_invalid} 위 안착"
            )
        }

    # =========================
    # 🟢 롱 타점 1
    # 저항 돌파형
    # =========================
    if (
        price > resistance_break
        and volume_ok
        and rsi >= 55
        and price > ema20
        and price > ema50
    ):
        return {
            "signal": "LONG",
            "type": "저항 돌파 롱",
            "message": (
                f"🟢 {symbol} 롱 타점 발생\n"
                f"유형: 저항 돌파 롱\n"
                f"현재가: {price}\n"
                f"거래량비율: {vol}\n"
                f"RSI: {rsi}\n\n"
                f"판단: 저항 돌파 + EMA 상단 + RSI 상승\n"
                f"행동: 롱 진입 검토\n"
                f"무효화: {resistance_break} 아래 재이탈"
            )
        }

    # =========================
    # 🟢 롱 타점 2
    # 지지 반등형
    # =========================
    if (
        price > ema20
        and rsi >= 50
        and volume_ok
    ):
        return {
            "signal": "LONG",
            "type": "지지 반등 롱",
            "message": (
                f"🟢 {symbol} 롱 타점 발생\n"
                f"유형: 지지 반등 롱\n"
                f"현재가: {price}\n"
                f"거래량비율: {vol}\n"
                f"RSI: {rsi}\n\n"
                f"판단: EMA20 위 회복 + RSI 50 이상\n"
                f"행동: 롱 진입 검토\n"
                f"무효화: EMA20 아래 재이탈"
            )
        }

    return None
