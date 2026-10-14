"""
總覽「04 各家預測」（2026-10）：失業與通膨，各家投行 vs 市場共識 vs Cleveland Fed。

每一期（就業報告／CPI／PCE）一筆，存在 state/forecasts.json：
  公布前：每次更新都重抓市場共識（ForexFactory）與 Cleveland Fed 即時預測，
          只保留「公布前的最後一版」；投行預估來自 config/bank_forecasts.yaml（手動）
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


def recon(key: str, period: str, _get_fn=None) -> dict:
    """
    投行預估的偵察（只記錄、不上畫面）：用關鍵字搜新聞，看找得到哪些預覽文章，
    並測試幾個彙整來源讀不讀得到，結果寫進 log 與 state，之後決定要不要做自動擷取。
    """
    import html as _h
    import urllib.parse as up
    get = _get_fn or _get
    word = {"employment": "(payrolls OR \"jobs report\" OR NFP)", "cpi": "CPI", "pce": "PCE"}[key]
    q = f"({' OR '.join(chr(34) + b + chr(34) for b in ('Goldman Sachs', 'JPMorgan', 'Morgan Stanley', 'Citi', 'Bank of America'))} OR \"major banks\" OR \"investment bank\") {word} (preview OR expects OR forecast) when:7d"
    found, access = [], {}
    try:
        r = get("https://news.google.com/rss/search?q=" + up.quote(q) + "&hl=en-US&gl=US&ceid=US:en")
        for it in re.findall(r"<item>.*?</item>", r.text, re.S)[:20]:
            t = _h.unescape((re.search(r"<title>(.*?)</title>", it, re.S) or [None, ""])[1])
            found.append(t[:140])
    except Exception as e:                         # noqa: BLE001
        found.append(f"（搜尋失敗：{e}）")
    for name, url in (("investingLive", "https://investinglive.com/feed"),
                      ("eFXdata", "https://efxdata.com/"),
                      ("FXStreet", "https://www.fxstreet.com/rss/news")):
        try:
            access[name] = getattr(get(url), "status_code", 0)
        except Exception as e:                     # noqa: BLE001
            access[name] = f"失敗：{type(e).__name__}"
    # investingLive 的預覽彙整（例：「US CPI preview: 14 investment bank forecasters…」）：
    # 讀內文，數一數五家各被提到幾次、附近有沒有數字——只記錄，不上畫面
    bodies = []
    try:
        fr = get("https://investinglive.com/feed")
        if getattr(fr, "status_code", 0) == 200:
            kw = {"employment": r"payroll|NFP|jobs report|non-?farm", "cpi": r"\bCPI\b", "pce": r"\bPCE\b"}[key]
            for it in re.findall(r"<item>.*?</item>", fr.text, re.S):
                t = _h.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", (re.search(r"<title>(.*?)</title>", it, re.S) or [None, ""])[1]))
                ln = (re.search(r"<link>(.*?)</link>", it, re.S) or [None, ""])[1].strip()
                if re.search(kw, t, re.I) and re.search(r"preview|forecaster|bank|expect", t, re.I) and ln:
                    try:
                        import trafilatura
                        txt = trafilatura.extract(get(ln).text) or ""
                    except Exception:              # noqa: BLE001
                        txt = ""
                    hits = {b: len(re.findall(p_, txt)) for b, p_ in (
                        ("BofA", r"Bank of America|BofA"), ("Citi", r"Citi(?:group)?\b"), ("JPM", r"JPMorgan|J\.P\. Morgan"),
                        ("MS", r"Morgan Stanley"), ("GS", r"Goldman"))}
                    bodies.append({"title": t[:140], "link": ln, "chars": len(txt), "banks": hits,
                                   "numbers": len(re.findall(r"\d+\.\d+%", txt))})
                    if len(bodies) >= 3:
                        break
    except Exception as e:                         # noqa: BLE001
        bodies.append({"error": str(e)})
    for bd in bodies:
        log.info("投行預估偵察：investingLive 內文 %s", bd)
    log.info("投行預估偵察（%s %s）：找到 %d 則；來源可讀性 %s", RELEASES[key], period, len(found), access)
    for t in found[:12]:
        log.info("投行預估偵察：%s", t)
    return {"at": clock.now().isoformat(timespec="minutes"), "titles": found, "access": access, "bodies": bodies}


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


def update(ctxs: dict, offline: bool, state_path: Path | None = None, *,
           manual: dict | None = None, clev: dict | None = None, today: dt.date | None = None,
           do_recon: bool = True) -> dict:
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
        # 投行（手動）：隨時以設定檔為準；跟共識差太多的不採用
        m = manual.get(eid) or {}
        banks, bad = {}, []
        for b, vals in m.items():
            row = {}
            for k, v in vals.items():
                if k == "src":
                    continue
                if _sane(key, k, v, e.get("cons") or {}):
                    row[k] = v
                else:
                    bad.append(f"{b} {k}={v}")
            if row:
                row["src"] = vals.get("src", "")
                banks[b] = row
        if bad:
            log.warning("投行預估（%s）跟市場共識差太多、不採用：%s", eid, "、".join(bad))
        e["banks"] = banks
        e["bad"] = bad
    # 3. 首次公布值：資料月份對上、還沒記過才記
    for key in RELEASES:
        per, vals = actuals(series, key)
        e = rel.get(f"{key}|{per}")
        if e and vals and not e.get("actual"):
            e["actual"] = vals
            e["actual_at"] = clock.now().isoformat(timespec="minutes")
            log.info("各家預測：%s %s 首次公布值 %s", RELEASES[key], per, vals)
    # 4. 偵察（只記錄）：7 天內要公布、還沒公布的那一期
    if do_recon and not offline:
        for eid, e in rel.items():
            try:
                dd = dt.date.fromisoformat(e.get("date", ""))
            except ValueError:
                continue
            if not e.get("actual") and today <= dd <= today + dt.timedelta(days=7):
                e["recon"] = recon(e["key"], e["period"])
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
    out = {b: {k: v for k, v in ((e.get("banks") or {}).get(b) or {}).items() if k != "src"} for b in BANKS}
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
