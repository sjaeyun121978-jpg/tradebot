# entry_timing.py
# 진입레이더 / PRE-ENTRY / REAL ENTRY
# 분석은 structure_analyzer.analyze() 1번만 호출
# 여기서는 조건 필터 + 메시지 포맷만 담당

from datetime import datetime, timezone, timedelta
from core_analyzer import analyze, pct_distance

KST = timezone(timedelta(hours=9))

# ─────────────────────────────────────────────
# 임계값 상수
# ─────────────────────────────────────────────
RADAR_MIN_SCORE   = 60
PRE_MIN_SCORE     = 75
REAL_MIN_SCORE    = 90
PULLBACK_MIN_SCORE = 90

MIN_SCORE_GAP     = 15
PRE_SCORE_GAP     = 20

PRE_LEVEL_DISTANCE  = 0.0015   # 0.15%
PRE_VOLUME_RATIO    = 0.8
REAL_VOLUME_RATIO   = 1.2
PULLBACK_DISTANCE   = 0.0025

RSI_LONG_MIN  = 50
RSI_SHORT_MAX = 50

# PRE 신호 메모리 (1시간 유효)
PRE_SIGNAL_MEMORY    = {}
PRE_SIGNAL_EXPIRE_SEC = 3600


def _now_ts():
    return datetime.now().timestamp()


# ─────────────────────────────────────────────
# 메시지 포맷 헬퍼
# ─────────────────────────────────────────────

_TREND_KO  = {"UP": "상승", "DOWN": "하락", "SIDEWAYS": "횡보"}
_MACD_KO   = {
    "BULLISH": "강세↑", "BEARISH": "약세↓",
    "POSITIVE": "양전환", "NEGATIVE": "음전환", "NEUTRAL": "중립"
}
_DIV_KO    = {"BULLISH_DIV": "상승다이버전스", "BEARISH_DIV": "하락다이버전스"}


def _trend(tf, sig):
    return _TREND_KO.get(sig.get(f"trend_{tf}", "SIDEWAYS"), "횡보")


# ─────────────────────────────────────────────
# 1. 진입레이더 메시지
# ─────────────────────────────────────────────

def make_radar_message(sig, reason):
    direction = sig.get("direction", "WAIT")
    confidence = sig.get("confidence", 0)
    long_score  = sig.get("long_score", 0)
    short_score = sig.get("short_score", 0)
    rsi_val     = sig.get("rsi", 50)
    cci_val     = sig.get("cci", 0)
    macd        = _MACD_KO.get(sig.get("macd_state", "NEUTRAL"), "중립")
    div         = _DIV_KO.get(sig.get("divergence"), "")
    div_line    = f"\n   {div}" if div else ""

    if direction == "SHORT":
        badge      = "SHORT 감시"
        act_short  = "박스 하단 이탈 확인 후"
        act_long   = "박스 상단 돌파 전 무시"
    elif direction == "LONG":
        badge      = "LONG 감시"
        act_short  = "박스 하단 이탈 전 무시"
        act_long   = "박스 상단 돌파 확인 후"
    else:
        badge      = "방향 대기"
        act_short  = "하단 이탈 확인"
        act_long   = "상단 돌파 확인"

    rsi_txt = "강세↑" if rsi_val >= 50 else "약세↓"
    cci_txt = "강세↑" if cci_val >= 0  else "약세↓"

    return (
        f"🔍 {sig['symbol']} · 진입레이더 · 감시구간\n"
        f"\n"
        f"⚡ {badge} | 신뢰도 {confidence}%\n"
        f"   LONG {long_score}% · SHORT {short_score}%\n"
        f"\n"
        f"📊 {_trend('15m', sig)}(15M) · {_trend('1h', sig)}(1H)\n"
        f"   RSI {rsi_val:.1f} {rsi_txt} · CCI {cci_val:.0f} {cci_txt} · MACD {macd}"
        f"{div_line}\n"
        f"\n"
        f"⚠️ {reason}\n"
        f"▶ 숏: {act_short}\n"
        f"✗ 롱: {act_long}\n"
        f"\n"
        f"⏳ 대기 중"
    )


# ─────────────────────────────────────────────
# 2. PRE-ENTRY 메시지
# ─────────────────────────────────────────────

