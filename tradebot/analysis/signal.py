# signal_engine.py
# ═══════════════════════════════════════════════════════════════
# 중앙 신호 판단 엔진
# 전 세계 0.1% 트레이더 방법론 기반 설계
#
# 철학:
#   "애매하면 들어가지 않는다"
#   "진입은 어렵게, 수익은 크게, 손실은 작게"
#
# 구조:
#   core_analyzer.py → signal_engine.py → entry_timing.py
#   모든 코인에 동일 적용 (BTC, ETH, 기타 무한 확장)
# ═══════════════════════════════════════════════════════════════

from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))


# ───────────────────────────────────────────────────────────────
# 상수 — 검증된 기준값
# ───────────────────────────────────────────────────────────────

# 신뢰도 임계값
RADAR_MIN   = 60    # 감시 시작
PRE_MIN     = 72    # PRE 발령 (기존 75 → 72로 완화)
REAL_MIN    = 85    # REAL 발령 (기존 90 → 85로 완화, 가짜필터로 보완)

# 점수 갭
RADAR_GAP   = 12
PRE_GAP     = 18
REAL_GAP    = 25

# 거래량
PRE_VOL     = 1.0   # PRE: 평균 이상
REAL_VOL    = 1.5   # REAL: 평균 1.5배 이상 (가짜 신호 핵심 필터)

# RSI 기준
RSI_LONG_MIN    = 40    # 롱: RSI 40 이상 (과매도 탈출)
RSI_LONG_MAX    = 72    # 롱: RSI 72 이하 (과매수 금지)
RSI_SHORT_MIN   = 28    # 숏: RSI 28 이상 (과매도 추격 금지)
RSI_SHORT_MAX   = 60    # 숏: RSI 60 이하 (과매수 탈출)

# 가격 거리
PRE_DIST    = 0.003     # PRE: 핵심 가격 0.3% 이내
REAL_DIST   = 0.005     # REAL: 핵심 가격 0.5% 이내 (종가 기준으로 완화)

# 손익비 (최소 1:2 이상)
MIN_RR      = 2.0

# ATR 기반 손절 배수
ATR_STOP_MULTI  = 1.5   # 손절 = ATR * 1.5
ATR_TP1_MULTI   = 2.0   # 1차 익절 = ATR * 2.0
ATR_TP2_MULTI   = 3.5   # 2차 익절 = ATR * 3.5


# ───────────────────────────────────────────────────────────────
# 유틸
# ───────────────────────────────────────────────────────────────

def _safe(v, d=0.0):
    try: return float(v) if v is not None else d
    except: return d


def _get(sig, *keys, default=None):
    for k in keys:
        if k in sig and sig[k] is not None:
            return sig[k]
    return default


def _pct(a, b):
    a, b = _safe(a), _safe(b)
    return abs(a - b) / b if b != 0 else 999.0


# ───────────────────────────────────────────────────────────────
# ATR 계산 (Average True Range)
# 변동성 측정 → 손절/익절 자동 계산의 핵심
# ───────────────────────────────────────────────────────────────

def calc_atr(candles, period=14):
    """
    ATR: 시장의 실제 변동성
    → 손절을 너무 타이트하게 잡으면 개미털기에 당함
    → ATR 기반 손절은 시장 노이즈를 흡수
    """
    if len(candles) < period + 1:
        # 데이터 부족 시 최근 캔들 범위 평균으로 대체
        ranges = []
        for c in candles[-5:]:
            h = _safe(c.get("high"))
            l = _safe(c.get("low"))
            if h and l:
                ranges.append(h - l)
        return sum(ranges) / len(ranges) if ranges else 0.0

    trs = []
    for i in range(1, len(candles)):
        h = _safe(candles[i].get("high"))
        l = _safe(candles[i].get("low"))
        pc = _safe(candles[i-1].get("close"))
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)

    return sum(trs[-period:]) / period


# ───────────────────────────────────────────────────────────────
# 가짜 신호 필터 (핵심)
# ───────────────────────────────────────────────────────────────

