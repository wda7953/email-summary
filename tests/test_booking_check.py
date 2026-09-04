"""每週排課核對純邏輯測試。"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import booking_check as b  # noqa: E402


def test_active_students_filters_status_and_skip():
    raw = [
        ["id", "name", "phone", "venue", "level", "status", "created_at", "notes", "partner_id"],
        ["1", "陳麗卿", "", "武士", "", "active", "2026-06-15"],
        ["2", "靜", "", "柔力", "Pilates", "active", "2026-06-15"],
        ["3", "仁哥", "", "柔力", "", "active", "2026-06-16"],          # 排除
        ["4", "六哥", "", "柔力", "", "active", "2026-06-24"],          # 排除
        ["5", "蔡如斐", "", "柔力", "", "active", "2026-06-15"],        # 排除
        ["6", "某離職", "", "武士", "", "inactive", "2026-06-15"],      # 非在線
    ]
    out = b.active_students(raw)
    names = [s["name"] for s in out]
    assert names == ["陳麗卿", "靜"]
    assert out[0]["venue"] == "武士" and out[1]["venue"] == "柔力"


def test_extract_name_wushi():
    assert b.extract_name("陳麗卿 1200", "wushi") == "陳麗卿"
    assert b.extract_name("小叔叔 收1300", "wushi") == "小叔叔"
    assert b.extract_name("打掃", "wushi") == ""
    assert b.extract_name("x 潘逸霖", "wushi") == ""      # 取消的課不算有排
    assert b.extract_name("", "wushi") == ""


def test_extract_name_roulie():
    assert b.extract_name("小丘（柔力）900", "roulie") == "小丘"
    assert b.extract_name("Jess&Abby", "roulie") == "Jess&Abby"
    assert b.extract_name("olan 柔力", "roulie") == ""    # olan 個人時段不是學員
