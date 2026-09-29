"""payment_to_income 純函式測試：單次/套餐分類、去重鍵、防呆。"""
import os
import sys
from datetime import datetime as _real_datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import import_roulie_income as mod  # noqa: E402
from import_roulie_income import payment_to_income, _ge_start, target_months  # noqa: E402

ID2NAME = {"s1": "仁哥", "s2": "麗娟姐"}


def test_single_session_is_cash_income():
    p = {"id": "p1", "student_id": "s1", "venue": "柔力", "date": "2026-09-05",
         "package_name": "單次", "total_amount": 700, "period_sessions": 1}
    rec = payment_to_income(p, ID2NAME)
    assert rec["type"] == "現金收入"
    assert rec["amount"] == 700
    assert rec["description"] == "仁哥"          # 單次只放姓名
    assert rec["client_id"] == "stuapp_p1"       # 冪等鍵
    assert rec["sheet"] == "income"
    assert rec["date"] == "2026-09-05"           # 日期原樣沿用，不轉時區


def test_package_is_prepaid_with_package_name():
    p = {"id": "p2", "student_id": "s2", "venue": "柔力", "date": "2026-09-06",
         "package_name": "10堂套餐", "total_amount": 9600, "period_sessions": 10}
    rec = payment_to_income(p, ID2NAME)
    assert rec["type"] == "預收款"
    assert rec["amount"] == 9600
    assert rec["description"] == "麗娟姐 10堂套餐"  # 套餐附套餐名


def test_zero_amount_skipped():
    p = {"id": "p3", "student_id": "s1", "date": "2026-09-01",
         "total_amount": 0, "period_sessions": 1}
    assert payment_to_income(p, ID2NAME) is None


def test_missing_id_skipped():
    p = {"id": "", "student_id": "s1", "date": "2026-09-01",
         "total_amount": 700, "period_sessions": 1}
    assert payment_to_income(p, ID2NAME) is None


def test_unknown_student_falls_back_to_id_prefix():
    p = {"id": "p4", "student_id": "sX999", "date": "2026-09-01",
         "package_name": "", "total_amount": 600, "period_sessions": 1}
    rec = payment_to_income(p, ID2NAME)
    assert rec["description"].startswith("?")


def test_import_floor_blocks_before_2026_09():
    assert _ge_start(2026, 9) is True
    assert _ge_start(2026, 10) is True
    assert _ge_start(2026, 8) is False   # 8 月及以前的手動舊資料不碰
    assert _ge_start(2025, 12) is False


def test_override_bypasses_floor(monkeypatch):
    # 手動補匯不套下限
    monkeypatch.setenv("MONTH_OVERRIDE", "2026-07")
    assert target_months() == [(2026, 7)]


def test_september_run_excludes_august(monkeypatch):
    # 模擬 9 月跑：候選[8月,9月]，8月被下限擋掉，只留 9 月
    monkeypatch.delenv("MONTH_OVERRIDE", raising=False)

    fixed = mod.TZ.localize(_real_datetime(2026, 9, 15, 6, 0))
    monkeypatch.setattr(mod, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: fixed)}))
    assert target_months() == [(2026, 9)]


def test_october_run_includes_september(monkeypatch):
    monkeypatch.delenv("MONTH_OVERRIDE", raising=False)

    fixed = mod.TZ.localize(_real_datetime(2026, 10, 3, 6, 0))
    monkeypatch.setattr(mod, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: fixed)}))
    assert target_months() == [(2026, 9), (2026, 10)]
