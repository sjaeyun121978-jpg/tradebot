"""
step_state_engine.py v1
────────────────────────────────────────────────────────────
STEP / HOLD / WARNING / EXIT 통합 판단 엔진

외부 공개 함수: decide_step_state() 하나만 사용한다.
기존 signal.py / entry.py 의 hard filter 로직은 건드리지 않는다.
이 엔진은 그 결과를 덮어쓰는 방식으로 연결된다.

점수 기준:
  0~39   WAIT
  40~59  EARLY
  60~74  PRE
  75~100 REAL

GAP 기준:
  gap < 10  → 최대 EARLY
  gap < 20  → 최대 PRE
  gap >= 20 → REAL 가능
────────────────────────────────────────────────────────────
"""

from __future__ import annotations


# ─────────────────────────────────────────────────────────────
# 상수
# ─────────────────────────────────────────────────────────────

_STEP_WAIT  = "WAIT"
_STEP_EARLY = "EARLY"
_STEP_PRE   = "PRE"
_STEP_REAL  = "REAL"
_STEP_HOLD  = "HOLD"
_STEP_EXIT  = "EXIT"

_SCORE_EARLY = 40
_SCORE_PRE   = 60
_SCORE_REAL  = 75

_GAP_EARLY   = 10   # gap < 10  → 최대 EARLY
_GAP_PRE     = 20   # gap < 20  → 최대 PRE
# gap >= 20 → REAL 가능

# 점수 구성 최대치
_MAX_STRUCTURE  = 25
_MAX_WAVE       = 20
_MAX_FIBO       = 15
_MAX_INDICATOR  = 15
_MAX_VOL_CANDLE = 15
_MAX_RISK       = 10

# PRE/REAL 제한 임계
_STRUCT_MIN_PRE  = 10   # 구조 < 10 → PRE 금지
_STRUCT_MIN_REAL = 15   # 구조 < 15 → REAL 금지
_RISK_MIN_PRE    = 2    # 리스크 < 2 → PRE 금지
_RISK_MIN_REAL   = 4    # 리스크 < 4 → REAL 금지

# ── REAL 품질 게이트 강화 상수 (v2) ──────────────────────────
_REAL_TRAP_MAX       = 35   # trap_risk >= 35 → REAL 금지
_REAL_DIR_SCORE_MIN  = 60   # LONG: accum < 60 / SHORT: dist < 60 → REAL 금지
_REAL_WARNING_MAX    = 2    # warning > 2 → REAL 금지 (3개 이상)
_REAL_VOL_MIN        = 1.1  # vol_ratio < 1.1 → REAL 금지
_REAL_STRONG_GAP     = 25   # gap < 25 → REAL 금지

# ── REAL_2 (고확률 후보) 기준 ─────────────────────────────────
_REAL2_TRAP_MAX      = 30   # trap_risk < 30
_REAL2_DIR_SCORE_MIN = 70   # direction score >= 70
_REAL2_WARNING_MAX   = 1    # warning <= 1개


# ─────────────────────────────────────────────────────────────
# safe getter — 여러 후보 키를 순서대로 탐색
# ─────────────────────────────────────────────────────────────

def _get(data: dict, *keys, default=None):
    """여러 후보 키를 순서대로 탐색. 없으면 default 반환."""
    if not isinstance(data, dict):
        return default
    for k in keys:
        v = data.get(k)
        if v is not None:
            return v
    return default


def _num(data: dict, *keys, default=0.0) -> float:
    """숫자형 safe getter."""
    v = _get(data, *keys, default=default)
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _str(data: dict, *keys, default: str = "") -> str:
    v = _get(data, *keys, default=default)
    return str(v) if v is not None else default


def _bool(data: dict, *keys, default: bool = False) -> bool:
    v = _get(data, *keys, default=default)
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.lower() in ("true", "1", "yes")
    return default


# ─────────────────────────────────────────────────────────────
# 내부 점수 계산 함수들
# ─────────────────────────────────────────────────────────────

def _calculate_structure_score(data: dict, direction: str) -> tuple[float, list, list]:
    """
    구조 점수 (최대 25점)
    추세 정렬, HH/HL/LH/LL 구조, EMA 위치, 지지/저항 관계
    반환: (점수, 가점 사유, 감점 사유)
    """
    score   = 0.0
    gains   = []
    missing = []

    trend_15m = _str(data, "trend_15m", "tf_15m",  default="SIDEWAYS").upper()
    trend_1h  = _str(data, "trend_1h",  "tf_1h",   default="SIDEWAYS").upper()
    trend_4h  = _str(data, "trend_4h",  "tf_4h", "higher_tf", "htf_trend", default="SIDEWAYS").upper()

    price      = _num(data, "current_price", "price", "close")
    ema20      = _num(data, "ema20", "ema_20", "ma20")
    ema50      = _num(data, "ema50", "ema_50", "ma50")
    support    = _num(data, "support",    default=0)
    resistance = _num(data, "resistance", default=0)

    if direction == "LONG":
        # 15M 상승 추세
        if trend_15m == "UP":
            score += 7; gains.append("15M 상승 추세")
        elif trend_15m == "SIDEWAYS":
            score += 3; gains.append("15M 횡보(중립)")
        # 1H 방향 우호
        if trend_1h == "UP":
            score += 6; gains.append("1H 상승 추세")
        elif trend_1h == "SIDEWAYS":
            score += 2
        # 4H 방향 우호
        if trend_4h == "UP":
            score += 6; gains.append("4H 상승 추세")
        elif trend_4h == "DOWN":
            score -= 4; gains.append("⚠ 4H 하락 역행")
        # EMA 위치
        if ema20 > 0 and price > ema20:
            score += 3; gains.append("EMA20 상단")
        if ema50 > 0 and price > ema50:
            score += 3; gains.append("EMA50 상단")
        # 지지 근접
        if support > 0 and price > 0:
            dist = (price - support) / price
            if 0 < dist < 0.015:
                score += 3; gains.append("지지선 근접")

    elif direction == "SHORT":
        if trend_15m == "DOWN":
            score += 7; gains.append("15M 하락 추세")
        elif trend_15m == "SIDEWAYS":
            score += 3
        if trend_1h == "DOWN":
            score += 6; gains.append("1H 하락 추세")
        elif trend_1h == "SIDEWAYS":
            score += 2
        if trend_4h == "DOWN":
            score += 6; gains.append("4H 하락 추세")
        elif trend_4h == "UP":
            score -= 4; gains.append("⚠ 4H 상승 역행")
        if ema20 > 0 and price < ema20:
            score += 3; gains.append("EMA20 하단")
        if ema50 > 0 and price < ema50:
            score += 3; gains.append("EMA50 하단")
        if resistance > 0 and price > 0:
            dist = (resistance - price) / price
            if 0 < dist < 0.015:
                score += 3; gains.append("저항선 근접")
    else:
        missing.append("방향 미확정 — 구조 점수 0")

    return max(0.0, min(score, float(_MAX_STRUCTURE))), gains, missing


def _calculate_wave_score(data: dict, direction: str) -> tuple[float, list, list]:
    """파동 점수 (최대 20점) — HH/HL 유지, 추세선, 모멘텀"""
    score  = 0.0
    gains  = []
    misses = []

    macd_state  = _str(data, "macd_state", "macd", default="NEUTRAL").upper()
    macd_hist   = _num(data, "macd_hist", "histogram", "macd_histogram")
    divergence  = _str(data, "divergence", default="")
    bb_signal   = _str(data, "bb_signal",  default="NEUTRAL").upper()
    bb_squeeze  = _bool(data, "bb_squeeze", default=False)
    above_ema20 = _bool(data, "above_ema20", default=False)
    below_ema20 = _bool(data, "below_ema20", default=False)

    if direction == "LONG":
        if macd_state in ("BULLISH", "POSITIVE"):
            score += 8; gains.append("MACD 상방 전환")
        elif macd_hist > 0:
            score += 4; gains.append("MACD 양(+)")
        else:
            misses.append("MACD 하방")
        if divergence == "BULLISH_DIV":
            score += 6; gains.append("상승 다이버전스")
        if bb_squeeze:
            score += 3; gains.append("BB 수축 — 상승 임박")
        if bb_signal == "OVERSOLD":
            score += 3; gains.append("BB 하단 반등")
        if above_ema20:
            score += 3; gains.append("EMA20 상향 돌파")

    elif direction == "SHORT":
        if macd_state in ("BEARISH", "NEGATIVE"):
            score += 8; gains.append("MACD 하방 전환")
        elif macd_hist < 0:
            score += 4; gains.append("MACD 음(-)")
        else:
            misses.append("MACD 상방")
        if divergence == "BEARISH_DIV":
            score += 6; gains.append("하락 다이버전스")
        if bb_squeeze:
            score += 3; gains.append("BB 수축 — 하락 임박")
        if bb_signal == "OVERBOUGHT":
            score += 3; gains.append("BB 상단 저항")
        if below_ema20:
            score += 3; gains.append("EMA20 하향 이탈")
    else:
        misses.append("방향 없음 — 파동 0점")

    return max(0.0, min(score, float(_MAX_WAVE))), gains, misses


