"""
首頁「AI 大事」（2026-10-29）：十家 AI 相關公司近 14 天的重大事件。

流程（每次執行）
  ① 每家公司一組 Google News 查詢（近 14 天），只留標題含公司名、主要媒體優先
  ② 沒看過的標題交給 AI（預設模型 Haiku）：判斷是不是五類重大事件之一
     （財報、資本支出、發債、融資／IPO、算力合約），是的話寫一句中文、
     同一件事併成一則；不是的丟掉。每則標題只判斷一次（state 記 seen）
  ③ 有新事件的公司，重寫一段「對市場的影響」（只根據該公司近 14 天的事件）
  ④ Anthropic IPO 進度：SEC 申報（S-1 → S-1/A → 424B4 定價 → 8-A12B／CERT 掛牌）
狀態存在 state/ai_events.json；任何一步失敗只少那一塊，不擋主流程。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html as _html
import json
import logging
import re
from pathlib import Path
from urllib.parse import quote_plus

from .. import clock

log = logging.getLogger(__name__)

TYPES = ("財報", "資本支出", "發債", "融資／IPO", "算力合約")
NEWS_URL = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
SEC_SUB = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_MAJOR = re.compile(r"reuters|bloomberg|wsj|wall street journal|financial times|cnbc|barron|"
                    r"marketwatch|associated press|yahoo finance|the information|axios|nikkei", re.I)
TOPIC_Q = ('(earnings OR capex OR "capital expenditure" OR bond OR debt OR notes OR funding OR '
           'valuation OR IPO OR "data center" OR compute OR deal OR contract OR raise)')
DEFAULTS = {
    "enabled": True, "window_days": 14, "new_days": 3, "per_company": 8,
    "ipo": {"name": "Anthropic", "cik": 2130357},
    "companies": [
        {"zh": "微軟", "q": '"Microsoft"', "match": ["Microsoft", "MSFT", "Azure"]},
        {"zh": "Alphabet", "q": '("Alphabet" OR "Google")', "match": ["Alphabet", "Google", "Gemini"]},
        {"zh": "亞馬遜", "q": '("Amazon" OR "AWS")', "match": ["Amazon", "AWS"]},
        {"zh": "Meta", "q": '("Meta Platforms" OR "Meta")', "match": ["Meta"]},
        {"zh": "甲骨文", "q": '"Oracle"', "match": ["Oracle"]},
        {"zh": "Nvidia", "q": '"Nvidia"', "match": ["Nvidia", "NVIDIA"]},
        {"zh": "CoreWeave", "q": '"CoreWeave"', "match": ["CoreWeave"]},
        {"zh": "Anthropic", "q": '"Anthropic"', "match": ["Anthropic", "Claude"]},
        {"zh": "OpenAI", "q": '"OpenAI"', "match": ["OpenAI", "ChatGPT"]},
        {"zh": "xAI", "q": '"xAI"', "match": ["xAI"]},
    ],
}

EVENT_SYSTEM = (
    "你是財經記者。輸入是一家公司近兩週的新聞標題（JSON：id、日期、媒體、標題），以及這家公司已收錄的事件。"
    "只挑出屬於這五類的重大事件：財報、資本支出、發債、融資／IPO、算力合約（雲端或晶片的大型採購、租用、合作建置）。"
    "產品發表、人事、訴訟、股價漲跌、評論文章都不要。同一件事的多則標題併成一則；已收錄的事件不要重複。"
    "每則用繁體中文寫一句（40 字以內）：發生了什麼，數字照標題（金額可換算成「億美元」），不加標題以外的事實、不做預測。"
    "只回 JSON：{\"events\": [{\"type\": \"五類之一\", \"zh\": \"一句話\", \"ids\": [\"用到的標題 id\"]}]}；沒有就回 {\"events\": []}。")
IMPACT_SYSTEM = (
    "你是財經記者，替美國利率與總經儀表板寫「對市場的影響」。輸入是一家公司近兩週的重大事件。"
    "用繁體中文寫一段 60–100 字：這些事件對公司債供給、長端利率、股市或 AI 投資熱度偏向什麼方向、為什麼。"
    "只能根據輸入的事件推論，用「偏向」「若…則…」，不做預測、不寫輸入以外的數字、不給投資建議。只輸出那一段文字。")


def _cfg(cfg: dict | None) -> dict:
    out = dict(DEFAULTS)
    out.update({k: v for k, v in (cfg or {}).items() if v is not None})
    return out


def _key(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:12]


def parse_rss(xml: str, match: list[str], since: dt.date) -> list[dict]:
    """Google News RSS → [{id,title,source,date,url}]：標題要含公司名、日期在窗內。"""
    pat = re.compile(r"\b(?:" + "|".join(re.escape(m) for m in match) + r")\b")
    out, seen = [], set()
    for it in re.findall(r"<item>(.*?)</item>", xml or "", re.S):
        def g(tag):
            m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", it, re.S)
            return _html.unescape(m.group(1).strip()) if m else ""
        title, src = g("title"), g("source")
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        if not pat.search(title):
            continue
        try:
            d = dt.datetime.strptime(g("pubDate")[:16].strip(), "%a, %d %b %Y").date()
        except ValueError:
            continue
        if d < since or title.lower() in seen:
            continue
        seen.add(title.lower())
        out.append({"id": _key(title, d), "title": title, "source": src, "date": d.isoformat(), "url": g("link")})
    out.sort(key=lambda x: x["date"], reverse=True)
    out.sort(key=lambda x: not _MAJOR.search(x["source"] or ""))
    return out


def ipo_stage(filings: list[dict]) -> dict:
    """SEC 申報 → IPO 進度。filings：[{form, date}]（新→舊或舊→新都可）。"""
    steps = [("遞交 S-1", ("S-1",)), ("S-1 修正版", ("S-1/A",)), ("定價", ("424B4", "424B1")),
             ("掛牌", ("8-A12B", "CERT", "CERTNAS", "CERTNYS"))]
    out = []
    for label, forms in steps:
        ds = sorted(f["date"] for f in filings if f.get("form") in forms)
        # 修正版可能有好幾次：顯示最近一次；其餘顯示第一次
        out.append({"label": label, "date": (ds[-1] if label == "S-1 修正版" else ds[0]) if ds else ""})
    listed = bool(out[-1]["date"])
    return {"steps": out, "listed": listed, "active": bool(out[0]["date"]) and not listed}


def _fetch(url: str, headers=None, _get=None) -> str:
    if _get:
        return _get(url) or ""
    import requests
    r = requests.get(url, timeout=20, headers=headers or {"User-Agent": "Mozilla/5.0 (macro-dashboard)"})
    return r.text if r.status_code == 200 else ""


def _ai(src: str, system: str, call=None) -> str:
    if call is None:
        from .focus_today import _call_ai
        text, err = _call_ai(src, system)            # 預設模型（Haiku）
        if err:
            log.warning("AI 大事：AI 呼叫失敗（%s）", err)
            return ""
        return text
    return call(src, system)


def build(cfg: dict | None, state_path: Path, offline: bool = False, _get=None, call=None) -> dict | None:
    c = _cfg(cfg)
    if not c.get("enabled"):
        return None
    today = clock.today()
    since = today - dt.timedelta(days=int(c["window_days"]))
    try:
        state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    except Exception:                                # noqa: BLE001
        state = {}
    seen: dict = state.get("seen") or {}
    events: list = [e for e in state.get("events") or [] if e.get("date", "") >= since.isoformat()]
    impact: dict = state.get("impact") or {}
    changed: set = set()
    if not offline:
        for co in c["companies"]:
            try:
                q = quote_plus(f'{co["q"]} {TOPIC_Q} when:{int(c["window_days"])}d')
                heads = parse_rss(_fetch(NEWS_URL.format(q=q), _get=_get), co["match"], since)
            except Exception as e:                   # noqa: BLE001
                log.warning("AI 大事：%s 新聞抓取失敗（%s）", co["zh"], e)
                continue
            new = [h for h in heads if h["id"] not in seen][: int(c["per_company"])]
            if not new:
                continue
            have = [e["zh"] for e in events if e["co"] == co["zh"]]
            src = json.dumps({"company": co["zh"], "already": have,
                              "headlines": [{k: h[k] for k in ("id", "date", "source", "title")} for h in new]},
                             ensure_ascii=False)
            text = _ai(src, EVENT_SYSTEM, call)
            if not text:
                continue                             # 失敗：這批標題不記 seen，下次再試
            m = re.search(r"\{.*\}", text, re.S)
            try:
                got = json.loads(m.group(0)).get("events") or [] if m else []
            except ValueError:
                got = []
            byid = {h["id"]: h for h in new}
            for ev in got:
                ids = [i for i in ev.get("ids") or [] if i in byid]
                if ev.get("type") not in TYPES or not ids or not str(ev.get("zh") or "").strip():
                    continue
                hs = [byid[i] for i in ids]
                events.append({"id": _key(co["zh"], ev["zh"]), "co": co["zh"], "type": ev["type"],
                               "zh": str(ev["zh"]).strip()[:80], "date": max(h["date"] for h in hs),
                               "links": [{"title": h["title"], "source": h["source"], "url": h["url"]} for h in hs[:3]]})
                changed.add(co["zh"])
            for h in new:
                seen[h["id"]] = h["date"]
        # 對市場的影響：有新事件、或還沒寫過的公司
        for co in c["companies"]:
            evs = sorted([e for e in events if e["co"] == co["zh"]], key=lambda e: e["date"], reverse=True)
            if not evs:
                impact.pop(co["zh"], None)
                continue
            h = _key(*[e["id"] for e in evs])
            if (impact.get(co["zh"]) or {}).get("hash") == h:
                continue
            src = json.dumps({"company": co["zh"], "events": [{"date": e["date"], "type": e["type"], "zh": e["zh"]}
                                                               for e in evs]}, ensure_ascii=False)
            text = (_ai(src, IMPACT_SYSTEM, call) or "").strip()
            if text:
                impact[co["zh"]] = {"hash": h, "text": text.splitlines()[0][:200]}
        # IPO 進度
        ipo = c.get("ipo") or {}
        if ipo.get("cik"):
            try:
                from ..sec import USER_AGENT
                d = json.loads(_fetch(SEC_SUB.format(cik=int(ipo["cik"])), {"User-Agent": USER_AGENT}, _get) or "{}")
                r = (d.get("filings") or {}).get("recent") or {}
                state["ipo"] = {"name": ipo.get("name", ""), **ipo_stage(
                    [{"form": f, "date": x} for f, x in zip(r.get("form") or [], r.get("filingDate") or [])])}
            except Exception as e:                   # noqa: BLE001
                log.warning("AI 大事：IPO 進度抓取失敗（%s）", e)
    seen = {k: v for k, v in seen.items() if v >= (since - dt.timedelta(days=7)).isoformat()}
    events.sort(key=lambda e: e["date"], reverse=True)
    state.update({"seen": seen, "events": events, "impact": impact, "at": clock.stamp()})
    try:
        Path(state_path).parent.mkdir(parents=True, exist_ok=True)
        Path(state_path).write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        log.warning("AI 大事狀態寫入失敗（%s）", e)
    if not events and not state.get("ipo"):
        return None
    new_since = (today - dt.timedelta(days=int(c["new_days"]) - 1)).isoformat()
    return {"companies": [x["zh"] for x in c["companies"]], "events": events,
            "impact": {k: v["text"] for k, v in impact.items()}, "ipo": state.get("ipo") or {},
            "new_since": new_since, "window_days": int(c["window_days"]),
            "changed": sorted(changed)}
