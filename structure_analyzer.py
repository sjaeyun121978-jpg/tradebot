# structure_analyzer.py
# 1H 마감 종합 전광판
# 목적:
# - 1시간봉 마감 기준 현재 시장 상태판 출력
# - 롱/숏/WAIT를 초보자도 바로 판단 가능하게 표시
# - 데이터 부족 항목은 판정 제외로 명확히 분리
# - PRE/REAL 진입 알림과 역할 분리

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


def get_open(candle):
    return safe_float(candle.get("open")) if candle else 0


def get_high(candle):
    return safe_float(candle.get("high")) if candle else 0


def get_low(candle):
    return safe_float(candle.get("low")) if candle else 0


def get_close(candle):
    return safe_float(candle.get("close")) if candle else 0


def get_volume(candle):
    return safe_float(candle.get("volume")) if candle else 0


def pct_change(current, previous):
    if previous == 0:
        return 0
    return ((current - previous) / previous) * 100


def pct_distance(a, b):
    if b == 0:
        return 999
    return abs(a - b) / b * 100


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


def cci(candles, period=20):
    if len(candles) < period:
        return {
            "value": 0,
            "usable": False,
            "text": "데이터 부족",
        }

    target = candles[-period:]

    tps = []
    for c in target:
        tp = (get_high(c) + get_low(c) + get_close(c)) / 3
        tps.append(tp)

    ma = avg(tps)
    mean_dev = avg([abs(tp - ma) for tp in tps])

    if mean_dev == 0:
        return {
            "value": 0,
            "usable": True,
            "text": "중립",
        }

    value = (tps[-1] - ma) / (0.015 * mean_dev)

    if value >= 100:
        text = "강세"
    elif value <= -100:
        text = "약세"
    else:
        text = "중립"

    return {
        "value": value,
        "usable": True,
        "text": text,
    }


def macd_state(values):
    values = [safe_float(v) for v in values]

    if len(values) < 35:
        return {
            "state": "데이터 부족",
            "usable": False,
            "bias": "제외",
        }

    ema12 = ema(values, 12)
    ema26 = ema(values, 26)
    value = ema12 - ema26

    if value > 0:
        return {
            "state": "상방",
            "usable": True,
            "bias": "롱",
        }

    if value < 0:
        return {
            "state": "하방",
            "usable": True,
            "bias": "숏",
        }

    return {
        "state": "중립",
        "usable": True,
        "bias": "중립",
    }


# =========================
# 구조 판단
# =========================

def detect_trend(candles, min_count=50):
    if len(candles) < min_count:
        return {
            "trend": "데이터 부족",
            "usable": False,
            "bias": "제외",
            "reason": f"필요 캔들 {min_count}개 미만",
            "action": "진입 판단 핵심 근거에서 제외",
        }

    closes = [get_close(c) for c in candles]
    current = closes[-1]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)

    recent_high = max([get_high(c) for c in candles[-10:]])
    prev_high = max([get_high(c) for c in candles[-25:-10]])

    recent_low = min([get_low(c) for c in candles[-10:]])
    prev_low = min([get_low(c) for c in candles[-25:-10]])

    if current > ema20 > ema50 and recent_high > prev_high and recent_low >= prev_low:
        return {
            "trend": "상승",
            "usable": True,
            "bias": "롱",
            "reason": "EMA20 > EMA50 + 고점 갱신",
            "action": "롱 관점 우선, 단 추격은 금지",
            "ema20": ema20,
            "ema50": ema50,
            "ema200": ema200,
        }

    if current < ema20 < ema50 and recent_low < prev_low and recent_high <= prev_high:
        return {
            "trend": "하락",
            "usable": True,
            "bias": "숏",
            "reason": "EMA20 < EMA50 + 저점 이탈",
            "action": "숏 관점 우선, 단 추격은 금지",
            "ema20": ema20,
            "ema50": ema50,
            "ema200": ema200,
        }

    return {
        "trend": "횡보",
        "usable": True,
        "bias": "중립",
        "reason": "고점/저점 방향 확정 부족",
        "action": "가격 돌파 또는 이탈 전 대기",
        "ema20": ema20,
        "ema50": ema50,
        "ema200": ema200,
    }


