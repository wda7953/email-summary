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


def _active(*pairs):
    return [{"name": n, "venue": v} for n, v in pairs]


def test_match_exact_alias_and_ignore():
    active = _active(("陳麗卿", "武士"), ("靜", "柔力"), ("小丘", "柔力"))
    cal = ["陳麗卿", "麗卿姊", "阿明"]   # 完全相同 / 需別名 / 未知
    aliases = {"麗卿姊": "陳麗卿", "阿明": ""}   # 空字串＝已知非在線/忽略
    res = b.match(active, cal, aliases)
    missing = [m["name"] for m in res["missing"]]
    assert "陳麗卿" not in missing          # 完全相同命中
    assert "靜" in missing and "小丘" in missing
    assert res["unmatched"] == []           # 阿明被 aliases 標記忽略，不算 unmatched


def test_match_unmatched_gets_suggestion():
    active = _active(("陳麗卿", "武士"))
    res = b.match(active, ["麗卿姊"], {})     # 沒別名 → 進 unmatched 且附建議
    assert res["unmatched"] == ["麗卿姊"]
    assert res["suggestions"]["麗卿姊"] == "陳麗卿"


def test_suggest_alias_needs_two_common_chars():
    assert b.suggest_alias("麗卿姊", ["陳麗卿", "王小明"]) == "陳麗卿"
    assert b.suggest_alias("完全無關", ["陳麗卿"]) is None
