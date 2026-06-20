#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每天查 iCloud + Google Calendar 空檔，推薦皮拉提斯自主練習時間，發 LINE 提醒"""

import os
import sys
from datetime import date, datetime, timezone

import caldav
import pytz
import requests
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

TZ = pytz.timezone("Asia/Taipei")
ICLOUD_USER = "wda7953@hotmail.com"
ICLOUD_PASS = os.environ["ICLOUD_PASSWORD"]
LINE_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_USER = os.environ["LINE_USER_ID"]

# 柔力場館 Google Calendar（含 olan 教課時段）
GCAL_ID = "1b49f93678583508e8185ed6fe71f414c19f09ff801eac2a7bbe08e28b22dd76@group.calendar.google.com"

MIN_GAP = 30   # 最短空檔分鐘數
DAY_START = 8  # 搜尋起點（小時）
DAY_END = 22   # 搜尋終點（小時）

MODE = os.environ.get("REMINDER_MODE", "morning")


def send_line(msg: str) -> None:
    resp = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={"Authorization": f"Bearer {LINE_TOKEN}", "Content-Type": "application/json"},
        json={"to": LINE_USER, "messages": [{"type": "text", "text": msg}]},
        timeout=10,
    )
    if resp.status_code != 200:
        print(f"LINE 發送失敗：{resp.text}", file=sys.stderr)
        sys.exit(1)
    print(f"已發送：{msg[:30]}…")


def _gcal_creds() -> Credentials:
    creds = Credentials(
        token=None,
        refresh_token=os.environ["GCAL_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
    )
    creds.refresh(Request())
    return creds


def _to_tw(dt_str: str) -> datetime:
    """RFC3339 字串轉台灣時間 datetime"""
    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    return dt.astimezone(TZ)


def get_today_events() -> list[tuple[datetime, datetime]]:
    """取得今天 iCloud（全部行事曆）+ Google Calendar（柔力場館）的有時間事件"""
    today = date.today()
    window_start = TZ.localize(datetime(today.year, today.month, today.day, DAY_START, 0))
    window_end = TZ.localize(datetime(today.year, today.month, today.day, DAY_END, 0))
    events = []

    # ── iCloud（武士課 / 個人行程）──
    try:
        client = caldav.DAVClient(
            url="https://caldav.icloud.com",
            username=ICLOUD_USER,
            password=ICLOUD_PASS,
        )
        for cal in client.principal().calendars():
            try:
                for ev in cal.date_search(start=window_start, end=window_end):
                    try:
                        comp = ev.icalendar_component
                        dt_s = comp.get("DTSTART").dt
                        dt_e = comp.get("DTEND").dt
                        if isinstance(dt_s, date) and not isinstance(dt_s, datetime):
                            continue  # 全天事件跳過
                        if dt_s.tzinfo is None:
                            dt_s = TZ.localize(dt_s)
                        else:
                            dt_s = dt_s.astimezone(TZ)
                        if dt_e.tzinfo is None:
                            dt_e = TZ.localize(dt_e)
                        else:
                            dt_e = dt_e.astimezone(TZ)
                        events.append((dt_s, dt_e))
                    except Exception:
                        pass
            except Exception:
                pass
    except Exception as e:
        print(f"iCloud 讀取失敗：{e}", file=sys.stderr)

    # ── Google Calendar（柔力場館，含 olan 教課時段）──
    try:
        service = build("calendar", "v3", credentials=_gcal_creds(), cache_discovery=False)
        result = service.events().list(
            calendarId=GCAL_ID,
            timeMin=window_start.isoformat(),
            timeMax=window_end.isoformat(),
            singleEvents=True,
        ).execute()
        items = result.get("items", [])
        print(f"[DEBUG] Google Calendar 讀到 {len(items)} 個事件")
        for item in items:
            start = item.get("start", {})
            end = item.get("end", {})
            summary = item.get("summary", "(無標題)")
            print(f"[DEBUG] GCal 事件：{summary} / start={start} / end={end}")
            if "dateTime" not in start:
                print(f"[DEBUG] 跳過全天事件：{summary}")
                continue
            events.append((_to_tw(start["dateTime"]), _to_tw(end["dateTime"])))
    except Exception as e:
        print(f"Google Calendar 讀取失敗：{e}", file=sys.stderr)

    print(f"[DEBUG] iCloud+GCal 合計 {len(events)} 個有時間事件")
    for s, e in sorted(events):
        print(f"[DEBUG] 事件：{s.strftime('%H:%M')}–{e.strftime('%H:%M')}")

    return sorted(events)


def find_best_slot(events: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime, int]]:
    """找今天的空檔（回傳 [(開始, 結束, 分鐘數), ...]）"""
    today = date.today()
    window_start = TZ.localize(datetime(today.year, today.month, today.day, DAY_START, 0))
    window_end = TZ.localize(datetime(today.year, today.month, today.day, DAY_END, 0))

    # 合併重疊事件
    merged: list[list[datetime]] = []
    for s, e in events:
        s = max(s, window_start)
        e = min(e, window_end)
        if s >= e:
            continue
        if merged and s < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])

    # 列出空檔
    gaps = []
    cursor = window_start
    for s, e in merged:
        if s > cursor:
            mins = int((s - cursor).total_seconds() / 60)
            if mins >= MIN_GAP:
                gaps.append((cursor, s, mins))
        cursor = max(cursor, e)
    if cursor < window_end:
        mins = int((window_end - cursor).total_seconds() / 60)
        if mins >= MIN_GAP:
            gaps.append((cursor, window_end, mins))

    return gaps


def morning_reminder() -> None:
    today_str = datetime.now(TZ).strftime("%-m/%-d")
    events = get_today_events()
    gaps = find_best_slot(events)

    if not gaps:
        send_line(
            f"🧘‍♀️ {today_str} 早安！\n"
            "今天行程看起來很滿，但哪怕 15 分鐘的自主練習也算數唷 💪"
        )
        return

    # 選最長空檔
    best = max(gaps, key=lambda g: g[2])
    g_start, g_end, g_mins = best

    lines = [f"🧘‍♀️ {today_str} 早安！今天建議練習時段："]
    lines.append(f"✨ {g_start.strftime('%H:%M')}–{g_end.strftime('%H:%M')}（{g_mins} 分鐘）")

    others = [g for g in gaps if g != best]
    if others:
        other_str = "、".join(f"{g[0].strftime('%H:%M')}（{g[2]}分）" for g in others[:3])
        lines.append(f"其他空檔：{other_str}")

    lines.append("不要說「等一下」啊！")
    send_line("\n".join(lines))


def evening_reminder() -> None:
    today_str = datetime.now(TZ).strftime("%-m/%-d")
    send_line(
        f"🌙 {today_str} 今天有練皮拉提斯嗎？\n"
        "記得在 Obsidian 的 pilates-tracker 打 ✓"
    )


def main() -> None:
    if MODE == "evening":
        evening_reminder()
    else:
        morning_reminder()


if __name__ == "__main__":
    main()
