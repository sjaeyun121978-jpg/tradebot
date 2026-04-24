# daily_weekly_briefing.py
# 목적:
# 1. 매일 오전 9시 일봉 마감 브리핑
# 2. 매일 오전 9시 주간 진행 브리핑
# 3. 주봉 기준 큰 방향성 분석
# 4. 초보자도 바로 판단 가능한 판정형 전광판 출력

from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))


# =========================
# 기본 유틸
# =========================

def now_kst():
    return datetime.now(KST)


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def avg(values):
    values = [safe_float(v) for v in values if v is not None]
    if not values:
        return 0
    return sum(values) / len(values)


def get_close(candle):
    return safe_float(candle.get("close")) if candle else 0


def get_open(candle):
    return safe_float(candle.get("open")) if candle else 0


def get_high(candle):
    return safe_float(candle.get("high")) if candle else 0


def get_low(candle):
    return safe_float(candle.get("low")) if candle else 0


def get_volume(candle):
    return safe_float(candle.get("volume")) if candle else 0


def pct_change(current, previous):
    if previous == 0:
        return 0
    return ((current - previous) / previous) * 100


# =========================
# 지표
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


def macd_state(values):
    values = [safe_float(v) for v in values]

    if len(values) < 35:
        return "데이터 부족"

    ema12 = ema(values, 12)
    ema26 = ema(values, 26)
    macd_value = ema12 - ema26

    if macd_value > 0:
        return "상방"
    elif macd_value < 0:
        return "하방"
    else:
        return "중립"


# =========================
# 구조 분석
# =========================

def detect_trend(candles, min_count=50):
    if len(candles) < min_count:
        return {
            "trend": "데이터 부족",
            "usable": False,
            "note": "판정 제외",
            "reason": f"필요 캔들 {min_count}개 미만",
        }

    closes = [get_close(c) for c in candles]
    current = closes[-1]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)

    recent_high = max([get_high(c) for c in candles[-10:]])
    prev_high = max([get_high(c) for c in candles[-25:-10]])

    recent_low = min([get_low(c) for c in candles[-10:]])
    prev_low = min([get_low(c) for c in candles[-25:-10]])

    if current > ema20 > ema50 and recent_high > prev_high and recent_low >= prev_low:
        return {
            "trend": "상승",
            "usable": True,
            "note": "사용 가능",
            "reason": "EMA20 > EMA50 + 고점 갱신",
        }

    if current < ema20 < ema50 and recent_low < prev_low and recent_high <= prev_high:
        return {
            "trend": "하락",
            "usable": True,
            "note": "사용 가능",
            "reason": "EMA20 < EMA50 + 저점 이탈",
        }

    return {
        "trend": "횡보",
        "usable": True,
        "note": "사용 가능",
        "reason": "추세 확정 부족",
    }


def candle_shape(candle):
    o = get_open(candle)
    h = get_high(candle)
    l = get_low(candle)
    c = get_close(candle)

    body = abs(c - o)
    full = h - l

    if full == 0:
        return "판단 불가"

    body_ratio = body / full

    if c > o and body_ratio >= 0.6:
        return "강한 양봉"

    if c < o and body_ratio >= 0.6:
        return "강한 음봉"

    if body_ratio <= 0.25:
        return "도지/방향 미확정"

    if c > o:
        return "약한 양봉"

    if c < o:
        return "약한 음봉"

    return "중립"


def judge_bias(long_score, short_score):
    gap = abs(long_score - short_score)

    if gap < 10:
        return "중립"

    if long_score > short_score:
        return "롱 약우세" if gap < 20 else "롱 우세"

    if short_score > long_score:
        return "숏 약우세" if gap < 20 else "숏 우세"

    return "중립"


def confidence_label(score_gap, usable_count, volume_ok):
    if usable_count <= 1:
        return "낮음"

    if score_gap >= 25 and volume_ok:
        return "높음"

    if score_gap >= 15:
        return "중간"

    return "낮음"


# =========================
# 일봉 브리핑
# =========================

