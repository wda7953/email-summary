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

# ── 第二部分：孟潔跟 olan 上一對一課，要從薪資扣掉「當月堂數 × 單價」──
# 堂數來源＝學員 App 的 Google Sheet（孟潔在 App 裡就是一位學員，名字＝「孟潔」，她名下所有上課記錄都是這門一對一）。
# Sheet 分頁：Students['id','name',...]／Classes['id','student_id','date','venue','type','content',...]（見 student-app-gas/程式碼.js）。
STUDENT_APP_SHEET_ID = os.environ.get("STUDENT_APP_SHEET_ID", "1MxqLAMo0n-RowJ6a8kenA4eOp9isZYue7W1beZNTWDc")
MENGJE_STUDENT_NAME  = "孟潔"   # 孟潔在學員 App 裡的名字
ONE_ON_ONE_RATE      = 800     # 一對一單價（元／堂）

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

# ── 第二部分：扣掉孟潔當月跟 olan 上的一對一堂數 × 單價 ──
# 只扣「實際給孟潔的錢」，不動工作室收入(柔力)——這筆是孟潔付給 olan 個人的課費。
one_on_one_sessions = 0            # 孟潔當月跟 olan 上的堂數
one_on_one_error    = None        # 讀 App 失敗時記原因，發警告不無聲當 0
try:
    def _col(hdr, *names):
        """依欄名找欄位索引（不寫死位置，欄序改了也不會抓錯）。"""
        for i, c in enumerate(hdr):
            if str(c).strip() in names:
                return i
        return None
    # 1) Students 分頁：用名字找孟潔的 student_id
    stu = sheets_svc.spreadsheets().values().get(
        spreadsheetId=STUDENT_APP_SHEET_ID, range="Students!A1:Z2000",
    ).execute().get("values", [])
    if not stu:
        raise ValueError("Students 分頁讀不到資料")
    s_hdr = stu[0]
    s_id_col, s_name_col = _col(s_hdr, "id"), _col(s_hdr, "name")
    if s_id_col is None or s_name_col is None:
        raise ValueError("Students 分頁找不到 id／name 欄")
    mengje_id = next(
        (r[s_id_col] for r in stu[1:]
         if len(r) > max(s_id_col, s_name_col) and str(r[s_name_col]).strip() == MENGJE_STUDENT_NAME),
        None,
    )
    if not mengje_id:
        raise ValueError(f"學員 App 找不到名為「{MENGJE_STUDENT_NAME}」的學員")
    # 2) Classes 分頁：數孟潔名下、日期落在結算月的上課記錄筆數
    cls = sheets_svc.spreadsheets().values().get(
        spreadsheetId=STUDENT_APP_SHEET_ID, range="Classes!A1:Z5000",
    ).execute().get("values", [])
    if not cls:
        raise ValueError("Classes 分頁讀不到資料")
    c_hdr = cls[0]
    c_sid_col, c_date_col = _col(c_hdr, "student_id"), _col(c_hdr, "date")
    if c_sid_col is None or c_date_col is None:
        raise ValueError("Classes 分頁找不到 student_id／date 欄")
    ym = f"{year}-{month:02d}"     # 日期字串前 7 碼＝年月（App 存 YYYY-MM-DD 或 ISO，切前綴比對即可）
    for r in cls[1:]:
        if len(r) <= max(c_sid_col, c_date_col):
            continue
        if str(r[c_sid_col]).strip() == str(mengje_id).strip() and str(r[c_date_col])[:7] == ym:
            one_on_one_sessions += 1
except Exception as e:
    one_on_one_error = str(e)

one_on_one_deduct = one_on_one_sessions * ONE_ON_ONE_RATE
mengje_actual     = mengje_pay - one_on_one_deduct   # 實際給孟潔的錢

# ── 複查自檢：算完發出前驗證幾條規則，不通過就在訊息開頭標警告 ──
warnings = []
# 一對一堂數讀取失敗＝可能少扣或多付，一定要人工確認別無聲
if one_on_one_error:
    warnings.append(f"讀學員 App 一對一堂數失敗（{one_on_one_error}）→ 本月未扣一對一課費，請人工確認")
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

# 固定四項格式（2026-08-31 使用者確認）：收款、薪資、工作室收入、累計未實現
msg = f"孟潔 {year}/{month:02d} 薪資結算"
msg += f"\n收款：${total_paid:,}"
msg += f"\n應付薪資：${mengje_pay:,.0f}"
# 第二部分：扣掉跟 olan 上的一對一課費，補一行淨額（工作室收入不受影響）
if one_on_one_sessions > 0:
    msg += f"\n　扣一對一課費：-${one_on_one_deduct:,}（{one_on_one_sessions}堂×{ONE_ON_ONE_RATE}）"
    msg += f"\n　實際給孟潔：${mengje_actual:,.0f}"
elif one_on_one_error is None:
    msg += f"\n　一對一課費：$0（本月無跟olan上課）"
msg += f"\n工作室收入：${studio_income:,.0f}"
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
