# structure_analyzer.py
# 단일 분석 엔진 — 모든 메시지가 이 파일의 데이터를 공유
# 분석은 여기서 1번만 수행, 메시지별로 조건만 추가

from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))


# ─────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────

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


def get_close(c):  return safe_float(c.get("close")) if c else 0.0
def get_high(c):   return safe_float(c.get("high"))  if c else 0.0
def get_low(c):    return safe_float(c.get("low"))   if c else 0.0
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
    ma = avg(tps)
    md = avg([abs(tp - ma) for tp in tps])
    return (tps[-1] - ma) / (0.015 * md) if md != 0 else 0.0


def calc_macd(values):
    vals = [safe_float(v) for v in values]
    if len(vals) < 35:
        return "NEUTRAL", 0.0, 0.0
    ema12 = calc_ema(vals, 12)
    ema26 = calc_ema(vals, 26)
    macd_val = ema12 - ema26
    recent = [calc_ema(vals[:i+1], 12) - calc_ema(vals[:i+1], 26)
              for i in range(len(vals) - 9, len(vals))]
    signal = calc_ema(recent, 9)
    if macd_val > signal and macd_val > 0:
        state = "BULLISH"
    elif macd_val < signal and macd_val < 0:
        state = "BEARISH"
    elif macd_val > 0:
        state = "POSITIVE"
    elif macd_val < 0:
        state = "NEGATIVE"
    else:
        state = "NEUTRAL"
    return state, macd_val, signal


def detect_divergence(closes, rsi_values, lookback=5):
    """
    가격 구조와 RSI를 비교해 다이버전스 감지
    반환: "BULLISH_DIV" / "BEARISH_DIV" / None
    """
    if len(closes) < lookback + 1 or len(rsi_values) < lookback + 1:
        return None
    recent_closes = closes[-lookback:]
    recent_rsi    = rsi_values[-lookback:]
    price_higher  = recent_closes[-1] > max(recent_closes[:-1])
    rsi_lower     = recent_rsi[-1]    < min(recent_rsi[:-1])
    price_lower   = recent_closes[-1] < min(recent_closes[:-1])
    rsi_higher    = recent_rsi[-1]    > max(recent_rsi[:-1])
    if price_higher and rsi_lower:
        return "BEARISH_DIV"
    if price_lower and rsi_higher:
        return "BULLISH_DIV"
    return None


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
    if current > ema20 > ema50 and rh > ph and rl >= pl:
        return "UP"
    if current < ema20 < ema50 and rl < pl and rh <= ph:
        return "DOWN"
    return "SIDEWAYS"


def detect_price_structure(candles, lookback=20):
    """
    HH/HL = 상승구조
    LH/LL = 하락구조
    """
    if len(candles) < lookback * 2:
        return "UNKNOWN"
    prev = candles[-lookback*2:-lookback]
    curr = candles[-lookback:]
    ph = max(get_high(c) for c in prev)
    pl = min(get_low(c)  for c in prev)
    ch = max(get_high(c) for c in curr)
    cl = min(get_low(c)  for c in curr)
    hh = ch > ph
    hl = cl > pl
    lh = ch < ph
    ll = cl < pl
    if hh and hl:   return "HH/HL"
    if lh and ll:   return "LH/LL"
    if hh and ll:   return "HH/LL"
    if lh and hl:   return "LH/HL"
    return "SIDEWAYS"


def detect_range(candles, lookback=40):
    if len(candles) < lookback:
        return False, None, None, None
    recent = candles[-lookback:]
    rh = max(get_high(c) for c in recent)
    rl = min(get_low(c)  for c in recent)
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
    support    = min(get_low(c)  for c in recent[-20:])
    resistance = max(get_high(c) for c in recent[-20:])
    return support, resistance


# ─────────────────────────────────────────────
# 점수 계산 (단일 로직 — 모든 메시지 공유)
# ─────────────────────────────────────────────

