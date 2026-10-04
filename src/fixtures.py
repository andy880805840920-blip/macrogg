"""
離線示範資料。

用途：在沒有網路 / 還沒設定 API key 時，讓你先看到畫面長相與分析邏輯。

⚠️ 資料真實性說明
------------------
* 標示為 VERIFIED 的數字取自 BLS 2026 年 7 月就業報告與 6 月 JOLTS 的實際值。
* 其餘（較早月份、部分產業細項）為依趨勢生成的示範值，**不可用於實際研究**。
* 正式執行（python run.py）會全部改用 FRED 的真實資料。
"""

from __future__ import annotations

import random
import datetime as dt

random.seed(20260807)          # 固定種子，確保每次產生的示範資料一致

START = dt.date(2021, 1, 1)
END = dt.date(2026, 7, 1)


def _months(start: dt.date = START, end: dt.date = END) -> list[str]:
    out, cur = [], start
    while cur <= end:
        out.append(cur.isoformat())
        y, m = (cur.year + 1, 1) if cur.month == 12 else (cur.year, cur.month + 1)
        cur = dt.date(y, m, 1)
    return out


MONTHS = _months()

# --- VERIFIED：2026 年各月非農變動（BLS 現行修正後值，單位：千人）---
NFP_2026 = {
    "2026-01-01": 160.0, "2026-02-01": -156.0, "2026-03-01": 214.0,
    "2026-04-01": 148.0, "2026-05-01": 63.0, "2026-06-01": 20.0,
    "2026-07-01": -23.0,
}
# --- VERIFIED：初值（用於修正追蹤示範）---
NFP_2026_ORIGINAL = {
    "2026-01-01": 130.0, "2026-02-01": -92.0, "2026-03-01": 178.0,
    "2026-04-01": 115.0, "2026-05-01": 172.0, "2026-06-01": 57.0,
    "2026-07-01": -23.0,
}

# --- VERIFIED：2026 年 7 月家庭調查 ---
UNRATE_RECENT = {
    "2026-01-01": 4.0, "2026-02-01": 4.1, "2026-03-01": 4.2,
    "2026-04-01": 4.3, "2026-05-01": 4.2, "2026-06-01": 4.2,
    "2026-07-01": 4.1,
}
CIVPART_RECENT = {
    "2026-01-01": 62.1, "2026-02-01": 62.0, "2026-03-01": 61.9,
    "2026-04-01": 61.8, "2026-05-01": 61.6, "2026-06-01": 61.5,
    "2026-07-01": 61.4,
}
EMRATIO_RECENT = {
    "2026-01-01": 59.4, "2026-02-01": 59.3, "2026-03-01": 59.2,
    "2026-04-01": 59.1, "2026-05-01": 59.0, "2026-06-01": 59.0,
    "2026-07-01": 58.9,
}
UNEMPLOY_RECENT = {          # 千人
    "2026-04-01": 7373.0, "2026-05-01": 7280.0,
    "2026-06-01": 7100.0, "2026-07-01": 6900.0,
}

# --- VERIFIED：2026 年 7 月產業變動（部分）；其餘為示範值 ---
INDUSTRY_JUL = {
    "CES9093161101": -50.0,   # VERIFIED 地方政府教育
    "USFIRE": -14.0,          # VERIFIED 金融活動
    "CES6562000001": 38.0,    # 示範值 醫療與社福
    "USTRADE": -12.0,         # 示範值 零售
    "USLAH": -9.0,            # 示範值 休閒住宿餐飲
    "CES9093000001": -47.0,   # 示範值 地方政府（含教育）
    "CES9092000001": -4.0,
    "CES9091000001": -2.0,
    "MANEMP": -6.0,
    "USCONS": 4.0,
    "USMINE": -1.0,
    "USWTRADE": -3.0,
    "CES4300000001": 7.0,
    "CES4422000001": 1.0,
    "USINFO": -5.0,
    "USPBS": -8.0,
    "CES6561000001": 6.0,
    "USSERV": 3.0,
}

