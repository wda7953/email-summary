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

# 當月「轉私教」費用：原本柔力收、但要轉給 Joyce 上私教課的錢（只收場地費、課費不經柔力）。
# 柔力退給 Joyce → 加進 Joyce 實付、從工作室收入扣掉（兩邊相反，屬柔力↔Joyce 內部移轉）。
# 月分頁若有「轉私教／退費」列就抓（合計欄優先，退回 B 欄），沒有則為 0。
# ⚠️ 歷史的轉私教都記在「歷史2023-2026.05」退費欄、只用來扣累計未實現，不重複進當月實付。
refund_row = next((r for r in rows if r and any(k in str(r[0]) for k in ("轉私教", "私教", "退費"))), None)
month_refund = cell_total(refund_row) if refund_row else 0
if refund_row and month_refund == 0 and len(refund_row) > 1:
    month_refund = to_int(refund_row[1])

joyce_pay     = total_gross * 0.6 - total_venue + month_refund
studio_income = total_gross * 0.4 + total_venue - month_refund

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

# ── 累計未實現（真實預收餘額）＝ 全期間收款Σ − 已實現Σ − 轉出退費Σ ──
# 「歷史2023-2026.05」分頁的合計列已含 2023-05~2026-05；當年 6 月起再從各月分頁累加。
# 未來空白月份 (收款,已實現)=(0,0) 不影響，故直接掃 6~12 月。
# 退費說明（2026-08-30 使用者確認）：歷史表「退費」欄＝原本收的錢「轉去 Joyce 私教課」
#   （只收場地費、課費不經過柔力），這筆已離開柔力、不再是預收負債，故從未實現扣掉。
#   ⚠️ 2026-03 的「真退客戶」那筆不在退費欄，早已淨額寫進收款，不重複處理。
HIST_TAB = "歷史2023-2026.05"
read_errors = []
def month_paid_gross(tab):
    """讀 Joyce 單月分頁 → (當月收款, 當月已實現)。分頁不存在或空白回 (0,0)；讀取失敗記入 read_errors。"""
    try:
        rr = sheets_svc.spreadsheets().values().get(
            spreadsheetId=os.environ["GSHEET_ID"], range=f"'{tab}'!A1:Z11",
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
    g = sum(p * _ct(rr[3 + i] if len(rr) > 3 + i else []) for i, p in enumerate(PRICES))
    sr = next((r for r in rr if r and "銷售總額" in str(r[0])), None)
    return (_ct(sr) if sr else 0), g

try:
    hist = sheets_svc.spreadsheets().values().get(
        spreadsheetId=os.environ["GSHEET_ID"], range=f"'{HIST_TAB}'!A1:Z200",
    ).execute().get("values", [])
except Exception as e:
    hist = []
    read_errors.append(f"{HIST_TAB}（{e}）")
hist_hdr = hist[0] if hist else []
def hist_col(name):               # 用欄名定位，不寫死索引（歷史表若插欄也不會錯抓）
    return next((i for i, c in enumerate(hist_hdr) if str(c).strip() == name), None)
ci_paid, ci_real, ci_ref = hist_col("收款"), hist_col("已實現"), hist_col("退費")
hist_total = next((r for r in hist if r and str(r[0]).strip() == "合計"), None)
if hist_total is None or None in (ci_paid, ci_real, ci_ref):
    warnings.append(f"歷史表「{HIST_TAB}」讀取異常（缺合計列或收款/已實現/退費欄），累計未實現只含當年各月")
def hval(idx):
    return to_int(hist_total[idx]) if hist_total and idx is not None and len(hist_total) > idx else 0
cum_paid = hval(ci_paid)
cum_gross = hval(ci_real)
cum_refund = hval(ci_ref)         # 轉出退費（要扣）
for m in range(6, 13):
    p, g = month_paid_gross(f"{m}月")
    cum_paid += p
    cum_gross += g
# 未實現＝預收但未上課的錢，本質 ≥ 0；跌破 0 代表已實現超過收款＝學員端呈應收，不是負預收。
cum_unrealized_raw = cum_paid - cum_gross - cum_refund
cum_unrealized = max(0, cum_unrealized_raw)
if read_errors:                   # 有分頁讀取失敗＝累計可能偏低，發警告別無聲
    warnings.append("累計未實現有分頁讀取失敗（數字可能偏低）：" + "、".join(read_errors))
# 跨年守衛：歷史表只到 2026-05，換年前要先把 2026 整年併進歷史表，否則累計會漏
if year != 2026:
    warnings.append(f"累計未實現的歷史表只到 2026-05，現在是 {year} 年，請先把 2026-06~12 併進歷史表再改此段（否則累計漏算）")

# 固定四項格式（2026-08-31 使用者確認）：收款、薪資、工作室收入、累計未實現
msg = f"JOYCE {year}/{month:02d} 薪資結算"
msg += f"\n收款：${total_paid:,}"
msg += f"\n應付薪資：${joyce_pay:,.0f}"
msg += f"\n工作室收入：${studio_income:,.0f}"
if month_refund > 0:
    msg += f"\n（薪資含轉私教 +${month_refund:,}、已扣場租 ${total_venue:,}）"
# 未實現只看「開始執行到結算」的累計（預收款常跨月上完，當月未實現無意義）
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
