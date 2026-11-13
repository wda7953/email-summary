"""上週課表對帳 orchestrator：讀行事曆＋App Classes → 比對 → 發 LINE。

排程：每週一（cron-job.org 觸發 workflow_dispatch）。報「上一個完整週一～週日」。
補跑／校準：WEEK_START=YYYY-MM-DD（該週的週一）指定要對帳的那一週。
預覽：DRY_RUN=1 只在 log 印訊息、不推 LINE（olan 偏好：正式發前先看預覽）。

規則詳見 reconcile_check 註解；與排課核對共用 booking_aliases.json。
"""
import json
import os
from datetime import datetime, time, timedelta

import pytz
import requests

from app_sheet import fetch_all, id2name_from
from app_income import parse_rows
from booking_calendars import fetch_calendar_events_dated
from reconcile_check import (
    last_week_window, rows_in_window, app_class_keys, resolve_calendar,
    find_missing, self_check, build_message,
)

TZ = pytz.timezone("Asia/Taipei")
HERE = os.path.dirname(os.path.abspath(__file__))


def window():
    """回 (start_date, end_date)。WEEK_START=YYYY-MM-DD 指定該週週一；否則上一完整週。"""
    ov = os.environ.get("WEEK_START", "").strip()
    if ov:
        start = datetime(int(ov[:4]), int(ov[5:7]), int(ov[8:10])).date()
        return start, start + timedelta(days=6)
    return last_week_window(datetime.now(TZ))


def load_json(name, default):
    try:
        with open(os.path.join(HERE, name), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


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
    print(f"對帳視窗：{start} ~ {end}")

    try:
        students_raw, classes_raw, _payments = fetch_all()
        id2name = id2name_from(students_raw)
        classes = parse_rows(classes_raw)
        aliases = load_json("booking_aliases.json", {})
        skip_names = set(load_json("reconcile_skip_students.json", []))

        cal_start = TZ.localize(datetime.combine(start, time(0, 0)))
        cal_end = TZ.localize(datetime.combine(end + timedelta(days=1), time(0, 0)))
        events_dated = fetch_calendar_events_dated(cal_start, cal_end)
    except Exception as ex:
        # 讀名單／行事曆／設定檔失敗都要發得出 LINE：收到「失敗通知」才知道這週沒對到帳。
        send_line(f"⚠️ 課表對帳執行失敗，請查 GitHub Actions log：\n{ex}")
        raise

    win_rows = rows_in_window(classes, start, end)
    app_keys, unresolved_app = app_class_keys(win_rows, id2name)
    cal_keys, display, unmatched, cal_counted = resolve_calendar(
        events_dated, id2name, aliases, skip_names=skip_names)

    warnings = self_check(cal_counted, len(win_rows))
    missing = find_missing(cal_keys, app_keys)
    msg = build_message(start, end, missing, unmatched, display, warnings, unresolved_app)
    print(msg)

    if os.environ.get("DRY_RUN", "").strip():
        print("\n[DRY_RUN] 已跳過 LINE 推送（預覽模式）")
        return
    send_line(msg)


if __name__ == "__main__":
    main()
