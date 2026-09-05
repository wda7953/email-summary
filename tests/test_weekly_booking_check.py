"""orchestrator 的純邏輯部分測試（window）。不打真 API，import 不需環境變數。"""
import os
import sys
from datetime import date, timedelta

import pytest

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


def test_main_sends_failure_line_when_config_json_is_broken(monkeypatch):
    """load_aliases()/load_pairs() 讀壞掉的 JSON 也要走「執行失敗」發 LINE 這條路，
    不能因為呼叫點在 try 區塊外面而整支腳本靜默炸掉、完全沒收到通知。"""
    monkeypatch.setattr(wbc, "fetch_students", lambda: [["id", "name", "status"]])
    monkeypatch.setattr(wbc, "fetch_calendar_events", lambda start, end: [])
    monkeypatch.setattr(wbc, "load_skip", lambda: set())
    monkeypatch.setattr(wbc, "load_pairs", lambda: [])

    def boom():
        raise ValueError("booking_aliases.json 壞掉")

    monkeypatch.setattr(wbc, "load_aliases", boom)

    sent = []
    monkeypatch.setattr(wbc, "send_line", lambda msg: sent.append(msg))

    with pytest.raises(ValueError):
        wbc.main()

    assert sent, "load_aliases() 出錯應該也要先發一則失敗 LINE"
    assert "執行失敗" in sent[0]