def calc_scores(candles_15m, candles_1h, candles_4h, candles_1d):
    closes   = [get_close(c) for c in candles_15m]
    volumes  = [get_volume(c) for c in candles_15m]
    price    = closes[-1] if closes else 0

    ema20  = calc_ema(closes, 20)
    ema50  = calc_ema(closes, 50)
    ema200 = calc_ema(closes, 200)

    rsi_val    = calc_rsi(closes)
    cci_val    = calc_cci(candles_15m)
    macd_state, macd_val, macd_sig = calc_macd(closes)

    vol     = get_volume(candles_15m[-1]) if candles_15m else 0
    avg_vol = avg(volumes[-20:])

    trend_15m = detect_trend(candles_15m)
    trend_1h  = detect_trend(candles_1h)
    trend_4h  = detect_trend(candles_4h)
    trend_1d  = detect_trend(candles_1d)

    is_range, range_pos, range_high, range_low = detect_range(candles_15m)
    support, resistance = find_key_levels(candles_15m)
    structure = detect_price_structure(candles_15m)

    # RSI 시계열로 다이버전스 계산
    rsi_series = [calc_rsi(closes[:i+15], 14) for i in range(max(0, len(closes)-10), len(closes))]
    divergence = detect_divergence(closes[-10:], rsi_series)

    long_score  = 0
    short_score = 0

    # EMA 위치 (30점)
    if price > ema20:   long_score  += 12
    else:               short_score += 12
    if ema20 > ema50:   long_score  += 10
    elif ema20 < ema50: short_score += 10
    if price > ema200:  long_score  += 8
    else:               short_score += 8

    # RSI (12점)
    if rsi_val >= 55:   long_score  += 12
    elif rsi_val <= 45: short_score += 12

    # CCI (8점)
    if cci_val >= 100:  long_score  += 8
    elif cci_val <= -50: short_score += 8

    # MACD (10점)
    if macd_state in ("BULLISH", "POSITIVE"):   long_score  += 10
    elif macd_state in ("BEARISH", "NEGATIVE"): short_score += 10

    # 추세 (32점)
    if trend_15m == "UP":   long_score  += 12
    elif trend_15m == "DOWN": short_score += 12
    if trend_1h == "UP":    long_score  += 12
    elif trend_1h == "DOWN":  short_score += 12
    if trend_4h == "UP":    long_score  += 8
    elif trend_4h == "DOWN":  short_score += 8

    # 거래량 (8점)
    if avg_vol and vol >= avg_vol * 1.2:
        if long_score >= short_score: long_score  += 8
        else:                         short_score += 8

    # 가격 구조 (6점)
    if support and price <= support * 1.003:    long_score  += 6
    if resistance and price >= resistance * 0.997: short_score += 6

    # 다이버전스 (5점 보너스 — 모든 메시지 동일 데이터)
    if divergence == "BULLISH_DIV":  long_score  += 5
    if divergence == "BEARISH_DIV": short_score += 5

    long_score  = min(long_score, 100)
    short_score = min(short_score, 100)

    if long_score > short_score:
        direction   = "LONG"
        confidence  = long_score
        opposite    = short_score
        key_level   = resistance
    elif short_score > long_score:
        direction   = "SHORT"
        confidence  = short_score
        opposite    = long_score
        key_level   = support
    else:
        direction   = "WAIT"
        confidence  = 0
        opposite    = 0
        key_level   = None

    return {
        "direction":   direction,
        "long_score":  long_score,
        "short_score": short_score,
        "confidence":  confidence,
        "opposite":    opposite,
        "score_gap":   abs(long_score - short_score),
        "key_level":   key_level,
        "ema20":       ema20,
        "ema50":       ema50,
        "ema200":      ema200,
        "rsi":         rsi_val,
        "cci":         cci_val,
        "macd_state":  macd_state,
        "macd_val":    macd_val,
        "macd_signal": macd_sig,
        "volume":      vol,
        "avg_volume":  avg_vol,
        "trend_15m":   trend_15m,
        "trend_1h":    trend_1h,
        "trend_4h":    trend_4h,
        "trend_1d":    trend_1d,
        "is_range":    is_range,
        "range_pos":   range_pos,
        "range_high":  range_high,
        "range_low":   range_low,
        "support":     support,
        "resistance":  resistance,
        "structure":   structure,
        "divergence":  divergence,
        "above_ema20": price > ema20,
        "below_ema20": price < ema20,
        "current_price": price,
        "close_15m": get_close(candles_15m[-2]) if len(candles_15m) >= 2 else price,
    }


# ─────────────────────────────────────────────
# 핵심 진입점 — 모든 파일이 이걸 호출
# ─────────────────────────────────────────────

def analyze(symbol: str, candles_by_tf: dict) -> dict:
    """
    단일 분석 엔진.
    entry_timing, trade_logic, analyzers, briefing 전부 이걸 호출.
    반환값은 모든 메시지가 공유하는 공통 데이터.
    """
    c15 = candles_by_tf.get("15m", [])
    c1h = candles_by_tf.get("1h",  [])
    c4h = candles_by_tf.get("4h",  [])
    c1d = candles_by_tf.get("1d",  [])

    scores = calc_scores(c15, c1h, c4h, c1d)

    return {
        "symbol":    symbol,
        "timestamp": datetime.now(KST).strftime("%H:%M"),
        **scores,
    }
