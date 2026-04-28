"""
scenario_engine.py
시나리오 엔진 (Scenario Engine)

단순 LONG/SHORT 점수 → 조건 기반 시나리오로 전환

출력:
  primary   - 1순위 시나리오 (진입 조건 + 목표)
  secondary - 2순위 시나리오 (반대 방향 조건)
  wait      - 대기 조건
  invalid   - 무효화 조건 (손절)
  trigger   - 실제 진입 트리거
"""

from tradebot.analysis.core import (
    get_close, get_high, get_low, avg, safe_float, calc_ema,
)


def _safe(v, d=0.0):
    try:
        return float(v) if v is not None else d
    except Exception:
        return d


def _fmt(v):
    v = _safe(v)
    if abs(v) >= 1000:
        return f"{v:,.2f}"
    if abs(v) >= 10:
        return f"{v:.3f}"
    return f"{v:.4f}"


def _find_next_resistance(candles_1h, current_price, lookback=50):
    """현재가 위의 다음 저항선 탐색"""
    if not candles_1h or len(candles_1h) < 10:
        return current_price * 1.02
    highs = sorted(
        [get_high(c) for c in candles_1h[-lookback:] if get_high(c) > current_price],
    )
    if not highs:
        return current_price * 1.02
    # 현재가 0.5% 이상 위의 첫 번째 고점
    for h in highs:
        if h >= current_price * 1.005:
            return h
    return highs[0] if highs else current_price * 1.02


def _find_next_support(candles_1h, current_price, lookback=50):
    """현재가 아래의 다음 지지선 탐색"""
    if not candles_1h or len(candles_1h) < 10:
        return current_price * 0.98
    lows = sorted(
        [get_low(c) for c in candles_1h[-lookback:] if get_low(c) < current_price],
        reverse=True,
    )
    if not lows:
        return current_price * 0.98
    for l in lows:
        if l <= current_price * 0.995:
            return l
    return lows[0] if lows else current_price * 0.98


def build_scenarios(
    sig: dict,
    risk: dict,
    candles_by_tf: dict,
    market_state: dict,
) -> dict:
    """
    시나리오 생성 메인 함수

    반환:
    {
        "primary":   "1순위 시나리오 텍스트",
        "secondary": "2순위 시나리오 텍스트",
        "wait":      "대기 조건 텍스트",
        "invalid":   "무효화 조건 텍스트",
        "trigger_long":  "롱 진입 트리거",
        "trigger_short": "숏 진입 트리거",
        "summary":   "한줄 요약",
    }
    """
    direction  = str(sig.get("direction", "WAIT")).upper()
    price      = _safe(sig.get("current_price"))
    support    = _safe(sig.get("support",    0))
    resistance = _safe(sig.get("resistance", 0))
    is_range   = sig.get("is_range", False)
    range_pos  = sig.get("range_pos", "MIDDLE")
    bb_squeeze = sig.get("bb_squeeze", False)
    long_score = _safe(sig.get("long_score",  0))
    short_score= _safe(sig.get("short_score", 0))
    score_gap  = _safe(sig.get("score_gap",   0))
    trend_1h   = sig.get("trend_1h",  "SIDEWAYS")
    trend_4h   = sig.get("trend_4h",  "SIDEWAYS")
    state      = market_state.get("state", "RANGE")

    c1h = candles_by_tf.get("1h", [])

    next_res = _find_next_resistance(c1h, price)
    next_sup = _find_next_support(c1h, price)

    stop     = _safe(risk.get("stop"))    if risk and risk.get("valid") else 0
    tp1      = _safe(risk.get("tp1"))     if risk and risk.get("valid") else 0
    tp2      = _safe(risk.get("tp2"))     if risk and risk.get("valid") else 0
    rr       = _safe(risk.get("rr"))      if risk and risk.get("valid") else 0
    trail    = _safe(risk.get("trailing_trigger")) if risk and risk.get("valid") else 0

    # ── 박스장 시나리오 ────────────────────────────
    if state == "RANGE" or is_range:
        return _range_scenario(price, support, resistance, range_pos, next_res, next_sup)

    # ── 변동성 수축 시나리오 ───────────────────────
    if state == "SQUEEZE" or bb_squeeze:
        return _squeeze_scenario(price, support, resistance, long_score, short_score)

    # ── LONG 시나리오 ─────────────────────────────
    if direction == "LONG":
        primary = (
            f"1순위: {_fmt(resistance)} 돌파 + 거래량 증가 확인 후 롱\n"
            f"   → 목표1: {_fmt(tp1)}  목표2: {_fmt(tp2)}  손익비: 1:{rr:.1f}"
        )
        secondary = (
            f"2순위: {_fmt(support)} 이탈 시 숏 전환 검토\n"
            f"   → 이탈 후 {_fmt(next_sup)} 목표"
        )
        wait = (
            f"대기: {_fmt(resistance)} 돌파 확정 전 / "
            f"거래량 동반 없는 상승 중 / "
            f"박스 중앙 구간"
        )
        invalid = (
            f"무효화: 15M 종가 {_fmt(stop)} 하향 이탈 → 즉시 청산\n"
            f"트레일: {_fmt(trail)} 도달 후 손절 상향 조정"
        )
        trigger_long = (
            f"15M 종가 {_fmt(resistance)} 상향 돌파 + 거래량 평균 1.5배 이상"
        )
        trigger_short = f"15M 종가 {_fmt(support)} 하향 이탈"
        summary = (
            f"LONG 우세 ({long_score:.0f}% vs {short_score:.0f}%) — "
            f"{_fmt(resistance)} 돌파 확인 후 진입"
        )

    # ── SHORT 시나리오 ────────────────────────────
    elif direction == "SHORT":
        primary = (
            f"1순위: {_fmt(support)} 이탈 + 거래량 증가 확인 후 숏\n"
            f"   → 목표1: {_fmt(tp1)}  목표2: {_fmt(tp2)}  손익비: 1:{rr:.1f}"
        )
        secondary = (
            f"2순위: {_fmt(resistance)} 돌파 시 롱 전환 검토\n"
            f"   → 돌파 후 {_fmt(next_res)} 목표"
        )
        wait = (
            f"대기: {_fmt(support)} 이탈 확정 전 / "
            f"거래량 동반 없는 하락 중 / "
            f"박스 중앙 구간"
        )
        invalid = (
            f"무효화: 15M 종가 {_fmt(stop)} 상향 돌파 → 즉시 청산\n"
            f"트레일: {_fmt(trail)} 도달 후 손절 하향 조정"
        )
        trigger_long  = f"15M 종가 {_fmt(resistance)} 상향 돌파"
        trigger_short = (
            f"15M 종가 {_fmt(support)} 하향 이탈 + 거래량 평균 1.5배 이상"
        )
        summary = (
            f"SHORT 우세 ({short_score:.0f}% vs {long_score:.0f}%) — "
            f"{_fmt(support)} 이탈 확인 후 진입"
        )

    # ── WAIT 시나리오 ─────────────────────────────
    else:
        return _wait_scenario(price, support, resistance, next_res, next_sup, score_gap)

    return {
        "primary":       primary,
        "secondary":     secondary,
        "wait":          wait,
        "invalid":       invalid,
        "trigger_long":  trigger_long,
        "trigger_short": trigger_short,
        "summary":       summary,
    }


