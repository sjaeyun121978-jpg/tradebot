# entry_timing.py
# 통합 신뢰도 체계 적용 버전
# 역할:
# - 진입레이더: 이 종목 봐라
# - PRE-ENTRY: 준비해라, 아직 쏘지 마라
# - PULLBACK ENTRY: 눌림/되돌림 후보를 봐라
# - REAL ENTRY: 조건은 충족됐다, 최종 확인 후 실행 판단

from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

RADAR_MIN_SCORE = 60
PRE_MIN_SCORE = 75
PULLBACK_MIN_SCORE = 90
REAL_MIN_SCORE = 90

MIN_SCORE_GAP = 15
PRE_SCORE_GAP = 20

PRE_LEVEL_DISTANCE = 0.0015
PRE_VOLUME_RATIO = 0.8
REAL_VOLUME_RATIO = 1.2
PULLBACK_DISTANCE = 0.0025

RSI_LONG_MIN = 50
RSI_SHORT_MAX = 50

PRE_SIGNAL_MEMORY = {}
PRE_SIGNAL_EXPIRE_SEC = 60 * 60


def now_kst():
    return datetime.now(KST)


def now_ts():
    return datetime.now().timestamp()


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def avg(values):
    values = [safe_float(v) for v in values if v is not None]
    return sum(values) / len(values) if values else 0


def pct_distance(a, b):
    a = safe_float(a)
    b = safe_float(b)
    if b == 0:
        return 999
    return abs(a - b) / b


def get_latest(candles):
    return candles[-1] if candles else None


def get_closed_15m_candle(candles):
    if not candles:
        return None
    return candles[-2] if len(candles) >= 2 else candles[-1]


def get_close(candle):
    return safe_float(candle.get("close")) if candle else 0


def get_high(candle):
    return safe_float(candle.get("high")) if candle else 0


def get_low(candle):
    return safe_float(candle.get("low")) if candle else 0


def get_volume(candle):
    return safe_float(candle.get("volume")) if candle else 0


def ema(values, period):
    values = [safe_float(v) for v in values]
    if not values:
        return 0
    if len(values) < period:
        return avg(values)

    k = 2 / (period + 1)
    result = values[0]

    for price in values[1:]:
        result = price * k + result * (1 - k)

    return result


def rsi(values, period=14):
    values = [safe_float(v) for v in values]

    if len(values) < period + 1:
        return 50

    gains = []
    losses = []

    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))

    avg_gain = avg(gains[-period:])
    avg_loss = avg(losses[-period:])

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def cci(candles, period=20):
    if len(candles) < period:
        return 0

    target = candles[-period:]
    typical_prices = []

    for c in target:
        tp = (get_high(c) + get_low(c) + get_close(c)) / 3
        typical_prices.append(tp)

    ma = avg(typical_prices)
    mean_dev = avg([abs(tp - ma) for tp in typical_prices])

    if mean_dev == 0:
        return 0

    return (typical_prices[-1] - ma) / (0.015 * mean_dev)


def macd_state(values):
    values = [safe_float(v) for v in values]

    if len(values) < 35:
        return "NEUTRAL"

    ema12 = ema(values, 12)
    ema26 = ema(values, 26)
    macd_value = ema12 - ema26

    recent_macd = []
    for i in range(len(values) - 9, len(values)):
        sub = values[:i + 1]
        recent_macd.append(ema(sub, 12) - ema(sub, 26))

    signal = ema(recent_macd, 9)

    if macd_value > signal and macd_value > 0:
        return "BULLISH"
    if macd_value < signal and macd_value < 0:
        return "BEARISH"
    if macd_value > 0:
        return "POSITIVE"
    if macd_value < 0:
        return "NEGATIVE"

    return "NEUTRAL"


