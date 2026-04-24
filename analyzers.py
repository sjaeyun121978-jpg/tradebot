from claude_client import call_claude


def build_fact_analysis_prompt(symbol, price, indicators):

    ind_text = ""
    if indicators:
        ind_text = f"""
현재가: {price}
RSI: {indicators['rsi']}
MACD: {indicators['macd_cross']}
EMA20: {indicators['ema20']}
EMA50: {indicators['ema50']}
거래량비율: {indicators['vol_ratio']}
"""

    return f"""
너는 감이 아닌 조건 기반으로만 판단하는 실전 트레이더다.

절대 금지:
- 감으로 판단
- 애매한 표현
- 가능성 나열
- 장문 설명

반드시 현재 데이터 조건 충족 여부로만 판단한다.

코인: {symbol}

{ind_text}

출력 형식 절대 변경 금지:

📊 {symbol} 종합상황판

📌 상태
(현재 상태 한줄 정의)

🚦 방향 점수
롱 xx% (🟢/🟡/🔴)
숏 xx% (🟢/🟡/🔴)

⏱ 추세
15M (🟢/🟡/🔴)
1H (🟢/🟡/🔴)
4H (🟢/🟡/🔴)
1D (🟢/🟡/🔴)

📐 구조
(HH/HL 상승 or LH/LL 하락 or 전환초입 중 하나)

📊 지표
EMA (🟢/🟡/🔴)
RSI (🟢/🟡/🔴)
MACD (🟢/🟡/🔴)
거래량 (🟢/🟡/🔴)

🎯 핵심 시나리오
(가장 가능성 높은 1개만)

🟢 롱 조건
(확정 조건만)

🔴 숏 조건
(확정 조건만)

🛑 무효화
(명확한 가격 조건)

조건:
- 확률 합 100%
- 표 금지
- 한 줄씩 짧게
- 설명 길게 쓰지 말 것
"""


def analyze_fact(symbol, price, indicators):
    prompt = build_fact_analysis_prompt(symbol, price, indicators)
    return call_claude(prompt)


def analyze_info(text):
    prompt = f"""
다음 텍스트를 트레이딩 관점에서 분석하라.

출력 형식:
코인:
상황:
판단: 상승우세 / 하락우세 / 중립관망
대응:
핵심근거:
주의사항:

텍스트:
{text}
"""
    return call_claude(prompt)


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

텍스트:
{text}
"""
    return call_claude(prompt)


def analyze_candle_view(text):
    text_clean = text.replace(" ", "")

    if "상승하는것이중요하지않습니다" in text_clean:
        return "관점: 상승 자체보다 구조가 중요 → 추세 확정 아님"

    if "추세파동" in text_clean:
        return "관점: 아직 추세파동 확정 아님 → 조정 구간"

    if "임펄스" in text_clean and "조정파" in text_clean:
        return "관점: 다음 돌파가 임펄스인지 조정파인지 확인 필요"

    if "임펄스" in text_clean:
        return "관점: 강한 추세 시작 가능성 확인 필요"

    if "조정파" in text_clean:
        return "관점: 현재 반등은 조정 가능성 → 추격 주의"

    return "관점: 방향성 불확실 → 추가 조건 확인 필요"
