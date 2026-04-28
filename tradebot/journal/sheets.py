"""
journal/sheets.py
Google Sheets 연동 모듈

역할:
  - signals 탭: 신호 기록 upsert
  - summary 탭: 일일 요약 저장
  - 모든 실패는 로그만 남기고 메인 봇 보호

설정 (Railway 환경변수):
  ENABLE_GOOGLE_SHEETS=true
  GOOGLE_SHEET_ID=스프레드시트ID
  GOOGLE_SERVICE_ACCOUNT_JSON=JSON문자열 또는 base64

Google Sheets 설정 방법:
  1. Google Cloud → Service Account 생성 → JSON Key 발급
  2. Railway 환경변수에 GOOGLE_SERVICE_ACCOUNT_JSON 입력
     (JSON 원본 문자열 또는 base64 인코딩 둘 다 지원)
  3. Google Sheet 문서 생성 → URL에서 Sheet ID 복사
  4. Railway 환경변수에 GOOGLE_SHEET_ID 입력
  5. 서비스 계정 이메일을 해당 시트에 편집자로 공유
  6. ENABLE_GOOGLE_SHEETS=true 설정

  ⚠️ 서비스 계정 JSON 파일은 절대 GitHub에 올리지 말 것
"""

import base64
import json
import os

from tradebot.journal.storage import SIGNAL_COLUMNS

# summary 탭 헤더 (지시서 기준)
SUMMARY_COLUMNS = [
    "generated_at", "total_signals", "long_count", "short_count",
    "wait_count", "blocked_count", "tp1_hit_rate", "tp2_hit_rate",
    "sl_hit_rate", "avg_mfe", "avg_mae", "avg_rr",
    "best_symbol", "worst_symbol", "best_market_state", "worst_market_state",
    "comment",
]

# gspread 클라이언트 캐시 (인증 비용 절감)
_client_cache     = None
_sheet_cache      = {}
_worksheet_cache  = {}


def _log(msg: str):
    print(f"[SHEETS] {msg}", flush=True)


def _logerr(msg: str):
    print(f"[SHEETS ERROR] {msg}", flush=True)


# ─────────────────────────────────────────────
# 설정 체크
# ─────────────────────────────────────────────

def is_google_sheets_enabled() -> bool:
    """Google Sheets 연동 활성화 여부"""
    from tradebot.config import settings
    if not getattr(settings, "ENABLE_GOOGLE_SHEETS", False):
        return False
    if not getattr(settings, "GOOGLE_SHEET_ID", ""):
        return False
    if not (getattr(settings, "GOOGLE_SERVICE_ACCOUNT_JSON", "") or getattr(settings, "GOOGLE_SHEETS_KEY", "")):
        return False
    return True


def _load_service_account_info() -> dict:
    """
    GOOGLE_SERVICE_ACCOUNT_JSON 환경변수에서 서비스 계정 정보 로드
    JSON 원본 문자열 또는 base64 인코딩 둘 다 지원
    """
    from tradebot.config import settings
    raw = (getattr(settings, "GOOGLE_SERVICE_ACCOUNT_JSON", "") or "").strip() or (
        getattr(settings, "GOOGLE_SHEETS_KEY", "") or "").strip()
    if not raw:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON 또는 GOOGLE_SHEETS_KEY 환경변수 없음")

    # 먼저 JSON 파싱 시도
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass

    # base64 디코딩 후 JSON 파싱
    try:
        decoded = base64.b64decode(raw).decode("utf-8")
        return json.loads(decoded)
    except Exception as e:
        raise ValueError(f"서비스 계정 JSON 파싱 실패: {e}")


# ─────────────────────────────────────────────
# 클라이언트 / 시트 접근
# ─────────────────────────────────────────────

def get_gspread_client():
    """gspread 클라이언트 반환 (캐시)"""
    global _client_cache
    if _client_cache is not None:
        return _client_cache

    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        raise RuntimeError("gspread 또는 google-auth 패키지 없음")

    info = _load_service_account_info()
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds  = Credentials.from_service_account_info(info, scopes=scopes)
    client = gspread.authorize(creds)
    _client_cache = client
    _log("connected")
    return client


def get_sheet():
    """스프레드시트 객체 반환 (캐시)"""
    from tradebot.config import settings
    sheet_id = getattr(settings, "GOOGLE_SHEET_ID", "")
    if sheet_id in _sheet_cache:
        return _sheet_cache[sheet_id]

    client = get_gspread_client()
    sheet  = client.open_by_key(sheet_id)
    _sheet_cache[sheet_id] = sheet
    return sheet


def ensure_worksheet(tab_name: str, headers: list):
    """
    탭이 없으면 자동 생성 + 첫 행에 헤더 삽입
    반환: worksheet 객체
    """
    cache_key = f"{tab_name}"
    if cache_key in _worksheet_cache:
        return _worksheet_cache[cache_key]

    try:
        import gspread
        sheet = get_sheet()
        try:
            ws = sheet.worksheet(tab_name)
        except gspread.WorksheetNotFound:
            ws = sheet.add_worksheet(title=tab_name, rows=5000, cols=len(headers) + 5)
            ws.append_row(headers, value_input_option="USER_ENTERED")
            _log(f"worksheet created: {tab_name}")

        # 헤더 없으면 삽입
        try:
            existing = ws.row_values(1)
            if not existing:
                ws.append_row(headers, value_input_option="USER_ENTERED")
        except Exception:
            pass

        _worksheet_cache[cache_key] = ws
        _log(f"worksheet ready: {tab_name}")
        return ws

    except Exception as e:
        _logerr(f"ensure_worksheet({tab_name}) 실패: {e}")
        raise


