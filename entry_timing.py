# entry_timing.py
# PRE-ENTRY 정확도 강화 + PRE → REAL ENTRY 전환 로직
# 기존 기능 유지 목적:
# 1. 진입 레이더
# 2. PRE-ENTRY
# 3. PULLBACK ENTRY
# 4. REAL ENTRY
# 5. 롱/숏 양방향 점수 판단
# 6. 박스권 WAIT 처리
# 7. 점수 차이 미달 시 진입 금지
# 8. 같은 방향 알림 제한은 main.py에서 처리

from datetime import datetime, timezone, timedelta
import math

KST = timezone(timedelta(hours=9))

# =========================
# 설정값
# =========================

MIN_PRE_SCORE = 75
MIN_SCORE_GAP = 20

PRE_LEVEL_DISTANCE = 0.0015      # 0.15%
PRE_VOLUME_RATIO = 0.8           # 최근 20봉 평균의 0.8배 이상

REAL_VOLUME_RATIO = 1.2          # 최근 20봉 평균의 1.2배 이상
PULLBACK_DISTANCE = 0.0025       # 0.25%

RSI_LONG_MIN = 50
RSI_SHORT_MAX = 50

PRE_SIGNAL_MEMORY = {}
PRE_SIGNAL_EXPIRE_SEC = 60 * 60  # 1시간


# =========================
# 기본 유틸
# =========================

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


def pct_distance(a, b):
    a = safe_float(a)
    b = safe_float(b)

    if b == 0:
        return 999

    return abs(a - b) / b


def get_latest(candles):
    if not candles:
        return None
    return candles[-1]


def get_closed_15m_candle(candles):
    if not candles:
        return None

    if len(candles) >= 2:
        return candles[-2]

    return candles[-1]


def get_close(candle):
    if candle is None:
        return None
    return safe_float(candle.get("close"))


def get_high(candle):
    if candle is None:
        return None
    return safe_float(candle.get("high"))


def get_low(candle):
    if candle is None:
        return None
    return safe_float(candle.get("low"))


def get_volume(candle):
    if candle is None:
        return None
    return safe_float(candle.get("volume"))


def avg(values):
    values = [safe_float(v) for v in values if v is not None]
    if not values:
        return 0
    return sum(values) / len(values)


# =========================
# 지표 계산
# =========================

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

    latest_tp = typical_prices[-1]
    return (latest_tp - ma) / (0.015 * mean_dev)


def macd_state(values):
    values = [safe_float(v) for v in values]

    if len(values) < 35:
        return "NEUTRAL"

    ema12 = ema(values, 12)
    ema26 = ema(values, 26)
    macd_value = ema12 - ema26

    recent = values[-9:]
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


# =========================
# 구조 판단
# =========================

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
    highs = [get_high(c) for c in recent]
    lows = [get_low(c) for c in recent]
    closes = [get_close(c) for c in recent]

    range_high = max(highs)
    range_low = min(lows)
    current = closes[-1]

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
        latest = get_latest(candles)
        price = get_close(latest)
        return price, price

    recent = candles[-50:]

    support = min([get_low(c) for c in recent[-20:]])
    resistance = max([get_high(c) for c in recent[-20:]])

    return support, resistance


