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
    sessions, gross = 0, 0
    for ev in cal.search(start=start, end=end, event=True, expand=True):
        try:
            comp = ev.icalendar_component
            summary = str(comp.get("SUMMARY", ""))
            if WUSHI_SKIP.match(summary):
                continue
            nums = [int(n) for n in re.findall(r"\d+", summary) if 500 <= int(n) <= 1600]
            price = nums[-1] if nums else 900
            sessions += 1
            gross += price
        except:
            pass
    return sessions, gross

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
        s = item["start"].get("dateTime", item["start"].get("date"))
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

    w_sessions, w_gross = fetch_wushi(year, month)
    w_income = round(w_gross * 0.6)

    r_events = fetch_roulie_icloud(year, month) + fetch_roulie_gcal(year, month)
    r_sessions, r_prepay, r_olan_hrs, r_income = 0, 0, 0.0, 0
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

    msg = (
        f"【{year}年{month}月 收入月報】\n"
        f"\n"
        f"＝工時＝\n"
        f"武士：{w_sessions} 堂\n"
        f"柔力：{r_sessions} 堂 + {r_olan_hrs:.1f} 小時 Olan\n"
        f"\n"
        f"＝收入＝\n"
        f"武士：${w_income:,}（原始 ${w_gross:,} × 60%）\n"
        f"柔力：${r_income:,}\n"
        f"預收款：（另計）"
    )
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
