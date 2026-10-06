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
# 殖利率：優先 Yahoo 即時報價（±bp 對昨收），失敗退回 FRED（隔日）
# ---------------------------------------------------------------------------
def _yield_chip(rows: list, label: str) -> dict | None:
    rows = [r for r in (rows or []) if r.get("value") is not None]
    if len(rows) < 2:
        return None
    last, prev = rows[-1], rows[-2]
    return {"label": label, "value": last["value"],
            "delta_bp": round((last["value"] - prev["value"]) * 100),
            "date": last.get("date", "")}


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
        r = get(YQ_URL.format(sym=quote(symbol)))
        r.raise_for_status()
        res = (r.json().get("chart") or {}).get("result") or []
        meta = (res[0].get("meta") or {}) if res else {}
        cur = meta.get("regularMarketPrice")
        prev = _yahoo_prev_close(res[0]) if res else None
        ts = meta.get("regularMarketTime")
        if cur is None or prev is None:
            return None
        cur, prev = float(cur), float(prev)
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
                "date": date, "live": True}
    except Exception as e:                         # noqa: BLE001
        log.warning("Yahoo 殖利率 %s 抓取失敗（%s），退回 FRED", symbol, e)
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
        r = get(YQ_URL.format(sym=quote(symbol)))
        r.raise_for_status()
        res = (r.json().get("chart") or {}).get("result") or []
        meta = (res[0].get("meta") or {}) if res else {}
        cur = meta.get("regularMarketPrice")
        prev = _yahoo_prev_close(res[0]) if res else None
        ts = meta.get("regularMarketTime")
        if cur is None or prev is None:
            return None
        cur, prev = float(cur), float(prev)
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
        return {"value": cur, "prev": prev, "date": date, "live": True}
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


def _pct_chip(cid, label, rows):
    """百分比序列（天期利率、SOFR）：值 x.xx%、變動 ±bp 對前一日。"""
    v, p, d = _last2(rows)
    if v is None:
        return _mk(cid, label, "—", "缺資料", "", "")
    db = None if p is None else round((v - p) * 100)
    cls = "up" if (db or 0) > 0 else ("dn" if (db or 0) < 0 else "")
    return _mk(cid, label, f"{v:.2f}%",
               f"{db:+d} bp" if db is not None else "—", cls, d)


