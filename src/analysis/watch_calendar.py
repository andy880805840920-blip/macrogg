"""
首頁「接下來看什麼」的行事曆：本週＋下週會發布什麼、幾點（台灣時間）、
影響多大、它會動什麼。

日期來源（優先序，每一列都標出處）：
  1. FRED release/dates——各機構自己報給 FRED 的官方排程（就業報告、
     CPI、PPI、PCE、GDP、零售銷售、初領失業金、JOLTS、密大信心）。
  2. config/releases_calendar.yaml——手動抄錄的官方行事曆；FRED 問不到
     （或離線）時的後備。
  3. 公債標售：財政部 Fiscal Data 的 upcoming_auctions（已公告的標售，
     約提前一週）＋ yaml 裡抄錄的財政部「暫定標售時程表」補更遠的日期。
  4. 慣例推估——只有就業報告（第一個週五）、CPI（次月 12 日前後）、
     初領失業金（每週四）這三種推得出來的才推，畫面標「慣例推估」。

影響分級是**本站自己的規則**，不是市場共識：
  高＝發布後會直接重判本站九宮格的格位（就業、物價、聯準會）。
  中＝更新個別訊號、或市場常有反應，但不直接改格位。
"""
from __future__ import annotations

import datetime as dt
import logging

from .. import clock

log = logging.getLogger(__name__)

# key: (名稱, 影響, 美東發布時間 (時, 分), 它會動什麼)
EVENTS: dict[str, tuple[str, str, tuple[int, int], str]] = {
    "employment": ("就業報告（非農）", "high", (8, 30),
                   "失業率決定就業格位，非農與時薪決定方向。"),
    "cpi": ("CPI", "high", (8, 30), "先更新通膨軸的推估值與動能。"),
    "pce": ("PCE 物價", "high", (8, 30),
            "推估值換回實際值，通膨格位以實際值重新判定。"),
    "fomc": ("FOMC 利率決策", "high", (14, 0), ""),
    "ppi": ("PPI", "mid", (8, 30),
            "更新上游成本壓力，也是核心 PCE 推估的原料之一。"),
    "jolts": ("JOLTS 職缺", "mid", (10, 0),
              "職缺與離職率：勞動需求降溫通常先在這裡出現。"),
    "gdp": ("GDP", "mid", (8, 30),
            "整體成長速度；同一季依序公布初估、修正、終值。"),
    "retail": ("零售銷售", "mid", (8, 30),
               "每月的消費動能讀數；消費約佔 GDP 近七成。"),
    "claims": ("初領失業金", "mid", (8, 30),
               "兩次就業報告之間最即時的就業數據；重點盯續領人數有沒有一路往上爬。"),
    "umich": ("密大消費者信心（終值）", "mid", (10, 0),
              "含 1 年與 5–10 年通膨預期；預期升溫，聯準會就更難降息。"),
    "auction_10y": ("10 年期公債標售", "mid", (13, 0),
                    "看得標利率與投標倍數；需求疲弱時長端殖利率常跟著走高。"),
    "auction_30y": ("30 年期公債標售", "mid", (13, 0),
                    "超長天期的需求溫度計，財政供給壓力最先反映在這裡。"),
}
IMPACT_LABEL = {"high": "高", "mid": "中"}

SRC_FRED = "官方行事曆"
SRC_YAML = "官方行事曆"
SRC_TSY = "財政部公告"
SRC_TSY_TENT = "財政部暫定表"
SRC_CONV = "慣例推估"
SRC_FED = "官方行事曆"

AUCTIONS_URL = ("https://api.fiscaldata.treasury.gov/services/api/"
                "fiscal_service/v1/accounting/od/upcoming_auctions")
# 增額發行（reopening）的期限會寫成「9-Year 10-Month」「29-Year 11-Month」
_AUCTION_TERMS = {"auction_10y": ("Note", ("10-Year", "9-Year")),
                  "auction_30y": ("Bond", ("30-Year", "29-Year"))}


def _iso(d) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(d)[:10])
    except (TypeError, ValueError):
        return None


