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

from . import clock

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

    # ---- 政策利率區間 ----
    # 常數序列（真實的 DFEDTARU／DFEDTARL 也是階梯狀的常數）。
    # 值對齊 config/fomc.yaml 的後備值，離線畫面才會跟示範的聲明一致。
    s["DFEDTARU"] = [{"date": dd, "value": 3.75} for dd in d]
    s["DFEDTARL"] = [{"date": dd, "value": 3.50} for dd in d]

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

    # ---- 匯率 ----
    # 只用來把海外發債的原幣金額換算成美元等值。方向刻意跟 FRED 一致
    #（DEXUSEU 是「一歐元換多少美元」、DEXJPUS 是「一美元換多少日圓」），
    # 離線與正式執行走同一段換算程式，方向寫反在這裡就會被看出來。
    s["DEXUSEU"] = _walk(d, 1.0850, 0.00002, 0.004)     # 美元／歐元
    s["DEXUSUK"] = _walk(d, 1.2720, 0.00002, 0.005)     # 美元／英鎊
    s["DEXCAUS"] = _walk(d, 1.3720, -0.00002, 0.004)    # 加幣／美元
    s["DEXJPUS"] = _walk(d, 152.40, 0.0040, 0.500)      # 日圓／美元

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
    離線模式的發債素材，形狀與 sec.fetch_recent_offerings 的**輸入**一致
    （尚未去重的原始申報），最後一樣走 dedupe_deals。

    這裡刻意鋪的是**真實世界踩過的每一種坑**，讓分類、去重與多幣別的
    每一條路徑都會被走到：

      ① Alphabet 美元 — 預估版 424B2 → 三天後定價版 → 再四天後 8-K 2.03。
                       三份申報要收斂成**一筆** 250 億美元。
                       而且分券表在文件裡出現兩次（封面＋費用表），
                       去重之後仍然是 250 億，不是 500 億。
      ② Alphabet 歐元 — €90 億，與 ③ 同一週但**不同幣別** → 兩筆不同交易
      ③ Alphabet 加幣 — C$85 億
      ④ Amazon 加幣   — C$140 億，五檔分券
      ⑤ Amazon 貸款   — 8-K 2.03 的 US$175 億 delayed draw term loan。
                       這**不是**公開債券發行：另外列，不進筆數與金額。
      ⑥ Oracle ATM    — 424B5 賣的是最高 200 億美元的普通股 ATM 增發。
                       表格號跟債券一模一樣，靠內容才分得出來 → 完全排除。
      ⑦ Microsoft     — 昨天申報的預估版，還沒有定價版 → 列出但不計數
      ⑧ Meta 美元     — 250 億美元，分券表同樣重複出現

    預期結果：**5 筆**已定價的債券交易（①②③④⑧）。
    """
    import datetime as dt
    from .sec import dedupe_deals
    today = clock.today()

    def d(days_ago: int) -> str:
        return (today - dt.timedelta(days=days_ago)).isoformat()

    def tr(ccy, *pairs):
        return [{"currency": ccy, "amount": a, "maturity": m, "coupon": ""}
                for a, m in pairs]

    def deal(name, ticker, cik, day, form, ccy, tranches, *,
             prelim=False, security="bond", doc="d424b.htm"):
        totals = {}
        for x in tranches:
            totals[x["currency"]] = totals.get(x["currency"], 0.0) + x["amount"]
        return {"name": name, "ticker": ticker, "form": form, "date": d(day),
                "items": "", "kind": "offering", "preliminary": prelim,
                "security": security, "tranches": tranches, "totals": totals,
                "currency": (max(totals, key=lambda c: totals[c])
                             if totals else ""),
                "principal": (max(totals.values()) if totals else None),
                "amount": (totals["USD"] / 1e9 if "USD" in totals else None),
                "accession": f"0001652044-26-{day:06d}",
                "doc_url": ("https://www.sec.gov/Archives/edgar/data/"
                            f"{cik}/000165204426{day:06d}/{doc}"),
                "desc": form}

    GOOG = tr("USD", (3e9, "2031"), (2e9, "2033"), (6e9, "2036"),
              (4e9, "2046"), (6e9, "2056"), (4e9, "2066"))      # 250 億
    META = tr("USD", (5e9, "2032"), (7e9, "2036"), (8e9, "2046"), (5e9, "2056"))
    AMZN = tr("CAD", (1.25e9, "2028"), (2.5e9, "2030"), (2.0e9, "2032"),
              (3.5e9, "2035"), (4.75e9, "2055"))                 # C$140 億

    raw = [
        # ① 同一筆的三份申報。預估版的封面定價欄是空的 → 沒有分券。
        deal("Alphabet", "GOOGL", 1652044, 9, "424B2", "USD", [],
             prelim=True, doc="d424b2-prelim.htm"),
        deal("Alphabet", "GOOGL", 1652044, 6, "424B2", "USD", GOOG),
        {"name": "Alphabet", "ticker": "GOOGL", "form": "8-K", "date": d(2),
         "items": "2.03,9.01", "kind": "event", "security": "other",
         "tranches": [], "totals": {}, "amount": None, "preliminary": False,
         "accession": "0001652044-26-000093",
         "doc_url": "https://www.sec.gov/Archives/edgar/data/1652044/"
                    "000165204426000093/goog-8k.htm", "desc": "8-K"},
        # ②③ 同一週、不同幣別 → 兩筆
        deal("Alphabet", "GOOGL", 1652044, 5, "424B5", "EUR",
             tr("EUR", (4e9, "2033"), (5e9, "2041"))),
        deal("Alphabet", "GOOGL", 1652044, 4, "424B5", "CAD",
             tr("CAD", (3.5e9, "2030"), (5e9, "2045"))),
        # ④ 加幣五檔
        deal("Amazon", "AMZN", 1018724, 33, "424B2", "CAD", AMZN),
        # ⑤ 銀行貸款額度：8-K 2.03，配不到債券交易 → 另外列、不計數
        {"name": "Amazon", "ticker": "AMZN", "form": "8-K", "date": d(63),
         "items": "2.03,9.01", "kind": "event", "security": "other",
         "tranches": [], "totals": {}, "amount": None, "preliminary": False,
         "accession": "0001018724-26-000080",
         "doc_url": "https://www.sec.gov/Archives/edgar/data/1018724/"
                    "000101872426000080/amzn-8k.htm", "desc": "8-K"},
        # ⑥ ATM 普通股增發：表格號跟債券一樣，靠內容排除
        deal("Oracle", "ORCL", 1341439, 41, "424B5", "", [],
             security="equity", doc="d424b5-atm.htm"),
        # ⑦ 孤兒預估版
        deal("Microsoft", "MSFT", 789019, 1, "424B5", "USD", [],
             prelim=True, doc="d424b5-prelim.htm"),
        # ⑧ Meta 美元
        deal("Meta", "META", 1326801, 19, "424B2", "USD", META),
    ]
    return dedupe_deals(raw)


# ---------------------------------------------------------------------------
# 財報新聞稿（離線示範）
# ---------------------------------------------------------------------------
def earnings(companies: list) -> list[dict]:
    """
    離線模式的財報新聞稿素材，形狀與 sec.fetch_recent_earnings 的**輸出**一致。

    正式執行時由 EDGAR 的 submissions 端點取 8-K 項目 2.02。

    這裡刻意鋪出兩種狀態，讓畫面的兩條路徑都會被走到：
      ① 前兩家 — 新聞稿已經是**下一季**的（ahead=True）：季末後約 3 週公布，
                 而 XBRL 還停在上一季。這正是這一區存在的理由，
                 畫面要跳出「下方數字還沒更新到那一季」的提示。
      ② 其餘   — 新聞稿與下方表格是同一季（ahead=False），只列日期與連結。

    離線用的 period_end 是 config 的手動值（沒有 period_end 欄位），
    所以這裡自己造一個：以今天回推，讓相對關係固定、不隨執行日漂移。
    """
    import datetime as dt
    today = clock.today()

    def d(days_ago: int) -> str:
        return (today - dt.timedelta(days=days_ago)).isoformat()

    out = []
    for i, c in enumerate(companies):
        cik = c.get("cik") or 0
        ahead = i < 2
        # ahead：期末日在 115 天前、新聞稿在 21 天前 → 相差 94 天 > 60
        # 非 ahead：期末日在 45 天前、新聞稿在 24 天前 → 相差 21 天
        pe, day = (d(115), 21) if ahead else (d(45), 24)
        out.append({
            "name": c.get("name", ""), "ticker": c.get("ticker", ""),
            "date": d(day + i), "form": "8-K", "items": "2.02,9.01",
            "doc_url": (f"https://www.sec.gov/Archives/edgar/data/{cik}/"
                        f"00000000002600{i:02d}/earnings-8k.htm"),
            "accession": f"0000000000-26-0000{i:02d}",
            "period_end": c.get("period_end") or pe,
            "lag": None, "ahead": ahead,
        })
    # lag 照 sec.fetch_recent_earnings 的定義補上，讓兩邊的欄位完全一致
    for r in out:
        try:
            r["lag"] = abs((dt.date.fromisoformat(r["date"])
                            - dt.date.fromisoformat(r["period_end"])).days)
        except (ValueError, TypeError):
            r["lag"] = None
    out.sort(key=lambda x: x["date"], reverse=True)
    return out