def _level_chip(cid, spec, liq, offline, _get=None, _pre=None):
    """即時報價 chip（油價、VIX、MOVE）：Yahoo 主、FRED 後備。
    _pre 是呼叫端並行預抓的結果（避免逐顆串行等逾時）。
    日期新者勝：報價日不比 FRED 後備新（stale 成交）就退後備。"""
    if not offline:
        q = _pre if _pre is not None else fetch_yahoo_quote(
            spec["sym"], spec["lo"], spec["hi"], _get=_get)
        _, _, _fd = _last2((liq or {}).get(spec["fred"])
                           if spec.get("fred") else None)
        if q and _fd and str(q.get("date") or "") <= _fd:
            log.info("即時報價 %s 報價日 %s 不比 FRED %s 新，退後備",
                     spec["sym"], q.get("date"), _fd)
            q = None
        if q:
            dv = q["value"] - q["prev"]
            cls = "up" if dv > 0 else ("dn" if dv < 0 else "")
            if spec.get("fmt") == "index":
                pct = dv / q["prev"] * 100 if q["prev"] else 0.0
                return _mk(cid, spec["label"], f"{q['value']:,.0f}",
                           f"{dv:+,.0f}（{pct:+.2f}%）", cls, q["date"])
            return _mk(cid, spec["label"], f"{q['value']:.1f}{spec['unit']}",
                       f"{dv:+.1f}", cls, q["date"])
    rows = (liq or {}).get(spec["fred"]) if spec.get("fred") else None
    v, p, d = _last2(rows)
    if v is None:
        return _mk(cid, spec["label"], "—", "本次擷取失敗", "", "")
    dv = None if p is None else v - p
    cls = "up" if (dv or 0) > 0 else ("dn" if (dv or 0) < 0 else "")
    return _mk(cid, spec["label"], f"{v:.1f}{spec['unit']}",
               f"{dv:+.1f}" if dv is not None else "—", cls, d)


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
    焦點條的完整 chip 目錄（14 顆）。每顆：id、短標籤、顯示值、
    對前一日收盤的變動、方向色、資料日（月-日）、是否預設顯示。

    fedwatch 是佔位（special）：機率 chip 的分層來源標示已經在
    pages/home.py 有一套完整邏輯，目錄只負責排位置，不重刻一份。
    """
    rs, liq = rates_series or {}, liq_series or {}
    chips: list[dict] = []
    # ---- 天期利率：全部先試 Yahoo 即時，抓不到退 FRED 收盤 ----
    # 10Y／30Y 用已升級的即時 chip（同一次抓取，不重打）；3M／5Y 用
    # CBOE 殖利率指數（^IRX／^FVX，×10 慣例由 fetch_yahoo_yield 規範化）；
    # 2Y 是 Yahoo 唯一沒有指數的天期，改用 CME 微型殖利率期貨 2YY=F
    #（直接報殖利率、與現貨通常差幾個 bp，但流動性偶爾薄）——所以
    # 每檔即時值都過「與 FRED 收盤差逾 0.6 個百分點就不採用」的防呆，
    # 跟 10Y／30Y 的升級規則同一條。
    fresh = {c["label"]: c for c in (fresh_yields or [])}
    _tenors = (("dgs3mo", "DGS3MO", "3 個月", "^IRX"),
               ("dgs2", "DGS2", "2 年期", "2YY=F"),
               ("dgs5", "DGS5", "5 年期", "^FVX"),
               ("dgs10", "DGS10", "10 年期", None),
               ("dgs30", "DGS30", "30 年期", None))
    # 需要補抓的天期一次並行打（跟油價／波動率那批同一個小工具）
    _to_fetch = [(cid, label, sym) for cid, _, label, sym in _tenors
                 if sym and not offline and fresh.get(label) is None]
    _live_t = dict(zip((c for c, _, _ in _to_fetch), _pmap(
        lambda t: fetch_yahoo_yield(t[2], t[1], _get=_get), _to_fetch)))
    for cid, sid, label, live_sym in _tenors:
        fc = fresh.get(label)
        if fc is None and live_sym and not offline:
            fc = _live_t.get(cid)
            fred_last, _, fred_date = _last2(rs.get(sid))
            if (fc and fred_last is not None
                    and abs(fc["value"] - fred_last) > LIVE_JUMP_CAP):
                log.warning("殖利率即時 %s（%s）%.2f 與 FRED 收盤 %.2f 差逾 "
                            "%.2f 個百分點，不採用退收盤", live_sym, label,
                            fc["value"], fred_last, LIVE_JUMP_CAP)
                fc = None
            # 日期新者勝：微型合約（2YY=F）成交稀疏，Yahoo 的「最新價」
            # 可能是六週前的最後一筆成交（實例：2Y 顯示 7/15）——
            # 即時報價必須**晚於** FRED 最後收盤日才有資格上場，
            # 否則收盤反而比較新。跟 10Y/30Y 升級層同一條規則。
            if (fc and fred_date
                    and str(fc.get("date") or "") <= fred_date):
                log.info("殖利率即時 %s（%s）報價日 %s 不比 FRED 收盤 %s 新"
                         "（合約成交稀疏），退回收盤", live_sym, label,
                         fc.get("date"), fred_date)
                fc = None
        if fc:
            db = fc.get("delta_bp")
            cls = "up" if (db or 0) > 0 else ("dn" if (db or 0) < 0 else "")
            chips.append(_mk(cid, label, f"{fc['value']:.2f}%",
                             f"{db:+d} bp" if db is not None else "—",
                             cls, fc.get("date") or ""))
        else:
            chips.append(_pct_chip(cid, label, rs.get(sid)))
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
        chips.append(_mk("sofr_iorb", "SOFR−IORB", f"{spread:+.0f} bp",
                         d_disp, cls, sd))
    else:
        chips.append(_mk("sofr_iorb", "SOFR−IORB", "—", "缺資料", "", ""))
    # ON RRP：FRED 單位是十億美元 → 顯示成億美元（×10）。
    v, p, d = _last2(liq.get("RRPONTSYD"))
    if v is not None:
        dv = None if p is None else (v - p) * 10
        cls = "up" if (dv or 0) > 0 else ("dn" if (dv or 0) < 0 else "")
        chips.append(_mk("onrrp", "ON RRP", f"{v * 10:,.0f} 億美元",
                         f"{dv:+,.0f} 億" if dv is not None else "—", cls, d))
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
    _qids = ("wti", "brent", "vix", "move", "dji", "sox")
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


# 內文注定抓不到的網域：Google News 是 JS 轉址中介頁（沒有 <p> 正文，
# 抓一百次都是 0 段）、FT／WSJ 是付費牆。這些來源走「標題快訊」層——
# 標題＋RSS 官方摘要直接進材料包，不佔內文名額、不浪費抓取時間。
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
    「Fed」「fed」「FED」都要算）；中文照原樣子字串比對。"""
    if word.isascii():
        return word.lower() in title.lower()
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
    words = [w for kw in keywords for w in str(kw).split() if w]
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    out, seen = [], set()
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
                                        for w in words):
                continue
            if _excluded(title, exclude):
                continue
            key = re.sub(r"\s+", "", _norm_title(title))[:40]
            if key in seen:
                continue
            seen.add(key)
            n_hit += 1
            out.append(rec)
        log.info("市場焦點：feed %s 取得 %d 則、入選 %d 則", label, n_all, n_hit)
    out.sort(key=lambda x: x["at"], reverse=True)
    return out

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
    # 先砍 script/style 再抽 <p>：Yahoo 頁面的 JSON 資料塊裡也有長字串，
    # 不砍會把程式碼當成內文。
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", page,
                  flags=re.S | re.I)
    paras = []
    for m in re.finditer(r"<p[^>]*>(.*?)</p>", page, re.S | re.I):
        t = _html.unescape(re.sub(r"<[^>]+>", "", m.group(1)))
        t = re.sub(r"\s+", " ", t).strip()
        if len(t) >= 20:                           # 導覽、版權列都比這短
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


# 版式 A 的內文模式。主軸優先寫彭博／路透的事件：它們多半只有標題（付費牆），
# 但 Yahoo 等來源常轉載同一則通訊社稿的全文——同一件事的細節從那裡補。
_FOCUS_CONTENT_SYSTEM_A = (
    "你是財經記者。輸入是幾篇新聞的標題與內文節錄（可能中英文混合），"
    "後面可能另有一節「標題快訊」——那些只有標題與官方摘要、沒有內文；"
    "標【Bloomberg】【Reuters】的是彭博與路透。只取與這些主題相關的內容："
    "{kws}。讀完全部材料後依下面的格式輸出。\n"
    "【主軸】{min}–{main} 個中文字，可以分 2–3 段（每段一行）。挑今天最重要、"
    "彼此相關的三則報導（優先彭博、路透；同一件事的多篇報導合併），綜合成一篇"
    "完整的論述，依序講清楚：①發生了什麼（誰、做了什麼、數字）②為什麼（背景"
    "與原因）③對利率或聯準會代表什麼（只寫材料裡官員、分析師或市場講過的"
    "解讀）。不要三則各講一句拼起來，要講成一個有因果脈絡的故事。\n"
    "【補充】{ns} 行，每行一件**主軸以外**的其他事件、{supp} 個中文字以內。"
    "不能只重述標題：每行都要寫出發生了什麼，再加一個具體細節（數字、時間、"
    "誰說的或原因）。補充也必須直接跟上述主題有關，只是文中順帶提到某個詞的"
    "不算。不要寫「成為市場焦點」「備受關注」這類空泛的話。硬性規則："
    "只能使用材料已有的資訊，不得補充材料以外的事實或數字；「標題快訊」只能"
    "轉述其標題與摘要**字面上有的事**，不得展開細節、不得推測其內文，引用時"
    "帶來源（例如「路透報導稱…」）；不得自行推論來源沒有寫的因果關係；不做"
    "預測、不下投資結論；繁體中文。**絕對禁止評論材料本身**：不要說明材料的"
    "多寡、品質或相關性，不要出現「材料」「關鍵字」這類字眼——補充只夠寫一則"
    "就只寫一則。輸出格式：第一行單獨寫「【主軸】」，接著主軸的各段（每段"
    "一行）；然後單獨一行寫「【補充】」，接著每則補充一行。不要編號、不要"
    "符號開頭、不要粗體記號、不要任何前言。")


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


