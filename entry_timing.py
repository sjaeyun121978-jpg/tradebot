def judge_entry_timing(symbol, price, indicators):
    debug = get_entry_debug_status(symbol, price, indicators)

    if not debug:
        return None

    signal = debug["signal"]
    score = debug["score"]

    if signal not in ["LONG", "SHORT"]:
        return None

    if debug["entry_level"] == "REAL":
        return {
            "signal": signal,
            "type": "REAL",
            "message": (
                f"🔴 REAL ENTRY\n\n"
                f"방향: {signal}\n"
                f"조건충족: {score}%\n"
                f"현재가: {price}\n\n"
                f"{debug['detail']}\n\n"
                f"🛑 손절: {debug['stop_loss']}\n"
                f"🎯 1차 익절: {debug['tp1']}\n"
                f"🎯 2차 익절: {debug['tp2']}\n\n"
                f"🔥 지금 진입 가능"
            )
        }

    if debug["entry_level"] == "PULLBACK":
        return {
            "signal": signal,
            "type": "PULLBACK",
            "message": (
                f"🟢 PULLBACK ENTRY\n\n"
                f"방향: {signal}\n"
                f"조건충족: {score}%\n"
                f"현재가: {price}\n\n"
                f"{debug['detail']}\n\n"
                f"🛑 손절: {debug['stop_loss']}\n"
                f"🎯 1차 익절: {debug['tp1']}\n"
                f"🎯 2차 익절: {debug['tp2']}\n\n"
                f"✅ 돌파 후 눌림 확인 → 진입 가능"
            )
        }

    if debug["entry_level"] == "PRE":
        return {
            "signal": signal,
            "type": "PRE",
            "message": (
                f"🟡 PRE-ENTRY\n\n"
                f"방향: {signal}\n"
                f"조건충족: {score}%\n"
                f"현재가: {price}\n\n"
                f"{debug['detail']}\n\n"
                f"⚠️ 진입 대기: 핵심 조건 미완성"
            )
        }

    return None


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

    # =========================
    # 거래량
    # =========================
    if vol >= 1.2:
        long_score += 20
        short_score += 20
        long_reasons.append(f"✅ 거래량 {vol} 충족")
        short_reasons.append(f"✅ 거래량 {vol} 충족")
    else:
        long_reasons.append(f"❌ 거래량 {vol} 부족")
        short_reasons.append(f"❌ 거래량 {vol} 부족")

    # =========================
    # EMA 위치
    # =========================
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

    # =========================
    # RSI
    # =========================
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

    # =========================
    # CCI
    # =========================
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

    # =========================
    # 구조
    # =========================
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

    # =========================
    # 4H 역방향 감점
    # =========================
    if "하락" in s4h or "LH/LL" in s4h:
        long_score -= 10
        long_reasons.append("⚠️ 4H 하락 구조 → 롱 감점")

    if "상승" in s4h or "HH/HL" in s4h:
        short_score -= 10
        short_reasons.append("⚠️ 4H 상승 구조 → 숏 감점")

    # =========================
    # 진짜 돌파 확인
    # =========================
    long_break_ok = price >= long_break
    short_break_ok = price <= short_break

    long_breakout_confirm = (
        price >= long_break
        and vol >= 1.2
        and rsi >= 55
        and cci > 0
        and price > ema20
        and price > ema50
    )

    short_breakdown_confirm = (
        price <= short_break
        and vol >= 1.2
        and rsi <= 45
        and cci < 0
        and price < ema20
        and price < ema50
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

    # =========================
    # 돌파 후 눌림 진입
    # =========================
    long_pullback_entry = (
        price > long_break
        and price <= long_break + pullback_range
        and price > ema20
        and price > ema50
        and rsi >= 50
        and cci > 0
        and vol >= 0.8
        and ("상승" in s15 or "HH/HL" in s15 or "상승" in s1h or "HH/HL" in s1h)
    )

    short_pullback_entry = (
        price < short_break
        and price >= short_break - pullback_range
        and price < ema20
        and price < ema50
        and rsi <= 50
        and cci < 0
        and vol >= 0.8
        and ("하락" in s15 or "LH/LL" in s15 or "하락" in s1h or "LH/LL" in s1h)
    )

    if long_pullback_entry:
        long_score += 10
        long_reasons.append("✅ 돌파 후 눌림 매수 구간")

    if short_pullback_entry:
        short_score += 10
        short_reasons.append("✅ 이탈 후 되돌림 숏 구간")

    # =========================
    # 다이버전스
    # =========================
    if rsi_div == "하락 다이버전스" or cci_div == "하락 다이버전스":
        long_score -= 20
        long_reasons.append("⚠️ 하락 다이버전스 → 롱 감점")
        short_score += 10
        short_reasons.append("✅ 하락 다이버전스 보조")

    if rsi_div == "상승 다이버전스" or cci_div == "상승 다이버전스":
        short_score -= 20
        short_reasons.append("⚠️ 상승 다이버전스 → 숏 감점")
        long_score += 10
        long_reasons.append("✅ 상승 다이버전스 보조")

    long_score = max(0, min(100, long_score))
    short_score = max(0, min(100, short_score))

    # =========================
    # 최종 방향 선택
    # =========================
    if long_score >= short_score:
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

    # =========================
    # 알림 등급
    # =========================
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