def detect_trend(candles):
    if len(candles) < 50:
        return "SIDEWAYS"

    closes = [get_close(c) for c in candles]
    current = closes[-1]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)

    recent_high = max([get_high(c) for c in candles[-10:]])
    prev_high = max([get_high(c) for c in candles[-25:-10]])

    recent_low = min([get_low(c) for c in candles[-10:]])
    prev_low = min([get_low(c) for c in candles[-25:-10]])

    if current > ema20 > ema50 and recent_high > prev_high and recent_low >= prev_low:
        return "UP"

    if current < ema20 < ema50 and recent_low < prev_low and recent_high <= prev_high:
        return "DOWN"

    return "SIDEWAYS"


def detect_range(candles):
    if len(candles) < 40:
        return False, None, None, None

    recent = candles[-40:]

    range_high = max([get_high(c) for c in recent])
    range_low = min([get_low(c) for c in recent])
    current = get_close(recent[-1])

    width = (range_high - range_low) / current if current else 999

    if width > 0.035:
        return False, None, range_high, range_low

    upper_zone = range_high - ((range_high - range_low) * 0.25)
    lower_zone = range_low + ((range_high - range_low) * 0.25)

    if current >= upper_zone:
        pos = "TOP"
    elif current <= lower_zone:
        pos = "BOTTOM"
    else:
        pos = "MIDDLE"

    return True, pos, range_high, range_low


def find_key_levels(candles):
    if len(candles) < 50:
        price = get_close(get_latest(candles))
        return price, price

    recent = candles[-50:]
    support = min([get_low(c) for c in recent[-20:]])
    resistance = max([get_high(c) for c in recent[-20:]])

    return support, resistance


def get_role_text(alert_type):
    role_map = {
        "ENTRY_RADAR": "📡 진입레이더 → 이 종목 봐라",
        "PRE_ENTRY": "🟡 PRE-ENTRY → 준비해라, 아직 쏘지 마라",
        "PULLBACK_ENTRY": "🟠 PULLBACK ENTRY → 눌림/되돌림 후보를 봐라",
        "REAL_ENTRY": "🔥 REAL ENTRY → 조건은 충족됐다, 최종 확인 후 실행 판단",
        "WAIT": "⏸ WAIT → 아직 매매하지 마라",
    }
    return role_map.get(alert_type, "")


def get_signal_stage(confidence_score, has_trigger=False):
    if has_trigger and confidence_score >= REAL_MIN_SCORE:
        return "REAL_ENTRY"

    if confidence_score >= PULLBACK_MIN_SCORE:
        return "PULLBACK_ENTRY"

    if confidence_score >= PRE_MIN_SCORE:
        return "PRE_ENTRY"

    if confidence_score >= RADAR_MIN_SCORE:
        return "ENTRY_RADAR"

    return "WAIT"


def get_stage_label(confidence_score):
    if confidence_score >= 90:
        return "90% 이상: 실전타점 후보 구간"
    if confidence_score >= 75:
        return "75% 이상: PRE-ENTRY 준비 구간"
    if confidence_score >= 60:
        return "60% 이상: 진입레이더 감시 구간"
    return "60% 미만: 노이즈 구간"


