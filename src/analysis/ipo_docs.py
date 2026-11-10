"""
Anthropic IPO 細節（2026-11）：時間軸每一份 SEC 申報的重點、發行條件、估值與歷輪價格。

為什麼直接讀 SEC 申報、不讀新聞
--------------------------------
新聞標題常把數字取整或寫錯（例：2026-11-10 多則標題寫「定價 70–80 美元」，S-1/A 原文是
$70.00–$78.00）。發行股數、價格區間、同步私募、發行後股數、淨募資、歷輪優先股價格都寫在
申報文件裡，用正則直接抓原文；抓不到的欄位就不顯示，不用推估補。

流程（每次執行；每份申報只處理一次，結果記在 state/ipo_docs.json）
  ① SEC submissions：列出 DRS、DRS/A、S-1、S-1/A、424B4 等申報
  ② 沒處理過的申報：下載主文件 → 轉純文字 → parse_terms（發行條件）、parse_rounds（歷輪價格）
  ③ 重點摘要：截取封面、The Offering、Prospectus Summary 交給 AI 寫 4–6 點中文重點與
     「跟上一份相比改了什麼」；每點裡的數字都要在原文找得到（check_points），找不到的那點丟掉
  ④ 媒體估值：Google News 主要媒體標題裡的估值數字（parse_valuation），累積成時間序列
任何一步失敗只少那一塊。
"""
from __future__ import annotations

import datetime as dt
import html as _html
import json
import logging
import re
from pathlib import Path
from urllib.parse import quote_plus

from .. import clock

log = logging.getLogger(__name__)

SEC_SUB = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SEC_DOC = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
SEC_IDX = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/"
FORMS = ("DRS", "DRS/A", "S-1", "S-1/A", "424B4", "424B1", "8-A12B")
FORM_ZH = {"DRS": "秘密遞件草稿（DRS）", "DRS/A": "秘密遞件修正（DRS/A）", "S-1": "公開遞交 S-1",
           "S-1/A": "S-1 修正版", "424B4": "最終公開說明書（定價）", "424B1": "最終公開說明書（定價）",
           "8-A12B": "掛牌登記（8-A）"}
NEWS_URL = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
# 估值標題只收這些媒體（彙整站、分析師評論常出現「值不值 2 兆？」這種問句數字）
VAL_SOURCES = re.compile(r"reuters|bloomberg|wsj|wall street journal|financial times|cnbc|barron|"
                         r"associated press|ap news|new york times|axios|the information|cnn|forbes|fortune", re.I)
_MON = {m: i for i, m in enumerate(("January", "February", "March", "April", "May", "June", "July", "August",
                                    "September", "October", "November", "December"), 1)}


# ---------------------------------------------------------------------------
# 文字處理
# ---------------------------------------------------------------------------
def to_text(html: str) -> str:
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html or "")
    t = re.sub(r"<[^>]+>", " ", t)
    t = _html.unescape(t).replace("\xa0", " ")
    return re.sub(r"\s+", " ", t)


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _usd(v: str, unit: str) -> float:
    """金額 → 十億美元。"""
    u = unit.lower()
    return _num(v) * (1000 if u.startswith("tr") else 1 if u.startswith("b") else 0.001)


def _date_en(s: str) -> str:
    """'November 10, 2026' → '2026-11-10'；'May 2026' → '2026-05'。"""
    m = re.match(r"([A-Z][a-z]+)\s+(\d{1,2}),\s*(\d{4})", s or "")
    if m and m.group(1) in _MON:
        return f"{m.group(3)}-{_MON[m.group(1)]:02d}-{int(m.group(2)):02d}"
    m = re.match(r"([A-Z][a-z]+)\s+(\d{4})", s or "")
    if m and m.group(1) in _MON:
        return f"{m.group(2)}-{_MON[m.group(1)]:02d}"
    return ""