def make_pre_entry_message(sig):
    direction    = sig["direction"]
    price        = sig["current_price"]
    key          = sig["key_level"]
    div          = _DIV_KO.get(sig.get("divergence"), "")
    div_line     = f"✅ {div} 감지\n" if div else ""

    if direction == "SHORT":
        trigger = f"15분봉 종가 {key:.2f} 이탈"
        stop    = f"{sig['resistance']:.2f}"
        tp1, tp2 = price * 0.995, price * 0.990
    else:
        trigger = f"15분봉 종가 {key:.2f} 돌파"
        stop    = f"{sig['support']:.2f}"
        tp1, tp2 = price * 1.005, price * 1.010

    vol_ratio = sig["volume"] / sig["avg_volume"] if sig.get("avg_volume") else 0
    dist_pct  = pct_distance(price, key) * 100 if key else 0

    return (
        f"🚨 {sig['symbol']} PRE-ENTRY\n"
        f"→ 준비해라, 아직 쏘지 마라\n"
        f"\n"
        f"신뢰도: {sig['confidence']}% | 방향: {direction}\n"
        f"현재가: {price:.2f}\n"
        f"\n"
        f"✅ 신뢰도 75% 이상\n"
        f"✅ 핵심 가격 근접 {dist_pct:.2f}%\n"
        f"✅ 거래량 {vol_ratio:.2f}배\n"
        f"{div_line}"
        f"\n"
        f"📌 트리거: {trigger}\n"
        f"🛑 손절: {stop}\n"
        f"🎯 1차: {tp1:.2f} / 2차: {tp2:.2f}\n"
        f"\n"
        f"⚠️ REAL ENTRY 아님 — 가격 트리거 대기 중"
    )


# ─────────────────────────────────────────────
# 3. REAL ENTRY 메시지
# ─────────────────────────────────────────────

def make_real_entry_message(sig, pre_sig):
    direction = sig["direction"]
    price     = sig["current_price"]
    key       = pre_sig["key_level"]
    div       = _DIV_KO.get(sig.get("divergence"), "")
    div_line  = f"✅ {div} 확인\n" if div else ""
    vol_ratio = sig["volume"] / sig["avg_volume"] if sig.get("avg_volume") else 0

    if direction == "SHORT":
        stop    = pre_sig.get("resistance") or price * 1.005
        tp1, tp2 = price * 0.995, price * 0.990
        trigger = f"지지선 {key:.2f} 이탈 확정"
    else:
        stop    = pre_sig.get("support") or price * 0.995
        tp1, tp2 = price * 1.005, price * 1.010
        trigger = f"저항선 {key:.2f} 돌파 확정"

    return (
        f"🔥 {sig['symbol']} REAL ENTRY\n"
        f"→ 조건 충족, 최종 확인 후 실행 판단\n"
        f"\n"
        f"신뢰도: {sig['confidence']}% | 방향: {direction}\n"
        f"현재가: {price:.2f}\n"
        f"\n"
        f"✅ PRE-ENTRY 선행 존재\n"
        f"✅ {trigger}\n"
        f"✅ 거래량 {vol_ratio:.2f}배\n"
        f"✅ RSI / MACD 조건 충족\n"
        f"{div_line}"
        f"\n"
        f"🛑 손절: {stop:.2f}\n"
        f"🎯 1차: {tp1:.2f} / 2차: {tp2:.2f}\n"
        f"\n"
        f"⚠️ 자동진입 아님 — 직접 확인 후 체결"
    )


# ─────────────────────────────────────────────
# 4. PULLBACK 메시지
# ─────────────────────────────────────────────

def make_pullback_message(sig, reason):
    direction = sig["direction"]
    price     = sig["current_price"]
    ema20     = sig["ema20"]

    if direction == "SHORT":
        stop = price * 1.004
        tp1, tp2 = price * 0.996, price * 0.992
    else:
        stop = price * 0.996
        tp1, tp2 = price * 1.004, price * 1.008

    return (
        f"🟠 {sig['symbol']} PULLBACK ENTRY\n"
        f"→ 눌림/되돌림 후보\n"
        f"\n"
        f"신뢰도: {sig['confidence']}% | 방향: {direction}\n"
        f"현재가: {price:.2f} | EMA20: {ema20:.2f}\n"
        f"\n"
        f"✅ {reason}\n"
        f"\n"
        f"🛑 손절: {stop:.2f}\n"
        f"🎯 1차: {tp1:.2f} / 2차: {tp2:.2f}\n"
        f"\n"
        f"⚠️ 자동진입 아님"
    )


