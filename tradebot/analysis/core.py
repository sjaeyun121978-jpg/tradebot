# core_analyzer.py
# 단일 분석 엔진
# ─────────────────────────────────────────────
# 모든 메시지(진입레이더/PRE/REAL/전광판/브리핑)가
# 이 파일의 analyze() 결과를 공유한다.
#
# 새 지표 추가 = 이 파일만 수정
# 나머지 파일은 건드릴 필요 없음
# ─────────────────────────────────────────────

from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))


# ─────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────

def now_kst():
    return datetime.now(KST)


def safe_float(value, default=0.0):
    try:
        return float(value) if value is not None else default
    except Exception:
        return default


def avg(values):
    vals = [safe_float(v) for v in values if v is not None]
    return sum(vals) / len(vals) if vals else 0.0


def pct_distance(a, b):
    a, b = safe_float(a), safe_float(b)
    return abs(a - b) / b if b != 0 else 999.0


def pct_change(current, previous):
    if previous == 0:
        return 0.0
    return ((current - previous) / previous) * 100


def get_open(c):   return safe_float(c.get("open"))   if c else 0.0
def get_high(c):   return safe_float(c.get("high"))   if c else 0.0
def get_low(c):    return safe_float(c.get("low"))    if c else 0.0
def get_close(c):  return safe_float(c.get("close"))  if c else 0.0
def get_volume(c): return safe_float(c.get("volume")) if c else 0.0


# ─────────────────────────────────────────────
# 지표 계산
# ─────────────────────────────────────────────

def calc_ema(values, period):
    vals = [safe_float(v) for v in values]
    if not vals:
        return 0.0
    if len(vals) < period:
        return avg(vals)
    k = 2 / (period + 1)
    result = vals[0]
    for p in vals[1:]:
        result = p * k + result * (1 - k)
    return result


