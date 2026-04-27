# structure_analyzer.py
# 1H 마감 종합 전광판
# ─────────────────────────────────────────────
# 분석은 core_analyzer.analyze() 에서 1번만 수행
# 이 파일은 포맷(메시지 생성)만 담당
# ─────────────────────────────────────────────

from datetime import datetime, timezone, timedelta
from tradebot.analysis.core import analyze as _core_analyze, now_kst

KST = timezone(timedelta(hours=9))

_TREND_KO = {"UP": "상승", "DOWN": "하락", "SIDEWAYS": "횡보"}
_MACD_KO  = {
    "BULLISH": "강세↑", "BEARISH": "약세↓",
    "POSITIVE": "양전환", "NEGATIVE": "음전환", "NEUTRAL": "중립"
}
_BB_KO = {
    "OVERBOUGHT": "상단 과매수",
    "OVERSOLD":   "하단 과매도",
    "SQUEEZE":    "밴드 수축 (큰 움직임 임박)",
    "NEUTRAL":    "중립",
}
_DIV_KO = {
    "BULLISH_DIV": "상승 다이버전스",
    "BEARISH_DIV": "하락 다이버전스",
}


def _trend(key, sig):
    return _TREND_KO.get(sig.get(key, "SIDEWAYS"), "횡보")


def _bias_label(sig):
    ls, ss = sig["long_score"], sig["short_score"]
    gap = abs(ls - ss)
    if gap < 15:  return "중립"
    if ls > ss:   return "롱 우세" if gap >= 25 else "롱 약우세"
    return "숏 우세" if gap >= 25 else "숏 약우세"


def _confidence_label(sig):
    gap = sig["score_gap"]
    vol = sig.get("volume_ratio", 0)
    if gap >= 25 and vol >= 1.0: return "높음"
    if gap >= 15:                return "중간"
    return "낮음"


def _final_state(sig):
    d = sig["direction"]
    if d == "LONG":  return "LONG WATCH"
    if d == "SHORT": return "SHORT WATCH"
    return "WAIT"


def _build_message(symbol, sig):
    price      = sig["current_price"]
    support    = sig["support"]
    resistance = sig["resistance"]
    state      = _final_state(sig)
    bias       = _bias_label(sig)
    confidence = _confidence_label(sig)
    div        = _DIV_KO.get(sig.get("divergence"), "없음")
    bb_sig     = _BB_KO.get(sig.get("bb_signal", "NEUTRAL"), "중립")
    squeeze    = "⚡ 밴드 수축 — 큰 움직임 임박" if sig.get("bb_squeeze") else ""

    if state == "LONG WATCH":
        action     = f"{resistance:.2f} 돌파 전 롱 추격 금지, {support:.2f} 이탈 시 관점 약화"
        conclusion = f"현재는 {bias} 상태.\n{resistance:.2f} 돌파 전 롱 추격 금지.\n{support:.2f} 이탈 시 관점 재검토."
    elif state == "SHORT WATCH":
        action     = f"{support:.2f} 이탈 전 숏 추격 금지, {resistance:.2f} 돌파 시 관점 약화"
        conclusion = f"현재는 {bias} 상태.\n{support:.2f} 이탈 전 숏 추격 금지.\n{resistance:.2f} 돌파 시 관점 재검토."
    else:
        action     = f"{support:.2f} 이탈 또는 {resistance:.2f} 돌파 전 진입 금지"
        conclusion = f"현재는 관망 구간.\n{support:.2f} 이탈 전 숏 금지, {resistance:.2f} 돌파 전 롱 금지."

    bb_line = f"\n볼린저밴드: {bb_sig}"
    if squeeze:
        bb_line += f"\n{squeeze}"

    return f"""📊 {symbol} 1H 마감 종합 전광판
시간: {now_kst().strftime('%Y-%m-%d %H:%M')}
현재가: {price:.2f}

🧭 최종판정
상태: {state}
우세: {bias}
신뢰도: {confidence}
행동: {action}

🎯 핵심 가격
숏 확정: {support:.2f} 이탈
롱 전환: {resistance:.2f} 돌파
구간: {support:.2f} ~ {resistance:.2f}

📊 멀티 타임프레임
15M: {_trend('trend_15m', sig)} / 1H: {_trend('trend_1h', sig)}
4H:  {_trend('trend_4h', sig)} / 1D: {_trend('trend_1d', sig)}
구조: {sig.get('structure', '-')}

📊 지표
RSI:  {sig['rsi']:.2f} {'강세↑' if sig['rsi'] >= 50 else '약세↓'}
CCI:  {sig['cci']:.2f} {'강세↑' if sig['cci'] >= 0 else '약세↓'}
MACD: {_MACD_KO.get(sig['macd_state'], '-')}
EMA20/50/200: {sig['ema20']:.2f} / {sig['ema50']:.2f} / {sig['ema200']:.2f}
거래량: {sig.get('volume_ratio', 0):.2f}배{bb_line}
다이버전스: {div}

LONG {sig['long_score']}% · SHORT {sig['short_score']}%
박스권: {'있음 (' + sig.get('range_pos','') + ')' if sig.get('is_range') else '없음'}

📌 롱 관점
조건: {resistance:.2f} 돌파 + 거래량 증가
주의: 돌파 전 선진입 금지

📌 숏 관점
조건: {support:.2f} 이탈 + 거래량 증가
주의: 이탈 전 추격 숏 금지

✅ 결론
{conclusion}

※ 자동진입 아님. 1H 마감 기준 상황판.
"""


# ─────────────────────────────────────────────
# 메인 분석 (core_analyzer 재사용)
# ─────────────────────────────────────────────

def analyze_structure(symbol, candles_by_tf):
    sig = _core_analyze(symbol, candles_by_tf)

    if not sig.get("current_price"):
        return {
            "type": "STRUCTURE_DASHBOARD",
            "alert_type": "STRUCTURE_DASHBOARD",
            "direction": "WAIT",
            "message": f"📊 {symbol} 1H 마감 종합 전광판\n\n⚪ 데이터 부족",
        }

    message = _build_message(symbol, sig)

    return {
        "type":        "STRUCTURE_DASHBOARD",
        "alert_type":  "STRUCTURE_DASHBOARD",
        "direction":   sig["direction"],
        "state":       _final_state(sig),
        "bias":        _bias_label(sig),
        "confidence":  _confidence_label(sig),
        "message":     message,
        "image_bytes": None,   # main.py에서 chart_renderer로 채움
        **sig,
    }


# 하위 호환
def run_structure_analysis(symbol, candles_by_tf):
    return analyze_structure(symbol, candles_by_tf)

def fact_based_structure_analysis(symbol, candles_by_tf):
    return analyze_structure(symbol, candles_by_tf)

def analyze(symbol, candles_by_tf):
    return analyze_structure(symbol, candles_by_tf)
