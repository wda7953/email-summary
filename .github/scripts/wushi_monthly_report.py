import re, sys, os
from collections import Counter
from datetime import date, timedelta, datetime
import caldav, pytz, requests

TZ = pytz.timezone("Asia/Taipei")

SKIP_RE = re.compile(r"^(打掃|[xX]|.*另計|黃誼淇|鳳甲國中)")
TIERS   = [1600, 1300, 1200, 1100, 1000, 990, 900, 500]

def send_line(msg):
    requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={"Authorization": f"Bearer {os.environ['LINE_CHANNEL_ACCESS_TOKEN']}", "Content-Type": "application/json"},
        json={"to": os.environ["LINE_USER_ID"], "messages": [{"type": "text", "text": msg}]},
        timeout=10,
    )

def parse_event(summary, ev_date):
    if SKIP_RE.match(summary): return None
    receipt = sum(int(m) for m in re.findall(r"收(\d+)", summary))
    nums    = [int(n) for n in re.findall(r"\d+", summary) if 500 <= int(n) <= 1600]
    price   = nums[-1] if nums else 900
    name    = re.sub(r"\d.*", "", summary).strip()
    return {"date": ev_date, "name": name, "price": price, "receipt_amt": receipt} if name else None

def fetch_events(year, month):
    client  = caldav.DAVClient(url="https://caldav.icloud.com",
                               username=os.environ["ICLOUD_USERNAME"],
                               password=os.environ["ICLOUD_PASSWORD"])
    wushi   = next((c for c in client.principal().calendars() if "武士" in str(c.get_display_name())), None)
    if not wushi: raise ValueError("找不到武士行事曆")
    next_m  = date(year + (month // 12), month % 12 + 1, 1)
    raw     = wushi.search(
        start=datetime(year, month, 1, 0, 0, tzinfo=TZ),
        end=datetime(next_m.year, next_m.month, next_m.day, 0, 0, tzinfo=TZ),
        event=True,
        expand=True,
    )
    events = []
    for ev in raw:
        try:
            comp = ev.icalendar_component
            dt   = comp.get("DTSTART").dt
            d    = dt.date() if hasattr(dt, "date") else dt
            p    = parse_event(str(comp.get("SUMMARY", "")), d)
            if p: events.append(p)
        except Exception as ex:
            # 不再靜默吞掉：印到 stderr(GitHub Actions log 看得到)，避免抓取階段漏算又無跡可循
            try: summary = str(comp.get("SUMMARY", ""))
            except Exception: summary = "?"
            print(f"略過解析失敗事件：{summary!r} — {ex}", file=sys.stderr)
    return events

def week_ranges(year, month):
    last = (date(year + (month // 12), month % 12 + 1, 1) - timedelta(days=1)).day
    weeks, start = [], 1
    while start <= last:
        d   = date(year, month, start)
        end = min(start + (6 - d.weekday()), last)
        weeks.append((date(year, month, start), date(year, month, end)))
        start = end + 1
    return weeks

def format_report(month, ws, we, sessions, receipts, show_names=True):
    """show_names=True：含名字(給 olan 核對)；False：只留數量(轉發武士用)。"""
    renewal_amt   = sum(r["receipt_amt"] for r in receipts)
    renewal_names = [r["name"] for r in receipts]
    # 固定價位先鋪底（即使 0 堂也要顯示）；非標準價位（如活動價、1111）也放進來，最後一起由高到低排
    price_names = {t: [] for t in TIERS}
    for s in sessions:
        price_names.setdefault(s["price"], []).append(s["name"])
    lines = [
        f"{month}/{ws.day}-{month}/{we.day} Olan週業績回報",
        f"當週續約金額：{renewal_amt:,}",
        f"當週總銷售金額：{renewal_amt:,}",
        f"當週總執行堂數：{len(sessions)}",
    ]
    listed = 0  # 已列進名單的堂數，用來自檢
    for p in sorted(price_names, reverse=True):  # 全部價位一起由高到低排（非標準價依數值插到正確位置）
        nc = Counter(price_names[p])
        ns = ("  " + "、".join(f"{n} × {c}" if c > 1 else n for n, c in nc.items())) if (show_names and nc) else ""
        lines.append(f"{p}（{len(price_names[p])}）{ns}")
        listed += len(price_names[p])
    # 發前自檢：總堂數必須等於各價位列名單加總，否則有堂被吞掉，標 ⚠️ 提醒報表不可信
    if listed != len(sessions):
        lines.append(f"⚠️自檢異常：總堂數{len(sessions)}≠名單加總{listed}，有堂未列出，請通知維護")
    lines.append("體驗/成交：")
    if renewal_names and show_names:
        lines.append(f"當週續約人數：{len(renewal_names)}（{'、'.join(renewal_names)}）")
    else:
        lines.append(f"當週續約人數：{len(renewal_names)}")
    return "\n".join(lines)

def build_month_message(year, month, events, show_names):
    """把整月各週彙整成『一則』文字（含或不含名字）。"""
    marker = "🔍 核對版（含名字）" if show_names else "📋 回報版（無名字）"
    parts = [f"【{year}年{month}月武士業績回報】{marker}"]
    for ws, we in week_ranges(year, month):
        s = [e for e in events if ws <= e["date"] <= we]
        r = [e for e in s if e["receipt_amt"] > 0]
        parts.append(format_report(month, ws, we, s, r, show_names))
    return "\n\n".join(parts)

def main(year=None, month=None):
    today = date.today()
    year  = year or today.year
    month = month or today.month
    events = fetch_events(year, month)
    # 兩則：先含名字(核對用)、再無名字(可轉發武士)
    send_line(build_month_message(year, month, events, show_names=True))
    print("已傳：含名字核對版")
    send_line(build_month_message(year, month, events, show_names=False))
    print("已傳：無名字回報版")
    print("完成！")

if __name__ == "__main__":
    a = sys.argv[1:]
    main(int(a[0]), int(a[1])) if len(a) >= 2 else main()
