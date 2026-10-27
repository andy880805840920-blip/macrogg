"""
首頁「接下來看什麼」的三個篩選（第十八批）：數據／發債／官員談話，
以及數據列的「市場預估／前值」。

來源（全部免金鑰；任何一個失敗只少那一塊，不影響其他）：
  市場預估、前值   ForexFactory 週曆 JSON（nfs.faireconomy.media）——**非官方**，
                   只有本週（下週的大約週末前才出來）。改版或擋掉就安靜消失。
  公債標售         TreasuryDirect 已公告場次（約提前一週，有金額）＋財政部
                   「暫定標售時程表」PDF（整季，標「暫定」）。短期國庫券不列。
  國債回購         財政部「暫定回購時程表」PDF（整季）。
  官員談話         聯準會官網行事曆 JSON（主席、副主席、理事，排得最遠）＋
                   ForexFactory（也有各地區聯儲總裁，但只有本週）；同一場只留一筆。
                   票委名單寫在 config/focus.yaml 的 fomc_voters，每年一月更新。
時間一律是美東時間，畫面上換成台北時間（watch_calendar.taipei_time）。
"""
from __future__ import annotations

import datetime as dt
import html
import logging
import re

log = logging.getLogger(__name__)

FF_URLS = ("https://nfs.faireconomy.media/ff_calendar_thisweek.json",
           "https://nfs.faireconomy.media/ff_calendar_nextweek.json")
FED_CAL_URL = "https://www.federalreserve.gov/json/calendar.json"
TD_UPCOMING_URL = "https://www.treasurydirect.gov/TA_WS/securities/upcoming?format=json"
TENTATIVE_AUCTION_PDF = "https://home.treasury.gov/system/files/221/Tentative-Auction-Schedule.pdf"
TENTATIVE_BUYBACK_PDF = "https://home.treasury.gov/system/files/221/Tentative-Buyback-Schedule.pdf"
UA = {"User-Agent": "Mozilla/5.0 (macro-dashboard)"}

# ForexFactory 標題 → (本站事件 key, 中文標籤, 單位換算)
FF_MAP = {
    "Non-Farm Employment Change": ("employment", "非農新增", "k"),
    "Unemployment Rate": ("employment", "失業率", ""),
    "Average Hourly Earnings m/m": ("employment", "平均時薪月增", ""),
    "Core CPI m/m": ("cpi", "核心 CPI 月增", ""),
    "CPI m/m": ("cpi", "CPI 月增", ""),
    "Core CPI y/y": ("cpi", "核心 CPI 年增", ""),
    "CPI y/y": ("cpi", "CPI 年增", ""),
    "Core PCE Price Index m/m": ("pce", "核心 PCE 月增", ""),
    "Core PCE Price Index y/y": ("pce", "核心 PCE 年增", ""),
    "PCE Price Index m/m": ("pce", "PCE 月增", ""),
    "Core PPI m/m": ("ppi", "核心 PPI 月增", ""),
    "PPI m/m": ("ppi", "PPI 月增", ""),
    "Retail Sales m/m": ("retail", "零售銷售月增", ""),
    "Core Retail Sales m/m": ("retail", "核心零售月增", ""),
    "Unemployment Claims": ("claims", "初領失業金", "k"),
    "JOLTS Job Openings": ("jolts", "職缺數", "m"),
    "Advance GDP q/q": ("gdp", "GDP 季增年率", ""),
    "Prelim GDP q/q": ("gdp", "GDP 季增年率", ""),
    "Final GDP q/q": ("gdp", "GDP 季增年率", ""),
    "Prelim UoM Consumer Sentiment": ("umich", "消費者信心", ""),
    "Revised UoM Consumer Sentiment": ("umich", "消費者信心", ""),
    "Federal Funds Rate": ("fomc", "政策利率上限", ""),
}