# 各產業的就業水準基準（千人，2026-07），以及歷史月變動的平均/標準差
INDUSTRY_BASE = {
    "USMINE": (630, 0.2, 2), "USCONS": (8320, 6, 12), "MANEMP": (12700, -2, 12),
    "USWTRADE": (6180, 1, 6), "USTRADE": (15500, -2, 18),
    "CES4300000001": (6850, 8, 12), "CES4422000001": (590, 0.4, 1.5),
    "USINFO": (2900, -2, 7), "USFIRE": (9090, -6, 9),
    "USPBS": (22800, -2, 25), "CES6562000001": (23400, 55, 20),
    "CES6561000001": (4000, 5, 6), "USLAH": (17300, 8, 25),
    "USSERV": (5980, 3, 6), "CES9091000001": (2950, -3, 8),
    "CES9092000001": (5560, 2, 8), "CES9093000001": (15100, 5, 22),
}


def _walk_back(level_end: float, changes: list[float]) -> list[float]:
    """由最終水準值與各期變動，回推整條水準值序列。"""
    levels = [level_end]
    for ch in reversed(changes):
        levels.append(levels[-1] - ch)
    return list(reversed(levels))


def _series(dates: list[str], levels: list[float]) -> list[dict]:
    return [{"date": d, "value": round(v, 3)} for d, v in zip(dates, levels)]


def _gen_changes(dates: list[str], mean: float, sd: float,
                 overrides: dict[str, float] | None = None) -> list[float]:
    out = []
    for d in dates[1:]:
        v = (overrides or {}).get(d)
        out.append(v if v is not None else random.gauss(mean, sd))
    return out


def _interp_recent(dates: list[str], recent: dict[str, float],
                   early: float, noise: float = 0.05) -> list[float]:
    """已知近期實際值，較早期間用線性趨勢＋雜訊補齊。"""
    keys = sorted(recent)
    first_known_idx = dates.index(keys[0])
    first_known_val = recent[keys[0]]
    out = []
    for i, d in enumerate(dates):
        if d in recent:
            out.append(recent[d])
        elif i < first_known_idx:
            frac = i / max(first_known_idx, 1)
            out.append(early + (first_known_val - early) * frac + random.gauss(0, noise))
        else:
            out.append(out[-1] + random.gauss(0, noise))
    return out


