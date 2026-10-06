"""
長端利率的三股力量與供給、拍賣（2026-10 改版）。

拆解（模型三段相加）
--------------------
    10 年擬合殖利率（Kim-Wright）＝ 預期實質路徑 ＋ 預期通膨 ＋ 期限溢酬
      期限溢酬    Kim-Wright THREEFYTP10                 → 財政與供給壓力
      預期通膨    克里夫蘭聯儲 EXPINF10YR（已扣風險溢酬）→ 通膨壓力
      預期實質路徑 擬合殖利率 − 期限溢酬 − 預期通膨        → 政策壓力
    實際 10Y（DGS10）與擬合殖利率的差列為「殘差」，照實顯示。

預期通膨是月頻，所以三段一律用**月均**對齊，貢獻＝月均對月均的變動。
TIPS 實質利率與損益兩平是市場口徑，只當參考：兩者各自混了風險溢酬，
三段加不起來，也分不出誰是主因。

所有判定都只做「哪一段動得最多」這種事實比較，不做加權總分。
"""

from __future__ import annotations

import datetime as dt

COMP = [  # key, 中文, 壓力名稱, 性質
    ("real", "預期實質路徑", "政策壓力", "市場預先替 Fed 定價；Fed 跟上之前只是預告"),
    ("infl", "預期通膨", "通膨壓力", "名目緊縮、實質未收緊：借貸成本變高，但實質利率沒動"),
    ("tp", "期限溢酬", "財政與供給壓力", "不靠 Fed 也會收緊金融條件"),
]
COMP_ZH = {k: zh for k, zh, _, _ in COMP}
PRESSURE_ZH = {k: p for k, _, p, _ in COMP}
NATURE = {k: n for k, _, _, n in COMP}


def monthly_avg(rows: list[dict]) -> dict:
    acc: dict = {}
    for r in rows or []:
        v = r.get("value")
        if v is None:
            continue
        acc.setdefault(r["date"][:7], []).append(v)
    return {k: sum(v) / len(v) for k, v in acc.items()}


def decompose(series: dict) -> list[dict]:
    """逐月：{month, fitted, tp, infl, real, nominal, resid}，由舊到新。"""
    fy = monthly_avg(series.get("THREEFY10") or [])
    tp = monthly_avg(series.get("THREEFYTP10") or [])
    ei = monthly_avg(series.get("EXPINF10YR") or [])
    nom = monthly_avg(series.get("DGS10") or [])
    out = []
    for m in sorted(set(fy) & set(tp) & set(ei)):
        real = fy[m] - tp[m] - ei[m]
        out.append({"month": m, "fitted": fy[m], "tp": tp[m], "infl": ei[m], "real": real,
                    "nominal": nom.get(m), "resid": (nom[m] - fy[m]) if m in nom else None})
    return out


def contribution(dec: list[dict], k: int) -> dict | None:
    """最新一個月 對 k 個月前：各段變動（bp）與主因。"""
    if len(dec) <= k:
        return None
    a, b = dec[-1 - k], dec[-1]
    d = {key: (b[key] - a[key]) * 100 for key in ("real", "infl", "tp")}
    d_res = ((b["resid"] - a["resid"]) * 100
             if b.get("resid") is not None and a.get("resid") is not None else 0.0)
    d_nom = ((b["nominal"] - a["nominal"]) * 100
             if b.get("nominal") is not None and a.get("nominal") is not None
             else sum(d.values()) + d_res)
    main = max(d, key=lambda x: abs(d[x]))
    return {"k": k, "from": a["month"], "to": b["month"], "parts": d, "resid": d_res,
            "nominal": d_nom, "start": a.get("nominal") or a["fitted"],
            "end": b.get("nominal") or b["fitted"], "main": main,
            "main_bp": d[main], "same_sign_share": (abs(d[main]) / (sum(abs(v) for v in d.values()) or 1))}


