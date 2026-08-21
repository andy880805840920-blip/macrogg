"""
今日市場焦點（首頁 hero 之上的窄條）。

三顆數字＋一段焦點文字：
  10 年期／30 年期殖利率（FRED，較前一交易日的變動）
  2026 年底升息一碼機率（CME FedWatch，由 Gemini 搜尋擷取——見下）
  市場焦點一段（Google News RSS 爬標題，Gemini 只挑重點寫敘述）

分工原則（跟潤稿層同一套哲學）
------------------------------
事實由爬蟲拿、AI 只整理敘述。唯一的例外是 FedWatch 機率：CME 沒有
免費 API、網頁是 JS 動態的，直接爬既脆弱又有條款問題，所以這個數字
由 Gemini 開搜尋接地去擷取——**這違反「AI 不碰數字」的全站原則**，
因此配三道防護欄（0–100 範圍、單日跳動 >20pp 視為擷取錯誤沿用前值、
失敗顯示「—」不編造），畫面上明標「AI 擷取，僅供參考」。

焦點段的防護欄
--------------
① 只能用標題裡已有的資訊——輸出裡的每一串數字都必須出現在輸入標題裡
② 長度上限（config 可調），超過就退回
③ API 掛掉／驗證沒過 → 退回「直接列前幾條標題」——沒有 AI 也有東西看
④ 同一批標題只呼叫一次（標題集合做雜湊快取），一天最多兩三次 API

任何一步失敗都不影響主流程：這一條掛了，首頁其他區塊照常產出。
"""

from __future__ import annotations

import re
import json
import hashlib
import logging
import datetime as dt
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote

import requests

from .. import clock
from .brief import cjk_len

log = logging.getLogger(__name__)

TIMEOUT = 20
RSS_URL = ("https://news.google.com/rss/search?q={q}"
           "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant")

DEFAULT_KEYWORDS = [
    "川普 聯準會", "Fed 利率", "Kevin Warsh", "美國財政部", "貝森特",
    "美債 殖利率", "債券市場", "美伊",
]


# ---------------------------------------------------------------------------
# 殖利率：FRED 序列的最新值與較前一交易日的變動（基點）
# ---------------------------------------------------------------------------
def _yield_chip(rows: list, label: str) -> dict | None:
    rows = [r for r in (rows or []) if r.get("value") is not None]
    if len(rows) < 2:
        return None
    last, prev = rows[-1], rows[-2]
    return {"label": label, "value": last["value"],
            "delta_bp": round((last["value"] - prev["value"]) * 100),
            "date": last.get("date", "")}


# ---------------------------------------------------------------------------
# 新聞標題：Google News RSS
# ---------------------------------------------------------------------------
def fetch_headlines(keywords: list[str], hours: int = 30,
                    _get=None) -> list[dict]:
    """
    逐關鍵字打 RSS、收近 `hours` 小時的標題。單一關鍵字失敗就跳過——
    新聞條這種東西寧可少一組也不要整段消失。
    """
    get = _get or (lambda url: requests.get(
        url, timeout=TIMEOUT, headers={"User-Agent": "macro-dashboard/1.0"}))
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    out, seen = [], set()
    for kw in keywords:
        try:
            r = get(RSS_URL.format(q=quote(kw)))
            r.raise_for_status()
            root = ET.fromstring(r.content)
        except Exception as e:                     # noqa: BLE001
            log.warning("市場焦點：關鍵字「%s」抓取失敗（%s）", kw, e)
            continue
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = item.findtext("pubDate") or ""
            src = ""
            se = item.find("source")
            if se is not None and se.text:
                src = se.text.strip()
            if not title:
                continue
            try:
                at = parsedate_to_datetime(pub)
                if at.tzinfo is None:
                    at = at.replace(tzinfo=dt.timezone.utc)
            except (ValueError, TypeError):
                continue
            if at < cutoff:
                continue
            # 標題常帶「 - 來源」尾巴，去掉再去重
            core = re.sub(r"\s*[-–—]\s*[^-–—]{1,30}$", "", title)
            key = re.sub(r"\s+", "", core)[:40]
            if key in seen:
                continue
            seen.add(key)
            out.append({"title": title, "link": link, "source": src,
                        "at": at.isoformat(), "kw": kw})
    out.sort(key=lambda x: x["at"], reverse=True)
    return out


def _norm_title(t: str) -> str:
    """去掉尾巴的「 - 來源」、標點與空白，留下可比對的核心字串。"""
    t = re.sub(r"\s*[-–—|]\s*[^-–—|]{1,30}$", "", t)
    return re.sub(r"[\s，。、！？：；「」『』()（）\[\]【】,.:;!?'\"]+", "", t)


def _sim(a: str, b: str) -> float:
    """字元二元組的 Jaccard 相似度（0–1）。中文不需要斷詞，二元組就夠。"""
    if len(a) < 2 or len(b) < 2:
        return 1.0 if a == b else 0.0
    A = {a[i:i + 2] for i in range(len(a) - 1)}
    B = {b[i:i + 2] for i in range(len(b) - 1)}
    return len(A & B) / max(1, len(A | B))


