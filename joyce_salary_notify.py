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

# A1：用標題列定位「當月合計」欄，不再用 row[-1]。
# Sheets API 會省略列尾端空白格，若合計格空白，row[-1] 會抓到中間某週的堂數 → 算錯還不報錯。
# 改為固定欄位置：該格空白或該列較短一律當 0，寧可算 0 也不抓錯值。
header = rows[0] if rows else []
total_col = next((i for i, c in enumerate(header) if "合計" in str(c)), len(header) - 1)
def cell_total(row):
    return to_int(row[total_col]) if len(row) > total_col else 0

total_gross = 0
for i, price in enumerate(PRICES):
    row = rows[3 + i] if len(rows) > 3 + i else []
    total_gross += price * cell_total(row)

rent_row = rows[10] if len(rows) > 10 else []
total_venue = to_int(rent_row[1]) if len(rent_row) > 1 else 0

# A2：收款（當週銷售總額列）拿來跟已實現(total_gross)交叉比對——這才是有偵錯力的檢查
sales_row = next((r for r in rows if r and "銷售總額" in str(r[0])), None)
total_paid = cell_total(sales_row) if sales_row else 0

joyce_pay     = total_gross * 0.6 - total_venue
studio_income = total_gross * 0.4 + total_venue

# ── 複查自檢：算完發出前驗證幾條規則，不通過就在訊息開頭標警告 ──
warnings = []
# 1) 單價列標籤要對得上（抓「表格位移／新增價位漏算」——孟潔踩過的坑）
for i, price in enumerate(PRICES):
    row = rows[3 + i] if len(rows) > 3 + i else []
    label = str(row[0]).strip().replace(",", "") if row else ""
    if label != str(price):
        warnings.append(f"第{4+i}列單價標籤應為 {price}，實際「{label}」→ 表格結構可能變了，數字未必可信")
# 2) 場租列標籤要像場租
rent_label = str(rent_row[0]).strip() if rent_row else ""
if "租" not in rent_label:
    warnings.append(f"場租列（第11列）標籤為「{rent_label}」，非預期的場租列")
# 3) 營業額為 0（分頁空白或月份抓錯）
if total_gross == 0:
    warnings.append(f"{sheet_name} 營業額為 0，可能分頁空白或月份抓錯")
# 4) 交叉比對：已實現營業額不該大於收款（收的比實現的少 = 一定哪裡錯了）
if total_paid > 0 and total_gross > total_paid:
    warnings.append(f"已實現營業額(${total_gross:,}) > 收款(${total_paid:,})，不合理，請查堂數或單價")
# 5) 應付薪資為負（場租費 > 分潤，通常是場租填錯）
if joyce_pay < 0:
    warnings.append(f"應付薪資為負(${joyce_pay:,.0f})，場租費可能填錯")

msg = f"JOYCE {year}/{month:02d} 薪資結算\n應付薪資：${joyce_pay:,.0f}\n工作室收入：${studio_income:,.0f}"
if total_paid > 0:
    msg += f"\n（收款 ${total_paid:,}｜未實現 ${total_paid - total_gross:,}）"
if warnings:
    msg = "⚠️ 複查警告（請人工確認後再採用）\n" + "\n".join(f"・{w}" for w in warnings) + "\n\n" + msg

resp = requests.post(
    "https://api.line.me/v2/bot/message/push",
    headers={"Authorization": f"Bearer {os.environ['LINE_CHANNEL_ACCESS_TOKEN']}", "Content-Type": "application/json"},
    json={"to": os.environ["LINE_USER_ID"], "messages": [{"type": "text", "text": msg}]},
)
print(f"LINE：{resp.status_code}")
print(msg)