def _call_ai(src_text: str, system: str, env=None) -> tuple[str, str]:
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
        try:
            out = _post_anthropic(a_key, PROVIDERS["anthropic"]["model"],
                                  src_text, system=system, temperature=0.3)
            log.info("市場焦點：Anthropic（%s）產出",
                     PROVIDERS["anthropic"]["model"])
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
FOCUS_PROMPT_VERSION = "f6-main3"

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


def summarize_content(articles: list[dict], keywords: list[str],
                      item_cap: int = DEFAULT_ITEM_CHARS, env=None,
                      briefs: list[dict] | None = None,
                      meta_markers=None, n_items: int = DEFAULT_ITEMS,
                      vague_markers=None, caps: list[int] | None = None,
                      mins: list[int] | None = None
                      ) -> tuple[str, str]:
    """
    讀文章內文寫成重點。caps 有給＝版式 A（一段主軸＋補充），否則 N 則等長。回傳 (重點, "model-content")；失敗回 ("", 原因)。

    briefs 是「標題快訊」層：付費牆來源（路透、彭博、FT、WSJ）的標題＋
    RSS 官方摘要。它們進材料包供模型織進重點，但提示詞硬性規定只能
    轉述字面——標題只有十幾個字，模型對著標題腦補是這一層最大的風險。
    數字鎖的驗證範圍涵蓋「全文＋快訊」的合併文字。
    """
    if not articles and not briefs:
        return "", "沒有任何材料"
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
    if caps:
        _mins = list(mins) if mins else [DEFAULT_MAIN_MIN]
        system = _FOCUS_CONTENT_SYSTEM_A.format(
            kws="、".join(keywords), main=caps[0], supp=caps[1] if len(caps) > 1 else 0,
            ns=len(caps) - 1, min=_mins[0])
    else:
        system = _FOCUS_CONTENT_SYSTEM.format(kws="、".join(keywords),
                                              cap=item_cap, n=n_items)
    text, err = _generate_items(src_text, system, env, item_cap=item_cap,
                                n_items=n_items, meta_markers=meta_markers,
                                vague_markers=vague_markers, caps=caps,
                                mins=mins)
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


# 來源權重：通訊社與財經專業媒體、官方發布 > 一般入口轉載。
# 比對的是 feed 標籤（_feed_label）與 Google News 標題尾巴的媒體名。
# 彭博、路透優先（2026-10 使用者指定）：權重 3，比其他專業媒體高一倍，
# 相同主題、相同時效時一定排在前面。
SOURCE_WEIGHT = (("reuters", 3.0), ("bloomberg", 3.0), ("wall street", 1.5),
                 ("financial times", 1.5), ("cnbc", 1.5),
                 ("federal reserve", 1.5), ("yahoo finance", 0.5))

# 發布日加分：當天（或前一天，台灣早上那次對應美國前一天）有這類
# 發布時，標題提到它的新聞加分——FOMC、CPI、非農當天，大家看的就是那件事。
EVENT_WORDS = {
    "fomc": ("FOMC", "聯準會", "Fed", "Powell", "利率決策", "rate decision"),
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
}


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
    return [w for kw in (kws or []) for w in str(kw).split() if w]


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


def rank_score(h: dict, keywords, secondary=None, *, heat=None, now=None,
               events=None) -> float:
    """
    一則標題的重要性分數，全部確定性規則（看得到、測得到）：
      主題    主級關鍵字一次 2 分、次級 1 分
      熱度    同一個主題詞被 N 家不同來源報導 → 加 min(N−1, 3) 分
      時效    12 小時內 +2、24 小時內 +1.5、48 小時內 +0.5
      來源    彭博、路透 +3；其他財經專業媒體、官方發布 +1.5；Yahoo Finance +0.5
      發布日  當天有 FOMC／CPI／非農等發布、標題又提到它 → +2
    """
    t = _kw_text(h.get("title") or "")
    p_words, s_words = _kw_words(keywords), _kw_words(secondary)
    hit_p = [w for w in p_words if _kw_hit(w, t)]
    hit_s = [w for w in s_words if _kw_hit(w, t)]
    score = 2.0 * len(hit_p) + 1.0 * len(hit_s)
    if heat:
        n = max([heat.get(w, 0) for w in hit_p + hit_s] or [0])
        score += min(max(n - 1, 0), 3)
    if now is not None:
        age = _age_hours(h, now)
        if age is not None:
            score += (2.0 if age <= 12 else 1.5 if age <= 24
                      else 0.5 if age <= 48 else 0.0)
    score += _src_weight(h)
    for kind in (events or ()):
        if any(_kw_hit(w, t) for w in EVENT_WORDS.get(kind, ())):
            score += 2.0
            break
    return score


