import os
import json


# ── 환경변수 — GOOGLE_SHEETS_KEY는 사용하지 않는다 ──────────
SPREADSHEET_ID              = os.getenv("SPREADSHEET_ID") or os.getenv("GOOGLE_SHEET_ID")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _get_client():
    """지연 임포트 — ENABLE_SHEETS=False 환경에서 gspread 없어도 봇 시작 가능"""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        raise RuntimeError("gspread 또는 google-auth 패키지 없음. pip install gspread google-auth")

    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON 환경변수 없음 (GOOGLE_SHEETS_KEY는 사용하지 않음)")

    try:
        info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"GOOGLE_SERVICE_ACCOUNT_JSON JSON 파싱 실패: {e}")

    client_email = info.get("client_email", "(없음)")
    print(f"[SHEETS] service account env loaded", flush=True)
    print(f"[SHEETS] client_email={client_email}", flush=True)
    # private_key는 절대 로그 출력 금지

    credentials = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(credentials)


def _get_spreadsheet():
    if not SPREADSHEET_ID:
        raise RuntimeError("SPREADSHEET_ID 환경변수 없음 (GOOGLE_SHEET_ID도 확인)")
    client      = _get_client()
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    print(f"[SHEETS] opened spreadsheet: {SPREADSHEET_ID}", flush=True)
    ws_titles = [ws.title for ws in spreadsheet.worksheets()]
    print(f"[SHEETS] worksheets: {ws_titles}", flush=True)
    return spreadsheet


def _get_or_create_worksheet(sheet_name):
    try:
        import gspread
        spreadsheet = _get_spreadsheet()
        ws_titles   = [ws.title for ws in spreadsheet.worksheets()]
        print(f"[SHEETS] 워크시트 목록: {ws_titles}", flush=True)

        if sheet_name in ws_titles:
            return spreadsheet.worksheet(sheet_name)

        print(f"[SHEETS] '{sheet_name}' 워크시트 없음 — 생성 시도", flush=True)
        try:
            return spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=30)
        except gspread.exceptions.APIError as api_err:
            status = getattr(api_err.response, "status_code", None)
            if status == 403:
                raise RuntimeError(
                    f"[SHEETS] 403 Forbidden: 권한 문제 또는 다른 시트 ID. "
                    f"SPREADSHEET_ID={SPREADSHEET_ID} 확인 필요"
                )
            raise
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"[SHEETS] 워크시트 접근 실패: {e}")


def save_to_sheets(sheet_name, row):
    worksheet = _get_or_create_worksheet(sheet_name)
    worksheet.append_row(row, value_input_option="USER_ENTERED")
    print(f"[SHEETS] append success: {sheet_name}", flush=True)


def get_recent_records(sheet_name, count=5):
    try:
        worksheet = _get_or_create_worksheet(sheet_name)
        rows = worksheet.get_all_values()
        return rows[-count:] if len(rows) > 1 else []
    except Exception:
        return []

