# signal_engine.py v6
# ═══════════════════════════════════════════════════════════════
# 중앙 신호 판단 엔진
# v6 변경: market_data(오더북/CVD/펀딩비/청산) → PRE/REAL 필터에 반영
# ═══════════════════════════════════════════════════════════════

from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

# ── 임계값 ──────────────────────────────────────────────────────
RADAR_MIN  = 60
PRE_MIN    = 72
REAL_MIN   = 85

RADAR_GAP  = 12
PRE_GAP    = 18
REAL_GAP   = 25

PRE_VOL    = 1.0
REAL_VOL   = 1.5

RSI_LONG_MIN   = 40
RSI_LONG_MAX   = 72
RSI_SHORT_MIN  = 28
RSI_SHORT_MAX  = 60

PRE_DIST   = 0.003
REAL_DIST  = 0.005

MIN_RR     = 2.0

ATR_STOP_MULTI = 1.5
ATR_TP1_MULTI  = 2.0
ATR_TP2_MULTI  = 3.5


# ── 유틸 ────────────────────────────────────────────────────────

def _safe(v, d=0.0):
    try:
        return float(v) if v is not None else d
    except Exception:
        return d


def _get(sig, *keys, default=None):
    for k in keys:
        if k in sig and sig[k] is not None:
            return sig[k]
    return default


def _pct(a, b):
    a, b = _safe(a), _safe(b)
    return abs(a - b) / b if b != 0 else 999.0


# ── ATR ─────────────────────────────────────────────────────────

def calc_atr(candles, period=14):
    if len(candles) < period + 1:
        ranges = []
        for c in candles[-5:]:
            h = _safe(c.get("high"))
            l = _safe(c.get("low"))
            if h and l:
                ranges.append(h - l)
        return sum(ranges) / len(ranges) if ranges else 0.0
    trs = []
    for i in range(1, len(candles)):
        h  = _safe(candles[i].get("high"))
        l  = _safe(candles[i].get("low"))
        pc = _safe(candles[i-1].get("close"))
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-period:]) / period


# ── market_data 필터 (신규 v6) ───────────────────────────────────

def market_data_filters(sig, direction, market_data: dict) -> tuple:
    """
    오더북/CVD/펀딩비/청산/롱숏 기반 추가 필터
    반환: (차단 여부, 이유 목록)
    True = 차단, False = 통과
    """
    if not market_data:
        return False, []

    block_reasons = []

    # ── 오더북: 강한 역방향 벽 ─────────────────────
    ob = market_data.get("orderbook", {})
    if ob.get("usable"):
        pressure   = ob.get("pressure", "NEUTRAL")
        wall_ratio = ob.get("wall_ratio", 1.0)
        imbalance  = ob.get("imbalance", 1.0)

        if direction == "LONG" and pressure == "SELL" and imbalance <= 0.65:
            block_reasons.append(f"오더북 강한 매도 우세 (불균형 {imbalance:.2f}) — 롱 저항")
        if direction == "SHORT" and pressure == "BUY" and imbalance >= 1.55:
            block_reasons.append(f"오더북 강한 매수 우세 (불균형 {imbalance:.2f}) — 숏 저항")
        if wall_ratio >= 8:
            block_reasons.append(f"극강 주문벽 감지 (강도 {wall_ratio:.1f}x) — 돌파 불확실")

    # ── CVD: 체결 방향 역행 ────────────────────────
    trades = market_data.get("trades", {})
    if trades.get("usable"):
        cvd_signal = trades.get("cvd_signal", "NEUTRAL")
        buy_ratio  = trades.get("buy_ratio", 50)

        if direction == "LONG" and cvd_signal == "BEARISH" and buy_ratio <= 38:
            block_reasons.append(f"CVD 매도 강세 ({buy_ratio:.1f}%) — 실제 체결 방향 역행")
        if direction == "SHORT" and cvd_signal == "BULLISH" and buy_ratio >= 62:
            block_reasons.append(f"CVD 매수 강세 ({buy_ratio:.1f}%) — 실제 체결 방향 역행")

    # ── 펀딩비: 방향 역행 과열 ─────────────────────
    fr = market_data.get("funding_rate", {})
    if fr.get("usable"):
        fr_signal = fr.get("signal", "NEUTRAL")
        fr_rate   = fr.get("funding_rate", 0)

        # 롱인데 롱 과열 → 추격 금지
        if direction == "LONG" and fr_signal == "LONG_OVERHEATED":
            block_reasons.append(f"펀딩비 롱 과열 (+{fr_rate:.4f}%) — 롱 추격 위험")
        # 숏인데 숏 과열 → 추격 금지
        if direction == "SHORT" and fr_signal == "SHORT_OVERHEATED":
            block_reasons.append(f"펀딩비 숏 과열 ({fr_rate:.4f}%) — 숏 추격 위험")

    # ── 청산: 같은 방향 대량 청산 직후 ────────────
    liq = market_data.get("liquidations", {})
    if liq.get("usable"):
        dominant  = liq.get("dominant", "BALANCED")
        large_liq = liq.get("large_liq", 0)

        # 롱 청산이 쏟아지는 중에 롱 진입 → 위험
        if direction == "LONG" and dominant == "LONG_LIQUIDATED" and large_liq >= 3:
            block_reasons.append(f"롱 대량 청산 진행 중 ({large_liq}건) — 추가 하락 압력")
        if direction == "SHORT" and dominant == "SHORT_LIQUIDATED" and large_liq >= 3:
            block_reasons.append(f"숏 대량 청산 진행 중 ({large_liq}건) — 숏스퀴즈 위험")

    blocked = len(block_reasons) > 0
    return blocked, block_reasons