def build_daily_briefing(symbol, candles_by_tf):
    daily = candles_by_tf.get("1d", [])
    h4 = candles_by_tf.get("4h", [])
    h1 = candles_by_tf.get("1h", [])

    if len(daily) < 3:
        return f"📅 {symbol} 일봉 브리핑\n\n⚪ 데이터 부족 → 일봉 브리핑 판정 제외"

    yesterday = daily[-2]
    before_yesterday = daily[-3]
    current_daily = daily[-1]

    current_price = get_close(current_daily)

    prev_close = get_close(before_yesterday)
    y_open = get_open(yesterday)
    y_high = get_high(yesterday)
    y_low = get_low(yesterday)
    y_close = get_close(yesterday)
    y_volume = get_volume(yesterday)

    closes_d = [get_close(c) for c in daily]
    volumes_d = [get_volume(c) for c in daily]

    change = pct_change(y_close, prev_close)
    shape = candle_shape(yesterday)

    daily_trend = detect_trend(daily, 50)
    h4_trend = detect_trend(h4, 50)
    h1_trend = detect_trend(h1, 50)

    ema20_d = ema(closes_d, 20)
    ema50_d = ema(closes_d, 50)
    rsi_d = rsi(closes_d, 14)
    macd_d = macd_state(closes_d)

    avg_vol_20 = avg(volumes_d[-20:])
    volume_ratio = y_volume / avg_vol_20 if avg_vol_20 else 0
    volume_ok = volume_ratio >= 1.0

    long_score = 0
    short_score = 0

    if y_close > ema20_d:
        long_score += 20
    else:
        short_score += 20

    if ema20_d > ema50_d:
        long_score += 20
    else:
        short_score += 20

    if rsi_d >= 55:
        long_score += 20
    elif rsi_d <= 45:
        short_score += 20
    else:
        long_score += 10
        short_score += 10

    if macd_d == "상방":
        long_score += 15
    elif macd_d == "하방":
        short_score += 15

    if shape in ["강한 양봉", "약한 양봉"]:
        long_score += 15
    elif shape in ["강한 음봉", "약한 음봉"]:
        short_score += 15

    if volume_ok:
        if long_score >= short_score:
            long_score += 10
        else:
            short_score += 10

    bias = judge_bias(long_score, short_score)

    usable_count = sum([
        daily_trend.get("usable", False),
        h4_trend.get("usable", False),
        h1_trend.get("usable", False),
    ])

    score_gap = abs(long_score - short_score)
    confidence = confidence_label(score_gap, usable_count, volume_ok)

    long_trigger = y_high
    short_trigger = y_low
    daily_mid = (y_high + y_low) / 2

    if bias in ["롱 우세", "롱 약우세"]:
        state = "상승 유지 또는 재상승 대기"
        action = f"{long_trigger:.2f} 돌파 전 롱 추격 금지, {short_trigger:.2f} 이탈 시 롱 관점 약화"
    elif bias in ["숏 우세", "숏 약우세"]:
        state = "조정 또는 하락 압력 우세"
        action = f"{short_trigger:.2f} 이탈 전 숏 추격 금지, {long_trigger:.2f} 돌파 시 숏 관점 약화"
    else:
        state = "방향 미확정"
        action = f"{short_trigger:.2f} ~ {long_trigger:.2f} 구간 돌파 확인 전 대기"

    excluded = []

    for name, item in [
        ("4H 추세", h4_trend),
        ("1H 추세", h1_trend),
        ("일봉 추세", daily_trend),
    ]:
        if not item.get("usable"):
            excluded.append(f"⚪ {name}: 데이터 부족 → 판정 제외")

    if macd_d == "데이터 부족":
        excluded.append("⚪ MACD: 데이터 부족 → 판정 제외")

    if not excluded:
        excluded_text = "없음"
    else:
        excluded_text = "\n".join(excluded)

    msg = f"""📅 {symbol} 일봉 마감 브리핑
기준: {now_kst().strftime('%Y-%m-%d 09:00')}
대상 일봉: 전일 마감봉
현재가: {current_price:.2f}

🧭 하루 최종판정
상태: {state}
우세: {bias}
신뢰도: {confidence}
행동: {action}

📌 어제 → 오늘 변화
전일 시가: {y_open:.2f}
전일 고가: {y_high:.2f}
전일 저가: {y_low:.2f}
전일 종가: {y_close:.2f}
전일 변화율: {change:.2f}%
캔들 형태: {shape}

🎯 오늘 핵심 가격
롱 강화: {long_trigger:.2f} 돌파
숏 강화: {short_trigger:.2f} 이탈
중립 기준: {daily_mid:.2f}
현재 구간: 돌파 전까지 확인 구간

📊 일봉 구조
판정: {daily_trend.get('trend')}
근거: {daily_trend.get('reason')}
행동: 일봉 방향은 오늘 매매의 큰 배경으로만 사용

📊 하위 타임프레임 정렬
4H: {h4_trend.get('trend')} / {h4_trend.get('note')}
1H: {h1_trend.get('trend')} / {h1_trend.get('note')}
판정: 일봉과 하위봉이 일치하면 신뢰도 상승, 충돌하면 진입 대기

📊 지표
EMA20: {ema20_d:.2f}
EMA50: {ema50_d:.2f}
RSI: {rsi_d:.2f}
MACD: {macd_d}
거래량: {volume_ratio:.2f}배

🐂 롱 관점
조건: {long_trigger:.2f} 돌파 + 거래량 증가
의미: 전일 고점 돌파로 상승 재개 가능성 증가
주의: 돌파 전 선진입 금지

🐻 숏 관점
조건: {short_trigger:.2f} 이탈 + 거래량 증가
의미: 전일 저점 이탈로 조정 확대 가능성 증가
주의: 이탈 전 추격 숏 금지

⚪ 판정 제외 항목
{excluded_text}

✅ 오늘 전략
{bias} 상태지만 최종 진입은 가격 트리거 확인 후 판단.
오늘은 {short_trigger:.2f} 이탈 또는 {long_trigger:.2f} 돌파가 핵심이다.

※ 자동진입 아님. 하루 방향 확인용 브리핑.
"""
    return msg


