"""
情境合成頁的固定收益對照（2026-10 改版）。

每一格情境對七個可觀察的市場變數各給一個「框架預期方向」，再跟近 1 個月
的實際變動並排——讀者自己看得到框架與市場哪裡一致、哪裡相反。

    short  短端曲線（10Y − 2Y）    ＋走陡　－走平　0 區間
    long   長端曲線（30Y − 10Y）   ＋走陡　－走平
    dur    10Y 殖利率              ＋上行（存續期間宜縮短）　－下行（宜拉長）
    tips   10Y 實質殖利率          ＋上行（TIPS 價格走弱）　－下行（走強）
    be     10Y 損益兩平            ＋擴大（通膨補償上升）　－收斂
    ig     投資級利差              ＋走擴　－收斂
    hy     高收益利差              ＋走擴　－收斂

「框架預期」是教科書式的映射（僅供對照，不構成投資建議）；「實際」只是事實。
另外提供存續期間與凸性的價格試算、市場定價方向、以及過去幾個月的格位軌跡。
"""

from __future__ import annotations

ROWS = [
    ("short", "短端曲線", "10Y − 2Y", "DGS10-DGS2", 5),
    ("long", "長端曲線", "30Y − 10Y", "DGS30-DGS10", 5),
    ("dur", "存續期間", "10Y 殖利率", "DGS10", 5),
    ("tips", "TIPS 價格", "10Y 實質殖利率", "DFII10", 5),
    ("be", "損益兩平", "10Y 通膨補償", "T10YIE", 5),
    ("ig", "投資級利差", "IG OAS", "BAMLC0A0CM", 5),
    ("hy", "高收益利差", "HY OAS", "BAMLH0A0HYM2", 15),
]

WORD = {
    "short": {"+": "走陡", "-": "走平", "0": "區間"},
    "long": {"+": "走陡", "-": "走平", "0": "區間"},
    "dur": {"+": "殖利率上行→縮短", "-": "殖利率下行→拉長", "0": "中性"},
    "tips": {"+": "實質利率上升→走弱", "-": "實質利率下降→走強", "0": "持平"},
    "be": {"+": "擴大", "-": "收斂", "0": "持平"},
    "ig": {"+": "走擴", "-": "收斂", "0": "區間"},
    "hy": {"+": "走擴", "-": "收斂", "0": "區間"},
}

# 情境 → 七個變數的預期方向（順序同 ROWS）
EXPECT = {
    #                       short long dur tips be  ig  hy
    "衰退式降息":            ("+", "0", "-", "-", "-", "+", "+"),
    "轉向降息":              ("+", "0", "-", "-", "0", "+", "+"),
    "預防性降息":            ("+", "0", "-", "-", "0", "-", "-"),
    "按兵不動":              ("0", "0", "0", "0", "0", "0", "0"),
    "小心觀望":              ("0", "0", "0", "0", "0", "0", "0"),
    "溫和成長":              ("0", "+", "0", "0", "0", "-", "-"),
    "兩難":                  ("-", "0", "+", "+", "+", "+", "+"),
    "升息壓力":              ("-", "+", "+", "+", "0", "+", "+"),
    "傾向緊縮":              ("-", "+", "+", "+", "0", "+", "0"),
    "忍受通膨":              ("+", "+", "+", "0", "+", "0", "0"),
    "降息受阻":              ("0", "0", "0", "0", "0", "+", "+"),
    "停滯性通膨：通膨優先":  ("-", "-", "+", "+", "+", "+", "+"),
    "停滯性通膨：救就業":    ("+", "+", "0", "-", "+", "+", "+"),
    "兩難僵局":              ("0", "0", "0", "0", "+", "+", "+"),
}

WHY = {
    "short": "短端跟著政策預期走：升息預期推高 2Y 比 10Y 多＝走平",
    "long": "長端看期限溢酬：財政與供給壓力推高 30Y＝走陡",
    "dur": "價格變動 ≈ −存續期間 × 殖利率變動，殖利率上行時長天期跌最多",
    "tips": "TIPS 價格跟實質殖利率反向：市場預期未來實質利率升高時 TIPS 走弱",
    "be": "損益兩平＝名目 − 實質，是市場要求的通膨補償",
    "ig": "投資級利差近期受科技巨頭大量發債影響（見長端頁）",
    "hy": "高收益利差反映景氣與違約風險",
}


