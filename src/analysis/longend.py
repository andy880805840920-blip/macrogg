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


def curve_snapshots(series: dict, year_start: bool = True) -> list[dict]:
    """
    曲線快照：現在、1 週前、1 個月前、年初（2026-10 使用者：要跟利差表的週／月變化對得起來）。
    回傳 [{label, date, points:[(tenor, years, value)]}]。
    """
    maps = {sid: {x["date"]: x for x in series.get(sid) or [] if x.get("value") is not None}
            for _, sid, _ in CURVE}
    common = sorted(set.intersection(*(set(m) for m in maps.values())))
    if not common:
        return []
    d0 = dt.date.fromisoformat(common[-1][:10])
    marks = [("現在", d0), ("1 週前", d0 - dt.timedelta(days=7)),
             ("1 個月前", d0 - dt.timedelta(days=30))]
    if year_start:
        marks.append(("年初", dt.date(d0.year - 1, 12, 31)))
    out = []
    for lab, dd in marks:
        dates = [day for day in common if day <= dd.isoformat()]
        if not dates:
            continue
        day = dates[-1]
        out.append({"label": lab, "date": day,
                    "points": [(ten, yrs, maps[sid][day]["value"]) for ten, sid, yrs in CURVE]})
    return out


# ---------------------------------------------------------------------------
# 利差：10-2、30-10、30-2 的水準、週變化、月變化與型態（2026-10）
# ---------------------------------------------------------------------------
SPREADS = [("10-2", "DGS10", "DGS2", "10 年", "2 年"),
           ("30-10", "DGS30", "DGS10", "30 年", "10 年"),
           ("30-2", "DGS30", "DGS2", "30 年", "2 年")]
WINDOWS = (("wow", 7, "週"), ("mom", 30, "月"))
FLAT_BP = 2.0          # 利差變動 2bp 以內＝大致持平


def regime(d_long: float | None, d_short: float | None) -> dict:
    """
    曲線型態（以 bp 計）：
      變陡（利差擴大）  長端漲得比短端多 → 熊陡（長端帶動）
                        短端跌得比長端多 → 牛陡（短端帶動）
                        長端漲、短端跌    → 扭轉變陡
      變平（利差收窄）  短端漲得比長端多 → 熊平（短端帶動）
                        長端跌得比短端多 → 牛平（長端帶動）
                        長端跌、短端漲    → 扭轉變平
    「熊」＝殖利率上升（債價跌），「牛」＝殖利率下降。
    """
    if d_long is None or d_short is None:
        return {"code": "na", "zh": "—", "lead": ""}
    ds = d_long - d_short
    if abs(ds) < FLAT_BP:
        return {"code": "flat", "zh": "大致持平", "lead": ""}
    if ds > 0:                                   # 變陡
        if d_long > 0 and d_short < 0:
            return {"code": "twist_steep", "zh": "扭轉變陡", "lead": "兩端反向"}
        if abs(d_long) >= abs(d_short):
            return ({"code": "bear_steep", "zh": "熊陡", "lead": "長端帶動"} if d_long > 0
                    else {"code": "bull_steep", "zh": "牛陡", "lead": "短端帶動"})
        return ({"code": "bull_steep", "zh": "牛陡", "lead": "短端帶動"} if d_short < 0
                else {"code": "bear_steep", "zh": "熊陡", "lead": "長端帶動"})
    if d_long < 0 and d_short > 0:
        return {"code": "twist_flat", "zh": "扭轉變平", "lead": "兩端反向"}
    if abs(d_short) >= abs(d_long):
        return ({"code": "bear_flat", "zh": "熊平", "lead": "短端帶動"} if d_short > 0
                else {"code": "bull_flat", "zh": "牛平", "lead": "長端帶動"})
    return ({"code": "bull_flat", "zh": "牛平", "lead": "長端帶動"} if d_long < 0
            else {"code": "bear_flat", "zh": "熊平", "lead": "短端帶動"})