def main_sentence(c: dict | None) -> str:
    if not c:
        return "資料不足，無法拆解"
    m = c["main"]
    return (f"{_mz(c['from'])}→{_mz(c['to'])} 10Y 月均 {c['nominal']:+.0f}bp，"
            f"主因：{COMP_ZH[m]} {c['parts'][m]:+.0f}bp（{PRESSURE_ZH[m]}）")


def _mz(m: str) -> str:
    return f"{int(m[5:7])} 月"


def _ten_zh(t: str) -> str:
    from ..treasury_source import TENOR_ZH
    return TENOR_ZH.get(t, t)


# ---------------------------------------------------------------------------
# 殖利率曲線
# ---------------------------------------------------------------------------
CURVE = [("3M", "DGS3MO", .25), ("1Y", "DGS1", 1), ("2Y", "DGS2", 2), ("5Y", "DGS5", 5),
         ("7Y", "DGS7", 7), ("10Y", "DGS10", 10), ("20Y", "DGS20", 20), ("30Y", "DGS30", 30)]


def _at(rows: list[dict], date: str):
    """date 當天或之前最近的一筆。"""
    best = None
    for r in rows or []:
        if r.get("value") is None:
            continue
        if r["date"] <= date:
            best = r
        else:
            break
    return best


def curve_snapshots(series: dict) -> list[dict]:
    """現在、1 個月前、1 年前三條曲線：[{label, date, points:[(tenor, years, value)]}]。"""
    last = (series.get("DGS10") or [{}])[-1].get("date")
    if not last:
        return []
    d0 = dt.date.fromisoformat(last[:10])
    out = []
    for lab, dd in (("現在", d0), ("1 個月前", d0 - dt.timedelta(days=30)),
                    ("1 年前", d0 - dt.timedelta(days=365))):
        pts = []
        for ten, sid, yrs in CURVE:
            r = _at(series.get(sid) or [], dd.isoformat())
            if r:
                pts.append((ten, yrs, r["value"]))
        if len(pts) >= 4:
            out.append({"label": lab, "date": dd.isoformat(), "points": pts})
    return out


# ---------------------------------------------------------------------------
# 拍賣
# ---------------------------------------------------------------------------
_CMT = {"2-Year": "DGS2", "3-Year": "DGS3", "5-Year": "DGS5", "7-Year": "DGS7",
        "10-Year": "DGS10", "20-Year": "DGS20", "30-Year": "DGS30"}


def _cmt_close(series: dict, term: str, date: str):
    sid = _CMT.get(term)
    if sid == "DGS3":             # 沒有 3 年 CMT：用 2 年與 5 年線性內插
        a, b = _at(series.get("DGS2") or [], date), _at(series.get("DGS5") or [], date)
        if a and b and a["date"] == date and b["date"] == date:
            return a["value"] + (b["value"] - a["value"]) / 3
        return None
    r = _at(series.get(sid) or [], date) if sid else None
    return r["value"] if r and r["date"] == date else None


