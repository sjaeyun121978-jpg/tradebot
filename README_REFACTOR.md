# TradeBot Refactored

## 실행

```bash
python main.py
```

실제 엔트리포인트는 `tradebot/app/main.py`, 실제 루프는 `tradebot/scheduler/jobs.py`입니다.

## 최종 리팩토링 구조

```text
tradebot/
├─ app/main.py                    # 앱 시작점
├─ config/settings.py             # 환경변수, 심볼, 주기, 기능 ON/OFF
├─ data/bybit_client.py           # Bybit 가격/캔들 수집
├─ analysis/                      # 분석 계산 전용
│  ├─ core.py                     # RSI, CCI, MACD, EMA, 구조 계산
│  ├─ entry.py                    # 진입레이더, PRE/REAL 판단
│  ├─ structure.py                # 1H 전광판 분석 결과 생성
│  └─ briefing.py                 # 일봉/주간 브리핑
├─ messages/                      # 렌더러에 넘길 payload 정리
│  ├─ radar_payload.py            # 진입레이더 payload 정리
│  └─ hourly_payload.py           # 1H 전광판 payload 정리
├─ render/                        # 이미지 생성 전용
│  ├─ chart_renderer.py           # 기존 호출부 호환 facade
│  ├─ radar_card.py               # 진입레이더 카드 전용
│  ├─ hourly_card.py              # 1H 전광판 카드 전용
│  └─ fonts/                      # 한글 폰트
├─ delivery/telegram.py           # 텔레그램 전송 전용
├─ delivery/sheets.py             # 구글시트 저장
├─ journal/signal_journal.py      # 신호 기록
├─ scheduler/jobs.py              # 언제 실행할지만 담당
├─ ai/                            # Claude 분석
└─ trading/trade_logic.py         # 자동매매 초안, 기본 비활성화
```

## 리팩토링 원칙

`jobs.py`는 분석, 문구 조립, 그림 그리기를 직접 하지 않습니다.

```text
scheduler/jobs.py
→ 실행 시점 판단, 블록 ON/OFF, 전송 호출

analysis/
→ 계산만 담당

messages/
→ 화면에 넣을 payload 정리

render/
→ 이미지만 그림

delivery/
→ 전송만 담당
```

## 현재 이미지 카드

| 기능 | 파일 |
|---|---|
| 진입레이더 | `tradebot/render/radar_card.py` |
| 1H 마감 종합 전광판 | `tradebot/render/hourly_card.py` |
| 기존 호환 wrapper | `tradebot/render/chart_renderer.py` |

## 카드 추가 방법

새 카드가 필요하면 `chart_renderer.py`에 계속 붙이지 않습니다.

1. `messages/새기능_payload.py` 생성
2. `render/새기능_card.py` 생성
3. `scheduler/jobs.py`에서 실행 시점과 전송만 연결
4. 기존 함수명이 필요하면 `chart_renderer.py`에 wrapper만 추가

## 운영 블록 스위치

```env
ENABLE_ENTRY_RADAR=true
ENABLE_HOURLY_DASHBOARD=true
ENABLE_DAILY_BRIEFING=true
ENABLE_PRE_REAL=true
ENABLE_INFO_ANALYSIS=false
ENABLE_AUTO_TRADE=false
```

## 필수 환경변수

```env
TELEGRAM_TOKEN=...
TELEGRAM_CHAT_ID=...
SYMBOLS=BTCUSDT,ETHUSDT
```

구글시트 사용 시:

```env
ENABLE_SHEETS=true
GOOGLE_SERVICE_ACCOUNT_JSON=...
SPREADSHEET_ID=...
```

## 주의

`ENABLE_AUTO_TRADE`는 기본값 `false`입니다. 자동매매는 현재 별도 검증 전까지 안전모드로 둡니다.


## STEP 성능 검증 운영 기준

1. v9 배포 후 최소 72시간 동안 조건 변경 금지
2. STEP 로그 최소 50건 미만이면 튜닝 금지
3. 승률 판단 기준
   - 60% 이상: 조건 유지 가능
   - 50~59%: 미세조정 후보
   - 45~49%: 조건 강화 후보
   - 45% 미만: 조건 재설계 후보
4. 튜닝 대상 우선순위
   - STEP+방향별 승률
   - 저거래량 구간 실패
   - 4H 역추세 실패
   - 특정 market_state 실패
   - 특정 reversal_score 구간 실패
5. 자동 조건 변경 금지
   - tuning_report.json은 추천만 제공
   - 실제 조건 변경은 사람이 검토 후 별도 반영