def calc_rsi(values, period=14):
    vals = [safe_float(v) for v in values]
    if len(vals) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(vals)):
        d = vals[i] - vals[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = avg(gains[-period:])
    al = avg(losses[-period:])
    if al == 0:
        return 100.0
    return 100 - (100 / (1 + ag / al))


def calc_cci(candles, period=20):
    if len(candles) < period:
        return 0.0
    tps = [(get_high(c) + get_low(c) + get_close(c)) / 3 for c in candles[-period:]]
    ma  = avg(tps)
    md  = avg([abs(tp - ma) for tp in tps])
    return (tps[-1] - ma) / (0.015 * md) if md != 0 else 0.0


def calc_macd(values):
    """
    반환: (state, macd_val, signal_val)
    state: BULLISH / BEARISH / POSITIVE / NEGATIVE / NEUTRAL
    """
    vals = [safe_float(v) for v in values]
    if len(vals) < 35:
        return "NEUTRAL", 0.0, 0.0
    ema12 = calc_ema(vals, 12)
    ema26 = calc_ema(vals, 26)
    macd_val = ema12 - ema26
    recent = [
        calc_ema(vals[:i+1], 12) - calc_ema(vals[:i+1], 26)
        for i in range(len(vals) - 9, len(vals))
    ]
    signal = calc_ema(recent, 9)
    if macd_val > signal and macd_val > 0:   state = "BULLISH"
    elif macd_val < signal and macd_val < 0: state = "BEARISH"
    elif macd_val > 0:                       state = "POSITIVE"
    elif macd_val < 0:                       state = "NEGATIVE"
    else:                                    state = "NEUTRAL"
    return state, macd_val, signal


def calc_bollinger(values, period=20, std_dev=2.0):
    """
    볼린저밴드 계산
    반환:
      upper  : 상단 밴드
      middle : 중간선 (SMA)
      lower  : 하단 밴드
      width  : 밴드 폭 (%) — 클수록 변동성 큼
      pct_b  : 현재가 위치 (0=하단, 1=상단)
      squeeze: True면 밴드 수축 (큰 움직임 임박)
      position: "UPPER" / "LOWER" / "MIDDLE"
      signal : "OVERBOUGHT" / "OVERSOLD" / "SQUEEZE" / "NEUTRAL"
    """
    vals = [safe_float(v) for v in values]
    if len(vals) < period:
        return {
            "upper": 0.0, "middle": 0.0, "lower": 0.0,
            "width": 0.0, "pct_b": 0.5,
            "squeeze": False, "position": "MIDDLE",
            "signal": "NEUTRAL", "usable": False,
        }

    recent = vals[-period:]
    middle = avg(recent)
    std    = (sum((x - middle) ** 2 for x in recent) / period) ** 0.5
    upper  = middle + std_dev * std
    lower  = middle - std_dev * std

    current = vals[-1]
    band_range = upper - lower
    pct_b  = (current - lower) / band_range if band_range != 0 else 0.5
    width  = (band_range / middle * 100) if middle != 0 else 0.0

    # 최근 50봉 평균 밴드폭과 비교해 수축 여부 판단
    squeeze = False
    if len(vals) >= period + 30:
        past_widths = []
        for i in range(30):
            sub = vals[-(period + 30 - i):-(30 - i) or None]
            if len(sub) >= period:
                m = avg(sub[-period:])
                s = (sum((x - m) ** 2 for x in sub[-period:]) / period) ** 0.5
                bw = (2 * std_dev * s / m * 100) if m != 0 else 0
                past_widths.append(bw)
        if past_widths:
            avg_width = avg(past_widths)
            squeeze = width < avg_width * 0.7   # 평균의 70% 미만이면 수축

    if pct_b >= 0.9:
        position = "UPPER"
        signal   = "OVERBOUGHT"
    elif pct_b <= 0.1:
        position = "LOWER"
        signal   = "OVERSOLD"
    elif squeeze:
        position = "MIDDLE"
        signal   = "SQUEEZE"
    else:
        position = "MIDDLE"
        signal   = "NEUTRAL"

    return {
        "upper":    upper,
        "middle":   middle,
        "lower":    lower,
        "width":    width,
        "pct_b":    pct_b,
        "squeeze":  squeeze,
        "position": position,
        "signal":   signal,
        "usable":   True,
    }


def calc_divergence(closes, period=10):
    """
    RSI 기반 다이버전스 감지
    반환: "BULLISH_DIV" / "BEARISH_DIV" / None
    """
    if len(closes) < period + 15:
        return None
    rsi_vals = [calc_rsi(closes[:i+1], 14) for i in range(len(closes) - period, len(closes))]
    price_slice = closes[-period:]
    price_higher = price_slice[-1] > max(price_slice[:-1])
    rsi_lower    = rsi_vals[-1]    < min(rsi_vals[:-1])
    price_lower  = price_slice[-1] < min(price_slice[:-1])
    rsi_higher   = rsi_vals[-1]    > max(rsi_vals[:-1])
    if price_higher and rsi_lower:  return "BEARISH_DIV"
    if price_lower  and rsi_higher: return "BULLISH_DIV"
    return None


def candle_shape(candle):
    o, h, l, c = get_open(candle), get_high(candle), get_low(candle), get_close(candle)
    body = abs(c - o)
    full = h - l
    if full == 0:
        return "도지"
    ratio = body / full
    if c > o and ratio >= 0.6:  return "강한양봉"
    if c < o and ratio >= 0.6:  return "강한음봉"
    if ratio <= 0.25:           return "도지"
    return "약한양봉" if c > o else "약한음봉"


# ─────────────────────────────────────────────
# 구조 분석
# ─────────────────────────────────────────────

def detect_trend(candles):
    if len(candles) < 50:
        return "SIDEWAYS"
    closes  = [get_close(c) for c in candles]
    current = closes[-1]
    ema20   = calc_ema(closes, 20)
    ema50   = calc_ema(closes, 50)
    rh = max(get_high(c) for c in candles[-10:])
    ph = max(get_high(c) for c in candles[-25:-10])
    rl = min(get_low(c)  for c in candles[-10:])
    pl = min(get_low(c)  for c in candles[-25:-10])
    if current > ema20 > ema50 and rh > ph and rl >= pl: return "UP"
    if current < ema20 < ema50 and rl < pl and rh <= ph: return "DOWN"
    return "SIDEWAYS"


def detect_price_structure(candles, lookback=20):
    if len(candles) < lookback * 2:
        return "UNKNOWN"
    prev = candles[-lookback*2:-lookback]
    curr = candles[-lookback:]
    ph, pl = max(get_high(c) for c in prev), min(get_low(c) for c in prev)
    ch, cl = max(get_high(c) for c in curr), min(get_low(c) for c in curr)
    if ch > ph and cl > pl:  return "HH/HL"
    if ch < ph and cl < pl:  return "LH/LL"
    if ch > ph and cl < pl:  return "HH/LL"
    if ch < ph and cl > pl:  return "LH/HL"
    return "SIDEWAYS"


def detect_range(candles, lookback=40):
    if len(candles) < lookback:
        return False, None, None, None
    recent = candles[-lookback:]
    rh  = max(get_high(c) for c in recent)
    rl  = min(get_low(c)  for c in recent)
    cur = get_close(recent[-1])
    width = (rh - rl) / cur if cur else 999
    if width > 0.035:
        return False, None, rh, rl
    upper = rh - (rh - rl) * 0.25
    lower = rl + (rh - rl) * 0.25
    if cur >= upper:   pos = "TOP"
    elif cur <= lower: pos = "BOTTOM"
    else:              pos = "MIDDLE"
    return True, pos, rh, rl


def find_key_levels(candles, lookback=50):
    if len(candles) < lookback:
        p = get_close(candles[-1]) if candles else 0
        return p, p
    recent = candles[-lookback:]
    return (
        min(get_low(c)  for c in recent[-20:]),
        max(get_high(c) for c in recent[-20:]),
    )


# ─────────────────────────────────────────────
# 점수 계산 (단일 로직 — 모든 메시지 공유)
# ─────────────────────────────────────────────

def calc_scores(candles_15m, candles_1h, candles_4h, candles_1d):
    closes  = [get_close(c) for c in candles_15m]
    volumes = [get_volume(c) for c in candles_15m]
    price   = closes[-1] if closes else 0.0

    ema20  = calc_ema(closes, 20)
    ema50  = calc_ema(closes, 50)
    ema200 = calc_ema(closes, 200)

    rsi_val            = calc_rsi(closes)
    cci_val            = calc_cci(candles_15m)
    macd_state, mv, ms = calc_macd(closes)
    bb                 = calc_bollinger(closes)   # ★ 볼린저밴드
    divergence         = calc_divergence(closes)

    vol     = get_volume(candles_15m[-1]) if candles_15m else 0.0
    avg_vol = avg(volumes[-20:])

    trend_15m = detect_trend(candles_15m)
    trend_1h  = detect_trend(candles_1h)
    trend_4h  = detect_trend(candles_4h)
    trend_1d  = detect_trend(candles_1d)

    is_range, range_pos, range_high, range_low = detect_range(candles_15m)
    support, resistance = find_key_levels(candles_15m)
    structure = detect_price_structure(candles_15m)

    long_score  = 0
    short_score = 0

    # EMA 위치 (30점)
    if price > ema20:    long_score  += 12
    else:                short_score += 12
    if ema20 > ema50:    long_score  += 10
    elif ema20 < ema50:  short_score += 10
    if price > ema200:   long_score  += 8
    else:                short_score += 8

    # RSI (12점)
    if rsi_val >= 55:    long_score  += 12
    elif rsi_val <= 45:  short_score += 12

    # CCI (8점)
    if cci_val >= 100:   long_score  += 8
    elif cci_val <= -50: short_score += 8

    # MACD (10점)
    if macd_state in ("BULLISH", "POSITIVE"):    long_score  += 10
    elif macd_state in ("BEARISH", "NEGATIVE"):  short_score += 10

    # 추세 (32점)
    if trend_15m == "UP":    long_score  += 12
    elif trend_15m == "DOWN": short_score += 12
    if trend_1h == "UP":     long_score  += 12
    elif trend_1h == "DOWN":  short_score += 12
    if trend_4h == "UP":     long_score  += 8
    elif trend_4h == "DOWN":  short_score += 8

    # 거래량 (8점)
    if avg_vol and vol >= avg_vol * 1.2:
        if long_score >= short_score: long_score  += 8
        else:                         short_score += 8

    # 가격 구조 (6점)
    if support    and price <= support    * 1.003: long_score  += 6
    if resistance and price >= resistance * 0.997: short_score += 6

    # ★ 볼린저밴드 (10점)
    if bb["usable"]:
        if bb["signal"] == "OVERSOLD":    long_score  += 10   # 하단 터치 → 과매도
        elif bb["signal"] == "OVERBOUGHT": short_score += 10  # 상단 터치 → 과매수
        elif bb["signal"] == "SQUEEZE":                       # 수축 → 방향 우세쪽 가산
            if long_score >= short_score: long_score  += 5
            else:                         short_score += 5

    # ★ 다이버전스 (5점 보너스)
    if divergence == "BULLISH_DIV":  long_score  += 5
    if divergence == "BEARISH_DIV": short_score += 5

    long_score  = min(long_score,  100)
    short_score = min(short_score, 100)

    if long_score > short_score:
        direction  = "LONG"
        confidence = long_score
        key_level  = resistance
    elif short_score > long_score:
        direction  = "SHORT"
        confidence = short_score
        key_level  = support
    else:
        direction  = "WAIT"
        confidence = 0
        key_level  = None

    return {
        # 방향 / 점수
        "direction":    direction,
        "long_score":   long_score,
        "short_score":  short_score,
        "confidence":   confidence,
        "opposite":     short_score if direction == "LONG" else long_score,
        "score_gap":    abs(long_score - short_score),
        "key_level":    key_level,
        # EMA
        "ema20":        ema20,
        "ema50":        ema50,
        "ema200":       ema200,
        "above_ema20":  price > ema20,
        "below_ema20":  price < ema20,
        # 지표
        "rsi":          rsi_val,
        "cci":          cci_val,
        "macd_state":   macd_state,
        "macd_val":     mv,
        "macd_signal":  ms,
        # ★ 볼린저밴드
        "bb_upper":     bb["upper"],
        "bb_middle":    bb["middle"],
        "bb_lower":     bb["lower"],
        "bb_width":     bb["width"],
        "bb_pct_b":     bb["pct_b"],
        "bb_squeeze":   bb["squeeze"],
        "bb_position":  bb["position"],
        "bb_signal":    bb["signal"],
        # 거래량
        "volume":       vol,
        "avg_volume":   avg_vol,
        "volume_ratio": vol / avg_vol if avg_vol else 0.0,
        # 추세
        "trend_15m":    trend_15m,
        "trend_1h":     trend_1h,
        "trend_4h":     trend_4h,
        "trend_1d":     trend_1d,
        # 구조
        "structure":    structure,
        "divergence":   divergence,
        "is_range":     is_range,
        "range_pos":    range_pos,
        "range_high":   range_high,
        "range_low":    range_low,
        "support":      support,
        "resistance":   resistance,
        # 현재가
        "current_price": price,
        "close_15m":     get_close(candles_15m[-2]) if len(candles_15m) >= 2 else price,
    }


# ─────────────────────────────────────────────
# 일봉/주봉 전용 추가 계산
# ─────────────────────────────────────────────

def calc_daily_extras(candles_1d, candles_1w):
    """
    브리핑 전용 추가 데이터
    일봉/주봉 캔들 형태, 주간 범위 등
    """
    if not candles_1d or len(candles_1d) < 3:
        return {}

    yesterday = candles_1d[-2]
    closes_d  = [get_close(c) for c in candles_1d]
    volumes_d = [get_volume(c) for c in candles_1d]

    avg_vol_20   = avg(volumes_d[-20:])
    y_volume     = get_volume(yesterday)
    volume_ratio = y_volume / avg_vol_20 if avg_vol_20 else 0.0

    # 주봉 기준 주간 범위
    week_days   = candles_1d[-7:]
    week_open   = get_open(week_days[0])
    week_high   = max(get_high(c) for c in week_days)
    week_low    = min(get_low(c)  for c in week_days)
    week_close  = get_close(week_days[-1])
    week_change = pct_change(week_close, week_open)

    # 주봉 캔들 흐름
    day_flows = []
    for i, c in enumerate(week_days[-5:], 1):
        o, cl = get_open(c), get_close(c)
        flow  = "상승" if cl > o else ("하락" if cl < o else "보합")
        day_flows.append(f"{i}일차: {flow} / {candle_shape(c)}")

    weekly_trend = detect_trend(candles_1w) if candles_1w and len(candles_1w) >= 30 else "SIDEWAYS"

    bb_daily = calc_bollinger(closes_d)

    return {
        "yesterday_open":   get_open(yesterday),
        "yesterday_high":   get_high(yesterday),
        "yesterday_low":    get_low(yesterday),
        "yesterday_close":  get_close(yesterday),
        "yesterday_change": pct_change(get_close(yesterday), get_close(candles_1d[-3])),
        "yesterday_shape":  candle_shape(yesterday),
        "daily_volume_ratio": volume_ratio,
        "week_open":        week_open,
        "week_high":        week_high,
        "week_low":         week_low,
        "week_close":       week_close,
        "week_change":      week_change,
        "week_mid":         (week_high + week_low) / 2,
        "day_flows":        day_flows,
        "trend_1w":         weekly_trend,
        "bb_daily_upper":   bb_daily["upper"],
        "bb_daily_lower":   bb_daily["lower"],
        "bb_daily_signal":  bb_daily["signal"],
        "ema20_daily":      calc_ema(closes_d, 20),
        "ema50_daily":      calc_ema(closes_d, 50),
        "rsi_daily":        calc_rsi(closes_d),
        "macd_daily":       calc_macd(closes_d)[0],
    }


# ─────────────────────────────────────────────
# 핵심 진입점 — 모든 파일이 이걸 호출
# ─────────────────────────────────────────────

def analyze(symbol: str, candles_by_tf: dict) -> dict:
    """
    단일 분석 엔진.
    entry_timing / structure_analyzer / daily_weekly_briefing
    전부 이걸 호출한다.
    """
    c15 = candles_by_tf.get("15m", [])
    c1h = candles_by_tf.get("1h",  [])
    c4h = candles_by_tf.get("4h",  [])
    c1d = candles_by_tf.get("1d",  [])
    c1w = candles_by_tf.get("1w",  [])

    scores = calc_scores(c15, c1h, c4h, c1d)
    daily_extras = calc_daily_extras(c1d, c1w)

    return {
        "symbol":    symbol,
        "timestamp": now_kst().strftime("%H:%M"),
        **scores,
        "daily":     daily_extras,   # 브리핑 전용 추가 데이터
    }
