# daily_weekly_briefing.py
# 일봉 브리핑 / 주간 브리핑
# ─────────────────────────────────────────────
# 분석은 core_analyzer.analyze() 에서 1번만 수행
# 이 파일은 포맷(메시지 생성)만 담당
# ─────────────────────────────────────────────

from datetime import datetime, timezone, timedelta
from core_analyzer import analyze, now_kst

KST = timezone(timedelta(hours=9))

_TREND_KO = {"UP": "상승", "DOWN": "하락", "SIDEWAYS": "횡보"}
_MACD_KO  = {
    "BULLISH": "강세↑", "BEARISH": "약세↓",
    "POSITIVE": "양전환", "NEGATIVE": "음전환", "NEUTRAL": "중립"
}
_BB_KO = {
    "OVERBOUGHT": "상단 과매수 ⚠️",
    "OVERSOLD":   "하단 과매도 ✅",
    "SQUEEZE":    "밴드 수축 (큰 움직임 임박) ⚡",
    "NEUTRAL":    "중립",
}


def _bias_label(long_score, short_score):
    gap = abs(long_score - short_score)
    if gap < 10:  return "중립"
    if long_score > short_score:
        return "롱 우세" if gap >= 20 else "롱 약우세"
    return "숏 우세" if gap >= 20 else "숏 약우세"


def _confidence_label(gap, vol_ok):
    if gap >= 25 and vol_ok: return "높음"
    if gap >= 15:            return "중간"
    return "낮음"


# ─────────────────────────────────────────────
# 일봉 브리핑
# ─────────────────────────────────────────────

def build_daily_briefing(symbol, sig):
    d = sig.get("daily", {})
    if not d:
        return f"📅 {symbol} 일봉 브리핑\n\n⚪ 데이터 부족"

    price      = sig["current_price"]
    support    = sig["support"]
    resistance = sig["resistance"]

    y_open   = d.get("yesterday_open",   0)
    y_high   = d.get("yesterday_high",   0)
    y_low    = d.get("yesterday_low",    0)
    y_close  = d.get("yesterday_close",  0)
    y_change = d.get("yesterday_change", 0)
    y_shape  = d.get("yesterday_shape",  "-")
    vol_ratio = d.get("daily_volume_ratio", 0)

    ema20_d  = d.get("ema20_daily", sig["ema20"])
    ema50_d  = d.get("ema50_daily", sig["ema50"])
    rsi_d    = d.get("rsi_daily",   sig["rsi"])
    macd_d   = _MACD_KO.get(d.get("macd_daily", sig["macd_state"]), "-")
    bb_sig   = _BB_KO.get(d.get("bb_daily_signal", sig.get("bb_signal", "NEUTRAL")), "중립")
    div      = sig.get("divergence")
    div_line = f"\n다이버전스: {'상승 다이버전스 ✅' if div == 'BULLISH_DIV' else '하락 다이버전스 ⚠️' if div == 'BEARISH_DIV' else '없음'}"

    bias       = _bias_label(sig["long_score"], sig["short_score"])
    confidence = _confidence_label(sig["score_gap"], vol_ratio >= 1.0)

    if "롱" in bias:
        state  = "상승 유지 또는 재상승 대기"
        action = f"{y_high:.2f} 돌파 전 롱 추격 금지, {y_low:.2f} 이탈 시 롱 관점 약화"
    elif "숏" in bias:
        state  = "조정 또는 하락 압력 우세"
        action = f"{y_low:.2f} 이탈 전 숏 추격 금지, {y_high:.2f} 돌파 시 숏 관점 약화"
    else:
        state  = "방향 미확정"
        action = f"{y_low:.2f} ~ {y_high:.2f} 구간 돌파 확인 전 대기"

    trend_15m = _TREND_KO.get(sig.get("trend_15m", "SIDEWAYS"), "횡보")
    trend_1h  = _TREND_KO.get(sig.get("trend_1h",  "SIDEWAYS"), "횡보")
    trend_4h  = _TREND_KO.get(sig.get("trend_4h",  "SIDEWAYS"), "횡보")
    trend_1d  = _TREND_KO.get(sig.get("trend_1d",  "SIDEWAYS"), "횡보")

    daily_mid = (y_high + y_low) / 2

    return f"""📅 {symbol} 일봉 마감 브리핑
기준: {now_kst().strftime('%Y-%m-%d 09:00')}
현재가: {price:.2f}

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
전일 변화율: {y_change:.2f}%
캔들 형태: {y_shape}

🎯 오늘 핵심 가격
롱 강화: {y_high:.2f} 돌파
숏 강화: {y_low:.2f} 이탈
중립 기준: {daily_mid:.2f}

📊 멀티 타임프레임
15M: {trend_15m} / 1H: {trend_1h}
4H:  {trend_4h}  / 1D: {trend_1d}

📊 지표
EMA20/50: {ema20_d:.2f} / {ema50_d:.2f}
RSI: {rsi_d:.2f} {'강세↑' if rsi_d >= 50 else '약세↓'}
MACD: {macd_d}
볼린저밴드: {bb_sig}
거래량: {vol_ratio:.2f}배{div_line}

LONG {sig['long_score']}% · SHORT {sig['short_score']}%

🐂 롱 관점
조건: {y_high:.2f} 돌파 + 거래량 증가
주의: 돌파 전 선진입 금지

🐻 숏 관점
조건: {y_low:.2f} 이탈 + 거래량 증가
주의: 이탈 전 추격 숏 금지

✅ 오늘 전략
{bias} 상태. {y_low:.2f} 이탈 또는 {y_high:.2f} 돌파가 핵심.

※ 자동진입 아님. 하루 방향 확인용 브리핑.
"""


