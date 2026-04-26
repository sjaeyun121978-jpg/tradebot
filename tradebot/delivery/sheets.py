import os
import json
import gspread
from google.oauth2.service_account import Credentials


SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_client():
    service_account_info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)

    credentials = Credentials.from_service_account_info(
        service_account_info,
        scopes=SCOPES
    )

    return gspread.authorize(credentials)


def get_spreadsheet():
    client = get_client()
    return client.open_by_key(SPREADSHEET_ID)


def get_or_create_worksheet(sheet_name):
    spreadsheet = get_spreadsheet()

    try:
        return spreadsheet.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(
            title=sheet_name,
            rows=1000,
            cols=30
        )


def save_to_sheets(sheet_name, row):
    worksheet = get_or_create_worksheet(sheet_name)
    worksheet.append_row(row, value_input_option="USER_ENTERED")


def get_recent_records(sheet_name, count=5):
    worksheet = get_or_create_worksheet(sheet_name)
    rows = worksheet.get_all_values()

    if len(rows) <= 1:
        return []

    return rows[-count:]
