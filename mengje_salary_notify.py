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

# 一對一課，體驗不計入收入
sheets_svc = build("sheets", "v4", credentials=creds)
sheet_name = f"{month}月"
result = sheets_svc.spreadsheets().values().get(
    spreadsheetId=os.environ["MENGJE_SHEET_ID"],
    range=f"'{sheet_name}'!A1:Z30",   # B1：放寬至 30 列，新增單價列排到第 11 列以後也讀得到
).execute()
rows = result.get("values", [])
print(f"讀取 {sheet_name}，共 {len(rows)} 列")

def to_int(s):
    """千分位逗號字串轉整數，例如 '2,000' -> 2000"""
    return int(str(s).replace(",", "")) if s not in (None, "") else 0

# 新版表格為橫向格式（欄列互換）：A 欄為項目標籤，最後一欄為「當月合計」堂數。
# 單價列 = A 欄標籤為純數字者（如 1400/1300/1500），自動偵測，
# 「日期」「當週銷售總額」「體驗」等非數字標籤自動排除。
# ⚠️ 2026-08-02：原寫死 PRICES=[1400,1300]，漏算 7 月新增的 1500 價位、孟潔被少付；
#    改為自動偵測後，日後新增價位不必改程式，避免再漏。

# A1：用標題列定位「當月合計」欄，不再用 row[-1]。
# Sheets API 會省略列尾端空白格，若合計格空白，row[-1] 會抓到中間某週的堂數 → 算錯還不報錯。
header = rows[0] if rows else []
total_col = next((i for i, c in enumerate(header) if "合計" in str(c)), len(header) - 1)
def cell_total(row):
    return to_int(row[total_col]) if len(row) > total_col else 0

def price_of(row):
    """B1：判斷這列是不是單價列，是就回傳單價、否則回 None。
    容許千分位逗號（'1,500'），並限定合理價格區間 100~2000，避免把年份/編號/統計數字誤當單價。"""
    if not row:
        return None
    clean = str(row[0]).strip().replace(",", "")
    if clean.isdigit() and 100 <= int(clean) <= 2000:
        return int(clean)
    return None

total_gross = 0
for row in rows:
    price = price_of(row)
    if price is not None:                     # 單價列
        total_gross += price * cell_total(row)

# A2：收款（當週銷售總額列）拿來跟已實現(total_gross)交叉比對——有偵錯力的檢查
sales_row = next((r for r in rows if r and "銷售總額" in str(r[0])), None)
total_paid = cell_total(sales_row) if sales_row else 0

mengje_pay    = total_gross * 0.65
studio_income = total_gross * 0.35

# ── 複查自檢：算完發出前驗證幾條規則，不通過就在訊息開頭標警告 ──
warnings = []
price_rows = [r for r in rows if price_of(r) is not None]
# 1) 完全沒偵測到單價列（分頁空白或格式改變 → 會整個算成 0）
if not price_rows:
    warnings.append(f"{sheet_name} 未偵測到任何單價列，可能分頁空白或格式改變")
# 2) 營業額為 0（分頁空白或月份抓錯）
if total_gross == 0:
    warnings.append(f"{sheet_name} 營業額為 0，可能分頁空白或月份抓錯")
# 3) 交叉比對：已實現營業額不該大於收款（收的比實現的少 = 一定哪裡錯了）
if total_paid > 0 and total_gross > total_paid:
    warnings.append(f"已實現營業額(${total_gross:,}) > 收款(${total_paid:,})，不合理，請查堂數或單價")

# ── 累計未實現（真實預收餘額）＝ 全期間收款Σ − 已實現Σ ──
# 孟潔 2026-05 才開始上課，故掃 5~12 月各分頁累加（未來空白月＝0，不影響）。
read_errors = []
def month_paid_gross(tab):
    """讀孟潔單月分頁 → (當月收款, 當月已實現)。分頁不存在或空白回 (0,0)；讀取失敗記入 read_errors。"""
    try:
        rr = sheets_svc.spreadsheets().values().get(
            spreadsheetId=os.environ["MENGJE_SHEET_ID"], range=f"'{tab}'!A1:Z30",
        ).execute().get("values", [])
    except Exception as e:
        read_errors.append(f"{tab}（{e}）")
        return 0, 0
    if not rr:
        return 0, 0
    hd = rr[0]
    tc = next((i for i, c in enumerate(hd) if "合計" in str(c)), None)
    if tc is None:                    # 找不到「合計」欄＝格式異常，別硬抓最後一欄算錯
        read_errors.append(f"{tab}（找不到合計欄）")
        return 0, 0
    def _ct(row):
        return to_int(row[tc]) if len(row) > tc else 0
    g = sum(price_of(r) * _ct(r) for r in rr if price_of(r) is not None)
    sr = next((r for r in rr if r and "銷售總額" in str(r[0])), None)
    return (_ct(sr) if sr else 0), g

cum_paid = cum_gross = 0
for m in range(5, 13):
    p, g = month_paid_gross(f"{m}月")
    cum_paid += p
    cum_gross += g
# 未實現＝預收但未上課的錢，本質 ≥ 0；跌破 0 代表已實現超過收款＝學員端呈應收，不是負預收。
cum_unrealized_raw = cum_paid - cum_gross
cum_unrealized = max(0, cum_unrealized_raw)
if read_errors:                       # 有分頁讀取失敗＝累計可能偏低，發警告別無聲
    warnings.append("累計未實現有分頁讀取失敗（數字可能偏低）：" + "、".join(read_errors))
if year != 2026:
    warnings.append(f"累計未實現目前假設孟潔 2026-05 起算，現在是 {year} 年，跨年請確認累計範圍是否要往前併")

msg = f"孟潔 {year}/{month:02d} 薪資結算\n應付薪資：${mengje_pay:,.0f}\n工作室收入：${studio_income:,.0f}"
if total_paid > 0:
    msg += f"\n（當月收款 ${total_paid:,}｜當月未實現 ${total_paid - total_gross:,}）"
msg += f"\n📊 累計未實現(預收餘額)：${cum_unrealized:,}"
if cum_unrealized_raw < 0:
    msg += f"（已實現超收款 ${-cum_unrealized_raw:,}，學員端呈應收，故預收以0計）"
if warnings:
    msg = "⚠️ 複查警告（請人工確認後再採用）\n" + "\n".join(f"・{w}" for w in warnings) + "\n\n" + msg

if os.environ.get("DRY_RUN") == "1":
    print("[DRY_RUN] 不發送 LINE，訊息如下：\n" + msg)
    raise SystemExit(0)

resp = requests.post(
    "https://api.line.me/v2/bot/message/push",
    headers={"Authorization": f"Bearer {os.environ['LINE_CHANNEL_ACCESS_TOKEN']}", "Content-Type": "application/json"},
    json={"to": os.environ["LINE_USER_ID"], "messages": [{"type": "text", "text": msg}]},
)
print(f"LINE：{resp.status_code}")
print(msg)