def build_signal(symbol, candles_by_tf):
    candles_15m = candles_by_tf.get("15m", [])
    candles_1h = candles_by_tf.get("1h", [])
    candles_4h = candles_by_tf.get("4h", [])
    candles_1d = candles_by_tf.get("1d", [])

    latest = get_latest(candles_15m)
    closed_15m = get_closed_15m_candle(candles_15m)

    current_price = get_close(latest)
    close_15m = get_close(closed_15m)

    closes_15m = [get_close(c) for c in candles_15m]
    volumes_15m = [get_volume(c) for c in candles_15m]

    ema20 = ema(closes_15m, 20)
    ema50 = ema(closes_15m, 50)
    ema200 = ema(closes_15m, 200)

    current_rsi = rsi(closes_15m, 14)
    current_cci = cci(candles_15m, 20)
    current_macd = macd_state(closes_15m)

    volume = get_volume(latest)
    avg_volume_20 = avg(volumes_15m[-20:])

    trend_15m = detect_trend(candles_15m)
    trend_1h = detect_trend(candles_1h)
    trend_4h = detect_trend(candles_4h)
    trend_1d = detect_trend(candles_1d)

    is_range, range_position, range_high, range_low = detect_range(candles_15m)
    support, resistance = find_key_levels(candles_15m)

    long_score = 0
    short_score = 0
    reasons_long = []
    reasons_short = []

    if current_price > ema20:
        long_score += 12
        reasons_long.append("EMA20 상단")
    else:
        short_score += 12
        reasons_short.append("EMA20 하단")

    if ema20 > ema50:
        long_score += 10
        reasons_long.append("EMA20/50 상승 정렬")
    elif ema20 < ema50:
        short_score += 10
        reasons_short.append("EMA20/50 하락 정렬")

    if current_price > ema200:
        long_score += 8
        reasons_long.append("EMA200 상단")
    else:
        short_score += 8
        reasons_short.append("EMA200 하단")

    if current_rsi >= 55:
        long_score += 12
        reasons_long.append(f"RSI {current_rsi:.2f} 상승 우위")
    elif current_rsi <= 45:
        short_score += 12
        reasons_short.append(f"RSI {current_rsi:.2f} 하락 우위")

    if current_cci >= 100:
        long_score += 8
        reasons_long.append(f"CCI {current_cci:.2f} 강세")
    elif current_cci <= -50:
        short_score += 8
        reasons_short.append(f"CCI {current_cci:.2f} 약세")

    if current_macd in ["BULLISH", "POSITIVE"]:
        long_score += 10
        reasons_long.append("MACD 상방")
    elif current_macd in ["BEARISH", "NEGATIVE"]:
        short_score += 10
        reasons_short.append("MACD 하방")

    if trend_15m == "UP":
        long_score += 12
        reasons_long.append("15M 상승 구조")
    elif trend_15m == "DOWN":
        short_score += 12
        reasons_short.append("15M 하락 구조")

    if trend_1h == "UP":
        long_score += 12
        reasons_long.append("1H 상승 구조")
    elif trend_1h == "DOWN":
        short_score += 12
        reasons_short.append("1H 하락 구조")

    if trend_4h == "UP":
        long_score += 8
        reasons_long.append("4H 상승 구조")
    elif trend_4h == "DOWN":
        short_score += 8
        reasons_short.append("4H 하락 구조")

    if avg_volume_20 and volume >= avg_volume_20 * 1.2:
        if long_score >= short_score:
            long_score += 8
            reasons_long.append("거래량 증가")
        else:
            short_score += 8
            reasons_short.append("거래량 증가")

    if current_price <= support * 1.003:
        long_score += 6
        reasons_long.append("핵심 지지 근접")

    if current_price >= resistance * 0.997:
        short_score += 6
        reasons_short.append("핵심 저항 근접")

    long_score = min(long_score, 100)
    short_score = min(short_score, 100)

    if long_score > short_score:
        direction = "LONG"
        confidence_score = long_score
        opposite_score = short_score
        key_level = resistance
    elif short_score > long_score:
        direction = "SHORT"
        confidence_score = short_score
        opposite_score = long_score
        key_level = support
    else:
        direction = "WAIT"
        confidence_score = 0
        opposite_score = 0
        key_level = None

    score_gap = abs(long_score - short_score)

    return {
        "symbol": symbol,
        "current_price": current_price,
        "close_15m": close_15m,
        "direction": direction,
        "long_score": long_score,
        "short_score": short_score,
        "confidence_score": confidence_score,
        "opposite_score": opposite_score,
        "score_gap": score_gap,
        "stage_label": get_stage_label(confidence_score),
        "ema20": ema20,
        "ema50": ema50,
        "ema200": ema200,
        "below_ema20": current_price < ema20,
        "above_ema20": current_price > ema20,
        "rsi": current_rsi,
        "cci": current_cci,
        "macd_state": current_macd,
        "volume": volume,
        "avg_volume_20": avg_volume_20,
        "trend_15m": trend_15m,
        "trend_1h": trend_1h,
        "trend_4h": trend_4h,
        "trend_1d": trend_1d,
        "is_range": is_range,
        "range_position": range_position,
        "range_high": range_high,
        "range_low": range_low,
        "support": support,
        "resistance": resistance,
        "key_level": key_level,
        "reasons_long": reasons_long,
        "reasons_short": reasons_short,
    }


