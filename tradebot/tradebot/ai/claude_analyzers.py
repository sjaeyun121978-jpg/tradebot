from tradebot.ai.claude_client import call_claude


def build_fact_analysis_prompt(symbol, price, indicators):
    ind_text = ""
    structure_text = ""

    if indicators:
        ind_text = f"""
현재가: {price}

RSI: {indicators.get('rsi')}
RSI 방향: {indicators.get('rsi_slope')}
RSI 다이버전스: {indicators.get('rsi_divergence')}

CCI: {indicators.get('cci')}
CCI 방향: {indicators.get('cci_slope')}
CCI 다이버전스: {indicators.get('cci_divergence')}

MACD: {indicators.get('macd_cross')}

EMA20: {indicators.get('ema20')}
EMA50: {indicators.get('ema50')}
EMA 상태: {indicators.get('ema_state')}

거래량비율: {indicators.get('vol_ratio')}
"""

        if "structure" in indicators:
            s = indicators["structure"]

            structure_text = f"""
구조 분석 데이터:

[15M]
구조: {s.get('15M', {}).get('structure')}
파동: {s.get('15M', {}).get('wave')}
엘리엇: {s.get('15M', {}).get('elliott')}
유사패턴: {s.get('15M', {}).get('similar_case')}

[1H]
구조: {s.get('1H', {}).get('structure')}
파동: {s.get('1H', {}).get('wave')}
엘리엇: {s.get('1H', {}).get('elliott')}
유사패턴: {s.get('1H', {}).get('similar_case')}

[4H]
구조: {s.get('4H', {}).get('structure')}
파동: {s.get('4H', {}).get('wave')}
엘리엇: {s.get('4H', {}).get('elliott')}
유사패턴: {s.get('4H', {}).get('similar_case')}

[1D]
구조: {s.get('1D', {}).get('structure')}
파동: {s.get('1D', {}).get('wave')}
엘리엇: {s.get('1D', {}).get('elliott')}
유사패턴: {s.get('1D', {}).get('similar_case')}
"""

    return f"""
너는 실전 트레이더다.
초보자도 보고 바로 행동할 수 있게 작성한다.

절대 금지:
- 애매한 표현
- 가능성만 나열
- 장문 설명
- 감으로 판단

핵심:
- “지금 행동” 먼저
- 구조 + 파동 + 다이버전스 + 지표 종합 판단
- RSI + CCI 다이버전스 반드시 반영
- 둘이 같은 방향이면 강한 신호
- 충돌하면 무조건 진입 금지

=====================

코인: {symbol}

{ind_text}

{structure_text}

=====================

출력 형식:

📊 {symbol} 종합상황판

📌 현재 행동
(🟢 즉시 롱 / 🔴 즉시 숏 / 🟡 대기 / ⚪ 진입 금지)

📌 상태
(한줄 요약)

🚦 방향 점수
롱 xx% / 숏 xx%
→ 차이 xx%, 행동: (진입 / 대기 / 금지)

⏱ 추세
15M (🟢/🟡/🔴)
1H (🟢/🟡/🔴)
4H (🟢/🟡/🔴)
1D (🟢/🟡/🔴)

📐 구조
(상승 / 하락 / 박스 / 전환)
→ 한줄 설명

📊 파동 / 엘리엇
→ 현재 위치 한줄

📊 과거 유사 구조
→ 현재 패턴 한줄

📊 다이버전스
RSI:
CCI:
종합:

📊 지표
EMA:
RSI:
CCI:
MACD:
거래량:

🎯 1순위 시나리오
(한줄)

🚨 트리거
롱:
숏:

⛔ 현재 구간
(진입 금지 / 대기)

🛑 롱 무효화
🛑 숏 무효화

✅ 최종 판단
(한줄)

=====================

규칙:
- 한 줄씩
- 확률 합 100%
- 차이 10% 미만 → 진입 금지
- 거래량 약 → 진입 금지
- 다이버전스 반드시 명시
"""


def analyze_fact(symbol, price, indicators):
    return call_claude(build_fact_analysis_prompt(symbol, price, indicators))


def analyze_info(text):
    prompt = f"""
다음 텍스트를 트레이딩 관점으로 요약

코인:
상황:
판단:
대응:
근거:

{text}
"""
    return call_claude(prompt)


def analyze_gaedwaeji(text):
    prompt = f"""
시나리오 구조 정리

코인:
시간:
1안:
2안:
3안:
핵심 방향:

{text}
"""
    return call_claude(prompt)


def analyze_candle_view(text):
    text_clean = text.replace(" ", "")

    if "상승하는것이중요하지않습니다" in text_clean:
        return "상승보다 구조 중요"

    if "추세파동" in text_clean:
        return "추세 미확정 조정"

    if "임펄스" in text_clean:
        return "강한 추세 가능성"

    if "조정파" in text_clean:
        return "반등 주의 구간"

    return "방향 불확실"
