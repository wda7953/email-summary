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
    return re.sub(r"\s+", "", (s or "")).strip()


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
    回 {'missing','unmatched','suggestions'}。"""
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
