"""
market_state.py
시장 상태 분류 엔진 (Market State Engine)

진입 전 최우선 판단: "지금 매매 가능한 장인가?"

state 종류:
  TREND_UP   - 상승 추세장 (매매 가능)
  TREND_DOWN - 하락 추세장 (매매 가능)
  RANGE      - 박스장 (진입 금지)
  SQUEEZE    - 변동성 수축 (방향 확정 대기)
  CHAOS      - 급변동/휩쏘 (진입 금지)
  WEAK       - 거래량/데이터 부족 (진입 금지)
"""

from tradebot.analysis.core import (
    calc_rsi, calc_bollinger, detect_trend, detect_range,
    get_close, get_high, get_low, get_volume,
    avg, safe_float,
)


# ─────────────────────────────────────────────
# 내부 유틸
# ─────────────────────────────────────────────

def _calc_atr(candles, period=14):
    if len(candles) < period + 1:
        ranges = [
            safe_float(c.get("high")) - safe_float(c.get("low"))
            for c in candles[-5:]
            if safe_float(c.get("high")) and safe_float(c.get("low"))
        ]
        return sum(ranges) / len(ranges) if ranges else 0.0
    trs = []
    for i in range(1, len(candles)):
        h  = safe_float(candles[i].get("high"))
        l  = safe_float(candles[i].get("low"))
        pc = safe_float(candles[i-1].get("close"))
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-period:]) / period


def _volatility_ratio(candles):
    """현재 ATR / 과거 ATR 비율 — 급변동 감지"""
    if len(candles) < 35:
        return 1.0
    cur_atr  = _calc_atr(candles[-15:], 14)
    past_atr = _calc_atr(candles[-35:-15], 14)
    return cur_atr / past_atr if past_atr > 0 else 1.0


def _whipsaw_score(candles, lookback=8):
    """단기 방향 전환 빈도 (0~1, 높을수록 휩쏘)"""
    if len(candles) < lookback + 1:
        return 0.0
    recent = candles[-(lookback + 1):]
    reversals = 0
    for i in range(2, len(recent)):
        prev = 1 if get_close(recent[i-1]) >= get_close(recent[i-2]) else -1
        curr = 1 if get_close(recent[i])   >= get_close(recent[i-1]) else -1
        if prev != curr:
            reversals += 1
    return reversals / (lookback - 1) if lookback > 1 else 0.0


def _volume_ok(candles, threshold=0.6):
    """현재 거래량이 20봉 평균의 threshold 이상인지"""
    if not candles:
        return False
    vols    = [get_volume(c) for c in candles[-20:]]
    avg_vol = avg(vols)
    cur_vol = get_volume(candles[-1])
    return cur_vol >= avg_vol * threshold if avg_vol > 0 else True


# ─────────────────────────────────────────────
# 메인 분류 함수
# ─────────────────────────────────────────────