def _chg(rows: list[dict], last: str, days: int):
    """last 那天的值 − days 天前（當天或之前最近一筆）的值。"""
    a = _at(rows, last)
    b = _at(rows, (dt.date.fromisoformat(last[:10]) - dt.timedelta(days=days)).isoformat())
    if not a or not b:
        return None
    return a["value"] - b["value"]


def spread_series(series: dict, long_id: str, short_id: str, since: str = "") -> list[dict]:
    A, B = series.get(long_id) or [], series.get(short_id) or []
    bm = {r["date"]: r["value"] for r in B if r.get("value") is not None}
    return [{"date": r["date"], "value": (r["value"] - bm[r["date"]]) * 100} for r in A
            if r.get("value") is not None and r["date"] in bm and r["date"] >= since]


def spread_rows(series: dict) -> list[dict]:
    """[{key, label, value, wow, mom, d_long/d_short per window, regime per window}]（bp）。"""
    out = []
    for key, lid, sid, lz, sz in SPREADS:
        sp = spread_series(series, lid, sid)
        if len(sp) < 25:
            continue
        last = sp[-1]["date"]
        row = {"key": key, "label": f"{lz} − {sz}", "value": sp[-1]["value"], "date": last,
               "long": lz, "short": sz}
        for w, days, _ in WINDOWS:
            common = {r["date"] for r in sp}
            dl = _chg([r for r in series.get(lid) or [] if r["date"] in common], last, days)
            ds_ = _chg([r for r in series.get(sid) or [] if r["date"] in common], last, days)
            row[w] = None if dl is None or ds_ is None else (dl - ds_) * 100
            row[w + "_long"] = None if dl is None else dl * 100
            row[w + "_short"] = None if ds_ is None else ds_ * 100
            row[w + "_regime"] = regime(row[w + "_long"], row[w + "_short"])
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# 誰在推曲線：長端拆通膨預期／實質利率（其中期限溢酬），短端看政策預期
# ---------------------------------------------------------------------------
def curve_drivers(series: dict) -> dict:
    """
    週、月兩個窗的變動（bp；油價為 %）：
      long：10 年 = 損益兩平（通膨預期）＋ TIPS 實質利率；期限溢酬是實質利率裡「財政與供給」的那一塊
      short：2 年、3 個月，以及 2 年 − 3 個月（市場對未來兩年升降息的定價）
    市場口徑（損益兩平、TIPS）是日資料，跟上方模型拆解（月均）不同，畫面上會講。
    """
    last = (series.get("DGS10") or [{}])[-1].get("date")
    if not last:
        return {}
    out = {"date": last}
    for w, days, _ in WINDOWS:
        g = {}
        for k, sid in (("y10", "DGS10"), ("be", "T10YIE"), ("real", "DFII10"),
                       ("tp", "THREEFYTP10"), ("y2", "DGS2"), ("y3m", "DGS3MO"), ("y30", "DGS30")):
            rows = series.get(sid) or []
            v = _chg(rows, last, days)
            if k in ("be", "real"):
                # These releases can lag Treasury. Require the same two nominal days.
                start = _at(series.get("DGS10") or [],
                            (dt.date.fromisoformat(last) - dt.timedelta(days=days)).isoformat())
                m = {r["date"]: r["value"] for r in rows if r.get("value") is not None}
                v = m[last] - m[start["date"]] if last in m and start and start["date"] in m else None
            g[k] = None if v is None else v * 100
        oil = series.get("DCOILWTICO") or []
        a = _at(oil, last)
        b = _at(oil, (dt.date.fromisoformat(last) - dt.timedelta(days=days)).isoformat())
        g["oil_pct"] = ((a["value"] / b["value"] - 1) * 100) if a and b and b["value"] else None
        g["oil"] = a["value"] if a else None
        g["path"] = (None if g["y2"] is None or g["y3m"] is None else g["y2"] - g["y3m"])
        out[w] = g
    return out


