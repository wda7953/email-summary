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