def pick_fallback(headlines: list[dict], keywords: list[str],
                  n: int = 3) -> list[dict]:
    """
    沒有 AI 時的確定性挑選：關鍵字命中數多者優先。
    輸入已按時間新→舊排好，穩定排序讓同分者維持新的在前。

    挑的時候擋掉「同一件事的另一種寫法」：fetch 端的去重是完全比對
    （去尾巴後前 40 字），同一則新聞在不同媒體的標題只要改幾個字就會
    穿過去——實際發生過「來源標題選到兩則一樣的新聞」。這裡再用
    字元二元組相似度把 >0.55 的視為重複，跳過選下一則。
    """
    def _hits(h):
        t = h["title"]
        return sum(1 for kw in keywords for w in kw.split() if w in t)
    picked = []
    for h in sorted(headlines, key=_hits, reverse=True):
        cand = _norm_title(h["title"])
        if any(_sim(cand, _norm_title(p["title"])) > 0.55 for p in picked):
            continue
        picked.append(h)
        if len(picked) >= n:
            break
    return picked


# ---------------------------------------------------------------------------
# Gemini：焦點段（無接地）與 FedWatch 擷取（搜尋接地）
# ---------------------------------------------------------------------------
_FOCUS_SYSTEM = (
    "你是財經編輯。從輸入的新聞標題清單挑出對「美國公債殖利率與聯準會政策」"
    "最重要的一到三則，寫成一段不超過 {cap} 個中文字的市場焦點。規則："
    "只能使用標題裡已有的資訊，不得補充任何標題以外的事實或數字；"
    "不做預測、不下投資結論；繁體中文；直接輸出那一段文字，不要任何前言。")


def _digits_ok(text: str, source: str) -> bool:
    """輸出裡的每一串數字都必須出現在來源標題裡（防 AI 編數字）。"""
    src = re.sub(r"[\s,，]", "", source)
    for num in re.findall(r"\d+(?:\.\d+)?", text.replace(",", "")):
        if num not in src:
            return False
    return True


def summarize(headlines: list[dict], cap: int, env=None) -> tuple[str, str]:
    """回傳 (焦點段, 來源標記)。失敗回 ("", 原因)。"""
    from .polish import _pick_provider, _gemini_call
    import os
    env = env or os.environ
    provider, key = _pick_provider(env)
    if provider != "gemini" or not key:
        return "", "沒有 Gemini 金鑰"
    lines = "\n".join(f"- [{h['source'] or '—'}] {h['title']}"
                      for h in headlines[:24])
    model = (env.get("BRIEF_MODEL") or "").strip() or "gemini-flash-latest"
    try:
        text = _gemini_call(key, model, lines,
                            system=_FOCUS_SYSTEM.format(cap=cap),
                            think=False, temperature=0.3).strip()
    except Exception as e:                         # noqa: BLE001
        return "", f"呼叫失敗（{e}）"
    if not text or cjk_len(text) > cap + 40:
        return "", f"長度不合格（{cjk_len(text)} 字）"
    if not _digits_ok(text, lines):
        return "", "輸出出現標題裡沒有的數字"
    return text, "model"


_FW_PROMPT = (
    "用 Google 搜尋查 CME FedWatch 工具目前對 2026 年 12 月 FOMC 會議的"
    "利率機率分布，找出「較目前利率區間**升息 25 個基點（一碼）**」的機率。"
    '只輸出一行 JSON：{"pct": <0 到 100 的數字>}；查不到明確數字就輸出 '
    '{"pct": null}。不要輸出其他文字。')