def _calculate_fibo_score(data: dict, direction: str) -> tuple[float, list, list]:
    """피보나치 점수 (최대 15점)"""
    score  = 0.0
    gains  = []
    misses = []

    fibo_level = _str(data, "fibo_level", "fib_level", "retracement", "fibo_zone", default="")
    fibo_float = _num(data, "fibo_level", "fib_level", "retracement", default=0.0)
    is_range   = _bool(data, "is_range",  default=False)
    range_pos  = _str(data, "range_pos",  default="").upper()

    # 피보 되돌림 구간 — 0.382~0.618 정상 구간
    if 0.35 <= fibo_float <= 0.65:
        score += 8; gains.append(f"피보 정상 되돌림 ({fibo_float:.3f})")
    elif 0.2 <= fibo_float < 0.35:
        score += 5; gains.append(f"피보 얕은 되돌림 ({fibo_float:.3f})")
    elif 0.65 < fibo_float <= 0.79:
        score += 5; gains.append(f"피보 깊은 되돌림 ({fibo_float:.3f})")
    elif fibo_level:
        score += 3; gains.append(f"피보 레벨 감지 ({fibo_level})")

    if direction == "LONG":
        if is_range and range_pos == "BOTTOM":
            score += 5; gains.append("박스 하단 지지")
        elif is_range and range_pos == "MIDDLE":
            score += 1
        elif is_range and range_pos == "TOP":
            misses.append("박스 상단 — 롱 불리")
    elif direction == "SHORT":
        if is_range and range_pos == "TOP":
            score += 5; gains.append("박스 상단 저항")
        elif is_range and range_pos == "MIDDLE":
            score += 1
        elif is_range and range_pos == "BOTTOM":
            misses.append("박스 하단 — 숏 불리")

    if not fibo_level and not is_range:
        misses.append("피보 레벨 데이터 없음")

    return max(0.0, min(score, float(_MAX_FIBO))), gains, misses


def _calculate_indicator_score(data: dict, direction: str) -> tuple[float, list, list]:
    """보조지표 점수 (최대 15점) — RSI, CCI, 스토캐스틱"""
    score  = 0.0
    gains  = []
    misses = []

    rsi = _num(data, "rsi", "rsi_14", "rsi14", default=50.0)
    cci = _num(data, "cci", default=0.0)

    if direction == "LONG":
        if 40 <= rsi <= 60:
            score += 8; gains.append(f"RSI 중립권 ({rsi:.1f})")
        elif 30 <= rsi < 40:
            score += 6; gains.append(f"RSI 과매도 회복 ({rsi:.1f})")
        elif 60 < rsi <= 70:
            score += 4; gains.append(f"RSI 상승세 ({rsi:.1f})")
        elif rsi > 70:
            score += 1; misses.append(f"RSI 과매수 ({rsi:.1f}) — 추격 위험")
        elif rsi < 30:
            score += 3; gains.append(f"RSI 극매도 반등 기대 ({rsi:.1f})")

        if cci > 0:
            score += 4; gains.append(f"CCI 양전환 ({cci:.0f})")
        elif -50 <= cci <= 0:
            score += 2
        else:
            misses.append(f"CCI 약세 ({cci:.0f})")

        # 스토캐스틱 대용 — RSI로 대체
        if rsi < 35:
            score += 3; gains.append("과매도 구간 반등 기대")

    elif direction == "SHORT":
        if 40 <= rsi <= 60:
            score += 8; gains.append(f"RSI 중립권 ({rsi:.1f})")
        elif 60 < rsi <= 70:
            score += 6; gains.append(f"RSI 과매수 회복 ({rsi:.1f})")
        elif 30 <= rsi < 40:
            score += 4; gains.append(f"RSI 하락세 ({rsi:.1f})")
        elif rsi < 30:
            score += 1; misses.append(f"RSI 과매도 ({rsi:.1f}) — 추격 위험")
        elif rsi > 70:
            score += 3; gains.append(f"RSI 극매수 반락 기대 ({rsi:.1f})")

        if cci < 0:
            score += 4; gains.append(f"CCI 음전환 ({cci:.0f})")
        elif 0 <= cci <= 50:
            score += 2
        else:
            misses.append(f"CCI 강세 ({cci:.0f})")

        if rsi > 65:
            score += 3; gains.append("과매수 구간 반락 기대")
    else:
        misses.append("방향 없음 — 지표 0점")

    return max(0.0, min(score, float(_MAX_INDICATOR))), gains, misses


def _calculate_volume_candle_score(data: dict, direction: str) -> tuple[float, list, list]:
    """거래량/캔들 점수 (최대 15점)"""
    score  = 0.0
    gains  = []
    misses = []

    volume    = _num(data, "volume",     default=0.0)
    avg_vol   = _num(data, "avg_volume", default=0.0)
    vol_ratio = volume / avg_vol if avg_vol > 0 else _num(data, "volume_ratio", "vol_ratio", default=0.0)

    if vol_ratio >= 2.0:
        score += 12; gains.append(f"거래량 {vol_ratio:.1f}배 — 강한 거래량")
    elif vol_ratio >= 1.5:
        score += 9;  gains.append(f"거래량 {vol_ratio:.1f}배 — 충분")
    elif vol_ratio >= 1.0:
        score += 5;  gains.append(f"거래량 {vol_ratio:.1f}배 — 보통")
    elif vol_ratio >= 0.7:
        score += 2;  misses.append(f"거래량 {vol_ratio:.1f}배 — 부족")
    else:
        misses.append(f"거래량 {vol_ratio:.1f}배 — 매우 부족")

    # 캔들 형태 점수
    close_15m = _num(data, "close_15m", "close", default=0.0)
    open_15m  = _num(data, "open_15m",  "open",  default=0.0)
    high_15m  = _num(data, "high_15m",  "high",  default=0.0)
    low_15m   = _num(data, "low_15m",   "low",   default=0.0)

    if close_15m > 0 and open_15m > 0 and high_15m > 0 and low_15m > 0:
        body   = abs(close_15m - open_15m)
        candle = high_15m - low_15m if high_15m != low_15m else 0.0001
        body_ratio = body / candle

        if direction == "LONG" and close_15m > open_15m and body_ratio > 0.6:
            score += 3; gains.append("강한 양봉")
        elif direction == "SHORT" and close_15m < open_15m and body_ratio > 0.6:
            score += 3; gains.append("강한 음봉")

    # 데이터 없으면 기록
    if avg_vol == 0 and vol_ratio == 0:
        misses.append("거래량 데이터 없음")

    return max(0.0, min(score, float(_MAX_VOL_CANDLE))), gains, misses