def market_data_bonuses(sig, direction, market_data: dict) -> list:
    """
    market_data 기반 PRE 신호 강화 항목
    충족 시 structural_hits에 추가됨
    """
    if not market_data:
        return []

    hits = []

    ob = market_data.get("orderbook", {})
    if ob.get("usable"):
        pressure  = ob.get("pressure", "NEUTRAL")
        imbalance = ob.get("imbalance", 1.0)
        if direction == "LONG" and pressure == "BUY" and imbalance >= 1.25:
            hits.append(f"오더북 매수 우세 (불균형 {imbalance:.2f})")
        if direction == "SHORT" and pressure == "SELL" and imbalance <= 0.80:
            hits.append(f"오더북 매도 우세 (불균형 {imbalance:.2f})")

    trades = market_data.get("trades", {})
    if trades.get("usable"):
        cvd_signal   = trades.get("cvd_signal", "NEUTRAL")
        large_trades = trades.get("large_trades", 0)
        if direction == "LONG" and cvd_signal == "BULLISH":
            hits.append("CVD 매수 우세 — 실제 체결 방향 일치")
        if direction == "SHORT" and cvd_signal == "BEARISH":
            hits.append("CVD 매도 우세 — 실제 체결 방향 일치")
        if large_trades >= 3:
            hits.append(f"대량 체결 {large_trades}건 — 고래 진입 감지")

    fr = market_data.get("funding_rate", {})
    if fr.get("usable"):
        fr_signal = fr.get("signal", "NEUTRAL")
        fr_rate   = fr.get("funding_rate", 0)
        if direction == "LONG" and fr_signal in ("SHORT_OVERHEATED", "SHORT_MILD"):
            hits.append(f"펀딩비 숏 과열 ({fr_rate:.4f}%) — 숏스퀴즈 가능")
        if direction == "SHORT" and fr_signal in ("LONG_OVERHEATED", "LONG_MILD"):
            hits.append(f"펀딩비 롱 과열 (+{fr_rate:.4f}%) — 롱 청산 압력")

    oi = market_data.get("open_interest", {})
    if oi.get("usable") and oi.get("oi_signal") == "INCREASING":
        hits.append(f"OI 증가 (+{oi.get('oi_1h_change', 0):.2f}%) — 포지션 축적")

    ls = market_data.get("long_short_ratio", {})
    if ls.get("usable"):
        ls_signal = ls.get("signal", "NEUTRAL")
        if direction == "LONG" and ls_signal == "SHORT_CROWDED":
            hits.append(f"숏 과밀 ({ls.get('short_pct',50):.1f}%) — 역발상 롱 유리")
        if direction == "SHORT" and ls_signal == "LONG_CROWDED":
            hits.append(f"롱 과밀 ({ls.get('long_pct',50):.1f}%) — 역발상 숏 유리")

    return hits


