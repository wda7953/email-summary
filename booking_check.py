"""每週排課核對：純邏輯（零 I/O，方便測試）。

判定「有排到」只認：行事曆名字完全等於 App 全名，或別名表命中。
故意不讓模糊比對算「有排」——假陰性（把真的漏排藏起來）最危險。
模糊比對只拿來替「對不到 App 的行事曆名字」附上「疑似＝某某」建議。
"""
import re
from datetime import timedelta

# 這三人不用每週排（olan 2026-09-04 指定）
SKIP_STUDENTS = frozenset({"仁哥", "六哥", "蔡如斐"})

# 非學員標題雜訊：打掃、或 x/X 開頭（取消的課）不算學員預約
TITLE_NOISE = re.compile(r"^(打掃|[xX])")


def active_students(students_raw, skip=SKIP_STUDENTS):
    """Students 二維陣列（含表頭）→ [{'name','venue'}]，只留 status==active 且不在 skip。"""
    out = []
    if not students_raw:
        return out
    header = students_raw[0]
    idx = {h: i for i, h in enumerate(header)}

    def col(row, key):
        i = idx.get(key, -1)
        return row[i].strip() if 0 <= i < len(row) else ""

    for r in students_raw[1:]:
        name, status, venue = col(r, "name"), col(r, "status"), col(r, "venue")
        if not name or status != "active" or name in skip:
            continue
        out.append({"name": name, "venue": venue})
    return out


def extract_name(summary, kind):
    """從行事曆標題抓學員名。kind='wushi'|'roulie'。抓不到回 ''（該事件不計）。"""
    s = (summary or "").strip()
    if not s:
        return ""
    if kind == "roulie":
        s = re.sub(r"[（(]\s*柔力\s*[)）]", "", s).strip()   # 去括號柔力標記
        s = re.sub(r"\s*柔力\s*", " ", s).strip()           # 去無括號的柔力標記（如「olan 柔力」）
    if TITLE_NOISE.match(s):
        return ""
    name = re.sub(r"\s*收?\d.*", "", s).strip()   # 名字＝第一個數字前的文字，含前面的空白/「收」尾巴
    if not name or name.lower() == "olan":
        return ""
    return name


def _norm(s):
    return re.sub(r"\s+", "", (s or ""))


def _lcs_len(a, b):
    """最長共同子字串長度（O(n*m) DP，名字短，足夠）。"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


def suggest_alias(cal_name, app_names):
    """替對不到的行事曆名字找最像的 App 全名（需≥2 共同字），找不到回 None。"""
    a = _norm(cal_name)
    best, best_len = None, 0
    for name in app_names:
        l = _lcs_len(a, _norm(name))
        if l > best_len:
            best, best_len = name, l
    return best if best_len >= 2 else None


def match(active, calendar_names, aliases):
    """active: [{'name','venue'}]；calendar_names: 已抽名的 list[str]；
    aliases: {行事曆暱稱: App全名}，值為空字串＝已知忽略（排除三人/已結案/非學員）。
    回 {'missing','unmatched','suggestions'}。
    已知限制：比對用正規化後的名字，若兩位在線學員全名完全相同會被當成同一位
    （行事曆標題沒有學員 id 可分辨）——暫可接受，發生再處理。"""
    app_names = {_norm(s["name"]) for s in active}
    alias_norm = {_norm(k): _norm(v) for k, v in aliases.items()}

    matched, unmatched = set(), []
    for cn in calendar_names:
        n = _norm(cn)
        if n in app_names:
            matched.add(n)
        elif n in alias_norm:
            tgt = alias_norm[n]
            if tgt and tgt in app_names:
                matched.add(tgt)
            # tgt 為空、或指向非在線學員 → 已知，忽略（不進 unmatched）
        else:
            unmatched.append(cn)

    missing = [s for s in active if _norm(s["name"]) not in matched]
    suggestions = {cn: suggest_alias(cn, [s["name"] for s in active]) for cn in unmatched}
    return {"missing": missing, "unmatched": unmatched, "suggestions": suggestions}


def format_range(start):
    """start(date/datetime) → '9/5–9/12'（含當天共 8 天，末日＝start+7）。"""
    end = start + timedelta(days=7)
    return f"{start.month}/{start.day}–{end.month}/{end.day}"


def self_check(active_count, raw_event_count, name_count):
    """發前自檢：名單/事件讀到 0，或事件都抓不出名字（如全取消／假期週被 extract_name
    濾成空字串，raw_event_count>0 但 name_count==0）→ 回警告清單（有警告就不發漏排，
    避免「全部濾空」被誤判成「在線學員全員漏排」）。"""
    w = []
    if active_count == 0:
        w.append("學員名單讀到 0 人（App/Sheet 讀取可能失敗）")
    if raw_event_count == 0:
        w.append("行事曆讀到 0 筆事件（iCloud/GCal 憑證可能失效）")
    elif name_count == 0:
        w.append("行事曆有事件但抓不到任何學員名，解析可能有問題")
    return w


def build_message(start, result, warnings):
    """組 LINE 訊息。warnings 非空時只報異常、不列漏排（避免誤報全員漏排）。"""
    rng = format_range(start)
    lines = [f"📅 下週排課核對 {rng}", ""]
    if warnings:
        lines.append("⚠️ 讀取異常，本次結果不可信：")
        lines += [f"・{w}" for w in warnings]
        return "\n".join(lines)

    missing = result["missing"]
    if not missing:
        lines.append(f"✅ 下週在線學員都排到了（{rng}）")
    else:
        lines.append(f"⚠️ 還沒排到（{len(missing)} 位）：")
        lines += [f"・{m['name']}（{m['venue'] or '?'}）" for m in missing]

    unmatched = result["unmatched"]
    if unmatched:
        lines.append("")
        lines.append(f"❓ 行事曆有、對不到 App（{len(unmatched)} 個，需確認別名）：")
        for cn in unmatched:
            sug = result["suggestions"].get(cn)
            lines.append(f"・「{cn}」→ 疑似 {sug}" if sug else f"・「{cn}」→ 疑似 ?")
    return "\n".join(lines)