def detect_range(candles):
    if len(candles) < 40:
        return {
            "is_range": False,
            "usable": False,
            "position": "데이터 부족",
            "high": None,
            "low": None,
            "action": "박스권 판단 제외",
        }

    recent = candles[-40:]

    high = max([get_high(c) for c in recent])
    low = min([get_low(c) for c in recent])
    current = get_close(recent[-1])

    width = (high - low) / current if current else 999

    if width > 0.035:
        return {
            "is_range": False,
            "usable": True,
            "position": "박스권 아님",
            "high": high,
            "low": low,
            "action": "추세 판단 우선",
        }

    upper = high - ((high - low) * 0.25)
    lower = low + ((high - low) * 0.25)

    if current >= upper:
        position = "상단"
        action = "상단 돌파 전 롱 추격 금지, 실패 시 숏 후보"
    elif current <= lower:
        position = "하단"
        action = "하단 이탈 전 숏 추격 금지, 반등 시 롱 후보"
    else:
        position = "중앙"
        action = "박스 중앙은 양방향 진입 금지"

    return {
        "is_range": True,
        "usable": True,
        "position": position,
        "high": high,
        "low": low,
        "action": action,
    }


def find_key_levels(candles):
    if len(candles) < 30:
        current = get_close(candles[-1]) if candles else 0
        return {
            "support": current,
            "resistance": current,
            "usable": False,
            "reason": "데이터 부족",
        }

    recent = candles[-50:] if len(candles) >= 50 else candles

    support = min([get_low(c) for c in recent[-20:]])
    resistance = max([get_high(c) for c in recent[-20:]])

    return {
        "support": support,
        "resistance": resistance,
        "usable": True,
        "reason": "최근 20봉 고저점 기준",
    }


def candle_shape(candle):
    if not candle:
        return "판단 불가"

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


# =========================
# 항목별 판정
# =========================

def judge_wave(tf_15m, tf_1h, tf_4h, tf_1d):
    usable = [x for x in [tf_15m, tf_1h, tf_4h, tf_1d] if x.get("usable")]

    if len(usable) < 2:
        return {
            "judgement": "판정 제외",
            "bias": "없음",
            "meaning": "파동 판단에 필요한 타임프레임 근거 부족",
            "action": "진입 근거로 사용 금지",
            "usable": False,
        }

    long_count = sum(1 for x in usable if x.get("bias") == "롱")
    short_count = sum(1 for x in usable if x.get("bias") == "숏")

    if long_count > short_count and short_count == 0:
        return {
            "judgement": "상승 파동 우세",
            "bias": "롱 우세",
            "meaning": "다수 타임프레임이 상승 방향으로 정렬",
            "action": "저항 돌파 확인 후 롱만 검토",
            "usable": True,
        }

    if short_count > long_count and long_count == 0:
        return {
            "judgement": "하락 파동 우세",
            "bias": "숏 우세",
            "meaning": "다수 타임프레임이 하락 방향으로 정렬",
            "action": "지지 이탈 확인 후 숏만 검토",
            "usable": True,
        }

    if long_count > short_count:
        return {
            "judgement": "상승 우세지만 충돌 존재",
            "bias": "롱 약우세",
            "meaning": "상승 근거가 더 많지만 일부 하락 타임프레임과 충돌",
            "action": "롱 추격 금지, 돌파 확인 필요",
            "usable": True,
        }

    if short_count > long_count:
        return {
            "judgement": "하락 우세지만 충돌 존재",
            "bias": "숏 약우세",
            "meaning": "하락 근거가 더 많지만 일부 상승 타임프레임과 충돌",
            "action": "숏 추격 금지, 이탈 확인 필요",
            "usable": True,
        }

    return {
        "judgement": "방향 충돌",
        "bias": "중립",
        "meaning": "롱/숏 근거가 맞서 방향 확정 불가",
        "action": "상단 돌파 또는 하단 이탈 전 진입 금지",
        "usable": True,
    }


