"""
總覽「04 各家預測」（2026-10）：失業與通膨，各家投行 vs 市場共識 vs Cleveland Fed。

每一期（就業報告／CPI／PCE）一筆，存在 state/forecasts.json：
  公布前：每次更新都重抓市場共識（ForexFactory）與 Cleveland Fed 即時預測，
          只保留「公布前的最後一版」；投行預估自動擷取自預覽文章（見 auto_update），
          config/bank_forecasts.yaml 的手動值逐欄優先
  公布後：記下**首次公布值**（之後的修正不算），凍結各家預估，計分

計分規則（「誰最準」）：
  - 先把每家預估四捨五入到實際值的位數再比（投行多寫到 0.1，Cleveland Fed 有兩位小數）
  - 每個指標離實際值最近的記一次「命中」，同樣近就一起算
  - 方向命中：預估高於／低於共識，實際也在同一邊
  - 市場共識與 Cleveland Fed 一起排，當作基準
防抓錯：任何預估跟市場共識差太多（見 SANITY）就不採用，寫進 log。
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import math
import re
from pathlib import Path

from .. import clock

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
STATE_FILE = ROOT / "state" / "forecasts.json"
YAML_FILE = ROOT / "config" / "bank_forecasts.yaml"

BANKS = ("BofA", "Citi", "JPM", "MS", "GS")
CONS, CLEV = "市場共識", "Cleveland Fed"
RELEASES = {"employment": "就業報告", "cpi": "CPI", "pce": "PCE"}
GROUP = {"employment": "employment", "cpi": "inflation", "pce": "inflation"}
# (欄位代號, 表頭, FRED 序列, 算法)
INDICATORS = {
    "employment": [("nfp", "非農新增", "PAYEMS", "diff"), ("u3", "失業率", "UNRATE", "level"),
                   ("ahe_mom", "時薪月增", "CES0500000003", "mom")],
    "cpi": [("cpi_mom", "CPI 月增", "CPIAUCSL", "mom"), ("core_mom", "核心月增", "CPILFESL", "mom"),
            ("cpi_yoy", "CPI 年增", "CPIAUCNS", "yoy"), ("core_yoy", "核心年增", "CPILFENS", "yoy")],
    "pce": [("pce_mom", "PCE 月增", "PCEPI", "mom"), ("core_mom", "核心月增", "PCEPILFE", "mom"),
            ("pce_yoy", "PCE 年增", "PCEPI", "yoy"), ("core_yoy", "核心年增", "PCEPILFE", "yoy")],
}
# ForexFactory 的中文標籤 → 欄位
FF = {"employment": {"非農新增": "nfp", "失業率": "u3", "平均時薪月增": "ahe_mom"},
      "cpi": {"CPI 月增": "cpi_mom", "核心 CPI 月增": "core_mom", "CPI 年增": "cpi_yoy", "核心 CPI 年增": "core_yoy"},
      "pce": {"PCE 月增": "pce_mom", "核心 PCE 月增": "core_mom", "核心 PCE 年增": "core_yoy"}}
# Cleveland Fed 即時預測：(月增 m／年增 y, 序列名)
CLEV_MAP = {"cpi": {"cpi_mom": ("m", "CPI Inflation"), "core_mom": ("m", "Core CPI Inflation"),
                    "cpi_yoy": ("y", "CPI Inflation"), "core_yoy": ("y", "Core CPI Inflation")},
            "pce": {"pce_mom": ("m", "PCE Inflation"), "core_mom": ("m", "Core PCE Inflation"),
                    "pce_yoy": ("y", "PCE Inflation"), "core_yoy": ("y", "Core PCE Inflation")}}
CLEV_URL = "https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_{}.json"
# 防抓錯：跟市場共識差超過這麼多就不採用（非農單位：千人）
SANITY = {"nfp": 150, "u3": 0.3, "ahe_mom": 0.3}
SANITY_PCT = 0.3
# 實際值偏高時的意思（給「高於共識」的顏色）：hawkish＝偏鷹
HOT = {"u3": "dovish"}


# ---------------------------------------------------------------------------
# 數字工具
# ---------------------------------------------------------------------------
def round_half(x: float, nd: int) -> float:
    """半進位（跟 BLS／BEA 新聞稿口徑一致；內建 round() 是銀行家捨入）。"""
    f = 10 ** nd
    return math.floor(abs(x) * f + 0.5) / f * (1 if x >= 0 else -1)


def decimals(k: str) -> int:
    return 0 if k == "nfp" else 1


def fmt(k: str, v, nd: int | None = None) -> str:
    if v is None:
        return "無資料"
    if k == "nfp":
        return f"{v / 10:+.1f} 萬"
    nd = 1 if nd is None else nd
    return f"{v:.{nd}f}%"


def parse_ff(k: str, s) -> float | None:
    """ForexFactory 的字串（「0.3%」「+10.0 萬」）→ 數字；非農換成千人。"""
    m = re.search(r"[-+]?\d+(?:\.\d+)?", str(s or "").replace(",", ""))
    if not m:
        return None
    v = float(m.group())
    if k == "nfp":
        return v * 10 if "萬" in str(s) else v
    return v


# ---------------------------------------------------------------------------
# 實際值（首次公布值）
# ---------------------------------------------------------------------------
def _shift(ym: str, n: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    t = y * 12 + (m - 1) + n
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def actuals(series: dict, key: str) -> tuple[str, dict]:
    """最新一期（資料月份 YYYY-MM）與各欄位的實際值；序列缺就少那一欄。"""
    out, period = {}, ""
    for k, _, sid, how in INDICATORS[key]:
        rows = [r for r in (series or {}).get(sid) or [] if r.get("value") is not None]
        if len(rows) < 2:
            continue
        by = {str(r["date"])[:7]: float(r["value"]) for r in rows}
        p = str(rows[-1]["date"])[:7]
        period = max(period, p)
        cur = by.get(p)
        if how == "level":
            v = round_half(cur, 1)
        elif how == "diff":
            prev = by.get(_shift(p, -1))
            v = None if prev is None else round(cur - prev)
        elif how == "mom":
            prev = by.get(_shift(p, -1))
            v = None if not prev else round_half((cur / prev - 1) * 100, 1)
        else:
            prev = by.get(_shift(p, -12))
            v = None if not prev else round_half((cur / prev - 1) * 100, 1)
        if v is not None:
            out[k] = {"p": p, "v": v}
    # 只回傳「最新那一期」的欄位（各序列月份可能不同步）
    return period, {k: x["v"] for k, x in out.items() if x["p"] == period}


# ---------------------------------------------------------------------------
# 外部來源
# ---------------------------------------------------------------------------
def _get(url, **kw):
    import requests
    return requests.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0 (MACRO GG dashboard)"}, **kw)


def fetch_cleveland(_get_fn=None) -> dict:
    """{"m": {"2026-09": {"CPI Inflation": 0.53, …}}, "y": {…}, "asof": "2026-10-13"}；失敗回 {}。"""
    get = _get_fn or _get
    out = {"m": {}, "y": {}}
    for tag, name in (("m", "month"), ("y", "year")):
        try:
            r = get(CLEV_URL.format(name))
            if getattr(r, "status_code", 200) != 200:
                raise ValueError(f"HTTP {r.status_code}")
            for blk in r.json() or []:
                sub = str((blk.get("chart") or {}).get("subcaption", ""))
                mm = re.match(r"(\d{4})-(\d{1,2})$", sub)
                if not mm:
                    continue
                per = f"{mm.group(1)}-{int(mm.group(2)):02d}"
                vals = {}
                for ds in blk.get("dataset") or []:
                    pts = [d.get("value") for d in ds.get("data") or [] if d.get("value") not in ("", None)]
                    if pts:
                        vals[ds.get("seriesname", "")] = float(pts[-1])
                cats = ((blk.get("categories") or [{}])[0].get("category") or [])
                vals["_asof"] = cats[-1].get("label", "") if cats else ""
                out[tag][per] = vals
        except Exception as e:                     # noqa: BLE001
            log.warning("Cleveland Fed 即時預測抓取失敗（%s）：%s", name, e)
            return {}
    return out


# ---------------------------------------------------------------------------
# 投行預估：自動擷取（2026-10）
#
#   1. 讀幾個財經快訊的 RSS，挑出這一期的「預覽」文章（標題有 CPI／PCE／非農
#      ＋ preview／forecast／expect…，而且是公布前 10 天內、公布時刻之前發的）
#   2. 抓內文，交給 AI 只回 JSON：五家各自「明確寫出」的數字
#   3. 三道檢查才採用：
#        a. 數字確實出現在**提到那一家的那一句**裡（AI 不能自己編數字）
#        b. 那一句或前一句有對應的字眼（核心→core、年增→year/annual…）
#        c. 跟市場共識差距合理（_sane）
#   4. 每篇文章記內容雜湊，沒變就不重問 AI；後讀到的文章逐欄覆蓋
#   手動設定檔（config/bank_forecasts.yaml）永遠優先。
# ---------------------------------------------------------------------------
FEEDS = (("investingLive", "https://investinglive.com/feed"),
         ("FXStreet", "https://www.fxstreet.com/rss/news"),
         ("eFXdata", "https://efxdata.com/feed"))
TITLE_KW = {"employment": r"payroll|\bNFP\b|jobs report|non-?farm|employment report",
            "cpi": r"\bCPI\b", "pce": r"\bPCE\b"}
TITLE_PREVIEW = r"preview|forecast|expect|bank|forecaster|\bsees?\b|estimate|what to"
ALIASES = {"BofA": r"Bank of America|\bBofA\b|\bBoA\b|\bBAML\b",
           "Citi": r"\bCiti(?:group|bank)?\b",
           "JPM": r"JP ?Morgan|\bJPM\b",
           "MS": r"Morgan Stanley",
           "GS": r"Goldman"}
# 那一句（或前一句）要有的字眼
CONTEXT_KW = {"core": r"\bcore\b", "yoy": r"year|annual|y/y|\byoy\b|12-month",
              "nfp": r"payroll|\bjobs\b|non-?farm|\bNFP\b|employment|hiring",
              "u3": r"unemployment|jobless", "ahe_mom": r"earnings|wage|hourly|pay\b"}
MAX_AI_ARTICLES = 6
_MONTHS = ("January February March April May June July August September October November December").split()

AUTO_SYSTEM = """You extract investment-bank forecasts from a news article about an upcoming US data release.
Return ONLY a JSON object, no prose, no code fences. Format:
{"GS": {"core_mom": 0.24, "core_yoy": 2.5}, "JPM": {...}}
Banks (use exactly these keys): BofA = Bank of America; Citi = Citigroup/Citi; JPM = JPMorgan/J.P. Morgan; MS = Morgan Stanley; GS = Goldman Sachs. Ignore every other institution.
Fields allowed for this release: %(fields)s
Rules:
- Only include a number the article explicitly attributes to that bank for THIS release (%(release)s for %(month)s). A bank listed in a group ("including X, Y") that shares one number counts.
- Never infer, average, or copy the consensus/median. If a bank is mentioned without a number, leave it out.
- Percent fields in percent as written (0.24 means 0.24%%). nfp in thousands of jobs (+120k -> 120; -20,000 -> -20).
- "_mom" = month-over-month change, "_yoy" = year-over-year. "core_" = excluding food and energy. Headline fields have no "core_".
- If nothing qualifies, return {}."""
FIELD_DESC = {"nfp": "nfp (nonfarm payrolls change)", "u3": "u3 (unemployment rate)",
              "ahe_mom": "ahe_mom (average hourly earnings m/m)",
              "cpi_mom": "cpi_mom (headline CPI m/m)", "core_mom": "core_mom (core m/m)",
              "cpi_yoy": "cpi_yoy (headline CPI y/y)", "core_yoy": "core_yoy (core y/y)",
              "pce_mom": "pce_mom (headline PCE m/m)", "pce_yoy": "pce_yoy (headline PCE y/y)"}


def _strip_cdata(s: str) -> str:
    import html as _h
    return _h.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", s or "")).strip()


def feed_items(xml: str) -> list[dict]:
    """RSS → [{"title", "link", "pub"(aware datetime 或 None)}]"""
    from email.utils import parsedate_to_datetime
    out = []
    for it in re.findall(r"<item\b.*?</item>", xml or "", re.S):
        g = lambda tag: _strip_cdata((re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", it, re.S) or [None, ""])[1])  # noqa: E731
        pub = None
        try:
            pub = parsedate_to_datetime(g("pubDate"))
            if pub and pub.tzinfo is None:
                pub = pub.replace(tzinfo=dt.timezone.utc)
        except (TypeError, ValueError):
            pub = None
        if g("link"):
            out.append({"title": g("title"), "link": g("link"), "pub": pub})
    return out


def release_dt(key: str, iso: str) -> dt.datetime | None:
    try:
        from . import watch_calendar as wc
        return wc.taipei_time(dt.date.fromisoformat(iso[:10]), wc.EVENTS[key][2])
    except Exception:                              # noqa: BLE001
        return None


def is_preview(key: str, it: dict, rel_at: dt.datetime | None) -> bool:
    t = it.get("title", "")
    if not (re.search(TITLE_KW[key], t, re.I) and re.search(TITLE_PREVIEW, t, re.I)):
        return False
    pub = it.get("pub")
    if rel_at and pub:
        return rel_at - dt.timedelta(days=10) <= pub < rel_at
    return True


def sentences(text: str) -> list[str]:
    t = re.sub(r"J\.\s?P\.\s?Morgan", "JPMorgan", text or "")
    t = re.sub(r"\bU\.S\.", "US", t)
    out = []
    for line in t.splitlines():
        line = line.strip(" -•*\t")
        if line:
            out += [x.strip() for x in re.split(r"(?<=[.!?;])\s+(?=[A-Z(\"“])", line) if x.strip()]
    return out


def _num_pat(k: str, v: float) -> str:
    """數字在原文可能的寫法：0.2 → 0.2／0.20；120 → 120k／120,000／120 thousand。"""
    if k == "nfp":
        n = int(round(abs(v)))
        alts = [rf"{n}\s?(?:k|K|thousand)", rf"{n:,}(?:,000)", rf"{n * 1000:,}"]
        if n >= 1000 or n % 1000 == 0:
            alts.append(rf"{n}")
        if n % 100 == 0 and n >= 100:
            alts.append(rf"{n / 1000:g}\s?(?:m|million)")
        return r"(?<![\d.,])(?:" + "|".join(alts) + r")(?![\d])"
    s = f"{abs(v):.2f}".rstrip("0")
    s = s + "0" if s.endswith(".") else s
    ip, fp = s.split(".")
    if fp == "0":                                  # 3.0 也可能寫成 3%
        return rf"(?<![\d.]){ip}(?:\.0+)?(?![\d.])"
    return rf"(?<![\d.]){'(?:' + ip + ')?' if ip == '0' else ip}\.{fp}0*(?!\d)"


OTHER_INST = (r"Deutsche|Barclays|\bUBS\b|Wells Fargo|Nomura|\bBNP|HSBC|\bTD\b|\bRBC\b|\bBMO\b|Scotia|Jefferies|"
              r"Pantheon|Oxford Economics|Capital Economics|SocGen|Soci[eé]t[eé] G[eé]n[eé]rale|Natixis|Mizuho|MUFG|\bING\b|"
              r"Commerzbank|Standard Chartered|Nordea|Danske|\bSEB\b|Rabobank|Santander|BBVA|Credit Agricole|Evercore|"
              r"Bloomberg Economics|economists?\b|forecasters?\b|median|consensus|survey")


def clauses(s: str) -> list[str]:
    """
    一句拆成子句，數字要跟機構在同一個子句才算（防「A 0.16%，B 和 C 0.18%」張冠李戴）。
    沒提到任何機構的子句沿用前一個子句的機構（「GS 看核心 0.3%，整體 0.5%」）。
    """
    parts = re.split(r",?\s+(?:while|whereas|but|with)\s+|;\s*|,\s+and\s+(?=the rest|others)", s)
    out = []
    for p in parts:
        if re.search(r"\bfrom\s+[-+]?\d", p):
            out += re.split(r"\s+to\s+(?=[-+]?\d)", p)
        else:
            out.append(p)
    inst = "|".join(ALIASES.values()) + "|" + OTHER_INST
    merged = []
    for p in out:
        if merged and not re.search(inst, p, re.I):
            merged[-1] = merged[-1] + ", " + p
        else:
            merged.append(p)
    return merged


def evidence(key: str, bank: str, k: str, v: float, sents: list[str]) -> str:
    """找「提到這一家、而且有這個數字」的那一句；同時檢查那一句或前一句有對應字眼。沒有就回空字串。"""
    need = []
    if k.startswith("core_"):
        need.append(CONTEXT_KW["core"])
    if k.endswith("_yoy"):
        need.append(CONTEXT_KW["yoy"])
    if k in CONTEXT_KW:
        need.append(CONTEXT_KW[k])
    for i, s in enumerate(sents):
        if not re.search(ALIASES[bank], s) or not re.search(_num_pat(k, v), s):
            continue
        if not any(re.search(ALIASES[bank], c) and re.search(_num_pat(k, v), c) for c in clauses(s)):
            continue
        ctx = (sents[i - 1] + " " if i else "") + s
        if all(re.search(p, ctx, re.I) for p in need):
            # 年增的句子不該被當成月增（反之亦然）：月增欄位所在句只講年增就不採用
            if k.endswith("_mom") and re.search(CONTEXT_KW["yoy"], s, re.I) and not re.search(r"month|m/m|\bmom\b", s, re.I):
                continue
            return s
    return ""


def _parse_json(text: str) -> dict:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return {}
    try:
        d = json.loads(m.group())
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


def extract(key: str, period: str, text: str, cons: dict, ai=None) -> tuple[dict, list]:
    """
    一篇文章 → ({bank: {欄位: (數值, 證據句)}}, [被擋下的說明])。
    ai(text, system) -> (回覆, 錯誤)；預設用 focus_today._call_ai。
    """
    if ai is None:
        from .focus_today import _call_ai as ai
    fields = [x[0] for x in INDICATORS[key]]
    try:
        month = _MONTHS[int(period[5:7]) - 1] + " " + period[:4]
    except (ValueError, IndexError):
        month = period
    system = AUTO_SYSTEM % {"fields": "; ".join(FIELD_DESC[f] for f in fields),
                            "release": {"employment": "the US jobs report", "cpi": "US CPI", "pce": "US PCE"}[key],
                            "month": month}
    reply, err = ai(text[:12000], system)
    if err:
        return {}, [f"AI 失敗：{err}"]
    raw = _parse_json(reply)
    sents = sentences(text)
    got, bad = {}, []
    for b, vals in raw.items():
        if b not in BANKS or not isinstance(vals, dict):
            continue
        for k, v in vals.items():
            if k not in fields or isinstance(v, bool):
                continue
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            q = evidence(key, b, k, v, sents)
            if not q:
                bad.append(f"{b} {k}={v:g}（原文找不到對應句）")
            elif not _sane(key, k, v, cons):
                bad.append(f"{b} {k}={v:g}（跟市場共識差太多）")
            else:
                got.setdefault(b, {})[k] = (v, q[:240])
    return got, bad


def auto_update(e: dict, *, get_fn=None, ai=None, now: dt.datetime | None = None) -> None:
    """公布前：讀預覽文章、擷取、通過檢查的寫進 e["auto"]（逐欄覆蓋）。"""
    import hashlib
    get = get_fn or _get
    key, per = e["key"], e["period"]
    rel_at = release_dt(key, e.get("date", ""))
    now = now or clock.now()
    if rel_at and now >= rel_at:
        return
    seen = e.setdefault("auto_seen", {})
    auto = e.setdefault("auto", {})
    log_ = e.setdefault("auto_log", [])
    asked = 0
    for name, url in FEEDS:
        try:
            r = get(url)
            if getattr(r, "status_code", 200) != 200:
                raise ValueError(f"HTTP {r.status_code}")
            items = [it for it in feed_items(r.text) if is_preview(key, it, rel_at)]
        except Exception as ex:                    # noqa: BLE001
            log.info("投行預估自動擷取：%s 讀不到（%s）", name, ex)
            continue
        for it in items[:8]:
            if asked >= MAX_AI_ARTICLES:
                break
            try:
                import trafilatura
                text = trafilatura.extract(get(it["link"]).text) or ""
            except Exception as ex:                # noqa: BLE001
                log.info("投行預估自動擷取：內文抓取失敗 %s（%s）", it["link"], ex)
                continue
            if not any(re.search(p, text) for p in ALIASES.values()):
                seen[it["link"]] = "nobank"
                continue
            h = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
            if seen.get(it["link"]) == h:
                continue
            asked += 1
            got, bad = extract(key, per, text, e.get("cons") or {}, ai=ai)
            if any(b.startswith("AI 失敗") for b in bad):
                log.warning("投行預估自動擷取：%s", bad[0])
                continue                           # 沒記雜湊，下次再試
            seen[it["link"]] = h
            at = now.isoformat(timespec="minutes")
            for b, vals in got.items():
                for k, (v, q) in vals.items():
                    auto.setdefault(b, {})[k] = {"v": v, "src": it["link"], "name": name, "at": at, "q": q}
            msg = {"at": at, "src": name, "title": it["title"][:140], "link": it["link"],
                   "got": {b: {k: x[0] for k, x in vals.items()} for b, vals in got.items()}, "bad": bad}
            log_.append(msg)
            del log_[:-12]
            log.info("投行預估自動擷取（%s %s）：%s 採用 %s；擋下 %s", RELEASES[key], per, name, msg["got"], bad or "無")


def load_manual(path: Path | None = None) -> dict:
    """config/bank_forecasts.yaml → {"cpi|2026-09": {"GS": {"core_mom": 0.3, "src": url}, …}}"""
    try:
        import yaml
        d = yaml.safe_load((path or YAML_FILE).read_text(encoding="utf-8")) or {}
    except Exception as e:                         # noqa: BLE001
        log.warning("投行預估設定檔讀取失敗（%s），本次只用自動來源", e)
        return {}
    out = {}
    for key in RELEASES:
        for per, banks in (d.get(key) or {}).items():
            per = str(per)[:7]
            for b, vals in (banks or {}).items():
                b = str(b).strip()
                if b not in BANKS or not isinstance(vals, dict):
                    continue
                row = {k: float(v) for k, v in vals.items()
                       if k in {x[0] for x in INDICATORS[key]} and isinstance(v, (int, float))}
                if vals.get("src"):
                    row["src"] = str(vals["src"])
                if row:
                    out.setdefault(f"{key}|{per}", {})[b] = row
    return out


# ---------------------------------------------------------------------------
# 每一期的資料
# ---------------------------------------------------------------------------
def _sane(key: str, k: str, v: float, cons: dict) -> bool:
    c = cons.get(k)
    if c is None:
        return True
    lim = SANITY.get(k, SANITY_PCT)
    return abs(v - c) <= lim + 1e-9


def merge_banks(key: str, e: dict, man: dict) -> tuple[dict, list]:
    """
    自動擷取 ∪ 手動設定（手動逐欄優先）→ {bank: {欄位: 數值, "src": 網址, "meta": {欄位: 出處}}}。
    兩邊都過一次 _sane（共識可能在擷取之後才變）。
    """
    cons = e.get("cons") or {}
    fields = {x[0] for x in INDICATORS[key]}
    banks, bad = {}, []
    for b in BANKS:
        row, meta = {}, {}
        for k, x in ((e.get("auto") or {}).get(b) or {}).items():
            if k in fields and isinstance(x, dict) and _sane(key, k, x["v"], cons):
                row[k] = x["v"]
                meta[k] = {"via": "auto", "src": x.get("src", ""), "name": x.get("name", ""),
                           "at": x.get("at", ""), "q": x.get("q", "")}
        mv = man.get(b) or {}
        for k, v in mv.items():
            if k == "src" or k not in fields:
                continue
            if _sane(key, k, v, cons):
                row[k] = v
                meta[k] = {"via": "manual", "src": mv.get("src", "")}
            else:
                bad.append(f"{b} {k}={v}")
        if row:
            srcs = [m["src"] for m in meta.values() if m.get("src")]
            banks[b] = dict(row, src=srcs[0] if srcs else "", meta=meta)
    return banks, bad


def update(ctxs: dict, offline: bool, state_path: Path | None = None, *,
           manual: dict | None = None, clev: dict | None = None, today: dt.date | None = None,
           do_auto: bool = True, get_fn=None, ai=None) -> dict:
    """更新 state/forecasts.json 並回傳 {"releases": {...}, "manual_bad": [...]}（給首頁畫表格）。"""
    sp = state_path or STATE_FILE
    try:
        st = json.loads(sp.read_text(encoding="utf-8"))
    except Exception:                              # noqa: BLE001
        st = {}
    rel = st.get("releases") if isinstance(st.get("releases"), dict) else {}
    today = today or clock.today()
    sched = ctxs.get("_schedule") or {}
    cons_all = (ctxs.get("_watch_extra") or {}).get("consensus") or {}
    series = ctxs.get("_all_series") or {}
    manual = load_manual() if manual is None else manual
    need_clev = False
    # 1. 依行事曆建立／更新「近期的各期」
    for key in RELEASES:
        for d, _src in sched.get(key) or []:
            try:
                dd = dt.date.fromisoformat(str(d)[:10])
            except ValueError:
                continue
            if not (today - dt.timedelta(days=40) <= dd <= today + dt.timedelta(days=10)):
                continue
            per = _shift(dd.isoformat()[:7], -1)
            e = rel.setdefault(f"{key}|{per}", {"key": key, "period": per})
            e["date"] = dd.isoformat()
            if key in CLEV_MAP and not e.get("actual"):
                need_clev = True
    if need_clev and not offline and clev is None:
        clev = fetch_cleveland()
    # 2. 公布前：重抓共識、Cleveland Fed、投行（只留最後一版）；公布後凍結
    for eid, e in rel.items():
        key, per = e.get("key"), e.get("period")
        if key not in RELEASES:
            continue
        closed = bool(e.get("actual"))
        if not closed:
            c_rows = cons_all.get(f"{key}|{e.get('date', '')}") or []
            cons = {}
            for r in c_rows:
                k = FF[key].get(r.get("label", ""))
                v = parse_ff(k, r.get("forecast")) if k else None
                if k and v is not None:
                    cons[k] = v
            if cons:
                e["cons"] = cons
                e["cons_at"] = clock.now().isoformat(timespec="minutes")
            if clev and key in CLEV_MAP:
                cv = {}
                for k, (tag, name) in CLEV_MAP[key].items():
                    v = ((clev.get(tag) or {}).get(per) or {}).get(name)
                    if v is not None:
                        cv[k] = round(v, 2)
                if cv:
                    e["clev"] = cv
                    e["clev_asof"] = ((clev.get("m") or {}).get(per) or {}).get("_asof", "")
        e["banks"], e["bad"] = merge_banks(key, e, manual.get(eid) or {})
        if e["bad"]:
            log.warning("投行預估（%s）跟市場共識差太多、不採用：%s", eid, "、".join(e["bad"]))
    # 3. 首次公布值：資料月份對上、還沒記過才記
    for key in RELEASES:
        per, vals = actuals(series, key)
        e = rel.get(f"{key}|{per}")
        if e and vals and not e.get("actual"):
            e["actual"] = vals
            e["actual_at"] = clock.now().isoformat(timespec="minutes")
            log.info("各家預測：%s %s 首次公布值 %s", RELEASES[key], per, vals)
    # 4. 投行預估自動擷取：10 天內要公布、還沒公布的那一期；擷取完重新合併
    if do_auto and not offline:
        for eid, e in rel.items():
            try:
                dd = dt.date.fromisoformat(e.get("date", ""))
            except ValueError:
                continue
            if e.get("key") in RELEASES and not e.get("actual") and today <= dd <= today + dt.timedelta(days=10):
                e.pop("recon", None)
                try:
                    auto_update(e, get_fn=get_fn, ai=ai)
                except Exception as ex:            # noqa: BLE001
                    log.warning("投行預估自動擷取失敗（%s）：%s", eid, ex)
                e["banks"], e["bad"] = merge_banks(e["key"], e, manual.get(eid) or {})
    st["releases"] = rel
    if offline:                                    # 離線示範不寫狀態檔
        return {"releases": rel}
    try:
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:                         # noqa: BLE001
        log.warning("各家預測狀態寫入失敗（%s）", e)
    return {"releases": rel}


# ---------------------------------------------------------------------------
# 計分與表格資料
# ---------------------------------------------------------------------------
def forecasters(e: dict) -> dict:
    """{名稱: {欄位: 數值}}，順序：五家投行、市場共識、Cleveland Fed。"""
    fields = {x[0] for x in INDICATORS.get(e.get("key"), [])} or None
    out = {b: {k: v for k, v in ((e.get("banks") or {}).get(b) or {}).items()
               if k not in ("src", "meta") and (fields is None or k in fields)} for b in BANKS}
    out[CONS] = dict(e.get("cons") or {})
    out[CLEV] = dict(e.get("clev") or {})
    return out


def score(e: dict) -> dict:
    """單一期：{欄位: {"best": [名稱…], "err": {名稱: 誤差}, "dir": {名稱: True/False}}}"""
    act = e.get("actual") or {}
    fc = forecasters(e)
    out = {}
    for k, a in act.items():
        nd = decimals(k)
        errs = {n: abs(round_half(v[k], nd) - a) for n, v in fc.items() if v.get(k) is not None}
        if not errs:
            continue
        lo = min(errs.values())
        best = [n for n, x in errs.items() if abs(x - lo) < 1e-9]
        dirs = {}
        c = fc[CONS].get(k)
        if c is not None and abs(a - c) > 1e-9:
            for n, v in fc.items():
                if n == CONS or v.get(k) is None:
                    continue
                f = round_half(v[k], nd)
                if abs(f - c) > 1e-9:
                    dirs[n] = (f > c) == (a > c)
        out[k] = {"best": best, "err": errs, "dir": dirs}
    return out


def leaderboard(rel: dict, group: str) -> dict:
    """{"rows": [...], "periods": N}；rows 依命中數、平均誤差排序。"""
    agg = {}
    n_periods = 0
    for e in rel.values():
        if GROUP.get(e.get("key")) != group or not e.get("actual"):
            continue
        sc = score(e)
        if not sc:
            continue
        n_periods += 1
        seen = set()
        for k, s in sc.items():
            for n, err in s["err"].items():
                a = agg.setdefault(n, {"hit": 0, "dir": 0, "dirn": 0, "err": [], "nfp": [], "periods": 0})
                seen.add(n)
                if n in s["best"]:
                    a["hit"] += 1
                if k == "nfp":
                    a["nfp"].append(err)
                else:
                    a["err"].append(err)
            for n, ok in s["dir"].items():
                a = agg[n]
                a["dirn"] += 1
                a["dir"] += 1 if ok else 0
        for n in seen:
            agg[n]["periods"] += 1
    rows = []
    for n, a in agg.items():
        rows.append({"name": n, "hit": a["hit"], "dir": a["dir"], "dirn": a["dirn"],
                     "err": (sum(a["err"]) / len(a["err"])) if a["err"] else None,
                     "nfp_err": (sum(a["nfp"]) / len(a["nfp"])) if a["nfp"] else None,
                     "periods": a["periods"]})
    rows.sort(key=lambda r: (-r["hit"], r["err"] if r["err"] is not None else
                             (r["nfp_err"] if r["nfp_err"] is not None else 9e9)))
    return {"rows": rows, "periods": n_periods}


def pick(rel: dict, key: str, today: dt.date | None = None) -> dict | None:
    """這個分頁要顯示哪一期：10 天內即將公布的優先，否則最近一期已公布的。"""
    today = today or clock.today()
    es = [e for e in rel.values() if e.get("key") == key and e.get("date")]
    up = sorted([e for e in es if not e.get("actual") and e["date"] >= today.isoformat()
                 and e["date"] <= (today + dt.timedelta(days=10)).isoformat()], key=lambda e: e["date"])
    if up:
        return up[0]
    done = sorted([e for e in es if e.get("actual")], key=lambda e: e["date"], reverse=True)
    if done:
        return done[0]
    rest = sorted(es, key=lambda e: e["date"])
    return rest[0] if rest else None
