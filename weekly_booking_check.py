"""每週排課核對 orchestrator：讀名單＋行事曆 → 比對 → 發 LINE。

視窗＝執行當天起 8 天（含當天）；可用 CHECK_START=YYYY-MM-DD 覆蓋（測試/校準）。
"""
import json
import os
from datetime import datetime, timedelta

import pytz
import requests

from app_sheet import fetch_students
from booking_calendars import fetch_calendar_events
from booking_check import (
    SKIP_STUDENTS, active_students, extract_name, match, self_check, build_message,
)

TZ = pytz.timezone("Asia/Taipei")


def window():
    ov = os.environ.get("CHECK_START", "").strip()
    if ov:
        start = TZ.localize(datetime(int(ov[:4]), int(ov[5:7]), int(ov[8:10])))
    else:
        now = datetime.now(TZ)
        start = TZ.localize(datetime(now.year, now.month, now.day))
    return start, start + timedelta(days=8)   # end 不含當日 → 涵蓋含當天共 8 天


def load_aliases():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "booking_aliases.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def load_skip():
    """讀不用每週排的學員清單（booking_skip_students.json），資料化維護，不用改 code。
    檔案不存在時退回 booking_check.SKIP_STUDENTS 當保底。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "booking_skip_students.json")
    try:
        with open(path, encoding="utf-8") as f:
            return set(json.load(f))
    except FileNotFoundError:
        return SKIP_STUDENTS


def load_pairs():
    """讀名字共用組清單（booking_pairs.json），給 App 沒登記 partner_id 的組合用
    （如 小叔叔↔媽媽 擇一有排即可）。檔案不存在時回空 list（不影響其他判斷）。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "booking_pairs.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def send_line(msg):
    resp = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={"Authorization": f"Bearer {os.environ['LINE_CHANNEL_ACCESS_TOKEN']}",
                 "Content-Type": "application/json"},
        json={"to": os.environ["LINE_USER_ID"], "messages": [{"type": "text", "text": msg}]},
        timeout=10,
    )
    print("LINE push:", resp.status_code)


def main():
    start, end = window()
    print(f"核對視窗：{start.date()} ~ {(end - timedelta(days=1)).date()}")

    try:
        active = active_students(fetch_students(), skip=load_skip())
        raw_events = fetch_calendar_events(start, end)
    except Exception as ex:
        # 讀名單／行事曆失敗（憑證失效、行事曆改名…）也要發得出 LINE，
        # 不然就是「沒收到通知」而不是「收到失敗通知」——後者才有用。
        send_line(f"⚠️ 排課核對執行失敗，請查 GitHub Actions log：\n{ex}")
        raise

    calendar_names = [nm for (summary, kind) in raw_events
                      if (nm := extract_name(summary, kind))]

    # === TEMP DEBUG（查媽媽運動為何沒被讀到，看完即移除）===
    print("DEBUG_RAW_EVENTS:", [f"{k}|{s}" for (s, k) in raw_events])
    print("DEBUG_NAMES:", sorted(set(calendar_names)))
    # === END TEMP DEBUG ===

    warnings = self_check(len(active), len(raw_events), len(calendar_names))
    result = match(active, calendar_names, load_aliases(), pairs=load_pairs())
    msg = build_message(start, result, warnings)
    print(msg)
    send_line(msg)


if __name__ == "__main__":
    main()