# ---------------------------------------------------------------------------
# 發行條件（封面與 The Offering）
# ---------------------------------------------------------------------------
def parse_terms(t: str) -> dict:
    """
    從申報純文字抓發行條件。每個欄位獨立：抓不到就不放（例如早期草稿還沒有價格區間）。
    股數與金額都照原文，金額單位十億美元。
    """
    out: dict = {}
    m = re.search(r"initial public offering price per share will be between \$\s?([\d.]+)\s*and \$\s?([\d.]+)", t)
    if m:
        out["price_lo"], out["price_hi"] = float(m.group(1)), float(m.group(2))
    m = re.search(r"initial public offering price (?:per share )?(?:is|was) \$\s?([\d.]+)", t)
    if m:
        out["price"] = float(m.group(1))
    m = re.search(r"We are (?:offering|selling) ([\d,]+) shares of (?:our )?Class A common stock"
                  r"(?:[^.]{0,120}?selling stockholders[^.]{0,80}?(?:offering|selling) an additional ([\d,]+) shares)?", t)
    if m:
        out["shares_primary"] = _num(m.group(1))
        if m.group(2):
            out["shares_secondary"] = _num(m.group(2))
        out["shares_offered"] = out["shares_primary"] + out.get("shares_secondary", 0.0)
    m = re.search(r"option to purchase up to an additional ([\d,]+) shares", t)
    if m:
        out["greenshoe"] = _num(m.group(1))
    m = re.search(r"aggregate of \$\s?([\d.,]+)\s*(billion|million) of (?:our )?Class \w common stock in a (?:concurrent )?private placement", t)
    if m:
        out["private_placement"] = _usd(m.group(1), m.group(2))
    outs = [_num(x) for x in re.findall(
        r"common stock to be outstanding after this offering(?: and the concurrent private placement)?\s+(\d[\d,]*) shares", t)]
    outs = [x for x in outs if x > 0]
    if outs:
        out["shares_after"] = max(outs)
    m = re.search(r"net proceeds from[^.]{0,300}?will be approximately \$\s?([\d.,]+)\s*(billion|million)"
                  r"(?:\s*\(or approximately \$\s?([\d.,]+)\s*(billion|million))?[^.]{0,200}?"
                  r"assumed initial public offering price of \$\s?([\d.]+)", t)
    if m:
        out["net_proceeds"] = _usd(m.group(1), m.group(2))
        if m.group(3):
            out["net_proceeds_full"] = _usd(m.group(3), m.group(4))
        out["assumed_price"] = float(m.group(5))
        out["net_incl_pp"] = bool(re.search(r"concurrent private placement", t[m.start():m.start() + 400]))
    m = re.search(r"under the symbol “([A-Z]+(?:\.[A-Z]+)?)\.?”", t)
    if m:
        out["ticker"] = m.group(1)
    m = re.search(r"list our Class A common stock on the (Nasdaq [A-Za-z ]+?Market|New York Stock Exchange)", t)
    if m:
        out["exchange"] = m.group(1).strip()
    m = re.search(r"purchase shares of our Class A common stock in this offering at the initial public offering price "
                  r"at an aggregate purchase price of up to \$\s?([\d.,]+)\s*(billion|million)", t)
    if m:
        out["insider_ioi"] = _usd(m.group(1), m.group(2))
    m = re.search(r"In the nine months ended ([A-Z][a-z]+ \d{1,2}, \d{4})\s*,?\s*our revenue was \$\s?([\d.,]+)\s*(billion|million)"
                  r"\s*,?\s*representing a year-over-year growth rate of ([\d,]+)\s*%", t)
    if m:
        out["rev_period"] = _date_en(m.group(1))
        out["rev_9m"] = _usd(m.group(2), m.group(3))
        out["rev_growth"] = _num(m.group(4))
    m = re.search(r"Our operating loss was \$\s?([\d.,]+)\s*(billion|million) for the nine months", t)
    if m:
        out["op_loss_9m"] = _usd(m.group(1), m.group(2))
    m = re.search(r"effected a (\d+)-for-(\d+) stock split", t)
    if m:
        out["split"] = int(m.group(1)) / int(m.group(2))
        d = re.search(r"On ([A-Z][a-z]+ \d{1,2}, \d{4}), the Company effected a \d+-for-\d+ stock split", t)
        if d:
            out["split_date"] = _date_en(d.group(1))
    return out


def parse_rounds(t: str) -> list[dict]:
    """歷輪優先股（Certain Relationships 一節）：期間、每股價格、總金額（十億美元）。"""
    rows, seen = [], set()
    for m in re.finditer(r"(?:From ([A-Z][a-z]+ \d{4}) to ([A-Z][a-z]+ \d{4})|In ([A-Z][a-z]+ \d{4})), we sold an aggregate of "
                         r"([\d,]+) shares of our Series ([A-Z])[-\w]* (?:redeemable )?convertible preferred stock at a "
                         r"purchase price of \$\s?([\d.,]+) per share, for an aggregate purchase price of \$\s?([\d,]+)", t):
        series = m.group(5)
        if series in seen:
            continue
        seen.add(series)
        price, shares = _num(m.group(6)), _num(m.group(4))
        amount = _num(m.group(7)) / 1e9
        # 原文 HTML 偶爾把數字拆開（S-1 的「$23,454,545,69 8」）：跟股數×價格對不上就用乘出來的值
        calc = shares * price / 1e9
        if abs(amount - calc) > 0.01 * calc:
            amount = calc
        rows.append({"series": series, "from": _date_en(m.group(1) or m.group(3)), "to": _date_en(m.group(2) or m.group(3)),
                     "price": price, "amount": amount, "shares": shares})
    return sorted(rows, key=lambda r: r["from"])


