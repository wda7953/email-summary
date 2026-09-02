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


def test_fetch_uses_expand_not_date_search():
    """防呆：抓行事曆必須用 search(expand=True) 展開重複性事件。

    2026-09-02 曾因用 date_search（不展開）漏算每週固定學員，堂數嚴重低估。
    禁止退回 date_search，否則同一個 bug 會復發。
    """
    src = open(w.__file__, encoding="utf-8").read()
    assert "expand=True" in src, "fetch_events 必須用 search(expand=True) 展開重複性事件"
    assert "date_search" not in src, "禁止用 date_search（不展開重複性事件，會漏算固定學員）"
