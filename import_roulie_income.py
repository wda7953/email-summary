"""柔力現金收入／預收款自動匯入記帳 App。

柔力進帳都是現金收款，**當月認列**（記在收款日所屬月）→ 需即時匯入，故每天跑，
每次匯「當月＋上月」（當月＝即時認列；上月＝補月初才登記的漏記）。
武士抽成是隔月結算的整筆受僱薪水、另計，**不從 Payments 匯**。

分類：讀學員 App Payments(venue=柔力) → period_sessions==1→現金收入、>1→預收款；
金額用 total_amount(收款認列)；日期沿用 Payments 表台灣日期字串（不轉時區，避 UTC+1 坑）。
冪等：client_id="stuapp_<payment id>"；寫入前先讀記帳 income 已有的 client_id，只補新的
（避免每天重打數十次 API）。有新進帳才發 LINE。

MONTH_OVERRIDE=YYYY-MM 可只補特定月。
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


# 匯入器起始月：只從 2026-09 起，永不碰 9 月以前（5–8 月是手動舊資料，client_id 不同會重複）
IMPORT_FROM = (2026, 9)


def _ge_start(year, month):
    return (year, month) >= IMPORT_FROM


def target_months():
    """MONTH_OVERRIDE 優先（單月）；否則回 [上月, 當月]，並濾掉 IMPORT_FROM 以前的月。

    當月＝柔力當月認列即時匯入；上月＝補月初才在學員 App 登記的上月漏記。
    起始月下限保護 9 月前的手動舊資料：9 月時上月(8月)會被擋、只匯 9 月。
    """
    ov = os.environ.get("MONTH_OVERRIDE", "").strip()
    if ov:
        return [(int(ov[:4]), int(ov[5:7]))]  # 手動補匯不套下限（要補就補）
    now = datetime.now(TZ)
    prev_last = now.replace(day=1) - timedelta(days=1)
    cand = [(prev_last.year, prev_last.month), (now.year, now.month)]
    return [m for m in cand if _ge_start(*m)]


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


def existing_client_ids(year, month):
    """讀記帳 income 該月已有的 client_id 集合（去重前置，避免重打 API）。"""
    try:
        r = requests.get(
            EXPENSE_API,
            params={"action": "getRecords", "sheet": "income",
                    "year": year, "month": month, "token": EXPENSE_TOKEN},
            timeout=30,
        )
        data = r.json()
        return {str(rec.get("client_id", "")) for rec in data.get("records", []) if rec.get("client_id")}
    except Exception as e:  # noqa: BLE001 — 讀不到就當空集合（頂多多打幾次 API，冪等仍安全）
        print(f"  ⚠️ 讀 {year}-{month:02d} 既有 client_id 失敗，改全量嘗試：{e}")
        return set()


def add_income(record):
    """POST addRecord 到記帳 App。回應可能是 GAS 中間頁，狀態以讀回試算表為準。"""
    r = requests.post(
        f"{EXPENSE_API}?action=addRecord&token={EXPENSE_TOKEN}",
        json=record, timeout=30,
    )
    return r.status_code


def import_month(year, month):
    """匯入單月柔力收款，回傳新增彙總 dict（只算真正新寫入的）。"""
    students_raw, _classes_raw, payments_raw = fetch_all()
    id2name = id2name_from(students_raw)
    rows = rows_for_month(parse_rows(payments_raw), "柔力", year, month)
    done = existing_client_ids(year, month)

    r = {"cash_n": 0, "cash_sum": 0, "pre_n": 0, "pre_sum": 0}
    for p in rows:
        rec = payment_to_income(p, id2name)
        if rec is None or rec["client_id"] in done:
            continue
        code = add_income(rec)
        print(f"  [{code}] {year}-{month:02d} {rec['type']} {rec['description']} ${rec['amount']:,} ({rec['date']})")
        if rec["type"] == "現金收入":
            r["cash_n"] += 1
            r["cash_sum"] += rec["amount"]
        else:
            r["pre_n"] += 1
            r["pre_sum"] += rec["amount"]
    return r


def main():
    months = target_months()
    total = {"cash_n": 0, "cash_sum": 0, "pre_n": 0, "pre_sum": 0}
    for year, month in months:
        print(f"檢查 {year}-{month:02d} 柔力收款...")
        r = import_month(year, month)
        for k in total:
            total[k] += r[k]

    new_n = total["cash_n"] + total["pre_n"]
    if new_n == 0:
        print("無新進帳，不發 LINE。")
        return

    summary = (
        f"✅ 記帳新增柔力收款 {new_n} 筆\n"
        f"現金收入 {total['cash_n']} 筆 ${total['cash_sum']:,}\n"
        f"預收款 {total['pre_n']} 筆 ${total['pre_sum']:,}"
    )
    print(summary)

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
