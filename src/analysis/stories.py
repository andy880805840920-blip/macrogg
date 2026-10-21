"""
首頁「今日快報」限時動態（2026-10）：每天第一次打開首頁時播一次，五則：

  1 你的指標    問候＋依兩個指標漲跌自動寫的一句＋數值與變動（瀏覽器端讀報價板）
  2 今日主軸    主軸標題＋第一句
  3 對利率      主軸的「對利率」，並判斷偏向推升／壓低／不明確
  4 最新數據    最近一次公布的重要數據（不含每週的初領失業金）；有市場預估就標高於／低於預估
  5 今明兩天    數據、發債、官員談話、休市

這裡只組資料（JSON），畫面與動畫在 pages/home.py。
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from .. import clock

ROOT = Path(__file__).resolve().parents[2]
RELEASES_FILE = ROOT / "state" / "releases.json"
_TPE = dt.timezone(dt.timedelta(hours=8))

_UNCLEAR = re.compile(r"方向不明|不明確|取決於|兩面")
_UP = re.compile(r"推升|上行|走高|攀升|上揚|升息預期|加碼升息|壓力未退|走升")
_DN = re.compile(r"壓低|下行|回落|走低|下滑|降息預期|降溫|滑落|下修升息")


def rate_direction(note: str) -> str:
    """對利率那句的方向：up／down／unclear／flat。只看第一個子句（後半常是對照數據）。"""
    s = (note or "").strip()
    if not s:
        return ""
    if _UNCLEAR.search(s):
        return "unclear"
    head = re.split(r"[；;]|不過|但是|然而", s)[0]
    up, dn = bool(_UP.search(head)), bool(_DN.search(head))
    if up and not dn:
        return "up"
    if dn and not up:
        return "down"
    if "持平" in head:
        return "flat"
    return "unclear" if up and dn else "flat"


def _num(s) -> float | None:
    m = re.search(r"[-+]?\d+(?:\.\d+)?", str(s or "").replace(",", ""))
    return float(m.group()) if m else None


def _vs(actual: str, forecast: str) -> str:
    a, f = _num(actual), _num(forecast)
    if a is None or f is None:
        return ""
    if abs(a - f) < 1e-9:
        return "符合預估"
    return "高於預估" if a > f else "低於預估"


def _cons_for(cons: dict, key: str, seen: dt.date | None) -> list:
    """ForexFactory 的預估是以美東發布日為鍵；發布日在第一次看到的前 3 天內就算同一次。"""
    if not seen:
        return []
    for k in range(0, 4):
        rows = cons.get(f"{key}|{(seen - dt.timedelta(days=k)).isoformat()}")
        if rows:
            return rows
    return []


def _fmt_like(actual: str, v: float) -> str:
    """存檔的預估是數字：照實際值的寫法（小數位、% 或 K）補上單位。"""
    a = str(actual or "")
    m = re.search(r"\d+(?:\.(\d+))?", a.replace(",", ""))
    nd = len(m.group(1)) if m and m.group(1) else (1 if "%" in a else 0)
    unit = "%" if "%" in a else ("K" if a.rstrip().endswith("K") else ("萬" if a.rstrip().endswith("萬") else ""))
    return f"{v:.{nd}f}{unit}"


def _stored_cons(ctxs: dict, ck: str, cl: str, period: str) -> float | None:
    """ForexFactory 週曲只放本週與下週，過了一週就查不到——改用存檔的預估（2026-10）：
    PPI 用 state/ppi.json（通膨模組 ppi.cons）；CPI、非農、PCE 用各家預測的市場共識。"""
    if ck == "ppi":
        from .ppi_watch import FF_LABEL
        pp = (ctxs.get("inflation") or {}).get("ppi") or {}
        if period and str(pp.get("period") or "")[:7] not in ("", period[:7]):
            return None
        return (pp.get("cons") or {}).get(FF_LABEL.get(cl, ""))
    try:
        from .forecasts import FF
    except Exception:                              # noqa: BLE001
        return None
    field = (FF.get(ck) or {}).get(cl)
    rel = ((ctxs.get("_forecasts") or {}).get("releases") or {})
    if not field or not rel:
        return None
    es = [e for e in rel.values() if e.get("key") == ck and (e.get("cons") or {}).get(field) is not None]
    if period:
        es = [e for e in es if str(e.get("period") or "")[:7] == period[:7]]
    es.sort(key=lambda e: str(e.get("date") or ""))
    return es[-1]["cons"][field] if es else None


def latest_release(ctxs: dict, releases: dict | None = None) -> dict | None:
    """最近一次公布的重要數據（依 state/releases.json 第一次看到的時間）。"""
    if releases is None:
        try:
            releases = json.loads(RELEASES_FILE.read_text(encoding="utf-8"))
        except Exception:                          # noqa: BLE001
            releases = {}
    lab, inf = ctxs.get("labor") or {}, ctxs.get("inflation") or {}
    fom = ctxs.get("fomc") or {}
    lk, ik = lab.get("kpi") or {}, inf.get("kpi") or {}
    cons = (ctxs.get("_watch_extra") or {}).get("consensus") or {}
    # 初領失業金不放（2026-10）：每週四都公布，放進來會蓋掉前幾天更重要的
    # CPI、PPI、就業報告；它在就業頁與本期變化照常更新
    order = ("labor", "inflation", "pce", "ppi", "fomc", "jolts")

    def seen_at(k):
        r = (releases or {}).get(k)
        try:
            return dt.datetime.fromisoformat(r["first_seen"]) if isinstance(r, dict) else None
        except (KeyError, TypeError, ValueError):
            return None
    cand = [(seen_at(k), -i, k) for i, k in enumerate(order) if seen_at(k)]
    keys = [k for _, _, k in sorted(cand, reverse=True)] or list(order)

    def mon(s):
        return f"{int(str(s)[5:7])} 月" if len(str(s)) >= 7 else ""

    for k in keys:
        at = seen_at(k)
        d = at.astimezone(_TPE).date() if at else None
        rows, name, per = [], "", ""
        if k == "labor" and lk.get("nfp_display", "—") != "—":
            name = f"就業報告（{mon(lab.get('data_month', ''))}）"
            per = str(lab.get("data_month") or "")
            rows = [("非農新增", lk["nfp_display"], "employment", "非農新增"),
                    ("失業率", lk.get("u3_display", "—"), "employment", "失業率")]
        elif k == "inflation" and ik.get("core_display", "—") != "—":
            name = f"CPI 物價（{mon(inf.get('data_month', ''))}）"
            per = str(inf.get("data_month") or "")
            rows = [("核心 CPI 月增", ik["core_display"], "cpi", "核心 CPI 月增"),
                    ("CPI 月增", ik.get("headline_display", "—"), "cpi", "CPI 月增")]
        elif k == "pce" and ik.get("pce_display", "—") != "—":
            name = f"PCE 物價（{mon((inf.get('asof') or {}).get('pce', ''))}）"
            per = str((inf.get("asof") or {}).get("pce") or "")
            rows = [("核心 PCE 年增", ik["pce_display"], "pce", "核心 PCE 年增")]
        elif k == "ppi" and (inf.get("ppi") or {}).get("mom") is not None:
            pp = inf["ppi"]
            name = f"PPI 生產者物價（{mon(pp.get('period') or pp.get('asof', ''))}）"
            per = str(pp.get("period") or pp.get("asof") or "")
            rows = [("PPI 月增", f"{pp['mom']:.1f}%", "ppi", "PPI 月增")]
            if pp.get("core_mom_1d") is not None:
                rows.append(("核心 PPI 月增", f"{pp['core_mom_1d']:.1f}%", "ppi", "核心 PPI 月增"))
        elif k == "jolts" and lab.get("jolts"):
            jr = lab["jolts"]
            name = f"JOLTS 職缺（{mon(lab.get('jolts_month', ''))}）"
            rows = [(r.get("label", ""), r.get("value", "—"), "jolts" if i == 0 else "",
                     "職缺數" if i == 0 else "") for i, r in enumerate(jr[:2])]
        elif k == "fomc" and not fom.get("empty") and fom.get("decision_label"):
            name = f"FOMC 決議（{str(fom.get('latest_date', ''))[5:].replace('-', '/')}）"
            rows = [("決議", fom["decision_label"], "", ""),
                    ("目標區間", fom.get("rate_range", "—"), "", "")]
        if not rows:
            continue
        out = []
        for label, actual, ck, cl in rows:
            if not actual or actual == "—":
                continue
            c = next((x for x in _cons_for(cons, ck, d) if x.get("label") == cl), None) if ck else None
            if ck and not (c or {}).get("forecast"):
                sv = _stored_cons(ctxs, ck, cl, per)
                if sv is not None:
                    fc = f"{sv / 10:+,.1f} 萬" if cl == "非農新增" else _fmt_like(actual, sv)
                    c = {"forecast": fc, "previous": (c or {}).get("previous", "")}
            out.append({"label": label, "actual": actual,
                        "forecast": (c or {}).get("forecast", ""),
                        "previous": (c or {}).get("previous", ""),
                        "vs": _vs(actual, (c or {}).get("forecast", "")) if c else ""})
        if out:
            return {"name": name, "date": f"{d.month}/{d.day}" if d else "", "rows": out[:2]}
    return None


EDITION_CUTOFF_HOURS = 5


def edition_day(t: dt.datetime) -> str:
    """
    這份內容算哪一天的版本：台灣時間往前推 5 小時取日期。
    早上 05:03 那次（延遲到幾點都）算當天；晚上 20:33 那次拖過午夜（00:30）仍算前一天。
    """
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return (t.astimezone(_TPE) - dt.timedelta(hours=EDITION_CUTOFF_HOURS)).date().isoformat()


def build_story(ctxs: dict) -> dict:
    f = ctxs.get("_focus") or {}
    paras = [p.strip() for p in (f.get("text") or "").split("\n") if p.strip()]
    first = para = ""
    chunks = []
    if paras and f.get("layout") == "main":
        m = [x for x in paras[0].split("¶") if x.strip()]
        if m:
            # 今日市場圖（9:16 圖卡）用整段第一段，畫面上最多五行
            para = m[0].strip()
            chunks = [x.strip() for x in m if x.strip()][:4]
            para = para if len(para) <= 240 else para[:238] + "…"
            first = re.split(r"(?<=[。！？])", m[0].strip())[0]
            first = first if len(first) <= 70 else first[:68] + "…"
    rn = (f.get("rate_note") or "").strip()
    now = clock.now()
    return {
        "day": clock.today().isoformat(),
        # 版本日期：每天播一次是看「內容是哪一天的版本」，不看讀者打開的時間
        # （GitHub 排程常延遲，早上那次不一定 05:03 準時上線）
        "edition": edition_day(now),
        "stamp": now.strftime("%m/%d %H:%M"),
        "headline": (f.get("headline") or "").strip(),
        "lead": first,
        "para": para,
        "paras": chunks,          # 今日快報圖卡：原文本身的分段（只有一段時由瀏覽器依句號分段）
        "rate": rn,
        "rate_dir": rate_direction(rn),
        "latest": latest_release(ctxs),
        "up": ctxs.get("_story_up") or [],
    }
