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
        for k in ("total_amount", "period_sessions", "paid_amount"):
            v = str(d.get(k, "")).strip()
            d[k] = int(v) if v.lstrip("-").isdigit() else 0
        out.append(d)
    return out


def rows_for_month(rows, venue, year, month):
    """篩出指定場地、指定年月（依 date 欄前綴 YYYY-MM）的列。"""
    ym = f"{year:04d}-{month:02d}"
    return [r for r in rows if r.get("venue") == venue and str(r.get("date", "")).startswith(ym)]


def _name(id2name, sid):
    return id2name.get(sid, f"?{sid[:8]}")


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
    }


def summarize_wushi(rows, id2name, skip_names=frozenset({"黃誼淇"})):
    """武士收款加總（排除 skip_names）後 ×60% 抽成。"""
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


def build_message(year, month, roulie, wushi, r_sessions, w_sessions):
    """組月報 LINE 訊息文字；回 (msg, warnings)。"""
    warnings = []
    if roulie["total"] == 0 and wushi["gross"] == 0:
        warnings.append("柔力＋武士皆讀到 0，App 讀取可能失敗或該月無資料")

    single_detail = "、".join(f"{n} {c}×{fee}" for n, c, fee, _ in roulie["single"])
    pkg_detail = "、".join(f"{n} {amt:,}" for n, amt, _ in roulie["package"])
    total = roulie["total"] + wushi["income"]

    lines = [
        f"【{year}年{month}月 收入月報】",
        "",
        "＝柔力＝",
        f"單次：${roulie['single_total']:,}",
        f"　{single_detail}" if single_detail else "　（無）",
        f"套餐：${roulie['package_total']:,}",
        f"　{pkg_detail}" if pkg_detail else "　（無）",
        f"柔力小計：${roulie['total']:,}",
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