# ── 가짜 신호 필터 ───────────────────────────────────────────────

def fake_signal_filters(sig, direction, candles_15m, market_data=None):
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

    vol_ratio = volume / avg_vol if avg_vol > 0 else 0

    if vol_ratio < REAL_VOL:
        reasons.append(f"거래량 부족 ({vol_ratio:.1f}배 < {REAL_VOL}배)")

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

    if direction == "LONG":
        if rsi_val > RSI_LONG_MAX:
            reasons.append(f"RSI 과매수 진입 금지 ({rsi_val:.1f})")
        if rsi_val < RSI_LONG_MIN:
            reasons.append(f"RSI 과매도 미탈출 ({rsi_val:.1f})")
    if direction == "SHORT":
        if rsi_val < RSI_SHORT_MIN:
            reasons.append(f"RSI 과매도 추격 금지 ({rsi_val:.1f})")
        if rsi_val > RSI_SHORT_MAX:
            reasons.append(f"RSI 과매수 미탈출 ({rsi_val:.1f})")

    if is_range and range_pos == "MIDDLE":
        reasons.append("박스권 중앙 — 노이즈 구간")

    if direction == "LONG" and macd in ("BEARISH", "NEGATIVE"):
        reasons.append("MACD 하방 — 롱 모멘텀 미확인")
    if direction == "SHORT" and macd in ("BULLISH", "POSITIVE"):
        reasons.append("MACD 상방 — 숏 모멘텀 미확인")

    if direction == "LONG" and bb_signal == "OVERBOUGHT":
        reasons.append("볼린저 상단 과매수 — 롱 추격 금지")
    if direction == "SHORT" and bb_signal == "OVERSOLD":
        reasons.append("볼린저 하단 과매도 — 숏 추격 금지")

    if candles_15m and len(candles_15m) >= 2:
        last = candles_15m[-2]
        o = _safe(last.get("open")); c = _safe(last.get("close"))
        h = _safe(last.get("high")); l = _safe(last.get("low"))
        body = abs(c - o)
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        full = h - l if h != l else 0.0001
        if direction == "LONG" and upper_wick > body * 1.5 and upper_wick / full > 0.4:
            reasons.append("직전봉 긴 위꼬리 — 상단 저항 강함")
        if direction == "SHORT" and lower_wick > body * 1.5 and lower_wick / full > 0.4:
            reasons.append("직전봉 긴 아래꼬리 — 하단 지지 강함")

    # ── market_data 필터 추가 (v6 신규) ──────────────
    if market_data:
        blocked, block_reasons = market_data_filters(sig, direction, market_data)
        if blocked:
            reasons.extend(block_reasons)

    return len(reasons) == 0, reasons


# ── 손절/익절 계산 ───────────────────────────────────────────────

def calc_risk_levels(sig, direction, candles_15m):
    price      = _safe(_get(sig, "current_price"))
    atr        = calc_atr(candles_15m)
    support    = _safe(_get(sig, "support",    default=price * 0.99))
    resistance = _safe(_get(sig, "resistance", default=price * 1.01))

    if direction == "LONG":
        atr_stop   = price - atr * ATR_STOP_MULTI
        level_stop = support * 0.998
        stop = max(atr_stop, level_stop)
        tp1  = price + atr * ATR_TP1_MULTI
        tp2  = price + atr * ATR_TP2_MULTI
        risk = price - stop; reward = tp1 - price
        rr   = reward / risk if risk > 0 else 0
        if rr < MIN_RR:
            tp1 = price + risk * MIN_RR
            tp2 = price + risk * MIN_RR * 1.8
    else:
        atr_stop   = price + atr * ATR_STOP_MULTI
        level_stop = resistance * 1.002
        stop = min(atr_stop, level_stop)
        tp1  = price - atr * ATR_TP1_MULTI
        tp2  = price - atr * ATR_TP2_MULTI
        risk = stop - price; reward = price - tp1
        rr   = reward / risk if risk > 0 else 0
        if rr < MIN_RR:
            tp1 = price - risk * MIN_RR
            tp2 = price - risk * MIN_RR * 1.8

    stop_pct = abs(price - stop) / price * 100
    rr_final = abs(tp1 - price) / abs(price - stop) if abs(price - stop) > 0 else 0

    return {
        "entry":    price,
        "stop":     round(stop, 4),
        "tp1":      round(tp1, 4),
        "tp2":      round(tp2, 4),
        "stop_pct": round(stop_pct, 2),
        "rr":       round(rr_final, 2),
        "atr":      round(atr, 4),
    }


