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
import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from .. import clock


# 關鍵數字的**計算方法版本**。改了任何一個 key_metrics 的算法就要 +1。
#
# 為什麼需要這個東西
# ------------------
# 快照存的是「算完的數字」，不是原始序列。所以計算方法一改，下一期的
# 變化卡就會拿**舊程式算的上期**去減**新程式算的本期**，把口徑差異
# 報成真實變動。
#
# 實際發生過：v73 修好年增率的除數之後，畫面上出現
#
#     核心 CPI 年增　2.81 → 2.48　（−0.33 個百分點）
#
# 而同一頁的走勢列（每次重算）寫著 6 月是 2.6——同一個月份兩個數字。
# 那 −0.33 裡面大部分是「我改了程式」，不是物價變了。核心服務除住房
# 甚至寫成 3.35 → 2.24，一個月掉 1.11 個百分點。
#
# 這種錯**只錯一期然後自己好**，所以最難抓：等你發現的時候它已經消失了。
#
# 處置：版本對不上時改用 `metrics_prev`——由**現行程式**回頭算的上一期。
# 平常（版本相同）維持「跟你上次看到的比」，資料修正照樣看得到；
# 只有改程式的那一期會切換基準，而那正是唯一需要切換的時候。
METHOD_VERSION = 2


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
    # 這一期的關鍵數字換過計算方法（見 METHOD_VERSION）。畫面上要講出來：
    # 基準跟平常不一樣，讀者才不會把它跟「上次你看到的」混為一談。
    method_changed: bool = False
    headline: str = ""
    # 對照的是哪一版**資料**，不是哪一次執行。排程每天跑、資料一個月出一次，
    # 用執行時間當基準會讓「對照今天早上 05:01」這種毫無意義的字串出現在
    # 最顯眼的位置，還會讓人以為核心 CPI 在一小時內掉了 0.5 個百分點。
    # 每個模組各自的對照基準。三個模組的發布節奏不同，共用一個「上期」
    # 對不齊——就業每月第一個週五、CPI 每月中、FOMC 每 6–8 週。
    # [{module, label, from, to, released, days}]
    bases: list = field(default_factory=list)
    days_since: int | None = None    # 距離最近一次發布幾天
    n_dovish: int = 0               # 本期偏鴿方向的變化筆數
    n_hawkish: int = 0
    net_lean: str = "neutral"       # dovish / hawkish / mixed / neutral


