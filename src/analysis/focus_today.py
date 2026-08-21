"""
今日市場焦點（首頁 hero 之上的窄條）。

三顆數字＋一段焦點文字：
  10 年期／30 年期殖利率（FRED，較前一交易日的變動）
  2026 年底升息一碼機率（聯邦基金期貨自算——見下）
  市場焦點一段（Google News RSS 爬標題，Gemini 只挑重點寫敘述）

分工原則（跟潤稿層同一套哲學）
------------------------------
事實由爬蟲拿、AI 只整理敘述。

FedWatch 機率的三層來源（依序退回）
----------------------------------
FedWatch 與 Bloomberg WIRP 都不是原始資料——兩者都是從 CME 的
30 天期聯邦基金期貨（ZQ）價格反推的。所以第一層直接用同一套算法自算：

  ① **期貨自算**：Yahoo Finance 延遲報價抓 2027 年 1 月合約（1 月沒有
     FOMC 會議，整月平均利率 ≈ 12 月會議之後的利率，繞開「會期跨月
     加權」）。隱含利率＝100 − 價格；
     升息一碼機率＝(隱含利率 − 目前目標區間中點) ÷ 0.25，鎖 0–100。
     數字是可驗算的規則，不再是 AI 抄的。
  ② **Gemini 搜尋擷取**（僅在①失敗時）：這違反「AI 不碰數字」原則，
     所以只當備援，畫面明標「AI 擷取，僅供參考」。
  ③ **沿用前值**（≤4 天）：兩層都失敗時沿用快取並標明日期。

共用防護欄：合理範圍檢查、單日跳動 >20pp 視為擷取錯誤沿用前值、
每日快取（一天最多算一次）、失敗顯示「—」不編造。

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
# 殖利率：優先 Yahoo 即時報價（±bp 對昨收），失敗退回 FRED（隔日）
# ---------------------------------------------------------------------------
def _yield_chip(rows: list, label: str) -> dict | None:
    rows = [r for r in (rows or []) if r.get("value") is not None]
    if len(rows) < 2:
        return None
    last, prev = rows[-1], rows[-2]
    return {"label": label, "value": last["value"],
            "delta_bp": round((last["value"] - prev["value"]) * 100),
            "date": last.get("date", "")}


# CBOE 的殖利率指數：^TNX＝10 年期、^TYX＝30 年期。
# 慣例是「殖利率 ×10」（49.8 ＝ 4.98%），但 Yahoo 顯示上兩種格式都出現過
# ——所以拿到值之後做規範化（>20 就除以 10）再做合理範圍檢查。
YIELD_SYMBOLS = (("^TNX", "10 年期"), ("^TYX", "30 年期"))


def fetch_yahoo_yield(symbol: str, label: str, _get=None) -> dict | None:
    """
    即時殖利率 chip：目前報價（延遲約 15 分鐘）與較前一交易日收盤的變動。

    FRED 的日頻序列要隔一個交易日才有值——首頁的「今日」焦點條掛著
    昨天的數字不太對勁。抓不到（Yahoo 擋 IP、格式變了）就回 None，
    由呼叫端退回 FRED 版 chip，小字會標明來源。
    """
    get = _get or (lambda url: requests.get(
        url, timeout=TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0 (macro-dashboard)"}))
    try:
        r = get(YQ_URL.format(sym=quote(symbol)))
        r.raise_for_status()
        res = (r.json().get("chart") or {}).get("result") or []
        meta = (res[0].get("meta") or {}) if res else {}
        cur = meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose")
        if prev is None:
            prev = meta.get("previousClose")
        ts = meta.get("regularMarketTime")
        if cur is None or prev is None:
            return None
        cur, prev = float(cur), float(prev)
        if cur > 20.0:                    # ×10 慣例 → 換算回百分比
            cur, prev = cur / 10.0, prev / 10.0
        if not (0.1 <= cur <= 15.0 and 0.1 <= prev <= 15.0):
            log.warning("Yahoo 殖利率 %s 數值異常（%.2f／%.2f），不採用",
                        symbol, cur, prev)
            return None
        date = ""
        if ts:
            try:
                date = dt.datetime.fromtimestamp(
                    int(ts), dt.timezone.utc).date().isoformat()
            except (ValueError, TypeError, OSError):
                date = ""
        return {"label": label, "value": round(cur, 2),
                "delta_bp": round((cur - prev) * 100),
                "date": date, "live": True}
    except Exception as e:                         # noqa: BLE001
        log.warning("Yahoo 殖利率 %s 抓取失敗（%s），退回 FRED", symbol, e)
        return None


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


# ---------------------------------------------------------------------------
# Yahoo 自家 RSS（直達文章頁）＋內文擷取
# ---------------------------------------------------------------------------
# 不經 Google News 的理由：它的連結是自家轉址頁，解回原始文章網址的方法
# 脆弱且常變；Yahoo 的 RSS 連結直達文章頁，內文抓得到，AI 才有東西摘。
# feed 網址放 config（feeds:），Yahoo 改版時不用改程式。
DEFAULT_FEEDS = [
    "https://tw.news.yahoo.com/rss/finance",
    "https://tw.stock.yahoo.com/rss?category=news",
    "https://finance.yahoo.com/news/rssindex",
]
_FEED_LABEL = (("tw.news.yahoo", "Yahoo奇摩新聞"),
               ("tw.stock.yahoo", "Yahoo奇摩股市"),
               ("finance.yahoo", "Yahoo Finance"))


def _feed_label(url: str) -> str:
    for key, label in _FEED_LABEL:
        if key in url:
            return label
    return re.sub(r"^https?://([^/]+).*$", r"\1", url)


def fetch_feed_headlines(feeds: list[str], keywords: list[str],
                         hours: int = 30, _get=None) -> list[dict]:
    """
    直接吃 Yahoo 的 RSS，只留**標題命中任一關鍵字詞**的項目。
    單一 feed 失敗就跳過；全部失敗回空列表，由呼叫端退回 Google News。
    """
    get = _get or (lambda url: requests.get(
        url, timeout=TIMEOUT, headers={"User-Agent": "macro-dashboard/1.0"}))
    words = [w for kw in keywords for w in str(kw).split() if w]
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    out, seen = [], set()
    for feed in feeds:
        try:
            r = get(feed)
            r.raise_for_status()
            root = ET.fromstring(r.content)
        except Exception as e:                     # noqa: BLE001
            log.warning("市場焦點：feed %s 抓取失敗（%s）", feed, e)
            continue
        label = _feed_label(feed)
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = item.findtext("pubDate") or ""
            if not title or not link:
                continue
            if not any(w in title for w in words):
                continue
            try:
                at = parsedate_to_datetime(pub)
                if at.tzinfo is None:
                    at = at.replace(tzinfo=dt.timezone.utc)
            except (ValueError, TypeError):
                continue
            if at < cutoff:
                continue
            key = re.sub(r"\s+", "", _norm_title(title))[:40]
            if key in seen:
                continue
            seen.add(key)
            out.append({"title": title, "link": link, "source": label,
                        "at": at.isoformat(), "kw": ""})
    out.sort(key=lambda x: x["at"], reverse=True)
    return out


def fetch_article_text(url: str, _get=None, cap: int = 1800) -> str:
    """
    抓文章頁、抽出正文（<p> 段落）。Yahoo 新聞頁的正文是伺服器渲染的，
    requests 就抓得到。抽不出足夠文字（<100 字）回空字串——改版、擋爬、
    影音頁都會走到這裡，由呼叫端退回標題模式。
    """
    import html as _html
    get = _get or (lambda u: requests.get(
        u, timeout=TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0 (macro-dashboard)"}))
    try:
        r = get(url)
        r.raise_for_status()
        page = r.text
    except Exception as e:                         # noqa: BLE001
        log.warning("市場焦點：文章抓取失敗（%s：%s）", url[:60], e)
        return ""
    # 先砍 script/style 再抽 <p>：Yahoo 頁面的 JSON 資料塊裡也有長字串，
    # 不砍會把程式碼當成內文。
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", page,
                  flags=re.S | re.I)
    paras = []
    for m in re.finditer(r"<p[^>]*>(.*?)</p>", page, re.S | re.I):
        t = _html.unescape(re.sub(r"<[^>]+>", "", m.group(1)))
        t = re.sub(r"\s+", " ", t).strip()
        if len(t) >= 20:                           # 導覽、版權列都比這短
            paras.append(t)
        if sum(len(p) for p in paras) >= cap:
            break
    body = "\n".join(paras)[:cap]
    return body if cjk_len(body) >= 100 or len(body) >= 300 else ""


_FOCUS_CONTENT_SYSTEM = (
    "你是財經編輯。輸入是幾篇新聞的標題與內文節錄。"
    "只挑與這些關鍵字相關的內容：{kws}。"
    "寫成一段不超過 {cap} 個中文字的市場焦點。規則："
    "只能使用內文已有的資訊，不得補充內文以外的事實或數字；"
    "與關鍵字無關的內容一律不寫；不做預測、不下投資結論；"
    "繁體中文；直接輸出那一段文字，不要任何前言。")


def summarize_content(articles: list[dict], keywords: list[str],
                      cap: int, env=None) -> tuple[str, str]:
    """從文章內文摘關鍵字相關的重點。回傳 (焦點段, 來源標記)；失敗回 ("", 原因)。"""
    from .polish import _pick_provider, _gemini_call
    import os
    env = env or os.environ
    provider, key = _pick_provider(env)
    if provider != "gemini" or not key:
        return "", "沒有 Gemini 金鑰"
    src_text = "\n\n".join(
        f"【{a.get('source') or '—'}】{a['title']}\n{a['body']}"
        for a in articles)
    model = (env.get("BRIEF_MODEL") or "").strip() or "gemini-flash-latest"
    try:
        text = _gemini_call(
            key, model, src_text,
            system=_FOCUS_CONTENT_SYSTEM.format(
                kws="、".join(keywords), cap=cap),
            think=False, temperature=0.3).strip()
    except Exception as e:                         # noqa: BLE001
        return "", f"呼叫失敗（{e}）"
    if not text or cjk_len(text) > cap + 40:
        return "", f"長度不合格（{cjk_len(text)} 字）"
    # 數字鎖對「內文」驗：輸出的每一串數字都必須出現在輸入的內文裡
    if not _digits_ok(text, src_text):
        return "", "輸出出現內文裡沒有的數字"
    return text, "model-content"


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


# ---------------------------------------------------------------------------
# FedWatch 第一層：聯邦基金期貨自算（FedWatch／WIRP 的同款方法）
# ---------------------------------------------------------------------------
YQ_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
          "?range=5d&interval=1d")
# 2027 年 1 月合約：1 月沒有 FOMC 會議，整月均價 ≈ 12 月會後的利率。
# 年度往前滾時到 config/focus.yaml 改 fedwatch_contract（例如 2027 年底
# 的機率就改 ZQF28.CBT）。
DEFAULT_ZQ = "ZQF27.CBT"


def _last_value(rows) -> float | None:
    rows = [r for r in (rows or []) if r.get("value") is not None]
    return rows[-1]["value"] if rows else None


def fetch_zq_implied(symbol: str, _get=None) -> float | None:
    """抓一檔聯邦基金期貨的最新價，回傳隱含利率（100 − 價格）。"""
    get = _get or (lambda url: requests.get(
        url, timeout=TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0 (macro-dashboard)"}))
    try:
        r = get(YQ_URL.format(sym=quote(symbol)))
        r.raise_for_status()
        res = (r.json().get("chart") or {}).get("result") or []
        meta = (res[0].get("meta") or {}) if res else {}
        px = meta.get("regularMarketPrice")
        if px is None and res:
            closes = (((res[0].get("indicators") or {}).get("quote") or [{}])[0]
                      .get("close") or [])
            px = next((c for c in reversed(closes) if c is not None), None)
        if px is None:
            return None
        px = float(px)
        # 期貨價 ＝ 100 − 利率：合理價位在 90–100 之間。
        # 落在外面代表抓到錯的商品或壞報價，寧可不算。
        if not 90.0 <= px <= 100.0:
            log.warning("聯邦基金期貨 %s 報價 %.2f 超出合理範圍，不採用",
                        symbol, px)
            return None
        return round(100.0 - px, 4)
    except Exception as e:                         # noqa: BLE001
        log.warning("聯邦基金期貨報價抓取失敗（%s：%s）", symbol, e)
        return None


def fedwatch_from_futures(rates_series: dict | None, cfg: dict | None,
                          _get=None) -> float | None:
    """
    升息一碼機率 ＝ (期貨隱含利率 − 目前目標區間中點) ÷ 0.25，鎖 0–100。

    目標區間直接取 FRED 的 DFEDTARL／DFEDTARU（rates 模組本來就有抓），
    不另外手填——手填的利率漏更新一次，機率就整個平移。
    """
    rs = rates_series or {}
    lo = _last_value(rs.get("DFEDTARL"))
    hi = _last_value(rs.get("DFEDTARU"))
    if lo is None or hi is None:
        log.warning("FedWatch 自算：抓不到目標區間（DFEDTARL/U），跳過")
        return None
    mid = (lo + hi) / 2
    sym = (cfg or {}).get("fedwatch_contract") or DEFAULT_ZQ
    implied = fetch_zq_implied(sym, _get)
    if implied is None:
        return None
    # 隱含利率偏離目前中點超過 1.5 個百分點，多半是合約寫錯年份
    # 或抓到壞報價——六碼的跳動不會在一夜之間發生。
    if abs(implied - mid) > 1.5:
        log.warning("FedWatch 自算：隱含利率 %.2f%% 偏離中點 %.2f%% 過大，不採用",
                    implied, mid)
        return None
    return round(max(0.0, min(100.0, (implied - mid) / 0.25 * 100)), 1)


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

    # ---- 殖利率升級成即時：Yahoo 逐檔試，抓不到的那檔退回 FRED ----
    _fred = {"10 年期": (rates_series or {}).get("DGS10"),
             "30 年期": (rates_series or {}).get("DGS30")}
    _fresh = []
    for _sym, _label in YIELD_SYMBOLS:
        c = (fetch_yahoo_yield(_sym, _label)
             or _yield_chip(_fred.get(_label), _label))
        if c:
            _fresh.append(c)
    if _fresh:
        out["yields"] = _fresh
        out["asof"] = _fresh[0].get("date", "")

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:                              # noqa: BLE001
        state = {}
    if not isinstance(state, dict):
        state = {}
    today = clock.today().isoformat()

    # ---- FedWatch：一天最多算一次；跳動 >20pp 視為擷取錯誤沿用前值 ----
    # 來源三層：期貨自算 → Gemini 擷取 → 沿用前值（見模組說明）。
    fw_old = state.get("fedwatch") or {}
    if fw_old.get("date") == today and fw_old.get("pct") is not None:
        out["fedwatch"] = {"pct": fw_old["pct"],
                           "delta_pp": fw_old.get("delta_pp"),
                           "suspect": bool(fw_old.get("suspect")),
                           "src": fw_old.get("src", "")}
    else:
        pct = fedwatch_from_futures(rates_series, cfg)
        fw_src = "futures"
        if pct is None:
            pct = fetch_fedwatch(env)
            fw_src = "ai"
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
                                   "src": fw_old.get("src", ""),
                                   "stale_from": fw_old.get("date")}
        elif pct is not None:
            if prev is not None and abs(pct - prev) > 20:
                log.warning("FedWatch 單日跳動 %.0f→%.0f，視為擷取錯誤沿用前值",
                            prev, pct)
                pct, suspect = prev, True
                fw_src = fw_old.get("src", fw_src)
            delta = (round(pct - prev, 1)
                     if (prev is not None and not suspect
                         and fw_old.get("date") != today) else None)
            out["fedwatch"] = {"pct": pct, "delta_pp": delta,
                               "suspect": suspect, "src": fw_src}
            state["fedwatch"] = {"pct": pct, "date": today,
                                 "delta_pp": delta, "suspect": suspect,
                                 "src": fw_src}

    # ---- 焦點段（三層）：Yahoo RSS＋內文摘要 → Google News 標題摘要 →
    #      列標題。同一批文章只呼叫一次 AI（雜湊快取）。 ----
    feeds = cfg.get("feeds") or DEFAULT_FEEDS
    heads = fetch_feed_headlines(feeds, keywords)
    mode = "content"
    if not heads:
        log.warning("市場焦點：Yahoo RSS 無命中或全部失敗，退回 Google News 標題模式")
        heads = fetch_headlines(keywords)
        # 來源白名單（config 的 sources）只在標題模式有意義——
        # Yahoo feed 本身就只有 Yahoo。全部沒命中時退回不過濾。
        _srcs = [str(s).lower() for s in (cfg.get("sources") or []) if s]
        if heads and _srcs:
            _hits = [h for h in heads
                     if any(w in (h.get("source") or "").lower() for w in _srcs)]
            if _hits:
                heads = _hits
            else:
                log.warning("市場焦點：來源白名單 %s 沒命中任何標題，退回全部來源",
                            _srcs)
        mode = "title"
    if heads:
        top = pick_fallback(heads, keywords, n=6)
        h = hashlib.sha256((mode + "|" + "|".join(x["title"] for x in top))
                           .encode("utf-8")).hexdigest()[:16]
        if state.get("hash") == h and state.get("text"):
            out["text"] = state["text"]
            out["text_source"] = "cache"
            out["cached_mode"] = ("content"
                                  if state.get("text_source") == "model-content"
                                  else "title")
            out["links"] = state.get("links") or []
        else:
            text, src = "", ""
            if mode == "content":
                arts = []
                for x in top[:3]:
                    body = fetch_article_text(x["link"])
                    if body:
                        arts.append({"title": x["title"], "body": body,
                                     "source": x.get("source", "")})
                if arts:
                    text, src = summarize_content(arts, keywords, cap, env)
                    if not text:
                        log.warning("市場焦點：內文摘要退回標題模式（%s）", src)
                else:
                    log.warning("市場焦點：內文全部抓不到，改用標題摘要")
            if not text:
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
            state.update({"hash": h, "text": out["text"], "links": links,
                          "text_source": out["text_source"]})
    else:
        log.warning("市場焦點：沒有抓到任何標題")

    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    except Exception as e:                         # noqa: BLE001
        log.warning("市場焦點狀態寫入失敗（%s）", e)
    return out