# =========================
# 점수 계산
# =========================

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
        reasons_short.append("EMA20/50 하단")

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
        reasons_long.append(f"CCI {current_cci:.2f} 양수 강세")
    elif current_cci <= -50:
        short_score += 8
        reasons_short.append(f"CCI {current_cci:.2f} 음수")

    if current_macd in ["BULLISH", "POSITIVE"]:
        long_score += 10
        reasons_long.append("MACD 상방")
    elif current_macd in ["BEARISH", "NEGATIVE"]:
        short_score += 10
        reasons_short.append("MACD 하방")

    if trend_15m == "UP":
        long_score += 12
        reasons_long.append("단기 상승 구조")
    elif trend_15m == "DOWN":
        short_score += 12
        reasons_short.append("단기 하락 구조")

    if trend_1h == "UP":
        long_score += 12
        reasons_long.append("1H 상승 구조")
    elif trend_1h == "DOWN":
        short_score += 12
        reasons_short.append("단기/1H 하락 구조")

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
        key_level = resistance
    elif short_score > long_score:
        direction = "SHORT"
        key_level = support
    else:
        direction = "WAIT"
        key_level = None

    return {
        "symbol": symbol,
        "current_price": current_price,
        "close_15m": close_15m,
        "direction": direction,
        "long_score": long_score,
        "short_score": short_score,
        "score_gap": abs(long_score - short_score),
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


# =========================
# PRE-ENTRY 필터
# =========================

def is_valid_pre_entry(signal):
    direction = signal.get("direction")
    long_score = signal.get("long_score", 0)
    short_score = signal.get("short_score", 0)
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

    if signal.get("score_gap", 0) < MIN_SCORE_GAP:
        return False, "롱/숏 점수 차이 20% 미만"

    if direction == "SHORT":
        if short_score < MIN_PRE_SCORE:
            return False, "SHORT 점수 75% 미만"

        if short_score - long_score < MIN_SCORE_GAP:
            return False, "SHORT 우위 점수 부족"

        if not (trend_15m == "DOWN" and (trend_1h == "DOWN" or signal.get("below_ema20"))):
            return False, "하락 추세 정렬 부족"

        if key_level and current_price:
            distance = pct_distance(current_price, key_level)
            if distance > PRE_LEVEL_DISTANCE:
                return False, "핵심 지지선과 거리 0.15% 초과"

        if avg_volume_20 and volume < avg_volume_20 * PRE_VOLUME_RATIO:
            return False, "거래량 최소 조건 부족"

        if is_range and range_position != "TOP":
            return False, "박스권 숏 예외 조건 아님"

    if direction == "LONG":
        if long_score < MIN_PRE_SCORE:
            return False, "LONG 점수 75% 미만"

        if long_score - short_score < MIN_SCORE_GAP:
            return False, "LONG 우위 점수 부족"

        if not (trend_15m == "UP" and (trend_1h == "UP" or signal.get("above_ema20"))):
            return False, "상승 추세 정렬 부족"

        if key_level and current_price:
            distance = pct_distance(current_price, key_level)
            if distance > PRE_LEVEL_DISTANCE:
                return False, "핵심 저항선과 거리 0.15% 초과"

        if avg_volume_20 and volume < avg_volume_20 * PRE_VOLUME_RATIO:
            return False, "거래량 최소 조건 부족"

        if is_range and range_position != "BOTTOM":
            return False, "박스권 롱 예외 조건 아님"

    return True, "PRE-ENTRY 유효"


# =========================
# PRE → REAL 전환
# =========================

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

    close_15m = current_signal.get("close_15m")
    key_level = pre_signal.get("key_level")
    volume = current_signal.get("volume")
    avg_volume_20 = current_signal.get("avg_volume_20")
    rsi_value = current_signal.get("rsi")
    macd = current_signal.get("macd_state")
    long_score = current_signal.get("long_score", 0)
    short_score = current_signal.get("short_score", 0)

    if not key_level:
        return False, "핵심 가격 없음"

    if direction == "SHORT":
        if close_15m >= key_level:
            return False, "15분봉 종가 지지선 이탈 미확정"

        if avg_volume_20 and volume < avg_volume_20 * REAL_VOLUME_RATIO:
            return False, "REAL 거래량 부족"

        if rsi_value >= RSI_SHORT_MAX:
            return False, "RSI 50 아래 미충족"

        if macd not in ["BEARISH", "NEGATIVE"]:
            return False, "MACD 하방 미충족"

        if short_score - long_score < MIN_SCORE_GAP:
            return False, "숏 우위 점수 유지 실패"

    if direction == "LONG":
        if close_15m <= key_level:
            return False, "15분봉 종가 저항선 돌파 미확정"

        if avg_volume_20 and volume < avg_volume_20 * REAL_VOLUME_RATIO:
            return False, "REAL 거래량 부족"

        if rsi_value <= RSI_LONG_MIN:
            return False, "RSI 50 위 미충족"

        if macd not in ["BULLISH", "POSITIVE"]:
            return False, "MACD 상방 미충족"

        if long_score - short_score < MIN_SCORE_GAP:
            return False, "롱 우위 점수 유지 실패"

    return True, "REAL ENTRY 확정"


# =========================
# PULLBACK ENTRY
# =========================

def is_pullback_entry(signal):
    direction = signal.get("direction")
    current_price = signal.get("current_price")
    ema20 = signal.get("ema20")
    trend_15m = signal.get("trend_15m")
    trend_1h = signal.get("trend_1h")
    long_score = signal.get("long_score", 0)
    short_score = signal.get("short_score", 0)

    if direction == "LONG":
        if long_score < MIN_PRE_SCORE:
            return False, "LONG 점수 부족"

        if long_score - short_score < MIN_SCORE_GAP:
            return False, "LONG 점수 차이 부족"

        if not (trend_15m == "UP" and trend_1h in ["UP", "SIDEWAYS"]):
            return False, "상승 눌림 구조 아님"

        if pct_distance(current_price, ema20) <= PULLBACK_DISTANCE and current_price >= ema20:
            return True, "상승 추세 EMA20 눌림"

    if direction == "SHORT":
        if short_score < MIN_PRE_SCORE:
            return False, "SHORT 점수 부족"

        if short_score - long_score < MIN_SCORE_GAP:
            return False, "SHORT 점수 차이 부족"

        if not (trend_15m == "DOWN" and trend_1h in ["DOWN", "SIDEWAYS"]):
            return False, "하락 되돌림 구조 아님"

        if pct_distance(current_price, ema20) <= PULLBACK_DISTANCE and current_price <= ema20:
            return True, "하락 추세 EMA20 되돌림"

    return False, "PULLBACK 조건 미충족"


# =========================
# 메시지 생성
# =========================

def format_check(ok, text):
    return f"✅ {text}" if ok else f"❌ {text}"


def make_pre_entry_message(signal, reason):
    direction = signal.get("direction")
    current_price = signal.get("current_price")
    long_score = signal.get("long_score", 0)
    short_score = signal.get("short_score", 0)
    key_level = signal.get("key_level")
    volume = signal.get("volume")
    avg_volume_20 = signal.get("avg_volume_20")
    rsi_value = signal.get("rsi")
    cci_value = signal.get("cci")
    trend_15m = signal.get("trend_15m")
    trend_1h = signal.get("trend_1h")
    is_range = signal.get("is_range")
    range_position = signal.get("range_position")

    score = short_score if direction == "SHORT" else long_score
    opposite = long_score if direction == "SHORT" else short_score

    volume_ratio = volume / avg_volume_20 if avg_volume_20 else 0
    level_distance = pct_distance(current_price, key_level) * 100 if key_level else 0

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

    msg = f"""🚨 {signal.get('symbol')} 실전 타점

🟡 PRE-ENTRY

방향: {direction}
주도점수: {score}%
반대점수: {opposite}%
점수차이: {abs(score - opposite)}%
현재가: {current_price:.2f}

{format_check(score >= MIN_PRE_SCORE, f'{direction} 점수 75% 이상')}
{format_check(abs(score - opposite) >= MIN_SCORE_GAP, '롱/숏 점수 차이 20% 이상')}
{format_check(volume_ratio >= PRE_VOLUME_RATIO, f'거래량 {volume_ratio:.2f}배')}
{format_check(level_distance <= PRE_LEVEL_DISTANCE * 100, f'핵심 가격 근접 {level_distance:.2f}%')}
{format_check(trend_15m in ['UP', 'DOWN'], f'15분 추세 {trend_15m}')}
{format_check(trend_1h in ['UP', 'DOWN', 'SIDEWAYS'], f'1시간 추세 {trend_1h}')}
{format_check(True, f'RSI {rsi_value:.2f}')}
{format_check(True, f'CCI {cci_value:.2f}')}

📌 핵심 트리거:
{trigger_text}

🛑 손절 기준:
{stop_text}

🎯 1차 익절:
{tp1:.2f}

🎯 2차 익절:
{tp2:.2f}

⚠️ 조건은 좋지만 아직 REAL ENTRY 아님
⚠️ 가격 트리거 + 거래량 + 15분봉 종가 확정 전까지 대기

※ 자동진입 아님. 확인용 알림.
"""
    return msg


def make_real_entry_message(signal, reason, pre_signal):
    direction = signal.get("direction")
    current_price = signal.get("current_price")
    key_level = pre_signal.get("key_level")
    volume = signal.get("volume")
    avg_volume_20 = signal.get("avg_volume_20")
    volume_ratio = volume / avg_volume_20 if avg_volume_20 else 0

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

    msg = f"""🔥 {signal.get('symbol')} REAL ENTRY

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
    return msg


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

    msg = f"""🟠 {signal.get('symbol')} PULLBACK ENTRY

방향: {direction}
현재가: {current_price:.2f}
EMA20: {ema20:.2f}

✅ {reason}

📌 의미:
추세 진행 중 눌림 또는 되돌림 구간

🛑 손절:
{stop:.2f}

🎯 1차 익절:
{tp1:.2f}

🎯 2차 익절:
{tp2:.2f}

⚠️ 자동진입 아님. 확인용 알림.
"""
    return msg


def make_wait_message(signal, reason):
    msg = f"""⏸ {signal.get('symbol')} WAIT

현재가: {signal.get('current_price'):.2f}
LONG 점수: {signal.get('long_score')}%
SHORT 점수: {signal.get('short_score')}%
점수차이: {signal.get('score_gap')}%

대기 사유:
{reason}

📌 판단:
방향 우위가 부족하거나 박스권 노이즈 가능성이 있어 진입 금지

※ 자동진입 아님. 확인용 알림.
"""
    return msg


# =========================
# 외부 호출 함수
# =========================

def analyze_entry_timing(symbol, candles_by_tf, structure_result=None):
    signal = build_signal(symbol, candles_by_tf)
    results = []

    direction = signal.get("direction")
    score_gap = signal.get("score_gap", 0)

    if direction == "WAIT" or score_gap < MIN_SCORE_GAP:
        return {
            "type": "WAIT",
            "alert_type": "WAIT",
            "direction": "WAIT",
            "message": make_wait_message(signal, "롱/숏 점수 차이 부족 또는 방향 미확정"),
            **signal,
        }

    active_pre = get_active_pre_signal(symbol)
    real_ok, real_reason = is_real_entry_from_pre(active_pre, signal)

    if real_ok:
        results.append({
            "type": "REAL_ENTRY",
            "alert_type": "REAL_ENTRY",
            "direction": direction,
            "message": make_real_entry_message(signal, real_reason, active_pre),
            "reason": real_reason,
            **signal,
        })

        PRE_SIGNAL_MEMORY.pop(symbol, None)
        return results

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

    if not results:
        return {
            "type": "WAIT",
            "alert_type": "WAIT",
            "direction": "WAIT",
            "message": make_wait_message(signal, pre_reason),
            "reason": pre_reason,
            **signal,
        }

    return results


def run_entry_timing(symbol, candles_by_tf, structure_result=None):
    return analyze_entry_timing(symbol, candles_by_tf, structure_result)


def check_entry(symbol, candles_by_tf, structure_result=None):
    return analyze_entry_timing(symbol, candles_by_tf, structure_result)


def analyze(symbol, candles_by_tf, structure_result=None):
    return analyze_entry_timing(symbol, candles_by_tf, structure_result)


# =========================
# 진입 레이더
# =========================

def run_entry_radar(symbol, candles_by_tf, structure_result=None):
    signal = build_signal(symbol, candles_by_tf)

    direction = signal.get("direction")
    long_score = signal.get("long_score")
    short_score = signal.get("short_score")
    score_gap = signal.get("score_gap")

    if score_gap < 15:
        radar_state = "WAIT"
        reason = "롱/숏 점수 차이 15% 미만"
    elif signal.get("is_range") and signal.get("range_position") == "MIDDLE":
        radar_state = "WAIT"
        reason = "박스권 중앙"
    else:
        radar_state = direction
        reason = "방향 후보 감지"

    msg = f"""📡 {symbol} 진입 레이더

상태: {radar_state}
현재가: {signal.get('current_price'):.2f}

LONG 점수: {long_score}%
SHORT 점수: {short_score}%
점수차이: {score_gap}%

15분 추세: {signal.get('trend_15m')}
1시간 추세: {signal.get('trend_1h')}
RSI: {signal.get('rsi'):.2f}
CCI: {signal.get('cci'):.2f}
MACD: {signal.get('macd_state')}

판단:
{reason}
"""

    return {
        "type": "ENTRY_RADAR",
        "alert_type": "ENTRY_RADAR",
        "direction": radar_state,
        "message": msg,
        "reason": reason,
        **signal,
    }


def entry_radar(symbol, candles_by_tf, structure_result=None):
    return run_entry_radar(symbol, candles_by_tf, structure_result)


def analyze_radar(symbol, candles_by_tf, structure_result=None):
    return run_entry_radar(symbol, candles_by_tf, structure_result)


def check_radar(symbol, candles_by_tf, structure_result=None):
    return run_entry_radar(symbol, candles_by_tf, structure_result)
