from app_income import (
    parse_rows, rows_for_month, summarize_roulie, summarize_wushi,
    count_sessions, build_message, roulie_price_split,
    student_price_tier, count_sessions_by_price,
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


def test_parse_rows_handles_formatted_numbers():
    # 千分位、小數、空值都要容錯，不能靜默變 0
    raw = [HEADER,
           ["p1", "s1", "柔力", "2026-08-01", "套餐", "8,000", "6", "0"],
           ["p2", "s2", "柔力", "2026-08-02", "單次", "700.0", "1", ""]]
    rows = parse_rows(raw)
    assert rows[0]["total_amount"] == 8000
    assert rows[0]["period_sessions"] == 6
    assert rows[1]["total_amount"] == 700


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


# ── Task 2b：柔力單價分段（1000 以下／以上，含套餐）──
def test_roulie_price_split_by_unit_price():
    rows = [
        {"total_amount": 700, "period_sessions": 1},     # 單價 700 → 以下
        {"total_amount": 600, "period_sessions": 1},     # 單價 600 → 以下
        {"total_amount": 1600, "period_sessions": 2},    # 孟潔 800/堂 → 以下
        {"total_amount": 1000, "period_sessions": 1},    # 單價 1000 → 以上（含門檻）
        {"total_amount": 8000, "period_sessions": 6},    # 套餐 1333/堂 → 以上
    ]
    s = roulie_price_split(rows)
    assert s["below"] == 700 + 600 + 1600   # 2900
    assert s["above"] == 1000 + 8000        # 9000
    assert s["total"] == 11900
    assert s["below_pct"] == 24.4           # 2900/11900
    assert s["above_pct"] == 75.6


def test_roulie_price_split_guards_zero_sessions():
    # 堂數為 0 不可除以零，以 1 堂計
    s = roulie_price_split([{"total_amount": 700, "period_sessions": 0}])
    assert s["below"] == 700 and s["above"] == 0


# ── Task 2c：柔力實際執行堂數分段（1000 以下／以上）──
def test_student_price_tier_uses_latest_payment_and_handles_cheap_package():
    payments = [
        {"student_id": "s1", "venue": "柔力", "date": "2026-09-05",
         "total_amount": 700, "period_sessions": 1},                    # 700 → below
        {"student_id": "s2", "venue": "柔力", "date": "2026-02-07",
         "total_amount": 21000, "period_sessions": 30},                 # 蘇家愷 700/堂 套餐 → below
        {"student_id": "s3", "venue": "柔力", "date": "2026-09-04",
         "total_amount": 8000, "period_sessions": 6},                   # 1333/堂 → above
        {"student_id": "s4", "venue": "武士", "date": "2026-09-01",
         "total_amount": 12000, "period_sessions": 10},                 # 別場地不算柔力級距
    ]
    tier = student_price_tier(payments, "柔力")
    assert tier == {"s1": "below", "s2": "below", "s3": "above"}


def test_student_price_tier_takes_most_recent():
    payments = [
        {"student_id": "s1", "venue": "柔力", "date": "2026-01-01",
         "total_amount": 700, "period_sessions": 1},    # 舊：below
        {"student_id": "s1", "venue": "柔力", "date": "2026-09-01",
         "total_amount": 1200, "period_sessions": 1},   # 新：above（漲價）→ 以最新為準
    ]
    assert student_price_tier(payments, "柔力") == {"s1": "above"}


def test_count_sessions_by_price_splits_and_reports_unknown():
    payments = [
        {"student_id": "s1", "venue": "柔力", "date": "2026-09-05",
         "total_amount": 700, "period_sessions": 1},    # below
        {"student_id": "s2", "venue": "柔力", "date": "2026-09-04",
         "total_amount": 8000, "period_sessions": 6},   # above
    ]
    classes = [
        {"student_id": "s1", "venue": "柔力", "date": "2026-09-10"},
        {"student_id": "s1", "venue": "柔力", "date": "2026-09-12"},
        {"student_id": "s1", "venue": "柔力", "date": "2026-09-14"},
        {"student_id": "s2", "venue": "柔力", "date": "2026-09-11"},
        {"student_id": "s9", "venue": "柔力", "date": "2026-09-15"},  # 無繳費 → unknown
        {"student_id": "s1", "venue": "柔力", "date": "2026-08-30"},  # 別月不算
        {"student_id": "s2", "venue": "武士", "date": "2026-09-20"},  # 別場地不算
    ]
    s = count_sessions_by_price(classes, payments, "柔力", 2026, 9)
    assert s["below"] == 3 and s["above"] == 1 and s["unknown"] == 1
    assert s["total"] == 5
    assert s["below_pct"] == 75.0 and s["above_pct"] == 25.0  # 分母＝已分級4堂


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


def test_build_message_shows_price_split_when_present():
    roulie = {
        "single": [("仁哥", 1, 700, 700)], "package": [("吳大哥", 8000, 6)],
        "single_total": 700, "package_total": 8000, "total": 8700,
        "price_split": {"below": 700, "above": 8000, "total": 8700,
                        "below_pct": 8.0, "above_pct": 92.0},
    }
    wushi = {"gross": 0, "income": 0}
    split = {"below": 6, "above": 3, "unknown": 1, "total": 10,
             "below_pct": 66.7, "above_pct": 33.3}
    msg, _ = build_message(2026, 9, roulie, wushi, 10, 0, r_session_split=split)
    assert "單價分佈：" in msg
    assert "1000以下 $700（8.0%）" in msg
    assert "1000以上 $8,000（92.0%）" in msg
    # 堂數分段行
    assert "柔力單價：1000以下 6 堂（66.7%）／1000以上 3 堂（33.3%）" in msg
    assert "未分級 1 堂" in msg


def test_build_message_warns_on_unresolved():
    roulie = {"single": [("?abcd1234", 1, 700, 700)], "package": [],
              "single_total": 700, "package_total": 0, "total": 700}
    wushi = {"gross": 1000, "income": 600}
    msg, warnings = build_message(2026, 8, roulie, wushi, 1, 1, unresolved=2)
    assert any("對不到學員" in w for w in warnings)


def test_build_message_zero_warns():
    roulie = {"single": [], "package": [], "single_total": 0, "package_total": 0, "total": 0}
    wushi = {"gross": 0, "income": 0}
    msg, warnings = build_message(2026, 8, roulie, wushi, 0, 0)
    assert warnings and "0" in warnings[0]
    assert msg.startswith("⚠️")