def fetch_fedwatch(env=None) -> float | None:
    """FedWatch 機率，Gemini 搜尋接地擷取。抓不到回 None，不編造。"""
    from .polish import _pick_provider, _http, GEMINI_BASE
    import os
    env = env or os.environ
    provider, key = _pick_provider(env)
    if provider != "gemini" or not key:
        return None
    model = (env.get("BRIEF_MODEL") or "").strip() or "gemini-flash-latest"
    try:
        r = _http("POST", f"{GEMINI_BASE}/models/{model}:generateContent",
                  label="FedWatch 擷取", headers={
                      "x-goog-api-key": key,
                      "content-type": "application/json"},
                  json={"contents": [{"role": "user",
                                      "parts": [{"text": _FW_PROMPT}]}],
                        "tools": [{"google_search": {}}],
                        "generationConfig": {"temperature": 0.0,
                                             "maxOutputTokens": 2048}})
        r.raise_for_status()
        cands = (r.json().get("candidates") or [])
        text = "".join(p.get("text", "")
                       for p in ((cands[0].get("content") or {})
                                 .get("parts", []))) if cands else ""
        m = re.search(r'\{[^{}]*"pct"[^{}]*\}', text)
        if not m:
            return None
        pct = json.loads(m.group(0)).get("pct")
        if pct is None:
            return None
        pct = float(pct)
        return pct if 0.0 <= pct <= 100.0 else None
    except Exception as e:                         # noqa: BLE001
        log.warning("FedWatch 擷取失敗（%s）", e)
        return None


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def build(rates_series: dict | None, offline: bool, cfg: dict | None,
          state_path: Path, env=None) -> dict:
    cfg = cfg or {}
    keywords = cfg.get("keywords") or DEFAULT_KEYWORDS
    cap = int(cfg.get("max_chars") or 120)

    yields = [c for c in (
        _yield_chip((rates_series or {}).get("DGS10"), "10 年期"),
        _yield_chip((rates_series or {}).get("DGS30"), "30 年期"),
    ) if c]
    out = {"yields": yields,
           "asof": (yields[0]["date"] if yields else ""),
           "fedwatch": None, "text": "", "text_source": "",
           "links": [], "generated": clock.today().isoformat()}

    if offline or cfg.get("enabled") is False:
        out["text"] = ("離線示範模式：不抓取新聞，正式執行時這裡是"
                       "當天的市場焦點一段。")
        out["text_source"] = "offline"
        return out

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:                              # noqa: BLE001
        state = {}
    if not isinstance(state, dict):
        state = {}
    today = clock.today().isoformat()

    # ---- FedWatch：一天最多擷取一次；跳動 >20pp 視為擷取錯誤沿用前值 ----
    fw_old = state.get("fedwatch") or {}
    if fw_old.get("date") == today and fw_old.get("pct") is not None:
        out["fedwatch"] = {"pct": fw_old["pct"],
                           "delta_pp": fw_old.get("delta_pp"),
                           "suspect": bool(fw_old.get("suspect"))}
    else:
        pct = fetch_fedwatch(env)
        prev = fw_old.get("pct")
        suspect = False
        if pct is None and prev is not None:
            # 本次擷取失敗（429、斷線…）但手上有近幾天的值 → 沿用並標明，
            # 不要讓一次限流就把整顆 chip 打回「—」。超過 4 天就太舊，
            # 寧可顯示「—」也不要掛一個一週前的機率。state 的 date 不動，
            # 下一次執行還會再試。
            try:
                _age = (dt.date.fromisoformat(today)
                        - dt.date.fromisoformat(fw_old.get("date", ""))).days
            except (ValueError, TypeError):
                _age = 99
            if _age <= 4:
                out["fedwatch"] = {"pct": prev, "delta_pp": None,
                                   "suspect": False,
                                   "stale_from": fw_old.get("date")}
        elif pct is not None:
            if prev is not None and abs(pct - prev) > 20:
                log.warning("FedWatch 單日跳動 %.0f→%.0f，視為擷取錯誤沿用前值",
                            prev, pct)
                pct, suspect = prev, True
            delta = (round(pct - prev, 1)
                     if (prev is not None and not suspect
                         and fw_old.get("date") != today) else None)
            out["fedwatch"] = {"pct": pct, "delta_pp": delta,
                               "suspect": suspect}
            state["fedwatch"] = {"pct": pct, "date": today,
                                 "delta_pp": delta, "suspect": suspect}

    # ---- 焦點段：RSS 爬標題 → 來源白名單 → 同一批標題只呼叫一次 → 驗證 → 退回 ----
    heads = fetch_headlines(keywords)
    # 來源白名單（config 的 sources）：只留 source 含指定字串的標題。
    # 全部沒命中時退回不過濾並記 log——寧可來源雜一點，也不要整段消失。
    _srcs = [str(s).lower() for s in (cfg.get("sources") or []) if s]
    if heads and _srcs:
        _hits = [h for h in heads
                 if any(w in (h.get("source") or "").lower() for w in _srcs)]
        if _hits:
            heads = _hits
        else:
            log.warning("市場焦點：來源白名單 %s 沒命中任何標題，退回全部來源",
                        _srcs)
    if heads:
        top = pick_fallback(heads, keywords, n=6)
        h = hashlib.sha256("|".join(x["title"] for x in top)
                           .encode("utf-8")).hexdigest()[:16]
        if state.get("hash") == h and state.get("text"):
            out["text"], out["text_source"] = state["text"], "cache"
            out["links"] = state.get("links") or []
        else:
            text, src = summarize(top, cap, env)
            # 顯示用的標題把尾巴的「 - 來源」去掉——旁邊已經另掛來源小標，
            # 留著會變成「…- Yahoo奇摩財經　Yahoo奇摩財經」連講兩次。
            links = [{"title": re.sub(r"\s*[-–—|]\s*[^-–—|]{1,30}$", "",
                                      x["title"]).strip() or x["title"],
                      "link": x["link"],
                      "source": x["source"]} for x in top[:3]]
            if text:
                out["text"], out["text_source"] = text, src
            else:
                log.warning("市場焦點：AI 段落退回列標題（%s）", src)
                out["text"] = "；".join(
                    f"{x['title']}" for x in links) or ""
                out["text_source"] = "headlines"
            out["links"] = links
            state.update({"hash": h, "text": out["text"], "links": links})
    else:
        log.warning("市場焦點：沒有抓到任何標題")

    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    except Exception as e:                         # noqa: BLE001
        log.warning("市場焦點狀態寫入失敗（%s）", e)
    return out
