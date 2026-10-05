"""
聯準會頁的事實層（2026-10 改版）
================================

使用者的要求：聯準會頁不要自己發明分數。合成的「客觀訊號分數」
（政策行動 ±3、反對票 ±2、風險句 ±1）權重沒有外部依據，而且只看過去；
記者會與聲明的詞頻分數會把記者的提問、否定句一起算進去。三個分數全部
拿掉，改成這裡整理的**官方文件裡的事實**：

  決議        聲明本文：升／降／維持、幅度、新的目標區間
  投票        聲明引言的票數＋反對者名單與方向
  靜默期      聯準會的固定規則：會議開始前的第二個週六起，到會後隔天午夜
  SEP／點陣圖 官網「Projection Materials」網頁版的表 1 與圖 2
  會議紀要    官網 minutes 網頁；聯準會用固定的量詞（all／most／many／
              several／some／a few）描述有多少與會者持某個觀點
  委員名單    官網 FOMC 頁的「Committee Members／Alternate Members」
  官員發言    理事：官方演講 RSS；地方總裁：新聞標題（畫面標「依新聞」）
  行程        官網行事曆的資料檔（json/calendar.json）

這個模組只做**解析與整理**，不另外計分。唯一的「判斷」是政策方向的文字
標籤，規則寫死在 policy_direction()：先看政策行動，維持不變時看反對票
主張的方向——不加權、不出數字。
"""
from __future__ import annotations

import datetime as dt
import html as _html
import json
import logging
import re

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 決議：從聲明本文解析
# ---------------------------------------------------------------------------
_FRAC = {"1/8": 0.125, "1/4": 0.25, "3/8": 0.375, "1/2": 0.5,
         "5/8": 0.625, "3/4": 0.75, "7/8": 0.875}


def _num(s: str) -> float | None:
    """「3-3/4」→ 3.75、「4」→ 4.0、「1/4」→ 0.25。"""
    s = (s or "").strip()
    m = re.fullmatch(r"(\d+)(?:[-\s](\d/\d))?", s)
    if m:
        return int(m.group(1)) + _FRAC.get(m.group(2) or "", 0.0)
    if s in _FRAC:
        return _FRAC[s]
    return None


_RANGE_RE = re.compile(
    r"target range for the federal funds rate\s+"
    r"(?:by\s+(?:a\s+)?(?P<by>[\d/\-]+)\s+percentage point\s+|"
    r"by\s+(?P<bp>\d+)\s+basis points\s+)?"
    r"(?:to|at)\s+(?P<lo>[\d\-/]+)\s+to\s+(?P<hi>[\d\-/]+)\s+percent", re.I)
_ACT_RE = [
    ("hike", re.compile(r"decided to (?:raise|increase)\s+the target range", re.I)),
    ("cut", re.compile(r"decided to (?:lower|reduce|decrease)\s+the target range", re.I)),
    ("hold", re.compile(r"decided to (?:maintain|keep)\s+the target range", re.I)),
]


def parse_decision(text: str) -> dict:
    """
    回傳 {action, move_bp, lower, upper}；解析不到的欄位為 None。

    幅度優先讀「by 1/4 percentage point」；沒寫幅度但有新舊區間時，
    呼叫端可以用前後兩次的區間相減補上（見 decision_history）。
    """
    # 聲明裡的分數常用不斷行連字號（3‑1/2，U+2011）或其他破折號，先統一
    text = re.sub(r"[\u2010\u2011\u2012\u2013\u2014]", "-", text or "")
    text = re.sub(r"\s+", " ", text)
    act = next((n for n, p in _ACT_RE if p.search(text)), None)
    out = {"action": act, "move_bp": None, "lower": None, "upper": None}
    m = _RANGE_RE.search(text)
    if m:
        out["lower"], out["upper"] = _num(m.group("lo")), _num(m.group("hi"))
        if m.group("by"):
            v = _num(m.group("by"))
            out["move_bp"] = None if v is None else round(v * 100)
        elif m.group("bp"):
            out["move_bp"] = int(m.group("bp"))
    if act == "hold":
        out["move_bp"] = 0
    return out


_CN_N = {1: "一", 2: "兩", 3: "三", 4: "四"}


def move_label(action: str | None, move_bp: int | None) -> str:
    if action == "hold":
        return "維持不變"
    if action not in ("hike", "cut"):
        return "政策行動未辨識"
    word = "升息" if action == "hike" else "降息"
    if not move_bp:
        return word
    n = abs(int(move_bp)) // 25
    if n * 25 == abs(int(move_bp)) and n in _CN_N:
        return f"{word}{_CN_N[n]}碼"
    return f"{word} {abs(int(move_bp))} 個基點"


def range_text(lo, hi) -> str:
    if lo is None or hi is None:
        return "—"
    return f"{lo:.2f}–{hi:.2f}%"


def surname(name: str) -> str:
    """「Lorie K. Logan」→ Logan。只用來對照名單，不處理 Jr. 之類的後綴以外的情況。"""
    parts = [p for p in re.split(r"\s+", (name or "").strip()) if p]
    parts = [p for p in parts if p.rstrip(".,") not in ("Jr", "Sr", "II", "III")]
    return parts[-1].rstrip(".,") if parts else ""


# 反對的不是利率方向、而是其他事項（資產負債表、聲明措辭）
OTHER_DISSENT = {"balance_sheet": "反對資產負債表的做法",
                 "no_easing_bias": "反對聲明加入寬鬆傾向",
                 "unknown": "反對其他事項"}