# ---------------------------------------------------------------------------
# 自選期間（2026-10）：頁面嵌入對齊好的日資料，瀏覽器端用**同一套規則**
# 重算（src/pages/longend.py 的 _CW_JS）。這裡是參考實作：伺服器端先算好
# 預設的「1 週」畫面，tests/test_curve_window.py 逐窗比對兩邊輸出一字不差。
# ---------------------------------------------------------------------------
CW_FIELDS = (("y3m", "DGS3MO"), ("y2", "DGS2"), ("y10", "DGS10"), ("y30", "DGS30"),
             ("be", "T10YIE"), ("real", "DFII10"), ("tp", "THREEFYTP10"), ("oil", "DCOILWTICO"))
CW_WINDOWS = (("1w", "1 週", 7), ("1m", "1 個月", 30), ("3m", "3 個月", 91), ("ytd", "年初至今", 0))


def curve_data(series: dict, since: str) -> dict:
    """以 10 年期的交易日為軸，各序列對齊（缺值為 None）。since 之後（含）。"""
    dates = [r["date"][:10] for r in series.get("DGS10") or []
             if r.get("value") is not None and r["date"][:10] >= since]
    out = {"d": dates}
    for k, sid in CW_FIELDS:
        m = {r["date"][:10]: r["value"] for r in series.get(sid) or [] if r.get("value") is not None}
        out[k] = [None if m.get(x) is None else round(m[x], 4) for x in dates]
    return out


def _cw_idx(cd: dict, date: str) -> int:
    """date 當天或之前最近的交易日索引（早於第一天時回 0）。"""
    i = 0
    for j, x in enumerate(cd["d"]):
        if x <= date:
            i = j
        else:
            break
    return i


def _cw_val(cd: dict, k: str, i: int):
    """主要指標只取當天；期限溢酬最多回看 5 個交易日，實際日期另存。"""
    arr = cd.get(k) or []
    # 利率與拆解指標只用選定資料日；期限溢酬晚公布，另標示實際日期。
    lookback = 6 if k == "tp" else 1
    for j in range(i, max(-1, i - lookback), -1):
        if j < len(arr) and arr[j] is not None:
            return arr[j]
    return None


def cw_start(cd: dict, key: str, end: str, year: int) -> str:
    """快捷鍵 → 起點日期（yyyy-mm-dd，尚未對齊交易日）。"""
    if key == "ytd":
        return f"{year - 1}-12-31"
    days = {k: n for k, _, n in CW_WINDOWS}[key]
    return (dt.date.fromisoformat(end) - dt.timedelta(days=days)).isoformat()


def _hu(v: float, nd: int = 0) -> float:
    """四捨五入（半數往上，跟 JS 的 Math.round 一致；Python 的 round 是銀行家捨入）。"""
    import math
    f = 10 ** nd
    return math.floor(v * f + 0.5 + 1e-10) / f


def _num(v: float, nd: int = 0) -> str:
    r = _hu(v, nd)
    return f"{0.0 if r == 0 else r:.{nd}f}".replace("-", "−")


def _sgn(v: float, unit: str = "bp", nd: int = 0) -> str:
    r = _hu(v, nd)
    if r == 0:
        return f"{0:.{nd}f}{unit}"
    return ("+" if r > 0 else "") + _num(v, nd) + unit


def _md2(iso: str) -> str:
    return f"{int(iso[5:7])}/{int(iso[8:10])}"