def _calculate_risk_score(data: dict, direction: str) -> tuple[float, list, list]:
    """리스크 점수 (최대 10점) — 손익비, 오더북, CVD, 펀딩비"""
    score  = 0.0
    gains  = []
    misses = []

    price      = _num(data, "current_price", "price", "close")
    support    = _num(data, "support",    default=0.0)
    resistance = _num(data, "resistance", default=0.0)

    # 손익비 추정
    if direction == "LONG" and support > 0 and price > support:
        risk   = price - support
        if resistance > price:
            reward = resistance - price
            rr = reward / risk if risk > 0 else 0
            if rr >= 2.5:
                score += 5; gains.append(f"손익비 {rr:.1f} — 우수")
            elif rr >= 1.5:
                score += 3; gains.append(f"손익비 {rr:.1f}")
            else:
                misses.append(f"손익비 부족 ({rr:.1f})")
        else:
            score += 2

    elif direction == "SHORT" and resistance > 0 and price < resistance:
        risk   = resistance - price
        if support > 0 and support < price:
            reward = price - support
            rr = reward / risk if risk > 0 else 0
            if rr >= 2.5:
                score += 5; gains.append(f"손익비 {rr:.1f} — 우수")
            elif rr >= 1.5:
                score += 3; gains.append(f"손익비 {rr:.1f}")
            else:
                misses.append(f"손익비 부족 ({rr:.1f})")
        else:
            score += 2
    else:
        misses.append("지지/저항 데이터 없어 손익비 미계산")

    # 오더북
    ob = _get(data, "orderbook", default={}) or {}
    if isinstance(ob, dict) and ob.get("usable"):
        pressure  = str(ob.get("pressure", "NEUTRAL")).upper()
        imbalance = float(ob.get("imbalance", 1.0) or 1.0)
        if direction == "LONG" and pressure == "BUY" and imbalance >= 1.2:
            score += 2; gains.append(f"오더북 매수 우세 ({imbalance:.2f})")
        elif direction == "SHORT" and pressure == "SELL" and imbalance <= 0.85:
            score += 2; gains.append(f"오더북 매도 우세 ({imbalance:.2f})")

    # CVD
    trades = _get(data, "trades", default={}) or {}
    if isinstance(trades, dict) and trades.get("usable"):
        cvd = str(trades.get("cvd_signal", "NEUTRAL")).upper()
        if direction == "LONG" and cvd == "BULLISH":
            score += 2; gains.append("CVD 매수 우세")
        elif direction == "SHORT" and cvd == "BEARISH":
            score += 2; gains.append("CVD 매도 우세")

    # 펀딩비
    fr = _get(data, "funding_rate", default={}) or {}
    if isinstance(fr, dict) and fr.get("usable"):
        fr_signal = str(fr.get("signal", "NEUTRAL")).upper()
        if direction == "LONG" and "SHORT_OVERHEATED" in fr_signal:
            score += 1; gains.append("펀딩비 숏 과열 — 롱 유리")
        elif direction == "SHORT" and "LONG_OVERHEATED" in fr_signal:
            score += 1; gains.append("펀딩비 롱 과열 — 숏 유리")

    return max(0.0, min(score, float(_MAX_RISK))), gains, misses


def _apply_penalties(score: float, data: dict, direction: str,
                     gap: float, component_scores: dict) -> tuple[float, list]:
    """패널티 적용 — 점수 제한만 (탈락 처리 없음)"""
    penalties = []
    s_struct = component_scores.get("structure", 0)
    s_risk   = component_scores.get("risk", 0)
    s_vol    = component_scores.get("vol_candle", 0)

    # 구조 약함 — PRE 상한
    if s_struct < _STRUCT_MIN_PRE:
        if score >= _SCORE_PRE:
            score = _SCORE_PRE - 1
            penalties.append(f"구조 점수 부족({s_struct:.0f}) — PRE 제한")

    # 구조 약함 — REAL 상한
    elif s_struct < _STRUCT_MIN_REAL:
        if score >= _SCORE_REAL:
            score = _SCORE_REAL - 1
            penalties.append(f"구조 점수 부족({s_struct:.0f}) — REAL 제한")

    # 리스크 약함 — PRE 상한
    if s_risk < _RISK_MIN_PRE:
        if score >= _SCORE_PRE:
            score = _SCORE_PRE - 1
            penalties.append(f"리스크 점수 부족({s_risk:.0f}) — PRE 제한")

    # 리스크 약함 — REAL 상한
    elif s_risk < _RISK_MIN_REAL:
        if score >= _SCORE_REAL:
            score = _SCORE_REAL - 1
            penalties.append(f"리스크 점수 부족({s_risk:.0f}) — REAL 제한")

    # 거래량 부족 + 구조 약함 → REAL 금지
    if s_vol < 5 and s_struct < _STRUCT_MIN_REAL:
        if score >= _SCORE_REAL:
            score = _SCORE_REAL - 1
            penalties.append("거래량 부족 + 구조 약함 — REAL 제한")

    # GAP 기준 상한
    if gap < _GAP_EARLY:
        if score >= _SCORE_EARLY:
            score = _SCORE_EARLY - 1
            penalties.append(f"GAP 부족({gap:.0f}) — EARLY 제한")
    elif gap < _GAP_PRE:
        if score >= _SCORE_PRE:
            score = _SCORE_PRE - 1
            penalties.append(f"GAP 부족({gap:.0f}) — PRE 제한")

    return max(0.0, score), penalties


def _decide_step(score: float) -> str:
    if score >= _SCORE_REAL:
        return _STEP_REAL
    if score >= _SCORE_PRE:
        return _STEP_PRE
    if score >= _SCORE_EARLY:
        return _STEP_EARLY
    return _STEP_WAIT


def _decide_step_detail(score: float) -> str:
    if   score <= 24: return "WAIT_LOW"
    elif score <= 39: return "WAIT_HIGH"
    elif score <= 49: return "EARLY_1"
    elif score <= 59: return "EARLY_2"
    elif score <= 67: return "PRE_1"
    elif score <= 74: return "PRE_2"
    elif score <= 84: return "REAL_1"
    else:             return "REAL_2"


def _calculate_long_score(data: dict) -> tuple[float, dict, list, list]:
    s1, g1, m1 = _calculate_structure_score(data, "LONG")
    s2, g2, m2 = _calculate_wave_score(data, "LONG")
    s3, g3, m3 = _calculate_fibo_score(data, "LONG")
    s4, g4, m4 = _calculate_indicator_score(data, "LONG")
    s5, g5, m5 = _calculate_volume_candle_score(data, "LONG")
    s6, g6, m6 = _calculate_risk_score(data, "LONG")

    components = {
        "structure":  s1, "wave": s2, "fibo": s3,
        "indicator":  s4, "vol_candle": s5, "risk": s6,
    }
    total  = s1 + s2 + s3 + s4 + s5 + s6
    gains  = g1 + g2 + g3 + g4 + g5 + g6
    misses = m1 + m2 + m3 + m4 + m5 + m6
    return min(total, 100.0), components, gains, misses


def _calculate_short_score(data: dict) -> tuple[float, dict, list, list]:
    s1, g1, m1 = _calculate_structure_score(data, "SHORT")
    s2, g2, m2 = _calculate_wave_score(data, "SHORT")
    s3, g3, m3 = _calculate_fibo_score(data, "SHORT")
    s4, g4, m4 = _calculate_indicator_score(data, "SHORT")
    s5, g5, m5 = _calculate_volume_candle_score(data, "SHORT")
    s6, g6, m6 = _calculate_risk_score(data, "SHORT")

    components = {
        "structure":  s1, "wave": s2, "fibo": s3,
        "indicator":  s4, "vol_candle": s5, "risk": s6,
    }
    total  = s1 + s2 + s3 + s4 + s5 + s6
    gains  = g1 + g2 + g3 + g4 + g5 + g6
    misses = m1 + m2 + m3 + m4 + m5 + m6
    return min(total, 100.0), components, gains, misses


