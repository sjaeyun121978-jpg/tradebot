# TradeBot Refactored

## 실행 파일
- Railway 또는 로컬 실행: `python main.py`
- 실제 엔트리포인트: `tradebot/app/main.py`
- 실제 루프: `tradebot/scheduler/jobs.py`

## 데이터 소스
- Binance 제거
- Bybit v5 linear market 기준으로 통합
- 심볼 기본값: `BTCUSDT,ETHUSDT`
- 환경변수 `SYMBOLS`로 변경 가능

## 폴더 역할
```text
tradebot/
├─ app/main.py                 # 실행 시작점
├─ config/settings.py          # 환경변수, 심볼, 주기, 임계값
├─ data/bybit_client.py        # Bybit 가격/캔들 수집 및 캐시
├─ analysis/core.py            # EMA, RSI, MACD, 구조, 점수 계산
├─ analysis/structure.py       # 팩트기반 구조분석
├─ analysis/signal.py          # PRE/REAL/RADAR 판단
├─ analysis/entry.py           # 진입레이더, 진입타이밍 메시지
├─ analysis/briefing.py        # 일봉/주간 브리핑
├─ render/chart_renderer.py    # 텔레그램 이미지 카드
├─ delivery/telegram.py        # 텔레그램 전송 통합
├─ delivery/sheets.py          # 구글시트 저장
├─ journal/signal_journal.py   # 신호기록
├─ scheduler/jobs.py           # 15분봉, 정시, 일봉 작업 루프
├─ ai/claude_client.py         # Claude API
├─ ai/claude_analyzers.py      # Claude 분석 프롬프트
└─ trading/trade_logic.py      # 자동매매 초안, 현재 분리 보관
```

## 주요 통합 내용
1. `main.py`를 실행 래퍼로 축소했다.
2. Binance 수집 로직을 제거하고 Bybit 수집 로직으로 통합했다.
3. 텔레그램 전송은 `tradebot/delivery/telegram.py`로 통합했다.
4. 정시 전광판, 15분봉 진입레이더, 브리핑, PRE/REAL 실행 관리는 `tradebot/scheduler/jobs.py`로 분리했다.
5. 기존 분석 로직은 누락 방지를 위해 기능 단위로 이동했다.
6. 폰트는 기존 `fonts/` 폴더를 유지하고 렌더러에서 루트 폰트 경로를 참조하도록 수정했다.

## 배포 전 확인 환경변수
```text
TG_BOT_TOKEN 또는 TELEGRAM_TOKEN
TG_CHAT_ID 또는 TELEGRAM_CHAT_ID
ENABLE_SHEETS=false 또는 true
GOOGLE_SERVICE_ACCOUNT_JSON
SPREADSHEET_ID
ANTHROPIC_KEY
SYMBOLS=BTCUSDT,ETHUSDT
```