def window_analysis(cd: dict, start: str, end: str) -> dict:
    """
    起訖兩天（各自對齊到當天或之前的交易日）之間：
      tenors   2／10／30 年 起點、終點、變動（bp）
      spreads  10-2、30-10、30-2 起點、終點、變動、型態
      text     三句判讀（型態／長端原因／短端原因）
    """
    ia, ib = _cw_idx(cd, start), _cw_idx(cd, end)
    if ia >= ib:
        ia = max(0, ib - 1)
    da, db = cd["d"][ia], cd["d"][ib]
    v = lambda k, i: _cw_val(cd, k, i)
    ten = []
    for k, zh in (("y2", "2 年"), ("y10", "10 年"), ("y30", "30 年")):
        a, b = v(k, ia), v(k, ib)
        ten.append({"k": k, "zh": zh, "a": a, "b": b,
                    "d": None if a is None or b is None else (b - a) * 100})
    T = {t["k"]: t for t in ten}
    sp = []
    for key, lk, sk in (("10-2", "y10", "y2"), ("30-10", "y30", "y10"), ("30-2", "y30", "y2")):
        L, S = T[lk], T[sk]
        if None in (L["a"], L["b"], S["a"], S["b"]):
            continue
        a, b = (L["a"] - S["a"]) * 100, (L["b"] - S["b"]) * 100
        g = regime(L["d"], S["d"])
        sp.append({"key": key, "a": a, "b": b, "d": b - a,
                   "zh": g["zh"], "lead": g["lead"], "code": g["code"]})
    S = {x["key"]: x for x in sp}

    def dch(k):
        a, b = v(k, ia), v(k, ib)
        return None if a is None or b is None else (b - a) * 100
    be, real, tp, y3m = dch("be"), dch("real"), dch("tp"), dch("y3m")
    oa, ob = v("oil", ia), v("oil", ib)
    oil = (ob / oa - 1) * 100 if oa and ob else None
    def tp_date(i):
        arr = cd.get("tp") or []
        return next((cd["d"][j] for j in range(i, max(-1, i-6), -1)
                     if j < len(arr) and arr[j] is not None), None)
    result = {"start": da, "end": db, "tenors": ten, "spreads": sp,
              "drivers": {"be": be, "real": real, "tp": tp, "oil": oil, "y3m": y3m,
                          "tp_dates": [tp_date(ia), tp_date(ib)]}}
    view = window_view(result)
    result["text"] = [view["headline"], view["panels"][1]["verdict"], view["panels"][2]["verdict"]]
    return result


def window_view(r: dict) -> dict:
    """讀者可直接掃讀的結論與三段說明；與瀏覽器端採相同規則。"""
    T = {t["k"]: t for t in r["tenors"]}
    S = {x["key"]: x for x in r["spreads"]}
    D = r["drivers"]
    x = S.get("10-2")
    if not x:
        headline = "資料不足，暫不判定曲線方向。"
    elif abs(x["d"]) < 2:
        headline = "曲線大致持平：10 年與 2 年的利差變動很小。"
    else:
        headline = ("曲線變陡：10 年與 2 年的利差擴大。" if x["d"] > 0
                    else "曲線變平：10 年與 2 年的利差縮小。")
    metrics = [{"label": x["key"].replace("-", " 年 − ") + " 年",
                "value": f"{_num(x['a'])} → {_num(x['b'])} bp",
                "note": "變動 " + _sgn(x["d"])} for x in r["spreads"]]
    panels = [{"title": "利差怎麼變", "verdict": "長短利差擴大代表曲線變陡，縮小代表變平。",
               "metrics": metrics, "note": "比較的是所選期間的起點與終點。"}]
    be, real, dy = D.get("be"), D.get("real"), T["y10"]["d"]
    aligned = None not in (be, real, dy) and abs(dy-be-real) <= 2
    if aligned and max(abs(dy), abs(be), abs(real)) < 0.5:
        verdict = "10 年期與拆解指標大致持平。"
    elif aligned and abs(dy) < 0.5:
        verdict = "通膨補償與實質利率的變動大致抵銷，10 年期接近持平。"
    elif aligned:
        verdict = "10 年期主要由" + ("通膨補償" if abs(be) > abs(real) else "實質利率") + "變動帶動。"
    elif None in (be, real, dy):
        verdict = "所選日期的拆解資料不足，暫不判定主要原因。"
    else:
        verdict = "參考指標與 10 年期變動尚未吻合，暫不判定主要原因。"
    metric = lambda label, v, unit="bp": {"label": label, "value": "—" if v is None else _sgn(v, unit), "note": "所選期間變動"}
    lm = [metric("10 年期", dy), metric("通膨補償", be), metric("實質利率", real)]
    td = D.get("tp_dates") or [None, None]
    if D.get("tp") is not None:
        lm.append({"label": "期限溢酬（參考）", "value": _sgn(D["tp"]),
                   "note": f"資料日 {td[0]} → {td[1]}"})
    if D.get("oil") is not None:
        lm.append(metric("油價（參考）", D["oil"], "%"))
    panels.append({"title": "10 年期為什麼變", "verdict": verdict, "metrics": lm,
                   "note": "期限溢酬僅作參考，不再加到通膨補償與實質利率之上；損益兩平也含風險與流動性因素。"})
    dy2, y3m = T["y2"]["d"], D.get("y3m")
    path = None if dy2 is None or y3m is None else dy2-y3m
    verdict = ("資料不足，暫不判定短端定價方向。" if path is None else
               "2 年期相對短端走高，未來利率偏高的定價增強。" if path > 5 else
               "2 年期相對短端走低，未來利率偏低的定價增強。" if path < -5 else
               "2 年期與短端的相對變化不大，定價方向大致未變。")
    panels.append({"title": "短端定價怎麼變", "verdict": verdict,
                   "metrics": [metric("2 年期", dy2), metric("3 個月期", y3m), metric("2 年 − 3 個月利差", path)],
                   "note": "這是公債短端的相對變化；年底政策利率方向另看下方期貨定價。"})
    return {"headline": headline, "panels": panels}