# ─────────────────────────────────────────────
# 주간 브리핑
# ─────────────────────────────────────────────

def build_weekly_progress_briefing(symbol, sig):
    d = sig.get("daily", {})
    if not d:
        return f"📆 {symbol} 주간 진행 브리핑\n\n⚪ 데이터 부족"

    price      = sig["current_price"]
    week_open  = d.get("week_open",  price)
    week_high  = d.get("week_high",  price)
    week_low   = d.get("week_low",   price)
    week_close = d.get("week_close", price)
    week_change = d.get("week_change", 0)
    week_mid   = d.get("week_mid",   (week_high + week_low) / 2)
    day_flows  = d.get("day_flows",  [])
    trend_1w   = _TREND_KO.get(d.get("trend_1w", "SIDEWAYS"), "횡보")

    ema20_d  = d.get("ema20_daily", sig["ema20"])
    ema50_d  = d.get("ema50_daily", sig["ema50"])
    rsi_d    = d.get("rsi_daily",   sig["rsi"])
    macd_d   = _MACD_KO.get(d.get("macd_daily", sig["macd_state"]), "-")
    bb_sig   = _BB_KO.get(d.get("bb_daily_signal", sig.get("bb_signal", "NEUTRAL")), "중립")
    div      = sig.get("divergence")
    div_line = f"\n다이버전스: {'상승 다이버전스 ✅' if div == 'BULLISH_DIV' else '하락 다이버전스 ⚠️' if div == 'BEARISH_DIV' else '없음'}"

    bias       = _bias_label(sig["long_score"], sig["short_score"])
    confidence = _confidence_label(sig["score_gap"], sig.get("volume_ratio", 0) >= 1.0)

    weekly_candle = (
        "주봉 양봉 진행" if price > week_open
        else "주봉 음봉 진행" if price < week_open
        else "주봉 보합"
    )
    position_text = "주간 범위 상단부" if price >= week_mid else "주간 범위 하단부"

    if "롱" in bias:
        state  = "주간 상승 흐름 우세"
        action = f"{week_high:.2f} 돌파 시 주간 상승 강화, {week_low:.2f} 이탈 시 주간 구조 훼손"
    elif "숏" in bias:
        state  = "주간 조정 흐름 우세"
        action = f"{week_low:.2f} 이탈 시 주간 약세 강화, {week_high:.2f} 돌파 시 숏 관점 약화"
    else:
        state  = "주간 방향 미확정"
        action = f"{week_low:.2f} ~ {week_high:.2f} 범위 이탈 전까지 중립"

    now = now_kst()
    from datetime import timedelta as td
    days_since_monday = now.weekday()
    monday = now - td(days=days_since_monday)
    week_start = monday.replace(hour=9, minute=0, second=0, microsecond=0)
    week_end   = week_start + td(days=7)

    trend_15m = _TREND_KO.get(sig.get("trend_15m", "SIDEWAYS"), "횡보")
    trend_1h  = _TREND_KO.get(sig.get("trend_1h",  "SIDEWAYS"), "횡보")
    trend_4h  = _TREND_KO.get(sig.get("trend_4h",  "SIDEWAYS"), "횡보")

    day_flow_text = "\n".join(day_flows) if day_flows else "데이터 부족"

    return f"""📆 {symbol} 주간 진행 브리핑
주봉 기간: {week_start.strftime('%Y-%m-%d 09:00')} ~ {week_end.strftime('%Y-%m-%d 09:00')}
현재 시점: {now.strftime('%Y-%m-%d %H:%M')}
현재가: {price:.2f}

🧭 주간 최종판정
상태: {state}
우세: {bias}
신뢰도: {confidence}
행동: {action}

📌 이번 주 진행 상황
주간 시가: {week_open:.2f}
주간 고가: {week_high:.2f}
주간 저가: {week_low:.2f}
현재가: {price:.2f}
주간 변화율: {week_change:.2f}%
현재 주봉: {weekly_candle}
현재 위치: {position_text}

🎯 이번 주 핵심 가격
주간 상승 강화: {week_high:.2f} 돌파
주간 약세 강화: {week_low:.2f} 이탈
주간 중심선: {week_mid:.2f}

📊 이번 주 일봉 흐름
{day_flow_text}

📊 구조
주봉 추세: {trend_1w}
15M: {trend_15m} / 1H: {trend_1h} / 4H: {trend_4h}

📊 지표
EMA20/50: {ema20_d:.2f} / {ema50_d:.2f}
RSI: {rsi_d:.2f} {'강세↑' if rsi_d >= 50 else '약세↓'}
MACD: {macd_d}
볼린저밴드: {bb_sig}
거래량: {sig.get('volume_ratio', 0):.2f}배{div_line}

LONG {sig['long_score']}% · SHORT {sig['short_score']}%

🐂 주간 롱 관점
조건: {week_high:.2f} 돌파 + 일봉 종가 유지
주의: 돌파 전 추격 롱 금지

🐻 주간 숏 관점
조건: {week_low:.2f} 이탈 + 일봉 종가 이탈 유지
주의: 이탈 전 추격 숏 금지

✅ 주간 전략
이번 주는 {bias} 상태.
{week_low:.2f} 방어와 {week_high:.2f} 돌파 여부가 핵심.

※ 자동진입 아님. 숲 전체 확인용 브리핑.
"""


