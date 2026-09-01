"""讀學員管理 App 的 Google Sheet（Students/Classes/Payments）。

憑證沿用既有 GDRIVE_REFRESH_TOKEN（drive.readonly 即可讀 Sheets），
搭配 GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET。
"""
import os
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SHEET_ID = "1MxqLAMo0n-RowJ6a8kenA4eOp9isZYue7W1beZNTWDc"


def _service():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GDRIVE_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _get(svc, rng):
    return svc.spreadsheets().values().get(spreadsheetId=SHEET_ID, range=rng).execute().get("values", [])


def fetch_all():
    """回傳 (students_raw, classes_raw, payments_raw) 三個含表頭的二維陣列。"""
    # 開放範圍（不寫死列數）：撈全部歷史，Sheets 只回有資料的列。
    # 寫死上限會在資料成長後把最新月份(附在最底部)截掉、靜默少算。
    svc = _service()
    return (
        _get(svc, "Students!A:I"),
        _get(svc, "Classes!A:E"),
        _get(svc, "Payments!A:I"),
    )


def id2name_from(students_raw):
    """Students 表頭：id,name,phone,venue,... → {id: name}。"""
    m = {}
    for r in students_raw[1:]:
        if len(r) >= 2:
            m[r[0]] = r[1]
    return m