def future_view(forwards: list[dict], market: dict | None) -> dict:
    """公債遠期與政策利率分開判讀；不把不同天期或不同未來區間連成單一路徑。"""
    valid = [x for x in forwards if x.get("gap_bp") is not None]
    up = sum(x["gap_bp"] > 5 for x in valid)
    dn = sum(x["gap_bp"] < -5 for x in valid)
    n = len(valid)
    if not n:
        headline = "公債遠期資料不足，暫不判定方向。"
    elif up == n:
        headline = f"已取得的 {n} 個遠期區間均高於目前同天期利率，公債未來定價偏高。"
    elif dn == n:
        headline = f"已取得的 {n} 個遠期區間均低於目前同天期利率，公債未來定價偏低。"
    elif not up and not dn:
        headline = "遠期與目前同天期利率接近，公債未來定價大致持平。"
    else:
        headline = f"不同區間方向分歧：{up} 個偏高、{dn} 個偏低，其餘接近目前同天期利率。"
    changes = [x["mom_bp"] for x in forwards if x.get("mom_bp") is not None]
    if not changes:
        recent = "近一個月比較資料不足，暫不判定定價變化。"
    elif all(v > 5 for v in changes):
        recent = f"有月比較資料的 {len(changes)} 個區間全部上修，近期定價整體往更高利率移動。"
    elif all(v < -5 for v in changes):
        recent = f"有月比較資料的 {len(changes)} 個區間全部下修，近期定價整體往更低利率移動。"
    elif all(abs(v) <= 5 for v in changes):
        recent = "近一個月定價變動不大。"
    else:
        recent = "近一個月各區間調整方向不一致，需分開看。"
    market = market or {}
    r0, end = market.get("r0"), market.get("market_end")
    policy = None
    if r0 is not None and end is not None:
        delta = (end-r0)*100
        direction = "偏升" if delta > 12.5 else "偏降" if delta < -12.5 else "大致持平"
        policy = {"title": f"年底政策利率定價{direction}", "now": f"{r0:.2f}%", "end": f"{end:.2f}%",
                  "change": _sgn(delta), "year": str(market.get("year") or ""),
                  "text": "這是期貨隱含的市場定價；可判讀年底方向，無法據此斷定每場會議的動作。"}
    return {"headline": headline, "recent": recent, "policy": policy}


