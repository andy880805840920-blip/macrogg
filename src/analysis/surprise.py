"""
市場預期與意外值（surprise）。

為什麼需要
----------
「非農 −2.3 萬」單獨看少了最重要的參照點：**市場原本以為會是多少**。
市場只對「意外」反應，不對「水準」反應——預期 −5 萬而公布 −2.3 萬，
是利空出盡；預期 +8.5 萬而公布 −2.3 萬，才是重擊。

三種預期來源，優先順序由高到低
------------------------------
  1. 手動輸入（config/consensus.yaml）— 你在發布前把 Bloomberg／
     Reuters 的市場預期填進去。最準確。
  2. 爬取的公開預期 — 由 src/consensus_source.py 提供，穩定性較差。
  3. **時間序列模型的預測值** — 一律可用的後備。這不是市場預期，
     是「若照歷史規律外推應該是多少」，兩者意義不同，畫面上會標明來源。

意外值一律標準化：(實際 − 預期) ÷ 歷史意外的標準差。
標準化後才能跨指標比較——非農差 5 萬與失業率差 0.1pp 哪個比較意外，
不標準化是無法回答的。
"""

from __future__ import annotations

from dataclasses import dataclass


SOURCE_LABEL = {
    "manual": "手動輸入的市場預期",
    "scraped": "公開來源的市場預期",
    "model": "時間序列模型推估（非市場預期）",
    "none": "無預期資料",
}


@dataclass
class Surprise:
    label: str
    actual: float | None = None
    expected: float | None = None
    diff: float | None = None
    z: float | None = None            # 標準化意外值
    source: str = "none"
    unit: str = ""
    verdict: str = "inline"           # beat | miss | inline
    note: str = ""

    @property
    def source_label(self) -> str:
        return SOURCE_LABEL.get(self.source, self.source)


def ar_forecast(series: list[dict], order: int = 3) -> float | None:
    """
    以 AR(p) 的最小平方解預測下一期。

    這是「若照歷史規律外推」的值，**不是市場預期**。
    用途是在沒有真實預期時仍能算出一個參照點，並在畫面上標明來源。
    """
    vals = [r["value"] for r in series]
    if len(vals) < order * 3 + 5:
        return None

    # 建立設計矩陣（含常數項）
    X, y = [], []
    for i in range(order, len(vals)):
        X.append([1.0] + vals[i - order:i])
        y.append(vals[i])

    beta = _ols(X, y)
    if beta is None:
        return None
    last = [1.0] + vals[-order:]
    return sum(b * x for b, x in zip(beta, last))


def _ols(X: list[list[float]], y: list[float]) -> list[float] | None:
    """純 Python 的最小平方解（正規方程 + 高斯消去）。維度很小，夠用。"""
    k = len(X[0])
    xtx = [[sum(X[r][i] * X[r][j] for r in range(len(X))) for j in range(k)]
           for i in range(k)]
    xty = [sum(X[r][i] * y[r] for r in range(len(X))) for i in range(k)]

    # 高斯消去（含部分樞軸）
    for i in range(k):
        piv = max(range(i, k), key=lambda r: abs(xtx[r][i]))
        if abs(xtx[piv][i]) < 1e-12:
            return None
        xtx[i], xtx[piv] = xtx[piv], xtx[i]
        xty[i], xty[piv] = xty[piv], xty[i]
        for r in range(i + 1, k):
            f = xtx[r][i] / xtx[i][i]
            for c in range(i, k):
                xtx[r][c] -= f * xtx[i][c]
            xty[r] -= f * xty[i]
    beta = [0.0] * k
    for i in reversed(range(k)):
        beta[i] = (xty[i] - sum(xtx[i][j] * beta[j]
                                for j in range(i + 1, k))) / xtx[i][i]
    return beta


def historical_sd(series: list[dict], order: int = 3, window: int = 36) -> float | None:
    """歷史上「實際 vs 模型預測」的標準差，用來標準化意外值。"""
    vals = [r["value"] for r in series]
    if len(vals) < order * 3 + 10:
        return None
    errs = []
    start = max(order * 3 + 5, len(vals) - window)
    for i in range(start, len(vals)):
        f = ar_forecast([{"value": v} for v in vals[:i]], order)
        if f is not None:
            errs.append(vals[i] - f)
    if len(errs) < 6:
        return None
    m = sum(errs) / len(errs)
    var = sum((e - m) ** 2 for e in errs) / max(len(errs) - 1, 1)
    return var ** 0.5


def evaluate(label: str, series: list[dict], consensus: float | None,
             source: str, unit: str = "", higher_is_better: bool = True,
             order: int = 3) -> Surprise:
    """
    consensus 為 None 時自動退回模型推估，並把 source 標成 model。
    """
    if not series:
        return Surprise(label=label, unit=unit)

    actual = series[-1]["value"]
    expected, src = consensus, source
    if expected is None:
        expected = ar_forecast(series[:-1], order)
        src = "model" if expected is not None else "none"

    s = Surprise(label=label, actual=actual, expected=expected,
                 source=src, unit=unit)
    if expected is None:
        return s

    s.diff = actual - expected
    sd = historical_sd(series, order)
    if sd:
        s.z = s.diff / sd

    thresh = (sd * 0.5) if sd else abs(expected) * 0.05
    if s.diff > thresh:
        s.verdict = "beat" if higher_is_better else "miss"
    elif s.diff < -thresh:
        s.verdict = "miss" if higher_is_better else "beat"
    else:
        s.verdict = "inline"

    s.note = ("標準化後 "
              + (f"{s.z:+.1f} 個標準差" if s.z is not None else "（標準差不足無法標準化）"))
    return s


VERDICT_TEXT = {
    "beat": "優於預期",
    "miss": "不如預期",
    "inline": "符合預期",
}
