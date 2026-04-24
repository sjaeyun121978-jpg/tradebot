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
너는 실전 트레이더다.

출력은 "전광판 형태"로 작성한다.
긴 설명 금지.
한 줄씩 짧게.

아이콘 규칙:
🟢 상승/유리
🟡 중립/대기
🔴 하락/불리
🎯 진입 조건
🛑 무효화
📌 결론

======================

코인: {symbol}

{ind_text}

아래 형식 그대로 출력:

📊 {symbol} 종합상황판

📌 상태
(현재 시장 한줄 정의)

🚦 방향 점수
롱 xx% (아이콘)
숏 xx% (아이콘)

⏱ 추세
15M (아이콘)
1H (아이콘)
4H (아이콘)
1D (아이콘)

📐 구조
(예: LH/LL 유지 or HL/HH 전환)

📊 지표
EMA (아이콘)
RSI (아이콘)
MACD (아이콘)
거래량 (아이콘)

🎯 핵심 시나리오
(한줄)

🟢 롱 조건
(한줄)

🔴 숏 조건
(한줄)

🛑 무효화
(한줄)

======================

조건:
- 반드시 한 줄씩 짧게
- 표 금지
- 설명 길게 쓰지 말 것
- 확률 반드시 합 100%
"""
