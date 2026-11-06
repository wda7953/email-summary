from datetime import date

from app_income import (
    parse_rows, rows_for_month, summarize_roulie, summarize_wushi,
    count_sessions, build_message, roulie_price_split,
    student_price_tier, count_sessions_by_price, sessions_by_week,
    student_latest_unit_price, summarize_wushi_executed,
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


# ── 武士改「實際執行」認列（2026-11-06 olan 拍板）──
# 柔力維持收款，武士改＝當月實際上課堂數 × 該生單價(App 成交價：總額÷堂數) ×60%
WUSHI_PAY = [
    {"student_id": "s1", "venue": "武士", "date": "2026-10-01",
     "total_amount": 9000, "period_sessions": 10},    # 900/堂
    {"student_id": "s2", "venue": "武士", "date": "2026-10-02",
     "total_amount": 12000, "period_sessions": 10},   # 1200/堂
]


def test_student_latest_unit_price_latest_wins_and_filters():
    payments = [
        {"student_id": "s1", "venue": "武士", "date": "2026-01-01",
         "total_amount": 9000, "period_sessions": 10},    # 舊 900
        {"student_id": "s1", "venue": "武士", "date": "2026-10-01",
         "total_amount": 11000, "period_sessions": 10},   # 新 1100 → 以最新為準
        {"student_id": "s1", "venue": "柔力", "date": "2026-10-05",
         "total_amount": 700, "period_sessions": 1},       # 別場地不算武士單價
        {"student_id": "s3", "venue": "武士", "date": "2026-10-01",
         "total_amount": 0, "period_sessions": 1},         # 0 元不列入
    ]
    assert student_latest_unit_price(payments, "武士") == {"s1": 1100.0}


def test_summarize_wushi_executed_sessions_times_unit_cut60():
    id2name = {"s1": "甲", "s2": "乙"}
    classes = [
        {"student_id": "s1", "venue": "武士", "date": "2026-10-03"},
        {"student_id": "s1", "venue": "武士", "date": "2026-10-10"},
        {"student_id": "s1", "venue": "武士", "date": "2026-10-17"},
        {"student_id": "s2", "venue": "武士", "date": "2026-10-05"},
        {"student_id": "s2", "venue": "武士", "date": "2026-10-12"},
    ]
    r = summarize_wushi_executed(classes, WUSHI_PAY, 2026, 10, id2name)
    assert r["counted"] == 5
    assert r["gross"] == 5100           # 3*900 + 2*1200
    assert r["income"] == 3060          # round(5100*0.6)
    assert r["unknown"] == 0 and r["excluded"] == 0


def test_summarize_wushi_executed_filters_venue_and_month():
    id2name = {"s1": "甲"}
    classes = [
        {"student_id": "s1", "venue": "武士", "date": "2026-10-03"},   # 計
        {"student_id": "s1", "venue": "武士", "date": "2026-09-30"},   # 別月不計
        {"student_id": "s1", "venue": "柔力", "date": "2026-10-04"},   # 別場地不計
    ]
    r = summarize_wushi_executed(classes, WUSHI_PAY, 2026, 10, id2name)
    assert r["counted"] == 1 and r["gross"] == 900 and r["income"] == 540


def test_summarize_wushi_executed_skips_income_names():
    id2name = {"s1": "甲", "skip": "黃誼淇", "lin": "為舜的媽 林阿姨"}
    pay = WUSHI_PAY + [
        {"student_id": "skip", "venue": "武士", "date": "2026-10-01",
         "total_amount": 10000, "period_sessions": 10},
        {"student_id": "lin", "venue": "武士", "date": "2026-10-01",
         "total_amount": 10000, "period_sessions": 10},
    ]
    classes = [
        {"student_id": "s1", "venue": "武士", "date": "2026-10-03"},
        {"student_id": "skip", "venue": "武士", "date": "2026-10-04"},
        {"student_id": "lin", "venue": "武士", "date": "2026-10-05"},
    ]
    r = summarize_wushi_executed(classes, pay, 2026, 10, id2name,
                                 skip_names={"黃誼淇", "為舜的媽 林阿姨"})
    assert r["counted"] == 1 and r["gross"] == 900   # 只算 s1
    assert r["excluded"] == 2                         # 黃誼淇＋林阿姨 的堂數不計入收入
    assert r["income"] == 540


def test_summarize_wushi_executed_unknown_price_reported_not_in_gross():
    id2name = {"s1": "甲", "s9": "無繳費"}
    classes = [
        {"student_id": "s1", "venue": "武士", "date": "2026-10-03"},
        {"student_id": "s9", "venue": "武士", "date": "2026-10-04"},   # 查無武士繳費 → unknown
    ]
    r = summarize_wushi_executed(classes, WUSHI_PAY, 2026, 10, id2name)
    assert r["counted"] == 1 and r["gross"] == 900
    assert r["unknown"] == 1 and r["income"] == 540


def test_summarize_wushi_executed_free_students_count_hours_not_income():
    # 免費課（如 x媽媽運動）：有付出工時要算堂數，但收入 $0，且不當「漏記價」提醒補價
    id2name = {"s1": "甲", "mom": "媽媽"}
    classes = [
        {"student_id": "s1", "venue": "武士", "date": "2026-10-03"},
        {"student_id": "mom", "venue": "武士", "date": "2026-10-04"},
        {"student_id": "mom", "venue": "武士", "date": "2026-10-11"},
    ]
    r = summarize_wushi_executed(classes, WUSHI_PAY, 2026, 10, id2name,
                                 free_names={"媽媽"})
    assert r["counted"] == 1 and r["gross"] == 900 and r["income"] == 540
    assert r["free"] == 2        # 媽媽兩堂算工時
    assert r["unknown"] == 0     # 免費不算漏記


def test_summarize_wushi_executed_free_beats_unknown_only_for_listed():
    # 不在免費清單、又查無價 → 仍是 unknown（要補價）
    id2name = {"mom": "媽媽", "s9": "漏記價"}
    classes = [
        {"student_id": "mom", "venue": "武士", "date": "2026-10-04"},
        {"student_id": "s9", "venue": "武士", "date": "2026-10-05"},
    ]
    r = summarize_wushi_executed(classes, WUSHI_PAY, 2026, 10, id2name,
                                 free_names={"媽媽"})
    assert r["free"] == 1 and r["unknown"] == 1


def test_build_message_wushi_shows_free_line():
    roulie = {"single": [], "package": [], "single_total": 0,
              "package_total": 0, "total": 0}
    wushi = {"gross": 900, "income": 540, "counted": 1,
             "free": 2, "unknown": 1, "excluded": 0}
    msg, _ = build_message(2026, 10, roulie, wushi, r_sessions=0, w_sessions=4)
    assert "免費課 2 堂（算工時、不計收入）" in msg
    assert "未計入 1 堂" in msg


def test_build_message_wushi_execution_format():
    roulie = {"single": [], "package": [], "single_total": 0,
              "package_total": 0, "total": 10000}
    wushi = {"gross": 5100, "income": 3060, "counted": 5, "unknown": 2, "excluded": 1}
    msg, _ = build_message(2026, 10, roulie, wushi, r_sessions=50, w_sessions=8)
    assert "實際執行 5 堂" in msg
    assert "抽成 $3,060（×60%）" in msg
    assert "未計入 2 堂" in msg
    assert "已排除 1 堂" in msg
    assert "本月收入：$13,060" in msg


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


# ── sessions_by_week：武士業績報告跟學員 App 對帳用的逐週計數 ──
def _cls(sid, d, venue="武士"):
    return [f"id_{sid}_{d}", sid, d, venue, "一般"]


def test_sessions_by_week_counts_per_week_and_venue():
    weeks = [(date(2026, 10, 5), date(2026, 10, 11)),
             (date(2026, 10, 12), date(2026, 10, 18))]
    raw = [CLS_HEADER,
           _cls("s1", "2026-10-08"),            # 第1週武士
           _cls("s2", "2026-10-09"),            # 第1週武士
           _cls("s3", "2026-10-09", "柔力"),    # 柔力不算
           _cls("s1", "2026-10-15"),            # 第2週武士
           _cls("s9", "2026-09-30")]            # 不在範圍
    rows = parse_rows(raw)
    out = sessions_by_week(rows, "武士", 2026, 10, {}, weeks)
    assert out[(date(2026, 10, 5), date(2026, 10, 11))] == 2
    assert out[(date(2026, 10, 12), date(2026, 10, 18))] == 1


def test_sessions_by_week_applies_skip_names():
    weeks = [(date(2026, 10, 19), date(2026, 10, 25))]
    raw = [CLS_HEADER,
           _cls("s1", "2026-10-19"),
           _cls("skip1", "2026-10-21")]         # 要被排除的人
    rows = parse_rows(raw)
    id2name = {"s1": "黃郁雯", "skip1": "黃誼淇"}
    out = sessions_by_week(rows, "武士", 2026, 10, id2name, weeks, frozenset({"黃誼淇"}))
    assert out[(date(2026, 10, 19), date(2026, 10, 25))] == 1  # 黃誼淇被排除
