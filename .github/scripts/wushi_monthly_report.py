import re, sys, os
from collections import Counter
from datetime import date, timedelta, datetime
import caldav, pytz, requests

TZ = pytz.timezone("Asia/Taipei")

SKIP_RE = re.compile(r"^(打掃|[xX]|.*另計|黃誼淇|鳳甲國中)")
TIERS   = [1600, 1300, 1200, 1100, 1000, 990, 900, 500]

# 學員 App 對帳時，要用「與行事曆報告相同的排除」比對武士堂數。
# 行事曆 SKIP 的人對應到 App 的學員姓名：黃誼淇、另計(為舜的媽 林阿姨)、x媽媽運動(媽媽)。
APP_RECONCILE_SKIP = frozenset({"黃誼淇", "為舜的媽 林阿姨", "媽媽"})

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

def _parse_raw(ev):
    """把一筆 caldav 原始事件轉成 (日期, parse_event結果)；解析失敗印 stderr 後回 (None, None)。"""
    try:
        comp = ev.icalendar_component
        dt   = comp.get("DTSTART").dt
        d    = dt.date() if hasattr(dt, "date") else dt
        return d, parse_event(str(comp.get("SUMMARY", "")), d)
    except Exception as ex:
        # 不再靜默吞掉：印到 stderr(GitHub Actions log 看得到)，避免抓取階段漏算又無跡可循
        try: summary = str(ev.icalendar_component.get("SUMMARY", ""))
        except Exception: summary = "?"
        print(f"略過解析失敗事件：{summary!r} — {ex}", file=sys.stderr)
        return None, None

def collect_events(search_fn, year, month):
    """逐週查詢再合併，避開 iCloud「月寬一次 expand」會靜默漏掉被改過的週期課的毛病。

    背景：某堂週期課只要被逐堂改過時間/取消(recurrence override)，iCloud 對整月一次展開
    就會連整條系列一起漏掉(2026-10 孫淑英事件)；但縮小到單週查就正常。故改逐週各打一次。

    search_fn(start, end)：回傳該區間的原始事件清單(已 expand=True)。
    每筆事件只歸入 start<=日期<=end 的那一週 → 天然去重、不漏算、不重複。
    """
    events = []
    for ws, we in week_ranges(year, month):
        start = datetime(ws.year, ws.month, ws.day, 0, 0, tzinfo=TZ)
        end   = datetime(we.year, we.month, we.day, 0, 0, tzinfo=TZ) + timedelta(days=1)
        for ev in search_fn(start, end):
            d, p = _parse_raw(ev)
            if p and ws <= d <= we:  # 只收屬於本週窗口的，避免邊界事件被兩週各算一次
                events.append(p)
    return events

def fetch_events(year, month):
    client  = caldav.DAVClient(url="https://caldav.icloud.com",
                               username=os.environ["ICLOUD_USERNAME"],
                               password=os.environ["ICLOUD_PASSWORD"])
    wushi   = next((c for c in client.principal().calendars() if "武士" in str(c.get_display_name())), None)
    if not wushi: raise ValueError("找不到武士行事曆")
    # 逐週查：expand=True 展開週期課，但範圍縮到單週以避開 iCloud 月寬漏抓
    search_fn = lambda start, end: wushi.search(start=start, end=end, event=True, expand=True)
    return collect_events(search_fn, year, month)

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

def reconcile_diffs(weeks, cal_counts, app_counts, month):
    """純函式：逐週比對行事曆 vs App 武士堂數，回傳不符週的描述清單（相符回空）。"""
    diffs = []
    for ws, we in weeks:
        c = cal_counts.get((ws, we), 0)
        a = app_counts.get((ws, we), 0)
        if c != a:
            diffs.append(f"{month}/{ws.day}-{we.day} 行事曆{c}/App{a}")
    return diffs

def reconcile_with_app(year, month, weeks, cal_counts):
    """跟學員 App 對帳（事後安全網）：逐週 App 武士堂數 vs 行事曆，回傳一行提醒字串。

    best-effort：任何錯誤（App 連不上、缺 secret、import 失敗）都吞掉並回提示字串，
    **絕不可擋住主報告**。只放進 olan 的核對版，不進轉發武士的回報版。
    """
    try:
        import os.path
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
        import app_sheet, app_income
        students_raw, classes_raw, _ = app_sheet.fetch_all()
        id2name = app_sheet.id2name_from(students_raw)
        rows = app_income.parse_rows(classes_raw)
        app_counts = app_income.sessions_by_week(rows, "武士", year, month, id2name, weeks, APP_RECONCILE_SKIP)
        diffs = reconcile_diffs(weeks, cal_counts, app_counts, month)
        if not diffs:
            return "✅ 學員App對帳：各週武士堂數相符"
        return "⚠️ 學員App對帳不符(可能漏記，請查)：" + "；".join(diffs)
    except Exception as ex:
        return f"（學員App對帳略過：{ex}）"

def main(year=None, month=None):
    today = date.today()
    year  = year or today.year
    month = month or today.month
    events = fetch_events(year, month)
    # 逐週行事曆堂數，供對帳
    weeks = week_ranges(year, month)
    cal_counts = {(ws, we): len([e for e in events if ws <= e["date"] <= we]) for ws, we in weeks}
    # 核對版加一行學員 App 對帳（只給 olan；回報版不帶）
    msg_check = build_month_message(year, month, events, show_names=True)
    recon = reconcile_with_app(year, month, weeks, cal_counts)
    if recon:
        msg_check += "\n\n" + recon
    send_line(msg_check)
    print("已傳：含名字核對版（含學員App對帳）")
    send_line(build_month_message(year, month, events, show_names=False))
    print("已傳：無名字回報版")
    print("完成！")

if __name__ == "__main__":
    a = sys.argv[1:]
    main(int(a[0]), int(a[1])) if len(a) >= 2 else main()