def fetch_auctions(_get=None, today: dt.date | None = None) -> dict:
    """
    已公告的 10 年／30 年期標售日 → {"auction_10y": [iso…], "auction_30y": […]}。
    失敗回 {}（畫面改用 yaml 的暫定表）。
    """
    today = today or clock.today()
    if _get is None:
        import requests

        def _get(url, params):
            return requests.get(url, params=params, timeout=20)
    try:
        r = _get(AUCTIONS_URL, {"sort": "-record_date", "page[size]": "100",
                                "filter": f"auction_date:gte:{today.isoformat()}"})
        r.raise_for_status()
        rows = (r.json() or {}).get("data") or []
    except Exception as e:                            # noqa: BLE001
        log.warning("公債標售：財政部 upcoming_auctions 抓取失敗（%s），"
                    "改用 yaml 暫定表", e)
        return {}
    out: dict[str, list[str]] = {}
    for row in rows:
        d = _iso(row.get("auction_date"))
        if not d or d < today:
            continue
        for key, (typ, terms) in _AUCTION_TERMS.items():
            if (row.get("security_type") == typ
                    and str(row.get("security_term", "")).startswith(terms)):
                out.setdefault(key, [])
                if d.isoformat() not in out[key]:
                    out[key].append(d.isoformat())
    for v in out.values():
        v.sort()
    log.info("公債標售：財政部已公告 %s（共讀 %d 列）",
             "、".join(f"{k} {','.join(v)}" for k, v in out.items()) or "無 10Y／30Y",
             len(rows))
    return out


def _thursdays(today: dt.date, n: int = 3) -> list[dt.date]:
    d = today + dt.timedelta(days=(3 - today.weekday()) % 7)
    return [d + dt.timedelta(weeks=i) for i in range(n)]


def merge_schedule(fred: dict | None, calendar: dict | None,
                   auctions: dict | None, today: dt.date | None = None,
                   back_days: int = 3) -> dict[str, list[tuple[str, str]]]:
    """
    各事件的日期清單 {key: [(iso, 出處), …]}，含最近 back_days 天內剛發布的
    （給焦點區判斷「昨天有什麼發布」）。

    每個 key 只取一個來源：FRED 有今天以後的日期就整組用 FRED，否則用
    yaml。不混用——同一份報告兩個來源各給一個日期時，混用會變成兩列。
    標售例外：財政部 API 只涵蓋已公告的（約一週），更遠的接 yaml 暫定表。
    """
    from ..site import next_cpi_release, next_first_friday
    today = today or clock.today()
    lo = today - dt.timedelta(days=back_days)
    fred, calendar, auctions = fred or {}, calendar or {}, auctions or {}
    out: dict[str, list[tuple[str, str]]] = {}

    def _yaml(key):
        return sorted({d for d in (_iso(v) for v in
                                   ((calendar.get(key) or {}).values()))
                       if d and d >= lo})

    for key in EVENTS:
        if key == "fomc":
            continue
        if key.startswith("auction_"):
            api = sorted({d for d in map(_iso, auctions.get(key) or []) if d})
            cut = max(api) if api else lo - dt.timedelta(days=1)
            rows = ([(d, SRC_TSY) for d in api if d >= lo]
                    + [(d, SRC_TSY_TENT) for d in _yaml(key) if d > cut])
        else:
            f = sorted({d for d in map(_iso, fred.get(key) or []) if d and d >= lo})
            if any(d >= today for d in f):
                rows = [(d, SRC_FRED) for d in f]
            else:
                rows = [(d, SRC_YAML) for d in _yaml(key)]
            if not any(d >= today for d, _ in rows):
                conv = {"employment": lambda: [next_first_friday(today - dt.timedelta(days=1))],
                        "cpi": lambda: [next_cpi_release(today - dt.timedelta(days=1))],
                        "claims": lambda: _thursdays(today)}.get(key)
                if conv:
                    rows += [(d, SRC_CONV) for d in conv() if d >= today]
        if rows:
            out[key] = [(d.isoformat(), s) for d, s in sorted(rows)]
    return out


