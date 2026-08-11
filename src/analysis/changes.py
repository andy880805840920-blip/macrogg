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
    regime_changed: bool = False    # 聯準會的重心（哪個使命優先）翻轉
    headline: str = ""
    # 對照的是哪一版**資料**，不是哪一次執行。排程每天跑、資料一個月出一次，
    # 用執行時間當基準會讓「對照今天早上 05:01」這種毫無意義的字串出現在
    # 最顯眼的位置，還會讓人以為核心 CPI 在一小時內掉了 0.5 個百分點。
    prev_vintage: dict = field(default_factory=dict)
    cur_vintage: dict = field(default_factory=dict)
    data_changed: bool = False      # 有沒有任何一個模組拿到新一期的資料
    n_dovish: int = 0               # 本期偏鴿方向的變化筆數
    n_hawkish: int = 0
    net_lean: str = "neutral"       # dovish / hawkish / mixed / neutral


def snapshot(ctxs: dict) -> dict:
    """把本期的關鍵狀態壓成一個可比對的小字典。"""
    import datetime as dt
    snap = {"at": dt.datetime.now().isoformat(timespec="seconds")}

    # 資料版本：比對的基準要用這個，不是上面那個執行時間。
    vintage = {}
    if ctxs.get("labor"):
        vintage["labor"] = ctxs["labor"]["data_month"]
    if ctxs.get("inflation"):
        vintage["inflation"] = ctxs["inflation"]["data_month"]
    if ctxs.get("fomc") and not ctxs["fomc"].get("empty"):
        vintage["fomc"] = ctxs["fomc"]["latest_date"]
    snap["vintage"] = vintage

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
        # 九宮格改成「一個體制一張」之後，格名本身就是結論：
        # 重心從通膨優先翻成就業優先時，同一個格位的名字會直接變
        #（例如「停滯性通膨：通膨優先」→「停滯性通膨：救就業」），
        # 所以只比 name 就抓得到體制翻轉，不需要另外存修正前後兩份。
        snap["scenario"] = {"name": sc.name, "grid_name": sc.name,
                            "regime": sc.regime,
                            "labor": sc.labor_state,
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


def _invert(lean: str) -> str:
    """訊號消失時，它對利率的意涵要反過來。中性維持中性。"""
    return {"hawkish": "dovish", "dovish": "hawkish"}.get(lean, lean)


def compare(cur: dict, prev: dict | None) -> ChangeSet:
    cs = ChangeSet()
    if not prev:
        cs.headline = "這是第一次執行，還沒有可以比對的上期資料。"
        return cs

    cs.has_previous = True
    cs.prev_at = prev.get("at", "")[:16].replace("T", " ")
    cs.prev_vintage = prev.get("vintage") or {}
    cs.cur_vintage = cur.get("vintage") or {}
    # 舊快照沒有 vintage 欄位——那種情況無從判斷，當成「有變」以免誤報
    #「沒有新資料」而其實有。
    cs.data_changed = (cs.prev_vintage != cs.cur_vintage
                       if cs.prev_vintage else True)

    # ---- 情境 ----
    ps, qs = prev.get("scenario"), cur.get("scenario")
    if ps and qs:
        cs.scenario_from, cs.scenario_to = ps["name"], qs["name"]
        # 名字變了就算移動——可能是格位移動，也可能是重心翻轉
        #（格位沒動但那一格在新體制下叫別的名字）。兩者都值得報。
        moved_name = ps["name"] != qs["name"]
        same_cell = (ps.get("labor"), ps.get("inflation")) == \
                    (qs.get("labor"), qs.get("inflation"))
        # 只有一種情況要壓下來：舊版快照存的是「修正後結論」而非格名，
        # 改版後第一次執行會冒出一次假的移動。舊快照沒有 regime 欄位，
        # 用它來辨識。
        if moved_name and same_cell and "regime" not in ps:
            cs.scenario_moved = False
        else:
            cs.scenario_moved = moved_name
        cs.regime_changed = (ps.get("regime") != qs.get("regime")
                             and "regime" in ps)

    # ---- 訊號的新增與消失 ----
    for mod in ("labor", "inflation"):
        p, c = prev.get(mod), cur.get(mod)
        if not (p and c):
            continue
        pk, ck = set(p.get("flags", [])), set(c.get("flags", []))
        label = "就業" if mod == "labor" else "物價"
        for k in ck - pk:
            _lean = c.get("flag_leans", {}).get(k, "")
            cs.new_flags.append({"module": label, "kind": "new",
                                 "title": c.get("flag_titles", {}).get(k, k),
                                 "lean": _lean,
                                 "change_lean": _lean})
        for k in pk - ck:
            # 這裡是整張卡最容易搞錯的一件事：一條**已解除**的鷹派訊號，
            # 代表的是鷹派壓力消失了——那是**鴿派**的變化。
            # 掛訊號自己的 lean 會讓畫面上的方向全部反過來：
            # 四條解除的鷹派訊號會顯示成四個「利升息」，
            # 而卡片標題同時說情境往降息的方向移動，兩者互相矛盾。
            _lean = p.get("flag_leans", {}).get(k, "")
            cs.resolved_flags.append({"module": label, "kind": "gone",
                                      "title": p.get("flag_titles", {}).get(k, k),
                                      "lean": _lean,
                                      "change_lean": _invert(_lean)})
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
            # 顏色要表達「這個變動對利率的意思」，不是「數字漲了還是跌了」。
            # up_is 記的是「這個指標往上代表偏鷹還是偏鴿」——
            # 例如損益兩平就業增速變高，代表同樣的非農其實更弱，是偏鴿的。
            # 用漲跌上色會把它標成跟「核心 CPI 上升」同一個顏色，意思剛好相反。
            _up = meta.get("up_is", "")
            _lean = ("" if not _up else
                     (_up if delta > 0 else _invert(_up)))
            cs.metric_moves.append({
                "label": meta.get("label", key),
                "from": old, "to": new, "delta": delta,
                "unit": meta.get("unit", ""),
                # 水準與變化量的單位不同：率的變化是「個百分點」
                "delta_unit": meta.get("delta_unit", meta.get("unit", "")),
                "lean": _lean,
            })

    # ---- 本期整體往哪一邊 ----
    # 只數訊號的變化，不把數字變動也算進去：同一件事會被算兩次
    #（「核心 CPI 年增下降」既是一條數字變動，也可能同時解除一條訊號）。
    _all = cs.new_flags + cs.resolved_flags
    cs.n_dovish = sum(1 for f in _all if f["change_lean"] == "dovish")
    cs.n_hawkish = sum(1 for f in _all if f["change_lean"] == "hawkish")
    if cs.n_dovish and cs.n_dovish > cs.n_hawkish:
        cs.net_lean = "dovish"
    elif cs.n_hawkish and cs.n_hawkish > cs.n_dovish:
        cs.net_lean = "hawkish"
    elif cs.n_dovish or cs.n_hawkish:
        cs.net_lean = "mixed"

    cs.headline = _headline(cs)
    return cs


NET_TEXT = {
    "dovish": "本期整體往**降息**的方向移動",
    "hawkish": "本期整體往**升息**的方向移動",
    "mixed": "本期兩個方向的變化**打平**",
    "neutral": "",
}


def net_line(cs: ChangeSet) -> str:
    """
    一句淨結論。多條變化平鋪在畫面上而沒有加總，讀者只能自己數——
    而且很容易數錯：解除一條鷹派訊號其實是鴿派的變化。
    """
    if not (cs.n_dovish or cs.n_hawkish):
        return ""
    base = NET_TEXT.get(cs.net_lean, "")
    return f"{base}：{cs.n_dovish} 項偏降息、{cs.n_hawkish} 項偏升息"


def _headline(cs: ChangeSet) -> str:
    if cs.regime_changed:
        # 重心翻轉是最重大的變化：同一份數據的結論會整個換一張九宮格
        return (f"聯準會的重心翻轉，情境由「{cs.scenario_from}」"
                f"變成「{cs.scenario_to}」")
    if cs.scenario_moved:
        return f"情境由「{cs.scenario_from}」移動到「{cs.scenario_to}」"
    if not (cs.new_flags or cs.resolved_flags):
        return "情境與訊號組成與上期相同"
    # 情境沒動時，標題說「還在哪一格」就好。
    #
    # 先前寫的是「新觸發 1 項訊號、4 項訊號解除」——那是流水帳：下面的兩欄
    # 已經把每一條列出來了，標題再數一次不會多給任何資訊，而讀者最想知道的
    # 「所以往哪邊」反而沒講。方向交給下一行的淨結論，這裡不重複。
    return (f"情境仍是「{cs.scenario_to}」，但訊號組成有變"
            if cs.scenario_to else "情境未變，訊號組成有變")