# 官員中文名（姓氏）。沒列到的照英文顯示。
OFFICIAL_ZH = {
    "Warsh": "Warsh", "Jefferson": "傑佛遜", "Bowman": "鮑曼", "Waller": "沃勒",
    "Cook": "庫克", "Barr": "巴爾", "Miran": "米蘭", "Powell": "鮑爾",
    "Williams": "威廉斯", "Hammack": "哈瑪克", "Paulson": "保爾森", "Logan": "洛根",
    "Kashkari": "卡什卡利", "Barkin": "巴爾金", "Goolsbee": "古爾斯比", "Daly": "戴莉",
    "Musalem": "穆薩勒姆", "Schmid": "施密德", "Collins": "柯林斯", "Bostic": "博斯蒂克",
}
TOPIC_ZH = {"Economic Outlook": "經濟前景", "Monetary Policy": "貨幣政策",
            "U.S. Economy and Monetary Policy": "美國經濟與貨幣政策",
            "Economic Outlook and Monetary Policy": "經濟前景與貨幣政策",
            "Supervision and Regulation": "金融監理", "Financial Stability": "金融穩定",
            "AI": "人工智慧", "Payments": "支付", "Bank Regulation": "銀行監理",
            "Semiannual Monetary Policy Report to the Congress": "半年度貨幣政策國會報告"}
BANK_ZH = {"Williams": "紐約", "Hammack": "克里夫蘭", "Paulson": "費城", "Logan": "達拉斯",
           "Kashkari": "明尼亞波利斯", "Barkin": "里奇蒙", "Goolsbee": "芝加哥", "Daly": "舊金山",
           "Musalem": "聖路易", "Schmid": "堪薩斯城", "Collins": "波士頓", "Bostic": "亞特蘭大"}
ROLE_ZH = (("Vice Chair for Supervision", "監理副主席"), ("Vice Chair", "副主席"),
           ("Chairman", "主席"), ("Chair", "主席"), ("Governor", "理事"))


def _get_default(url, **kw):
    import requests
    return requests.get(url, headers=UA, timeout=20, **kw)


# ---------------------------------------------------------------------------
# ForexFactory：市場預估、前值、本週官員談話
# ---------------------------------------------------------------------------
def _ff_value(s: str, unit: str) -> str:
    s = (s or "").strip()
    if not s:
        return ""
    m = re.match(r"^(-?[\d.]+)([KMB%]?)$", s)
    if not m:
        return s
    v, suf = float(m.group(1)), m.group(2)
    if suf == "K" or (unit == "k" and suf == ""):
        return f"{v / 10:,.1f} 萬"
    if suf == "M":
        return f"{v * 100:,.0f} 萬"
    return s


_FF_MEMO: list = []


def fetch_ff(_get=None) -> list[dict]:
    """
    ForexFactory 本週＋下週的美國事件（下週還沒出來時只有本週）。
    同一次執行抓一次就好（PPI 模組與「接下來看什麼」都要用；那個端點會限流）。
    """
    if _get is None and _FF_MEMO:
        return list(_FF_MEMO[0])
    get = _get or _get_default
    out = []
    for url in FF_URLS:
        try:
            r = get(url)
            if getattr(r, "status_code", 200) != 200:
                continue
            for e in r.json() or []:
                if e.get("country") == "USD":
                    out.append(e)
        except Exception as e:                       # noqa: BLE001
            log.info("ForexFactory 週曆抓取失敗（%s）：%s", url.rsplit("/", 1)[-1], e)
    log.info("ForexFactory：美國事件 %d 筆", len(out))
    if _get is None and out:
        _FF_MEMO[:] = [list(out)]
    return out


def consensus_map(ff_events: list[dict]) -> dict:
    """{"key|YYYY-MM-DD"（美東日期）: [{label, forecast, previous}]}"""
    out: dict[str, list] = {}
    for e in ff_events or []:
        m = FF_MAP.get((e.get("title") or "").strip())
        if not m:
            continue
        key, label, unit = m
        d = str(e.get("date") or "")[:10]
        f, p = _ff_value(e.get("forecast"), unit), _ff_value(e.get("previous"), unit)
        if key == "employment" and label == "非農新增":
            f = _signed_wan(e.get("forecast"))
            p = _signed_wan(e.get("previous"))
        if not (f or p):
            continue
        row = {"label": label, "forecast": f, "previous": p}
        lst = out.setdefault(f"{key}|{d}", [])
        if all(x["label"] != label for x in lst):
            lst.append(row)
    return out


def _signed_wan(s) -> str:
    m = re.match(r"^(-?[\d.]+)K$", str(s or "").strip())
    if not m:
        return str(s or "").strip()
    return f"{float(m.group(1)) / 10:+,.1f} 萬"