def event_dates(schedule: dict, fomc_dates=None) -> dict[str, list[str]]:
    """給焦點區的 {種類: [ISO…]}（含剛發布的）。"""
    ev = {k: [d for d, _ in v] for k, v in (schedule or {}).items()}
    if fomc_dates:
        ev["fomc"] = sorted({str(d)[:10] for d in fomc_dates})
    return ev


def taipei_time(d: dt.date, hm: tuple[int, int]) -> dt.datetime:
    """美東 d 日 hh:mm → 台北時間（夏令自動處理，用 clock.ny_offset）。"""
    noon = dt.datetime(d.year, d.month, d.day, 12, tzinfo=dt.timezone.utc)
    off = clock.ny_offset(noon)
    utc = dt.datetime(d.year, d.month, d.day, *hm,
                      tzinfo=dt.timezone.utc) - dt.timedelta(hours=off)
    return utc.astimezone(clock.TAIPEI)


_WD = "一二三四五六日"
_GROUPS = ("本週", "下週", "下下週", "第 4 週", "第 5 週")


def _group(d: dt.date, mon: dt.date) -> str:
    """週一起算的週別＋日期範圍，例如「下週　10/05–10/11」。"""
    k = (d - mon).days // 7
    a = mon + dt.timedelta(days=7 * k)
    b = a + dt.timedelta(days=6)
    return (f"{_GROUPS[k]}　{a.month:02d}/{a.day:02d}–"
            f"{b.month:02d}/{b.day:02d}")


def watch_rows(schedule: dict, fomc_next: str | None = None,
               fomc_desc: str = "", trig: dict | None = None,
               now: dt.datetime | None = None, weeks: int = 2) -> list[dict]:
    """
    本週＋下週（weeks＞2 時往後延伸，總覽日曆用 4 週）（週一起算，台北日期；週末改看下週＋下下週）尚未發布的事件，
    依時間排序。
    回傳 [{group, key, name, impact, date, tpe, when, src, desc}]。
    同一種事件第二次出現（例如每週的失業金）不重複說明——一頁一個意思講一次。
    """
    now = now or clock.now()
    today = now.date()
    mon = today - dt.timedelta(days=today.weekday())
    # 週六、週日（台灣週六 07:00 那次）本週已經沒有發布，改看接下來兩整週
    start = mon + dt.timedelta(days=7 if today.weekday() >= 5 else 0)
    end_next = start + dt.timedelta(days=7 * weeks - 1)
    items = []
    sched = dict(schedule or {})
    if fomc_next:
        sched["fomc"] = [(fomc_next, SRC_FED)]
    for key, rows in sched.items():
        if key not in EVENTS:
            continue
        name, imp, hm, desc = EVENTS[key]
        if key == "fomc":
            desc = fomc_desc or desc
        if trig and trig.get(key):
            desc = trig[key] if key == "employment" else (desc + trig[key])
        for iso, src in rows:
            d = _iso(iso)
            if not d:
                continue
            tpe = taipei_time(d, hm)
            # 已經發布的不列（22:45 那次執行時，當晚 20:30 的 CPI 已經出來了）
            if tpe <= now or d > end_next:
                continue
            items.append({"key": key, "name": name, "impact": imp,
                          "date": d, "tpe": tpe, "src": src, "desc": desc,
                          "group": _group(d, mon), "week": (d - start).days // 7})
    items.sort(key=lambda x: (x["tpe"], x["impact"] != "high"))
    seen = set()
    for it in items:
        if it["key"] in seen:
            it["desc"] = ""
        seen.add(it["key"])
        tw = "台灣隔天 " if it["tpe"].date() > it["date"] else "台灣 "
        it["when"] = (f"{'今天 ' if it['date'] == today else ''}"
                      f"{tw}{it['tpe'].strftime('%H:%M')}")
        it["label"] = f"{it['date'].month:02d}/{it['date'].day:02d}（{_WD[it['date'].weekday()]}）"
    return items
