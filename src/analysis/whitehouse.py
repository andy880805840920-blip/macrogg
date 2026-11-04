"""
首頁「白宮與國會」（2026-11，取代期中選舉那一格；設定：config/whitehouse.yaml）。

每次執行
  ① 川普說了什麼：Google News（近 7 天、標題含 Trump／White House）＋白宮公告。
     沒看過的標題交給 AI：只挑跟市場有關的（財政、聯準會、AI 與晶片、能源、關稅），
     每則寫一句中文、標管道與主題；同一件事併成一則。每則標題只判斷一次（state 記 seen）。
  ② 政策進度：清單人工維護（A）。每項政策有自己的新聞查詢，AI 只判斷「是否可能已進到下一段」，
     結果寫進執行紀錄與 state["suggestions"] 提醒維護者（B），**不改畫面**。
     updated 超過 stale_days 天也提醒。
  ③ 本週重點：依①②寫 2–3 句；內容沒變就沿用，每天最多重寫一次。
  ④ 政策不確定性指數：FRED USEPUINDXD（每日、波動大，畫 30 日均）。
狀態存在 state/whitehouse.json；任何一步失敗只少那一塊，不擋主流程。
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
from pathlib import Path
from urllib.parse import quote_plus

from .. import clock
from .ai_events import NEWS_URL, _ai, _fetch, _key, _sim, parse_rss

log = logging.getLogger(__name__)

TOPICS = ("財政", "聯準會", "AI 與晶片", "能源", "關稅")
CHANNELS = ("Truth Social", "記者會", "受訪", "演說", "行政命令", "白宮公告", "其他")
WH_FEED = "https://www.whitehouse.gov/presidential-actions/feed/"
TRUMP_Q = ('Trump (tariff OR tariffs OR Fed OR "interest rates" OR Warsh OR oil OR energy OR LNG OR '
           'chips OR Nvidia OR "artificial intelligence" OR AI OR budget OR shutdown OR "executive order")')
EPU = "USEPUINDXD"

STATEMENT_SYSTEM = (
    "你是財經記者，替美國利率與總經儀表板整理「川普說了什麼」。輸入是近一週的新聞標題（JSON：id、日期、媒體、標題），"
    "以及已收錄的項目。只挑川普本人（或白宮正式公告、行政命令）**跟市場有關**的發言或動作，主題限五類："
    "財政（預算、停擺、舉債、減稅）、聯準會（利率、人事、施壓）、AI 與晶片（出口管制、晶片、AI 法規、資料中心）、"
    "能源（油氣、電力、核能、LNG）、關稅（關稅、貿易協議）。其他政治、選舉、司法、外交新聞都不要；評論文章不要。"
    "同一件事的多則標題併成一則；已收錄的不要重複。"
    "每則用繁體中文寫一句（35 字以內）：他說了什麼或做了什麼，只寫標題裡有的事實，不評論、不預測、不引用長段原話。"
    "管道從這幾個選一個：Truth Social、記者會、受訪、演說、行政命令、白宮公告、其他。"
    "只回 JSON：{\"items\": [{\"topic\": \"五類之一\", \"channel\": \"管道\", \"zh\": \"一句話\", \"ids\": [\"標題 id\"]}]}；"
    "沒有就回 {\"items\": []}。")
PROGRESS_SYSTEM = (
    "你在幫儀表板維護者檢查政策進度。輸入是一項政策（名稱、各階段、目前階段、下一步）以及近一週的新聞標題。"
    "判斷新聞是否顯示這項政策**可能已經進到下一階段**，或下一步的日期改了。只根據標題，不確定就說不確定。"
    "只回 JSON：{\"changed\": true 或 false, \"note\": \"繁體中文一句話，說明哪則新聞、可能的新階段或新日期\"}。")
SUMMARY_SYSTEM = (
    "你是財經記者，替美國利率與總經儀表板寫「白宮與國會・本週重點」。輸入是近一週川普跟市場有關的發言，"
    "以及政策進度清單（名稱、目前階段、下一步）。用繁體中文寫 2–3 句、合計 90 字以內："
    "本週最重要的一兩件事，以及接下來最近的關鍵日期。只能用輸入裡的事實，不評論對錯、不預測、不給投資建議。只輸出那段文字。")


def _cfg(cfg: dict | None) -> dict:
    out = {"enabled": False, "election_tile": False, "window_days": 7, "new_days": 3, "stale_days": 14,
           "topics": list(TOPICS), "policies": []}
    out.update({k: v for k, v in (cfg or {}).items() if v is not None})
    return out


def _d(x) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(x)[:10])
    except (TypeError, ValueError):
        return None


def policy_rows(policies: list, today: dt.date, stale_days: int = 14) -> list[dict]:
    """設定檔的政策清單 → 畫面用的列（倒數、過時旗標）。格式不對的那一項略過。"""
    out = []
    for p in policies or []:
        stages = [str(s) for s in p.get("stages") or []]
        if not p.get("name") or not stages:
            continue
        stage = max(1, min(len(stages), int(p.get("stage") or 1)))
        nx = p.get("next") or {}
        nd = _d(nx.get("date"))
        days = (nd - today).days if nd else None
        up = _d(p.get("updated"))
        ch = _d(p.get("changed"))          # 進度真的變了的那天（亮橘點用）；updated 只是最後確認日
        out.append({
            "id": str(p.get("id") or _key(p["name"])), "name": str(p["name"]),
            "topics": [t for t in p.get("topics") or [] if t in TOPICS] or ["財政"],
            "stages": stages, "stage": stage, "status": str(p.get("status") or ""),
            "next_date": nd.isoformat() if nd and days is not None and days >= 0 else "",
            "next_text": str(nx.get("text") or ""), "days": days if days is not None and days >= 0 else None,
            "impact": str(p.get("impact") or ""), "link": p.get("link") or {},
            "updated": up.isoformat() if up else "", "changed": ch.isoformat() if ch else "",
            "stale": bool(up and (today - up).days > int(stale_days)),
            "q": str(p.get("q") or ""),
        })
    return out


def calendar_events(rows: list[dict], today: dt.date, days: int = 45) -> list[dict]:
    """有明確日期的政策下一步 → 首頁「接下來看什麼」月曆的「政策」項目。"""
    out = []
    for r in rows:
        d = _d(r.get("next_date"))
        if d and today <= d <= today + dt.timedelta(days=days):
            out.append({"date": d.isoformat(), "name": f'{r["name"]}：{r["next_text"]}' if r["next_text"] else r["name"],
                        "topics": r["topics"]})
    return out


def merge_items(items: list[dict], days: int = 2) -> list[dict]:
    """同主題、日期相近、句子幾乎一樣 → 同一則（留來源較多的那句，連結合併）。"""
    out: list[dict] = []
    for e in sorted(items, key=lambda x: x.get("date", ""), reverse=True):
        hit = None
        for k in out:
            a, b = _d(k.get("date")), _d(e.get("date"))
            if k["topic"] == e["topic"] and a and b and abs((a - b).days) <= days and _sim(k["zh"], e["zh"], "") >= 0.5:
                hit = k
                break
        if not hit:
            out.append(dict(e, links=list(e.get("links") or [])))
            continue
        urls = {x.get("url") for x in hit["links"]}
        hit["links"] = (hit["links"] + [x for x in e.get("links") or [] if x.get("url") not in urls])[:3]
        hit["date"] = max(hit["date"], e["date"])
    return out


def epu_block(series: dict | None, today: dt.date) -> dict | None:
    """政策不確定性指數：最新 30 日均、近一年分位、近 180 天的 30 日均走勢。"""
    obs = [(_d(o.get("date")), o.get("value")) for o in (series or {}).get(EPU) or []]
    obs = [(d, float(v)) for d, v in obs if d and isinstance(v, (int, float))]
    if len(obs) < 40:
        return None
    obs.sort()
    vals = [v for _, v in obs]
    ma = [sum(vals[max(0, i - 29):i + 1]) / len(vals[max(0, i - 29):i + 1]) for i in range(len(vals))]
    year = [m for (d, _), m in zip(obs, ma) if d >= obs[-1][0] - dt.timedelta(days=365)]
    pct = sum(1 for m in year if m <= ma[-1]) / len(year) * 100 if year else None
    level = ("偏高" if pct is not None and pct >= 75 else "偏低" if pct is not None and pct <= 25 else "中等")
    spark = [(d.isoformat(), round(m, 1)) for (d, _), m in zip(obs, ma) if d >= obs[-1][0] - dt.timedelta(days=180)]
    return {"value": round(ma[-1]), "pct": round(pct) if pct is not None else None, "level": level,
            "date": obs[-1][0].isoformat(), "spark": spark[::3] + ([spark[-1]] if spark and (len(spark) - 1) % 3 else [])}


def _json(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except ValueError:
        return {}


def build(cfg: dict | None, state_path: Path, offline: bool = False, series: dict | None = None,
          _get=None, call=None) -> dict | None:
    c = _cfg(cfg)
    if not c.get("enabled"):
        return None
    today = clock.today()
    win = int(c["window_days"])
    since = today - dt.timedelta(days=win)
    try:
        state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    except Exception:                                # noqa: BLE001
        state = {}
    seen: dict = state.get("seen") or {}
    items = [x for x in state.get("items") or [] if x.get("date", "") >= since.isoformat()]
    rows = policy_rows(c.get("policies") or [], today, int(c["stale_days"]))
    suggestions: dict = state.get("suggestions") or {}
    for r in rows:
        if r["stale"]:
            log.warning("白宮與國會：「%s」的進度 %s 之後就沒確認過（config/whitehouse.yaml）", r["name"], r["updated"])
    if not offline:
        # ① 川普說了什麼
        heads = []
        try:
            q = quote_plus(f"{TRUMP_Q} when:{win}d")
            heads += parse_rss(_fetch(NEWS_URL.format(q=q), _get=_get), ["Trump", "White House"], since)
        except Exception as e:                       # noqa: BLE001
            log.warning("白宮與國會：新聞抓取失敗（%s）", e)
        try:
            heads += [dict(h, source=h.get("source") or "白宮公告")
                      for h in parse_rss(_fetch(WH_FEED, _get=_get), [], since)]
        except Exception as e:                       # noqa: BLE001
            log.warning("白宮與國會：白宮公告抓取失敗（%s）", e)
        new = [h for h in heads if h["id"] not in seen][:30]
        if new:
            src = json.dumps({"already": [x["zh"] for x in items],
                              "headlines": [{k: h[k] for k in ("id", "date", "source", "title")} for h in new]},
                             ensure_ascii=False)
            text = _ai(src, STATEMENT_SYSTEM, call)
            if text:
                byid = {h["id"]: h for h in new}
                for it in _json(text).get("items") or []:
                    ids = [i for i in it.get("ids") or [] if i in byid]
                    zh = str(it.get("zh") or "").strip()[:60]
                    if it.get("topic") not in TOPICS or not ids or not zh:
                        continue
                    hs = [byid[i] for i in ids]
                    ch = it.get("channel") if it.get("channel") in CHANNELS else "其他"
                    items.append({"id": _key(it["topic"], zh), "topic": it["topic"], "channel": ch, "zh": zh,
                                  "date": max(h["date"] for h in hs),
                                  "links": [{"title": h["title"], "source": h["source"], "url": h["url"]} for h in hs[:3]]})
                for h in new:
                    seen[h["id"]] = h["date"]
        # ② 政策進度提醒（不改畫面）
        for r in rows:
            if not r["q"]:
                continue
            try:
                q = quote_plus(f'{r["q"]} when:{win}d')
                ph = [h for h in parse_rss(_fetch(NEWS_URL.format(q=q), _get=_get), [], since)
                      if f'p:{r["id"]}:{h["id"]}' not in seen][:10]
            except Exception as e:                   # noqa: BLE001
                log.warning("白宮與國會：「%s」新聞抓取失敗（%s）", r["name"], e)
                continue
            if not ph:
                continue
            src = json.dumps({"policy": {"name": r["name"], "stages": r["stages"], "current": r["stages"][r["stage"] - 1],
                                         "next": r["next_text"], "next_date": r["next_date"]},
                              "headlines": [{k: h[k] for k in ("date", "source", "title")} for h in ph]},
                             ensure_ascii=False)
            got = _json(_ai(src, PROGRESS_SYSTEM, call))
            if got.get("changed"):
                note = str(got.get("note") or "")[:120]
                suggestions[r["id"]] = {"date": today.isoformat(), "note": note,
                                        "links": [h["url"] for h in ph[:3]]}
                log.warning("白宮與國會：「%s」可能有新進度，請確認後更新 config/whitehouse.yaml：%s", r["name"], note)
            for h in ph:
                seen[f'p:{r["id"]}:{h["id"]}'] = h["date"]
    items = merge_items(items)
    items.sort(key=lambda x: x["date"], reverse=True)
    # ③ 本週重點：內容（發言＋政策）有變才重寫，且一天最多一次
    summary = state.get("summary") or {}
    h = _key(*[x["id"] for x in items[:8]], *[f'{r["id"]}{r["stage"]}{r["next_date"]}{r["next_text"]}' for r in rows])
    if not offline and (items or rows) and summary.get("hash") != h and summary.get("date") != today.isoformat():
        src = json.dumps({"statements": [{"date": x["date"], "topic": x["topic"], "zh": x["zh"]} for x in items[:8]],
                          "policies": [{"name": r["name"], "current": r["stages"][r["stage"] - 1],
                                        "next": r["next_text"], "next_date": r["next_date"]} for r in rows]},
                         ensure_ascii=False)
        text = (_ai(src, SUMMARY_SYSTEM, call) or "").strip()
        if text:
            summary = {"hash": h, "date": today.isoformat(), "text": " ".join(text.split())[:200]}
    seen = {k: v for k, v in seen.items() if v >= (since - dt.timedelta(days=7)).isoformat()}
    suggestions = {k: v for k, v in suggestions.items() if v.get("date", "") >= since.isoformat()}
    state.update({"seen": seen, "items": items, "summary": summary, "suggestions": suggestions, "at": clock.stamp()})
    try:
        Path(state_path).parent.mkdir(parents=True, exist_ok=True)
        Path(state_path).write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        log.warning("白宮與國會狀態寫入失敗（%s）", e)
    ae = c.get("after_election") or {}
    until = _d(ae.get("until"))
    return {
        "items": items, "policies": rows, "topics": [t for t in c["topics"] if t in TOPICS],
        "summary": summary.get("text", ""),
        "after": str(ae.get("text") or "") if ae.get("text") and (not until or today <= until) else "",
        "epu": epu_block(series, today),
        "calendar": calendar_events(rows, today),
        "new_since": (today - dt.timedelta(days=int(c["new_days"]) - 1)).isoformat(),
        "window_days": win, "election_tile": bool(c.get("election_tile")),
        "checked": max((r["updated"] for r in rows if r["updated"]), default=""),
    }
