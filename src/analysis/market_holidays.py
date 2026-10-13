"""
首頁「接下來看什麼・休市」（2026-10）：美國、英國、台灣、中國、香港、日本、韓國
七個市場的休市與提早收盤，分股市（股）、債市（債）、匯市（匯，當地貨幣交割）。

資料來源：Python `holidays` 套件——各交易所自己的休市表（XNYS、XLON、XTAI、
XSHG、XHKG、XJPX、XKRX）與各國假日表，純本機計算、不連網。
套件沒有的部分用規則補，可再用 config/market_holidays.yaml 手動修正：

  美國  股＝紐約證交所；債＝SIFMA 建議（聯邦假日＋耶穌受難日；聯邦假日落在
        週六、於週五補假時照休，但元旦補到前一年 12/31 時只提早收盤）；
        匯＝美元交割（聯準會 Fedwire：假日落在週六時，週五照常營業）。
        提早收盤：股市 13:00（感恩節隔天、7/3、12/24）；債市 14:00（SIFMA：
        元旦、耶穌受難日、陣亡將士紀念日、獨立紀念日、聖誕節的前一個營業日，
        以及感恩節隔天）。
  台灣  股＝證交所；債、匯＝國定假日（春節前的「無交易日」只有股市不交易）。
  其他  股債匯都跟交易所休市表（中國的補班週末股市不開，但不是休市，不列）。
  英國、香港另有平安夜、除夕（香港還有農曆除夕）的半日市。

颱風等臨時休市無法事先排定，不列。
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
MARKETS = (("US", "美國"), ("GB", "英國"), ("TW", "台灣"), ("CN", "中國"),
           ("HK", "香港"), ("JP", "日本"), ("KR", "韓國"))
EXCH = {"US": "XNYS", "GB": "XLON", "TW": "XTAI", "CN": "XSHG",
        "HK": "XHKG", "JP": "XJPX", "KR": "XKRX"}
LANG = {"TW": "zh_TW", "CN": "zh_TW", "HK": "zh_HK"}
TZ = {"US": "America/New_York", "GB": "Europe/London", "HK": "Asia/Hong_Kong"}
TZ_ZH = {"US": "美東", "GB": "倫敦", "HK": "香港"}
ASSETS = ("eq", "bd", "fx")
ASSET_ZH = {"eq": "股市", "bd": "債市", "fx": "匯市"}

# 英文假日名 → 台灣常用譯名（美、英、日、韓）
NAME_ZH = {
    "New Year's Day": "元旦", "Martin Luther King Jr. Day": "金恩紀念日",
    "Washington's Birthday": "總統日", "Good Friday": "耶穌受難日", "Memorial Day": "陣亡將士紀念日",
    "Juneteenth National Independence Day": "六月節", "Independence Day": "獨立紀念日",
    "Labor Day": "勞動節", "Columbus Day": "哥倫布日", "Veterans Day": "退伍軍人節",
    "Thanksgiving Day": "感恩節", "Christmas Day": "聖誕節",
    "Boxing Day": "節禮日", "Easter Monday": "復活節星期一", "May Day": "五月銀行假日",
    "Spring Bank Holiday": "春季銀行假日", "Late Summer Bank Holiday": "夏末銀行假日",
    "Bank Holiday": "銀行休業日", "Coming of Age Day": "成人之日", "Foundation Day": "建國紀念日",
    "Emperor's Birthday": "天皇誕生日", "Vernal Equinox Day": "春分之日", "Showa Day": "昭和之日",
    "Constitution Day": "憲法紀念日", "Greenery Day": "綠之日", "Children's Day": "兒童節",
    "Marine Day": "海之日", "Mountain Day": "山之日", "Respect for the Aged Day": "敬老之日",
    "Autumnal Equinox Day": "秋分之日", "Sports Day": "體育之日", "Culture Day": "文化之日",
    "Labor Thanksgiving Day": "勤勞感謝之日", "Substitute Holiday": "補假", "National Holiday": "國民休日",
    "Korean New Year": "春節", "The day preceding Korean New Year": "春節前一天",
    "The second day of Korean New Year": "春節第二天", "Independence Movement Day": "三一節",
    "Buddha's Birthday": "佛誕日", "Chuseok": "中秋節", "The day preceding Chuseok": "中秋節前一天",
    "The second day of Chuseok": "中秋節第二天", "National Foundation Day": "開天節",
    "Hangul Day": "韓文日", "Local Election Day": "地方選舉日", "End of Year Holiday": "年末休市",
    "Liberation Day": "光復節",
}
# 韓國的 Constitution Day 是制憲節（日本的是憲法紀念日）
NAME_ZH_KR = {"Constitution Day": "制憲節", "Memorial Day": "顯忠日"}


def _zh(name: str, mk: str) -> str:
    out = []
    for part in str(name or "").split(";"):
        p = part.strip()
        if not p:
            continue
        obs = False
        m = re.match(r"Alternative holiday for (.+)", p)
        if m:
            p, obs = m.group(1), True
        if p.endswith("(observed)"):
            p, obs = p[:-len("(observed)")].strip(), True
        z = (NAME_ZH_KR.get(p) if mk == "KR" else None) or NAME_ZH.get(p, p)
        z = re.sub(r"放假日（[^）]*補班）", "調休放假", z)
        z = (z.replace("臺灣光復暨金門古寧頭大捷紀念日", "光復節").replace("中華民國開國紀念日", "元旦")
             .replace("（調整放假）", "（補假）").replace("一月一日", "元旦"))
        if mk == "JP" and p == "Bank Holiday":
            z = "年末年始休市"
        z = z.replace("無交易（僅辦理結算交割）", "無交易日（僅結算交割）")
        z = z + ("（補假）" if obs else "")
        if z not in out:
            out.append(z)
    if len(out) > 1 and "年末年始休市" in out:
        out.remove("年末年始休市")
    return "、".join(out)


def _years(a: dt.date, b: dt.date) -> list[int]:
    return list(range(a.year - 1, b.year + 2))


def _calendars(years: list[int]) -> dict:
    """{market: {asset: {date: 原文名稱}}}"""
    import holidays
    cal: dict = {}
    for mk, _ in MARKETS:
        lang = LANG.get(mk, "en_US")
        eq = dict(holidays.financial_holidays(EXCH[mk], years=years, language=lang))
        cal[mk] = {"eq": eq, "bd": eq, "fx": eq}
    tw = dict(holidays.country_holidays("TW", years=years, language="zh_TW"))
    cal["TW"]["bd"] = cal["TW"]["fx"] = tw
    # 美國：債＝聯邦假日＋耶穌受難日；元旦補到前一年 12/31 不休（只提早收盤）
    fed = dict(holidays.country_holidays("US", years=years, language="en_US"))
    bd = {d: n for d, n in fed.items()
          if not (d.month == 12 and d.day == 31 and "New Year" in n)}
    for d, n in cal["US"]["eq"].items():
        if "Good Friday" in n:
            bd[d] = n
    fx = {d: n for d, n in fed.items() if not (d.weekday() == 4 and "(observed)" in n)}
    cal["US"]["bd"], cal["US"]["fx"] = bd, fx
    return cal


def _open(cal_a: dict, d: dt.date) -> bool:
    return d.weekday() < 5 and d not in cal_a


def _prev_open(cal_a: dict, d: dt.date) -> dt.date:
    x = d - dt.timedelta(days=1)
    while not _open(cal_a, x):
        x -= dt.timedelta(days=1)
    return x


def _thanksgiving(y: int) -> dt.date:
    d = dt.date(y, 11, 1)
    d += dt.timedelta(days=(3 - d.weekday()) % 7)
    return d + dt.timedelta(days=21)


def _early(cal: dict, years: list[int]) -> dict:
    """{(market, date): {asset: "HH:MM"（當地）}}"""
    out: dict = {}

    def put(mk, a, d, hm):
        if _open(cal[mk][a], d):
            out.setdefault((mk, d), {})[a] = hm

    us_eq, us_bd = cal["US"]["eq"], cal["US"]["bd"]
    for y in years:
        tg = _thanksgiving(y)
        put("US", "eq", tg + dt.timedelta(days=1), "13:00")
        put("US", "eq", dt.date(y, 7, 3), "13:00")
        put("US", "eq", dt.date(y, 12, 24), "13:00")
        put("US", "bd", tg + dt.timedelta(days=1), "14:00")
        for g in (dt.date(y, 1, 1), dt.date(y + 1, 1, 1)):     # 元旦前一個營業日
            put("US", "bd", _prev_open(us_bd, g), "14:00")
        for d, n in us_bd.items():
            if d.year != y:
                continue
            if any(k in n for k in ("Good Friday", "Memorial Day", "Christmas Day")) or \
                    (n.startswith("Independence Day")):
                put("US", "bd", _prev_open(us_bd, d), "14:00")
        for mk, hm in (("GB", "12:30"), ("HK", "12:00")):
            for md in ((12, 24), (12, 31)):
                put(mk, "eq", dt.date(y, *md), hm)
        lny = sorted(d for d, n in cal["HK"]["eq"].items() if d.year == y and "年初一" in n)
        if lny:
            put("HK", "eq", lny[0] - dt.timedelta(days=1), "12:00")
    return out


def _early_name(mk: str, d: dt.date, cal: dict) -> str:
    """提早收盤那天的名稱：平安夜、感恩節隔天、○○前一天。"""
    if (d.month, d.day) == (12, 24):
        return "平安夜"
    if mk == "US" and d - dt.timedelta(days=1) == _thanksgiving(d.year):
        return "感恩節隔天"
    if mk == "HK" and (d + dt.timedelta(days=1)) in cal["HK"]["eq"] and \
            "年初一" in cal["HK"]["eq"][d + dt.timedelta(days=1)]:
        return "農曆除夕"
    for k in range(1, 6):                      # 下一個休市日的前一天
        x = d + dt.timedelta(days=k)
        n = cal[mk]["bd"].get(x) or cal[mk]["eq"].get(x)
        if n and x.weekday() < 5:
            return _zh(n, mk).replace("（補假）", "") + ("前一天" if k == 1 else "連假前")
        if x.weekday() < 5 and not n:
            break
    return "跨年前一天" if (d.month, d.day) == (12, 31) else "提早收盤"


def _tw_time(mk: str, d: dt.date, hm: str) -> str:
    from zoneinfo import ZoneInfo
    h, m = map(int, hm.split(":"))
    loc = dt.datetime(d.year, d.month, d.day, h, m, tzinfo=ZoneInfo(TZ[mk]))
    tw = loc.astimezone(ZoneInfo("Asia/Taipei"))
    return ("隔日 " if tw.date() > d else "") + tw.strftime("%H:%M")


def _note(mk: str, closed: set, early: dict) -> str:
    """對本站的影響（只有美國、台灣——網站的報價主要來自這兩地）。"""
    if mk == "US":
        if {"eq", "bd"} <= closed:
            return "美股、美債都休市，網站的收盤價與官方殖利率沿用前一日"
        if "bd" in closed:
            return "當天沒有官方殖利率，網站沿用前一日" + ("；美元不交割，匯市交易清淡" if "fx" in closed else "")
        if "eq" in closed:
            return "當天沒有美股收盤價，網站沿用前一日"
    if mk == "TW":
        if "eq" in closed and "fx" in closed:
            return "台股、台指期與台幣報價停在前一交易日"
        if "eq" in closed:
            return "台股、台指期報價停在前一交易日；台幣照常交易"
    return ""


def _load_overrides() -> list:
    try:
        import yaml
        p = ROOT / "config" / "market_holidays.yaml"
        if not p.exists():
            return []
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return [x for x in (data.get("overrides") or []) if isinstance(x, dict)]
    except Exception as e:                         # noqa: BLE001
        log.warning("休市：config/market_holidays.yaml 讀取失敗（%s），略過手動修正", e)
        return []


def market_events(start: dt.date, end: dt.date, overrides: list | None = None) -> list[dict]:
    """
    start～end（含）之間的休市與提早收盤。每筆：
      {date, mk, mk_zh, name, closed: [eq/bd/fx…], early: {asset: "HH:MM"},
       tw: "台灣時間（提早收盤最早的那個）", note}
    依日期、再依 MARKETS 順序排列。套件不可用時回 []。
    """
    try:
        years = _years(start, end)
        cal = _calendars(years)
        early_all = _early(cal, years)
    except Exception as e:                         # noqa: BLE001
        log.warning("休市：假日表無法計算（%s），本次不顯示", e)
        return []
    ov = overrides if overrides is not None else _load_overrides()
    by: dict = {}
    d = start
    while d <= end:
        if d.weekday() < 5:
            for mk, mz in MARKETS:
                closed = [a for a in ASSETS if d in cal[mk][a]]
                early = dict(early_all.get((mk, d)) or {})
                if not closed and not early:
                    continue
                raw = next((cal[mk][a][d] for a in ASSETS if d in cal[mk][a]), "")
                by[(mk, d)] = {"date": d, "mk": mk, "mk_zh": mz, "closed": closed, "early": early,
                               "name": _zh(raw, mk) if raw else "", "note": ""}
        d += dt.timedelta(days=1)
    # 手動修正：同一天同一市場的欄位覆蓋；remove: true 拿掉
    for o in ov:
        try:
            od = dt.date.fromisoformat(str(o.get("date"))[:10])
        except ValueError:
            continue
        mk = str(o.get("market") or "").upper()
        if not (start <= od <= end) or mk not in EXCH:
            continue
        if o.get("remove"):
            by.pop((mk, od), None)
            continue
        e = by.setdefault((mk, od), {"date": od, "mk": mk, "mk_zh": dict(MARKETS)[mk], "closed": [],
                                    "early": {}, "name": "", "note": ""})
        if "closed" in o:
            e["closed"] = [a for a in ASSETS if a in (o.get("closed") or [])]
        if "early" in o:
            e["early"] = {a: str(v) for a, v in (o.get("early") or {}).items() if a in ASSETS}
        for k in ("name", "note"):
            if o.get(k):
                e[k] = str(o[k])
    out = []
    for (mk, d), e in by.items():
        e["early"] = {a: hm for a, hm in e["early"].items() if a not in e["closed"]}
        if not e["closed"] and not e["early"]:
            continue
        if e["early"] and not e["name"]:
            e["name"] = _early_name(mk, d, cal)
        e["note"] = e["note"] or _note(mk, set(e["closed"]), e["early"])
        e["tw"] = ""
        if e["early"] and mk in TZ:
            a, hm = min(e["early"].items(), key=lambda x: x[1])
            e["tw"] = _tw_time(mk, d, hm)
        out.append(e)
    order = {m: i for i, (m, _) in enumerate(MARKETS)}
    return sorted(out, key=lambda e: (e["date"], order[e["mk"]]))


def status_text(e: dict) -> tuple[str, str]:
    """(標籤, 狀態說明)。標籤：全部休市／部分休市／提早收盤。"""
    closed, early = e["closed"], e["early"]
    tz = TZ_ZH.get(e["mk"], "當地")
    ea = "、".join(f"{ASSET_ZH[a]} {hm}" for a, hm in sorted(early.items(), key=lambda x: x[1]))
    if len(closed) == 3:
        return "全部休市", ""
    if closed:
        open_ = [ASSET_ZH[a] for a in ASSETS if a not in closed]
        s = "、".join(ASSET_ZH[a] for a in closed) + "休市・" + "、".join(open_) + "照常"
        if ea:
            s += f"（{ea} 提早收盤，{tz}）"
        return "部分休市", s
    tw = ("＝台灣\u00a0" + e["tw"].replace(" ", "\u00a0")) if e.get("tw") else ""
    return "提早收盤", f"{ea} 收盤（{tz}）{tw}"