def _calculate_warning_flags(data: dict, direction: str, gap: float,
                              component_scores: dict,
                              accumulation_score: float = 0.0,
                              distribution_score: float = 0.0,
                              trap_risk_score: float = 0.0) -> tuple[bool, list]:
    """WARNING 조건 판정 (신호를 막지 않음, 카운트만)"""
    warnings = []

    price      = _num(data, "current_price", "price", "close")
    resistance = _num(data, "resistance", default=0.0)
    support    = _num(data, "support",    default=0.0)
    rsi        = _num(data, "rsi", "rsi_14", default=50.0)
    trend_4h   = _str(data, "trend_4h", "higher_tf", default="SIDEWAYS").upper()
    volume     = _num(data, "volume",     default=0.0)
    avg_vol    = _num(data, "avg_volume", default=0.0)
    vol_ratio  = volume / avg_vol if avg_vol > 0 else _num(data, "volume_ratio", "vol_ratio", default=1.0)
    trend_15m  = _str(data, "trend_15m", default="SIDEWAYS").upper()

    # 1. 거래량 없는 상승/하락
    if vol_ratio < 0.7 and trend_15m in ("UP", "DOWN"):
        warnings.append(f"거래량 없는 {'상승' if trend_15m == 'UP' else '하락'} ({vol_ratio:.1f}배)")

    # 2. 상위 TF 역행
    if direction == "LONG" and trend_4h == "DOWN":
        warnings.append("4H 하락 추세 역행 롱")
    elif direction == "SHORT" and trend_4h == "UP":
        warnings.append("4H 상승 추세 역행 숏")

    # 3. 저항 근접 LONG
    if direction == "LONG" and resistance > 0 and price > 0:
        dist = (resistance - price) / price
        if 0 < dist < 0.008:
            warnings.append(f"주요 저항 근접 롱 ({dist*100:.2f}%)")

    # 4. 지지 근접 SHORT
    if direction == "SHORT" and support > 0 and price > 0:
        dist = (price - support) / price
        if 0 < dist < 0.008:
            warnings.append(f"주요 지지 근접 숏 ({dist*100:.2f}%)")

    # 5. RSI 과열 추격
    if direction == "LONG" and rsi > 72:
        warnings.append(f"RSI 과매수 추격 ({rsi:.1f})")
    elif direction == "SHORT" and rsi < 28:
        warnings.append(f"RSI 과매도 추격 ({rsi:.1f})")

    # 6. GAP 부족
    if gap < _GAP_EARLY:
        warnings.append(f"방향 불명확 (GAP {gap:.0f}점)")

    # 7. 박스권 중앙
    is_range  = _bool(data, "is_range",  default=False)
    range_pos = _str(data, "range_pos",  default="").upper()
    if is_range and range_pos == "MIDDLE":
        warnings.append("박스권 중앙 — 노이즈 구간")

    # ── 신규 v2: 매집/분산/trap 기반 경고 ───────────────────
    if trap_risk_score >= 45:
        warnings.append("개미털기/페이크 돌파 위험")

    if direction == "LONG" and distribution_score >= 55:
        warnings.append("상단 분산/매도 흡수 위험")

    if direction == "SHORT" and accumulation_score >= 55:
        warnings.append("하단 매집/매수 흡수 위험")

    # 방향과 같을 때는 긍정 신호 (WARNING 아님 — main_reasons에서 처리)
    # direction == "LONG" and accumulation_score >= 55 → 매집 흔적 감지 (긍정)
    # direction == "SHORT" and distribution_score >= 55 → 분산 흔적 감지 (긍정)

    has_warning = len(warnings) > 0
    return has_warning, warnings


# ─────────────────────────────────────────────────────────────
# 신규 v2: 매집 / 분산 / Trap Risk 점수 함수
# ─────────────────────────────────────────────────────────────

def _calculate_accumulation_score(data: dict, direction: str) -> tuple[float, list]:
    """
    매집 점수 (0~100) — 하락 중 흡수/매집 가능성 탐지.
    LONG 방향에서 높으면 유리, SHORT 방향에서 높으면 반대 위험.
    필드 없으면 0점 처리, 에러 없음.
    """
    score   = 0.0
    reasons = []

    try:
        price      = _num(data, "current_price", "price", "close")
        support    = _num(data, "support",     default=0.0)
        resistance = _num(data, "resistance",  default=0.0)
        is_range   = _bool(data, "is_range",   default=False)
        range_pos  = _str(data,  "range_pos",  default="").upper()
        volume     = _num(data, "volume",      default=0.0)
        avg_vol    = _num(data, "avg_volume",  default=0.0)
        vol_ratio  = volume / avg_vol if avg_vol > 0 else _num(data, "volume_ratio", "vol_ratio", default=0.0)
        bb_squeeze = _bool(data, "bb_squeeze", default=False)
        bb_signal  = _str(data,  "bb_signal",  default="NEUTRAL").upper()

        # 캔들 형태
        close_v = _num(data, "close_15m", "close", default=price)
        open_v  = _num(data, "open_15m",  "open",  default=price)
        high_v  = _num(data, "high_15m",  "high",  default=price)
        low_v   = _num(data, "low_15m",   "low",   default=price)
        candle_range = high_v - low_v if high_v > low_v else 0.001
        lower_wick   = (min(open_v, close_v) - low_v)  / candle_range if candle_range > 0 else 0.0

        # 오더북 / CVD / 펀딩비
        ob     = _get(data, "orderbook",     default={}) or {}
        trades = _get(data, "trades",        default={}) or {}
        fr     = _get(data, "funding_rate",  default={}) or {}

        ob_pressure  = str(ob.get("pressure", "NEUTRAL")).upper()   if isinstance(ob, dict) else "NEUTRAL"
        ob_imbalance = float(ob.get("imbalance", 1.0) or 1.0)       if isinstance(ob, dict) else 1.0
        cvd_signal   = str(trades.get("cvd_signal", "NEUTRAL")).upper() if isinstance(trades, dict) else "NEUTRAL"
        ob_usable    = bool(ob.get("usable"))     if isinstance(ob, dict)     else False
        tr_usable    = bool(trades.get("usable")) if isinstance(trades, dict) else False
        fr_usable    = bool(fr.get("usable"))     if isinstance(fr, dict)     else False
        fr_signal    = str(fr.get("signal", "NEUTRAL")).upper() if isinstance(fr, dict) else "NEUTRAL"

        # ── 가점 항목 ────────────────────────────────────────

        # 1. 박스권 하단 또는 지지선 근처
        if is_range and range_pos == "BOTTOM":
            score += 15; reasons.append("박스 하단 매집 구간")
        elif support > 0 and price > 0:
            dist_sup = (price - support) / price
            if 0 < dist_sup < 0.012:
                score += 15; reasons.append(f"지지선 근접 ({dist_sup*100:.2f}%)")
            elif 0.012 <= dist_sup < 0.025:
                score += 8

        # 2. 저점 이탈 실패 / 지지선 재회복 — 아래꼬리로 판단
        if lower_wick > 0.45:
            score += 15; reasons.append(f"아래꼬리 강한 지지 ({lower_wick*100:.0f}%)")
        elif lower_wick > 0.25:
            score += 8;  reasons.append(f"아래꼬리 지지 ({lower_wick*100:.0f}%)")

        # 3. 거래량 증가했는데 가격 하락폭 제한
        if vol_ratio >= 1.3 and close_v >= open_v * 0.998:
            score += 15; reasons.append(f"거래량 증가({vol_ratio:.1f}x) + 가격 방어")
        elif vol_ratio >= 1.0 and close_v >= open_v * 0.999:
            score += 8

        # 4. 거래량 감소 조정 + 가격 유지
        if vol_ratio < 0.8 and close_v > open_v:
            score += 10; reasons.append("거래량 감소 조정 중 가격 유지")

        # 5. BB squeeze / 변동성 압축
        if bb_squeeze:
            score += 10; reasons.append("BB squeeze — 변동성 압축")
        elif bb_signal == "OVERSOLD":
            score += 6;  reasons.append("BB 하단 과매도")

        # 6. CVD bullish
        if tr_usable and cvd_signal == "BULLISH":
            score += 10; reasons.append("CVD 매수 우세")

        # 7. 오더북 매수 우세
        if ob_usable and ob_pressure == "BUY" and ob_imbalance >= 1.2:
            score += 5; reasons.append(f"오더북 매수 우세 ({ob_imbalance:.2f})")

        # 8. 펀딩비 숏 과열 — 숏스퀴즈 가능
        if fr_usable and "SHORT_OVERHEATED" in fr_signal:
            score += 5; reasons.append("펀딩비 숏 과열")

    except Exception:
        pass   # 에러 내지 않고 현재 점수 그대로 반환

    return min(score, 100.0), reasons


