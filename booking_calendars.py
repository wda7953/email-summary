"""讀三個行事曆來源，回傳 [(summary, kind)]。kind='wushi'|'roulie'。

- iCloud「武士」：全部事件＝武士課。
- iCloud「工作室」：只取 summary 含「柔力」的事件。
- 柔力 Google Calendar：只取含「柔力」或「olan」、且非全天的事件。
抓 iCloud 一律 expand=True（展開重複性事件，否則固定週課漏算）。
"""
import os
import re
import sys

import caldav
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

GCAL_ID = "1b49f93678583508e8185ed6fe71f414c19f09ff801eac2a7bbe08e28b22dd76@group.calendar.google.com"


def _icloud_cal(name_kw):
    client = caldav.DAVClient(
        url="https://caldav.icloud.com",
        username=os.environ["ICLOUD_USERNAME"],
        password=os.environ["ICLOUD_PASSWORD"],
    )
    cal = next((c for c in client.principal().calendars()
                if name_kw in str(c.get_display_name())), None)
    if not cal:
        raise ValueError(f"找不到行事曆：{name_kw}")
    return cal


def _icloud_summaries(name_kw, start, end):
    out = []
    for ev in _icloud_cal(name_kw).search(start=start, end=end, event=True, expand=True):
        try:
            out.append(str(ev.icalendar_component.get("SUMMARY", "")))
        except Exception as ex:
            print(f"略過 iCloud 事件（{name_kw}）：{ex}", file=sys.stderr)
    return out


def _gcal_summaries(start, end):
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GCAL_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/calendar.readonly"],
    )
    creds.refresh(Request())
    svc = build("calendar", "v3", credentials=creds, cache_discovery=False)
    res = svc.events().list(
        calendarId=GCAL_ID, singleEvents=True, orderBy="startTime",
        timeMin=start.isoformat(), timeMax=end.isoformat(),
    ).execute()
    out = []
    for item in res.get("items", []):
        if not item.get("start", {}).get("dateTime"):   # 跳過全天事件（多為個人行程）
            continue
        out.append(item.get("summary", ""))
    return out


def fetch_calendar_events(start, end):
    """回傳 [(summary, kind)]；start/end 為 tz-aware datetime。"""
    events = [(s, "wushi") for s in _icloud_summaries("武士", start, end)]
    for s in _icloud_summaries("工作室", start, end):
        if "柔力" in s:
            events.append((s, "roulie"))
    for s in _gcal_summaries(start, end):
        if "柔力" in s or re.search(r"olan", s, re.I):
            events.append((s, "roulie"))
    return events
