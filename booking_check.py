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
