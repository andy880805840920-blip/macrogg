"""
損益兩平就業增速（breakeven payroll growth）。

為什麼這是必要的
----------------
「非農 +2 萬」這個數字單獨看是無法解讀的。

    若每月新增勞動力 10 萬人 → +2 萬代表失業率會上升，就業市場明顯轉弱
    若每月新增勞動力 2 萬人   → +2 萬代表供需大致平衡

換句話說，**同一個數字在不同的勞動供給環境下意義完全相反**。
2025 年後移民政策收緊，勞動供給成長大幅放慢，這個門檻從過去的
10–15 萬掉到可能只剩 0–5 萬——不校準就會系統性高估勞動市場的疲弱程度。

計算方式
--------
    每月損益兩平 ≈ Δ工作年齡人口 × 勞動參與率 × 機構調查／家庭調查就業比

前兩項決定「每個月新增多少人想工作」，第三項把家庭調查的口徑
換算成非農（機構調查）的口徑——兩者統計範圍不同，直接比會有偏誤。

⚠️ 三個必須注意的地方
  1. 人口序列（CNP16OV）每年一月會做人口普查控制調整，出現不連續的跳點。
     所以一律用 12 個月平均的變動，不用單月。
  2. 參與率本身會趨勢性下滑（人口老化），所以用近期平均而非單月。
  3. 這是估計值，不是官方數字。畫面上要標明。
"""

from __future__ import annotations

from dataclasses import dataclass, field


# 一月的人口控制調整會造成跳點，計算變動時要排除
CENSUS_ADJ_MONTH = "01"


@dataclass
class Breakeven:
    monthly: float | None = None          # 每月損益兩平就業（千人）
    pop_growth: float | None = None       # 每月工作年齡人口成長（千人）
    participation: float | None = None    # 使用的參與率（%）
    ces_cps_ratio: float | None = None    # 機構／家庭調查就業比
    nfp_3m: float | None = None           # 非農近三個月平均
    gap: float | None = None              # 非農 − 損益兩平
    verdict: str = "unknown"              # above | balanced | below | unknown
    series: list[dict] = field(default_factory=list)   # 逐月的損益兩平估計
    note: str = ""


def estimate(pop_rows: list[dict], lfpr_rows: list[dict],
             payems_rows: list[dict], cps_emp_rows: list[dict],
             lookback: int = 12) -> Breakeven:
    """
    pop_rows     : CNP16OV  工作年齡人口（千人）
    lfpr_rows    : CIVPART  勞動參與率（%）
    payems_rows  : PAYEMS   非農就業（千人）
    cps_emp_rows : CE16OV   家庭調查就業（千人）
    """
    b = Breakeven()
    if len(pop_rows) < lookback + 2 or not lfpr_rows:
        b.note = "資料不足，無法估計"
        return b

    # ---- 1. 人口成長：排除一月的普查調整跳點，取近 N 個月平均 ----
    deltas = []
    for i in range(1, len(pop_rows)):
        if pop_rows[i]["date"][5:7] == CENSUS_ADJ_MONTH:
            continue            # 一月的跳點是統計口徑調整，不是真實人口變動
        deltas.append({"date": pop_rows[i]["date"],
                       "value": pop_rows[i]["value"] - pop_rows[i - 1]["value"]})
    if len(deltas) < lookback:
        b.note = "人口序列不足"
        return b
    b.pop_growth = sum(d["value"] for d in deltas[-lookback:]) / lookback

    # ---- 2. 參與率：用近期平均，避開單月雜訊 ----
    recent_lfpr = [r["value"] for r in lfpr_rows[-3:]]
    b.participation = sum(recent_lfpr) / len(recent_lfpr)

    # ---- 3. 兩份調查的口徑換算 ----
    if payems_rows and cps_emp_rows:
        p, c = payems_rows[-1]["value"], cps_emp_rows[-1]["value"]
        b.ces_cps_ratio = (p / c) if c else 1.0
    else:
        b.ces_cps_ratio = 1.0

    b.monthly = b.pop_growth * (b.participation / 100) * b.ces_cps_ratio

    # ---- 4. 對照實際的非農三個月平均 ----
    if len(payems_rows) > 4:
        chg = [payems_rows[i]["value"] - payems_rows[i - 1]["value"]
               for i in range(1, len(payems_rows))]
        b.nfp_3m = sum(chg[-3:]) / 3
        b.gap = b.nfp_3m - b.monthly
        if b.gap > 25:
            b.verdict = "above"
        elif b.gap < -25:
            b.verdict = "below"
        else:
            b.verdict = "balanced"

    # ---- 5. 逐月序列，供畫圖 ----
    b.series = _series(deltas, lfpr_rows, b.ces_cps_ratio, lookback)

    b.note = (f"以近 {lookback} 個月平均人口成長 {b.pop_growth/10:,.1f} 萬人／月、"
              f"參與率 {b.participation:.1f}% 估計。"
              "此為推估值，非官方公布數字。")
    return b


def _series(pop_deltas: list[dict], lfpr_rows: list[dict],
            ratio: float, lookback: int) -> list[dict]:
    """逐月的損益兩平估計（滾動 N 個月平均的人口成長 × 當期參與率）。"""
    lfpr_map = {r["date"]: r["value"] for r in lfpr_rows}
    out = []
    for i in range(lookback, len(pop_deltas)):
        window = pop_deltas[i - lookback:i]
        avg = sum(w["value"] for w in window) / lookback
        d = pop_deltas[i]["date"]
        lf = lfpr_map.get(d)
        if lf is None:
            continue
        out.append({"date": d, "value": avg * (lf / 100) * ratio})
    return out


VERDICT_TEXT = {
    "above": ("高於損益兩平", "就業成長快過勞動供給，失業率有下行壓力"),
    "balanced": ("接近損益兩平", "就業成長與勞動供給大致同步，失業率應維持穩定"),
    "below": ("低於損益兩平", "就業成長跟不上勞動供給，失業率有上行壓力"),
    "unknown": ("無法判定", ""),
}
