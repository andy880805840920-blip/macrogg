"""
PPI（生產者物價）發布日的機制（2026-10）。

PPI 原本只出現在通膨頁的 PPI 卡（年增、三月年化）與「管線壓力」訊號（核心 PPI 與
核心 CPI 年增差距 ≥0.5pp）；PPI 公布那天網站幾乎不會把它當成一則新消息。這個模組補上：

  市場預估  從 ForexFactory 週曆抓「PPI 月增」「核心 PPI 月增」的預估，**存檔**
            （state/ppi.json，以資料月份為鍵）——週曆只放本週與下週，過了就查不到，
            但「高於預期」的訊號要留到下一期 PPI 出來
  月增      官方口徑一位小數（指數算出的月增四捨五入到 0.1，跟 BLS 新聞稿一致）
  訊號      有預估：實際月增 − 預估 ≥ 0.2 → 「PPI 高於預期」（偏鷹）；≤ −0.2 → 「低於預期」（偏鴿）
            沒預估：核心 PPI 三月年化 − 年增 ≥ 1pp → 「上游漲價加速」；≤ −1pp → 「上游降溫」
            ——加到通膨模組的訊號清單（通膨頁關鍵訊號、總覽本期變化都看得到）

「本期變化」的 PPI 期別、「本次更新」、快報「最新數據」各自在 changes／brief／stories。
"""
from __future__ import annotations

import json
import logging
import math
import re
from pathlib import Path

from .. import clock

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
STATE_FILE = ROOT / "state" / "ppi.json"

SURPRISE = 0.2          # 實際月增與預估差多少（個百分點）才算「明顯高／低於預期」
ACCEL = 1.0             # 沒預估時：三月年化比年增高／低多少（個百分點）才算加速／降溫
FF_LABEL = {"PPI 月增": "ppi_mom", "核心 PPI 月增": "core_ppi_mom"}
LABEL = {"ppi_mom": "PPI 月增", "core_ppi_mom": "核心 PPI 月增"}


def round1(x: float | None) -> float | None:
    """半進位到一位小數（官方口徑；內建 round() 是銀行家捨入）。"""
    if x is None:
        return None
    return math.floor(abs(x) * 10 + 0.5) / 10 * (1 if x >= 0 else -1)


