"""
長端利率與債務模組的離線示範資料（P5）。

⚠️ 依趨勢生成的示範值，**不是真實數據**。

不過水準是照 2026 年 7 月底的實況設定：
    10 年期 4.69%、30 年期 5.21%（2007 年以來最高）、政策利率 3.50–3.75%
這樣示範資料才會跟聯準會模組的「三票主張升息」互相吻合。
"""

from __future__ import annotations

import random
import datetime as dt

random.seed(20260815)

END = dt.date(2026, 8, 7)


def _bdays(n: int) -> list[str]:
    out, cur = [], END
    while len(out) < n:
        if cur.weekday() < 5:
            out.append(cur.isoformat())
        cur -= dt.timedelta(days=1)
    out.reverse()
    return out


def _quarters(n: int) -> list[str]:
    out, y, q = [], 2026, 2
    for _ in range(n):
        out.append(dt.date(y, q * 3 - 2, 1).isoformat())
        q -= 1
        if q == 0:
            q, y = 4, y - 1
    out.reverse()
    return out


def _walk(dates, end_value, drift, noise):
    """由最終值往回走，模擬出一條有趨勢的日頻序列。"""
    vals, v = [], end_value
    for _ in dates:
        vals.append(v)
        v -= drift + random.gauss(0, noise)
    vals.reverse()
    return [{"date": d, "value": round(x, 3)} for d, x in zip(dates, vals)]


def build() -> dict[str, list[dict]]:
    d = _bdays(420)
    s: dict[str, list[dict]] = {}

    # ---- 名目殖利率：長端上行明顯多於短端（曲線走陡）----
    s["DGS3MO"] = _walk(d, 3.72, 0.0004, 0.015)
    s["DGS2"] = _walk(d, 3.83, 0.0006, 0.022)
    s["DGS5"] = _walk(d, 4.18, 0.0016, 0.026)
    s["DGS10"] = _walk(d, 4.69, 0.0028, 0.030)
    s["DGS30"] = _walk(d, 5.21, 0.0038, 0.032)

    # ---- 實質利率與通膨補償 ----
    s["DFII5"] = _walk(d, 1.62, 0.0009, 0.022)
    s["DFII10"] = _walk(d, 2.03, 0.0016, 0.024)
    s["DFII30"] = _walk(d, 2.55, 0.0022, 0.026)
    # 名目 = 實質 + 損益兩平，所以由前兩者反推以維持一致性
    s["T5YIE"] = [{"date": a["date"], "value": round(a["value"] - b["value"], 3)}
                  for a, b in zip(s["DGS5"], s["DFII5"])]
    s["T10YIE"] = [{"date": a["date"], "value": round(a["value"] - b["value"], 3)}
                   for a, b in zip(s["DGS10"], s["DFII10"])]
    s["T5YIFR"] = _walk(d, 2.66, 0.0004, 0.012)

    # ---- 期限溢酬：由負轉正，這是長端上行的主因 ----
    s["THREEFYTP10"] = _walk(d, 0.78, 0.0022, 0.014)

    # ---- 信用利差 ----
    s["BAMLC0A0CM"] = _walk(d, 1.12, -0.0004, 0.011)
    s["BAMLC0A4CBBB"] = _walk(d, 1.38, -0.0005, 0.013)
    s["BAMLH0A0HYM2"] = _walk(d, 3.42, -0.0018, 0.032)

    # ---- 政府債務（季頻）----
    q = _quarters(20)
    gdp, v = [], 31_600.0
    for _ in q:
        gdp.append(v)
        v /= 1.0115
    gdp.reverse()
    s["GDP"] = [{"date": dd, "value": round(x, 1)} for dd, x in zip(q, gdp)]

    # 實質 GDP（鏈式美元）：名目季增約 1.15%，實質約 0.5%，
    # 兩者的差就是平減指數——r 減 g 的 g 要用這一條，不能寫死。
    rgdp, v = [], 23_900.0
    for _ in q:
        rgdp.append(v)
        v /= 1.005
    rgdp.reverse()
    s["GDPC1"] = [{"date": dd, "value": round(x, 1)} for dd, x in zip(q, rgdp)]

    debt, v = [], 39_800_000.0          # 百萬美元
    for _ in q:
        debt.append(v)
        v /= 1.017
    debt.reverse()
    s["GFDEBTN"] = [{"date": dd, "value": round(x, 0)} for dd, x in zip(q, debt)]

    s["GFDEGDQ188S"] = [
        {"date": dd, "value": round(dv / 1000 / gv * 100, 2)}
        for dd, dv, gv in zip(q, [x["value"] for x in s["GFDEBTN"]],
                              [x["value"] for x in s["GDP"]])
    ]

    # 利息支出：這幾年是財政壓力的主要來源
    interest, v = [], 1_240.0            # 十億，年率
    for _ in q:
        interest.append(v)
        v /= 1.028
    interest.reverse()
    s["A091RC1Q027SBEA"] = [{"date": dd, "value": round(x, 1)}
                            for dd, x in zip(q, interest)]

    receipts, v = [], 5_180.0
    for _ in q:
        receipts.append(v)
        v /= 1.010
    receipts.reverse()
    s["FGRECPT"] = [{"date": dd, "value": round(x, 1)} for dd, x in zip(q, receipts)]

    outlays, v = [], 7_420.0
    for _ in q:
        outlays.append(v)
        v /= 1.013
    outlays.reverse()
    s["FGEXPND"] = [{"date": dd, "value": round(x, 1)} for dd, x in zip(q, outlays)]

    # 聯準會持有的公債（週頻，百萬美元）。設成緩步下降，
    # 對應目前仍在進行的縮表——這樣離線畫面才會走到「縮表推升供給」那條分支。
    wk, cur = [], END
    while len(wk) < 60:
        wk.append(cur.isoformat())
        cur -= dt.timedelta(days=7)
    wk.reverse()
    treast, v = [], 4_180_000.0            # 百萬美元
    for _ in wk:
        treast.append(v)
        v += 8_500.0                       # 往回走 → 過去比較高，代表在減持
    treast.reverse()
    s["TREAST"] = [{"date": d_, "value": round(x, 0)}
                   for d_, x in zip(wk, treast)]

    # 月度赤字
    months, y, m = [], 2026, 7
    for _ in range(36):
        months.append(dt.date(y, m, 1).isoformat())
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    months.reverse()
    s["MTSDS133FMS"] = [{"date": dd, "value": round(-190_000 + random.gauss(0, 45_000))}
                        for dd in months]
    return s


