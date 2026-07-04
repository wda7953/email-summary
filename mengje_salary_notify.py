import os, requests
from datetime import date
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
    range=f"'{sheet_name}'!A1:Z6",
).execute()
rows = result.get("values", [])
print(f"讀取 {sheet_name}，共 {len(rows)} 列")

def to_int(s):
    """千分位逗號字串轉整數，例如 '2,000' -> 2000"""
    return int(str(s).replace(",", "")) if s not in (None, "") else 0

# 新版表格為橫向格式（欄列互換）：
# row0 = 日期標題列（最後一欄是「當月合計」）
# row1 = 當週續約金額（本次結算未使用，保留給未來擴充）
# row2 = 當週銷售總額（本次結算未使用，保留給未來擴充）
# row3~4 = 2 個單價列（1400/1300），最後一欄是當月合計堂數
total_gross = 0
for i, price in enumerate(PRICES):
    row = rows[3 + i]
    count = to_int(row[-1]) if len(row) > 1 else 0
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