def _delta(series: dict, spec: str, n: int = 22):
    """spec 是單一序列或「A-B」；回傳 (最新值, n 個交易日的變動 bp, 日期)。"""
    if "-" in spec:
        a, b = spec.split("-")
        A = {r["date"]: r["value"] for r in series.get(a) or [] if r.get("value") is not None}
        B = {r["date"]: r["value"] for r in series.get(b) or [] if r.get("value") is not None}
        ds = [d for d in sorted(A) if d in B]
        if len(ds) <= n:
            return None, None, ""
        now, then = A[ds[-1]] - B[ds[-1]], A[ds[-1 - n]] - B[ds[-1 - n]]
        return now * 100, (now - then) * 100, ds[-1]
    rows = [r for r in series.get(spec) or [] if r.get("value") is not None]
    if len(rows) <= n:
        return None, None, ""
    return rows[-1]["value"], (rows[-1]["value"] - rows[-1 - n]["value"]) * 100, rows[-1]["date"]


def compare(name: str, series: dict, n: int = 22) -> list[dict]:
    """框架預期 vs 近 1 個月實際，逐列。"""
    exp = EXPECT.get(name) or EXPECT["按兵不動"]
    out = []
    for (key, label, sub, spec, th), e in zip(ROWS, exp):
        lvl, d, date = _delta(series, spec, n)
        act = None if d is None else ("+" if d > th else "-" if d < -th else "0")
        if act is None:
            match = "na"
        elif act == e:
            match = "same"
        elif e == "0" or act == "0":
            match = "off"
        else:
            match = "opp"
        out.append({"key": key, "label": label, "sub": sub, "expect": e,
                    "expect_txt": WORD[key][e], "actual": act,
                    "actual_txt": (WORD[key][act] if act else "—"),
                    "delta_bp": d, "level": lvl, "date": date, "match": match,
                    "why": WHY[key], "unit": "bp" if "-" in spec else "%"})
    return out


MATCH_ZH = {"same": "一致", "off": "偏離", "opp": "相反", "na": "無資料"}


# ---------------------------------------------------------------------------
# 存續期間與凸性：價格變動 ≈ −D×Δy ＋ ½×C×Δy²
# ---------------------------------------------------------------------------
def _price(y: float, coupon: float, years: float, freq: int = 2) -> float:
    n = int(round(years * freq))
    c, r = coupon / freq, y / freq
    return sum(c / (1 + r) ** k for k in range(1, n + 1)) + 100 / (1 + r) ** n


def dur_conv(y_pct: float, years: float) -> tuple[float, float]:
    """平價債（票息＝殖利率）的修正存續期間與凸性（年、年²）。"""
    y, h = y_pct / 100, 1e-4
    c = y_pct
    p0, pu, pd = _price(y, c, years), _price(y + h, c, years), _price(y - h, c, years)
    return -(pu - pd) / (2 * h * p0), (pu + pd - 2 * p0) / (p0 * h * h)


def price_change(D: float, C: float, dy_bp: float) -> float:
    dy = dy_bp / 10000
    return (-D * dy + 0.5 * C * dy * dy) * 100


def duration_table(series: dict, n: int = 22) -> list[dict]:
    out = []
    for lab, sid, yrs in (("2 年", "DGS2", 2), ("5 年", "DGS5", 5), ("10 年", "DGS10", 10), ("30 年", "DGS30", 30)):
        rows = [r for r in series.get(sid) or [] if r.get("value") is not None]
        if len(rows) <= n:
            continue
        y = rows[-1]["value"]
        D, C = dur_conv(y, yrs)
        dy = (y - rows[-1 - n]["value"]) * 100
        out.append({"tenor": lab, "yield": y, "D": D, "C": C, "dy": dy,
                    "real": price_change(D, C, dy),
                    "up25": price_change(D, C, 25), "dn25": price_change(D, C, -25)})
    return out


# ---------------------------------------------------------------------------
# 市場定價方向 vs 本頁判讀
# ---------------------------------------------------------------------------
def market_lean(curve: dict | None) -> str | None:
    if not curve or curve.get("terminal") is None or curve.get("r0") is None:
        return None
    d = (curve["terminal"] - curve["r0"]) * 100
    return "hawkish" if d >= 12.5 else ("dovish" if d <= -12.5 else "neutral")