def snapshot(ctxs: dict) -> dict:
    """
    把本期的關鍵狀態壓成一個可比對的小字典。

    每個模組都帶自己的 `vintage`（資料期別）與 `released`（發布日）。
    輪替的條件是 vintage，不是執行時間——見 roll() 的說明。
    """
    today = clock.today().isoformat()
    mods: dict = {}

    lab = ctxs.get("labor")
    if lab:
        mods["labor"] = {
            "vintage": lab["data_month"],
            "released": today,          # 第一次看到這一期的日子 ≈ 發布日
            "month": lab["data_month"],
            "score": lab["score"]["score"],
            "tilt": lab["tilt"]["tilt"],
            "flags": [f.key for f in lab["flags"]],
            "flag_titles": {f.key: f.headline for f in lab["flags"]},
            "flag_leans": {f.key: f.lean for f in lab["flags"]},
            "metrics": lab.get("key_metrics", {}),
            # 這幾個數字是**用哪一版程式算的**。見 METHOD_VERSION。
            "method": METHOD_VERSION,
            # 用現行程式回頭算的「上一期」。方法版本對不上時拿它當基準，
            # 這樣改完程式的那一期不會把口徑差異報成真實變動。
            "metrics_prev": lab.get("key_metrics_prev", {}),
        }
    inf = ctxs.get("inflation")
    if inf:
        # 期別＝CPI 月份＋PCE 月份的複合：通膨模組一個月有兩次發布
        # （CPI 月中、PCE 月底），只綁 CPI 的話，PCE 把推估值換成實際值
        # 的那一刻不會輪替基準——而那個數字正是九宮格通膨軸在用的。
        _pce_m = ((inf.get("asof") or {}).get("pce") or "")[:7]
        mods["inflation"] = {
            "vintage": inf["data_month"] + (f"|{_pce_m}" if _pce_m else ""),
            "released": today,
            "month": inf["data_month"],
            "tilt": inf["tilt"]["tilt"],
            "flags": [f.key for f in inf["flags"]],
            "flag_titles": {f.key: f.headline for f in inf["flags"]},
            "flag_leans": {f.key: f.lean for f in inf["flags"]},
            "metrics": inf.get("key_metrics", {}),
            "method": METHOD_VERSION,
            "metrics_prev": inf.get("key_metrics_prev", {}),
        }
    fom = ctxs.get("fomc")
    if fom and not fom.get("empty"):
        mods["fomc"] = {
            "vintage": fom["latest_date"],
            "released": fom["latest_date"],   # 聲明的發布日就是會議日
            "focus": (fom.get("focus") or {}).get("focus", ""),
            "focus_label": (fom.get("focus") or {}).get("label", ""),
            "objective": (fom.get("shift") or {}).get("objective"),
        }
    # ---- 每週失業金：唯一的週頻資料，期別＝統計週結束日 ----
    _cl = ((lab or {}).get("claims") or {}).get("machine") or {}
    if _cl.get("week"):
        def _wan(v):
            return None if v is None else v / 1e4
        mods["claims"] = {
            "vintage": _cl["week"], "released": today,
            "flags": [], "flag_titles": {}, "flag_leans": {},
            "metrics": {
                "ic_ma": {"label": "初領失業金（四週平均）",
                          "value": _wan(_cl.get("ic_ma")), "unit": "萬人",
                          "threshold": 0.5, "up_is": "dovish"},
                "ic_now": {"label": "初領失業金（單週）",
                           "value": _wan(_cl.get("ic_now")), "unit": "萬人",
                           "threshold": 1.0, "up_is": "dovish"},
                "cc": {"label": "續領失業金",
                       "value": _wan(_cl.get("cc")), "unit": "萬人",
                       "threshold": 1.5, "up_is": "dovish"},
            },
            "method": METHOD_VERSION, "metrics_prev": {},
        }

    # ---- JOLTS：比就業報告晚一個月，落在空窗期，自己一個期別 ----
    _jr = (lab or {}).get("jolts_raw") or {}
    if lab and lab.get("jolts_month"):
        mods["jolts"] = {
            "vintage": lab["jolts_month"], "released": today,
            "flags": [], "flag_titles": {}, "flag_leans": {},
            "metrics": {
                "openings": {"label": "職缺數",
                             "value": (None if _jr.get("JTSJOL") is None
                                       else _jr["JTSJOL"] / 10),
                             "unit": "萬個", "threshold": 5,
                             "up_is": "hawkish"},
                "hires": {"label": "招聘率", "value": _jr.get("JTSHIR"),
                          "unit": "%", "delta_unit": " 個百分點",
                          "threshold": 0.05, "up_is": "hawkish"},
                "quits": {"label": "離職率", "value": _jr.get("JTSQUR"),
                          "unit": "%", "delta_unit": " 個百分點",
                          "threshold": 0.05, "up_is": "hawkish"},
                "layoffs": {"label": "裁員率", "value": _jr.get("JTSLDR"),
                            "unit": "%", "delta_unit": " 個百分點",
                            "threshold": 0.05, "up_is": "dovish"},
            },
            "method": METHOD_VERSION, "metrics_prev": {},
        }

    # ---- 市場價格：日頻資料按「週」輪替基準（逐日比會全是雜訊）；
    #      供給壓力等級做成旗標，翻轉時走既有的新增/解除機制即時報 ----
    rts = ctxs.get("rates")
    if rts and rts.get("as_of"):
        try:
            _iso = dt.date.fromisoformat(rts["as_of"]).isocalendar()
            _week = f"{_iso[0]}-W{_iso[1]:02d}"
        except (ValueError, TypeError):
            _week = rts["as_of"][:10]
        _mr = rts.get("market_raw") or {}
        _lv = getattr(rts.get("pressure"), "level", "") or ""
        # 只有偏高/偏低掛旗標；中性不掛——翻回中性時畫面上會出現
        # 「－ 偏高不再成立」（方向自動反轉成偏降息），一列就講完，
        # 不需要再多一列「＋ 中性」的廢話。
        _LV_TITLE = {"high": "長端供給壓力偏高", "low": "長端供給壓力偏低"}
        _LV_LEAN = {"high": "hawkish", "low": "dovish"}
        _exp = getattr((ctxs.get("inflation") or {}).get("summary"),
                       "expect_5y5y", None)
        mods["market"] = {
            "vintage": _week, "released": today,
            "flags": ([f"pressure_{_lv}"] if _lv in _LV_TITLE else []),
            "flag_titles": ({f"pressure_{_lv}": _LV_TITLE[_lv]}
                            if _lv in _LV_TITLE else {}),
            "flag_leans": ({f"pressure_{_lv}": _LV_LEAN.get(_lv, "")}
                           if _lv in _LV_TITLE else {}),
            "metrics": {
                "dgs10": {"label": "10 年期殖利率", "value": _mr.get("dgs10"),
                          "unit": "%", "delta_unit": " 個百分點",
                          "threshold": 0.08, "up_is": "hawkish"},
                "dgs30": {"label": "30 年期殖利率", "value": _mr.get("dgs30"),
                          "unit": "%", "delta_unit": " 個百分點",
                          "threshold": 0.08, "up_is": "hawkish"},
                "tp": {"label": "期限溢酬", "value": _mr.get("term_premium"),
                       "unit": "%", "delta_unit": " 個百分點",
                       "threshold": 0.08, "up_is": "hawkish"},
                "ig": {"label": "投資級利差", "value": _mr.get("ig_spread"),
                       "unit": "%", "delta_unit": " 個百分點",
                       "threshold": 0.05, "up_is": ""},
                # 通膨預期是日頻市場價格，放這裡週頻追蹤——
                # 留在通膨模組會被 CPI 月份鎖住，一個月才比一次
                "exp5y5y": {"label": "長期通膨預期", "value": _exp,
                            "unit": "%", "delta_unit": " 個百分點",
                            "threshold": 0.03, "up_is": "hawkish"},
            },
            "method": METHOD_VERSION, "metrics_prev": {},
        }

    scn = ctxs.get("scenario")
    if scn:
        sc = scn["scenario"]
        # 情境沒有自己的發布日——它是三個模組合成的，所以期別取三者的組合。
        # 任何一個模組換期別，情境就算換了一期。
        mods["scenario"] = {
            "vintage": "|".join(
                f"{k}:{mods[k]['vintage']}" for k in ("labor", "inflation", "fomc")
                if k in mods),
            "released": today,
            # 九宮格改成「一個體制一張」之後，格名本身就是結論：
            # 重心從通膨優先翻成就業優先時，同一個格位的名字會直接變
            #（例如「停滯性通膨：通膨優先」→「停滯性通膨：救就業」），
            # 所以只比 name 就抓得到體制翻轉。
            "name": sc.name, "grid_name": sc.name, "regime": sc.regime,
            "labor": sc.labor_state, "inflation": sc.infl_state,
        }
    return {"at": clock.iso(),
            "modules": mods}


