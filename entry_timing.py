def judge_entry_timing(symbol, price, indicators):
    debug = get_entry_debug_status(symbol, price, indicators)

    if not debug:
        return None

    score = debug["score"]
    signal = debug["signal"]
    detail = debug["detail"]

    # 핵심 조건 판단 (돌파/이탈 포함 여부)
    key_break = ("돌파" in detail) or ("이탈" in detail)

    # 🔴 REAL ENTRY
    if score >= 95 and key_break:
        return {
            "signal": signal,
            "type": "REAL",
            "message": (
                f"방향: {signal}\n"
                f"조건충족: {score}%\n\n"
                f"{detail}\n\n"
                f"🔥 지금 진입 가능"
            )
        }

    # 🟡 PRE ENTRY
    if score >= 85:
        return {
            "signal": signal,
            "type": "PRE",
            "message": (
                f"방향: {signal}\n"
                f"조건충족: {score}%\n\n"
                f"{detail}\n\n"
                f"⚠️ 핵심 조건 미완성 (대기)"
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
    structure = indicators.get("structure", {})

    if None in [rsi, cci, vol, ema20, ema50]:
        return None

    if symbol == "ETH":
        long_break = 2330
        short_break = 2300
    else:
        long_break = 79000
        short_break = 77000

    score = 0
    reasons = []

    # 거래량
    if vol >= 1.2:
        score += 20
        reasons.append(f"✅ 거래량 {vol}")
    else:
        reasons.append(f"❌ 거래량 {vol}")

    # EMA
    if price > ema20 and price > ema50:
        score += 20
        reasons.append("✅ EMA 상단")
    else:
        reasons.append("❌ EMA 미확정")

    # RSI
    if rsi >= 55:
        score += 15
        reasons.append(f"✅ RSI {rsi}")
    else:
        reasons.append(f"❌ RSI {rsi}")

    # CCI
    if cci > 0:
        score += 15
        reasons.append(f"✅ CCI {cci}")
    else:
        reasons.append(f"❌ CCI {cci}")

    # 구조
    s15 = str(structure.get("15M", {}))
    if "상승" in s15 or "HH" in s15:
        score += 15
        reasons.append("✅ 상승 구조")
    else:
        reasons.append("❌ 구조 미확정")

    # 돌파
    if price >= long_break:
        score += 15
        reasons.append(f"✅ 저항 {long_break} 돌파")
    else:
        reasons.append(f"❌ 저항 {long_break} 미돌파")

    return {
        "signal": "LONG" if score >= 50 else "SHORT",
        "score": score,
        "detail": "\n".join(reasons)
    }