_FF_SPEAK = re.compile(r"^(?:FOMC Member|Fed Chair(?:man)?|Fed Vice Chair(?: for Supervision)?|"
                       r"Fed Governor)\s+([A-Z][A-Za-z'\-]+)\s+(?:Speaks|Testifies)")


def ff_speeches(ff_events: list[dict]) -> list[dict]:
    out = []
    for e in ff_events or []:
        t = (e.get("title") or "").strip()
        m = _FF_SPEAK.match(t)
        if not m:
            continue
        try:
            at = dt.datetime.fromisoformat(str(e.get("date")))
        except (TypeError, ValueError):
            continue
        role = ("主席" if "Chair" in t and "Vice" not in t else
                "副主席" if "Vice Chair" in t else "理事" if "Governor" in t else "")
        out.append({"name": m.group(1), "role": role, "et": at.replace(tzinfo=None),
                    "et_date": at.date().isoformat(),
                    "kind": "作證" if "Testifies" in t else "談話",
                    "topic": "", "where": "", "src": "ForexFactory"})
    return out


# ---------------------------------------------------------------------------
# 聯準會官網行事曆：理事會成員的演講、對談、作證
# ---------------------------------------------------------------------------
_FED_TITLE = re.compile(r"^(Speech|Discussion|Testimony|Panel Discussion|Remarks)\s*-\s*(.+)$")


def _parse_fed_time(s: str):
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*([ap])\.?m\.?", (s or "").lower())
    if not m:
        return None
    h, mi = int(m.group(1)) % 12, int(m.group(2))
    if m.group(3) == "p":
        h += 12
    return h, mi


def fetch_fed_calendar(_get=None) -> list[dict]:
    get = _get or _get_default
    try:
        r = get(FED_CAL_URL)
        txt = r.content.decode("utf-8-sig") if hasattr(r, "content") else r.text
        import json
        events = (json.loads(txt) or {}).get("events") or []
    except Exception as e:                           # noqa: BLE001
        log.info("聯準會行事曆抓取失敗：%s", e)
        return []
    out = []
    for e in events:
        if e.get("type") not in ("Speeches", "Testimony"):
            continue
        m = _FED_TITLE.match((e.get("title") or "").strip())
        if not m:
            continue
        who = m.group(2).strip()
        role = next((zh for en, zh in ROLE_ZH if who.startswith(en)), "")
        name = who.split()[-1].rstrip(",") if who else ""
        hm = _parse_fed_time(e.get("time") or "")
        for dd in re.findall(r"\d{1,2}", str(e.get("days") or "")):
            try:
                d = dt.date.fromisoformat(f"{e.get('month')}-{int(dd):02d}")
            except (TypeError, ValueError):
                continue
            out.append({"name": name, "role": role,
                        "et": dt.datetime.combine(d, dt.time(*(hm or (12, 0)))),
                        "et_date": d.isoformat(), "time_known": hm is not None,
                        "kind": {"Speech": "演講", "Testimony": "國會作證"}.get(m.group(1), "對談"),
                        "topic": html.unescape(e.get("description") or "").strip()
                        .replace("To be announced.", "")[:60],
                        "where": html.unescape(e.get("location") or "").strip(),
                        "src": "聯準會官網"})
    return out


def merge_speeches(fed: list[dict], ff: list[dict], voters: dict | None,
                   board: list | None, today: dt.date, days: int = 35) -> list[dict]:
    """官網優先；ForexFactory 補地區聯儲總裁。同一人同一天只留一筆。"""
    seen, out = set(), []
    yr_voters = {str(k): set(v or []) for k, v in (voters or {}).items()}
    board_s = set(board or [])
    fed_days = {(x["name"], x["et_date"]) for x in fed}
    for x in list(fed) + list(ff):
        d = dt.date.fromisoformat(x["et_date"])
        if not (today <= d <= today + dt.timedelta(days=days)):
            continue
        # 官網的每一場都留（同一天可能有演講＋對談）；ForexFactory 只補官網沒有的人／日
        if x["src"] != "聯準會官網" and (x["name"], x["et_date"]) in fed_days:
            continue
        k = (x["name"], x["et"])
        if k in seen:
            continue
        seen.add(k)
        voter = x["name"] in board_s or x["name"] in yr_voters.get(str(d.year), set())
        role = x.get("role") or ("理事" if x["name"] in board_s else
                                 f"{BANK_ZH.get(x['name'], '')}聯儲總裁")
        _tp = x.get("topic") or ""
        # 官網的主題多半是短英文；翻不到又很長（整句活動說明）就不放
        if _tp not in TOPIC_ZH and len(_tp.split()) > 4:
            _tp = ""
        out.append({**x, "zh": OFFICIAL_ZH.get(x["name"], x["name"]), "role": role,
                    "topic": TOPIC_ZH.get(_tp, _tp),
                    "voter": voter})
    out.sort(key=lambda x: x["et"])
    return out