def fake_signal_filters(sig, direction, candles_15m):
    """
    가짜 신호를 걸러내는 다중 필터
    하나라도 걸리면 REAL 발령 금지

    반환: (통과 여부, 실패 이유)
    """
    reasons = []

    price     = _safe(_get(sig, "current_price"))
    rsi_val   = _safe(_get(sig, "rsi", default=50))
    cci_val   = _safe(_get(sig, "cci", default=0))
    macd      = _get(sig, "macd_state", default="NEUTRAL")
    trend_1h  = _get(sig, "trend_1h",  default="SIDEWAYS")
    trend_4h  = _get(sig, "trend_4h",  default="SIDEWAYS")
    is_range  = _get(sig, "is_range",  default=False)
    range_pos = _get(sig, "range_pos", default=None)
    volume    = _safe(_get(sig, "volume",     default=0))
    avg_vol   = _safe(_get(sig, "avg_volume", default=0))
    bb_signal = _get(sig, "bb_signal", default="NEUTRAL")
    div       = _get(sig, "divergence", default=None)

    vol_ratio = volume / avg_vol if avg_vol > 0 else 0

    # ── 필터 1: 거래량 없는 신호 = 가짜 ─────
    # 개미털기는 거래량 없이 가격만 움직임
    if vol_ratio < REAL_VOL:
        reasons.append(f"거래량 부족 ({vol_ratio:.1f}배 < {REAL_VOL}배)")

    # ── 필터 2: 상위 타임프레임 역방향 ──────
    # 1H/4H 추세와 반대 진입은 역류 수영
    if direction == "LONG":
        if trend_4h == "DOWN":
            reasons.append("4H 하락 추세 역행 진입")
        if trend_1h == "DOWN" and trend_4h != "UP":
            reasons.append("1H 하락 + 4H 미확인")

    if direction == "SHORT":
        if trend_4h == "UP":
            reasons.append("4H 상승 추세 역행 진입")
        if trend_1h == "UP" and trend_4h != "DOWN":
            reasons.append("1H 상승 + 4H 미확인")

    # ── 필터 3: RSI 극단값 진입 금지 ────────
    # 과매수에서 롱, 과매도에서 숏 = 추격 매매
    if direction == "LONG":
        if rsi_val > RSI_LONG_MAX:
            reasons.append(f"RSI 과매수 진입 금지 ({rsi_val:.1f} > {RSI_LONG_MAX})")
        if rsi_val < RSI_LONG_MIN:
            reasons.append(f"RSI 과매도 미탈출 ({rsi_val:.1f} < {RSI_LONG_MIN})")

    if direction == "SHORT":
        if rsi_val < RSI_SHORT_MIN:
            reasons.append(f"RSI 과매도 추격 금지 ({rsi_val:.1f} < {RSI_SHORT_MIN})")
        if rsi_val > RSI_SHORT_MAX:
            reasons.append(f"RSI 과매수 미탈출 ({rsi_val:.1f} > {RSI_SHORT_MAX})")

    # ── 필터 4: 박스권 중앙 진입 금지 ───────
    # 중앙은 양방향 노이즈 = 훼이크 무빙 최다 발생 구간
    if is_range and range_pos == "MIDDLE":
        reasons.append("박스권 중앙 — 노이즈 구간")

    # ── 필터 5: MACD 역방향 ──────────────────
    # 모멘텀이 반대 방향이면 진입 위험
    if direction == "LONG" and macd in ("BEARISH", "NEGATIVE"):
        reasons.append("MACD 하방 — 롱 모멘텀 미확인")
    if direction == "SHORT" and macd in ("BULLISH", "POSITIVE"):
        reasons.append("MACD 상방 — 숏 모멘텀 미확인")

    # ── 필터 6: 볼린저밴드 반대 신호 ────────
    if direction == "LONG" and bb_signal == "OVERBOUGHT":
        reasons.append("볼린저 상단 과매수 — 롱 추격 금지")
    if direction == "SHORT" and bb_signal == "OVERSOLD":
        reasons.append("볼린저 하단 과매도 — 숏 추격 금지")

    # ── 필터 7: 캔들 형태 (위꼬리/아래꼬리) ─
    # 긴 역방향 꼬리 = 세력의 거부 신호
    if candles_15m and len(candles_15m) >= 2:
        last = candles_15m[-2]  # 직전 마감 봉
        o = _safe(last.get("open"));  c = _safe(last.get("close"))
        h = _safe(last.get("high"));  l = _safe(last.get("low"))
        body = abs(c - o)
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        full = h - l if h != l else 0.0001

        if direction == "LONG" and upper_wick > body * 1.5 and upper_wick / full > 0.4:
            reasons.append("직전봉 긴 위꼬리 — 상단 저항 강함")
        if direction == "SHORT" and lower_wick > body * 1.5 and lower_wick / full > 0.4:
            reasons.append("직전봉 긴 아래꼬리 — 하단 지지 강함")

    passed = len(reasons) == 0
    return passed, reasons