def _shift(ym: str, n: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    t = y * 12 + (m - 1) + n
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def _num(s) -> float | None:
    m = re.search(r"[-+]?\d+(?:\.\d+)?", str(s or ""))
    return float(m.group()) if m else None


def capture(cons_map: dict, state: dict) -> None:
    """ForexFactory 的 {"ppi|YYYY-MM-DD": [rows]} → state["cons"][資料月份]（覆蓋成最新一版）。"""
    for k, rows in (cons_map or {}).items():
        if not k.startswith("ppi|"):
            continue
        d = k.split("|", 1)[1]
        if len(d) < 7:
            continue
        per = _shift(d[:7], -1)                     # 10 月公布的是 9 月的 PPI
        got = {}
        for r in rows or []:
            f = FF_LABEL.get(r.get("label", ""))
            v = _num(r.get("forecast"))
            if f and v is not None:
                got[f] = v
        if got:
            ent = state.setdefault("cons", {}).setdefault(per, {})
            ent.update(got)
            ent["date"] = d
            ent["at"] = clock.now().isoformat(timespec="minutes")
    # 只留近 12 期
    c = state.get("cons") or {}
    for old in sorted(c)[:-12]:
        c.pop(old, None)


def evaluate(pp: dict, cons: dict | None):
    """回傳 Flag 或 None。pp＝通膨模組的 ppi 字典（含 headline_mom、core_mom、core_3m、core_yoy）。"""
    from .rules import Flag
    act = {"ppi_mom": round1(pp.get("headline_mom")), "core_ppi_mom": round1(pp.get("core_mom"))}
    cons = cons or {}
    diffs = {k: round(act[k] - cons[k], 2) for k in act
             if act.get(k) is not None and cons.get(k) is not None}
    if diffs:
        hot = [k for k, d in diffs.items() if d >= SURPRISE - 1e-9]
        cool = [k for k, d in diffs.items() if d <= -SURPRISE + 1e-9]
        txt = "、".join(f"{LABEL[k]} {act[k]:.1f}%（預估 {cons[k]:.1f}%）" for k in diffs)
        if hot and not cool:
            big = max(diffs[k] for k in hot)
            return Flag("ppi_hot", "watch", "PPI 明顯高於預期",
                        f"{txt}。出廠價漲得比市場預期快，上游成本壓力升溫；"
                        "PPI 的醫療、金融服務分項也直接進核心 PCE，月底的 PCE 可能跟著偏高。",
                        "hawkish", "上游漲價超預期，升息預期易升溫",
                        tier=2, strength=big / SURPRISE)
        if cool and not hot:
            big = max(-diffs[k] for k in cool)
            return Flag("ppi_cool", "info", "PPI 明顯低於預期",
                        f"{txt}。出廠價漲得比市場預期慢，上游成本壓力緩和。",
                        "dovish", "上游漲價低於預期，通膨壓力緩和",
                        tier=2, strength=big / SURPRISE)
        return None
    c3, cy = pp.get("core_3m"), pp.get("core_yoy")
    if c3 is None or cy is None:
        return None
    gap = c3 - cy
    if gap >= ACCEL:
        return Flag("ppi_accel", "watch", "上游漲價加速",
                    f"核心 PPI 三月年化 {c3:.1f}%，比年增 {cy:.1f}% 高 {gap:.1f} 個百分點——"
                    "近三個月出廠價漲得比過去一年快，成本壓力在升溫。",
                    "hawkish", "上游成本壓力升溫", tier=3, strength=gap / ACCEL)
    if gap <= -ACCEL:
        return Flag("ppi_decel", "info", "上游漲價降溫",
                    f"核心 PPI 三月年化 {c3:.1f}%，比年增 {cy:.1f}% 低 {abs(gap):.1f} 個百分點——"
                    "近三個月出廠價漲得比過去一年慢，成本壓力在消退。",
                    "dovish", "上游成本壓力消退", tier=3, strength=-gap / ACCEL)
    return None


def update(ctxs: dict, offline: bool, state_path: Path | None = None, *,
           cons_map: dict | None = None) -> dict | None:
    """
    在通膨模組建好之後、變化比對之前呼叫：補 PPI 月增、市場預估與訊號。
    cons_map＝watch_extra.consensus_map(…)；None 時自己抓 ForexFactory（離線就不抓）。
    """
    inf = ctxs.get("inflation")
    pp = (inf or {}).get("ppi")
    if not pp:
        return None
    sp = state_path or STATE_FILE
    try:
        st = json.loads(sp.read_text(encoding="utf-8"))
        st = st if isinstance(st, dict) else {}
    except Exception:                              # noqa: BLE001
        st = {}
    if cons_map is None and not offline:
        try:
            from . import watch_extra as wx
            cons_map = wx.consensus_map(wx.fetch_ff())
        except Exception as e:                     # noqa: BLE001
            log.info("PPI：ForexFactory 預估抓取失敗（%s），沿用已存的預估", e)
            cons_map = {}
    capture(cons_map or {}, st)
    per = str(pp.get("asof") or "")[:7]
    cons = (st.get("cons") or {}).get(per) or {}
    pp["period"] = per
    pp["mom"] = round1(pp.get("headline_mom"))
    pp["core_mom_1d"] = round1(pp.get("core_mom"))
    pp["cons"] = {k: v for k, v in cons.items() if k in LABEL}
    flag = evaluate(pp, cons)
    if flag is not None:
        flags = [f for f in inf.get("flags") or [] if not f.key.startswith("ppi_")
                 or f.key in ("ppi_pipeline", "ppi_relief")]
        # 插在同一層的最後面，不重排既有訊號（通膨規則有自己的第一層固定先後）
        pos = next((i for i, f in enumerate(flags) if f.tier > flag.tier), len(flags))
        flags.insert(pos, flag)
        inf["flags"] = flags
        try:
            from ..pages.inflation import _tilt
            inf["tilt"] = _tilt(flags)
        except Exception:                          # noqa: BLE001
            pass
        log.info("PPI 訊號：%s（%s）", flag.headline, flag.detail[:80])
    if not offline:
        try:
            sp.parent.mkdir(parents=True, exist_ok=True)
            sp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:                     # noqa: BLE001
            log.warning("PPI 狀態寫入失敗（%s）", e)
    return pp
