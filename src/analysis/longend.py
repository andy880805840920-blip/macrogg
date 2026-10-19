"""
長端利率的組成與供給、拍賣（2026-10 改版；2026-10 v4 改用 TIPS＋BEI 與 ACM 期限溢酬拆解）。

拆解（2026-10 v4，依 Fisher／Hicks 的推導）
--------------------------------------------
    名目殖利率 ＝ 預期利率路徑 ＋ 期限溢酬
              ＝（預期實質利率路徑 ＋ 預期平均通膨）＋（實質期限溢酬 ＋ 通膨風險溢酬）
    市場上看得到的兩個價格剛好把四項重新分組：
      TIPS 實質殖利率（DFII10）＝ 預期實質利率路徑 ＋ 實質期限溢酬
      損益兩平通膨率（BEI＝DGS10 − DFII10）＝ 預期平均通膨 ＋ 通膨風險溢酬
    所以 名目 ＝ TIPS ＋ BEI（逐日恆等，沒有殘差）；期限溢酬由模型估計
    （NY Fed ACM 為主，舊金山聯儲、Kim-Wright 對照），跟 TIPS／BEI 重疊、不相加。

所有判定都只做「哪一段動得最多」這種事實比較，不做加權總分。
"""

from __future__ import annotations

import datetime as dt
import re

