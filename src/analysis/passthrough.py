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


# 一組相關係數至少要有這麼多個配對月份才算數
_MIN_PAIRS = 18


@dataclass
class Passthrough:
    best_lag: int | None = None          # 薪資領先幾個月
    best_corr: float | None = None
    corr_by_lag: list = field(default_factory=list)   # [{lag, corr}]
    max_lag_evaluated: int | None = None  # 樣本實際撐得住的最長領先期
    max_lag_asked: int = 0                # 原本想測到幾期
    truncated: bool = False               # 想測的期數被樣本長度砍掉了
    n_overlap: int = 0                    # 重疊樣本期數
    corr_note: str = ""                   # 相關係數符號的解讀
    wage_latest: float | None = None
    supercore_latest: float | None = None
    gap: float | None = None             # supercore 年增 − 薪資年增（正＝服務業漲得比薪資快）
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
    # 每多測一期領先，可用的配對就少一筆。樣本只有 n 期時，
    # 領先 n−18 期以上的組合根本湊不到最低配對數，會被靜靜跳過——
    # 於是「測到 18 個月」變成一句沒有兌現的話。這裡先算清楚實際能測到哪，
    # 再把它寫進結果，畫面上才不會宣稱一個沒做過的檢定。
    p.n_overlap = len(dates)
    p.max_lag_asked = max_lag
    p.max_lag_evaluated = max(0, min(max_lag, len(dates) - _MIN_PAIRS))
    p.truncated = p.max_lag_evaluated < max_lag

    for lag in range(0, p.max_lag_evaluated + 1):
        pairs = []
        for i in range(lag, len(dates)):
            w = wmap.get(dates[i - lag])
            s = smap.get(dates[i])
            if w is not None and s is not None:
                pairs.append((w, s))
        if len(pairs) < _MIN_PAIRS:
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
        bits = [f"在 0 到 {p.max_lag_evaluated} 個月的範圍內，"
                f"相關性最強的組合是薪資領先 {p.best_lag} 個月"
                f"（相關係數 {p.best_corr:+.2f}）。"]
        if p.truncated:
            bits.append(
                f"原本要測到 {p.max_lag_asked} 個月，但重疊樣本只有 "
                f"{p.n_overlap} 期——領先愈久，能配對的月份就愈少，"
                f"超過 {p.max_lag_evaluated} 個月的組合湊不到最低 {_MIN_PAIRS} 組配對，"
                "沒有納入檢定。真正的峰值有可能落在這個範圍之外。")
        bits.append("相關不等於因果，這只描述兩者在此樣本中的時間關係。")
        p.note = "".join(bits)

        # 符號要講清楚。負相關代表「薪資高的時期對應 supercore 低」，
        # 那是在**反駁**薪資推升服務業通膨的機制，不是佐證它。
        if p.best_corr < -0.3:
            # 這段話很重要但先前寫得太長（142 字），擋在閱讀動線上。
            # 該講的只有兩件事：符號是反的、原因是共同趨勢。
            p.corr_note = (
                f"相關係數是負的：薪資高的月份，{p.best_lag} 個月後的服務業通膨"
                "反而較低，方向與「薪資推升通膨」相反。樣本只涵蓋通膨自高點"
                "回落這一段，兩條線同時下行就足以做出負相關——不能當因果讀。")
        elif abs(p.best_corr) < 0.3:
            p.corr_note = ("相關係數接近零，這段樣本看不出穩定的領先落後關係，"
                           "下方的領先期數不宜當作預測依據。")
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