def _fwd(y1: float, n1: float, y2: float, n2: float) -> float:
    """n1 年後、期間 n2−n1 年的遠期利率（年複利，%）。CMT 是平價殖利率，這裡是近似。"""
    a, b = (1 + y1 / 100) ** n1, (1 + y2 / 100) ** n2
    return ((b / a) ** (1 / (n2 - n1)) - 1) * 100


FORWARDS = [("1y1y", "1 年後的 1 年期", "DGS1", 1, "DGS2", 2, "DGS1"),
            ("2y3y", "2 年後的 3 年期", "DGS2", 2, "DGS5", 5, "DGS3*"),
            ("5y5y", "5 年後的 5 年期", "DGS5", 5, "DGS10", 10, "DGS5"),
            ("10y20y", "10 年後的 20 年期", "DGS10", 10, "DGS30", 30, "DGS20")]


def forwards(series: dict) -> list[dict]:
    """
    市場隱含的未來利率：用現在的曲線算遠期利率，跟「同天期現在的利率」比。
    遠期＞現在＝市場定價該天期利率會走高（或要求更多期限溢酬）；遠期＜現在＝定價會走低。
    另附 1 週前、1 個月前的遠期，看市場的預期往哪邊改。
    """
    ten = [r for r in series.get("DGS10") or [] if r.get("value") is not None]
    if not ten:
        return []
    last = ten[-1]["date"][:10]
    d0 = dt.date.fromisoformat(last)
    out = []
    for key, zh, s1, n1, s2, n2, spot in FORWARDS:
        needed = {s1, s2} | ({"DGS2", "DGS5"} if spot == "DGS3*" else {spot})
        maps = {sid: {r["date"][:10]: r["value"] for r in series.get(sid) or []
                      if r.get("value") is not None} for sid in needed}
        common = sorted(set.intersection(*(set(m) for m in maps.values())))
        vals, dates = {}, {}
        for tag, dd in (("now", d0), ("w", d0-dt.timedelta(days=7)), ("m", d0-dt.timedelta(days=30))):
            date = next((d for d in reversed(common) if d <= dd.isoformat()), None)
            if date is None or (dd-dt.date.fromisoformat(date)).days > 7:
                vals[tag], dates[tag] = None, None
            else:
                vals[tag] = _fwd(maps[s1][date], n1, maps[s2][date], n2)
                dates[tag] = date
        if vals["now"] is None:
            continue
        date = dates["now"]
        sp = (maps["DGS2"][date] + (maps["DGS5"][date]-maps["DGS2"][date])/3
              if spot == "DGS3*" else maps[spot][date])
        out.append({"key": key, "label": zh, "fwd": vals["now"], "spot": sp,
                    "date": date, "mom_date": dates["m"], "wow_date": dates["w"],
                    "gap_bp": (vals["now"]-sp)*100,
                    "wow_bp": None if vals["w"] is None else (vals["now"]-vals["w"])*100,
                    "mom_bp": None if vals["m"] is None else (vals["now"]-vals["m"])*100,
                    "spot_zh": {"DGS1": "1 年期", "DGS3*": "3 年期", "DGS5": "5 年期", "DGS20": "20 年期"}[spot]})
    return out


def _bp(v) -> str:
    return "—" if v is None else f"{v:+.0f}bp".replace("-", "−")


