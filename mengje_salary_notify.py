import os, requests
from datetime import date, timedelta
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

creds = Credentials(
    token=None,
    refresh_token=os.environ["GDRIVE_REFRESH_TOKEN"],
    token_uri="https://oauth2.googleapis.com/token",
    client_id=os.environ["GOOGLE_CLIENT_ID"],
    client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
    scopes=["https://www.googleapis.com/auth/drive.readonly"],
)
creds.refresh(Request())

today = date.today()
last_month_date = today.replace(day=1) - __import__("datetime").timedelta(days=1)
month = last_month_date.month
year  = last_month_date.year

# 一對一價位（體驗不計入收入）
PRICES = [1400, 1300]

sheets_svc = build("sheets", "v4", credentials=creds)
sheet_name = f"{month}月"
result = sheets_svc.spreadsheets().values().get(
    spreadsheetId=os.environ["MENGJE_SHEET_ID"],
    range=f"\'{sheet_name}\'!A4:D100",
).execute()
rows = result.get("values", [])
print(f"讀取 {sheet_name}，共 {len(rows)} 列")

total_gross = 0
for row in rows:
    if not row or not row[0] or row[0] == "當月合計":
        break
    for i, price in enumerate(PRICES):
        count = int(row[1 + i]) if len(row) > 1 + i and row[1 + i] else 0
        total_gross += price * count

mengje_pay    = total_gross * 0.65
studio_income = total_gross * 0.35
msg = f"孟潔 {year}/{month:02d} 薪資結算\n應付薪資：${mengje_pay:,.0f}\n工作室收入：${studio_income:,.0f}"

resp = requests.post(
    "https://api.line.me/v2/bot/message/push",
    headers={"Authorization": f"Bearer {os.environ['LINE_CHANNEL_ACCESS_TOKEN']}", "Content-Type": "application/json"},
    json={"to": os.environ["LINE_USER_ID"], "messages": [{"type": "text", "text": msg}]},
)
print(f"LINE：{resp.status_code}")
print(msg)