# ── PRE 판단 ────────────────────────────────────────────────────

def check_pre_signal(sig, candles_15m, market_data=None):
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
    rsi_val    = _safe(_get(sig, "rsi",        default=50))
    cci_val    = _safe(_get(sig, "cci",        default=0))
    macd       = _get(sig, "macd_state",       default="NEUTRAL")
    trend_15m  = _get(sig, "trend_15m",        default="SIDEWAYS")
    trend_1h   = _get(sig, "trend_1h",         default="SIDEWAYS")
    trend_4h   = _get(sig, "trend_4h",         default="SIDEWAYS")
    div        = _get(sig, "divergence",       default=None)
    bb_signal  = _get(sig, "bb_signal",        default="NEUTRAL")
    bb_squeeze = _get(sig, "bb_squeeze",       default=False)
    is_range   = _get(sig, "is_range",         default=False)
    range_pos  = _get(sig, "range_pos",        default=None)
    volume     = _safe(_get(sig, "volume",     default=0))
    avg_vol    = _safe(_get(sig, "avg_volume", default=0))
    support    = _safe(_get(sig, "support",    default=0))
    resistance = _safe(_get(sig, "resistance", default=0))

    vol_ratio = volume / avg_vol if avg_vol > 0 else 0

    if vol_ratio < PRE_VOL:
        return False, [f"거래량 부족 ({vol_ratio:.1f}배 < {PRE_VOL}배)"]
    if is_range and range_pos == "MIDDLE":
        return False, ["박스권 중앙 — PRE 발령 불가"]
    if direction == "LONG" and trend_4h == "DOWN":
        return False, ["4H 하락 추세 역행"]
    if direction == "SHORT" and trend_4h == "UP":
        return False, ["4H 상승 추세 역행"]

    # ── market_data 블로킹 필터 (v6) ─────────────────
    if market_data:
        blocked, block_reasons = market_data_filters(sig, direction, market_data)
        if blocked:
            return False, block_reasons

    structural_hits = []

    if direction == "LONG":
        if trend_15m == "UP":                           structural_hits.append("15M 상승 전환")
        if trend_1h in ("UP", "SIDEWAYS"):              structural_hits.append("1H 방향 우호적")
        if 45 <= rsi_val <= 65:                         structural_hits.append(f"RSI 적정 ({rsi_val:.1f})")
        if macd in ("BULLISH", "POSITIVE"):             structural_hits.append("MACD 상방 전환")
        if div == "BULLISH_DIV":                        structural_hits.append("상승 다이버전스")
        if bb_signal == "OVERSOLD":                     structural_hits.append("볼린저 하단 반등")
        if bb_squeeze:                                  structural_hits.append("볼린저 수축 — 상승 임박")
        if is_range and range_pos == "BOTTOM":          structural_hits.append("박스 하단 지지")
        if support and _pct(price, support) <= PRE_DIST: structural_hits.append(f"지지선 근접")
        if cci_val > -50:                               structural_hits.append("CCI 회복 중")
    else:
        if trend_15m == "DOWN":                           structural_hits.append("15M 하락 전환")
        if trend_1h in ("DOWN", "SIDEWAYS"):              structural_hits.append("1H 방향 우호적")
        if 35 <= rsi_val <= 55:                           structural_hits.append(f"RSI 적정 ({rsi_val:.1f})")
        if macd in ("BEARISH", "NEGATIVE"):               structural_hits.append("MACD 하방 전환")
        if div == "BEARISH_DIV":                          structural_hits.append("하락 다이버전스")
        if bb_signal == "OVERBOUGHT":                     structural_hits.append("볼린저 상단 저항")
        if bb_squeeze:                                    structural_hits.append("볼린저 수축 — 하락 임박")
        if is_range and range_pos == "TOP":               structural_hits.append("박스 상단 저항")
        if resistance and _pct(price, resistance) <= PRE_DIST: structural_hits.append(f"저항선 근접")
        if cci_val < 50:                                  structural_hits.append("CCI 하락 중")

    # ── market_data 보너스 항목 추가 (v6) ────────────
    if market_data:
        structural_hits.extend(market_data_bonuses(sig, direction, market_data))

    if len(structural_hits) < 3:
        return False, [f"구조적 신호 부족 ({len(structural_hits)}/3개)"]

    return True, structural_hits


