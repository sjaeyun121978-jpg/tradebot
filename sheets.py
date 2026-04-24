import json
import gspread
from google.oauth2.service_account import Credentials

from config import GOOGLE_SHEETS_KEY, GOOGLE_SHEETS_ID


def get_sheets_client():
    try:
        if not GOOGLE_SHEETS_KEY or not GOOGLE_SHEETS_ID:
            return None

        key_data = json.loads(GOOGLE_SHEETS_KEY)

        scopes = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]

        creds = Credentials.from_service_account_info(key_data, scopes=scopes)

        return gspread.authorize(creds)

    except Exception as e:
        print(f"[Sheets 연결 실패] {e}")
        return None


def save_to_sheets(sheet_name, row_data):
    try:
        gc = get_sheets_client()

        if not gc:
            return False

        sh = gc.open_by_key(GOOGLE_SHEETS_ID)

        try:
            ws = sh.worksheet(sheet_name)
        except:
            ws = sh.add_worksheet(title=sheet_name, rows=1000, cols=10)

        ws.append_row([str(x) for x in row_data])

        return True

    except Exception as e:
        print(f"[Sheets 저장 실패] {e}")
        return False


def get_recent_records(sheet_name, limit=5):
    try:
        gc = get_sheets_client()

        if not gc:
            return []

        sh = gc.open_by_key(GOOGLE_SHEETS_ID)
        ws = sh.worksheet(sheet_name)

        rows = ws.get_all_values()

        return rows[-limit:] if len(rows) > limit else rows

    except Exception as e:
        print(f"[Sheets 조회 실패] {e}")
        return []