# ─────────────────────────────────────────────
# 5. WAIT 메시지
# ─────────────────────────────────────────────

def make_wait_message(sig, reason):
    return (
        f"⏸ {sig['symbol']} WAIT\n"
        f"\n"
        f"신뢰도: {sig['confidence']}%\n"
        f"LONG {sig['long_score']}% · SHORT {sig['short_score']}%\n"
        f"\n"
        f"사유: {reason}"
    )


# ─────────────────────────────────────────────
# 조건 필터
# ─────────────────────────────────────────────

def _check_pre(sig):
    d   = sig["direction"]
    c   = sig["confidence"]
    gap = sig["score_gap"]

    if d == "WAIT":                    return False, "방향 미확정"
    if c < PRE_MIN_SCORE:              return False, "신뢰도 75% 미만"
    if gap < PRE_SCORE_GAP:            return False, "점수차 20% 미만"

    price = sig["current_price"]
    key   = sig["key_level"]
    vol   = sig["volume"]
    avg_v = sig["avg_volume"]

    if key and pct_distance(price, key) > PRE_LEVEL_DISTANCE:
        return False, "핵심 가격 0.15% 초과"

    if avg_v and vol < avg_v * PRE_VOLUME_RATIO:
        return False, "거래량 부족"

    if d == "SHORT":
        if not (sig["trend_15m"] == "DOWN" and
                (sig["trend_1h"] == "DOWN" or sig["below_ema20"])):
            return False, "하락 추세 정렬 부족"
        if sig["is_range"] and sig["range_pos"] != "TOP":
            return False, "박스권 숏 조건 아님"

    if d == "LONG":
        if not (sig["trend_15m"] == "UP" and
                (sig["trend_1h"] == "UP" or sig["above_ema20"])):
            return False, "상승 추세 정렬 부족"
        if sig["is_range"] and sig["range_pos"] != "BOTTOM":
            return False, "박스권 롱 조건 아님"

    return True, "PRE-ENTRY 유효"


def _check_real(pre_sig, sig):
    if not pre_sig:                        return False, "활성 PRE 없음"
    if sig["direction"] != pre_sig["direction"]: return False, "방향 불일치"
    if sig["confidence"] < REAL_MIN_SCORE: return False, "신뢰도 90% 미만"
    if sig["score_gap"] < PRE_SCORE_GAP:   return False, "점수차 부족"

    d     = sig["direction"]
    close = sig["close_15m"]
    key   = pre_sig["key_level"]
    vol   = sig["volume"]
    avg_v = sig["avg_volume"]

    if not key:                            return False, "핵심 가격 없음"
    if avg_v and vol < avg_v * REAL_VOLUME_RATIO: return False, "거래량 부족"

    if d == "SHORT":
        if close >= key:                   return False, "이탈 미확정"
        if sig["rsi"] >= RSI_SHORT_MAX:    return False, "RSI 조건 미충족"
        if sig["macd_state"] not in ("BEARISH", "NEGATIVE"): return False, "MACD 조건 미충족"

    if d == "LONG":
        if close <= key:                   return False, "돌파 미확정"
        if sig["rsi"] <= RSI_LONG_MIN:     return False, "RSI 조건 미충족"
        if sig["macd_state"] not in ("BULLISH", "POSITIVE"): return False, "MACD 조건 미충족"

    return True, "REAL ENTRY 확정"


def _check_pullback(sig):
    d     = sig["direction"]
    c     = sig["confidence"]
    gap   = sig["score_gap"]
    price = sig["current_price"]
    ema20 = sig["ema20"]

    if c < PULLBACK_MIN_SCORE: return False, "신뢰도 90% 미만"
    if gap < PRE_SCORE_GAP:    return False, "점수차 부족"

    if d == "LONG":
        if sig["trend_15m"] == "UP" and sig["trend_1h"] in ("UP", "SIDEWAYS"):
            if pct_distance(price, ema20) <= PULLBACK_DISTANCE and price >= ema20:
                return True, "상승 추세 EMA20 눌림"

    if d == "SHORT":
        if sig["trend_15m"] == "DOWN" and sig["trend_1h"] in ("DOWN", "SIDEWAYS"):
            if pct_distance(price, ema20) <= PULLBACK_DISTANCE and price <= ema20:
                return True, "하락 추세 EMA20 되돌림"

    return False, "PULLBACK 조건 미충족"