def divergence(page_lean: str, curve: dict | None) -> dict | None:
    ml = market_lean(curve)
    if ml is None:
        return None
    zh = {"hawkish": "偏緊縮", "dovish": "偏寬鬆", "neutral": "大致不動"}
    d = (curve["terminal"] - curve["r0"]) * 100
    agree = ml == page_lean
    return {"agree": agree, "market": ml, "page": page_lean, "bp": d,
            "text": (f"本頁判讀{zh.get(page_lean, '—')}，期貨也定價{zh[ml]}（終端 {d:+.0f}bp）——兩邊一致"
                     if agree else
                     f"本頁判讀{zh.get(page_lean, '—')}，但期貨定價{zh[ml]}（終端 {d:+.0f}bp）——"
                     "這個分歧就是要盯的地方：不是市場之後修正，就是判讀漏看了什麼")}


# ---------------------------------------------------------------------------
# 格位軌跡（依目前的門檻回推過去幾個月）
# ---------------------------------------------------------------------------
def _yoy_at(rows: list, month: str):
    mp = {r["date"][:7]: r["value"] for r in rows or [] if r.get("value") is not None}
    y, m = int(month[:4]), int(month[5:7])
    prev = f"{y - 1}-{m:02d}"
    return (mp[month] / mp[prev] - 1) * 100 if month in mp and prev in mp and mp[prev] else None


def _ann3_at(rows: list, month: str):
    mp = {r["date"][:7]: r["value"] for r in rows or [] if r.get("value") is not None}
    y, m = int(month[:4]), int(month[5:7])
    m3 = m - 3
    yy = y - 1 if m3 <= 0 else y
    m3 = m3 + 12 if m3 <= 0 else m3
    prev = f"{yy}-{m3:02d}"
    return ((mp[month] / mp[prev]) ** 4 - 1) * 100 if month in mp and prev in mp and mp[prev] else None


def _prev_month(mo: str) -> str:
    y, m = int(mo[:4]), int(mo[5:7]) - 1
    return f"{y - 1}-12" if m == 0 else f"{y}-{m:02d}"


def grid_trail(series: dict, u_lo: float | None, u_hi: float | None, bands: dict | None,
               months: int = 6) -> list[dict]:
    """
    過去 N 個月的格位：失業率對 FOMC 長期區間、核心 PCE 年增對 SEP 門檻，
    再套 Supercore 推一格的規則。門檻一律用**目前**的值（SEP 一季一變），
    也不含就業的失去工作者推格——畫面上會註明是回推。
    """
    from .scenario import supercore_push
    ur = series.get("UNRATE") or []
    pce = series.get("PCEPILFE") or []
    sc = series.get("IA001260M") or []
    if not ur or not pce or u_lo is None or u_hi is None:
        return []
    b = bands or {}
    lo, hi = b.get("low", 2.30), b.get("high", 2.90)
    last = min(ur[-1]["date"][:7], pce[-1]["date"][:7])
    ms, mo = [], last
    for _ in range(months):
        ms.append(mo)
        mo = _prev_month(mo)
    umap = {r["date"][:7]: r["value"] for r in ur}
    out = []
    for mo in reversed(ms):
        u, p = umap.get(mo), _yoy_at(pce, mo)
        if u is None or p is None:
            continue
        ls = "弱" if u > u_hi else ("強" if u < u_lo else "中")
        base = "低" if p < lo else ("高" if p > hi else "中")
        s_now, s_prev = _ann3_at(sc, mo), _ann3_at(sc, _prev_month(mo))
        is_, _ = supercore_push(base, [s_prev, s_now])
        out.append({"month": mo, "labor": ls, "infl": is_, "u": u, "pce": p, "sc3": s_now})
    return out


# ---------------------------------------------------------------------------
# 點陣圖中位數（每個年度欄）
# ---------------------------------------------------------------------------
def dot_medians(sep: dict | None) -> dict:
    """{年: 中位數}，只取數字年度（不含 Longer run）。點陣圖是每位與會者一點。"""
    dots = (sep or {}).get("dots") or {}
    years = dots.get("years") or []
    out = {}
    for j, y in enumerate(years):
        if not str(y).isdigit():
            continue
        pts = []
        for lvl, cnt in dots.get("rows") or []:
            if j < len(cnt):
                pts += [lvl] * int(cnt[j] or 0)
        if pts:
            pts.sort()
            n = len(pts)
            out[str(y)] = pts[n // 2] if n % 2 else (pts[n // 2 - 1] + pts[n // 2]) / 2
    return out
