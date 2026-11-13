"""上週課表對帳：純邏輯（零 I/O，方便測試）。

比對「上週行事曆上過的課」vs「學員 App Classes 已記錄的課」，
挑出『有上課、但 App 沒記到』的堂（olan 偶爾忘記記課表）。

防誤報設計（沿用排課核對 booking_check 的 philosophy）：
- 只把能對到 App 學員全名（完全相同／別名表命中）的行事曆課拿來比對；
  對不到的另列「對不到 App」，不當漏記——假陽性（把有記的報成漏記）最傷信任。
- 別名表（booking_aliases.json）值為空字串＝已知忽略（團課/一對二/非學員），直接略過。
- 自檢：行事曆或 App Classes 讀到 0 → 不報漏記，只報異常。
- reconcile_skip：指定學員不納入對帳（如課不記在 App 的學員），資料化維護、不用改 code。
- 逐 (學員, 場地, 日期) 比對堂數：同日同生上兩堂也抓得到少記。
"""
import re
from collections import Counter, defaultdict
from datetime import date, timedelta

import booking_check as bc  # extract_name：與排課核對共用同一套抽名規則

KIND_VENUE = {"wushi": "武士", "roulie": "柔力"}


def _norm(s):
    return re.sub(r"\s+", "", (s or ""))


def last_week_window(now):
    """now: 台灣 tz-aware datetime（排程週一跑）→ 回 (上週一, 上週日) date（含兩端）。"""
    today = now.date()
    this_mon = today - timedelta(days=today.weekday())   # 本週一（weekday(): 一=0）
    return this_mon - timedelta(days=7), this_mon - timedelta(days=1)


def rows_in_window(rows, start, end):
    """App Classes rows（dict，含 date 欄）篩出 date 落在 [start, end] 的列。"""
    out = []
    for r in rows:
        ds = str(r.get("date", ""))[:10]
        try:
            d = date.fromisoformat(ds)
        except ValueError:
            continue
        if start <= d <= end:
            out.append(r)
    return out


def app_class_keys(rows, id2name):
    """窗內 Classes rows → (Counter{(norm_name, venue, 'YYYY-MM-DD'): 堂數}, 對不到學員id的筆數)。"""
    keys = Counter()
    unresolved = 0
    for r in rows:
        name = id2name.get(r.get("student_id", ""))
        if not name:
            unresolved += 1          # student_id 對不到 Students（改名/未建檔）→ 另計，不靜默
            continue
        ds = str(r.get("date", ""))[:10]
        keys[(_norm(name), r.get("venue", ""), ds)] += 1
    return keys, unresolved


def resolve_calendar(events_dated, id2name, aliases, skip_names=frozenset()):
    """events_dated: [(summary, kind, date)]（date 為 date 物件或 None）。
    id2name: {id: name}（全部學員，給全名集合）；aliases: {暱稱: 全名}，空值＝已知忽略。
    回 (cal_keys: Counter{(norm_name, venue, 'YYYY-MM-DD'): n},
        display: {norm_name: 顯示全名},
        unmatched: [(顯示名, venue, 'YYYY-MM-DD')],
        counted: 有抽到名字的行事曆課數（給自檢用）)。
    skip_names：解析出的全名在此集合（正規化比對）→ 不納入對帳。"""
    all_norm = {_norm(n): n for n in id2name.values()}
    alias_norm = {_norm(k): _norm(v) for k, v in aliases.items() if v}
    ignore_norm = {_norm(k) for k, v in aliases.items() if not v}   # 空值＝已知忽略
    skip_norm = {_norm(n) for n in skip_names}

    cal = Counter()
    display = {}
    unmatched = []
    counted = 0
    for summary, kind, d in events_dated:
        venue = KIND_VENUE.get(kind)
        if not venue:
            continue
        nm = bc.extract_name(summary, kind)
        if not nm:
            continue                 # 打掃／olan 個人時段等雜訊
        counted += 1
        n = _norm(nm)
        if n in ignore_norm:
            continue                 # 團課/一對二/非學員，已知忽略
        if n in all_norm:
            full_norm = n
        elif n in alias_norm and alias_norm[n] in all_norm:
            full_norm = alias_norm[n]
        else:
            unmatched.append((nm, venue, d.isoformat() if d else "?"))
            continue
        if full_norm in skip_norm:
            continue
        ds = d.isoformat() if d else "?"
        cal[(full_norm, venue, ds)] += 1
        display[full_norm] = all_norm[full_norm]
    return cal, display, unmatched, counted


def find_missing(cal_keys, app_keys):
    """cal_keys / app_keys: Counter{(norm, venue, date): n}。
    回 [(norm, venue, date, 少記堂數)]，只收行事曆堂數 > App 堂數者。"""
    out = []
    for key, cn in cal_keys.items():
        gap = cn - app_keys.get(key, 0)
        if gap > 0:
            out.append((key[0], key[1], key[2], gap))
    return out


def self_check(cal_counted, app_total):
    """發前自檢：行事曆或 App Classes 讀到 0 → 回警告（有警告就不報漏記，避免誤報全員漏記）。"""
    w = []
    if cal_counted == 0:
        w.append("上週行事曆抓不到任何課（iCloud/GCal 憑證可能失效，或上週真的沒排課）")
    if app_total == 0:
        w.append("App Classes 讀到 0 筆（Sheet 讀取可能失敗）")
    return w


def _fmt_md(iso):
    """'2026-11-05' → '11/5'；非法/空 → 原樣。"""
    try:
        d = date.fromisoformat(iso)
        return f"{d.month}/{d.day}"
    except ValueError:
        return iso


def fmt_range(start, end):
    return f"{start.month}/{start.day}–{end.month}/{end.day}"


def build_message(start, end, missing, unmatched, display, warnings, unresolved_app=0):
    """組對帳 LINE 訊息。warnings 非空時只報異常、不列漏記。"""
    rng = fmt_range(start, end)
    lines = [f"🗂️ 上週課表對帳 {rng}", ""]

    if warnings:
        lines.append("⚠️ 讀取異常，本次結果不可信：")
        lines += [f"・{w}" for w in warnings]
        return "\n".join(lines)

    # 漏記：依 (學員, 場地) 聚合，列出少記的日期
    if not missing:
        lines.append(f"✅ 上週的課都記到了（{rng}）")
    else:
        grouped = defaultdict(list)   # (norm, venue) -> [(date_iso, gap)]
        for norm, venue, ds, gap in missing:
            grouped[(norm, venue)].append((ds, gap))
        total = sum(gap for _, _, _, gap in missing)
        lines.append(f"⚠️ 有上課、App 沒記到（{total} 堂）：")
        for (norm, venue), items in sorted(grouped.items(), key=lambda kv: kv[0][0]):
            items.sort(key=lambda x: x[0])
            dates = "、".join(
                f"{_fmt_md(ds)}×{gap}" if gap > 1 else _fmt_md(ds) for ds, gap in items
            )
            lines.append(f"・{display.get(norm, norm)}（{venue}）{dates}")

    if unmatched:
        lines.append("")
        lines.append(f"❓ 行事曆有、對不到 App 學員（{len(unmatched)}，無法判斷有沒有記）：")
        for nm, venue, ds in sorted(unmatched, key=lambda x: (x[0], x[2])):
            lines.append(f"・「{nm}」（{venue}）{_fmt_md(ds)}")

    if unresolved_app:
        lines.append("")
        lines.append(f"註：App 有 {unresolved_app} 筆上課紀錄對不到學員（改名/未建檔），未納入比對")

    return "\n".join(lines)
