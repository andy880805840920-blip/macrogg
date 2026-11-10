"""
AI 資料中心擴張與監管（首頁 AI 大事視窗，2026-11）。

資料
----
算力與電力　Epoch AI「Frontier Data Centers」（CC BY 4.0）：美國各大 AI 資料中心園區的時間軸，
            每一筆是某個日期的 IT 電力（MW）與算力（H100 等效顆數），未來日期是 Epoch 依公告、
            許可文件、衛星影像推估的完工時程。只涵蓋「前沿 AI 資料中心」，不是全美所有機房。
州長　　　　改選前現任黨派（config/datacenters.yaml）＋ Polymarket 已結算的 2026 州長盤（closed 事件）；
            還沒結算的州用 election 模組的即時盤口，標「領先」。
國會　　　　election 模組的參眾兩院盤口（已結算＝確定）。
監管　　　　每州近 30 天新聞標題 → AI 一句政策動向＋對建設時程的影響（附原文）；聯邦層級另一組。

計算
----
某年「累積」＝該州每個園區在當年 12/31 以前最後一筆時間軸數值的加總；
某年「新增」＝當年累積 − 前一年累積（可為負：Epoch 下修時程或站點延後）。
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import logging
import re
from pathlib import Path
from urllib.parse import quote_plus

from .. import clock

log = logging.getLogger(__name__)

EPOCH = "https://epoch.ai/data/data_centers/{f}.csv"
EPOCH_PAGE = "https://epoch.ai/data/data-centers"
NEWS_URL = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"

ABBR_NAME = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
             "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
             "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
             "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
             "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
             "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
             "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
             "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
             "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
             "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
             "DC": "District of Columbia"}
NAME_ABBR = {v: k for k, v in ABBR_NAME.items()}
_AB_RE = re.compile(r"(?:,|\s)\s*(" + "|".join(ABBR_NAME) + r")\b(?:\s*\d{5})?\s*(?:,|$|\s)")
_NM_RE = re.compile(r"\b(" + "|".join(sorted(NAME_ABBR, key=len, reverse=True)) + r")\b")


# ---------------------------------------------------------------------------
# Epoch：讀檔、州別、彙總
# ---------------------------------------------------------------------------
def _rows(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text or "")))


def _f(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _tag(s: str) -> str:
    """'Oracle #confident, OpenAI #likely' → 'Oracle、OpenAI'（Epoch 的把握程度標記拿掉）。"""
    parts = [re.sub(r"\s*#\w+", "", p).strip() for p in (s or "").split(",")]
    return "、".join(p for p in parts if p)


def site_state(row: dict, overrides: dict) -> str | None:
    """園區所在州：設定檔優先 → 地址裡的州代碼 → 地址或名稱裡的州全名。"""
    if row.get("Name") in (overrides or {}):
        return str(overrides[row["Name"]]).upper()
    addr = (row.get("Address") or "").replace("\n", " ")
    m = _AB_RE.search(" " + addr + " ")
    if m:
        return m.group(1)
    for s in (addr, row.get("Name") or ""):
        m = _NM_RE.search(s)
        if m:
            return NAME_ABBR[m.group(1)]
    return None


def _at(tl: list[dict], date: str, col: str) -> float:
    v = 0.0
    for r in tl:
        if r["Date"] <= date:
            v = _f(r.get(col))
        else:
            break
    return v


def aggregate(dcs: list[dict], tls: list[dict], years, overrides: dict, today: str) -> dict:
    """
    → {"states": {AB: {"lvl": {y: {mw, h}}, "add": {y: {mw, h}}, "sites": [...]}}, "total": {...}, "missing": [...]}
    """
    by: dict = {}
    for r in tls:
        by.setdefault(r.get("Data center"), []).append(r)
    for v in by.values():
        v.sort(key=lambda r: r["Date"])
    states: dict = {}
    missing = []
    ys = list(years)
    for d in dcs:
        if (d.get("Country") or "") != "United States":
            continue
        ab = site_state(d, overrides)
        if not ab:
            missing.append(d.get("Name"))
            continue
        tl = by.get(d["Name"]) or []
        s = states.setdefault(ab, {"lvl": {y: {"mw": 0.0, "h": 0.0} for y in [ys[0] - 1] + ys}, "sites": []})
        for y in [ys[0] - 1] + ys:
            s["lvl"][y]["mw"] += _at(tl, f"{y}-12-31", "IT power (MW)")
            s["lvl"][y]["h"] += _at(tl, f"{y}-12-31", "H100 equivalents")
        # 時間軸：只留數值有變的節點（未來日期＝Epoch 推估）
        ms, last = [], None
        for r in tl:
            key = (round(_f(r.get("IT power (MW)"))), round(_f(r.get("H100 equivalents")), -3))
            if key == last:
                continue
            last = key
            ms.append({"d": r["Date"][:7], "mw": round(_f(r.get("IT power (MW)"))),
                       "h": round(_f(r.get("H100 equivalents"))), "f": r["Date"] > today})
        past = [r for r in tl if r["Date"] <= today and (r.get("Construction status") or "").strip()]
        s["sites"].append({
            "name": d["Name"], "owner": _tag(d.get("Owner")), "users": _tag(d.get("Users")),
            "now_mw": round(_at(tl, today, "IT power (MW)")), "now_h": round(_at(tl, today, "H100 equivalents")),
            "end_mw": round(_f(tl[-1].get("IT power (MW)"))) if tl else 0,
            "end_h": round(_f(tl[-1].get("H100 equivalents"))) if tl else 0,
            "end_d": tl[-1]["Date"][:7] if tl else "",
            "ms": ms[-10:], "note_en": (past[-1]["Construction status"].strip()[:600] if past else ""),
            "note_d": past[-1]["Date"] if past else ""})
    for s in states.values():
        s["add"] = {y: {k: s["lvl"][y][k] - s["lvl"][y - 1][k] for k in ("mw", "h")} for y in ys}
        s["sites"].sort(key=lambda x: -x["end_h"])
    total = {y: {k: sum(s["lvl"][y][k] for s in states.values()) for k in ("mw", "h")} for y in [ys[0] - 1] + ys}
    if missing:
        log.warning("資料中心：找不到州的站點 %s（在 config/datacenters.yaml 的 state_overrides 補）", "、".join(missing))
    return {"states": states, "total": total, "missing": missing}


# ---------------------------------------------------------------------------
# 政治：州長（改選前 → 2026 結果）、國會
# ---------------------------------------------------------------------------
def governors(cfg: dict, election: dict | None, _get=None, offline: bool = False) -> dict:
    """{AB: {"before": D/R, "after": D/R/?, "name": 當選人, "status": "定"/"領先"/"沒改選", "flip": bool}}"""
    gb = cfg.get("governor_before") or {}
    before = {ab: p for p in ("D", "R") for ab in gb.get(p) or []}
    out = {ab: {"before": p, "after": p, "name": "", "status": "沒改選", "flip": False} for ab, p in before.items()}
    from . import polymarket as pm
    up = {pm.ABBR.get(s) for s in pm.GOVERNOR_2026}
    for ab in up:
        if ab in out:
            out[ab].update(after="?", status="未知")
    res: dict = {}
    if not offline:
        try:
            ovr = ((cfg.get("_election_cfg") or {}).get("party_overrides")) or {}
            for ev in pm.fetch_tag_events("midterms", _get, closed=True):
                r = pm.state_race(ev, ovr)
                if r and r["kind"] == "governor" and r["lead"]["p"] >= 0.95:
                    res[r["abbr"]] = {"after": r["lead"]["party"], "name": r["lead"]["name"], "status": "定"}
        except Exception as e:                       # noqa: BLE001
            log.warning("資料中心：州長結果抓取失敗（%s）", e)
    # 還在交易的盤（例：計票未完的州）：用選舉模組的即時盤口
    for st, r in (((election or {}).get("maps") or {}).get("governor") or {}).get("races", {}).items():
        ab = r.get("abbr")
        if ab and ab not in res:
            res[ab] = {"after": r["lead"]["party"], "name": r["lead"]["name"], "status": "領先",
                       "p": r["lead"]["p"]}
    for ab, r in res.items():
        if ab in out:
            out[ab].update(r)
            out[ab]["flip"] = r["after"] in ("D", "R") and r["after"] != out[ab]["before"]
    return out


def congress(election: dict | None) -> dict:
    """參眾兩院：Polymarket 盤口（closed＝已結算，等於確定）。"""
    out = {}
    for k, zh in (("house", "眾議院"), ("senate", "參議院")):
        d = (election or {}).get(k) or {}
        if d.get("dem") is None:
            continue
        win = "D" if d["dem"] >= d["rep"] else "R"
        out[k] = {"zh": zh, "win": win, "p": max(d["dem"], d["rep"]), "closed": bool(d.get("closed"))}
    return out


# ---------------------------------------------------------------------------
# 監管新聞（AI 整理，數字要在標題裡找得到）
# ---------------------------------------------------------------------------
STATE_SYSTEM = (
    "你是財經記者，替台灣讀者整理美國某一州的 AI 資料中心政策。輸入：州名、州長（改選前→選後）、該州主要 AI 資料中心"
    "（Epoch AI 的電力與完工時程）、近 30 天新聞標題（id、日期、媒體、標題）。"
    "只根據標題，用繁體中文寫：policy＝州政府／議會／公用事業委員會／州長對 AI 或資料中心的最新政策方向（50 字內，"
    "沒有相關標題就寫空字串）；impact＝對上列資料中心建設時程的可能影響（40 字內，用「偏向」「若…則…」，不做預測）；"
    "risk＝推遲風險「高」「中」「低」或「資料不足」。公司名用英文。不寫標題以外的事實或數字。"
    "只回 JSON：{\"policy\": \"…\", \"impact\": \"…\", \"risk\": \"…\", \"ids\": [\"用到的標題 id\"]}。")
FED_SYSTEM = (
    "你是財經記者。輸入是近兩週美國聯邦層級 AI 監管的新聞標題（id、日期、媒體、標題），以及國會選舉結果。"
    "用繁體中文寫 2–4 點（每點 45 字內）：國會、白宮、聯邦機構對 AI 監管或州法優先權（preemption）、資料中心用電與許可的最新動向，"
    "以及新國會對這些議題的可能方向（只能根據輸入推論，用「偏向」）。不寫輸入以外的數字。"
    "只回 JSON：{\"points\": [{\"zh\": \"…\", \"ids\": [\"…\"]}]}。")


def _ai(src: str, system: str, call=None) -> str:
    if call is None:
        from .focus_today import _call_ai
        text, err = _call_ai(src, system)
        if err:
            log.warning("資料中心：AI 呼叫失敗（%s）", err)
            return ""
        return text
    return call(src, system)


def _json(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except ValueError:
        return {}


def _fetch(url: str, _get=None) -> str:
    if _get:
        return _get(url) or ""
    import requests
    r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0 (macro-dashboard)"})
    return r.text if r.status_code == 200 else ""


def _h(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:12]


def state_reg(ab: str, gov: dict, sites: list, cache: dict, days: int, _get=None, call=None) -> dict | None:
    from .ai_events import parse_rss
    from .ipo_docs import check_points
    name = ABBR_NAME[ab]
    since = clock.today() - dt.timedelta(days=days)
    q = quote_plus(f'"{name}" ("data center" OR "data centers") (moratorium OR regulation OR bill OR law OR '
                   f'legislature OR governor OR "utility commission" OR "public service commission" OR tariff OR '
                   f'permit OR "AI law" OR ban) when:{days}d')
    heads = parse_rss(_fetch(NEWS_URL.format(q=q), _get), [name], since)[:14]
    if not heads:
        return cache.get(ab)
    key = _h(*[h["id"] for h in heads], gov.get("after"), gov.get("status"))
    if (cache.get(ab) or {}).get("hash") == key:
        return cache[ab]
    src = {"state": name, "governor": {"before": gov.get("before"), "after": gov.get("after"),
                                       "winner": gov.get("name"), "status": gov.get("status")},
           "sites": [{"name": s["name"], "owner": s["owner"], "mw_now": s["now_mw"], "mw_end": s["end_mw"],
                      "end": s["end_d"]} for s in sites[:6]],
           "headlines": [{k: h[k] for k in ("id", "date", "source", "title")} for h in heads]}
    j = _json(_ai(json.dumps(src, ensure_ascii=False), STATE_SYSTEM, call))
    if not j:
        return cache.get(ab)
    titles = " ".join(h["title"] for h in heads) + " " + json.dumps(src["sites"])
    byid = {h["id"]: h for h in heads}
    pol = (check_points([str(j.get("policy") or "")[:90]], titles) or [""])[0]
    imp = (check_points([str(j.get("impact") or "")[:80]], titles) or [""])[0]
    risk = j.get("risk") if j.get("risk") in ("高", "中", "低", "資料不足") else "資料不足"
    links = [{"source": byid[i]["source"], "url": byid[i]["url"], "title": byid[i]["title"], "date": byid[i]["date"]}
             for i in j.get("ids") or [] if i in byid][:3]
    out = {"hash": key, "policy": pol, "impact": imp, "risk": risk if (pol or imp) else "資料不足",
           "links": links, "at": clock.today().isoformat()}
    cache[ab] = out
    return out


def federal_reg(cong: dict, cache: dict, _get=None, call=None) -> dict | None:
    from .ai_events import parse_rss
    from .ipo_docs import check_points
    since = clock.today() - dt.timedelta(days=14)
    q = quote_plus('("AI regulation" OR "AI law" OR "AI moratorium" OR preemption OR "AI executive order" OR '
                   '"data center" ) (Congress OR "White House" OR Senate OR FERC OR "executive order") when:14d')
    heads = [h for h in parse_rss(_fetch(NEWS_URL.format(q=q), _get), [], since)
             if re.search(r"\bAI\b|data center|artificial intelligence", h["title"], re.I)][:20]
    if not heads:
        return cache.get("_fed")
    key = _h(*[h["id"] for h in heads], json.dumps(cong, sort_keys=True))
    if (cache.get("_fed") or {}).get("hash") == key:
        return cache["_fed"]
    j = _json(_ai(json.dumps({"congress": cong, "headlines": [{k: h[k] for k in ("id", "date", "source", "title")}
                                                               for h in heads]}, ensure_ascii=False), FED_SYSTEM, call))
    byid = {h["id"]: h for h in heads}
    titles = " ".join(h["title"] for h in heads)
    pts = []
    for p in j.get("points") or []:
        zh = (check_points([str(p.get("zh") or "")[:80]], titles) or [""])[0]
        if not zh:
            continue
        pts.append({"zh": zh, "links": [{"source": byid[i]["source"], "url": byid[i]["url"]}
                                        for i in p.get("ids") or [] if i in byid][:2]})
    if not pts:
        return cache.get("_fed")
    cache["_fed"] = {"hash": key, "points": pts, "at": clock.today().isoformat()}
    return cache["_fed"]


NOTE_SYSTEM = (
    "把每個資料中心最新的施工進度（英文，來自 Epoch AI）翻成繁體中文一句（45 字內），保留數字與單位（MW、棟數），"
    "公司名用英文，不加原文以外的內容。輸入 JSON {名稱: 英文}，只回 JSON {名稱: 中文}。")


def translate_notes(states: dict, cache: dict, call=None) -> None:
    """每個園區最新進度翻成中文；以英文原文的雜湊快取，原文沒變不重翻。"""
    from .ipo_docs import check_points
    todo = {}
    for s in states.values():
        for x in s["sites"]:
            if not x.get("note_en"):
                continue
            k = _h(x["name"], x["note_en"])
            if (cache.get(x["name"]) or {}).get("hash") == k:
                x["note"] = cache[x["name"]]["zh"]
            else:
                todo[x["name"]] = (k, x)
    names = list(todo)
    for i in range(0, len(names), 15):
        batch = {n: todo[n][1]["note_en"][:500] for n in names[i:i + 15]}
        j = _json(_ai(json.dumps(batch, ensure_ascii=False), NOTE_SYSTEM, call))
        for n, zh in j.items():
            if n in todo and isinstance(zh, str):
                zh = (check_points([zh.strip()[:70]], batch[n]) or [""])[0]
                if zh:
                    cache[n] = {"hash": todo[n][0], "zh": zh}
                    todo[n][1]["note"] = zh


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def build(cfg: dict | None, state_path: Path, election: dict | None = None, election_cfg: dict | None = None,
          offline: bool = False, _get=None, call=None) -> dict | None:
    c = dict(cfg or {})
    if not c.get("enabled", True):
        return None
    c["_election_cfg"] = election_cfg or {}
    years = [int(y) for y in c.get("years") or (2025, 2026, 2027, 2028)]
    today = clock.today().isoformat()
    try:
        st = json.loads(Path(state_path).read_text(encoding="utf-8"))
    except Exception:                                # noqa: BLE001
        st = {}
    agg = None
    if not offline:
        try:
            dcs = _rows(_fetch(EPOCH.format(f="data_centers"), _get))
            tls = _rows(_fetch(EPOCH.format(f="data_center_timelines"), _get))
            if len(dcs) > 20 and len(tls) > 50:
                agg = aggregate(dcs, tls, years, c.get("state_overrides") or {}, today)
                agg["epoch_at"] = today
        except Exception as e:                       # noqa: BLE001
            log.warning("資料中心：Epoch 資料抓取失敗（%s），沿用上次結果", e)
    if agg is None:
        agg = st.get("agg")
        if agg:                                      # JSON 存檔後年份鍵變字串，換回整數
            for s in agg["states"].values():
                for k in ("lvl", "add"):
                    s[k] = {int(y): v for y, v in s[k].items()}
            agg["total"] = {int(y): v for y, v in agg["total"].items()}
    if not agg or not agg.get("states"):
        return None
    gov = governors(c, election, _get, offline)
    cong = congress(election)
    # 選舉卡 hide_after 之後 election 會是 None：沿用最後一次的國會結果與還在計票州的領先者
    if cong:
        st["congress"] = cong
    else:
        cong = st.get("congress") or {}
    prev_gov = st.get("gov") or {}
    for ab, g in gov.items():
        if g.get("after") == "?" and (prev_gov.get(ab) or {}).get("after") not in (None, "?"):
            gov[ab] = prev_gov[ab]
    st["gov"] = gov
    reg_cache: dict = st.get("reg") or {}
    note_cache: dict = st.get("notes") or {}
    if not offline:
        last = years[-1]
        top = sorted(agg["states"], key=lambda a: -agg["states"][a]["lvl"][last]["h"])[: int(c.get("reg_states", 14))]
        for ab in top:
            try:
                state_reg(ab, gov.get(ab, {}), agg["states"][ab]["sites"], reg_cache,
                          int(c.get("reg_window_days", 30)), _get, call)
            except Exception as e:                   # noqa: BLE001
                log.warning("資料中心：%s 監管新聞整理失敗（%s）", ab, e)
        try:
            federal_reg(cong, reg_cache, _get, call)
        except Exception as e:                       # noqa: BLE001
            log.warning("資料中心：聯邦監管新聞整理失敗（%s）", e)
        try:
            translate_notes(agg["states"], note_cache, call)
        except Exception as e:                       # noqa: BLE001
            log.warning("資料中心：進度翻譯失敗（%s）", e)
    else:
        for s in agg["states"].values():
            for x in s["sites"]:
                if (note_cache.get(x["name"]) or {}).get("zh"):
                    x["note"] = note_cache[x["name"]]["zh"]
    st.update({"agg": agg, "reg": reg_cache, "notes": note_cache, "at": clock.stamp()})
    try:
        Path(state_path).parent.mkdir(parents=True, exist_ok=True)
        Path(state_path).write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        log.warning("資料中心狀態寫入失敗（%s）", e)
    return {"years": years, "states": agg["states"], "total": agg["total"], "epoch_at": agg.get("epoch_at", ""),
            "gov": gov, "congress": cong, "reg": {k: v for k, v in reg_cache.items() if k != "_fed"},
            "fed": reg_cache.get("_fed"), "source": EPOCH_PAGE}
