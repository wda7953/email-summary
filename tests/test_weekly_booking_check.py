"""orchestrator 的純邏輯部分測試（window）。不打真 API，import 不需環境變數。"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import weekly_booking_check as wbc  # noqa: E402


def test_window_uses_check_start_override(monkeypatch):
    monkeypatch.setenv("CHECK_START", "2026-09-05")
    start, end = wbc.window()
    assert start.date() == date(2026, 9, 5)
    assert (end - start).days == 8
    assert (start + timedelta(days=7)).date() == date(2026, 9, 12)   # 顯示範圍末日（含當天共8天）


def test_load_skip_reads_json_file():
    skip = wbc.load_skip()
    assert "小丘" in skip
    assert "順哥" in skip


def test_load_pairs_reads_json_file():
    pairs = wbc.load_pairs()
    assert ["小叔叔", "媽媽"] in pairs
