"""
首頁「今日快報」限時動態（2026-10）：每天第一次打開首頁時播一次，五則：

  1 你的指標    問候＋依兩個指標漲跌自動寫的一句＋數值與變動（瀏覽器端讀報價板）
  2 今日主軸    主軸標題＋第一句
  3 對利率      主軸的「對利率」，並判斷偏向推升／壓低／不明確
  4 最新數據    最近一次公布的重要數據；有市場預估就標高於／低於預估
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
    order = ("labor", "inflation", "pce", "fomc", "jolts", "claims")

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
        rows, name = [], ""
        if k == "labor" and lk.get("nfp_display", "—") != "—":
            name = f"就業報告（{mon(lab.get('data_month', ''))}）"
            rows = [("非農新增", lk["nfp_display"], "employment", "非農新增"),
                    ("失業率", lk.get("u3_display", "—"), "employment", "失業率")]
        elif k == "inflation" and ik.get("core_display", "—") != "—":
            name = f"CPI 物價（{mon(inf.get('data_month', ''))}）"
            rows = [("核心 CPI 月增", ik["core_display"], "cpi", "核心 CPI 月增"),
                    ("CPI 月增", ik.get("headline_display", "—"), "cpi", "CPI 月增")]
        elif k == "pce" and ik.get("pce_display", "—") != "—":
            name = f"PCE 物價（{mon((inf.get('asof') or {}).get('pce', ''))}）"
            rows = [("核心 PCE 年增", ik["pce_display"], "pce", "核心 PCE 年增")]
        elif k == "claims" and ((lab.get("claims") or {}).get("machine") or {}).get("ic_now"):
            mc = lab["claims"]["machine"]
            wk = str(mc.get("week", ""))
            name = "初領失業金" + (f"（統計週至 {int(wk[5:7])}/{int(wk[8:10])}）" if len(wk) >= 10 else "")
            rows = [("初領人數", f"{mc['ic_now'] / 10000:.1f} 萬人", "claims", "初領失業金")]
            if mc.get("ic_ma"):
                rows.append(("四週平均", f"{mc['ic_ma'] / 10000:.1f} 萬人", "", ""))
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
    早上那次延到 08:40 也算當天；晚上 22:45 那次拖過午夜（00:30）仍算前一天。
    """
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return (t.astimezone(_TPE) - dt.timedelta(hours=EDITION_CUTOFF_HOURS)).date().isoformat()


def build_story(ctxs: dict) -> dict:
    f = ctxs.get("_focus") or {}
    paras = [p.strip() for p in (f.get("text") or "").split("\n") if p.strip()]
    first = ""
    if paras and f.get("layout") == "main":
        m = [x for x in paras[0].split("¶") if x.strip()]
        if m:
            first = re.split(r"(?<=[。！？])", m[0].strip())[0]
            first = first if len(first) <= 70 else first[:68] + "…"
    rn = (f.get("rate_note") or "").strip()
    now = clock.now()
    return {
        "day": clock.today().isoformat(),
        # 版本日期：每天播一次是看「內容是哪一天的版本」，不看讀者打開的時間
        # （GitHub 排程常延遲，早上那次不一定 07:03 準時上線）
        "edition": edition_day(now),
        "stamp": now.strftime("%m/%d %H:%M"),
        "headline": (f.get("headline") or "").strip(),
        "lead": first,
        "rate": rn,
        "rate_dir": rate_direction(rn),
        "latest": latest_release(ctxs),
        "up": ctxs.get("_story_up") or [],
    }