# ─────────────────────────────────────────────
# PRE 메모리 관리
# ─────────────────────────────────────────────

def _save_pre(sig):
    sym = sig.get("symbol")
    if sym:
        PRE_SIGNAL_MEMORY[sym] = {"ts": _now_ts(), "sig": sig.copy()}


def _get_pre(symbol):
    item = PRE_SIGNAL_MEMORY.get(symbol)
    if not item:
        return None
    if _now_ts() - item["ts"] > PRE_SIGNAL_EXPIRE_SEC:
        PRE_SIGNAL_MEMORY.pop(symbol, None)
        return None
    return item["sig"]


# ─────────────────────────────────────────────
# 진입레이더 실행 흐름 (RADAR → PRE → REAL)
# ─────────────────────────────────────────────

def run_entry_radar(symbol: str, candles_by_tf: dict) -> dict:
    """
    15분봉 마감 시 호출.
    structure_analyzer.analyze()로 단일 분석 후
    조건에 따라 RADAR / PRE / REAL / PULLBACK / WAIT 분기.
    """
    # ① 단일 분석 엔진 호출
    sig = analyze(symbol, candles_by_tf)

    c   = sig["confidence"]
    gap = sig["score_gap"]
    d   = sig["direction"]

    # ② WAIT 조건
    if d == "WAIT" or c < RADAR_MIN_SCORE or gap < MIN_SCORE_GAP:
        reason = "신뢰도 60% 미만" if c < RADAR_MIN_SCORE else "점수차 15% 미만"
        return _result("WAIT", sig, make_wait_message(sig, reason), reason)

    # ③ REAL ENTRY 체크 (PRE 선행 필요)
    pre = _get_pre(symbol)
    real_ok, real_reason = _check_real(pre, sig)
    if real_ok:
        PRE_SIGNAL_MEMORY.pop(symbol, None)
        return _result("REAL_ENTRY", sig, make_real_entry_message(sig, pre), real_reason)

    results = []

    # ④ PULLBACK 체크
    pb_ok, pb_reason = _check_pullback(sig)
    if pb_ok:
        results.append(_result("PULLBACK_ENTRY", sig, make_pullback_message(sig, pb_reason), pb_reason))

    # ⑤ PRE-ENTRY 체크
    pre_ok, pre_reason = _check_pre(sig)
    if pre_ok:
        _save_pre(sig)
        results.append(_result("PRE_ENTRY", sig, make_pre_entry_message(sig), pre_reason))

    if results:
        return results

    # ⑥ 기본 RADAR
    if sig["is_range"] and sig["range_pos"] == "MIDDLE":
        reason = "박스권 중앙"
    else:
        reason = "방향 후보 감지"

    return _result("ENTRY_RADAR", sig, make_radar_message(sig, reason), reason)


def _result(rtype, sig, message, reason):
    return {
        "type":       rtype,
        "alert_type": rtype,
        "direction":  sig.get("direction", "WAIT"),
        "message":    message,
        "reason":     reason,
        **sig,
    }


# ─────────────────────────────────────────────
# 하위 호환 alias
# ─────────────────────────────────────────────

def analyze_entry_timing(symbol, candles_by_tf, structure_result=None):
    return run_entry_radar(symbol, candles_by_tf)

def run_entry_timing(symbol, candles_by_tf, structure_result=None):
    return run_entry_radar(symbol, candles_by_tf)

def check_entry(symbol, candles_by_tf, structure_result=None):
    return run_entry_radar(symbol, candles_by_tf)

def entry_radar(symbol, candles_by_tf, structure_result=None):
    return run_entry_radar(symbol, candles_by_tf)

def analyze_radar(symbol, candles_by_tf, structure_result=None):
    return run_entry_radar(symbol, candles_by_tf)

def check_radar(symbol, candles_by_tf, structure_result=None):
    return run_entry_radar(symbol, candles_by_tf)
