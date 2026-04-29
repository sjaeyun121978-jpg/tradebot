"""
entry_filter.py v3
진입 금지 엔진 (Kill Switch Engine)

핵심 변경 (v3):
  거래량 부족 → warnings(감점)으로 이동, 차단 아님
  신뢰도/점수갭 → 완전 부족(soft 기준)일 때만 차단
  direction → 후보 방향 보존 (blocked여도 WAIT 덮어쓰기 금지)
  candidate_direction → 항상 원래 방향 반환
"""

from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

_last_signal_time      = {}
_last_signal_direction = {}

MIN_SCORE_GAP   = 20
MIN_CONFIDENCE  = 65
SOFT_SCORE_GAP  = 12
SOFT_CONFIDENCE = 55
SOFT_VOL_RATIO  = 0.60
EMA200_ZONE_PCT = 0.008
KEY_LEVEL_PCT   = 0.003


def _safe(v, d=0.0):
    try:
        return float(v) if v is not None else d
    except Exception:
        return d


def _get(d, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] is not None:
            return d[k]
    return default


def check_entry(
    symbol:      str,
    direction:   str,
    sig:         dict,
    market_state: dict,
    all_signals: dict = None,
) -> dict:
    """
    진입 가능 여부 판단.

    반환:
    {
        "trade_allowed":      True/False,
        "blocked":            True/False,
        "block_reasons":      [...],   # 강한 차단 사유
        "warnings":           [...],   # 감점/주의 사유 (차단 아님)
        "block_reason":       "대표 사유",
        "direction":          "LONG/SHORT/WAIT",  # 후보 방향 보존
        "candidate_direction": "LONG/SHORT/WAIT",
    }
    """
    reasons  = []
    warnings = []
    direction = (direction or "WAIT").upper()

    if direction == "WAIT":
        return _decision(True, ["방향 미확정"], direction, warnings)

    # ── 0. 추세 구조 기반 후보 방향 파악 ────────────────
    trend_15m = _get(sig, "trend_15m", default="SIDEWAYS")
    trend_1h  = _get(sig, "trend_1h",  default="SIDEWAYS")
    trend_4h  = _get(sig, "trend_4h",  default="SIDEWAYS")

    trend_aligned = False
    if direction == "LONG":
        trend_aligned = trend_15m == "UP" or trend_1h == "UP"
    elif direction == "SHORT":
        trend_aligned = trend_15m == "DOWN" or trend_1h == "DOWN"

    # ── 1. 시장상태 차단 ─────────────────────────────
    state = market_state.get("state", "NO_DATA") if market_state else "NO_DATA"
    if state in ("CHAOS", "NO_DATA"):
        reasons.append(f"시장상태 {state} — {(market_state or {}).get('reason', '')}")
    elif state == "RANGE":
        warnings.append(f"박스장 — {(market_state or {}).get('reason', '')}")
    elif state == "SQUEEZE":
        warnings.append("변동성 수축 — 방향 확정 대기")

    # ── 2. BTC/ETH 동시 과잉 신호 제어 ──────────────
    if all_signals:
        now_ts = datetime.now(KST).timestamp()
        for other_sym, other_sig in all_signals.items():
            if other_sym == symbol:
                continue
            other_dir  = _get(other_sig, "direction", default="WAIT")
            other_time = _last_signal_time.get(other_sym, 0)
            if str(other_dir).upper() == direction and now_ts - other_time < 1800:
                my_conf    = _safe(_get(sig, "confidence", default=0))
                other_conf = _safe(_get(other_sig, "confidence", default=0))
                if my_conf <= other_conf:
                    reasons.append(
                        f"동시 신호 제어: {other_sym} 더 강함 "
                        f"({other_conf:.0f}% > {my_conf:.0f}%)"
                    )

    # ── 3. 1H/4H 방향 충돌 (강한 차단) ──────────────
    if direction == "LONG":
        if trend_4h == "DOWN":
            reasons.append("4H 하락 추세 역행 롱")
        if trend_1h == "DOWN" and trend_4h == "DOWN":
            reasons.append("1H+4H 동시 하락 — 롱 금지")
    if direction == "SHORT":
        if trend_4h == "UP":
            reasons.append("4H 상승 추세 역행 숏")
        if trend_1h == "UP" and trend_4h == "UP":
            reasons.append("1H+4H 동시 상승 — 숏 금지")

    # ── 4. 점수 갭/신뢰도 (소프트 기준으로 완화) ──────
    score_gap  = _safe(_get(sig, "score_gap",  default=0))
    confidence = _safe(_get(sig, "confidence", default=0))

    if score_gap < SOFT_SCORE_GAP:
        reasons.append(f"점수 갭 매우 부족 ({score_gap:.0f} < {SOFT_SCORE_GAP})")
    elif score_gap < MIN_SCORE_GAP:
        warnings.append(f"점수 갭 주의 ({score_gap:.0f} < {MIN_SCORE_GAP})")

    if confidence < SOFT_CONFIDENCE:
        reasons.append(f"조건 상태 부족 ({confidence:.0f}% < {SOFT_CONFIDENCE}%)")
    elif confidence < MIN_CONFIDENCE:
        warnings.append(f"조건 상태 주의 ({confidence:.0f}% < {MIN_CONFIDENCE}%)")

    # ── 5. 거래량 — 감점/주의만, 차단 아님 ────────────
    volume    = _safe(_get(sig, "volume",     default=0))
    avg_vol   = _safe(_get(sig, "avg_volume", default=0))
    vol_ratio = volume / avg_vol if avg_vol > 0 else 0

    if vol_ratio < SOFT_VOL_RATIO:
        warnings.append(f"거래량 부족 ({vol_ratio:.1f}배 < {SOFT_VOL_RATIO}배)")
    elif vol_ratio < 0.8:
        warnings.append(f"거래량 약함 ({vol_ratio:.1f}배 < 0.8배)")

    # ── 6. 박스 중앙 ────────────────────────────────
    is_range  = _get(sig, "is_range",  default=False)
    range_pos = _get(sig, "range_pos", default=None)
    if is_range and range_pos == "MIDDLE":
        reasons.append("박스 중앙 — 양방향 노이즈 구간")

    # ── 7. RSI 극단 추격 ─────────────────────────────
    rsi = _safe(_get(sig, "rsi", default=50))
    if direction == "LONG"  and rsi > 75:
        reasons.append(f"RSI 과매수 추격 금지 ({rsi:.1f})")
    if direction == "LONG"  and rsi < 30:
        reasons.append(f"RSI 과매도 반등 미확인 ({rsi:.1f})")
    if direction == "SHORT" and rsi < 25:
        reasons.append(f"RSI 과매도 추격 금지 ({rsi:.1f})")
    if direction == "SHORT" and rsi > 70:
        reasons.append(f"RSI 과매수 하락 미확인 ({rsi:.1f})")

    # ── 8. EMA200 근처 ───────────────────────────────
    price  = _safe(_get(sig, "current_price", default=0))
    ema200 = _safe(_get(sig, "ema200",        default=0))
    if price > 0 and ema200 > 0:
        dist = abs(price - ema200) / ema200
        if dist < EMA200_ZONE_PCT:
            reasons.append(f"EMA200 근접 ({dist*100:.2f}%) — 돌파/이탈 확인 전 금지")

    # ── 9. 직전 고점/저점 바로 앞 ────────────────────
    resistance = _safe(_get(sig, "resistance", default=0))
    support    = _safe(_get(sig, "support",    default=0))
    if direction == "LONG" and resistance > 0 and price > 0:
        dist_res = (resistance - price) / price
        if 0 < dist_res < KEY_LEVEL_PCT:
            reasons.append(f"저항 {resistance:,.2f} 바로 앞 — 돌파 확인 후 진입")
    if direction == "SHORT" and support > 0 and price > 0:
        dist_sup = (price - support) / price
        if 0 < dist_sup < KEY_LEVEL_PCT:
            reasons.append(f"지지 {support:,.2f} 바로 앞 — 이탈 확인 후 진입")

    # ── 10. 오더북/CVD 역방향 강세 ───────────────────
    ob = sig.get("orderbook", {})
    if ob.get("usable"):
        pressure  = ob.get("pressure", "NEUTRAL")
        imbalance = _safe(ob.get("imbalance", 1.0))
        if direction == "LONG"  and pressure == "SELL" and imbalance <= 0.65:
            reasons.append(f"오더북 강한 매도 우세 ({imbalance:.2f})")
        if direction == "SHORT" and pressure == "BUY"  and imbalance >= 1.55:
            reasons.append(f"오더북 강한 매수 우세 ({imbalance:.2f})")

    trades = sig.get("trades", {})
    if trades.get("usable"):
        cvd_signal = trades.get("cvd_signal", "NEUTRAL")
        buy_ratio  = _safe(trades.get("buy_ratio", 50))
        if direction == "LONG"  and cvd_signal == "BEARISH" and buy_ratio <= 35:
            reasons.append(f"CVD 강한 매도 ({buy_ratio:.0f}%) — 롱 역방향")
        if direction == "SHORT" and cvd_signal == "BULLISH" and buy_ratio >= 65:
            reasons.append(f"CVD 강한 매수 ({buy_ratio:.0f}%) — 숏 역방향")

    # 추세 정렬 시 soft warning은 차단하지 않는다
    # reasons에 들어간 강한 역방향/시장위험만 차단
    blocked = len(reasons) > 0

    if not blocked:
        _last_signal_time[symbol]      = datetime.now(KST).timestamp()
        _last_signal_direction[symbol] = direction

    return _decision(blocked, reasons, direction, warnings)


def _decision(blocked: bool, reasons: list, direction: str, warnings: list = None) -> dict:
    warnings = warnings or []
    return {
        "trade_allowed":       not blocked,
        "blocked":             blocked,
        "block_reasons":       reasons,
        "warnings":            warnings,
        "block_reason":        reasons[0] if reasons else "",
        "direction":           direction,          # 후보 방향 보존 (WAIT 덮어쓰기 금지)
        "candidate_direction": direction,
    }


# 하위 호환
def should_block_entry(symbol, direction, sig, market_state, all_signals=None):
    """기존 (blocked, reasons) 튜플 반환 형식 유지"""
    result = check_entry(symbol, direction, sig, market_state, all_signals)
    return result["blocked"], result["block_reasons"]