# 每個模組的「資料期別」欄位。scenario 沒有自己的期別——
# 它是三個模組合成出來的，所以任何一個模組換期別，它就跟著算換了一期。
VINTAGE_OF = {"labor": "labor", "inflation": "inflation", "fomc": "fomc"}


def roll(prev_state: dict | None, cur: dict) -> dict:
    """
    更新狀態檔：**只有該模組的資料期別真的變了，才把舊的那份推到 previous。**

    為什麼不能每次執行都覆蓋
    ------------------------
    先前的做法是「這次的快照蓋掉上次的」，於是比較的視窗只有 24 小時：
    就業報告落地那天卡片會亮，隔天快照被覆蓋成發布後的狀態，
    比較變成「今天 vs 昨天」＝沒有變化，卡片就熄了。
    **讀者若在發布後第三天才打開網站，等於完全錯過那張卡。**
    對一個每週看一次的儀表板來說，這是最沒道理的一種行為——
    邊際資訊量最高的那張卡，偏偏在新聞剛發生之後就消失。

    改成以**資料期別**為輪替條件之後，「7 月就業報告帶來的變化」
    會一直留到 8 月報告出來為止。

    為什麼要逐模組而不是全站一起輪替
    --------------------------------
    三個模組的發布節奏不同：就業報告每月第一個週五、CPI 每月中、
    FOMC 每 6–8 週。用一個共同的「上期」去套三個不同節奏的東西，
    對不齊——實際畫面上就會出現「7 月就業報告 · 6 月 CPI · 7/29 聲明」
    這種三個模組停在三個期別、卻共用同一個基準的情況。

    另外累積一條 `history`
    ----------------------
    狀態檔先前只留 current 與 previous，每一期覆蓋一次。所以全站永遠回答不了
    這兩個問題：「這一格待了幾期」「上一次換格是什麼時候」——而首頁那句
    「情境**仍是**停滯性通膨」正好會讓讀者立刻問出來。

    這裡在期別換的時候 append 一列（不到 100 bytes，十年也只有幾 KB）。
    畫面可以之後再補，但**累積要越早開始越好**：晚一個月就永遠少一個月，
    這段歷史沒有辦法事後回填。

    回傳的結構：
        {"at": ...,
         "modules": {"labor": {"current": {...}, "previous": {...}}, ...},
         "history": [{"at", "vintage", "name", "regime", "labor", "inflation"}, ...]}
    """
    prev_state = prev_state or {}
    old_mods = prev_state.get("modules") or {}
    # 舊格式（單一份平面快照）也要能升級：把它整份當成每個模組的 previous。
    # 沒有這一段的話，改版後第一次執行會把所有變化都當成「第一次」而全部消失。
    if not old_mods and prev_state.get("labor"):
        old_mods = {k: {"current": prev_state[k]}
                    for k in ("labor", "inflation", "fomc", "scenario")
                    if prev_state.get(k)}

    out = {"at": cur.get("at"), "modules": {}}
    for key, snap in (cur.get("modules") or {}).items():
        old = old_mods.get(key) or {}
        old_cur = old.get("current")
        if old_cur is None:
            out["modules"][key] = {"current": snap}
            continue
        if old_cur.get("vintage") != snap.get("vintage"):
            # 期別換了 → 舊的那份成為對照基準
            out["modules"][key] = {"current": snap, "previous": old_cur}
        else:
            # 同一期別的重跑：值可能因為修正而變（ALFRED 會改前兩月），
            # 所以 current 照更新，但有兩樣東西不能跟著動：
            #   previous —— 動了等於把基準往前挪，畫面上的變化會憑空消失
            #   released —— snapshot() 每次都填今天，不保留舊值的話
            #               「N 天前發布」永遠會顯示「今天發布」，這個標籤就廢了
            merged = dict(snap)
            if old_cur.get("released"):
                merged["released"] = old_cur["released"]
            out["modules"][key] = {"current": merged}
            if old.get("previous"):
                out["modules"][key]["previous"] = old["previous"]

    out["history"] = _roll_history(prev_state.get("history"),
                                   (cur.get("modules") or {}).get("scenario"),
                                   cur.get("at"))
    return out