def curve_story(rows: list[dict], drv: dict, fwd: list[dict], *, fomc_next: str = "",
                refunding_next: str = "") -> dict:
    """
    規則寫成的判讀（不交給 AI）：
      head    一句話：本月曲線型態（以 10-2 為主）＋誰帶動
      long    長端原因：10 年變動拆成通膨預期與實質利率，期限溢酬、油價當旁證
      short   短端原因：2 年變動與 2 年−3 個月（政策預期）
      outlook 接下來的觀察條件（通膨／財政／政策各一條，依目前主因排序）
    """
    r = {x["key"]: x for x in rows}
    m = drv.get("mom") or {}
    head = ""
    if "10-2" in r:
        g = r["10-2"]["mom_regime"]
        x = r["10-2"]
        head = (f"近一個月 10-2 利差 {_bp(x['mom'])}，{g['zh']}"
                + (f"（{g['lead']}）" if g["lead"] else "")
                + f"：10 年 {_bp(x['mom_long'])}、2 年 {_bp(x['mom_short'])}")
        if "30-10" in r and r["30-10"]["mom_regime"]["code"] not in ("flat", "na"):
            head += f"；30-10 {r['30-10']['mom_regime']['zh']}"
        head += "。"
    long_txt = ""
    if m.get("y10") is not None and m.get("be") is not None and m.get("real") is not None:
        be, real, tp = m["be"], m["real"], m.get("tp")
        lead = "通膨預期" if abs(be) > abs(real) else "實質利率"
        long_txt = (f"10 年 {_bp(m['y10'])}：通膨預期（損益兩平）{_bp(be)}、實質利率 {_bp(real)}"
                    + (f"；期限溢酬（財政與供給）{_bp(tp)}" if tp is not None else "")
                    + (f"；油價 {m['oil_pct']:+.0f}%".replace("-", "−") if m.get("oil_pct") is not None else "")
                    + f"。主要是{lead}在推")
        if lead == "實質利率" and tp is not None and abs(tp) >= abs(real) * 0.5:
            long_txt += "，期限溢酬也在漲——財政與供給有份"
        elif lead == "通膨預期" and (m.get("oil_pct") or 0) > 5:
            long_txt += "，跟油價上漲同步"
        long_txt += "。"
    short_txt = ""
    if m.get("y2") is not None:
        p = m.get("path")
        short_txt = (f"2 年 {_bp(m['y2'])}"
                     + (f"，2 年 − 3 個月 {_bp(p)}" if p is not None else "")
                     + ("：市場把升息押得更多（或降息延後）" if (p or 0) > 5 else
                        "：市場提高降息預期" if (p or 0) < -5 else "：政策預期大致沒變")
                     + "。")
    # 接下來看什麼：依目前主因排序
    tp_hot = (m.get("tp") or 0) > 5
    be_hot = (m.get("be") or 0) > 5 or (m.get("oil_pct") or 0) > 8
    pol_hot = abs(m.get("path") or 0) > 5
    items = [
        (tp_hot, "財政", "期限溢酬若續升，長端領漲的熊陡會延續"
         + (f"；下一次季度再融資公告 {refunding_next}，看長債發行量" if refunding_next else "") + "。"),
        (be_hot, "通膨", "損益兩平與油價同步走高時，長端會被通膨預期往上拉；油價回落則反向。"),
        (pol_hot, "政策", "短端跟著升降息預期走"
         + (f"；下次 FOMC {fomc_next}" if fomc_next else "") + "，決議偏鷹時曲線傾向熊平。"),
    ]
    items.sort(key=lambda x: not x[0])
    # 遠期：一句話
    f = {x["key"]: x for x in fwd}
    fwd_txt = ""
    if "1y1y" in f and "5y5y" in f:
        a, b = f["1y1y"], f["5y5y"]
        fwd_txt = (f"市場定價：1 年後的 1 年期利率 {a['fwd']:.2f}%（比現在 {_bp(a['gap_bp'])}）、"
                   f"5 年後的 5 年期 {b['fwd']:.2f}%（比現在 {_bp(b['gap_bp'])}）。")
    return {"head": head, "long": long_txt, "short": short_txt, "fwd": fwd_txt,
            "outlook": [{"tag": t, "text": x, "hot": h} for h, t, x in items]}


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
