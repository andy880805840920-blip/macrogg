"""
Regime 紅綠燈 + 綜合評分。

設計原則
--------
* 門檻寫在 config 裡，不寫死在程式碼，方便你依經驗調整。
* 燈號一律附帶「文字狀態」，不靠顏色單獨傳達（顏色 + 圖示 + 文字）。
* 綜合分數用 z-score 加權，並保留每個指標的貢獻，讓分數可解釋。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .core import (sahm_rule, moving_avg, value_at, zscore,
                   zscore_window, diff_series)
from .. import fmt


STATUS_LABEL = {"good": "健康", "warning": "留意", "critical": "警戒", "unknown": "無資料"}


@dataclass
class Light:
    key: str
    label: str
    desc: str
    value: float | None
    prev: float | None
    status: str            # good | warning | critical | unknown
    display: str           # 格式化後的顯示字串
    delta_dir: str = "flat"   # up | down | flat
    # 歷史狀態軌跡。只看當期無法分辨「連續惡化」與「剛轉黃」。
    history: list = field(default_factory=list)   # [{date, status, label}]


def _classify(value: float | None, cfg: dict) -> str:
    if value is None:
        return "unknown"
    if cfg["direction"] == "higher_is_worse":
        if "green_below" in cfg and value < cfg["green_below"]:
            return "good"
        if "red_above" in cfg and value > cfg["red_above"]:
            return "critical"
        return "warning"
    else:  # lower_is_worse
        if "green_above" in cfg and value > cfg["green_above"]:
            return "good"
        if "red_below" in cfg and value < cfg["red_below"]:
            return "critical"
        return "warning"


# 各燈號歷史值的顯示格式，須與 _compute_light_values 的 display 格式一致
_HISTORY_LABEL_FMT = {
    "sahm": lambda v: f"{v:+.2f}",
    "vu_ratio": lambda v: f"{v:.2f}",
    "quits_rate": lambda v: f"{v:.1f}%",
    "layoff_rate": lambda v: f"{v:.1f}%",
    "prime_epop": lambda v: f"{v:.1f}%",
    "continuing_claims": lambda v: fmt.persons_to_wan(v, digits=0),
    "nfp_3m_avg": lambda v: fmt.wan(v),
    "u6_u3_gap": lambda v: f"{v:.2f}pp",
}


def build_lights(series: dict[str, list[dict]], light_cfgs: list[dict],
                 histories: dict[str, list[dict]] | None = None) -> list[Light]:
    """依 config 產生所有燈號。缺資料的指標顯示為 unknown，不會讓流程中斷。"""
    computed = _compute_light_values(series)
    histories = histories if histories is not None else light_histories(series)
    out: list[Light] = []

    for cfg in light_cfgs:
        key = cfg["key"]
        val, prev, display = computed.get(key, (None, None, "—"))
        status = _classify(val, cfg)
        if val is not None and prev is not None:
            delta = val - prev
            direction = "up" if delta > 1e-9 else ("down" if delta < -1e-9 else "flat")
        else:
            direction = "flat"
        # 軌跡條 tooltip 的數字要跟卡片本身同一種格式——
        # 例如續領失業金卡片顯示「192 萬人」，tooltip 若顯示原始值
        # 「1917000.00」，讀者會以 10 倍、100 倍的錯誤尺度解讀。
        label_fmt = _HISTORY_LABEL_FMT.get(key, lambda v: f"{v:.2f}")
        hist = [
            {"date": h["date"], "status": _classify(h["value"], cfg),
             "label": label_fmt(h["value"])}
            for h in (histories.get(key) or [])
        ]
        out.append(
            Light(key=key, label=cfg["label"], desc=cfg.get("desc", ""),
                  value=val, prev=prev, status=status, display=display,
                  delta_dir=direction, history=hist)
        )
    return out


def light_histories(s: dict[str, list[dict]], n: int = 12) -> dict[str, list[dict]]:
    """
    每個燈號最近 n 期的數值，用來畫狀態軌跡條。

    只呈現當期狀態時，讀者分不出「連續三個月惡化」與「這個月剛轉黃」，
    而那兩者的意義差很多。
    """
    out: dict[str, list[dict]] = {}

    unrate = s.get("UNRATE", [])
    if len(unrate) > 16:
        out["sahm"] = [
            {"date": unrate[-(n - i)]["date"],
             "value": sahm_rule(unrate[:len(unrate) - (n - 1 - i)])}
            for i in range(n)
        ]
        out["sahm"] = [h for h in out["sahm"] if h["value"] is not None]

    jol, unemp = s.get("JTSJOL", []), s.get("UNEMPLOY", [])
    if jol and unemp:
        umap = {r["date"]: r["value"] for r in unemp}
        pairs = [{"date": r["date"], "value": r["value"] / umap[r["date"]]}
                 for r in jol if r["date"] in umap and umap[r["date"]]]
        out["vu_ratio"] = pairs[-n:]

    for key, sid in (("quits_rate", "JTSQUR"), ("layoff_rate", "JTSLDR"),
                     ("prime_epop", "LNS12300060"), ("continuing_claims", "CCSA")):
        rows = s.get(sid, [])
        if rows:
            out[key] = [{"date": r["date"], "value": r["value"]} for r in rows[-n:]]

    payems = s.get("PAYEMS", [])
    if len(payems) > n + 4:
        ch = diff_series(payems)
        out["nfp_3m"] = []
        out["nfp_3m_avg"] = [
            {"date": ch[i]["date"],
             "value": sum(c["value"] for c in ch[i - 2:i + 1]) / 3}
            for i in range(len(ch) - n, len(ch))
        ]
        out.pop("nfp_3m")

    u3, u6 = s.get("UNRATE", []), s.get("U6RATE", [])
    if u3 and u6:
        m3 = {r["date"]: r["value"] for r in u3}
        pairs = [{"date": r["date"], "value": r["value"] - m3[r["date"]]}
                 for r in u6 if r["date"] in m3]
        out["u6_u3_gap"] = pairs[-n:]

    return out


def _compute_light_values(s: dict[str, list[dict]]) -> dict[str, tuple]:
    """把原始序列換算成各燈號要用的數值。回傳 {key: (現值, 前值, 顯示字串)}"""
    out: dict[str, tuple] = {}

    # --- Sahm Rule ---
    unrate = s.get("UNRATE", [])
    if unrate:
        cur = sahm_rule(unrate)
        prev = sahm_rule(unrate[:-1]) if len(unrate) > 14 else None
        out["sahm"] = (cur, prev, f"{cur:+.2f}" if cur is not None else "—")

    # --- V/U ratio（JOLTS 落後兩個月，要對齊到同一個月）---
    jol, unemp = s.get("JTSJOL", []), s.get("UNEMPLOY", [])
    if jol and unemp:
        umap = {r["date"]: r["value"] for r in unemp}
        pairs = [(r["date"], r["value"] / umap[r["date"]])
                 for r in jol if r["date"] in umap and umap[r["date"]]]
        if pairs:
            cur = pairs[-1][1]
            prev = pairs[-2][1] if len(pairs) > 1 else None
            out["vu_ratio"] = (cur, prev, f"{cur:.2f}")

    # --- 簡單的水準型燈號 ---
    for key, sid, pattern in [
        ("quits_rate", "JTSQUR", "{:.1f}%"),
        ("layoff_rate", "JTSLDR", "{:.1f}%"),
        ("prime_epop", "LNS12300060", "{:.1f}%"),
    ]:
        rows = s.get(sid, [])
        if rows:
            cur, prev = value_at(rows, 0), value_at(rows, 1)
            out[key] = (cur, prev, pattern.format(cur) if cur is not None else "—")

    # --- 續領失業金 ---
    cc = s.get("CCSA", [])
    if cc:
        cur, prev = value_at(cc, 0), value_at(cc, 1)
        out["continuing_claims"] = (cur, prev,
                                   fmt.persons_to_wan(cur, digits=0) if cur else "—")

    # --- 非農三個月均值 ---
    payems = s.get("PAYEMS", [])
    if len(payems) > 4:
        ch = diff_series(payems)
        cur = moving_avg(ch, 3)
        prev = moving_avg(ch[:-1], 3)
        out["nfp_3m_avg"] = (cur, prev, fmt.wan(cur))

    # --- U-6 與 U-3 的差距 ---
    u3, u6 = s.get("UNRATE", []), s.get("U6RATE", [])
    if u3 and u6:
        m3 = {r["date"]: r["value"] for r in u3}
        pairs = [(r["date"], r["value"] - m3[r["date"]]) for r in u6 if r["date"] in m3]
        if pairs:
            cur = pairs[-1][1]
            prev = pairs[-2][1] if len(pairs) > 1 else None
            out["u6_u3_gap"] = (cur, prev, f"{cur:.2f} 個百分點")

    return out


# ---------------------------------------------------------------------------
# 綜合評分 — 每個指標的 z-score 加權相加，並保留逐項貢獻
# ---------------------------------------------------------------------------

# P3 之後這組權重會改由「歷史迴歸對利率定價的解釋力」校準。
# 現階段先用等權重的變體：把資訊量較高的指標給高一點的權重。
# 週頻序列。z-score 窗口換算成月時要除以每月約 4.345 週。
_WEEKLY = {"CCSA", "ICSA"}

DEFAULT_WEIGHTS = {
    "PAYEMS": 1.0,
    "UNRATE": 1.0,
    "CCSA": 0.8,
    "JTSQUR": 0.8,
    "LNS12300060": 0.6,
    "JTSLDR": 0.6,
    "ICSA": 0.4,
    "U6RATE": 0.4,
}


@dataclass
class ScoreItem:
    series_id: str
    label: str
    z: float
    weight: float
    contribution: float
    inverted: bool
    window: int = 0          # 這一條的 z-score 實際用了幾個月


@dataclass
class CompositeScore:
    score: float
    prev_score: float | None
    items: list[ScoreItem] = field(default_factory=list)
    window: int = 0            # z-score 實際用到的期數（月），供畫面誠實標示

    @property
    def delta(self) -> float | None:
        return None if self.prev_score is None else self.score - self.prev_score


def composite_score(series: dict[str, list[dict]], labels: dict[str, str],
                    invert_flags: dict[str, bool],
                    weights: dict[str, float] | None = None) -> CompositeScore:
    """
    正分＝勞動市場偏強，負分＝偏弱。

    對 invert=True 的指標（失業率、裁員率等）翻轉符號，讓所有指標
    的「正值」都代表勞動市場強勁，這樣加總才有意義。
    """
    weights = weights or DEFAULT_WEIGHTS
    items: list[ScoreItem] = []
    total_w = 0.0
    total = 0.0
    windows: list[int] = []          # 各序列實際用到的期數，供畫面誠實標示

    for sid, w in weights.items():
        rows = series.get(sid, [])
        # 流量型序列（就業水準）要先轉成月變動再算 z-score
        use = diff_series(rows) if sid in ("PAYEMS", "USPRIV") else rows
        z = zscore(use)
        if z is None:
            continue
        # 週資料（CCSA/ICSA）一筆是一週，不能跟月資料的筆數混在一起取 min——
        # 60 筆週資料只有 14 個月，卻會被當成 60 期而蓋過真正最短的那條。
        # 一律換算成「月」再比較。
        n = zscore_window(use)
        n_month = round(n / 4.345) if sid in _WEEKLY else n
        windows.append(n_month)
        inv = invert_flags.get(sid, False)
        signed = -z if inv else z
        items.append(ScoreItem(sid, labels.get(sid, sid), z, w, signed * w, inv,
                               window=n_month))
        total += signed * w
        total_w += w

    score = total / total_w if total_w else 0.0
    items.sort(key=lambda i: abs(i.contribution), reverse=True)

    # 上期分數：把每個序列倒退「一個月」重算。
    # 週資料倒退一筆只是倒退一週，畫面上卻標成「較上月」——
    # 量測過的差距不只大小不同，連正負號都會相反。週資料要倒退四筆。
    _back = {sid: (4 if sid in _WEEKLY else 1) for sid in series}
    prev_series = {k: v[:-_back.get(k, 1)]
                   for k, v in series.items() if len(v) > _back.get(k, 1)}
    prev = None
    if prev_series:
        pt, pw = 0.0, 0.0
        for sid, w in weights.items():
            rows = prev_series.get(sid, [])
            use = diff_series(rows) if sid in ("PAYEMS", "USPRIV") else rows
            z = zscore(use)
            if z is None:
                continue
            signed = -z if invert_flags.get(sid, False) else z
            pt += signed * w
            pw += w
        prev = pt / pw if pw else None

    # 窗口取各序列的最小值——分數是加總的，最短的那條決定了整體可信度。
    # 但畫面不能拿這個最小值去描述每一列：多數序列用的是 60 個月，
    # 只有週資料被壓到十幾個月，說成「全部都是近 14 個月」會錯得離譜。
    return CompositeScore(score=score, prev_score=prev, items=items,
                          window=min(windows) if windows else 0)