# =========================
# 주간 브리핑
# =========================

def get_week_start_kst(dt=None):
    dt = dt or now_kst()

    # 코인 주봉 기준: 월요일 오전 9시 시작
    days_since_monday = dt.weekday()
    monday = dt - timedelta(days=days_since_monday)
    week_start = monday.replace(hour=9, minute=0, second=0, microsecond=0)

    if dt < week_start:
        week_start -= timedelta(days=7)

    return week_start


def build_weekly_progress_briefing(symbol, candles_by_tf):
    daily = candles_by_tf.get("1d", [])
    weekly = candles_by_tf.get("1w", [])

    if len(daily) < 7:
        return f"📆 {symbol} 주간 진행 브리핑\n\n⚪ 데이터 부족 → 주간 브리핑 판정 제외"

    current_time = now_kst()
    week_start = get_week_start_kst(current_time)
    week_end = week_start + timedelta(days=7)

    # 최근 7개 일봉으로 이번 주 흐름 근사
    week_days = daily[-7:]

    week_open = get_open(week_days[0])
    week_high = max([get_high(c) for c in week_days])
    week_low = min([get_low(c) for c in week_days])
    current_price = get_close(week_days[-1])

    week_change = pct_change(current_price, week_open)

    closes_d = [get_close(c) for c in daily]
    volumes_d = [get_volume(c) for c in daily]

    ema20_d = ema(closes_d, 20)
    ema50_d = ema(closes_d, 50)
    rsi_d = rsi(closes_d, 14)
    macd_d = macd_state(closes_d)

    avg_vol_20 = avg(volumes_d[-20:])
    recent_vol = avg(volumes_d[-7:])
    volume_ratio = recent_vol / avg_vol_20 if avg_vol_20 else 0

    daily_trend = detect_trend(daily, 50)
    weekly_trend = detect_trend(weekly, 30) if weekly else {
        "trend": "데이터 부족",
        "usable": False,
        "note": "판정 제외",
        "reason": "주봉 캔들 부족",
    }

    long_score = 0
    short_score = 0

    if current_price > week_open:
        long_score += 20
    else:
        short_score += 20

    if current_price > ema20_d:
        long_score += 20
    else:
        short_score += 20

    if ema20_d > ema50_d:
        long_score += 20
    else:
        short_score += 20

    if rsi_d >= 55:
        long_score += 15
    elif rsi_d <= 45:
        short_score += 15
    else:
        long_score += 7
        short_score += 7

    if macd_d == "상방":
        long_score += 15
    elif macd_d == "하방":
        short_score += 15

    if volume_ratio >= 1.0:
        if long_score >= short_score:
            long_score += 10
        else:
            short_score += 10

    bias = judge_bias(long_score, short_score)
    score_gap = abs(long_score - short_score)

    usable_count = sum([
        daily_trend.get("usable", False),
        weekly_trend.get("usable", False),
    ])

    confidence = confidence_label(score_gap, usable_count, volume_ratio >= 1.0)

    if current_price > week_open:
        weekly_candle = "주봉 양봉 진행"
    elif current_price < week_open:
        weekly_candle = "주봉 음봉 진행"
    else:
        weekly_candle = "주봉 보합"

    week_mid = (week_high + week_low) / 2

    if current_price >= week_mid:
        position_text = "주간 범위 상단부"
    else:
        position_text = "주간 범위 하단부"

    if bias in ["롱 우세", "롱 약우세"]:
        state = "주간 상승 흐름 우세"
        action = f"{week_high:.2f} 돌파 시 주간 상승 강화, {week_low:.2f} 이탈 시 주간 구조 훼손"
    elif bias in ["숏 우세", "숏 약우세"]:
        state = "주간 조정 흐름 우세"
        action = f"{week_low:.2f} 이탈 시 주간 약세 강화, {week_high:.2f} 돌파 시 숏 관점 약화"
    else:
        state = "주간 방향 미확정"
        action = f"{week_low:.2f} ~ {week_high:.2f} 범위 이탈 전까지 중립"

    day_flow_lines = []

    for idx, candle in enumerate(week_days[-5:], start=1):
        o = get_open(candle)
        c = get_close(candle)
        shape = candle_shape(candle)

        if c > o:
            flow = "상승"
        elif c < o:
            flow = "하락"
        else:
            flow = "보합"

        day_flow_lines.append(f"{idx}일차: {flow} / {shape}")

    day_flow_text = "\n".join(day_flow_lines)

    excluded = []

    if not weekly_trend.get("usable"):
        excluded.append("⚪ 주봉 추세: 데이터 부족 → 참고만, 핵심 판정 제외")

    if macd_d == "데이터 부족":
        excluded.append("⚪ MACD: 데이터 부족 → 판정 제외")

    if not excluded:
        excluded_text = "없음"
    else:
        excluded_text = "\n".join(excluded)

    msg = f"""📆 {symbol} 주간 진행 브리핑
주봉 기간: {week_start.strftime('%Y-%m-%d 09:00')} ~ {week_end.strftime('%Y-%m-%d 09:00')}
현재 시점: {current_time.strftime('%Y-%m-%d %H:%M')}
현재가: {current_price:.2f}

🧭 주간 최종판정
상태: {state}
우세: {bias}
신뢰도: {confidence}
행동: {action}

📌 이번 주 진행 상황
주간 시가: {week_open:.2f}
주간 고가: {week_high:.2f}
주간 저가: {week_low:.2f}
현재가: {current_price:.2f}
주간 변화율: {week_change:.2f}%
현재 주봉: {weekly_candle}
현재 위치: {position_text}

🎯 이번 주 핵심 가격
주간 상승 강화: {week_high:.2f} 돌파
주간 약세 강화: {week_low:.2f} 이탈
주간 중심선: {week_mid:.2f}

📊 이번 주 일봉 흐름
{day_flow_text}

📊 주간 구조
주봉 추세: {weekly_trend.get('trend')} / {weekly_trend.get('note')}
일봉 추세: {daily_trend.get('trend')} / {daily_trend.get('note')}
판정: 주봉은 숲, 일봉은 이번 주 진행 방향 확인용

📊 지표
EMA20: {ema20_d:.2f}
EMA50: {ema50_d:.2f}
RSI: {rsi_d:.2f}
MACD: {macd_d}
주간 평균 거래량: {volume_ratio:.2f}배

🐂 주간 롱 관점
조건: {week_high:.2f} 돌파 + 일봉 종가 유지
의미: 이번 주 상승 흐름 강화
주의: 돌파 전 추격 롱 금지

🐻 주간 숏 관점
조건: {week_low:.2f} 이탈 + 일봉 종가 이탈 유지
의미: 이번 주 약세 전환 또는 조정 확대
주의: 이탈 전 추격 숏 금지

⚪ 판정 제외 항목
{excluded_text}

✅ 주간 전략
이번 주는 {bias} 상태.
작은 봉에서 방향을 잃어도 주간 기준은 {week_low:.2f} 방어와 {week_high:.2f} 돌파 여부가 핵심이다.

※ 자동진입 아님. 숲 전체 확인용 브리핑.
"""
    return msg


# =========================
# 외부 호출 함수
# =========================

def run_daily_briefing(symbol, candles_by_tf):
    return {
        "type": "DAILY_BRIEFING",
        "alert_type": "DAILY_BRIEFING",
        "direction": "INFO",
        "message": build_daily_briefing(symbol, candles_by_tf),
    }


def run_weekly_progress_briefing(symbol, candles_by_tf):
    return {
        "type": "WEEKLY_PROGRESS_BRIEFING",
        "alert_type": "WEEKLY_PROGRESS_BRIEFING",
        "direction": "INFO",
        "message": build_weekly_progress_briefing(symbol, candles_by_tf),
    }


def run_all_briefings(symbol, candles_by_tf):
    return [
        run_daily_briefing(symbol, candles_by_tf),
        run_weekly_progress_briefing(symbol, candles_by_tf),
    ]
