"""
今日市場焦點（首頁 hero 之上的窄條）。

三顆數字＋一段焦點文字：
  10 年期／30 年期殖利率（FRED，較前一交易日的變動）
  2026 年底升息一碼機率（聯邦基金期貨自算——見下）
  市場焦點一段（Google News RSS 爬標題，Gemini 只挑重點寫敘述）

分工原則（跟潤稿層同一套哲學）
------------------------------
事實由爬蟲拿、AI 只整理敘述。

FedWatch 機率的三層來源（依序退回）
----------------------------------
FedWatch 與 Bloomberg WIRP 都不是原始資料——兩者都是從 CME 的
30 天期聯邦基金期貨（ZQ）價格反推的。所以第一層直接用同一套算法自算：

  ① **期貨自算**：Yahoo Finance 延遲報價抓 2027 年 1 月合約（1 月沒有
     FOMC 會議，整月平均利率 ≈ 12 月會議之後的利率，繞開「會期跨月
     加權」）。隱含利率＝100 − 價格；
     升息一碼機率＝(隱含利率 − 目前目標區間中點) ÷ 0.25，鎖 0–100。
     數字是可驗算的規則，不再是 AI 抄的。
  ② **Gemini 搜尋擷取**（僅在①失敗時）：這違反「AI 不碰數字」原則，
     所以只當備援，畫面明標「AI 擷取，僅供參考」。
  ③ **沿用前值**（≤4 天）：兩層都失敗時沿用快取並標明日期。

共用防護欄：合理範圍檢查、單日跳動 >20pp 視為擷取錯誤沿用前值、
每日快取（一天最多算一次）、失敗顯示「—」不編造。

焦點段的防護欄
--------------
① 只能用標題裡已有的資訊——輸出裡的每一串數字都必須出現在輸入標題裡
② 長度上限（config 可調），超過就退回
③ API 掛掉／驗證沒過 → 退回「直接列前幾條標題」——沒有 AI 也有東西看
④ 同一批標題只呼叫一次（標題集合做雜湊快取），一天最多兩三次 API

任何一步失敗都不影響主流程：這一條掛了，首頁其他區塊照常產出。
"""

from __future__ import annotations

import re
import json
import math
import hashlib
import logging
import calendar
import datetime as dt
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote
import html as _html

import requests

from .. import clock
from .brief import cjk_len

log = logging.getLogger(__name__)

# 逾時 8 秒：報價與 RSS 端點正常都在一兩秒內回應，撐到逾時的幾乎都是
# 被限流或被擋——20 秒只是把「注定失敗」拖長。8 秒已含網路抖動的餘裕。
TIMEOUT = 8
RSS_URL = ("https://news.google.com/rss/search?q={q}"
           "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant")

DEFAULT_KEYWORDS = [
    "川普 聯準會", "Fed 利率", "Kevin Warsh", "美國財政部", "貝森特",
    "美債 殖利率", "債券市場", "美伊",
]


# ---------------------------------------------------------------------------
# 殖利率：官方日資料為主；Yahoo 盤中以獨立指標顯示
# ---------------------------------------------------------------------------
def _yield_chip(rows: list, label: str) -> dict | None:
    rows = [r for r in (rows or []) if r.get("value") is not None]
    if len(rows) < 2:
        return None
    last, prev = rows[-1], rows[-2]
    return {"label": label, "value": last["value"],
            "delta_bp": round((last["value"] - prev["value"]) * 100),
            "date": last.get("date", ""), "source": last.get("source") or "FRED"}


def _yahoo_prev_close(res0: dict) -> float | None:
    """
    前一交易日收盤：從日線自己找，不信 chartPreviousClose——那是「圖表
    區間開始前」的收盤，range=5d 時可能是五天前，變動就變成五日變動。
    最後一根若就是今天這根（同一天，或收盤價等於目前價——期貨夜盤的
    日線日期會跟成交時間對不上），昨收是倒數第二根；否則是最後一根。
    沒有日線才退 previousClose → chartPreviousClose。
    與 netlify/functions/quotes.mjs 的 prevClose 同一條規則。
    """
    meta = res0.get("meta") or {}
    ts = res0.get("timestamp") or []
    q = ((res0.get("indicators") or {}).get("quote") or [{}])[0] or {}
    cl = q.get("close") or []
    bars = [(t, c) for t, c in zip(ts, cl) if t is not None and c is not None]
    cur, rmt = meta.get("regularMarketPrice"), meta.get("regularMarketTime")
    if bars and rmt is not None and cur is not None:
        off = int(meta.get("gmtoffset") or 0)

        def _day(x):
            return (int(x) + off) // 86400
        last = bars[-1]
        is_cur = (_day(last[0]) == _day(rmt)
                  or abs(float(last[1]) - float(cur))
                  <= 1e-9 * max(1.0, abs(float(cur))))
        if not is_cur:
            return float(last[1])
        if len(bars) >= 2:
            return float(bars[-2][1])
    for k in ("previousClose", "chartPreviousClose"):
        if meta.get(k) is not None:
            return float(meta[k])
    return None


def _period_bases_d(points, ref: str) -> dict:
    """同 _period_bases，另外帶基準日（點開說明要寫「對 9/30 收盤」）。"""
    out = {"bm": None, "by": None, "bmd": "", "byd": ""}
    if not ref or len(ref) < 10:
        return out
    m0, y0 = ref[:7] + "-01", ref[:4] + "-01-01"
    for d, v in points:
        if v is None:
            continue
        if d < m0:
            out["bm"], out["bmd"] = v, d
        if d < y0:
            out["by"], out["byd"] = v, d
    return out


def _period_bases(points, ref: str) -> tuple:
    """
    MTD／YTD 的基準（第十八批）：points＝[(YYYY-MM-DD, 值)…] 依日期排序，
    ref＝最新資料日。MTD 基準＝參考月份**之前**最後一筆（上月底收盤），
    YTD 基準＝參考年份之前最後一筆（去年底收盤）。缺就回 None——寧可「—」。
    """
    if not ref or len(ref) < 10:
        return None, None
    m0, y0 = ref[:7] + "-01", ref[:4] + "-01-01"
    bm = by = None
    for d, v in points:
        if v is None:
            continue
        if d < m0:
            bm = v
        if d < y0:
            by = v
    return bm, by


def _yahoo_bases(res0: dict, scale=None) -> dict:
    """Yahoo 日線 → {"bm": 上月底收盤, "by": 去年底收盤}（交易所當地日期）。"""
    meta = res0.get("meta") or {}
    ts = res0.get("timestamp") or []
    cl = (((res0.get("indicators") or {}).get("quote") or [{}])[0] or {}).get("close") or []
    off = int(meta.get("gmtoffset") or 0)

    def _d(x):
        return dt.datetime.fromtimestamp(int(x) + off, dt.timezone.utc).date().isoformat()
    pts = [(_d(t), (scale(float(c)) if scale else float(c)))
           for t, c in zip(ts, cl) if t is not None and c is not None]
    rmt = meta.get("regularMarketTime")
    ref = _d(rmt) if rmt else (pts[-1][0] if pts else "")
    return _period_bases_d(pts, ref)


def _fred_bases_d(rows) -> dict:
    rows = [r for r in (rows or []) if r.get("value") is not None and not r.get("live")]
    if not rows:
        return {"bm": None, "by": None, "bmd": "", "byd": ""}
    return _period_bases_d([(str(r.get("date") or "")[:10], r["value"]) for r in rows],
                           str(rows[-1].get("date") or "")[:10])


def _fred_bases(rows) -> tuple:
    rows = [r for r in (rows or []) if r.get("value") is not None and not r.get("live")]
    if not rows:
        return None, None
    return _period_bases([(str(r.get("date") or "")[:10], r["value"]) for r in rows],
                         str(rows[-1].get("date") or "")[:10])


# CBOE 的殖利率指數：^TNX＝10 年期、^TYX＝30 年期。
# 慣例是「殖利率 ×10」（49.8 ＝ 4.98%），但 Yahoo 顯示上兩種格式都出現過
# ——所以拿到值之後做規範化（>20 就除以 10）再做合理範圍檢查。
YIELD_SYMBOLS = (("^TNX", "10 年期"), ("^TYX", "30 年期"))


