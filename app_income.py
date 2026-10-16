"""收入月報：學員 App 資料聚合純函式（零 I/O，方便測試）。

收款認列：月收入＝當月 Payments 每筆 total_amount 加總（單次＋套餐全額）。
paid_amount 欄不可靠（部分套餐記 0），一律用 total_amount。
"""


def parse_rows(raw):
    """raw: 含表頭的二維陣列（Google Sheets values）→ list[dict]，數字欄轉 int。"""
    if not raw:
        return []
    header = raw[0]
    out = []
    for r in raw[1:]:
        d = {header[i]: (r[i] if i < len(r) else "") for i in range(len(header))}
        # 金額/堂數容錯：Sheets 可能回傳格式化字串（千分位、小數），去逗號後用 float→int
        for k in ("total_amount", "period_sessions"):
            s = str(d.get(k, "")).replace(",", "").strip()
            try:
                d[k] = int(float(s))
            except (ValueError, TypeError):
                d[k] = 0
        out.append(d)
    return out


def rows_for_month(rows, venue, year, month):
    """篩出指定場地、指定年月（依 date 欄前綴 YYYY-MM）的列。"""
    ym = f"{year:04d}-{month:02d}"
    return [r for r in rows if r.get("venue") == venue and str(r.get("date", "")).startswith(ym)]


def _name(id2name, sid):
    return id2name.get(sid, f"?{sid[:8]}")


def roulie_price_split(rows, threshold=1000):
    """柔力收入依『單價＝總額÷堂數』分兩段：未滿門檻 vs 門檻(含)以上。
    含套餐（套餐單價＝總額÷堂數）；1000 本身歸「1000 以上」。
    回 below/above 金額、total、及四捨五入到小數一位的佔比。"""
    below = 0   # 單價 < threshold
    above = 0   # 單價 >= threshold（含門檻值本身）
    for r in rows:
        sess = r["period_sessions"] if r["period_sessions"] > 0 else 1  # 防除以零
        unit = r["total_amount"] / sess
        if unit < threshold:
            below += r["total_amount"]
        else:
            above += r["total_amount"]
    total = below + above
    return {
        "below": below,
        "above": above,
        "total": total,
        "below_pct": round(below / total * 100, 1) if total else 0.0,
        "above_pct": round(above / total * 100, 1) if total else 0.0,
    }


def summarize_roulie(rows, id2name):
    """柔力收入：單次(period_sessions==1)依姓名彙總，套餐(>1)逐筆列出。"""
    single_agg = {}  # (name, fee) -> [count, subtotal]
    package = []
    for r in rows:
        name = _name(id2name, r["student_id"])
        amt = r["total_amount"]
        if r["period_sessions"] == 1:
            fee = amt
            a = single_agg.setdefault((name, fee), [0, 0])
            a[0] += 1
            a[1] += amt
        else:
            package.append((name, amt, r["period_sessions"]))
    single = sorted(
        [(n, c, fee, sub) for (n, fee), (c, sub) in single_agg.items()],
        key=lambda x: -x[3],
    )
    single_total = sum(x[3] for x in single)
    package_total = sum(p[1] for p in package)
    return {
        "single": single,
        "package": sorted(package, key=lambda x: -x[1]),
        "single_total": single_total,
        "package_total": package_total,
        "total": single_total + package_total,
        "price_split": roulie_price_split(rows),  # 單價 1000 以下／以上 收入分段
    }


def summarize_wushi(rows, id2name, skip_names=frozenset()):
    """武士收款加總（排除 skip_names）後 ×60% 抽成。
    預設不排除任何人；黃誼淇是 60% 抽成、只是請款時間由 olan 決定，2026-09-16 起不再排除。
    保留 skip_names 參數機制，日後若有真正不抽成的學生可傳入。"""
    gross = 0
    for r in rows:
        if _name(id2name, r["student_id"]) in skip_names:
            continue
        gross += r["total_amount"]
    return {"gross": gross, "income": round(gross * 0.6)}


def count_sessions(rows, venue, year, month, id2name, skip_names=frozenset()):
    """Classes 出席堂數：指定場地/年月，預設不排除任何人。"""
    ym = f"{year:04d}-{month:02d}"
    n = 0
    for r in rows:
        if r.get("venue") != venue:
            continue
        if not str(r.get("date", "")).startswith(ym):
            continue
        if _name(id2name, r["student_id"]) in skip_names:
            continue
        n += 1
    return n


def build_message(year, month, roulie, wushi, r_sessions, w_sessions, unresolved=0):
    """組月報 LINE 訊息文字；回 (msg, warnings)。unresolved＝對不到學員名的收費筆數。"""
    warnings = []
    if roulie["total"] == 0 and wushi["gross"] == 0:
        warnings.append("柔力＋武士皆讀到 0，App 讀取可能失敗或該月無資料")
    if unresolved:
        warnings.append(f"{unresolved} 筆收費對不到學員名（顯示為 ?），收入歸屬／武士排除可能有誤")

    single_detail = "、".join(f"{n} {c}×{fee}" for n, c, fee, _ in roulie["single"])
    pkg_detail = "、".join(f"{n} {amt:,}" for n, amt, _ in roulie["package"])
    total = roulie["total"] + wushi["income"]

    # 單價分段（1000 以下／以上，含套餐）；舊呼叫沒帶 price_split 就不顯示
    ps = roulie.get("price_split")
    split_lines = []
    if ps and ps["total"]:
        split_lines = [
            "單價分佈：",
            f"　1000以下 ${ps['below']:,}（{ps['below_pct']}%）",
            f"　1000以上 ${ps['above']:,}（{ps['above_pct']}%）",
        ]

    lines = [
        f"【{year}年{month}月 收入月報】",
        "",
        "＝柔力＝",
        f"單次：${roulie['single_total']:,}",
        f"　{single_detail}" if single_detail else "　（無）",
        f"套餐：${roulie['package_total']:,}",
        f"　{pkg_detail}" if pkg_detail else "　（無）",
        f"柔力小計：${roulie['total']:,}",
        *split_lines,
        "",
        "＝武士＝",
        f"收款 ${wushi['gross']:,} → 抽成 ${wushi['income']:,}（×60%）",
        "",
        "＝合計＝",
        f"本月收入：${total:,}",
        "",
        "＝堂數＝",
        f"柔力：{r_sessions} 堂　武士：{w_sessions} 堂",
    ]
    msg = "\n".join(lines)
    if warnings:
        msg = "⚠️ 複查警告（請人工確認）\n" + "\n".join(f"・{w}" for w in warnings) + "\n\n" + msg
    return msg, warnings