def _range_scenario(price, support, resistance, range_pos, next_res, next_sup):
    mid = (support + resistance) / 2 if support and resistance else price
    return {
        "primary":  (
            f"1순위: 박스 상단 {_fmt(resistance)} 돌파 시 롱\n"
            f"   → 목표: {_fmt(next_res)}"
        ),
        "secondary": (
            f"2순위: 박스 하단 {_fmt(support)} 이탈 시 숏\n"
            f"   → 목표: {_fmt(next_sup)}"
        ),
        "wait":    f"현재 박스 {_fmt(support)}~{_fmt(resistance)} 내 대기 ({range_pos})",
        "invalid": f"박스 내 중간({_fmt(mid)}) 진입 금지 — 양방향 노이즈",
        "trigger_long":  f"15M 종가 {_fmt(resistance)} 돌파 + 거래량 증가",
        "trigger_short": f"15M 종가 {_fmt(support)} 이탈 + 거래량 증가",
        "summary": f"박스장 대기 ({_fmt(support)}~{_fmt(resistance)})",
    }


def _squeeze_scenario(price, support, resistance, long_score, short_score):
    likely = "롱" if long_score >= short_score else "숏"
    return {
        "primary":  f"1순위: 변동성 수축 후 {likely} 방향 폭발 예상",
        "secondary": "2순위: 반대 방향 확인 시 즉시 대응",
        "wait":    "현재 방향 미확정 — 봉 마감 후 방향 확인",
        "invalid": "수축 구간 내 섣부른 진입 금지",
        "trigger_long":  f"15M 종가 {_fmt(resistance)} 돌파 + 급격한 거래량 증가",
        "trigger_short": f"15M 종가 {_fmt(support)} 이탈 + 급격한 거래량 증가",
        "summary": "변동성 수축 — 큰 움직임 임박, 방향 확인 대기",
    }


def _wait_scenario(price, support, resistance, next_res, next_sup, score_gap):
    return {
        "primary":  f"1순위: 방향 확정 후 진입 검토 (현재 갭 {score_gap:.0f}%p)",
        "secondary": "2순위: 상/하단 돌파 이탈 확인 후 방향 결정",
        "wait":    f"대기: {_fmt(support)}~{_fmt(resistance)} 내 관망",
        "invalid": "방향 불명확 — 진입 금지",
        "trigger_long":  f"15M 종가 {_fmt(resistance)} 돌파 + 거래량",
        "trigger_short": f"15M 종가 {_fmt(support)} 이탈 + 거래량",
        "summary": f"방향 미확정 (갭 {score_gap:.0f}%p) — WAIT",
    }


def format_scenario_message(scenario: dict) -> str:
    """시나리오 텔레그램 메시지 포맷"""
    return (
        f"📋 시나리오\n"
        f"{'─'*28}\n"
        f"🥇 {scenario.get('primary', '-')}\n\n"
        f"🥈 {scenario.get('secondary', '-')}\n\n"
        f"⏳ 대기: {scenario.get('wait', '-')}\n\n"
        f"❌ 무효화: {scenario.get('invalid', '-')}\n\n"
        f"🚨 트리거\n"
        f"  롱: {scenario.get('trigger_long', '-')}\n"
        f"  숏: {scenario.get('trigger_short', '-')}"
    )
