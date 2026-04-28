import os
import json


SPREADSHEET_ID              = os.getenv("SPREADSHEET_ID")
GOOGLE_SERVICE_ACCOUNT_JSON = (
    os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    or os.getenv("GOOGLE_SHEETS_KEY")
)

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
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON 또는 GOOGLE_SHEETS_KEY 환경변수 없음")

    print("[SHEETS] service account env loaded", flush=True)
    info        = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    credentials = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(credentials)


def _get_spreadsheet():
    if not SPREADSHEET_ID:
        raise RuntimeError("SPREADSHEET_ID 환경변수 없음")
    return _get_client().open_by_key(SPREADSHEET_ID)


def _get_or_create_worksheet(sheet_name):
    try:
        import gspread
        spreadsheet = _get_spreadsheet()
        try:
            return spreadsheet.worksheet(sheet_name)
        except gspread.WorksheetNotFound:
            return spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=30)
    except Exception as e:
        raise RuntimeError(f"워크시트 접근 실패: {e}")


def save_to_sheets(sheet_name, row):
    worksheet = _get_or_create_worksheet(sheet_name)
    worksheet.append_row(row, value_input_option="USER_ENTERED")


def get_recent_records(sheet_name, count=5):
    try:
        worksheet = _get_or_create_worksheet(sheet_name)
        rows = worksheet.get_all_values()
        return rows[-count:] if len(rows) > 1 else []
    except Exception:
        return []