def build() -> dict[str, list[dict]]:
    # 每次進 build() 都重設種子。random.seed 只在 import 時跑一次的話，
    # 第二次呼叫（build_vintages 內部）會抽到完全不同的序列——
    # 67 個月裡有 59 個對不上，於是離線模式會憑空生出一堆從未發生的
    # 「修正」，把「近一年修正傾向」算成實際值的一半。
    random.seed(20260807)
    d = MONTHS
    s: dict[str, list[dict]] = {}

    # ---- 非農總數 ----
    changes = _gen_changes(d, mean=170, sd=90, overrides=NFP_2026)
    s["PAYEMS"] = _series(d, _walk_back(159_800.0, changes))

    gov_changes = _gen_changes(d, mean=18, sd=22, overrides={"2026-07-01": -53.0})
    s["USGOVT"] = _series(d, _walk_back(23_610.0, gov_changes))
    priv_levels = [a["value"] - b["value"] for a, b in zip(s["PAYEMS"], s["USGOVT"])]
    s["USPRIV"] = _series(d, priv_levels)

    # ---- 家庭調查 ----
    s["UNRATE"] = _series(d, _interp_recent(d, UNRATE_RECENT, early=6.3, noise=0.06))
    s["CIVPART"] = _series(d, _interp_recent(d, CIVPART_RECENT, early=61.4, noise=0.06))
    s["EMRATIO"] = _series(d, _interp_recent(d, EMRATIO_RECENT, early=57.5, noise=0.06))
    s["U6RATE"] = _series(d, [r["value"] + 3.5 + random.gauss(0, 0.06)
                              for r in s["UNRATE"]])
    s["UNEMPLOY"] = _series(d, _interp_recent(d, UNEMPLOY_RECENT, early=10_100, noise=45))
    s["CLF16OV"] = _series(
        d, [u["value"] / (r["value"] / 100) for u, r in zip(s["UNEMPLOY"], s["UNRATE"])]
    )
    s["CE16OV"] = _series(
        d, [l["value"] - u["value"] for l, u in zip(s["CLF16OV"], s["UNEMPLOY"])]
    )
    s["LNS11300060"] = _series(d, _interp_recent(
        d, {"2026-07-01": 83.2, "2026-06-01": 83.3, "2026-05-01": 83.3}, early=81.8, noise=0.07))
    s["LNS12300060"] = _series(d, _interp_recent(
        d, {"2026-07-01": 80.4, "2026-06-01": 80.5, "2026-05-01": 80.5}, early=77.8, noise=0.07))

    # ---- 失業結構 ----
    # 失去工作者比重：示範模式直接用 FRED 實際歷史（1967–2026-07），
    # 讓 z 值窗口與歷次衰退對照有真實的長度可算。NA＝2025-10 政府關門缺值。
    s["LNS13023622"] = _job_losers_history()
    # 其他三類比重：示範用，把「100 − 失去工作者比重」依固定比例拆開
    _jlh = [r for r in s["LNS13023622"] if r["date"] >= "2015"]
    for _sid, _w in (("LNS13023706", 0.22), ("LNS13023558", 0.57),
                     ("LNS13023570", 0.21)):
        s[_sid] = [{"date": r["date"],
                    "value": round((100 - r["value"]) * _w + random.gauss(0, 0.3), 1)}
                   for r in _jlh]
    # CPI-U（實質薪資平減用）：示範用，年增 2.9% 的平滑指數，不耗用亂數
    s["CPIAUCSL"] = [{"date": dd, "value": round(300 * 1.029 ** (i / 12), 3)}
                     for i, dd in enumerate(d)]
    s["LNS13023621"] = _series(d, _interp_recent(
        d, {"2026-07-01": 2050.0, "2026-06-01": 2010.0}, early=2900, noise=35))
    s["LNS13023705"] = _series(d, _interp_recent(
        d, {"2026-07-01": 790.0}, early=900, noise=25))
    s["LNS13023557"] = _series(d, _interp_recent(
        d, {"2026-07-01": 2350.0}, early=2600, noise=40))
    s["LNS13023569"] = _series(d, _interp_recent(
        d, {"2026-07-01": 720.0}, early=650, noise=25))
    s["UEMP27OV"] = _series(d, _interp_recent(          # VERIFIED 1.8M / 25.5%
        d, {"2026-07-01": 1760.0, "2026-06-01": 1720.0}, early=3900, noise=45))
    s["UEMPMED"] = _series(d, _interp_recent(
        d, {"2026-07-01": 10.8, "2026-06-01": 10.4}, early=15.0, noise=0.3))
    s["LNS12032194"] = _series(d, _interp_recent(
        d, {"2026-07-01": 4720.0}, early=5800, noise=70))
    s["LNS12026619"] = _series(d, _interp_recent(
        d, {"2026-07-01": 8900.0}, early=7300, noise=80))

    # ---- 薪資與工時（VERIFIED：AHE 37.62、月增 0.02、年增 3.2%）----
    ahe_end = 37.62
    ahe_levels, v = [], ahe_end
    for _ in range(len(d)):
        ahe_levels.append(v)
        v -= random.uniform(0.08, 0.13)
    s["CES0500000003"] = _series(d, list(reversed(ahe_levels)))
    s["CES0500000003"][-1]["value"] = 37.62
    s["CES0500000003"][-2]["value"] = 37.60
    s["CES0500000003"][-13]["value"] = round(37.62 / 1.032, 2)

    # 僱用成本指數（季頻，指數值）。年增設定成約 3.6%，比平均時薪的 3.2%
    # 略高——這是實務上常見的關係（平均時薪會被職位組成拉動，ECI 不會），
    # 差距 0.4 個百分點在門檻（0.7）以內，離線畫面走的是「兩者一致」那條。
    eci_end = 176.4
    eci_levels, v = [], eci_end
    for _ in range((len(d) // 3) + 6):
        eci_levels.append(v)
        v /= 1.0089                      # 季增約 0.89% → 年增約 3.6%
    eci_dates = [dd for i, dd in enumerate(d) if i % 3 == 0][-len(eci_levels):]
    s["ECIALLCIV"] = _series(eci_dates,
                             list(reversed(eci_levels))[-len(eci_dates):])

    prod_end = 31.95
    prod_levels, v = [], prod_end
    for _ in range(len(d)):
        prod_levels.append(v)
        v -= random.uniform(0.07, 0.12)
    s["AHETPI"] = _series(d, list(reversed(prod_levels)))
    s["AHETPI"][-1]["value"] = 31.95
    s["AHETPI"][-13]["value"] = round(31.95 / 1.036, 2)      # 非管理職年增 3.6%

    s["AWHAETP"] = _series(d, _interp_recent(
        d, {"2026-07-01": 34.2, "2026-06-01": 34.2}, early=34.7, noise=0.06))

    # ---- JOLTS（VERIFIED：2026-06 職缺 7,359K、招聘率 3.4、離職率 2.0、裁員率 1.1）----
    jd = d[:-1]     # JOLTS 落後一個月
    s["JTSJOL"] = _series(jd, _interp_recent(
        jd, {"2026-06-01": 7359.0, "2026-05-01": 7537.0,
             "2026-04-01": 7585.0, "2026-03-01": 6887.0}, early=9800, noise=90))
    s["JTSHIR"] = _series(jd, _interp_recent(
        jd, {"2026-06-01": 3.4, "2026-05-01": 3.4}, early=4.4, noise=0.05))
    s["JTSQUR"] = _series(jd, _interp_recent(
        jd, {"2026-06-01": 2.0, "2026-05-01": 2.0}, early=2.8, noise=0.04))
    s["JTSLDR"] = _series(jd, _interp_recent(
        jd, {"2026-06-01": 1.1, "2026-05-01": 1.1}, early=1.0, noise=0.03))
    # 疫情前基準（人力流動總結用）：2015–2020 接 FRED 實際值
    s["JTSHIR"] = _jolts_pre(_JOLTS_PRE_H) + s["JTSHIR"]
    s["JTSLDR"] = _jolts_pre(_JOLTS_PRE_L) + s["JTSLDR"]
    s["JTSTSR"] = _series(jd, _interp_recent(
        jd, {"2026-06-01": 3.4}, early=4.0, noise=0.05))

    # ---- 每週失業金（週頻，示範值）----
    weeks, cur = [], dt.date(2026, 8, 1)
    while len(weeks) < 130:
        weeks.append(cur.isoformat())
        cur -= dt.timedelta(days=7)
    weeks.reverse()
    ic, cc = [], []
    base_ic, base_cc = 218_000, 1_960_000
    for i, _w in enumerate(weeks):
        drift = i / len(weeks)
        ic.append(base_ic + drift * 18_000 + random.gauss(0, 7_000))
        cc.append(base_cc + drift * 140_000 + random.gauss(0, 18_000))
    s["ICSA"] = _series(weeks, ic)
    s["CCSA"] = _series(weeks, cc)
    s["IC4WSA"] = _series(
        weeks[3:], [sum(ic[i - 3:i + 1]) / 4 for i in range(3, len(ic))]
    )

    # ---- 產業細項 ----
    for sid, (base, mean, sd) in INDUSTRY_BASE.items():
        ov = {"2026-07-01": INDUSTRY_JUL.get(sid)} if sid in INDUSTRY_JUL else None
        ch = _gen_changes(d, mean, sd, ov)
        s[sid] = _series(d, _walk_back(float(base), ch))

    ov = {"2026-07-01": INDUSTRY_JUL["CES9093161101"]}
    s["CES9093161101"] = _series(d, _walk_back(8_120.0, _gen_changes(d, 3, 10, ov)))

    # ---- 工作年齡人口（損益兩平就業增速用）----
    # 近年移民政策收緊，人口成長明顯放慢：早期每月約 +18 萬，近期降到約 +7 萬
    pop_changes = []
    for i, dd in enumerate(d[1:]):
        base = 180 if i < len(d) - 19 else 70
        pop_changes.append(base + random.gauss(0, 6))
    s["CNP16OV"] = _series(d, _walk_back(273_500.0, pop_changes))

    # ---- 參照 ----
    s["NROU"] = _series(d, [4.4] * len(d))
    # FOMC 對長期失業率的判斷。取自 2026 年 6 月 SEP 的**真實值**
    # （federalreserve.gov/monetarypolicy/fomcprojtabl20260617.htm）——
    # 九宮格的就業軸門檻直接由它們決定，用假的會讓離線畫面的判定
    # 與正式執行對不起來。SEP 一季更新一次，所以只有幾個觀測點。
    s["UNRATEMDLR"] = [{"date": "2026-06-17", "value": 4.2}]
    s["UNRATECTLLR"] = [{"date": "2026-06-17", "value": 4.0}]
    s["UNRATECTHLR"] = [{"date": "2026-06-17", "value": 4.3}]
    return s


# 三個實際發布版本的 2026 年月變動（VERIFIED，單位：千人）
#   2026-06-05 發布：5 月初值 +172
#   2026-07-02 發布：5 月一修 +129、6 月初值 +57
#   2026-08-07 發布：5 月二修 +63、6 月一修 +20、7 月初值 -23
VINTAGE_CHANGES = {
    "2026-06-05": {"2026-01-01": 160.0, "2026-02-01": -156.0, "2026-03-01": 214.0,
                   "2026-04-01": 148.0, "2026-05-01": 172.0},
    "2026-07-02": {"2026-01-01": 160.0, "2026-02-01": -156.0, "2026-03-01": 214.0,
                   "2026-04-01": 148.0, "2026-05-01": 129.0, "2026-06-01": 57.0},
    "2026-08-07": dict(NFP_2026),
}


def build_vintages() -> dict[str, dict[str, dict[str, float]]]:
    """
    產生 PAYEMS 的示範 vintage，讓修正追蹤在離線模式下也能運作。

    以 2025-12 的水準值為共同錨點，再依各版本的月變動往前推。
    （實務上 2026 年 1–4 月在各版本間也略有差異，示範資料簡化處理。）
    """
    data = build()
    levels = {r["date"]: r["value"] for r in data["PAYEMS"]}
    dates = sorted(levels)
    anchor_date = "2025-12-01"
    if anchor_date not in levels:
        anchor_date = dates[-8]

    base = {d: levels[d] for d in dates if d <= anchor_date}

    out: dict[str, dict[str, float]] = {}
    for vdate, changes in VINTAGE_CHANGES.items():
        series = dict(base)
        cur = series[anchor_date]
        for d in sorted(changes):
            cur += changes[d]
            series[d] = cur
        out[vdate] = series
    return {"PAYEMS": out}


# FRED LNS13023622（Job Losers as a Percent of Total Unemployed）1967-01 起，
# 2026-10 抄錄；只供離線示範，正式執行一律即時抓 FRED。
_JL_HISTORY = {
    1967: "38.7 39.8 39.9 43.0 41.5 42.7 42.2 40.5 41.3 40.7 41.1 40.9",
    1968: "43.9 39.7 39.6 37.9 37.9 33.2 36.7 38.1 38.2 37.9 36.5 34.3",
    1969: "36.1 36.3 36.8 37.4 36.6 35.4 35.7 34.0 33.3 34.8 36.7 39.2",
    1970: "38.8 40.6 41.9 41.9 46.5 44.3 44.7 45.4 46.3 48.2 47.4 47.7",
    1971: "47.0 48.0 45.4 46.6 46.4 46.7 46.4 46.6 46.4 45.6 45.9 45.1",
    1972: "44.4 43.2 42.7 41.1 44.7 44.0 44.2 44.6 43.5 41.7 41.6 41.8",
    1973: "40.8 38.8 38.1 36.8 37.4 39.4 38.0 38.6 38.9 37.1 39.5 40.6",
    1974: "43.7 43.4 43.1 43.0 40.6 40.7 41.3 42.1 42.6 43.8 47.0 49.6",
    1975: "53.3 55.1 55.5 56.4 56.9 58.0 56.6 55.6 57.0 54.5 54.0 51.3",
    1976: "50.3 49.5 51.0 50.2 50.4 50.7 50.2 48.5 48.6 48.4 48.6 49.6",
    1977: "46.3 47.8 46.0 44.9 45.0 43.2 44.9 45.5 44.9 44.5 44.1 43.2",
    1978: "43.4 42.4 41.8 42.5 42.7 40.5 40.9 41.4 39.5 42.1 40.6 40.4",
    1979: "42.3 42.7 42.1 43.0 40.2 40.2 43.0 43.9 42.6 44.8 45.5 44.2",
    1980: "47.8 47.1 47.7 50.4 52.3 53.8 55.2 54.1 54.1 52.7 52.4 53.3",
    1981: "50.2 51.6 49.9 50.4 50.1 51.2 50.2 51.9 52.4 51.8 52.7 55.7",
    1982: "57.3 54.7 57.1 57.7 57.2 59.0 58.4 58.5 60.5 62.6 61.4 60.0",
    1983: "59.8 60.1 60.2 59.9 60.6 58.3 58.3 57.8 57.1 56.0 55.0 54.6",
    1984: "53.6 54.0 52.6 51.5 51.4 51.7 52.2 49.9 50.1 51.5 50.6 50.7",
    1985: "50.8 50.9 49.4 50.2 47.2 49.0 50.5 51.0 50.0 49.2 50.3 49.0",
    1986: "48.2 49.1 49.9 47.9 49.9 50.3 48.9 48.2 49.0 49.2 48.1 49.1",
    1987: "49.7 48.5 48.2 49.0 47.6 48.6 48.4 47.1 46.8 48.6 46.7 45.5",
    1988: "45.2 45.8 45.3 43.8 47.5 47.4 46.8 46.2 47.0 46.4 46.0 46.5",
    1989: "46.2 44.7 45.7 44.8 43.2 42.7 45.3 46.4 44.8 45.9 46.4 46.6",
    1990: "46.7 45.3 46.2 46.5 47.3 47.8 47.7 48.6 49.2 50.1 51.2 50.0",
    1991: "52.7 54.0 54.5 54.3 53.6 54.2 55.1 54.8 55.4 54.2 54.5 55.5",
    1992: "54.0 57.0 57.4 57.3 57.7 56.0 55.7 55.0 55.7 57.7 55.2 54.1",
    1993: "53.6 52.8 55.1 55.0 53.4 54.4 55.0 55.5 54.7 54.6 52.5 53.3",
    1994: "49.6 48.9 48.1 45.3 45.4 47.6 48.1 47.3 47.1 47.2 47.9 47.9",
    1995: "48.0 47.1 47.1 45.3 47.6 46.4 47.0 46.4 45.9 48.1 47.5 46.9",
    1996: "47.6 48.5 47.6 49.2 46.4 47.6 45.9 44.2 45.8 45.0 45.7 43.7",
    1997: "45.0 44.5 45.0 44.7 44.3 45.7 44.0 44.8 44.6 45.3 45.6 47.0",
    1998: "44.5 44.6 46.1 45.2 46.1 45.4 45.7 45.3 45.5 44.9 45.6 46.8",
    1999: "45.6 44.7 45.0 45.0 45.4 44.6 45.1 45.1 43.7 43.7 43.8 42.7",
    2000: "44.0 45.5 43.8 42.2 42.7 43.6 43.4 45.0 45.6 44.3 44.3 45.9",
    2001: "46.4 47.9 49.7 49.4 50.6 51.0 51.2 49.4 51.3 55.4 55.7 53.9",
    2002: "55.2 54.6 53.3 54.1 55.1 55.2 55.1 55.0 55.4 56.0 55.6 55.2",
    2003: "55.2 56.0 55.2 54.5 56.6 54.0 55.4 56.0 55.7 55.1 54.4 54.1",
    2004: "52.0 52.4 53.6 53.2 51.0 49.9 52.1 50.1 50.9 50.7 51.1 50.6",
    2005: "51.7 48.7 48.6 47.3 47.2 48.5 48.2 47.2 49.4 47.8 46.5 47.8",
    2006: "47.5 46.3 48.3 49.2 49.7 48.1 46.2 46.5 46.7 46.4 47.5 47.9",
    2007: "48.6 49.1 47.2 48.8 49.5 48.6 51.3 51.4 49.5 51.0 50.5 50.5",
    2008: "51.0 52.1 53.2 53.1 50.6 51.2 50.9 52.4 54.4 56.6 58.7 59.0",
    2009: "62.4 62.9 64.1 64.8 65.0 64.9 64.7 64.9 65.3 64.7 63.9 63.4",
    2010: "61.9 63.4 63.0 61.5 62.4 62.8 62.1 62.3 62.8 61.3 63.0 61.2",
    2011: "60.1 60.2 60.3 59.4 60.0 58.8 59.2 58.2 58.0 57.9 57.5 57.5",
    2012: "57.1 55.4 55.0 54.2 55.3 56.2 56.2 55.2 54.3 53.8 53.7 52.6",
    2013: "53.8 54.0 53.4 54.1 52.4 52.0 51.7 52.6 52.3 54.9 53.1 51.8",
    2014: "52.9 52.1 51.8 53.4 51.1 50.7 49.6 49.8 49.0 48.2 49.2 49.5",
    2015: "47.7 48.3 49.0 48.6 50.0 49.1 49.6 49.9 48.9 49.8 48.8 47.8",
    2016: "46.5 47.9 48.5 49.5 48.9 48.7 48.9 48.1 48.9 47.6 47.0 48.0",
    2017: "49.0 49.5 49.9 50.2 48.9 49.6 48.9 49.3 48.7 48.9 47.5 49.4",
    2018: "48.8 48.5 47.8 46.8 46.6 47.9 48.2 46.0 46.7 47.0 47.4 46.1",
    2019: "48.0 45.7 45.3 46.0 45.0 45.5 47.2 47.4 45.1 46.6 48.1 47.1",
    2020: "44.3 46.4 57.9 89.5 87.0 80.5 79.1 76.2 72.6 70.1 69.9 67.4",
    2021: "68.4 65.6 63.4 64.4 62.3 60.3 57.4 54.2 53.7 50.9 49.6 48.3",
    2022: "49.4 47.4 45.6 47.8 45.3 43.8 45.7 46.8 44.4 45.5 46.3 45.5",
    2023: "44.4 46.2 49.3 45.8 48.8 47.3 45.3 47.1 45.8 48.3 49.3 48.8",
    2024: "48.7 49.4 47.2 49.2 48.4 47.1 48.9 47.4 47.9 48.6 47.7 47.2",
    2025: "46.7 46.7 46.7 47.6 48.1 47.1 46.2 47.1 46.8 NA 45.7 46.4",
    2026: "46.6 47.6 46.8 47.2 46.2 46.4 47.4",
}


def _job_losers_history() -> list[dict]:
    out = []
    for y, line in _JL_HISTORY.items():
        for m, v in enumerate(line.split(), 1):
            if v != "NA":
                out.append({"date": f"{y}-{m:02d}-01", "value": float(v)})
    return out


# FRED JTSHIR／JTSLDR 2015-01…2020-12（2026-10 抄錄，只供離線示範）
_JOLTS_PRE_H = "3.6 3.6 3.6 3.7 3.6 3.6 3.6 3.6 3.7 3.7 3.8 3.9 3.6 3.8 3.7 3.7 3.6 3.7 3.8 3.7 3.7 3.6 3.7 3.7 3.8 3.7 3.7 3.6 3.7 3.8 3.7 3.8 3.7 3.8 3.7 3.7 3.7 3.8 3.8 3.8 3.9 3.9 3.8 3.9 3.8 4.0 3.9 3.9 3.9 3.8 3.8 4.0 3.8 3.8 3.9 3.9 3.9 3.8 3.9 3.9 3.9 3.9 3.4 3.1 6.1 5.4 4.5 4.3 4.2 4.3 4.1 3.9"
_JOLTS_PRE_L = "1.3 1.2 1.4 1.3 1.2 1.3 1.2 1.2 1.4 1.3 1.2 1.3 1.3 1.3 1.3 1.2 1.3 1.2 1.2 1.3 1.1 1.1 1.2 1.2 1.2 1.2 1.2 1.2 1.2 1.3 1.3 1.3 1.2 1.2 1.2 1.2 1.3 1.2 1.2 1.2 1.2 1.2 1.2 1.2 1.2 1.2 1.3 1.2 1.1 1.2 1.1 1.3 1.2 1.2 1.2 1.2 1.3 1.2 1.2 1.3 1.2 1.3 8.6 7.0 1.6 1.6 1.3 1.1 1.1 1.2 1.5 1.3"


def _jolts_pre(line: str) -> list[dict]:
    return [{"date": f"{2015 + i // 12}-{i % 12 + 1:02d}-01", "value": float(v)}
            for i, v in enumerate(line.split())]