def pick_fallback(headlines: list[dict], keywords: list[str],
                  n: int = 3, exclude: list[str] | None = None,
                  secondary: list[str] | None = None, *,
                  pool: list[dict] | None = None, now=None,
                  events=None) -> list[dict]:
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
                                             events=events))
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
_FOCUS_SYSTEM_A = (
    "你是財經編輯。輸入是新聞標題清單（有些附官方摘要），標【Bloomberg】"
    "【Reuters】的是彭博與路透。挑出對「美國公債殖利率與聯準會政策」最重要"
    "的事，輸出：【主軸】{main} 個中文字以內，可分 2–3 段（每段一行），把"
    "今天最重要、彼此相關的幾則標題綜合起來講——發生什麼、為什麼、對利率或"
    "聯準會代表什麼（只寫標題與摘要裡有的）；優先選彭博或路透報導的事件，"
    "同一件事有多則標題時合併來寫。【補充】{ns} 行，每行一件主軸以外的事、"
    "{supp} 個中文字以內，要寫出發生了什麼，不要只重述標題。不要空話。只能"
    "使用標題與摘要裡已有的資訊，不得補充以外的事實或數字；不做預測、不下"
    "投資結論；繁體中文。補充只夠寫一則就只寫一則。輸出格式：第一行單獨寫"
    "「【主軸】」，接著主軸各段（每段一行）；然後單獨一行寫「【補充】」，"
    "接著每則補充一行。不要編號、不要符號開頭、不要任何前言。")


def _digits_ok(text: str, source: str) -> bool:
    """輸出裡的每一串數字都必須出現在來源標題裡（防 AI 編數字）。"""
    src = re.sub(r"[\s,，]", "", source)
    for num in re.findall(r"\d+(?:\.\d+)?", text.replace(",", "")):
        if num not in src:
            return False
    return True


def summarize(headlines: list[dict], item_cap: int = DEFAULT_ITEM_CHARS,
              env=None, n_items: int = DEFAULT_ITEMS, meta_markers=None,
              vague_markers=None, caps: list[int] | None = None,
              mins: list[int] | None = None
              ) -> tuple[str, str]:
    """標題模式：只有標題（＋官方摘要）可用時寫成 N 則重點。
    回傳 (重點, "model")；失敗回 ("", 原因)。"""
    lines = "\n".join(
        f"- [{h.get('source') or '—'}] {h['title']}"
        + (f"——{h['summary']}" if h.get("summary") else "")
        for h in headlines[:24])
    system = (_FOCUS_SYSTEM_A.format(main=caps[0],
                                     supp=caps[1] if len(caps) > 1 else 0,
                                     ns=len(caps) - 1)
              if caps else _FOCUS_SYSTEM.format(cap=item_cap, n=n_items))
    text, err = _generate_items(
        lines, system, env,
        item_cap=item_cap, n_items=n_items, meta_markers=meta_markers,
        vague_markers=vague_markers, caps=caps)
    return (text, "model") if text else ("", err)


# ---------------------------------------------------------------------------
# FedWatch 第一層：聯邦基金期貨自算（FedWatch／WIRP 的同款方法）
# ---------------------------------------------------------------------------
YQ_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
          "?range=5d&interval=1d")
# 預設目標會議（config 的 fedwatch_meeting 蓋掉它；一年更新一次）
DEFAULT_MEETING = "2026-12-09"

# FedWatch 的算法版本。state 的當日快取只在版本一致時沿用——
# 修了算法之後當天的下一次執行就重算，不必等到隔天。
# 1＝單合約 vs FRED 中點；2＝雙合約價差＋品質閘門；
# 3＝2 ＋遠月停滯偵測＋Atlanta 交叉檢核；
# 4＝WIRP 逐會議法（日曆日加權、不封頂、正負＝升降息）
# 6＝回傳值多帶逐場 meetings（聯準會頁用），算法同 5
FW_METHOD = 6


