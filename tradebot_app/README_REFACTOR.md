# Refactor Guide

## 구조 원칙

- 데이터 수집은 `tradebot/data`만 담당합니다.
- 지표 계산은 `tradebot/indicators`만 담당합니다.
- 판단 근거 생성은 `tradebot/evidence`만 담당합니다.
- STEP 판단은 `tradebot/step`만 담당합니다.
- 메시지 전송은 `tradebot/notify`만 담당합니다.
- 이미지 생성은 `tradebot/render`만 담당합니다.
- 실행 순서는 `tradebot/scheduler`만 담당합니다.

## 수정 위치

| 수정 대상 | 수정 파일 |
|---|---|
| WAIT/EARLY/PRE 조건 | `tradebot/step/detect_step.py` |
| REAL/REAL_1/REAL_2 기준 | `tradebot/step/decide_real.py` |
| HOLD/EXIT | `tradebot/step/manage_position.py` |
| RSI | `tradebot/indicators/rsi.py` |
| CCI | `tradebot/indicators/cci.py` |
| EMA | `tradebot/indicators/ema.py` |
| MACD | `tradebot/indicators/macd.py` |
| Fibo | `tradebot/indicators/fibo.py` |
| Divergence | `tradebot/indicators/divergence.py` |
| 매집 근거 | `tradebot/evidence/detect_accumulation.py` |
| 분산 근거 | `tradebot/evidence/detect_distribution.py` |
| Trap/페이크 위험 | `tradebot/evidence/detect_trap.py` |
| STEP 메시지 | `tradebot/notify/send_step_message.py` |
| STEP 카드 | `tradebot/render/step_card.py` |
| 실행 주기 | `tradebot/scheduler/run_cycle.py` |

## 절대 금지

- `scheduler`에서 판단 로직을 추가하지 않습니다.
- `notify`에서 점수나 STEP을 변경하지 않습니다.
- `render`에서 판단 로직을 추가하지 않습니다.
- REAL 조건 변경이 EARLY/PRE에 영향을 주면 안 됩니다.
- EARLY/PRE 조건 변경이 REAL 기준에 영향을 주면 안 됩니다.

## STEP 흐름

```text
get_market_data
→ run_indicators
→ run_evidence
→ detect_step
→ decide_real
→ manage_position
→ send_step_message
```

## 배포

GitHub에는 `tradebot_app` 폴더 하나를 운영 단위로 올립니다.
Railway/Nixpacks 실행 기준 디렉터리는 `tradebot_app`입니다.