def classify_market(candles_by_tf: dict) -> dict:
    """
    시장 상태 분류

    반환:
    {
        "state":         "TREND_UP/TREND_DOWN/RANGE/SQUEEZE/CHAOS/WEAK",
        "tradable":      True/False,
        "trend_aligned": True/False,
        "reason":        "판단 근거 텍스트",
        "details":       { 상세 수치 dict }
    }
    """
    c15 = candles_by_tf.get("15m", [])
    c1h = candles_by_tf.get("1h",  [])
    c4h = candles_by_tf.get("4h",  [])
    c1d = candles_by_tf.get("1d",  [])

    if not c15 or len(c15) < 50:
        return _result("WEAK", False, False, "캔들 데이터 부족 (50봉 미만)")

    closes = [get_close(c) for c in c15]

    # 기본 지표
    trend_15m = detect_trend(c15)
    trend_1h  = detect_trend(c1h) if len(c1h) >= 50 else "SIDEWAYS"
    trend_4h  = detect_trend(c4h) if len(c4h) >= 50 else "SIDEWAYS"
    trend_1d  = detect_trend(c1d) if len(c1d) >= 50 else "SIDEWAYS"

    is_range_15,  range_pos, range_hi, range_lo = detect_range(c15)
    is_range_1h,  _,         _,        _         = detect_range(c1h) if c1h else (False, None, None, None)

    bb         = calc_bollinger(closes)
    vol_ratio  = _volatility_ratio(c15)
    whipsaw    = _whipsaw_score(c15)
    vol_ok     = _volume_ok(c15)
    rsi        = calc_rsi(closes)

    trend_aligned = (trend_1h == trend_4h and trend_1h in ("UP", "DOWN"))

    details = {
        "trend_15m":     trend_15m,
        "trend_1h":      trend_1h,
        "trend_4h":      trend_4h,
        "trend_1d":      trend_1d,
        "is_range":      is_range_15,
        "range_pos":     range_pos,
        "bb_squeeze":    bb.get("squeeze", False),
        "bb_width":      round(bb.get("width", 0), 3),
        "vol_ratio":     round(vol_ratio, 2),
        "whipsaw":       round(whipsaw, 2),
        "rsi":           round(rsi, 1),
        "vol_ok":        vol_ok,
        "trend_aligned": trend_aligned,
    }

    # ── CHAOS: 급변동 ──────────────────────────
    if vol_ratio >= 2.5:
        return _result("CHAOS", False, trend_aligned,
            f"급변동 감지 (ATR {vol_ratio:.1f}배) — 진입 금지", details)

    if whipsaw >= 0.7:
        return _result("CHAOS", False, trend_aligned,
            f"휩쏘 구간 (방향전환 {whipsaw:.0%}) — 진입 금지", details)

    # ── WEAK: 거래량 부족 ──────────────────────
    if not vol_ok:
        return _result("WEAK", False, trend_aligned,
            "거래량 부족 (평균 60% 미만) — 진입 금지", details)

    # ── SQUEEZE: 변동성 수축 ───────────────────
    if bb.get("squeeze") and bb.get("width", 999) < 1.5:
        return _result("SQUEEZE", False, trend_aligned,
            f"볼린저 수축 (밴드폭 {bb.get('width',0):.2f}%) — 방향 확정 대기", details)

    # ── RANGE: 박스장 ─────────────────────────
    if is_range_15 and is_range_1h:
        return _result("RANGE", False, trend_aligned,
            f"박스장 (15M+1H 동시) 위치:{range_pos} — 돌파 확인 전 금지", details)

    if is_range_15 and trend_1h == "SIDEWAYS" and trend_4h == "SIDEWAYS":
        return _result("RANGE", False, trend_aligned,
            f"박스장 (15M박스+상위봉 횡보) — 중앙 진입 금지", details)

    # ── TREND: 추세장 ─────────────────────────
    if trend_4h == "UP" and trend_1h in ("UP", "SIDEWAYS"):
        return _result("TREND_UP", True, trend_aligned,
            f"상승 추세장 (4H:{trend_4h}/1H:{trend_1h})", details)

    if trend_4h == "DOWN" and trend_1h in ("DOWN", "SIDEWAYS"):
        return _result("TREND_DOWN", True, trend_aligned,
            f"하락 추세장 (4H:{trend_4h}/1H:{trend_1h})", details)

    if trend_1h == "UP" and trend_15m == "UP":
        return _result("TREND_UP", True, trend_aligned,
            f"단기 상승 (1H+15M 일치)", details)

    if trend_1h == "DOWN" and trend_15m == "DOWN":
        return _result("TREND_DOWN", True, trend_aligned,
            f"단기 하락 (1H+15M 일치)", details)

    # ── 방향 미확정 → RANGE 처리 ──────────────
    return _result("RANGE", False, trend_aligned,
        f"방향 미확정 (4H:{trend_4h}/1H:{trend_1h}/15M:{trend_15m}) — 대기", details)


def _result(state, tradable, trend_aligned, reason, details=None):
    return {
        "state":         state,
        "tradable":      tradable,
        "trend_aligned": trend_aligned,
        "reason":        reason,
        "details":       details or {},
    }


def is_tradable(ms: dict) -> bool:
    return bool(ms.get("tradable", False))


def get_state(ms: dict) -> str:
    return ms.get("state", "WEAK")
