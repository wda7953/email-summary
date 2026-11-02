"""武士週業績報告回歸測試：確保任何價格（含活動價）都會列出、堂數對得上名單。

這支測試守的鐵律：報表裡「當週總執行堂數」必須等於所有價位列名單加總。
2026-09 曾因固定價位清單漏列非標準價（1111）導致有人憑空消失，這裡防它復發。
"""
import os
import re
import sys
from datetime import date

# 讓測試找得到 .github/scripts 下的腳本；env 改成用到才讀，import 不會炸
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".github", "scripts"))

import wushi_monthly_report as w  # noqa: E402


def _session(name, price):
    return {"date": date(2026, 8, 3), "name": name, "price": price, "receipt_amt": 0}


def _listed_total(report):
    """把報表裡每個價位列括號中的人數加總（含非標準價位列）。"""
    return sum(int(m) for m in re.findall(r"（(\d+)）", report))


def test_standard_prices_reconcile():
    sessions = [_session("A", 1300), _session("B", 1300), _session("C", 1000)]
    rep = w.format_report(8, date(2026, 8, 3), date(2026, 8, 9), sessions, [])
    assert "當週總執行堂數：3" in rep
    assert _listed_total(rep) == 3  # 堂數 = 名單加總


def test_event_price_not_dropped():
    """活動價 / 非標準價（888）不能被吞掉，要有自己一列，堂數仍對得上。"""
    sessions = [_session("A", 1300), _session("郁雯姊", 888)]
    rep = w.format_report(8, date(2026, 8, 3), date(2026, 8, 9), sessions, [])
    assert "888（1）" in rep and "郁雯姊" in rep
    assert "當週總執行堂數：2" in rep
    assert _listed_total(rep) == 2
    assert "⚠️自檢異常" not in rep  # 對得上就不該觸發自檢警告


def test_selfcheck_invariant_across_prices():
    """混合標準價 + 多個非標準價，總堂數仍須等於名單加總。"""
    sessions = [
        _session("A", 1600), _session("B", 1111),
        _session("C", 1111), _session("D", 700), _session("E", 900),
    ]
    rep = w.format_report(8, date(2026, 8, 3), date(2026, 8, 9), sessions, [])
    assert "當週總執行堂數：5" in rep
    assert _listed_total(rep) == 5
    assert "⚠️自檢異常" not in rep


def test_prices_sorted_high_to_low_with_nonstandard_inline():
    """價位列全部由高到低排，非標準價(1111)要插在 1200 與 1100 之間，不落在最後。"""
    sessions = [_session("A", 1200), _session("B", 1111), _session("C", 1100)]
    rep = w.format_report(8, date(2026, 8, 3), date(2026, 8, 9), sessions, [])
    order = [int(m) for m in re.findall(r"^(\d+)（", rep, re.M)]
    assert order == sorted(order, reverse=True), f"價位未由高到低排：{order}"
    assert order.index(1200) < order.index(1111) < order.index(1100)


def test_show_names_false_strips_all_names():
    """無名字版：價位列與續約人數都不能出現任何名字，但數量要對。"""
    sessions = [_session("小叔叔", 1300), _session("郁雯姊", 1111)]
    receipts = [dict(_session("小叔叔", 1300), receipt_amt=1300)]
    rep = w.format_report(8, date(2026, 8, 3), date(2026, 8, 9), sessions, receipts, show_names=False)
    assert "小叔叔" not in rep and "郁雯姊" not in rep
    assert "1300（1）" in rep and "1111（1）" in rep       # 數量仍在
    assert "當週續約人數：1" in rep and "（小叔叔）" not in rep
    # 含名字版對照：名字要在
    rep2 = w.format_report(8, date(2026, 8, 3), date(2026, 8, 9), sessions, receipts, show_names=True)
    assert "小叔叔" in rep2 and "郁雯姊" in rep2


def test_fetch_uses_expand_not_date_search():
    """防呆：抓行事曆必須用 search(expand=True) 展開重複性事件。

    2026-09-02 曾因用 date_search（不展開）漏算每週固定學員，堂數嚴重低估。
    禁止退回 date_search，否則同一個 bug 會復發。
    """
    src = open(w.__file__, encoding="utf-8").read()
    assert "expand=True" in src, "fetch_events 必須用 search(expand=True) 展開重複性事件"
    assert "date_search" not in src, "禁止用 date_search（不展開重複性事件，會漏算固定學員）"


