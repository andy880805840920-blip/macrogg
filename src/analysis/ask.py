"""
偷懶頁（/ask/）：把全站已經算好的數字，依 config/ask.yaml 的卡片清單組成「答案卡」。

不經 AI。每張卡＝標題、資料日期、一段解釋、圖（依頻率給期間）、小表、跳轉連結、
「這個指標怎麼看」教學（config/learn.yaml）。問句判讀在瀏覽器端
（src/pages/ask_match.js），這裡只負責：
  1. 每張卡的內容（fragment HTML，/ask/c/<id>.html，點到才載入）
  2. 給判讀器用的索引（卡片的詞、意圖、範例問句）

資料只讀 context 與序列，不另外抓網路；任何一張卡失敗只影響那一張
（顯示「本次沒有取得資料」），不擋整頁。
"""

from __future__ import annotations

import datetime as dt
import logging
import math
import re
import string
from pathlib import Path

import yaml

from .. import charts, clock

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
CATS = ("總覽", "指標報價", "聯準會", "就業", "通膨", "長端與債務", "情境", "名詞")

PAGE_NAMES = {"/": "總覽", "/labor/": "就業", "/inflation/": "通膨", "/fomc/": "聯準會",
              "/rates/": "長端與債務", "/scenario/": "情境合成"}
ANCHOR_NAMES = {
    "focus": "今日市場焦點", "election": "期中選舉", "hm-cat-data": "接下來看什麼・數據",
    "hm-cat-spk": "接下來看什麼・官員談話", "hm-cat-sup": "接下來看什麼・發債",
    "signals": "本期關鍵訊號", "kpi": "關鍵數字", "unrate": "失業率變動分解", "claims": "每週失業金申請",
    "industry": "行業別貢獻分解", "revision": "歷史數據修正", "sticky": "超級核心服務",
    "ppi": "生產者物價 PPI", "contrib": "分項貢獻分解", "trend": "通膨廣度", "passthrough": "薪資到服務業通膨",
    "consumption": "實質消費力道", "energy": "能源價格與傳導", "next": "下次會議與靜默期",
    "people": "投票委員與官員", "sep": "點陣圖與經濟預測", "market": "市場路徑 vs 點陣圖", "diff": "聲明逐句比對",
    "minutes": "會議紀要", "presser": "記者會", "decomp": "長端利率的組成", "hyperscalers": "科技巨頭",
    "curve": "殖利率曲線", "global": "全球長端", "supply": "債券供給", "auctions": "Coupon 拍賣結果",
    "demand": "信用利差", "debt": "政府財政", "grid": "九宮格定位", "triggers": "情境轉換門檻",
    "positioning": "固定收益對照",
}
# fomc 頁的 #trend 是「歷次決議」，跟通膨頁同名錨點不同義
_ANCHOR_BY_PAGE = {("/fomc/", "trend"): "歷次決議", ("/fomc/", "focus"): "目前重心與轉向條件",
                   ("/scenario/", "market"): "市場定價：期貨路徑與點陣圖"}

# 圖表期間（依資料頻率）：日 1 年、週 6 個月、月 2 年、季 3 年；「長期」一律 5 年
WINDOW_MONTHS = {"d": 12, "w": 6, "m": 24, "q": 36}
LONG_MONTHS = 60


def load_config(root: Path = ROOT) -> tuple[dict, dict]:
    cfg = yaml.safe_load((root / "config" / "ask.yaml").read_text(encoding="utf-8")) or {}
    learn = yaml.safe_load((root / "config" / "learn.yaml").read_text(encoding="utf-8")) or {}
    return cfg, learn


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def esc(s) -> str:
    import html
    return html.escape(str(s), quote=True)


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def fnum(v, dg: int = 1, sign: bool = False) -> str:
    v = _num(v)
    if v is None:
        return "—"
    s = f"{v:+,.{dg}f}" if sign else f"{v:,.{dg}f}"
    return "0" if s in ("+0", "-0") else s.replace("-0.0", "0.0") if re.fullmatch(r"[+-]0\.0+", s) else s


def _get(obj, path: str):
    """'labor.kpi.u3_plain' → ctxs['labor']['kpi']['u3_plain']（屬性也可）。"""
    cur = obj
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, (list, tuple)) and part.isdigit():
            i = int(part)
            cur = cur[i] if i < len(cur) else None
        else:
            cur = getattr(cur, part, None)
    return cur


def rows_of(series: dict, sid: str) -> list[dict]:
    out = []
    for r in (series or {}).get(sid) or []:
        v = _num(r.get("value"))
        if v is not None and r.get("date"):
            out.append({"date": str(r["date"])[:10], "value": v})
    out.sort(key=lambda r: r["date"])
    return out


