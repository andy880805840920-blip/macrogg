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
    （也就是尚未去重的原始申報），最後一樣走 dedupe_deals。

    正式執行時由 EDGAR 的 submissions 端點即時取得。這裡刻意鋪五種情況，
    讓畫面與去重邏輯的每一條路徑都會被走到：
      ① Alphabet — 先一份預估版 424B2（封面沒有定價、金額 None），三天後
                   定價版 424B2 有金額，再四天後同一筆的 8-K 2.03。
                   三份申報要收斂成**一筆**交易。
      ② Oracle   — 424B5 有金額，沒有對應的 8-K（單純的公開發行）
      ③ Meta     — 只有 8-K 2.03、配不到任何 424B（銀行貸款那一類，要獨立列）
                   而且金額解析不到，走「金額待確認」那條路徑
      ④ Microsoft— 昨天才申報的預估版，還沒有定價版 → 走「尚未定價」那條
                   路徑：列在明細裡但不計入筆數與合計
      ⑤ Amazon   — 同一筆的兩個幣別分開申報（相隔一天、金額不同），
                   要併成一筆並把兩個金額相加
    """
    import datetime as dt
    from .sec import dedupe_deals
    today = clock.today()

    def d(days_ago: int) -> str:
        return (today - dt.timedelta(days=days_ago)).isoformat()

    raw = [
        # 預估版：封面寫 Subject to Completion，定價欄是空的 → 沒有金額。
        # 三天後的定價版會把它吃掉，畫面上不該看到這一份。
        {"name": "Alphabet", "ticker": "GOOGL", "form": "424B2",
         "date": d(9), "items": "", "kind": "offering", "amount": None,
         "preliminary": True,
         "accession": "0001652044-26-000088",
         "doc_url": "https://www.sec.gov/Archives/edgar/data/1652044/"
                    "000165204426000088/d424b2-prelim.htm",
         "desc": "424B2"},
        {"name": "Alphabet", "ticker": "GOOGL", "form": "424B2",
         "date": d(6), "items": "", "kind": "offering", "amount": 12.5,
         "preliminary": False,
         "accession": "0001652044-26-000090",
         "doc_url": "https://www.sec.gov/Archives/edgar/data/1652044/"
                    "000165204426000090/d424b2.htm",
         "desc": "424B2"},
        # 同一筆交易的 8-K：定價後四天申報，去重之後不該再出現
        {"name": "Alphabet", "ticker": "GOOGL", "form": "8-K",
         "date": d(2), "items": "2.03", "kind": "event", "amount": None,
         "accession": "0001652044-26-000093",
         "doc_url": "https://www.sec.gov/Archives/edgar/data/1652044/"
                    "000165204426000093/goog-8k.htm",
         "desc": "8-K"},
        {"name": "Meta", "ticker": "META", "form": "8-K",
         "date": d(19), "items": "2.03,9.01", "kind": "event", "amount": None,
         "accession": "0001326801-26-000058",
         "doc_url": "https://www.sec.gov/Archives/edgar/data/1326801/"
                    "000132680126000058/meta-8k.htm",
         "desc": "8-K"},
        {"name": "Oracle", "ticker": "ORCL", "form": "424B5",
         "date": d(41), "items": "", "kind": "offering", "amount": 18.0,
         "preliminary": False,
         "accession": "0001341439-26-000031",
         "doc_url": "https://www.sec.gov/Archives/edgar/data/1341439/"
                    "000134143926000031/d424b5.htm",
         "desc": "424B5"},
        # 昨天申報、還沒定價 → 明細列「尚未定價」，不計入筆數與合計
        {"name": "Microsoft", "ticker": "MSFT", "form": "424B5",
         "date": d(1), "items": "", "kind": "offering", "amount": None,
         "preliminary": True,
         "accession": "0000789019-26-000042",
         "doc_url": "https://www.sec.gov/Archives/edgar/data/789019/"
                    "000078901926000042/d424b5-prelim.htm",
         "desc": "424B5"},
        # 同一筆交易的美元券與歐元券分兩份申報 → 併成一筆、金額相加
        {"name": "Amazon", "ticker": "AMZN", "form": "424B2",
         "date": d(33), "items": "", "kind": "offering", "amount": 9.0,
         "preliminary": False,
         "accession": "0001018724-26-000071",
         "doc_url": "https://www.sec.gov/Archives/edgar/data/1018724/"
                    "000101872426000071/d424b2-usd.htm",
         "desc": "424B2"},
        {"name": "Amazon", "ticker": "AMZN", "form": "424B2",
         "date": d(32), "items": "", "kind": "offering", "amount": 3.5,
         "preliminary": False,
         "accession": "0001018724-26-000072",
         "doc_url": "https://www.sec.gov/Archives/edgar/data/1018724/"
                    "000101872426000072/d424b2-eur.htm",
         "desc": "424B2"},
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
