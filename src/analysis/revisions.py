"""
修正追蹤 — 這個模組的價值在於回答：
  「這次的『超預期』有多少是被前兩個月的下修吃掉的？」

兩種資料來源，優先順序：
  1. ALFRED vintage（官方歷史版本，最完整）
  2. 本地快照比對（第二次執行起可用，ALFRED 掛掉時的後備）
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MonthRevision:
    obs_date: str
    original: float | None      # 初值（月變動）
    current: float              # 目前值（月變動）
    net: float | None           # current - original


@dataclass
class RevisionResult:
    series_id: str
    recent: list[MonthRevision] = field(default_factory=list)
    # 兩種口徑，不要混用：
    #   two_month_net  = 相對「上一次發布」的修正 → 這是 BLS 新聞稿講的數字
    #   cumulative_net = 相對「初值」的累計修正   → 通常更大，反映完整修正史
    two_month_net: float | None = None
    cumulative_net: float | None = None
    bias_12m: float | None = None           # 近 12 個月「初值→現行」的平均修正
    bias_direction: str = "unknown"
    ma3_now: float | None = None
    ma3_before_revision: float | None = None
    source: str = "none"                    # alfred | snapshot | none


def _levels_to_changes(levels: dict[str, float]) -> dict[str, float]:
    """把水準值字典轉成月變動字典。"""
    dates = sorted(levels)
    out = {}
    for i in range(1, len(dates)):
        out[dates[i]] = levels[dates[i]] - levels[dates[i - 1]]
    return out


def from_vintages(
    series_id: str,
    vintages: dict[str, dict[str, float]],
    current_rows: list[dict],
    n_months: int = 12,
) -> RevisionResult:
    """
    vintages : {vintage_date: {obs_date: level}}  來自 ALFRED
    """
    res = RevisionResult(series_id=series_id)
    if not vintages:
        return res

    res.source = "alfred"
    vdates = sorted(vintages)

    # 每個觀測月的「初值」＝最早那個包含它的 vintage 裡的月變動
    first_change: dict[str, float] = {}
    for vd in vdates:
        ch = _levels_to_changes(vintages[vd])
        for obs, val in ch.items():
            first_change.setdefault(obs, val)

    current_levels = {r["date"]: r["value"] for r in current_rows}
    current_change = _levels_to_changes(current_levels)

    obs_dates = sorted(current_change)[-n_months:]
    for obs in obs_dates:
        orig = first_change.get(obs)
        cur = current_change[obs]
        res.recent.append(
            MonthRevision(obs_date=obs, original=orig, current=cur,
                          net=None if orig is None else cur - orig)
        )

    # 上一次發布的版本（倒數第二個 vintage）— BLS 口徑的修正就是跟它比
    prev_release_change: dict[str, float] = {}
    if len(vdates) >= 2:
        prev_release_change = _levels_to_changes(vintages[vdates[-2]])

    _finalize(res, current_change, prev_release_change)
    return res


def from_snapshots(
    series_id: str,
    previous: dict[str, float],
    current_rows: list[dict],
    n_months: int = 12,
) -> RevisionResult:
    """
    後備方案：拿上一次執行的快照跟這次比。
    只能看出「上次到這次」的修正，看不到更早的修正史。
    """
    res = RevisionResult(series_id=series_id)
    if not previous:
        return res

    res.source = "snapshot"
    current_levels = {r["date"]: r["value"] for r in current_rows}
    prev_change = _levels_to_changes(previous)
    cur_change = _levels_to_changes(current_levels)

    for obs in sorted(cur_change)[-n_months:]:
        orig = prev_change.get(obs)
        res.recent.append(
            MonthRevision(obs_date=obs, original=orig, current=cur_change[obs],
                          net=None if orig is None else cur_change[obs] - orig)
        )

    # 快照模式下，「上次執行」就是「上一次發布」，兩種口徑相同
    _finalize(res, cur_change, prev_change)
    return res


def _finalize(res: RevisionResult, current_change: dict[str, float],
              prev_release_change: dict[str, float]) -> None:
    """計算合計修正、系統性偏誤，以及三個月均值的修正前後對照。"""
    revised = [r for r in res.recent if r.net is not None]

    # 本次發布修正的是「前兩個月」，也就是倒數第 2、3 筆
    if len(res.recent) >= 3:
        prior_two = res.recent[-3:-1]

        # (1) BLS 口徑：相對上一次發布
        if prev_release_change:
            deltas = [current_change[r.obs_date] - prev_release_change[r.obs_date]
                      for r in prior_two
                      if r.obs_date in prev_release_change and r.obs_date in current_change]
            if deltas:
                res.two_month_net = sum(deltas)

        # (2) 累計口徑：相對初值
        cum = [r.net for r in prior_two if r.net is not None]
        if cum:
            res.cumulative_net = sum(cum)

        # 沒有上一版可比時，退而用累計值，並在畫面上標明口徑
        if res.two_month_net is None:
            res.two_month_net = res.cumulative_net

    if len(revised) >= 6:
        res.bias_12m = sum(r.net for r in revised) / len(revised)
        if res.bias_12m < -5:
            res.bias_direction = "systematically_down"
        elif res.bias_12m > 5:
            res.bias_direction = "systematically_up"
        else:
            res.bias_direction = "neutral"

    # 三個月均值：修正後 vs 若前兩月維持上一版的值
    dates = sorted(current_change)
    if len(dates) >= 3:
        last3 = dates[-3:]
        res.ma3_now = sum(current_change[d] for d in last3) / 3

        rev_by_date = {r.obs_date: r for r in res.recent}
        hypo = []
        for i, d in enumerate(last3):
            # 最新一個月本身就是初值，沒有「修正前」可言
            if i == 2:
                hypo.append(current_change[d])
                continue
            if d in prev_release_change:
                hypo.append(prev_release_change[d])
            else:
                r = rev_by_date.get(d)
                hypo.append(r.original if r and r.original is not None
                            else current_change[d])
        res.ma3_before_revision = sum(hypo) / 3