def _last_value(rows) -> float | None:
    rows = [r for r in (rows or []) if r.get("value") is not None]
    return rows[-1]["value"] if rows else None


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
    get = _get or (lambda url: requests.get(
        url, timeout=TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0 (macro-dashboard)"}))
    try:
        r = get(YQ_URL.format(sym=quote(symbol)))
        r.raise_for_status()
        res = (r.json().get("chart") or {}).get("result") or []
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
    horizon = str(cfg.get("fedwatch_meeting") or DEFAULT_MEETING)
    if horizon < today.isoformat():
        later = [d for d in fomc if d >= today.isoformat()]
        if not later:
            log.warning("FedWatch 前推：config 沒有今天之後的 FOMC 日期，"
                        "請在 config/focus.yaml 補上明年的會議日")
            return None
        horizon = later[-1]
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
            log.warning("FedWatch 前推：%s 合約報價不可用，整批不採用",
                        _zq_symbol(m))
            return None
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
    for m in path["meetings"]:
        log.info("FedWatch 前推：%s 會議 Start %.4f → End %.4f，隱含 %+.2f bp"
                 "（%s）", m["date"], m["start"], m["end"], m["move_bp"],
                 m["how"])
    log.info("FedWatch 前推：起點 %.4f%%（%s）；至 %s 累計 %+.2f bp",
             path["r0"], path["r0_src"], horizon, path["cum_bp"])
    return {"src": "futures", "date": today.isoformat(),
            # 逐場全列：聯準會頁的「市場路徑 vs 點陣圖」要每一場的會後利率
            "meetings": path["meetings"],
            "next": path["meetings"][0], "horizon": path["meetings"][-1],
            "cum_bp": path["cum_bp"], "r0": path["r0"],
            "r0_src": path["r0_src"],
            "prev": ({"next": prev["meetings"][0],
                      "horizon": prev["meetings"][-1],
                      "cum_bp": prev["cum_bp"]} if prev else None)}


def futures_curve(rates_series: dict | None, months: int = 13, _get=None,
                  today: dt.date | None = None) -> dict | None:
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
    ms, mo = [], today.isoformat()[:7]
    for _ in range(months):
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


def fw_chips(fw: dict | None) -> list[dict]:
    """
    三顆升降息 chip（給目錄用的一般 chip 格式）：
      fedwatch  下次會議：機率最高的兩個結果（單場推算只會切成相鄰兩種，
                第三種在這個方法下是 0%，不硬湊）
      fw_dec    目標會議（12 月）單場的隱含幅度
      fw_cum    從現在到目標會議（含）的累計隱含幅度
    """
    def _md(d):
        return f"{int(d[5:7])}/{int(d[8:10])}"

    if not fw or not fw.get("next"):
        return [_mk("fedwatch", "下次 FOMC 機率", "—", "本次擷取失敗", "", ""),
                _mk("fw_dec", "目標會議單場幅度", "—", "本次擷取失敗", "", ""),
                _mk("fw_cum", "累計升降息幅度", "—", "本次擷取失敗", "", "")]
    nxt, hz, prev = fw["next"], fw["horizon"], fw.get("prev") or {}
    when = (f"沿用 {fw['stale_from'][5:]}" if fw.get("stale_from")
            else str(fw.get("date") or ""))
    nm, hm = int(nxt["date"][5:7]), int(hz["date"][5:7])
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

    dec_txt, dec_cls = _amt(hz["move_bp"], (prev.get("horizon") or {}).get(
        "move_bp"))
    cum_txt, cum_cls = _amt(fw["cum_bp"], prev.get("cum_bp"))
    return [
        _mk("fedwatch", f"{nm} 月 FOMC（{_md(nxt['date'])}）", top, second,
            d_cls, when, on=True),
        _mk("fw_dec", f"{hm} 月 FOMC 單場幅度", f"{hz['move_bp']:+.1f} bp",
            dec_txt, dec_cls, when),
        _mk("fw_cum", f"至 {hm} 月 FOMC 累計", f"{fw['cum_bp']:+.1f} bp",
            cum_txt, cum_cls, when),
    ]


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
TOPIC_PROMPT_VERSION = "t1"
TOPIC_CHARS, TOPIC_MIN = 80, 40
TOPIC_HARD = int(TOPIC_CHARS * HARD_MULT_SUPP)          # 100 字

DEFAULT_TOPICS = [
    {"id": "fed", "label": "聯準會",
     "chips": ["fedwatch", "fw_dec", "fw_cum", "dgs3mo", "dgs2"],
     "keywords": ["Fed", "FOMC", "Powell", "Warsh", "聯準會", "降息", "升息",
                  "rate cut", "rate hike"]},
    {"id": "long", "label": "長天期美債",
     "chips": ["dgs5", "dgs10", "dgs30", "move"],
     "keywords": ["Treasury", "yields", "bond market", "美債", "殖利率", "公債標售"]},
    {"id": "funding", "label": "資金市場",
     "chips": ["sofr", "sofr_iorb", "onrrp", "srf"],
     "keywords": ["repo", "SOFR", "reserves", "money market", "回購", "準備金"]},
    {"id": "oil", "label": "油價", "chips": ["wti", "brent"],
     "keywords": ["oil", "crude", "OPEC", "Brent", "油價", "原油"]},
    # AI 消息同時推動美股、台股與半導體：三個主題都收 AI 關鍵字（2026-10）
    {"id": "equity", "label": "美股", "chips": ["dji", "vix"],
     "keywords": ["Dow", "S&P 500", "Wall Street", "stocks", "美股", "道瓊", "標普",
                  "AI", "Nvidia", "OpenAI", "data center", "人工智慧", "輝達"]},
    {"id": "semi", "label": "AI 與半導體", "chips": ["sox"],
     "keywords": ["chip", "semiconductor", "Nvidia", "TSMC", "半導體", "晶片",
                  "輝達", "台積電", "AI", "OpenAI", "data center", "人工智慧", "資料中心"]},
    {"id": "twf", "label": "台指期", "chips": ["txf"],
     "keywords": ["台指期", "台股", "加權指數", "外資", "夜盤", "人工智慧", "輝達",
                  "台積電", "AI 伺服器"],
     "exclude": ["ETF", "存股", "高股息", "定期定額", "0050"]},
    {"id": "election", "label": "期中選舉", "chips": ["pm_house", "pm_senate"],
     "keywords": ["midterm", "Senate race", "House majority", "期中選舉",
                  "參議院", "眾議院"]},
]

_GNEWS = {"en": "https://news.google.com/rss/search?q={q}%20when:2d"
                "&hl=en-US&gl=US&ceid=US:en",
          "zh": "https://news.google.com/rss/search?q={q}%20when:2d"
                "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"}


def topic_specs(cfg: dict | None) -> list[dict]:
    """config 的 topics:（沒設就用內建的八個主題），正規化成固定欄位。"""
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
        的 Google News 搜尋 feed（只有標題與摘要，同樣用詞組篩）
      · 跟主軸來源標題太像的（同一件事）先剔掉——補充不重複主軸
      · 有內文的取前 2 篇抓正文；只有標題的取前 3 則當「標題快訊」
    """
    fetch = _fetch or fetch_feed_headlines
    body = _body or fetch_article_text
    mains = [_norm_title(x) for x in main_titles if x]
    picked: dict = {}
    for s in specs:
        exc = s["exclude"] if s["exclude"] is not None else (global_exclude or [])
        extra = []
        if s["search"]:
            try:
                extra = fetch([{"url": _topic_url(x), "all": True}
                               for x in s["search"]], [], hours=36, exclude=exc)
            except Exception as e:                 # noqa: BLE001
                log.warning("主題補充：%s 的搜尋 feed 失敗（%s）", s["id"], e)
        seen, cand = set(), []
        for h, _srch in ([(x, False) for x in pool]
                         + [(x, True) for x in (extra or [])]):
            title = h.get("title") or ""
            k = _norm_title(title)[:40]
            if (k in seen or _excluded(title, exc)
                    or not any(_phrase_hit(w, title) for w in s["keywords"])
                    or any(_sim(_norm_title(title), m) > 0.55 for m in mains)):
                continue
            seen.add(k)
            h = dict(h)
            # Google News 搜尋的項目：真正的來源在標題尾巴「 - Reuters」
            if _srch or not h.get("source") or "news.google" in h.get("source", ""):
                m_ = re.search(r"\s[-–—]\s([^-–—]{2,40})$", title)
                h["source"] = (m_.group(1).replace(".com", "").strip()
                               if m_ else "Google News")
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
        arts = [{"title": h["title"], "body": b, "source": h.get("source", "")}
                for (t2, h), b in zip(jobs, bodies) if t2 == tid and b]
        if not arts and not m["briefs"]:
            continue
        out[tid] = {"arts": arts, "briefs": m["briefs"],
                    "links": [{"title": re.sub(r"\s*[-–—|]\s*[^-–—|]{1,30}$", "",
                                               x["title"]).strip() or x["title"],
                               "link": x["link"], "source": x.get("source", "")}
                              for x in m["links"]]}
    return out


_TOPIC_SYSTEM = (
    "你是財經記者。輸入的最前面是今天首頁「主軸」已經寫過的內容，後面分成幾個"
    "主題區塊（=== 代號｜主題 ===），每個區塊是該主題的新聞標題、摘要與內文"
    "節錄（可能中英文混合）。為每個區塊寫一則重點，{min}–{cap} 個中文字："
    "寫出發生了什麼，再加一個具體細節（數字、時間、誰說的或原因）；材料裡有人"
    "講到時，點出它對利率、聯準會或市場的意義。不能只重述標題。不要跟主軸講"
    "同一件事——區塊裡若都是主軸那件事，就寫同一主題下的另一件事；真的沒有"
    "別的事就輸出「代號｜略」。硬性規則：只能使用該區塊材料裡的資訊，不得補充"
    "材料以外的事實或數字；只有標題的新聞只能轉述標題與摘要字面上的事，引用時"
    "帶來源（例如「路透報導稱…」）；不得自行推論來源沒有寫的因果關係；不做"
    "預測、不下投資結論；繁體中文；不要評論材料本身，不要出現「材料」「區塊」"
    "這類字眼。輸出格式：每個主題一行，「代號｜內容」，例如「oil｜…」，"
    "不要其他文字、不要編號、不要粗體記號。")

_TOPIC_LINE = re.compile(r"^\s*[-*・•]?\s*([a-z][a-z0-9_]*)\s*[｜|:：]\s*(.+?)\s*$")


def _topic_block(tid: str, label: str, m: dict) -> str:
    parts = [f"=== {tid}｜{label} ==="]
    for a in m["arts"]:
        parts.append(f"【{a.get('source') or '—'}】{a['title']}\n{a['body']}")
    for b in m["briefs"]:
        parts.append(f"【{b.get('source') or '—'}】{b['title']}（只有標題）"
                     + (f"——{b['summary']}" if b.get("summary") else ""))
    return "\n".join(parts)


def _parse_topic_lines(text: str) -> dict:
    out = {}
    for ln in _tidy_focus(text).splitlines():
        m = _TOPIC_LINE.match(ln)
        if m and m.group(1) not in out:
            out[m.group(1)] = m.group(2).strip()
    return out


def summarize_topics(material: dict, labels: dict, main_text: str, env=None,
                     meta_markers=None) -> dict:
    """
    一次 AI 呼叫寫完所有主題；逐則驗證（後設字眼、數字鎖對該主題自己的
    材料、長度）。有問題的主題帶原因**只重寫那幾個**一次；仍不合格就不顯示
    那個主題（前端自動遞補）。回傳 {tid: 文字}。
    """
    if not material:
        return {}
    system = _TOPIC_SYSTEM.format(min=TOPIC_MIN, cap=TOPIC_CHARS)
    head = "=== 今日主軸（不要重複）===\n" + (main_text or "").replace(MAIN_PARA, "\n")
    srcs = {tid: _topic_block(tid, labels.get(tid, tid), m)
            for tid, m in material.items()}
    good: dict = {}
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
            s = (got.get(tid) or "").strip()
            if not s or s in ("略", "無", "—"):
                continue                           # 沒有別的事：這個主題不顯示
            if _meta_hits(s, meta_markers):
                bad[tid] = "在評論材料而不是寫新聞"
            elif not _digits_ok(s, srcs[tid]):
                bad[tid] = "出現該主題材料裡沒有的數字"
            elif cjk_len(s) < int(TOPIC_MIN * SHORT_TOL) and attempt == 1:
                bad[tid] = (f"只有 {cjk_len(s)} 字，像在列標題（要寫出發生了什麼"
                            "再加一個具體細節）")
            else:
                good[tid] = _trim_to(s, TOPIC_HARD)
        if not bad or attempt == 2:
            if bad:
                log.warning("主題補充：重寫後仍不合格，不顯示 %s", "、".join(bad))
            break
        log.warning("主題補充：%s，帶原因重寫一次",
                    "；".join(f"{k} {v}" for k, v in bad.items()))
        todo = list(bad)
        note = ("\n\n（上一次這幾個主題被退回："
                + "；".join(f"{k}：{v}" for k, v in bad.items())
                + f"。請只重寫這幾個主題，每則 {TOPIC_MIN}–{TOPIC_CHARS} 字。）")
    log.info("主題補充：產出 %d 個主題（%s）", len(good), "、".join(good))
    return good


def build_topics(cfg: dict | None, pool: list[dict], main_text: str,
                 main_titles, state: dict, env=None, now=None,
                 meta_markers=None) -> dict:
    """
    主題補充的整條流程（含快取）：回傳 {"items": [...], "map": {chip: tid}}。
    快取鍵＝提示詞版本＋主軸＋各主題入選標題；12 小時內相同就沿用。
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
    key = hashlib.sha256((TOPIC_PROMPT_VERSION + "|" + (main_text or "") + "|" + "|".join(
        f"{tid}:" + ",".join(x["title"] for x in m["links"] + m["briefs"])
        for tid, m in sorted(mat.items()))).encode("utf-8")).hexdigest()[:16]
    old = state.get("topics") or {}
    _age = _age_hours({"at": old.get("at")}, now or dt.datetime.now(dt.timezone.utc))
    if old.get("hash") == key and old.get("items") and _age is not None \
            and _age < CACHE_TTL_HOURS:
        log.info("主題補充：材料與上次相同，沿用 %.1f 小時前的內容", _age)
        res["items"] = old["items"]
        return res
    texts = summarize_topics(mat, labels, main_text, env, meta_markers)
    res["items"] = [{"id": tid, "label": labels[tid], "text": texts[tid],
                     "links": mat[tid]["links"]}
                    for tid in res["order"] if tid in texts]
    if res["items"]:
        state["topics"] = {"hash": key, "items": res["items"],
                           "at": (now or dt.datetime.now(dt.timezone.utc)).isoformat()}
    return res


def _todays_events(events: dict | None, cfg: dict | None,
                   today: dt.date) -> list[str]:
    """
    今天（或前一天）有哪些發布事件。前一天也算：台灣早上 07:00 那次
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


def build(rates_series: dict | None, offline: bool, cfg: dict | None,
          state_path: Path, env=None, liq_series: dict | None = None,
          events: dict | None = None, election: dict | None = None) -> dict:
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
        out["text"] = ("離線示範模式：不抓取新聞，正式執行時這裡是"
                       "當天的市場焦點一段。")
        out["text_source"] = "offline"
        out["chips"] = build_catalog(rates_series, liq_series, yields,
                                     offline=True, election=election)
        out["topic_map"] = chip_topic_map(topic_specs(cfg))
        return out

    # ---- 殖利率即時 chip：優先重用長端模組已升級的序列（帶 live 標記
    # 的最後一列），同一次執行不再重打 Yahoo；沒升級到的才逐檔補抓，
    # 抓不到退回 FRED 收盤。補抓的兩檔並行。 ----
    _fred = {"10 年期": (rates_series or {}).get("DGS10"),
             "30 年期": (rates_series or {}).get("DGS30")}
    _sym_of = dict((lb, sym) for sym, lb in YIELD_SYMBOLS)
    _reused = {lb: _chip_from_live_rows(_fred.get(lb), lb)
               for _, lb in YIELD_SYMBOLS}
    _need = [lb for _, lb in YIELD_SYMBOLS if not _reused.get(lb)]
    _fetched = dict(zip(_need, _pmap(
        lambda lb: fetch_yahoo_yield(_sym_of[lb], lb), _need)))
    _fresh = []
    for _, _label in YIELD_SYMBOLS:
        c = (_reused.get(_label) or _fetched.get(_label)
             or _yield_chip(_fred.get(_label), _label))
        if c:
            _fresh.append(c)
    if _fresh:
        out["yields"] = _fresh
        out["asof"] = _fresh[0].get("date", "")

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

    # ---- 焦點段（三層）：Yahoo RSS＋內文摘要 → Google News 標題摘要 →
    #      列標題。同一批文章只呼叫一次 AI（雜湊快取）。 ----
    feeds = cfg.get("feeds") or DEFAULT_FEEDS
    exclude = cfg.get("exclude_keywords") or []
    kw2 = [str(k) for k in (cfg.get("keywords_secondary") or []) if k]
    meta_markers = ([str(m) for m in cfg.get("meta_markers") if m]
                    if cfg.get("meta_markers") else None)
    vague_markers = ([str(m) for m in cfg.get("vague_markers") if m]
                     if cfg.get("vague_markers") else None)
    # feed 過濾要認得兩級關鍵字（次級只是排序權重低，不是不收）
    _raw_pool: list = []                           # 主題補充用：時間窗內全部項目
    heads = fetch_feed_headlines(feeds, keywords + kw2, exclude=exclude,
                                 raw_out=_raw_pool)
    mode = "content"
    if not heads:
        log.warning("市場焦點：Yahoo RSS 無命中或全部失敗，退回 Google News 標題模式")
        heads = fetch_headlines(keywords)
        # 來源白名單（config 的 sources）只在標題模式有意義——
        # Yahoo feed 本身就只有 Yahoo。全部沒命中時退回不過濾。
        _srcs = [str(s).lower() for s in (cfg.get("sources") or []) if s]
        if heads and _srcs:
            _hits = [h for h in heads
                     if any(w in (h.get("source") or "").lower() for w in _srcs)]
            if _hits:
                heads = _hits
            else:
                log.warning("市場焦點：來源白名單 %s 沒命中任何標題，退回全部來源",
                            _srcs)
        mode = "title"
    if heads:
        _now = dt.datetime.now(dt.timezone.utc)
        _ev = _todays_events(events, cfg, clock.today())
        if _ev:
            log.info("市場焦點：今天的發布事件 %s，相關新聞排序加分",
                     "、".join(_ev))
        _rk = dict(exclude=exclude, secondary=kw2, pool=heads, now=_now,
                   events=_ev)
        top = pick_fallback(heads, keywords, n=6, **_rk)
        # 兩層材料：內文名額只給抓得到正文的來源（Google News 是 JS
        # 轉址中介頁、FT／WSJ 是付費牆——先前佔掉名額又必然 0 段）；
        # 付費牆來源改走「標題快訊」層：標題＋RSS 官方摘要直接進材料包。
        body_cand = pick_fallback([x for x in heads
                                   if not _headline_only(x["link"])],
                                  keywords, n=6, **_rk)
        # 標題快訊名額 6：彭博、路透多半只有標題，名額太少會被擠掉，
        # 而主軸要優先寫它們報導的事件
        briefs = pick_fallback([x for x in heads
                                if _headline_only(x["link"])],
                               keywords, n=6, **_rk)
        h = hashlib.sha256((FOCUS_PROMPT_VERSION + "|" + mode + "|" + "|".join(
            x["title"] for x in (top + body_cand + briefs)))
                           .encode("utf-8")).hexdigest()[:16]
        _age = _age_hours({"at": state.get("at")}, _now)
        _fresh = _age is not None and _age < CACHE_TTL_HOURS
        if state.get("hash") == h and state.get("text") and _fresh:
            out["text"] = state["text"]
            out["text_source"] = "cache"
            out["cached_mode"] = ("content"
                                  if state.get("text_source") == "model-content"
                                  else "title")
            out["links"] = state.get("links") or []
            out["layout"] = state.get("layout", "")
            # 快取命中要出聲：先前這條路徑一行 log 都不印，整個新聞區在
            # Actions log 上完全隱形，看起來就像「完全沒有跑」。
            log.info("市場焦點：入選標題與上次相同，沿用 %.1f 小時前的內容"
                     "（%s；超過 %d 小時會強制重新生成）", _age,
                     "內文重點" if out["cached_mode"] == "content"
                     else "標題重點", CACHE_TTL_HOURS)
        else:
            if state.get("hash") == h and state.get("text"):
                log.info("市場焦點：入選標題沒變，但內容已超過 %d 小時，"
                         "重新生成", CACHE_TTL_HOURS)
            text, src = "", ""
            _gen = dict(n_items=n_items, meta_markers=meta_markers,
                        vague_markers=vague_markers, caps=caps)
            if mode == "content":
                # 內文並行抓（各篇獨立的 I/O 等待，串行是慢的主因之一）
                _bodies = _pmap(lambda x: fetch_article_text(x["link"]),
                                body_cand)
                arts = [{"title": x["title"], "body": b,
                         "source": x.get("source", "")}
                        for x, b in zip(body_cand, _bodies) if b]
                if len(arts) < 3:
                    # 材料太薄不放棄：第二輪把時間窗放寬到 60 小時、
                    # 候選從排名往後遞補再抓一批（使用者指定：先繼續爬，
                    # 第二輪還是不夠才「寫僅有的訊息」）。
                    log.info("市場焦點：內文只有 %d 篇，第二輪擴大"
                             "時間窗（60 小時）再爬", len(arts))
                    heads2 = fetch_feed_headlines(feeds, keywords + kw2,
                                                  hours=60, exclude=exclude)
                    _got = {x["link"] for x in body_cand}
                    cand2 = [x for x in pick_fallback(
                        [h2 for h2 in heads2
                         if not _headline_only(h2["link"])],
                        keywords, n=12, **{**_rk, "pool": heads2})
                        if x["link"] not in _got][:6]
                    _b2 = _pmap(lambda x: fetch_article_text(x["link"]),
                                cand2)
                    arts += [{"title": x["title"], "body": b,
                              "source": x.get("source", "")}
                             for x, b in zip(cand2, _b2) if b]
                if arts:
                    # 抓到多少內文寫進 log：摘要品質有疑慮時要能回頭查
                    # 是不是內文本身太薄。
                    log.info("市場焦點：內文擷取 %d 篇＋標題快訊 %d 則"
                             "（%s）", len(arts), len(briefs),
                             "、".join(f"{a['title'][:12]}…{len(a['body'])}字"
                                       for a in arts))
                    text, src = summarize_content(arts, keywords, item_cap,
                                                  env, briefs=briefs, mins=mins,
                                                  **_gen)
                    if not text:
                        log.warning("市場焦點：內文重點退回標題模式（%s）", src)
                else:
                    # 一篇內文都沒有：直接走標題模式。先前仍會硬試「內文
                    # 重點」，只剩快訊時模型最容易開始評論材料、被後設
                    # 偵測退回，白花一到兩次 API 呼叫。
                    log.warning("市場焦點：沒有抓到任何內文，直接用標題"
                                "（含官方摘要）寫重點")
            if not text:
                text, src = summarize(top, item_cap, env, **_gen)
            # 顯示用的標題把尾巴的「 - 來源」去掉——旁邊已經另掛來源小標，
            # 留著會變成「…- Yahoo奇摩財經　Yahoo奇摩財經」連講兩次。
            links = [{"title": re.sub(r"\s*[-–—|]\s*[^-–—|]{1,30}$", "",
                                      x["title"]).strip() or x["title"],
                      "link": x["link"],
                      "source": x["source"]} for x in top[:3]]
            if text:
                out["text"], out["text_source"] = text, src
                out["layout"] = "main"
                log.info("市場焦點：產出主軸＋%d 則補充（%s）",
                         len(text.splitlines()) - 1,
                         "內文" if src == "model-content" else "標題")
            else:
                # 第三層退路（列標題）不再把標題串成一段假摘要——
                # 下方「來源標題」本來就列著同樣三條，串起來等於同一批字
                # 印兩次（畫面上實際發生過）。text 留空，由首頁改成
                # 直接攤開標題清單並註明「本次 AI 摘要不可用」。
                # text 留空也讓快取不生效，下一次執行會再試 AI。
                log.warning("市場焦點：AI 重點退回列標題（%s）", src)
                out["text"] = ""
                out["text_source"] = "headlines"
            out["links"] = links
            state.update({"hash": h, "text": out["text"], "links": links,
                          "text_source": out["text_source"],
                          "layout": out.get("layout", ""),
                          "at": _now.isoformat()})
    else:
        log.warning("市場焦點：沒有抓到任何標題")

    # ---- 主題補充：依讀者選的前兩個指標換主題（主軸寫成才做）----
    out["topics"], out["topic_map"] = [], chip_topic_map(topic_specs(cfg))
    if out.get("layout") == "main" and out.get("text"):
        try:
            _tp = build_topics(cfg, _raw_pool, out["text"].split("\n")[0],
                               [x.get("title", "") for x in out.get("links") or []],
                               state, env, now=dt.datetime.now(dt.timezone.utc),
                               meta_markers=meta_markers)
            out["topics"], out["topic_map"] = _tp["items"], _tp["map"]
        except Exception as e:                     # noqa: BLE001
            log.warning("主題補充失敗（%s），補充維持一般內容", e)

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