# ── REAL 판단 ────────────────────────────────────────────────────

def check_real_signal(sig, candles_15m, market_data=None):
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
    rsi_val    = _safe(_get(sig, "rsi",        default=50))
    macd       = _get(sig, "macd_state",       default="NEUTRAL")
    trend_15m  = _get(sig, "trend_15m",        default="SIDEWAYS")
    trend_1h   = _get(sig, "trend_1h",         default="SIDEWAYS")
    volume     = _safe(_get(sig, "volume",     default=0))
    avg_vol    = _safe(_get(sig, "avg_volume", default=0))
    support    = _safe(_get(sig, "support",    default=0))
    resistance = _safe(_get(sig, "resistance", default=0))
    above_ema20 = _get(sig, "above_ema20", default=False)
    below_ema20 = _get(sig, "below_ema20", default=False)

    vol_ratio = volume / avg_vol if avg_vol > 0 else 0

    # 가짜 신호 필터 (market_data 포함)
    passed, fake_reasons = fake_signal_filters(sig, direction, candles_15m, market_data)
    if not passed:
        return False, fake_reasons, None

    real_hits  = []
    real_fails = []

    if direction == "LONG":
        if above_ema20:
            real_hits.append("15M 종가 EMA20 상단 확정")
        elif close_15m > resistance * 0.998:
            real_hits.append(f"저항 돌파 확정")
        else:
            real_fails.append("EMA20 / 저항 돌파 미확정")

        if trend_15m == "UP" and trend_1h in ("UP", "SIDEWAYS"):
            real_hits.append(f"추세 정렬 (15M:{trend_15m}/1H:{trend_1h})")
        else:
            real_fails.append(f"추세 미정렬")

        if RSI_LONG_MIN <= rsi_val <= RSI_LONG_MAX:
            real_hits.append(f"RSI 적정 ({rsi_val:.1f})")
        else:
            real_fails.append(f"RSI 범위 이탈 ({rsi_val:.1f})")

        if macd in ("BULLISH", "POSITIVE"):
            real_hits.append(f"MACD {macd}")
        else:
            real_fails.append(f"MACD 미충족 ({macd})")

        if vol_ratio >= REAL_VOL:
            real_hits.append(f"거래량 {vol_ratio:.1f}배 확인")
        else:
            real_fails.append(f"거래량 부족 ({vol_ratio:.1f}배)")

    else:
        if below_ema20:
            real_hits.append("15M 종가 EMA20 하단 확정")
        elif close_15m < support * 1.002:
            real_hits.append(f"지지 이탈 확정")
        else:
            real_fails.append("EMA20 / 지지 이탈 미확정")

        if trend_15m == "DOWN" and trend_1h in ("DOWN", "SIDEWAYS"):
            real_hits.append(f"추세 정렬 (15M:{trend_15m}/1H:{trend_1h})")
        else:
            real_fails.append(f"추세 미정렬")

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

    # ── market_data 보너스 조건 추가 (v6) ─────────────
    if market_data:
        bonuses = market_data_bonuses(sig, direction, market_data)
        real_hits.extend(bonuses[:2])   # 최대 2개 추가 조건

    if len(real_hits) < 4:
        return False, real_fails, None

    levels = calc_risk_levels(sig, direction, candles_15m)
    if levels["rr"] < MIN_RR:
        return False, [f"손익비 부족 ({levels['rr']:.1f} < {MIN_RR})"], None

    return True, real_hits, levels