def _calculate_distribution_score(data: dict, direction: str) -> tuple[float, list]:
    """
    분산 점수 (0~100) — 상단 분산/고점 매도 가능성 탐지.
    SHORT 방향에서 높으면 유리, LONG 방향에서 높으면 위험.
    필드 없으면 0점 처리, 에러 없음.
    """
    score   = 0.0
    reasons = []

    try:
        price      = _num(data, "current_price", "price", "close")
        support    = _num(data, "support",     default=0.0)
        resistance = _num(data, "resistance",  default=0.0)
        is_range   = _bool(data, "is_range",   default=False)
        range_pos  = _str(data,  "range_pos",  default="").upper()
        volume     = _num(data, "volume",      default=0.0)
        avg_vol    = _num(data, "avg_volume",  default=0.0)
        vol_ratio  = volume / avg_vol if avg_vol > 0 else _num(data, "volume_ratio", "vol_ratio", default=0.0)
        bb_squeeze = _bool(data, "bb_squeeze", default=False)
        bb_signal  = _str(data,  "bb_signal",  default="NEUTRAL").upper()

        # 캔들 형태
        close_v = _num(data, "close_15m", "close", default=price)
        open_v  = _num(data, "open_15m",  "open",  default=price)
        high_v  = _num(data, "high_15m",  "high",  default=price)
        low_v   = _num(data, "low_15m",   "low",   default=price)
        candle_range = high_v - low_v if high_v > low_v else 0.001
        upper_wick   = (high_v - max(open_v, close_v)) / candle_range if candle_range > 0 else 0.0

        ob     = _get(data, "orderbook",    default={}) or {}
        trades = _get(data, "trades",       default={}) or {}
        fr     = _get(data, "funding_rate", default={}) or {}

        ob_pressure  = str(ob.get("pressure", "NEUTRAL")).upper()      if isinstance(ob, dict) else "NEUTRAL"
        ob_imbalance = float(ob.get("imbalance", 1.0) or 1.0)          if isinstance(ob, dict) else 1.0
        cvd_signal   = str(trades.get("cvd_signal", "NEUTRAL")).upper() if isinstance(trades, dict) else "NEUTRAL"
        ob_usable    = bool(ob.get("usable"))     if isinstance(ob, dict)     else False
        tr_usable    = bool(trades.get("usable")) if isinstance(trades, dict) else False
        fr_usable    = bool(fr.get("usable"))     if isinstance(fr, dict)     else False
        fr_signal    = str(fr.get("signal", "NEUTRAL")).upper() if isinstance(fr, dict) else "NEUTRAL"

        # ── 가점 항목 ────────────────────────────────────────

        # 1. 박스권 상단 또는 저항선 근처
        if is_range and range_pos == "TOP":
            score += 15; reasons.append("박스 상단 분산 구간")
        elif resistance > 0 and price > 0:
            dist_res = (resistance - price) / price
            if 0 < dist_res < 0.012:
                score += 15; reasons.append(f"저항선 근접 ({dist_res*100:.2f}%)")
            elif 0.012 <= dist_res < 0.025:
                score += 8

        # 2. 고점 돌파 실패 / 저항 재진입 — 윗꼬리로 판단
        if upper_wick > 0.45:
            score += 15; reasons.append(f"윗꼬리 강한 저항 ({upper_wick*100:.0f}%)")
        elif upper_wick > 0.25:
            score += 8;  reasons.append(f"윗꼬리 저항 ({upper_wick*100:.0f}%)")

        # 3. 거래량 증가했는데 가격 상승폭 제한
        if vol_ratio >= 1.3 and close_v <= open_v * 1.002:
            score += 15; reasons.append(f"거래량 증가({vol_ratio:.1f}x) + 가격 저항")
        elif vol_ratio >= 1.0 and close_v <= open_v * 1.001:
            score += 8

        # 4. 거래량 감소 상승 + 가격 둔화
        if vol_ratio < 0.8 and close_v < open_v:
            score += 10; reasons.append("거래량 감소 반등 중 가격 둔화")

        # 5. BB squeeze 후 상단 실패
        if bb_squeeze and bb_signal == "OVERBOUGHT":
            score += 10; reasons.append("BB squeeze + 상단 과열")
        elif bb_signal == "OVERBOUGHT":
            score += 6;  reasons.append("BB 상단 과매수")

        # 6. CVD bearish
        if tr_usable and cvd_signal == "BEARISH":
            score += 10; reasons.append("CVD 매도 우세")

        # 7. 오더북 매도 우세
        if ob_usable and ob_pressure == "SELL" and ob_imbalance <= 0.85:
            score += 5; reasons.append(f"오더북 매도 우세 ({ob_imbalance:.2f})")

        # 8. 펀딩비 롱 과열 — 롱 청산 압력
        if fr_usable and "LONG_OVERHEATED" in fr_signal:
            score += 5; reasons.append("펀딩비 롱 과열")

    except Exception:
        pass

    return min(score, 100.0), reasons


def _calculate_trap_risk_score(data: dict, direction: str) -> tuple[float, list]:
    """
    개미털기 / 페이크 돌파 / 추격 위험 점수 (0~100).
    높을수록 REAL 진입 위험. 필드 없으면 0점.
    """
    score   = 0.0
    reasons = []

    try:
        price      = _num(data, "current_price", "price", "close")
        support    = _num(data, "support",    default=0.0)
        resistance = _num(data, "resistance", default=0.0)
        rsi        = _num(data, "rsi", "rsi_14", default=50.0)
        volume     = _num(data, "volume",     default=0.0)
        avg_vol    = _num(data, "avg_volume", default=0.0)
        vol_ratio  = volume / avg_vol if avg_vol > 0 else _num(data, "volume_ratio", "vol_ratio", default=1.0)
        is_range   = _bool(data, "is_range",  default=False)
        range_pos  = _str(data,  "range_pos", default="").upper()
        trend_15m  = _str(data, "trend_15m",  default="SIDEWAYS").upper()

        # 캔들 형태 — 장대봉 직후 약화
        close_v = _num(data, "close_15m", "close", default=price)
        open_v  = _num(data, "open_15m",  "open",  default=price)
        high_v  = _num(data, "high_15m",  "high",  default=price)
        low_v   = _num(data, "low_15m",   "low",   default=price)
        candle_range = high_v - low_v if high_v > low_v else 0.001
        body_ratio   = abs(close_v - open_v) / candle_range if candle_range > 0 else 0.0

        ob     = _get(data, "orderbook", default={}) or {}
        trades = _get(data, "trades",    default={}) or {}

        ob_pressure = str(ob.get("pressure", "NEUTRAL")).upper()       if isinstance(ob, dict) else "NEUTRAL"
        cvd_signal  = str(trades.get("cvd_signal", "NEUTRAL")).upper() if isinstance(trades, dict) else "NEUTRAL"
        ob_usable   = bool(ob.get("usable"))     if isinstance(ob, dict)     else False
        tr_usable   = bool(trades.get("usable")) if isinstance(trades, dict) else False

        # 1. 거래량 없는 돌파
        if vol_ratio < 0.7 and trend_15m in ("UP", "DOWN"):
            score += 20; reasons.append(f"거래량 없는 돌파 ({vol_ratio:.1f}x)")

        # 2. 저항/지지 근접 (LONG은 저항, SHORT는 지지)
        if direction == "LONG" and resistance > 0 and price > 0:
            dist = (resistance - price) / price
            if 0 < dist < 0.008:
                score += 10; reasons.append(f"저항 0.8% 이내 롱 ({dist*100:.2f}%)")
        if direction == "SHORT" and support > 0 and price > 0:
            dist = (price - support) / price
            if 0 < dist < 0.008:
                score += 10; reasons.append(f"지지 0.8% 이내 숏 ({dist*100:.2f}%)")

        # 3. RSI 과열 추격
        if direction == "LONG" and rsi > 72:
            score += 10; reasons.append(f"RSI 과매수 추격 ({rsi:.1f})")
        elif direction == "SHORT" and rsi < 28:
            score += 10; reasons.append(f"RSI 과매도 추격 ({rsi:.1f})")

        # 4. GAP 부족
        long_score_v  = _num(data, "long_score",  default=0.0)
        short_score_v = _num(data, "short_score", default=0.0)
        gap_est = abs(long_score_v - short_score_v)
        if gap_est < _GAP_EARLY:
            score += 10; reasons.append(f"방향 GAP 부족 ({gap_est:.0f})")

        # 5. 박스권 중앙
        if is_range and range_pos == "MIDDLE":
            score += 10; reasons.append("박스권 중앙 페이크 가능")

        # 6. CVD / 오더북이 진입 방향과 반대
        if direction == "LONG":
            if ob_usable and ob_pressure == "SELL":
                score += 10; reasons.append("오더북 매도 우세 — 롱 저항")
            if tr_usable and cvd_signal == "BEARISH":
                score += 10; reasons.append("CVD 매도 우세 — 롱 역행")
        elif direction == "SHORT":
            if ob_usable and ob_pressure == "BUY":
                score += 10; reasons.append("오더북 매수 우세 — 숏 저항")
            if tr_usable and cvd_signal == "BULLISH":
                score += 10; reasons.append("CVD 매수 우세 — 숏 역행")

        # 7. 장대봉 이후 다음 봉 힘 약화 (몸통 비율 낮음)
        if body_ratio < 0.3 and vol_ratio < 0.9:
            score += 10; reasons.append(f"캔들 힘 약화 (몸통 {body_ratio*100:.0f}%)")

    except Exception:
        pass

    return min(score, 100.0), reasons


