from app_income import (
    parse_rows, rows_for_month, summarize_roulie, summarize_wushi,
    count_sessions, build_message,
)

HEADER = ["id", "student_id", "venue", "date", "package_name",
          "total_amount", "period_sessions", "paid_amount", "notes"]
CLS_HEADER = ["id", "student_id", "date", "venue", "type"]


# ── Task 1：欄位解析與月份篩選 ──
def test_parse_rows_maps_header():
    raw = [HEADER, ["p1", "s1", "柔力", "2026-08-01", "單次", "700", "1", "700"]]
    rows = parse_rows(raw)
    assert rows[0]["venue"] == "柔力"
    assert rows[0]["total_amount"] == 700
    assert rows[0]["period_sessions"] == 1
    assert rows[0]["student_id"] == "s1"


def test_rows_for_month_filters_venue_and_month():
    raw = [HEADER,
           ["p1", "s1", "柔力", "2026-08-01", "單次", "700", "1", "700"],
           ["p2", "s2", "柔力", "2026-07-31", "單次", "700", "1", "700"],
           ["p3", "s3", "武士", "2026-08-05", "", "3000", "5", "0"]]
    rows = parse_rows(raw)
    got = rows_for_month(rows, "柔力", 2026, 8)
    assert len(got) == 1 and got[0]["id"] == "p1"


# ── Task 2：柔力聚合 ──
def test_summarize_roulie_splits_single_and_package():
    id2name = {"s1": "仁哥", "s2": "品漩", "s3": "吳大哥"}
    rows = [
        {"student_id": "s1", "total_amount": 700, "period_sessions": 1},
        {"student_id": "s1", "total_amount": 700, "period_sessions": 1},
        {"student_id": "s2", "total_amount": 600, "period_sessions": 1},
        {"student_id": "s3", "total_amount": 8000, "period_sessions": 6},
    ]
    r = summarize_roulie(rows, id2name)
    assert ("仁哥", 2, 700, 1400) in r["single"]
    assert ("品漩", 1, 600, 600) in r["single"]
    assert r["single_total"] == 2000
    assert ("吳大哥", 8000, 6) in r["package"]
    assert r["package_total"] == 8000
    assert r["total"] == 10000


# ── Task 3：武士聚合 ──
def test_summarize_wushi_cut_and_skip():
    id2name = {"s1": "甲", "skip": "黃誼淇"}
    rows = [
        {"student_id": "s1", "total_amount": 10000, "period_sessions": 10},
        {"student_id": "skip", "total_amount": 9999, "period_sessions": 10},
    ]
    r = summarize_wushi(rows, id2name, skip_names={"黃誼淇"})
    assert r["gross"] == 10000
    assert r["income"] == 6000


# ── Task 4：堂數統計 ──
def test_count_sessions_by_venue_month_with_skip():
    id2name = {"s1": "甲", "skip": "黃誼淇"}
    raw = [CLS_HEADER,
           ["c1", "s1", "2026-08-02", "武士", "P"],
           ["c2", "skip", "2026-08-03", "武士", "P"],
           ["c3", "s1", "2026-07-30", "武士", "P"],
           ["c4", "s1", "2026-08-04", "柔力", "P"]]
    rows = parse_rows(raw)
    assert count_sessions(rows, "武士", 2026, 8, id2name, skip_names={"黃誼淇"}) == 1
    assert count_sessions(rows, "武士", 2026, 8, id2name) == 2  # 不排除＝含黃誼淇
    assert count_sessions(rows, "柔力", 2026, 8, id2name) == 1


# ── Task 5：組訊息 ──
def test_build_message_has_sections_and_totals():
    roulie = {
        "single": [("仁哥", 2, 700, 1400), ("品漩", 1, 600, 600)],
        "package": [("吳大哥", 8000, 6)],
        "single_total": 2000, "package_total": 8000, "total": 10000,
    }
    wushi = {"gross": 95604, "income": 57362}
    msg, warnings = build_message(2026, 8, roulie, wushi, r_sessions=88, w_sessions=100)
    assert "【2026年8月 收入月報】" in msg
    assert "仁哥 2×700" in msg
    assert "吳大哥 8,000" in msg
    assert "柔力小計：$10,000" in msg
    assert "抽成 $57,362" in msg
    assert "本月收入：$67,362" in msg
    assert "柔力：88 堂" in msg and "武士：100 堂" in msg
    assert warnings == []


def test_build_message_zero_warns():
    roulie = {"single": [], "package": [], "single_total": 0, "package_total": 0, "total": 0}
    wushi = {"gross": 0, "income": 0}
    msg, warnings = build_message(2026, 8, roulie, wushi, 0, 0)
    assert warnings and "0" in warnings[0]
    assert msg.startswith("⚠️")
