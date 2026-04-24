from claude_client import call_claude


# =========================
# 1. 팩트기반구조분석 (핵심)
# =========================
def build_fact_analysis_prompt(symbol, price, indicators):

    ind_text = ""
    if indicators:
        ind_text = f"""
현재가: {price}
RSI: {indicators['rsi']}
MACD: {indicators['macd']} / {indicators['macd_signal']} / {indicators['macd_cross']}
EMA20: {indicators['ema20']}
EMA50: {indicators['ema50']}
볼린저밴드 상단: {indicators['bb_upper']}
볼린저밴드 하단: {indicators['bb_lower']}
거래량 비율: {indicators['vol_ratio']}
"""

    return f"""
너는 트레이딩 분석가다.

감, 추측 금지.
조건 기반으로만 판단하라.

다음 구조로 분석하라:

1. 다중 타임프레임 추세
2. 구조 분석 (HH/HL/LH/LL)
3. 파동 분석
4. 보조지표 분석
5. 지지/저항 위치
6. 최종 결론

코인: {symbol}

{ind_text}
"""


def analyze_fact(symbol, price, indicators):
    prompt = build_fact_analysis_prompt(symbol, price, indicators)
    return call_claude(prompt)


# =========================
# 2. 멍꿀 정보 분석
# =========================
def analyze_info(text):

    prompt = f"""
다음 텍스트를 트레이딩 관점에서 분석하라.

출력 형식:
코인:
상황:
판단: (상승우세 / 하락우세 / 중립관망)
대응:
핵심근거:
주의사항:

텍스트:
{text}
"""
    return call_claude(prompt)


# =========================
# 3. 개돼지기법 분석
# =========================
def analyze_gaedwaeji(text):

    prompt = f"""
다음 시나리오를 구조적으로 정리하라.

출력 형식:
코인:
시간봉:
기준일:
1안:
2안:
3안:
핵심방향:
전고A:
주의:

{text}
"""
    return call_claude(prompt)


# =========================
# 4. 캔들의신 관점 해석
# =========================
def analyze_candle_view(text):

    text_clean = text.replace(" ", "")

    if "상승하는것이중요하지않습니다" in text_clean:
        return "관점: 상승 자체보다 구조가 중요 → 추세 아님"

    if "추세파동" in text_clean:
        return "관점: 아직 추세 아님 → 조정 구간"

    if "임펄스" in text_clean:
        return "관점: 강한 추세 시작 가능"

    if "조정파" in text_clean:
        return "관점: 반등 = 조정 → 기존 추세 유지"

    return "관점: 방향성 불확실"