def fetch_yahoo_yield(symbol: str, label: str, _get=None) -> dict | None:
    """
    即時殖利率 chip：目前報價（延遲約 15 分鐘）與較前一交易日收盤的變動。

    FRED 的日頻序列要隔一個交易日才有值——首頁的「今日」焦點條掛著
    昨天的數字不太對勁。抓不到（Yahoo 擋 IP、格式變了）就回 None，
    由呼叫端退回 FRED 版 chip，小字會標明來源。
    """
    get = _get or (lambda url: requests.get(
        url, timeout=TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0 (macro-dashboard)"}))
    try:
        r = get(YQ_URL_1Y.format(sym=quote(symbol)))
        r.raise_for_status()
        res = (r.json().get("chart") or {}).get("result") or []
        meta = (res[0].get("meta") or {}) if res else {}
        cur = meta.get("regularMarketPrice")
        prev = _yahoo_prev_close(res[0]) if res else None
        ts = meta.get("regularMarketTime")
        if cur is None or prev is None:
            return None
        cur, prev = float(cur), float(prev)
        _x10 = cur > 20.0
        bases = _yahoo_bases(res[0], (lambda v: v / 10.0) if _x10 else None)
        if cur > 20.0:                    # ×10 慣例 → 換算回百分比
            cur, prev = cur / 10.0, prev / 10.0
        if not (0.1 <= cur <= 15.0 and 0.1 <= prev <= 15.0):
            log.warning("Yahoo 殖利率 %s 數值異常（%.2f／%.2f），不採用",
                        symbol, cur, prev)
            return None
        date = ""
        if ts:
            try:
                date = dt.datetime.fromtimestamp(
                    int(ts), dt.timezone.utc).date().isoformat()
            except (ValueError, TypeError, OSError):
                date = ""
        return {"label": label, "value": round(cur, 2),
                "delta_bp": round((cur - prev) * 100),
                "date": date, "live": True, **bases}
    except Exception as e:                         # noqa: BLE001
        log.warning("Yahoo 殖利率 %s 抓取失敗（%s），盤中指標暫缺", symbol, e)
        return None


# DGS 序列升級成即時時，單日跳動的合理上限（百分點）。
# 近年最劇烈的單日波動也在 0.3 以內；超過 0.6 幾乎必是報價鏈出錯
#（×10 慣例沒換算到、抓錯商品），寧可退回收盤值也不上壞數字。
LIVE_JUMP_CAP = 0.60

# FRED 序列 ↔ Yahoo 即時代號的對照（與 YIELD_SYMBOLS 同一組標的）。
LIVE_SERIES = (("^TNX", "DGS10", "10 年期"), ("^TYX", "DGS30", "30 年期"))


def upgrade_yields_live(series: dict, _get=None) -> list[str]:
    """
    把 DGS10／DGS30 的最新值升級成即時報價：在 FRED 序列**尾端附加一列**
    （標 ``live: True``），讓長端頁與首頁長端區跟焦點條顯示同一個數字。

    為什麼是附加而不是取代：FRED 的 H.15 收盤要隔一至兩個交易日才出來，
    焦點條早就改用 Yahoo 即時了，結果同一個 10 年期在首頁上緣是今天的
    數字、長端區卻是兩天前的收盤——同站兩個數字，讀者只會當成錯字。

    規則（確定性，全在這裡）：
    ① **兩檔都成功才升級**。只升 10Y 不升 30Y 的話，30−10 斜率會拿
       今天的 10Y 減兩天前的 30Y，錯得比不升級還多——all-or-nothing。
    ② 即時日期必須**晚於** FRED 最後一列（同日代表收盤已出，不必疊）。
    ③ 與最後收盤差超過 LIVE_JUMP_CAP 個百分點視為報價鏈出錯，整組放棄。
    ④ 失敗只記 log，畫面安靜退回收盤值——即時是加分，不是必要條件。

    快照與資料庫不受影響：store 在 gather 階段已寫完，這裡改的是
    記憶體裡的序列。回傳升級說明字串列表（空＝沒升級），給呼叫端記 log。
    """
    pend, out = [], []
    for sym, sid, label in LIVE_SERIES:
        rows = series.get(sid) or []
        last = rows[-1] if rows else {}
        if last.get("value") is None:
            log.warning("殖利率即時升級：%s 沒有 FRED 底稿，整組放棄", sid)
            return []
        chip = fetch_yahoo_yield(sym, label, _get=_get)
        if not chip or not chip.get("date"):
            log.warning("殖利率即時升級：%s 抓不到即時報價，整組放棄", sym)
            return []
        if chip["date"] <= str(last.get("date") or ""):
            log.info("殖利率即時升級：%s 的 FRED 收盤已是 %s，不必疊",
                     sid, last.get("date"))
            return []
        if abs(chip["value"] - last["value"]) > LIVE_JUMP_CAP:
            log.warning("殖利率即時升級：%s 即時 %.2f 與收盤 %.2f 差逾 "
                        "%.2f 個百分點，判定報價鏈出錯，整組放棄",
                        sym, chip["value"], last["value"], LIVE_JUMP_CAP)
            return []
        pend.append((rows, {"date": chip["date"], "value": chip["value"],
                            "live": True}))
        out.append(f"{label} {chip['value']:.2f}%（{chip['date']}）")
    for rows, row in pend:
        rows.append(row)
    return out


# ---------------------------------------------------------------------------
# 自選 chip 目錄：各天期利率、流動性、油價、波動率
# ---------------------------------------------------------------------------
# Yahoo 即時報價的規格：代號、顯示名、合理範圍、單位、FRED 後備序列。
# 範圍是防呆（抓錯商品、格式變了），不是預測——超出就整顆退回 FRED 後備。
# MOVE 是唯一沒有 FRED 後備的（ICE 授權），Yahoo 掛掉只能標「擷取失敗」。
QUOTE_SPECS = {
    "gold": {"sym": "GC=F", "label": "黃金期貨", "lo": 300.0, "hi": 15000.0, "unit": " 美元／盎司", "fred": None, "digits": 2},
    "dxy": {"sym": "DX-Y.NYB", "label": "美元指數 DXY", "lo": 40.0, "hi": 180.0, "unit": "", "fred": None, "digits": 2},
    "twd": {"sym": "TWD=X", "label": "台幣 USD/TWD", "lo": 15.0, "hi": 60.0, "unit": " 元", "fred": "DEXTAUS", "digits": 3},
    "wti":   {"sym": "CL=F",  "label": "WTI 原油",   "lo": 10.0, "hi": 300.0,
              "unit": " 美元", "fred": "DCOILWTICO"},
    "brent": {"sym": "BZ=F",  "label": "Brent 原油", "lo": 10.0, "hi": 300.0,
              "unit": " 美元", "fred": "DCOILBRENTEU"},
    "vix":   {"sym": "^VIX",  "label": "VIX",        "lo": 5.0,  "hi": 100.0,
              "unit": "",      "fred": "VIXCLS"},
    "move":  {"sym": "^MOVE", "label": "MOVE",       "lo": 30.0, "hi": 300.0,
              "unit": "",      "fred": None},
    # 股市：道瓊、費城半導體（沒有 FRED 後備；整數顯示＋漲跌幅）
    "dji":   {"sym": "^DJI",  "label": "道瓊指數",   "lo": 10000.0,
              "hi": 100000.0, "unit": "", "fred": None, "fmt": "index"},
    "sox":   {"sym": "^SOX",  "label": "費城半導體", "lo": 500.0,
              "hi": 30000.0, "unit": "", "fred": None, "fmt": "index"},
    # 第十八批：S&P 500、NASDAQ 綜合指數、台灣加權指數、三組匯率
    "spx":   {"sym": "^GSPC", "label": "S&P 500", "lo": 1000.0,
              "hi": 30000.0, "unit": "", "fred": None, "fmt": "index"},
    "ixic":  {"sym": "^IXIC", "label": "NASDAQ 綜合", "lo": 3000.0,
              "hi": 100000.0, "unit": "", "fred": None, "fmt": "index"},
    "twii":  {"sym": "^TWII", "label": "台灣加權指數", "lo": 5000.0,
              "hi": 100000.0, "unit": "", "fred": None, "fmt": "index"},
    "eurusd": {"sym": "EURUSD=X", "label": "EUR/USD", "lo": 0.5, "hi": 2.0,
               "unit": "", "fred": None, "digits": 4},
    "usdjpy": {"sym": "JPY=X", "label": "USD/JPY", "lo": 50.0, "hi": 300.0,
               "unit": "", "fred": None, "digits": 2},
    "usdcnh": {"sym": "CNH=X", "label": "USD/CNH", "lo": 4.0, "hi": 12.0,
               "unit": "", "fred": None, "digits": 4},
}

# 預設顯示組（使用者未自選、關 JS、初次造訪都用這組）。
# 固定四格版面，預設就湊滿四顆；30 年期入列因為長端是本站主軸。
DEFAULT_CHIPS = ("dgs2", "dgs10", "dgs30", "fedwatch")


def fetch_yahoo_quote(symbol: str, lo: float, hi: float,
                      _get=None) -> dict | None:
    """
    泛用即時報價（油價、VIX、MOVE）：目前價與前一交易日收盤。

    跟 fetch_yahoo_yield 同一個端點與解析，但沒有殖利率的 ×10 慣例——
    合理範圍由呼叫端按商品給。抓不到或超出範圍回 None，退 FRED 後備。
    """
    get = _get or (lambda url: requests.get(
        url, timeout=TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0 (macro-dashboard)"}))
    try:
        r = get(YQ_URL_1Y.format(sym=quote(symbol)))
        r.raise_for_status()
        res = (r.json().get("chart") or {}).get("result") or []
        meta = (res[0].get("meta") or {}) if res else {}
        cur = meta.get("regularMarketPrice")
        prev = _yahoo_prev_close(res[0]) if res else None
        ts = meta.get("regularMarketTime")
        if cur is None or prev is None:
            return None
        cur, prev = float(cur), float(prev)
        bases = _yahoo_bases(res[0])
        for _k in ("bm", "by"):              # 基準超出合理範圍＝壞資料，只丟基準
            if bases.get(_k) is not None and not lo <= bases[_k] <= hi:
                bases[_k] = None
        if not (lo <= cur <= hi and lo <= prev <= hi):
            log.warning("Yahoo 報價 %s 超出合理範圍（%.2f／%.2f），不採用",
                        symbol, cur, prev)
            return None
        date = ""
        if ts:
            try:
                date = dt.datetime.fromtimestamp(
                    int(ts), dt.timezone.utc).date().isoformat()
            except (ValueError, TypeError, OSError):
                date = ""
        _ts = None
        if ts:
            try:
                _ts = dt.datetime.fromtimestamp(int(ts), dt.timezone.utc)
            except (ValueError, TypeError, OSError):
                _ts = None
        return {"value": cur, "prev": prev, "date": date, "live": True, "ts": _ts, **bases}
    except Exception as e:                         # noqa: BLE001
        log.warning("Yahoo 報價 %s 抓取失敗（%s）", symbol, e)
        return None


def _last2(rows) -> tuple:
    """FRED 序列的（最新值, 前一值, 最新日期），略過空值。"""
    rows = [r for r in (rows or []) if r.get("value") is not None]
    if not rows:
        return None, None, ""
    prev = rows[-2]["value"] if len(rows) > 1 else None
    return rows[-1]["value"], prev, str(rows[-1].get("date") or "")


def _at_or_before(rows, date: str):
    """不晚於 `date` 的最後一個值（IORB 配 SOFR 用——期別不能倒掛）。"""
    best = None
    for r in rows or []:
        if r.get("value") is None:
            continue
        if str(r.get("date") or "") <= date:
            best = r["value"]
        else:
            break
    return best


def _mk(cid, label, value, delta, direction, date, on=False, iso=""):
    _iso = len(date) >= 10 and date[4] == "-" and date[7] == "-"
    # iso：完整資料日，給前端盤中報價判斷「誰比較新」（畫面上只顯示月-日）
    return {"id": cid, "label": label, "value": value, "delta": delta,
            "dir": direction, "date": date[5:] if _iso else date,
            "iso": date[:10] if _iso else iso,
            "on": cid in DEFAULT_CHIPS or on}


def _attach(chip: dict, num, bm, by, kind: str, unit: str = "", *, bmd: str = "",
            byd: str = "", pv=None, pc: bool = False) -> dict:
    """
    MTD／YTD 用的數字（第十八批）：num＝目前值、bm／by＝上月底／去年底基準，
    kind＝變動怎麼算與怎麼寫（前端 _MODE_JS 同一套）：
      bp　值是百分比、變動寫 bp　　bp0　值本身就是 bp
      pct 漲跌幅 %　　　　　　　　　a0…a4 絕對變動（小數位數）　twd 升／貶
    """
    if num is None:
        return chip
    # 第十八批 v2：變動欄一律寫絕對差距；pc＝價格類，點開說明才給漲跌幅 %
    #（日＝對前一交易日 pv、MTD＝對 bmd 收盤、YTD＝對 byd 收盤）
    chip.update({"num": round(float(num), 6), "k": kind, "u": unit,
                 "bm": None if bm is None else round(float(bm), 6),
                 "by": None if by is None else round(float(by), 6),
                 "bmd": bmd or "", "byd": byd or "", "pc": bool(pc),
                 "pv": None if pv is None else round(float(pv), 6)})
    return chip


def _pct_chip(cid, label, rows):
    """百分比序列（天期利率、SOFR）：值 x.xx%、變動 ±bp 對前一日。"""
    v, p, d = _last2(rows)
    if v is None:
        return _mk(cid, label, "—", "缺資料", "", "")
    db = None if p is None else round((v - p) * 100)
    cls = "up" if (db or 0) > 0 else ("dn" if (db or 0) < 0 else "")
    b = _fred_bases_d(rows)
    return _attach(_mk(cid, label, f"{v:.2f}%",
                       f"{db:+d} bp" if db is not None else "—", cls, d), v, b["bm"], b["by"], "bp",
                   bmd=b["bmd"], byd=b["byd"], pv=p)


_QUOTE_UNSET = object()

def _level_chip(cid, spec, liq, offline, _get=None, _pre=_QUOTE_UNSET):
    """即時報價 chip（油價、VIX、MOVE）：Yahoo 主、FRED 後備。
    _pre 是呼叫端並行預抓的結果（避免逐顆串行等逾時）。
    日期新者勝：報價日不比 FRED 後備新（stale 成交）就退後備。"""
    if not offline:
        q = _pre if _pre is not _QUOTE_UNSET else fetch_yahoo_quote(
            spec["sym"], spec["lo"], spec["hi"], _get=_get)
        _, _, _fd = _last2((liq or {}).get(spec["fred"])
                           if spec.get("fred") else None)
        if q and _fd and (str(q.get("date") or "") < _fd if cid == "twd"
                         else str(q.get("date") or "") <= _fd):
            log.info("即時報價 %s 報價日 %s 不比 FRED %s 新，退後備",
                     spec["sym"], q.get("date"), _fd)
            q = None
        if q:
            dv = q["value"] - q["prev"]
            cls = "up" if dv > 0 else ("dn" if dv < 0 else "")
            if spec.get("fmt") == "index":
                pct = dv / q["prev"] * 100 if q["prev"] else 0.0
                chip = _mk(cid, spec["label"], f"{q['value']:,.0f}",
                           f"{dv:+,.0f}（{pct:+.2f}%）", cls, q["date"])
                chip["source"] = "Yahoo"
                return _attach(chip, q["value"], q.get("bm"), q.get("by"), "a0",
                               bmd=q.get("bmd", ""), byd=q.get("byd", ""), pv=q["prev"], pc=True)
            digits = spec.get("digits", 1)
            delta = (("貶" if dv > 0 else "升" if dv < 0 else "持平") + f"{abs(dv):.{digits}f}"
                     if cid == "twd" else f"{dv:+.{digits}f}")
            chip = _mk(cid, spec["label"], f"{q['value']:.{digits}f}{spec['unit']}", delta, cls, q["date"])
            chip["source"] = "Yahoo"
            return _attach(chip, q["value"], q.get("bm"), q.get("by"),
                           "twd" if cid == "twd" else f"a{digits}",
                           bmd=q.get("bmd", ""), byd=q.get("byd", ""), pv=q["prev"], pc=True)
    rows = (liq or {}).get(spec["fred"]) if spec.get("fred") else None
    v, p, d = _last2(rows)
    if v is None:
        return _mk(cid, spec["label"], "—", "本次擷取失敗", "", "")
    dv = None if p is None else v - p
    cls = "up" if (dv or 0) > 0 else ("dn" if (dv or 0) < 0 else "")
    digits = spec.get("digits", 1)
    delta = ("—" if dv is None else (("貶" if dv > 0 else "升" if dv < 0 else "持平") + f"{abs(dv):.{digits}f}"
             if cid == "twd" else f"{dv:+.{digits}f}"))
    chip = _mk(cid, spec["label"], f"{v:.{digits}f}{spec['unit']}", delta, cls, d)
    chip["source"] = "FRED"
    b = _fred_bases_d(rows)
    return _attach(chip, v, b["bm"], b["by"], "twd" if cid == "twd" else f"a{digits}",
                   bmd=b["bmd"], byd=b["byd"], pv=p, pc=True)


# 台指期：期交所行情頁背後使用的資料端點（**非官方 API**，可能改版）。
# 日盤（MarketType 0：08:45–13:45）與夜盤（1：15:00–次日 05:00）各問一次，
# 取時間較新的那一盤——使用者要的是「全天」的台指期，不只日盤。
#
# 兩個實測過的坑（2026-10-05，對著真實回應修的）：
#   ① 清單第一筆是「臺指現貨」（TXF-S／TXF-P），不是期貨——只認
#      TXF＋月份碼＋年尾數（TXFJ6-F、TXFJ6-M）這種期貨代號，取第一筆＝近月。
#   ② 夜盤的 CDate 是**開盤那天**：週五 15:00 開的夜盤，週六 04:59 的成交
#      CDate 仍是週五。直接拿 CDate＋CTime 比，夜盤永遠輸給同一天 13:45 的
#      日盤（畫面上只看得到日盤）。夜盤時間早於 15:00 的要把日期加一天。
TXF_URL = "https://mis.taifex.com.tw/futures/api/getQuoteList"
TXF_RANGE = (5000.0, 80000.0)
_TXF_FUT = re.compile(r"^TXF[A-Z]\d-[A-Z]$")


def _num(x):
    try:
        v = float(str(x).replace(",", ""))
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def _txf_when(cdate: str, ctime: str, night: bool):
    """期交所的 CDate／CTime（台北時間）→ 實際的 (YYYY-MM-DD, HHMMSS)。"""
    import datetime as _dt
    d = str(cdate or "")
    t = str(ctime or "").zfill(6)
    if len(d) != 8 or not d.isdigit() or not t.isdigit():
        return None
    day = _dt.date(int(d[:4]), int(d[4:6]), int(d[6:8]))
    if night and t < "150000":                     # 夜盤跨午夜：隔天凌晨
        day += _dt.timedelta(days=1)
    return day.isoformat(), t


def fetch_txf(_get_post=None) -> dict | None:
    """
    回傳 {value, prev, date, time, session, symbol}；失敗回 None。
    prev 是該盤的參考價（日盤＝前一日結算、夜盤＝當日日盤結算）。
    回應格式若對不上，會把第一筆的欄位名稱寫進 log——端點改版時一眼
    看得出來要改哪裡。
    """
    post = _get_post or (lambda url, body: requests.post(
        url, json=body, timeout=TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0 (macro-dashboard)",
                 "Referer": "https://mis.taifex.com.tw/futures/"}))
    best = None
    for mkt, session in (("0", "日盤"), ("1", "夜盤")):
        body = {"MarketType": mkt, "SymbolType": "F", "KindID": "1",
                "CID": "TXF", "ExpireMonth": "", "RowSize": "全部",
                "PageNo": "", "SortColumn": "", "AscDesc": "A"}
        try:
            r = post(TXF_URL, body)
            r.raise_for_status()
            rows = ((r.json() or {}).get("RtData") or {}).get("QuoteList") or []
        except Exception as e:                     # noqa: BLE001
            log.warning("台指期（%s）抓取失敗（%s）", session, e)
            continue
        # 近月＝第一筆期貨代號（清單依到期月排序；現貨列不算）
        row = next((x for x in rows
                    if _TXF_FUT.match(str(x.get("SymbolID") or ""))), None)
        last = _num((row or {}).get("CLastPrice"))
        ref = _num((row or {}).get("CRefPrice"))
        when = row and _txf_when(row.get("CDate"), row.get("CTime"), mkt == "1")
        if not (row and last and ref and when
                and TXF_RANGE[0] <= last <= TXF_RANGE[1]):
            log.warning("台指期（%s）回應裡找不到可用的近月報價（第一筆欄位："
                        "%s）", session, ", ".join(list(rows[0])[:12])
                        if rows else "無資料")
            continue
        day, tm = when
        cand = {"value": last, "prev": ref, "date": day,
                "time": f"{tm[:2]}:{tm[2:4]}", "session": session,
                "symbol": str(row.get("SymbolID")), "_key": day + tm}
        if best is None or cand["_key"] > best["_key"]:
            best = cand
    if best:
        best.pop("_key", None)
    return best


def _txf_chip(q: dict | None) -> dict:
    if not q:
        return _mk("txf", "台指期", "—", "本次擷取失敗", "", "")
    dv = q["value"] - q["prev"]
    pct = dv / q["prev"] * 100 if q["prev"] else 0.0
    cls = "up" if dv > 0 else ("dn" if dv < 0 else "")
    when = q["session"] + (f" {q['date'][5:]}" if q.get("date") else "")
    return _mk("txf", "台指期", f"{q['value']:,.0f}",
               f"{dv:+,.0f}（{pct:+.2f}%）", cls, when,
               iso=q.get("date") or "")


def build_catalog(rates_series: dict | None, liq_series: dict | None,
                  fresh_yields: list | None, offline: bool,
                  _get=None, fw: dict | None = None,
                  _post=None, election: dict | None = None) -> list[dict]:
    """
    焦點條的完整 chip 目錄（含可選盤中指標）。每顆：id、短標籤、顯示值、
    對前一日收盤的變動、方向色、資料日（月-日）、是否預設顯示。

    fedwatch 是佔位（special）：機率 chip 的分層來源標示已經在
    pages/home.py 有一套完整邏輯，目錄只負責排位置，不重刻一份。
    """
    rs, liq = rates_series or {}, liq_series or {}
    chips: list[dict] = []
    # Primary tenors always use the same official daily history as charts.
    for cid, sid, label in (("dgs3mo", "DGS3MO", "3 個月"),
                            ("dgs2", "DGS2", "2 年期"),
                            ("dgs5", "DGS5", "5 年期"),
                            ("dgs7", "DGS7", "7 年期"),
                            ("dgs10", "DGS10", "10 年期"),
                            ("dgs20", "DGS20", "20 年期"),
                            ("dgs30", "DGS30", "30 年期")):
        rows = [r for r in rs.get(sid) or [] if not r.get("live")]
        chip = _pct_chip(cid, label, rows)
        chip["source"] = (rows[-1].get("source") or "FRED") if rows else ""
        chips.append(chip)
    # Optional intraday indicators have separate IDs and never overwrite history.
    fresh = {c["label"]: c for c in fresh_yields or [] if c.get("live")}
    specs = (("live_dgs10", "10 年期", "^TNX"), ("live_dgs30", "30 年期", "^TYX"))
    quotes = dict(zip((cid for cid, _, _ in specs), _pmap(
        lambda t: (fresh.get(t[1]) or fetch_yahoo_yield(t[2], t[1], _get=_get))
                  if not offline else None, specs)))
    for cid, label, _ in specs:
        q = quotes.get(cid)
        if q:
            bp = q.get("delta_bp")
            chip = _mk(cid, label + "盤中", f"{q['value']:.2f}%",
                       f"{bp:+d} bp" if bp is not None else "—",
                       "up" if (bp or 0) > 0 else "dn" if (bp or 0) < 0 else "", q.get("date") or "")
            _attach(chip, q["value"], q.get("bm"), q.get("by"), "bp",
                    bmd=q.get("bmd", ""), byd=q.get("byd", ""),
                    pv=None if bp is None else q["value"] - bp / 100)
        else:
            chip = _mk(cid, label + "盤中", "—", "擷取失敗", "", "")
        chip["source"] = "Yahoo"
        chips.append(chip)
    # 升降息：下次會議機率＋目標會議單場＋累計（三顆一般 chip）
    for _c in fw_chips(fw):
        _c["on"] = _c["id"] in DEFAULT_CHIPS
        chips.append(_c)
    # ---- 流動性 ----
    chips.append(_pct_chip("sofr", "SOFR", liq.get("SOFR")))
    # SOFR−IORB：資金價格對地板的距離。IORB 取「不晚於 SOFR 日」的值，
    # 期別不倒掛；轉正＝準備金趨緊（2019-09 回購事件即此訊號先爆）。
    sv, _, sd = _last2(liq.get("SOFR"))
    iv = _at_or_before(liq.get("IORB"), sd) if sv is not None else None
    if sv is not None and iv is not None:
        spread = (sv - iv) * 100
        srows = [r for r in (liq.get("SOFR") or [])
                 if r.get("value") is not None]
        d_disp, cls = "—", ""
        if len(srows) > 1:
            s2, d2 = srows[-2]["value"], str(srows[-2].get("date") or "")
            i2 = _at_or_before(liq.get("IORB"), d2)
            if i2 is not None:
                dd = spread - (s2 - i2) * 100
                d_disp = f"{dd:+.0f} bp"
                cls = "up" if dd > 0 else ("dn" if dd < 0 else "")
        _sp = [(str(r.get("date") or "")[:10],
                (r["value"] - _iv) * 100)
               for r in srows
               for _iv in [_at_or_before(liq.get("IORB"), str(r.get("date") or ""))]
               if _iv is not None]
        _b = _period_bases_d(_sp, str(sd)[:10])
        chips.append(_attach(_mk("sofr_iorb", "SOFR−IORB", f"{spread:+.0f} bp",
                                 d_disp, cls, sd), spread, _b["bm"], _b["by"], "bp0", " bp",
                             bmd=_b["bmd"], byd=_b["byd"]))
    else:
        chips.append(_mk("sofr_iorb", "SOFR−IORB", "—", "缺資料", "", ""))
    # ON RRP：FRED 單位是十億美元 → 顯示成億美元（×10）。
    v, p, d = _last2(liq.get("RRPONTSYD"))
    if v is not None:
        dv = None if p is None else (v - p) * 10
        cls = "up" if (dv or 0) > 0 else ("dn" if (dv or 0) < 0 else "")
        _b = _fred_bases_d(liq.get("RRPONTSYD"))
        chips.append(_attach(_mk("onrrp", "ON RRP", f"{v * 10:,.0f} 億美元",
                                 f"{dv:+,.0f} 億" if dv is not None else "—", cls, d),
                             v * 10, None if _b["bm"] is None else _b["bm"] * 10,
                             None if _b["by"] is None else _b["by"] * 10, "a0", " 億",
                             bmd=_b["bmd"], byd=_b["byd"]))
    else:
        chips.append(_mk("onrrp", "ON RRP", "—", "缺資料", "", ""))
    # SRF（隔夜回購動用）：零是常態也是資訊——體系不缺錢；非零轉警示色。
    v, p, d = _last2(liq.get("RPONTSYD"))
    if v is None:
        chips.append(_mk("srf", "SRF 動用", "—", "缺資料", "", ""))
    elif v < 0.05:                       # 五千萬美元以下視為未動用
        chips.append(_mk("srf", "SRF 動用", "0（未動用）", "", "", d))
    else:
        dv = None if p is None else (v - p) * 10
        chips.append(_mk("srf", "SRF 動用", f"{v * 10:,.1f} 億美元",
                         f"{dv:+,.1f} 億" if dv is not None else "—",
                         "up", d))
    # ---- 即時報價：油價與波動率（並行）----
    _qids = ("wti", "brent", "vix", "move", "dji", "spx", "ixic", "sox", "twii",
             "gold", "dxy", "twd", "eurusd", "usdjpy", "usdcnh")
    _quotes = dict(zip(_qids, _pmap(
        lambda c: None if offline else fetch_yahoo_quote(
            QUOTE_SPECS[c]["sym"], QUOTE_SPECS[c]["lo"],
            QUOTE_SPECS[c]["hi"], _get=_get), _qids)))
    for cid in _qids:
        chips.append(_level_chip(cid, QUOTE_SPECS[cid], liq, offline,
                                 _get=_get, _pre=_quotes.get(cid)))
    # 台指期（日盤＋夜盤取較新的那一盤）
    # 測試注入了 _get（GET 假物件）卻沒給 _post 時不打真網路
    _txf_live = not offline and (_post is not None or _get is None)
    chips.append(_txf_chip(fetch_txf(_get_post=_post) if _txf_live else None))
    # 期中選舉（Polymarket）：眾院、參院兩顆。卡片停用或過了顯示期就不放。
    if election:
        from .polymarket import chips as _pm_chips
        chips.extend(_pm_chips(election))
    return chips


# ---------------------------------------------------------------------------
# 新聞標題：Google News RSS
# ---------------------------------------------------------------------------




def fetch_headlines(keywords: list[str], hours: int = 30,
                    _get=None) -> list[dict]:
    """
    逐關鍵字打 RSS、收近 `hours` 小時的標題。單一關鍵字失敗就跳過——
    新聞條這種東西寧可少一組也不要整段消失。
    """
    get = _get or (lambda url: requests.get(
        url, timeout=TIMEOUT, headers={"User-Agent": "macro-dashboard/1.0"}))
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    out, seen = [], set()
    for kw in keywords:
        try:
            r = get(RSS_URL.format(q=quote(kw)))
            r.raise_for_status()
            root = ET.fromstring(r.content)
        except Exception as e:                     # noqa: BLE001
            log.warning("市場焦點：關鍵字「%s」抓取失敗（%s）", kw, e)
            continue
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = item.findtext("pubDate") or ""
            src = ""
            se = item.find("source")
            if se is not None and se.text:
                src = se.text.strip()
            if not title:
                continue
            try:
                at = parsedate_to_datetime(pub)
                if at.tzinfo is None:
                    at = at.replace(tzinfo=dt.timezone.utc)
            except (ValueError, TypeError):
                continue
            if at < cutoff:
                continue
            # 標題常帶「 - 來源」尾巴，去掉再去重
            core = re.sub(r"\s*[-–—]\s*[^-–—]{1,30}$", "", title)
            key = re.sub(r"\s+", "", core)[:40]
            if key in seen:
                continue
            seen.add(key)
            out.append({"title": title, "link": link, "source": src,
                        "at": at.isoformat(), "kw": kw})
    out.sort(key=lambda x: x["at"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# Yahoo 自家 RSS（直達文章頁）＋內文擷取
# ---------------------------------------------------------------------------
# 不經 Google News 的理由：它的連結是自家轉址頁，解回原始文章網址的方法
# 脆弱且常變；Yahoo 的 RSS 連結直達文章頁，內文抓得到，AI 才有東西摘。
# feed 網址放 config（feeds:），Yahoo 改版時不用改程式。
DEFAULT_FEEDS = [
    "https://tw.news.yahoo.com/rss/finance",
    "https://tw.stock.yahoo.com/rss?category=news",
    "https://finance.yahoo.com/news/rssindex",
    # 標題級來源：RSS 公開、內文有付費牆——貢獻標題與連結進標題池，
    # 內文抓不到會被長度檢查擋下、自動跳過（logged），不影響其他來源。
    # 路透／彭博的全文走 Yahoo 轉載的通訊社稿（上面三條已涵蓋）。
    "https://www.ft.com/rss/home",
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
]
_FEED_LABEL = (("tw.news.yahoo", "Yahoo奇摩新聞"),
               ("tw.stock.yahoo", "Yahoo奇摩股市"),
               ("finance.yahoo", "Yahoo Finance"),
               ("ft.com", "Financial Times"),
               ("dj.com", "Wall Street Journal"),
               ("dowjones", "Wall Street Journal"),
               # Google News 搜尋型 feed：網址裡的 site: 限定就是來源
               ("reuters", "Reuters"),
               ("bloomberg", "Bloomberg"),
               ("cnbc.com", "CNBC"),
               ("federalreserve.gov", "Federal Reserve"),
               ("feeds.finance.yahoo", "Yahoo Finance"))


# 內文注定抓不到的網域：Google News 是 JS 轉址中介頁（彭博、路透的搜尋
# 結果都是這種連結）、FT／WSJ 是付費牆。這些來源走「標題快訊」層——
# 標題＋RSS 官方摘要直接進材料包，不佔內文名額、不浪費抓取時間；
# 它們一樣算正式來源，主軸用到時會列在下方連結。
_HEADLINE_ONLY = ("news.google.com", "ft.com", "wsj.com", "dj.com")






def _headline_only(link: str) -> bool:
    return any(h in (link or "") for h in _HEADLINE_ONLY)




def _pmap(fn, items, workers: int = 6) -> list:
    """
    小型並行工具：對 items 逐一跑 fn，回傳**順序不變**的結果列表。
    抓報價與內文全是獨立的 I/O 等待，串行是之前整輪變慢的主因之一。
    單一項目丟例外就記 None——呼叫端本來就要處理抓不到的情況。
    """
    if len(items) <= 1:
        out = []
        for x in items:
            try:
                out.append(fn(x))
            except Exception:                      # noqa: BLE001
                out.append(None)
        return out
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as ex:
        futs = [ex.submit(fn, x) for x in items]
        out = []
        for f in futs:
            try:
                out.append(f.result())
            except Exception:                      # noqa: BLE001
                out.append(None)
        return out


def _chip_from_live_rows(rows, label: str) -> dict | None:
    """
    長端模組已把 Yahoo 即時值附加進 DGS 序列（最後一列帶 live 標記）時，
    直接用那筆資料做 chip——同一次執行不再重打 Yahoo（先前 ^TNX／^TYX
    被抓了兩次）。變動照樣是對前一列（FRED 收盤）。
    """
    rows = [r for r in (rows or []) if r.get("value") is not None]
    if not rows or not rows[-1].get("live") or len(rows) < 2:
        return None
    last, prev = rows[-1], rows[-2]
    return {"label": label, "value": round(float(last["value"]), 2),
            "delta_bp": round((last["value"] - prev["value"]) * 100),
            "date": str(last.get("date") or ""), "live": True}


def _feed_label(url: str) -> str:
    for key, label in _FEED_LABEL:
        if key in url:
            return label
    return re.sub(r"^https?://([^/]+).*$", r"\1", url)


# 關鍵字比對的「假朋友」：包含關鍵字字串、但講的是別的東西的詞。
# 實例：關鍵字「利率」把「聯電Q3毛利率上看36%」放進了市場焦點。
# 比對前先把這些詞從標題裡拿掉，剩下的字串還有命中才算數。
# 「殖利率」不在此列——它本來就是要抓的東西，被「利率」多算一次也無妨。
_FALSE_FRIENDS = ("毛利率", "淨利率", "獲利率", "中獎率")


def _kw_text(title: str) -> str:
    """關鍵字比對用的標題：先拿掉假朋友，再比對。"""
    for ff in _FALSE_FRIENDS:
        title = title.replace(ff, "")
    return title


def _kw_hit(word: str, title: str) -> bool:
    """單一關鍵詞是否命中。英文詞不分大小寫（FT/WSJ 的標題是英文，
    「Fed」「fed」「FED」都要算）；中文照原樣子字串比對。

    英文必須是**完整單字**（可帶複數 s／es）：先前只看字母有沒有出現，
    「AI」會命中 said、again、chain，「Fed」會命中 Federal、FedEx，
    幾乎所有英文標題都被當成相關新聞還被加分（2026-10 修正）。"""
    if word.isascii():
        pat = re.escape(word.lower()).replace(r"\ ", r"\s+")
        return re.search(r"(?<![A-Za-z0-9])" + pat
                         + r"(?:s|es)?(?![A-Za-z])", title.lower()) is not None
    return word in title


def _excluded(title: str, exclude: list[str] | None) -> bool:
    """
    排除清單：標題命中任一排除詞就整條剔除。

    擋的是正向關鍵字擋不掉的東西——**真的含關鍵字、但不是總經新聞**。
    實例：「專家談美債布局：長天期沒賺，不如押0050或高股息」確實含
    「美債」，但那是台股 ETF 理財文。清單在 config 的 exclude_keywords，
    看到新的雜訊詞直接往裡加，不用改程式。
    """
    return any(x and str(x) in title for x in (exclude or []))


def fetch_feed_headlines(feeds: list, keywords: list[str],
                         hours: int = 30, _get=None,
                         exclude: list[str] | None = None,
                         raw_out: list | None = None) -> list[dict]:
    """
    吃 RSS，只留**標題命中任一關鍵字詞**的項目。單一 feed 失敗就跳過。

    feeds 的每一項可以是網址字串，或 {url: ..., all: true}——all 的 feed
    本身就是主題專屬（聯準會新聞稿、演講、十年期殖利率新聞），不再用
    關鍵字過濾（演講標題常是「Speech by Governor X」，一個關鍵字都不含）。

    每條 feed 都記一行「取得 N 則、命中 M 則」：先前 Yahoo 那幾條 feed
    內容早就不是總經新聞了（滿版台股個股、加密貨幣），卻一直沒人發現。

    raw_out：有給的話，時間窗內**所有**項目（不經關鍵字與排除詞過濾）
    也收進這個列表——主題補充從同一批 feed 用各自的關鍵字再篩一次，
    不必把每條 feed 重抓一遍。
    """
    get = _get or (lambda url: requests.get(
        url, timeout=TIMEOUT, headers={"User-Agent": "macro-dashboard/1.0"}))
    words = _kw_words(keywords)
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    out, seen = [], {}
    for feed in feeds:
        url = feed if isinstance(feed, str) else str(feed.get("url") or "")
        take_all = (not isinstance(feed, str)) and bool(feed.get("all"))
        try:
            r = get(url)
            r.raise_for_status()
            root = ET.fromstring(r.content)
        except Exception as e:                     # noqa: BLE001
            log.warning("市場焦點：feed %s 抓取失敗（%s）", url, e)
            continue
        label = _feed_label(url)
        n_all = n_hit = 0
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = item.findtext("pubDate") or ""
            if not title or not link:
                continue
            n_all += 1
            try:
                at = parsedate_to_datetime(pub)
                if at.tzinfo is None:
                    at = at.replace(tzinfo=dt.timezone.utc)
            except (ValueError, TypeError):
                continue
            if at < cutoff:
                continue
            # RSS 的官方摘要（FT／WSJ／CNBC 的 description 是出版社自己寫的
            # 一兩句話，合法免費）：付費牆來源靠它補一點實質內容。
            desc = _html.unescape(re.sub(
                r"<[^>]+>", " ", item.findtext("description") or ""))
            desc = re.sub(r"\s+", " ", desc).strip()[:240]
            if desc and _sim(_norm_title(desc), _norm_title(title)) > 0.7:
                desc = ""                          # 摘要只是標題重印就不留
            rec = {"title": title, "link": link, "source": label,
                   "at": at.isoformat(), "kw": "",
                   "summary": desc if len(desc) >= 30 else ""}
            if raw_out is not None:
                raw_out.append(dict(rec))
            if not take_all and not any(_kw_hit(w, _kw_text(title))
                                        for w in words) \
                    and not _ELECTION_RE.search(title):   # v2：期中選舉（另經 election_filter 把關）
                continue
            if _excluded(title, exclude) or is_junk(title):
                continue
            key = re.sub(r"\s+", "", _norm_title(title))[:40]
            if key in seen:
                # v2.2：同一則轉載保留權重高的來源（路透原文勝過 Yahoo 轉載），只算一則
                j = seen[key]
                if _src_weight(rec) > _src_weight(out[j]):
                    out[j] = rec
                continue
            seen[key] = len(out)
            n_hit += 1
            out.append(rec)
        log.info("市場焦點：feed %s 取得 %d 則、入選 %d 則", label, n_all, n_hit)
    out.sort(key=lambda x: x["at"], reverse=True)
    return out





# 文章頁的固定雜訊段落（不是內文）：Yahoo 的錯誤頁、「加入 Google 優先來源」
# 推廣列、訂閱與 cookie 提示。混進材料會被 AI 當成新聞內容（2026-10 實測）。
_JUNK_PARA = re.compile(r"Oops, something went wrong|將 ?Yahoo ?加入|設為首選來源|"
                        r"Sign in to access|Subscribe to|cookie|Cookie|JavaScript|"
                        r"All rights reserved|版權所有|請勿轉載|訂閱電子報|點我加入")


def fetch_article_text(url: str, _get=None, cap: int = 1800) -> str:
    """
    抓文章頁、抽出正文（<p> 段落）。Yahoo 新聞頁的正文是伺服器渲染的，
    requests 就抓得到。抽不出足夠文字（<100 字）回空字串——改版、擋爬、
    影音頁都會走到這裡，由呼叫端退回標題模式。
    """
    import html as _html
    get = _get or (lambda u: requests.get(
        u, timeout=TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0 (macro-dashboard)"}))
    try:
        r = get(url)
        r.raise_for_status()
        page = r.text
    except Exception as e:                         # noqa: BLE001
        log.warning("市場焦點：文章抓取失敗（%s：%s）", url[:60], e)
        return ""
    # 主力：trafilatura 抽正文（純本機解析、不連外）。Yahoo Finance 英文版
    # 2026 改版後整頁導覽列都包在 <p> 裡，舊的 <p> 抽法只抽到選單文字
    #（實測 10/11：四篇全是「Skip to navigation…」）。沒裝或抽不出來才退舊法。
    try:
        import trafilatura
        txt = trafilatura.extract(page, include_comments=False, include_tables=False,
                                  favor_precision=True) or ""
    except Exception:                              # noqa: BLE001
        txt = ""
    if txt:
        paras = [re.sub(r"\s+", " ", ln).strip() for ln in txt.splitlines()]
        paras = [ln for ln in paras if len(ln) >= 20 and not _JUNK_PARA.search(ln)]
        body = "\n".join(paras)[:cap]
        if cjk_len(body) >= 100 or len(body) >= 300:
            return body
    # 後備：先砍 script/style 再抽 <p>：Yahoo 頁面的 JSON 資料塊裡也有長字串，
    # 不砍會把程式碼當成內文。
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", page,
                  flags=re.S | re.I)
    paras = []
    for m in re.finditer(r"<p[^>]*>(.*?)</p>", page, re.S | re.I):
        t = _html.unescape(re.sub(r"<[^>]+>", "", m.group(1)))
        t = re.sub(r"\s+", " ", t).strip()
        if len(t) >= 20 and not _JUNK_PARA.search(t):   # 導覽、版權列都比這短
            paras.append(t)
        if sum(len(p) for p in paras) >= cap:
            break
    body = "\n".join(paras)[:cap]
    if cjk_len(body) >= 100 or len(body) >= 300:
        return body
    # 抽不出足夠內文的原因寫進 log：頁面抓得到（沒進上面的 except）但
    # <p> 太少，通常是影音頁、改版、或被導去同意頁——跟「被擋」是不同
    # 的修法，不留紀錄就只能猜。
    log.info("市場焦點：內文太薄不採用（%s：HTML %d 字元、抽出 %d 段 %d 字）",
             url[:60], len(page), len(paras), cjk_len(body))
    return ""


# 「優先寫內文才有的資訊」是這段 prompt 的重點：來源標題本來就列在
# 焦點段下方，摘要若只是把標題改寫串接，等於同一件事講兩次
#（實際發生過，使用者的原話：「上方的摘要還是在摘要新聞標題而不是內文」）。
# 數字防護欄（_digits_ok）對內文驗證，所以具體數字可以放心要求。
_FOCUS_CONTENT_SYSTEM = (
    "你是財經記者。輸入是幾篇新聞的標題與內文節錄（可能中英文混合），"
    "後面可能另有一節「標題快訊」——那些只有標題與官方摘要、沒有內文。"
    "只取與這些主題相關的內容：{kws}。"
    "讀完全部材料後，挑出今天最重要的 {n} 件事，寫成 {n} 則重點："
    "每則一行、只講一件事、{cap} 個中文字以內；依重要性排序，最重要的"
    "放第一則。**每一則都必須有具體事實**——誰、做了什麼、數字或時間"
    "至少要有一項；不要寫「成為市場焦點」「備受關注」「面臨多重挑戰」"
    "這類空泛的話。硬性規則：只能使用材料已有的資訊，不得補充材料以外"
    "的事實或數字；「標題快訊」只能轉述其標題與摘要**字面上有的事**，"
    "不得展開細節、不得推測其內文，引用時帶來源（例如「路透報導稱…」）；"
    "不得自行推論來源沒有寫的因果關係；不做預測、不下投資結論；繁體中文。"
    "**絕對禁止評論材料本身**：不要說明材料的多寡、品質或相關性，不要"
    "解釋你的處理過程，不要出現「材料」「關鍵字」「無法按要求」這類字眼"
    "——材料只夠寫一兩則就只寫一兩則，寧缺勿濫。"
    "直接輸出那幾則重點，每則一行，不要編號、不要符號開頭、不要標題或"
    "前言、不要粗體記號。")


# 版式 A 的內文模式。主軸優先採 Bloomberg／Reuters／Yahoo Finance：它們多半只有標題（付費牆），
# 但 Yahoo 等來源常轉載同一則通訊社稿的全文——同一件事的細節從那裡補。
# 版式 A（2026-10 第十七批）：標題＋主軸＋對利率＋補充＋來源代號。
# 主軸回到利率主線；正文不寫媒體名、不寫相對時間、人名用中文譯名。
_NEWS_RULES = (
    "寫作規則：①正文不寫媒體名稱——不要寫「路透報導」「彭博指出」「據金融時報」"
    "「Yahoo Finance」這類字眼，來源會另外列在下方，直接把事實寫出來；只有標題的"
    "報導也一樣，直接轉述標題與摘要字面上的事。②時間一律寫成「10/9」這種月/日"
    "（美國的事件可寫「10/9（美國時間）」），不要寫「本週」「上週」「週四」「昨天」"
    "「今天」「明天」這類相對時間；每篇報導的日期標在它的代號旁。③人名、公司名用"
    "台灣常用的中文譯名（例如川普、貝森特、輝達、台積電），不附英文；唯一例外是聯準會主席"
    "一律寫英文 Warsh（不要寫華許、沃許）。"
    "④聯準會現任主席是 Warsh（Kevin Warsh，2026 年 5 月接任）；鮑爾是前任主席、"
    "目前是理事，提到他要寫「前主席鮑爾」或「理事鮑爾」，絕對不要稱他為主席。")

_FOCUS_CONTENT_SYSTEM_A = (
    "你是財經記者，負責一個美國利率與總經儀表板的「今日主軸」。輸入是幾篇新聞，"
    "每篇有代號，例如【報導3｜Reuters｜10/9】；標「只有標題」的只有標題與官方摘要、"
    "沒有內文。最後一段「網站利率判讀」是本站用官方殖利率算出的近期走勢，另附 10 年期即時報價。"
    "主題範圍：{kws}。主軸以利率主線為優先：聯準會、通膨、就業、美債、財政與發債、"
    "關稅、美元；AI、油價、黃金、地緣政治只有在它們明確牽動利率或聯準會、或是"
    "材料裡最重大的事件時才當主軸；美國期中選舉只寫它對市場與政策（財政、關稅、發債）的影響。"
    "主軸的主角是新聞事件：市場數字（殖利率、油價、股市）在主軸裡最多一句，不要寫成解讀數據。"
    "說市場預期轉向（例如「升息預期升溫／退溫」）必須是材料裡寫到的，不得自行推論；"
    "不得寫任何預估值或市場共識數字。同一件事延續報導時直接寫最新發展，不要比較和前一版的差異。"
    "{event}{recent}依下面的格式輸出：\n"
    "【標題】一句話標題，14–28 個中文字，點出主軸的核心事件，不加句號。\n"
    "【主軸】{min}–{main} 個中文字，分 2–3 段（每段一行）。挑最重要、彼此相關的"
    "報導（優先彭博、路透；同一件事的多篇報導合併），綜合成一篇完整論述：①發生了"
    "什麼（誰、做了什麼、數字）②為什麼（背景與原因）③官員、分析師或市場怎麼解讀"
    "（只寫材料裡有的說法）。不要每則各講一句拼起來。\n"
    "【對利率】一句話，40–90 個中文字（超過 90 字會被退回），直接以事件開頭"
    "（例如「Warsh 暗示暫停升息，偏向壓低短端利率…」）：說明它對美國利率"
    "（短端、長端或升降息預期）偏向推升還是壓低、為什麼——解讀的是上面寫的那件事，"
    "不是數據本身；再用「網站利率判讀」的 **10 年期**數字對照市場實際走勢：方向一致就說"
    "市場已在反映（例如「10 年期今日 +Xbp 至 Y%，市場已在反映」，X、Y 填網站判讀的數字），"
    "不一致就**明講落差**（例如「不過 10 年期今日 -Xbp，市場還沒反映」）。只引用 10 年期這一組數字，不要另外"
    "混用其他期間或天期；寫「收盤」的不要說成盤中。只能寫「偏向」「若…則…」，"
    "不要寫「將會」「勢必」這類預測；事件對利率的方向不明確（例如油價、地緣衝突"
    "兩面都說得通）時，直接寫方向不明確、取決於什麼。數字只能用材料或網站判讀裡有的。\n"
    "【補充】{ns} 行，每行一件**主軸以外**的事件、{supp} 個中文字以內：寫出發生了"
    "什麼，再加一個具體細節（數字、時間、誰說的或原因）。\n"
    "【來源】主軸用到的報導代號，用逗號分隔，例如「1,4」。主軸寫的事件若有彭博、"
    "路透的報導（含「只有標題」的），把那幾則的代號**排在最前面**（最多 3 則），即使細節是從"
    "其他報導補的——它們是原始出處；再列實際提供細節的報導。\n"
    "硬性規則：只能使用材料已有的資訊，不得補充材料以外的事實或數字；只有標題的"
    "報導只能轉述字面上的事，不得推測其內文；不得自行推論來源沒有寫的因果關係；"
    "不做預測、不下投資結論；繁體中文。**絕對禁止評論材料本身**：不要說明材料的"
    "多寡、品質或相關性，不要出現「材料」「關鍵字」「代號」這類字眼——補充只夠寫"
    "一則就只寫一則。" + _NEWS_RULES +
    "輸出格式：【標題】【主軸】【對利率】【補充】【來源】各自單獨一行，內容接在"
    "下一行；不要編號、不要符號開頭、不要粗體記號、不要任何前言。")


def _post_gemini_hardy(key: str, model: str, src_text: str,
                       system: str, temperature: float = 0.3):
    """
    焦點段專用的 Gemini 呼叫鏈——**拚到底**的容錯政策，只住在這個檔案。

    跟整體情勢潤稿的 `polish._post_gemini` 刻意分家（使用者的要求：
    潤稿還原原本行為、不共用容錯層）：潤稿有規則組裝版可退，失敗
    立刻退回最划算；焦點段沒有退路（退了就是列標題），所以這裡
    404／截斷／5xx／timeout／429 全部換模型再試——
      404          記進 polish._DEAD（整把金鑰共用的黑名單，這是事實
                   不是政策：叫不動就是叫不動）
      回覆被截斷    改挑預設不推理的 lite
      5xx／timeout 單一模型容量池擠爆，換一顆（實測：flash-latest
                   連吃 503 時其他模型正常）
      429          免費層配額**逐模型**計（各自一桶 RPM／RPD），
                   這顆見底不代表別顆也是（實測：等完 35＋70 秒仍
                   連三個 429，換桶才有用）
    只有 400（參數錯）與 401（金鑰錯）直接往上拋——換誰都一樣。
    積木（_gemini_call、_alt_model）沿用 polish 的：那些是工具，
    政策在這裡。
    """
    from . import polish as _pl
    tried: list[str] = []
    cur, prefer_lite = model, False
    last_exc: Exception | None = None
    for _ in range(_pl.MAX_MODEL_TRIES):
        tried.append(cur)
        try:
            return _pl._gemini_call(key, cur, src_text, system,
                                    think=False, temperature=temperature)
        except _pl.TruncatedError as e:
            last_exc, prefer_lite = e, True
            log.warning("市場焦點：%s 回覆被截斷（%s）", cur, e)
        except requests.HTTPError as e:
            resp = getattr(e, "response", None)
            code = resp.status_code if resp is not None else 0
            if code in (400, 401):
                raise
            last_exc = e
            if code == 404:
                _pl._DEAD.add(cur)
            log.warning("市場焦點：%s 失敗（HTTP %d），換一顆模型再試",
                        cur, code)
        except requests.RequestException as e:
            # 連線層（timeout、斷線）＝過載到不回應，跟 5xx 同一件事。
            # 注意順序：HTTPError 是 RequestException 的子類，這個分支
            # 必須排在後面，否則 400／401 全被當成連線失敗。
            last_exc = e
            log.warning("市場焦點：%s 連線失敗（%s），換一顆模型再試", cur, e)
        alt = _pl._alt_model(key, tried, prefer_lite=prefer_lite)
        if not alt:
            break
        cur = alt
    raise last_exc if last_exc else RuntimeError("Gemini 沒有可用的模型")


# 2026-10-25 v2：主軸（含週日週報）與 FOMC 筆記改用 Sonnet；主題補充、總述潤稿維持 Haiku。
FOCUS_MODEL = "claude-sonnet-4-5"


def _call_ai(src_text: str, system: str, env=None, model: str | None = None) -> tuple[str, str]:
    """
    焦點段的 AI 呼叫：**Anthropic 主力** → Gemini 多模型鏈備援。
    回傳 (文字, 失敗原因)；成功時原因是空字串。

    為什麼 Anthropic 排前面：使用者已儲值付費額度，限流餘裕遠大於
    Gemini 的免費額度（實測 flash-latest 連吃三個 429 退回列標題）。
    為什麼仍要跨供應商：焦點段的新聞每次執行都不一樣，一天要打三次，
    曝險是整體情勢潤稿的幾十倍——單一供應商的任何故障都會直接上畫面。
    Gemini 備援走焦點專用的 _post_gemini_hardy（拚到底的換模型政策）。
    數字鎖等防護欄在呼叫端外面，對兩家一視同仁。
    """
    from .polish import _post_anthropic, PROVIDERS
    import os
    env = env or os.environ
    g_key = (env.get("GEMINI_API_KEY") or "").strip()
    a_key = (env.get("ANTHROPIC_API_KEY") or "").strip()
    if not g_key and not a_key:
        return "", "沒有 AI 金鑰"
    errs = []
    if not a_key and g_key:
        # 主力缺席要說話：沒設 ANTHROPIC_API_KEY（或 Secret 名字打錯，
        # Actions 會傳**空字串**進來）時，看起來就像「沒有優先用
        # Anthropic」——其實是根本沒有它的金鑰。
        log.warning("市場焦點：未設 ANTHROPIC_API_KEY（主力），"
                    "本次直接走 Gemini 備援")
    if a_key:
        a_model = model or PROVIDERS["anthropic"]["model"]
        try:
            out = _post_anthropic(a_key, a_model,
                                  src_text, system=system, temperature=0.3)
            log.info("市場焦點：Anthropic（%s）產出", a_model)
            return (out or "").strip(), ""
        except Exception as e:                     # noqa: BLE001
            errs.append(f"Anthropic：{e}")
            if g_key:
                log.warning("市場焦點：Anthropic 失敗（%s），"
                            "改用 Gemini 備援", e)
    if g_key:
        model = (env.get("BRIEF_MODEL") or "").strip() or "gemini-flash-latest"
        try:
            out = _post_gemini_hardy(g_key, model, src_text, system)
            log.info("市場焦點：Gemini（%s）產出", model)
            return (out or "").strip(), ""
        except Exception as e:                     # noqa: BLE001
            errs.append(f"Gemini：{e}")
    return "", "呼叫失敗（" + "；".join(errs) + "）"


# 後設偵測的預設清單（config 的 meta_markers 可覆寫）：這些詞組出現＝
# 模型在評論材料而不是寫新聞。實際事故：整篇「提供的材料中相關內容
# 極為有限…無法按要求綜合改寫」帶著粗體記號直接上線——長度、數字、
# 段落三道檢查都真心誠意地放行了，缺的就是「這是不是新聞」這一道。
DEFAULT_META_MARKERS = (
    "提供的材料", "材料中", "材料主要", "材料缺乏", "根據材料", "僅能提取",
    "相關內容極為有限", "相關資訊有限", "關鍵字", "按要求", "綜合改寫",
    "無法按", "不足以", "標題快訊", "內文細節", "可供轉述",
    "以下是", "以下為", "根據您", "綜上所述", "需要注意的是", "總結來說")


def _meta_hits(text: str, markers=None) -> list[str]:
    """回傳命中的後設詞組（空＝乾淨）。只比詞組不比單詞，
    「伊朗無法出口」的「無法」不會誤殺。"""
    return [m for m in (markers or DEFAULT_META_MARKERS) if m in (text or "")]


def _tidy_focus(text: str) -> str:
    """焦點段的排版清理：逐段去掉 markdown 記號（粗體實際上過線）。
    段落結構（空行）保留——首頁靠它分段渲染。"""
    from . import polish as _pl
    return "\n".join(_pl._sanitize(ln) if ln.strip() else ""
                      for ln in (text or "").splitlines())


# 版式：N 則重點、每則 item_cap 字（config 的 items／item_chars，
# 預設 3 則 × 100 字）。每則的硬底線＝item_cap × HARD_MULT（150 字）：
# 底線內直接採用；超過才帶原因重寫一次，仍超過就把那一則裁到底線之內
# ——長度永遠不會讓焦點段退回列標題（使用者指定）。
HARD_MULT = 1.5
DEFAULT_ITEMS, DEFAULT_ITEM_CHARS = 3, 100
# 版式 A（2026-10 使用者定案）：一段主軸＋兩則補充。
#   主軸：把當天最大的一件事講完整（發生什麼→為什麼→對利率／聯準會的意義），
#         MAIN_CHARS 字以內
#   補充：其他事件，每則 SUPP_CHARS 字以內
# 先前的「3 則 × 100 字」實際跑起來變成一篇文章一則、各自重述標題，
# 使用者嫌「只是列標題、不扎實」；一整段 300 字又嫌長——A 是折衷。
# 2026-10-05 使用者再定案：主軸 200–250 字、可分段，把三則相關報導綜合論述
# 講完整（發生什麼→為什麼→對利率／聯準會代表什麼）；補充每則 80 字內、
# 不能只列標題。
DEFAULT_MAIN_CHARS, DEFAULT_SUPP_ITEMS, DEFAULT_SUPP_CHARS = 250, 2, 80
DEFAULT_MAIN_MIN, DEFAULT_SUPP_MIN = 200, 40
# 版式 A 的硬底線比舊版緊（使用者給的是明確區間，不是大約）：
# 主軸上限 ×1.1（275 字）、補充 ×1.25（100 字）；下限 ×0.9 才算「太短」。
HARD_MULT_MAIN, HARD_MULT_SUPP, SHORT_TOL = 1.1, 1.25, 0.9
# 主軸的段落在內部用這個字元串起來（整段文字仍是「一行一則」的格式，
# 快取與 log 都不用改）；首頁渲染時再拆回段落。
MAIN_PARA = "¶"
MAX_MAIN_PARAS = 3


def focus_caps(cfg: dict | None) -> list[int]:
    """每一行的字數上限：[主軸, 補充, 補充]（config 的 main_chars／supp_items／supp_chars）。"""
    cfg = cfg or {}
    main = int(cfg.get("main_chars") or DEFAULT_MAIN_CHARS)
    n = int(cfg.get("supp_items") if cfg.get("supp_items") is not None
            else DEFAULT_SUPP_ITEMS)
    supp = int(cfg.get("supp_chars") or DEFAULT_SUPP_CHARS)
    return [main] + [supp] * n


def focus_mins(cfg: dict | None) -> list[int]:
    """每一行的字數下限：[主軸, 補充…]（config 的 main_min／supp_min）。"""
    cfg = cfg or {}
    n = len(focus_caps(cfg)) - 1
    main = int(cfg.get("main_min") if cfg.get("main_min") is not None
               else DEFAULT_MAIN_MIN)
    supp = int(cfg.get("supp_min") if cfg.get("supp_min") is not None
               else DEFAULT_SUPP_MIN)
    return [main] + [supp] * n


def focus_hards(caps: list[int]) -> list[int]:
    """版式 A 的硬底線：主軸 ×1.1、補充 ×1.25。"""
    return ([int(caps[0] * HARD_MULT_MAIN)]
            + [int(c * HARD_MULT_SUPP) for c in caps[1:]])

# 空話清單：命中兩個以上就帶原因重寫一次（第二次照樣採用——這是文風
# 問題，不是正確性問題，不值得為它退回列標題）。使用者嫌「AI 總結有點
# 籠統」，實際線上那段正是「成為市場焦點」「面臨多重挑戰」這種寫法。
DEFAULT_VAGUE_MARKERS = (
    "成為市場焦點", "備受關注", "引發市場關注", "引發關注", "多重挑戰",
    "值得關注", "市場密切關注", "持續升溫", "不容忽視", "牽動市場")

# 版式或提示詞一改就要讓快取失效：快取鍵含這個版本字串，
# 否則舊版的三段散文會一直被沿用到標題換掉為止。
FOCUS_PROMPT_VERSION = "v2-events-signals-sonnet"

# 快取時效：標題沒變也不能永遠沿用（使用者回報過「今日市場焦點都沒更新」
# ——來源池小、標題變得慢，雜湊天天一樣，同一段文字掛了好幾天）。
CACHE_TTL_HOURS = 12


def _trim_to(text: str, limit: int) -> str:
    """
    把文字裁到 limit 個中文字以內。優先砍**整段**（句子不被切斷）；
    連第一段都超長時，退而求其次砍到最後一個句末標點。
    只刪不改——留下的每個數字仍然出自原文，數字鎖的結論不受影響。
    """
    if cjk_len(text) <= limit:
        return text
    paras = [p for p in (text or "").split("\n") if p.strip()]
    kept: list[str] = []
    for para in paras:
        if cjk_len("".join(kept) + para) > limit:
            break
        kept.append(para)
    if kept:
        return "\n".join(kept)
    out = ""
    for ch in (paras[0] if paras else text):
        if cjk_len(out + ch) > limit:
            break
        out += ch
    cut = max(out.rfind(c) for c in "。！？")
    return out[:cut + 1] if cut > 0 else out


# 行首的編號與項目符號：模型常常不聽「不要編號」。
# 版式 A 另外會冒出「主軸：」「補充：」這種標籤，一起拿掉。
_ITEM_LEAD = re.compile(r"^\s*(?:[・•●▪◆◇■□\-–—*]|\d{1,2}[.、)）]|"
                        r"[（(]\d{1,2}[)）]|[一二三四五六七八九十][、.]|"
                        r"(?:主軸|補充\d?)\s*[:：])\s*")


def _split_items(text: str, n: int) -> list[str]:
    """一行一則；去掉行首編號與符號；超過 n 則只留前 n 則。"""
    items = [_ITEM_LEAD.sub("", ln).strip()
             for ln in (text or "").splitlines()]
    items = [x for x in items if x]
    if len(items) > n:
        log.info("市場焦點：模型寫了 %d 則，只留前 %d 則", len(items), n)
    return items[:n]


_TAG_MAIN = re.compile(r"^\s*(?:【\s*主軸\s*】|\[\s*主軸\s*\]|主軸\s*[:：])\s*")
_TAG_SUPP = re.compile(r"^\s*(?:【\s*補充\s*\d?\s*】|\[\s*補充\s*\]|補充\s*\d?\s*[:：])\s*")


def _split_main(text: str, n_supp: int) -> list[str]:
    """
    版式 A 的切分：回傳 [主軸, 補充…]，主軸的各段以 MAIN_PARA 串成一則。

    模型照格式時靠「【主軸】」「【補充】」兩個標記分節；沒照格式（沒有
    任何標記）時，最後 n_supp 行當補充、前面的都是主軸的段落——
    只剩一兩行就是「第一行主軸、其餘補充」，跟舊版一樣。
    """
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    main: list[str] = []
    supp: list[str] = []
    sec = ""
    tagged = any(_TAG_MAIN.match(ln) or _TAG_SUPP.match(ln) for ln in lines)
    for ln in lines:
        if _TAG_MAIN.match(ln):
            sec, ln = "main", _TAG_MAIN.sub("", ln)
        elif _TAG_SUPP.match(ln):
            sec, ln = "supp", _TAG_SUPP.sub("", ln)
        ln = _ITEM_LEAD.sub("", ln).strip()
        if not ln:
            continue
        if not tagged:
            main.append(ln)
        elif sec == "supp":
            supp.append(ln)
        else:
            main.append(ln)                        # 標記前的文字也算主軸
    if not tagged and len(main) > 1:
        k = max(1, len(main) - n_supp)
        main, supp = main[:k], main[k:]
    if not main and supp:
        main, supp = supp[:1], supp[1:]
    if len(main) > MAX_MAIN_PARAS:                 # 段太多：後面併進最後一段
        main = main[:MAX_MAIN_PARAS - 1] + ["".join(main[MAX_MAIN_PARAS - 1:])]
    if len(supp) > n_supp:
        log.info("市場焦點：模型寫了 %d 則補充，只留前 %d 則", len(supp), n_supp)
    return ([MAIN_PARA.join(main)] if main else []) + supp[:n_supp]


def _trim_item(text: str, limit: int) -> str:
    """_trim_to 的段落版：主軸的段落（MAIN_PARA）當成換行來裁，裁完再串回。"""
    return _trim_to(text.replace(MAIN_PARA, "\n"), limit).replace("\n", MAIN_PARA)


def _generate_items(src_text: str, system: str, env, *, item_cap: int = 0,
                    n_items: int = 0, meta_markers=None,
                    vague_markers=None, caps: list[int] | None = None,
                    mins: list[int] | None = None
                    ) -> tuple[str, str]:
    """
    共用的生成＋驗證核心（內文模式與標題模式都走這裡）。
    回傳 (多則重點以換行連接, "")；失敗回 ("", 原因)。

    驗證分三個層級，處置各不相同：
      後設字眼   模型在評論材料而不是寫新聞 → 重試一次，再犯就失敗
      數字鎖     正確性防護欄 → 一票否決、不重試
      長度／空話 文風問題 → 重寫一次，仍不理想就裁切後照樣採用
    """
    # caps：每一行各自的字數上限（版式 A：[主軸, 補充, 補充]）；沒給就是
    # 舊版的 N 則等長。硬底線一律是上限 × HARD_MULT。
    layout_a = bool(caps)
    caps = list(caps) if caps else [item_cap] * n_items
    n_items = len(caps)
    hards = (focus_hards(caps) if layout_a else [int(c * HARD_MULT) for c in caps])
    mins = list(mins or [])
    _cap_txt = (f"每則 {caps[0]} 字以內" if not layout_a else
                (f"主軸 {mins[0]}–{caps[0]} 字（可分段）" if mins and mins[0]
                 else f"主軸 {caps[0]} 字以內（可分段）")
                + f"、每則補充 {caps[1] if len(caps) > 1 else 0} 字以內")
    vague_markers = vague_markers or DEFAULT_VAGUE_MARKERS
    best: list[str] = []
    note = ""
    for attempt in (1, 2):
        text, err = _call_ai(src_text + note, system, env)
        if err:
            return "", err
        items = (_split_main(_tidy_focus(text), n_items - 1) if layout_a
                 else _split_items(_tidy_focus(text), n_items))
        if not items:
            return "", "輸出是空的"
        joined = "\n".join(items)
        meta = _meta_hits(joined, meta_markers)
        if meta:
            log.warning("市場焦點：輸出含後設字眼（%s），退回重試",
                        "、".join(meta[:4]))
            note = ("\n\n（上一次的輸出在評論材料本身，被退回。請直接輸出"
                    "重點：不要解釋材料的多寡或你的處理過程；材料只夠寫"
                    "一兩則就只寫一兩則。）")
            continue
        if not _digits_ok(joined, src_text):
            return "", "輸出出現材料裡沒有的數字"
        long_ = [i + 1 for i, it in enumerate(items) if cjk_len(it) > hards[i]]
        # 太短（版式 A 才檢查）：主軸撐不到下限＝沒講完整；補充太短＝在列標題
        short_ = [i + 1 for i, it in enumerate(items)
                  if i < len(mins) and mins[i]
                  and cjk_len(it) < int(mins[i] * SHORT_TOL)]
        vague = _meta_hits(joined, vague_markers)
        if attempt == 1 and (long_ or short_ or len(vague) >= 2):
            best = items
            why = []
            if long_ and len(set(hards)) == 1:
                why.append("第 " + "、".join(map(str, long_))
                           + f" 則超過 {hards[0]} 字")
            elif long_:
                why.append("、".join(f"第 {i} 行超過 {hards[i - 1]} 字"
                                     for i in long_))
            for i in short_:
                n_ = cjk_len(items[i - 1])
                why.append(f"主軸只有 {n_} 字，沒有把事情講完整（要 "
                           f"{mins[0]}–{caps[0]} 字）" if i == 1 else
                           f"第 {i} 行只有 {n_} 字，像在列標題（要寫出發生"
                           "了什麼再加一個具體細節）")
            if len(vague) >= 2:
                why.append("用了空泛的套話（" + "、".join(vague[:3]) + "）")
            log.warning("市場焦點：%s，帶原因重寫一次", "；".join(why))
            note = (f"\n\n（上一次的輸出被退回：{'；'.join(why)}。請重寫："
                    f"{_cap_txt}，講具體的事——誰、做了什麼、"
                    "數字或時間——不要套話。）")
            continue
        if short_:
            log.warning("市場焦點：重寫後仍偏短（第 %s 行），照樣採用",
                        "、".join(map(str, short_)))
        return "\n".join(_trim_item(it, hards[i]) for i, it in enumerate(items)), ""
    if best:
        log.warning("市場焦點：重寫後仍不合格，採用第一版並裁切超長的則")
        return "\n".join(_trim_item(it, hards[i]) for i, it in enumerate(best)), ""
    return "", "輸出反覆評論材料本身（後設字眼）"


# ---------------------------------------------------------------------------
# 第十七批（2026-10）：主軸的材料、檢查與後處理
# ---------------------------------------------------------------------------
MIN_MAIN_STORIES = 3          # 主軸至少要有幾則「不同的報導」（轉載只算一則）
MAX_MAIN_LINKS = 6            # 主軸來源最多 6 則：原文（彭博／路透）與其他各最多 3 則
MAIN_LINKS_PER_TIER = 3

# 人名、公司名統一用台灣常用中文譯名：{標準寫法: (別名…)}。
# config 的 name_map 可以追加或覆寫（同樣的格式）。
DEFAULT_NAME_MAP = {
    "川普": ("Donald Trump", "Trump", "特朗普", "唐納德·川普", "唐納·川普", "唐納德川普"),
    "鮑爾": ("Jerome Powell", "Powell", "鮑威爾", "鲍威尔"),
    "貝森特": ("Scott Bessent", "Bessent", "貝森"),
    # 2026-10-27：使用者指定 Warsh 一律用英文（其他人名照舊用中文譯名）
    "Warsh": ("Kevin Warsh", "華許", "沃許", "沃什", "瓦許", "華什"),
    "穆薩勒姆": ("Alberto Musalem", "Musalem", "穆薩萊姆", "穆塞勒姆"),
    "沃勒": ("Christopher Waller", "Waller", "華勒"),
    "庫克": ("Lisa Cook",),
    "鮑曼": ("Michelle Bowman", "Bowman"),
    "傑佛遜": ("Philip Jefferson",),
    "威廉斯": ("John Williams",),
    "古斯比": ("Austan Goolsbee", "Goolsbee", "古爾斯比"),
    "卡什卡利": ("Neel Kashkari", "Kashkari"),
    "戴利": ("Mary Daly",),
    "博斯蒂克": ("Raphael Bostic", "Bostic"),
    "洛根": ("Lorie Logan",),
    "哈瑪克": ("Beth Hammack", "Hammack"),
    "施密德": ("Jeffrey Schmid", "Schmid"),
    "米蘭": ("Stephen Miran", "Miran"),
    "柯林斯": ("Susan Collins",),
    "巴爾": ("Michael Barr",),
    "葉倫": ("Janet Yellen", "Yellen", "耶倫"),
    "萬斯": ("JD Vance", "J.D. Vance", "Vance"),
    "普丁": ("Vladimir Putin", "Putin", "普京"),
    "澤倫斯基": ("Volodymyr Zelenskyy", "Volodymyr Zelensky", "Zelenskyy", "Zelensky", "澤連斯基"),
    "習近平": ("Xi Jinping",),
    "植田和男": ("Kazuo Ueda", "Ueda"),
    "拉加德": ("Christine Lagarde", "Lagarde"),
    "黃仁勳": ("Jensen Huang",),
    "馬斯克": ("Elon Musk", "Musk"),
    "阿特曼": ("Sam Altman", "Altman"),
    "輝達": ("NVIDIA", "Nvidia", "英偉達"),
    "台積電": ("TSMC", "臺積電"),
    "微軟": ("Microsoft",),
    "甲骨文": ("Oracle",),
    "博通": ("Broadcom",),
    "美光": ("Micron",),
    "英特爾": ("Intel",),
    "特斯拉": ("Tesla",),
    "亞馬遜": ("Amazon",),
    "三星": ("Samsung",),
}


def _name_map(cfg: dict | None) -> dict:
    m = {k: tuple(v) for k, v in DEFAULT_NAME_MAP.items()}
    for k, v in ((cfg or {}).get("name_map") or {}).items():
        m[str(k)] = tuple(str(x) for x in (v if isinstance(v, (list, tuple)) else [v]))
    return m


def normalize_names(text: str, name_map: dict | None = None) -> str:
    """別名一次換成標準寫法（最長的先比，「貝森特」不會被「貝森」換成「貝森特特」）。
    英文別名要完整單字；換完把中文字之間多出來的空白拿掉。"""
    if not text:
        return text or ""
    pairs = [(a, k) for k, al in (name_map or DEFAULT_NAME_MAP).items()
             for a in (k,) + tuple(al) if a]
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    mapping = {a.lower() if a.isascii() else a: k for a, k in pairs}
    pat = re.compile("|".join(
        (r"(?<![A-Za-z])" + re.escape(a) + r"(?![A-Za-z])") if a.isascii() else re.escape(a)
        for a, _ in pairs), re.I)
    out = pat.sub(lambda m: mapping.get(m.group(0).lower() if m.group(0).isascii()
                                        else m.group(0), m.group(0)), text)
    out = re.sub(r"(?<=[一-鿿])[ \t]+(?=[一-鿿])", "", out)
    # 英文人名（Warsh）跟中文之間留一個空白：「主席 Warsh 表示」
    for k in (name_map or DEFAULT_NAME_MAP):
        if k.isascii():
            out = re.sub(r"(?<=[一-鿿])(?=" + re.escape(k) + r"(?![A-Za-z]))", " ", out)
            out = re.sub(r"(?<![A-Za-z])(" + re.escape(k) + r")(?=[一-鿿])", r"\1 ", out)
    return fix_chair(out)


# 現任聯準會主席（第十八批，使用者：主軸還把鮑爾當主席）。主席交接時改這裡。
FED_CHAIR = "Warsh"
FED_CHAIR_EN = "Kevin Warsh"
FED_CHAIR_SINCE = "2026 年 5 月"
FORMER_CHAIRS = ("鮑爾",)
_CHAIR_FIX = re.compile(r"(?<![前任])(?:美國)?(?:聯準會|Fed|聯儲)?主席(" + "|".join(FORMER_CHAIRS) + r")"
                        r"|(" + "|".join(FORMER_CHAIRS) + r")主席")


def fix_chair(text: str) -> str:
    """把「主席鮑爾」「聯準會主席鮑爾」「鮑爾主席」改成「前主席鮑爾」——
    舊報導或模型記憶常沿用舊稱謂；人換了就是換了，不改成別人的名字。"""
    if not text:
        return text or ""
    def _r(m):
        # 前面五個字內已有「前」「前任」（例：前聯準會主席鮑爾）就不動
        if "前" in text[max(0, m.start() - 5):m.start()]:
            return m.group(0)
        return "前主席" + (m.group(1) or m.group(2))
    return _CHAIR_FIX.sub(_r, text)


# 正文不寫媒體名（來源列在下方）。偵測到就帶原因重寫；重寫後仍有，
# 把「據路透報導，」「路透指出，」這類固定說法刪掉。
_MEDIA = (r"(?:路透社?|彭博社?|Reuters|Bloomberg|雅虎|Yahoo\s*(?:Finance|奇摩)?(?:財經|股市|新聞)?|"
          r"CNBC|金融時報|華爾街日報|WSJ|Financial Times|FXStreet|鉅亨網?|經濟日報|工商時報|"
          r"自由時報|BBC|衛報|Guardian|MarketWatch|巴倫週刊|Barron'?s|Stocktwits)")
_MEDIA_RE = re.compile(_MEDIA, re.I)
# v2.2：媒體名和「報導指出」之間可以有空白（10/27「CNBC 報導指出」漏網）
_MEDIA_STRIP = re.compile(r"(?:據|根據)\s*" + _MEDIA + r"\s*(?:的)?(?:報導|報道|消息|分析)?(?:指出|稱)?[，,]?\s*"
                          r"|" + _MEDIA + r"\s*(?:報導|報道|引述消息人士)(?:指出|稱)?[，,：:]?\s*", re.I)
# v2.2：寫給 AI 的用語跑進正文（10/27「主軸這件事對利率方向不明確」）——帶原因重寫，仍有就機械拿掉
_PROMPT_LEAK = re.compile(r"主軸(?:這件事|的事件|這則新聞|新聞|事件)(?:本身)?(?:對利率)?|本次主軸|這則主軸")
RATE_MAX = 90
# 相對時間（要寫成月/日）
_REL_DATE = re.compile(r"本週|上週|下週|本周|上周|下周|(?<![\d/])週[一二三四五六日]|(?<![\d/])周[一二三四五六日]|"
                       r"星期[一二三四五六日天]|昨天|昨日|今天|今日|明天|明日|前一天|前一交易日")
_UP_WORDS = re.compile(r"上行|走高|攀升|上升|上揚|走升|升高|彈升|推升|上漲|壓力未退|走揚")
_DN_WORDS = re.compile(r"回落|下行|走低|下滑|下降|走跌|回跌|降溫|下挫|滑落")


def _media_hits(text: str) -> list[str]:
    return sorted({m.group(0) for m in _MEDIA_RE.finditer(text or "")})


def _strip_media(text: str) -> str:
    return _MEDIA_STRIP.sub("", text or "")


def _strip_leak(text: str) -> str:
    """「主軸這件事對利率方向不明確」→「方向不明確」；正文的「主軸這件事」→「這件事」。"""
    t = _PROMPT_LEAK.sub(lambda m: "" if m.group(0).endswith("對利率") else "這件事", text or "")
    return re.sub(r"^[，、：:\s]+", "", t)


def _us_date(at: str) -> str:
    """報導時間 → 美東的月/日（給 AI 寫「10/9」用）。"""
    try:
        from zoneinfo import ZoneInfo
        t = dt.datetime.fromisoformat(str(at))
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        t = t.astimezone(ZoneInfo("America/New_York"))
        return f"{t.month}/{t.day}"
    except Exception:                              # noqa: BLE001
        return ""


def _story_count(items: list[dict]) -> int:
    """不同報導的數量：標題相似（>0.55）視為同一則（轉載只算一次）。"""
    seen: list[str] = []
    for x in items:
        c = _norm_title(x.get("title") or "")
        if c and not any(_sim(c, s) > 0.55 for s in seen):
            seen.append(c)
    return len(seen)


# ---------------------------------------------------------------------------
# 「對利率」的 10 年期即時對照（2026-10）：原本用 FRED 官方日資料（要隔一個交易日
# 才有值），寫的時候看到的常是前一兩天的走勢。改成以 10 年期（benchmark）的 Yahoo
# 報價（延遲約 15 分鐘）對照：最新報價較前一交易日收盤。「對利率」本身仍是解讀
# **主軸新聞**對利率的意思，10 年期只是拿來對照市場有沒有反映。
# 抓不到就退回官方近 5 日的寫法。
# ---------------------------------------------------------------------------
YQ_URL_5M = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=5d&interval=5m"


def _et(t_utc: dt.datetime) -> dt.datetime:
    return (t_utc + dt.timedelta(hours=clock.ny_offset(t_utc))).replace(tzinfo=None)


def live_10y(now_utc: dt.datetime | None = None, _get=None) -> dict | None:
    """
    10 年期即時：{"now", "d_today", "at_et", "date_et", "open"}。
    open＝報價是不是當下盤中（最新成交在 40 分鐘內）；不是就是最近一個交易日的收盤。
    """
    get = _get or (lambda url: requests.get(
        url, timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0 (macro-dashboard)"}))
    now_utc = now_utc or dt.datetime.now(dt.timezone.utc)
    try:
        r = get(YQ_URL_5M.format(sym=quote("^TNX")))
        r.raise_for_status()
        res = ((r.json().get("chart") or {}).get("result") or [None])[0] or {}
        meta = res.get("meta") or {}
        ts = res.get("timestamp") or []
        cl = (((res.get("indicators") or {}).get("quote") or [{}])[0] or {}).get("close") or []
        bars = [(dt.datetime.fromtimestamp(int(t), dt.timezone.utc), float(v))
                for t, v in zip(ts, cl) if v is not None]
        cur = meta.get("regularMarketPrice")
        if not bars or cur is None:
            return None
        sc = lambda v: v / 10.0 if v > 20.0 else v          # noqa: E731  ×10 慣例
        cur = sc(float(cur))
        last_t = dt.datetime.fromtimestamp(int(meta.get("regularMarketTime") or bars[-1][0].timestamp()),
                                           dt.timezone.utc)
        # 前一交易日收盤：最新那個美東交易日之前，最後一根 5 分鐘線
        d_last = _et(last_t).date()
        before = [v for t, v in bars if _et(t).date() < d_last]
        if not before:
            return None
        prev = sc(before[-1])
        if not (0.1 <= cur <= 15 and 0.1 <= prev <= 15):
            return None
        out = {"now": round(cur, 2), "d_today": round((cur - prev) * 100),
               "at_et": f"{_et(last_t):%H:%M}", "date_et": d_last.isoformat(),
               "open": (now_utc - last_t) <= dt.timedelta(minutes=40), "ts": last_t}
        return out
    except Exception as e:                         # noqa: BLE001
        log.warning("市場焦點：10 年期即時報價抓取失敗（%s），對利率只用官方日資料", e)
        return None


def rate_context(rates_series: dict | None, n: int = 5) -> dict | None:
    """網站自己的利率判讀：近 n 個交易日 2Y／10Y／30Y 的變動與曲線型態。"""
    from .longend import regime
    rs = rates_series or {}
    def _chg(sid):
        rows = [r for r in rs.get(sid) or [] if not r.get("live") and r.get("value") is not None]
        if len(rows) <= n:
            return None, "", ""
        a, b = rows[-1], rows[-1 - n]
        return round((a["value"] - b["value"]) * 100), str(b.get("date", "")), str(a.get("date", ""))
    d2, _, _ = _chg("DGS2")
    d10, d0, d1 = _chg("DGS10")
    d30, _, _ = _chg("DGS30")
    if d10 is None or d2 is None:
        return None
    rg = regime(float(d10), float(d2))
    md = lambda s: (f"{int(s[5:7])}/{int(s[8:10])}" if len(s) >= 10 else s)
    return {"d2": d2, "d10": d10, "d30": d30, "from": md(d0), "to": md(d1),
            "zh": rg.get("zh", ""), "lead": rg.get("lead", ""), "code": rg.get("code", "")}


def policy_context(rates_series: dict | None, fw: dict | None = None) -> dict | None:
    """
    政策現況（第十九批，使用者抓到「對利率」寫成「支持聯準會繼續降息」，實際上
    9/16 才升息一碼）：目標區間、最近一次決議（從 DFEDTARU 的歷史推）、
    市場定價（首頁同一組期貨推算）。stance＝寫作時政策方向的硬約束。
    """
    rs = rates_series or {}
    up = [r for r in rs.get("DFEDTARU") or [] if r.get("value") is not None]
    lo = [r for r in rs.get("DFEDTARL") or [] if r.get("value") is not None]
    if not up or not lo:
        return None
    out = {"lo": lo[-1]["value"], "hi": up[-1]["value"], "last": None}
    for a, b in zip(reversed(up[:-1]), reversed(up[1:])):
        if abs(b["value"] - a["value"]) >= 0.05:
            bp = round((b["value"] - a["value"]) * 100)
            out["last"] = {"date": str(b.get("date", ""))[:10], "bp": bp}
            break
    hz = (fw or {}).get("horizons") or []
    out["market"] = [(h["label"], h["cum_bp"]) for h in hz if h.get("cum_bp") is not None]
    nxt = (fw or {}).get("next") or {}
    if nxt.get("outcomes"):
        b0, p0 = nxt["outcomes"][0]
        out["next"] = (str(nxt.get("date", ""))[:10], outcome_name(b0), round(p0 * 100))
    # 政策方向：最近一次決議（一年內）＋市場對今年底的定價；兩者一致才下硬約束
    last_dir = 0
    if out["last"]:
        try:
            age = (clock.today() - dt.date.fromisoformat(out["last"]["date"])).days
        except ValueError:
            age = 9999
        if age <= 365:
            last_dir = 1 if out["last"]["bp"] > 0 else -1
    mk = out["market"][0][1] if out["market"] else 0.0
    mk_dir = 1 if mk >= 10 else (-1 if mk <= -10 else 0)
    out["stance"] = ("hike" if (last_dir > 0 and mk_dir >= 0) or (last_dir == 0 and mk_dir > 0)
                     else "cut" if (last_dir < 0 and mk_dir <= 0) or (last_dir == 0 and mk_dir < 0)
                     else "mixed")
    return out


# 升息循環裡不該出現的說法（反之亦然）。命中就帶原因重寫；重寫後仍有就換備用句。
_POLICY_CUT_TALK = re.compile(r"(?:繼續|持續|延續|進一步|再度|再次|支持(?:聯準會)?(?:繼續)?)降息|降息(?:步伐|週期|循環|路徑)")
_POLICY_HIKE_TALK = re.compile(r"(?:繼續|持續|延續|進一步|再度|再次|支持(?:聯準會)?(?:繼續)?)升息|升息(?:步伐|週期|循環|路徑)")


def _policy_hits(text: str, rc: dict | None) -> list:
    pol = (rc or {}).get("policy") or {}
    st = pol.get("stance")
    pat = _POLICY_CUT_TALK if st == "hike" else _POLICY_HIKE_TALK if st == "cut" else None
    return sorted(set(pat.findall(text or ""))) if pat else []


def _rate_block(rc: dict | None) -> str:
    if not rc:
        return ""
    lv = rc.get("live10")
    if lv:
        # 有 10 年期即時就只給它（benchmark），不再列近 5 日的 2 年／30 年，
        # 免得 AI 混用兩組數字寫出「近一週上升，但 -10bp」這種自相矛盾的句子
        md_ = f"{int(lv['date_et'][5:7])}/{int(lv['date_et'][8:10])}"
        when = (f"美東 {md_} {lv['at_et']} 盤中" if lv.get("open") else f"美東 {md_} 收盤")
        out = (f"\n\n=== 網站利率判讀（10 年期殖利率 benchmark；Yahoo 報價，延遲約 15 分鐘，{when}）===\n"
               f"10 年期 {lv['now']:.2f}%，今日 {lv['d_today']:+d}bp（較前一交易日收盤）。")
    else:
        d30 = f"、30 年期 {rc['d30']:+d}bp" if rc.get("d30") is not None else ""
        lead = f"（{rc['lead']}）" if rc.get("lead") else ""
        out = (f"\n\n=== 網站利率判讀（官方日殖利率，{rc['from']}→{rc['to']}）===\n"
               f"2 年期 {rc['d2']:+d}bp、10 年期 {rc['d10']:+d}bp{d30}；曲線型態：{rc['zh']}{lead}。")
    pol = rc.get("policy") or {}
    if pol:
        md = lambda s: (f"{int(s[5:7])}/{int(s[8:10])}" if len(s or "") >= 10 else (s or ""))
        last = pol.get("last")
        act = ("" if not last else
               f"最近一次決議 {md(last['date'])} {'升息' if last['bp'] > 0 else '降息'} {abs(last['bp'])}bp；")
        nx = pol.get("next")
        mk = "、".join(f"至{lb} {bp:+.0f}bp" for lb, bp in pol.get("market") or [])
        out += (f"\n政策現況：聯邦基金利率目標區間 {pol['lo']:.2f}–{pol['hi']:.2f}%；{act}"
                + (f"市場定價：{md(nx[0])} 會議{nx[1]}機率 {nx[2]}%" if nx else "")
                + (f"、累計{mk}" if mk else "") + "。")
        if pol.get("stance") == "hike":
            out += "\n※ 目前是升息循環，不得寫「繼續降息」「降息步伐」這類說法；「對利率」的政策方向要與此一致。"
        elif pol.get("stance") == "cut":
            out += "\n※ 目前是降息循環，不得寫「繼續升息」「升息步伐」這類說法；「對利率」的政策方向要與此一致。"
    return out


_RATE_PHRASE = {
    "bear_steep": "長端賣壓較重，長天期利率上行壓力未退",
    "bull_steep": "短端降得更快，市場在加碼定價降息",
    "bear_flat": "短端升得更快，市場在定價更緊的政策",
    "bull_flat": "長端回落較多，避險或成長擔憂主導",
    "twist_steep": "長短端反向，曲線變陡",
    "twist_flat": "長短端反向，曲線變平",
    "flat": "利率大致持平，市場在等下一個訊號",
}


def _rate_fallback(rc: dict | None) -> str:
    if not rc:
        return ""
    lv = rc.get("live10")
    if lv:
        when = f"美東 {lv['at_et']} 盤中" if lv.get("open") else "前一交易日收盤"
        d = lv["d_today"]
        mv = "持平" if abs(d) < 2 else ("上升" if d > 0 else "下降")
        return f"10 年期殖利率今日 {d:+d}bp 至 {lv['now']:.2f}%（{when}），{mv}。"
    phrase = _RATE_PHRASE.get(rc.get("code"), "走勢待觀察")
    st = ((rc.get("policy") or {}).get("stance"))
    # 「短端降得更快」在升息循環裡是下修升息預期，不是定價降息（第十九批）
    if rc.get("code") == "bull_steep" and st == "hike":
        phrase = "短端降得更快，市場下修升息預期"
    elif rc.get("code") == "bear_flat" and st == "cut":
        phrase = "短端升得更快，市場下修降息預期"
    return (f"近一週（{rc['from']}→{rc['to']}）10 年期 {rc['d10']:+d}bp、2 年期 {rc['d2']:+d}bp，"
            f"曲線{rc['zh']}，{phrase}。")


# 2026-10（使用者：「對利率能不能用主軸新聞去分析」）：對利率改以主軸事件的意涵
# 為主、官方殖利率為對照。新聞方向與近一週走勢不同是常態（官方資料比新聞晚
# 一到三天），所以不再要求「方向一致」，改成：不一致時必須點出落差並引用實際
# 的 10 年期變動；仍禁止違反政策現況、禁止預測口吻、數字必須出自材料。
_RATE_GAP = re.compile(r"尚未|還沒|未反映|沒有反映|反而|相反|落差|未跟進|消化|然而|不過|但")
_RATE_UNCLEAR = re.compile(r"方向不明|不明確|取決於|兩面")
_RATE_PREDICT = re.compile(r"將會|必將|勢必|一定會|必然")


def _rate_issues(note: str, rc: dict | None, src: str = "") -> list[str]:
    """對利率那一句的問題清單（空＝通過）。src＝給 AI 的材料全文（含網站判讀）。"""
    if not rc or not note:
        return []
    why = []
    ph = _policy_hits(note, rc)
    if ph:
        st = {"hike": "升息循環", "cut": "降息循環"}.get((rc.get("policy") or {}).get("stance"), "")
        why.append(f"政策方向和現況相反（目前是{st}，不得寫" + "、".join(ph) + "）")
    pr = sorted(set(_RATE_PREDICT.findall(note)))
    if pr:
        why.append("用了預測口吻（" + "、".join(pr) + "），請改成「偏向」「若…則…」")
    up, dn = bool(_UP_WORDS.search(note)), bool(_DN_WORDS.search(note))
    lv = rc.get("live10")
    d10 = (lv["d_today"] if lv else rc.get("d10")) or 0
    span = "今日" if lv else "近一週"
    # 明講方向不明確（「取決於…」）的句子不判方向：「油價上漲」的上漲說的是油價
    unclear = bool(_RATE_UNCLEAR.search(note))
    against = not unclear and ((d10 >= 3 and dn and not up) or (d10 <= -3 and up and not dn))
    if against:
        flat = note.replace(" ", "").replace("−", "-")
        if not (_RATE_GAP.search(note) and f"{abs(d10)}bp" in flat):
            why.append(f"新聞意涵和{span}走勢（10 年期 {d10:+d}bp）方向不同，卻沒有點出落差"
                       "（要寫出實際變動，並說明市場還沒反映或反向）")
    if src:
        bad = _missing_digits(note, src)
        if bad:
            why.append("用了材料裡沒有的數字（" + "、".join(bad[:3]) + "）")
    return why


def _rate_consistent(note: str, rc: dict | None, src: str = "") -> bool:
    return not _rate_issues(note, rc, src)


_TAG_ANY = re.compile(r"^\s*【\s*(標題|主軸|對利率|補充\s*\d?|來源)\s*】\s*(.*)$")


def _parse_main_output(text: str, n_supp: int) -> dict:
    """
    把 AI 輸出切成 {headline, main[段落], rate, supp[], ids[]}。
    先抽出【標題】【對利率】【來源】（各取一行，標記和內容同一行或下一行
    都認得），剩下的交給舊規則 _split_main（認得【主軸】【補充】，沒有標記
    時最後 n_supp 行是補充）。模型漏寫某個標記也不會把整段吃錯。
    """
    out = {"headline": "", "main": [], "rate": "", "supp": [], "ids": []}
    rest: list[str] = []
    want = ""
    for ln in (text or "").splitlines():
        if not ln.strip():
            continue
        m = _TAG_ANY.match(ln)
        tag = re.sub(r"\s*\d", "", m.group(1)) if m else ""
        if tag in ("標題", "對利率", "來源"):
            body = m.group(2).strip()
            if body:
                _put = body
                want = ""
            else:
                want = tag
                continue
        elif want and not m:
            tag, _put, want = want, ln.strip(), ""
        else:
            want = ""
            rest.append(ln)
            continue
        if tag == "標題" and not out["headline"]:
            out["headline"] = _ITEM_LEAD.sub("", _put).strip()
        elif tag == "對利率" and not out["rate"]:
            out["rate"] = _put
        elif tag == "來源":
            out["ids"] += [int(x) for x in re.findall(r"\d+", _put)]
    items = _split_main("\n".join(rest), n_supp)
    if items:
        out["main"] = [p for p in items[0].split(MAIN_PARA) if p.strip()]
        out["supp"] = items[1:]
    out["headline"] = out["headline"].strip().rstrip("。")
    out["rate"] = re.sub(r"^\s*(?:對利率|→)\s*[:：｜|]?\s*", "", out["rate"]).strip()
    return out


def _material_text(arts: list[dict], briefs: list[dict]) -> tuple[str, list[dict]]:
    """材料編號：先全文、後標題快訊，代號 1..n。回傳 (給 AI 的文字, 依代號排的材料)。"""
    mats = list(arts) + list(briefs)
    parts = []
    for i, a in enumerate(arts, 1):
        parts.append(f"【報導{i}｜{a.get('source') or '—'}｜{_us_date(a.get('at', ''))}】"
                     f"{a['title']}\n{a['body']}")
    if briefs:
        parts.append("=== 以下只有標題與官方摘要 ===")
    for j, b in enumerate(briefs, len(arts) + 1):
        parts.append(f"【報導{j}｜{b.get('source') or '—'}｜{_us_date(b.get('at', ''))}｜只有標題】"
                     f"{b['title']}" + (f"——{b['summary']}" if b.get("summary") else ""))
    return "\n\n".join(parts), mats


def _link_of(x: dict) -> dict:
    return {"title": re.sub(r"\s*[-–—|]\s*[^-–—|]{1,30}$", "", x["title"]).strip() or x["title"],
            "link": x["link"], "source": x.get("source", ""), "at": x.get("at", "")}


def _pick_links(mats: list[dict], ids: list[int], n: int,
                per_tier: int | None = None) -> list[dict]:
    """主軸下方的來源＝AI 回報實際用到的報導；彭博、路透排前面。
    AI 沒回報代號時，退回材料裡排名最前的幾則。
    per_tier：原文（彭博、路透）與其他來源**各自**最多幾則——只是上限、
    不硬湊；避免原文把實際提供細節的報導擠掉（2026-10）。"""
    used = [mats[i - 1] for i in dict.fromkeys(ids) if 1 <= i <= len(mats)]
    if not used:
        used = list(mats)
    used = [x for x in used if x.get("link")]
    used.sort(key=lambda x: -_src_weight(x))       # 穩定排序：同級維持原順序
    out, seen, tier_n = [], [], {True: 0, False: 0}
    for x in used:
        c = _norm_title(x["title"])
        if any(_sim(c, s) > 0.55 for s in seen):    # 同一則的轉載只列一次
            continue
        orig = _src_weight(x) >= 3.0
        if per_tier is not None and tier_n[orig] >= per_tier:
            continue
        tier_n[orig] += 1
        seen.append(c)
        out.append(_link_of(x))
        if len(out) >= n:
            break
    return out


def _generate_main(src_text: str, system: str, env, *, caps, mins, meta_markers=None,
                   vague_markers=None, rate_ctx=None, name_map=None,
                   release_dates_: dict | None = None,
                   model: str | None = None) -> tuple[dict | None, str]:
    """
    版式 A 的生成＋驗證。回傳 ({text, headline, rate, ids}, "")；失敗回 (None, 原因)。
      後設字眼   重試一次，再犯就失敗
      數字鎖     2026-10-26 放寬：帶著缺出處的數字重寫一次，第二次照樣採用（只記 log）
      其他       長度、空話、標題、對利率、媒體名、相對時間 → 帶原因重寫一次，
                 第二次照樣採用並機械修正（裁長度、刪媒體說法、對利率改用規則句）
    """
    n_supp = len(caps) - 1
    hards = focus_hards(caps)
    vague_markers = vague_markers or DEFAULT_VAGUE_MARKERS
    best = None
    note = ""
    for attempt in (1, 2):
        text, err = _call_ai(src_text + note, system, env, model=model)
        if err:
            if best:
                break
            return None, err
        r = _parse_main_output(_tidy_focus(text), n_supp)
        if not r["main"]:
            return None, "輸出是空的"
        main = MAIN_PARA.join(r["main"])
        joined = "\n".join([r["headline"], main, r["rate"]] + r["supp"])
        meta = _meta_hits(joined, meta_markers)
        if meta:
            log.warning("市場焦點：輸出含後設字眼（%s），退回重試", "、".join(meta[:4]))
            note = ("\n\n（上一次的輸出在評論材料本身，被退回。請直接輸出重點，不要解釋"
                    "材料的多寡或你的處理過程。）")
            continue
        # 數字鎖（2026-10-26 放寬）：不再一票否決——第一次帶著是哪些數字重寫，
        # 第二次仍有就照樣採用、只記 log（使用者：模型夠強，寧可出稿也不要退回列標題）
        _miss = _missing_digits(joined, src_text)
        why = []
        if _miss:
            if attempt == 1:
                why.append("出現材料裡沒有的數字（" + "、".join(_miss[:5])
                           + "）：只能用材料裡有的數字，沒有出處的請刪掉或改成文字描述")
            else:
                log.warning("市場焦點：重寫後仍有材料沒有的數字（%s），照樣採用", "、".join(_miss[:5]))
        if cjk_len(main) > hards[0]:
            why.append(f"主軸超過 {hards[0]} 字")
        if mins and mins[0] and cjk_len(main) < int(mins[0] * SHORT_TOL):
            why.append(f"主軸只有 {cjk_len(main)} 字，沒有把事情講完整（要 {mins[0]}–{caps[0]} 字）")
        for i, s in enumerate(r["supp"], 2):
            if i - 1 < len(hards) and cjk_len(s) > hards[i - 1]:
                why.append(f"第 {i - 1} 則補充超過 {hards[i - 1]} 字")
            elif i - 1 < len(mins or []) and mins[i - 1] \
                    and cjk_len(s) < int(mins[i - 1] * SHORT_TOL):
                why.append(f"第 {i - 1} 則補充只有 {cjk_len(s)} 字，像在列標題"
                           "（要寫出發生了什麼再加一個具體細節）")
        if len(_meta_hits(joined, vague_markers)) >= 2:
            why.append("用了空泛的套話")
        if not (8 <= cjk_len(r["headline"]) <= 34):
            why.append("缺少一句 14–28 字的【標題】")
        _leak = sorted(set(_PROMPT_LEAK.findall(joined)))
        if _leak:
            why.append("用了「" + "、".join(_leak[:2]) + "」這種寫給你的指示用語，讀者看不懂，直接寫事件本身")
        if len(r["supp"]) < min(n_supp, 2):
            why.append(f"補充只有 {len(r['supp'])} 則（要 {n_supp} 則，各寫一件主軸以外的事）")
        if r["rate"] and cjk_len(r["rate"]) > RATE_MAX:
            why.append(f"【對利率】{cjk_len(r['rate'])} 字，超過 {RATE_MAX} 字，請精簡")
        if rate_ctx and not r["rate"]:
            why.append("缺少【對利率】那一句")
        else:
            why += ["【對利率】" + x for x in _rate_issues(r["rate"], rate_ctx, src_text)]
        _ph = _policy_hits(joined, rate_ctx)
        if _ph:
            why.append("正文的政策方向和現況相反（不得寫" + "、".join(_ph) + "）")
        media = _media_hits(joined)
        if media:
            why.append("正文寫了媒體名稱（" + "、".join(media[:3]) + "），來源會列在下方，直接寫事實")
        rel = sorted(set(_REL_DATE.findall(joined)))
        if rel:
            why.append("用了相對時間（" + "、".join(rel[:3]) + "），請改寫成月/日")
        _rd = _release_date_issues(joined, release_dates_)
        if _rd:
            why.append("數據公布日期錯誤（" + "、".join(
                f"{FACT_NAMES[x['kind']]}寫成「{x['wrong']}」，官方是 {x['right']}" for x in _rd[:3])
                + "；報導標頭的日期是報導發布日、不是數據公布日，請以「官方數據發布日」區塊為準）")
        r["main_text"] = main
        if attempt == 1 and why:
            best = r
            log.warning("市場焦點：%s，帶原因重寫一次", "；".join(why))
            note = ("\n\n（上一次的輸出被退回：" + "；".join(why) + "。請依格式重寫。）")
            continue
        best = r
        if why:
            log.warning("市場焦點：重寫後仍有：%s，機械修正後採用", "；".join(why))
        break
    if not best:
        return None, "輸出反覆評論材料本身（後設字眼）"
    r = best
    # 公布日期仍錯：機械改成官方日期（寧可改日期，不留錯的公布日）
    fix = lambda s: _fix_release_dates(normalize_names(_strip_leak(_strip_media(s)), name_map),
                                       _release_date_issues(s, release_dates_))
    main = _trim_item(fix(r["main_text"]), hards[0])
    supp = [_trim_item(fix(s), hards[i + 1] if i + 1 < len(hards) else hards[-1])
            for i, s in enumerate(r["supp"])]
    rate = fix(r["rate"])
    if rate_ctx and (not rate or not _rate_consistent(rate, rate_ctx, src_text)):
        rate = _rate_fallback(rate_ctx)
    # 重寫後正文仍有方向相反的說法：拿掉那一句（寧可少一句，不留錯的政策方向）
    if _policy_hits(main + "".join(supp), rate_ctx):
        def _drop(t):
            return "".join(x for x in re.split(r"(?<=[。！？])", t)
                           if x and not _policy_hits(x, rate_ctx))
        main = "¶".join(_drop(p) for p in main.split("¶"))
        supp = [_drop(x) for x in supp]
    headline = fix(r["headline"]) if 6 <= cjk_len(r["headline"]) <= 40 else ""
    return {"text": "\n".join([main] + supp), "headline": headline, "rate": rate,
            "ids": r["ids"]}, ""


def write_main(arts: list[dict], briefs: list[dict], keywords: list[str], env=None, *,
               caps, mins, meta_markers=None, vague_markers=None, rate_ctx=None,
               name_map=None, event_note: str = "", recent_note: str = "",
               mode: str = "content", facts_block: str = "",
               release_dates_: dict | None = None,
               model: str | None = None) -> tuple[dict | None, str]:
    """主軸（內文模式或標題模式共用）：材料編號 → AI → 驗證 → 來源連結。"""
    if not arts and not briefs:
        return None, "沒有任何材料"
    body, mats = _material_text(arts, briefs)
    src_text = body + _rate_block(rate_ctx) + facts_block
    system = _FOCUS_CONTENT_SYSTEM_A.format(
        kws="、".join(keywords), main=caps[0], supp=caps[1] if len(caps) > 1 else 0,
        ns=len(caps) - 1, min=(mins or [DEFAULT_MAIN_MIN])[0],
        event=event_note, recent=recent_note)
    res, err = _generate_main(src_text, system, env, caps=caps, mins=mins,
                              meta_markers=meta_markers, vague_markers=vague_markers,
                              rate_ctx=rate_ctx, name_map=name_map,
                              release_dates_=release_dates_, model=model)
    if not res:
        return None, err
    res["links"] = _pick_links(mats, res.pop("ids"), MAX_MAIN_LINKS,
                                MAIN_LINKS_PER_TIER)
    res["source"] = "model-content" if mode == "content" else "model"
    return res, ""


def summarize_content(articles: list[dict], keywords: list[str],
                      item_cap: int = DEFAULT_ITEM_CHARS, env=None,
                      briefs: list[dict] | None = None,
                      meta_markers=None, n_items: int = DEFAULT_ITEMS,
                      vague_markers=None, caps: list[int] | None = None,
                      mins: list[int] | None = None, **kw
                      ) -> tuple[str, str]:
    """
    讀文章內文寫成重點（相容舊介面）。caps 有給＝版式 A，走 write_main
    （標題＋主軸＋對利率＋補充）；回傳 (主軸與補充, "model-content")，
    失敗回 ("", 原因)。完整結果（標題、對利率、來源）請用 write_main。
    """
    if not articles and not briefs:
        return "", "沒有任何材料"
    if caps:
        res, err = write_main(articles, list(briefs or []), keywords, env, caps=caps,
                              mins=mins, meta_markers=meta_markers,
                              vague_markers=vague_markers, mode="content", **kw)
        return (res["text"], "model-content") if res else ("", err)
    src_text = "\n\n".join(
        f"【{a.get('source') or '—'}】{a['title']}\n{a['body']}"
        for a in articles)
    if briefs:
        src_text += ("\n\n=== 標題快訊（只有標題與官方摘要，沒有內文）"
                     "===\n"
                     + "\n".join(
                         f"【{b.get('source') or '—'}】{b['title']}"
                         + (f"——{b['summary']}" if b.get("summary") else "")
                         for b in briefs))
    system = _FOCUS_CONTENT_SYSTEM.format(kws="、".join(keywords),
                                          cap=item_cap, n=n_items)
    text, err = _generate_items(src_text, system, env, item_cap=item_cap,
                                n_items=n_items, meta_markers=meta_markers,
                                vague_markers=vague_markers)
    return (text, "model-content") if text else ("", err)


def _norm_title(t: str) -> str:
    """去掉尾巴的「 - 來源」、標點與空白，留下可比對的核心字串。"""
    t = re.sub(r"\s*[-–—|]\s*[^-–—|]{1,30}$", "", t)
    return re.sub(r"[\s，。、！？：；「」『』()（）\[\]【】,.:;!?'\"]+", "", t)


def _sim(a: str, b: str) -> float:
    """字元二元組的 Jaccard 相似度（0–1）。中文不需要斷詞，二元組就夠。"""
    if len(a) < 2 or len(b) < 2:
        return 1.0 if a == b else 0.0
    A = {a[i:i + 2] for i in range(len(a) - 1)}
    B = {b[i:i + 2] for i in range(len(b) - 1)}
    return len(A & B) / max(1, len(A | B))


# All news paths share the user-selected publisher tiers.
SOURCE_WEIGHT = (("reuters", 3.0), ("bloomberg", 3.0), ("wall street", 1.5),
                 ("financial times", 1.5), ("cnbc", 1.5),
                 ("federal reserve", 1.5), ("yahoo finance", 0.5))

# 發布日加分：當天（或前一天，台灣早上那次對應美國前一天）有這類
# 發布時，標題提到它的新聞加分——FOMC、CPI、非農當天，大家看的就是那件事。
EVENT_WORDS = {
    "fomc": ("FOMC", "聯準會", "Fed", "Warsh", "華許", "利率決策", "rate decision",
             "press conference", "記者會"),
    "cpi": ("CPI", "通膨", "inflation", "消費者物價"),
    "employment": ("非農", "就業", "payrolls", "jobs report", "unemployment"),
    "pce": ("PCE",),
    "ppi": ("PPI",),
    "jolts": ("JOLTS", "職缺"),
    "gdp": ("GDP", "經濟成長"),
    "retail": ("零售銷售", "retail sales"),
    "claims": ("初領", "失業金", "jobless claims"),
    "umich": ("密大", "密西根", "consumer sentiment"),
    "auction_10y": ("10 年期公債標售", "10-year auction", "10-year note auction"),
    "auction_30y": ("30 年期公債標售", "30-year auction", "30-year bond auction"),
    # v2（2026-10-25）新增
    "refunding": ("refunding", "再融資", "borrowing estimate", "借款估計", "發債規模"),
    "gdp_adv": ("GDP", "經濟成長", "國內生產毛額"),
    "fomc_minutes": ("minutes", "會議紀要", "會議記錄"),
    "testimony": ("testimony", "testify", "testifies", "聽證", "作證", "國會報告"),
}
FOREIGN_DEFAULT_EXTRA = ("France", "French", "Germany", "German", "Europe", "European", "euro zone",
                         "eurozone", "ECB", "China", "Chinese", "法國", "德國", "歐洲", "歐元區", "歐洲央行", "中國")
_FOREIGN_BASE = re.compile(r"(?<![A-Za-z])(?:Egypt|India|Indian|Pakistan|Bangladesh|Turkey|Turkish|Brazil|"
                      r"Nigeria|Kenya|Argentina|Mexico|Indonesia|Philippines|Vietnam|Thailand|Malaysia|"
                      r"South Africa|Poland|Hungary|Australia|New Zealand|Canada|UK|Britain|Korea|Korean|"
                      r"Sri Lanka|Ghana|rupee|rupiah|ringgit|baht|RBA|RBI)(?![A-Za-z])|埃及|印度|巴基斯坦|孟加拉|土耳其|巴西|奈及利亞|阿根廷|盧比|"
                      r"墨西哥|印尼|菲律賓|越南|泰國|馬來西亞|南非|波蘭|澳洲|紐西蘭|加拿大|英國|南韓|韓國|斯里蘭卡")
_US_WORDS = re.compile(r"(?<![A-Za-z])(?:US|U\.S\.|Fed|FOMC|Treasury|Treasuries|Wall Street|"
                       r"American|Warsh|Powell|Trump|dollar)(?![A-Za-z])|美國|美債|聯準會|美股|美元|川普|華許")


# ---- v2.2（2026-10-27）：可在 config/focus.yaml 的 selection 區調整的清單 ----
#   foreign_extra       外國新聞名單（追加）：標題沒提到美國 → −2；鎖定事件的 +8 改成 +2
#   junk_patterns       雜訊頁（正規式，不分大小寫）：股價頁、影片頁、個股清單 → 直接排除
#   oil_price_words     油價訊號只加給同時提到價格的標題（漏油、油輪事故不算）
JUNK_DEFAULT = (r"Stock Price\s*&\s*Latest News", r"\([A-Z0-9]{1,6}\.[A-Z]{1,3}\)",
                r"^Watch\s", r"Stocks to Watch", r"and Many More")
OIL_PRICE_DEFAULT = ("price", "prices", "futures", "Brent", "WTI", "barrel", "油價", "原油價格", "油價格", "期貨")


def _word_re(words) -> re.Pattern | None:
    ws = [str(w).strip() for w in words or () if str(w).strip()]
    if not ws:
        return None
    return re.compile("|".join((r"(?<![A-Za-z])" + re.escape(w).replace(r"\ ", r"\s+") + r"(?![A-Za-z])")
                               if w.isascii() else re.escape(w) for w in ws), re.I)


class _Foreign:
    """外國新聞判斷＝內建名單＋可追加的名單（保留 .search 介面）。"""
    def __init__(self, extra=FOREIGN_DEFAULT_EXTRA):
        self.extra = _word_re(extra)

    def search(self, t: str):
        return _FOREIGN_BASE.search(t or "") or (self.extra.search(t or "") if self.extra else None)


_FOREIGN = _Foreign()
_JUNK = [re.compile(p, re.I) for p in JUNK_DEFAULT]
_OIL_PRICE = _word_re(OIL_PRICE_DEFAULT)


def apply_selection_cfg(cfg: dict | None) -> None:
    """讀 config 的 selection 區（沒寫就用內建預設）。"""
    global _FOREIGN, _JUNK, _OIL_PRICE
    sel = (cfg or {}).get("selection") or {}
    _FOREIGN = _Foreign(tuple(FOREIGN_DEFAULT_EXTRA) + tuple(sel.get("foreign_extra") or ()))
    pats = tuple(JUNK_DEFAULT) + tuple(sel.get("junk_patterns") or ())
    _JUNK = []
    for p in pats:
        try:
            _JUNK.append(re.compile(str(p), re.I))
        except re.error as e:
            log.warning("市場焦點：selection.junk_patterns 有錯的正規式 %r（%s），略過", p, e)
    _OIL_PRICE = _word_re(tuple(OIL_PRICE_DEFAULT) + tuple(sel.get("oil_price_words") or ()))


def is_junk(title: str) -> bool:
    return any(p.search(title or "") for p in _JUNK)


def is_foreign(title: str) -> bool:
    t = _kw_text(title or "")
    return bool(_FOREIGN.search(t) and not _US_WORDS.search(t))
# 鎖定級事件：當天（或台灣隔天早上）只要有相關報導，主軸一定寫它。
# 初領失業金、密大信心這類每週／次要數據只加分、不鎖定。
# v2（2026-10-25）：加入主席國會證詞、季度再融資公告、GDP 初值（主席記者會與 FOMC 同日，併在 fomc）
LOCK_EVENTS = ("fomc", "cpi", "employment", "pce", "testimony", "refunding", "gdp_adv")
EVENT_NAMES = {"fomc": "FOMC 利率決策", "cpi": "CPI 通膨數據",
               "employment": "非農就業報告", "pce": "PCE 物價數據",
               "testimony": "聯準會主席國會證詞", "refunding": "財政部季度再融資公告",
               "gdp_adv": "GDP 初值"}
# 美東發布時間（判斷「公布前」寫預告）：沒列的用 watch_calendar.EVENTS
EVENT_TIMES = {"refunding": (8, 30), "gdp_adv": (8, 30), "fomc_minutes": (14, 0), "fomc": (14, 0)}


def _src_weight(h: dict) -> float:
    s = f"{h.get('source') or ''} {h.get('title') or ''}".lower()
    return max([w for k, w in SOURCE_WEIGHT if k in s] or [0.0])


def _age_hours(h: dict, now: dt.datetime) -> float | None:
    try:
        at = dt.datetime.fromisoformat(str(h.get("at")))
        if at.tzinfo is None:
            at = at.replace(tzinfo=dt.timezone.utc)
        return (now - at).total_seconds() / 3600
    except (TypeError, ValueError):
        return None


def _kw_words(kws) -> list[str]:
    """關鍵字清單。中文（含中英混寫）照舊用空白分組：「川普 聯準會」＝任一個詞命中都算。
    2026-10-27 v2.2：全英文的多字關鍵字改成整段比對——「Wall Street」「debt ceiling」
    拆開的話 street、debt 會命中幾乎所有新聞。"""
    out = []
    for kw in (kws or []):
        s = str(kw).strip()
        if not s:
            continue
        out += [s] if s.isascii() else s.split()
    return out


def _heat_map(pool: list[dict], words: list[str]) -> dict:
    """每個關鍵字詞被幾家**不同來源**的標題提到——大家都在報的主題。"""
    seen: dict = {}
    for h in pool:
        t = _kw_text(h.get("title") or "")
        src = (h.get("source") or "").lower()
        for w in words:
            if _kw_hit(w, t):
                seen.setdefault(w, set()).add(src)
    return {w: len(v) for w, v in seen.items()}


# ---------------------------------------------------------------------------
# v2（2026-10-25）：期中選舉、事件分組、市場訊號、鎖定事件撞期
# ---------------------------------------------------------------------------
# 美國期中選舉＝次級詞。只認明確的選舉片語（不用 House、Senate 單字：White House 會誤判）；
# 標題要同時有「美國」與「市場或政策影響」字樣才算，不符合的直接排除（其他國家的選舉、純選情）。
_ELECTION_RE = re.compile(r"(?<![A-Za-z])(?:midterms?|Senate races?|House majority|"
                          r"control of (?:the )?Congress)(?![A-Za-z])|期中選舉|中期選舉|參議院|眾議院|國會選舉|選情",
                          re.I)
_ELECTION_US = re.compile(r"(?<![A-Za-z])(?:US|U\.S\.|American|America|Trump|Congress|Republicans?|"
                          r"Democrats?|GOP)(?![A-Za-z])|美國|美方|川普|國會|共和黨|民主黨")
_ELECTION_MKT = re.compile(r"(?<![A-Za-z])(?:stocks?|bonds?|Treasur(?:y|ies)|yields?|dollar|markets?|"
                           r"investors?|Wall Street|tariffs?|fiscal|tax cuts?|deficits?|spending)(?![A-Za-z])|"
                           r"美股|美債|殖利率|美元|市場|投資人|關稅|財政|減稅|赤字|股市|債市|華爾街")


def election_ok(title: str) -> bool:
    """選舉標題能不能用：要有美國字樣＋市場或政策影響字樣。不是選舉標題一律 True。"""
    t = title or ""
    if not _ELECTION_RE.search(t):
        return True
    return bool(_ELECTION_US.search(t) and _ELECTION_MKT.search(t))


def election_filter(items: list[dict]) -> list[dict]:
    return [x for x in items if election_ok(x.get("title") or "")]


# 事件分組：同一件事的不同報導歸成一組。中英文標題字面不像，改比對共同的數字（帶 % 或小數）
# 與專有名詞（人名統一成中文譯名、常見英文縮寫）。
_NUM_TOKEN = re.compile(r"\d+(?:\.\d+)?\s*%|\d+\.\d+|\d{2,}(?:萬|億|bp|個基點)")
_ENT_TOKENS = ("CPI", "PCE", "PPI", "GDP", "FOMC", "JOLTS", "OPEC", "Nvidia", "輝達", "Fed", "聯準會",
               "財政部", "Treasury", "tariff", "關稅", "oil", "油價", "原油", "gold", "黃金", "Iran", "伊朗",
               "AI", "payrolls", "非農", "refunding", "再融資", "yen", "日圓", "BOJ", "日本央行")
STORY_SIM = 0.45


def _story_tokens(title: str) -> tuple[set, set]:
    t = title or ""
    nums = {re.sub(r"\s+", "", m).replace("個基點", "bp") for m in _NUM_TOKEN.findall(t)}
    ents = set()
    for canon, aliases in DEFAULT_NAME_MAP.items():
        if canon in t or any(_kw_hit(a, t) for a in aliases):
            ents.add(canon)
    for w in _ENT_TOKENS:
        if _kw_hit(w, t):
            ents.add({"Nvidia": "輝達", "Fed": "聯準會", "Treasury": "財政部", "tariff": "關稅",
                      "oil": "油價", "原油": "油價", "gold": "黃金", "Iran": "伊朗", "payrolls": "非農",
                      "refunding": "再融資", "yen": "日圓", "BOJ": "日本央行"}.get(w, w))
    return nums, ents


def same_story(a: str, b: str) -> bool:
    """兩則標題是不是同一件事：字面相似，或共享數字＋至少一個專有名詞，或共享兩個以上專有名詞＋一個數字。"""
    if _sim(_norm_title(a), _norm_title(b)) > STORY_SIM:
        return True
    na, ea = _story_tokens(a)
    nb, eb = _story_tokens(b)
    return bool(na & nb) and bool(ea & eb)


def cluster_events(items: list[dict], score) -> list[dict]:
    """
    把標題歸成事件，回傳依分數由高到低的事件清單：
      [{"items": [...依分數排], "score": 事件分數, "sources": 不同媒體數, "lead": 最高分標題}]
    事件分數＝最高分那則的分數＋不同媒體數加成（min(N−1, 3)）＋市場訊號（由呼叫端給的 score 已含）。
    """
    scored = sorted(((score(x), i, x) for i, x in enumerate(items)), key=lambda z: (-z[0], z[1]))
    groups: list[dict] = []
    for s, _, x in scored:
        for g in groups:
            if any(same_story(x["title"], y["title"]) for y in g["items"][:6]):
                g["items"].append(x)
                g["scores"].append(s)
                break
        else:
            groups.append({"items": [x], "scores": [s]})
    out = []
    for g in groups:
        srcs = {(_src_name(y) or y.get("link", ""))for y in g["items"]}
        n = len(srcs)
        out.append({"items": g["items"], "lead": g["items"][0], "sources": n,
                    "score": round(g["scores"][0] + min(max(n - 1, 0), 3), 2)})
    out.sort(key=lambda g: -g["score"])
    return out


MAIN_MAX_ITEMS = 4          # v2.2：主軸材料（同一件事＋同主題相關報導）最多幾則
HEADLINE_ONLY_MIN = 120     # v2.2：主軸材料全部只有標題時的字數下限（原本 200）
_LEAD_FRAC = 0.45           # 標題「主角」＝標題前 45%（至少 20 字元）出現的專有名詞


def _lead_ents(title: str) -> set:
    t = title or ""
    return _story_tokens(t[:max(int(len(t) * _LEAD_FRAC), 20)])[1]


def related_items(main_c: dict, others: list[dict], n: int) -> tuple[list[dict], list[dict]]:
    """
    主軸那件事不到 MAIN_MAX_ITEMS 則時，從其他事件挑「標題主角相同」的報導補進主軸材料
    （例：主軸是「Warsh 如何說服市場」，補「Fed Meeting Focus Turns to Warsh」；
    「金價因 Fed 會議走穩」主角是黃金，不算）。回傳 (補進來的報導, 剩下的事件)。
    熱度（幾家媒體報同一件事）不受影響——相關報導不算同一件事。
    """
    if n <= 0:
        return [], others
    ents = _lead_ents(main_c["lead"]["title"])
    if not ents:
        return [], others
    got, rest = [], []
    for g in others:
        if len(got) < n and (_lead_ents(g["lead"]["title"]) & ents):
            got.append(g["lead"])
        else:
            rest.append(g)
    return got, rest


def _src_name(h: dict) -> str:
    """同一家媒體的判斷：RSS 的 source 欄，或 Google News 標題尾巴的「 - 來源」。"""
    s = (h.get("source") or "").strip().lower()
    if s and s not in ("google news",):
        return s
    m = re.search(r"\s[-–—|]\s*([^-–—|]{1,30})$", h.get("title") or "")
    return (m.group(1).strip().lower() if m else s)


# 市場訊號（線索，不強制）：變化超過門檻 → 提到這個市場的事件 +3。
# Yahoo 報價時間超過 12 小時的指標不加分（晚上兩次常是前一個交易日的變化）；油價期貨幾乎 24 小時交易照常算。
SIGNAL_BONUS = 3.0
SIGNAL_MAX_AGE_H = 12
SIGNAL_THRESH = {"rates_bp": 6, "oil_pct": 3.0, "spx_pct": 1.5, "fw_pp": 10}
SIGNAL_WORDS = {
    "rates": ("yield", "Treasury", "Treasuries", "bond", "bonds", "殖利率", "美債", "公債", "債市"),
    "oil": ("oil", "crude", "OPEC", "Brent", "WTI", "油價", "原油"),
    "equity": ("stocks", "S&P", "Wall Street", "Nasdaq", "Dow", "美股", "股市", "華爾街"),
    "policy": ("rate cut", "rate hike", "Fed", "FOMC", "降息", "升息", "聯準會", "Warsh", "華許"),
}


def market_signals(live10: dict | None, rates_series: dict | None, oil: dict | None,
                   spx: dict | None, fw_change_pp: float | None, now_utc: dt.datetime) -> dict:
    """回傳 {"rates": "10Y +8bp", "oil": "+3.4%", …}：只列超過門檻、而且報價不過時的指標。"""
    sig = {}
    fresh = lambda ts: ts is not None and (now_utc - ts).total_seconds() <= SIGNAL_MAX_AGE_H * 3600
    if live10 and live10.get("ts") is not None and fresh(live10["ts"]):
        if abs(live10.get("d_today") or 0) >= SIGNAL_THRESH["rates_bp"]:
            sig["rates"] = f"10 年期 {live10['d_today']:+d}bp"
    if "rates" not in sig:
        rows = [r for r in (rates_series or {}).get("DGS2") or [] if r.get("value") is not None and not r.get("live")]
        if len(rows) >= 2:
            try:
                d = dt.date.fromisoformat(str(rows[-1]["date"])[:10])
                # 官方日資料的時間＝美東當天收盤（約 UTC 21:00）
                ts = dt.datetime(d.year, d.month, d.day, 21, tzinfo=dt.timezone.utc)
            except (ValueError, TypeError):
                ts = None
            bp = round((rows[-1]["value"] - rows[-2]["value"]) * 100)
            if fresh(ts) and abs(bp) >= SIGNAL_THRESH["rates_bp"]:
                sig["rates"] = f"2 年期 {bp:+d}bp"
    if oil and oil.get("prev"):
        pct = (oil["value"] / oil["prev"] - 1) * 100
        if abs(pct) >= SIGNAL_THRESH["oil_pct"]:
            sig["oil"] = f"油價 {pct:+.1f}%"
    if spx and spx.get("prev") and fresh(spx.get("ts")):
        pct = (spx["value"] / spx["prev"] - 1) * 100
        if abs(pct) >= SIGNAL_THRESH["spx_pct"]:
            sig["equity"] = f"S&P 500 {pct:+.1f}%"
    if fw_change_pp is not None and abs(fw_change_pp) >= SIGNAL_THRESH["fw_pp"]:
        sig["policy"] = f"FedWatch {fw_change_pp:+.0f} 個百分點"
    return sig


def signal_bonus(title: str, sig: dict) -> float:
    t = _kw_text(title or "")
    for k in sig:
        if any(_kw_hit(w, t) for w in SIGNAL_WORDS.get(k, ())):
            # v2.2：油價訊號只加給提到價格的標題（10/25「UAE 漏油、關閉海灘」誤拿 +3）
            if k == "oil" and not (_OIL_PRICE and _OIL_PRICE.search(t)):
                continue
            return SIGNAL_BONUS
    return 0.0


_YIELD_LINK = ("yield", "yields", "Treasuries", "Treasury", "bond market", "殖利率", "美債", "債市")


def resolve_locks(locks: list[str], heads: list[dict]) -> tuple[list[str], list[str]]:
    """
    兩個以上鎖定事件撞期：看哪件事的相關標題比較多同時提到美債／殖利率，主軸寫那一件；
    平手寫再融資，再平手照 LOCK_EVENTS 的順序。回傳 (主鎖定, 降為加分的事件)。
    """
    if len(locks) <= 1:
        return list(locks), []
    def links(kind):
        n = 0
        for h in heads:
            t = _kw_text(h.get("title") or "")
            if any(_kw_hit(w, t) for w in EVENT_WORDS.get(kind, ())) and \
                    any(_kw_hit(w, t) for w in _YIELD_LINK):
                n += 1
        return n
    order = {k: i for i, k in enumerate(LOCK_EVENTS)}
    best = sorted(locks, key=lambda k: (-links(k), 0 if k == "refunding" else 1, order.get(k, 99)))[0]
    return [best], [k for k in locks if k != best]


_TESTIMONY_RE = re.compile(r"(?:Warsh|華許|Fed chair|聯準會主席).{0,40}(?:testimony|testif|Congress|Senate Banking|"
                           r"House Financial|國會|聽證|作證)|(?:testimony|testif|國會|聽證|作證).{0,40}(?:Warsh|華許|Fed chair|聯準會主席)",
                           re.I)


_PREVIEW_RE = re.compile(r"(?<![A-Za-z])(?:will|to testify|set to|next week|ahead of|preview)(?![A-Za-z])|下週|將赴|將出席|將於|將在|預計|前瞻", re.I)


def testimony_today(heads: list[dict]) -> bool:
    """主席國會證詞沒有可靠的行事曆來源：靠新聞標題判斷（兩則以上不同標題提到）。
    v2.2：「下週將赴國會作證」這類預告標題不算。"""
    return sum(1 for h in heads if _TESTIMONY_RE.search(h.get("title") or "")
               and not _PREVIEW_RE.search(h.get("title") or "")) >= 2


def derive_events(events: dict | None, cfg: dict | None, refunding: list[str] | None = None) -> dict:
    """在 watch_calendar 的事件之外補上：GDP 初值（1／4／7／10 月那一次）、FOMC 會議紀要（會後 21 天）、再融資公告。"""
    ev = {k: list(v) if not isinstance(v, str) else [v] for k, v in (events or {}).items()}
    gdp = [str(d)[:10] for d in ev.get("gdp") or []]
    ev["gdp_adv"] = [d for d in gdp if d[5:7] in ("01", "04", "07", "10")]
    mins = []
    for d in (cfg or {}).get("fomc_dates") or []:
        try:
            mins.append((dt.date.fromisoformat(str(d)[:10]) + dt.timedelta(days=21)).isoformat())
        except ValueError:
            continue
    ev["fomc_minutes"] = mins
    if refunding:
        ev["refunding"] = sorted({str(d)[:10] for d in refunding if d})
    return ev


def released_yet(kind: str, events: dict | None, cfg: dict | None, now_tw: dt.datetime) -> bool:
    """這個事件「今天（美東日期＝台北日期）」的那一次是不是已經公布了。不是今天的事件一律 True。"""
    from . import watch_calendar as wc
    today = now_tw.date()
    dates = [str(d)[:10] for d in ((events or {}).get(kind) or [])]
    if kind == "fomc":
        dates += [str(d)[:10] for d in (cfg or {}).get("fomc_dates") or []]
    if today.isoformat() not in dates:
        return True
    hm = EVENT_TIMES.get(kind) or (wc.EVENTS.get(kind) or (None, None, (8, 30)))[2]
    return now_tw >= wc.taipei_time(today, hm)


def event_day(kind: str, events: dict | None, cfg: dict | None, now_tw: dt.datetime) -> str:
    """鎖定事件是哪一天（美東）：今天或前一天那一次，寫成「10/14」。給 AI 的提示寫明確日期，不寫「今天」。"""
    dates = [str(d)[:10] for d in ((events or {}).get(kind) or [])]
    if kind == "fomc":
        dates += [str(d)[:10] for d in (cfg or {}).get("fomc_dates") or []]
    today = now_tw.date()
    for d in (today, today - dt.timedelta(days=1)):
        if d.isoformat() in dates:
            return f"{d.month}/{d.day}"
    return f"{today.month}/{today.day}"


def is_weekly(now_tw: dt.datetime) -> bool:
    """星期天早上（台北中午以前）改寫「本週回顧與下週重點」。"""
    return now_tw.weekday() == 6 and now_tw.hour < 12


def rank_score(h: dict, keywords, secondary=None, *, heat=None, now=None,
               events=None, lock_events=(), recent=None, parts: dict | None = None) -> float:
    """
    一則標題的重要性分數，全部確定性規則（看得到、測得到）：
      主題    主級關鍵字一次 2 分；次級每個 0.5 分、最多 1 分
      熱度    同一個主級詞被 N 家不同來源報導 → 加 min(N−1, 3) 分
      時效    12 小時內 +2、24 小時內 +1.5、48 小時內 +0.5
      來源    彭博、路透 +3；其他財經專業媒體、官方發布 +1.5；Yahoo Finance +0.5
      發布日  當天有 FOMC／CPI／非農等發布、標題又提到它 → +2；
              鎖定級事件（LOCK_EVENTS：FOMC、CPI、非農、PCE）→ +8，
              確保主軸一定寫它（2026-10 使用者指定）
      重複    前一兩次主軸已經用過的同一則報導 → −4（換寫別的事件；
              同一件事有新進展時，新報導的標題通常不同，不受影響）
              鎖定級事件的報導不扣
    """
    t = _kw_text(h.get("title") or "")
    p_words, s_words = _kw_words(keywords), _kw_words(secondary)
    hit_p = [w for w in p_words if _kw_hit(w, t)]
    hit_s = [w for w in s_words if _kw_hit(w, t)]
    if _ELECTION_RE.search(t) and election_ok(t):   # v2：美國期中選舉＝次級詞
        hit_s.append("election")
    # 第十七批：主軸回到利率主線——次級詞（AI、油價、黃金…）最多加 1 分，
    # 熱度只算主級詞；否則 AI 新聞家家都報，熱度＋來源分就把利率新聞擠掉
    #（實測：週日的前六名全是 AI）。
    pt = {}                                         # v2.2：分數明細（寫進 focus_log）
    if hit_p:
        pt["主題"] = 2.0 * len(hit_p)
    if hit_s:
        pt["次級"] = min(0.5 * len(hit_s), 1.0)
    if heat:
        n = max([heat.get(w, 0) for w in hit_p] or [0])
        if n > 1:
            pt["熱度"] = float(min(n - 1, 3))
    if now is not None:
        age = _age_hours(h, now)
        if age is not None:
            a = (2.0 if age <= 12 else 1.5 if age <= 24 else 0.5 if age <= 48 else 0.0)
            if a:
                pt["時效"] = a
    sw = _src_weight(h)
    if sw:
        pt["來源"] = sw
    # 其他國家的本地新聞（埃及通膨、孟加拉關稅）只是同字命中：沒提到美國就 −2
    foreign = bool(_FOREIGN.search(t) and not _US_WORDS.search(t))
    if foreign:
        pt["外國"] = -2.0
    ev_hit = False
    _evs = sorted(events or (), key=lambda k: k not in (lock_events or ()))
    for kind in _evs:
        if any(_kw_hit(w, t) for w in EVENT_WORDS.get(kind, ())):
            # v2.2：外國的同類數據（歐元區 GDP、英國通膨）不拿鎖定的 +8，只拿一般 +2
            ev_hit = kind in (lock_events or ()) and not foreign
            pt["鎖定" if ev_hit else "發布日"] = 8.0 if ev_hit else 2.0
            break
    if recent and not ev_hit:
        c = _norm_title(h.get("title") or "")
        if any(_sim(c, r) > 0.5 for r in recent):
            pt["重複"] = -4.0
    if parts is not None:
        parts.update(pt)
    return float(sum(pt.values()))


def pick_fallback(headlines: list[dict], keywords: list[str],
                  n: int = 3, exclude: list[str] | None = None,
                  secondary: list[str] | None = None, *,
                  pool: list[dict] | None = None, now=None,
                  events=None, lock_events=(), recent=None) -> list[dict]:
    """
    依 rank_score 挑前 n 則（同分維持輸入順序，也就是新的在前）。

    pool 是算「熱度」用的完整標題池（預設＝headlines 本身）——內文候選
    與標題快訊是兩個子集合，熱度要拿全部標題算才準。

    挑的時候擋掉「同一件事的另一種寫法」：fetch 端的去重是完全比對
    （去尾巴後前 40 字），同一則新聞在不同媒體的標題只要改幾個字就會
    穿過去——實際發生過「來源標題選到兩則一樣的新聞」。這裡再用
    字元二元組相似度把 >0.55 的視為重複，跳過選下一則。
    """
    heat = _heat_map(pool if pool is not None else headlines,
                     _kw_words(keywords) + _kw_words(secondary))
    ranked = sorted(headlines, reverse=True,
                    key=lambda h: rank_score(h, keywords, secondary,
                                             heat=heat, now=now,
                                             events=events,
                                             lock_events=lock_events,
                                             recent=recent))
    picked = []
    for h in ranked:
        # 排除詞在挑選層也擋一次：Google News 標題模式不經過 feed 的
        # 過濾，只在這裡把關
        if _excluded(h["title"], exclude):
            continue
        cand = _norm_title(h["title"])
        if any(_sim(cand, _norm_title(p["title"])) > 0.55 for p in picked):
            continue
        picked.append(h)
        if len(picked) >= n:
            break
    return picked


# ---------------------------------------------------------------------------
# Gemini：焦點段（無接地）與 FedWatch 擷取（搜尋接地）
# ---------------------------------------------------------------------------
_FOCUS_SYSTEM = (
    "你是財經編輯。輸入是新聞標題清單（有些附官方摘要）。挑出對"
    "「美國公債殖利率與聯準會政策」最重要的 {n} 件事，寫成 {n} 則重點："
    "每則一行、只講一件事、{cap} 個中文字以內，最重要的放第一則；"
    "每則要寫出具體的事（誰、做了什麼），不要寫「成為市場焦點」「備受"
    "關注」這類空話。只能使用標題與摘要裡已有的資訊，不得補充任何以外"
    "的事實或數字；不做預測、不下投資結論；繁體中文。標題只夠寫一兩則"
    "就只寫一兩則。直接輸出那幾則，每則一行，不要編號、不要符號開頭、"
    "不要任何前言。")


# 版式 A 的標題模式（只有標題＋官方摘要時）。主軸寫不厚是材料限制，
# 規則不放寬：仍只能轉述標題與摘要字面上有的事。
# 標題模式（一篇內文都抓不到時）：同一套格式，材料全部是「只有標題」。
_FOCUS_SYSTEM_A = _FOCUS_CONTENT_SYSTEM_A


# ---------------------------------------------------------------------------
# 官方數據發布日（2026-10）
# 事故：主軸寫「美國勞動統計局 10/19 公布九月 CPI」——實際是 10/14。材料是一篇 10/19 的報導
# （談 CPI 的後續評論），模型把「報導日期」當成「數據公布日」；數字鎖只檢查數字有沒有出現在
# 材料裡，報導標頭本來就有 10/19，所以放行。
# 修法：①把官方行事曆（config/releases_calendar.yaml）與本站算好的數字當成權威區塊交給模型；
#       ②產出後檢查「M/D 公布」這類日期，跟該數據的官方日期對不上就退回重寫，仍錯就機械改正。
# ---------------------------------------------------------------------------
FACT_NAMES = {"cpi": "CPI", "ppi": "PPI", "pce": "PCE", "employment": "非農就業報告",
              "jolts": "JOLTS 職缺", "gdp": "GDP", "retail": "零售銷售", "umich": "密大消費者信心"}
FACT_ALIASES = {"cpi": ("CPI", "消費者物價"), "ppi": ("PPI", "生產者物價"),
                "pce": ("PCE", "個人消費支出"), "employment": ("非農", "就業報告"),
                "jolts": ("JOLTS", "職缺"), "gdp": ("GDP", "國內生產毛額"),
                "retail": ("零售銷售",), "umich": ("密大", "密西根")}
_PUB = r"(?:公布|公佈|發布|發佈|出爐|釋出)"
_WD7 = "一二三四五六日"


def _period_zh(kind: str, period: str) -> str:
    m = re.match(r"(\d{4})Q(\d)-?(\w*)", period)
    if m:
        stage = {"advance": "初估", "second": "第二次估計", "third": "第三次估計"}.get(m[3], "")
        return f"第{'一二三四'[int(m[2]) - 1]}季{stage}"
    m = re.match(r"\d{4}-(\d{2})", period)
    return f"{int(m[1])} 月" if m else period


def release_facts(calendar: dict | None, today: dt.date, values: dict | None = None,
                  back: int = 21, ahead: int = 14) -> list[dict]:
    """官方行事曆中，今天往前 back 天、往後 ahead 天內的發布：[{kind, period, date, done, values}]。
    values＝{kind: (period, 文字)}：本站算好的數字，只附在期別相同的那一筆。"""
    out = []
    for kind, per in (calendar or {}).items():
        if kind not in FACT_NAMES or not isinstance(per, dict):
            continue
        for period, d in per.items():
            try:
                dd = dt.date.fromisoformat(str(d)[:10])
            except ValueError:
                continue
            if today - dt.timedelta(days=back) <= dd <= today + dt.timedelta(days=ahead):
                v = (values or {}).get(kind)
                out.append({"kind": kind, "period": str(period), "date": dd.isoformat(),
                            "done": dd <= today,
                            "values": v[1] if v and str(v[0]) == str(period)[:7] else ""})
    return sorted(out, key=lambda f: f["date"])


# FRED 官方行事曆只有日期、沒有資料期別：依各數據的慣例落後推期別（只用在手動行事曆沒有的日期）
_FACT_LAG = {"employment": 1, "cpi": 1, "ppi": 1, "retail": 1, "pce": 1, "jolts": 2, "umich": 0}


def _infer_period(kind: str, d: dt.date) -> str | None:
    if kind == "gdp":
        k = (d.month - 1) % 3 + 1                       # 季末後第幾個月：1 初估、2 第二次、3 第三次
        end_m, y = d.month - k, d.year
        if end_m <= 0:
            end_m, y = end_m + 12, y - 1
        return f"{y}Q{(end_m - 1) // 3 + 1}-" + {1: "advance", 2: "second", 3: "third"}[k]
    if kind not in _FACT_LAG:
        return None
    m, y = d.month - _FACT_LAG[kind], d.year
    if m <= 0:
        m, y = m + 12, y - 1
    return f"{y}-{m:02d}"


def merge_calendar(calendar: dict | None, fred: dict | None) -> dict:
    """手動行事曆＋FRED 官方行事曆：同一個日期以手動檔的期別為準；FRED 有、手動檔沒有的日期補進來。
    手動檔一年校準一次，FRED 會自動延伸到下一年，兩者合併後不會在年底「用完」。"""
    out = {k: dict(v) for k, v in (calendar or {}).items() if isinstance(v, dict)}
    for kind, ds in (fred or {}).items():
        if kind not in FACT_NAMES:
            continue
        have = {str(x)[:10] for x in (out.get(kind) or {}).values()}
        for iso in ds:
            iso = str(iso)[:10]
            if iso in have:
                continue
            try:
                per = _infer_period(kind, dt.date.fromisoformat(iso))
            except ValueError:
                continue
            if per and per not in (out.get(kind) or {}):
                out.setdefault(kind, {})[per] = iso
    return out


def release_dates(calendar: dict | None) -> dict[str, list[str]]:
    """{kind: [ISO…]}：行事曆裡每種數據的所有官方發布日（驗證用）。"""
    return {k: sorted(str(d)[:10] for d in v.values())
            for k, v in (calendar or {}).items() if k in FACT_NAMES and isinstance(v, dict)}


def _facts_block(facts: list[dict]) -> str:
    if not facts:
        return ""
    md = lambda s: f"{int(s[5:7])}/{int(s[8:10])}（{_WD7[dt.date.fromisoformat(s).weekday()]}）"
    lines = [f"- {_period_zh(f['kind'], f['period'])} {FACT_NAMES[f['kind']]}：美東 {md(f['date'])}"
             + ("已公布" if f["done"] else "將公布") + (f"；{f['values']}" if f["values"] else "")
             for f in facts]
    return ("\n\n=== 官方數據發布日（美東時間；來源：官方行事曆與本站資料，以此為準）===\n"
            + "\n".join(lines)
            + "\n※ 報導標頭的日期是「報導發布日」，不是數據公布日。寫到任何數據的公布日期，一律以上表為準；"
              "上表沒有的數據不要寫公布日期。上表有數字的，以上表的數字為準。"
              "報導若是數據公布之後的評論（官員發言、市場反應），要寫清楚是哪一天的事，不要跟公布當天混在一起。")


def _release_date_issues(text: str, dates: dict[str, list[str]] | None, today: dt.date | None = None) -> list[dict]:
    """找出「M/D 公布」與官方日期對不上的地方。同一句提到多種數據時，日期只要是其中任一種的官方日就放行。"""
    if not dates:
        return []
    today = today or clock.today()
    out = []
    for sent in re.split(r"(?<=[。！？；\n¶])", text or ""):
        kinds = [k for k, al in FACT_ALIASES.items() if k in dates and any(a in sent for a in al)]
        if not kinds:
            continue
        ok = {f"{int(d[5:7])}/{int(d[8:10])}" for k in kinds for d in dates[k]}
        for m in re.finditer(r"(\d{1,2})/(\d{1,2})(?=[^。，；！？]{0,10}?" + _PUB + ")", sent):
            tok = f"{int(m[1])}/{int(m[2])}"
            if tok in ok:
                continue
            past = [d for d in dates[kinds[0]] if d <= today.isoformat()]
            right = past[-1] if past else dates[kinds[0]][0]
            out.append({"kind": kinds[0], "wrong": m.group(0), "right": f"{int(right[5:7])}/{int(right[8:10])}",
                        "sent": sent})
    return out


def _fix_release_dates(text: str, issues: list[dict]) -> str:
    for it in issues:
        if it["sent"] in text:
            text = text.replace(it["sent"], it["sent"].replace(it["wrong"], it["right"], 1), 1)
    return text


_MONTHS_EN = ("january", "february", "march", "april", "may", "june", "july", "august",
              "september", "october", "november", "december")
_MONTH_RE = re.compile(r"(?<![A-Za-z])(" + "|".join(m[:3] for m in _MONTHS_EN) + r")[a-z]*\.?(?![A-Za-z])", re.I)


def _missing_digits(text: str, source: str) -> list[str]:
    """
    輸出裡不在來源的數字串（防 AI 編數字）。英文月份（December、Dec.）算成對應的數字，
    「12 月」不會因為材料只寫英文月份而被當成編造（2026-10-26）。
    """
    src = re.sub(r"[\s,，]", "", source)
    months = {str(_MONTHS_EN.index(next(x for x in _MONTHS_EN if x.startswith(m.group(1).lower()))) + 1)
              for m in _MONTH_RE.finditer(source or "")}
    out = []
    for num in re.findall(r"\d+(?:\.\d+)?", (text or "").replace(",", "")):
        if num not in src and num not in months and num not in out:
            out.append(num)
    return out


def _digits_ok(text: str, source: str) -> bool:
    """輸出裡的每一串數字都必須出現在來源裡（月份對照見 _missing_digits）。"""
    return not _missing_digits(text, source)


def summarize(headlines: list[dict], item_cap: int = DEFAULT_ITEM_CHARS,
              env=None, n_items: int = DEFAULT_ITEMS, meta_markers=None,
              vague_markers=None, caps: list[int] | None = None,
              mins: list[int] | None = None, **kw
              ) -> tuple[str, str]:
    """標題模式：只有標題（＋官方摘要）可用時寫成重點。
    回傳 (重點, "model")；失敗回 ("", 原因)。"""
    if caps:
        res, err = write_main([], list(headlines[:24]), kw.pop("keywords", None) or DEFAULT_KEYWORDS,
                              env, caps=caps, mins=mins, meta_markers=meta_markers,
                              vague_markers=vague_markers, mode="title", **kw)
        return (res["text"], "model") if res else ("", err)
    lines = "\n".join(
        f"- [{h.get('source') or '—'}] {h['title']}"
        + (f"——{h['summary']}" if h.get("summary") else "")
        for h in headlines[:24])
    system = _FOCUS_SYSTEM.format(cap=item_cap, n=n_items)
    text, err = _generate_items(
        lines, system, env,
        item_cap=item_cap, n_items=n_items, meta_markers=meta_markers,
        vague_markers=vague_markers)
    return (text, "model") if text else ("", err)


# ---------------------------------------------------------------------------
# FedWatch 第一層：聯邦基金期貨自算（FedWatch／WIRP 的同款方法）
# ---------------------------------------------------------------------------
YQ_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
          "?range=5d&interval=1d")
# 報價 chip 用一年日線：同一次請求順便算 MTD／YTD 基準（第十八批）
YQ_URL_1Y = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
             "?range=1y&interval=1d")
# 預設目標會議（config 的 fedwatch_meeting 蓋掉它；一年更新一次）
DEFAULT_MEETING = "2026-12-09"

# FedWatch 的算法版本。state 的當日快取只在版本一致時沿用——
# 修了算法之後當天的下一次執行就重算，不必等到隔天。
# 1＝單合約 vs FRED 中點；2＝雙合約價差＋品質閘門；
# 3＝2 ＋遠月停滯偵測＋Atlanta 交叉檢核；
# 4＝WIRP 逐會議法（日曆日加權、不封頂、正負＝升降息）
# 6＝回傳值多帶逐場 meetings（聯準會頁用），算法同 5
FW_METHOD = 7   # 第十八批：三個累計節點（今年底／明年中／明年底）


def _last_value(rows) -> float | None:
    rows = [r for r in (rows or []) if r.get("value") is not None]
    return rows[-1]["value"] if rows else None


_ZQ_MEMO: dict = {}


def fetch_zq_implied(symbol: str, _get=None,
                     require_movement: bool = False,
                     with_prev: bool = False):
    """
    抓一檔聯邦基金期貨，回傳隱含利率（100 − 價格）。

    價格**優先取近五個交易日的最後一筆日收盤（結算價）**，不是
    regularMarketPrice：遠月的 ZQ 合約流動性很低，「最新成交價」可能是
    幾個月前的一筆舊成交，直接用會把隱含利率整個帶偏——實際發生過
    機率顯示 100% 的事故，最可疑的就是這裡。日收盤是交易所每天標記的
    結算價，沒有成交也會更新。

    `require_movement`（給**遠月**合約用）：五天的收盤必須「有在動」。
    正常的遠月結算價每天被交易所重新標記，多少會動一兩個 tick；
    連續五天一模一樣、或五天裡湊不出兩筆有效收盤，代表這張合約的
    報價鏈是死的——這正是 100% 事故最後一型的長相（畫面上連續多日
    +0.0 pp）。當月合約**不能**開這個檢查：它被已實現的實際利率釘住，
    平盤好幾天是正常的。
    """
    # 同一次執行裡首頁（fedwatch_path）與情境頁（futures_curve）抓同一批合約：
    # 記住原始回應，兩邊用的是同一筆報價，數字一定一致（測試注入 _get 時不記）
    _memo = _get is None
    get = _get or (lambda url: requests.get(
        url, timeout=TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0 (macro-dashboard)"}))
    try:
        if _memo and symbol in _ZQ_MEMO:
            _js = _ZQ_MEMO[symbol]
        else:
            r = get(YQ_URL.format(sym=quote(symbol)))
            r.raise_for_status()
            _js = r.json()
            if _memo:
                _ZQ_MEMO[symbol] = _js
        res = (_js.get("chart") or {}).get("result") or []
        if not res:
            return (None, None) if with_prev else None
        closes = (((res[0].get("indicators") or {}).get("quote") or [{}])[0]
                  .get("close") or [])
        valid = [c for c in closes if c is not None]
        px = valid[-1] if valid else None
        # 前一個交易日的收盤：chip 的 ± 要「收盤對收盤」，跟其他
        # 指標同一個口徑（with_prev=True 時回傳 (最新, 前一日)）。
        px_prev = valid[-2] if len(valid) > 1 else None
        src = "5 日收盤"
        if require_movement:
            if len(valid) < 2:
                log.warning("聯邦基金期貨 %s 近五日只有 %d 筆結算價，"
                            "報價鏈疑似死掉，不採用", symbol, len(valid))
                return (None, None) if with_prev else None
            if len(set(valid)) == 1:
                log.warning("聯邦基金期貨 %s 近五日結算價五天一模一樣"
                            "（%.4f），報價鏈疑似死掉，不採用",
                            symbol, valid[0])
                return (None, None) if with_prev else None
        if px is None:
            if require_movement:
                return (None, None) if with_prev else None
            px = (res[0].get("meta") or {}).get("regularMarketPrice")
            src = "最新成交價（近五日無收盤，可能偏舊）"
        if px is None:
            return (None, None) if with_prev else None
        px = float(px)
        # 期貨價 ＝ 100 − 利率：合理價位在 90–100 之間。
        # 落在外面代表抓到錯的商品或壞報價，寧可不算。
        if not 90.0 <= px <= 100.0:
            log.warning("聯邦基金期貨 %s 報價 %.2f 超出合理範圍，不採用",
                        symbol, px)
            return (None, None) if with_prev else None
        implied = round(100.0 - px, 4)
        # 算術全部進 log：畫面上只有一個百分比，出錯時（100% 事故）
        # 沒有這一行就無從回推是哪一步壞掉。
        log.info("聯邦基金期貨 %s：價格 %.4f（%s）→ 隱含利率 %.3f%%",
                 symbol, px, src, implied)
        if with_prev:
            prev_ok = (px_prev is not None
                       and 90.0 <= float(px_prev) <= 100.0)
            return implied, (round(100.0 - float(px_prev), 4)
                             if prev_ok else None)
        return implied
    except Exception as e:                         # noqa: BLE001
        log.warning("聯邦基金期貨報價抓取失敗（%s：%s）", symbol, e)
        return (None, None) if with_prev else None


_MONTH_CODES = "FGHJKMNQUVXZ"                      # 期貨月份代碼：F=1月…Z=12月


def _anchor_symbol(today: dt.date) -> str:
    """當月聯邦基金期貨的代號（例：2026-08 → ZQQ26.CBT）。逐月自動滾。"""
    return f"ZQ{_MONTH_CODES[today.month - 1]}{today.year % 100:02d}.CBT"


def _zq_symbol(month: str) -> str:
    """月份鍵（"2026-11"）→ 合約代號（ZQX26.CBT）。"""
    y, m = int(month[:4]), int(month[5:7])
    return f"ZQ{_MONTH_CODES[m - 1]}{y % 100:02d}.CBT"


def _prev_month(month: str) -> str:
    y, m = int(month[:4]), int(month[5:7])
    return f"{y - 1:04d}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"


def calculate_meeting_probability(futures_prices: dict, fomc_dates: list,
                                  target: str) -> dict | None:
    """
    WIRP 同款的**逐會議**隱含機率。輸入：

        futures_prices  {"2026-11": 96.215, "2026-12": 96.140, ...}
        fomc_dates      ["2026-01-28", ..., "2026-12-09"]（決策日）
        target          目標會議決策日（"2026-12-09"）

    算法（與使用者提供的規格逐條對應）：
      1. 月平均隱含 EFFR ＝ 100 − 期貨價
      2. 無 FOMC 月是錨：End(T−1) ＝ Avg(T) ＝ Start(T+1)
      3. 有 FOMC 的月份按日曆日加權：Avg ＝ (N×Start ＋ M×End)/D，
         N＝月初到會議日（含當天）、M＝其餘天數、D＝N＋M＝當月天數
      4. 從錨月往後逐月反推 Start/End，一路推到目標會議月
      5. ExpectedMoveBps ＝ (End − Start) × 100
      6–8. moves ＝ bps/25；拆成相鄰兩個 25bp outcome：
         P(floor×25) ＝ 1−fraction、P((floor+1)×25) ＝ fraction。
         **不 clamp**；顯示用的單一 % ＝ moves × 100（WIRP 慣例，
         可以超過 100，代表定價超過一碼）。
      9. Unit test（tests/test_focus.py）：Nov 96.215＋Dec 96.140
         必須得到 Dec +25bp ≈ 42.27%。

    回傳 dict 含每一步中間值（price/avg/start/end/N/M/D、move_bp、
    moves、outcomes、pct），全部進 log 供逐項對 Bloomberg WIRP。
    資料不足（缺月份、找不到錨）回 None。
    """
    if not futures_prices or not target:
        return None
    meets = {str(d)[:7]: str(d) for d in fomc_dates}
    meets[str(target)[:7]] = str(target)           # 目標一定是會議月
    avg = {str(m): round(100.0 - float(p), 6)
           for m, p in futures_prices.items()}

    tm = str(target)[:7]
    chain = [tm]                                   # 目標月（含）往回到錨月
    m, hops = _prev_month(tm), 0
    while m in meets and hops < 6:                 # 連續會議月往回走
        chain.append(m)
        m, hops = _prev_month(m), hops + 1
    anchor = m                                     # 第一個無會議月
    if hops >= 6:
        log.warning("FedWatch 計算：往回 6 個月找不到無會議月，放棄")
        return None
    needed = [anchor] + list(reversed(chain))      # 錨月 → … → 目標月
    if any(mo not in avg for mo in needed):
        log.warning("FedWatch 計算：缺月份報價（需要 %s，有 %s）",
                    "、".join(needed), "、".join(sorted(avg)))
        return None

    months: dict = {anchor: {"price": futures_prices.get(anchor),
                             "avg": avg[anchor], "role": "anchor",
                             "start": avg[anchor], "end": avg[anchor]}}
    start = avg[anchor]                            # Start(錨月+1) ＝ Avg(錨月)
    end = start
    for mo in needed[1:]:
        d = dt.date.fromisoformat(meets[mo])
        days = calendar.monthrange(d.year, d.month)[1]
        n, m_days = d.day, days - d.day
        if m_days <= 0:                            # 月底最後一天開會，反推無解
            log.warning("FedWatch 計算：%s 的會議在月底最後一天，無法反推", mo)
            return None
        end = (days * avg[mo] - n * start) / m_days
        months[mo] = {"price": futures_prices.get(mo), "avg": avg[mo],
                      "role": "meeting", "meeting": meets[mo],
                      "D": days, "N": n, "M": m_days,
                      "start": round(start, 6), "end": round(end, 6)}
        start_next = end                           # Start(下月) ＝ End(本月)
        if mo != tm:
            start = start_next
    move_bp = (end - months[tm]["start"]) * 100
    moves = move_bp / 25.0
    lower = math.floor(moves)
    fraction = moves - lower
    outcomes = {lower * 25: round(1 - fraction, 4),
                (lower + 1) * 25: round(fraction, 4)}
    return {"pct": round(moves * 100, 2),          # WIRP 慣例：不封頂的單一 %
            "move_bp": round(move_bp, 3),
            "moves": round(moves, 4),
            "outcomes": outcomes,
            "anchor": anchor, "meeting": str(target),
            "months": months}


def _next_month(month: str) -> str:
    y, m = int(month[:4]), int(month[5:7])
    return f"{y + 1:04d}-01" if m == 12 else f"{y:04d}-{m + 1:02d}"


def _split_outcomes(move_bp: float) -> list:
    """把隱含變動拆成相鄰兩個 25bp 結果，回傳 [[bp, 機率], …]（機率大的在前）。
    存成清單而不是 dict：要寫進 state 的 JSON，dict 的整數鍵會被轉成字串。"""
    moves = move_bp / 25.0
    lower = math.floor(moves)
    frac = moves - lower
    out = [[int(lower * 25), round(1 - frac, 4)],
           [int((lower + 1) * 25), round(frac, 4)]]
    return sorted(out, key=lambda x: -x[1])


def meeting_path(futures_prices: dict, fomc_dates: list, horizon: str,
                 today: dt.date, fallback_rate: float | None = None
                 ) -> dict | None:
    """
    從**目前的利率**往後，逐場推出每一次會議的隱含利率（今天到 horizon）。

    為什麼要有這一版：舊算法（calculate_meeting_probability）從目標會議
    往回找「沒開會的月份」當起點——目標換成下一次會議（10/28）時，往回
    是 9 月（9/16 開會）、再往回是 8 月，而 8、9 月的合約都已經到期，
    報價被停滯偵測擋下，整個算不出來。這一版改成往前推：

      起點 r0（目前利率）依序取：
        ① 今天到第一場會議之間、沒開會的月份合約（整個月都是現行利率）
        ② 第一場會議月與「下個月」合約反推：下個月沒開會，它的平均
           就是會後利率 End；Avg(會議月)＝(N×r0＋M×End)/D → 解 r0
        ③ 都沒有就用目標區間中點（呼叫端傳入）
      每一場會議的會後利率 End 依序取：
        ① 下個月沒開會、又有合約 → End＝下個月平均（最穩：不受月底會議
           「M 很小、反推放大雜訊」的影響）
        ② 否則照日曆日加權反推：End＝(D×Avg−N×Start)/M
      下一場的 Start＝這一場的 End。

    「下個月沒開會」只在 config 有那一年的會議日程時才算數——2027 年的
    日期還沒填進 config 時，1 月視為未知，12 月會議改走加權反推。

    回傳 {r0, r0_src, meetings: [{date, start, end, move_bp, outcomes, how}],
    cum_bp}；資料不足回 None。
    """
    avg = {str(m): 100.0 - float(p) for m, p in (futures_prices or {}).items()}
    dates = sorted({str(d)[:10] for d in (fomc_dates or [])} | {str(horizon)})
    meet_months = {d[:7] for d in dates}
    years = {d[:4] for d in dates}

    def no_meeting(m: str) -> bool:
        return m[:4] in years and m not in meet_months

    upcoming = [d for d in dates if today.isoformat() <= d <= str(horizon)]
    if not upcoming:
        return None
    m1 = upcoming[0][:7]
    d1 = dt.date.fromisoformat(upcoming[0])
    days1 = calendar.monthrange(d1.year, d1.month)[1]

    r0, r0_src = None, ""
    x, cands = today.isoformat()[:7], []
    while x < m1:
        if no_meeting(x) and x in avg:
            cands.append(x)
        x = _next_month(x)
    if cands:
        r0, r0_src = avg[cands[-1]], f"{cands[-1]} 合約（當月沒有會議）"
    elif (no_meeting(_next_month(m1)) and _next_month(m1) in avg
          and m1 in avg and d1.day > 0):
        nx = _next_month(m1)
        r0 = (days1 * avg[m1] - (days1 - d1.day) * avg[nx]) / d1.day
        r0_src = f"{m1} 與 {nx} 合約反推"
    elif fallback_rate is not None:
        r0, r0_src = float(fallback_rate), "目標區間中點"
    else:
        return None

    meetings, start = [], r0
    for d in upcoming:
        mo, dd = d[:7], dt.date.fromisoformat(d)
        days = calendar.monthrange(dd.year, dd.month)[1]
        n, m_days = dd.day, days - dd.day
        nx = _next_month(mo)
        if no_meeting(nx) and nx in avg:
            end, how = avg[nx], f"{nx} 合約平均"
        elif mo in avg and m_days > 0:
            end = (days * avg[mo] - n * start) / m_days
            how = f"{mo} 合約日曆日加權反推（N={n}、M={m_days}）"
        else:
            log.warning("FedWatch 前推：%s 的會議缺報價或在月底，無法推算", d)
            return None
        move = (end - start) * 100
        meetings.append({"date": d, "start": round(start, 6),
                         "end": round(end, 6), "move_bp": round(move, 3),
                         "outcomes": _split_outcomes(move), "how": how})
        start = end
    return {"r0": round(r0, 6), "r0_src": r0_src, "meetings": meetings,
            "cum_bp": round((meetings[-1]["end"] - r0) * 100, 3)}


def fw_horizons(fomc_dates, today: dt.date) -> list[tuple[str, str]]:
    """
    升降息累計的三個節點（第十八批，使用者指定）：接下來的「年底、年中、年底」
    取前三個——十月時是「今年底、明年中、明年底」，一月時是「今年中、今年底、
    明年中」。年中＝該年上半年最後一場會議（通常是 6 月），年底＝該年最後一場。
    只用 config 裡有的會議日；明年的日程還沒填就只剩前一兩個。
    """
    by_year: dict[str, list[str]] = {}
    for d in sorted({str(x)[:10] for x in (fomc_dates or [])}):
        by_year.setdefault(d[:4], []).append(d)
    cands = []
    for y in sorted(by_year):
        ds = by_year[y]
        mid = [d for d in ds if int(d[5:7]) <= 6]
        if mid:
            cands.append((mid[-1], f"{y} 年中"))
        cands.append((ds[-1], f"{y} 年底"))
    return [c for c in cands if c[0] >= today.isoformat()][:3]


def fedwatch_path(rates_series: dict | None, cfg: dict | None, _get=None,
                  today: dt.date | None = None) -> dict | None:
    """
    下一次會議的機率＋目標會議（horizon，預設 12 月）的單場與累計幅度。

    抓取：今天所在月份到 horizon 月份的每一張聯邦基金期貨（並行）。
    當月合約兼健康檢查——它被已實現的利率釘住，隱含偏離 FRED 目標
    中點 >0.15 就判整條報價鏈壞掉、整批不採用；其他合約要「有在動」
    （五天收盤一模一樣＝報價死掉）。月份間差 >1.5 個百分點或單場
    |move|>100bp 一律判壞資料。

    同一次執行再用每張合約**前一日收盤**算一次，供 chip 標「前日」——
    跟其他 chip 一樣是收盤對收盤。
    """
    cfg = cfg or {}
    today = today or clock.today()
    rs = rates_series or {}
    lo, hi = _last_value(rs.get("DFEDTARL")), _last_value(rs.get("DFEDTARU"))
    if lo is None or hi is None:
        log.warning("FedWatch 前推：抓不到目標區間（DFEDTARL/U），跳過")
        return None
    mid = (lo + hi) / 2
    fomc = [str(x)[:10] for x in (cfg.get("fomc_dates") or [])]
    # 第十八批：不再盯單一目標會議（fedwatch_meeting 已不用），改算三個節點
    hz_list = fw_horizons(fomc, today)
    if not hz_list:
        log.warning("FedWatch 前推：config 沒有今天之後的 FOMC 日期，"
                    "請在 config/focus.yaml 補上明年的會議日")
        return None
    if len(hz_list) < 3:
        log.warning("FedWatch 前推：只排得出 %d 個累計節點——請在 config/focus.yaml "
                    "補上下一年的 FOMC 會議日", len(hz_list))
    horizon = hz_list[-1][0]
    months, mo = [], today.isoformat()[:7]
    while mo <= horizon[:7]:
        months.append(mo)
        mo = _next_month(mo)
    cur_m = months[0]
    res = _pmap(lambda m: fetch_zq_implied(
        _zq_symbol(m), _get, require_movement=(m != cur_m), with_prev=True),
        months)
    prices, prices_prev = {}, {}
    for m, r in zip(months, res):
        imp, imp_prev = r if isinstance(r, tuple) else (None, None)
        if imp is None:
            # 遠月成交稀、報價可能是死的：缺在第一個節點之後就把後面的節點
            # 截掉（少一兩顆 chip），缺在第一個節點之前才整批不採用
            if m <= hz_list[0][0][:7]:
                log.warning("FedWatch 前推：%s 合約報價不可用，整批不採用",
                            _zq_symbol(m))
                return None
            log.warning("FedWatch 前推：%s 合約報價不可用，累計節點只算到 %s 之前",
                        _zq_symbol(m), m)
            hz_list = [h for h in hz_list if h[0][:7] < m]
            horizon = hz_list[-1][0]
            break
        prices[m] = round(100.0 - imp, 4)
        if imp_prev is not None:
            prices_prev[m] = round(100.0 - imp_prev, 4)
    if abs((100.0 - prices[cur_m]) - mid) > 0.15:
        log.warning("FedWatch 前推：當月合約隱含 %.3f%% 偏離目標中點 %.3f%% "
                    "超過 0.15，判定報價鏈品質不佳，整批不採用",
                    100.0 - prices[cur_m], mid)
        return None
    imps = sorted(100.0 - p for p in prices.values())
    if imps[-1] - imps[0] > 1.5:
        log.warning("FedWatch 前推：月份間隱含利率相差 %.2f 個百分點，"
                    "疑為抓錯合約，不採用", imps[-1] - imps[0])
        return None
    path = meeting_path(prices, fomc, horizon, today, fallback_rate=mid)
    if path is None:
        return None
    if any(abs(m["move_bp"]) > 100 for m in path["meetings"]):
        log.warning("FedWatch 前推：有單場會議隱含變動超過四碼，判為壞資料")
        return None
    prev = None
    if set(prices_prev) == set(prices):
        prev = meeting_path(prices_prev, fomc, horizon, today,
                            fallback_rate=mid)

    def _cum(pth, d):
        m = next((x for x in (pth or {}).get("meetings") or [] if x["date"] == d), None)
        return None if m is None else round((m["end"] - pth["r0"]) * 100, 3)
    horizons = [{"date": d, "label": lb, "cum_bp": _cum(path, d),
                 "prev_cum_bp": _cum(prev, d) if prev else None}
                for d, lb in hz_list]
    _h0 = next(x for x in path["meetings"] if x["date"] == hz_list[0][0])
    for m in path["meetings"]:
        log.info("FedWatch 前推：%s 會議 Start %.4f → End %.4f，隱含 %+.2f bp"
                 "（%s）", m["date"], m["start"], m["end"], m["move_bp"],
                 m["how"])
    log.info("FedWatch 前推：起點 %.4f%%（%s）；至 %s 累計 %+.2f bp",
             path["r0"], path["r0_src"], horizon, path["cum_bp"])
    return {"src": "futures", "date": today.isoformat(),
            # 逐場全列：聯準會頁的「市場路徑 vs 點陣圖」要每一場的會後利率
            "meetings": path["meetings"],
            # horizon／cum_bp＝第一個節點（今年底），沿用舊鍵給聯準會頁
            "next": path["meetings"][0], "horizon": _h0,
            "cum_bp": horizons[0]["cum_bp"], "r0": path["r0"],
            "r0_src": path["r0_src"], "horizons": horizons,
            "prev": ({"next": prev["meetings"][0],
                      "horizon": next(x for x in prev["meetings"]
                                      if x["date"] == hz_list[0][0]),
                      "cum_bp": horizons[0]["prev_cum_bp"]} if prev else None)}


def futures_curve(rates_series: dict | None, months: int | None = 13, _get=None,
                  today: dt.date | None = None, fomc_dates=None) -> dict | None:
    """
    未來 12 個月每個月的聯邦基金期貨隱含利率，與「終端利率」（2026-10）。

    終端利率＝這段期間隱含利率離現行中點最遠的那一點（升息循環取最高、
    降息循環取最低），也標出在哪個月。遠月合約成交稀，抓不到就停在那裡，
    回傳實際抓到的範圍；當月合約仍做健康檢查（偏離中點 >0.15 整批不用）。
    """
    today = today or clock.today()
    rs = rates_series or {}
    lo, hi = _last_value(rs.get("DFEDTARL")), _last_value(rs.get("DFEDTARU"))
    if lo is None or hi is None:
        return None
    mid = (lo + hi) / 2
    if fomc_dates:
        # 第十八批：資料窗延到首頁第三個累計節點（明年底）那個月，兩邊同一條路徑
        hz = fw_horizons(fomc_dates, today)
        if hz:
            y, m = int(hz[-1][0][:4]), int(hz[-1][0][5:7])
            months = max(months or 0, (y - today.year) * 12 + m - today.month + 1)
    ms, mo = [], today.isoformat()[:7]
    for _ in range(months or 13):
        ms.append(mo)
        mo = _next_month(mo)
    res = _pmap(lambda m: fetch_zq_implied(_zq_symbol(m), _get,
                                           require_movement=(m != ms[0])), ms)
    pts = []
    for m, r in zip(ms, res):
        imp = r[0] if isinstance(r, tuple) else r
        if imp is None:
            break
        pts.append({"month": m, "rate": round(float(imp), 4)})
    if len(pts) < 2 or abs(pts[0]["rate"] - mid) > 0.15:
        return None
    if max(p["rate"] for p in pts) - min(p["rate"] for p in pts) > 2.0:
        return None
    far = max(pts, key=lambda p: abs(p["rate"] - mid))
    return {"r0": mid, "points": pts, "terminal": far["rate"], "terminal_month": far["month"],
            "terminal_bp": (far["rate"] - mid) * 100, "asof": today.isoformat(),
            "thin_from": pts[min(6, len(pts) - 1)]["month"],
            # 最遠那一點就是資料窗的最後一個月＝路徑還在走，終端可能在更遠處
            "open_end": far["month"] == pts[-1]["month"]}


_CN_N = {1: "一", 2: "兩", 3: "三", 4: "四"}


def outcome_name(bp: int) -> str:
    """0 → 維持；+25 → 升一碼；−50 → 降兩碼。"""
    if bp == 0:
        return "維持"
    n = abs(int(bp)) // 25
    return ("升" if bp > 0 else "降") + _CN_N.get(n, str(n)) + "碼"


FW_H_IDS = ("fw_h1", "fw_h2", "fw_h3")


def fw_chips(fw: dict | None) -> list[dict]:
    """
    升降息 chip（第十八批）：
      fedwatch      下次會議：機率最高的兩個結果
      fw_h1…fw_h3   到「今年底／明年中／明年底」（依 fw_horizons 滾動）的
                    累計隱含升降息幅度，對前一日收盤
    """
    def _md(d):
        return f"{int(d[5:7])}/{int(d[8:10])}"

    if not fw or not fw.get("next"):
        return ([_mk("fedwatch", "下次 FOMC 機率", "—", "本次擷取失敗", "", "")]
                + [_mk(c, "累計升降息幅度", "—", "本次擷取失敗", "", "") for c in FW_H_IDS])
    nxt, prev = fw["next"], fw.get("prev") or {}
    when = (f"沿用 {fw['stale_from'][5:]}" if fw.get("stale_from")
            else str(fw.get("date") or ""))
    nm = int(nxt["date"][5:7])
    o = [x for x in nxt["outcomes"] if x[1] >= 0.005] or nxt["outcomes"][:1]
    top = f"{outcome_name(o[0][0])} {o[0][1] * 100:.0f}%"
    if len(o) > 1:
        second = f"{outcome_name(o[1][0])} {o[1][1] * 100:.0f}%"
        p_prev = dict((b, p) for b, p in (prev.get("next") or {}).get(
            "outcomes", []))
        if o[1][0] in p_prev:
            second += f"（前日 {p_prev[o[1][0]] * 100:.0f}%）"
    else:
        second = "市場幾乎完全定價"
    # 方向色：升息那一側的機率變大＝偏鷹（紅），跟殖利率上升同色
    d_cls = ""
    if prev.get("next"):
        d_mv = nxt["move_bp"] - prev["next"]["move_bp"]
        d_cls = "up" if d_mv > 0.05 else ("dn" if d_mv < -0.05 else "")

    def _amt(cur, old):
        txt = f"約 {cur / 25:+.1f} 碼"
        if old is not None:
            txt += f"（前日 {old:+.1f} bp）"
        cls = ("" if old is None else "up" if cur - old > 0.05
               else "dn" if cur - old < -0.05 else "")
        return txt, cls

    out = [_mk("fedwatch", f"{nm} 月 FOMC（{_md(nxt['date'])}）", top, second,
               d_cls, when, on=True)]
    hz = fw.get("horizons") or ([{"date": fw["horizon"]["date"],
                                  "label": f"{fw['horizon']['date'][:4]} 年底",
                                  "cum_bp": fw.get("cum_bp"),
                                  "prev_cum_bp": prev.get("cum_bp")}]
                                if fw.get("horizon") and fw.get("cum_bp") is not None else [])
    for i, cid in enumerate(FW_H_IDS):
        h = hz[i] if i < len(hz) else None
        if not h or h.get("cum_bp") is None:
            out.append(_mk(cid, "累計升降息幅度", "—", "遠月報價不可用", "", ""))
            continue
        txt, cls = _amt(h["cum_bp"], h.get("prev_cum_bp"))
        out.append(_mk(cid, f"至 {h['label']}（{_md(h['date'])}）累計",
                       f"{h['cum_bp']:+.1f} bp", txt, cls, when))
    return out


def fedwatch_from_futures(rates_series: dict | None, cfg: dict | None,
                          _get=None) -> dict | None:
    """
    第一層：WIRP 同款逐會議算法（見 calculate_meeting_probability）。

    這一層負責把「抓哪些合約」接到算法上：
      · 報價鏈健康檢查——當月合約的答案已知（當月平均 ≈ 目前實際
        利率），隱含偏離 FRED 目標中點 >0.15 就判整條 Yahoo 報價鏈
        壞掉、整批退備援。
      · 由 fedwatch_meeting 與 fomc_dates 推出需要的月份（目標會議月
        ＋往回到第一個無會議月），合約代號自動生成（ZQZ26、ZQX26…），
        每張都過停滯偵測（五天收盤一模一樣＝報價死掉）。
      · 相鄰月份 sanity（>1.5 個百分點＝抓錯商品或年份）與單場會議
        |move|>100bp（四碼）的壞資料檻。

    成功回傳 calculate_meeting_probability 的完整 dict（pct 帶正負：
    正＝升息、負＝降息，依 WIRP 慣例**不封頂**），失敗回 None 退備援。
    """
    rs = rates_series or {}
    lo = _last_value(rs.get("DFEDTARL"))
    hi = _last_value(rs.get("DFEDTARU"))
    if lo is None or hi is None:
        log.warning("FedWatch 自算：抓不到目標區間（DFEDTARL/U），跳過")
        return None
    mid = (lo + hi) / 2

    health_sym = ((cfg or {}).get("fedwatch_health_contract")
                  or _anchor_symbol(clock.today()))
    cur = fetch_zq_implied(health_sym, _get)
    if cur is None:
        return None
    if abs(cur - mid) > 0.15:
        log.warning("FedWatch 自算：當月合約 %s 隱含 %.2f%% 偏離目標中點 "
                    "%.3f%% 超過 0.15，判定 Yahoo 報價鏈品質不佳，"
                    "整批不採用", health_sym, cur, mid)
        return None

    target = str((cfg or {}).get("fedwatch_meeting") or DEFAULT_MEETING)
    fomc_dates = [str(x) for x in ((cfg or {}).get("fomc_dates") or [])]
    if target not in fomc_dates:
        fomc_dates.append(target)
    meets = {d[:7] for d in fomc_dates}
    tm = target[:7]
    need = [tm]
    m, hops = _prev_month(tm), 0
    while m in meets and hops < 6:
        need.append(m)
        m, hops = _prev_month(m), hops + 1
    need.append(m)                                 # 錨月（無會議）
    if hops >= 6:
        log.warning("FedWatch 自算：往回 6 個月找不到無會議月，跳過")
        return None

    prices, prices_prev = {}, {}
    _mos = sorted(need)
    # 各合約獨立，並行抓；每張都開「有在動」檢查：連續五天收盤一模一樣
    # ＝報價死掉（+0.0 pp 事故的長相），比任何價位門檻都可靠
    _res = _pmap(lambda mo: fetch_zq_implied(
        _zq_symbol(mo), _get, require_movement=True, with_prev=True), _mos)
    for mo, r in zip(_mos, _res):
        imp, imp_prev = r if isinstance(r, tuple) else (None, None)
        if imp is None:
            return None
        prices[mo] = round(100.0 - imp, 4)
        if imp_prev is not None:
            prices_prev[mo] = round(100.0 - imp_prev, 4)
    avgs = sorted(100.0 - p for p in prices.values())
    if avgs[-1] - avgs[0] > 1.5:
        log.warning("FedWatch 自算：月份間隱含利率相差 %.2f 個百分點，"
                    "疑為抓錯合約，不採用", avgs[-1] - avgs[0])
        return None

    calc = calculate_meeting_probability(prices, fomc_dates, target)
    if calc is None:
        return None
    # chip 的 ± 改成真正的「收盤對收盤」：用每檔合約前一交易日的收盤
    # 再算一次機率，兩者相減。不再依賴 state 的歷史——週末沒有新收盤
    # 就顯示「週五 vs 週四」的變動，不會再掛 +0.0；擷取失敗或改版本
    # 也不會污染 ±。湊不齊前一日收盤（新合約上市第一天）就不標。
    calc["delta_pp"] = None
    if set(prices_prev) == set(prices):
        calc_prev = calculate_meeting_probability(prices_prev, fomc_dates,
                                                  target)
        if calc_prev is not None:
            calc["delta_pp"] = round(calc["pct"] - calc_prev["pct"], 1)
    if abs(calc["move_bp"]) > 100:
        log.warning("FedWatch 自算：單場會議隱含變動 %.1f bp（超過四碼），"
                    "判為壞資料，不採用", calc["move_bp"])
        return None
    # 十步中間值全部進 log，供逐項對 Bloomberg WIRP
    for mo in sorted(calc["months"]):
        info = calc["months"][mo]
        if info["role"] == "anchor":
            log.info("FedWatch %s（錨月，無會議）：價格 %s → 月均 %.4f%%",
                     mo, info["price"], info["avg"])
        else:
            log.info("FedWatch %s（會議 %s，D=%d N=%d M=%d)：價格 %s → "
                     "月均 %.4f%%，Start %.4f%% → End %.4f%%",
                     mo, info["meeting"], info["D"], info["N"], info["M"],
                     info["price"], info["avg"], info["start"], info["end"])
    log.info("FedWatch 自算（WIRP 法）：%s 會議隱含變動 %+.3f bp ＝ "
             "%.4f 碼 → %s一碼機率 %.2f%%（outcome 拆解 %s；"
             "健康檢查 %s 隱含 %.3f%% vs 中點 %.3f%% 通過）",
             target, calc["move_bp"], calc["moves"],
             "升息" if calc["move_bp"] >= 0 else "降息",
             abs(calc["pct"]),
             "、".join(f"{k:+d}bp {v*100:.1f}%"
                       for k, v in sorted(calc["outcomes"].items())),
             health_sym, cur, mid)
    return calc


# ---------------------------------------------------------------------------
# FedWatch 第二層：亞特蘭大聯準銀行 Market Probability Tracker（官方）
# ---------------------------------------------------------------------------
ATLANTA_URL = "https://www.atlantafed.org/cenfis/market-probability-tracker"


def fetch_atlanta_fedwatch(cfg: dict | None = None, _get=None) -> float | None:
    """
    官方的市場隱含機率（SOFR 選擇權反推）。README 規劃清單裡的那一項。

    資料端點的格式**還沒在 Actions 上實跑驗證過**（開發沙盒連不到
    atlantafed.org），所以這一版走「先偵察、後啟用」：

      沒設 atlanta_json_path 時——抓回應、把形狀寫進 log（content-type、
      開頭 300 字元），一律回 None 退下一層。log 就是下一步適配格式的
      依據。**不做模糊猜測**：對著未知格式用鍵名關鍵字亂抽一個數字，
      跟編造沒有兩樣。

      設了 atlanta_json_path（例：["probabilities", "hike25"]）之後——
      照路徑取值，0–1 自動換算成百分比，超出 0–100 不採用。
    """
    cfg = cfg or {}
    url = cfg.get("atlanta_mpt_url") or ATLANTA_URL
    path = cfg.get("atlanta_json_path") or []
    get = _get or (lambda u: requests.get(
        u, timeout=TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0 (macro-dashboard)"}))
    try:
        r = get(url)
        r.raise_for_status()
    except Exception as e:                         # noqa: BLE001
        log.warning("Atlanta Fed 機率抓取失敗（%s）", e)
        return None
    if not path:
        ct = (getattr(r, "headers", {}) or {}).get("Content-Type", "?")
        text = getattr(r, "text", "") or ""
        # 資料端點藏在頁面的 script 裡（開發沙盒的抓取工具看不到那層，
        # 只有真的連得上的機器看得到完整原始碼）——把原始碼裡所有像
        # 資料端點的 URL 挖出來寫進 log，這一行就是啟用的依據。
        cands = re.findall(
            r'["\']((?:https?://[^"\']+|/[^"\']+)?'
            r'(?:api|API|[Cc]hart|[Dd]ata|GetChart|feed|Feed|documents'
            r'|\.json|\.csv|\.xlsx|\.js)'
            r'[^"\']*)["\']', text)
        # 圖檔與樣式是雜訊（第一輪偵察 71 個候選裡前 12 個全是
        # highcharts 的圖示，真正的資料連結被擠出 log）——先剔除，
        # 再把「像資料檔」的排前面。
        _noise = (".png", ".svg", ".jpg", ".jpeg", ".gif", ".css",
                  ".woff", ".woff2", ".ico")
        uniq = []
        for c in cands:
            cl = c.lower()
            if (c.startswith(("/", "http")) and c not in uniq
                    and not any(cl.endswith(n) or n + "?" in cl
                                for n in _noise)):
                uniq.append(c)
        _prio = (".xlsx", ".csv", ".json", "api", "feed", "documents")
        uniq.sort(key=lambda c: (not any(p in c.lower() for p in _prio)))
        log.info("Atlanta Fed 偵察：%s → %s；候選資料端點 %d 個：%s"
                 "（把正確端點填進 atlanta_mpt_url、取值路徑"
                 "填進 atlanta_json_path 後啟用）",
                 url, ct, len(uniq), "、".join(uniq[:25]) or "（沒找到）")
        return None
    try:
        node = r.json()
        for k in path:
            node = node[int(k)] if isinstance(node, list) else node[k]
        pct = float(node)
        if 0.0 <= pct <= 1.0:
            pct *= 100.0                           # 0–1 機率換算成百分比
        if not 0.0 <= pct <= 100.0:
            log.warning("Atlanta Fed 機率 %.2f 超出 0–100，不採用", pct)
            return None
        pct = round(pct, 1)
        log.info("Atlanta Fed 機率：%s → %.1f%%", "/".join(map(str, path)), pct)
        return pct
    except Exception as e:                         # noqa: BLE001
        log.warning("Atlanta Fed 機率解析失敗（路徑 %s：%s）", path, e)
        return None


_FW_PROMPT = (
    "用 Google 搜尋查 CME FedWatch 工具目前對 2026 年 12 月 FOMC 會議的"
    "利率機率分布，找出「較目前利率區間**升息 25 個基點（一碼）**」的機率。"
    '只輸出一行 JSON：{"pct": <0 到 100 的數字>}；查不到明確數字就輸出 '
    '{"pct": null}。不要輸出其他文字。')


def fetch_fedwatch(env=None) -> float | None:
    """FedWatch 機率，Gemini 搜尋接地擷取。抓不到回 None，不編造。"""
    from .polish import _pick_provider, _http, GEMINI_BASE
    import os
    env = env or os.environ
    provider, key = _pick_provider(env)
    if provider != "gemini" or not key:
        return None
    model = (env.get("BRIEF_MODEL") or "").strip() or "gemini-flash-latest"
    try:
        r = _http("POST", f"{GEMINI_BASE}/models/{model}:generateContent",
                  label="FedWatch 擷取", headers={
                      "x-goog-api-key": key,
                      "content-type": "application/json"},
                  json={"contents": [{"role": "user",
                                      "parts": [{"text": _FW_PROMPT}]}],
                        "tools": [{"google_search": {}}],
                        "generationConfig": {"temperature": 0.0,
                                             "maxOutputTokens": 2048}})
        r.raise_for_status()
        cands = (r.json().get("candidates") or [])
        text = "".join(p.get("text", "")
                       for p in ((cands[0].get("content") or {})
                                 .get("parts", []))) if cands else ""
        m = re.search(r'\{[^{}]*"pct"[^{}]*\}', text)
        if not m:
            return None
        pct = json.loads(m.group(0)).get("pct")
        if pct is None:
            return None
        pct = float(pct)
        return pct if 0.0 <= pct <= 100.0 else None
    except Exception as e:                         # noqa: BLE001
        log.warning("FedWatch 擷取失敗（%s）", e)
        return None


def _pick_fw(fw, at):
    """
    期貨自算與 Atlanta Fed 官方值的**交叉檢核**。
    回傳 (pct, src, 期貨算法明細或 None)。期貨的 pct 帶正負
    （負＝降息定價），與官方值（升息機率）比對時取絕對值。

    兩邊都有值且差超過 25 個百分點 → 期貨端有問題（兩個獨立來源同時
    錯的機率遠低於期貨報價鏈單邊死掉），改用官方值。這比任何單邊
    防護都可靠——防護欄只能驗「合不合理」，交叉檢核驗的是「對不對」。
    只有一邊有值就用那邊；都沒有回全 None 讓呼叫端退 AI 層。
    """
    if fw is not None and at is not None and abs(abs(fw["pct"]) - at) > 25:
        log.warning("FedWatch 交叉檢核：期貨自算 %.1f%% 與官方 %.1f%% "
                    "差逾 25pp，判定期貨端報價有問題，改用官方值",
                    fw["pct"], at)
        return at, "atlanta", None
    if fw is not None:
        return fw["pct"], "futures", fw
    if at is not None:
        return at, "atlanta", None
    return None, "", None


def _jump_suspect(pct: float, prev, src: str) -> bool:
    """
    「單日跳動 >20pp 視為擷取錯誤」這條防護欄要不要啟動。

    **只防 AI 擷取**。期貨自算是確定性算式，而且有自己的防護欄
    （報價 90–100、偏離中點 ±1.5、中點＋0.40 陳舊報價、優先結算價），
    通過那些檢查之後算出來的大變動是**資訊**，不是錯誤。
    更關鍵的是：對期貨值也啟動這條的話，一次事故留下的壞前值
    （實例：陳舊報價造成的 100%）會永遠取代不掉——正確的 22% 與
    壞掉的 100% 差 78pp，每一次都被這條擋下、每一次都「沿用前值」，
    畫面就永遠卡在 100%。
    """
    return src != "futures" and prev is not None and abs(pct - prev) > 20


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 主題補充（2026-10）：主軸下方的兩則補充，依讀者在「選擇」裡排的前兩個
# 指標換成對應主題的新聞。每次更新把**所有主題**的補充都寫好放進頁面，
# 瀏覽器再依讀者的選擇挑兩則顯示（網站仍是靜態頁，不多耗 Netlify）。
#
# 規則（使用者定案）：
#   · 前兩個指標屬於同一主題 → 往下找下一個不同主題的指標
#   · 主題當天沒有新聞 → 往讀者選的下一個指標遞補；都沒有就用一般補充
#   · 台指期主題用自己的關鍵字與排除詞（全站的「台股」「金控」排除只
#     套用在主軸與其他主題）
#   · 每則補充前面加主題標籤
# ---------------------------------------------------------------------------
TOPIC_PROMPT_VERSION = "t4-policy-semi"
TOPIC_CHARS, TOPIC_MIN = 80, 40
# 公開RSS提供直接文章連結與出版社摘要；全部主題缺少可讀內容時補入。
TOPIC_HARD = int(TOPIC_CHARS * HARD_MULT_SUPP)          # 100 字

DEFAULT_TOPICS = [{'id': 'fed', 'label': '聯準會', 'chips': ['fedwatch', 'fw_h1', 'fw_h2', 'fw_h3', 'dgs3mo', 'dgs2'], 'keywords': ['Fed', 'Federal Reserve', 'FOMC', 'Powell', 'Warsh', '聯準會', '降息', '升息', 'rate cut', 'rate cuts', 'rate hike'], 'search': [{'q': 'Federal Reserve officials', 'lang': 'en'}, {'q': 'Fed (site:reuters.com OR site:bloomberg.com)', 'lang': 'en'}]}, {'id': 'long', 'label': '長天期美債', 'chips': ['dgs5', 'dgs7', 'dgs10', 'dgs20', 'dgs30', 'move', 'live_dgs10', 'live_dgs30'], 'keywords': ['Treasury', 'Treasuries', '10-year', '30-year', '美債', '美國公債', '美債殖利率', '公債標售'], 'search': [{'q': 'Treasury yields (site:reuters.com OR site:bloomberg.com)', 'lang': 'en'}, {'q': 'Treasury auction', 'lang': 'en'}], 'require': ['Treasury', 'Treasuries', 'US bonds', 'U.S. bonds', '美債', '美國公債', '美國財政部']}, {'id': 'funding', 'label': '資金市場', 'chips': ['sofr', 'sofr_iorb', 'onrrp', 'srf'], 'keywords': ['repo market', 'SOFR', 'bank reserves', 'reverse repo', 'standing repo', 'money market', '回購市場', '準備金', 'repo', 'repurchase agreement', 'repo rates', 'funding pressure', 'funding stress', 'money markets', 'money-market funds', 'money market funds', 'dollar liquidity', 'overnight funding', 'Treasury bills', 'T-bills', 'Treasury cash balance', 'market stress', 'IORB', 'SRF', 'ON RRP', '資金市場', '貨幣市場', '美元流動性', '隔夜利率', '隔夜融資', '短期融資', '回購利率', '銀行準備金', '美國國庫券', '短期美債', '資金壓力'], 'search': [{'q': '("money market" OR "money markets" OR repo OR SOFR OR "Treasury bills") ("United States" OR Fed OR "U.S.")', 'lang': 'en'}, {'q': 'Fed (reserves OR liquidity OR "market stress") (site:reuters.com OR site:bloomberg.com)', 'lang': 'en'}, {'q': '美國 (回購市場 OR 貨幣市場 OR 流動性 OR 國庫券)', 'lang': 'zh'}]}, {'id': 'oil', 'label': '油價', 'chips': ['wti', 'brent'], 'keywords': ['oil', 'crude', 'OPEC', 'Brent', 'WTI', '油價', '原油', 'crude oil', 'oil prices', 'OPEC+', 'Middle East war', 'US-Iran conflict', 'U.S.-Iran conflict', 'Iran', 'Israel', 'Gaza', 'Strait of Hormuz', 'Red Sea', '中東戰爭', '中東衝突', '美伊衝突', '伊朗', '以色列', '加薩', '荷姆茲海峽', '霍爾木茲海峽', '紅海', '油輪', '能源供應', '航運中斷', '制裁'], 'search': [{'q': 'oil prices (site:reuters.com OR site:bloomberg.com)', 'lang': 'en'}, {'q': '油價 (原油 OR 中東 OR 伊朗)', 'lang': 'zh'}]}, {'id': 'equity', 'label': '美股', 'chips': ['dji', 'spx', 'ixic', 'vix'], 'keywords': ['Dow', 'S&P 500', 'Nasdaq', 'Wall Street', 'stocks', 'VIX', '美股', '道瓊', '標普', 'AI', 'artificial intelligence', 'Nvidia', 'OpenAI', 'AI capex', 'data center', 'data centers', 'hyperscaler', '人工智慧', '輝達', '資料中心', 'AI 伺服器'], 'require': ['Dow', 'S&P 500', 'S&P', 'Nasdaq', 'Wall Street', 'US stocks', 'U.S. stocks', 'stocks', 'stock market', 'equities', 'VIX', '美股', '道瓊', '標普', '那斯達克', '華爾街', '美國股市'], 'exclude_add': ['台股', '日股', '陸股', '港股', '歐股', '韓股', 'A股', '日經', '恆生', 'Nikkei', 'Hang Seng', 'FTSE', 'DAX', 'European stocks', 'Asian stocks', 'China stocks', 'Japan stocks', 'oil stocks', 'crude stocks', 'G7 stocks', 'stockpile', 'World Bank', '世界銀行'], 'search': [{'q': '(S&P OR Nasdaq OR Dow OR "Wall Street") (site:reuters.com OR site:bloomberg.com)', 'lang': 'en'}, {'q': '美股 (道瓊 OR 標普 OR 那斯達克 OR 收盤)', 'lang': 'zh'}]}, {'id': 'semi', 'label': 'AI 與半導體', 'chips': ['sox'], 'keywords': ['chip', 'chips', 'chipmaker', 'chipmakers', 'semiconductor', 'semiconductors', 'Nvidia', 'TSMC', 'AI capex', '半導體', '晶片', '輝達', '台積電', 'AI', 'artificial intelligence', 'OpenAI', 'data center', 'data centers', 'hyperscaler', '人工智慧', '資料中心', 'AI 伺服器'], 'exclude': ['ETF', '存股', '高股息', '股息', '定期定額', '0050', '台股', '金控', '必漲', '卡位', '黑馬', '飆股', '千金股'], 'search': [{'q': 'chip stocks OR semiconductor (site:reuters.com OR site:bloomberg.com)', 'lang': 'en'}]}, {'id': 'twf', 'label': '台指期', 'chips': ['txf', 'twii'], 'keywords': ['台指期', '台股', '加權指數', '外資', '夜盤', '人工智慧', '輝達', '台積電', 'AI 伺服器', 'AI 概念股', 'TAIEX', 'Taiwan stocks', 'Taiwan futures', 'TXF', 'NVIDIA', 'TSMC'], 'exclude': ['ETF', '存股', '高股息', '定期定額', '0050', '必漲', '卡位', '黑馬', '飆股', '千金股', 'ETFs', '指數型基金', '指數股票型基金', '配息', '申購', '股息'], 'search': [{'q': '(台指期 OR 臺指期) (夜盤 OR 日盤)', 'lang': 'zh'}, {'q': '(台股 OR 加權指數) (外資 OR 收盤)', 'lang': 'zh'}], 'require': ['台指期', '臺指期', '台股', '臺股', '加權指數', '台灣股市', '臺灣股市', 'TAIEX', 'Taiwan stocks', 'Taiwan futures', 'TXF']}, {'id': 'election', 'label': '期中選舉', 'chips': ['pm_house', 'pm_senate'], 'keywords': ['midterm', 'midterms', 'Senate race', 'House majority', 'Senate control', 'House control', '期中選舉', '參議院', '眾議院', 'Senate election', 'House election', 'congressional election', 'midterm election', 'midterm elections', 'US election', '美國選舉', '美國大選', '國會選舉', '選情'], 'search': [{'q': '"midterm elections" (Senate OR House OR poll OR campaign) (site:reuters.com OR site:bloomberg.com)', 'lang': 'en'}, {'q': '("US midterms" OR "U.S. midterms" OR "midterm elections")', 'lang': 'en'}, {'q': '美國 (期中選舉 OR 中期選舉) (參議院 OR 眾議院 OR 民調)', 'lang': 'zh'}]}, {'id': 'gold', 'label': '黃金', 'chips': ['gold'], 'keywords': ['gold', 'bullion', 'XAU/USD', 'gold futures', '黃金', '金價'], 'exclude': ['ETF', 'ETFs', '黃金ETF', '珠寶促銷', '飾金促銷'], 'search': [{'q': 'gold prices (site:reuters.com OR site:bloomberg.com)', 'lang': 'en'}, {'q': '黃金 金價', 'lang': 'zh'}]}, {'id': 'fx', 'label': '匯率', 'chips': ['dxy', 'twd', 'eurusd', 'usdjpy', 'usdcnh'], 'keywords': ['USD/TWD', 'USDTWD', 'TWD', 'Taiwan dollar', 'New Taiwan dollar', 'DXY', 'dollar index', 'US dollar', 'U.S. dollar', 'dollar', '台幣', '臺幣', '新台幣', '美元', '美元指數', '台灣央行', '臺灣央行', '外資匯入', '外資匯出'], 'require': ['USD/TWD', 'USDTWD', 'TWD', 'Taiwan dollar', 'New Taiwan dollar', 'DXY', 'dollar index', 'US dollar', 'U.S. dollar', 'dollar', '台幣', '臺幣', '新台幣', '美元', '美元指數'], 'exclude': ['ETF', 'ETFs', '存股', '高股息', '定期定額'], 'search': [{'q': '台幣 美元 匯率', 'lang': 'zh'}, {'q': 'Taiwan dollar currency Reuters', 'lang': 'en'}, {'q': 'US dollar index (site:reuters.com OR site:bloomberg.com)', 'lang': 'en'}]}]

_GNEWS = {"en": "https://news.google.com/rss/search?q={q}%20when:2d"
                "&hl=en-US&gl=US&ceid=US:en",
          "zh": "https://news.google.com/rss/search?q={q}%20when:2d"
                "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"}


def topic_specs(cfg: dict | None) -> list[dict]:
    """config 的 topics:（沒設就用內建主題），正規化成固定欄位。"""
    raw = (cfg or {}).get("topics") or DEFAULT_TOPICS
    out = []
    for t in raw:
        if not isinstance(t, dict) or not t.get("id"):
            continue
        out.append({
            "id": str(t["id"]), "label": str(t.get("label") or t["id"]),
            "chips": [str(c) for c in (t.get("chips") or [])],
            "keywords": [str(k) for k in (t.get("keywords") or []) if k],
            # exclude 有寫就**取代**全站排除詞（台指期要放行「台股」）
            "exclude": ([str(x) for x in t["exclude"]]
                        if t.get("exclude") is not None else None),
            "search": [s for s in (t.get("search") or []) if isinstance(s, dict)
                       and s.get("q")],
            # require：標題至少要再命中其中一個詞組（例：美股必須真的在講美股）
            "require": [str(k) for k in (t.get("require") or []) if k],
            # exclude_add：在全站（或主題自己的）排除詞之外追加
            "exclude_add": [str(x) for x in (t.get("exclude_add") or []) if x],
            # feeds：只給這個主題用的 RSS（例：FXStreet 只餵匯率與黃金，不進主軸）
            "feeds": [f for f in (t.get("feeds") or []) if f],
        })
    return out


def chip_topic_map(specs: list[dict]) -> dict:
    return {c: s["id"] for s in specs for c in s["chips"]}


def pick_topics(sel: list[str], cmap: dict, available, n: int = 2) -> list[str]:
    """
    讀者的指標順序 → 要顯示的主題（最多 n 個）。同主題只算一次；
    沒有內容的主題跳過、往下一個指標遞補。前端 JS 是同一套規則。
    """
    out = []
    for c in sel or []:
        tid = cmap.get(c)
        if tid and tid in available and tid not in out:
            out.append(tid)
        if len(out) >= n:
            break
    return out


def _topic_url(s: dict) -> str:
    return _GNEWS.get(str(s.get("lang") or "en"), _GNEWS["en"]).format(
        q=quote(str(s["q"])))


def _phrase_hit(kw: str, title: str) -> bool:
    """
    主題關鍵字是**詞組**比對（跟主軸的「空白拆成單詞」不同）：「Wall Street」
    要整組出現，不能拆成「Wall」「Street」——拆開的話「market」「500」這種
    單詞會命中幾乎所有標題。中文詞組（「台股 外資」）則是每個詞都要出現。
    """
    t = _kw_text(title or "")
    kw = str(kw).strip()
    if not kw:
        return False
    if kw.isascii():
        return re.search(r"(?<![A-Za-z])" + re.escape(kw.lower()) + r"(?![A-Za-z])",
                         t.lower()) is not None
    return all(w in t for w in kw.split())


def _rank_topic(cand: list[dict], kws, n: int, now=None) -> list[dict]:
    """主題內排序：命中詞組數 ×2＋時效＋來源（彭博路透優先），再擋同一件事。"""
    scored = sorted(cand, reverse=True, key=lambda h: (
        2.0 * sum(_phrase_hit(k, h.get("title") or "") for k in kws)
        + rank_score(h, [], now=now)))
    out = []
    for h in scored:
        c = _norm_title(h["title"])
        if any(_sim(c, _norm_title(p["title"])) > 0.55 for p in out):
            continue
        out.append(h)
        if len(out) >= n:
            break
    return out


def gather_topic_material(specs: list[dict], pool: list[dict], *,
                          global_exclude=None, main_titles=(), now=None,
                          _fetch=None, _body=None) -> dict:
    """
    每個主題的材料：{tid: {"arts": [...], "briefs": [...], "links": [...]}}。
      · 候選＝主 feed 池（不分關鍵字的全部項目）用主題詞組篩＋主題自己
        的 Google News 搜尋與專屬 feed（同樣用詞組篩）
      · 跟主軸用到的報導是同一則的（標題相似）先剔掉——補充不重複主軸
      · 有內文的取前 2 篇抓正文；只有標題的取前 3 則當「標題快訊」
    """
    fetch = _fetch or fetch_feed_headlines
    body = _body or fetch_article_text
    mains = [_norm_title(x) for x in main_titles if x]
    picked: dict = {}
    for s in specs:
        exc = list(s["exclude"] if s["exclude"] is not None else (global_exclude or []))
        exc += s.get("exclude_add") or []
        req = s.get("require") or []
        extra = []
        srcs = ([{"url": _topic_url(x), "all": True} for x in s["search"]]
                + [{"url": f, "all": True} if isinstance(f, str) else {**f, "all": True}
                   for f in s.get("feeds") or []])
        if srcs:
            try:
                extra = fetch(srcs, [], hours=36, exclude=exc)
            except Exception as e:                 # noqa: BLE001
                log.warning("主題補充：%s 的搜尋 feed 失敗（%s）", s["id"], e)
        seen, cand = set(), []
        for h, _srch in ([(x, False) for x in pool]
                         + [(x, True) for x in (extra or [])]):
            title = h.get("title") or ""
            k = _norm_title(title)[:40]
            if (k in seen or _excluded(title, exc)
                    or not any(_phrase_hit(w, title) for w in s["keywords"])
                    or (req and not any(_phrase_hit(w, title) for w in req))
                    or any(_sim(_norm_title(title), m) > 0.55 for m in mains)):
                continue
            seen.add(k)
            h = dict(h)
            # Google News 搜尋的項目：真正的來源在標題尾巴「 - Reuters」
            if "news.google" in (h.get("link") or "") or not h.get("source") \
                    or "news.google" in h.get("source", ""):
                m_ = re.search(r"\s[-–—]\s([^-–—]{2,40})$", title)
                if m_:
                    h["source"] = m_.group(1).replace(".com", "").strip()
                elif not h.get("source"):
                    h["source"] = "Google News"
            cand.append(h)
        if not cand:
            continue
        picked[s["id"]] = {
            "body_cand": _rank_topic([h for h in cand if not _headline_only(h["link"])],
                                     s["keywords"], 2, now),
            "briefs": _rank_topic([h for h in cand if _headline_only(h["link"])],
                                  s["keywords"], 3, now),
            "links": _rank_topic(cand, s["keywords"], 2, now)}
    # 內文一次並行抓（全部主題合起來）
    jobs = [(tid, h) for tid, m in picked.items() for h in m["body_cand"]]
    bodies = _pmap(lambda j: body(j[1]["link"]), jobs, workers=8)
    out = {}
    for tid, m in picked.items():
        arts = [{"title": h["title"], "body": b, "source": h.get("source", ""),
                 "link": h["link"], "at": h.get("at", "")}
                for (t2, h), b in zip(jobs, bodies) if t2 == tid and b]
        if not arts and not m["briefs"]:
            continue
        out[tid] = {"arts": arts, "briefs": m["briefs"],
                    "links": [_link_of(x) for x in m["links"]]}
    return out


_TOPIC_SYSTEM = (
    "你是財經記者。輸入的最前面是今天首頁「主軸」已經寫過的內容，後面分成幾個"
    "主題區塊（=== 代號｜主題 ===），每個區塊裡的報導有編號，例如【1｜Reuters｜10/9】。"
    "為每個區塊寫一則重點，{min}–{cap} 個中文字：寫出發生了什麼，再加一個具體細節"
    "（數字、時間、誰說的或原因）；材料裡有人講到時，點出它對利率、聯準會或市場的"
    "意義。不能只重述標題。**不要跟主軸講同一件事**——區塊裡若都是主軸那件事，就寫"
    "同一主題下的另一件事；真的沒有別的事就輸出「代號｜略」。硬性規則：只能使用"
    "該區塊材料裡的資訊，不得補充材料以外的事實或數字；只有標題的新聞只能轉述"
    "標題與摘要字面上的事；不得自行推論來源沒有寫的因果關係；不做預測、不下投資"
    "結論；繁體中文；不要評論材料本身，不要出現「材料」「區塊」這類字眼。"
    "「AI 與半導體」只寫國際大廠與產業趨勢（輝達、台積電、博通、雲端大廠的資本支出等），"
    "不寫台股個股的股價、法人買賣超或概念股。"
    + _NEWS_RULES +
    "輸出格式：每個主題一行，「代號｜內容〔用到的報導編號〕」，例如"
    "「oil｜…〔1,3〕」，不要其他文字、不要編號開頭、不要粗體記號。")

_TOPIC_LINE = re.compile(r"^\s*[-*・•]?\s*([a-z][a-z0-9_]*)\s*[｜|:：]\s*(.+?)\s*$")


def _topic_block(tid: str, label: str, m: dict) -> str:
    parts = [f"=== {tid}｜{label} ==="]
    for i, a in enumerate(_topic_mats(m), 1):
        if a.get("body"):
            parts.append(f"【{i}｜{a.get('source') or '—'}｜{_us_date(a.get('at', ''))}】"
                         f"{a['title']}\n{a['body']}")
        else:
            parts.append(f"【{i}｜{a.get('source') or '—'}｜{_us_date(a.get('at', ''))}｜只有標題】"
                         f"{a['title']}" + (f"——{a['summary']}" if a.get("summary") else ""))
    return "\n".join(parts)


def _topic_mats(m: dict) -> list[dict]:
    return list(m.get("arts") or []) + list(m.get("briefs") or [])


_SALIENT_NUM = re.compile(r"\d+(?:\.\d+)?%|\d+(?:\.\d+)?\s*(?:bp|基點|億|兆|點)|\d{4,}")


def _dup_with_main(text: str, main_text: str) -> bool:
    """補充跟主軸講同一件事：共用 2 個以上的關鍵數字（百分比、bp、金額、點數），
    或補充的字元二元組有 45% 以上出現在主軸裡。"""
    if not text or not main_text:
        return False
    nums = set(_SALIENT_NUM.findall(text)) & set(_SALIENT_NUM.findall(main_text))
    if len(nums) >= 2:
        return True
    a = re.sub(r"[^一-鿿A-Za-z0-9]", "", text)
    b = re.sub(r"[^一-鿿A-Za-z0-9]", "", main_text)
    if len(a) < 10:
        return False
    A = {a[i:i + 2] for i in range(len(a) - 1)}
    B = {b[i:i + 2] for i in range(len(b) - 1)}
    return len(A & B) / max(1, len(A)) >= 0.45


_TOPIC_IDS = re.compile(r"\s*[〔\[［(（]\s*([\d,，、\s]+)\s*[〕\]］)）]\s*$")


def _parse_topic_lines(text: str) -> dict:
    """{tid: (內容, [報導編號])}"""
    out = {}
    for ln in _tidy_focus(text).splitlines():
        m = _TOPIC_LINE.match(ln)
        if m and m.group(1) not in out:
            body = m.group(2).strip()
            ids = []
            mi = _TOPIC_IDS.search(body)
            if mi:
                ids = [int(x) for x in re.findall(r"\d+", mi.group(1))]
                body = body[:mi.start()].strip()
            out[m.group(1)] = (body, ids)
    return out






def summarize_topics(material: dict, labels: dict, main_text: str, env=None,
                     meta_markers=None, name_map=None, rate_ctx=None) -> dict:
    """
    一次 AI 呼叫寫完所有主題；逐則驗證（後設字眼、數字鎖對該主題自己的
    材料、長度、跟主軸重複、媒體名、相對時間）。有問題的主題帶原因**只重寫
    那幾個**一次；仍不合格就不顯示那個主題（選單變灰）。
    回傳 {tid: {"text": 文字, "ids": [報導編號]}}。
    """
    if not material:
        return {}
    system = _TOPIC_SYSTEM.format(min=TOPIC_MIN, cap=TOPIC_CHARS)
    head = "=== 今日主軸（不要重複）===\n" + (main_text or "").replace(MAIN_PARA, "\n")
    _pol = ((rate_ctx or {}).get("policy") or {}).get("stance")
    if _pol in ("hike", "cut"):
        head += ("\n※ 政策現況：目前是" + ("升息" if _pol == "hike" else "降息")
                 + "循環，任何主題都不得寫相反方向的「繼續" + ("降息" if _pol == "hike" else "升息") + "」這類說法。")
    srcs = {tid: _topic_block(tid, labels.get(tid, tid), m)
            for tid, m in material.items()}
    good: dict = {}
    soft: dict = {}                                 # 第二次只剩文風問題的：修正後採用
    todo = list(material)
    note = ""
    for attempt in (1, 2):
        text, err = _call_ai(head + "\n\n" + "\n\n".join(srcs[t] for t in todo)
                             + note, system, env)
        if err:
            log.warning("主題補充：AI 呼叫失敗（%s）", err)
            break
        got = _parse_topic_lines(text)
        bad = {}
        for tid in todo:
            s, ids = got.get(tid) or ("", [])
            s = s.strip()
            if not s or s in ("略", "無", "—"):
                continue                           # 沒有別的事：這個主題不顯示
            if _meta_hits(s, meta_markers):
                bad[tid] = "在評論材料而不是寫新聞"
            elif not _digits_ok(s, srcs[tid]):
                bad[tid] = "出現該主題材料裡沒有的數字"
            elif _policy_hits(s, rate_ctx):
                bad[tid] = "政策方向跟現況相反（不得寫" + "、".join(_policy_hits(s, rate_ctx)) + "）"
            elif _dup_with_main(s, main_text):
                bad[tid] = "跟主軸講同一件事，請寫同主題的另一件事，沒有就輸出略"
            elif cjk_len(s) < int(TOPIC_MIN * SHORT_TOL) and attempt == 1:
                bad[tid] = (f"只有 {cjk_len(s)} 字，像在列標題（要寫出發生了什麼"
                            "再加一個具體細節）")
            elif (_media_hits(s) or _REL_DATE.search(s)) and attempt == 1:
                bad[tid] = "正文寫了媒體名稱或相對時間（要寫月/日、不寫媒體名）"
                soft[tid] = {"text": s, "ids": ids}
            else:
                good[tid] = {"text": s, "ids": ids}
        if not bad or attempt == 2:
            for tid in bad:
                if tid in soft and tid not in good:
                    good[tid] = soft[tid]
            hidden = [t for t in bad if t not in good]
            if hidden:
                log.warning("主題補充：重寫後仍不合格，不顯示 %s", "、".join(hidden))
            break
        log.warning("主題補充：%s，帶原因重寫一次",
                    "；".join(f"{k} {v}" for k, v in bad.items()))
        todo = list(bad)
        note = ("\n\n（上一次這幾個主題被退回："
                + "；".join(f"{k}：{v}" for k, v in bad.items())
                + f"。請只重寫這幾個主題，每則 {TOPIC_MIN}–{TOPIC_CHARS} 字。）")
    for tid, g in good.items():
        g["text"] = _trim_to(normalize_names(_strip_media(g["text"]), name_map), TOPIC_HARD)
    log.info("主題補充：產出 %d 個主題（%s）", len(good), "、".join(good))
    return good










def build_topics(cfg: dict | None, pool: list[dict], main_text: str,
                 main_titles, state: dict, env=None, now=None,
                 meta_markers=None, rate_ctx=None) -> dict:
    """
    主題補充的整條流程（含快取）：回傳 {"items": [...], "map": {chip: tid}}。
    快取鍵＝提示詞版本＋主軸來源標題＋各主題入選標題；12 小時內相同就沿用。
    寫不出合格內容的主題不在 items 裡——首頁選單會把它變灰、不能選。
    """
    specs = topic_specs(cfg)
    res = {"items": [], "map": chip_topic_map(specs),
           "order": [s["id"] for s in specs]}
    if not specs:
        return res
    labels = {s["id"]: s["label"] for s in specs}
    mat = gather_topic_material(
        specs, pool, global_exclude=(cfg or {}).get("exclude_keywords") or [],
        main_titles=main_titles, now=now)
    _stance = ((rate_ctx or {}).get("policy") or {}).get("stance") or ""
    # v2：主軸每次都重寫，快取鍵改用主軸的「來源標題」而不是主軸文字——新聞沒變就沿用
    _mk = "|".join(sorted(str(t) for t in (main_titles or [])))
    key = hashlib.sha256((TOPIC_PROMPT_VERSION + "|" + _stance + "|" + _mk + "|" + "|".join(
        f"{tid}:" + ",".join(x["title"] for x in _topic_mats(m))
        for tid, m in sorted(mat.items()))).encode("utf-8")).hexdigest()[:16]
    old = state.get("topics") or {}
    _age = _age_hours({"at": old.get("at")}, now or dt.datetime.now(dt.timezone.utc))
    if old.get("hash") == key and old.get("items") and _age is not None \
            and _age < CACHE_TTL_HOURS:
        log.info("主題補充：材料與上次相同，沿用 %.1f 小時前的內容", _age)
        res["items"] = old["items"]
        return res
    texts = summarize_topics(mat, labels, main_text, env, meta_markers,
                             name_map=_name_map(cfg), rate_ctx=rate_ctx)
    items = []
    for tid in res["order"]:
        if tid not in texts:
            continue
        mats = _topic_mats(mat[tid])
        links = _pick_links(mats, texts[tid]["ids"], 2) if texts[tid]["ids"] else []
        items.append({"id": tid, "label": labels[tid], "text": texts[tid]["text"],
                      "links": links or mat[tid]["links"]})
    res["items"] = items
    if res["items"]:
        state["topics"] = {"hash": key, "items": res["items"],
                           "at": (now or dt.datetime.now(dt.timezone.utc)).isoformat()}
    return res




def _lock_events(events: dict | None, cfg: dict | None, now_tw: dt.datetime) -> list[str]:
    """
    主軸鎖定的事件：當天（台北）有發布，或**前一天有發布且現在是台北中午前**。
    台北早上 05:03 那次對應美國前一天的 CPI／FOMC，要鎖；到了下午 15:03、
    晚上 20:33 就該換寫別的事，不再鎖（排序加分仍照 _todays_events）。
    """
    today = now_tw.date()
    days = {today.isoformat()}
    if now_tw.hour < 12:
        days.add((today - dt.timedelta(days=1)).isoformat())
    out = []
    for kind in LOCK_EVENTS:
        dates = (events or {}).get(kind) or []
        if isinstance(dates, str):
            dates = [dates]
        if kind == "fomc":
            dates = list(dates) + list((cfg or {}).get("fomc_dates") or [])
        if any(str(d)[:10] in days for d in dates):
            out.append(kind)
    return out


def _todays_events(events: dict | None, cfg: dict | None,
                   today: dt.date) -> list[str]:
    """
    今天（或前一天）有哪些發布事件。前一天也算：台灣早上 05:03 那次
    對應的是美國前一天的發布（CPI 美東 08:30＝台灣當晚，隔天早上才是
    第一次完整的收盤後執行）。events 是 {種類: [ISO 日期, …]}；FOMC
    會議日直接讀 config 的 fomc_dates（會後聲明在美東下午兩點，同理）。
    """
    days = {today.isoformat(), (today - dt.timedelta(days=1)).isoformat()}
    out = []
    for kind, dates in (events or {}).items():
        if isinstance(dates, str):
            dates = [dates]
        if any(str(d)[:10] in days for d in (dates or [])):
            out.append(kind)
    if "fomc" not in out and any(
            str(d)[:10] in days for d in ((cfg or {}).get("fomc_dates") or [])):
        out.append("fomc")
    return out


ARCHIVE_DAYS = 8          # v2：留 8 天給星期天週報用；首頁只顯示最近 ARCHIVE_SHOW 天
ARCHIVE_SHOW = 5
_TPE = dt.timezone(dt.timedelta(hours=8))


def update_archive(arch, st: dict) -> dict:
    """
    主軸存檔（2026-10）：{台灣日期: {headline, text, rate_note, links, at}}。
    同一天跑三次，後面的蓋掉前面的＝保留「當天最後一版」；只留最近 ARCHIVE_DAYS 天
    （2026-10 起週日也跑一次，週日版與週六內容相近）。沒有主軸（退回列標題）不存。
    """
    arch = dict(arch) if isinstance(arch, dict) else {}
    if st.get("text") and st.get("layout") == "main" and st.get("at"):
        try:
            at = dt.datetime.fromisoformat(str(st["at"]))
            if at.tzinfo is None:
                at = at.replace(tzinfo=dt.timezone.utc)
            day = at.astimezone(_TPE).date().isoformat()
            arch[day] = {"headline": st.get("headline", ""), "text": st.get("text", ""),
                         "rate_note": st.get("rate_note", ""), "links": st.get("links") or [],
                         "at": st["at"], "weekly": bool(st.get("weekly"))}
        except (TypeError, ValueError):
            pass
    keep = sorted(arch, reverse=True)[:ARCHIVE_DAYS]
    return {k: arch[k] for k in keep}


def archive_list(arch) -> list[dict]:
    """新→舊的清單，每筆多一個 date 欄位，給首頁畫日期列。"""
    return [dict(v, date=k) for k, v in sorted((arch or {}).items(), reverse=True)
            if isinstance(v, dict)][:ARCHIVE_SHOW]


# ---- v2（2026-10-25）：時間窗、FedWatch 變化、選題紀錄、星期天週報 ----
WINDOW_STEPS = (18, 30, 60)      # 小時；不到 MIN_MAIN_STORIES 則不同報導就放寬
BODY_SLOTS = 6                   # 內文擷取篇數上限（2026-10-26 恢復成 v1 的 6 篇）


def _fomc_block(cfg: dict | None, today: dt.date, days: int = 45) -> str:
    """近期 FOMC 會議日（官方日程，美東）放進材料：主軸寫「10/28 會議」時有出處。"""
    lo, hi = today.isoformat(), (today + dt.timedelta(days=days)).isoformat()
    ds = sorted({str(d)[:10] for d in (cfg or {}).get("fomc_dates") or [] if lo <= str(d)[:10] <= hi})
    if not ds:
        return ""
    return ("\n\n=== 近期 FOMC 會議日（官方日程，美東；利率決策在最後一天下午 2 點）===\n"
            + "、".join(f"{int(d[5:7])}/{int(d[8:10])}" for d in ds))
FOCUS_LOG_KEEP = 30


def _fw_move_prob(fw: dict | None) -> tuple[str, float] | None:
    """下一次會議「有動作」（升或降）的機率（0–1）與會議日。"""
    nxt = (fw or {}).get("next") or {}
    oc = nxt.get("outcomes") or []
    if not oc or not nxt.get("date"):
        return None
    try:
        return str(nxt["date"])[:10], float(sum(p for b, p in oc if b))
    except (TypeError, ValueError):
        return None


def fw_change(state: dict, fw: dict | None, today: str) -> float | None:
    """
    FedWatch 下一次會議「有動作」機率較前一天的變化（百分點）。
    state["fw_hist"]＝{日期: {"meeting", "p"}}，只留 10 天；會議換了（上一場開完）不比。
    """
    cur = _fw_move_prob(fw)
    hist = state.get("fw_hist") if isinstance(state.get("fw_hist"), dict) else {}
    if cur is None:
        return None
    hist[today] = {"meeting": cur[0], "p": round(cur[1], 4)}
    hist = {k: hist[k] for k in sorted(hist)[-10:]}
    state["fw_hist"] = hist
    prev = [k for k in sorted(hist) if k < today and hist[k].get("meeting") == cur[0]]
    if not prev:
        return None
    return round((cur[1] - float(hist[prev[-1]]["p"])) * 100, 1)


def write_focus_log(path: Path, entry: dict) -> None:
    """選題紀錄（state/focus_log.json）：每次執行一筆，只留最近 FOCUS_LOG_KEEP 筆。失敗不影響產出。"""
    try:
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except Exception:                          # noqa: BLE001
            rows = []
        if not isinstance(rows, list):
            rows = []
        rows.append(entry)
        path.write_text(json.dumps(rows[-FOCUS_LOG_KEEP:], ensure_ascii=False, indent=1,
                                   default=str), encoding="utf-8")
    except Exception as e:                         # noqa: BLE001
        log.warning("市場焦點：選題紀錄寫入失敗（%s）", e)


WEEKLY_CAPS, WEEKLY_MINS = [250, 60, 60, 60, 60], [200, 12, 12, 12, 12]

_FOCUS_WEEKLY_SYSTEM = (
    "你是財經記者，負責一個美國利率與總經儀表板星期天早上的「本週回顧與下週重點」。"
    "輸入有：本週每天的今日主軸（本站已發布的內容）、本週新聞標題（每則有代號，例如"
    "【報導3｜Reuters｜10/9｜只有標題】）、下週官方行事曆，以及「網站利率判讀」（本週 10 年期等殖利率的變化）。"
    "主題範圍：{kws}。依下面的格式輸出：\n"
    "【標題】一句話標題，14–28 個中文字，點出本週最重要的主線，不加句號。\n"
    "【主軸】本週回顧，{min}–{main} 個中文字，分 2–3 段（每段一行）：本週最重要的一兩件事"
    "發生了什麼、為什麼重要、官員或市場怎麼解讀（只寫材料裡有的）。主角是新聞事件，"
    "市場數字最多一句。\n"
    "【對利率】一句話，40–90 個中文字：本週這些事對美國利率偏向推升還是壓低、為什麼，"
    "再用「網站利率判讀」的 10 年期本週變化對照（方向一致說市場已在反映，不一致明講落差）。"
    "只能寫「偏向」「若…則…」。\n"
    "【補充】{ns} 行，每行一項下週重點，{supp} 個中文字以內，只能從「下週官方行事曆」挑："
    "寫日期（月/日）＋事件＋市場關注什麼。不要寫任何預估值或市場共識數字。\n"
    "【來源】回顧用到的新聞代號，用逗號分隔，例如「1,4」；彭博、路透排前面（最多 3 則）。\n"
    "硬性規則：只能使用材料已有的資訊，不得補充材料以外的事實或數字；不做預測、不下投資結論；"
    "美國期中選舉只寫它對市場與政策的影響；日期一律寫成月/日，不要用「本週」「下週」「週X」"
    "這類相對說法；繁體中文。絕對禁止評論材料本身（不要出現「材料」「關鍵字」「代號」這類字眼）。"
    + _NEWS_RULES +
    "輸出格式：【標題】【主軸】【對利率】【補充】【來源】各自單獨一行，內容接在下一行；"
    "不要編號、不要符號開頭、不要粗體記號、不要任何前言。")


def weekly_calendar(events: dict | None, cfg: dict | None, today: dt.date) -> list[tuple[str, str, str]]:
    """下週（明天起 7 天）的官方行事曆：[(ISO 日期, 事件名稱, 美東時間)]，依日期排。"""
    from . import watch_calendar as wc
    ev = dict(events or {})
    ev["fomc"] = sorted({str(d)[:10] for d in (ev.get("fomc") or [])}
                        | {str(d)[:10] for d in (cfg or {}).get("fomc_dates") or []})
    lo, hi = (today + dt.timedelta(days=1)).isoformat(), (today + dt.timedelta(days=7)).isoformat()
    out = []
    for kind, dates in ev.items():
        if kind in ("gdp_adv", "testimony"):
            continue                               # gdp 已在 gdp；證詞沒有行事曆
        if isinstance(dates, str):
            dates = [dates]
        meta = wc.EVENTS.get(kind)
        name = EVENT_NAMES.get(kind) or (meta[0] if meta else "")
        if meta and kind not in ("refunding", "fomc_minutes"):
            name = meta[0]
        hm = EVENT_TIMES.get(kind) or (meta[2] if meta else None)
        if not name:
            continue
        for d in dates:
            d = str(d)[:10]
            if lo <= d <= hi:
                out.append((d, name, f"{hm[0]:02d}:{hm[1]:02d}" if hm else ""))
    return sorted(set(out))


def _weekly_cal_block(rows) -> str:
    if not rows:
        return "\n\n=== 下週官方行事曆（美東時間）===\n（下週沒有重大發布）"
    md = lambda s: f"{int(s[5:7])}/{int(s[8:10])}（{_WD7[dt.date.fromisoformat(s).weekday()]}）"
    return ("\n\n=== 下週官方行事曆（美東時間）===\n"
            + "\n".join(f"- {md(d)} {t + ' ' if t else ''}{n}" for d, n, t in rows))


def write_weekly(state: dict, keywords: list[str], exclude, rates_series, fw, events, cfg,
                 env, now_tw: dt.datetime, *, caps=None, mins=None, meta_markers=None,
                 vague_markers=None, name_map=None, facts_block: str = "",
                 release_dates_: dict | None = None, model: str | None = None,
                 archive: dict | None = None, _fetch=None) -> tuple[dict | None, str]:
    """星期天早上的「本週回顧與下週重點」：本週每日主軸存檔＋Google News 7 天＋下週行事曆。"""
    today = now_tw.date()
    week0 = (today - dt.timedelta(days=7)).isoformat()
    arch = archive if archive is not None else (state.get("archive") or {})
    days = [(k, v) for k, v in sorted((arch or {}).items())
            if isinstance(v, dict) and week0 <= k < today.isoformat() and v.get("text")
            and not v.get("weekly")]
    fetch = _fetch or fetch_headlines
    heads = election_filter(fetch([k + " when:7d" for k in keywords], hours=170))
    heads = [h for h in heads if not _excluded(h["title"], exclude)]
    if not days and not heads:
        return None, "本週沒有主軸存檔，也抓不到新聞"
    _now = dt.datetime.now(dt.timezone.utc)
    clusters = cluster_events(heads, lambda h: rank_score(h, keywords, now=_now))
    briefs = [g["lead"] for g in clusters[:8]]
    body, mats = _material_text([], briefs)
    md = lambda s: f"{int(s[5:7])}/{int(s[8:10])}"
    arch_txt = "\n".join(f"【{md(k)} 主軸】{v.get('headline', '')}——"
                         + str(v.get("text", "")).splitlines()[0].replace(MAIN_PARA, "")
                         for k, v in days)
    rc = rate_context(rates_series)
    if rc is not None:
        rc["live10"] = None
        rc["policy"] = policy_context(rates_series, fw)
    cal = weekly_calendar(events, cfg, today)
    rd = {k: list(v) for k, v in (release_dates_ or {}).items()}
    for k in FACT_NAMES:
        for d in (events or {}).get(k) or []:
            rd.setdefault(k, [])
            if str(d)[:10] not in rd[k]:
                rd[k] = sorted(rd[k] + [str(d)[:10]])
    src_text = (("=== 本週每日主軸（本站已發布）===\n" + arch_txt + "\n\n") if arch_txt else "") \
        + ("=== 本週新聞標題 ===\n" + body if body else "") \
        + _weekly_cal_block(cal) + _rate_block(rc) + facts_block
    caps = WEEKLY_CAPS
    mins = WEEKLY_MINS
    system = _FOCUS_WEEKLY_SYSTEM.format(kws="、".join(keywords), main=caps[0], supp=caps[1],
                                         ns=len(caps) - 1, min=mins[0])
    res, err = _generate_main(src_text, system, env, caps=caps, mins=mins,
                              meta_markers=meta_markers, vague_markers=vague_markers,
                              rate_ctx=rc, name_map=name_map, release_dates_=rd, model=model)
    if not res:
        return None, err
    ids = res.pop("ids")
    res["links"] = _pick_links(mats, ids, MAX_MAIN_LINKS, MAIN_LINKS_PER_TIER) if mats else []
    res["source"] = "model-weekly"
    return res, ""


def build(rates_series: dict | None, offline: bool, cfg: dict | None,
          state_path: Path, env=None, liq_series: dict | None = None,
          events: dict | None = None, election: dict | None = None,
          calendar: dict | None = None, fact_values: dict | None = None,
          fred_releases: dict | None = None) -> dict:
    cfg = cfg or {}
    keywords = cfg.get("keywords") or DEFAULT_KEYWORDS
    # 版式：N 則重點 × 每則 item_cap 字（使用者指定 3 則、每則 100 字內）
    n_items = int(cfg.get("items") or DEFAULT_ITEMS)
    item_cap = int(cfg.get("item_chars") or DEFAULT_ITEM_CHARS)
    # 版式 A：一段主軸＋補充（每行各自的字數上限）
    caps = focus_caps(cfg)
    mins = focus_mins(cfg)

    yields = [c for c in (
        _yield_chip((rates_series or {}).get("DGS10"), "10 年期"),
        _yield_chip((rates_series or {}).get("DGS30"), "30 年期"),
    ) if c]
    out = {"yields": yields,
           "asof": (yields[0]["date"] if yields else ""),
           "fedwatch": None, "text": "", "text_source": "",
           "links": [], "generated": clock.today().isoformat(),
           "chips": []}

    if offline or cfg.get("enabled") is False:
        out["text"] = ("示範頁面暫不提供新聞摘要；正式網站顯示"
                       "當天的市場焦點一段。")
        out["text_source"] = "offline"
        out["chips"] = build_catalog(rates_series, liq_series, yields,
                                     offline=True, election=election)
        out["topic_map"] = chip_topic_map(topic_specs(cfg))
        return out

    # Official daily yields remain primary; build_catalog fetches optional
    # intraday quotes under separate IDs, without replacing out["yields"].

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:                              # noqa: BLE001
        state = {}
    if not isinstance(state, dict):
        state = {}
    today = clock.today().isoformat()

    # ---- FedWatch：一天最多算一次；跳動 >20pp 視為擷取錯誤沿用前值 ----
    # 來源鏈：期貨自算 ×交叉檢核× Atlanta Fed → Gemini 擷取 → 沿用前值。
    #
    # 「一天最多算一次」要跟**算法版本**綁在一起：修了算法、當天稍晚的
    # 排程卻沿用早上用舊算法算的值，修正要到隔天才生效——100% 事故
    # 實際發生過「修完 push、下一次執行畫面還是 100%」正是這個原因。
    # state 記下算出該值的方法版本，不一致就當天重算。
    fw_old = state.get("fedwatch") or {}
    if (fw_old.get("date") == today and fw_old.get("method") == FW_METHOD
            and fw_old.get("path")):
        out["fedwatch"] = fw_old["path"]
    else:
        # 期貨逐會議前推（下次會議機率＋目標會議單場與累計幅度）。
        # Atlanta Fed 照舊每次打一次：未設定端點時只做偵察、把候選網址
        # 寫進 log；設定後當交叉檢核（差逾 25pp 記警告）。
        _path = fedwatch_path(rates_series, cfg)
        _at = fetch_atlanta_fedwatch(cfg)
        if _path is not None and _at is not None:
            _hz_up = sum(p for b, p in _path["horizon"]["outcomes"] if b > 0)
            if abs(_hz_up * 100 - _at) > 25:
                log.warning("FedWatch 交叉檢核：期貨推算 %.0f%% 與亞特蘭大"
                            "聯準銀行 %.0f%% 差逾 25pp", _hz_up * 100, _at)
        if _path is not None:
            out["fedwatch"] = _path
            state["fedwatch"] = {"date": today, "method": FW_METHOD,
                                 "path": _path}
        elif fw_old.get("path") and fw_old.get("method") == FW_METHOD:
            # 本次擷取失敗（限流、斷線）但手上有近幾天的值 → 沿用並標明；
            # 超過 4 天就太舊，寧可顯示「—」。舊算法的值一律不沿用。
            try:
                _age = (dt.date.fromisoformat(today)
                        - dt.date.fromisoformat(fw_old.get("date", ""))).days
            except (ValueError, TypeError):
                _age = 99
            if _age <= 4:
                out["fedwatch"] = {**fw_old["path"],
                                   "stale_from": fw_old.get("date")}
                log.warning("FedWatch：本次推算失敗，沿用 %s 的結果",
                            fw_old.get("date"))

    # ---- 焦點段 v2（2026-10-25）：事件分組＋市場訊號＋每次重寫；星期天早上改週報 ----
    # 規格：Google 文件「MacroGG 今日主軸規則 v2（2026-10-25 定案）」；v2.2（2026-10-27）見 apply_selection_cfg
    apply_selection_cfg(cfg)
    feeds = cfg.get("feeds") or DEFAULT_FEEDS
    exclude = cfg.get("exclude_keywords") or []
    kw2 = [str(k) for k in (cfg.get("keywords_secondary") or []) if k]
    meta_markers = ([str(m) for m in cfg.get("meta_markers") if m]
                    if cfg.get("meta_markers") else None)
    vague_markers = ([str(m) for m in cfg.get("vague_markers") if m]
                     if cfg.get("vague_markers") else None)
    name_map = _name_map(cfg)
    _now = dt.datetime.now(dt.timezone.utc)
    now_tw = clock.now()
    _live_ts = None
    try:
        rate_ctx = rate_context(rates_series)
        if rate_ctx is not None:
            _lv = live_10y()
            if _lv:
                _live_ts = _lv.pop("ts", None)
                log.info("市場焦點：10 年期即時 %s", _lv)
            rate_ctx["live10"] = _lv
            rate_ctx["policy"] = policy_context(rates_series, out.get("fedwatch"))
            if rate_ctx["policy"]:
                log.info("市場焦點：政策現況 %s", rate_ctx["policy"])
    except Exception as e:                         # noqa: BLE001
        log.warning("市場焦點：利率判讀計算失敗（%s），本次不附對利率", e)
        rate_ctx = None
    calendar = merge_calendar(calendar, fred_releases)
    _facts = release_facts(calendar, clock.today(), fact_values)
    _fblk = _facts_block(_facts) + _fomc_block(cfg, clock.today())
    _rel_dates = release_dates(calendar)
    _ev_all = derive_events(events, cfg)
    _w = dict(caps=caps, mins=mins, meta_markers=meta_markers,
              vague_markers=vague_markers, name_map=name_map,
              facts_block=_fblk, release_dates_=_rel_dates, model=FOCUS_MODEL)
    flog = {"at": _now.isoformat(timespec="minutes"), "mode": "daily"}
    res, err = None, ""
    _raw_pool: list = []                           # 主題補充用：時間窗內全部項目
    weekly = is_weekly(now_tw)
    if weekly:
        flog["mode"] = "weekly"
        try:
            res, err = write_weekly(state, keywords, exclude, rates_series, out.get("fedwatch"),
                                    _ev_all, cfg, env, now_tw, **_w)
        except Exception as e:                     # noqa: BLE001
            res, err = None, f"週報產生失敗（{e}）"
        if res:
            log.info("市場焦點：星期天週報產出")
            try:                                   # 主題補充仍用近 30 小時的新聞池
                fetch_feed_headlines(feeds, keywords + kw2, hours=30, exclude=exclude,
                                     raw_out=_raw_pool)
            except Exception as e:                 # noqa: BLE001
                log.warning("市場焦點：主題補充的新聞池抓取失敗（%s）", e)
        else:
            log.warning("市場焦點：%s，改寫一般的今日主軸", err)
            weekly = False
            flog["mode"] = "daily（週報失敗）"
    heads, top, mode = [], [], "content"
    if not weekly:
        # 時間窗：18 小時；不到 3 則不同報導放寬到 30、再不夠 60 小時
        for _hrs in WINDOW_STEPS:
            _raw_pool = []
            heads = election_filter(fetch_feed_headlines(feeds, keywords + kw2, hours=_hrs,
                                                         exclude=exclude, raw_out=_raw_pool))
            flog["window_h"] = _hrs
            if _story_count(heads) >= MIN_MAIN_STORIES:
                break
            log.info("市場焦點：%d 小時內只有 %d 則不同報導，放寬時間窗", _hrs, _story_count(heads))
        if not heads:
            log.warning("市場焦點：RSS 無命中或全部失敗，退回 Google News 標題模式")
            heads = [h for h in election_filter(fetch_headlines(keywords)) if not is_junk(h["title"])]
            mode = "title"
    if heads:
        _ev_d = dict(_ev_all)
        if testimony_today(heads):
            _ev_d["testimony"] = [clock.today().isoformat()]
        _ev = _todays_events(_ev_d, cfg, clock.today())
        _lock, _demoted = resolve_locks(
            [k for k in _lock_events(_ev_d, cfg, now_tw) if k in _ev], heads)
        if _ev:
            log.info("市場焦點：今天的發布事件 %s%s", "、".join(_ev),
                     ("，主軸鎖定 " + "、".join(_lock)) if _lock else "，相關新聞排序加分")
        # 市場訊號（線索，不強制）
        try:
            _fw_pp = fw_change(state, out.get("fedwatch"), today)
            _oil = fetch_yahoo_quote("CL=F", 10.0, 300.0)
            _spx = fetch_yahoo_quote("^GSPC", 1000.0, 30000.0)
            _lv10 = dict((rate_ctx or {}).get("live10") or {}, ts=_live_ts) if (rate_ctx or {}).get("live10") else None
            sig = market_signals(_lv10, rates_series, _oil, _spx, _fw_pp, _now)
        except Exception as e:                     # noqa: BLE001
            log.warning("市場焦點：市場訊號計算失敗（%s），本次不加分", e)
            sig = {}
        if sig:
            log.info("市場焦點：市場訊號 %s", "、".join(sig.values()))
        _rk = dict(secondary=kw2, now=_now, events=_ev, lock_events=_lock)
        _score = lambda h: rank_score(h, keywords, **_rk) + signal_bonus(h["title"], sig)  # noqa: E731
        clusters = cluster_events([h for h in heads if not _excluded(h["title"], exclude)], _score)

        def _why(g):
            """分數明細（v2.2）：哪一項加了幾分，focus_log 一看就知道為什麼排第一。"""
            p = {}
            rank_score(g["lead"], keywords, parts=p, **_rk)
            if signal_bonus(g["lead"]["title"], sig):
                p["訊號"] = SIGNAL_BONUS
            if g["sources"] > 1:
                p["多家"] = float(min(g["sources"] - 1, 3))
            return "、".join(f"{k}{v:+g}" for k, v in p.items())
        flog.update({"signals": sig, "events": _ev, "locks": _lock, "demoted": _demoted,
                     "clusters": [{"score": g["score"], "sources": g["sources"], "why": _why(g),
                                   "titles": [x["title"] for x in g["items"][:3]]} for g in clusters[:8]]})
        if clusters:
            main_c, others = clusters[0], clusters[1:]
            # v2.2：主軸那件事不到 3 則 → 補同主題（標題主角相同）的相關報導，主軸材料最多 4 則
            rel, others = related_items(main_c, others, MAIN_MAX_ITEMS - len(main_c["items"]))
            main_items = main_c["items"][:MAIN_MAX_ITEMS] + rel
            if rel:
                flog["related"] = [x["title"] for x in rel]
                log.info("市場焦點：主軸補 %d 則同主題報導（%s）", len(rel),
                         "；".join(x["title"][:30] for x in rel))
            _body = lambda x: not _headline_only(x["link"])   # noqa: E731
            main_body = [x for x in main_items if _body(x)][:4]
            main_brief = [x for x in main_items if not _body(x)][:4]
            oth_body, oth_brief = [], []
            # 全文總共最多 BODY_SLOTS 篇（同 v1 的 6 篇）：主軸那件事先用，剩下的給其他事件
            _oth_cap = max(BODY_SLOTS - len(main_body), 2)
            for g in others[:10]:
                b = [x for x in g["items"] if _body(x)][:1]
                if b and len(oth_body) < _oth_cap:
                    oth_body += b
                elif len(oth_brief) < 3:
                    oth_brief += [x for x in g["items"] if not _body(x)][:1] or b
            top = main_items[:4] + [g["lead"] for g in others[:3]]
            arts = []
            _ml = {x["link"] for x in main_c["items"]}
            _rl = {x["link"] for x in rel}
            if mode == "content":
                cand = main_body + oth_body
                _bodies = _pmap(lambda x: fetch_article_text(x["link"]), cand)
                arts = [{"title": x["title"], "body": b, "source": x.get("source", ""),
                         "link": x["link"], "at": x.get("at", "")}
                        for x, b in zip(cand, _bodies) if b]
                # 主軸那件事的報導排前面、再來是相關報導；同一組裡彭博、路透優先
                arts.sort(key=lambda a: (a["link"] not in _ml, a["link"] not in _rl, -_src_weight(a)))
                if not any(a["link"] in _ml for a in arts) and not any(x["link"] in _ml for x in main_brief):
                    main_brief = [main_c["lead"]] + main_brief   # 主軸那件事的全文都抓不到：至少放標題
            briefs = main_brief + oth_brief
            _mids = ([i for i, a in enumerate(arts, 1) if a["link"] in _ml]
                     + [j for j, b in enumerate(briefs, len(arts) + 1) if b["link"] in _ml])
            _rids = ([i for i, a in enumerate(arts, 1) if a["link"] in _rl]
                     + [j for j, b in enumerate(briefs, len(arts) + 1) if b["link"] in _rl])
            # 主軸的材料全部只有標題（沒有任何內文）→ 字數下限降到 HEADLINE_ONLY_MIN，寧可短也不要補
            _main_has_body = any(a["link"] in (_ml | _rl) for a in arts)
            _wm = dict(_w)
            if not _main_has_body and mins:
                _wm["mins"] = [min(mins[0], HEADLINE_ONLY_MIN)] + list(mins[1:])
                flog["headline_only"] = True
            # 給 AI 的事件提示：鎖定事件（公布前寫預告）、撞期降級、本次主軸是哪件事（寫明美東日期）
            parts = []
            if _lock:
                _k = _lock[0]
                _d = event_day(_k, _ev_d, cfg, now_tw)
                _nm = EVENT_NAMES.get(_k, _k)
                if released_yet(_k, _ev_d, cfg, now_tw):
                    parts.append(f"{_d}（美東）有{_nm}：材料裡有相關報導時，主軸必須以這件事為核心。")
                else:
                    parts.append(f"{_nm}在 {_d}（美東）公布、目前尚未公布：主軸寫這次公布什麼、"
                                 "市場關注哪些重點；不要寫任何預估值或市場共識數字。")
                if _demoted:
                    parts.append("同時有" + "、".join(EVENT_NAMES.get(d, d) for d in _demoted)
                                 + "，主軸不寫，放在補充。")

            def _focus_note(mids, rids):
                if not mids:
                    return ""
                s = "本次主軸以代號 " + "、".join(map(str, mids)) + " 這件事為核心"
                if rids:
                    s += "，可以引用同主題的代號 " + "、".join(map(str, rids)) + " 補充背景或不同觀點"
                return s + "；補充從其他代號挑，不要重複主軸的事。"
            _ev_note = "".join(parts) + _focus_note(_mids, _rids)
            flog["main"] = main_c["lead"]["title"]
            if mode == "content" and arts:
                log.info("市場焦點：內文擷取 %d 篇＋標題快訊 %d 則（主軸事件 %d 則、%d 家媒體、相關 %d 則）",
                         len(arts), len(briefs), len(main_c["items"]), main_c["sources"], len(rel))
                res, err = write_main(arts, briefs, keywords, env, mode="content", rate_ctx=rate_ctx,
                                      event_note=_ev_note, **_wm)
                if not res:
                    log.warning("市場焦點：內文重點退回標題模式（%s）", err)
            elif mode == "content":
                log.warning("市場焦點：沒有抓到任何內文，直接用標題（含官方摘要）寫重點")
            if not res:
                _tid = [i for i, x in enumerate(top, 1) if x["link"] in _ml]
                _trid = [i for i, x in enumerate(top, 1) if x["link"] in _rl]
                _wt = dict(_w, mins=[min(mins[0], HEADLINE_ONLY_MIN)] + list(mins[1:])) if mins else _w
                res, err = write_main([], top, keywords, env, mode="title", rate_ctx=rate_ctx,
                                      event_note="".join(parts) + _focus_note(_tid, _trid), **_wt)
    elif not weekly:
        log.warning("市場焦點：沒有抓到任何標題")
    if res:
        out["text"], out["text_source"] = res["text"], res["source"]
        out["layout"] = "main"
        out["weekly"] = bool(weekly)
        out["headline"], out["rate_note"] = res["headline"], res["rate"]
        out["links"] = res["links"]
        log.info("市場焦點：產出標題＋主軸＋%d 則%s（%s；來源 %s）",
                 len(res["text"].splitlines()) - 1, "下週重點" if weekly else "補充",
                 "內文" if res["source"] == "model-content" else "標題",
                 "、".join(x.get("source", "") for x in res["links"]))
    elif heads or weekly:
        # 退路：text 留空，首頁攤開標題清單（不串假摘要），下一次執行再試 AI
        log.warning("市場焦點：AI 重點退回列標題（%s）", err)
        out["text"], out["text_source"] = "", "headlines"
        out["headline"], out["rate_note"] = "", ""
        out["links"] = [_link_of(x) for x in top[:3]]
    if res or heads:
        out["main_source_titles"] = [x["title"] for x in out.get("links") or []]
        state.update({"hash": "", "text": out["text"], "links": out["links"],
                      "text_source": out["text_source"],
                      "layout": out.get("layout", ""),
                      "weekly": bool(out.get("weekly")),
                      "headline": out.get("headline", ""),
                      "rate_note": out.get("rate_note", ""),
                      "main_source_titles": out["main_source_titles"],
                      "at": _now.isoformat()})
        if out["text"]:
            rm = [r for r in (state.get("recent_mains") or []) if isinstance(r, dict)]
            rm.append({"headline": out.get("headline", ""),
                       "titles": out["main_source_titles"], "at": _now.isoformat()})
            state["recent_mains"] = rm[-3:]
    flog["result"] = out.get("headline") or ("列標題：" + err if err else "")
    write_focus_log(state_path.parent / "focus_log.json", flog)

    # ---- 主題補充：依讀者選的前兩個指標換主題（主軸暫缺仍獨立產出）----
    out["topics"], out["topic_map"] = [], chip_topic_map(topic_specs(cfg))
    if not offline:
        try:
            _tp = build_topics(cfg, _raw_pool, (out.get("text") or "").split("\n")[0],
                               out.get("main_source_titles") or [],
                               state, env, now=dt.datetime.now(dt.timezone.utc),
                               meta_markers=meta_markers, rate_ctx=rate_ctx)
            out["topics"], out["topic_map"] = _tp["items"], _tp["map"]
        except Exception as e:                     # noqa: BLE001
            log.warning("主題補充失敗（%s），補充維持一般內容", e)

    # 2026-10：每天保留一篇主軸（當天最後一版），連同今天最多 5 天
    state["archive"] = update_archive(state.get("archive"), state)
    out["archive"] = archive_list(state["archive"])
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    except Exception as e:                         # noqa: BLE001
        log.warning("市場焦點狀態寫入失敗（%s）", e)
    # 自選 chip 目錄：任何一顆出錯都不該拖垮整條（目錄失敗退回預設三顆的
    # 舊行為——home 端對空目錄有後備渲染）。
    try:
        out["chips"] = build_catalog(rates_series, liq_series,
                                     out["yields"], offline=False,
                                     fw=out.get("fedwatch"), election=election)
    except Exception as e:                         # noqa: BLE001
        log.warning("chip 目錄組裝失敗（%s），退回預設呈現", e)
        out["chips"] = []
    return out