def judge_similar_structure(tf_15m, tf_1h, range_info):
    if not tf_15m.get("usable") or not tf_1h.get("usable"):
        return {
            "judgement": "판정 제외",
            "bias": "없음",
            "meaning": "15M 또는 1H 구조 데이터 부족",
            "action": "과거 유사 구조 근거로 사용 금지",
            "usable": False,
        }

    if range_info.get("usable") and range_info.get("is_range"):
        return {
            "judgement": "박스권 유사 구조",
            "bias": "WAIT",
            "meaning": "과거 박스권과 유사하게 중앙부 노이즈 가능성 높음",
            "action": "상단 돌파 또는 하단 이탈 전 대기",
            "usable": True,
        }

    if tf_1h.get("bias") == "숏" and tf_15m.get("bias") == "롱":
        return {
            "judgement": "하락 중 단기 반등",
            "bias": "숏 약우세",
            "meaning": "1H 하락 흐름 안에서 15M 반등이 나온 상태",
            "action": "반등 고점 실패 후 숏 검토, 즉시 추격 금지",
            "usable": True,
        }

    if tf_1h.get("bias") == "롱" and tf_15m.get("bias") == "숏":
        return {
            "judgement": "상승 중 단기 눌림",
            "bias": "롱 약우세",
            "meaning": "1H 상승 흐름 안에서 15M 눌림이 나온 상태",
            "action": "눌림 저점 방어 후 롱 검토, 즉시 추격 금지",
            "usable": True,
        }

    if tf_1h.get("bias") == tf_15m.get("bias") == "롱":
        return {
            "judgement": "상승 지속형",
            "bias": "롱 우세",
            "meaning": "15M과 1H가 상승 방향으로 일치",
            "action": "저항 돌파 시 롱 우선",
            "usable": True,
        }

    if tf_1h.get("bias") == tf_15m.get("bias") == "숏":
        return {
            "judgement": "하락 지속형",
            "bias": "숏 우세",
            "meaning": "15M과 1H가 하락 방향으로 일치",
            "action": "지지 이탈 시 숏 우선",
            "usable": True,
        }

    return {
        "judgement": "방향 미확정",
        "bias": "중립",
        "meaning": "과거 유사 구조상 양방향 가능",
        "action": "가격 확인 전 진입 금지",
        "usable": True,
    }


def judge_divergence(candles):
    if len(candles) < 30:
        return {
            "judgement": "판정 제외",
            "bias": "없음",
            "meaning": "다이버전스 판단 데이터 부족",
            "action": "반전 근거로 사용 금지",
            "usable": False,
        }

    closes = [get_close(c) for c in candles]
    current_rsi = rsi(closes, 14)
    current_cci = cci(candles, 20)

    recent_price_low = get_low(candles[-1]) < min([get_low(c) for c in candles[-10:-1]])
    recent_price_high = get_high(candles[-1]) > max([get_high(c) for c in candles[-10:-1]])

    prev_rsi = rsi(closes[:-1], 14)

    bullish_div = recent_price_low and current_rsi > prev_rsi
    bearish_div = recent_price_high and current_rsi < prev_rsi

    if bullish_div:
        return {
            "judgement": "상승 다이버전스 의심",
            "bias": "롱 후보",
            "meaning": "가격은 저점을 낮췄지만 RSI는 개선",
            "action": "롱 확정 아님, 저점 회복 확인 필요",
            "usable": True,
        }

    if bearish_div:
        return {
            "judgement": "하락 다이버전스 의심",
            "bias": "숏 후보",
            "meaning": "가격은 고점을 높였지만 RSI는 약화",
            "action": "숏 확정 아님, 고점 실패 확인 필요",
            "usable": True,
        }

    if current_cci.get("usable") and current_cci.get("value") < -50:
        bias = "숏 유지"
        action = "롱 선진입 금지"
    elif current_cci.get("usable") and current_cci.get("value") > 50:
        bias = "롱 유지"
        action = "숏 선진입 금지"
    else:
        bias = "중립"
        action = "다이버전스만으로 판단 금지"

    return {
        "judgement": "반전 신호 없음",
        "bias": bias,
        "meaning": "RSI/CCI 기준 뚜렷한 반전 근거 없음",
        "action": action,
        "usable": True,
    }