# ---------------------------------------------------------------------------
# 近期發債申報（離線示範）
# ---------------------------------------------------------------------------
def offerings() -> list[dict]:
    """
    離線模式的發債申報素材，形狀與 sec.fetch_recent_offerings 一致。

    正式執行時由 EDGAR 的 submissions 端點即時取得。這裡刻意混入
    「有解析到金額」與「沒解析到」兩種，讓畫面的兩條路徑都會被畫到。
    """
    import datetime as dt
    today = dt.date.today()

    def d(days_ago: int) -> str:
        return (today - dt.timedelta(days=days_ago)).isoformat()

    return [
        {"name": "Alphabet", "ticker": "GOOGL", "form": "424B2",
         "date": d(6), "items": "", "kind": "offering", "amount": 12.5,
         "accession": "0001652044-26-000090",
         "doc_url": "https://www.sec.gov/Archives/edgar/data/1652044/"
                    "000165204426000090/d424b2.htm",
         "desc": "424B2"},
        {"name": "Meta", "ticker": "META", "form": "8-K",
         "date": d(19), "items": "2.03,9.01", "kind": "event", "amount": None,
         "accession": "0001326801-26-000058",
         "doc_url": "https://www.sec.gov/Archives/edgar/data/1326801/"
                    "000132680126000058/meta-8k.htm",
         "desc": "8-K"},
        {"name": "Oracle", "ticker": "ORCL", "form": "424B5",
         "date": d(41), "items": "", "kind": "offering", "amount": 18.0,
         "accession": "0001341439-26-000031",
         "doc_url": "https://www.sec.gov/Archives/edgar/data/1341439/"
                    "000134143926000031/d424b5.htm",
         "desc": "424B5"},
    ]