def is_valid_pre_entry(signal):
    direction = signal.get("direction")
    confidence_score = signal.get("confidence_score", 0)
    score_gap = signal.get("score_gap", 0)

    current_price = signal.get("current_price")
    key_level = signal.get("key_level")
    volume = signal.get("volume")
    avg_volume_20 = signal.get("avg_volume_20")
    trend_15m = signal.get("trend_15m")
    trend_1h = signal.get("trend_1h")
    is_range = signal.get("is_range", False)
    range_position = signal.get("range_position")

    if direction == "WAIT":
        return False, "방향 미확정"

    if confidence_score < PRE_MIN_SCORE:
        return False, "신뢰도 75% 미만"

    if score_gap < PRE_SCORE_GAP:
        return False, "롱/숏 점수 차이 20% 미만"

    if direction == "SHORT":
        if not (trend_15m == "DOWN" and (trend_1h == "DOWN" or signal.get("below_ema20"))):
            return False, "하락 추세 정렬 부족"

        if key_level and current_price:
            if pct_distance(current_price, key_level) > PRE_LEVEL_DISTANCE:
                return False, "핵심 지지선과 거리 0.15% 초과"

        if avg_volume_20 and volume < avg_volume_20 * PRE_VOLUME_RATIO:
            return False, "거래량 최소 조건 부족"

        if is_range and range_position != "TOP":
            return False, "박스권 숏 예외 조건 아님"

    if direction == "LONG":
        if not (trend_15m == "UP" and (trend_1h == "UP" or signal.get("above_ema20"))):
            return False, "상승 추세 정렬 부족"

        if key_level and current_price:
            if pct_distance(current_price, key_level) > PRE_LEVEL_DISTANCE:
                return False, "핵심 저항선과 거리 0.15% 초과"

        if avg_volume_20 and volume < avg_volume_20 * PRE_VOLUME_RATIO:
            return False, "거래량 최소 조건 부족"

        if is_range and range_position != "BOTTOM":
            return False, "박스권 롱 예외 조건 아님"

    return True, "PRE-ENTRY 유효"


def remember_pre_signal(signal):
    symbol = signal.get("symbol")
    direction = signal.get("direction")

    if not symbol or not direction:
        return

    PRE_SIGNAL_MEMORY[symbol] = {
        "ts": now_ts(),
        "signal": signal.copy(),
        "direction": direction,
    }


def get_active_pre_signal(symbol):
    item = PRE_SIGNAL_MEMORY.get(symbol)

    if not item:
        return None

    if now_ts() - item.get("ts", 0) > PRE_SIGNAL_EXPIRE_SEC:
        PRE_SIGNAL_MEMORY.pop(symbol, None)
        return None

    return item.get("signal")


def is_real_entry_from_pre(pre_signal, current_signal):
    if not pre_signal:
        return False, "활성 PRE-ENTRY 없음"

    direction = pre_signal.get("direction")

    if current_signal.get("direction") != direction:
        return False, "PRE 방향과 현재 방향 불일치"

    if current_signal.get("confidence_score", 0) < REAL_MIN_SCORE:
        return False, "REAL 신뢰도 90% 미만"

    close_15m = current_signal.get("close_15m")
    key_level = pre_signal.get("key_level")
    volume = current_signal.get("volume")
    avg_volume_20 = current_signal.get("avg_volume_20")
    rsi_value = current_signal.get("rsi")
    macd = current_signal.get("macd_state")
    score_gap = current_signal.get("score_gap", 0)

    if not key_level:
        return False, "핵심 가격 없음"

    if score_gap < PRE_SCORE_GAP:
        return False, "점수 우위 유지 실패"

    if direction == "SHORT":
        if close_15m >= key_level:
            return False, "15분봉 종가 지지선 이탈 미확정"
        if avg_volume_20 and volume < avg_volume_20 * REAL_VOLUME_RATIO:
            return False, "REAL 거래량 부족"
        if rsi_value >= RSI_SHORT_MAX:
            return False, "RSI 50 아래 미충족"
        if macd not in ["BEARISH", "NEGATIVE"]:
            return False, "MACD 하방 미충족"

    if direction == "LONG":
        if close_15m <= key_level:
            return False, "15분봉 종가 저항선 돌파 미확정"
        if avg_volume_20 and volume < avg_volume_20 * REAL_VOLUME_RATIO:
            return False, "REAL 거래량 부족"
        if rsi_value <= RSI_LONG_MIN:
            return False, "RSI 50 위 미충족"
        if macd not in ["BULLISH", "POSITIVE"]:
            return False, "MACD 상방 미충족"

    return True, "REAL ENTRY 확정"