def vote_summary(vote: dict) -> dict:
    """{n_for, n_against, hike, cut, hold, names: {hike:[...], ...}, text}"""
    vote = vote or {}
    ds = vote.get("dissents") or []
    names = {"hike": [], "cut": [], "hold": []}
    other: dict = {}
    for d in ds:
        k = d.get("direction")
        if k in names:
            names[k].append(surname(d.get("name", "")))
        else:
            other.setdefault(OTHER_DISSENT.get(k, OTHER_DISSENT["unknown"]), []).append(
                surname(d.get("name", "")))
    n_against = len(ds) or (vote.get("stated_dissent") or 0)
    n_for = vote.get("stated_support")
    if n_for is None:
        n_for = len(vote.get("supporting") or []) or None
    bits = []
    if names["hike"]:
        bits.append(f"{len(names['hike'])} 票主張升息（{'、'.join(names['hike'])}）")
    if names["cut"]:
        bits.append(f"{len(names['cut'])} 票主張降息（{'、'.join(names['cut'])}）")
    if names["hold"]:
        bits.append(f"{len(names['hold'])} 票主張維持（{'、'.join(names['hold'])}）")
    for lab, who in other.items():
        bits.append(f"{len(who)} 票{lab}（{'、'.join(who)}）")
    if not ds and vote.get("stated_dissent"):
        bits.append(f"{vote['stated_dissent']} 票反對（名單解析失敗）")
    head = f"{n_for}:{n_against}" if n_for is not None else (
        f"{n_against} 票反對" if n_against else "")
    tail = "，".join(bits) if bits else "全體一致"
    return {"n_for": n_for, "n_against": n_against,
            "hike": len(names["hike"]), "cut": len(names["cut"]),
            "hold": len(names["hold"]), "names": names,
            "text": f"{head}，{tail}" if head else tail,
            "short": ("全體一致" if not bits else
                      "、".join(b.split("（")[0] for b in bits))}


def policy_direction(decision: dict, vote: dict) -> tuple[str, str]:
    """
    政策方向的文字標籤（取代舊的合成分數）。規則只有兩層：

      1. 有升息／降息 → 方向就是那個動作
      2. 維持不變 → 看反對票主張的方向（主張升息的多＝偏升息，反之偏降息）
      3. 都沒有 → 中性

    回傳 (hawkish|dovish|neutral, 標籤)。標籤例：「升息一碼，全體一致」
    「維持不變，3 票主張升息」。不加權、不合成數字。
    """
    vs = vote_summary(vote)
    act = decision.get("action")
    label = move_label(act, decision.get("move_bp")) + "，" + vs["short"]
    if act == "hike":
        return "hawkish", label
    if act == "cut":
        return "dovish", label
    if vs["hike"] > vs["cut"]:
        return "hawkish", label
    if vs["cut"] > vs["hike"]:
        return "dovish", label
    return "neutral", label


DIR_ZH = {"hawkish": "偏升息", "dovish": "偏降息", "neutral": "中性"}


# ---------------------------------------------------------------------------
# 靜默期（blackout）
# ---------------------------------------------------------------------------
def blackout(first_day: dt.date, last_day: dt.date) -> tuple[dt.date, dt.date]:
    """
    聯準會的溝通靜默期：會議開始前的**第二個週六**零時起，到會議結束
    **隔天**午夜止（美東時間）。回傳 (第一天, 最後一天)。

    例：10/27–28 的會議 → 10/17（週六）到 10/29。
    """
    d = first_day - dt.timedelta(days=1)
    while d.weekday() != 5:                       # 往回找第一個週六
        d -= dt.timedelta(days=1)
    return d - dt.timedelta(days=7), last_day + dt.timedelta(days=1)


def next_meeting_info(spans: list, today: dt.date) -> dict:
    """spans＝[(first, last)]，回傳下次會議與靜默期的狀態。"""
    fut = [(a, b) for a, b in spans or [] if b >= today]
    if not fut:
        return {}
    a, b = fut[0]
    bo_s, bo_e = blackout(a, b)
    if today < bo_s:
        status, txt = "before", f"靜默期 {bo_s.month}/{bo_s.day} 起（{(bo_s - today).days} 天後）"
    elif today <= bo_e:
        status, txt = "in", f"靜默期中（至 {bo_e.month}/{bo_e.day}），官員不公開談政策"
    else:                                          # 不會發生：b >= today
        status, txt = "after", ""
    span = (f"{a.month}/{a.day}–{b.day}" if a.month == b.month
            else f"{a.month}/{a.day}–{b.month}/{b.day}")
    return {"first": a.isoformat(), "date": b.isoformat(), "span": span,
            "days": (b - today).days, "blackout_start": bo_s.isoformat(),
            "blackout_end": bo_e.isoformat(), "blackout_status": status,
            "blackout_text": txt,
            "later": [y.isoformat() for _, y in fut[1:4]]}


# ---------------------------------------------------------------------------
# HTML 小工具
# ---------------------------------------------------------------------------
def _clean(s: str) -> str:
    s = re.sub(r"<sup>.*?</sup>", "", s or "", flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    s = _html.unescape(s).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def _table_after(doc: str, marker: str) -> str:
    i = doc.find(marker)
    if i < 0:
        return ""
    j = doc.find("<table", i)
    k = doc.find("</table>", j)
    return doc[j:k] if j >= 0 and k > j else ""


def _rows(table: str) -> list[tuple[str, list[str]]]:
    out = []
    body = table.split("<tbody", 1)[-1]
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S):
        th = re.search(r"<th[^>]*>(.*?)</th>", tr, re.S)
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        out.append((_clean(th.group(1)) if th else "", [_clean(x) for x in tds]))
    return out


