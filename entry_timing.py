def judge_entry_timing(symbol, price, indicators):
    debug = get_entry_debug_status(symbol, price, indicators)

    if not debug:
        return None

    signal = debug["signal"]
    entry_level = debug["entry_level"]

    if signal not in ["LONG", "SHORT"]:
        return None

    if entry_level not in ["PRE", "PULLBACK", "REAL"]:
        return None

    if entry_level == "REAL":
        title = "🔴 REAL ENTRY"
        tail = "🔥 핵심 가격 트리거 충족. 진입 가능"
    elif entry_level == "PULLBACK":
        title = "🟢 PULLBACK ENTRY"
        tail = "✅ 돌파/이탈 후 눌림 확인. 진입 가능"
    else:
        title = "🟡 PRE-ENTRY"
        tail = "⚠️ 조건은 좋지만 핵심 가격 트리거 미완성. 대기"

    return {
        "signal": signal,
        "type": entry_level,
        "message": (
            f"{title}\n\n"
            f"방향: {signal}\n"
            f"조건충족: {debug['score']}%\n"
            f"현재가: {price}\n\n"
            f"{debug['detail']}\n\n"
            f"🛑 손절: {debug['stop_loss']}\n"
            f"🎯 1차 익절: {debug['tp1']}\n"
            f"🎯 2차 익절: {debug['tp2']}\n\n"
            f"{tail}"
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
        pullback_range = 8

    elif symbol == "BTC":
        long_break = 79000
        short_break = 77000
        long_sl = 78300
        short_sl = 78500
        long_tp1 = 80500
        long_tp2 = 81000
        short_tp1 = 76000
        short_tp2 = 75500
        pullback_range = 350

    else:
        return None

    s15 = str(structure.get("15M", {}))
    s1h = str(structure.get("1H", {}))
    s4h = str(structure.get("4H", {}))

    long_score = 0
    short_score = 0
    long_reasons = []
    short_reasons = []

    is_box = (
        "박스" in s15
        or "횡보" in s15
        or "박스" in s1h
        or "횡보" in s1h
    )

    long_structure = (
        "HH/HL" in s15 or "상승" in s15
        or "HH/HL" in s1h or "상승" in s1h
    )

    short_structure = (
        "LH/LL" in s15 or "하락" in s15
        or "LH/LL" in s1h or "하락" in s1h
    )

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
        long_score += 20
        long_reasons.append("✅ EMA20/50 상단")
    else:
        long_reasons.append("❌ EMA20/50 상단 미확정")

    if price < ema20 and price < ema50:
        short_score += 20
        short_reasons.append("✅ EMA20/50 하단")
    else:
        short_reasons.append("❌ EMA20/50 하단 미확정")

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
    if long_structure:
        long_score += 15
        long_reasons.append("✅ 단기/1H 상승 구조")
    else:
        long_reasons.append("❌ 상승 구조 미확정")

    if short_structure:
        short_score += 15
        short_reasons.append("✅ 단기/1H 하락 구조")
    else:
        short_reasons.append("❌ 하락 구조 미확정")

    # 박스권 감점
    if is_box:
        long_score -= 15
        short_score -= 15
        long_reasons.append("⚠️ 박스권 감지 → 롱 감점")
        short_reasons.append("⚠️ 박스권 감지 → 숏 감점")

    # 4H 역방향 감점
    if "하락" in s4h or "LH/LL" in s4h:
        long_score -= 10
        long_reasons.append("⚠️ 4H 하락 구조 → 롱 감점")

    if "상승" in s4h or "HH/HL" in s4h:
        short_score -= 10
        short_reasons.append("⚠️ 4H 상승 구조 → 숏 감점")

    # 가격 트리거
    long_break_ok = price >= long_break
    short_break_ok = price <= short_break

    long_breakout_confirm = (
        long_break_ok
        and vol >= 1.2
        and rsi >= 55
        and cci > 0
        and price > ema20
        and price > ema50
        and long_structure
    )

    short_breakdown_confirm = (
        short_break_ok
        and vol >= 1.2
        and rsi <= 45
        and cci < 0
        and price < ema20
        and price < ema50
        and short_structure
    )

    if long_breakout_confirm:
        long_score += 15
        long_reasons.append(f"✅ 핵심 저항 {long_break} 돌파 확인")
    elif long_break_ok:
        long_score += 8
        long_reasons.append(f"🟡 핵심 저항 {long_break} 단순 돌파")
    else:
        long_reasons.append(f"❌ 핵심 저항 {long_break} 미돌파")

    if short_breakdown_confirm:
        short_score += 15
        short_reasons.append(f"✅ 핵심 지지 {short_break} 이탈 확인")
    elif short_break_ok:
        short_score += 8
        short_reasons.append(f"🟡 핵심 지지 {short_break} 단순 이탈")
    else:
        short_reasons.append(f"❌ 핵심 지지 {short_break} 미이탈")

    # 숏 전용 강화
    short_rebound_fail = (
        price < ema20
        and rsi < 55
        and cci < 100
        and short_structure
    )

    if short_rebound_fail:
        short_score += 10
        short_reasons.append("✅ 반등 실패 숏 조건")

    short_lh_fail = (
        "LH" in s15
        or "LH" in s1h
        or "하락 구조" in s15
        or "하락 구조" in s1h
    )

    if short_lh_fail:
        short_score += 10
        short_reasons.append("✅ LH 고점 낮아짐 감지")

    # 눌림 롱
    long_pullback_entry = (
        price > long_break
        and price <= long_break + pullback_range
        and price > ema20
        and price > ema50
        and rsi >= 50
        and cci > 0
        and vol >= 0.8
        and long_structure
    )

    if long_pullback_entry:
        long_score += 10
        long_reasons.append("✅ 돌파 후 눌림 롱 구간")

    # 되돌림 숏
    short_pullback_entry = (
        price < short_break
        and price >= short_break - pullback_range
        and price < ema20
        and price < ema50
        and rsi <= 50
        and cci < 0
        and vol >= 0.8
        and short_structure
    )

    if short_pullback_entry:
        short_score += 10
        short_reasons.append("✅ 이탈 후 되돌림 숏 구간")

    # 다이버전스
    if rsi_div == "하락 다이버전스" or cci_div == "하락 다이버전스":
        long_score -= 20
        short_score += 10
        long_reasons.append("⚠️ 하락 다이버전스 → 롱 감점")
        short_reasons.append("✅ 하락 다이버전스 보조")

    if rsi_div == "상승 다이버전스" or cci_div == "상승 다이버전스":
        short_score -= 20
        long_score += 10
        short_reasons.append("⚠️ 상승 다이버전스 → 숏 감점")
        long_reasons.append("✅ 상승 다이버전스 보조")

    long_score = max(0, min(100, long_score))
    short_score = max(0, min(100, short_score))

    score_gap = abs(long_score - short_score)

    if score_gap < 15:
        return {
            "signal": "WAIT",
            "score": max(long_score, short_score),
            "entry_level": "RADAR",
            "detail": (
                f"⚪ 박스권/방향성 부족\n"
                f"롱 점수: {long_score}%\n"
                f"숏 점수: {short_score}%\n"
                f"점수 차이: {score_gap}%\n"
                f"→ 신규 진입 금지"
            ),
            "stop_loss": "-",
            "tp1": "-",
            "tp2": "-",
        }

    if long_score > short_score:
        signal = "LONG" if long_score >= 60 else "WAIT"
        score = long_score
        detail = "\n".join(long_reasons)
        stop_loss = long_sl
        tp1 = long_tp1
        tp2 = long_tp2
        real_ok = long_breakout_confirm
        pullback_ok = long_pullback_entry

    else:
        signal = "SHORT" if short_score >= 60 else "WAIT"
        score = short_score
        detail = "\n".join(short_reasons)
        stop_loss = short_sl
        tp1 = short_tp1
        tp2 = short_tp2
        real_ok = short_breakdown_confirm
        pullback_ok = short_pullback_entry

    if signal == "WAIT":
        entry_level = "RADAR"
    elif score >= 95 and real_ok:
        entry_level = "REAL"
    elif score >= 90 and pullback_ok:
        entry_level = "PULLBACK"
    elif score >= 85:
        entry_level = "PRE"
    else:
        entry_level = "RADAR"

    return {
        "signal": signal,
        "score": score,
        "entry_level": entry_level,
        "detail": detail,
        "stop_loss": stop_loss,
        "tp1": tp1,
        "tp2": tp2,
    }