def derived(terms: dict, rounds: list[dict]) -> dict:
    """
    由原文數字算出的值（畫面上標「本站依申報計算」）：
      募資額＝發行股數 × 價格區間；隱含市值＝發行後各類股合計 × 價格區間（不含選擇權與 RSU，
      媒體常用的「完全稀釋」口徑會比這個大）；歷輪價格依股票分割調整後跟 IPO 價格比。
    """
    d: dict = {}
    lo, hi = terms.get("price_lo"), terms.get("price_hi")
    px = terms.get("price")
    if px:
        lo = hi = px
    if lo and hi:
        mid = (lo + hi) / 2
        d["mid"] = mid
        if terms.get("shares_offered"):
            n = terms["shares_offered"]
            d["gross_lo"], d["gross_hi"] = n * lo / 1e9, n * hi / 1e9
            if terms.get("shares_primary"):
                d["primary_mid"] = terms["shares_primary"] * mid / 1e9
        if terms.get("shares_after"):
            n = terms["shares_after"]
            d["cap_lo"], d["cap_mid"], d["cap_hi"] = n * lo / 1e9, n * mid / 1e9, n * hi / 1e9
        sp = terms.get("split") or 1.0
        if rounds:
            last = rounds[-1]
            adj = last["price"] / sp
            d["last_round"] = {**last, "adj": adj, "vs_lo": lo / adj - 1, "vs_hi": hi / adj - 1}
        d["rounds_adj"] = [{**r, "adj": r["price"] / sp} for r in rounds]
    return d


# ---------------------------------------------------------------------------
# AI 重點（每份申報一次）＋數字檢查
# ---------------------------------------------------------------------------
POINTS_SYSTEM = (
    "你是財經記者，替台灣讀者整理美國 IPO 申報文件的重點。輸入是一份 SEC 申報的節錄（封面、發行概要、公司概要），"
    "以及上一份申報已整理的發行條件（可能為空）。用繁體中文寫 4–6 點重點，每點 45 字以內："
    "發行股數與價格區間、募資用途、營收與獲利、股權與治理結構、重大合約或風險，只寫節錄裡有的。"
    "數字照原文（美元金額可換算成「億美元」：1 billion＝10 億，例如 $33.2 billion＝332 億美元），不加節錄以外的事實、不做評論。"
    "另寫一句「跟上一份相比改了什麼」（上一份為空就寫「首份申報」）。"
    "只回 JSON：{\"points\": [\"…\"], \"change\": \"…\"}。")


def excerpt(t: str, limit: int = 22000) -> str:
    """封面＋The Offering＋Prospectus Summary 開頭；找不到標記就取開頭。"""
    parts = []
    i = t.find("Subject to Completion")
    if i < 0:
        i = t.find("This is an initial public offering")
    parts.append(t[max(0, i):max(0, i) + 7000] if i >= 0 else t[:7000])
    j = t.find("The Offering Class A common stock offered")
    if j < 0:
        j = t.find("THE OFFERING")
    if j >= 0:
        parts.append(t[j:j + 7000])
    k = t.find("PROSPECTUS SUMMARY")
    if k >= 0:
        k2 = t.find("PROSPECTUS SUMMARY", k + 30)          # 第一個通常是目錄
        k = k2 if k2 > 0 else k
        parts.append(t[k:k + 8000])
    return " … ".join(parts)[:limit]


_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _vals(s: str) -> list[float]:
    out = []
    for x in _NUM_RE.findall(s or ""):
        try:
            out.append(float(x.replace(",", "")))
        except ValueError:
            pass
    return out


def _written(s: str) -> list[tuple[float, float]]:
    """文中的數字與它的精度（最後一位的一半）：'8.25'→(8.25, 0.005)、'846'→(846, 0.5)。"""
    out = []
    for x in _NUM_RE.findall(s or ""):
        dec = len(x.split(".")[1]) if "." in x else 0
        try:
            out.append((float(x.replace(",", "")), 0.5 * 10 ** -dec))
        except ValueError:
            pass
    return out


