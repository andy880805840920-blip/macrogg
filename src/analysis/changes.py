"""
本期變化摘要 — 跟上一期比，什麼變了。

為什麼這是最有價值的一塊
------------------------
對每期都追的人來說，「現在是什麼狀態」的邊際資訊很低——上期看過了。
真正的資訊在**變化**：情境格子有沒有移動、哪些訊號是新出現的、
哪些消失了、分數變化來自哪個指標。

這一層完全靠比對前後兩次執行的快照產生，不需要額外資料源。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ChangeSet:
    has_previous: bool = False
    prev_at: str = ""
    scenario_moved: bool = False
    scenario_from: str = ""
    scenario_to: str = ""
    new_flags: list = field(default_factory=list)        # 本期新出現
    resolved_flags: list = field(default_factory=list)   # 本期消失
    persisting: int = 0
    labor_score_delta: float | None = None
    labor_tilt_from: str = ""
    labor_tilt_to: str = ""
    infl_tilt_from: str = ""
    infl_tilt_to: str = ""
    metric_moves: list = field(default_factory=list)     # [{label, from, to, delta}]
    headline: str = ""


def snapshot(ctxs: dict) -> dict:
    """把本期的關鍵狀態壓成一個可比對的小字典。"""
    import datetime as dt
    snap = {"at": dt.datetime.now().isoformat(timespec="seconds")}

    lab = ctxs.get("labor")
    if lab:
        snap["labor"] = {
            "month": lab["data_month"],
            "score": lab["score"]["score"],
            "tilt": lab["tilt"]["tilt"],
            "flags": [f.key for f in lab["flags"]],
            "flag_titles": {f.key: f.headline for f in lab["flags"]},
            "flag_leans": {f.key: f.lean for f in lab["flags"]},
            "metrics": lab.get("key_metrics", {}),
        }
    inf = ctxs.get("inflation")
    if inf:
        snap["inflation"] = {
            "month": inf["data_month"],
            "tilt": inf["tilt"]["tilt"],
            "flags": [f.key for f in inf["flags"]],
            "flag_titles": {f.key: f.headline for f in inf["flags"]},
            "flag_leans": {f.key: f.lean for f in inf["flags"]},
            "metrics": inf.get("key_metrics", {}),
        }
    scn = ctxs.get("scenario")
    if scn:
        sc = scn["scenario"]
        snap["scenario"] = {"name": sc.name, "labor": sc.labor_state,
                            "inflation": sc.infl_state}
    return snap


def load_previous(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:                     # noqa: BLE001
        return None


def save(path: Path, snap: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def compare(cur: dict, prev: dict | None) -> ChangeSet:
    cs = ChangeSet()
    if not prev:
        cs.headline = "這是第一次執行，還沒有可以比對的上期資料。"
        return cs

    cs.has_previous = True
    cs.prev_at = prev.get("at", "")[:16].replace("T", " ")

    # ---- 情境 ----
    ps, qs = prev.get("scenario"), cur.get("scenario")
    if ps and qs:
        cs.scenario_from, cs.scenario_to = ps["name"], qs["name"]
        cs.scenario_moved = ps["name"] != qs["name"]

    # ---- 訊號的新增與消失 ----
    for mod in ("labor", "inflation"):
        p, c = prev.get(mod), cur.get(mod)
        if not (p and c):
            continue
        pk, ck = set(p.get("flags", [])), set(c.get("flags", []))
        label = "就業" if mod == "labor" else "物價"
        for k in ck - pk:
            cs.new_flags.append({"module": label,
                                 "title": c.get("flag_titles", {}).get(k, k),
                                 "lean": c.get("flag_leans", {}).get(k, "")})
        for k in pk - ck:
            cs.resolved_flags.append({"module": label,
                                      "title": p.get("flag_titles", {}).get(k, k),
                                      "lean": p.get("flag_leans", {}).get(k, "")})
        cs.persisting += len(pk & ck)

    # ---- 傾向與分數 ----
    if prev.get("labor") and cur.get("labor"):
        cs.labor_score_delta = cur["labor"]["score"] - prev["labor"]["score"]
        cs.labor_tilt_from = prev["labor"]["tilt"]
        cs.labor_tilt_to = cur["labor"]["tilt"]
    if prev.get("inflation") and cur.get("inflation"):
        cs.infl_tilt_from = prev["inflation"]["tilt"]
        cs.infl_tilt_to = cur["inflation"]["tilt"]

    # ---- 關鍵數字的移動 ----
    for mod in ("labor", "inflation"):
        p, c = prev.get(mod), cur.get(mod)
        if not (p and c):
            continue
        pm, cm = p.get("metrics") or {}, c.get("metrics") or {}
        for key, meta in cm.items():
            if key not in pm:
                continue
            old, new = pm[key]["value"], meta["value"]
            if old is None or new is None:
                continue
            delta = new - old
            if abs(delta) < meta.get("threshold", 0):
                continue
            cs.metric_moves.append({
                "label": meta.get("label", key),
                "from": old, "to": new, "delta": delta,
                "unit": meta.get("unit", ""),
            })

    cs.headline = _headline(cs)
    return cs


def _headline(cs: ChangeSet) -> str:
    if cs.scenario_moved:
        return f"情境由「{cs.scenario_from}」移動到「{cs.scenario_to}」"
    bits = []
    if cs.new_flags:
        bits.append(f"新觸發 {len(cs.new_flags)} 項訊號")
    if cs.resolved_flags:
        bits.append(f"{len(cs.resolved_flags)} 項訊號解除")
    if not bits:
        return "情境與訊號組成與上期相同"
    return "情境未變，但" + "、".join(bits)
