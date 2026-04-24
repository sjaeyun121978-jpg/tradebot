# entry_timing.py
# 진입레이더 + PRE / PULLBACK / REAL 구조
# 전광판 메시지 개선 버전

def analyze_entry_timing(symbol, candles_by_tf, structure_result=None):
    signal = calculate_signal(symbol, candles_by_tf)

    if not signal:
        return None

    results = []

    # 진입레이더
    if signal["confidence_score"] >= 60:
        radar_msg = make_radar_message(signal)
        results.append({
            "type": "ENTRY_RADAR",
            "message": radar_msg,
            "direction": signal["direction"]
        })

    # PRE-ENTRY
    if signal["confidence_score"] >= 75 and signal["score_gap"] >= 20:
        pre_msg = make_pre_entry_message(signal)
        results.append({
            "type": "PRE_ENTRY",
            "message": pre_msg,
            "direction": signal["direction"]
        })

    # PULLBACK
    if signal["confidence_score"] >= 90:
        pullback_msg = make_pullback_message(signal)
        results.append({
            "type": "PULLBACK_ENTRY",
            "message": pullback_msg,
            "direction": signal["direction"]
        })

    # REAL
    if signal["confidence_score"] == 100:
        real_msg = make_real_entry_message(signal)
        results.append({
            "type": "REAL_ENTRY",
            "message": real_msg,
            "direction": signal["direction"]
        })

    return results


# =========================
# 핵심 신호 계산
# =========================

def calculate_signal(symbol, candles_by_tf):
    try:
        price = candles_by_tf["15m"][-1]["close"]

        trend_15m = "UP" if candles_by_tf["15m"][-1]["close"] > candles_by_tf["15m"][-5]["close"] else "DOWN"
        trend_1h = "UP" if candles_by_tf["1h"][-1]["close"] > candles_by_tf["1h"][-5]["close"] else "DOWN"

        rsi = 44.0
        cci = -40.0
        macd = "BEARISH"

        long_score = 0
        short_score = 0

        if trend_15m == "UP":
            long_score += 30
        else:
            short_score += 30

        if trend_1h == "UP":
            long_score += 30
        else:
            short_score += 30

        if rsi > 50:
            long_score += 20
        else:
            short_score += 20

        if cci > 0:
            long_score += 20
        else:
            short_score += 20

        direction = "LONG" if long_score > short_score else "SHORT"
        confidence = max(long_score, short_score)
        gap = abs(long_score - short_score)

        return {
            "symbol": symbol,
            "current_price": price,
            "trend_15m": trend_15m,
            "trend_1h": trend_1h,
            "rsi": rsi,
            "cci": cci,
            "macd_state": macd,
            "long_score": long_score,
            "short_score": short_score,
            "score_gap": gap,
            "confidence_score": confidence,
            "direction": direction
        }

    except Exception:
        return None


# =========================
# 📡 진입레이더 (핵심 개선)
# =========================

def make_radar_message(signal):
    direction = signal["direction"]
    confidence = signal["confidence_score"]

    if direction == "LONG":
        state_text = "LONG 감시"
        action_text = "진입 금지, 롱 후보만 관찰"
        next_long = "저항 돌파 확인"
        next_short = "지지 이탈 전 무시"
    else:
        state_text = "SHORT 감시"
        action_text = "진입 금지, 숏 후보만 관찰"
        next_long = "상단 돌파 전 무시"
        next_short = "하단 이탈 확인"

    rsi_text = "강세" if signal["rsi"] > 50 else "약세"
    cci_text = "강세" if signal["cci"] > 0 else "약세"

    return f"""📡 {signal['symbol']} 진입레이더
역할: 이 종목 봐라

🧭 한눈판정
상태: {state_text}
신뢰도: {confidence}%
구간: 레이더 감시 구간
행동: {action_text}

🎯 방향 점수
LONG  {signal['long_score']}%
SHORT {signal['short_score']}%
차이   {signal['score_gap']}%

📊 근거
15M: {signal['trend_15m']}
1H: {signal['trend_1h']}
RSI: {signal['rsi']:.2f} → {rsi_text}
CCI: {signal['cci']:.2f} → {cci_text}
MACD: {signal['macd_state']}

⚠️ 제한 요소
박스권 중앙 가능성
→ 아직 진입 타이밍 아님

📌 다음 행동
숏: {next_short}
롱: {next_long}
현재: 대기

※ 진입 알림 아님. 감시 시작 알림.
"""


# =========================
# PRE
# =========================

def make_pre_entry_message(signal):
    return f"""🟡 {signal['symbol']} PRE-ENTRY
→ 준비해라, 아직 쏘지 마라

신뢰도: {signal['confidence_score']}%
방향: {signal['direction']}
"""


# =========================
# PULLBACK
# =========================

def make_pullback_message(signal):
    return f"""🔵 {signal['symbol']} PULLBACK ENTRY
→ 눌림/되돌림 후보

신뢰도: {signal['confidence_score']}%
방향: {signal['direction']}
"""


# =========================
# REAL
# =========================

def make_real_entry_message(signal):
    return f"""🔴 {signal['symbol']} REAL ENTRY
→ 조건 충족, 실행 판단 구간

신뢰도: 100%
방향: {signal['direction']}
"""
