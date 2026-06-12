import os, io, requests, openpyxl
from datetime import date, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

creds = Credentials(
    token=None,
    refresh_token=os.environ["GDRIVE_REFRESH_TOKEN"],
    token_uri="https://oauth2.googleapis.com/token",
    client_id=os.environ["GOOGLE_CLIENT_ID"],
    client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
    scopes=["https://www.googleapis.com/auth/drive.readonly"],
)
drive = build("drive", "v3", credentials=creds)
req = drive.files().get_media(fileId=os.environ["JOYCE_FILE_ID"])
buf = io.BytesIO()
dl = MediaIoBaseDownload(buf, req)
done = False
while not done:
    _, done = dl.next_chunk()
buf.seek(0)

today = date.today()
last_month_date = today.replace(day=1) - timedelta(days=1)
month = last_month_date.month
year  = last_month_date.year
PRICES = [1100, 1000, 900, 600, 500, 450, 400]

wb = openpyxl.load_workbook(buf, data_only=True)
ws = wb[f"{month}月"]
total_gross, total_venue = 0, 0
for row in ws.iter_rows(min_row=4, values_only=True):
    if not row[0] or str(row[0]) == "當月合計":
        break
    for i, price in enumerate(PRICES):
        total_gross += price * (row[1+i] or 0)
    total_venue += row[8] or 0

joyce_pay     = total_gross * 0.6 - total_venue
studio_income = total_gross * 0.4
msg = f"JOYCE {year}/{month:02d} 薪資結算\n應付薪資：${joyce_pay:,.0f}\n工作室收入：${studio_income:,.0f}"

resp = requests.post(
    "https://api.line.me/v2/bot/message/push",
    headers={"Authorization": f"Bearer {os.environ['LINE_CHANNEL_ACCESS_TOKEN']}", "Content-Type": "application/json"},
    json={"to": os.environ["LINE_USER_ID"], "messages": [{"type": "text", "text": msg}]},
)
print(f"LINE: {resp.status_code}")
print(msg)
