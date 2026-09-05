"""每週排課核對純邏輯測試。"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import booking_check as b  # noqa: E402


def test_active_students_filters_status_and_skip():
    raw = [
        ["id", "name", "phone", "venue", "level", "status", "created_at", "notes", "partner_id"],
        ["1", "陳麗卿", "", "武士", "", "active", "2026-06-15"],
        ["2", "靜", "", "柔力", "Pilates", "active", "2026-06-15"],
        ["3", "仁哥", "", "柔力", "", "active", "2026-06-16"],          # 排除
        ["4", "六哥", "", "柔力", "", "active", "2026-06-24"],          # 排除
        ["5", "蔡如斐", "", "柔力", "", "active", "2026-06-15"],        # 排除
        ["6", "某離職", "", "武士", "", "inactive", "2026-06-15"],      # 非在線
    ]
    out = b.active_students(raw)
    names = [s["name"] for s in out]
    assert names == ["陳麗卿", "靜"]
    assert out[0]["venue"] == "武士" and out[1]["venue"] == "柔力"
    assert out[0]["id"] == "1" and out[1]["id"] == "2"          # 帶出 id 供夥伴比對
    assert out[0]["partner_id"] == ""                            # 沒給 partner_id 欄 → 空字串


def test_extract_name_wushi():
    assert b.extract_name("陳麗卿 1200", "wushi") == "陳麗卿"
    assert b.extract_name("小叔叔 收1300", "wushi") == "小叔叔"
    assert b.extract_name("打掃", "wushi") == ""
    assert b.extract_name("x 潘逸霖", "wushi") == "潘逸霖"      # x＝不計業績但課照上，仍算有排
    assert b.extract_name("x 媽媽運動17", "wushi") == "媽媽運動"
    assert b.extract_name("", "wushi") == ""


def test_extract_name_roulie():
    assert b.extract_name("小丘（柔力）900", "roulie") == "小丘"
    assert b.extract_name("Jess&Abby", "roulie") == "Jess&Abby"
    assert b.extract_name("olan 柔力", "roulie") == ""    # olan 個人時段不是學員
    assert b.extract_name("olan 拉筋", "roulie") == ""    # olan 個人時段雜訊，不只完全等於 olan 才濾
    assert b.extract_name("Olan 個人時段", "roulie") == ""  # 不分大小寫


def _active(*pairs):
    """pairs: (name, venue) 或 (name, venue, id, partner_id)。"""
    out = []
    for p in pairs:
        if len(p) == 2:
            n, v = p
            out.append({"name": n, "venue": v})
        else:
            n, v, sid, pid = p
            out.append({"name": n, "venue": v, "id": sid, "partner_id": pid})
    return out


def test_match_exact_alias_and_ignore():
    active = _active(("陳麗卿", "武士"), ("靜", "柔力"), ("小丘", "柔力"))
    cal = ["陳麗卿", "麗卿姊", "阿明"]   # 完全相同 / 需別名 / 未知
    aliases = {"麗卿姊": "陳麗卿", "阿明": ""}   # 空字串＝已知非在線/忽略
    res = b.match(active, cal, aliases)
    missing = [m["name"] for m in res["missing"]]
    assert "陳麗卿" not in missing          # 完全相同命中
    assert "靜" in missing and "小丘" in missing
    assert res["unmatched"] == []           # 阿明被 aliases 標記忽略，不算 unmatched


def test_match_alias_clears_student_alone():
    # 只靠別名比對（行事曆名單裡沒有跟學員全名完全相同的重複項）
    active = _active(("陳麗卿", "武士"))
    res = b.match(active, ["麗卿姊"], {"麗卿姊": "陳麗卿"})
    assert res["missing"] == []
    assert res["unmatched"] == []


def test_match_broken_alias_surfaces_as_unmatched():
    # 別名指向的目標不在在線名單裡（壞掉/過期的別名）→ 不能悄悄消失，要出現在 unmatched
    active = _active(("陳麗卿", "武士"))
    res = b.match(active, ["麗卿姊"], {"麗卿姊": "不存在的人"})
    assert "麗卿姊" in res["unmatched"]


def test_match_partner_scheduled_covers_both():
    # A(靖宜先生, partner_id=2) 沒被排到，但夥伴 B(靖宜, id=2) 有排到 → A 不算漏排
    active = _active(("靖宜先生", "武士", "1", "2"), ("靖宜", "柔力", "2", "1"))
    res = b.match(active, ["靖宜"], {})
    missing = [m["name"] for m in res["missing"]]
    assert "靖宜先生" not in missing        # 夥伴覆蓋
    assert "靖宜" not in missing            # 自己也有排到


def test_match_no_partner_still_reports_missing():
    # 沒有 partner_id 的舊行為不變：沒排到就是漏排
    active = _active(("陳麗卿", "武士"), ("靜", "柔力"))
    res = b.match(active, ["陳麗卿"], {})
    missing = [m["name"] for m in res["missing"]]
    assert "靜" in missing
    assert "陳麗卿" not in missing


def test_match_pair_scheduled_covers_both_directions():
    pairs = [["小叔叔", "媽媽"]]
    active = _active(("小叔叔", "武士"), ("媽媽", "武士"))

    # 只排到「媽媽」→ 小叔叔靠共用組不算漏排
    res = b.match(active, ["媽媽"], {}, pairs=pairs)
    missing = [m["name"] for m in res["missing"]]
    assert "小叔叔" not in missing
    assert "媽媽" not in missing

    # 對稱：只排到「小叔叔」→ 媽媽不算漏排
    res2 = b.match(active, ["小叔叔"], {}, pairs=pairs)
    missing2 = [m["name"] for m in res2["missing"]]
    assert "媽媽" not in missing2
    assert "小叔叔" not in missing2


def test_match_unrelated_student_no_pair_no_partner_still_missing():
    pairs = [["小叔叔", "媽媽"]]
    active = _active(("小叔叔", "武士"), ("媽媽", "武士"), ("陳麗卿", "武士"))
    res = b.match(active, ["媽媽"], {}, pairs=pairs)
    missing = [m["name"] for m in res["missing"]]
    assert "陳麗卿" in missing          # 無共用組、無 partner_id → 行為不變，仍算漏排
    assert "小叔叔" not in missing
    assert "媽媽" not in missing


def test_match_unmatched_gets_suggestion():
    active = _active(("陳麗卿", "武士"))
    res = b.match(active, ["麗卿姊"], {})     # 沒別名 → 進 unmatched 且附建議
    assert res["unmatched"] == ["麗卿姊"]
    assert res["suggestions"]["麗卿姊"] == "陳麗卿"


def test_suggest_alias_needs_two_common_chars():
    assert b.suggest_alias("麗卿姊", ["陳麗卿", "王小明"]) == "陳麗卿"
    assert b.suggest_alias("完全無關", ["陳麗卿"]) is None


def test_format_range():
    assert b.format_range(date(2026, 9, 5)) == "9/5–9/12"


def test_build_message_missing_list():
    res = {"missing": _active(("陳麗卿", "武士"), ("靜", "柔力")),
           "unmatched": [], "suggestions": {}}
    msg = b.build_message(date(2026, 9, 5), res, [])
    assert "下週排課核對 9/5–9/12" in msg
    assert "還沒排到（2 位）" in msg
    assert "・陳麗卿（武士）" in msg and "・靜（柔力）" in msg


def test_build_message_all_scheduled():
    res = {"missing": [], "unmatched": [], "suggestions": {}}
    msg = b.build_message(date(2026, 9, 5), res, [])
    assert "✅ 下週在線學員都排到了" in msg


def test_build_message_unmatched_block():
    res = {"missing": [], "unmatched": ["小新媽"], "suggestions": {"小新媽": None}}
    msg = b.build_message(date(2026, 9, 5), res, [])
    assert "對不到 App（1 個" in msg
    assert "「小新媽」→ 疑似 ?" in msg


def test_build_message_warnings_override():
    res = {"missing": _active(("陳麗卿", "武士")), "unmatched": [], "suggestions": {}}
    msg = b.build_message(date(2026, 9, 5), res, ["行事曆讀到 0 筆事件（iCloud/GCal 憑證可能失效）"])
    assert "讀取異常" in msg
    assert "還沒排到" not in msg          # 有異常時不列漏排，避免誤報全員漏排


def test_self_check():
    assert b.self_check(0, 5, 3) == ["學員名單讀到 0 人（App/Sheet 讀取可能失敗）"]
    assert b.self_check(30, 0, 0) == ["行事曆讀到 0 筆事件（iCloud/GCal 憑證可能失效）"]
    assert b.self_check(30, 5, 0) == ["行事曆有事件但抓不到任何學員名，解析可能有問題"]
    assert b.self_check(30, 5, 3) == []
