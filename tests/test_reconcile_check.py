"""上週課表對帳純邏輯測試。"""
import os
import sys
from datetime import date, datetime

import pytz

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import reconcile_check as rc  # noqa: E402

TZ = pytz.timezone("Asia/Taipei")


def test_last_week_window_monday_run():
    # 2026-11-16 是週一 → 上週＝11/9(週一)~11/15(週日)
    now = TZ.localize(datetime(2026, 11, 16, 10, 0))
    start, end = rc.last_week_window(now)
    assert start == date(2026, 11, 9)
    assert end == date(2026, 11, 15)


def test_rows_in_window_filters_by_date():
    rows = [
        {"date": "2026-11-05", "venue": "武士", "student_id": "1"},
        {"date": "2026-11-02", "venue": "武士", "student_id": "1"},   # 窗外
        {"date": "壞日期", "venue": "武士", "student_id": "1"},        # 不合法略過
    ]
    out = rc.rows_in_window(rows, date(2026, 11, 3), date(2026, 11, 9))
    assert len(out) == 1 and out[0]["date"] == "2026-11-05"


def test_app_class_keys_counts_and_unresolved():
    id2name = {"1": "陳麗卿", "2": "小丘"}
    rows = [
        {"date": "2026-11-05", "venue": "武士", "student_id": "1"},
        {"date": "2026-11-05", "venue": "武士", "student_id": "1"},   # 同日兩堂
        {"date": "2026-11-06", "venue": "柔力", "student_id": "2"},
        {"date": "2026-11-06", "venue": "柔力", "student_id": "9"},   # 對不到學員
    ]
    keys, unresolved = rc.app_class_keys(rows, id2name)
    assert keys[("陳麗卿", "武士", "2026-11-05")] == 2
    assert keys[("小丘", "柔力", "2026-11-06")] == 1
    assert unresolved == 1


def _ev(summary, kind, y, m, d):
    return (summary, kind, date(y, m, d))


def test_resolve_calendar_exact_alias_ignore_noise():
    id2name = {"1": "陳麗卿", "2": "邱玉青"}
    aliases = {"玉青": "邱玉青", "武士團課": ""}
    events = [
        _ev("陳麗卿 1200", "wushi", 2026, 11, 5),      # 完全相同
        _ev("玉青 1000", "wushi", 2026, 11, 6),         # 別名命中
        _ev("武士團課", "wushi", 2026, 11, 7),          # 別名空值＝忽略
        _ev("打掃", "wushi", 2026, 11, 7),              # extract_name 濾掉
        _ev("阿明 900", "wushi", 2026, 11, 8),          # 對不到 App
    ]
    cal, display, unmatched, counted = rc.resolve_calendar(events, id2name, aliases)
    assert cal[("陳麗卿", "武士", "2026-11-05")] == 1
    assert cal[("邱玉青", "武士", "2026-11-06")] == 1
    assert ("武士團課", "武士", "2026-11-07") not in [(u[0], u[1], u[2]) for u in unmatched]
    assert unmatched == [("阿明", "武士", "2026-11-08")]
    assert counted == 4            # 陳麗卿/玉青/武士團課/阿明（打掃不算）
    assert display["陳麗卿"] == "陳麗卿"


def test_resolve_calendar_skip_names():
    id2name = {"1": "陳麗卿"}
    events = [_ev("陳麗卿 1200", "wushi", 2026, 11, 5)]
    cal, _d, _u, _c = rc.resolve_calendar(events, id2name, {}, skip_names={"陳麗卿"})
    assert cal == rc.Counter()     # 被 skip → 不納入對帳


def test_find_missing_reports_only_calendar_excess():
    cal = rc.Counter({
        ("陳麗卿", "武士", "2026-11-05"): 2,   # 行事曆 2 堂
        ("小丘", "柔力", "2026-11-06"): 1,
    })
    app = rc.Counter({
        ("陳麗卿", "武士", "2026-11-05"): 1,   # App 只記 1 → 少 1
        ("小丘", "柔力", "2026-11-06"): 1,     # 齊 → 不報
    })
    missing = rc.find_missing(cal, app)
    assert missing == [("陳麗卿", "武士", "2026-11-05", 1)]


def test_find_missing_app_more_than_calendar_not_reported():
    # App 比行事曆多（補排/補登）不是漏記，不報
    cal = rc.Counter({("陳麗卿", "武士", "2026-11-05"): 1})
    app = rc.Counter({("陳麗卿", "武士", "2026-11-05"): 2})
    assert rc.find_missing(cal, app) == []


def test_self_check():
    assert rc.self_check(0, 5) == ["上週行事曆抓不到任何課（iCloud/GCal 憑證可能失效，或上週真的沒排課）"]
    assert rc.self_check(5, 0) == ["App Classes 讀到 0 筆（Sheet 讀取可能失敗）"]
    assert rc.self_check(5, 5) == []


def test_build_message_missing_grouped():
    missing = [
        ("陳麗卿", "武士", "2026-11-05", 1),
        ("陳麗卿", "武士", "2026-11-07", 2),
        ("小丘", "柔力", "2026-11-08", 1),
    ]
    display = {"陳麗卿": "陳麗卿", "小丘": "小丘"}
    msg = rc.build_message(date(2026, 11, 3), date(2026, 11, 9), missing, [], display, [])
    assert "上週課表對帳 11/3–11/9" in msg
    assert "沒記到（4 堂）" in msg
    assert "・陳麗卿（武士）11/5、11/7×2" in msg
    assert "・小丘（柔力）11/8" in msg


def test_build_message_all_recorded():
    msg = rc.build_message(date(2026, 11, 3), date(2026, 11, 9), [], [], {}, [])
    assert "✅ 上週的課都記到了" in msg


def test_build_message_unmatched_and_unresolved():
    msg = rc.build_message(
        date(2026, 11, 3), date(2026, 11, 9), [],
        [("阿明", "武士", "2026-11-06")], {}, [], unresolved_app=2)
    assert "對不到 App 學員（1" in msg
    assert "「阿明」（武士）11/6" in msg
    assert "App 有 2 筆上課紀錄對不到學員" in msg


def test_build_message_warnings_override():
    missing = [("陳麗卿", "武士", "2026-11-05", 1)]
    msg = rc.build_message(date(2026, 11, 3), date(2026, 11, 9), missing, [], {"陳麗卿": "陳麗卿"},
                           ["App Classes 讀到 0 筆（Sheet 讀取可能失敗）"])
    assert "讀取異常" in msg
    assert "沒記到" not in msg     # 有異常時不列漏記，避免誤報
