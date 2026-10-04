"""
失去工作者佔失業人口比重（FRED LNS13023622）——就業轉折的主訊號。

為什麼換掉 Sahm 法則
--------------------
Sahm（失業率三月均比一年低點高 0.50）在 2024 年 7 月觸發，之後沒有衰退。
失業率可以因為「勞動力增加」上升——新進者、重返者變多，分母變大，
那不是景氣轉壞。失去工作者比重直接量「失業的人裡，有多少是被裁、被
解雇、約滿沒續」——這一塊只有景氣轉壞時才會快速膨脹。

兩層訊號（2026-10 回測 1967–2026、7 次可獨立檢驗的衰退後定案）
---------------------------------------------------------------
  留意：3 個月變化的 z 值 ≥ 1.5
        3 個月變化＝三月均 − 三個月前的三月均（單月樣本小、雜訊大）；
        z 值對過去 60 個月的同一種變化算（不含當月）。
        回測：1990、2001、2007 在衰退前 5–9 個月就亮；代價是 54 年
        誤報 5 次（約十年一次，2015–17 的製造業裁員潮佔 3 次）。
  警戒：比重三月均較過去 12 個月最低點上升 ≥ 3.0 個百分點，連 2 個月
        回測：每次都在衰退起點前後 4 個月內亮，誤報 2 次（1992、2024-01）；
        Sahm 同期誤報 3 次（含 2024-07），且每次都在衰退開始後才亮。
        → 格位往弱推一格（scenario.classify_labor）。

z 值為什麼不拿來當警戒：門檻拉到 2 以上時，60 個月窗口會吸進前一次
衰退的大波動、標準差被撐大，真正轉折時 z 反而算不高——1973、2007
都要到衰退開始一年後才亮。早期預警用 z，確認用上升幅度，各取所長。

所有門檻都是對歷史回測選出的本站門檻，不是外部標準，畫面上會標明。
回測本身由 recession_table() 用同一條序列重算，每次執行都能重現。
"""
from __future__ import annotations

import statistics as st

SERIES_ID = "LNS13023622"

Z_WINDOW = 60          # z 值的比較窗口（月）
Z_WATCH = 1.5          # 留意
RISE_ALERT = 3.0       # 警戒：較一年低點上升（個百分點）
RISE_PERSIST = 2       # 警戒要連續幾個月

# NBER 景氣循環高峰／谷底（月）。來源：NBER Business Cycle Dating
# Committee。新的循環公布時在這裡加一列。
RECESSIONS = [
    ("1969-12", "1970-11"), ("1973-11", "1975-03"), ("1980-01", "1980-07"),
    ("1981-07", "1982-11"), ("1990-07", "1991-03"), ("2001-03", "2001-11"),
    ("2007-12", "2009-06"), ("2020-02", "2020-04"),
]
# 1981 緊接 1980 衰退，前一次的尾巴會讓任何規則提早「命中」，不能獨立檢驗
NOT_INDEPENDENT = {"1981-07"}


def _mi(date: str) -> int:
    return int(date[:4]) * 12 + int(date[5:7]) - 1


def _lab(n: int) -> str:
    return f"{n // 12}-{n % 12 + 1:02d}"


def monthly(rows: list[dict]) -> dict[int, float]:
    """
    {月序號: 值}。單月缺值（例如 2025-10 政府關門沒有家庭調查）用前後
    兩個月線性內插——不補的話三月均與 3 個月變化會整段斷掉。
    連續缺兩個月以上不補。
    """
    m = {}
    for r in rows or []:
        v = r.get("value")
        if v is None:
            continue
        try:
            m[_mi(str(r["date"]))] = float(v)
        except (KeyError, ValueError, TypeError):
            continue
    if not m:
        return m
    for n in range(min(m) + 1, max(m)):
        if n not in m and n - 1 in m and n + 1 in m:
            m[n] = (m[n - 1] + m[n + 1]) / 2
    return m


def _ma3(m, n):
    try:
        return (m[n] + m[n - 1] + m[n - 2]) / 3
    except KeyError:
        return None


def _d3(m, n):
    a, b = _ma3(m, n), _ma3(m, n - 3)
    return None if a is None or b is None else a - b


def z_at(m, n, window: int = Z_WINDOW):
    x = _d3(m, n)
    h = [_d3(m, j) for j in range(n - window, n)]
    if x is None or any(v is None for v in h):
        return None
    sd = st.pstdev(h)
    return None if not sd else (x - st.mean(h)) / sd


