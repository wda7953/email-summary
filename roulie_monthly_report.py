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

# 固定按次收費客戶
PER_SESSION = {
    "品漩": 600,
    "蔡清蓉": 1000, "蔡青蓉": 1000,
    "鳳琴姊": 700, "鳳琴姐": 700,
    "仁哥": 700,
}
HOURLY_RATE = 700  # Olan 時段

def gcal_creds():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GCAL_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/calendar.readonly"],
    )
    creds.refresh(Request())
    return creds

def month_range(year, month):
    next_m = date(year + (month // 12), month % 12 + 1, 1)
    return (
        datetime(year, month, 1, 0, 0, tzinfo=TZ),
        datetime(next_m.year, next_m.month, 1, 0, 0, tzinfo=TZ),
    )

def fetch_icloud(year, month):
    client = caldav.DAVClient(url="https://caldav.icloud.com",
                               username=ICLOUD_USER, password=ICLOUD_PASS)
    cal = next((c for c in client.principal().calendars() if "工作室" in str(c.name)), None)
    if not cal:
        raise ValueError("找不到工作室行事曆")
    start, end = month_range(year, month)
    events = []
    for ev in cal.date_search(start=start, end=end):
        try:
            comp = ev.icalendar_component
            summary = str(comp.get("SUMMARY", ""))
            if "柔力" not in summary:
                continue
            dt = comp.get("DTSTART").dt
            dt_end = comp.get("DTEND").dt if comp.get("DTEND") else None
            ev_date = dt.date() if hasattr(dt, "date") else dt
            hours = 0
            if dt_end and hasattr(dt, "hour"):
                hours = (dt_end - dt).total_seconds() / 3600
            name = re.sub(r"[（(]柔力[)）].*", "", summary).strip()
            events.append({"date": ev_date, "name": name, "hours": hours})
        except Exception as e:
            print(f"略過 iCloud 事件：{e}")
    return events

def fetch_gcal(year, month, creds):
    svc = build("calendar", "v3", credentials=creds)
    start, end = month_range(year, month)
    result = svc.events().list(
        calendarId=GCAL_ID,
        timeMin=start.isoformat(), timeMax=end.isoformat(),
        singleEvents=True, orderBy="startTime",
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
        ev_date = dt_s.date()
        name = "Olan" if is_olan else re.sub(r"[（(]柔力[)）].*", "", summary).strip()
        events.append({"date": ev_date, "name": name, "hours": hours})
    return events

def build_report(events, year, month):
    session_count = 0   # 客戶堂數（含預收款）
    prepay_count  = 0   # 預收款客戶堂數
    olan_hours    = 0.0
    income        = 0
    detail        = {}  # name -> amt

    for ev in events:
        name  = ev["name"]
        hours = ev["hours"]

        if name == "Olan":
            olan_hours += hours
            amt = round(hours * HOURLY_RATE)
            income += amt
            detail["Olan"] = detail.get("Olan", 0) + amt
        elif name in PER_SESSION:
            session_count += 1
            amt = PER_SESSION[name]
            income += amt
            detail[name] = detail.get(name, 0) + amt
        else:
            session_count += 1
            prepay_count  += 1

    lines = [
        f"【{year}年{month}月 柔力月報】",
        f"",
        f"＝工時＝",
        f"客戶堂數：{session_count} 堂（含預收款 {prepay_count} 堂）",
        f"Olan 時段：{olan_hours:.1f} 小時",
        f"",
        f"＝收入（行事曆可計算）＝",
    ]
    for name, amt in detail.items():
        if name == "Olan":
            lines.append(f"Olan {olan_hours:.1f}hr：${amt:,}")
        else:
            cnt = amt // PER_SESSION[name]
            lines.append(f"{name} ×{cnt}：${amt:,}")
    lines.append(f"小計：${income:,}")
    lines.append(f"預收款客戶 {prepay_count} 堂：另計")
    return "\n".join(lines)

def send_line(msg):
    resp = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={"Authorization": f"Bearer {os.environ['LINE_CHANNEL_ACCESS_TOKEN']}",
                 "Content-Type": "application/json"},
        json={"to": os.environ["LINE_USER_ID"],
              "messages": [{"type": "text", "text": msg}]},
    )
    print(f"LINE：{resp.status_code}")

def main():
    today = date.today()
    last = today.replace(day=1) - timedelta(days=1)
    year, month = last.year, last.month

    print(f"抓取 {year}/{month} 柔力資料...")
    icloud_evs = fetch_icloud(year, month)
    print(f"iCloud 事件：{len(icloud_evs)}")
    creds = gcal_creds()
    gcal_evs = fetch_gcal(year, month, creds)
    print(f"Google 事件：{len(gcal_evs)}")

    all_events = icloud_evs + gcal_evs
    report = build_report(all_events, year, month)
    print(report)
    send_line(report)

if __name__ == "__main__":
    main()