def _f(s: str) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# SEP 與點陣圖
# ---------------------------------------------------------------------------
SEP_VARS = [
    ("gdp", "實質 GDP 成長", re.compile(r"^change in real gdp", re.I)),
    ("unrate", "失業率", re.compile(r"^unemployment rate", re.I)),
    ("pce", "PCE 通膨", re.compile(r"^pce inflation", re.I)),
    ("core_pce", "核心 PCE 通膨", re.compile(r"^core pce inflation", re.I)),
    ("ffr", "聯邦資金利率", re.compile(r"^federal funds rate", re.I)),
]
SEP_LABEL = {k: zh for k, zh, _ in SEP_VARS}


def parse_sep(doc: str, date: str = "") -> dict | None:
    """
    解析 fomcprojtabl{YYYYMMDD}.htm 的表 1（中位數／中央趨勢／全距，含前一季）
    與圖 2（點陣圖：每個利率水準有幾位與會者）。結構不如預期回 None。
    """
    t1 = _table_after(doc, "Table 1.")
    if not t1:
        return None
    thead = t1.split("<tbody", 1)[0]
    years = [y for y in re.findall(r"<th[^>]*>\s*(\d{4}|Longer run)\s*</th>", thead)]
    n = len(years) // 3 if len(years) >= 9 else len(years)
    years = years[:n]
    if n < 3:
        return None
    vars_: dict = {}
    prev_label = ""
    last = None
    for stub, cells in _rows(t1):
        pm = re.match(r"^(\w+) projection", stub)
        if pm and last:
            prev_label = pm.group(1)
            vars_[last]["prev"] = [_f(c) for c in cells[:n]]
            continue
        key = next((k for k, _, rx in SEP_VARS if rx.search(stub)), None)
        if not key:
            last = None
            continue
        last = key
        vars_[key] = {"median": [_f(c) for c in cells[:n]],
                      "ct": cells[n:2 * n], "range": cells[2 * n:3 * n],
                      "prev": []}
    if "ffr" not in vars_ or "core_pce" not in vars_:
        return None

    dots = {"years": [], "rows": []}
    t2 = _table_after(doc, "Figure 2.")
    if t2:
        dy = re.findall(r"<th[^>]*>\s*(\d{4}|Longer run)\s*</th>",
                        t2.split("<tbody", 1)[0])
        for stub, cells in _rows(t2):
            lvl = _f(stub)
            if lvl is None:
                continue
            cnt = [int(c) if c.isdigit() else 0 for c in cells[:len(dy)]]
            dots["rows"].append((lvl, cnt))
        dots["years"] = dy
        # 合理性：每一年的總人數要落在 15–19（理事 7＋總裁 12，常有缺席）
        tot = [sum(r[1][i] for r in dots["rows"]) for i in range(len(dy))]
        if not dy or not all(10 <= x <= 19 for x in tot[:1]):
            log.warning("點陣圖人數不合理（%s），只用表 1", tot)
            dots = {"years": [], "rows": []}
        else:
            dots["n"] = tot
    return {"date": date, "years": years, "vars": vars_,
            "prev_label": prev_label, "dots": dots}


_MONTH_ZH = {"March": "3 月", "June": "6 月", "September": "9 月",
             "December": "12 月"}


def sep_prev_zh(sep: dict) -> str:
    return _MONTH_ZH.get(sep.get("prev_label", ""), sep.get("prev_label", "") or "上一季")


