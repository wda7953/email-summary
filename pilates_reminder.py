#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每天查 iCloud 行事曆空檔，推薦皮拉提斯自主練習時間，發 LINE 提醒"""

import os
import sys
from datetime import date, datetime, timedelta

import caldav
import pytz
import requests

TZ = pytz.timezone("Asia/Taipei")
ICLOUD_USER = "wda7953@hotmail.com"
ICLOUD_PASS = os.environ["ICLOUD_PASSWORD"]
LINE_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_USER = os.environ["LINE_USER_ID"]

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


def get_today_events() -> list[tuple[datetime, datetime]]:
    """取得今天所有 iCloud 行事曆的有時間的事件"""
    client = caldav.DAVClient(
        url="https://caldav.icloud.com",
        username=ICLOUD_USER,
        password=ICLOUD_PASS,
    )
    today = date.today()
    window_start = TZ.localize(datetime(today.year, today.month, today.day, DAY_START, 0))
    window_end = TZ.localize(datetime(today.year, today.month, today.day, DAY_END, 0))

    events = []
    for cal in client.principal().calendars():
        try:
            for ev in cal.date_search(start=window_start, end=window_end):
                try:
                    comp = ev.icalendar_component
                    dt_s = comp.get("DTSTART").dt
                    dt_e = comp.get("DTEND").dt

                    # 全天事件（date 型別）跳過
                    if isinstance(dt_s, date) and not isinstance(dt_s, datetime):
                        continue

                    # 統一轉台灣時區
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