def _apply_real_quality_gate(
    step: str,
    score: float,
    direction: str,
    component_scores: dict,
    gap: float,
    accumulation_score: float,
    distribution_score: float,
    trap_risk_score: float,
    warning_reasons: list,
    data: dict,
) -> tuple[str, float, list, str, list]:
    """
    REAL 품질 게이트 v2 — 엄격화 버전.
    REAL만 대상. PRE/EARLY/WAIT/HOLD/EXIT는 무조건 통과.
    실패 조건 1개라도 있으면 PRE로 강등 (WAIT/EARLY로 떨어지지 않음).

    반환: (step, score, penalty_reasons, quality_tier, quality_reasons)
    """
    if step != _STEP_REAL:
        tier, tier_reasons = _calc_quality_tier(
            step, score, trap_risk_score, accumulation_score,
            distribution_score, direction, gap, len(warning_reasons),
        )
        return step, score, [], tier, tier_reasons

    s_struct = component_scores.get("structure", 0)
    s_risk   = component_scores.get("risk",      0)

    # ── vol_ratio 안전 추출 (여러 후보 필드) ──────────────────
    volume    = _num(data, "volume",    default=0.0)
    avg_vol   = _num(data, "avg_volume",default=0.0)
    if avg_vol > 0:
        vol_ratio = volume / avg_vol
    else:
        vol_ratio = _num(
            data, "volume_ratio", "vol_ratio",
            "volume_ma_ratio", "vol_ma_ratio",
            default=0.0,
        )

    fail_reasons = []

    # ① 기존 공통 게이트 (구조/리스크) — 유지
    if s_struct < _STRUCT_MIN_REAL:
        fail_reasons.append(f"구조 점수 부족 ({s_struct:.0f} < {_STRUCT_MIN_REAL})")
    if s_risk < _RISK_MIN_REAL:
        fail_reasons.append(f"리스크 점수 부족 ({s_risk:.0f} < {_RISK_MIN_REAL})")

    # ② Trap Risk 강화 (_REAL_TRAP_MAX = 35)
    if trap_risk_score >= _REAL_TRAP_MAX:
        fail_reasons.append(
            f"REAL 차단: Trap Risk 높음 ({trap_risk_score:.0f} >= {_REAL_TRAP_MAX})"
        )

    # ③ WARNING 개수 강화 (_REAL_WARNING_MAX = 2, 즉 3개 이상이면 차단)
    if len(warning_reasons) > _REAL_WARNING_MAX:
        fail_reasons.append(
            f"REAL 차단: WARNING 과다 ({len(warning_reasons)}개 > {_REAL_WARNING_MAX})"
        )

    # ④ 방향별 매집/분산 점수 필수화 (_REAL_DIR_SCORE_MIN = 60)
    if direction == "LONG":
        if accumulation_score < _REAL_DIR_SCORE_MIN:
            fail_reasons.append(
                f"REAL 차단: 매집 점수 부족 ({accumulation_score:.0f} < {_REAL_DIR_SCORE_MIN})"
            )
        # 기존 분산 위험 차단 유지
        if distribution_score >= 55:
            fail_reasons.append(
                f"REAL 차단: 분산 위험 ({distribution_score:.0f} >= 55)"
            )

    elif direction == "SHORT":
        if distribution_score < _REAL_DIR_SCORE_MIN:
            fail_reasons.append(
                f"REAL 차단: 분산 점수 부족 ({distribution_score:.0f} < {_REAL_DIR_SCORE_MIN})"
            )
        # 기존 매집 위험 차단 유지
        if accumulation_score >= 55:
            fail_reasons.append(
                f"REAL 차단: 매집 위험 ({accumulation_score:.0f} >= 55)"
            )

    # ⑤ 거래량 최소 조건 (_REAL_VOL_MIN = 1.1)
    if vol_ratio < _REAL_VOL_MIN:
        fail_reasons.append(
            f"REAL 차단: 거래량 부족 ({vol_ratio:.2f} < {_REAL_VOL_MIN})"
        )

    # ⑥ GAP 강화 (_REAL_STRONG_GAP = 25)
    if gap < _REAL_STRONG_GAP:
        fail_reasons.append(
            f"REAL 차단: GAP 부족 ({gap:.0f} < {_REAL_STRONG_GAP})"
        )

    # ── 강등 처리 ─────────────────────────────────────────────
    penalties = []
    if fail_reasons:
        step  = _STEP_PRE               # 무조건 PRE (WAIT/EARLY로 떨어지지 않음)
        score = min(score, 74.0)
        penalties = [f"REAL→PRE 강등: {r}" for r in fail_reasons]

    # ── REAL_1 / REAL_2 구분 (REAL 통과 시만) ────────────────
    if step == _STEP_REAL:
        dir_score     = accumulation_score if direction == "LONG" else distribution_score
        warning_count = len(warning_reasons)
        is_real2 = (
            trap_risk_score < _REAL2_TRAP_MAX
            and dir_score    >= _REAL2_DIR_SCORE_MIN
            and gap          >= _REAL_STRONG_GAP
            and warning_count <= _REAL2_WARNING_MAX
            and vol_ratio    >= _REAL_VOL_MIN
        )
        # step_detail은 _run_engine에서 score 기반으로 이미 결정되므로
        # REAL_2 조건 충족 정보를 penalties에 긍정 메모로 남겨둠
        # (실제 step_detail 보정은 _run_engine에서 처리)
        if not is_real2:
            penalties.append("REAL_1 — 일반 실전 후보 (REAL_2 미달)")

    tier, tier_reasons = _calc_quality_tier(
        step, score, trap_risk_score, accumulation_score,
        distribution_score, direction, gap, len(warning_reasons),
    )
    return step, score, penalties, tier, tier_reasons


def _calc_quality_tier(
    step: str, score: float,
    trap_risk: float, accum: float, dist: float, direction: str,
    gap: float = 0.0, warning_count: int = 0,
) -> tuple[str, list]:
    """
    quality_tier 판정 (HIGH / MID / LOW) v2 — 강화 기준.

    HIGH:
      REAL + trap_risk < _REAL2_TRAP_MAX + dir_score >= _REAL2_DIR_SCORE_MIN
      + gap >= _REAL_STRONG_GAP + warning_count <= _REAL2_WARNING_MAX

    MID:
      PRE 이상 + trap_risk < 45

    LOW:
      그 외
    """
    reasons  = []
    dir_score = accum if direction == "LONG" else (dist if direction == "SHORT" else 0.0)

    if step == _STEP_REAL:
        if (
            trap_risk     <  _REAL2_TRAP_MAX
            and dir_score >= _REAL2_DIR_SCORE_MIN
            and gap       >= _REAL_STRONG_GAP
            and warning_count <= _REAL2_WARNING_MAX
        ):
            reasons.append(
                f"trap={trap_risk:.0f} dir_score={dir_score:.0f} "
                f"gap={gap:.0f} warn={warning_count}"
            )
            return "HIGH", reasons

    if step in (_STEP_PRE, _STEP_REAL) and trap_risk < 45:
        reasons.append(f"trap_risk={trap_risk:.0f}")
        return "MID", reasons

    reasons.append("기타")
    return "LOW", reasons