# ---- 2026-10 孫淑英漏算事件：逐週查詢回歸測試 ----
# 根因：iCloud 對整月一次 expand 遇到被改過的週期課(10/26 改時間、10/29 取消)會連整條
# 孫淑英系列一起靜默漏掉，逐週查則正常。以下用假日曆鎖死「逐週收齊、不漏、不重複」。

class _FakeDt:
    def __init__(self, d): self.dt = d

class _FakeComp:
    def __init__(self, summary, d): self._s, self._d = summary, d
    def get(self, key, default=None):
        if key == "DTSTART": return _FakeDt(self._d)
        if key == "SUMMARY": return self._s
        return default

class _FakeEvent:
    def __init__(self, summary, d): self.icalendar_component = _FakeComp(summary, d)


def test_collect_events_gathers_recurring_each_week():
    """逐週查要把每一週的課都收齊；只在某週四出現的週期課(孫淑英)不可被漏。"""
    universe = [
        _FakeEvent("孫淑英8 1200", date(2026, 10, 8)),    # 第2週週四
        _FakeEvent("孫淑英8 1200", date(2026, 10, 15)),   # 第3週週四
        _FakeEvent("八哥20 1000", date(2026, 10, 9)),
        _FakeEvent("打掃12", date(2026, 10, 7)),           # 應被 SKIP_RE 跳過
    ]
    # 模擬正常的逐週伺服器：各週只回該窗口內(start<=d<end)的事件
    def search_fn(start, end):
        return [e for e in universe
                if start.date() <= e.icalendar_component.get("DTSTART").dt < end.date()]
    evs = w.collect_events(search_fn, 2026, 10)
    names = [e["name"] for e in evs]
    assert names.count("孫淑英") == 2, f"週期課被漏算：{names}"
    assert "八哥" in names
    assert "打掃" not in names  # 打掃不是課，仍須跳過


def test_collect_events_dedupes_boundary():
    """邊界去重：就算 search_fn 每週都回傳同一筆，也只能依日期歸入一週、算一次。"""
    ev = _FakeEvent("玉青18 1000", date(2026, 10, 9))
    greedy = lambda start, end: [ev]  # 故意每週都回傳同一筆
    evs = w.collect_events(greedy, 2026, 10)
    assert sum(1 for e in evs if e["name"] == "玉青") == 1, "邊界事件被重複計算"


def test_fetch_is_per_week_not_month_wide():
    """防呆：fetch 必須走逐週 collect_events，不可退回月寬一次查(會中 iCloud 漏抓)。"""
    src = open(w.__file__, encoding="utf-8").read()
    assert "collect_events" in src, "fetch_events 必須改用逐週 collect_events"
    assert "week_ranges" in src, "逐週查需以 week_ranges 切週"


# ---- 學員 App 對帳 tripwire（逐週武士堂數 行事曆 vs App）----
def test_reconcile_diffs_flags_mismatch_week():
    weeks = [(date(2026, 10, 5), date(2026, 10, 11)),
             (date(2026, 10, 19), date(2026, 10, 25))]
    cal = {weeks[0]: 9, weeks[1]: 14}
    app = {weeks[0]: 9, weeks[1]: 13}  # 第2週差1
    diffs = w.reconcile_diffs(weeks, cal, app, 10)
    assert diffs == ["10/19-25 行事曆14/App13"]


def test_reconcile_diffs_empty_when_all_match():
    weeks = [(date(2026, 10, 5), date(2026, 10, 11))]
    cal = app = {weeks[0]: 9}
    assert w.reconcile_diffs(weeks, cal, app, 10) == []


def test_reconcile_with_app_never_raises_on_failure():
    """App 對帳是事後安全網：任何 I/O 失敗都只能回提示字串，絕不可拋例外擋主報告。"""
    weeks = [(date(2026, 10, 5), date(2026, 10, 11))]
    # 沒有 Google 憑證/套件的環境下也不能炸，只回「略過」字串
    out = w.reconcile_with_app(2026, 10, weeks, {weeks[0]: 9})
    assert isinstance(out, str) and out != ""