# ---------------------------------------------------------------------------
# 公債標售：已公告（TreasuryDirect）＋暫定時程表（PDF）
# ---------------------------------------------------------------------------
def _term_label(term: str, typ: str = "", reopen: bool = False) -> tuple[str, bool]:
    """「19-Year 10-Month」→（「20 年期」, 增發）；「5-Year」→（「5 年期」, False）。"""
    m = re.match(r"^\s*(\d+)-Year(?:\s+(\d+)-Month)?", term or "")
    if not m:
        return term, reopen
    y, mo = int(m.group(1)), int(m.group(2) or 0)
    if mo:
        y, reopen = y + 1, True
    return f"{y} 年期", reopen


def _auction_name(years: str, kind: str, reopen: bool) -> str:
    base = {"TIPS": f"{years} TIPS", "FRN": f"{years}浮動利率債"}.get(kind, f"{years}公債")
    return f"{base}標售" + ("（增發）" if reopen else "")


def fetch_td_upcoming(_get=None) -> list[dict]:
    get = _get or _get_default
    try:
        rows = get(TD_UPCOMING_URL).json() or []
    except Exception as e:                           # noqa: BLE001
        log.info("TreasuryDirect 已公告標售抓取失敗：%s", e)
        return []
    out = []
    for r in rows:
        if r.get("securityType") == "Bill":
            continue
        kind = ("TIPS" if r.get("tips") == "Yes" else
                "FRN" if r.get("floatingRate") == "Yes" else "")
        yrs, reopen = _term_label(r.get("securityTerm"), kind, r.get("reopening") == "Yes")
        amt = r.get("offeringAmount") or ""
        try:
            amt = f"{float(amt) / 1e8:,.0f} 億美元" if amt else ""
        except ValueError:
            amt = ""
        out.append({"date": str(r.get("auctionDate"))[:10], "years": yrs, "kind": kind,
                    "reopen": reopen, "amount": amt, "src": "財政部公告"})
    return out


_TAS_LINE = re.compile(r"^(\d+)-Year\s+(NOTE|BOND|TIPS|FRN)\s*(R?T?|T?R?)?\s+"
                       r"\w+day,\s+(\w+ \d{1,2}, \d{4})\s+\w+day,\s+(\w+ \d{1,2}, \d{4})")


def parse_tentative_auctions(text: str) -> list[dict]:
    out = []
    for ln in (text or "").splitlines():
        m = _TAS_LINE.match(ln.strip())
        if not m:
            continue
        flags = m.group(3) or ""
        try:
            d = dt.datetime.strptime(m.group(5), "%B %d, %Y").date()
        except ValueError:
            continue
        kind = {"TIPS": "TIPS", "FRN": "FRN"}.get(m.group(2), "")
        out.append({"date": d.isoformat(), "years": f"{int(m.group(1))} 年期", "kind": kind,
                    "reopen": "R" in flags, "amount": "", "src": "財政部暫定表"})
    return out


def _pdf_text(url: str, _get=None) -> str:
    get = _get or _get_default
    try:
        r = get(url)
        if getattr(r, "status_code", 200) != 200:
            return ""
        import io
        import pdfplumber
        with pdfplumber.open(io.BytesIO(r.content)) as p:
            return "\n".join((pg.extract_text() or "") for pg in p.pages)
    except Exception as e:                           # noqa: BLE001
        log.info("PDF 讀取失敗（%s）：%s", url.rsplit("/", 1)[-1], e)
        return ""


