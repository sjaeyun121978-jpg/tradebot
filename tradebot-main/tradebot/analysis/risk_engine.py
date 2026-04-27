"""
risk_engine.py v2
리스크/손익 계산 엔진

핵심 변경 (v2):
  RR 억지 보정 제거
  → 실제 저항/지지 기준 TP 계산
  → RR < 1.5면 trade_allowed=False, reason 반환
  → TP를 강제로 늘리지 않음
"""

from tradebot.analysis.core import (
    get_close, get_high, get_low, avg, safe_float,
)

MIN_RR         = 1.5
ATR_STOP_MULTI = 1.5
ATR_TP1_MULTI  = 2.0
ATR_TP2_MULTI  = 3.5
ATR_TRAIL_MULTI = 1.2


def _safe(v, d=0.0):
    try:
        return float(v) if v is not None else d
    except Exception:
        return d


def _calc_atr(candles, period=14):
    if not candles or len(candles) < period + 1:
        ranges = [
            safe_float(c.get("high")) - safe_float(c.get("low"))
            for c in (candles or [])[-5:]
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


def _structural_stop(candles, direction, lookback=10):
    """구조적 손절: 직전 스윙 저점/고점"""
    if not candles or len(candles) < lookback:
        return None
    recent = candles[-lookback:]
    if direction == "LONG":
        return min(get_low(c) for c in recent) * 0.998
    return max(get_high(c) for c in recent) * 1.002


def _find_next_tp(candles_1h, price, direction, lookback=50):
    """
    실제 구조 기반 TP 탐색
    LONG:  현재가 위의 다음 저항(고점)
    SHORT: 현재가 아래의 다음 지지(저점)
    """
    if not candles_1h or len(candles_1h) < 10:
        return None
    if direction == "LONG":
        candidates = sorted(
            [get_high(c) for c in candles_1h[-lookback:] if get_high(c) > price * 1.005]
        )
        return candidates[0] if candidates else None
    else:
        candidates = sorted(
            [get_low(c) for c in candles_1h[-lookback:] if get_low(c) < price * 0.995],
            reverse=True,
        )
        return candidates[0] if candidates else None


def calculate_risk(
    sig:          dict,
    candles_15m:  list,
    direction:    str = None,
    candles_1h:   list = None,
) -> dict:
    """
    리스크/손익 계산

    반환:
    {
        "valid":         True/False,
        "trade_allowed": True/False,   # RR 기준 통과 여부
        "reason":        str,          # 실패 사유
        "entry":         float,
        "stop":          float,
        "tp1":           float,
        "tp2":           float,
        "trailing_trigger": float,
        "stop_pct":      float,
        "tp1_pct":       float,
        "rr":            float,
        "atr":           float,
        "stop_type":     str,
        "invalidate":    str,
        "reentry":       str,
    }
    """
    direction = (direction or sig.get("direction", "WAIT")).upper()
    if direction == "WAIT":
        return _invalid("방향 미확정")

    price      = _safe(sig.get("current_price"))
    support    = _safe(sig.get("support",    0))
    resistance = _safe(sig.get("resistance", 0))

    if price <= 0:
        return _invalid("현재가 없음")

    atr = _calc_atr(candles_15m)
    if atr <= 0:
        atr = price * 0.005

    # ── 손절 계산 ─────────────────────────────────
    atr_stop   = price - atr * ATR_STOP_MULTI if direction == "LONG" else price + atr * ATR_STOP_MULTI
    struct_stop = _structural_stop(candles_15m, direction)

    if direction == "LONG":
        level_stop = support * 0.998 if support > 0 else None
        candidates = [s for s in [atr_stop, struct_stop, level_stop] if s and s > 0 and s < price]
        stop = max(candidates) if candidates else atr_stop
    else:
        level_stop = resistance * 1.002 if resistance > 0 else None
        candidates = [s for s in [atr_stop, struct_stop, level_stop] if s and s > 0 and s > price]
        stop = min(candidates) if candidates else atr_stop

    stop_type = _stop_type(stop, atr_stop, struct_stop)
    risk = abs(price - stop)
    if risk <= 0:
        return _invalid("손절 계산 오류")

    # ── TP 계산: 실제 구조 기반 ──────────────────
    # 1순위: 실제 저항/지지선
    # 2순위: ATR 기반 (구조선 없을 때만)
    struct_tp1 = _find_next_tp(candles_1h, price, direction) if candles_1h else None

    if direction == "LONG":
        # 구조 기반 tp1
        if struct_tp1 and struct_tp1 > price:
            tp1 = struct_tp1
        else:
            tp1 = price + atr * ATR_TP1_MULTI
        tp2   = price + atr * ATR_TP2_MULTI
        trail = price + atr * ATR_TRAIL_MULTI
        reward = tp1 - price
    else:
        if struct_tp1 and struct_tp1 < price:
            tp1 = struct_tp1
        else:
            tp1 = price - atr * ATR_TP1_MULTI
        tp2   = price - atr * ATR_TP2_MULTI
        trail = price - atr * ATR_TRAIL_MULTI
        reward = price - tp1

    if reward <= 0:
        return _invalid("익절 계산 오류 (구조 확인 필요)")

    rr = reward / risk

    # ── RR 기준 미달: 억지 보정 없이 거절 ────────
    if rr < MIN_RR:
        return {
            "valid":         True,
            "trade_allowed": False,
            "reason":        f"손익비 부족 (RR {rr:.2f} < {MIN_RR}) — 진입 금지",
            "entry":   round(price, 4),
            "stop":    round(stop,  4),
            "tp1":     round(tp1,   4),
            "tp2":     round(tp2,   4),
            "trailing_trigger": round(trail, 4),
            "stop_pct":  round(abs(price - stop) / price * 100, 2),
            "tp1_pct":   round(reward / price * 100, 2),
            "rr":        round(rr, 2),
            "atr":       round(atr, 4),
            "stop_type": stop_type,
            "invalidate": f"15M 종가 {stop:,.2f} 이탈 시 청산",
            "reentry":    "RR 충족 구간 재탐색 후 재진입 검토",
        }

    stop_pct = abs(price - stop) / price * 100
    tp1_pct  = reward / price * 100
    rr_final = reward / risk

    if direction == "LONG":
        invalidate = f"15M 종가 {stop:,.2f} 하향 이탈 시 즉시 청산"
        reentry    = f"재진입: {stop:,.2f} 지지 확인 후 재롱 검토"
    else:
        invalidate = f"15M 종가 {stop:,.2f} 상향 돌파 시 즉시 청산"
        reentry    = f"재진입: {stop:,.2f} 저항 확인 후 재숏 검토"

    return {
        "valid":         True,
        "trade_allowed": True,
        "reason":        "",
        "entry":         round(price, 4),
        "stop":          round(stop,  4),
        "tp1":           round(tp1,   4),
        "tp2":           round(tp2,   4),
        "trailing_trigger": round(trail, 4),
        "stop_pct":      round(stop_pct, 2),
        "tp1_pct":       round(tp1_pct,  2),
        "rr":            round(rr_final, 2),
        "atr":           round(atr, 4),
        "stop_type":     stop_type,
        "invalidate":    invalidate,
        "reentry":       reentry,
    }


def _stop_type(stop, atr_stop, struct_stop):
    if struct_stop and abs(stop - struct_stop) < abs(stop - atr_stop):
        return "STRUCTURAL"
    if struct_stop and atr_stop:
        return "HYBRID"
    return "ATR"


def _invalid(reason):
    return {
        "valid": False, "trade_allowed": False, "reason": reason,
        "entry": 0, "stop": 0, "tp1": 0, "tp2": 0,
        "stop_pct": 0, "tp1_pct": 0, "rr": 0, "atr": 0,
        "trailing_trigger": 0, "stop_type": "NONE",
        "invalidate": "", "reentry": "",
    }


def format_risk_message(risk: dict, direction: str) -> str:
    if not risk.get("valid"):
        return f"⚠️ 리스크 계산 불가: {risk.get('reason', '')}"
    if not risk.get("trade_allowed"):
        return (
            f"⛔ 리스크 기준 미달\n"
            f"  {risk.get('reason', '')}\n"
            f"  손익비: 1:{risk.get('rr', 0):.1f} (기준: 1:{MIN_RR})"
        )
    dir_emoji = "🚀" if direction == "LONG" else "💥"
    return (
        f"{dir_emoji} 진입가:  {risk['entry']:>12,.2f}\n"
        f"🛑 손절가: {risk['stop']:>12,.2f}  (-{risk['stop_pct']:.1f}%)\n"
        f"🎯 1차익절: {risk['tp1']:>11,.2f}  (+{risk['tp1_pct']:.1f}%)\n"
        f"🎯 2차익절: {risk['tp2']:>11,.2f}\n"
        f"📐 손익비:  1:{risk['rr']:.1f}\n"
        f"🔄 트레일: {risk['trailing_trigger']:>12,.2f}\n"
        f"❌ 무효화: {risk['invalidate']}"
    )