# 歷史只保留這麼多列。一期一列、一個月大約一到兩期，
# 400 列夠放十幾年——上限只是避免檔案無限長，不是資料保存策略。
HISTORY_MAX = 400


def _roll_history(old: list | None, scen: dict | None, at: str | None) -> list:
    """
    情境的期別歷史。**同一期別只留一列**，期別換了才 append。

    為什麼用期別而不是執行時間當去重鍵：排程每天跑一次，但資料一個月才出
    一到兩期。用執行時間的話一個月會累積三十列一模一樣的東西，
    而「這一格待了幾期」就會變成「待了幾天」——那是完全不同的問題，
    而且答案會隨排程頻率改變，不是隨數據改變。
    """
    hist = list(old or [])
    if not scen or not scen.get("vintage"):
        return hist[-HISTORY_MAX:]
    row = {
        "at": at,
        "vintage": scen.get("vintage"),
        "name": scen.get("name"),
        "regime": scen.get("regime"),
        "labor": scen.get("labor"),
        "inflation": scen.get("inflation"),
    }
    if hist and hist[-1].get("vintage") == row["vintage"]:
        # 同一期別重跑：期別沒換但判定可能因為資料修正而變，
        # 所以就地更新最後一列，不新增。
        hist[-1] = row
    else:
        hist.append(row)
    return hist[-HISTORY_MAX:]


