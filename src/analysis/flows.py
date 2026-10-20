"""
長端頁「市場籌碼」（2026-10）：公債期貨各類參與者的 DV01 曝險（CFTC TFF）、初級交易商現券庫存（紐約聯儲）。

DV01（每變動 1bp 的損益，百萬美元）＝淨口數 × 每口 DV01。每口 DV01 用「最便宜交割券」的近似：
  以該週對應天期的殖利率當票面利率、CTD 近似剩餘年限算平價債券的 DV01，再除以轉換因子
  （同一張債以 6% 殖利率折現的價格）。是近似值，用來比較方向與相對大小，不是交易所公布的數字。
"""
from __future__ import annotations

import bisect
import datetime as dt

# code: (標籤, 對應殖利率序列, CTD 近似剩餘年限, 每口面額)
CONTRACTS = {"042601": ("2Y", "DGS2", 1.9, 200_000), "044601": ("5Y", "DGS5", 4.2, 100_000),
             "043602": ("10Y", "DGS7", 6.7, 100_000), "043607": ("Ultra 10Y", "DGS10", 9.6, 100_000),
             "020601": ("Bond", "DGS20", 17.0, 100_000), "020604": ("Ultra Bond", "DGS30", 25.0, 100_000)}
PARTIES = [("dlr", "交易商（Dealers）"), ("am", "資產管理（Asset Managers）"),
           ("lev", "槓桿基金（Lev Funds）"), ("oth", "其他（含未申報）")]
PD_BUCKETS = [("bills", "T-Bills"), ("lt3", "3 年以內"), ("g3l6", "3–6 年"), ("g6l7", "6–7 年"),
              ("g7l11", "7–11 年"), ("g11l21", "11–21 年"), ("g21", "21 年以上")]


def _pv(c: float, y: float, m: float) -> float:
    n, r = max(1, round(m * 2)), y / 2
    return sum(c / 2 / (1 + r) ** k for k in range(1, n + 1)) + 1 / (1 + r) ** n


def contract_dv01(y: float, m: float, notional: float) -> float:
    """每口期貨 DV01（美元）。y＝殖利率（小數）。"""
    dv = (_pv(y, y, m) - _pv(y, y + 0.0001, m)) * notional
    return dv / _pv(y, 0.06, m)


def _y_at(rows: list[dict], date: str) -> float | None:
    ds = [r["date"] for r in rows]
    i = bisect.bisect_right(ds, date) - 1
    return rows[i]["value"] / 100 if i >= 0 else (rows[0]["value"] / 100 if rows else None)


def futures_dv01(tff: list[dict], series: dict) -> dict:
    """{date: {code: {party: DV01 百萬美元}}}；oth 合併其他申報者與未申報者。"""
    out: dict = {}
    # 對應天期缺資料時，退回最近的天期（例如 7 年 → 10 年 → 5 年），不讓整區因一條序列消失
    near = {"DGS2": ("DGS2", "DGS1", "DGS3", "DGS5"), "DGS5": ("DGS5", "DGS7", "DGS3", "DGS10"),
            "DGS7": ("DGS7", "DGS10", "DGS5"), "DGS10": ("DGS10", "DGS7", "DGS20"),
            "DGS20": ("DGS20", "DGS30", "DGS10"), "DGS30": ("DGS30", "DGS20", "DGS10")}
    def _rows(sid):
        for k in near.get(sid, (sid,)):
            r = [x for x in (series.get(k) or []) if x.get("value") is not None]
            if r:
                return r
        return []
    ys = {k: _rows(v[1]) for k, v in CONTRACTS.items()}
    for r in tff:
        c = r["code"]
        if c not in CONTRACTS or not ys[c]:
            continue
        _, _, m, n = CONTRACTS[c]
        y = _y_at(ys[c], r["date"])
        if y is None:
            continue
        v = contract_dv01(y, m, n) / 1e6
        out.setdefault(r["date"], {})[c] = {"dlr": r["dlr"] * v, "am": r["am"] * v, "lev": r["lev"] * v,
                                             "oth": (r["oth"] + r["nr"]) * v, "per": v * 1e6}
    return {d: x for d, x in out.items() if len(x) == len(CONTRACTS)}


def _ago(dates: list[str], last: str, days: int) -> str | None:
    t = (dt.date.fromisoformat(last) - dt.timedelta(days=days)).isoformat()
    prev = [d for d in dates if d <= t]
    return prev[-1] if prev else None