def freq_of(rows: list[dict]) -> str:
    if len(rows) < 3:
        return "m"
    ds = [dt.date.fromisoformat(r["date"]) for r in rows[-12:]]
    gaps = sorted((b - a).days for a, b in zip(ds, ds[1:]))
    g = gaps[len(gaps) // 2]
    return "d" if g <= 4 else "w" if g <= 9 else "m" if g <= 45 else "q"


def _back(rows: list[dict], i: int, months: int) -> dict | None:
    """rows[i] 往回 months 個月的那一筆（同月）。"""
    d = dt.date.fromisoformat(rows[i]["date"])
    y, m = d.year, d.month - months
    while m <= 0:
        y, m = y - 1, m + 12
    key = f"{y:04d}-{m:02d}"
    for j in range(i, -1, -1):
        if rows[j]["date"][:7] == key:
            return rows[j]
        if rows[j]["date"][:7] < key:
            return None
    return None


def transform(rows: list[dict], tf: str, sc: float = 1.0) -> list[dict]:
    """lv 水準、d 差分、yoy 年增 %、mom 月增 %、a3 三個月年化 %。"""
    out = []
    f = freq_of(rows)
    for i, r in enumerate(rows):
        v = None
        if tf == "lv":
            v = r["value"]
        elif tf == "d":
            if i:
                v = r["value"] - rows[i - 1]["value"]
        elif tf in ("yoy", "mom", "a3"):
            if f in ("m", "q"):
                b = _back(rows, i, {"yoy": 12, "mom": 1, "a3": 3}[tf])
            else:
                b = None
                if tf == "yoy":
                    target = (dt.date.fromisoformat(r["date"]) - dt.timedelta(days=365)).isoformat()
                    b = next((x for x in reversed(rows[:i]) if x["date"] <= target), None)
            if b and b["value"]:
                ratio = r["value"] / b["value"]
                v = (ratio ** 4 - 1) * 100 if tf == "a3" else (ratio - 1) * 100
        if v is not None:
            out.append({"date": r["date"], "value": v * sc})
    return out


def period_label(date: str, f: str) -> str:
    try:
        d = dt.date.fromisoformat(date[:10])
    except ValueError:
        return date
    if f == "m":
        return f"{d.year} 年 {d.month} 月"
    if f == "q":
        return f"{d.year} Q{(d.month - 1) // 3 + 1}"
    if f == "w":
        return f"{d.month}/{d.day} 當週"
    return f"{d.month}/{d.day}"


def _ago(rows: list[dict], months: int) -> dict | None:
    if not rows:
        return None
    end = dt.date.fromisoformat(rows[-1]["date"])
    target = (end - dt.timedelta(days=int(months * 30.44))).isoformat()
    return next((r for r in reversed(rows) if r["date"] <= target), None)


def thin(points: list[dict], months: int) -> list[dict]:
    """
    答案卡的圖要小（每張卡是一個獨立小檔）：視窗內點太密就抽樣。
    日資料看一年以內全留；看兩年改週末值；更長改月底值。週資料超過兩年改月底值。
    """
    pts = charts.last_months(points, months)
    if len(pts) < 3:
        return pts
    f = freq_of(pts)
    key = None
    if f == "d" and months > 24 or f == "w" and months > 24:
        key = lambda d: d[:7]                                      # noqa: E731
    elif f == "d" and months > 12:
        key = lambda d: dt.date.fromisoformat(d).isocalendar()[:2]  # noqa: E731
    if key is None:
        return pts
    out = []
    for p in pts:
        if out and key(out[-1]["date"]) == key(p["date"]):
            out[-1] = p
        else:
            out.append(p)
    return out


def chart(lines: list[dict], unit: str, f: str, dg: int = 1, long: bool = False,
          refs=(), zero: bool = False, aria: str = "") -> str:
    months = LONG_MONTHS if long else WINDOW_MONTHS.get(f, 24)
    ser = [{"label": ln["label"], "color": ln.get("color") or f"var(--series-{i + 1})",
            "points": thin(ln["points"], months)} for i, ln in enumerate(lines) if ln.get("points")]
    if not ser:
        return ""
    try:
        return charts.compact_lines(ser, unit=unit, digits=dg, months=months, refs=list(refs),
                                    zero=zero, aria=aria or ser[0]["label"],
                                    show_legend=len(ser) > 1)
    except Exception as e:                       # noqa: BLE001
        log.warning("偷懶頁圖表失敗（%s）：%s", aria, e)
        return ""


def _chg_unit(u: str) -> str:
    return " 個百分點" if u == "%" else (" " + u if u else "")


# ---------------------------------------------------------------------------
# 卡片內容
# ---------------------------------------------------------------------------
class Out(dict):
    """一張卡的內容：ans（HTML 段落）、date、chart、chart_long、table、note。"""


STALE_DAYS = {"d": 7, "w": 21, "m": 105, "q": 240}


def stale_note(date: str, f: str) -> str:
    """資料日期太舊時給一句（例如流動性序列卡在兩個月前）；不舊就回空字串。"""
    try:
        d = dt.date.fromisoformat(str(date)[:10])
    except (TypeError, ValueError):
        return ""
    if (clock.today() - d).days > STALE_DAYS.get(f, 100):
        return f"（資料停在 {d.month}/{d.day}，來源尚未更新）" if f in ("d", "w") else \
               f"（資料停在 {period_label(d.isoformat(), f)}，來源尚未更新）"
    return ""


def chg_text(d, dg: int, unit: str) -> str:
    """變動量：四捨五入後是 0 就寫「持平」；數字與單位之間空一格。"""
    d = _num(d)
    if d is None:
        return "—"
    if round(d, dg) == 0:
        return "持平"
    u = "%" if unit == "%" else unit
    return fnum(d, dg, sign=True) + (" 個百分點" if unit == "%" else (" " + u if u else ""))


def _ytd_base(pts: list[dict]) -> dict | None:
    """去年最後一筆（年初以來的基準）。"""
    if not pts:
        return None
    y = pts[-1]["date"][:4]
    return next((r for r in reversed(pts) if r["date"][:4] < y), None)


def series_card(card: dict, S: dict, C: dict) -> Out | None:
    sp = card["src"]
    raw = rows_of(S, sp["s"])
    if not raw:
        return None
    f = freq_of(raw)
    tf, u, dg, sc = sp.get("tf", "lv"), sp.get("u", ""), int(sp.get("dg", 1)), float(sp.get("sc", 1))
    pts = transform(raw, tf, sc)
    if not pts:
        return None
    lab = sp.get("lab") or card["q"]
    last, prev = pts[-1], (pts[-2] if len(pts) > 1 else None)
    yago = _ago(pts, 12)
    tri = _ago(pts, 3)
    signed = tf in ("d",)
    ud = "%" if u == "%" else (" " + u if u else "")
    v = fnum(last["value"], dg, sign=signed) + ud
    per = period_label(last["date"], f)
    stale = stale_note(last["date"], f)
    word = "上月" if f == "m" else "上季" if f == "q" else "上週" if f == "w" else "前一日"
    parts = [f"{esc(lab)}最新為 <b>{esc(v)}</b>（{esc(per)}）{esc(stale)}"]
    if prev:
        if tf == "d":
            parts.append(f"{word}為 {esc(fnum(prev['value'], dg, sign=True) + ud)}")
        else:
            parts.append(f"較{word} {esc(chg_text(last['value'] - prev['value'], dg, u))}")
    if yago and tf != "d":
        parts.append(f"一年前為 {esc(fnum(yago['value'], dg) + ud)}")
    ans = "，".join(parts) + "。"
    # 依問法補一句（頁面判讀到對應意圖／期間時才顯示）
    extra = []
    if tf == "d":
        if tri:
            n3 = [r["value"] for r in pts if r["date"] > tri["date"]]
            if n3:
                extra.append(("int", "變化", f"近三期平均 {fnum(sum(n3) / len(n3), dg, sign=True)}{ud}"
                              + (f"、一年前同期 {fnum(yago['value'], dg, sign=True)}{ud}" if yago else "") + "。"))
        ys = [r["value"] for r in pts if r["date"][:4] == last["date"][:4]]
        if ys:
            extra.append(("per", "y", f"今年以來累計 {fnum(sum(ys), dg, sign=True)}{ud}。"))
    else:
        ch3 = chg_text(last["value"] - tri["value"], dg, u) if tri else ""
        ch12 = chg_text(last["value"] - yago["value"], dg, u) if yago else ""
        if ch3 or ch12:
            extra.append(("int", "變化", "比三個月前 " + (ch3 or "—") + "、比一年前 " + (ch12 or "—") + "。"))
        if tf == "lv":
            yb = _ytd_base(pts)
            if yb:
                extra.append(("per", "y", f"年初以來 {chg_text(last['value'] - yb['value'], dg, u)}（去年底 {fnum(yb['value'], dg)}{ud}）。"))
    for kind, key, txt in extra:
        attr = "data-int" if kind == "int" else "data-per"
        ans += f' <span class="ask-x" {attr}="{key}" hidden>{esc(txt)}</span>'
    say = card.get("say")
    if say:
        t = _fill_ctx(say, C)
        if t:
            ans += " " + esc(t)
    lines = [{"label": lab, "points": pts}]
    if sp.get("s2"):
        r2 = transform(rows_of(S, sp["s2"]), tf, sc)
        if r2:
            lines.append({"label": sp.get("lab2") or sp["s2"], "points": r2})
    unit_c = u if u == "%" else ""
    ch = chart(lines, unit_c, f, dg, zero=(tf == "d"), aria=lab)
    chl = chart(lines, unit_c, f, dg, long=True, zero=(tf == "d"), aria=lab + "（五年）")

    def cell(r):
        return fnum(r["value"], dg, sign=signed) if r else "—"
    head = ["", "最新", "上期", "三個月前", "一年前"]
    row = [lab + (f"（{u}）" if u and u != "%" else ""), cell(last), cell(prev), cell(tri), cell(yago)]
    if tf == "lv":
        yb = _ytd_base(pts)
        head.append("去年底")
        row.append(cell(yb))
    return Out(ans=ans, date=per, chart=ch, chart_long=chl, table=(head, [row]), freq=f, stale=bool(stale))


def _fill_ctx(tpl: str, C: dict) -> str:
    def rep(m):
        v = _get(C, m.group(1))
        return "" if v is None else str(v)
    out = re.sub(r"\{ctx:([\w.]+)\}", rep, tpl).strip()
    return re.sub(r"\*\*", "", out)


def _chip(C: dict, cid: str) -> dict | None:
    for ch in ((C.get("_focus") or {}).get("chips") or []):
        if ch.get("id") == cid:
            return ch
    return None


def _chip_fmt(ch: dict, v) -> str:
    k = ch.get("k") or ""
    v = _num(v)
    if v is None:
        return "—"
    if k in ("bp", "pct"):
        return f"{v:.2f}%"
    if k == "bp0":
        return f"{v:+.0f} bp"
    m = re.match(r"a(\d)", k)
    dg = int(m.group(1)) if m else (3 if k == "twd" else 2)
    return f"{v:,.{dg}f}" + (ch.get("u") or "")


def _chip_delta(ch: dict, base) -> str:
    """報價的變動：殖利率用 bp、其餘用原單位＋百分比；四捨五入後是 0 寫「持平」。"""
    v, b = _num(ch.get("num")), _num(base)
    if v is None or b is None:
        return "—"
    k = ch.get("k") or ""
    if k == "bp":
        d = (v - b) * 100
        return "持平" if round(d) == 0 else f"{d:+.0f} bp"
    if k == "bp0":
        d = v - b
        return "持平" if round(d) == 0 else f"{d:+.0f} bp"
    d = v - b
    m = re.match(r"a(\d)", k)
    dg = int(m.group(1)) if m else (3 if k == "twd" else 2)
    pct = (v / b - 1) * 100 if (ch.get("pc") and b) else None
    if round(d, dg) == 0 and (pct is None or round(pct, 2) == 0):
        return "持平"
    s = f"{d:+,.{dg}f}" + (ch.get("u") or "")
    if pct is not None:
        s += f"（{pct:+.2f}%）"
    return s


def chip_card(card: dict, S: dict, C: dict) -> Out | None:
    sp = card["src"]
    ch = _chip(C, sp["chip"])
    if not ch:
        return None
    lab = ch.get("label") or card["q"]
    date = ch.get("iso") or ""
    stale = stale_note(date, "d")
    if not ch.get("num") and ch.get("num") != 0:
        # 台指期、SRF 這類只有文字的報價
        if "失敗" in str(ch.get("value")) + str(ch.get("delta")) or str(ch.get("value")).startswith("—"):
            return None
        ans = (f"{esc(lab)}：<b>{esc(ch.get('value'))}</b>" + (f"，{esc(ch.get('delta'))}" if ch.get("delta") else "")
               + f"。{esc(stale)}")
        return Out(ans=ans, date=_dlabel(date, ch.get("date")), chart="", chart_long="", table=None, freq="d")
    d1 = _chip_delta(ch, ch.get("pv"))
    mtd = _chip_delta(ch, ch.get("bm"))
    ytd = _chip_delta(ch, ch.get("by"))
    bits = []
    if d1 != "—":
        bits.append(f"日變動 <span data-per=\"d\">{esc(d1)}</span>")
    if mtd != "—":
        bits.append(f"月初至今 <span data-per=\"m\">{esc(mtd)}</span>")
    if ytd != "—":
        bits.append(f"年初至今 <span data-per=\"y\">{esc(ytd)}</span>")
    ans = (f"{esc(lab)} <b>{esc(_chip_fmt(ch, ch.get('num')))}</b>（{esc(_dlabel(date, ch.get('date')))}）{esc(stale)}。"
           + "；".join(bits) + ("。" if bits else ""))
    rows = [["最新", _chip_fmt(ch, ch.get("num")), ""]]
    if ch.get("pv") is not None:
        rows.append(["前一日", _chip_fmt(ch, ch.get("pv")), d1])
    if ch.get("bm") is not None:
        rows.append([f"上月底（{(ch.get('bmd') or '')[5:]}）", _chip_fmt(ch, ch.get("bm")), mtd])
    if ch.get("by") is not None:
        rows.append([f"去年底（{(ch.get('byd') or '')[:4]}）", _chip_fmt(ch, ch.get("by")), ytd])
    table = (["", "數值", "與最新相比"], rows)
    ch_html = chl = ""
    if sp.get("s"):
        pts = rows_of(S, sp["s"])
        if pts:
            u = "%" if (ch.get("k") == "bp") else ""
            ch_html = chart([{"label": lab, "points": pts}], u, freq_of(pts), 2, aria=lab)
            chl = chart([{"label": lab, "points": pts}], u, freq_of(pts), 2, long=True, aria=lab + "（五年）")
    src = ch.get("source")
    return Out(ans=ans, date=_dlabel(date, ch.get("date")), chart=ch_html, chart_long=chl, table=table,
               freq="d", note=f"報價來源：{src}" if src else "")


def _dlabel(iso: str, short: str | None = None) -> str:
    try:
        d = dt.date.fromisoformat(iso[:10])
        return f"{d.month}/{d.day}" + (f"（{short.split(' ')[0]}）" if short and not short[:1].isdigit() else "")
    except (ValueError, TypeError):
        return short or ""


# ---------------------------------------------------------------------------
# 自訂卡（src: {fn: ...}）
# ---------------------------------------------------------------------------
FNS: dict = {}


def fn(name):
    def deco(f):
        FNS[name] = f
        return f
    return deco


def _p(*sentences) -> str:
    return "".join(s for s in sentences if s)


def _b(x) -> str:
    return f"<b>{esc(x)}</b>"


@fn("focus_today")
def _focus_today(card, S, C):
    fo = C.get("_focus") or {}
    txt = fo.get("text") or ""
    if not txt:
        return None
    on = [c for c in fo.get("chips") or [] if c.get("on") and c.get("value")]
    rows = [[c.get("label"), c.get("value"), c.get("delta") or ""] for c in on[:8]]
    return Out(ans=esc(txt), date=_dlabel(fo.get("generated") or fo.get("asof") or ""),
               table=(["", "最新", "變動"], rows) if rows else None)


@fn("brief")
def _brief(card, S, C):
    b = C.get("_brief") or {}
    txt = (b.get("text") or "").strip()
    if not txt:
        return None
    paras = [p.strip() for p in txt.split("\n") if p.strip()]
    # 第一段是「本次更新」的清單，偷懶頁直接給結論段
    body = paras[1:] or paras
    return Out(ans="<br>".join(esc(p) for p in body[:3]), date=(C.get("labor") or {}).get("generated_at", "")[:10])


@fn("changes")
def _changes(card, S, C):
    ch = C.get("changes")
    if not ch or not getattr(ch, "has_previous", False):
        return None
    rows = [[f.get("module", ""), f.get("title", ""), {"dovish": "利寬鬆", "hawkish": "利緊縮"}.get(f.get("lean"), "")]
            for f in (getattr(ch, "new_flags", None) or [])[:6]]
    sc = (f"情境從「{ch.scenario_from}」移到「{ch.scenario_to}」。" if ch.scenario_moved
          else f"情境維持「{ch.scenario_to}」。")
    head = (ch.headline or "").strip()
    return Out(ans=esc(head.rstrip("。") + "。") + ("" if "情境" in head else " " + esc(sc)), date=(ch.prev_at or "")[:10] and f"對照 {ch.prev_at[:16]}",
               table=(["模組", "新出現的訊號", "方向"], rows) if rows else None)


def _week_rows(C: dict, keys: tuple | None = None, weeks: int = 2) -> list[dict]:
    from . import watch_calendar as wc
    fom = C.get("fomc") or {}
    try:
        rows = wc.watch_rows(C.get("_schedule") or {}, fomc_next=((fom.get("next_meeting")) or {}).get("date"),
                             weeks=weeks)
    except Exception:                              # noqa: BLE001
        return []
    return [r for r in rows if not keys or r["key"] in keys]


def _cons_for(C: dict, key: str, date: str) -> list[dict]:
    return ((C.get("_watch_extra") or {}).get("consensus") or {}).get(f"{key}|{date}") or []


def _tpe(r) -> str:
    t = r["tpe"]
    return f"{t.month:02d}/{t.day:02d}（{'一二三四五六日'[t.weekday()]}）{t.strftime('%H:%M')}"


@fn("week_data")
def _week_data(card, S, C):
    rows = _week_rows(C)
    if not rows:
        return None
    tb = []
    for r in rows[:12]:
        cons = _cons_for(C, r["key"], r["date"].isoformat())
        c = "、".join(f"{x['label']} {x['forecast']}" for x in cons[:2])
        tb.append([_tpe(r), r["name"], c or "—"])
    hi = [r for r in rows if r.get("impact") == "high"][:3]
    ans = ("接下來兩週的重要發布：" + "、".join(f"{_b(r['name'])}（{esc(_tpe(r))}）" for r in hi) + "。"
           if hi else f"接下來兩週共有 {len(rows)} 項發布。")
    return Out(ans=ans + " 時間都是台灣時間。", date=f"截至 {clock.today():%m/%d}",
               table=(["台灣時間", "發布", "市場預估"], tb))


_REL_NAMES = {"cpi": "CPI", "employment": "就業報告（非農）", "pce": "PCE 物價"}


@fn("next_release")
def _next_release(card, S, C):
    key = card["src"]["key"]
    rows = _week_rows(C, (key,), weeks=8)
    name = _REL_NAMES.get(key, key)
    if not rows:
        nxt = {"cpi": (C.get("inflation") or {}).get("next_cpi"),
               "pce": (C.get("inflation") or {}).get("next_pce"),
               "employment": (C.get("labor") or {}).get("next_release")}.get(key)
        if not nxt:
            return None
        return Out(ans=f"下一次{esc(name)}預定在 {_b(nxt)}（美東日期）。", date=nxt)
    r = rows[0]
    cons = _cons_for(C, key, r["date"].isoformat())
    ans = f"下一次{esc(name)}在台灣時間 {_b(_tpe(r))}。"
    tb = None
    if cons:
        ans += " 市場預估：" + "、".join(f"{esc(x['label'])} {_b(x['forecast'])}（前值 {esc(x['previous'])}）" for x in cons) + "。"
        tb = (["項目", "市場預估", "前值"], [[x["label"], x["forecast"], x["previous"]] for x in cons])
    else:
        ans += " 市場預估通常在公布當週才出來，本週以外不提供。"
    return Out(ans=ans, date=r["date"].isoformat(), table=tb)


@fn("speakers")
def _speakers(card, S, C):
    if not C.get("_watch_extra"):
        return None
    sp = (C.get("_watch_extra") or {}).get("speeches") or []
    now = clock.now()
    rows = []
    from . import watch_calendar as wc
    for s in sp:
        et = s.get("et")
        if not isinstance(et, dt.datetime):
            continue
        try:
            tpe = wc.taipei_time(et.date(), (et.hour, et.minute))
        except Exception:                          # noqa: BLE001
            continue
        if tpe < now - dt.timedelta(hours=2):
            continue
        rows.append([f"{tpe.month:02d}/{tpe.day:02d} {tpe:%H:%M}", f"{s.get('name')}（{s.get('role', '')}）",
                     "票委" if s.get("voter") else "", s.get("topic") or s.get("kind") or ""])
    nm = (C.get("fomc") or {}).get("next_meeting") or {}
    bt = nm.get("blackout_text") or ""
    if not rows:
        return Out(ans="近期沒有已排定的聯準會官員公開談話。" + (f" {esc(bt)}。" if bt else ""), date=f"{clock.today():%m/%d}")
    voters = sum(1 for r in rows if r[2])
    ans = f"接下來有 {_b(len(rows))} 場官員公開談話，其中票委 {voters} 場。" + (f" {esc(bt)}。" if bt else "")
    return Out(ans=ans, date=f"{clock.today():%m/%d}", table=(["台灣時間", "官員", "", "形式／主題"], rows[:10]))


@fn("election")
def _election(card, S, C):
    e = C.get("_election")
    if not isinstance(e, dict):
        return None
    rows = []
    for k, zh in (("house", "眾議院"), ("senate", "參議院")):
        x = e.get(k)
        if isinstance(x, dict) and x.get("dem") is not None:
            dem, rep = x["dem"], x["rep"]
            lead = "民主黨" if dem >= rep else "共和黨"
            rows.append([zh, lead, f"{max(dem, rep) * 100:.0f}%", f"{min(dem, rep) * 100:.0f}%"])
    if not rows:
        return None
    ans = ("Polymarket 預測市場：" + "；".join(f"{esc(r[0])} {_b(r[1] + ' ' + r[2])}" for r in rows)
           + f"。距 {esc(e.get('election_date'))} 選舉還有 {esc(e.get('days_to'))} 天。機率是合約價格，不是民調。")
    return Out(ans=ans, date=e.get("date", ""), table=(["", "領先", "機率", "對手"], rows))


@fn("fed_rate")
def _fed_rate(card, S, C):
    f = C.get("fomc") or {}
    if not f.get("rate_range"):
        return None
    lo, hi = rows_of(S, "DFEDTARL"), rows_of(S, "DFEDTARU")
    ans = (f"聯邦基金利率目標區間目前是 {_b(f['rate_range'])}，上次調整在 {esc(f.get('latest_date'))}"
           f"（{esc(f.get('decision_label') or '')}）。")
    lines = [x for x in ({"label": "上緣", "points": hi}, {"label": "下緣", "points": lo}) if x["points"]]
    return Out(ans=ans, date=f.get("latest_date", ""),
               chart=chart(lines, "%", "m", 2, aria="政策利率區間"),
               chart_long=chart(lines, "%", "m", 2, long=True, aria="政策利率區間（五年）"),
               table=(["日期", "決議", "區間", "票數"], [[d.get("date"), d.get("move"), d.get("range"), d.get("votes")]
                                                     for d in (f.get("decisions") or [])[:6]]))


@fn("last_decision")
def _last_decision(card, S, C):
    f = C.get("fomc") or {}
    ds = f.get("decisions") or []
    if not ds:
        return None
    d0 = ds[0]
    sh = f.get("shift") or {}
    ans = (f"{esc(d0.get('date'))} 的 FOMC {_b(d0.get('move'))}，區間 {esc(d0.get('range'))}，"
           f"投票 {esc(d0.get('votes'))}（{esc(d0.get('dissent'))}）。")
    if sh.get("label"):
        ans += f" 本站把這次聲明歸為「{esc(sh['label'])}」。"
    return Out(ans=ans, date=d0.get("date", ""),
               table=(["日期", "決議", "區間", "投票"], [[d.get("date"), d.get("move"), d.get("range"),
                                                       f"{d.get('votes')}（{d.get('dissent')}）"] for d in ds[:6]]))


@fn("next_fomc")
def _next_fomc(card, S, C):
    nm = (C.get("fomc") or {}).get("next_meeting") or {}
    if not nm.get("date"):
        return None
    from . import watch_calendar as wc
    try:
        tpe = wc.taipei_time(dt.date.fromisoformat(nm["date"]), (14, 0))
        when = f"台灣時間 {tpe.month}/{tpe.day} {tpe:%H:%M} 公布聲明"
    except Exception:                              # noqa: BLE001
        when = ""
    ans = (f"下次 FOMC 在 {_b(nm.get('span') or nm['date'])}（還有 {esc(nm.get('days'))} 天），{esc(when)}。"
           + (f" {esc(nm.get('blackout_text'))}。" if nm.get("blackout_text") else ""))
    later = nm.get("later") or []
    return Out(ans=ans, date=nm["date"], table=(["之後的會議"], [[x] for x in later]) if later else None)


def _fw_ok(ch) -> bool:
    """期貨機率報價是否可用（抓取失敗時報價板會放「—，本次擷取失敗」）。"""
    if not ch:
        return False
    t = f"{ch.get('value') or ''}{ch.get('delta') or ''}"
    return bool(ch.get("value")) and "失敗" not in t and not str(ch.get("value")).startswith("—")


@fn("fedwatch")
def _fedwatch(card, S, C):
    ch = _chip(C, "fedwatch")
    if not _fw_ok(ch):
        return None
    hs = [c for c in (_chip(C, f"fw_h{i}") for i in (1, 2, 3)) if _fw_ok(c)]
    ans = f"{esc(ch.get('label'))}：{_b(ch.get('value'))}，{esc(ch.get('delta'))}。"
    if hs:
        ans += " 往後看，市場預期" + "；".join(f"{esc(h['label'])} {esc(h['value'])}" for h in hs) + "。"
    ans += " 機率由聯邦基金期貨價格推算（本站自算，方法同 CME FedWatch）。"
    rows = [[ch.get("label"), ch.get("value"), ch.get("delta")]] + [[h["label"], h["value"], h.get("delta")] for h in hs]
    return Out(ans=ans, date=_dlabel(ch.get("iso") or ""), table=(["", "市場定價", "說明"], rows))


@fn("rate_path")
def _rate_path(card, S, C):
    hs = [c for c in (_chip(C, f"fw_h{i}") for i in (1, 2, 3)) if _fw_ok(c)]
    fc = (C.get("scenario") or {}).get("futures_curve")
    if not hs and not fc:
        return None
    ans = ("市場（聯邦基金期貨）預期：" + "；".join(f"{esc(h['label'])} {_b(h['value'])}（{esc(h.get('delta') or '')}）" for h in hs) + "。"
           if hs else "")
    ch = ""
    if fc and fc.get("points"):
        pts = [{"date": p.get("month", "")[:7] + "-01", "value": p.get("rate")} for p in fc["points"]
               if p.get("rate") is not None and p.get("month")]
        ch = chart([{"label": "期貨隱含利率", "points": pts}], "%", "m", 2, aria="期貨隱含路徑") if len(pts) > 1 else ""
        ans += f" 期貨曲線的終點約 {esc(fnum(fc.get('terminal'), 2))}%（{esc(fc.get('terminal_month'))}）。"
    return Out(ans=ans, date=_dlabel((hs[0].get("iso") if hs else "") or ""), chart=ch,
               table=(["期間", "累計變動", "說明"], [[h["label"], h["value"], h.get("delta")] for h in hs]) if hs else None)


@fn("dots")
def _dots(card, S, C):
    sep = (C.get("fomc") or {}).get("sep") or {}
    dots = sep.get("dots") or {}
    med = dots.get("median") if isinstance(dots, dict) else None
    years = sep.get("years") or []
    rows = []
    if isinstance(med, list):
        for y, v in zip(years, med):
            rows.append([y, fnum(v, 3) + "%" if v is not None else "—"])
    elif isinstance(dots, dict):
        for y, v in dots.items():
            if isinstance(v, (int, float)):
                rows.append([y, fnum(v, 3) + "%"])
            elif isinstance(v, dict) and v.get("median") is not None:
                rows.append([y, fnum(v["median"], 3) + "%"])
    if not rows:
        sd = (C.get("scenario") or {}).get("dots") or {}
        rows = [[y, fnum(v, 3) + "%"] for y, v in sd.items() if v is not None]
    if not rows:
        return None
    ans = (f"{esc(sep.get('date') or '最新')} 的點陣圖中位數：" + "、".join(f"{esc(r[0])} 年底 {_b(r[1])}" for r in rows[:3])
           + "。點陣圖是每位委員的個人預測，不是承諾。")
    return Out(ans=ans, date=sep.get("date", ""), table=(["年底", "中位數"], rows))


@fn("mvd")
def _mvd(card, S, C):
    m = (C.get("fomc") or {}).get("mvd") or (C.get("scenario") or {}).get("mvd")
    if not m:
        return None
    rows = []
    for r in m.get("rows") or []:
        rows.append([r.get("label") or r.get("year"), fnum(r.get("market"), 2) + "%", fnum(r.get("dots"), 2) + "%",
                     fnum(r.get("gap_bp"), 0, sign=True) + " bp" if r.get("gap_bp") is not None else "—"])
    ans = esc(m.get("text") or m.get("summary") or "市場隱含路徑與點陣圖的比較見下表。")
    return Out(ans=ans, date=m.get("asof", ""), table=(["", "市場", "點陣圖", "差距"], rows) if rows else None)


@fn("sep_macro")
def _sep_macro(card, S, C):
    sep = (C.get("fomc") or {}).get("sep") or {}
    vs = sep.get("vars") or {}
    years = sep.get("years") or []
    if not vs:
        return None
    zh = {"gdp": "實質 GDP 成長", "unrate": "失業率", "pce": "PCE 通膨", "core_pce": "核心 PCE"}
    rows = []
    for k in ("gdp", "unrate", "pce", "core_pce"):
        v = vs.get(k)
        if v and v.get("median"):
            rows.append([zh[k]] + [fnum(x, 1) if x is not None else "—" for x in v["median"][:4]])
    if not rows:
        return None
    y0 = years[0] if years else ""
    first = {r[0]: r[1] for r in rows}
    ans = (f"{esc(sep.get('date'))} 的經濟預測（中位數），{esc(y0)} 年底："
           + "、".join(f"{esc(k)} {_b(v + '%')}" for k, v in first.items()) + "。")
    return Out(ans=ans, date=sep.get("date", ""), table=([""] + [str(y) for y in years[:4]], rows))


@fn("fed_focus")
def _fed_focus(card, S, C):
    fo = (C.get("fomc") or {}).get("focus") or {}
    if not fo.get("label"):
        return None
    ans = f"本站判斷聯準會目前重心是 {_b(fo['label'])}。{esc(fo.get('note') or '')}"
    rows = [[e] for e in fo.get("evidence") or []]
    return Out(ans=ans, date=(C.get("fomc") or {}).get("latest_date", ""), table=(["依據"], rows) if rows else None,
               note="重心判讀是本站規則（聲明與記者會措辭計分）。")


@fn("shift_conds")
def _shift_conds(card, S, C):
    sc = (C.get("fomc") or {}).get("shift_conds") or []
    if not sc:
        return None
    met = sum(1 for x in sc if x.get("met"))
    ans = f"要讓聯準會轉向，本站追蹤 {len(sc)} 個條件，目前達成 {_b(met)} 個。"
    return Out(ans=ans, date=(C.get("fomc") or {}).get("latest_date", ""),
               table=(["條件", "目前", "達成"], [[x.get("need"), x.get("now"), "✓" if x.get("met") else "—"] for x in sc]),
               note="條件是本站規則。")


@fn("statement_diff")
def _statement_diff(card, S, C):
    f = C.get("fomc") or {}
    rows = f.get("diff_rows") or []
    notes = f.get("diff_notes") or []
    if not rows and not notes:
        return None
    st = f.get("stability") or {}
    ans = f"{esc(st.get('title') or '')}。{esc(st.get('desc') or '')}"
    tb = []
    for n in notes[:6]:
        tb.append([n if isinstance(n, str) else (n.get("text") if isinstance(n, dict) else str(n))])
    return Out(ans=ans, date=f.get("latest_date", ""), table=(["主要改動"], tb) if tb else None)


@fn("vote")
def _vote(card, S, C):
    vs = (C.get("fomc") or {}).get("vote_summary") or {}
    if not vs.get("text"):
        return None
    names = vs.get("names") or {}
    zh = {"hike": "主張升息", "cut": "主張降息", "hold": "主張不動"}
    rows = [[zh[k], "、".join(v)] for k, v in names.items() if v]
    ans = f"上次決議投票 {_b(vs['text'])}。" + ("".join(f" {esc(r[0])}：{esc(r[1])}。" for r in rows) if rows else "")
    return Out(ans=ans, date=(C.get("fomc") or {}).get("latest_date", ""),
               table=(["", "委員"], rows) if rows else None)


@fn("minutes")
def _minutes(card, S, C):
    m = (C.get("fomc") or {}).get("minutes") or {}
    if not m.get("meeting"):
        return None
    rows = []
    for g in m.get("groups") or []:
        topic, items = (g if isinstance(g, (list, tuple)) else (g.get("topic"), g.get("items")))
        for it in (items or [])[:2]:
            rows.append([topic, it.get("level", ""), it.get("zh") or it.get("text", "")])
    ans = (f"{esc(m['meeting'])} 會議的紀要（{esc(m.get('released'))} 公布）。"
           + (esc(m.get("overview")) if m.get("overview") else "下表依主題列出「多數／許多／少數」委員的看法。"))
    return Out(ans=ans, date=m.get("released", ""), table=(["主題", "人數用語", "原文"], rows[:8]) if rows else None)


@fn("presser")
def _presser(card, S, C):
    ps = (C.get("fomc") or {}).get("presser_summary") or {}
    tp = ps.get("topics") or []
    if not tp:
        return None
    rows = [[t.get("name"), (t.get("sentences") or [""])[0]] for t in tp[:6]]
    ans = f"上次記者會主席談到 {_b('、'.join(t.get('name') for t in tp[:5]))}；下表摘每個主題第一句原文。"
    return Out(ans=ans, date=(C.get("fomc") or {}).get("latest_date", ""), table=(["主題", "原文"], rows))


@fn("blackout")
def _blackout(card, S, C):
    nm = (C.get("fomc") or {}).get("next_meeting") or {}
    if not nm.get("blackout_start"):
        return None
    st = nm.get("blackout_status")
    now_txt = "現在 <b>是</b>靜默期" if st == "in" else "現在 <b>不是</b>靜默期"
    ans = (f"{now_txt}。{esc(nm.get('blackout_text') or '')}；靜默期 {esc(nm['blackout_start'])} 至 "
           f"{esc(nm.get('blackout_end'))}，期間官員不公開談貨幣政策。")
    return Out(ans=ans, date=nm.get("date", ""))


@fn("officials")
def _officials(card, S, C):
    offs = (C.get("fomc") or {}).get("officials") or []
    vot = [o for o in offs if o.get("voter")]
    if not vot:
        return None
    lean = {"hawkish": "偏鷹", "dovish": "偏鴿", "neutral": "中性"}
    rows = [[o.get("name"), o.get("title") or o.get("affil"), lean.get(o.get("lean"), ""), o.get("dissent_tag", "")] for o in vot]
    ans = f"今年 FOMC 有投票權的委員共 {_b(len(vot))} 位；鷹鴿是本站依近期發言與投票的歸類。"
    return Out(ans=ans, date=(C.get("fomc") or {}).get("latest_date", ""), table=(["委員", "職位", "傾向", "反對票紀錄"], rows))


@fn("terminal")
def _terminal(card, S, C):
    fc = (C.get("scenario") or {}).get("futures_curve")
    sep = (C.get("fomc") or {}).get("sep") or {}
    dots = (C.get("scenario") or {}).get("dots") or {}
    if not fc and not dots:
        return None
    ans = ""
    if fc:
        ans += (f"期貨曲線的終點約 {_b(fnum(fc.get('terminal'), 2) + '%')}，出現在 {esc(fc.get('terminal_month'))}"
                f"（相對現在 {esc(fnum(fc.get('terminal_bp'), 0, sign=True))} bp）。")
    if dots:
        ans += " 點陣圖中位數：" + "、".join(f"{esc(y)} 年 {esc(fnum(v, 3))}%" for y, v in list(dots.items())[:4]) + "。"
    return Out(ans=ans.strip(), date=sep.get("date", ""))


# ---- 就業 ----
@fn("labor_now")
def _labor_now(card, S, C):
    sd = C.get("scenario") or {}
    sc = sd.get("scenario")
    why = (sd.get("why") or {}).get("labor") or {}
    if not sc:
        return None
    st = {"強": "強", "中": "中性", "弱": "弱"}.get(sc.labor_state, sc.labor_state)
    ans = f"本站判定就業 {_b(st)}（動能 {esc(sc.labor_momentum)}）。{esc(why.get('lead') or '')}"
    rows = [[r.get("label"), r.get("value")] for r in (why.get("rows") or [])[:5]]
    return Out(ans=ans, date=(C.get("labor") or {}).get("data_month", ""), table=(["依據", "數值"], rows) if rows else None,
               note="強／中／弱的門檻是本站規則。")


@fn("industry")
def _industry(card, S, C):
    at = (C.get("labor") or {}).get("attribution") or {}
    groups = at.get("groups") or []
    if not groups:
        return None
    rows = []
    for g in groups:
        for m in re.finditer(r'data-tip="([^｜"]+)｜([^"]+)"', g.get("bars") or ""):
            rows.append([g.get("title"), m.group(1), m.group(2)])
    sums = "、".join(f"{esc(g.get('title'))} {esc(fnum(g.get('sum'), 1, sign=True))} 萬人" for g in groups)
    kpi = (C.get("labor") or {}).get("kpi") or {}
    ans = f"{esc(kpi.get('nfp_plain') or '')} 分行業看：{sums}。"
    nf = sum(g.get("sum") or 0 for g in groups)
    title = f"非農為什麼{'增加' if nf > 0 else '減少'}？哪些行業在{'增加' if nf > 0 else '減少'}？"
    return Out(ans=ans, date=(C.get("labor") or {}).get("data_month", ""), title=title,
               table=(["類別", "行業", "月變動"], rows[:12]))


@fn("unrate_why")
def _unrate_why(card, S, C):
    lab = C.get("labor") or {}
    d = lab.get("decomp") or {}
    if d.get("delta_rate") is None:
        return None
    up = d["delta_rate"] > 0
    ans = (f"{esc(lab.get('data_month'))} 失業率{'上升' if up else '下降' if d['delta_rate'] < 0 else '持平'} "
           f"{_b(fnum(abs(d['delta_rate']), 1) + ' 個百分點')}，本站拆解結果：{_b(d.get('verdict_text'))}。"
           f"就業人數變動 {esc(fnum(d.get('delta_employed', 0) / 10, 1, sign=True))} 萬、"
           f"勞動力變動 {esc(fnum(d.get('delta_labor_force', 0) / 10, 1, sign=True))} 萬。")
    if not d.get("significant"):
        ans += f" 這次變動小於 {esc(d.get('signif_threshold'))} 個百分點，在抽樣誤差內。"
    pts = rows_of(S, "UNRATE")
    word = "上升" if up else "下降" if d["delta_rate"] < 0 else "持平"
    return Out(ans=ans, date=lab.get("data_month", ""), title=f"失業率為什麼{word}？",
               chart=chart([{"label": "失業率", "points": pts}], "%", "m", 1, aria="失業率"),
               chart_long=chart([{"label": "失業率", "points": pts}], "%", "m", 1, long=True, aria="失業率（五年）"),
               table=(["拆解", "貢獻（個百分點）"], [["就業變動", fnum(d.get("employment_effect"), 2, sign=True)],
                                                  ["勞動力變動", fnum(d.get("laborforce_effect"), 2, sign=True)],
                                                  ["合計", fnum(d.get("delta_rate"), 2, sign=True)]]))


@fn("unemp_structure")
def _unemp_structure(card, S, C):
    us = (C.get("labor") or {}).get("unemp_structure") or {}
    rows = us.get("rows") or []
    if not rows:
        return None
    ans = f"{esc(us.get('verdict') or '')} 失業者依原因分四類，佔比與一年變化見下表。"
    return Out(ans=ans, date=(C.get("labor") or {}).get("data_month", ""),
               table=(["原因", "人數", "佔失業者", "佔比一年變化"],
                      [[r.get("label"), r.get("display"), f"{fnum(r.get('share'), 1)}%", r.get("share_yoy_display")] for r in rows]))


@fn("job_losers")
def _job_losers(card, S, C):
    ax = (C.get("labor") or {}).get("axis") or {}
    if ax.get("jl_share") is None:
        return None
    st = "警戒" if ax.get("jl_alert") else "留意" if ax.get("jl_watch") else "正常"
    ans = (f"失去工作者佔失業者 {_b(fnum(ax['jl_share'], 1) + '%')}（{esc(ax.get('jl_date'))}），"
           f"比一年低點高 {esc(fnum(ax.get('jl_rise'), 1))} 個百分點，偏離程度 z＝{esc(fnum(ax.get('jl_z'), 2))}，本站判讀 {_b(st)}。")
    pts = rows_of(S, "LNS13023622")
    tot = rows_of(S, "UNEMPLOY")
    share = []
    tm = {r["date"]: r["value"] for r in tot}
    for r in pts:
        if tm.get(r["date"]):
            share.append({"date": r["date"], "value": r["value"] / tm[r["date"]] * 100})
    return Out(ans=ans, date=ax.get("jl_date", ""),
               chart=chart([{"label": "失去工作者佔失業者", "points": share}], "%", "m", 1, aria="失去工作者比重"),
               chart_long=chart([{"label": "失去工作者佔失業者", "points": share}], "%", "m", 1, long=True, aria="失去工作者比重（五年）"),
               note="z 分數與警戒線是本站規則。")


def sahm_series(S: dict) -> list[dict]:
    u = rows_of(S, "UNRATE")
    out = []
    for i in range(14, len(u)):
        ma3 = sum(r["value"] for r in u[i - 2:i + 1]) / 3
        lows = [sum(r["value"] for r in u[j - 2:j + 1]) / 3 for j in range(i - 12, i)]
        out.append({"date": u[i]["date"], "value": ma3 - min(lows)})
    return out


@fn("sahm")
def _sahm(card, S, C):
    s = sahm_series(S)
    if not s:
        return None
    v = s[-1]["value"]
    ans = (f"薩姆指標 {_b(fnum(v, 2))}（{esc(period_label(s[-1]['date'], 'm'))}），觸發線 0.5——"
           + ("<b>已觸發</b>，歷史上常伴隨衰退開始。" if v >= 0.5 else f"還差 {esc(fnum(0.5 - v, 2))}，未觸發。"))
    return Out(ans=ans, date=period_label(s[-1]["date"], "m"),
               chart=chart([{"label": "薩姆指標", "points": s}], "", "m", 2, refs=[{"value": 0.5, "label": "觸發 0.5"}], aria="薩姆指標"),
               chart_long=chart([{"label": "薩姆指標", "points": s}], "", "m", 2, long=True, refs=[{"value": 0.5, "label": "觸發 0.5"}], aria="薩姆指標（五年）"))


@fn("ustar")
def _ustar(card, S, C):
    u = (C.get("labor") or {}).get("ustar") or {}
    if u.get("u") is None:
        return None
    ans = (f"失業率 {_b(fnum(u['u'], 1) + '%')}，FOMC 認定的長期失業率區間 {esc(fnum(u.get('lo'), 1))}–{esc(fnum(u.get('hi'), 1))}%"
           f"（中位數 {esc(fnum(u.get('ustar'), 1))}%），差 {esc(u.get('display'))}。{esc(u.get('note') or '')}")
    return Out(ans=ans, date=(C.get("labor") or {}).get("data_month", ""))


@fn("real_wage")
def _real_wage(card, S, C):
    a, c = rows_of(S, "CES0500000003"), rows_of(S, "CPIAUCSL")
    if not a or not c:
        return None
    ay, cy = transform(a, "yoy"), {r["date"]: r["value"] for r in transform(c, "yoy")}
    rw = [{"date": r["date"], "value": r["value"] - cy[r["date"]]} for r in ay if r["date"] in cy]
    if not rw:
        return None
    v = rw[-1]["value"]
    ans = (f"扣掉 CPI 後，實質時薪一年{'增加' if v >= 0 else '減少'} {_b(fnum(abs(v), 1) + '%')}"
           f"（{esc(period_label(rw[-1]['date'], 'm'))}）。名目時薪年增 {esc(fnum(ay[-1]['value'], 1))}%。")
    return Out(ans=ans, date=period_label(rw[-1]["date"], "m"),
               chart=chart([{"label": "實質時薪年增", "points": rw}], "%", "m", 1, zero=True, aria="實質時薪"),
               chart_long=chart([{"label": "實質時薪年增", "points": rw}], "%", "m", 1, long=True, zero=True, aria="實質時薪（五年）"))


@fn("vu")
def _vu(card, S, C):
    j, u = rows_of(S, "JTSJOL"), {r["date"]: r["value"] for r in rows_of(S, "UNEMPLOY")}
    s = [{"date": r["date"], "value": r["value"] / u[r["date"]]} for r in j if u.get(r["date"])]
    if not s:
        return None
    v = s[-1]["value"]
    ans = f"每個失業者對應 {_b(fnum(v, 2))} 個職缺（{esc(period_label(s[-1]['date'], 'm'))}）；大於 1 代表職缺比找工作的人多。"
    return Out(ans=ans, date=period_label(s[-1]["date"], "m"),
               chart=chart([{"label": "職缺／失業", "points": s}], "", "m", 2, refs=[{"value": 1.0, "label": "1 比 1"}], aria="職缺失業比"),
               chart_long=chart([{"label": "職缺／失業", "points": s}], "", "m", 2, long=True, refs=[{"value": 1.0, "label": "1 比 1"}], aria="職缺失業比（五年）"))


@fn("hires_layoffs")
def _hires_layoffs(card, S, C):
    fl = (C.get("labor") or {}).get("flow") or {}
    h, l = rows_of(S, "JTSHIR"), rows_of(S, "JTSLDR")
    if not h or not l:
        return None
    ans = (f"招聘率 {_b(fnum(h[-1]['value'], 1) + '%')}、裁員率 {_b(fnum(l[-1]['value'], 1) + '%')}"
           f"（{esc(period_label(h[-1]['date'], 'm'))}）。" + (f"本站歸類為「{esc(fl.get('name'))}」：{esc(fl.get('meaning'))}。" if fl.get("name") else ""))
    lines = [{"label": "招聘率", "points": h}, {"label": "裁員率", "points": l}]
    return Out(ans=ans, date=period_label(h[-1]["date"], "m"), chart=chart(lines, "%", "m", 1, aria="招聘與裁員"),
               chart_long=chart(lines, "%", "m", 1, long=True, aria="招聘與裁員（五年）"))


@fn("revisions")
def _revisions(card, S, C):
    rv = (C.get("labor") or {}).get("revision") or {}
    rows = rv.get("rows") or []
    if not rows:
        return None
    net = rv.get("two_month_net")
    ans = (f"本次報告把前兩個月合計修正 {_b(fnum((net or 0) / 10, 1, sign=True) + ' 萬人')}。" if net is not None else "")
    ans += " 下表是各月第一次公布的數字與目前的數字。"
    return Out(ans=ans, date=(C.get("labor") or {}).get("data_month", ""),
               table=(["月份", "首次公布（萬人）", "目前（萬人）", "修正"],
                      [[r["label"], fnum(r["original"] / 10, 1, sign=True), fnum(r["current"] / 10, 1, sign=True),
                        fnum((r["current"] - r["original"]) / 10, 1, sign=True)] for r in rows[-8:]]))


def _tilt_card(C, mod):
    t = (C.get(mod) or {}).get("tilt") or {}
    if not t:
        return None
    word = {"hawkish": "偏緊縮", "dovish": "偏寬鬆", "balanced": "大致平衡"}.get(t.get("tilt"), t.get("tilt"))
    ans = (f"本期訊號合計 {_b(word)}：利緊縮分數 {esc(fnum(t.get('hawkish'), 1))}、利寬鬆分數 {esc(fnum(t.get('dovish'), 1))}。")
    flags = (C.get(mod) or {}).get("flags") or []
    rows = []
    for f in flags[:8]:
        title = getattr(f, "title", None) or (f.get("title") if isinstance(f, dict) else "")
        lean = getattr(f, "lean", None) or (f.get("lean") if isinstance(f, dict) else "")
        rows.append([title, {"dovish": "利寬鬆", "hawkish": "利緊縮"}.get(lean, "中性")])
    return Out(ans=ans, date=(C.get(mod) or {}).get("data_month", ""), table=(["訊號", "方向"], rows) if rows else None,
               note="計分是本站規則。")


@fn("labor_tilt")
def _labor_tilt(card, S, C):
    return _tilt_card(C, "labor")


@fn("infl_tilt")
def _infl_tilt(card, S, C):
    return _tilt_card(C, "inflation")


# ---- 通膨 ----
@fn("infl_now")
def _infl_now(card, S, C):
    v3 = (C.get("inflation") or {}).get("verdict3") or {}
    if not v3.get("label"):
        return None
    sd = C.get("scenario") or {}
    why = (sd.get("why") or {}).get("inflation") or {}
    ans = f"本站判定通膨 {_b(v3['label'])}：{esc(v3.get('reason') or '')}。"
    rows = [[r.get("label"), r.get("value")] for r in (why.get("rows") or [])[:5]]
    return Out(ans=ans, date=(C.get("inflation") or {}).get("data_month", ""), table=(["依據", "數值"], rows) if rows else None,
               note="三分法（明確升溫／黏著不降／穩定降溫）是本站規則：" + (v3.get("rule") or ""))


@fn("pce_nowcast")
def _pce_nowcast(card, S, C):
    pn = (C.get("inflation") or {}).get("pce_nowcast") or {}
    if pn.get("value") is None:
        return None
    ans = (f"用已公布的 CPI、PPI 換算，{esc((pn.get('source_month') or '')[:7])} 核心 PCE 年增推估 {_b(fnum(pn['value'], 2) + '%')}。"
           f"過去 {esc(pn.get('n_backtest'))} 個月回測的平均誤差約 {esc(fnum(pn.get('mae_gap'), 2))} 個百分點。")
    rows = [[c.get("label"), f"{fnum(c.get('weight'), 1)}%", f"{fnum(c.get('yoy'), 1)}%"] for c in (pn.get("components") or [])]
    return Out(ans=ans, date=(pn.get("source_month") or "")[:7], table=(["成分", "權重", "年增"], rows) if rows else None,
               note="推估方法是本站規則；BEA 公布後換回實際值。")


@fn("cpi_vs_pce")
def _cpi_vs_pce(card, S, C):
    a = {k: transform(rows_of(S, k), "yoy") for k in ("CPIAUCSL", "PCEPI", "CPILFESL", "PCEPILFE")}
    if not all(a.values()):
        return None
    pce_d = a["PCEPI"][-1]["date"]
    cpi = {r["date"]: r["value"] for r in a["CPIAUCSL"]}
    core = {r["date"]: r["value"] for r in a["CPILFESL"]}
    pc = a["PCEPILFE"][-1]["value"]
    gap = cpi.get(pce_d, a["CPIAUCSL"][-1]["value"]) - a["PCEPI"][-1]["value"]
    ans = (f"{esc(period_label(pce_d, 'm'))}：CPI 年增 {esc(fnum(cpi.get(pce_d), 1))}%、PCE 年增 {esc(fnum(a['PCEPI'][-1]['value'], 1))}%，"
           f"差 {_b(fnum(gap, 1) + ' 個百分點')}；核心 CPI {esc(fnum(core.get(pce_d), 1))}%、核心 PCE {esc(fnum(pc, 1))}%。")
    gs = [{"date": r["date"], "value": core[r["date"]] - r["value"]} for r in a["PCEPILFE"] if r["date"] in core]
    return Out(ans=ans, date=period_label(pce_d, "m"),
               chart=chart([{"label": "核心 CPI − 核心 PCE", "points": gs}], "", "m", 2, zero=True, aria="CPI 與 PCE 差距"),
               chart_long=chart([{"label": "核心 CPI − 核心 PCE", "points": gs}], "", "m", 2, long=True, zero=True, aria="CPI 與 PCE 差距（五年）"))


@fn("target_gap")
def _target_gap(card, S, C):
    t = (C.get("inflation") or {}).get("target") or {}
    if t.get("value") is None:
        return None
    ans = (f"{esc(t.get('label'))} {_b(fnum(t['value'], 2) + '%')}，比 2% 目標高 {_b(fnum(t.get('gap'), 2) + ' 個百分點')}；"
           f"近期動能（三個月年化）{esc(fnum(t.get('momentum'), 2))}%。")
    pts = transform(rows_of(S, "PCEPILFE"), "yoy")
    return Out(ans=ans, date=(C.get("inflation") or {}).get("data_month", ""),
               chart=chart([{"label": "核心 PCE 年增", "points": pts}], "%", "m", 1, refs=[{"value": 2.0, "label": "2% 目標"}], aria="核心 PCE"),
               chart_long=chart([{"label": "核心 PCE 年增", "points": pts}], "%", "m", 1, long=True, refs=[{"value": 2.0, "label": "2% 目標"}], aria="核心 PCE（五年）"))


@fn("supercore")
def _supercore(card, S, C):
    sm = (C.get("inflation") or {}).get("summary")
    if sm is None:
        return None
    st = (C.get("inflation") or {}).get("stickiness") or {}
    ans = (f"PCE Supercore 三個月年化 {_b(fnum(getattr(sm, 'pce_supercore_3m', None), 1) + '%')}、"
           f"十二個月 {esc(fnum(getattr(sm, 'pce_supercore_12m', None), 1))}%；CPI 版三個月年化 {esc(fnum(getattr(sm, 'supercore_3m', None), 1))}%。"
           f" {esc(_fill_ctx(st.get('verdict') or '', C))}")
    rows = [["PCE 版", fnum(getattr(sm, "pce_supercore_3m", None), 1), fnum(getattr(sm, "pce_supercore_6m", None), 1), fnum(getattr(sm, "pce_supercore_12m", None), 1)],
            ["CPI 版", fnum(getattr(sm, "supercore_3m", None), 1), fnum(getattr(sm, "supercore_6m", None), 1), fnum(getattr(sm, "supercore_12m", None), 1)]]
    return Out(ans=ans, date=(C.get("inflation") or {}).get("data_month", ""), table=(["%", "三個月年化", "六個月年化", "十二個月"], rows))


@fn("energy")
def _energy(card, S, C):
    inf = C.get("inflation") or {}
    eh = inf.get("energy_headline") or {}
    ev = inf.get("energy_viz") or {}
    if not eh and not ev:
        return None
    ans = (f"能源對頭條 CPI 的推力約 {_b(eh.get('value') or '—')}（{esc(eh.get('note') or '')}）。{esc(inf.get('energy_core_note') or '')}")
    pts = transform(rows_of(S, "CPIENGSL"), "yoy")
    return Out(ans=ans, date=inf.get("data_month", ""),
               chart=chart([{"label": "能源 CPI 年增", "points": pts}], "%", "m", 1, zero=True, aria="能源 CPI"),
               chart_long=chart([{"label": "能源 CPI 年增", "points": pts}], "%", "m", 1, long=True, zero=True, aria="能源 CPI（五年）"))


@fn("contrib")
def _contrib(card, S, C):
    at = (C.get("inflation") or {}).get("attribution") or {}
    parts = at.get("parts") or []
    if not parts:
        return None
    ps = sorted(parts, key=lambda p: -abs(p.get("value") or 0))
    ans = ("核心通膨的月漲幅主要來自 " + "、".join(f"{_b(p['label'])}（{esc(fnum(p['value'], 2, sign=True))}）" for p in ps[:3])
           + f"，合計 {esc(fnum(at.get('total'), 2))} 個百分點。")
    return Out(ans=ans, date=(C.get("inflation") or {}).get("data_month", ""),
               table=(["分項", "貢獻（個百分點）", "說明"], [[p["label"], fnum(p["value"], 2, sign=True), p.get("note", "")] for p in ps]))


@fn("infl_why")
def _infl_why(card, S, C):
    out = _contrib(card, S, C)
    v3 = (C.get("inflation") or {}).get("verdict3") or {}
    if out is None:
        return None
    out["ans"] = f"本站判定通膨 {_b(v3.get('label', ''))}：{esc(v3.get('reason') or '')}。" + out["ans"]
    lb = v3.get("label") or ""
    out["title"] = ("通膨為什麼升溫？" if "升溫" in lb else "通膨為什麼降溫？" if "降溫" in lb
                    else "通膨為什麼降不下來？" if lb else "")
    return out


@fn("breadth")
def _breadth(card, S, C):
    tv = (C.get("inflation") or {}).get("trend_verdict") or {}
    m, t = rows_of(S, "MEDCPIM159SFRBCLE"), rows_of(S, "TRMMEANCPIM159SFRBCLE")
    if not tv and not m:
        return None
    ans = f"{_b(tv.get('title') or '')}。{esc(tv.get('desc') or '')}"
    lines = [x for x in ({"label": "中位數 CPI", "points": m}, {"label": "截尾平均 CPI", "points": t}) if x["points"]]
    return Out(ans=ans, date=(C.get("inflation") or {}).get("data_month", ""), chart=chart(lines, "%", "m", 1, aria="通膨廣度"),
               chart_long=chart(lines, "%", "m", 1, long=True, aria="通膨廣度（五年）"))


@fn("wage_pass")
def _wage_pass(card, S, C):
    pt = (C.get("inflation") or {}).get("passthrough") or {}
    if not pt.get("verdict_desc"):
        return None
    ans = f"{_b(pt.get('verdict_title') or '')}。{esc(pt.get('verdict_desc'))}"
    return Out(ans=ans, date=(C.get("inflation") or {}).get("data_month", ""))


@fn("infl_expect")
def _infl_expect(card, S, C):
    m, e1, f5 = rows_of(S, "MICH"), rows_of(S, "EXPINF1YR"), rows_of(S, "T5YIFR")
    if not m and not f5:
        return None
    parts = []
    if m:
        parts.append(f"密西根消費者 1 年通膨預期 {_b(fnum(m[-1]['value'], 1) + '%')}（{esc(period_label(m[-1]['date'], 'm'))}）")
    if e1:
        parts.append(f"克里夫蘭聯儲 1 年預期 {esc(fnum(e1[-1]['value'], 2))}%")
    if f5:
        parts.append(f"市場 5 年後 5 年遠期通膨 {_b(fnum(f5[-1]['value'], 2) + '%')}（{esc(_dlabel(f5[-1]['date']))}）")
    lines = [x for x in ({"label": "密西根 1 年", "points": m}, {"label": "5y5y 遠期", "points": f5}) if x["points"]]
    return Out(ans="；".join(parts) + "。", date=period_label((m or f5)[-1]["date"], "m"),
               chart=chart(lines, "%", "m", 2, aria="通膨預期"), chart_long=chart(lines, "%", "m", 2, long=True, aria="通膨預期（五年）"))


# ---- 長端 ----
@fn("longend_why")
def _longend_why(card, S, C):
    cd = (C.get("rates") or {}).get("le", {}).get("curve_drivers") or {}
    cv = (C.get("rates") or {}).get("curve")
    if not cd and not cv:
        return None
    rows = []
    ans = ""
    for key, zh in (("wow", "過去一週"), ("mom", "過去一個月")):
        x = cd.get(key) or {}
        if x.get("y10") is None:
            continue
        rows.append([zh, fnum(x.get("y10"), 0, sign=True), fnum(x.get("real"), 0, sign=True), fnum(x.get("be"), 0, sign=True),
                     fnum(x.get("tp"), 0, sign=True), fnum(x.get("path"), 0, sign=True)])
    m = cd.get("mom") or {}
    if m.get("y10") is not None:
        big = max((("實質殖利率", m.get("real")), ("損益兩平（通膨補償）", m.get("be"))), key=lambda t: abs(t[1] or 0))
        ans = (f"過去一個月 10 年期{'上升' if m['y10'] > 0 else '下降'} {_b(fnum(abs(m['y10']), 0) + ' bp')}，"
               f"主要來自{_b(big[0])}（{esc(fnum(big[1], 0, sign=True))} bp）；期限溢酬 {esc(fnum(m.get('tp'), 0, sign=True))} bp、"
               f"政策路徑預期 {esc(fnum(m.get('path'), 0, sign=True))} bp。")
    if cv is not None:
        dc = getattr(cv, "decomposition", {}) or {}
        ans += f" 目前 10 年期 {esc(fnum(dc.get('nominal'), 2))}% ＝ 實質 {esc(fnum(dc.get('real'), 2))}% ＋ 損益兩平 {esc(fnum(dc.get('breakeven'), 2))}%。"
    y10m = (cd.get("mom") or {}).get("y10")
    title = ("長天期殖利率為什麼上升？" if (y10m or 0) > 0 else "長天期殖利率為什麼下降？") if y10m is not None else ""
    return Out(ans=ans, date=cd.get("date", ""), title=title,
               table=(["bp", "10 年期", "實質", "損益兩平", "期限溢酬", "政策路徑"], rows) if rows else None,
               note="期限溢酬與另外兩項有重疊，不可直接相加。")


@fn("spread")
def _spread(card, S, C):
    key = card["src"]["key"]
    le = (C.get("rates") or {}).get("le") or {}
    sp = next((s for s in le.get("spreads") or [] if s.get("key") == key), None)
    a, b = {"10-2": ("DGS10", "DGS2"), "30-2": ("DGS30", "DGS2"), "30-10": ("DGS30", "DGS10")}[key]
    ra, rb = rows_of(S, a), {r["date"]: r["value"] for r in rows_of(S, b)}
    pts = [{"date": r["date"], "value": (r["value"] - rb[r["date"]]) * 100} for r in ra if r["date"] in rb]
    if not sp and not pts:
        return None
    if sp:
        w = sp.get("wow_regime") or {}
        mo = sp.get("mom_regime") or {}
        ans = (f"{esc(sp.get('label'))} 利差 {_b(fnum(sp.get('value'), 0) + ' bp')}（{esc(_dlabel(sp.get('date', '')))}）。"
               f"過去一週 {esc(fnum(sp.get('wow'), 0, sign=True))} bp（長端 {esc(fnum(sp.get('wow_long'), 0, sign=True))}、短端 {esc(fnum(sp.get('wow_short'), 0, sign=True))}），"
               f"型態 {_b(w.get('zh') or '—')}{('，' + esc(w.get('lead'))) if w.get('lead') else ''}；"
               f"過去一個月 {esc(fnum(sp.get('mom'), 0, sign=True))} bp，{esc(mo.get('zh') or '')}。")
        if (sp.get("value") or 0) < 0:
            ans += " 目前<b>倒掛</b>。"
    else:
        ans = f"{esc(key)} 利差 {_b(fnum(pts[-1]['value'], 0) + ' bp')}。"
    return Out(ans=ans, date=(sp or {}).get("date", ""),
               chart=chart([{"label": f"{key} 利差（bp）", "points": pts}], "", "d", 0, zero=True, aria=f"{key} 利差"),
               chart_long=chart([{"label": f"{key} 利差（bp）", "points": pts}], "", "d", 0, long=True, zero=True, aria=f"{key} 利差（五年）"))


@fn("curve_shape")
def _curve_shape(card, S, C):
    le = (C.get("rates") or {}).get("le") or {}
    br = le.get("brief") or {}
    sp = br.get("sp") or {}
    if not sp:
        return None
    rows = [[k, fnum(v.get("b"), 0), fnum(v.get("d"), 0, sign=True), v.get("zh", ""), v.get("lead", "")] for k, v in sp.items()]
    lv = br.get("lv") or {}
    ans = (f"{esc(br.get('from'))} 到 {esc(br.get('to'))}：" + "、".join(f"{esc(k)} 年 {esc(fnum(v.get('d'), 0, sign=True))} bp" for k, v in lv.items())
           + "。" + "；".join(f"{esc(k)} 利差 {_b(v.get('zh'))}" for k, v in sp.items()) + "。")
    return Out(ans=ans, date=br.get("to", ""), table=(["利差", "最新（bp）", "一週變動", "型態", "帶動"], rows))


@fn("auctions")
def _auctions(card, S, C):
    le = (C.get("rates") or {}).get("le") or {}
    au = sorted(le.get("auctions") or [], key=lambda a: a.get("date") or "", reverse=True)
    if not au:
        return None
    zh = le.get("tenor_zh") or {}
    rows = [[a.get("date"), zh.get(a.get("term"), a.get("term")), fnum(a.get("btc"), 2), fnum(a.get("avg_btc"), 2),
             fnum(a.get("tail_bp"), 1, sign=True), f"{fnum(a.get('dealer_pct'), 1)}%", a.get("verdict", "")] for a in au]
    rc = le.get("auction_recent") or {}
    a0 = au[0]
    ans = (f"最近一場是 {esc(a0.get('date'))} 的 {esc(zh.get(a0.get('term'), a0.get('term')))}：投標倍數 {esc(fnum(a0.get('btc'), 2))}"
           f"（前 6 場平均 {esc(fnum(a0.get('avg_btc'), 2))}）、尾差約 {esc(fnum(a0.get('tail_bp'), 1, sign=True))} bp，本站判讀 {_b(a0.get('verdict'))}。"
           f" 近三週 {esc(le.get('auction_recent_n') or 0)} 場：偏強 {esc(rc.get('偏強', 0))}、中性 {esc(rc.get('中性', 0))}、偏弱 {esc(rc.get('偏弱', 0))}。")
    return Out(ans=ans, date=a0.get("date", ""), table=(["日期", "天期", "投標倍數", "前 6 場平均", "尾差 bp", "交易商承接", "判讀"], rows),
               note="強弱判讀是本站規則：" + (le.get("auction_rule") or ""))


@fn("auction_next")
def _auction_next(card, S, C):
    wx = (C.get("_watch_extra") or {}).get("auctions") or []
    today = clock.today().isoformat()
    up = [a for a in wx if (a.get("date") or "") >= today]
    if not up:
        return None
    rows = [[a.get("date"), a.get("name") or a.get("years"), a.get("amount") or "", a.get("src") or ""] for a in up[:10]]
    lg = next((a for a in up if any(t in (a.get("years") or "") for t in ("10 年", "20 年", "30 年"))), None)
    ans = f"接下來 {_b(len(up))} 場公債標售已排定" + (f"；下一場長天期是 {_b(lg.get('date'))} 的 {esc(lg.get('years'))}" if lg else "") + "。結果通常在美東 13:00（台灣深夜）公布。"
    return Out(ans=ans, date=up[0].get("date", ""), table=(["日期", "標售", "金額", "來源"], rows))


@fn("refunding")
def _refunding(card, S, C):
    rf = ((C.get("rates") or {}).get("le") or {}).get("refunding") or {}
    if not rf.get("date"):
        return None
    ans = (f"最近一次季度再融資在 {_b(rf['date'])}，下次預定 {_b(rf.get('next') or '—')}。{esc(rf.get('guidance_zh') or '')}"
           + (f" 回購：{esc(rf.get('buybacks_zh'))}" if rf.get("buybacks_zh") else ""))
    return Out(ans=ans, date=rf["date"], note=("原文：" + rf.get("guidance_en")) if rf.get("guidance_en") else "")


@fn("buyback")
def _buyback(card, S, C):
    bb = (C.get("_watch_extra") or {}).get("buybacks") or []
    today = clock.today().isoformat()
    up = [b for b in bb if (b.get("date") or "") >= today]
    if not up:
        return None
    rows = [[b.get("date"), b.get("segment"), b.get("purpose"), b.get("max")] for b in up[:10]]
    ans = f"接下來排定 {_b(len(up))} 次公債回購，下一次 {_b(up[0].get('date'))}（{esc(up[0].get('segment'))}，{esc(up[0].get('purpose'))}）。"
    return Out(ans=ans, date=up[0].get("date", ""), table=(["日期", "天期", "目的", "上限"], rows))


@fn("supply")
def _supply(card, S, C):
    pr = (C.get("rates") or {}).get("pressure")
    if pr is None:
        return None
    lv = {"high": "偏高", "medium": "中等", "low": "偏低"}.get(getattr(pr, "level", ""), getattr(pr, "level", ""))
    ans = f"本站的債券供給壓力分數 {_b(fnum(pr.score, 2))}（{esc(lv)}）。{esc(pr.gap_note or '')}"
    rows = [[p.get("label"), p.get("detail")] for p in (pr.priced or [])] + [[p.get("label"), p.get("detail")] for p in (pr.demand or [])]
    return Out(ans=ans, date=(C.get("rates") or {}).get("as_of", ""), table=(["項目", "現況"], rows) if rows else None,
               note="壓力分數是本站規則。")


@fn("fed_bs")
def _fed_bs(card, S, C):
    le = (C.get("rates") or {}).get("le") or {}
    fp = le.get("fed_policy") or {}
    ta = rows_of(S, "TREAST")
    if not fp and not ta:
        return None
    ans = esc(fp.get("text_zh") or "")
    if ta:
        y = _ago(ta, 12)
        ans += (f" 聯準會持有公債 {_b(fnum(ta[-1]['value'] / 1e6, 2) + ' 兆美元')}（{esc(_dlabel(ta[-1]['date']))}）"
                + (f"，一年變動 {esc(fnum((ta[-1]['value'] - y['value']) / 1e3, 0, sign=True))} 億美元" if y else "") + "。")
    pts = [{"date": r["date"], "value": r["value"] / 1e6} for r in ta]
    return Out(ans=ans, date=ta[-1]["date"] if ta else "", chart=chart([{"label": "持有公債（兆美元）", "points": pts}], "", "w", 2, aria="聯準會持有公債"),
               chart_long=chart([{"label": "持有公債（兆美元）", "points": pts}], "", "w", 2, long=True, aria="聯準會持有公債（五年）"))


def _debt_words(d) -> str:
    from . import rates as _r
    t, desc = _r.DEBT_VERDICT.get(getattr(d, "verdict", "") or "unknown", ("", ""))
    return (f"本站判讀：{t}。{desc}" if t and t != "資料不足" else "")


def _hs_words(h) -> str:
    from . import rates as _r
    try:
        t, desc = _r.hs_verdict(h)
    except Exception:                              # noqa: BLE001
        t, desc = _r.HS_VERDICT.get(getattr(h, "verdict", "") or "unknown", ("", ""))
    return (f"本站判讀：{t}。{desc}" if t and t != "資料不足" else "")


def _debt(C):
    return (C.get("rates") or {}).get("debt")


@fn("debt")
def _debt_card(card, S, C):
    d = _debt(C)
    if d is None or d.debt_gdp is None:
        return None
    pts = rows_of(S, "GFDEGDQ188S")
    ans = f"聯邦債務佔 GDP {_b(fnum(d.debt_gdp, 1) + '%')}（{esc(period_label(d.debt_gdp_asof or '', 'q'))}）。{esc(_debt_words(d))}"
    return Out(ans=ans, date=period_label(d.debt_gdp_asof or "", "q"), chart=chart([{"label": "債務佔 GDP", "points": pts}], "%", "q", 1, aria="債務佔 GDP"),
               chart_long=chart([{"label": "債務佔 GDP", "points": pts}], "%", "q", 1, long=True, aria="債務佔 GDP（五年）"))


@fn("deficit")
def _deficit(card, S, C):
    d = _debt(C)
    if d is None or d.deficit_gdp is None:
        return None
    ans = (f"財政赤字約佔 GDP {_b(fnum(abs(d.deficit_gdp), 1) + '%')}；利息支出佔 GDP {esc(fnum(d.interest_gdp, 1))}%、"
           f"佔稅收 {esc(fnum(d.interest_to_revenue, 1))}%。")
    return Out(ans=ans, date=period_label(d.debt_gdp_asof or "", "q"))


@fn("interest_cost")
def _interest_cost(card, S, C):
    d = _debt(C)
    if d is None or d.interest_to_revenue is None:
        return None
    ans = (f"利息支出佔聯邦稅收 {_b(fnum(d.interest_to_revenue, 1) + '%')}、佔 GDP {esc(fnum(d.interest_gdp, 1))}%；"
           f"已發行債務平均利率 {esc(fnum(d.effective_rate, 2))}%。r−g（實質利率減實質成長）{esc(fnum(d.r_minus_g, 2, sign=True))} 個百分點。"
           f" {esc(d.gap_divergence or '')}")
    return Out(ans=ans, date=period_label(d.debt_gdp_asof or "", "q"),
               table=(["項目", "數值"], [["利息／稅收", f"{fnum(d.interest_to_revenue, 1)}%"], ["有效利率", f"{fnum(d.effective_rate, 2)}%"],
                                         ["名目成長", f"{fnum(d.nominal_growth, 1)}%"], ["r − g", fnum(d.r_minus_g, 2, sign=True)],
                                         ["i − g", fnum(d.i_minus_g, 2, sign=True)]]))


@fn("global_long")
def _global_long(card, S, C):
    g = ((C.get("rates") or {}).get("le") or {}).get("global") or {}
    rows = [r for r in g.get("rows") or [] if r.get("value") is not None]
    if not rows:
        return None
    tb = [[r["name"], f"{fnum(r['value'], 2)}%", fnum(r.get("chg12"), 0, sign=True), r.get("date", "")[:7]] for r in rows]
    ans = "主要國家 10 年期公債殖利率（月資料）：" + "、".join(f"{esc(r[0])} {_b(r[1])}" for r in tb) + "。"
    ch = g.get("chart") or ""
    return Out(ans=ans, date=rows[0].get("date", "")[:7], table=(["", "殖利率", "一年變動 bp", "月份"], tb),
               chart="" if "empty" in ch[:40] else ch)


@fn("hs_capex")
def _hs_capex(card, S, C):
    h = (C.get("rates") or {}).get("hyperscalers")
    if h is None or not getattr(h, "companies", None):
        return None
    ans = (f"{esc(h.period_span or h.as_of)} 主要科技巨頭資本支出合計 {_b(fnum(h.total_capex, 1) + ' 十億美元')}，"
           f"年增 {esc(fnum(h.capex_yoy, 0))}%，約佔營運現金流 {esc(fnum(h.capex_to_ocf, 0))}%。{esc(_hs_words(h))}")
    rows = [[c.get("name"), fnum(c.get("capex"), 1), f"{fnum(c.get('capex_yoy'), 0, sign=True)}%", f"{fnum(c.get('capex_to_ocf'), 0)}%"] for c in h.companies]
    return Out(ans=ans, date=h.as_of, table=(["公司", "資本支出（十億美元）", "年增", "佔營運現金流"], rows))


@fn("hs_debt")
def _hs_debt(card, S, C):
    r = C.get("rates") or {}
    of = r.get("offerings") or {}
    h = r.get("hyperscalers")
    if not of.get("available") and h is None:
        return None
    ans = ""
    if h is not None:
        ans += f"{esc(h.as_of)} 主要科技巨頭發債 {_b(fnum(h.total_issued, 1) + ' 十億美元')}。"
    if of.get("available"):
        ans += f" 近期公開發行 {esc(of.get('count'))} 筆，合計 {esc(of.get('total_display'))}。"
    rows = [[x.get("date"), x.get("name") or x.get("issuer"), x.get("amount_display") or x.get("amount") or ""] for x in (of.get("rows") or [])[:8]]
    return Out(ans=ans, date=(h.as_of if h is not None else of.get("latest", "")), table=(["日期", "發行人", "金額"], rows) if rows else None)


@fn("mortgage")
def _mortgage(card, S, C):
    m = ((C.get("rates") or {}).get("le") or {}).get("mortgage") or {}
    if m.get("value") is None:
        return None
    ans = (f"30 年期固定房貸利率 {_b(fnum(m['value'], 2) + '%')}（{esc(m.get('date'))} 當週，房地美調查）"
           + (f"，一年變動 {esc(fnum(m.get('chg_1y'), 0, sign=True))} bp" if m.get("chg_1y") is not None else "") + "。房貸利率大致跟著 10 年期公債走。")
    return Out(ans=ans, date=m.get("date", ""), chart=m.get("chart") or "")


# ---- 情境 ----
def _sc(C):
    return (C.get("scenario") or {}).get("scenario")


@fn("cell")
def _cell(card, S, C):
    sc = _sc(C)
    if sc is None:
        return None
    ans = f"目前在九宮格的 {_b(sc.name)}：就業 {_b(sc.labor_state)}、通膨 {_b(sc.infl_state)}。{esc(sc.description)}"
    from . import scenario as _s
    reg = _s.REGIME_LABEL.get(sc.regime, sc.regime) if hasattr(_s, "REGIME_LABEL") else sc.regime
    return Out(ans=ans + f" 適用「{esc(reg)}」的九宮格。", date=(C.get("scenario") or {}).get("as_of", ""),
               table=(["", "現況"], [["就業", f"{sc.labor_state}（動能 {sc.labor_momentum}）"], ["通膨", f"{sc.infl_state}（動能 {sc.infl_momentum}）"],
                                     ["方向", {"hawkish": "偏緊縮", "dovish": "偏寬鬆"}.get(sc.lean, "中性")]]),
               note="九宮格與門檻是本站規則。")


@fn("sc_lean")
def _sc_lean(card, S, C):
    sc = _sc(C)
    if sc is None:
        return None
    word = {"hawkish": "偏緊縮（利率易升難降）", "dovish": "偏寬鬆（利率易降難升）"}.get(sc.lean, "中性")
    ans = f"目前情境 {_b(sc.name)}，方向 {_b(word)}。{esc(sc.fomc_note or '')}"
    rows = [[k, v] for k, v in (sc.positioning or {}).items()]
    return Out(ans=ans, date=(C.get("scenario") or {}).get("as_of", ""), table=(["資產", "情境對照"], rows) if rows else None,
               note="情境方向是本站規則，不構成投資建議。")


@fn("triggers")
def _triggers(card, S, C):
    sc = _sc(C)
    if sc is None or not sc.triggers:
        return None
    adj = [t for t in sc.triggers if getattr(t, "adjacent", False) and not t.met]
    ans = "最接近的換格條件：" + "；".join(f"{_b(t.label)}——{esc(t.plain or t.threshold)}（{esc(t.distance)}）" for t in adj[:2]) + "。"
    rows = [[t.label, t.current, t.threshold, t.distance] for t in sc.triggers]
    return Out(ans=ans, date=(C.get("scenario") or {}).get("as_of", ""), table=(["轉換", "目前", "門檻", "距離"], rows),
               note="門檻是本站規則。")


@fn("sc_next")
def _sc_next(card, S, C):
    nr = (C.get("scenario") or {}).get("next_releases") or []
    if not nr:
        return None
    ans = "接下來可能讓格子移動的發布：" + "、".join(f"{_b(r['label'])}（{esc(r['date'])}，{esc(r['axis'])}）" for r in nr[:3]) + "。"
    return Out(ans=ans, date=nr[0].get("date", ""), table=(["日期", "發布", "影響", "為什麼"], [[r["date"], r["label"], r["axis"], r["why"]] for r in nr]))


@fn("trail")
def _trail(card, S, C):
    tr = (C.get("scenario") or {}).get("trail") or []
    if not tr:
        return None
    rows = [[t["month"], t["labor"], t["infl"], fnum(t.get("u"), 1), fnum(t.get("pce"), 2)] for t in tr]
    moved = len({(t["labor"], t["infl"]) for t in tr})
    ans = f"過去 {len(tr)} 個月格位" + ("一直沒有移動。" if moved == 1 else f"經過 {moved} 個不同格子。") + " 每月的就業／通膨判定見下表。"
    return Out(ans=ans, date=tr[-1]["month"], table=(["月份", "就業", "通膨", "失業率", "核心 PCE"], rows))


@fn("duration")
def _duration(card, S, C):
    du = (C.get("scenario") or {}).get("duration") or []
    sc = _sc(C)
    if not du:
        return None
    pos = (sc.positioning or {}).get("債券存續期間") if sc else ""
    ans = f"本站情境對照：{_b(pos or '—')}。下表是各天期公債殖利率變動 ±25 bp 時的價格變化。"
    rows = [[d["tenor"], f"{fnum(d['yield'], 2)}%", fnum(d["D"], 1), f"{fnum(d['up25'], 2, sign=True)}%", f"{fnum(d['dn25'], 2, sign=True)}%"] for d in du]
    return Out(ans=ans, date=(C.get("scenario") or {}).get("as_of", ""), table=(["天期", "殖利率", "存續期間（年）", "+25 bp", "−25 bp"], rows),
               note="情境對照是本站規則，不構成投資建議。")


@fn("divergence")
def _divergence(card, S, C):
    dv = (C.get("scenario") or {}).get("divergence")
    if not dv:
        return None
    ans = esc(dv.get("text") or dv.get("summary") or "")
    return Out(ans=ans or "本站判讀與期貨定價的比較見情境頁。", date=(C.get("scenario") or {}).get("as_of", ""))


# ---------------------------------------------------------------------------
# 練習模板（learn.yaml 的 practice）：全站一次算好所有欄位，填得滿才顯示
# ---------------------------------------------------------------------------
def practice_vals(C: dict, S: dict) -> dict:
    v: dict = {}

    def put(k, x):
        if x is not None and x != "":
            v[k] = x

    def last(sid, tf="lv", sc=1.0, back=0):
        r = transform(rows_of(S, sid), tf, sc)
        return r[-1 - back]["value"] if len(r) > back else None
    f = C.get("fomc") or {}
    dec = f.get("decision") or {}
    put("lower", fnum(dec.get("lower"), 2) if dec.get("lower") is not None else None)
    put("upper", fnum(dec.get("upper"), 2) if dec.get("upper") is not None else None)
    nm = f.get("next_meeting") or {}
    put("next_meeting", nm.get("span"))
    put("blackout_end", nm.get("blackout_end"))
    put("in_blackout", "在靜默期" if nm.get("blackout_status") == "in" else ("不在靜默期" if nm.get("blackout_status") else None))
    ds = f.get("decisions") or []
    if ds:
        put("last_decision", ds[0].get("move"))
        put("votes", ds[0].get("votes"))
        put("dissent", ds[0].get("dissent"))
        put("last_move", f"{ds[0].get('date')} {ds[0].get('move')}")
        try:
            put("days_since", (clock.today() - dt.date.fromisoformat(ds[0]["date"])).days)
        except (KeyError, TypeError, ValueError):
            pass
    fo = f.get("focus") or {}
    put("focus", fo.get("label"))
    st = f.get("stability") or {}
    if f.get("changed_count") is not None:
        put("n_changes", f.get("changed_count"))
    # 就業
    ur = last("UNRATE")
    put("ur", fnum(ur, 1))
    if ur is not None and last("UNRATE", back=1) is not None:
        put("ur_chg", fnum(ur - last("UNRATE", back=1), 1, sign=True) + " 個百分點")
    sh = sahm_series(S)
    if sh:
        put("sahm", fnum(sh[-1]["value"], 2))
    nfp = last("PAYEMS", "d", 0.1)
    put("nfp", fnum(nfp, 1, sign=True))
    lab = C.get("labor") or {}
    put("month", lab.get("data_month"))
    km = lab.get("key_metrics") or {}
    if (km.get("nfp_3m") or {}).get("value") is not None:
        put("nfp3", fnum(km["nfp_3m"]["value"], 1, sign=True))
    put("lfpr", fnum(last("CIVPART"), 1))
    put("prime", fnum(last("LNS11300060"), 1))
    for sid, k in (("CIVPART", "lfpr_y"), ("LNS11300060", "prime_y")):
        r = rows_of(S, sid)
        y = _ago(r, 12)
        if r and y:
            put(k, fnum(r[-1]["value"] - y["value"], 1, sign=True) + " 個百分點")
    put("ahe_m", fnum(last("CES0500000003", "mom"), 1))
    put("ahe_y", fnum(last("CES0500000003", "yoy"), 1))
    a, c = last("CES0500000003", "yoy"), last("CPIAUCSL", "yoy")
    if a is not None and c is not None:
        put("real_ahe", fnum(a - c, 1, sign=True))
    ax = lab.get("axis") or {}
    put("loser_share", fnum(ax.get("jl_share"), 1) if ax.get("jl_share") is not None else None)
    put("z", fnum(ax.get("jl_z"), 2) if ax.get("jl_z") is not None else None)
    put("icsa", fnum(last("ICSA", sc=0.0001), 1))
    put("icsa4", fnum(last("IC4WSA", sc=0.0001), 1))
    put("ccsa", fnum(last("CCSA", sc=0.0001), 1))
    put("openings", fnum(last("JTSJOL", sc=0.1), 1))
    j, un = last("JTSJOL"), None
    ju = rows_of(S, "JTSJOL")
    if ju:
        um = {r["date"]: r["value"] for r in rows_of(S, "UNEMPLOY")}
        if um.get(ju[-1]["date"]):
            put("vu", fnum(ju[-1]["value"] / um[ju[-1]["date"]], 2))
    put("quits", fnum(last("JTSQUR"), 1))
    put("layoffs", fnum(last("JTSLDR"), 1))
    rv = lab.get("revision") or {}
    if rv.get("two_month_net") is not None:
        put("rev2", fnum(rv["two_month_net"] / 10, 1, sign=True))
    # 通膨
    put("cpi_y", fnum(last("CPIAUCSL", "yoy"), 1))
    put("cpi_m", fnum(last("CPIAUCSL", "mom"), 1))
    put("core_m", fnum(last("CPILFESL", "mom"), 1))
    put("core_3m", fnum(last("CPILFESL", "a3"), 1))
    sm = (C.get("inflation") or {}).get("summary")
    if sm is not None:
        put("core_6m", fnum(getattr(sm, "core_6m", None), 1))
        put("core_pce_3m", fnum(getattr(sm, "pce_core_3m", None), 1))
        put("sc_3m", fnum(getattr(sm, "pce_supercore_3m", None), 1))
        put("sc_y", fnum(getattr(sm, "pce_supercore_12m", None), 1))
    put("core_y", fnum(last("CPILFESL", "yoy"), 1))
    put("pce_y", fnum(last("PCEPI", "yoy"), 1))
    cp = last("PCEPILFE", "yoy")
    put("core_pce", fnum(cp, 1))
    if cp is not None:
        put("pce_gap", fnum(cp - 2, 1, sign=True))
    cy, py = last("CPIAUCSL", "yoy"), last("PCEPI", "yoy")
    if cy is not None and py is not None:
        put("gap", fnum(cy - py, 1))
    cc = last("CPILFESL", "yoy")
    if cc is not None and cp is not None:
        put("core_gap", fnum(cc - cp, 1) + " 個百分點")
    put("shelter_y", fnum(last("CUSR0000SAH1", "yoy"), 1))
    put("shelter_m", fnum(last("CUSR0000SAH1", "mom"), 1))
    put("ppi_m", fnum(last("PPIFIS", "mom"), 1))
    put("core_ppi_m", fnum(last("PPIFES", "mom"), 1))
    put("median", fnum(last("MEDCPIM159SFRBCLE"), 1))
    put("eci_y", fnum(last("ECIALLCIV", "yoy"), 1))
    put("real_m", fnum(last("PCEC96", "mom"), 1))
    put("real_y", fnum(last("PCEC96", "yoy"), 1))
    put("saving", fnum(last("PSAVERT"), 1))
    put("energy_y", fnum(last("CPIENGSL", "yoy"), 1))
    put("mich1", fnum(last("MICH"), 1))
    put("be5", fnum(last("T5YIE"), 2))
    put("be10", fnum(last("T10YIE"), 2))
    put("be5y5y", fnum(last("T5YIFR"), 2))
    bm = rows_of(S, "T10YIE")
    y = _ago(bm, 1)
    if bm and y:
        put("be10_m", fnum((bm[-1]["value"] - y["value"]) * 100, 0, sign=True))
    sd = C.get("scenario") or {}
    sc = sd.get("scenario")
    if sc is not None:
        put("labor_state", sc.labor_state)
        put("infl_state", sc.infl_state)
        adj = [t for t in (sc.triggers or []) if getattr(t, "adjacent", False) and not t.met]
        if len(adj) >= 2:
            put("path1", adj[0].label), put("gap1", adj[0].distance.replace("還差 ", ""))
            put("path2", adj[1].label), put("gap2", adj[1].distance.replace("還差 ", ""))
        put("duration_pref", (sc.positioning or {}).get("債券存續期間"))
    tr = sd.get("trail") or []
    if tr:
        cur = (tr[-1]["labor"], tr[-1]["infl"])
        n = 0
        for t in reversed(tr):
            if (t["labor"], t["infl"]) != cur:
                put("prev_cell", f"就業 {t['labor']}、通膨 {t['infl']}")
                break
            n += 1
        put("months", n)
    du = {d["tenor"]: d for d in sd.get("duration") or []}
    if "10 年" in du:
        put("dur10", fnum(du["10 年"]["D"], 1))
        put("price_chg", fnum(du["10 年"]["D"] * -0.5, 1, sign=True))
    # 長端
    for k, sid in (("y2", "DGS2"), ("y10", "DGS10"), ("y30", "DGS30")):
        put(k, fnum(last(sid), 2))
    d10 = rows_of(S, "DGS10")
    if len(d10) > 1:
        put("d10", fnum((d10[-1]["value"] - d10[-2]["value"]) * 100, 0, sign=True))
        ys = [r for r in d10 if r["date"][:4] < d10[-1]["date"][:4]]
        if ys:
            put("ytd10", fnum((d10[-1]["value"] - ys[-1]["value"]) * 100, 0, sign=True))
    a10, a2, a3m = rows_of(S, "DGS10"), {r["date"]: r["value"] for r in rows_of(S, "DGS2")}, {r["date"]: r["value"] for r in rows_of(S, "DGS3MO")}
    s1 = [{"date": r["date"], "value": (r["value"] - a2[r["date"]]) * 100} for r in a10 if r["date"] in a2]
    s2 = [{"date": r["date"], "value": (r["value"] - a3m[r["date"]]) * 100} for r in a10 if r["date"] in a3m]
    if s1 and s2:
        put("s2s10", fnum(s1[-1]["value"], 0)), put("s3m10", fnum(s2[-1]["value"], 0))
        m1, m2 = _ago(s1, 1), _ago(s2, 1)
        if m1 and m2:
            put("s2s10_m", fnum(m1["value"], 0) + " bp"), put("s3m10_m", fnum(m2["value"], 0) + " bp")
    br = ((C.get("rates") or {}).get("le") or {}).get("brief") or {}
    if br.get("lv") and br.get("sp"):
        put("window", f"{br.get('from')} 至 {br.get('to')}")
        put("d2", fnum((br["lv"].get("2") or {}).get("d"), 0, sign=True))
        put("regime", "、".join(f"{k} {x.get('zh')}" for k, x in br["sp"].items()))
    put("real10", fnum(last("DFII10"), 2))
    put("tp10", fnum(last("THREEFYTP10"), 2))
    tp = rows_of(S, "THREEFYTP10")
    y = _ago(tp, 12)
    if y:
        put("tp10_y", fnum(y["value"], 2))
    rr = rows_of(S, "DFII10")
    ys = [r for r in rr if rr and r["date"][:4] < rr[-1]["date"][:4]]
    if rr and ys:
        put("real10_ytd", fnum((rr[-1]["value"] - ys[-1]["value"]) * 100, 0, sign=True))
    rf = ((C.get("rates") or {}).get("le") or {}).get("refunding") or {}
    put("next_refunding", rf.get("next"))
    bb = [b for b in (C.get("_watch_extra") or {}).get("buybacks") or [] if (b.get("date") or "") >= clock.today().isoformat()]
    if bb:
        put("next_buyback", bb[0].get("date")), put("range", bb[0].get("segment"))
        m = re.search(r"(\d+)", bb[0].get("max") or "")
        put("size", m.group(1) if m else None)
    put("ig", fnum((last("BAMLC0A0CM") or 0) * 100, 0) if last("BAMLC0A0CM") is not None else None)
    put("hy", fnum((last("BAMLH0A0HYM2") or 0) * 100, 0) if last("BAMLH0A0HYM2") is not None else None)
    for k, sid in (("ig_pct", "BAMLC0A0CM"), ("hy_pct", "BAMLH0A0HYM2"), ("vix_pct", "VIXCLS")):
        r = rows_of(S, sid)
        if r:
            end = dt.date.fromisoformat(r[-1]["date"])
            yrs = 1 if k == "vix_pct" else 5
            win = [x["value"] for x in r if x["date"] >= (end - dt.timedelta(days=365 * yrs)).isoformat()]
            if len(win) > 20:
                put(k, fnum(sum(1 for x in win if x <= r[-1]["value"]) / len(win) * 100, 0))
    # 報價
    for cid in ("spx", "ixic", "twii", "vix", "move", "wti", "brent", "gold", "dxy", "eurusd", "usdjpy", "usdcnh", "sofr"):
        ch = _chip(C, cid)
        if ch and ch.get("num") is not None:
            put(cid, _chip_fmt(ch, ch["num"]).replace("%", ""))
            if ch.get("pv"):
                put(cid + "_d", fnum((ch["num"] / ch["pv"] - 1) * 100, 2, sign=True))
            if ch.get("by"):
                put(cid + "_ytd", fnum((ch["num"] / ch["by"] - 1) * 100, 1, sign=True))
            if ch.get("bm"):
                put(cid + "_m", fnum((ch["num"] / ch["bm"] - 1) * 100, 1, sign=True))
    tw = _chip(C, "twd")
    if tw and tw.get("num") is not None:
        put("usdtwd", _chip_fmt(tw, tw["num"]))
    si = _chip(C, "sofr_iorb")
    if si and si.get("num") is not None:
        put("spread", fnum(si["num"], 0))
        iorb = rows_of(S, "IORB")
        if iorb:
            put("iorb", fnum(iorb[-1]["value"], 2))
    on = _chip(C, "onrrp")
    if on and on.get("num") is not None:
        put("onrrp", fnum(on["num"], 0))
        if on.get("bm") is not None:
            put("onrrp_m", fnum(on["num"] - on["bm"], 0, sign=True) + " 億美元")
    au = sorted(((C.get("rates") or {}).get("le") or {}).get("auctions") or [], key=lambda a: a.get("date") or "")
    if au:
        a0 = au[-1]
        zh = ((C.get("rates") or {}).get("le") or {}).get("tenor_zh") or {}
        put("tenor", zh.get(a0.get("term"), a0.get("term")))
        put("btc", fnum(a0.get("btc"), 2) if a0.get("btc") is not None else None)
        put("btc_avg", fnum(a0.get("avg_btc"), 2) if a0.get("avg_btc") is not None else None)
        put("tail", fnum(a0.get("tail_bp"), 1, sign=True) if a0.get("tail_bp") is not None else None)
        put("dealer", fnum(a0.get("dealer_pct"), 1) if a0.get("dealer_pct") is not None else None)
    e = C.get("_election")
    if isinstance(e, dict):
        for k in ("house", "senate"):
            x = e.get(k)
            if isinstance(x, dict) and x.get("dem") is not None:
                put(f"{k}_lead", "民主黨" if x["dem"] >= x["rep"] else "共和黨")
                put(f"{k}_p", f"{max(x['dem'], x['rep']) * 100:.0f}")
        put("days_to", e.get("days_to"))
    # ---- 第二十一批：練習題補欄位 ----
    from . import watch_calendar as wc
    if nm.get("date"):
        try:
            t = wc.taipei_time(dt.date.fromisoformat(nm["date"]), (14, 0))
            put("tpe_time", f"{t.month}/{t.day} {t:%H:%M}")
        except Exception:                          # noqa: BLE001
            pass
    fw = _chip(C, "fedwatch")
    if _fw_ok(fw):
        put("fw_label", fw.get("label")), put("fw_value", fw.get("value")), put("fw_delta", fw.get("delta"))
        h1 = _chip(C, "fw_h1")
        if _fw_ok(h1):
            put("fw_h1", f"{h1['label']} {h1['value']}")
    sep = f.get("sep") or {}
    ffr = ((sep.get("vars") or {}).get("ffr") or {}).get("median") or []
    if ffr and ffr[0] is not None and sep.get("years"):
        put("year", sep["years"][0]), put("dot_median", fnum(ffr[0], 3))
        put("longrun", fnum(ffr[-1], 3) if ffr[-1] is not None else None)
        if f.get("rate_mid") is not None:
            put("rate_mid", fnum(f["rate_mid"], 3))
            put("dot_gap", fnum((ffr[0] - f["rate_mid"]) * 100, 0, sign=True))
    cpv = ((sep.get("vars") or {}).get("core_pce") or {}).get("median") or []
    if cpv and cpv[0] is not None:
        put("sep_core", fnum(cpv[0], 1))
    put("shift_label", (f.get("shift") or {}).get("label"))
    wx = C.get("_watch_extra") or {}
    if wx:
        now = clock.now()
        up = []
        for x in wx.get("speeches") or []:
            et = x.get("et")
            if isinstance(et, dt.datetime):
                try:
                    tp = wc.taipei_time(et.date(), (et.hour, et.minute))
                except Exception:                  # noqa: BLE001
                    continue
                if now - dt.timedelta(hours=2) <= tp <= now + dt.timedelta(days=7):
                    up.append(x)
        put("n_speakers", len(up)), put("n_voters", sum(1 for x in up if x.get("voter")))
        ups = [a for a in wx.get("auctions") or [] if (a.get("date") or "") >= clock.today().isoformat()]
        if ups:
            put("n_auctions", len(ups))
            lg = next((a for a in ups if any(t in (a.get("years") or "") for t in ("10 年", "20 年", "30 年"))), None)
            if lg:
                put("next_long", f"{lg.get('date')} {lg.get('years')}")
    fc = sd.get("futures_curve") if isinstance(sd, dict) else None
    if fc:
        put("terminal", fnum(fc.get("terminal"), 2)), put("terminal_month", fc.get("terminal_month"))
    if tr and "prev_cell" not in v:
        put("prev_cell", f"同一格（過去 {len(tr)} 個月沒有換格）")
    nf = transform(rows_of(S, "PAYEMS"), "d", 0.1)
    if len(nf) >= 6:
        put("nfp6", fnum(sum(r["value"] for r in nf[-6:]) / 6, 1, sign=True))
        put("nfp3", v.get("nfp3") or fnum(sum(r["value"] for r in nf[-3:]) / 3, 1, sign=True))
    dc = lab.get("decomp") or {}
    if dc.get("delta_rate") is not None:
        put("ur_d", fnum(dc["delta_rate"], 1, sign=True))
        put("emp_c", fnum(dc.get("employment_effect"), 2, sign=True))
        put("lf_c", fnum(dc.get("laborforce_effect"), 2, sign=True))
    groups = (lab.get("attribution") or {}).get("groups") or []
    tops = []
    for g in groups:
        for m in re.finditer(r'data-tip="([^｜"]+)｜([+-]?[\d.]+) 萬人"', g.get("bars") or ""):
            tops.append((m.group(1), float(m.group(2))))
    if tops:
        tops.sort(key=lambda t: -abs(t[1]))
        put("top3", "、".join(f"{n}（{x:+.1f} 萬）" for n, x in tops[:3]))
        put("cyc", fnum(groups[0].get("sum"), 1, sign=True))
    rr = rv.get("rows") or []
    if rr:
        put("n_down", sum(1 for r in rr[-6:] if r["current"] < r["original"]))
    inf = C.get("inflation") or {}
    parts = sorted((inf.get("attribution") or {}).get("parts") or [], key=lambda x: -abs(x.get("value") or 0))
    if parts:
        put("top_parts", "、".join(f"{x['label']}（{x['value']:+.2f}）" for x in parts[:3]))
        put("contrib_total", fnum((inf.get("attribution") or {}).get("total"), 2))
        sh = next((x for x in parts if x["label"] == "住房"), None)
        if sh:
            put("shelter_c", fnum(sh["value"], 2, sign=True))
    from . import scenario as _scn
    put("low", fnum(getattr(_scn, "SC_LO", None), 1) if getattr(_scn, "SC_LO", None) is not None else None)
    put("high", fnum(getattr(_scn, "SC_HI", None), 1) if getattr(_scn, "SC_HI", None) is not None else None)
    pn = inf.get("pce_nowcast") or {}
    if pn.get("value") is not None:
        put("pce_nowcast", fnum(pn["value"], 2))
    put("trim", fnum(last("TRMMEANCPIM159SFRBCLE"), 1))
    eh = (inf.get("energy_headline") or {}).get("value") or ""
    m = re.search(r"[+-]?[\d.]+", eh)
    if m:
        put("energy_c", m.group(0))
    y5, y10 = last("DGS5"), last("DGS10")
    if y5 is not None and y10 is not None:
        put("fwd5y5y", fnum((((1 + y10 / 100) ** 10 / (1 + y5 / 100) ** 5) ** 0.2 - 1) * 100, 2))
    put("last_refunding", rf.get("date"))
    ta = rows_of(S, "TREAST")
    if ta:
        put("treast", fnum(ta[-1]["value"] / 1e6, 2))
        yb = _ago(ta, 12)
        if yb:
            put("treast_y", fnum((ta[-1]["value"] - yb["value"]) / 1e3, 0, sign=True))
    dbt = (C.get("rates") or {}).get("debt")
    if dbt is not None:
        put("debt_gdp", fnum(dbt.debt_gdp, 1) if dbt.debt_gdp is not None else None)
        put("deficit_gdp", fnum(abs(dbt.deficit_gdp), 1) if dbt.deficit_gdp is not None else None)
        put("int_rev", fnum(dbt.interest_to_revenue, 1) if dbt.interest_to_revenue is not None else None)
    gr = [r for r in (((C.get("rates") or {}).get("le") or {}).get("global") or {}).get("rows") or [] if r.get("value") is not None]
    if gr:
        put("global_rows", "、".join(f"{r['name']} {fnum(r['value'], 2)}%" for r in gr))
    hsx = (C.get("rates") or {}).get("hyperscalers")
    if hsx is not None and getattr(hsx, "companies", None):
        put("hs_span", hsx.period_span or hsx.as_of)
        put("capex_total", fnum(hsx.total_capex, 1)), put("capex_yoy", fnum(hsx.capex_yoy, 0))
        put("hs_issued", fnum(hsx.total_issued, 1))
    so, io = rows_of(S, "SOFR"), {r["date"]: r["value"] for r in rows_of(S, "IORB")}
    sp20 = [(r["value"] - io[r["date"]]) * 100 for r in so if r["date"] in io][-20:]
    if sp20:
        put("spread20", fnum(sum(sp20) / len(sp20), 1))
    srf = _chip(C, "srf")
    if srf and srf.get("value"):
        put("srf", srf["value"])
    tx = _chip(C, "txf")
    if tx and tx.get("value") and "失敗" not in str(tx.get("value")):
        put("txf", tx["value"]), put("txf_chg", tx.get("delta") or "")
    rows_w = _week_rows(C, weeks=4)
    if len(rows_w) >= 2:
        hi = [r for r in rows_w if r.get("impact") == "high"] or rows_w
        rest = [r for r in rows_w if r is not hi[0]]
        put("event1", hi[0]["name"]), put("time1", _tpe(hi[0]))
        put("event2", rest[0]["name"]), put("time2", _tpe(rest[0]))
    return v


class _Strict(string.Formatter):
    def get_value(self, key, args, kwargs):
        if key not in kwargs:
            raise KeyError(key)
        return kwargs[key]


def fill_practice(tpl: str, vals: dict) -> str | None:
    try:
        return _Strict().format(tpl, **vals)
    except (KeyError, IndexError, ValueError):
        return None


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
def href_label(h: str) -> str:
    page, _, anc = (h or "/").partition("#")
    pn = PAGE_NAMES.get(page, "")
    an = _ANCHOR_BY_PAGE.get((page, anc)) or ANCHOR_NAMES.get(anc, "")
    return pn + ("・" + an if an else "")


def learn_html(key: str, L: dict, vals: dict, open_: bool = False, flat: bool = False) -> str:
    t = L.get(key)
    if not t:
        return ""
    chain = "".join(f"<i>{esc(s.rstrip('。'))}</i>" + ("<em>→</em>" if i < len(t["chain"]) - 1 else "")
                    for i, s in enumerate(t.get("chain") or []))
    rows = [("① 一句話", esc(t.get("one", ""))), ("② 怎麼來的", esc(t.get("origin", ""))),
            ("③ 怎麼看", esc(t.get("read", ""))), ("④ 跟利率的關係", f'<span class="ask-chain">{chain}</span>'),
            ("⑤ 常見誤讀", esc(t.get("myth", "")))]
    pr = fill_practice(t.get("practice", ""), vals)
    if pr:
        rows.append(("⑥ 用今天的數字練習", esc(pr)))
    body = "".join(f'<div class="ask-l"><h4>{h}</h4><p>{p}</p></div>' for h, p in rows)
    q = t.get("quiz") or {}
    if q.get("opts"):
        opts = "".join(f'<button type="button" class="ask-opt" data-ok="{1 if i == q.get("ans") else 0}">'
                       f'{"ABC"[i]}. {esc(o)}</button>' for i, o in enumerate(q["opts"]))
        body += (f'<div class="ask-quiz"><b>小測驗：{esc(q.get("q"))}</b>{opts}'
                 f'<div class="ask-why" hidden>正解 {"ABC"[q.get("ans", 0)]}。{esc(q.get("why") or "")}</div></div>')
    body += (f'<div class="ask-src">出處：{esc(t.get("source", ""))}'
             + ("　·　含本站規則（非官方說法）" if t.get("site_rule") else "") + "<br>教學內容，不構成投資建議。</div>")
    if flat:
        return f'<div class="ask-learn ask-flat">{body}</div>'
    return (f'<details class="ask-learn"{" open" if open_ else ""}><summary><b>這個指標怎麼看</b>'
            f'<span>{esc(t.get("title", ""))}：{esc(t.get("one", ""))}</span></summary>{body}</details>')


def table_html(tb) -> str:
    if not tb:
        return ""
    head, rows = tb
    if not rows:
        return ""
    th = "".join(f"<th>{esc(h)}</th>" for h in head)
    tr = "".join("<tr>" + "".join(f"<td>{esc(c if c is not None else '—')}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="ask-tw"><table class="ask-tbl"><tr>{th}</tr>{tr}</table></div>'


_TITLES: dict = {}


def card_html(card: dict, out: Out | None, L: dict, vals: dict) -> str:
    h = card.get("h") or "/"
    go = f'<a class="ask-go" href="{esc(h)}">看完整分析 → {esc(href_label(h))}</a>'
    if out is None:
        return (f'<article class="ask-card" data-id="{esc(card["id"])}"><h2>{esc(card["q"])}</h2>'
                f'<div class="ask-meta">{esc(card["c"])}</div>'
                f'<p class="ask-ans">這一項本次沒有取得資料（資料來源暫時抓不到，或尚未公布）。可以到原頁面看最近一次的結果。</p>'
                f'{go}{learn_html(card.get("l", ""), L, vals)}</article>')
    ch = out.get("chart") or ""
    chl = out.get("chart_long") or ""
    graph = ""
    if ch:
        if chl:
            graph = (f'<div class="ask-ch"><div class="ask-pt"><button type="button" class="on" data-p="n">'
                     f'{ {"d": "一年", "w": "半年", "m": "兩年", "q": "三年"}.get(out.get("freq", "m"), "預設") }</button>'
                     f'<button type="button" data-p="l">五年</button></div><div class="ask-cv" data-v="n">{ch}</div>'
                     f'<div class="ask-cv" data-v="l" hidden>{chl}</div></div>')
        else:
            graph = f'<div class="ask-ch">{ch}</div>'
    note = f'<div class="ask-note">{esc(out["note"])}</div>' if out.get("note") else ""
    date = out.get("date") or ""
    ans = out.get("ans", "")
    wy = card.get("wy")
    if wy and wy in _TITLES:
        # 問「為什麼」但命中的是數值卡時，指向拆解原因的那張卡
        ans += (f' <span class="ask-x" data-int="原因" hidden>想知道原因：'
                f'<a data-id="{esc(wy)}">{esc(_TITLES[wy])}</a></span>')
    return (f'<article class="ask-card" data-id="{esc(card["id"])}"><h2>{esc(out.get("title") or card["q"])}</h2>'
            f'<div class="ask-meta">{esc(card["c"])}' + (f'　·　資料 {esc(date)}' if date else "") + '</div>'
            f'<p class="ask-ans">{ans}</p>{graph}{table_html(out.get("table"))}{note}{go}'
            f'{learn_html(card.get("l", ""), L, vals)}</article>')


def term_html(key: str, term: dict, L: dict, vals: dict, data_cards: list[dict]) -> str:
    t = L.get(key) or {}
    links = "".join(f'<a href="?q={esc(c["q"])}" data-card="{esc(c["id"])}">{esc(c["q"])}</a>' for c in data_cards[:6])
    return (f'<article class="ask-card ask-term" data-id="t_{esc(key)}"><h2>什麼是{esc(term.get("t") or t.get("title"))}？</h2>'
            f'<div class="ask-meta">名詞　·　{esc(t.get("section", ""))}</div>'
            + (f'<div class="ask-k">看即時數據</div><div class="ask-qs">{links}</div>' if links else "")
            + learn_html(key, L, vals, flat=True) + '</article>')


# ---------------------------------------------------------------------------
# 組裝
# ---------------------------------------------------------------------------
def index_cards(cfg: dict, L: dict) -> list[dict]:
    """判讀器用的卡片清單（只看設定檔，不看資料）。"""
    out = []
    for card in cfg.get("cards") or []:
        out.append({"i": card["id"], "q": card["q"], "c": card["c"], "k": card.get("k") or [],
                    "w": card.get("w") or [], "m": card.get("m") or [], "n": card.get("n") or [],
                    "p": card.get("p") or [],
                    "x": card.get("x") or [], "r": card.get("r") or [], "l": card.get("l") or ""})
    for key, term in (cfg.get("terms") or {}).items():
        if key not in L:
            continue
        dc = [c for c in cfg.get("cards") or [] if c.get("l") == key]
        out.append({"i": f"t_{key}", "q": f"什麼是{term.get('t') or L[key]['title']}？", "c": "名詞",
                    "k": term.get("k") or [], "w": [], "m": [], "n": ["定義"],
                    "x": [f"{k}是什麼" for k in (term.get("k") or [])[:2]], "r": [c["id"] for c in dc[:3]],
                    "l": key, "t": 1})
    return out


def build_index(root: Path = ROOT) -> dict:
    cfg, L = load_config(root)
    return {"v": 1, "rules": cfg.get("rules") or {}, "s2t": (cfg.get("s2t") or "").replace(" ", ""),
            "syn": cfg.get("syn") or [], "ints": cfg.get("ints") or {}, "per": cfg.get("per") or {},
            "oos": cfg.get("oos") or [], "oosNear": cfg.get("oos_near") or [],
            "cards": index_cards(cfg, L), "cats": list(CATS)}


def build(C: dict, S: dict, root: Path = ROOT) -> dict:
    """回傳 {"index": 判讀索引, "frags": {id: html}, "stats": {...}}。"""
    cfg, L = load_config(root)
    vals = practice_vals(C, S)
    _TITLES.clear()
    _TITLES.update({c["id"]: c["q"] for c in cfg.get("cards") or []})
    frags: dict = {}
    ok = miss = 0
    outs = {}
    for card in cfg.get("cards") or []:
        sp = card.get("src") or {}
        out = None
        try:
            if "chip" in sp:
                out = chip_card(card, S, C)
            elif "s" in sp:
                out = series_card(card, S, C)
            elif "fn" in sp:
                out = FNS[sp["fn"]](card, S, C)
        except Exception as e:                     # noqa: BLE001
            log.warning("偷懶頁卡片 %s 產生失敗（%s）", card["id"], e)
            out = None
        ok += out is not None
        miss += out is None
        outs[card["id"]] = out
        if out is not None and out.get("title"):
            _TITLES[card["id"]] = out["title"]       # 連結也用當期的標題（失業率為什麼下降？）
    for card in cfg.get("cards") or []:
        frags[card["id"]] = card_html(card, outs[card["id"]], L, vals)
    for key, term in (cfg.get("terms") or {}).items():
        if key in L:
            dc = [c for c in cfg.get("cards") or [] if c.get("l") == key]
            frags[f"t_{key}"] = term_html(key, term, L, vals, dc)
    index = build_index(root)
    for c in index["cards"]:
        o = outs.get(c["i"])
        if o is not None and o.get("title"):
            c["x"] = c["x"] + [c["q"]]           # 原標題仍當範例問句，判讀不受影響
            c["q"] = o["title"]
    n_prac = sum(1 for k, t in L.items() if fill_practice(t.get("practice", ""), vals))
    return {"index": index, "frags": frags,
            "stats": {"cards": len(index["cards"]), "data_ok": ok, "data_missing": miss,
                      "practice": n_prac, "learn": len(L)}}