# ───────────────────────────────────────────────────────────────
# 손절/익절 자동 계산
# ───────────────────────────────────────────────────────────────

def calc_risk_levels(sig, direction, candles_15m):
    """
    ATR 기반 손절/익절 자동 계산
    손익비 최소 1:2 보장
    """
    price  = _safe(_get(sig, "current_price"))
    atr    = calc_atr(candles_15m)
    support    = _safe(_get(sig, "support",    default=price * 0.99))
    resistance = _safe(_get(sig, "resistance", default=price * 1.01))

    if direction == "LONG":
        # 손절: ATR 기반 또는 직전 저점 중 더 보수적인 값
        atr_stop = price - atr * ATR_STOP_MULTI
        level_stop = support * 0.998  # 지지선 아래 0.2%
        stop = max(atr_stop, level_stop)  # 더 위에 있는 손절 (타이트)

        tp1 = price + atr * ATR_TP1_MULTI
        tp2 = price + atr * ATR_TP2_MULTI

        risk   = price - stop
        reward = tp1 - price
        rr     = reward / risk if risk > 0 else 0

        # 손익비 1:2 미만이면 tp1 조정
        if rr < MIN_RR:
            tp1 = price + risk * MIN_RR
            tp2 = price + risk * MIN_RR * 1.8

    else:  # SHORT
        atr_stop = price + atr * ATR_STOP_MULTI
        level_stop = resistance * 1.002
        stop = min(atr_stop, level_stop)  # 더 아래에 있는 손절

        tp1 = price - atr * ATR_TP1_MULTI
        tp2 = price - atr * ATR_TP2_MULTI

        risk   = stop - price
        reward = price - tp1
        rr     = reward / risk if risk > 0 else 0

        if rr < MIN_RR:
            tp1 = price - risk * MIN_RR
            tp2 = price - risk * MIN_RR * 1.8

    stop_pct = abs(price - stop) / price * 100
    rr_final = abs(tp1 - price) / abs(price - stop) if abs(price - stop) > 0 else 0

    return {
        "entry":     price,
        "stop":      round(stop, 4),
        "tp1":       round(tp1, 4),
        "tp2":       round(tp2, 4),
        "stop_pct":  round(stop_pct, 2),
        "rr":        round(rr_final, 2),
        "atr":       round(atr, 4),
    }


# ───────────────────────────────────────────────────────────────
# PRE 신호 판단
# ───────────────────────────────────────────────────────────────

