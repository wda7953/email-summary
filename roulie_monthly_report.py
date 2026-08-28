import os, re
from datetime import date, datetime, timedelta
import caldav, pytz, requests
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

TZ = pytz.timezone("Asia/Taipei")
ICLOUD_USER = "wda7953@hotmail.com"
ICLOUD_PASS = os.environ["ICLOUD_PASSWORD"]
GCAL_ID = "1b49f93678583508e8185ed6fe71f414c19f09ff801eac2a7bbe08e28b22dd76@group.calendar.google.com"

WUSHI_SKIP = re.compile(r"^(打掃|[xX]|.*另計|黃誼淇|鳳甲國中)")
ROULIE_PER_SESSION = {
    "品漩": 600, "蔡清蓉": 1000, "蔡青蓉": 1000,
    "鳳琴姊": 700, "鳳琴姐": 700, "仁哥": 700, "育睿": 1500,
}
HOURLY_RATE = 700

def month_range(year, month):
    nxt = date(year + (month // 12), month % 12 + 1, 1)
    return datetime(year, month, 1, tzinfo=TZ), datetime(nxt.year, nxt.month, 1, tzinfo=TZ)

def icloud_cal(name_kw):
    client = caldav.DAVClient(url="https://caldav.icloud.com",
                               username=ICLOUD_USER, password=ICLOUD_PASS)
    cal = next((c for c in client.principal().calendars() if name_kw in str(c.name)), None)
    if not cal:
        raise ValueError(f"找不到行事曆：{name_kw}")
    return cal

def fetch_wushi(year, month):
    cal = icloud_cal("武士")
    start, end = month_range(year, month)
    sessions, gross, hours, defaults = 0, 0, 0.0, 0
    for ev in cal.search(start=start, end=end, event=True, expand=True):
        try:
            comp = ev.icalendar_component
            summary = str(comp.get("SUMMARY", ""))
            if WUSHI_SKIP.match(summary):
                continue
            nums = [int(n) for n in re.findall(r"\d+", summary) if 500 <= int(n) <= 1600]
            price = nums[-1] if nums else 900
            if not nums:              # 摘要抓不到金額 → 用 900 預設（A3：統計預設次數）
                defaults += 1
            dt_s = comp.get("DTSTART").dt
            dt_e = comp.get("DTEND").dt if comp.get("DTEND") else None
            hours += (dt_e - dt_s).total_seconds() / 3600 if dt_e else 1.0
            sessions += 1
            gross += price
        except:
            pass
    return sessions, gross, hours, defaults

def extract_roulie_name(summary):
    name = re.sub(r"[（(]柔力[)）]", "", summary)
    name = re.sub(r"\d.*$", "", name).strip()
    return name

def fetch_roulie_icloud(year, month):
    cal = icloud_cal("工作室")
    start, end = month_range(year, month)
    events = []
    for ev in cal.search(start=start, end=end, event=True, expand=True):
        try:
            comp = ev.icalendar_component
            summary = str(comp.get("SUMMARY", ""))
            if "柔力" not in summary:
                continue
            dt_s = comp.get("DTSTART").dt
            dt_e = comp.get("DTEND").dt if comp.get("DTEND") else None
            hours = (dt_e - dt_s).total_seconds() / 3600 if (dt_e and hasattr(dt_s, "hour")) else 0
            name = extract_roulie_name(summary)
            events.append({"name": name, "hours": hours})
        except:
            pass
    return events

def fetch_roulie_gcal(year, month):
    creds = Credentials(
        token=None, refresh_token=os.environ["GCAL_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/calendar.readonly"],
    )
    creds.refresh(Request())
    svc = build("calendar", "v3", credentials=creds)
    start, end = month_range(year, month)
    result = svc.events().list(
        calendarId=GCAL_ID, singleEvents=True, orderBy="startTime",
        timeMin=start.isoformat(), timeMax=end.isoformat(),
    ).execute()
    events = []
    for item in result.get("items", []):
        summary = item.get("summary", "")
        is_olan = bool(re.search(r"\bolan\b", summary, re.IGNORECASE))
        if not (is_olan or "柔力" in summary):
            continue
        # B3：跳過全天事件（無 dateTime）。全天事件會被算成 24 小時倍數，多為個人行程非上課
        if not item["start"].get("dateTime"):
            continue
        s = item["start"]["dateTime"]
        e = item["end"].get("dateTime", item["end"].get("date"))
        dt_s = datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(TZ)
        dt_e = datetime.fromisoformat(e.replace("Z", "+00:00")).astimezone(TZ)
        hours = (dt_e - dt_s).total_seconds() / 3600
        name = "Olan" if is_olan else extract_roulie_name(summary)
        events.append({"name": name, "hours": hours})
    return events

def main():
    today = date.today()
    last = today.replace(day=1) - timedelta(days=1)
    year, month = last.year, last.month
    print(f"計算 {year}/{month}...")

    w_sessions, w_gross, w_hours, w_defaults = fetch_wushi(year, month)
    w_income = round(w_gross * 0.6)

    r_events = fetch_roulie_icloud(year, month) + fetch_roulie_gcal(year, month)
    r_sessions, r_prepay, r_olan_hrs, r_income = 0, 0, 0.0, 0
    prepay_names = {}  # B2：記下被當成預收款的姓名＋堂數，列進月報供人工核（抓「新學員/打錯字被靜默漏算」）
    for ev in r_events:
        name, hours = ev["name"], ev["hours"]
        if name == "Olan":
            r_olan_hrs += hours
            r_income += round(hours * HOURLY_RATE)
        elif name in ROULIE_PER_SESSION:
            r_sessions += 1
            r_income += ROULIE_PER_SESSION[name]
        else:
            r_sessions += 1
            r_prepay += 1
            if name:
                prepay_names[name] = prepay_names.get(name, 0) + 1
    r_hours = sum(ev["hours"] for ev in r_events)
    total_hours = w_hours + r_hours

    # ── 複查自檢：發出前驗證幾條規則，不通過就在訊息開頭標警告 ──
    warnings = []
    # 1) 三個來源全 0（行事曆讀取失敗／授權過期／月份無資料，最容易被忽略的靜默錯）
    if w_sessions == 0 and r_sessions == 0 and r_olan_hrs == 0:
        warnings.append("武士＋柔力皆抓到 0 堂，行事曆可能讀取失敗、授權過期或該月無資料")
    # 2) 有柔力事件解析不到姓名（抽成/預收歸屬會錯）
    unnamed = sum(1 for ev in r_events if not ev["name"])
    if unnamed:
        warnings.append(f"{unnamed} 筆柔力事件無法解析姓名，收入歸屬可能有誤")
    # 3) 武士全部堂數都靠 900 預設（單一堂 900 屬正常，但「整月每堂都抓不到金額」＝價格格式可能全變了）
    if w_sessions >= 3 and w_defaults == w_sessions:
        warnings.append(f"武士 {w_sessions} 堂全部用 900 預設（都抓不到金額），價格格式可能已改變")

    msg = (
        f"【{year}年{month}月 收入月報】\n"
        f"\n"
        f"＝工時＝\n"
        f"武士：{w_sessions} 堂\n"
        f"柔力：{r_sessions} 堂 + {r_olan_hrs:.1f} 小時 Olan\n"
        f"總工時：{total_hours:.1f} 小時\n"
        f"\n"
        f"＝收入＝\n"
        f"武士：${w_income:,}（原始 ${w_gross:,} × 60%）\n"
        f"柔力：${r_income:,}\n"
        f"預收款：（另計）"
    )
    if prepay_names:
        # 列出被歸為預收款的人（含堂數），方便核對有沒有新學員/打錯字被漏算
        detail = "、".join(f"{n}×{c}" for n, c in sorted(prepay_names.items()))
        msg += f"\n預收名單：{detail}"
    if warnings:
        msg = "⚠️ 複查警告（請人工確認後再採用）\n" + "\n".join(f"・{w}" for w in warnings) + "\n\n" + msg
    print(msg)

    resp = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={"Authorization": f"Bearer {os.environ['LINE_CHANNEL_ACCESS_TOKEN']}",
                 "Content-Type": "application/json"},
        json={"to": os.environ["LINE_USER_ID"],
              "messages": [{"type": "text", "text": msg}]},
    )
    print(f"LINE：{resp.status_code}")

if __name__ == "__main__":
    main()
