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
    parse_rows, rows_for_month, summarize_roulie, summarize_wushi_executed,
    count_sessions, count_sessions_by_price, build_message,
)

TZ = pytz.timezone("Asia/Taipei")

# 武士收入排除名單（只套在「收入金額」，堂數顯示不排除）。olan 2026-11-06 拍板排除
# 黃誼淇、為舜的媽 林阿姨兩人。注意：「媽媽」是另一個人，不在此列（olan 2026-11-06 確認）。
WUSHI_INCOME_SKIP = frozenset({"黃誼淇", "為舜的媽 林阿姨"})

# 武士免費課學員（如 x媽媽運動）：有付出工時→算武士堂數，但收入 $0，不當漏記價提醒補價。
WUSHI_FREE_STUDENTS = frozenset({"媽媽"})

# 業績回報學員（堂費由老闆直接按堂數算進 olan 薪資、App 不會有繳費紀錄）：
# 查無 App 繳費單價時改用此指定單價計入（仍當一般武士 ×60%）。olan 2026-11-06 確認只有這兩位。
# key＝student_id（穩定、不怕改名）；value＝每堂單價。
WUSHI_PERF_PRICES = {
    "c410af57-723a-4381-82f1-0b463128b276": 1000,  # 吳彩足
    "32671753-17a9-4cbb-a78e-a20883cdaa56": 1000,  # 邱玉青
}


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
    # 武士改「實際執行」認列：當月實際上課堂數 × 該生單價(App 成交價) ×60%（olan 2026-11-06）
    wushi = summarize_wushi_executed(classes, payments, year, month, id2name,
                                     WUSHI_INCOME_SKIP, WUSHI_FREE_STUDENTS,
                                     perf_prices=WUSHI_PERF_PRICES)
    # 堂數顯示不排除任何人（olan 2026-09-01 決定）
    r_sessions = count_sessions(classes, "柔力", year, month, id2name)
    w_sessions = count_sessions(classes, "武士", year, month, id2name)
    # 柔力實際執行堂數依單價級距分段（1000 以下／以上）
    r_session_split = count_sessions_by_price(classes, payments, "柔力", year, month)
    # 自檢：本月收費有幾筆對不到學員名（可能是打錯字/新學員未建檔）
    unresolved = sum(1 for r in r_rows + w_rows if r["student_id"] not in id2name)

    msg, _ = build_message(year, month, roulie, wushi, r_sessions, w_sessions,
                           unresolved, r_session_split=r_session_split)
    msg += "\n\n資料來源：學員 App 試算表（Payments／Classes）"
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