def check_pre_signal(sig, candles_15m):
    """
    PRE: "심상치 않다 — 다음 봉 주목"
    구조적 변화 감지 기반
    """
    direction  = _get(sig, "direction",  default="WAIT")
    confidence = _safe(_get(sig, "confidence", default=0))
    score_gap  = _safe(_get(sig, "score_gap",  default=0))

    if direction == "WAIT":
        return False, ["방향 미확정"]

    if confidence < PRE_MIN:
        return False, [f"신뢰도 부족 ({confidence}% < {PRE_MIN}%)"]

    if score_gap < PRE_GAP:
        return False, [f"점수차 부족 ({score_gap}%p < {PRE_GAP}%p)"]

    price      = _safe(_get(sig, "current_price"))
    rsi_val    = _safe(_get(sig, "rsi",    default=50))
    cci_val    = _safe(_get(sig, "cci",    default=0))
    macd       = _get(sig, "macd_state",   default="NEUTRAL")
    trend_15m  = _get(sig, "trend_15m",    default="SIDEWAYS")
    trend_1h   = _get(sig, "trend_1h",     default="SIDEWAYS")
    trend_4h   = _get(sig, "trend_4h",     default="SIDEWAYS")
    div        = _get(sig, "divergence",   default=None)
    bb_signal  = _get(sig, "bb_signal",    default="NEUTRAL")
    bb_squeeze = _get(sig, "bb_squeeze",   default=False)
    is_range   = _get(sig, "is_range",     default=False)
    range_pos  = _get(sig, "range_pos",    default=None)
    volume     = _safe(_get(sig, "volume",     default=0))
    avg_vol    = _safe(_get(sig, "avg_volume", default=0))
    support    = _safe(_get(sig, "support",    default=0))
    resistance = _safe(_get(sig, "resistance", default=0))

    vol_ratio = volume / avg_vol if avg_vol > 0 else 0

    # ── 거래량 최소 조건 ─────────────────────
    if vol_ratio < PRE_VOL:
        return False, [f"거래량 부족 ({vol_ratio:.1f}배 < {PRE_VOL}배)"]

    # ── 박스권 중앙 금지 ─────────────────────
    if is_range and range_pos == "MIDDLE":
        return False, ["박스권 중앙 — PRE 발령 불가"]

    # ── 4H 역방향 금지 ──────────────────────
    if direction == "LONG" and trend_4h == "DOWN":
        return False, ["4H 하락 추세 역행"]
    if direction == "SHORT" and trend_4h == "UP":
        return False, ["4H 상승 추세 역행"]

    # ── 구조적 신호 스코어링 ─────────────────
    # 이 중 3개 이상 충족해야 PRE 발령
    structural_hits = []

    if direction == "LONG":
        if trend_15m == "UP":
            structural_hits.append("15M 상승 전환")
        if trend_1h in ("UP", "SIDEWAYS"):
            structural_hits.append("1H 방향 우호적")
        if rsi_val >= 45 and rsi_val <= 65:
            structural_hits.append(f"RSI 진입 적정 구간 ({rsi_val:.1f})")
        if macd in ("BULLISH", "POSITIVE"):
            structural_hits.append("MACD 상방 전환")
        if div == "BULLISH_DIV":
            structural_hits.append("상승 다이버전스")
        if bb_signal == "OVERSOLD":
            structural_hits.append("볼린저 하단 반등")
        if bb_squeeze:
            structural_hits.append("볼린저 수축 — 상승 임박")
        if is_range and range_pos == "BOTTOM":
            structural_hits.append("박스 하단 지지")
        if support and _pct(price, support) <= PRE_DIST:
            structural_hits.append(f"지지선 근접 ({_pct(price, support)*100:.2f}%)")
        if cci_val > -50:
            structural_hits.append("CCI 회복 중")

    else:  # SHORT
        if trend_15m == "DOWN":
            structural_hits.append("15M 하락 전환")
        if trend_1h in ("DOWN", "SIDEWAYS"):
            structural_hits.append("1H 방향 우호적")
        if rsi_val >= 35 and rsi_val <= 55:
            structural_hits.append(f"RSI 진입 적정 구간 ({rsi_val:.1f})")
        if macd in ("BEARISH", "NEGATIVE"):
            structural_hits.append("MACD 하방 전환")
        if div == "BEARISH_DIV":
            structural_hits.append("하락 다이버전스")
        if bb_signal == "OVERBOUGHT":
            structural_hits.append("볼린저 상단 저항")
        if bb_squeeze:
            structural_hits.append("볼린저 수축 — 하락 임박")
        if is_range and range_pos == "TOP":
            structural_hits.append("박스 상단 저항")
        if resistance and _pct(price, resistance) <= PRE_DIST:
            structural_hits.append(f"저항선 근접 ({_pct(price, resistance)*100:.2f}%)")
        if cci_val < 50:
            structural_hits.append("CCI 하락 중")

    if len(structural_hits) < 3:
        return False, [f"구조적 신호 부족 ({len(structural_hits)}/3개)"]

    return True, structural_hits