def merge_auctions(announced: list[dict], tentative: list[dict]) -> list[dict]:
    """同一天同期別以已公告為準（有金額）；暫定表補其餘。"""
    k = {(a["date"], a["years"], a["kind"]) for a in announced}
    out = list(announced) + [t for t in tentative if (t["date"], t["years"], t["kind"]) not in k]
    for a in out:
        a["name"] = _auction_name(a["years"], a["kind"], a["reopen"])
    return sorted(out, key=lambda a: a["date"])


# ---------------------------------------------------------------------------
# 國債回購：暫定時程表（PDF）
# ---------------------------------------------------------------------------
_BB = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}/\d{1,2}/\d{4})\*?\s+(\d{1,2}:\d{2})\s*([ap]m)\s*[–-]\s*"
                 r"(\d{1,2}:\d{2})\s*([ap]m)\s+(\d{1,2}/\d{1,2}/\d{4})\s+(Liquidity Support|Cash Management)"
                 r"\s+(TIPS\s+\S+\s+to\s+\S+\s+)?\$0\s+(?:=\s*or\s*>\s*)?\$([\d.]+)\s*(billion|million)")
_BB_RANGE = re.compile(r"^(\d+(?:Mo|Y))\s+to\s+(\d+Y)")


def parse_buybacks(text: str) -> list[dict]:
    lines = [x.strip() for x in (text or "").splitlines()]
    out = []
    for i, ln in enumerate(lines):
        m = _BB.search(ln)
        if not m:
            continue
        try:
            d = dt.datetime.strptime(m.group(2), "%m/%d/%Y").date()
        except ValueError:
            continue
        if m.group(9):
            seg = "TIPS " + m.group(9).strip().replace("TIPS", "").strip().replace(" to ", "–")
        else:
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            r = _BB_RANGE.match(nxt)
            seg = ("名目債 " + f"{r.group(1)}–{r.group(2)}") if r else "名目債"
        amt = float(m.group(10)) * (10 if m.group(11) == "billion" else 0.01)
        out.append({"date": d.isoformat(), "segment": seg.replace("Mo", "個月"),
                    "purpose": "流動性支援" if m.group(8).startswith("Liquidity") else "現金管理",
                    "max": f"最多 {amt:,.0f} 億美元" if amt >= 10 else f"最多 {amt:,.1f} 億美元",
                    "end": (int(m.group(5).split(":")[0]) % 12 + (12 if m.group(6) == "pm" else 0),
                            int(m.group(5).split(":")[1])),
                    "src": "財政部暫定表"})
    return out


# ---------------------------------------------------------------------------
def collect(cfg: dict | None, offline: bool = False, today: dt.date | None = None,
            _get=None) -> dict:
    """run.py 呼叫：回傳 {consensus, auctions, buybacks, speeches}，每塊獨立失敗。"""
    from .. import clock
    today = today or clock.today()
    if offline:
        return {}
    cfg = cfg or {}
    out: dict = {}
    ff = fetch_ff(_get)
    out["consensus"] = consensus_map(ff)
    try:
        out["auctions"] = merge_auctions(fetch_td_upcoming(_get),
                                         parse_tentative_auctions(_pdf_text(TENTATIVE_AUCTION_PDF, _get)))
    except Exception as e:                           # noqa: BLE001
        log.warning("公債標售時程組裝失敗：%s", e)
        out["auctions"] = []
    try:
        out["buybacks"] = parse_buybacks(_pdf_text(TENTATIVE_BUYBACK_PDF, _get))
    except Exception as e:                           # noqa: BLE001
        log.warning("國債回購時程組裝失敗：%s", e)
        out["buybacks"] = []
    try:
        out["speeches"] = merge_speeches(fetch_fed_calendar(_get), ff_speeches(ff),
                                         cfg.get("fomc_voters"), cfg.get("fomc_board"), today)
    except Exception as e:                           # noqa: BLE001
        log.warning("官員談話組裝失敗：%s", e)
        out["speeches"] = []
    log.info("接下來看什麼：市場預估 %d 組、標售 %d 場、回購 %d 場、官員談話 %d 場",
             len(out["consensus"]), len(out["auctions"]), len(out["buybacks"]),
             len(out["speeches"]))
    return out