def is_pullback_entry(signal):
    direction = signal.get("direction")
    confidence_score = signal.get("confidence_score", 0)
    current_price = signal.get("current_price")
    ema20 = signal.get("ema20")
    trend_15m = signal.get("trend_15m")
    trend_1h = signal.get("trend_1h")
    score_gap = signal.get("score_gap", 0)

    if confidence_score < PULLBACK_MIN_SCORE:
        return False, "PULLBACK 신뢰도 90% 미만"

    if score_gap < PRE_SCORE_GAP:
        return False, "점수 차이 부족"

    if direction == "LONG":
        if not (trend_15m == "UP" and trend_1h in ["UP", "SIDEWAYS"]):
            return False, "상승 눌림 구조 아님"

        if pct_distance(current_price, ema20) <= PULLBACK_DISTANCE and current_price >= ema20:
            return True, "상승 추세 EMA20 눌림"

    if direction == "SHORT":
        if not (trend_15m == "DOWN" and trend_1h in ["DOWN", "SIDEWAYS"]):
            return False, "하락 되돌림 구조 아님"

        if pct_distance(current_price, ema20) <= PULLBACK_DISTANCE and current_price <= ema20:
            return True, "하락 추세 EMA20 되돌림"

    return False, "PULLBACK 조건 미충족"


def make_radar_message(signal, reason):
    return f"""📡 {signal.get('symbol')} 진입레이더
→ 이 종목 봐라

신뢰도: {signal.get('confidence_score')}%
구간: {signal.get('stage_label')}

상태: {signal.get('direction')}
현재가: {signal.get('current_price'):.2f}

LONG 점수: {signal.get('long_score')}%
SHORT 점수: {signal.get('short_score')}%
점수차이: {signal.get('score_gap')}%

15M 추세: {signal.get('trend_15m')}
1H 추세: {signal.get('trend_1h')}
RSI: {signal.get('rsi'):.2f}
CCI: {signal.get('cci'):.2f}
MACD: {signal.get('macd_state')}

판단:
{reason}

※ 진입 알림 아님. 감시 시작 알림.
"""


def make_pre_entry_message(signal, reason):
    direction = signal.get("direction")
    current_price = signal.get("current_price")
    key_level = signal.get("key_level")

    if direction == "SHORT":
        trigger_text = f"15분봉 종가 {key_level:.2f} 이탈"
        stop_text = f"{signal.get('resistance'):.2f}"
        tp1 = current_price * 0.995
        tp2 = current_price * 0.990
    else:
        trigger_text = f"15분봉 종가 {key_level:.2f} 돌파"
        stop_text = f"{signal.get('support'):.2f}"
        tp1 = current_price * 1.005
        tp2 = current_price * 1.010

    volume_ratio = signal.get("volume") / signal.get("avg_volume_20") if signal.get("avg_volume_20") else 0
    level_distance = pct_distance(current_price, key_level) * 100 if key_level else 0

    return f"""🚨 {signal.get('symbol')} 실전타점

🟡 PRE-ENTRY
→ 준비해라, 아직 쏘지 마라

신뢰도: {signal.get('confidence_score')}%
구간: {signal.get('stage_label')}

방향: {direction}
현재가: {current_price:.2f}

LONG 점수: {signal.get('long_score')}%
SHORT 점수: {signal.get('short_score')}%
점수차이: {signal.get('score_gap')}%

✅ 신뢰도 75% 이상
✅ 점수차이 20% 이상
✅ 핵심 가격 근접 {level_distance:.2f}%
✅ 거래량 {volume_ratio:.2f}배

📌 핵심 트리거:
{trigger_text}

🛑 손절 기준:
{stop_text}

🎯 1차 익절:
{tp1:.2f}

🎯 2차 익절:
{tp2:.2f}

⚠️ 아직 REAL ENTRY 아님
⚠️ 가격 트리거 + 거래량 + 15분봉 종가 확정 전까지 대기

※ 자동진입 아님. 준비 알림.
"""