def judge_volume(candles):
    if len(candles) < 20:
        return {
            "judgement": "판정 제외",
            "bias": "없음",
            "meaning": "거래량 평균 계산 데이터 부족",
            "action": "거래량 근거 제외",
            "usable": False,
            "ratio": 0,
        }

    volume = get_volume(candles[-1])
    avg_vol = avg([get_volume(c) for c in candles[-20:]])
    ratio = volume / avg_vol if avg_vol else 0

    if ratio >= 1.5:
        return {
            "judgement": "거래량 강함",
            "bias": "신뢰도 상승",
            "meaning": "현재 움직임에 거래량이 동반",
            "action": "가격 트리거 발생 시 신뢰도 높게 반영",
            "usable": True,
            "ratio": ratio,
        }

    if ratio >= 1.0:
        return {
            "judgement": "거래량 보통",
            "bias": "중립",
            "meaning": "평균 수준의 거래량",
            "action": "가격 트리거와 함께만 사용",
            "usable": True,
            "ratio": ratio,
        }

    return {
        "judgement": "거래량 약함",
        "bias": "신뢰도 낮음",
        "meaning": "움직임에 힘이 부족",
        "action": "진입 신뢰도 낮게 반영",
        "usable": True,
        "ratio": ratio,
    }


# =========================
# 종합 점수
# =========================

def calc_bias_score(items):
    long_score = 0
    short_score = 0
    wait_score = 0

    for item in items:
        if not item.get("usable", True):
            continue

        bias = str(item.get("bias", ""))

        if "롱 우세" in bias or bias == "롱":
            long_score += 20
        elif "롱 약우세" in bias or "롱 후보" in bias or "롱 유지" in bias:
            long_score += 10
        elif "숏 우세" in bias or bias == "숏":
            short_score += 20
        elif "숏 약우세" in bias or "숏 후보" in bias or "숏 유지" in bias:
            short_score += 10
        elif "WAIT" in bias or "중립" in bias:
            wait_score += 10

    total = max(long_score + short_score + wait_score, 1)

    long_pct = round(long_score / total * 100)
    short_pct = round(short_score / total * 100)

    return long_pct, short_pct


def final_judgement(long_pct, short_pct, usable_count, range_info):
    gap = abs(long_pct - short_pct)

    if usable_count < 3:
        return {
            "state": "WAIT",
            "bias": "판정 신뢰도 낮음",
            "confidence": "낮음",
            "reason": "사용 가능한 근거 부족",
        }

    if range_info.get("usable") and range_info.get("is_range") and range_info.get("position") == "중앙":
        return {
            "state": "WAIT",
            "bias": "중립",
            "confidence": "낮음",
            "reason": "박스권 중앙 노이즈 구간",
        }

    if gap < 15:
        return {
            "state": "WAIT",
            "bias": "중립",
            "confidence": "낮음",
            "reason": "롱/숏 우위 차이 15% 미만",
        }

    if long_pct > short_pct:
        return {
            "state": "LONG WATCH",
            "bias": "롱 약우세" if gap < 25 else "롱 우세",
            "confidence": "중간" if gap < 25 else "높음",
            "reason": "롱 근거가 숏 근거보다 우세",
        }

    return {
        "state": "SHORT WATCH",
        "bias": "숏 약우세" if gap < 25 else "숏 우세",
        "confidence": "중간" if gap < 25 else "높음",
        "reason": "숏 근거가 롱 근거보다 우세",
    }


# =========================
# 메시지 생성
# =========================

def format_tf_line(label, item):
    if not item.get("usable"):
        return f"⚪ {label}: 데이터 부족 → 판정 제외"
    return f"✅ {label}: {item.get('trend')} → {item.get('bias')}"


def build_usable_evidence(tf_items, extra_items):
    lines = []

    for label, item in tf_items:
        lines.append(format_tf_line(label, item))

    for label, item in extra_items:
        if not item.get("usable", True):
            continue
        lines.append(f"✅ {label}: {item.get('judgement')} → {item.get('bias')}")

    return "\n".join(lines)


def build_excluded_evidence(tf_items, extra_items):
    lines = []

    for label, item in tf_items:
        if not item.get("usable"):
            lines.append(f"⚪ {label} 추세: 데이터 부족 → 판정 제외")

    for label, item in extra_items:
        if not item.get("usable", True):
            lines.append(f"⚪ {label}: {item.get('meaning')} → 판정 제외")

    if not lines:
        return "없음"

    return "\n".join(lines)