# 10 年期名目殖利率的拆解（2026-10 v4）：
#   名目 ＝ TIPS 實質殖利率 ＋ 損益兩平通膨率（BEI＝名目 − TIPS），兩項相加恰好等於名目
#   期限溢酬（NY Fed ACM）跟上面兩項重疊：TIPS 含實質期限溢酬、BEI 含通膨風險溢酬，
#   所以它單獨並列，不跟另外兩項相加。
# key 沿用 real／infl／tp（其他區塊與燈號分組用這三個 key）。
COMP = [  # key, 中文, 灰字（白話定位）, 白話說明
    ("real", "實質利率", "政策預期", "市場對 Fed 未來政策路徑的預估"),
    ("infl", "損益兩平通膨率", "通膨預期；長期", "長期通膨水準的錨定，也是市場對 Fed 獨立性的信心"),
    ("tp", "期限溢酬", "因為不確定性所要求的額外補償", "來自政策與通膨預期，是市場自行收緊金融條件的機制"),
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


def _clean(rows) -> list[dict]:
    return [r for r in rows or [] if r.get("value") is not None]


def driver_series(series: dict, tp: dict | None) -> dict:
    """
    日資料（%）：y10／y20／y30（名目）、real（TIPS，DFII10）、infl（BEI＝DGS10 − DFII10，
    同一天兩者都有才算）、tp（ACM）、tp_sf（舊金山聯儲）、tp_kw（Kim-Wright）、
    path（預期利率路徑＝名目 − ACM 期限溢酬）。
    """
    y10 = _clean(series.get("DGS10"))
    tips = {r["date"]: r["value"] for r in _clean(series.get("DFII10"))}
    acm = _clean((tp or {}).get("acm"))
    acm_m = {r["date"]: r["value"] for r in acm}
    return {
        "y10": y10, "y20": _clean(series.get("DGS20")), "y30": _clean(series.get("DGS30")),
        "real": [{"date": d, "value": v} for d, v in sorted(tips.items())],
        "infl": [{"date": r["date"], "value": r["value"] - tips[r["date"]]} for r in y10 if r["date"] in tips],
        "tp": acm, "tp_sf": _clean((tp or {}).get("sf")), "tp_kw": _clean(series.get("THREEFYTP10")),
        "path": [{"date": r["date"], "value": r["value"] - acm_m[r["date"]]} for r in y10 if r["date"] in acm_m],
    }


def _before(rows: list[dict], iso: str):
    """iso 之前（不含）最後一筆。"""
    best = None
    for r in rows:
        if r["date"] < iso:
            best = r
        else:
            break
    return best


def _shift_m(iso: str, k: int) -> str:
    y, m = int(iso[:4]), int(iso[5:7]) - k
    while m <= 0:
        y, m = y - 1, m + 12
    import calendar
    return f"{y}-{m:02d}-{min(int(iso[8:10]), calendar.monthrange(y, m)[1]):02d}"


def level_changes(rows: list[dict]) -> dict:
    """最新值與 DTD／MTD／YTD 變化（bp）。MTD 基期＝上月最後一筆；YTD 基期＝去年最後一筆。"""
    rows = _clean(rows)
    if not rows:
        return {}
    last = rows[-1]
    d = last["date"]
    out = {"value": last["value"], "date": d}
    for tag, base in (("dtd", rows[-2] if len(rows) > 1 else None),
                      ("mtd", _before(rows, d[:8] + "01")),
                      ("ytd", _before(rows, d[:4] + "-01-01"))):
        out[tag] = (last["value"] - base["value"]) * 100 if base else None
        out[tag + "_from"] = base["date"] if base else ""
    y1 = _before(rows, (dt.date.fromisoformat(d) - dt.timedelta(days=364)).isoformat())
    out["y1"] = y1["value"] if y1 else None
    return out


def pick_main(parts: dict, nominal: float | None) -> str | None:
    """
    驅動因素：跟名目同方向、變動絕對值最大的那一項（名目幾乎沒動時三項都算）。
    期限溢酬跟另外兩項重疊，但它若是最大的同向變動，代表這個月主要是「補償」在變。
    """
    cand = {k: v for k, v in parts.items() if v is not None}
    if not cand:
        return None
    if nominal is not None and abs(nominal) >= 1:
        same = {k: v for k, v in cand.items() if v * nominal > 0}
        cand = same or cand
    return max(cand, key=lambda k: abs(cand[k]))


def contribution_window(ds: dict, mode) -> dict | None:
    """
    一段期間的變動（bp）：mode＝"mtd"、"ytd" 或整數月數（滾動 k 個月）。
    回傳沿用舊結構：parts{real, infl, tp}、nominal、start／end（10Y 水準）、main、path。
    """
    y10 = ds.get("y10") or []
    if not y10:
        return None
    # 終點取名目與 TIPS 都有資料的最後一天（TIPS 晚一天公布），名目 ＝ TIPS ＋ BEI 才會恆等
    common = (ds.get("infl") or [{}])[-1].get("date") or y10[-1]["date"]
    y10 = [r for r in y10 if r["date"] <= common]
    end = y10[-1]
    if mode == "mtd":
        start_iso = end["date"][:8] + "01"
    elif mode == "ytd":
        start_iso = end["date"][:4] + "-01-01"
    else:
        start_iso = _shift_m(end["date"], int(mode))
        nxt = [r for r in y10 if r["date"] > start_iso]
        start_iso = nxt[0]["date"] if nxt else start_iso
    b = _before(y10, start_iso)
    if not b:
        return None

    def chg(key):
        rows = ds.get(key) or []
        if key in ("real", "infl", "path"):
            rows = [r for r in rows if r["date"] <= common]
        e = rows[-1] if rows else None
        s = _before(rows, start_iso)
        return (e["value"] - s["value"]) * 100 if e and s else None
    parts = {"real": chg("real"), "infl": chg("infl"), "tp": chg("tp")}
    # 模型口徑（預期利率路徑＋期限溢酬）的起訖 10Y：ACM 有資料的那兩天
    pr, tr_ = ds.get("path") or [], ds.get("tp") or []
    ps, ts_ = _before(pr, start_iso), _before(tr_, start_iso)
    m_start = (ps["value"] + ts_["value"]) if ps and ts_ and ps["date"] == ts_["date"] else None
    m_end = (pr[-1]["value"] + tr_[-1]["value"]) if pr and tr_ and pr[-1]["date"] == tr_[-1]["date"] else None
    nominal = (end["value"] - b["value"]) * 100
    main = pick_main(parts, nominal)
    return {"k": mode, "from": b["date"], "to": end["date"], "parts": parts, "resid": 0.0,
            "nominal": nominal, "start": b["value"], "end": end["value"], "main": main,
            "main_bp": parts.get(main) if main else None, "path": chg("path"),
            "m_start": m_start, "m_end": m_end,
            "tp_from": (_before(ds.get("tp") or [], start_iso) or {}).get("date", ""),
            "tp_to": ((ds.get("tp") or [{}])[-1]).get("date", "")}


def ytd_paths(ds: dict, keys=("y10", "real", "infl", "tp", "path")) -> dict:
    """年初至今的逐日累積變化（bp），基期＝去年最後一筆；{key: [{date, value}]}。"""
    y10 = ds.get("y10") or []
    if not y10:
        return {}
    start = y10[-1]["date"][:4] + "-01-01"
    out = {}
    for k in keys:
        rows = ds.get(k) or []
        base = _before(rows, start)
        if base:
            out[k] = [{"date": r["date"], "value": (r["value"] - base["value"]) * 100}
                      for r in rows if r["date"] >= start]
    return out


def main_sentence(c: dict | None) -> str:
    if not c or not c.get("main"):
        return "資料不足，無法拆解"
    m = c["main"]
    return (f"{_md2(c['from'])}→{_md2(c['to'])} 10Y {c['nominal']:+.0f}bp，"
            f"驅動因素：{COMP_ZH[m]} {c['parts'][m]:+.0f}bp")


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


def _r6(v: float) -> float:
    import math
    return math.floor(v * 1e6 + 0.5) / 1e6


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
    # 先四捨五入到 1e-6 bp：5.60−4.75 這種兩位小數相減會出現 1.9999999，
    # 畫面顯示 +2bp 卻被判成「大致持平」（2026-10 修正，JS 同規則）
    ds = _r6(d_long - d_short)
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


def _drv_idx(cd: dict, i: int, back: int = 5):
    """拆解用的資料日：i 當天或往前最多 back 個交易日內，10 年期、損益兩平、
    實質利率**三者都有值**的最近一天。實質利率（DFII10）比殖利率晚一天公布，
    只看當天的話最新一天永遠是「資料不足」（2026-10 修正）。"""
    for j in range(i, max(-1, i - back - 1), -1):
        if all(j < len(cd.get(k) or []) and cd[k][j] is not None for k in ("y10", "be", "real")):
            return j
    return None


def _lag_idx(cd: dict, k: str, i: int, back: int = 5):
    """晚公布的序列（期限溢酬、油價）：i 當天或往前 back 個交易日內最近有值的索引。"""
    arr = cd.get(k) or []
    for j in range(i, max(-1, i - back - 1), -1):
        if j < len(arr) and arr[j] is not None:
            return j
    return None


def window_analysis(cd: dict, start: str, end: str) -> dict:
    """
    起訖兩天（各自對齊到當天或之前的交易日）之間：
      tenors   2／10／30 年 起點、終點、變動（bp）
      spreads  10-2、30-10、30-2 起點、終點、變動、型態
      drivers  10 年期拆解（用兩端各自最近「三項都有值」的日子）、期限溢酬、
               油價（晚公布：起訖退到同一天就視為沒有新資料，回 None）
      text     三句判讀（曲線／10 年期原因／短端定價）
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
    ja, jb = _drv_idx(cd, ia), _drv_idx(cd, ib)
    if ja is not None and jb is not None and ja < jb:
        be = (cd["be"][jb] - cd["be"][ja]) * 100
        real = (cd["real"][jb] - cd["real"][ja]) * 100
        d10 = (cd["y10"][jb] - cd["y10"][ja]) * 100
        drv_dates = [cd["d"][ja], cd["d"][jb]]
    else:
        be = real = d10 = None
        drv_dates = [None, None]

    def lagged(k):
        a, b = _lag_idx(cd, k, ia), _lag_idx(cd, k, ib)
        if a is None or b is None or a >= b:
            return None, None, None
        return cd[k][a], cd[k][b], [cd["d"][a], cd["d"][b]]
    ta, tb, tp_dates = lagged("tp")
    tp = None if ta is None else (tb - ta) * 100
    oa, ob, _ = lagged("oil")
    oil = (ob / oa - 1) * 100 if oa and ob else None
    a3, b3 = v("y3m", ia), v("y3m", ib)
    y3m = None if a3 is None or b3 is None else (b3 - a3) * 100
    result = {"start": da, "end": db, "tenors": ten, "spreads": sp,
              "drivers": {"be": be, "real": real, "d10": d10, "dates": drv_dates,
                          "tp": tp, "tp_dates": tp_dates or [None, None],
                          "oil": oil, "y3m": y3m}}
    view = window_view(result)
    result["text"] = [view["headline"], view["panels"][0]["verdict"], view["panels"][1]["verdict"]]
    return result


def curve_headline(S: dict) -> str:
    """一句話的曲線判讀：以 30−2 為主，附上兩段（10−2、30−10）。Python／JS 同規則。"""
    x, a, b = S.get("30-2"), S.get("10-2"), S.get("30-10")
    if not x or not a or not b:
        return "資料不足，暫不判定曲線方向。"
    seg = f"10−2 {_sgn(a['d'], '')}、30−10 {_sgn(b['d'], '')}"
    if abs(_r6(x["d"])) < FLAT_BP:
        if abs(_r6(a["d"])) >= FLAT_BP and abs(_r6(b["d"])) >= FLAT_BP and a["d"] * b["d"] < 0:
            return f"30−2 大致持平（{_sgn(x['d'])}）：{seg}，兩段互相抵銷。"
        return f"曲線大致持平：30−2 {_sgn(x['d'])}；{seg}。"
    lead = f"（{x['lead']}）" if x["lead"] else ""
    move = "擴大" if x["d"] > 0 else "收窄"
    return f"曲線{x['zh']}{lead}：30−2 {move} {_num(abs(x['d']))}bp；{seg}。"


def window_view(r: dict) -> dict:
    """讀者可直接掃讀的結論與兩段說明；與瀏覽器端採相同規則。"""
    T = {t["k"]: t for t in r["tenors"]}
    S = {x["key"]: x for x in r["spreads"]}
    D = r["drivers"]
    headline = curve_headline(S)
    panels = []
    be, real, dy = D.get("be"), D.get("real"), D.get("d10")
    aligned = None not in (be, real, dy) and abs(dy-be-real) <= 2
    if aligned and max(abs(dy), abs(be), abs(real)) < 0.5:
        verdict = "10 年期與拆解指標大致持平。"
    elif aligned and abs(dy) < 0.5:
        verdict = "損益兩平與實質利率的變動大致抵銷，10 年期接近持平。"
    elif aligned:
        verdict = "10 年期主要由" + ("損益兩平" if abs(be) > abs(real) else "實質利率") + "變動帶動。"
    elif None in (be, real, dy):
        verdict = "所選期間的拆解資料不足，暫不判定主要原因。"
    else:
        verdict = "參考指標與 10 年期變動尚未吻合，暫不判定主要原因。"
    metric = lambda label, v, unit="bp", note="所選期間變動": {
        "label": label, "value": "—" if v is None else _sgn(v, unit), "note": note}
    dd = D.get("dates") or [None, None]
    dnote = f"拆解資料 {_md2(dd[0])} → {_md2(dd[1])}" if dd[0] and dd[1] else "拆解資料不足"
    lm = [metric("10 年期", dy, note=dnote), metric("損益兩平", be, note=dnote),
          metric("實質利率", real, note=dnote)]
    td = D.get("tp_dates") or [None, None]
    lm.append(metric("期限溢酬（參考）", D.get("tp"),
                     note=(f"資料日 {_md2(td[0])} → {_md2(td[1])}" if D.get("tp") is not None
                           else "所選期間尚無新資料（約晚一週公布）")))
    if D.get("oil") is not None:
        lm.append(metric("油價（參考）", D["oil"], "%"))
    panels.append({"title": "10 年期為什麼變", "verdict": verdict, "metrics": lm,
                   "note": "實質利率比殖利率晚一天公布，拆解改用兩端最近都有資料的日子；期限溢酬僅作參考，不加到損益兩平與實質利率之上。"})
    dy2, y3m = T["y2"]["d"], D.get("y3m")
    path = None if dy2 is None or y3m is None else dy2-y3m
    verdict = short_end_verdict(dy2, y3m)
    panels.append({"title": "短端定價怎麼變", "verdict": verdict,
                   "metrics": [metric("2 年期", dy2), metric("3 個月期", y3m), metric("2 年 − 3 個月利差", path)],
                   "note": "這是公債短端的相對變化；年底政策利率方向另看下方期貨定價。"})
    return {"headline": headline, "panels": panels}


# ---------------------------------------------------------------------------
# 30−2 週報（2026-10 第十七批）：最上方固定段落，滾動一週（最新收盤比 5 個
# 交易日前），2Y／10Y／30Y 與三條利差，加上市場隱含的 1 年後、5 年後。
# ---------------------------------------------------------------------------
BRIEF_TENORS = (("2", "DGS2"), ("10", "DGS10"), ("30", "DGS30"))
BRIEF_SPREADS = (("10-2", "10", "2"), ("30-10", "30", "10"), ("30-2", "30", "2"))
_RG_PHRASE = {"bear_steep": "長端升幅大於短端", "bull_steep": "短端降幅大於長端",
              "bear_flat": "短端升幅大於長端", "bull_flat": "長端降幅大於短端",
              "twist_steep": "短端降、長端升", "twist_flat": "短端升、長端降"}


def _fwd_set(y: dict) -> dict | None:
    """一天的曲線 → 1 年後、5 年後的 2Y／10Y／30Y（%）。缺天期回 None。
      1 年後：2Y＝1y2y（1Y、3Y）；10Y≈1y9y（1Y、10Y）；30Y≈1y29y（1Y、30Y）
      5 年後：2Y＝5y2y（5Y、7Y）；10Y＝5y10y（5Y、15Y，15Y 由 10Y／20Y 內插）；
              30Y≈5y25y（5Y、30Y）
    3Y 沒有資料時由 2Y／5Y 內插（標記 interp3）。"""
    need = ("1", "2", "5", "7", "10", "20", "30")
    if any(y.get(k) is None for k in need):
        return None
    y3 = y.get("3")
    interp3 = y3 is None
    if interp3:
        y3 = y["2"] + (y["5"] - y["2"]) / 3
    y15 = (y["10"] + y["20"]) / 2
    return {"1": {"2": _fwd(y["1"], 1, y3, 3), "10": _fwd(y["1"], 1, y["10"], 10),
                  "30": _fwd(y["1"], 1, y["30"], 30)},
            "5": {"2": _fwd(y["5"], 5, y["7"], 7), "10": _fwd(y["5"], 5, y15, 15),
                  "30": _fwd(y["5"], 5, y["30"], 30)},
            "interp3": interp3}


def curve_brief(series: dict, n: int = 5) -> dict | None:
    """最上方的 30−2 週報資料＋文字。最新共同資料日比 n 個交易日前。"""
    ids = {"1": "DGS1", "2": "DGS2", "3": "DGS3", "5": "DGS5", "7": "DGS7",
           "10": "DGS10", "20": "DGS20", "30": "DGS30"}
    m = {k: {r["date"][:10]: r["value"] for r in series.get(sid) or []
             if r.get("value") is not None and not r.get("live")} for k, sid in ids.items()}
    axis = sorted(set(m["2"]) & set(m["10"]) & set(m["30"]))
    if len(axis) <= n:
        return None
    d1, d0 = axis[-1], axis[-1 - n]
    lv = {}
    for k, _ in BRIEF_TENORS:
        a, b = m[k][d0], m[k][d1]
        lv[k] = {"a": a, "b": b, "d": (b - a) * 100}
    sp = {}
    for key, lk, sk in BRIEF_SPREADS:
        a = (lv[lk]["a"] - lv[sk]["a"]) * 100
        b = (lv[lk]["b"] - lv[sk]["b"]) * 100
        g = regime(lv[lk]["d"], lv[sk]["d"])
        sp[key] = {"a": a, "b": b, "d": b - a, **g}
    curves = {d: {k: m[k].get(d) for k in ids} for d in (d0, d1)}
    f_now, f_prev = _fwd_set(curves[d1]), _fwd_set(curves[d0])
    fwd = {}
    if f_now:
        for h in ("1", "5"):
            lvls = f_now[h]
            spr = {key: (lvls[lk] - lvls[sk]) * 100 for key, lk, sk in BRIEF_SPREADS}
            prev = ({key: (f_prev[h][lk] - f_prev[h][sk]) * 100 for key, lk, sk in BRIEF_SPREADS}
                    if f_prev else None)
            fwd[h] = {"lv": lvls, "sp": spr, "prev_sp": prev,
                      "prev_lv": f_prev[h] if f_prev else None}
    out = {"from": d0, "to": d1, "lv": lv, "sp": sp, "fwd": fwd,
           "interp3": bool(f_now and f_now["interp3"])}
    # 年內區間（監控表「現在」欄的位置條）：今年 1/1 起的最低、最高
    year = d1[:4] + "-01-01"
    ytd_days = [d for d in axis if d >= year] or axis
    rng = {}
    for k, _ in BRIEF_TENORS:
        vals = [m[k][d] for d in ytd_days]
        rng[k] = {"lo": min(vals), "hi": max(vals)}
    for key, lk, sk in BRIEF_SPREADS:
        vals = [(m[lk][d] - m[sk][d]) * 100 for d in ytd_days]
        rng[key] = {"lo": min(vals), "hi": max(vals)}
    out["ytd"] = rng
    # 這一週每天的變動：找出最大的單日變動（天期或利差），給白話段落點名
    week = axis[-1 - n:]
    best = None
    for i in range(1, len(week)):
        p, c = week[i - 1], week[i]
        cands = [(f"{k} 年", (m[k][c] - m[k][p]) * 100) for k, _ in BRIEF_TENORS]
        cands += [(key.replace("-", "−"), ((m[lk][c] - m[sk][c]) - (m[lk][p] - m[sk][p])) * 100)
                  for key, lk, sk in BRIEF_SPREADS]
        for name, v in cands:
            if best is None or abs(v) > abs(best["d"]) + 1e-9:
                best = {"date": c, "name": name, "d": v}
    out["move"] = best
    # 遠期歷史（近 3 個月，給監控表的小走勢線）
    hist = {"1": {k: [] for k in ("2", "10", "30", "10-2", "30-10", "30-2")},
            "5": {k: [] for k in ("2", "10", "30", "10-2", "30-10", "30-2")}}
    for d in axis[-64:]:
        f = _fwd_set({k: m[k].get(d) for k in ids})
        if not f:
            continue
        for h in ("1", "5"):
            for k in ("2", "10", "30"):
                hist[h][k].append(round(f[h][k], 4))
            for key, lk, sk in BRIEF_SPREADS:
                hist[h][key].append(round((f[h][lk] - f[h][sk]) * 100, 2))
    out["fwd_hist"] = hist
    out["text"] = _brief_text(out)
    return out


def _verb(v: float) -> str:
    return "幾乎不動" if abs(_r6(v)) < 1 else (f"上升 {_num(abs(v))}bp" if v > 0 else f"下跌 {_num(abs(v))}bp")


def brief_prose(b: dict, events: list | None = None) -> str:
    """
    最上方的白話段落：2–3 句、只帶幾個關鍵數字（2026-10 使用者：「純文字加少數
    關鍵數字」）。逐項數字放在下方「數字明細」收合區（_brief_text）。
      ① 本週曲線怎麼動、哪一端帶動、30−2 現在多少
      ② 最大單日變動在哪天、當天有什麼事件（4bp 以上才講）
      ③ 市場定價：1 年後、5 年後的 30−2，以及比上週往哪邊修正
    """
    lv, sp, fwd = b["lv"], b["sp"], b["fwd"]
    x = sp["30-2"]
    d2, d10, d30 = lv["2"]["d"], lv["10"]["d"], lv["30"]["d"]
    now = _num(x["b"])
    if abs(_r6(x["d"])) < FLAT_BP:
        ds = [d2, d10, d30]
        if all(abs(_r6(v)) < FLAT_BP for v in ds):
            s1 = f"本週曲線幾乎沒動：2 年、10 年、30 年變動都在 2bp 以內，30−2 停在 {now}bp。"
        elif all(v > 0 for v in ds) or all(v < 0 for v in ds):
            lo, hi = min(abs(v) for v in ds), max(abs(v) for v in ds)
            rng = f"{_num(lo)}–{_num(hi)}" if _num(lo) != _num(hi) else _num(lo)
            s1 = (f"本週曲線大致平行{'上移' if d2 > 0 else '下移'}：2 年、10 年、30 年"
                  f"都{'上升' if d2 > 0 else '下跌'} {rng}bp，形狀幾乎不變，30−2 停在 {now}bp。")
        else:
            s1 = f"本週曲線形狀幾乎沒變：各天期漲跌互見，30−2 停在 {now}bp。"
        a, c = sp["10-2"]["d"], sp["30-10"]["d"]
        if abs(_r6(a)) >= FLAT_BP and abs(_r6(c)) >= FLAT_BP and a * c < 0:
            s1 = s1[:-1] + f"；不過中段與長段反向（10−2 {_sgn(a)}、30−10 {_sgn(c)}），互相抵銷。"
    else:
        size = "明顯" if abs(x["d"]) >= 8 else "小幅"
        shape = "變陡" if x["d"] > 0 else "變平"
        lead = f"，{x['lead']}" if x.get("lead") else ""
        s1 = (f"本週曲線{size}{shape}：30 年{_verb(d30)}、2 年{_verb(d2)}{lead}，"
              f"30−2 {'擴大' if x['d'] > 0 else '收窄'}到 {now}bp。")
    out = [s1]
    mv = b.get("move")
    if mv and abs(mv["d"]) >= 4:
        names = [zh for d, zh in (events or []) if d == mv["date"]]
        ev = f"，當天有{'、'.join(dict.fromkeys(names))}" if names else ""
        out.append(f"主要變化集中在 {_md2(mv['date'])}：{mv['name']}單日"
                   f"{'上升' if mv['d'] > 0 else '下跌'} {_num(abs(mv['d']))}bp{ev}。")
    if fwd.get("1") and fwd.get("5"):
        f1, f5 = fwd["1"]["sp"]["30-2"], fwd["5"]["sp"]["30-2"]
        g1, g5 = f1 - x["b"], f5 - x["b"]
        c1 = "up" if g1 > 5 else "dn" if g1 < -5 else "eq"
        c5 = "up" if g5 > 5 else "dn" if g5 < -5 else "eq"
        view = {("dn", "dn"): "市場仍押注曲線未來回平",
                ("up", "up"): "市場押注曲線未來續陡",
                ("up", "dn"): "市場押注一年內續陡、長期回平",
                ("dn", "up"): "市場押注一年內回平、長期再陡",
                ("eq", "dn"): "市場押注一年內大致維持、長期回平",
                ("eq", "up"): "市場押注一年內大致維持、長期更陡",
                ("dn", "eq"): "市場押注一年內回平、之後大致維持",
                ("up", "eq"): "市場押注一年內續陡、之後大致維持",
                ("eq", "eq"): "市場預期曲線大致維持現在的陡度"}[(c1, c5)]
        s3 = (f"市場定價方面，遠期顯示 30−2 一年後約 {_num(f1)}bp、五年後約 {_num(f5)}bp，{view}")
        pv = fwd["1"].get("prev_sp")
        if pv:
            r = f1 - pv["30-2"]
            s3 += ("；比上週往變陡修正了 " + _num(abs(r)) + "bp" if r > 2 else
                   "；比上週往變平修正了 " + _num(abs(r)) + "bp" if r < -2 else "，與上週相近")
        out.append(s3 + "。")
    return "".join(out)


def _brief_text(b: dict) -> list[str]:
    lv, sp, fwd = b["lv"], b["sp"], b["fwd"]
    x = sp["30-2"]
    move = ("大致持平" if abs(_r6(x["d"])) < FLAT_BP else
            f"擴大 {_num(abs(x['d']))}bp" if x["d"] > 0 else f"收窄 {_num(abs(x['d']))}bp")
    s1 = f"30−2 利差 {_num(x['a'])} → {_num(x['b'])}bp（{move}）"
    tenors = f"2Y {_sgn(lv['2']['d'])}、10Y {_sgn(lv['10']['d'])}、30Y {_sgn(lv['30']['d'])}"
    if x["code"] == "flat":
        d2, d30 = lv["2"]["d"], lv["30"]["d"]
        if abs(_r6(d2)) < FLAT_BP and abs(_r6(d30)) < FLAT_BP:
            how = "各天期變動都不大"
        else:
            how = "兩端同步" + ("上行" if d2 + d30 > 0 else "下行") + "（大致平行）"
    else:
        lead = f"，{x['lead']}" if x["lead"] and not x["code"].startswith("twist") else ""
        how = f"{x['zh']}：{_RG_PHRASE.get(x['code'], '')}{lead}"
    s2 = f"{tenors}；{how}。"
    a, c = sp["10-2"]["d"], sp["30-10"]["d"]
    seg = f"分段：10−2 {_sgn(a)}、30−10 {_sgn(c)}"
    if abs(_r6(x["d"])) < FLAT_BP:
        s3 = seg + ("，兩段互相抵銷。" if abs(_r6(a)) >= FLAT_BP and abs(_r6(c)) >= FLAT_BP and a * c < 0
                    else "，兩段都沒什麼動。")
    else:
        same = [(abs(a), "2→10 年段") if a * x["d"] > 0 else None,
                (abs(c), "10→30 年段") if c * x["d"] > 0 else None]
        same = [s for s in same if s]
        s3 = seg + (f"，主要來自 {max(same)[1]}。" if same else "。")
    out = [s1, s2, s3]
    if fwd.get("1") and fwd.get("5"):
        def part(h, zh):
            f = fwd[h]["sp"]["30-2"]
            g = f - x["b"]
            pv = fwd[h]["prev_sp"]
            wk = f"，較上週 {_sgn(f - pv['30-2'])}" if pv else ""
            return f"{zh} 30−2 約 {_num(f)}bp（比現在 {_sgn(g)}{wk}）"
        out.append("市場隱含：" + part("1", "1 年後") + "；" + part("5", "5 年後") + "。")
        g1 = fwd["1"]["sp"]["30-2"] - x["b"]
        g5 = fwd["5"]["sp"]["30-2"] - x["b"]
        p1 = "未來一年續陡" if g1 > 5 else "未來一年回平" if g1 < -5 else "未來一年大致維持"
        p5 = "五年後更陡" if g5 > 5 else "五年後更平" if g5 < -5 else "五年後與現在接近"
        pv = fwd["1"]["prev_sp"]
        if pv:
            r = fwd["1"]["sp"]["30-2"] - pv["30-2"]
            rev = ("較上週往更陡修正" if r > 2 else "較上週往更平修正" if r < -2 else "與上週相近")
            out.append(f"定價偏向{p1}、{p5}；{rev}。")
        else:
            out.append(f"定價偏向{p1}、{p5}。")
    return out


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
    from .. import fmt as _f
    return "—" if v is None else f"{_f.signed(v)}bp".replace("-", "−")



def short_end_verdict(dy2, y3m) -> str:
    """
    短端定價：看 2 年 − 3 個月利差怎麼變，並點出是哪一端在動（瀏覽器端 shortEndVerdict 同一套規則）。
    3 個月期反映未來一季的政策利率、2 年期反映未來兩年；只看利差會把「近端升息定價增加」
    誤讀成「未來利率偏低」。
    """
    if dy2 is None or y3m is None:
        return "資料不足，暫不判定短端定價方向。"
    path = dy2 - y3m
    if abs(path) <= 5:
        return "2 年期與 3 個月期同步變動，短端定價方向大致未變。"
    if path < 0:
        if y3m > 5 and dy2 > -5:
            return "3 個月期上升、2 年期沒跟上：近期升息的定價增加，但市場不認為利率會一路走高。"
        return "2 年期下跌多於 3 個月期：未來兩年的利率定價下修。"
    if y3m < -5 and dy2 < 5:
        return "3 個月期下跌、2 年期沒跟著降：近期降息的定價增加，但之後的利率定價沒有一起下修。"
    return "2 年期上升多於 3 個月期：未來兩年的利率定價上修。"

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


# ---------------------------------------------------------------------------
# 財政部買回（Buybacks）
# ---------------------------------------------------------------------------
BB_TYPE_ZH = {"Liquidity Support": "流動性支援", "Cash Management": "現金管理"}


def bucket_zh(b: str) -> str:
    """'Nominal Coupons 10Y to 20Y'／'10Y to 20Y' → '10–20 年'；TIPS 加前綴。"""
    tips = "TIPS" in b
    core = b.replace("Nominal Coupons", "").replace("TIPS", "").strip()
    m = re.match(r"(\d+)(Mo|Y) to (\d+)Y", core)
    if not m:
        return b
    lo = f'{m.group(1)} 個月' if m.group(2) == "Mo" else m.group(1)
    txt = f"{lo}–{m.group(3)} 年"
    return ("TIPS " if tips else "") + txt


def buyback_view(ops: list[dict], schedule: dict, reactions: dict, today: dt.date,
                 n: int = 24) -> dict:
    """
    買回區塊要用的資料：
      rows      近 n 場（新到舊）：上限、實際買回、投標、投標倍數（投標 ÷ 上限）、
                上限公布後與結果後 1 小時的 10／20／30 年殖利率變化
      latest    最新一場
      caps      各天期目前的每場上限（取該天期最近一場實際操作；比暫定排程準，
                因為排程公布後財政部可能另行調整，例如 2026-08-19 加倍長端上限）
      upcoming  暫定排程裡還沒到的場次（上限若低於該天期最近實際上限，一併列出）
      quarter   本次再融資季（排程起日之後）累計買回，依類型
    """
    if not ops:
        return {}
    iso = today.isoformat()
    done = sorted((o for o in ops if o.get("accepted") is not None and o["date"] <= iso),
                  key=lambda o: o["date"])
    rows = []
    for o in done[-n:][::-1]:
        rx = reactions.get(o["date"]) or {}
        rows.append({**o, "bucket_zh": bucket_zh(f'{o["sec"]} {o["bucket"]}'),
                     "type_zh": BB_TYPE_ZH.get(o["type"], o["type"]),
                     "cover": (o["offered"] / o["max"]) if o.get("offered") and o.get("max") else None,
                     "announce_at": rx.get("announce_at"), "announce": rx.get("announce") or {},
                     "result": rx.get("result") or {}})
    caps: dict = {}
    for o in done:
        caps[(o["type"], o["sec"], o["bucket"])] = o
    cap_rows = sorted(({"bucket_zh": bucket_zh(f'{s} {b}'), "max": o["max"], "date": o["date"],
                        "type_zh": BB_TYPE_ZH.get(o["type"], o["type"]), "sec": s}
                       for (_, s, b), o in caps.items() if o["date"] >= (today - dt.timedelta(days=120)).isoformat()),
                      key=lambda r: (r["type_zh"] != "流動性支援", "TIPS" in r["bucket_zh"],
                                     float(re.match(r"[\d.]+", r["bucket_zh"].replace("TIPS ", "")).group())
                                     if re.match(r"[\d.]+", r["bucket_zh"].replace("TIPS ", "")) else 0))
    up = []
    for s in (schedule or {}).get("ops") or []:
        if s["date"] < iso:
            continue
        sec = "TIPS" if "TIPS" in s["bucket"] else "Nominal Coupons"
        b = s["bucket"].replace("Nominal Coupons", "").replace("TIPS", "").strip()
        recent = caps.get((s["type"], sec, b))
        up.append({**s, "bucket_zh": bucket_zh(s["bucket"]),
                   "type_zh": BB_TYPE_ZH.get(s["type"], s["type"]),
                   "recent_max": recent["max"] if recent and recent["max"] > s["max"] else None})
    q0 = (schedule or {}).get("ops", [{}])[0].get("date", "") if (schedule or {}).get("ops") else ""
    quarter = {}
    for o in done:
        if q0 and o["date"] >= q0:
            k = BB_TYPE_ZH.get(o["type"], o["type"])
            quarter[k] = quarter.get(k, 0.0) + (o["accepted"] or 0)
    return {"rows": rows, "latest": rows[0] if rows else None, "caps": cap_rows,
            "upcoming": up, "quarter": quarter, "quarter_from": q0,
            "schedule_name": (schedule or {}).get("name", ""), "schedule_url": (schedule or {}).get("url", "")}


# ---------------------------------------------------------------------------
# 期貨市場定價 vs 點陣圖（2026-10）：市場 Lead／Behind the Curve
# ---------------------------------------------------------------------------
# 歷史上市場與點陣圖顯著分歧的量級（約略值，取自當時的 SEP 與期貨定價）：
DOTS_GAP_HISTORY = [
    ("2015/12", "點陣圖 2016 年底 1.375%（升 4 碼），期貨只定價約 2 碼", "市場落後約 50bp", "2016 年實際只升 1 碼"),
    ("2022 年初", "點陣圖 2022 年底 0.9%（升 3 碼），期貨 2 月已定價約 6 碼", "市場領先約 75bp 以上", "2022 年實際升 17 碼（425bp）"),
    ("2023/12", "點陣圖 2024 年底 4.6%（降 3 碼），期貨定價降約 6 碼", "市場領先（往降息）約 75bp", "2024 年實際降 4 碼（100bp）"),
]
DOTS_GAP_RULE = ("差距＝期貨隱含利率 − 點陣圖中位數（同一個年底）。|差距| < 12.5bp（半碼）正常：兩者一致；"
                 "12.5～50bp 留意：差半碼到兩碼；> 50bp 警戒：差兩碼以上，跟 2015 年底、2022 年初、2023 年底"
                 "幾次顯著分歧的量級相當。")


def dots_gap(fc: dict | None, dots: dict | None, mvd: dict | None = None) -> dict | None:
    """
    期貨隱含利率對點陣圖年底中位數，每個兩者都有的年底一列；主判讀用最遠的那個年底。
      Lead the Curve：市場定價的動作比點陣圖大（同方向走得更遠）——市場走在 Fed 前面
      Behind the Curve：市場定價的動作比點陣圖小，或方向相反——市場不買單點陣圖的路徑
    """
    rows = []
    fc, dots = fc or {}, dots or {}
    r0, pts = fc.get("r0"), fc.get("points") or []
    if r0 is not None and pts:
        bym = {p["month"]: p for p in pts}
        for y in sorted(dots):
            # 年底＝當年最後一次 FOMC（12 月中）之後的利率：
            #   當年度優先用 mvd（與上方「年底政策利率」同一個數字）；
            #   之後的年度用隔年 1 月合約（全月都在 12 月會議之後），沒有才退回 12 月合約（含會議前的天數）
            if mvd and str(mvd.get("year")) == str(y) and mvd.get("market_end") is not None:
                p, partial = {"month": f"{y}-12", "rate": mvd["market_end"]}, False
            elif f"{int(y) + 1}-01" in bym:
                p, partial = bym[f"{int(y) + 1}-01"], False
            else:
                yp = [q for q in pts if q["month"][:4] == str(y)]
                if not yp:
                    continue
                p = bym.get(f"{y}-12") or yp[-1]
                partial = True
            fed, mkt = (dots[y] - r0) * 100, (p["rate"] - r0) * 100
            rows.append({"year": str(y), "month": p["month"], "market": p["rate"], "dots": dots[y],
                         "fed_bp": fed, "mkt_bp": mkt, "gap_bp": mkt - fed, "partial": partial})
    if not rows and mvd and mvd.get("market_end") is not None and mvd.get("dot_median") is not None:
        r0 = mvd.get("r0")
        fed = (mvd["dot_median"] - r0) * 100 if r0 is not None else 0.0
        mkt = (mvd["market_end"] - r0) * 100 if r0 is not None else mvd["gap_bp"]
        rows.append({"year": str(mvd.get("year")), "month": f'{mvd.get("year")}-12', "market": mvd["market_end"],
                     "dots": mvd["dot_median"], "fed_bp": fed, "mkt_bp": mkt, "gap_bp": mvd["gap_bp"],
                     "partial": False})
    if not rows:
        return None
    m = rows[-1]
    g, fed = m["gap_bp"], m["fed_bp"]
    status = "good" if abs(g) < 12.5 else ("critical" if abs(g) > 50 else "warning")
    if abs(g) < 12.5:
        stance, why = "一致", "期貨與點陣圖大致相同，市場跟 Fed 的路徑沒有分歧"
    else:
        if abs(fed) >= 12.5:
            lead = (g > 0) == (fed > 0)
            move = "升息" if fed > 0 else "降息"
            why = (f"點陣圖預期{move} {abs(fed) / 25:.1f} 碼，期貨定價{'更多' if lead else '較少'}（{m['mkt_bp']:+.0f}bp）")
        else:
            lead = True
            why = f"點陣圖預期利率大致不動，期貨已定價{'升息' if g > 0 else '降息'} {abs(g) / 25:.1f} 碼"
        stance = "Lead the Curve（市場領先）" if lead else "Behind the Curve（市場落後）"
    return {"rows": rows, "main": m, "gap_bp": g, "status": status, "stance": stance, "why": why,
            "rule": DOTS_GAP_RULE, "history": DOTS_GAP_HISTORY}


# ---------------------------------------------------------------------------
# 再融資聲明的中文摘要（自動更新用）：常見句型對照；對不上就只放原文
# ---------------------------------------------------------------------------
_GUIDE_ZH = [
    (r"anticipates maintaining nominal coupon and FRN auction sizes for at least the next several quarters",
     "財政部預期至少未來數季維持名目 coupon 與 FRN 的拍賣規模不變。"),
    (r"anticipates maintaining nominal coupon and FRN auction sizes for at least the next (?:quarter|couple of quarters)",
     "財政部預期近一兩季維持名目 coupon 與 FRN 的拍賣規模不變——指引期間縮短，留意之後增發。"),
    (r"(?:anticipates|expects|plans)[^.]*increas\w* (?:nominal )?coupon",
     "財政部表示將（或預期）增加名目 coupon 的拍賣規模——長端供給上升。"),
    (r"(?:anticipates|expects|plans)[^.]*(?:decreas|reduc)\w* (?:nominal )?coupon",
     "財政部表示將（或預期）減少名目 coupon 的拍賣規模。"),
]


def refunding_guidance_zh(en: str) -> str:
    import re as _re
    for pat, zh in _GUIDE_ZH:
        if _re.search(pat, en or "", _re.I):
            return zh
    return ""


def refunding_buybacks_zh(liq: float | None, cash: float | None) -> str:
    if liq is None:
        return ""
    s = f"本季最多買回 {liq * 10:,.0f} 億美元的舊券（流動性支援）"
    if cash is not None:
        s += f"，以及最多 {cash * 10:,.0f} 億美元的 1 個月至 2 年期（現金管理）"
    return s + "。"