def futures_view(tff: list[dict], series: dict) -> dict | None:
    by = futures_dv01(tff, series)
    if len(by) < 10:
        return None
    ds = sorted(by)
    last = ds[-1]
    w1, w4, y1 = ds[-2], ds[-5] if len(ds) > 4 else ds[0], _ago(ds, last, 364)
    tot = lambda d, p: sum(by[d][c][p] for c in CONTRACTS)
    matrix = []
    for p, zh in PARTIES:
        cells = [{"code": c, "label": CONTRACTS[c][0], "v": by[last][c][p],
                  "w1": by[last][c][p] - by[w1][c][p], "w4": by[last][c][p] - by[w4][c][p]} for c in CONTRACTS]
        cells.append({"code": "tot", "label": "合計", "v": tot(last, p), "w1": tot(last, p) - tot(w1, p),
                      "w4": tot(last, p) - tot(w4, p)})
        matrix.append({"key": p, "label": zh, "cells": cells})
    # 參考圖口徑：資產管理＝淨多 DV01、槓桿基金與交易商＝淨空 DV01（都以正值呈現）
    sign = {"am": 1, "lev": -1, "dlr": -1}
    chart = {p: [{"date": d, "value": sign[p] * tot(d, p)} for d in ds] for p in sign}
    head, chg, share, verdict = "", {}, {}, ""
    if y1:
        chg = {p: sign[p] * (tot(last, p) - tot(y1, p)) for p in sign}
        # 空方結構：交易商佔（交易商＋槓桿基金）淨空 DV01 的比重——對做資產管理多單的是誰
        def _sh(d):
            a, b = -tot(d, "dlr"), -tot(d, "lev")
            return a / (a + b) if a > 0 and b > 0 else None
        share = {"now": _sh(last), "ago": _sh(y1)}
        am, lev, dlr = chg["am"], chg["lev"], chg["dlr"]
        flow = f"資產管理淨多 {am:+.0f}、槓桿基金淨空 {lev:+.0f}、交易商淨空 {dlr:+.0f}（百萬美元／bp）"
        if share["now"] is not None and share["ago"] is not None:
            if share["now"] > share["ago"] + 0.03:
                verdict = "空方由槓桿基金轉向交易商"
                head = (f"空方由槓桿基金轉向交易商：交易商佔兩者淨空 DV01 的比重一年內由 "
                        f"{share['ago']:.0%} 升到 {share['now']:.0%}；{flow}")
            elif share["now"] < share["ago"] - 0.03:
                verdict = "空方回到槓桿基金"
                head = (f"空方回到槓桿基金：交易商佔兩者淨空 DV01 的比重一年內由 "
                        f"{share['ago']:.0%} 降到 {share['now']:.0%}；{flow}")
            else:
                verdict = "空方結構大致不變"
                head = f"空方結構大致不變（交易商佔兩者淨空 DV01 約 {share['now']:.0%}）；{flow}"
        else:
            head = f"近一年{flow}"
    return {"date": last, "w1": w1, "w4": w4, "y1": y1, "matrix": matrix, "chart": chart, "head": head,
            "chg_1y": chg, "share": share, "verdict": verdict, "per": {CONTRACTS[c][0]: by[last][c]["per"] for c in CONTRACTS}}


def dealer_inventory(pd: dict, auctions: list[dict] | None = None) -> dict | None:
    """初級交易商公債淨持倉（十億美元）：各期別、合計、水位分位、變化，加上 coupon 拍賣承接比例。"""
    if not pd or not pd.get("l2"):
        return None
    def _map(rows):
        return {r["date"]: r["value"] for r in rows or []}
    m = {k: _map(v) for k, v in pd.items()}
    ds = sorted(m["l2"])
    rows = []
    for d in ds:
        r = {"date": d, "bills": m.get("bills", {}).get(d), "lt3": (m["l2"].get(d) or 0) + (m.get("g2l3", {}).get(d) or 0)}
        for k in ("g3l6", "g6l7", "g7l11", "g11l21", "g21"):
            r[k] = m.get(k, {}).get(d)
        r["coupons"] = sum(r[k] for k in ("lt3", "g3l6", "g6l7", "g7l11", "g11l21", "g21") if r.get(k) is not None)
        rows.append(r)
    last = rows[-1]
    d3 = (dt.date.fromisoformat(last["date"]) - dt.timedelta(days=3 * 365)).isoformat()
    win = [r["coupons"] for r in rows if r["date"] >= d3]
    pct = sum(1 for v in win if v <= last["coupons"]) / len(win) if win else None
    def ago(days):
        t = (dt.date.fromisoformat(last["date"]) - dt.timedelta(days=days)).isoformat()
        p = [r for r in rows if r["date"] <= t]
        return p[-1] if p else None
    w4, y1 = ago(28), ago(364)
    buckets = [{"key": k, "label": zh, "v": last.get(k),
                "w4": None if not w4 or last.get(k) is None or w4.get(k) is None else last[k] - w4[k],
                "y1": None if not y1 or last.get(k) is None or y1.get(k) is None else last[k] - y1[k]}
               for k, zh in PD_BUCKETS]
    # 拍賣承接：近 3 個月 vs 一年前同期的初級交易商得標比例（競標得標量為分母）
    take = {}
    if auctions:
        t0 = dt.date.fromisoformat(last["date"])
        def avg(a, b):
            vs = [x["dealer_pct"] for x in auctions if x.get("dealer_pct") is not None
                  and (t0 - dt.timedelta(days=a)).isoformat() < x["date"] <= (t0 - dt.timedelta(days=b)).isoformat()]
            return (sum(vs) / len(vs), len(vs)) if vs else (None, 0)
        take = {"now": avg(91, -7), "ago": avg(91 + 364, 364)}
    up = (last["coupons"] - y1["coupons"]) if y1 else None
    tk_now, tk_ago = (take.get("now") or (None,))[0], (take.get("ago") or (None,))[0]
    if up is None:
        read = ""
    elif up > 0 and tk_now is not None and tk_ago is not None and tk_now > tk_ago + 2:
        read = "庫存上升、拍賣承接比例也升高——偏被動吸收（終端需求不足時由交易商接手）"
    elif up > 0:
        read = "庫存上升但拍賣承接比例沒有升高——偏主動持有：資產負債表空間放寬後，交易商願意持有更多現券"
    else:
        read = "coupon 庫存下降——交易商在去化中長天期現券，造市與承接新債的空間相對充裕"
    if read and y1 and last.get("bills") is not None and y1.get("bills") is not None:
        read += f"（一年內 coupon {up:+.0f}、T-Bills {last['bills'] - y1['bills']:+.0f} 十億美元）"
    return {"date": last["date"], "rows": rows, "last": last, "pct3y": pct, "w4": w4, "y1": y1,
            "buckets": buckets, "take": take, "read": read,
            "chg_1y": up, "chg_4w": (last["coupons"] - w4["coupons"]) if w4 else None}
