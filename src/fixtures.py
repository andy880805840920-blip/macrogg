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
    s["LNS13023621"] = _series(d, _interp_recent(
        d, {"2026-07-01": 2050.0, "2026-06-01": 2010.0}, early=2900, noise=35))
    s["LNS13026638"] = _series(d, _interp_recent(
        d, {"2026-07-01": 870.0, "2026-06-01": 905.0}, early=1500, noise=30))
    s["LNS13023653"] = _series(d, _interp_recent(
        d, {"2026-07-01": 640.0}, early=800, noise=25))
    s["LNS13023705"] = _series(d, _interp_recent(
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