def build_item_summary(name, item):
    return (
        f"{name}: {item.get('judgement')} → {item.get('action')}"
    )


def build_final_action(final, support, resistance):
    state = final.get("state")

    if state == "LONG WATCH":
        return (
            f"{resistance:.2f} 돌파 전 롱 추격 금지, "
            f"{support:.2f} 이탈 시 롱 관점 약화"
        )

    if state == "SHORT WATCH":
        return (
            f"{support:.2f} 이탈 전 숏 추격 금지, "
            f"{resistance:.2f} 돌파 시 숏 관점 약화"
        )

    return f"{support:.2f} 이탈 또는 {resistance:.2f} 돌파 전 진입 금지"


def build_final_conclusion(final, support, resistance):
    bias = final.get("bias")
    state = final.get("state")

    if state == "LONG WATCH":
        return (
            f"현재는 {bias} 상태다.\n"
            f"{resistance:.2f} 돌파 전 롱 추격 금지.\n"
            f"{support:.2f} 이탈 시 관점 재검토."
        )

    if state == "SHORT WATCH":
        return (
            f"현재는 {bias} 상태다.\n"
            f"{support:.2f} 이탈 전 숏 추격 금지.\n"
            f"{resistance:.2f} 돌파 시 관점 재검토."
        )

    return (
        f"현재는 관망 구간이다.\n"
        f"{support:.2f} 이탈 전 숏 금지, {resistance:.2f} 돌파 전 롱 금지.\n"
        f"지금은 가격 확인 전까지 WAIT가 우선이다."
    )


def build_message(symbol, data):
    current_price = data["current_price"]
    support = data["support"]
    resistance = data["resistance"]
    final = data["final"]

    action = build_final_action(final, support, resistance)

    usable_text = build_usable_evidence(
        data["tf_items"],
        data["extra_items"],
    )

    excluded_text = build_excluded_evidence(
        data["tf_items"],
        data["extra_items"],
    )

    item_text = "\n".join([
        build_item_summary("추세", data["trend_summary"]),
        build_item_summary("파동", data["wave"]),
        build_item_summary("과거 유사 구조", data["similar"]),
        build_item_summary("다이버전스", data["divergence"]),
        build_item_summary("거래량", data["volume"]),
    ])

    conclusion = build_final_conclusion(final, support, resistance)

    msg = f"""📊 {symbol} 1H 마감 종합 전광판
시간: {now_kst().strftime('%Y-%m-%d %H:%M')}
현재가: {current_price:.2f}

🧭 최종판정
상태: {final.get('state')}
우세: {final.get('bias')}
신뢰도: {final.get('confidence')}
이유: {final.get('reason')}
행동: {action}

🎯 다음 확인 가격
숏 확정: {support:.2f} 이탈
롱 전환: {resistance:.2f} 돌파
현재 구간: {support:.2f} ~ {resistance:.2f} 사이 대기

📌 사용 가능한 근거
{usable_text}

📌 제외할 근거
{excluded_text}

📊 항목별 판정
{item_text}

📌 롱 관점
조건: {resistance:.2f} 돌파 + 거래량 증가
의미: 상단 돌파 시 롱 관점 강화
주의: 돌파 전 선진입 금지

📌 숏 관점
조건: {support:.2f} 이탈 + 거래량 증가
의미: 하단 이탈 시 숏 관점 강화
주의: 이탈 전 추격 숏 금지

✅ 최종 결론
{conclusion}

※ 자동진입 아님. 1H 마감 기준 종합 상황판.
"""
    return msg


# =========================
# 메인 분석
# =========================