# ───────────────────────────────────────────────────────────────
# REAL 신호 판단
# ───────────────────────────────────────────────────────────────

def check_real_signal(sig, candles_15m):
    """
    REAL: "지금 들어가라"
    15분봉 종가 확정 + 가짜 신호 필터 전부 통과
    """
    direction  = _get(sig, "direction",  default="WAIT")
    confidence = _safe(_get(sig, "confidence", default=0))
    score_gap  = _safe(_get(sig, "score_gap",  default=0))

    if direction == "WAIT":
        return False, ["방향 미확정"], None

    if confidence < REAL_MIN:
        return False, [f"신뢰도 부족 ({confidence}% < {REAL_MIN}%)"], None

    if score_gap < REAL_GAP:
        return False, [f"점수차 부족 ({score_gap}%p < {REAL_GAP}%p)"], None

    price      = _safe(_get(sig, "current_price"))
    close_15m  = _safe(_get(sig, "close_15m",  default=price))
    rsi_val    = _safe(_get(sig, "rsi",    default=50))
    macd       = _get(sig, "macd_state",   default="NEUTRAL")
    trend_15m  = _get(sig, "trend_15m",    default="SIDEWAYS")
    trend_1h   = _get(sig, "trend_1h",     default="SIDEWAYS")
    volume     = _safe(_get(sig, "volume",     default=0))
    avg_vol    = _safe(_get(sig, "avg_volume", default=0))
    support    = _safe(_get(sig, "support",    default=0))
    resistance = _safe(_get(sig, "resistance", default=0))
    above_ema20 = _get(sig, "above_ema20", default=False)
    below_ema20 = _get(sig, "below_ema20", default=False)
    ema20      = _safe(_get(sig, "ema20",   default=price))

    vol_ratio = volume / avg_vol if avg_vol > 0 else 0

    # ── 가짜 신호 필터 전체 통과 ─────────────
    passed, fake_reasons = fake_signal_filters(sig, direction, candles_15m)
    if not passed:
        return False, fake_reasons, None

    # ── 핵심 진입 조건 ───────────────────────
    real_hits = []
    real_fails = []

    if direction == "LONG":
        # 필수: 15분봉 종가가 EMA20 위 또는 저항 돌파
        if above_ema20:
            real_hits.append("15M 종가 EMA20 상단 확정")
        elif close_15m > resistance * 0.998:
            real_hits.append(f"저항 {resistance:.0f} 돌파 확정")
        else:
            real_fails.append("EMA20 / 저항 돌파 미확정")

        # 필수: 추세 정렬
        if trend_15m == "UP" and trend_1h in ("UP", "SIDEWAYS"):
            real_hits.append(f"추세 정렬 (15M:{trend_15m} / 1H:{trend_1h})")
        else:
            real_fails.append(f"추세 미정렬 (15M:{trend_15m} / 1H:{trend_1h})")

        # 필수: RSI
        if RSI_LONG_MIN <= rsi_val <= RSI_LONG_MAX:
            real_hits.append(f"RSI 적정 ({rsi_val:.1f})")
        else:
            real_fails.append(f"RSI 범위 이탈 ({rsi_val:.1f})")

        # 필수: MACD
        if macd in ("BULLISH", "POSITIVE"):
            real_hits.append(f"MACD {macd}")
        else:
            real_fails.append(f"MACD 미충족 ({macd})")

        # 필수: 거래량
        if vol_ratio >= REAL_VOL:
            real_hits.append(f"거래량 {vol_ratio:.1f}배 확인")
        else:
            real_fails.append(f"거래량 부족 ({vol_ratio:.1f}배)")

    else:  # SHORT
        if below_ema20:
            real_hits.append("15M 종가 EMA20 하단 확정")
        elif close_15m < support * 1.002:
            real_hits.append(f"지지 {support:.0f} 이탈 확정")
        else:
            real_fails.append("EMA20 / 지지 이탈 미확정")

        if trend_15m == "DOWN" and trend_1h in ("DOWN", "SIDEWAYS"):
            real_hits.append(f"추세 정렬 (15M:{trend_15m} / 1H:{trend_1h})")
        else:
            real_fails.append(f"추세 미정렬 (15M:{trend_15m} / 1H:{trend_1h})")

        if RSI_SHORT_MIN <= rsi_val <= RSI_SHORT_MAX:
            real_hits.append(f"RSI 적정 ({rsi_val:.1f})")
        else:
            real_fails.append(f"RSI 범위 이탈 ({rsi_val:.1f})")

        if macd in ("BEARISH", "NEGATIVE"):
            real_hits.append(f"MACD {macd}")
        else:
            real_fails.append(f"MACD 미충족 ({macd})")

        if vol_ratio >= REAL_VOL:
            real_hits.append(f"거래량 {vol_ratio:.1f}배 확인")
        else:
            real_fails.append(f"거래량 부족 ({vol_ratio:.1f}배)")

    # 필수 조건 5개 중 4개 이상 충족
    if len(real_hits) < 4:
        return False, real_fails, None

    # ── 손절/익절 계산 ────────────────────────
    levels = calc_risk_levels(sig, direction, candles_15m)

    # 손익비 검증
    if levels["rr"] < MIN_RR:
        return False, [f"손익비 부족 ({levels['rr']:.1f} < {MIN_RR})"], None

    return True, real_hits, levels