def auction_rows(auctions: list[dict], series: dict, n_prev: int = 6) -> list[dict]:
    """
    名目 coupon（不含 TIPS、FRN）逐場加上：
      tail_bp     得標殖利率 − 當日收盤固定期限殖利率（近似 tail；正＝需求弱）
      disp_bp     得標殖利率 − 中位得標殖利率（分散度，越大越分歧）
      dealer/indirect/direct  佔競標得標量 %
      vs6         與同天期前 6 場平均的差
      verdict     偏弱／中性／偏強（規則見 VERDICT_RULE）
    """
    nom = [a for a in auctions if not a.get("tips") and not a.get("frn")
           and a.get("term") in _CMT]
    by: dict = {}
    out = []
    for a in nom:
        acc = a.get("comp_acc") or ((a["pd"] + a["direct"] + a["indirect"]) or None)
        row = dict(a)
        if acc:
            row["dealer_pct"] = a["pd"] / acc * 100
            row["indirect_pct"] = a["indirect"] / acc * 100
            row["direct_pct"] = a["direct"] / acc * 100
        close = _cmt_close(series, a["term"], a["date"])
        row["tail_bp"] = (a["high"] - close) * 100 if close is not None else None
        row["disp_bp"] = ((a["high"] - a["median"]) * 100
                          if a.get("median") is not None else None)
        prev = by.get(a["term"], [])[-n_prev:]
        if prev:
            def avg(k):
                vs = [p[k] for p in prev if p.get(k) is not None]
                return sum(vs) / len(vs) if vs else None
            row["avg_btc"], row["avg_dealer"] = avg("btc"), avg("dealer_pct")
            row["avg_tail"] = avg("tail_bp")
        sig = 0
        if row.get("tail_bp") is not None:
            sig += 1 if row["tail_bp"] > 0.5 else (-1 if row["tail_bp"] < -0.5 else 0)
        if row.get("avg_dealer") is not None and row.get("dealer_pct") is not None:
            dd = row["dealer_pct"] - row["avg_dealer"]
            sig += 1 if dd > 2 else (-1 if dd < -2 else 0)
        if row.get("avg_btc") is not None and row.get("btc") is not None:
            db = row["btc"] - row["avg_btc"]
            sig += 1 if db < -0.1 else (-1 if db > 0.1 else 0)
        row["signals"] = sig
        row["verdict"] = "偏弱" if sig >= 2 else ("偏強" if sig <= -2 else "中性")
        by.setdefault(a["term"], []).append(row)
        out.append(row)
    return out


VERDICT_RULE = ("三個訊號各給一分：tail≈ 高於 +0.5bp、交易商承接比近 6 場平均高 2 個百分點以上、"
                "投標倍數比近 6 場平均低 0.1 以上，各算一個「偏弱」訊號（反方向算偏強）。"
                "淨兩個以上偏弱＝偏弱，淨兩個以上偏強＝偏強，其餘中性。")


def latest_by_tenor(rows: list[dict]) -> list[dict]:
    from ..treasury_source import TENORS
    out = []
    for t in TENORS:
        cand = [r for r in rows if r["term"] == t]
        if cand:
            out.append(cand[-1])
    return out


def size_path(auctions: list[dict], months: int = 24) -> dict:
    """各天期每月拍賣規模（含增發），{term: [{date, value}]}，十億美元。"""
    from ..treasury_source import TENORS
    nom = [a for a in auctions if not a.get("tips") and not a.get("frn")]
    out = {}
    for t in TENORS:
        acc: dict = {}
        for a in nom:
            if a["term"] == t and a.get("offering"):
                acc[a["date"][:7]] = acc.get(a["date"][:7], 0) + a["offering"]
        pts = [{"date": m + "-01", "value": v} for m, v in sorted(acc.items())]
        out[t] = pts[-months:]
    return out


# ---------------------------------------------------------------------------
# Fed 資產端
# ---------------------------------------------------------------------------
SOMA_PARTS = [("bills", "T-Bills"), ("notesbonds", "Notes＋Bonds"), ("tips", "TIPS"),
              ("frn", "FRN"), ("mbs", "MBS")]


def soma_mix(soma: list[dict]) -> dict:
    """現在 vs 約一年前的組成（%），與 MBS、Bills 近 12 個月的月變動。"""
    if not soma:
        return {}
    now = soma[-1]
    ago = next((r for r in reversed(soma) if r["date"] <= _minus_days(now["date"], 364)), soma[0])

    def mix(r):
        tot = sum(r.get(k, 0) for k, _ in SOMA_PARTS) or 1
        return [(lab, r.get(k, 0), r.get(k, 0) / tot * 100) for k, lab in SOMA_PARTS]
    # 每月最後一週
    me: dict = {}
    for r in soma:
        me[r["date"][:7]] = r
    ms = [me[k] for k in sorted(me)]
    flows = []
    for a, b in zip(ms, ms[1:]):
        flows.append({"date": b["date"][:7] + "-01", "mbs": b["mbs"] - a["mbs"],
                      "bills": b["bills"] - a["bills"]})
    return {"now": {"date": now["date"], "mix": mix(now), "total": sum(now.get(k, 0) for k, _ in SOMA_PARTS)},
            "ago": {"date": ago["date"], "mix": mix(ago)},
            "flows": flows[-12:]}