def _calculate_hold_score(data: dict, position: dict, direction: str) -> tuple[float, list]:
    """
    HOLD 점수 (최대 100점)
    포지션이 없으면 0 반환.
    """
    if not position:
        return 0.0, []

    score   = 0.0
    reasons = []

    trend_4h  = _str(data, "trend_4h", "higher_tf", default="SIDEWAYS").upper()
    trend_1h  = _str(data, "trend_1h", default="SIDEWAYS").upper()
    trend_15m = _str(data, "trend_15m", default="SIDEWAYS").upper()
    price     = _num(data, "current_price", "price", "close")
    support   = _num(data, "support",    default=0.0)
    resistance= _num(data, "resistance", default=0.0)
    pos_side  = _str(position, "direction", "side", default="").upper()
    stop_loss = _num(position, "stop", "stop_loss", "sl", default=0.0)
    volume    = _num(data, "volume",     default=0.0)
    avg_vol   = _num(data, "avg_volume", default=0.0)
    vol_ratio = volume / avg_vol if avg_vol > 0 else _num(data, "volume_ratio", default=1.0)
    fibo      = _num(data, "fibo_level", "retracement", default=0.0)
    macd      = _str(data, "macd_state", default="NEUTRAL").upper()

    if pos_side == "LONG":
        # 상위 TF 방향 유지
        if trend_4h in ("UP", "SIDEWAYS"):
            score += 20; reasons.append("4H 상승 유지")
        # 구조 유지
        if trend_1h in ("UP", "SIDEWAYS"):
            score += 20; reasons.append("1H 구조 유지")
        # HL 유지 (지지 위)
        if support > 0 and price > support:
            score += 15; reasons.append("지지선 위 유지")
        # 피보 정상 되돌림
        if 0.382 <= fibo <= 0.618:
            score += 15; reasons.append(f"피보 정상 되돌림 ({fibo:.3f})")
        # 조정 거래량 감소
        if trend_15m == "DOWN" and vol_ratio < 0.8:
            score += 10; reasons.append("조정 중 거래량 감소")
        # 손절 미이탈
        if stop_loss > 0 and price > stop_loss:
            score += 10; reasons.append("손절선 미이탈")
        # MACD 방향 유지
        if macd in ("BULLISH", "POSITIVE"):
            score += 10; reasons.append("MACD 유지")

    elif pos_side == "SHORT":
        if trend_4h in ("DOWN", "SIDEWAYS"):
            score += 20; reasons.append("4H 하락 유지")
        if trend_1h in ("DOWN", "SIDEWAYS"):
            score += 20; reasons.append("1H 구조 유지")
        if resistance > 0 and price < resistance:
            score += 15; reasons.append("저항선 아래 유지")
        if 0.382 <= fibo <= 0.618:
            score += 15; reasons.append(f"피보 정상 되돌림 ({fibo:.3f})")
        if trend_15m == "UP" and vol_ratio < 0.8:
            score += 10; reasons.append("반등 중 거래량 감소")
        if stop_loss > 0 and price < stop_loss:
            score += 0  # 손절 이탈 — HOLD 점수 없음
        elif stop_loss > 0:
            score += 10; reasons.append("손절선 미이탈")
        if macd in ("BEARISH", "NEGATIVE"):
            score += 10; reasons.append("MACD 유지")

    return min(score, 100.0), reasons


def _calculate_exit_score(data: dict, position: dict, direction: str) -> tuple[float, str, list]:
    """
    EXIT 점수 (최대 100점) + EXIT 타입 판정
    포지션 없으면 0 반환.
    """
    if not position:
        return 0.0, "NONE", []

    score     = 0.0
    exit_type = "NONE"
    reasons   = []

    price      = _num(data, "current_price", "price", "close")
    support    = _num(data, "support",    default=0.0)
    resistance = _num(data, "resistance", default=0.0)
    rsi        = _num(data, "rsi", default=50.0)
    macd       = _str(data, "macd_state", default="NEUTRAL").upper()
    trend_15m  = _str(data, "trend_15m",  default="SIDEWAYS").upper()
    trend_1h   = _str(data, "trend_1h",   default="SIDEWAYS").upper()
    volume     = _num(data, "volume",     default=0.0)
    avg_vol    = _num(data, "avg_volume", default=0.0)
    vol_ratio  = volume / avg_vol if avg_vol > 0 else _num(data, "volume_ratio", default=1.0)
    stop_loss  = _num(position, "stop", "stop_loss", "sl", default=0.0)
    pos_side   = _str(position, "direction", "side", default="").upper()

    if pos_side == "LONG":
        # LOSS_EXIT 조건
        if stop_loss > 0 and price < stop_loss:
            score += 40; exit_type = "LOSS_EXIT"
            reasons.append(f"손절선 이탈 ({stop_loss:,.2f})")
        if trend_15m == "DOWN" and vol_ratio >= 1.5:
            score += 30; exit_type = exit_type if exit_type != "NONE" else "LOSS_EXIT"
            reasons.append(f"강한 음봉 + 거래량 ({vol_ratio:.1f}배)")
        if support > 0 and price < support * 0.998:
            score += 25; exit_type = exit_type if exit_type != "NONE" else "LOSS_EXIT"
            reasons.append("주요 지지 이탈")

        # STRUCTURE_EXIT 조건
        if trend_1h == "DOWN" and macd in ("BEARISH", "NEGATIVE"):
            score += 20; exit_type = exit_type if exit_type != "NONE" else "STRUCTURE_EXIT"
            reasons.append("1H 하락 전환 + MACD 약화")

        # PROFIT_EXIT 조건
        if resistance > 0 and price >= resistance * 0.998:
            if rsi > 65 or vol_ratio < 0.8:
                score += 20; exit_type = exit_type if exit_type != "NONE" else "PROFIT_EXIT"
                reasons.append("저항 도달 + 모멘텀 둔화")

    elif pos_side == "SHORT":
        if stop_loss > 0 and price > stop_loss:
            score += 40; exit_type = "LOSS_EXIT"
            reasons.append(f"손절선 이탈 ({stop_loss:,.2f})")
        if trend_15m == "UP" and vol_ratio >= 1.5:
            score += 30; exit_type = exit_type if exit_type != "NONE" else "LOSS_EXIT"
            reasons.append(f"강한 양봉 + 거래량 ({vol_ratio:.1f}배)")
        if resistance > 0 and price > resistance * 1.002:
            score += 25; exit_type = exit_type if exit_type != "NONE" else "LOSS_EXIT"
            reasons.append("주요 저항 돌파")

        if trend_1h == "UP" and macd in ("BULLISH", "POSITIVE"):
            score += 20; exit_type = exit_type if exit_type != "NONE" else "STRUCTURE_EXIT"
            reasons.append("1H 상승 전환 + MACD 상방")

        if support > 0 and price <= support * 1.002:
            if rsi < 35 or vol_ratio < 0.8:
                score += 20; exit_type = exit_type if exit_type != "NONE" else "PROFIT_EXIT"
                reasons.append("지지 도달 + 모멘텀 둔화")

    if score == 0:
        exit_type = "NONE"

    return min(score, 100.0), exit_type, reasons


def _decide_action_text(final_state: str, direction: str,
                        warning: bool, exit_type: str) -> str:
    """사용자 노출 행동 문구 — 짧고 명확하게"""
    if final_state == _STEP_EXIT:
        type_ko = {"LOSS_EXIT": "손절 EXIT", "PROFIT_EXIT": "익절 EXIT",
                   "STRUCTURE_EXIT": "구조 EXIT"}.get(exit_type, "EXIT")
        return f"{direction} {type_ko} — 포지션 정리 검토"
    if final_state == _STEP_HOLD:
        warn_tag = " (WARNING)" if warning else ""
        return f"{direction} HOLD{warn_tag} — 포지션 유지"
    if final_state == _STEP_REAL:
        warn_tag = " (주의)" if warning else ""
        return f"{direction} REAL 진입 가능{warn_tag} — 자동진입 아님"
    if final_state == _STEP_PRE:
        return f"{direction} PRE — 조건 확인 중 / 다음 15분봉 대기"
    if final_state == _STEP_EARLY:
        warn_tag = " / WARNING" if warning else ""
        return f"{direction} EARLY — 초기 구조 감지{warn_tag}"
    return "WAIT — 방향 대기 / 진입 조건 미달"


def _missing_fields_report(data: dict) -> list:
    """누락된 주요 필드 기록 (debug용)"""
    important = [
        ("price", ["current_price", "price", "close"]),
        ("rsi",   ["rsi", "rsi_14"]),
        ("macd",  ["macd_state", "macd"]),
        ("trend_15m", ["trend_15m"]),
        ("trend_1h",  ["trend_1h"]),
        ("trend_4h",  ["trend_4h", "higher_tf"]),
        ("volume",    ["volume", "avg_volume"]),
        ("support",   ["support"]),
        ("resistance",["resistance"]),
    ]
    missing = []
    for label, keys in important:
        found = any(_get(data, k) is not None for k in keys)
        if not found:
            missing.append(label)
    return missing


# ─────────────────────────────────────────────────────────────
# 공개 진입점
# ─────────────────────────────────────────────────────────────

def decide_step_state(
    market_data: dict,
    current_position: dict = None,
    previous_decision: dict = None,
) -> dict:
    """
    STEP / HOLD / WARNING / EXIT 통합 판단 엔진.

    Parameters
    ----------
    market_data       : 분석 데이터 (signal.py 의 sig 또는 analysis_data)
    current_position  : 현재 보유 포지션 dict (없으면 None)
    previous_decision : 직전 decision dict (상태 연속성 참고용, 선택)

    Returns
    -------
    dict : final_state, direction, score, long_score, short_score, gap,
           warning, warning_reasons, hold_score, exit_score, exit_type,
           step, step_detail, main_reasons, penalty_reasons, action_text, debug
    """
    # ── fallback: None 데이터 ───────────────────────────────
    if not market_data:
        return _fallback_wait("market_data is None")

    try:
        return _run_engine(market_data, current_position, previous_decision)
    except Exception as exc:
        return _fallback_wait(str(exc))


