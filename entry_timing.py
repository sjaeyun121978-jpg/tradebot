def judge_entry_timing(symbol, price, indicators):
    debug = get_entry_debug_status(symbol, price, indicators)

    if not debug:
        return None

    if debug["signal"] not in ["LONG", "SHORT"]:
        return None

    if debug["score"] < 85:
        return None

    return {
        "signal": debug["signal"],
        "type": debug["type"],
        "message": (
            f"{'🟢' if debug['signal'] == 'LONG' else '🔴'} {symbol} 실전 진입 타점\n\n"
            f"📌 방향: {debug['signal']}\n"
            f"📊 조건 충족률: {debug['score']}%\n"
            f"현재가: {price}\n\n"
            f"{debug['detail']}\n\n"
            f"🛑 손절: {debug['stop_loss']}\n"
            f"🎯 1차 익절: {debug['tp1']}\n"
            f"🎯 2차 익절: {debug['tp2']}"
        )
    }


def get_entry_debug_status(symbol, price, indicators):
    if not price or not indicators:
        return None

    rsi = indicators.get("rsi")
    cci = indicators.get("cci")
    vol = indicators.get("vol_ratio")
    ema20 = indicators.get("ema20")
    ema50 = indicators.get("ema50")
    rsi_div = indicators.get("rsi_divergence")
    cci_div = indicators.get("cci_divergence")
    structure = indicators.get("structure", {})

    if None in [rsi, cci, vol, ema20, ema50]:
        return None

    if symbol == "ETH":
        long_break = 2330
        short_break = 2300
        long_sl = 2315
        short_sl = 2320
        long_tp1 = 2340
        long_tp2 = 2360
        short_tp1 = 2290
        short_tp2 = 2283

    elif symbol == "BTC":
        long_break = 79000
        short_break = 77000
        long_sl = 78300
        short_sl = 78500
        long_tp1 = 80500
        long_tp2 = 81000
        short_tp1 = 76000
        short_tp2 = 75500

    else:
        return None

    s15 = structure.get("15M", {}).get("structure", "")
    s1h = structure.get("1H", {}).get("structure", "")
    s4h = structure.get("4H", {}).get("structure", "")

    long_score = 0
    short_score = 0
    long_reasons = []
    short_reasons = []

    # 거래량
    if vol >= 1.2:
        long_score += 20
        short_score += 20
        long_reasons.append(f"✅ 거래량 {vol} 충족")
        short_reasons.append(f"✅ 거래량 {vol} 충족")
    else:
        long_reasons.append(f"❌ 거래량 {vol} 부족")
        short_reasons.append(f"❌ 거래량 {vol} 부족")

    # EMA
    if price > ema20 and price > ema50:
        long_score += 25
        long_reasons.append("✅ EMA20/50 상단")
    else:
        long_reasons.append("❌ EMA 상단 미확정")

    if price < ema20 and price < ema50:
        short_score += 25
        short_reasons.append("✅ EMA20/50 하단")
    else:
        short_reasons.append("❌ EMA 하단 미확정")

    # RSI
    if rsi >= 55:
        long_score += 15
        long_reasons.append(f"✅ RSI {rsi} 상승 우위")
    else:
        long_reasons.append(f"❌ RSI {rsi} 상승 부족")

    if rsi <= 45:
        short_score += 15
        short_reasons.append(f"✅ RSI {rsi} 하락 우위")
    else:
        short_reasons.append(f"❌ RSI {rsi} 하락 부족")

    # CCI
    if cci > 0:
        long_score += 15
        long_reasons.append(f"✅ CCI {cci} 양수")
    else:
        long_reasons.append(f"❌ CCI {cci} 롱 부족")

    if cci < 0:
        short_score += 15
        short_reasons.append(f"✅ CCI {cci} 음수")
    else:
        short_reasons.append(f"❌ CCI {cci} 숏 부족")

    # 구조
    if "HH/HL" in s15 or "상승" in s15 or "HH/HL" in s1h or "상승" in s1h:
        long_score += 15
        long_reasons.append("✅ 단기/1H 상승 구조")
    else:
        long_reasons.append("❌ 상승 구조 미확정")

    if "LH/LL" in s15 or "하락" in s15 or "LH/LL" in s1h or "하락" in s1h:
        short_score += 15
        short_reasons.append("✅ 단기/1H 하락 구조")
    else:
        short_reasons.append("❌ 하락 구조 미확정")

    # 돌파/이탈
    if price >= long_break:
        long_score += 10
        long_reasons.append(f"✅ 핵심 저항 {long_break} 돌파")
    else:
        long_reasons.append(f"❌ 핵심 저항 {long_break} 미돌파")

    if price <= short_break:
        short_score += 10
        short_reasons.append(f"✅ 핵심 지지 {short_break} 이탈")
    else:
        short_reasons.append(f"❌ 핵심 지지 {short_break} 미이탈")

    # 다이버전스 충돌 차단
    if rsi_div == "하락 다이버전스" or cci_div == "하락 다이버전스":
        long_score -= 20
        long_reasons.append("⚠️ 하락 다이버전스 → 롱 감점")

    if rsi_div == "상승 다이버전스" or cci_div == "상승 다이버전스":
        short_score -= 20
        short_reasons.append("⚠️ 상승 다이버전스 → 숏 감점")

    long_score = max(0, min(100, long_score))
    short_score = max(0, min(100, short_score))

    if long_score >= short_score:
        signal = "LONG" if long_score >= 85 else "WAIT"
        return {
            "signal": signal,
            "type": "롱 조건 진행",
            "score": long_score,
            "detail": "\n".join(long_reasons),
            "stop_loss": long_sl,
            "tp1": long_tp1,
            "tp2": long_tp2,
        }

    signal = "SHORT" if short_score >= 85 else "WAIT"
    return {
        "signal": signal,
        "type": "숏 조건 진행",
        "score": short_score,
        "detail": "\n".join(short_reasons),
        "stop_loss": short_sl,
        "tp1": short_tp1,
        "tp2": short_tp2,
    }