def dot_views(sep: dict, year_idx: int, mid: float) -> dict:
    """某一年的點陣圖相對現行利率中點：幾人預期更高／不變／更低，以中位數為準的碼數。"""
    rows = (sep.get("dots") or {}).get("rows") or []
    up = sum(c[year_idx] for lv, c in rows if lv > mid + 1e-6)
    same = sum(c[year_idx] for lv, c in rows if abs(lv - mid) < 1e-6)
    down = sum(c[year_idx] for lv, c in rows if lv < mid - 1e-6)
    med = ((sep.get("vars") or {}).get("ffr") or {}).get("median") or []
    m = med[year_idx] if year_idx < len(med) else None
    # 表 1 的中位數四捨五入到 0.1（4.125 → 4.1），算「差幾碼」要用點陣圖本身
    pts = sorted(lv for lv, c in rows for _ in range(c[year_idx] if year_idx < len(c) else 0))
    exact = None
    if pts:
        n = len(pts)
        exact = pts[n // 2] if n % 2 else (pts[n // 2 - 1] + pts[n // 2]) / 2
    return {"up": up, "same": same, "down": down, "median": m,
            "median_exact": exact if exact is not None else m}


# ---------------------------------------------------------------------------
# 會議紀要（minutes）
# ---------------------------------------------------------------------------
# 聯準會描述「有多少與會者」用的是一套固定量詞。順序很重要：
# 長的先比（almost all 要在 all 之前、a few 要在 few 之前）。
QUANTIFIERS = [
    (1, "幾乎全體", re.compile(r"\balmost all (?:of the )?(?:other )?participants\b", re.I)),
    (0, "全體", re.compile(r"\ball (?:of the )?participants\b", re.I)),
    (2, "多數", re.compile(r"\b(?:most|a (?:large |substantial |clear )?majority of)"
                          r" (?:the )?(?:other )?participants\b", re.I)),
    (3, "許多", re.compile(r"\bmany (?:other )?participants\b", re.I)),
    (4, "數位", re.compile(r"\b(?:several|various) (?:other )?participants\b", re.I)),
    (5, "部分", re.compile(r"\bsome (?:other )?participants\b", re.I)),
    (6, "少數", re.compile(r"\ba few (?:other )?participants\b", re.I)),
    (7, "兩位", re.compile(r"\b(?:a couple of|two) (?:other )?participants\b", re.I)),
    (8, "一位", re.compile(r"\bone participant\b", re.I)),
    # 沒有加量詞的「Participants ...」＝聯準會慣例上的全體或接近全體
    (0, "普遍", re.compile(r"^(?:participants|participants generally)\b"
                          r"|\bparticipants generally\b", re.I)),
]

MINUTES_TOPICS = [
    # 資產負債表排在政策路徑前面：「balance sheet policy」也含 policy
    ("資產負債表", ["balance sheet", "reserves"]),
    ("政策路徑", ["policy", "target range", "tightening", "firming", "easing",
              "rate increase", "rate cut", "restrictive", "accommodat"]),
    ("通膨", ["inflation", "price", "tariff"]),
    ("就業", ["labor market", "unemployment", "employment", "payroll", "wage",
            "hiring"]),
    ("金融情勢", ["financial stability", "financial conditions", "valuation",
              "leverage", "credit", "treasury market"]),
    ("經濟活動", ["activity", "gdp", "spending", "investment", "growth",
              "productivity"]),
]


def _sentences(text: str) -> list[str]:
    from .fomc_text import _sentences_of
    return _sentences_of(text, 0)


def parse_minutes(doc: str) -> dict | None:
    """
    只讀「Participants' Views on Current Conditions」到「Committee Policy
    Actions」之前——那是與會者討論的部分；前面是幕僚報告，後面是決議本身。
    回傳 {rows: [{topic, rank, level, text}], words}。
    """
    paras = [_clean(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", doc or "", re.S)]
    paras = [p for p in paras if len(p) > 40]
    if not paras:
        return None
    s = next((i for i, p in enumerate(paras)
              if re.match(r"Participants'?\s*[’']?\s*Views on Current Conditions", p)), None)
    e = next((i for i, p in enumerate(paras)
              if i > (s or 0) and p.startswith("Committee Policy Actions")), None)
    if s is None:
        return None
    seg = paras[s:e]
    seg[0] = re.sub(r"^Participants'?\s*[’']?\s*Views on Current Conditions and the "
                    r"Economic Outlook\s*", "", seg[0])
    rows = []
    for p in seg:
        for sent in _sentences(p):
            q = next(((r, zh) for r, zh, rx in QUANTIFIERS if rx.search(sent)), None)
            if not q:
                continue
            low = sent.lower()
            topic = next((t for t, kws in MINUTES_TOPICS
                          if any(k in low for k in kws)), "其他")
            rows.append({"topic": topic, "rank": q[0], "level": q[1],
                         "text": sent})
    return {"rows": rows, "words": sum(len(p.split()) for p in seg)} if rows else None


def minutes_by_topic(rows: list, per_topic: int = 3) -> list[tuple[str, list]]:
    """依主題分組，每組照量詞由大到小取前幾句。政策路徑排第一。"""
    # 「其他」不列：多半是程序性的句子（「與會者指出兩次會議間隔很短」）
    order = ["政策路徑", "通膨", "就業", "經濟活動", "金融情勢", "資產負債表"]
    out = []
    for t in order:
        rs = [r for r in rows if r["topic"] == t]
        if not rs:
            continue
        rs = sorted(rs, key=lambda r: r["rank"])[:per_topic]
        out.append((t, rs))
    return out


def minutes_index(calendar_html: str) -> list[dict]:
    """行事曆頁上所有已公布的會議紀要：[{meeting, released, url}]，新的在後。"""
    out = []
    for m in re.finditer(r"fomcminutes(\d{8})\.htm", calendar_html or ""):
        ymd = m.group(1)
        tail = calendar_html[m.end(): m.end() + 400]
        r = re.search(r"Released\s+([A-Z][a-z]+ \d{1,2}, \d{4})", tail)
        rel = ""
        if r:
            try:
                rel = dt.datetime.strptime(r.group(1), "%B %d, %Y").date().isoformat()
            except ValueError:
                rel = ""
        d = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"
        if all(x["meeting"] != d for x in out):
            out.append({"meeting": d, "released": rel,
                        "url": f"https://www.federalreserve.gov/monetarypolicy/fomcminutes{ymd}.htm"})
    return sorted(out, key=lambda x: x["meeting"])


def sep_index(calendar_html: str) -> list[str]:
    """行事曆頁上的 SEP 網頁版日期（YYYYMMDD），舊到新。"""
    return sorted(set(re.findall(r"fomcprojtabl(\d{8})\.htm", calendar_html or "")))


# ---------------------------------------------------------------------------
# 委員名單
# ---------------------------------------------------------------------------
CITY_ZH = {"Boston": "波士頓", "New York": "紐約", "Philadelphia": "費城",
           "Cleveland": "克里夫蘭", "Richmond": "里奇蒙", "Atlanta": "亞特蘭大",
           "Chicago": "芝加哥", "St. Louis": "聖路易", "Minneapolis": "明尼亞波利斯",
           "Kansas City": "堪薩斯城", "Dallas": "達拉斯", "San Francisco": "舊金山"}


def parse_roster(doc: str) -> dict | None:
    """官網 FOMC 頁：{year, members:[{name, affil, extra}], alternates:[...]}。"""
    def _items(block: str) -> list[dict]:
        out = []
        for li in re.findall(r"<li[^>]*>(.*?)</li>", block, re.S):
            txt = _clean(li)
            parts = [p.strip() for p in txt.split(",")]
            if len(parts) < 2:
                continue
            name, rest = parts[0], parts[1:]
            # 「First Vice President, New York」「Interim President, Atlanta」
            # 「New York, Vice Chair」「Board of Governors, Chairman」
            affil = next((p for p in rest if p == "Board of Governors" or p in CITY_ZH), rest[-1])
            extra = [p for p in rest if p != affil]
            out.append({"name": name, "affil": affil, "extra": ", ".join(extra)})
        return out

    m = re.search(r"(\d{4}) Committee Members\s*</h\d>(.*?)<h\d>\s*Alternate Members\s*</h\d>(.*?)</ul>",
                  doc or "", re.S)
    if not m:
        return None
    members, alts = _items(m.group(2)), _items(m.group(3))
    if not 10 <= len(members) <= 12:
        log.warning("FOMC 委員名單人數不合理（%d），略過", len(members))
        return None
    return {"year": int(m.group(1)), "members": members, "alternates": alts}


def parse_board_titles(doc: str) -> dict:
    """理事會頁：{姓: 'Chairman'|'Vice Chair'|'Vice Chair for Supervision'}。"""
    # 頁面下半是委員會分工表（「Governor Barr, Chair ...」），會撞名，只讀名單段
    txt = _clean(doc or "").split("Board of Governors Members")[0]
    out = {}
    for name, title in re.findall(
            r"([A-Z][A-Za-z.]+(?: [A-Z][A-Za-z.]+){1,3}),\s*"
            r"(Chairman|Vice Chair for Supervision|Vice Chair)\b", txt):
        out.setdefault(surname(name), title)
    return out


def official_title(m: dict, board_titles: dict) -> str:
    sn = surname(m["name"])
    if m["affil"] == "Board of Governors":
        t = board_titles.get(sn) or ("Chairman" if "Chair" in m.get("extra", "") else "")
        return {"Chairman": "主席", "Chair": "主席", "Vice Chair": "理事會副主席",
                "Vice Chair for Supervision": "監管副主席"}.get(t, "理事")
    city = CITY_ZH.get(m["affil"], m["affil"])
    extra = m.get("extra", "")
    if "First Vice President" in extra:
        return f"{city}聯儲第一副總裁"
    if "Interim" in extra:
        return f"{city}聯儲代理總裁"
    if "Vice Chair" in extra:
        return f"{city}聯儲總裁（FOMC 副主席）"
    return f"{city}聯儲總裁"


def dissent_record(docs: list, today: dt.date, months: int = 12) -> dict:
    """近 N 個月每位官員的反對票：{姓: {hike: n, cut: n, hold: n, dates: [...]}}。"""
    cut = today - dt.timedelta(days=int(months * 30.5))
    rec: dict = {}
    for d in docs:
        try:
            dd = dt.date.fromisoformat(getattr(d, "date", "") or d.get("date"))
        except (ValueError, TypeError, AttributeError):
            continue
        if dd < cut:
            continue
        vote = getattr(d, "vote", None) or (d.get("vote") if isinstance(d, dict) else {}) or {}
        for x in vote.get("dissents") or []:
            sn = surname(x.get("name", ""))
            r = rec.setdefault(sn, {"hike": 0, "cut": 0, "hold": 0, "other": {}, "dates": []})
            k = x.get("direction")
            if k in ("hike", "cut", "hold"):
                r[k] += 1
            else:
                lab = OTHER_DISSENT.get(k, OTHER_DISSENT["unknown"])
                r["other"][lab] = r["other"].get(lab, 0) + 1
            r["dates"].append(dd.isoformat())
    return rec


def vote_history(docs: list, sn: str, today: dt.date, months: int = 12,
                 roster_year: int | None = None, roster_voters: set | None = None) -> list[dict]:
    """
    近 N 個月每場會議這個人怎麼投：只用聲明投票段落裡**有名字**的事實。
      for      名字在「Voting for」名單
      against  名字在反對名單（附方向）
      none     兩邊都沒有＝那場沒有投票權（輪值、尚未就任）
    2026 年 6 月起的新版聲明只寫票數（「12:0」）不列贊成者姓名：
    票數加總剛好等於今年委員名單人數時，依名單推定贊成（inferred=True）。
    """
    roster_voters = roster_voters or set()
    cut = today - dt.timedelta(days=int(months * 30.5))
    out = []
    for d in docs:
        date = getattr(d, "date", "") or (d.get("date") if isinstance(d, dict) else "")
        try:
            dd = dt.date.fromisoformat(date)
        except (ValueError, TypeError):
            continue
        if dd < cut or dd > today:
            continue
        vote = getattr(d, "vote", None) or (d.get("vote") if isinstance(d, dict) else {}) or {}
        sup = {surname(x) for x in vote.get("supporting") or []}
        dis = {surname(x.get("name", "")): x.get("direction") for x in vote.get("dissents") or []}
        if sn in dis:
            k = dis[sn]
            out.append({"date": date, "v": "against", "dir": k,
                         "label": ({"hike": "主張升息", "cut": "主張降息", "hold": "主張維持"}.get(k)
                                   or OTHER_DISSENT.get(k, OTHER_DISSENT["unknown"]))})
        elif sn in sup:
            out.append({"date": date, "v": "for", "dir": "", "label": "贊成"})
        elif (not sup and dd.year == roster_year and sn in roster_voters
              and (vote.get("stated_support") or 0) + len(dis) == len(roster_voters)):
            out.append({"date": date, "v": "for", "dir": "", "label": "贊成",
                        "inferred": True})
        else:
            out.append({"date": date, "v": "none", "dir": "", "label": "未投票"})
    out.sort(key=lambda x: x["date"])
    return out


# 地方聯儲輪值：紐約每年投票，其餘 11 家分四組輪流（聯邦準備法第 12A 條）。
# 以 2025 年為基準：波士頓／芝加哥／聖路易／堪薩斯城。
_ROT = (("Boston", "Philadelphia", "Richmond"), ("Chicago", "Cleveland"),
        ("St. Louis", "Dallas", "Atlanta"), ("Kansas City", "Minneapolis", "San Francisco"))


def rotation(year: int) -> list[str]:
    """該年有投票權的地方聯儲（不含紐約）。"""
    return [g[(year - 2025) % len(g)] for g in _ROT]


def _dissent_tag(r: dict | None) -> tuple[str, str]:
    if not r:
        return "近 12 個月未投反對票", "neutral"
    bits = []
    if r.get("hike"):
        bits.append(f"{r['hike']} 次主張升息")
    if r.get("cut"):
        bits.append(f"{r['cut']} 次主張降息")
    if r.get("hold"):
        bits.append(f"{r['hold']} 次主張維持")
    for lab, n in (r.get("other") or {}).items():
        bits.append(f"{n} 次{lab}")
    lean = ("hawkish" if r.get("hike", 0) > r.get("cut", 0) else
            "dovish" if r.get("cut", 0) > r.get("hike", 0) else "neutral")
    return "近 12 個月反對：" + "、".join(bits), lean


def build_officials(roster: dict | None, board_titles: dict, docs: list,
                    today: dt.date, notes: dict | None = None) -> list[dict]:
    """
    依發言份量分層：
      1  主席
      2  FOMC 副主席（紐約聯儲總裁）與理事會副主席
      3  其他投票委員——近 12 個月沒投過反對票的人，是決定多數落在哪邊的關鍵
      4  候補委員（今年不投票，但參與討論、也交點陣圖）
    只標**已表態的事實**（反對票），不替任何人貼鷹鴿標籤。
    """
    if not roster:
        return []
    notes = notes or {}
    rec = dissent_record(docs, today)
    _rv = {surname(m["name"]) for m in roster["members"]}
    out = []
    for voter, group in ((True, roster["members"]), (False, roster["alternates"])):
        for m in group:
            sn = surname(m["name"])
            title = official_title(m, board_titles)
            if not voter:
                tier = 4
            elif title == "主席":
                tier = 1
            elif "副主席" in title and "監管" not in title:
                tier = 2
            else:
                tier = 3
            tag, lean = _dissent_tag(rec.get(sn))
            out.append({"name": m["name"], "surname": sn, "title": title,
                        "voter": voter, "tier": tier, "board": m["affil"] == "Board of Governors",
                        "affil": m["affil"], "city_zh": CITY_ZH.get(m["affil"], ""),
                        "dissent_tag": tag, "lean": lean,
                        "votes": vote_history(docs, sn, today, roster_year=roster.get("year"),
                                              roster_voters=_rv),
                        "note": notes.get(sn, "")})
    out.sort(key=lambda x: (x["tier"], 0 if x["lean"] != "neutral" else 1, x["surname"]))
    return out


# ---------------------------------------------------------------------------
# 官員發言與行程
# ---------------------------------------------------------------------------
def parse_speech_feed(xml: str) -> list[dict]:
    """官方演講 RSS：[{surname, title, date, url}]（只有理事）。"""
    out = []
    for it in re.findall(r"<item>(.*?)</item>", xml or "", re.S):
        def g(tag):
            m = re.search(rf"<{tag}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{tag}>", it, re.S)
            return _html.unescape(m.group(1).strip()) if m else ""
        title = g("title")
        if "," not in title:
            continue
        who, what = title.split(",", 1)
        try:
            date = dt.datetime.strptime(g("pubDate")[:16].strip(), "%a, %d %b %Y").date().isoformat()
        except ValueError:
            date = ""
        out.append({"surname": who.strip(), "title": what.strip(), "date": date,
                    "url": g("link"), "kind": g("category") or "Speech"})
    return out


def parse_calendar_json(raw: str) -> list[dict]:
    """官網行事曆資料檔：[{date, type, title, desc, time}]，展開多日事件。"""
    try:
        data = json.loads(raw.lstrip("﻿"))
    except (ValueError, AttributeError):
        return []
    out = []
    for e in (data.get("events") if isinstance(data, dict) else data) or []:
        mo = str(e.get("month") or "")
        if not re.fullmatch(r"\d{4}-\d{2}", mo):
            continue
        for day in re.findall(r"\d{1,2}", str(e.get("days") or "")):
            try:
                d = dt.date(int(mo[:4]), int(mo[5:7]), int(day))
            except ValueError:
                continue
            out.append({"date": d.isoformat(), "type": e.get("type") or "",
                        "title": re.sub(r"\s+", " ", e.get("title") or "").strip(),
                        "desc": re.sub(r"\s+", " ", e.get("description") or "").strip(),
                        "time": e.get("time") or ""})
    return out


def upcoming_events(events: list, today: dt.date, until: dt.date) -> list[dict]:
    """今天到 until（含）之間：官員演講／作證、會議紀要、褐皮書。"""
    keep = []
    for e in events:
        if not (today.isoformat() <= e["date"] <= until.isoformat()):
            continue
        t = e["title"]
        if e["type"] in ("Speeches", "Testimony"):
            kind = "作證" if e["type"] == "Testimony" else "演講"
            who = re.sub(r"^(?:Speech|Discussion|Testimony|Remarks)\s*-\s*", "", t)
            keep.append({"date": e["date"], "kind": kind, "who": who,
                         "topic": e["desc"], "time": e["time"]})
        elif t == "FOMC Minutes":
            keep.append({"date": e["date"], "kind": "會議紀要", "who": "",
                         "topic": "上次會議的紀要公布", "time": e["time"]})
        elif e["type"] == "Beige":
            keep.append({"date": e["date"], "kind": "褐皮書", "who": "",
                         "topic": "12 個地區的經濟現況報告", "time": e["time"]})
    keep.sort(key=lambda x: x["date"])
    return keep


_POLICY_WORDS = re.compile(
    r"\b(rate|rates|hike|hikes|hiking|cut|cuts|cutting|inflation|inflationary|monetary|"
    r"policy|tighten\w*|bps|basis points?|restrictive|neutral rate|labor market|jobs|"
    r"economy|economic outlook)\b", re.I)


_MAJOR = re.compile(r"reuters|bloomberg|wsj|wall street journal|financial times|"
                    r"barron|cnbc|marketwatch|associated press|\bap\b|yahoo finance|"
                    r"nikkei|axios|new york times|washington post", re.I)


def parse_news_rss(xml: str, sname: str, limit: int = 2) -> list[dict]:
    """Google News RSS：標題含姓氏者，優先談政策的標題。"""
    out = []
    for it in re.findall(r"<item>(.*?)</item>", xml or "", re.S):
        def g(tag):
            m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", it, re.S)
            return _html.unescape(m.group(1).strip()) if m else ""
        title = g("title")
        if not re.search(rf"\b{re.escape(sname)}\b", title):
            continue
        src = g("source")
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        try:
            date = dt.datetime.strptime(g("pubDate")[:16].strip(), "%a, %d %b %Y").date().isoformat()
        except ValueError:
            date = ""
        out.append({"title": title, "source": src, "date": date, "url": g("link"),
                    "policy": bool(_POLICY_WORDS.search(title))})
    # 新的在前，再把主要媒體、談政策的標題穩定排到前面
    out.sort(key=lambda x: x["date"], reverse=True)
    out.sort(key=lambda x: not _MAJOR.search(x["source"] or ""))
    out.sort(key=lambda x: not x["policy"])
    seen, res = set(), []
    for x in out:                                  # 同一天同來源只留一則
        k = (x["date"], x["source"])
        if k in seen:
            continue
        seen.add(k)
        res.append(x)
    return res[:limit]


# ---------------------------------------------------------------------------
# 市場路徑 vs 點陣圖
# ---------------------------------------------------------------------------
def market_vs_dots(fw: dict | None, sep: dict | None, mid: float | None) -> dict:
    """
    期貨推出的「今年最後一場會議後」隱含利率，對照點陣圖的今年底中位數。
    兩邊都是「今年底的政策利率中點」，比較基準一致。
    """
    if not fw or not sep or mid is None:
        return {}
    ms = fw.get("meetings") or [x for x in (fw.get("next"), fw.get("horizon")) if x]
    # next 與 horizon 可能是同一場
    seen, meets = set(), []
    for m in ms:
        if m and m["date"] not in seen:
            seen.add(m["date"])
            meets.append(m)
    if not meets:
        return {}
    last = meets[-1]
    yr = last["date"][:4]
    years = sep.get("years") or []
    if yr not in years:
        return {"meetings": meets, "r0": fw.get("r0")}
    _i = years.index(yr)
    med = dot_views(sep, _i, mid).get("median_exact") if (sep.get("dots") or {}).get("rows") \
        else (sep["vars"]["ffr"]["median"] or [None])[_i]
    if med is None:
        return {"meetings": meets, "r0": fw.get("r0")}
    gap_bp = (last["end"] - med) * 100
    if gap_bp <= -12.5:
        lean, txt = "dovish", f"市場押得比點陣圖低約 {abs(gap_bp) / 25:.1f} 碼——不完全相信還要再升"
    elif gap_bp >= 12.5:
        lean, txt = "hawkish", f"市場押得比點陣圖高約 {gap_bp / 25:.1f} 碼——預期升得比委員會說的還多"
    else:
        lean, txt = "neutral", "市場路徑與點陣圖大致一致"
    return {"meetings": meets, "year": yr, "market_end": last["end"],
            "dot_median": med, "gap_bp": gap_bp, "lean": lean, "text": txt,
            "dot_vs_now_bp": (med - mid) * 100, "r0": fw.get("r0"),
            "stale_from": fw.get("stale_from"), "asof": fw.get("date")}


# ---------------------------------------------------------------------------
# 「目前重心」的轉向條件
# ---------------------------------------------------------------------------
def shift_conditions(focus: dict, infl_verdict: dict | None, unrate: float | None,
                     sep: dict | None) -> list[dict]:
    """
    把「什麼情況會讓重心轉向」寫成可以逐月核對的條件。數字全部取自現成的
    判定（通膨頁的三分法、勞動頁的失業率、SEP 的年底預測），不另外算。
    """
    f = (focus or {}).get("focus")
    yrs = (sep or {}).get("years") or []
    vars_ = (sep or {}).get("vars") or {}
    u_proj = (vars_.get("unrate") or {}).get("median") or []
    c_proj = (vars_.get("core_pce") or {}).get("median") or []
    u_end = u_proj[0] if u_proj else None
    c_now = c_proj[0] if c_proj else None
    c_next = c_proj[1] if len(c_proj) > 1 else None
    yr0 = yrs[0] if yrs else ""
    yr1 = yrs[1] if len(yrs) > 1 else ""
    iv = (infl_verdict or {}).get("label")
    out = []
    if f in ("inflation", "unknown", "balanced", None):
        out.append({
            "need": "核心 PCE 連兩個月「穩定降溫」（通膨頁的三分法判定）",
            "now": f"目前：{iv}" if iv else "目前：無資料",
            "met": iv == "穩定降溫"})
        if u_end is not None:
            out.append({
                "need": f"失業率高於 SEP {yr0} 年底預測 {u_end:.1f}%",
                "now": f"目前：{unrate:.1f}%" if unrate is not None else "目前：無資料",
                "met": unrate is not None and unrate > u_end + 1e-9})
        if c_now is not None and c_next is not None:
            out.append({
                "need": f"SEP 核心 PCE 路徑下修（目前 {yr0} 年 {c_now:.1f}% → {yr1} 年 {c_next:.1f}%）",
                "now": "下一份 SEP 才會更新", "met": False})
    if f == "employment":
        out.append({"need": "通膨三分法轉為「明確升溫」",
                    "now": f"目前：{iv}" if iv else "目前：無資料",
                    "met": iv == "明確升溫"})
    return out


# ---------------------------------------------------------------------------
# AI 中文說明（聲明改動、會議紀要重點、官員新聞）
# ---------------------------------------------------------------------------
AI_PROMPT_VERSION = "fx1"
AI_SYSTEM = (
    "你是總經網站的編輯，讀者是台灣的學生與一般投資人。請把使用者提供的英文素材"
    "逐項寫成繁體中文（台灣用語）。只根據素材本身，不加入素材以外的事實或數字，"
    "不要推測市場反應。輸出 JSON，鍵與輸入相同，值是中文字串。")


def ai_payload(changed_rows: list, minutes_rows: list, officials: list) -> dict:
    p: dict = {}
    for i, r in enumerate(changed_rows or []):
        old, new = getattr(r, "old", "") or "", getattr(r, "new", "") or ""
        kind = getattr(r, "kind", "")
        p[f"d{i}"] = {"task": "用一句話（40 字內）說明這處聲明改動的意思",
                      "kind": {"changed": "改寫", "added": "新增", "removed": "刪除"}.get(kind, kind),
                      "old": old, "new": new}
    for i, r in enumerate(minutes_rows or []):
        p[f"m{i}"] = {"task": "翻成一句中文（50 字內），保留量詞的意思", "text": r["text"]}
    for o in officials or []:
        if o.get("news"):
            p[f"o_{o['surname']}"] = {
                "task": "根據這幾則新聞標題，用一句話（35 字內）說這位官員最近對利率的立場；"
                        "標題沒談利率就寫「近期標題未談利率」",
                "headlines": [n["title"] for n in o["news"]]}
    return p


def _digits(s: str) -> set:
    return set(re.findall(r"\d+(?:\.\d+)?", s or ""))


def _check(item: dict, out: str) -> bool:
    if not isinstance(out, str) or not out.strip():
        return False
    if len(out) > 80:
        return False
    src = json.dumps(item, ensure_ascii=False)
    # 數字鎖：中文裡出現的數字都要在原文找得到
    return _digits(out) <= _digits(src) | {"1", "2"}


def ai_notes(payload: dict, cache_path, offline: bool, call=None) -> dict:
    """
    一次呼叫產生全部中文說明。快取以素材雜湊為鍵：素材沒變就不重打。
    失敗（沒金鑰、限流、JSON 壞掉）一律回空 dict——畫面只顯示原文。
    """
    import hashlib
    from pathlib import Path
    if not payload:
        return {}
    key = hashlib.sha256((AI_PROMPT_VERSION + json.dumps(payload, sort_keys=True,
                                                         ensure_ascii=False)).encode()).hexdigest()
    cache = {}
    p = Path(cache_path) if cache_path else None
    if p and p.exists():
        try:
            cache = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            cache = {}
    if cache.get("key") == key:
        return cache.get("notes") or {}
    if offline:
        return {}
    if call is None:
        from .focus_today import _call_ai as call
    text, err = call(json.dumps(payload, ensure_ascii=False), AI_SYSTEM)
    if err or not text:
        log.warning("聯準會頁 AI 說明失敗（%s），只顯示原文", err or "空回應")
        return {}
    m = re.search(r"\{.*\}", text, re.S)
    try:
        raw = json.loads(m.group(0)) if m else {}
    except ValueError:
        raw = {}
    notes = {k: v.strip() for k, v in raw.items()
             if k in payload and _check(payload[k], v)}
    dropped = len(payload) - len(notes)
    if dropped:
        log.info("聯準會頁 AI 說明：%d 則未通過檢查，該項只顯示原文", dropped)
    if p:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"key": key, "notes": notes}, ensure_ascii=False,
                                    indent=1), encoding="utf-8")
        except OSError:
            pass
    return notes