def _invalidate_cache():
    """인증 오류 시 캐시 초기화"""
    global _client_cache
    _client_cache = None
    _sheet_cache.clear()
    _worksheet_cache.clear()


# ─────────────────────────────────────────────
# 신호 기록
# ─────────────────────────────────────────────

def _find_signal_row(ws, signal_id: str) -> int:
    """
    signal_id 컬럼(A열=1번)에서 해당 값의 행 번호 반환
    못 찾으면 -1 반환
    """
    try:
        # signal_id는 첫 번째 컬럼
        col_values = ws.col_values(1)  # A열 전체
        for i, val in enumerate(col_values):
            if val == signal_id:
                return i + 1  # 1-indexed
        return -1
    except Exception:
        return -1


def append_signal_row(row: dict) -> bool:
    """신호 행을 signals 탭에 append (중복 체크 없음)"""
    try:
        from tradebot.config import settings
        ws      = ensure_worksheet(settings.GOOGLE_SHEET_SIGNALS_TAB, SIGNAL_COLUMNS)
        values  = [str(row.get(col, "")) for col in SIGNAL_COLUMNS]
        ws.append_row(values, value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        _logerr(f"append_signal_row 실패: {e}")
        return False


def upsert_signal_row(row: dict) -> bool:
    """
    signal_id 기준 upsert
    있으면 해당 행 업데이트, 없으면 append
    """
    try:
        from tradebot.config import settings
        ws        = ensure_worksheet(settings.GOOGLE_SHEET_SIGNALS_TAB, SIGNAL_COLUMNS)
        signal_id = str(row.get("signal_id", ""))
        if not signal_id:
            return False

        row_num = _find_signal_row(ws, signal_id)
        values  = [str(row.get(col, "")) for col in SIGNAL_COLUMNS]

        if row_num > 0:
            # 기존 행 업데이트
            ws.update(f"A{row_num}", [values], value_input_option="USER_ENTERED")
            _log(f"signal updated: {signal_id}")
        else:
            # 신규 append
            ws.append_row(values, value_input_option="USER_ENTERED")
            _log(f"signal upserted: {signal_id}")

        return True

    except Exception as e:
        _logerr(f"upsert_signal_row 실패: {e}")
        _invalidate_cache()
        return False


def append_summary_row(summary: dict) -> bool:
    """summary 탭에 요약 행 추가"""
    try:
        from tradebot.config import settings
        ws      = ensure_worksheet(settings.GOOGLE_SHEET_SUMMARY_TAB, SUMMARY_COLUMNS)
        values  = [str(summary.get(col, "")) for col in SUMMARY_COLUMNS]
        ws.append_row(values, value_input_option="USER_ENTERED")
        _log("summary row appended")
        return True
    except Exception as e:
        _logerr(f"append_summary_row 실패: {e}")
        return False


def sync_csv_to_sheet(csv_path: str, tab_name: str) -> bool:
    """
    CSV 전체를 Google Sheets 탭에 동기화
    API quota 주의: 대량 데이터는 batch_update 사용
    """
    try:
        import csv as csv_mod
        from tradebot.config import settings

        if not os.path.exists(csv_path):
            return False

        with open(csv_path, "r", encoding="utf-8") as f:
            reader  = csv_mod.DictReader(f)
            headers = reader.fieldnames or []
            rows    = list(reader)

        if not headers or not rows:
            return False

        ws = ensure_worksheet(tab_name, headers)

        # 기존 데이터 지우고 전체 재작성 (batch)
        ws.clear()
        ws.append_row(headers, value_input_option="USER_ENTERED")

        batch = [[str(r.get(col, "")) for col in headers] for r in rows]
        if batch:
            ws.append_rows(batch, value_input_option="USER_ENTERED")

        _log(f"sync_csv_to_sheet 완료: {len(rows)}행 → {tab_name}")
        return True

    except Exception as e:
        _logerr(f"sync_csv_to_sheet 실패: {e}")
        return False


# ─────────────────────────────────────────────
# 안전 래퍼 (절대 예외 던지지 않음)
# ─────────────────────────────────────────────

def safe_write_signal(row: dict) -> bool:
    """
    CSV 저장 후 호출되는 안전 래퍼
    실패해도 False 반환만, 절대 예외 던지지 않음
    """
    if not is_google_sheets_enabled():
        return False
    try:
        return upsert_signal_row(row)
    except Exception as e:
        _logerr(f"safe_write_signal 실패: {e}")
        return False


def safe_write_summary(summary: dict) -> bool:
    """
    summary를 Google Sheets에 안전하게 저장
    """
    if not is_google_sheets_enabled():
        return False
    try:
        return append_summary_row(summary)
    except Exception as e:
        _logerr(f"safe_write_summary 실패: {e}")
        return False