def check_points(points: list[str], src: str) -> list[str]:
    """
    每點裡的數字都要在原文找得到。容許的換算只有真的會出現的幾種：原樣、billion→億（×10）、
    million→億（÷100）、股數→億股（÷1e8）、萬（÷1e4）、billion→兆（÷1000）；容許誤差是「寫出來的
    最後一位的一半」（8.01 億股 ↔ 801,351,354 股 OK；9.5 億股 ↔ 8.25 億股 不 OK）。
    只有 12 以下的整數（月份、項數）跟年份不檢查。找不到的那點整點丟掉。
    """
    import bisect
    cands = sorted(v * f for v in set(_vals(src)) for f in (1, 10, 0.01, 1e-8, 1e-4, 1e-3))

    def ok(b: float, tol: float) -> bool:
        if (b <= 12 and b == int(b)) or (1990 <= b <= 2035 and b == int(b)):
            return True
        i = bisect.bisect_left(cands, b - tol - 1e-9)
        return i < len(cands) and cands[i] <= b + tol + 1e-9
    return [p for p in points if all(ok(b, t) for b, t in _written(p))]


def _ai(src: str, system: str, call=None) -> str:
    if call is None:
        from .focus_today import _call_ai
        text, err = _call_ai(src, system)
        if err:
            log.warning("IPO 申報重點：AI 呼叫失敗（%s）", err)
            return ""
        return text
    return call(src, system)


def summarize(t: str, prev_terms: dict | None, call=None) -> dict:
    ex = excerpt(t)
    text = _ai(json.dumps({"excerpt": ex, "previous_terms": prev_terms or {}}, ensure_ascii=False), POINTS_SYSTEM, call)
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        j = json.loads(m.group(0)) if m else {}
    except ValueError:
        j = {}
    pts = [str(p).strip()[:70] for p in j.get("points") or [] if str(p).strip()]
    good = check_points(pts, ex)
    if len(good) < len(pts):
        log.info("IPO 申報重點：%d 點的數字在原文找不到，已略過", len(pts) - len(good))
    ch = str(j.get("change") or "").strip()[:90]
    return {"points": good[:6], "change": ch if check_points([ch], ex) else ""}


# ---------------------------------------------------------------------------
# 媒體估值（主要媒體標題）
# ---------------------------------------------------------------------------
_AMT = r"\$\s?(\d+(?:\.\d+)?)\s*(trillion|tn|t|billion|bn|b)\b"
_VAL_PATS = [re.compile(p, re.I) for p in (
    r"valuation (?:of |at |near |around |closer to |to )?(?:up to |about |around |more than |as much as )?" + _AMT,
    _AMT + r"(?:\s*IPO)? valuation",
    r"valued at (?:up to |about |more than |as much as )?" + _AMT,
    r"(?:be |seeks to be |seek to be )valued at (?:more than |about )?" + _AMT,
    r"worth (?:up to |about )?" + _AMT,
)]
_NOISE = re.compile(r"\?|bubble|overvalued|worth more than every|burry", re.I)


def parse_valuation(title: str) -> float | None:
    """標題裡的估值（十億美元）；不是在講估值、或是問句／評論就回 None。"""
    if _NOISE.search(title or ""):
        return None
    for p in _VAL_PATS:
        m = p.search(title or "")
        if m:
            v, u = m.group(1), m.group(2).lower()
            val = float(v) * (1000 if u.startswith("t") else 1)
            return val if val >= 100 else None        # 太小的通常是募資額，不是估值
    return None


