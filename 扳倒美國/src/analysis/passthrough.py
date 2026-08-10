"""
薪資到服務業通膨的傳導（labour → inflation bridge）。

為什麼這是兩個模組真正的連結
----------------------------
核心服務除住房（supercore）的成本主體是人力。所以薪資的走向，
會在幾個月到一年之後反映到這一塊的通膨上。

這是判斷「通膨的黏性會不會持續」的核心機制：
  * 薪資降溫但 supercore 還高 → 通膨的下行還沒走完，會繼續降
  * 薪資回升而 supercore 已低 → 服務業通膨有再起的風險

沒有這一層，勞動模組與通膨模組就只是兩個各自獨立的儀表板。

方法
----
把兩條序列都轉成年增率後做交叉相關（cross-correlation），
找出「薪資領先 supercore 幾個月時相關性最高」。
相關不等於因果，但它至少告訴你在這個樣本裡兩者的時間關係。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Passthrough:
    best_lag: int | None = None          # 薪資領先幾個月
    best_corr: float | None = None
    corr_by_lag: list = field(default_factory=list)   # [{lag, corr}]
    wage_latest: float | None = None
    supercore_latest: float | None = None
    gap: float | None = None             # 薪資年增 − supercore 年化
    verdict: str = "unknown"
    series: list = field(default_factory=list)        # 疊圖用
    note: str = ""


def analyse(wage_yoy: list[dict], supercore_yoy: list[dict],
            max_lag: int = 18) -> Passthrough:
    """
    wage_yoy      : 薪資年增率序列（平均時薪或 ECI）
    supercore_yoy : 核心服務除住房的年增率序列
    """
    p = Passthrough()
    wmap = {r["date"]: r["value"] for r in wage_yoy}
    smap = {r["date"]: r["value"] for r in supercore_yoy}
    dates = sorted(set(wmap) & set(smap))
    if len(dates) < 24:
        p.note = "重疊樣本不足，無法估計領先落後關係"
        return p

    # ---- 交叉相關：薪資落後 lag 期去對 supercore ----
    for lag in range(0, max_lag + 1):
        pairs = []
        for i in range(lag, len(dates)):
            w = wmap.get(dates[i - lag])
            s = smap.get(dates[i])
            if w is not None and s is not None:
                pairs.append((w, s))
        if len(pairs) < 18:
            continue
        c = _corr([a for a, _ in pairs], [b for _, b in pairs])
        if c is None:
            continue
        p.corr_by_lag.append({"lag": lag, "corr": c})
        if p.best_corr is None or abs(c) > abs(p.best_corr):
            p.best_corr, p.best_lag = c, lag

    p.wage_latest = wmap[dates[-1]]
    p.supercore_latest = smap[dates[-1]]
    p.gap = p.supercore_latest - p.wage_latest

    # ---- 判定 ----
    if p.gap is not None:
        if p.gap > 0.8:
            p.verdict = "supercore_above"
        elif p.gap < -0.8:
            p.verdict = "wage_above"
        else:
            p.verdict = "aligned"

    p.series = [{"date": d, "wage": wmap[d], "supercore": smap[d]}
                for d in dates[-60:]]

    if p.best_lag is not None:
        p.note = (f"樣本內相關性最高的組合是薪資領先 {p.best_lag} 個月"
                  f"（相關係數 {p.best_corr:+.2f}）。"
                  "相關不等於因果，這只描述兩者在此樣本中的時間關係。")
    return p


def _corr(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 6:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = sum((x - ma) ** 2 for x in a) ** 0.5
    db = sum((y - mb) ** 2 for y in b) ** 0.5
    if da == 0 or db == 0:
        return None
    return num / (da * db)


VERDICT_TEXT = {
    "supercore_above": (
        "服務業通膨高於薪資增速",
        "服務業的漲價幅度超過人力成本的上升，除了薪資之外還有其他推力"
        "（例如租金、保險或訂價能力）。單靠薪資降溫不足以讓它回落。"),
    "wage_above": (
        "薪資增速高於服務業通膨",
        "人力成本上升的部分尚未完全轉嫁到售價。若企業後續調價，"
        "服務業通膨有上行的風險。"),
    "aligned": (
        "薪資與服務業通膨大致同步",
        "兩者的增速接近，代表服務業的漲價主要反映人力成本，沒有額外的推力。"),
    "unknown": ("資料不足", ""),
}