def make_pullback_message(signal, reason):
    direction = signal.get("direction")
    current_price = signal.get("current_price")
    ema20 = signal.get("ema20")

    if direction == "SHORT":
        stop = current_price * 1.004
        tp1 = current_price * 0.996
        tp2 = current_price * 0.992
    else:
        stop = current_price * 0.996
        tp1 = current_price * 1.004
        tp2 = current_price * 1.008

    return f"""🟠 {signal.get('symbol')} PULLBACK ENTRY
→ 눌림/되돌림 후보를 봐라

신뢰도: {signal.get('confidence_score')}%
구간: {signal.get('stage_label')}

방향: {direction}
현재가: {current_price:.2f}
EMA20: {ema20:.2f}

✅ {reason}

📌 의미:
추세 진행 중 눌림 또는 되돌림 후보

🛑 손절:
{stop:.2f}

🎯 1차 익절:
{tp1:.2f}

🎯 2차 익절:
{tp2:.2f}

⚠️ 자동진입 아님. 눌림 후보 확인 알림.
"""


def make_real_entry_message(signal, reason, pre_signal):
    direction = signal.get("direction")
    current_price = signal.get("current_price")
    key_level = pre_signal.get("key_level")

    volume_ratio = signal.get("volume") / signal.get("avg_volume_20") if signal.get("avg_volume_20") else 0

    if direction == "SHORT":
        stop = pre_signal.get("resistance") or current_price * 1.005
        tp1 = current_price * 0.995
        tp2 = current_price * 0.990
        trigger = f"지지선 {key_level:.2f} 이탈 확정"
    else:
        stop = pre_signal.get("support") or current_price * 0.995
        tp1 = current_price * 1.005
        tp2 = current_price * 1.010
        trigger = f"저항선 {key_level:.2f} 돌파 확정"

    return f"""🔥 {signal.get('symbol')} REAL ENTRY
→ 조건은 충족됐다, 최종 확인 후 실행 판단

신뢰도: {signal.get('confidence_score')}%
구간: 90% 이상 + 가격 트리거 발생

방향: {direction}
현재가: {current_price:.2f}

✅ PRE-ENTRY 선행 존재
✅ {trigger}
✅ 15분봉 종가 확정
✅ 거래량 {volume_ratio:.2f}배
✅ RSI 조건 충족
✅ MACD 방향 충족
✅ 점수 우위 유지

🚀 진입 판단:
REAL ENTRY 조건 충족

🛑 손절:
{stop:.2f}

🎯 1차 익절:
{tp1:.2f}

🎯 2차 익절:
{tp2:.2f}

⚠️ 자동진입 아님. 최종 체결은 직접 확인.
"""


def make_wait_message(signal, reason):
    return f"""⏸ {signal.get('symbol')} WAIT
→ 아직 매매하지 마라

신뢰도: {signal.get('confidence_score')}%
구간: {signal.get('stage_label')}

현재가: {signal.get('current_price'):.2f}

LONG 점수: {signal.get('long_score')}%
SHORT 점수: {signal.get('short_score')}%
점수차이: {signal.get('score_gap')}%

대기 사유:
{reason}

📌 판단:
방향 우위가 부족하거나 조건 완성 전이다.

※ 자동진입 아님. 대기 알림.
"""


