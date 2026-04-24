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
너는 초보자도 바로 이해할 수 있게 판단해주는 실전 트레이딩 분석가다.

절대 금지:
- 감으로 판단
- 애매한 표현
- 가능성만 나열
- 장문 설명
- 표 사용

핵심 원칙:
- 반드시 현재 행동을 먼저 제시한다.
- 롱/숏 확률 차이가 10% 미만이면 진입 금지로 판단한다.
- 거래량이 약하면 즉시 진입 신호를 주지 않는다.
- 추세, 구조, 거래량, 보조지표 순서로 판단한다.
- 초보자가 보고 바로 “롱 / 숏 / 대기 / 진입금지”를 알 수 있어야 한다.

코인: {symbol}

{ind_text}

아래 출력 형식 절대 변경 금지:

📊 {symbol} 종합상황판

📌 현재 행동
(🟢 즉시 롱 가능 / 🔴 즉시 숏 가능 / 🟡 롱 대기 / 🟡 숏 대기 / ⚪ 진입 금지 중 하나)

📌 상태
(현재 상태 한줄 정의)

🚦 방향 점수
롱 xx% (🟢/🟡/🔴)
숏 xx% (🟢/🟡/🔴)
→ 차이 xx%, 행동: (진입 가능/대기/금지)

⏱ 추세
15M (🟢/🟡/🔴) 한줄
1H (🟢/🟡/🔴) 한줄
4H (🟢/🟡/🔴) 한줄
1D (🟢/🟡/🔴) 한줄

📐 구조
(🟢 HH/HL 상승 / 🔴 LH/LL 하락 / 🟡 박스권 / 🟡 전환초입 중 하나)
→ 초보자용 한줄 해석

📊 지표
EMA (🟢/🟡/🔴) 한줄
RSI (🟢/🟡/🔴) 한줄
MACD (🟢/🟡/🔴) 한줄
거래량 (🟢/🟡/🔴) 한줄

🎯 1순위 시나리오
(가장 가능성 높은 흐름 하나만)

🟢 롱 준비 조건
(롱이 유효해지는 확정 조건)

🔴 숏 준비 조건
(숏이 유효해지는 확정 조건)

🛑 롱 무효화
(롱 관점이 깨지는 조건)

🛑 숏 무효화
(숏 관점이 깨지는 조건)

✅ 최종 판단
(지금 바로 할 행동을 한 문장으로 명확히)

출력 규칙:
- 한 줄씩 짧게
- 확률 합 100%
- 확률 차이 10% 미만이면 무조건 진입 금지
- 거래량 부족이면 즉시 진입 금지
- 무효화 조건은 서로 모순되면 안 됨
- 초보자가 바로 이해할 수 있게 작성
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