def valuation_series(items: list[dict]) -> list[dict]:
    """[{date, value, source, title, url}] → 每天一點：中位數、最低、最高、則數與各則。"""
    by: dict = {}
    for it in items:
        by.setdefault(it["date"], []).append(it)
    out = []
    for d in sorted(by):
        vs = sorted(x["value"] for x in by[d])
        n = len(vs)
        med = vs[n // 2] if n % 2 else (vs[n // 2 - 1] + vs[n // 2]) / 2
        out.append({"date": d, "median": med, "lo": vs[0], "hi": vs[-1], "n": n,
                    "items": sorted(by[d], key=lambda x: -x["value"])[:6]})
    return out


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def _fetch(url: str, headers=None, _get=None) -> str:
    if _get:
        return _get(url) or ""
    import requests
    r = requests.get(url, timeout=60, headers=headers or {"User-Agent": "Mozilla/5.0 (macro-dashboard)"})
    return r.text if r.status_code == 200 else ""


def build(cik: int, name: str, state_path: Path, offline: bool = False, _get=None, call=None,
          max_new: int = 4) -> dict:
    """
    回傳 {filings:[{form, form_zh, date, acc, url, points, change, terms}], terms, derived, rounds,
          valuations:[每天一點], val_items, at}。max_new：每次最多處理幾份新申報（文件很大，分次補齊）。
    """
    try:
        st = json.loads(Path(state_path).read_text(encoding="utf-8"))
    except Exception:                                # noqa: BLE001
        st = {}
    docs: dict = st.get("docs") or {}
    vals: list = st.get("val_items") or []
    if not offline:
        try:
            from ..sec import USER_AGENT
            ua = {"User-Agent": USER_AGENT}
            sub = json.loads(_fetch(SEC_SUB.format(cik=int(cik)), ua, _get) or "{}")
            r = (sub.get("filings") or {}).get("recent") or {}
            fl = [{"form": f, "date": d, "acc": a, "doc": p}
                  for f, d, a, p in zip(r.get("form") or [], r.get("filingDate") or [],
                                        r.get("accessionNumber") or [], r.get("primaryDocument") or [])
                  if f in FORMS]
            fl.sort(key=lambda x: (x["date"], x["acc"]))
            done = 0
            prev_terms: dict = {}
            for f in fl:
                if f["acc"] in docs:
                    prev_terms = docs[f["acc"]].get("terms") or prev_terms
                    continue
                if done >= max_new:
                    break
                acc = f["acc"].replace("-", "")
                url = SEC_DOC.format(cik=int(cik), acc=acc, doc=f["doc"]) if f["doc"] else SEC_IDX.format(cik=int(cik), acc=acc)
                try:
                    t = to_text(_fetch(url, ua, _get))
                except Exception as e:               # noqa: BLE001
                    log.warning("IPO 申報 %s %s 下載失敗（%s）", f["form"], f["date"], e)
                    continue
                if len(t) < 2000:
                    log.warning("IPO 申報 %s %s 內容太短，下次再試", f["form"], f["date"])
                    continue
                terms = parse_terms(t)
                rounds = parse_rounds(t)
                summ = summarize(t, prev_terms, call)
                if not summ["points"]:
                    log.warning("IPO 申報 %s %s：重點摘要失敗，下次再試", f["form"], f["date"])
                    continue                         # 不記錄，下次再試
                docs[f["acc"]] = {**f, "url": url, "terms": terms, "rounds": rounds, **summ}
                prev_terms = terms or prev_terms
                done += 1
        except Exception as e:                       # noqa: BLE001
            log.warning("IPO 申報清單抓取失敗（%s）", e)
        # 媒體估值：近 30 天標題，累積在 state（保留 180 天）
        try:
            from .ai_events import parse_rss
            since = clock.today() - dt.timedelta(days=30)
            q = quote_plus(f'"{name}" (valuation OR valued OR worth) when:30d')
            heads = parse_rss(_fetch(NEWS_URL.format(q=q), _get=_get), [name], since)
            have = {(v["date"], v["title"].lower()) for v in vals}
            for h in heads:
                if not VAL_SOURCES.search(h.get("source") or ""):
                    continue
                v = parse_valuation(h["title"])
                if v and (h["date"], h["title"].lower()) not in have:
                    vals.append({"date": h["date"], "value": v, "source": h["source"], "title": h["title"], "url": h["url"]})
        except Exception as e:                       # noqa: BLE001
            log.warning("IPO 媒體估值抓取失敗（%s）", e)
    cut = (clock.today() - dt.timedelta(days=180)).isoformat()
    vals = sorted([v for v in vals if v["date"] >= cut], key=lambda v: v["date"])
    st.update({"docs": docs, "val_items": vals, "at": clock.stamp()})
    try:
        Path(state_path).parent.mkdir(parents=True, exist_ok=True)
        Path(state_path).write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        log.warning("IPO 申報狀態寫入失敗（%s）", e)
    filings = sorted(docs.values(), key=lambda x: (x["date"], x["acc"]))
    for f in filings:
        f["form_zh"] = FORM_ZH.get(f["form"], f["form"])
    # 條件取「最新一份有該欄位的申報」，每個欄位各自往回找
    terms: dict = {}
    for f in filings:
        for k, v in (f.get("terms") or {}).items():
            terms[k] = v
            terms[f"{k}__date"] = f["date"]
    rounds = next((f["rounds"] for f in reversed(filings) if f.get("rounds")), [])
    return {"filings": filings, "terms": terms, "rounds": rounds, "derived": derived(terms, rounds),
            "valuations": valuation_series(vals), "val_items": vals[-40:], "at": st["at"]}