def analyze_entry_timing(symbol, candles_by_tf, structure_result=None):
    signal = build_signal(symbol, candles_by_tf)

    direction = signal.get("direction")
    confidence_score = signal.get("confidence_score", 0)
    score_gap = signal.get("score_gap", 0)

    if direction == "WAIT" or confidence_score < RADAR_MIN_SCORE or score_gap < MIN_SCORE_GAP:
        return {
            "type": "WAIT",
            "alert_type": "WAIT",
            "direction": "WAIT",
            "message": make_wait_message(signal, "신뢰도 60% 미만 또는 점수차이 15% 미만"),
            **signal,
        }

    active_pre = get_active_pre_signal(symbol)
    real_ok, real_reason = is_real_entry_from_pre(active_pre, signal)

    if real_ok:
        PRE_SIGNAL_MEMORY.pop(symbol, None)
        return [{
            "type": "REAL_ENTRY",
            "alert_type": "REAL_ENTRY",
            "direction": direction,
            "message": make_real_entry_message(signal, real_reason, active_pre),
            "reason": real_reason,
            **signal,
        }]

    results = []

    pullback_ok, pullback_reason = is_pullback_entry(signal)
    if pullback_ok:
        results.append({
            "type": "PULLBACK_ENTRY",
            "alert_type": "PULLBACK_ENTRY",
            "direction": direction,
            "message": make_pullback_message(signal, pullback_reason),
            "reason": pullback_reason,
            **signal,
        })

    pre_ok, pre_reason = is_valid_pre_entry(signal)
    if pre_ok:
        remember_pre_signal(signal)
        results.append({
            "type": "PRE_ENTRY",
            "alert_type": "PRE_ENTRY",
            "direction": direction,
            "message": make_pre_entry_message(signal, pre_reason),
            "reason": pre_reason,
            **signal,
        })

    if results:
        return results

    return {
        "type": "ENTRY_RADAR",
        "alert_type": "ENTRY_RADAR",
        "direction": direction,
        "message": make_radar_message(signal, "방향은 감지됐지만 PRE/REAL 조건은 아직 미완성"),
        "reason": "진입레이더 구간",
        **signal,
    }


def run_entry_radar(symbol, candles_by_tf, structure_result=None):
    signal = build_signal(symbol, candles_by_tf)

    confidence_score = signal.get("confidence_score", 0)
    score_gap = signal.get("score_gap", 0)

    if confidence_score < RADAR_MIN_SCORE:
        radar_state = "WAIT"
        reason = "신뢰도 60% 미만"
    elif score_gap < MIN_SCORE_GAP:
        radar_state = "WAIT"
        reason = "롱/숏 점수 차이 15% 미만"
    elif signal.get("is_range") and signal.get("range_position") == "MIDDLE":
        radar_state = "WAIT"
        reason = "박스권 중앙"
    else:
        radar_state = signal.get("direction")
        reason = "방향 후보 감지"

    return {
        "type": "ENTRY_RADAR",
        "alert_type": "ENTRY_RADAR",
        "direction": radar_state,
        "message": make_radar_message(signal, reason),
        "reason": reason,
        **signal,
    }


def run_entry_timing(symbol, candles_by_tf, structure_result=None):
    return analyze_entry_timing(symbol, candles_by_tf, structure_result)


def check_entry(symbol, candles_by_tf, structure_result=None):
    return analyze_entry_timing(symbol, candles_by_tf, structure_result)


def analyze(symbol, candles_by_tf, structure_result=None):
    return analyze_entry_timing(symbol, candles_by_tf, structure_result)


def entry_radar(symbol, candles_by_tf, structure_result=None):
    return run_entry_radar(symbol, candles_by_tf, structure_result)


def analyze_radar(symbol, candles_by_tf, structure_result=None):
    return run_entry_radar(symbol, candles_by_tf, structure_result)


def check_radar(symbol, candles_by_tf, structure_result=None):
    return run_entry_radar(symbol, candles_by_tf, structure_result)
