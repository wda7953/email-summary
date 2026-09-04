import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import booking_calendars as c  # noqa: E402


def test_uses_expand_not_date_search():
    src = open(c.__file__, encoding="utf-8").read()
    assert "expand=True" in src, "iCloud 讀取必須 expand=True 展開重複性事件"
    assert "date_search" not in src, "禁用 date_search（會漏算固定週課）"


def test_has_gcal_id():
    assert c.GCAL_ID.endswith("@group.calendar.google.com")


def test_is_roulie_studio_keeps_only_roulie_titles():
    assert c.is_roulie_studio("靜（柔力）900") is True
    assert c.is_roulie_studio("打掃") is False
    assert c.is_roulie_studio("陳麗卿 1200") is False


def test_is_roulie_gcal_keeps_roulie_or_olan_case_insensitive():
    assert c.is_roulie_gcal("小丘（柔力）900") is True
    assert c.is_roulie_gcal("Olan 個人時段") is True
    assert c.is_roulie_gcal("OLAN") is True
    assert c.is_roulie_gcal("陳麗卿 1200") is False