def analyze_structure(symbol, candles_by_tf):
    candles_15m = candles_by_tf.get("15m", [])
    candles_1h = candles_by_tf.get("1h", [])
    candles_4h = candles_by_tf.get("4h", [])
    candles_1d = candles_by_tf.get("1d", [])

    base = candles_1h if candles_1h else candles_15m

    if not base:
        return {
            "type": "STRUCTURE",
            "alert_type": "STRUCTURE",
            "direction": "WAIT",
            "message": f"📊 {symbol} 1H 마감 종합 전광판\n\n⚪ 데이터 부족 → 분석 불가",
        }

    current_price = get_close(base[-1])

    tf_15m = detect_trend(candles_15m, 50)
    tf_1h = detect_trend(candles_1h, 50)
    tf_4h = detect_trend(candles_4h, 50)
    tf_1d = detect_trend(candles_1d, 50)

    range_info = detect_range(candles_1h if candles_1h else candles_15m)
    levels = find_key_levels(candles_1h if candles_1h else candles_15m)

    support = levels["support"]
    resistance = levels["resistance"]

    wave = judge_wave(tf_15m, tf_1h, tf_4h, tf_1d)
    similar = judge_similar_structure(tf_15m, tf_1h, range_info)
    divergence = judge_divergence(candles_1h if candles_1h else candles_15m)
    volume = judge_volume(candles_1h if candles_1h else candles_15m)

    usable_tf_count = sum([
        tf_15m.get("usable", False),
        tf_1h.get("usable", False),
        tf_4h.get("usable", False),
        tf_1d.get("usable", False),
    ])

    trend_long = sum(1 for x in [tf_15m, tf_1h, tf_4h, tf_1d] if x.get("bias") == "롱")
    trend_short = sum(1 for x in [tf_15m, tf_1h, tf_4h, tf_1d] if x.get("bias") == "숏")

    if trend_long > trend_short:
        trend_summary = {
            "judgement": "롱 우세" if trend_long - trend_short >= 2 else "롱 약우세",
            "bias": "롱",
            "meaning": "상승 타임프레임이 더 많음",
            "action": "저항 돌파 확인 후 롱 검토",
            "usable": True,
        }
    elif trend_short > trend_long:
        trend_summary = {
            "judgement": "숏 우세" if trend_short - trend_long >= 2 else "숏 약우세",
            "bias": "숏",
            "meaning": "하락 타임프레임이 더 많음",
            "action": "지지 이탈 확인 후 숏 검토",
            "usable": True,
        }
    else:
        trend_summary = {
            "judgement": "방향 충돌",
            "bias": "중립",
            "meaning": "타임프레임별 방향이 충돌",
            "action": "돌파/이탈 전 WAIT",
            "usable": True,
        }

    score_items = [
        tf_15m,
        tf_1h,
        tf_4h,
        tf_1d,
        wave,
        similar,
        divergence,
        volume,
    ]

    long_pct, short_pct = calc_bias_score(score_items)

    final = final_judgement(
        long_pct=long_pct,
        short_pct=short_pct,
        usable_count=usable_tf_count,
        range_info=range_info,
    )

    tf_items = [
        ("15M", tf_15m),
        ("1H", tf_1h),
        ("4H", tf_4h),
        ("1D", tf_1d),
    ]

    extra_items = [
        ("파동", wave),
        ("과거 유사 구조", similar),
        ("다이버전스", divergence),
        ("거래량", volume),
    ]

    data = {
        "current_price": current_price,
        "support": support,
        "resistance": resistance,
        "final": final,
        "tf_items": tf_items,
        "extra_items": extra_items,
        "trend_summary": trend_summary,
        "wave": wave,
        "similar": similar,
        "divergence": divergence,
        "volume": volume,
    }

    message = build_message(symbol, data)

    direction = "WAIT"
    if final.get("state") == "LONG WATCH":
        direction = "LONG"
    elif final.get("state") == "SHORT WATCH":
        direction = "SHORT"

    return {
        "type": "STRUCTURE_DASHBOARD",
        "alert_type": "STRUCTURE_DASHBOARD",
        "direction": direction,
        "state": final.get("state"),
        "bias": final.get("bias"),
        "confidence": final.get("confidence"),
        "current_price": current_price,
        "support": support,
        "resistance": resistance,
        "long_score": long_pct,
        "short_score": short_pct,
        "message": message,
    }


# =========================
# 호환 함수명
# =========================

def run_structure_analysis(symbol, candles_by_tf):
    return analyze_structure(symbol, candles_by_tf)


def fact_based_structure_analysis(symbol, candles_by_tf):
    return analyze_structure(symbol, candles_by_tf)


def analyze(symbol, candles_by_tf):
    return analyze_structure(symbol, candles_by_tf)
