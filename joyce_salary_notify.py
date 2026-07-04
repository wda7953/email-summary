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
PRICES = [1100, 1000, 900, 600, 500, 450, 400]

sheets_svc = build("sheets", "v4", credentials=creds)
sheet_name = f"{month}月"
result = sheets_svc.spreadsheets().values().get(
    spreadsheetId=os.environ["GSHEET_ID"],
    range=f"'{sheet_name}'!A1:Z11",
).execute()
rows = result.get("values", [])
print(f"讀取 {sheet_name}，共 {len(rows)} 列")

# 新版表格為橫向格式（欄列互換）：
# row0 = 日期標題列（最後一欄是「當月合計」）
# row1 = 當週續約金額（本次結算未使用，保留給未來擴充）
# row2 = 當週銷售總額（本次結算未使用，保留給未來擴充）
# row3~9 = 7 個單價列（1100~400），最後一欄是當月合計堂數
# row10 = 場租費（合併儲存格，只有 B 欄有值，代表整月租金）
def to_int(s):
    """千分位逗號字串轉整數，例如 '2,000' -> 2000"""
    return int(str(s).replace(",", "")) if s not in (None, "") else 0

total_gross = 0
for i, price in enumerate(PRICES):
    row = rows[3 + i]
    count = to_int(row[-1]) if len(row) > 1 else 0
    total_gross += price * count

rent_row = rows[10] if len(rows) > 10 else []
total_venue = to_int(rent_row[1]) if len(rent_row) > 1 else 0

joyce_pay     = total_gross * 0.6 - total_venue
studio_income = total_gross * 0.4
msg = f"JOYCE {year}/{month:02d} 薪資結算\n應付薪資：${joyce_pay:,.0f}\n工作室收入：${studio_income:,.0f}"

resp = requests.post(
    "https://api.line.me/v2/bot/message/push",
    headers={"Authorization": f"Bearer {os.environ['LINE_CHANNEL_ACCESS_TOKEN']}", "Content-Type": "application/json"},
    json={"to": os.environ["LINE_USER_ID"], "messages": [{"type": "text", "text": msg}]},
)
print(f"LINE：{resp.status_code}")
print(msg)
