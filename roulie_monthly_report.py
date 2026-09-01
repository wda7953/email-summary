"""收入月報（柔力＋武士）：改讀學員 App Google Sheet，收款認列。

排程：每月 1 號 00:00 台灣時間（cron-job.org 觸發），報上月。
可用 MONTH_OVERRIDE=YYYY-MM 指定月份補發。
規則詳見 auto-memory project-roulie-hours-from-app / project-roulie-rules。
"""
import os
from datetime import datetime, timedelta

import pytz
import requests

from app_sheet import fetch_all, id2name_from
from app_income import (
    parse_rows, rows_for_month, summarize_roulie, summarize_wushi,
    count_sessions, build_message,
)

TZ = pytz.timezone("Asia/Taipei")


def target_month():
    """MONTH_OVERRIDE 優先；否則報「台灣時間昨天所屬的月」＝上月（整個 1 號都成立、不怕延遲）。"""
    ov = os.environ.get("MONTH_OVERRIDE", "").strip()
    if ov:
        return int(ov[:4]), int(ov[5:7])
    yday = datetime.now(TZ) - timedelta(days=1)
    return yday.year, yday.month


def main():
    year, month = target_month()
    print(f"計算 {year}/{month}...")

    students_raw, classes_raw, payments_raw = fetch_all()
    id2name = id2name_from(students_raw)
    payments = parse_rows(payments_raw)
    classes = parse_rows(classes_raw)

    r_rows = rows_for_month(payments, "柔力", year, month)
    w_rows = rows_for_month(payments, "武士", year, month)
    roulie = summarize_roulie(r_rows, id2name)
    wushi = summarize_wushi(w_rows, id2name)
    # 堂數顯示不排除任何人（olan 2026-09-01 決定）
    r_sessions = count_sessions(classes, "柔力", year, month, id2name)
    w_sessions = count_sessions(classes, "武士", year, month, id2name)
    # 自檢：本月收費有幾筆對不到學員名（可能是打錯字/新學員未建檔）
    unresolved = sum(1 for r in r_rows + w_rows if r["student_id"] not in id2name)

    msg, _ = build_message(year, month, roulie, wushi, r_sessions, w_sessions, unresolved)
    print(msg)

    resp = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={
            "Authorization": f"Bearer {os.environ['LINE_CHANNEL_ACCESS_TOKEN']}",
            "Content-Type": "application/json",
        },
        json={
            "to": os.environ["LINE_USER_ID"],
            "messages": [{"type": "text", "text": msg}],
        },
        timeout=10,
    )
    print("LINE push:", resp.status_code)


if __name__ == "__main__":
    main()
