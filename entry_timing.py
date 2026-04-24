def judge_entry_timing(symbol, price, indicators):
    """
    트리거 v4 (실전용)
    - 구조 + 다이버전스 + 거래량 + EMA
    - 손절 / 익절 포함
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

    # =========================
    # 코인별 기준
    # =========================
    if symbol == "ETH":
        support = 2295
        resistance = 2315

        long_sl = 2290
        long_tp1 = 2325
        long_tp2 = 2340

        short_sl = 2320
        short_tp1 = 2290
        short_tp2 = 2275

    elif symbol == "BTC":
        support = 77000
        resistance = 78500

        long_sl = 76800
        long_tp1 = 79000
        long_tp2 = 80500

        short_sl = 78800
        short_tp1 = 76800
        short_tp2 = 75500

    else:
        return None

    # =========================
    # 구조
    # =========================
    s15 = structure.get("15M", {}).get("structure", "")
    s1h = structure.get("1H", {}).get("structure", "")

    lower_bear = "LH/LL" in s15 or "하락" in s15
    lower_bull = "HH/HL" in s15 or "상승" in s15

    mid_bear = "LH/LL" in s1h or "하락" in s1h
    mid_bull = "HH/HL" in s1h or "상승" in s1h

    # =========================
    # 다이버전스
    # =========================
    bull_div = rsi_div == "상승 다이버전스" or cci_div == "상승 다이버전스"
    bear_div = rsi_div == "하락 다이버전스" or cci_div == "하락 다이버전스"

    strong_bull = rsi_div == "상승 다이버전스" and cci_div == "상승 다이버전스"
    strong_bear = rsi_div == "하락 다이버전스" and cci_div == "하락 다이버전스"

    volume_ok = vol >= 1.2

    # =========================
    # 🔴 숏 진입
    # =========================
    if (
        price < support
        and volume_ok
        and rsi <= 45
        and price < ema20
        and (lower_bear or mid_bear)
        and not strong_bull
    ):
        return {
            "signal": "SHORT",
            "type": "지지 이탈",
            "message": (
                f"🔴 {symbol} 숏 진입 타점\n\n"

                f"📌 진입 근거\n"
                f"- 지지 {support} 이탈\n"
                f"- 하락 구조 유지\n"
                f"- EMA 하단\n"
                f"- 거래량 증가\n\n"

                f"📉 진입\n"
                f"{price} 부근 숏\n\n"

                f"🛑 손절\n"
                f"{short_sl} (상단 복귀 시)\n\n"

                f"🎯 익절\n"
                f"1차: {short_tp1}\n"
                f"2차: {short_tp2}\n\n"

                f"⚠️ 진입 금지\n"
                f"- RSI/CCI 상승 다이버전스 발생 시\n"
                f"- 거래량 감소 시\n"
            )
        }

    # =========================
    # 🔴 숏 (다이버전스)
    # =========================
    if (
        strong_bear
        and volume_ok
        and price < ema20
        and (lower_bear or mid_bear)
    ):
        return {
            "signal": "SHORT",
            "type": "다이버전스",
            "message": (
                f"🔴 {symbol} 숏 진입 타점 (다이버전스)\n\n"

                f"📌 진입 근거\n"
                f"- RSI + CCI 하락 다이버전스\n"
                f"- EMA 저항\n"
                f"- 하락 구조 유지\n\n"

                f"📉 진입\n"
                f"{price} 부근 숏\n\n"

                f"🛑 손절\n"
                f"{short_sl}\n\n"

                f"🎯 익절\n"
                f"1차: {short_tp1}\n"
                f"2차: {short_tp2}\n\n"

                f"⚠️ 진입 금지\n"
                f"- 구조 상승 전환 시\n"
            )
        }

    # =========================
    # 🟢 롱 진입
    # =========================
    if (
        price > resistance
        and volume_ok
        and rsi >= 50
        and price > ema20
        and (lower_bull or mid_bull)
        and not strong_bear
    ):
        return {
            "signal": "LONG",
            "type": "돌파",
            "message": (
                f"🟢 {symbol} 롱 진입 타점\n\n"

                f"📌 진입 근거\n"
                f"- 저항 {resistance} 돌파\n"
                f"- 상승 구조\n"
                f"- EMA 상단\n"
                f"- 거래량 증가\n\n"

                f"📈 진입\n"
                f"{price} 부근 롱\n\n"

                f"🛑 손절\n"
                f"{long_sl}\n\n"

                f"🎯 익절\n"
                f"1차: {long_tp1}\n"
                f"2차: {long_tp2}\n\n"

                f"⚠️ 진입 금지\n"
                f"- 하락 다이버전스 발생 시\n"
            )
        }

    # =========================
    # 🟢 롱 (다이버전스)
    # =========================
    if (
        strong_bull
        and volume_ok
        and price > ema20
        and (lower_bull or mid_bull)
    ):
        return {
            "signal": "LONG",
            "type": "다이버전스",
            "message": (
                f"🟢 {symbol} 롱 진입 타점 (다이버전스)\n\n"

                f"📌 진입 근거\n"
                f"- RSI + CCI 상승 다이버전스\n"
                f"- EMA 회복\n"
                f"- 구조 유지\n\n"

                f"📈 진입\n"
                f"{price} 부근 롱\n\n"

                f"🛑 손절\n"
                f"{long_sl}\n\n"

                f"🎯 익절\n"
                f"1차: {long_tp1}\n"
                f"2차: {long_tp2}\n\n"

                f"⚠️ 진입 금지\n"
                f"- 구조 하락 전환 시\n"
            )
        }

    return None