def tenure(state: dict | None) -> dict:
    """
    目前這個情境待了幾期、上一次是從哪一格移過來的。

    回傳 {"periods": int, "from": str, "since": str} —— 資訊不足時回 {}。
    只有兩列以上才有話可說：一列的時候「已維持 1 期」是廢話。

    這個問題是首頁自己引出來的：結論卡寫「情境**仍是**停滯性通膨」，
    讀者下一句一定是「仍是多久了」。先前狀態檔只留 current 與 previous，
    答不出來。
    """
    hist = (state or {}).get("history") or []
    if len(hist) < 2:
        return {}
    name = hist[-1].get("name")
    if not name:
        return {}
    n = 0
    for row in reversed(hist):
        if row.get("name") != name:
            return {"periods": n, "from": row.get("name") or "",
                    "since": (hist[-n].get("vintage") or "")}
        n += 1
    # 整段歷史都是同一格：講得出期數，但講不出「從哪裡來」
    return {"periods": n, "from": "", "since": hist[0].get("vintage") or ""}


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


MODULE_LABEL = {"labor": "就業", "inflation": "物價", "fomc": "聯準會",
                "claims": "失業金", "jolts": "JOLTS", "market": "市場"}


def _side(state: dict, which: str) -> dict:
    """把 {mod: {current, previous}} 攤平成 {mod: snapshot}，缺的就不放。"""
    return {k: v[which] for k, v in (state.get("modules") or {}).items()
            if v.get(which)}


def _vintage_label(mod: str, raw: str) -> str:
    """2026-07 → 7 月；2026-07-29 → 7/29；複合與週別另處理。"""
    raw = raw or ""
    if "|" in raw:                        # 通膨的複合期別：CPI 月份|PCE 月份
        a, b = raw.split("|", 1)
        return f"{_vintage_label(mod, a)}（PCE {_vintage_label(mod, b)}）"
    if "W" in raw:                        # 市場單位的週別：2026-W34
        try:
            return f"第 {int(raw.split('W')[1])} 週"
        except (ValueError, IndexError):
            return raw
    parts = raw.split("-")
    try:
        if len(parts) == 3:
            return f"{int(parts[1])}/{int(parts[2])}"
        if len(parts) == 2:
            return f"{int(parts[1])} 月"
    except ValueError:
        pass
    return raw