# ───────────────────────────────────────────────────────────────
# 메시지 생성
# ───────────────────────────────────────────────────────────────

def make_pre_message(sig, hits):
    direction  = _get(sig, "direction", default="WAIT")
    symbol     = _get(sig, "symbol",    default="?")
    confidence = _safe(_get(sig, "confidence", default=0))
    price      = _safe(_get(sig, "current_price"))
    vol        = _safe(_get(sig, "volume",     default=0))
    avg_vol    = _safe(_get(sig, "avg_volume", default=0))
    vol_ratio  = vol / avg_vol if avg_vol > 0 else 0

    dir_emoji = "🟢" if direction == "LONG" else "🔴"
    dir_txt   = "LONG" if direction == "LONG" else "SHORT"

    hits_txt = "\n".join([f"  ✅ {h}" for h in hits])

    return (
        f"⚡ {symbol} PRE-ENTRY 발령\n"
        f"{'─'*30}\n"
        f"{dir_emoji} 방향: {dir_txt} | 신뢰도: {confidence}%\n"
        f"💰 현재가: {price:,.2f}\n"
        f"📊 거래량: {vol_ratio:.1f}배 (평균 대비)\n"
        f"\n"
        f"🔍 포착된 구조적 신호:\n"
        f"{hits_txt}\n"
        f"\n"
        f"⚠️ 아직 진입 아님\n"
        f"→ 다음 15분봉 마감 확인 후 REAL 판단\n"
        f"→ 거래량 {REAL_VOL}배 이상 동반 필수\n"
        f"\n"
        f"🕐 {datetime.now(KST).strftime('%H:%M')} 기준"
    )


