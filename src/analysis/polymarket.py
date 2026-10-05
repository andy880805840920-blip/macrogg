"""
美國期中選舉預測（Polymarket）
================================

首頁「期中選舉預測」卡片與焦點條的兩顆 chip（眾院／參院）的資料來源。

資料：Polymarket 的公開唯讀介面，不需要金鑰。
  · Gamma API（gamma-api.polymarket.com）：事件與各選項的目前價格
  · CLOB API（clob.polymarket.com）：價格歷史（30 天小走勢圖）

**價格不是機率**：預測市場的價格反映下注者的看法，不是民調；交易量小的盤
容易被少數人推動。所以這裡有三道檢查：
  · 交易量門檻：太小的盤不採用（config 可調）
  · 兩黨（或兩位候選人）價格加總要接近 100%，多選項的盤全部加總也要接近
    100%——對不上代表資料有問題，整個盤不採用，不硬湊
  · 抓不到時沿用上次成功的結果（最多 3 天，畫面標日期），更舊就不顯示

更新頻率跟著網站排程（每天 3 次）——選情不需要每分鐘更新。
選舉日之後卡片標題改成「選舉結果」，價格接近 100% 就代表市場認定結果
已經確定；hide_after 那天之後整張卡片自動隱藏。
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
from pathlib import Path

import requests

from .. import clock

log = logging.getLogger(__name__)

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
EVENT_URL = "https://polymarket.com/event/{slug}"
TIMEOUT = 12

DEFAULTS = {
    "enabled": True,
    "election_date": "2026-11-03",
    "hide_after": "2026-11-17",
    "house": "which-party-will-win-the-house-in-2026",
    "senate": "which-party-will-win-the-senate-in-2026",
    "balance": "balance-of-power-2026-midterms",
    "tag": "midterms",
    "n_races": 4,
    "min_volume": 100000,          # 眾院／參院／權力組合的事件交易量下限（美元）
    "race_min_volume": 300000,     # 個別州參院選戰的事件交易量下限
    "stale_days": 3,
    # ---- 各州地圖（2026-10 新增）----
    "map": True,
    # 參院：這次沒改選的 65 席（2026 年初：民主黨 34 含兩位與民主黨同黨團的
    # 獨立參議員、共和黨 31）。過半 51 席；50:50 由副總統（共和黨）投票。
    "senate_not_up": {"D": 34, "R": 31},
    "senate_majority": 51,
    "senate_tiebreak": "R",
    "senate_control": "R",
    # 州長：這次沒改選的 14 州（民主黨 6：DE KY NJ NC VA WA；共和黨 8：
    # IN LA MS MO MT ND UT WV），改選前 27:23
    "governor_not_up": {"D": 6, "R": 8},
    "governor_before": {"R": 27, "D": 23},
    # Polymarket 沒加 midterms 標籤、要另外抓的事件
    "extra_events": {"governor": {"California": "california-governor-election-2026"}},
    # 盤口上沒標黨派的候選人
    "party_overrides": {},
    "senate_seats_event": "republican-senate-seats-after-the-2026-midterm-elections-927",
    "house_seats_event": "republican-house-seats-after-the-2026-midterm-elections",
    "governor_seats_event": "how-many-republican-governors-after-the-2026-midterm-elections",
}

# 2026 有改選的州（地圖上「沒改選」與「沒有盤口」要分開標）
SENATE_2026 = ("Alabama", "Alaska", "Arkansas", "Colorado", "Delaware", "Florida",
               "Georgia", "Idaho", "Illinois", "Iowa", "Kansas", "Kentucky",
               "Louisiana", "Maine", "Massachusetts", "Michigan", "Minnesota",
               "Mississippi", "Montana", "Nebraska", "New Hampshire", "New Jersey",
               "New Mexico", "North Carolina", "Ohio", "Oklahoma", "Oregon",
               "Rhode Island", "South Carolina", "South Dakota", "Tennessee",
               "Texas", "Virginia", "West Virginia", "Wyoming")
GOVERNOR_2026 = ("Alabama", "Alaska", "Arizona", "Arkansas", "California",
                 "Colorado", "Connecticut", "Florida", "Georgia", "Hawaii", "Idaho",
                 "Illinois", "Iowa", "Kansas", "Maine", "Maryland", "Massachusetts",
                 "Michigan", "Minnesota", "Nebraska", "Nevada", "New Hampshire",
                 "New Mexico", "New York", "Ohio", "Oklahoma", "Oregon",
                 "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota",
                 "Tennessee", "Texas", "Vermont", "Wisconsin", "Wyoming")
ABBR = {"Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
        "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
        "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA",
        "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN",
        "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA",
        "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI",
        "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT",
        "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ",
        "New Mexico": "NM", "New York": "NY", "North Carolina": "NC",
        "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR",
        "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
        "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
        "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
        "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY"}
# 勝率分級（地圖深淺）：≥85% 穩拿、65–85% 傾向、55–65% 微幅、<55% 五五波
TIERS = ((0.85, "safe", "穩拿"), (0.65, "likely", "傾向"), (0.55, "lean", "微幅"))
COMPETITIVE = 0.65            # 領先者低於這個價格＝競爭州

STATES = {
    "Alabama": "阿拉巴馬", "Alaska": "阿拉斯加", "Arizona": "亞利桑那",
    "Arkansas": "阿肯色", "California": "加州", "Colorado": "科羅拉多",
    "Connecticut": "康乃狄克", "Delaware": "德拉瓦", "Florida": "佛羅里達",
    "Georgia": "喬治亞", "Hawaii": "夏威夷", "Idaho": "愛達荷",
    "Illinois": "伊利諾", "Indiana": "印第安納", "Iowa": "愛荷華",
    "Kansas": "堪薩斯", "Kentucky": "肯塔基", "Louisiana": "路易斯安那",
    "Maine": "緬因", "Maryland": "馬里蘭", "Massachusetts": "麻州",
    "Michigan": "密西根", "Minnesota": "明尼蘇達", "Mississippi": "密西西比",
    "Missouri": "密蘇里", "Montana": "蒙大拿", "Nebraska": "內布拉斯加",
    "Nevada": "內華達", "New Hampshire": "新罕布夏", "New Jersey": "紐澤西",
    "New Mexico": "新墨西哥", "New York": "紐約", "North Carolina": "北卡羅來納",
    "North Dakota": "北達科他", "Ohio": "俄亥俄", "Oklahoma": "奧克拉荷馬",
    "Oregon": "奧勒岡", "Pennsylvania": "賓州", "Rhode Island": "羅德島",
    "South Carolina": "南卡羅來納", "South Dakota": "南達科他",
    "Tennessee": "田納西", "Texas": "德州", "Utah": "猶他", "Vermont": "佛蒙特",
    "Virginia": "維吉尼亞", "Washington": "華盛頓州", "West Virginia": "西維吉尼亞",
    "Wisconsin": "威斯康辛", "Wyoming": "懷俄明",
}
PARTY = {"D": "民", "R": "共", "I": "獨"}

# 權力組合的選項 → 中文（順序＝畫面上的堆疊順序）
BALANCE_LABELS = (
    ("Democrats Sweep", "民主黨兩院全拿", "dem"),
    ("D Senate, R House", "民主黨拿參院、共和黨守眾院", "mix2"),
    ("R Senate, D House", "共和黨守參院、民主黨拿眾院", "mix"),
    ("Republicans Sweep", "共和黨兩院全拿", "rep"),
    ("Other", "其他", "oth"),
)


def _cfg(cfg: dict | None) -> dict:
    return {**DEFAULTS, **{k: v for k, v in (cfg or {}).items() if v is not None}}


def _f(x) -> float | None:
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def _yes_price(m: dict) -> float | None:
    """選項的「是」價格（0–1）。outcomePrices 是 JSON 字串：["0.675","0.325"]。"""
    try:
        prices = json.loads(m.get("outcomePrices") or "[]")
        outs = json.loads(m.get("outcomes") or "[]")
    except (TypeError, ValueError):
        return None
    if not prices:
        return None
    i = outs.index("Yes") if "Yes" in outs else 0
    p = _f(prices[i]) if i < len(prices) else None
    return p if p is not None and 0 <= p <= 1 else None


def _yes_token(m: dict) -> str:
    try:
        toks = json.loads(m.get("clobTokenIds") or "[]")
        outs = json.loads(m.get("outcomes") or "[]")
    except (TypeError, ValueError):
        return ""
    i = outs.index("Yes") if "Yes" in outs else 0
    return str(toks[i]) if i < len(toks) else ""


def _options(ev: dict) -> list[dict]:
    """事件底下有價格的選項（Polymarket 會預留 Party A／Person B 這種空白位子）。"""
    out = []
    for m in ev.get("markets") or []:
        p = _yes_price(m)
        name = (m.get("groupItemTitle") or m.get("question") or "").strip()
        if p is None or not name:
            continue
        out.append({"name": name, "p": p,
                    "d1": _f(m.get("oneDayPriceChange")),
                    "vol": _f(m.get("volume")) or 0.0,
                    "token": _yes_token(m),
                    "closed": bool(m.get("closed"))})
    return out


def _get_json(url: str, params: dict | None = None, _get=None):
    get = _get or (lambda u, p: requests.get(
        u, params=p, timeout=TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0 (macro-dashboard)"}))
    r = get(url, params or {})
    r.raise_for_status()
    return r.json()


def fetch_event(slug: str, _get=None) -> dict | None:
    data = _get_json(f"{GAMMA}/events", {"slug": slug}, _get)
    if isinstance(data, list) and data:
        return data[0]
    return None


def fetch_history(token: str, _get=None) -> list[float]:
    """近 30 天的日線價格（0–1）。抓不到回空陣列——小走勢圖就不畫。"""
    if not token:
        return []
    try:
        data = _get_json(f"{CLOB}/prices-history",
                         {"market": token, "interval": "1m", "fidelity": 1440},
                         _get)
        pts = [_f(x.get("p")) for x in (data or {}).get("history") or []]
        return [p for p in pts if p is not None and 0 <= p <= 1][-31:]
    except Exception as e:                         # noqa: BLE001
        log.info("Polymarket：價格歷史抓取失敗（%s）", e)
        return []


def _sum_ok(opts: list[dict], lo: float = 0.9, hi: float = 1.1) -> bool:
    s = sum(o["p"] for o in opts)
    return lo <= s <= hi


def _party_pair(ev: dict) -> dict | None:
    """眾院／參院：民主黨與共和黨兩個選項，加總要接近 100%。"""
    opts = _options(ev)
    dem = next((o for o in opts if o["name"].lower().startswith("democrat")), None)
    rep = next((o for o in opts if o["name"].lower().startswith("republican")), None)
    if not dem or not rep or not _sum_ok([dem, rep]):
        return None
    return {"dem": dem["p"], "rep": rep["p"], "d1": dem["d1"],
            "token": dem["token"], "closed": dem["closed"] and rep["closed"]}


def _balance(ev: dict) -> list[dict] | None:
    opts = {o["name"].strip().lower(): o for o in _options(ev)}
    rows = []
    for en, zh, key in BALANCE_LABELS:
        o = opts.get(en.lower())
        if o is not None:
            rows.append({"key": key, "label": zh, "p": o["p"], "d1": o["d1"]})
    if len(rows) < 4 or not _sum_ok(rows):
        return None
    return rows


_CAND = re.compile(r"^(?:Sen\.\s*)?(.+?)\s*(?:\(([DRI])\))?\s*$")


def _cand(name: str) -> dict:
    m = _CAND.match(name.strip())
    nm, party = (m.group(1), m.group(2) or "") if m else (name, "")
    return {"name": nm.strip(), "party": PARTY.get(party, "")}


def _race(ev: dict, min_vol: float) -> dict | None:
    """一州的參院選戰：前兩名候選人、加總接近 100%、交易量夠。"""
    title = (ev.get("title") or "").strip()
    st = re.sub(r"\s*Senate Election Winner\s*$", "", title).strip()
    if st == title or (_f(ev.get("volume")) or 0) < min_vol:
        return None
    opts = sorted(_options(ev), key=lambda o: -o["p"])[:2]
    if len(opts) < 2 or not _sum_ok(opts, 0.85, 1.15):
        return None
    lead, other = opts
    return {"state": STATES.get(st, st), "state_en": st,
            "lead": {**_cand(lead["name"]), "p": lead["p"]},
            "other": {**_cand(other["name"]), "p": other["p"]},
            "close": abs(lead["p"] - 0.5),
            "vol": _f(ev.get("volume")) or 0.0,
            "url": EVENT_URL.format(slug=ev.get("slug") or "")}


def fetch_tag_events(tag: str, _get=None) -> list[dict]:
    """某個標籤底下所有未結束的事件（分頁抓完）。"""
    out = []
    for off in range(0, 500, 100):
        try:
            evs = _get_json(f"{GAMMA}/events",
                            {"closed": "false", "tag_slug": tag,
                             "limit": 100, "offset": off}, _get)
        except Exception as e:                     # noqa: BLE001
            log.warning("Polymarket：選戰清單抓取失敗（%s）", e)
            break
        if not evs:
            break
        out.extend(evs)
        if len(evs) < 100:
            break
    return out


def pick_races(evs: list[dict], n: int, min_vol: float) -> list[dict]:
    """
    自動挑「勝負最接近」的 n 州：交易量過門檻的參院選戰，依領先者價格
    離 50% 的距離排序。名單每次更新自動重算，不用手動維護。
    """
    races = [r for r in (_race(ev, min_vol) for ev in evs) if r]
    races.sort(key=lambda r: (r["close"], -r["vol"]))
    return races[:n]


def fetch_races(tag: str, n: int, min_vol: float, _get=None) -> list[dict]:
    return pick_races(fetch_tag_events(tag, _get), n, min_vol)


# ---------------------------------------------------------------------------
# 各州地圖：參院與州長，每州的領先者、勝率分級、席次加總、一句話分析
# ---------------------------------------------------------------------------
_KIND_RE = re.compile(r"^\s*(.+?)\s+(Senate|Governor)\s+Election\s+Winner\s*$", re.I)


def _party_of(name: str, overrides: dict) -> str:
    """候選人 → D／R／I／?。先看「(D)」標記，再看設定檔，最後看選項名本身。"""
    m = re.search(r"\(([DRI])\)", name)
    if m:
        return m.group(1)
    base = re.sub(r"^Sen\.\s*", "", name).strip()
    for k, v in (overrides or {}).items():
        if k.strip().lower() == base.lower():
            return str(v).upper()[:1]
    low = base.lower()
    if low.startswith("democrat"):
        return "D"
    if low.startswith("republican"):
        return "R"
    if low.startswith("independent"):
        return "I"
    return "?"


def tier_of(p: float) -> tuple[str, str]:
    for th, key, zh in TIERS:
        if p >= th:
            return key, zh
    return "toss", "五五波"


def state_race(ev: dict, overrides: dict) -> dict | None:
    """一州一場選舉（參院或州長）→ 地圖用的資料；選項加總不合理就不採用。"""
    m = _KIND_RE.match(ev.get("title") or "")
    if not m:
        return None
    st, kind = m.group(1).strip(), m.group(2).lower()
    opts = sorted(_options(ev), key=lambda o: -o["p"])
    if len(opts) < 2 or not (0.85 <= sum(o["p"] for o in opts) <= 1.2):
        return None
    lead, other = opts[0], opts[1]

    def c(o):
        nm = _cand(o["name"])["name"]
        pa = _party_of(o["name"], overrides)
        return {"name": nm, "party": pa, "p": o["p"]}
    L, O = c(lead), c(other)
    tk, tz = tier_of(L["p"])
    return {"kind": kind, "state_en": st, "state": STATES.get(st, st),
            "abbr": ABBR.get(st, st[:2].upper()), "lead": L, "other": O,
            "tier": tk, "tier_zh": tz, "gap": round((L["p"] - O["p"]) * 100, 1),
            "vol": _f(ev.get("volume")) or 0.0,
            "url": EVENT_URL.format(slug=ev.get("slug") or "")}


def tally(kind: str, races: dict, c: dict) -> dict:
    """照各州目前領先者全拿的席次（參院加上沒改選的席次）。"""
    lead = {"D": 0, "R": 0, "I": 0, "?": 0}
    comp = {"D": [], "R": [], "I": [], "?": []}
    for r in races.values():
        pa = r["lead"]["party"]
        lead[pa] = lead.get(pa, 0) + 1
        if r["lead"]["p"] < COMPETITIVE:
            comp.setdefault(pa, []).append(r)
    base = c.get("senate_not_up" if kind == "senate" else "governor_not_up") or {}
    total = {k: lead.get(k, 0) + int(base.get(k, 0)) for k in ("D", "R", "I")}
    up = SENATE_2026 if kind == "senate" else GOVERNOR_2026
    missing = [s for s in up if s not in races]
    return {"lead": lead, "total": total, "base": base, "missing": missing,
            "competitive": {k: sorted(v, key=lambda r: r["gap"]) for k, v in comp.items()},
            "n_up": len(up)}


def _names(rs: list[dict], n: int = 2) -> str:
    return "、".join(r["state"] for r in rs[:n])


def sentence(kind: str, t: dict, c: dict) -> str:
    """一句話分析：固定規則從數字組句（數字一定對得上地圖，不交給 AI）。"""
    D, R, I = t["total"]["D"], t["total"]["R"], t["total"]["I"]
    comp = [r for v in t["competitive"].values() for r in v]
    comp.sort(key=lambda r: r["gap"])
    nd, nr = len(t["competitive"].get("D", [])), len(t["competitive"].get("R", []))
    if kind == "senate":
        maj, tie, ctl = (int(c.get("senate_majority", 51)),
                         str(c.get("senate_tiebreak", "R")),
                         str(c.get("senate_control", "R")))
        name = {"D": "民主黨", "R": "共和黨"}
        if D >= maj or R >= maj:
            win = "D" if D >= maj else "R"
            verb = "保住" if win == ctl else "翻轉"
            res = (f"{name[win]}將以 {max(D, R)}:{min(D, R)} {verb}參院")
        elif D == R or (D + I == R) or (R + I == D):
            res = f"將形成 {D}:{R}，由副總統投票，{name.get(tie, tie)}掌控參院"
        else:
            res = f"兩黨都不到 {maj} 席，{I} 席獨立派成為關鍵"
    else:
        gb = c.get("governor_before") or {}
        bR, bD = gb.get("R", "—"), gb.get("D", "—")
        res = (f"民主黨 {D} 州 : 共和黨 {R} 州（改選前共和黨 {bR}:{bD}）" if D > R
               else f"共和黨 {R} 州 : 民主黨 {D} 州（改選前共和黨 {bR}:{bD}）")
    if not comp:
        return f"照目前領先者全拿，{res}；沒有勝負接近的州。"
    if kind != "senate":
        res = "將是" + res
    head = (f"{len(comp)} 個競爭州裡民主黨領先 {nd} 州、共和黨領先 {nr} 州"
            if nd or nr else f"{len(comp)} 個競爭州")
    close = [r for r in comp if r["gap"] < 20][:2]
    tail = ""
    if close:
        lim = 10 if all(r["gap"] < 10 for r in close) else 20
        tail = (f"；但{_names(close)}的差距" + ("都" if len(close) > 1 else "")
                + f"在 {lim} 個百分點內，結果仍可能翻盤")
    return f"{head}，照目前領先者全拿，{res}{tail}。"


def _bucket_zh(label: str, unit: str = "席") -> str:
    s = label.strip()
    m = re.match(r"^(?:Below|Under|Less than)\s*(\d+)$", s, re.I)
    if m:
        return f"{m.group(1)} {unit}以下"
    m = re.match(r"^(?:Above|Over|More than)\s*(\d+)$", s, re.I)
    if m:
        return f"{m.group(1)} {unit}以上"
    s = s.replace("≤", "≦").replace(">=", "≧").replace("+", f" {unit}以上")
    s = re.sub(r"(\d)\s*[–-]\s*(\d)", r"\1–\2", s)
    return s + ("" if s.endswith(("以上", "以下")) else f" {unit}")


def seat_mode(ev: dict | None, unit: str = "席") -> dict | None:
    """席次分布盤：市場價格最高的那一格（例：共和黨眾院席次 190 席以下 30.5%）。"""
    if not ev:
        return None
    opts = _options(ev)
    if len(opts) < 3 or not _sum_ok(opts, 0.85, 1.15):
        return None
    top = max(opts, key=lambda o: o["p"])
    return {"label": _bucket_zh(top["name"], unit), "p": top["p"],
            "url": EVENT_URL.format(slug=ev.get("slug") or "")}


def build_maps(evs: list[dict], c: dict, _get=None) -> dict:
    ov = c.get("party_overrides") or {}
    maps: dict = {"senate": {}, "governor": {}}
    for ev in evs:
        r = state_race(ev, ov)
        if r and r["state_en"] not in maps[r["kind"]]:
            maps[r["kind"]][r["state_en"]] = r
    for kind, extra in (c.get("extra_events") or {}).items():
        for st, slug in (extra or {}).items():
            if kind in maps and st not in maps[kind]:
                try:
                    ev = fetch_event(str(slug), _get)
                    r = state_race(ev, ov) if ev else None
                    if r:
                        maps[kind][st] = r
                except Exception as e:             # noqa: BLE001
                    log.info("Polymarket：%s %s 的事件抓取失敗（%s）", st, kind, e)
    out = {}
    for kind in ("senate", "governor"):
        t = tally(kind, maps[kind], c)
        unk = [r["state"] for r in maps[kind].values() if r["lead"]["party"] == "?"]
        if unk:
            log.warning("Polymarket：%s 有領先者沒標黨派（%s），請在 "
                        "election.party_overrides 補上", kind, "、".join(unk))
        out[kind] = {"races": maps[kind], "tally": t,
                     "sentence": sentence(kind, t, c)}
    for kind, key in (("senate", "senate_seats_event"), ("house", "house_seats_event"),
                      ("governor", "governor_seats_event")):
        try:
            sm = (seat_mode(fetch_event(str(c.get(key) or ""), _get),
                            "州" if kind == "governor" else "席") if c.get(key) else None)
        except Exception:                          # noqa: BLE001
            sm = None
        if sm:
            out.setdefault("seats", {})[kind] = sm
    out["governor_before"] = dict(c.get("governor_before") or {})
    return out


def _days_to(date_iso: str) -> int | None:
    try:
        return (dt.date.fromisoformat(date_iso) - clock.today()).days
    except (TypeError, ValueError):
        return None


def build(cfg: dict | None, state_path: Path, offline: bool = False,
          _get=None) -> dict | None:
    """
    回傳卡片與 chip 要用的資料；停用、過了 hide_after、或完全沒有資料時回 None。
    """
    c = _cfg(cfg)
    if not c.get("enabled"):
        return None
    today = clock.today()
    try:
        if today > dt.date.fromisoformat(str(c["hide_after"])):
            return None
    except (TypeError, ValueError):
        pass
    if offline:
        return None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:                              # noqa: BLE001
        state = {}

    out: dict = {"election_date": str(c["election_date"]),
                 "days_to": _days_to(str(c["election_date"])),
                 "date": today.isoformat(), "source": "Polymarket"}
    try:
        for key in ("house", "senate"):
            ev = fetch_event(str(c[key]), _get)
            pair = _party_pair(ev) if ev and (_f(ev.get("volume")) or 0) >= float(
                c["min_volume"]) else None
            if pair:
                pair["hist"] = fetch_history(pair.pop("token"), _get)
                pair["url"] = EVENT_URL.format(slug=c[key])
                pair["vol"] = _f(ev.get("volume")) or 0.0
                out[key] = pair
            else:
                log.warning("Polymarket：%s 的盤不採用（找不到、交易量不足或"
                            "兩黨加總不接近 100%%）", key)
        ev = fetch_event(str(c["balance"]), _get)
        bal = _balance(ev) if ev and (_f(ev.get("volume")) or 0) >= float(
            c["min_volume"]) else None
        if bal:
            out["balance"] = {"rows": bal,
                              "url": EVENT_URL.format(slug=c["balance"]),
                              "vol": _f(ev.get("volume")) or 0.0}
        _evs = fetch_tag_events(str(c["tag"]), _get)
        out["races"] = pick_races(_evs, int(c["n_races"]), float(c["race_min_volume"]))
        if c.get("map"):
            try:
                out["maps"] = build_maps(_evs, c, _get)
            except Exception as e:                 # noqa: BLE001
                log.warning("Polymarket：各州地圖組裝失敗（%s）", e)
    except Exception as e:                         # noqa: BLE001
        log.warning("Polymarket 抓取失敗（%s）", e)

    if out.get("house") or out.get("senate"):
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        except Exception as e:                     # noqa: BLE001
            log.warning("選舉預測狀態寫入失敗（%s）", e)
        log.info("Polymarket：眾院民主黨 %s、參院民主黨 %s、選戰 %d 州",
                 f"{out['house']['dem']:.1%}" if out.get("house") else "—",
                 f"{out['senate']['dem']:.1%}" if out.get("senate") else "—",
                 len(out.get("races") or []))
        return out
    # 這次抓不到：沿用上次（最多 stale_days 天），畫面標日期
    try:
        age = (today - dt.date.fromisoformat(str(state.get("date")))).days
    except (TypeError, ValueError):
        age = 99
    if (state.get("house") or state.get("senate")) and age <= int(c["stale_days"]):
        log.warning("Polymarket：本次抓取失敗，沿用 %s 的結果", state.get("date"))
        return {**state, "stale_from": state.get("date"),
                "days_to": _days_to(str(c["election_date"]))}
    return None


def chips(pm: dict | None) -> list[dict]:
    """焦點條的兩顆 chip：眾院、參院（民主黨的價格）。"""
    from .focus_today import _mk
    out = []
    for key, label in (("house", "眾院・民主黨"), ("senate", "參院・民主黨")):
        d = (pm or {}).get(key)
        if not d:
            out.append(_mk(f"pm_{key}", label, "—", "本次擷取失敗", "", ""))
            continue
        d1 = d.get("d1")
        pp = None if d1 is None else round(d1 * 100, 1)
        # 不上漲跌色：全站的紅綠是「對利率／市場」的方向，選情沒有好壞之分
        out.append(_mk(f"pm_{key}", label, f"{d['dem'] * 100:.1f}%",
                       (f"{pp:+.1f} 百分點" if pp is not None else "—"), "",
                       str((pm or {}).get("stale_from") or (pm or {}).get("date") or "")))
    return out