def rise_at(m, n):
    """三月均 − 前 12 個月三月均的最低點（個百分點）。"""
    a = _ma3(m, n)
    h = [_ma3(m, j) for j in range(n - 12, n)]
    if a is None or any(v is None for v in h):
        return None
    return a - min(h)


def state_at(m, n) -> str:
    """good／warning／critical／unknown（與燈號同一套詞彙）。"""
    rises = [rise_at(m, n - j) for j in range(RISE_PERSIST)]
    z = z_at(m, n)
    if rises[0] is None and z is None:
        return "unknown"
    if all(r is not None and r >= RISE_ALERT for r in rises):
        return "critical"
    if z is not None and z >= Z_WATCH:
        return "warning"
    return "good"


def signals(rows: list[dict], n_hist: int = 12) -> dict | None:
    """
    當期狀態＋近 n_hist 期軌跡。回傳：
      date, share, prev_share, ma3, rise, z, state, history[{date,state,label,value}]
    資料不足回 None。
    """
    m = monthly(rows)
    if len(m) < 16:
        return None
    n = max(m)
    hist = []
    for j in range(n - n_hist + 1, n + 1):
        if j not in m:
            continue
        r = rise_at(m, j)
        hist.append({"date": _lab(j) + "-01", "value": r,
                     "state": state_at(m, j),
                     "label": (f"較一年低點 {r:+.1f}pp" if r is not None else "—")})
    return {"date": _lab(n), "share": m[n], "prev_share": m.get(n - 1),
            "ma3": _ma3(m, n), "rise": rise_at(m, n),
            "prev_rise": rise_at(m, n - 1), "z": z_at(m, n),
            "state": state_at(m, n), "history": hist}


def recession_table(rows: list[dict]) -> list[dict]:
    """
    歷次衰退對照（用同一條序列即時重算，不是寫死的數字）：
      peak        衰退起點（NBER 高峰月）
      low/high    衰退前後比重三月均的低點與高點、上升幅度
      watch_lead  「留意」第一次亮的月份 − 衰退起點（負＝提前）
      alert_lead  「警戒」第一次亮的月份 − 衰退起點
    觀察窗：起點前 9 個月到谷底。樣本不足的欄位為 None。
    """
    m = monthly(rows)
    if not m:
        return []
    out = []
    for pk_s, tr_s in RECESSIONS:
        pk, tr = _mi(pk_s), _mi(tr_s)
        if pk - 18 < min(m) or tr > max(m):
            continue
        lows = [(j, _ma3(m, j)) for j in range(pk - 18, pk + 1) if _ma3(m, j) is not None]
        highs = [(j, _ma3(m, j)) for j in range(pk, min(tr + 13, max(m) + 1))
                 if _ma3(m, j) is not None]
        if not lows or not highs:
            continue
        lo = min(lows, key=lambda x: x[1])
        hi = max(highs, key=lambda x: x[1])

        def first(pred):
            for j in range(pk - 9, tr + 1):
                if pred(j):
                    return j - pk
            return None
        zok = z_at(m, pk - 9) is not None
        out.append({
            "peak": pk_s, "independent": pk_s not in NOT_INDEPENDENT,
            "low": lo[1], "low_date": _lab(lo[0]),
            "high": hi[1], "high_date": _lab(hi[0]), "rise": hi[1] - lo[1],
            "watch_lead": (first(lambda j: (z_at(m, j) or -9) >= Z_WATCH)
                           if zok else None),
            "watch_na": not zok,
            "alert_lead": first(lambda j: state_at(m, j) == "critical"),
        })
    return out


def false_alarms(rows: list[dict]) -> dict:
    """
    衰退以外期間的誤報段數（觸發後隔 6 個月以上再亮才算新的一段）。
    排除每次衰退起點前 12 個月到谷底後 12 個月。
    """
    m = monthly(rows)
    if not m:
        return {"watch": [], "alert": []}
    rec = [(_mi(a), _mi(b)) for a, b in RECESSIONS]

    def inrec(n):
        return any(p - 12 <= n <= t + 12 for p, t in rec)
    res = {}
    for key, pred in (("watch", lambda n: (z_at(m, n) or -9) >= Z_WATCH),
                      ("alert", lambda n: state_at(m, n) == "critical")):
        eps, last = [], -99
        for n in sorted(m):
            if pred(n) and not inrec(n):
                if n - last > 6:
                    eps.append(_lab(n))
                last = n
        res[key] = eps
    return res