def compare(state: dict) -> ChangeSet:
    """
    比的是**每個模組自己的上一期發布**，不是上一次執行。

    輸入是 roll() 產生的狀態：{"modules": {mod: {"current":…, "previous":…}}}。
    某個模組沒有 previous（第一次看到這一期）就跳過它，不硬比。
    """
    cs = ChangeSet()
    state = state or {}
    cur = _side(state, "current")
    prev = _side(state, "previous")
    if not prev:
        cs.headline = "這是第一次執行，還沒有可以比對的上期資料。"
        return cs

    cs.has_previous = True
    cs.prev_at = (state.get("at") or "")[:16].replace("T", " ")

    # ---- 每個模組各自的對照基準 ----
    today = clock.today()
    for mod in ("labor", "inflation", "fomc", "claims", "jolts", "market"):
        c, p = cur.get(mod), prev.get(mod)
        if not (c and p):
            continue
        days = None
        try:
            days = (today - dt.date.fromisoformat(c.get("released", ""))).days
        except (ValueError, TypeError):
            pass
        cs.bases.append({
            "module": mod, "label": MODULE_LABEL.get(mod, mod),
            "from": _vintage_label(mod, p.get("vintage", "")),
            "to": _vintage_label(mod, c.get("vintage", "")),
            "released": c.get("released", ""), "days": days,
        })
    _d = [b["days"] for b in cs.bases if b["days"] is not None]
    cs.days_since = min(_d) if _d else None

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
    for mod in ("labor", "inflation", "market"):
        p, c = prev.get(mod), cur.get(mod)
        if not (p and c):
            continue
        pk, ck = set(p.get("flags", [])), set(c.get("flags", []))
        label = MODULE_LABEL.get(mod, mod)
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
    for mod in ("labor", "inflation", "claims", "jolts", "market"):
        p, c = prev.get(mod), cur.get(mod)
        if not (p and c):
            continue
        # 上期的基準要用哪一份：見 METHOD_VERSION 的說明。
        #
        # 版本相同（正常情況）→ 用快照裡存的那一份，也就是「你上次真的
        # 看到的數字」。BLS 下修前兩月時，那個修正**看得到**，而那是訊號。
        #
        # 版本不同（我改了計算方法）→ 快照裡那份是舊程式算的，拿來相減
        # 得到的是口徑差異不是真實變動。改用 metrics_prev：由現行程式
        # 回頭算的上一期，兩邊口徑一致。
        pm = p.get("metrics") or {}
        if p.get("method") != c.get("method"):
            _recomputed = c.get("metrics_prev") or {}
            if _recomputed:
                pm = _recomputed
                cs.method_changed = True
            else:
                # 連重算的那一份都沒有 → 寧可這期不比，也不要報一個
                # 「其中大半是程式改動」的變動量出去。
                cs.method_changed = True
                continue
        cm = c.get("metrics") or {}
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
                # 哪一個模組。整體總述要用它挑出「這次剛發布的那個模組」
                # 的變動來寫摘要——非發布日的模組不該被算進「本次更新」。
                "module": mod,
                "key": key,
                "label": meta.get("label", key),
                "from": old, "to": new, "delta": delta,
                "unit": meta.get("unit", ""),
                # 水準與變化量的單位不同：率的變化是「個百分點」
                "delta_unit": meta.get("delta_unit", meta.get("unit", "")),
                # 這個指標的雜訊門檻。帶出來是給**跨指標排序**用的：
                # 「非農動了 5.7 萬人」跟「核心 CPI 動了 0.33 個百分點」
                # 沒辦法直接比大小（單位不同），但都可以問「動了幾倍的雜訊」。
                # 見 brief._whats_new。
                "threshold": meta.get("threshold", 0) or 0,
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


def basis_text(cs: ChangeSet) -> str:
    """「就業 7 月（對照 6 月）　·　物價 6 月（對照 5 月）」。"""
    return "　·　".join(
        f'{b["label"]} {b["to"]}（對照 {b["from"]}）' for b in cs.bases)


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