def _run_engine(data: dict, position: dict, prev: dict) -> dict:
    missing_fields = _missing_fields_report(data)

    # ── 1. LONG / SHORT 독립 점수 계산 ──────────────────────
    long_raw,  long_comp,  long_gains,  long_misses  = _calculate_long_score(data)
    short_raw, short_comp, short_gains, short_misses = _calculate_short_score(data)

    long_score  = round(long_raw,  1)
    short_score = round(short_raw, 1)
    gap         = round(abs(long_score - short_score), 1)

    # ── 2. 방향 결정 ─────────────────────────────────────────
    existing_dir = _str(data, "direction", default="").upper()
    if existing_dir in ("LONG", "SHORT"):
        direction = existing_dir
    elif long_score > short_score and gap >= 10:
        direction = "LONG"
    elif short_score > long_score and gap >= 10:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    # ── 3. 방향에 맞는 점수 / 컴포넌트 선택 ─────────────────
    if direction == "LONG":
        raw_score  = long_raw
        comp       = long_comp
        main_gains = long_gains
        main_miss  = long_misses
    elif direction == "SHORT":
        raw_score  = short_raw
        comp       = short_comp
        main_gains = short_gains
        main_miss  = short_misses
    else:
        raw_score  = max(long_raw, short_raw) * 0.5
        comp       = long_comp if long_raw >= short_raw else short_comp
        main_gains = []
        main_miss  = ["방향 불명확 — 점수 50% 적용"]

    # ── 4. 패널티 적용 ───────────────────────────────────────
    penalized_score, penalty_reasons = _apply_penalties(
        raw_score, data, direction, gap, comp
    )
    score = round(penalized_score, 1)

    # ── 4b. 신규 v2 점수 계산 ────────────────────────────────
    accumulation_score, accum_reasons = _calculate_accumulation_score(data, direction)
    distribution_score, dist_reasons  = _calculate_distribution_score(data, direction)
    trap_risk_score,    trap_reasons   = _calculate_trap_risk_score(data, direction)

    accumulation_score = round(accumulation_score, 1)
    distribution_score = round(distribution_score, 1)
    trap_risk_score    = round(trap_risk_score,    1)

    # ── 5. STEP 판정 ─────────────────────────────────────────
    step        = _decide_step(score)
    step_detail = _decide_step_detail(score)

    # ── 6. WARNING (v2: 신규 점수 전달) ──────────────────────
    warning, warning_reasons = _calculate_warning_flags(
        data, direction, gap, comp,
        accumulation_score=accumulation_score,
        distribution_score=distribution_score,
        trap_risk_score=trap_risk_score,
    )

    # WARNING 3개 이상 + 리스크 낮음 → REAL → PRE 강등 (기존 로직 유지)
    if step == _STEP_REAL and len(warning_reasons) >= 3 and comp.get("risk", 0) < _RISK_MIN_REAL:
        step        = _STEP_PRE
        step_detail = "PRE_2"
        score       = min(score, float(_SCORE_REAL - 1))
        penalty_reasons.append(f"WARNING {len(warning_reasons)}개 + 리스크 약함 — REAL→PRE 강등")

    # ── 6b. REAL 품질 게이트 (v2 신규) ───────────────────────
    step, score, gate_penalties, quality_tier, quality_reasons = _apply_real_quality_gate(
        step, score, direction, comp, gap,
        accumulation_score, distribution_score, trap_risk_score,
        warning_reasons, data,
    )
    penalty_reasons.extend(gate_penalties)
    if gate_penalties:
        step_detail = "PRE_2"

    # ── 6c. REAL_1 / REAL_2 step_detail 보정 ─────────────────
    # REAL 통과 후 vol_ratio 재계산 (gate 함수 내부와 동일 로직)
    if step == _STEP_REAL:
        _vol_r    = _num(data, "volume", default=0.0)
        _avg_v    = _num(data, "avg_volume", default=0.0)
        _vr       = _vol_r / _avg_v if _avg_v > 0 else _num(
            data, "volume_ratio", "vol_ratio", "volume_ma_ratio", "vol_ma_ratio", default=0.0
        )
        dir_score = accumulation_score if direction == "LONG" else distribution_score
        is_real2  = (
            trap_risk_score  < _REAL2_TRAP_MAX
            and dir_score    >= _REAL2_DIR_SCORE_MIN
            and gap          >= _REAL_STRONG_GAP
            and len(warning_reasons) <= _REAL2_WARNING_MAX
            and _vr          >= _REAL_VOL_MIN
        )
        step_detail = "REAL_2" if is_real2 else "REAL_1"

    # ── 7. HOLD / EXIT (포지션 보유 시) ─────────────────────
    hold_score   = 0.0
    hold_reasons = []
    exit_score   = 0.0
    exit_type    = "NONE"
    exit_reasons = []

    if position:
        hold_score,  hold_reasons  = _calculate_hold_score(data, position, direction)
        exit_score, exit_type, exit_reasons = _calculate_exit_score(data, position, direction)

        if exit_type == "LOSS_EXIT" and exit_score >= 75:
            step = _STEP_EXIT
        elif hold_score >= 70:
            step = _STEP_HOLD
        elif exit_score >= 60 and hold_score < 50:
            step = _STEP_EXIT

    # ── 8. final_state ───────────────────────────────────────
    final_state = step

    # ── 9. action_text ───────────────────────────────────────
    action_text = _decide_action_text(final_state, direction, warning, exit_type)

    # ── 10. main_reasons 정리 (v2: 매집/분산 긍정 신호 추가) ─
    main_reasons = [r for r in main_gains if not r.startswith("⚠")][:5]
    # 방향과 맞는 매집/분산 신호 main_reasons에 추가
    if direction == "LONG" and accumulation_score >= 55 and accum_reasons:
        main_reasons.append(f"매집 감지 ({accumulation_score:.0f}점)")
    elif direction == "SHORT" and distribution_score >= 55 and dist_reasons:
        main_reasons.append(f"분산 감지 ({distribution_score:.0f}점)")
    if not main_reasons:
        main_reasons = main_miss[:3]

    return {
        "final_state":        final_state,
        "direction":          direction,
        "step":               step,
        "step_detail":        step_detail,
        "score":              score,
        "long_score":         long_score,
        "short_score":        short_score,
        "gap":                gap,
        "warning":            warning,
        "warning_reasons":    warning_reasons,
        "hold_score":         round(hold_score, 1),
        "exit_score":         round(exit_score, 1),
        "exit_type":          exit_type,
        "main_reasons":       main_reasons,
        "penalty_reasons":    penalty_reasons,
        "action_text":        action_text,
        # ── v2 신규 필드 ─────────────────────────────────────
        "accumulation_score": accumulation_score,
        "distribution_score": distribution_score,
        "trap_risk_score":    trap_risk_score,
        "quality_tier":       quality_tier,
        "quality_reasons":    quality_reasons,
        "debug": {
            "components":            comp,
            "missing_fields":        missing_fields,
            "hold_reasons":          hold_reasons,
            "exit_reasons":          exit_reasons,
            "raw_score":             round(raw_score, 1),
            "accumulation_reasons":  accum_reasons,
            "distribution_reasons":  dist_reasons,
            "trap_reasons":          trap_reasons,
        },
    }


def _fallback_wait(reason: str) -> dict:
    return {
        "final_state":        "WAIT",
        "direction":          "NEUTRAL",
        "step":               "WAIT",
        "step_detail":        "WAIT_LOW",
        "score":              0,
        "long_score":         0,
        "short_score":        0,
        "gap":                0,
        "warning":            False,
        "warning_reasons":    [],
        "hold_score":         0,
        "exit_score":         0,
        "exit_type":          "NONE",
        "main_reasons":       [],
        "penalty_reasons":    [],
        "action_text":        "WAIT — 데이터 부족 또는 오류",
        "accumulation_score": 0,
        "distribution_score": 0,
        "trap_risk_score":    0,
        "quality_tier":       "LOW",
        "quality_reasons":    [],
        "debug": {
            "error": reason, "missing_fields": [], "components": {},
            "accumulation_reasons": [], "distribution_reasons": [], "trap_reasons": [],
        },
    }