# ─────────────────────────────────────────────
# 외부 호출 함수 (core_analyzer 재사용)
# ─────────────────────────────────────────────

def run_daily_briefing(symbol, candles_by_tf):
    sig = analyze(symbol, candles_by_tf)
    return {
        "type":       "DAILY_BRIEFING",
        "alert_type": "DAILY_BRIEFING",
        "direction":  "INFO",
        "message":    build_daily_briefing(symbol, sig),
    }


def run_weekly_progress_briefing(symbol, candles_by_tf):
    sig = analyze(symbol, candles_by_tf)
    return {
        "type":       "WEEKLY_PROGRESS_BRIEFING",
        "alert_type": "WEEKLY_PROGRESS_BRIEFING",
        "direction":  "INFO",
        "message":    build_weekly_progress_briefing(symbol, sig),
    }


def run_all_briefings(symbol, candles_by_tf):
    # ★ analyze() 1번만 호출 → 두 브리핑이 동일 데이터 공유
    sig = analyze(symbol, candles_by_tf)
    return [
        {
            "type":       "DAILY_BRIEFING",
            "alert_type": "DAILY_BRIEFING",
            "direction":  "INFO",
            "message":    build_daily_briefing(symbol, sig),
        },
        {
            "type":       "WEEKLY_PROGRESS_BRIEFING",
            "alert_type": "WEEKLY_PROGRESS_BRIEFING",
            "direction":  "INFO",
            "message":    build_weekly_progress_briefing(symbol, sig),
        },
    ]
