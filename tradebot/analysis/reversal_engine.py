"""
reversal_engine.py v1
변곡점 포착 엔진

오더북 / CVD / OI / 펀딩비 / 청산 + 가격 구조를 종합하여
WATCH / PRE / REAL 단계의 변곡 신호를 생성한다.

기존 calc_scores()는 유지하고, 이 엔진은 독립 실행 후
decision payload에 병합된다.
"""

from __future__ import annotations


def _num(v, default=0.0):
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def _get(d, key, default=None):
    if isinstance(d, dict):
        return d.get(key, default)
    try:
        return getattr(d, key, default)
    except Exception:
        return default


def _wall_qty(wall):
    """bid_wall / ask_wall이 dict{"qty":...} 또는 숫자 모두 처리"""
    if isinstance(wall, dict):
        return _num(wall.get("qty", wall.get("quantity", 0)))
    return _num(wall, 0)


def analyze_reversal(sig: dict, market: dict | None = None) -> dict:
    """
    변곡점 포착 엔진

    반환:
    {
        "reversal_direction":    "LONG" | "SHORT" | "NONE",
        "reversal_stage":        "NONE" | "WATCH" | "PRE" | "REAL",
        "reversal_score":        int,
        "reversal_gap":          int,
        "reversal_long_score":   int,
        "reversal_short_score":  int,
        "reversal_reasons":      list[str],
        "reversal_warnings":     list[str],
        "reversal_invalid":      str,
        "reversal_block":        bool,
    }
    """
    sig    = sig    or {}
    market = market or {}

    reasons  = []
    warnings = []
    long_score  = 0
    short_score = 0

    # ── 1. 가격 구조 ───────────────────────────────────────
    trend_15m = str(_get(sig, "trend_15m", "SIDEWAYS") or "SIDEWAYS").upper()
    trend_1h  = str(_get(sig, "trend_1h",  "SIDEWAYS") or "SIDEWAYS").upper()
    trend_4h  = str(_get(sig, "trend_4h",  "SIDEWAYS") or "SIDEWAYS").upper()

    current_price = _num(_get(sig, "current_price", 0))
    ema20         = _num(_get(sig, "ema20",  0))
    ema50         = _num(_get(sig, "ema50",  0))
    macd_hist     = _num(_get(sig, "macd_hist", _get(sig, "macd_histogram", 0)))
    rsi           = _num(_get(sig, "rsi", 50))
    volume_ratio  = _num(_get(sig, "volume_ratio",
                          _get(sig, "vol_ratio", _get(sig, "volume_ratio_15m", 1.0))))

    if trend_15m == "UP":
        long_score  += 12
        reasons.append("15분 상승 구조")
    elif trend_15m == "DOWN":
        short_score += 12
        reasons.append("15분 하락 구조")

    if trend_1h == "UP":
        long_score  += 10
        reasons.append("1시간 상승 구조")
    elif trend_1h == "DOWN":
        short_score += 10
        reasons.append("1시간 하락 구조")

    if current_price > 0 and ema20 > 0:
        if current_price > ema20:
            long_score  += 8
            reasons.append("현재가 EMA20 상방")
        else:
            short_score += 8
            reasons.append("현재가 EMA20 하방")

    if ema20 > 0 and ema50 > 0:
        if ema20 > ema50:
            long_score  += 8
            reasons.append("EMA20 > EMA50")
        else:
            short_score += 8
            reasons.append("EMA20 < EMA50")

    if macd_hist > 0:
        long_score  += 8
        reasons.append("MACD 양전환")
    elif macd_hist < 0:
        short_score += 8
        reasons.append("MACD 음전환")

    if 45 <= rsi <= 65 and trend_15m == "UP":
        long_score  += 6
        reasons.append("RSI 상승 여지")
    elif 35 <= rsi <= 55 and trend_15m == "DOWN":
        short_score += 6
        reasons.append("RSI 하락 여지")

    if volume_ratio >= 1.2:
        if trend_15m == "UP":
            long_score  += 8
            reasons.append("상승 거래량 동반")
        elif trend_15m == "DOWN":
            short_score += 8
            reasons.append("하락 거래량 동반")
    elif volume_ratio < 0.6:
        warnings.append("저거래량 — 변곡 신뢰 낮음")

    # ── 2. 오더북 ─────────────────────────────────────────
    ob = (market.get("orderbook") or market.get("order_book")
          or market.get("orderBook") or {})

    bid_wall_raw = _get(ob, "bid_wall_strength", _get(ob, "bid_wall", 0))
    ask_wall_raw = _get(ob, "ask_wall_strength", _get(ob, "ask_wall", 0))
    bid_wall  = _wall_qty(bid_wall_raw)
    ask_wall  = _wall_qty(ask_wall_raw)
    imbalance = _num(_get(ob, "imbalance", 0))

    # 양쪽 값이 모두 있을 때만 비교 (한쪽 0이면 데이터 없음으로 처리)
    if bid_wall > 0 and ask_wall > 0:
        if bid_wall >= ask_wall * 1.25:
            long_score  += 12
            reasons.append("매수벽 우세")
        elif ask_wall >= bid_wall * 1.25:
            short_score += 12
            reasons.append("매도벽 우세")

    # imbalance: Bybit 기준 1.0=중립, >1=매수강세, <1=매도강세
    # 0이면 데이터 없음으로 간주하여 점수 부여 금지
    if imbalance >= 1.25:
        long_score  += 8
        reasons.append("오더북 매수 불균형")
    elif 0 < imbalance <= 0.80:
        short_score += 8
        reasons.append("오더북 매도 불균형")

    # ── 3. CVD ────────────────────────────────────────────
    cvd = market.get("cvd") or market.get("trades") or {}
    cvd_delta = _num(_get(cvd, "delta",
                    _get(cvd, "cvd_delta",
                    _get(cvd, "cvd",     0))))
    cvd_slope = _num(_get(cvd, "slope",
                    _get(cvd, "cvd_slope",
                    _get(cvd, "cvd_change", 0))))

    if cvd_delta > 0 and cvd_slope > 0:
        long_score  += 14
        reasons.append("CVD 매수 전환")
    elif cvd_delta < 0 and cvd_slope < 0:
        short_score += 14
        reasons.append("CVD 매도 전환")
    elif cvd_delta > 0:
        long_score  += 6
    elif cvd_delta < 0:
        short_score += 6

    # ── 4. OI ─────────────────────────────────────────────
    oi = market.get("open_interest") or market.get("oi") or {}
    oi_change = _num(_get(oi, "change_pct",
                    _get(oi, "oi_change_pct",
                    _get(oi, "oi_1h_change", 0))))

    if oi_change >= 1.0:
        if long_score >= short_score:
            long_score  += 10
            reasons.append("OI 증가 + 롱 우세")
        else:
            short_score += 10
            reasons.append("OI 증가 + 숏 우세")
    elif oi_change <= -1.0:
        warnings.append("OI 감소 — 추세 신뢰 약화")

    # ── 5. 펀딩비 ─────────────────────────────────────────
    funding = (market.get("funding") or market.get("funding_rate") or {})
    funding_rate = _num(_get(funding, "rate",
                       _get(funding, "funding_rate",
                       _get(funding, "fundingRate", 0))))

    # funding_rate는 % 단위 (예: 0.01 = 0.01%)
    # -0.03% 이하: 숏 과밀 → 롱 반전 가능  |  +0.03% 이상: 롱 과밀 → 숏 반전 가능
    if funding_rate <= -0.03:
        long_score  += 8
        reasons.append("펀딩비 음수 과열 — 숏 과밀")
    elif funding_rate >= 0.03:
        short_score += 8
        reasons.append("펀딩비 양수 과열 — 롱 과밀")

    # ── 6. 청산 ───────────────────────────────────────────
    liq = market.get("liquidations") or {}
    long_liq  = _num(_get(liq, "long_liq_usd",  _get(liq, "long",  0)))
    short_liq = _num(_get(liq, "short_liq_usd", _get(liq, "short", 0)))

    if short_liq > 0 and short_liq > long_liq * 1.5:
        long_score  += 10
        reasons.append("숏 청산 우세")
    elif long_liq > 0 and long_liq > short_liq * 1.5:
        short_score += 10
        reasons.append("롱 청산 우세")

    # ── 7. 방향 및 단계 판정 ─────────────────────────────
    gap = abs(long_score - short_score)

    if long_score >= short_score:
        direction      = "LONG"
        score          = int(long_score)
        opposite_score = int(short_score)
    else:
        direction      = "SHORT"
        score          = int(short_score)
        opposite_score = int(long_score)

    # ── EARLY ENTRY 포함 5단계 판정 ───────────────────
    early_confirm = 0  # 항상 초기화
    if score < 40 or gap < 8:
        direction = "NONE"
        stage     = "NONE"
    elif score >= 80 and gap >= 22:
        stage = "REAL"
    elif score >= 68 and gap >= 16:
        stage = "PRE"
    elif score >= 55 and gap >= 12:
        stage = "EARLY"   # 변곡 초입 진입 구간
    else:
        stage = "WATCH"

    # ── EARLY 최소 확인 조건 (가짜 반등 필터) ────────
    early_confirm = 0

    # 구조 전환
    if trend_15m in ("UP", "DOWN"):
        early_confirm += 1

    # EMA 방향 일치
    if current_price > 0 and ema20 > 0:
        if current_price > ema20 and trend_15m == "UP":
            early_confirm += 1
        elif current_price < ema20 and trend_15m == "DOWN":
            early_confirm += 1

    # CVD 전환 (핵심 필터)
    if cvd_delta > 0 and trend_15m == "UP":
        early_confirm += 1
    elif cvd_delta < 0 and trend_15m == "DOWN":
        early_confirm += 1

    # 오더북 보조 (방향 일치 여부 확인)
    # imbalance 기준: 1.0=중립, >=1.25=매수우세, <=0.80=매도우세
    # abs(imbalance) > 0.10은 imbalance=1.0(기본값)도 항상 통과하므로 방향 일치 조건으로 변경
    if direction == "LONG" and imbalance >= 1.25:
        early_confirm += 1
    elif direction == "SHORT" and 0 < imbalance <= 0.80:
        early_confirm += 1

    # EARLY 최소 3개 조건 미충족 → WATCH로 강등
    if stage == "EARLY" and early_confirm < 3:
        stage = "WATCH"
        warnings.append(f"EARLY 조건 미충족 ({early_confirm}/3) — WATCH 유지")

    # ── 8. 무효화 조건 ────────────────────────────────────
    reversal_block = False
    invalid        = ""

    if direction == "LONG":
        if trend_4h == "DOWN":
            warnings.append("4H 하락 추세 내 15M 롱 변곡 — EARLY/PRE까지만 허용")
            invalid = "직전 저점 이탈 또는 CVD 재음전환"
            # REAL 기준이 score >= 80이므로, 4H 역추세에서는 score >= 90만 허용
            if stage == "REAL" and score < 90:
                reversal_block = True
                stage = "PRE"
                invalid = "4H 하락 추세 유지 시 REAL LONG 제한 — PRE까지만 허용"
        else:
            invalid = "직전 저점 이탈 또는 CVD 재음전환"
    elif direction == "SHORT":
        if trend_4h == "UP":
            warnings.append("4H 상승 추세 내 15M 숏 변곡 — EARLY/PRE까지만 허용")
            invalid = "직전 고점 돌파 또는 CVD 재양전환"
            # REAL 기준이 score >= 80이므로, 4H 역추세에서는 score >= 90만 허용
            if stage == "REAL" and score < 90:
                reversal_block = True
                stage = "PRE"
                invalid = "4H 상승 추세 유지 시 REAL SHORT 제한 — PRE까지만 허용"
        else:
            invalid = "직전 고점 돌파 또는 CVD 재양전환"
    else:
        invalid = "방향 신호 없음"

    return {
        "reversal_direction":   direction,
        "reversal_stage":       stage,
        "reversal_score":       score,
        "reversal_gap":         gap,
        "reversal_long_score":  int(long_score),
        "reversal_short_score": int(short_score),
        "reversal_reasons":     reasons[:8],
        "reversal_warnings":    warnings[:5],
        "reversal_invalid":     invalid,
        "reversal_block":       reversal_block,
        "reversal_early_confirm": early_confirm,
    }