# ── 메시지 생성 ──────────────────────────────────────────────────

def make_pre_message(sig, hits):
    direction  = _get(sig, "direction", default="WAIT")
    symbol     = _get(sig, "symbol",    default="?")
    confidence = _safe(_get(sig, "confidence", default=0))
    price      = _safe(_get(sig, "current_price"))
    volume     = _safe(_get(sig, "volume",     default=0))
    avg_vol    = _safe(_get(sig, "avg_volume", default=0))
    vol_ratio  = volume / avg_vol if avg_vol > 0 else 0

    dir_emoji = "🟢" if direction == "LONG" else "🔴"
    dir_txt   = "LONG" if direction == "LONG" else "SHORT"
    hits_txt  = "\n".join([f"  ✅ {h}" for h in hits])

    return (
        f"⚡ {symbol} PRE-ENTRY 발령\n"
        f"{'─'*30}\n"
        f"{dir_emoji} 방향: {dir_txt} | 신뢰도: {confidence}%\n"
        f"💰 현재가: {price:,.2f}\n"
        f"📊 거래량: {vol_ratio:.1f}배\n"
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
    hits_txt  = "\n".join([f"  ✅ {h}" for h in hits])

    return (
        f"🔥 {symbol} REAL ENTRY\n"
        f"{'═'*30}\n"
        f"{dir_emoji} {dir_txt} | 신뢰도 {confidence}%\n"
        f"\n"
        f"💰 진입가: {levels['entry']:,.2f}\n"
        f"🛑 손절:   {levels['stop']:,.2f}  (-{levels['stop_pct']:.1f}%)\n"
        f"🎯 1차:    {levels['tp1']:,.2f}\n"
        f"🎯 2차:    {levels['tp2']:,.2f}\n"
        f"📐 손익비: 1 : {levels['rr']:.1f}\n"
        f"\n"
        f"✅ 통과 조건:\n"
        f"{hits_txt}\n"
        f"\n"
        f"⚠️ 자동진입 아님 — 직접 체결 확인\n"
        f"💡 손절 미준수 시 봇 신호 무의미\n"
        f"\n"
        f"🕐 {datetime.now(KST).strftime('%H:%M')} 기준"
    )


# ── 메인 진입점 ──────────────────────────────────────────────────

def evaluate(sig: dict, candles_15m: list, market_data: dict = None) -> dict:
    """
    단일 진입점. market_data가 있으면 PRE/REAL 판단에 반영.
    """
    direction  = _get(sig, "direction",  default="WAIT")
    confidence = _safe(_get(sig, "confidence", default=0))
    score_gap  = _safe(_get(sig, "score_gap",  default=0))

    if direction == "WAIT" or confidence < RADAR_MIN or score_gap < RADAR_GAP:
        return {
            "type": "WAIT", "message": None, "levels": None,
            "hits": [], "reasons": [f"신뢰도 {confidence}% / 갭 {score_gap}%p"],
        }

    real_ok, real_hits_or_reasons, levels = check_real_signal(sig, candles_15m, market_data)
    if real_ok:
        return {
            "type":    "REAL",
            "message": make_real_message(sig, real_hits_or_reasons, levels),
            "levels":  levels,
            "hits":    real_hits_or_reasons,
            "reasons": [],
        }

    pre_ok, pre_hits_or_reasons = check_pre_signal(sig, candles_15m, market_data)
    if pre_ok:
        return {
            "type":    "PRE",
            "message": make_pre_message(sig, pre_hits_or_reasons),
            "levels":  None,
            "hits":    pre_hits_or_reasons,
            "reasons": [],
        }

    return {
        "type": "RADAR", "message": None, "levels": None,
        "hits": [],
        "reasons": real_hits_or_reasons if not real_ok else pre_hits_or_reasons,
    }
