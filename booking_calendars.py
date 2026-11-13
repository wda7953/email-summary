"""讀三個行事曆來源，回傳 [(summary, kind)]。kind='wushi'|'roulie'。

- iCloud「武士」：全部事件＝武士課。
- iCloud「工作室」：只取 summary 含「柔力」的事件。
- 柔力 Google Calendar：只取含「柔力」或「olan」、且非全天的事件。
抓 iCloud 一律 expand=True（展開重複性事件，否則固定週課漏算）。
"""
import os
import re
import sys
from datetime import datetime, date as _date

import caldav
import pytz
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

GCAL_ID = "1b49f93678583508e8185ed6fe71f414c19f09ff801eac2a7bbe08e28b22dd76@group.calendar.google.com"
TZ = pytz.timezone("Asia/Taipei")


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


def _gcal_items(start, end):
    """共用：讀柔力 Google Calendar 的原始事件 list（singleEvents 已展開重複課）。"""
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
    return res.get("items", [])


def _gcal_summaries(start, end):
    out = []
    for item in _gcal_items(start, end):
        if not item.get("start", {}).get("dateTime"):   # 跳過全天事件（多為個人行程）
            continue
        out.append(item.get("summary", ""))
    return out


def _to_taipei_date(dt):
    """把 iCloud/GCal 事件起始時間轉成台灣日期（date）。
    - tz-aware datetime → 轉台灣時區再取 date（避免 UTC 日界線 off-by-one）。
    - naive datetime → 當作已是台灣當地時間，不位移。
    - date（全天事件）→ 原樣。"""
    if isinstance(dt, datetime):
        return dt.astimezone(TZ).date() if dt.tzinfo else dt.date()
    if isinstance(dt, _date):
        return dt
    return None


def _icloud_events_dated(name_kw, start, end):
    """同 _icloud_summaries，但每筆回 (summary, 台灣date)。"""
    out = []
    for ev in _icloud_cal(name_kw).search(start=start, end=end, event=True, expand=True):
        try:
            comp = ev.icalendar_component
            summary = str(comp.get("SUMMARY", ""))
            dtstart = comp.get("DTSTART")
            d = _to_taipei_date(dtstart.dt) if dtstart is not None else None
            out.append((summary, d))
        except Exception as ex:
            print(f"略過 iCloud 事件（{name_kw}）：{ex}", file=sys.stderr)
    return out


def _gcal_events_dated(start, end):
    """同 _gcal_summaries，但每筆回 (summary, 台灣date)；跳過全天事件。"""
    out = []
    for item in _gcal_items(start, end):
        dt = item.get("start", {}).get("dateTime")
        if not dt:
            continue
        try:
            d = datetime.fromisoformat(dt).astimezone(TZ).date()
        except ValueError:
            continue
        out.append((item.get("summary", ""), d))
    return out


def is_roulie_studio(summary):
    """iCloud「工作室」行事曆：只認 summary 含「柔力」的事件為柔力課。"""
    return "柔力" in summary


def is_roulie_gcal(summary):
    """柔力 Google Calendar：只認含「柔力」或「olan」（不分大小寫）的事件為柔力課。"""
    return ("柔力" in summary) or bool(re.search(r"olan", summary, re.I))


def fetch_calendar_events(start, end):
    """回傳 [(summary, kind)]；start/end 為 tz-aware datetime。"""
    events = [(s, "wushi") for s in _icloud_summaries("武士", start, end)]
    for s in _icloud_summaries("工作室", start, end):
        if is_roulie_studio(s):
            events.append((s, "roulie"))
    for s in _gcal_summaries(start, end):
        if is_roulie_gcal(s):
            events.append((s, "roulie"))
    return events


def fetch_calendar_events_dated(start, end):
    """同 fetch_calendar_events，但每筆帶台灣日期：回 [(summary, kind, date)]。
    供「上週課表對帳」逐日比對行事曆 vs App Classes 用。"""
    events = [(s, "wushi", d) for (s, d) in _icloud_events_dated("武士", start, end)]
    for s, d in _icloud_events_dated("工作室", start, end):
        if is_roulie_studio(s):
            events.append((s, "roulie", d))
    for s, d in _gcal_events_dated(start, end):
        if is_roulie_gcal(s):
            events.append((s, "roulie", d))
    return events