def make_real_message(sig, hits, levels):
    direction  = _get(sig, "direction", default="WAIT")
    symbol     = _get(sig, "symbol",    default="?")
    confidence = _safe(_get(sig, "confidence", default=0))

    dir_emoji = "🚀" if direction == "LONG" else "💥"
    dir_txt   = "LONG" if direction == "LONG" else "SHORT"

    hits_txt = "\n".join([f"  ✅ {h}" for h in hits])

    stop_pct = levels["stop_pct"]
    rr       = levels["rr"]

    return (
        f"🔥 {symbol} REAL ENTRY\n"
        f"{'═'*30}\n"
        f"{dir_emoji} {dir_txt} | 신뢰도 {confidence}%\n"
        f"\n"
        f"💰 진입가: {levels['entry']:,.2f}\n"
        f"🛑 손절:   {levels['stop']:,.2f}  (-{stop_pct:.1f}%)\n"
        f"🎯 1차:    {levels['tp1']:,.2f}\n"
        f"🎯 2차:    {levels['tp2']:,.2f}\n"
        f"📐 손익비: 1 : {rr:.1f}\n"
        f"\n"
        f"✅ 통과 조건:\n"
        f"{hits_txt}\n"
        f"\n"
        f"⚠️ 자동진입 아님 — 직접 체결 확인\n"
        f"💡 손절 미준수 시 봇 신호 무의미\n"
        f"\n"
        f"🕐 {datetime.now(KST).strftime('%H:%M')} 기준"
    )


def make_pre_fail_message(sig, reasons):
    """PRE 거의 근접했지만 아직 미달 시 참고 메시지"""
    direction  = _get(sig, "direction", default="WAIT")
    symbol     = _get(sig, "symbol",    default="?")
    confidence = _safe(_get(sig, "confidence", default=0))

    if confidence < PRE_MIN - 10:
        return None  # 너무 멀면 메시지 없음

    reasons_txt = "\n".join([f"  ❌ {r}" for r in reasons[:3]])

    return (
        f"👀 {symbol} PRE 미달 ({confidence}%)\n"
        f"방향: {direction}\n"
        f"미충족:\n{reasons_txt}\n"
        f"→ 조건 충족 시 PRE 발령 예정"
    )


# ───────────────────────────────────────────────────────────────
# 메인 진입점 — entry_timing.py에서 이걸 호출
# ───────────────────────────────────────────────────────────────

def evaluate(sig: dict, candles_15m: list) -> dict:
    """
    단일 진입점.
    모든 코인에 동일 적용.

    반환:
    {
        "type": "REAL" / "PRE" / "RADAR" / "WAIT",
        "message": str,
        "levels": dict or None,  # REAL일 때만
        "hits": list,
        "reasons": list,
    }
    """
    direction  = _get(sig, "direction",  default="WAIT")
    confidence = _safe(_get(sig, "confidence", default=0))
    score_gap  = _safe(_get(sig, "score_gap",  default=0))

    # ── WAIT ────────────────────────────────
    if direction == "WAIT" or confidence < RADAR_MIN or score_gap < RADAR_GAP:
        return {
            "type":    "WAIT",
            "message": None,
            "levels":  None,
            "hits":    [],
            "reasons": [f"신뢰도 {confidence}% / 갭 {score_gap}%p"],
        }

    # ── REAL 체크 ───────────────────────────
    real_ok, real_hits_or_reasons, levels = check_real_signal(sig, candles_15m)
    if real_ok:
        return {
            "type":    "REAL",
            "message": make_real_message(sig, real_hits_or_reasons, levels),
            "levels":  levels,
            "hits":    real_hits_or_reasons,
            "reasons": [],
        }

    # ── PRE 체크 ────────────────────────────
    pre_ok, pre_hits_or_reasons = check_pre_signal(sig, candles_15m)
    if pre_ok:
        return {
            "type":    "PRE",
            "message": make_pre_message(sig, pre_hits_or_reasons),
            "levels":  None,
            "hits":    pre_hits_or_reasons,
            "reasons": [],
        }

    # ── RADAR (기본 감시) ────────────────────
    return {
        "type":    "RADAR",
        "message": None,   # 레이더 메시지는 entry_timing에서 생성
        "levels":  None,
        "hits":    [],
        "reasons": real_hits_or_reasons if not real_ok else pre_hits_or_reasons,
    }
