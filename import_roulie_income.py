"""柔力現金收入／預收款自動匯入記帳 App。

讀學員 App Payments（venue=柔力）→ 依 period_sessions 分類
（單次==1→現金收入、套餐>1→預收款），用收款認列(total_amount)
寫進記帳 App 的 income 工作表。

冪等：client_id = "stuapp_<payment id>"，重跑不重複 → 補歷史＋每月自動皆安全。
武士付款不匯（武士薪水是另計的整筆受僱薪水，概念不同）。
日期直接沿用 Payments 表上的台灣日期字串，不做時區轉換（避開 UTC+1 坑）。

排程：每月 1 號匯「台灣昨天所屬的月」＝上月；MONTH_OVERRIDE=YYYY-MM 可補特定月。
規則詳見 auto-memory project-expense-app / project-roulie-hours-from-app。
"""
import os
from datetime import datetime, timedelta

import pytz
import requests

from app_sheet import fetch_all, id2name_from
from app_income import parse_rows, rows_for_month

TZ = pytz.timezone("Asia/Taipei")

# 記帳 App 後端（token 與前端 js/api.js 相同，屬「自己資料、公開低風險」防護）
EXPENSE_API = "https://script.google.com/macros/s/AKfycbzDgpGZGLa81qEkhjZmpGhJaUcQvZ3SuD3tvNjMJi5WRMFQdce0rFGny-hbmW5dKjP1/exec"
EXPENSE_TOKEN = "exp7k2m9qf4wx8vn3"


def target_month():
    """MONTH_OVERRIDE 優先；否則「台灣昨天所屬的月」＝上月（整個 1 號都成立、不怕延遲）。"""
    ov = os.environ.get("MONTH_OVERRIDE", "").strip()
    if ov:
        return int(ov[:4]), int(ov[5:7])
    yday = datetime.now(TZ) - timedelta(days=1)
    return yday.year, yday.month


def payment_to_income(p, id2name):
    """一筆柔力 Payment dict → 記帳 income 記錄 dict（純函式，零 I/O）。

    金額<=0 或無 id 回傳 None（不匯）。
    """
    pid = str(p.get("id", "")).strip()
    amt = p.get("total_amount", 0)
    if not pid or not amt or amt <= 0:
        return None
    is_single = p.get("period_sessions") == 1
    itype = "現金收入" if is_single else "預收款"
    name = id2name.get(p.get("student_id", ""), "?" + str(p.get("student_id", ""))[:8])
    pkg = str(p.get("package_name", "")).strip()
    desc = name if is_single else (f"{name} {pkg}".strip() if pkg else name)
    return {
        "sheet": "income",
        "date": str(p.get("date", "")),   # 台灣日期字串，原樣沿用
        "description": desc,
        "amount": amt,
        "type": itype,
        "client_id": f"stuapp_{pid}",
    }


def add_income(record):
    """POST addRecord 到記帳 App。回應可能是 GAS 中間頁，狀態以讀回試算表為準。"""
    r = requests.post(
        f"{EXPENSE_API}?action=addRecord&token={EXPENSE_TOKEN}",
        json=record, timeout=30,
    )
    return r.status_code


def main():
    year, month = target_month()
    print(f"匯入 {year}-{month:02d} 柔力收入...")

    students_raw, _classes_raw, payments_raw = fetch_all()
    id2name = id2name_from(students_raw)
    rows = rows_for_month(parse_rows(payments_raw), "柔力", year, month)

    cash_n = cash_sum = pre_n = pre_sum = 0
    for p in rows:
        rec = payment_to_income(p, id2name)
        if rec is None:
            continue
        code = add_income(rec)
        print(f"  [{code}] {rec['type']} {rec['description']} ${rec['amount']:,} ({rec['date']})")
        if rec["type"] == "現金收入":
            cash_n += 1
            cash_sum += rec["amount"]
        else:
            pre_n += 1
            pre_sum += rec["amount"]

    summary = (
        f"✅ 記帳已同步 {year}-{month:02d} 柔力收款\n"
        f"現金收入 {cash_n} 筆 ${cash_sum:,}\n"
        f"預收款 {pre_n} 筆 ${pre_sum:,}"
    )
    print(summary)

    # 發 LINE 告知結果（有設 token 才發）——自動寫入財務資料，給你一個對帳/防呆的回報
    tok = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    uid = os.environ.get("LINE_USER_ID")
    if tok and uid:
        try:
            requests.post(
                "https://api.line.me/v2/bot/message/push",
                headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
                json={"to": uid, "messages": [{"type": "text", "text": summary}]},
                timeout=10,
            )
        except Exception as e:  # noqa: BLE001
            print("LINE push failed:", e)


if __name__ == "__main__":
    main()