def _minus_days(iso: str, n: int) -> str:
    return (dt.date.fromisoformat(iso[:10]) - dt.timedelta(days=n)).isoformat()


# ---------------------------------------------------------------------------
# Fed 跟上曲線了嗎
# ---------------------------------------------------------------------------
def match_the_curve(mvd: dict | None, contrib12: dict | None) -> dict | None:
    """
    期貨隱含的年底利率、點陣圖中位數、現行利率三者對照。
    市場比點陣圖多定價的部分＝「市場還在等 Fed 跟上」。
    """
    if not mvd or mvd.get("market_end") is None or mvd.get("dot_median") is None:
        return None
    r0 = mvd.get("r0")
    mk = (mvd["market_end"] - r0) * 100 if r0 is not None else None
    dots = (mvd["dot_median"] - r0) * 100 if r0 is not None else None
    gap = mvd.get("gap_bp")
    if gap is None and mk is not None and dots is not None:
        gap = mk - dots
    if gap is None:
        return None
    if abs(gap) < 12.5:
        verdict = "Fed 已跟上曲線：點陣圖與期貨路徑大致一致"
    elif gap > 0:
        verdict = f"市場比點陣圖多定價 {gap:.0f}bp 的緊縮——Fed 還沒跟上"
    else:
        verdict = f"市場比點陣圖少定價 {abs(gap):.0f}bp——市場不相信點陣圖的緊縮"
    return {"year": mvd.get("year"), "r0": r0, "market_end": mvd["market_end"],
            "dot_median": mvd["dot_median"], "market_bp": mk, "dots_bp": dots,
            "gap_bp": gap, "verdict": verdict,
            "real12_bp": (contrib12 or {}).get("parts", {}).get("real")}


# ---------------------------------------------------------------------------
# 事件日曆
# ---------------------------------------------------------------------------
def events(today: dt.date, upcoming: list[dict], refunding_next: str | None,
           days: int = 28) -> list[dict]:
    end = today + dt.timedelta(days=days)
    ev = []
    for a in upcoming or []:
        if a.get("type") == "Bill" or a.get("frn"):
            continue
        d = dt.date.fromisoformat(a["date"])
        if today <= d <= end:
            ev.append({"date": a["date"], "kind": "拍賣",
                       "text": f"{_ten_zh(a['term'])}{' TIPS' if a.get('tips') else ''}"
                               f"{'（增發舊券）' if a.get('reopening') else '（新券）'}"
                               + (f"　{a['offering']*10:,.0f} 億美元" if a.get("offering") else "　金額待公告")})
    if refunding_next:
        d = dt.date.fromisoformat(refunding_next)
        if today <= d <= today + dt.timedelta(days=60):
            ev.append({"date": refunding_next, "kind": "再融資",
                       "text": "每季再融資公告（下一季各天期 coupon 規模與指引）"})
    # 每週四 H.4.1（Fed 資產負債表）
    d = today
    while d <= end:
        if d.weekday() == 3:
            ev.append({"date": d.isoformat(), "kind": "Fed 資產", "text": "H.4.1 Fed 資產負債表"})
            break
        d += dt.timedelta(days=1)
    # MSPD：每月第 4 個工作日
    for mo in range(2):
        y, m = today.year + (today.month + mo > 12), (today.month + mo - 1) % 12 + 1
        d, n = dt.date(y, m, 1), 0
        while True:
            if d.weekday() < 5:
                n += 1
                if n == 4:
                    break
            d += dt.timedelta(days=1)
        if today <= d <= end:
            ev.append({"date": d.isoformat(), "kind": "債務月報", "text": "財政部 MSPD（流通在外公債明細）"})
    ev.sort(key=lambda e: e["date"])
    return ev
