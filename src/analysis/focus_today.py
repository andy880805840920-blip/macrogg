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
        prev = meta.get("chartPreviousClose")
        if prev is None:
            prev = meta.get("previousClose")
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
        prev = meta.get("chartPreviousClose")
        if prev is None:
            prev = meta.get("previousClose")
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


def _mk(cid, label, value, delta, direction, date, on=False):
    return {"id": cid, "label": label, "value": value, "delta": delta,
            "dir": direction, "date": date[5:] if len(date) >= 10 else date,
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


def build_catalog(rates_series: dict | None, liq_series: dict | None,
                  fresh_yields: list | None, offline: bool,
                  _get=None) -> list[dict]:
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
    chips.append({"id": "fedwatch", "special": "fedwatch",
                  "on": "fedwatch" in DEFAULT_CHIPS})
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
    _qids = ("wti", "brent", "vix", "move")
    _quotes = dict(zip(_qids, _pmap(
        lambda c: None if offline else fetch_yahoo_quote(
            QUOTE_SPECS[c]["sym"], QUOTE_SPECS[c]["lo"],
            QUOTE_SPECS[c]["hi"], _get=_get), _qids)))
    for cid in _qids:
        chips.append(_level_chip(cid, QUOTE_SPECS[cid], liq, offline,
                                 _get=_get, _pre=_quotes.get(cid)))
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
               ("bloomberg", "Bloomberg"))


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


def fetch_feed_headlines(feeds: list[str], keywords: list[str],
                         hours: int = 30, _get=None,
                         exclude: list[str] | None = None) -> list[dict]:
    """
    直接吃 Yahoo 的 RSS，只留**標題命中任一關鍵字詞**的項目。
    單一 feed 失敗就跳過；全部失敗回空列表，由呼叫端退回 Google News。
    """
    get = _get or (lambda url: requests.get(
        url, timeout=TIMEOUT, headers={"User-Agent": "macro-dashboard/1.0"}))
    words = [w for kw in keywords for w in str(kw).split() if w]
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    out, seen = [], set()
    for feed in feeds:
        try:
            r = get(feed)
            r.raise_for_status()
            root = ET.fromstring(r.content)
        except Exception as e:                     # noqa: BLE001
            log.warning("市場焦點：feed %s 抓取失敗（%s）", feed, e)
            continue
        label = _feed_label(feed)
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = item.findtext("pubDate") or ""
            if not title or not link:
                continue
            if not any(_kw_hit(w, _kw_text(title)) for w in words):
                continue
            if _excluded(title, exclude):
                continue
            try:
                at = parsedate_to_datetime(pub)
                if at.tzinfo is None:
                    at = at.replace(tzinfo=dt.timezone.utc)
            except (ValueError, TypeError):
                continue
            if at < cutoff:
                continue
            key = re.sub(r"\s+", "", _norm_title(title))[:40]
            if key in seen:
                continue
            seen.add(key)
            # RSS 的官方摘要（FT／WSJ 的 description 是出版社自己寫的
            # 一兩句話，合法免費）：付費牆來源靠它補一點實質內容。
            desc = _html.unescape(re.sub(
                r"<[^>]+>", " ", item.findtext("description") or ""))
            desc = re.sub(r"\s+", " ", desc).strip()[:240]
            if desc and _sim(_norm_title(desc), _norm_title(title)) > 0.7:
                desc = ""                          # 摘要只是標題重印就不留
            out.append({"title": title, "link": link, "source": label,
                        "at": at.isoformat(), "kw": "",
                        "summary": desc if len(desc) >= 30 else ""})
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
    "只取與這些關鍵字相關的內容：{kws}。"
    "讀完全部材料後，**重新綜合改寫成一篇連貫的報導**，不是逐篇摘要："
    "把各篇的資訊整合成同一條敘事線，分成 2 到 3 個段落，"
    "段落之間用一個空行分隔，每段 60 到 110 個中文字，總長不超過 {cap} 字。"
    "優先寫內文才有、標題沒有的具體資訊：金額與規模、時間點、"
    "人名與職稱、機構名、關鍵引述。硬性規則："
    "只能使用材料已有的資訊，不得補充材料以外的事實或數字；"
    "「標題快訊」只能轉述其標題與摘要**字面上有的事**，不得展開細節、"
    "不得推測其內文，引用時帶來源（例如「路透報導稱…」）；"
    "不得自行推論來源沒有寫的因果關係；不做預測、不下投資結論；"
    "與關鍵字無關的內容一律不寫；繁體中文；"
    "直接輸出報導本文，不要標題、不要前言。")


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


def summarize_content(articles: list[dict], keywords: list[str],
                      cap: int, env=None,
                      briefs: list[dict] | None = None) -> tuple[str, str]:
    """
    從文章內文摘關鍵字相關的重點。回傳 (焦點段, 來源標記)；失敗回 ("", 原因)。

    briefs 是「標題快訊」層：付費牆來源（路透、彭博、FT、WSJ）的標題＋
    RSS 官方摘要。它們進材料包供模型織進論述，但提示詞硬性規定只能
    轉述字面——標題只有十幾個字，模型對著標題腦補是這一層最大的風險。
    數字鎖的驗證範圍涵蓋「全文＋快訊」的合併文字。
    """
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
    if not articles and not briefs:
        return "", "沒有任何材料"
    text, err = _call_ai(
        src_text,
        _FOCUS_CONTENT_SYSTEM.format(kws="、".join(keywords), cap=cap),
        env)
    if err:
        return "", err
    if not text or cjk_len(text) > cap + 40:
        return "", f"長度不合格（{cjk_len(text)} 字）"
    # 數字鎖對「內文」驗：輸出的每一串數字都必須出現在輸入的內文裡
    if not _digits_ok(text, src_text):
        return "", "輸出出現內文裡沒有的數字"
    return text, "model-content"


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


def pick_fallback(headlines: list[dict], keywords: list[str],
                  n: int = 3, exclude: list[str] | None = None) -> list[dict]:
    """
    沒有 AI 時的確定性挑選：關鍵字命中數多者優先。
    輸入已按時間新→舊排好，穩定排序讓同分者維持新的在前。

    挑的時候擋掉「同一件事的另一種寫法」：fetch 端的去重是完全比對
    （去尾巴後前 40 字），同一則新聞在不同媒體的標題只要改幾個字就會
    穿過去——實際發生過「來源標題選到兩則一樣的新聞」。這裡再用
    字元二元組相似度把 >0.55 的視為重複，跳過選下一則。
    """
    def _hits(h):
        t = _kw_text(h["title"])
        return sum(1 for kw in keywords for w in kw.split() if _kw_hit(w, t))
    picked = []
    for h in sorted(headlines, key=_hits, reverse=True):
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
    "你是財經編輯。從輸入的新聞標題清單挑出對「美國公債殖利率與聯準會政策」"
    "最重要的一到三則，寫成一段不超過 {cap} 個中文字的市場焦點。規則："
    "只能使用標題裡已有的資訊，不得補充任何標題以外的事實或數字；"
    "不做預測、不下投資結論；繁體中文；直接輸出那一段文字，不要任何前言。")


def _digits_ok(text: str, source: str) -> bool:
    """輸出裡的每一串數字都必須出現在來源標題裡（防 AI 編數字）。"""
    src = re.sub(r"[\s,，]", "", source)
    for num in re.findall(r"\d+(?:\.\d+)?", text.replace(",", "")):
        if num not in src:
            return False
    return True


def summarize(headlines: list[dict], cap: int, env=None) -> tuple[str, str]:
    """回傳 (焦點段, 來源標記)。失敗回 ("", 原因)。"""
    lines = "\n".join(f"- [{h['source'] or '—'}] {h['title']}"
                      for h in headlines[:24])
    text, err = _call_ai(lines, _FOCUS_SYSTEM.format(cap=cap), env)
    if err:
        return "", err
    if not text or cjk_len(text) > cap + 40:
        return "", f"長度不合格（{cjk_len(text)} 字）"
    if not _digits_ok(text, lines):
        return "", "輸出出現標題裡沒有的數字"
    return text, "model"


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
FW_METHOD = 4


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
def build(rates_series: dict | None, offline: bool, cfg: dict | None,
          state_path: Path, env=None, liq_series: dict | None = None) -> dict:
    cfg = cfg or {}
    keywords = cfg.get("keywords") or DEFAULT_KEYWORDS
    cap = int(cfg.get("max_chars") or 120)

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
                                     offline=True)
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
    # 目標會議的顯示標籤（「12 月」）——三層來源共用，chip 標題用
    _meet = str(cfg.get("fedwatch_meeting") or DEFAULT_MEETING)
    _meet_label = f"{int(_meet[5:7])} 月"
    if (fw_old.get("date") == today and fw_old.get("pct") is not None
            and fw_old.get("method") == FW_METHOD):
        out["fedwatch"] = {"pct": fw_old["pct"],
                           "delta_pp": fw_old.get("delta_pp"),
                           "suspect": bool(fw_old.get("suspect")),
                           "src": fw_old.get("src", ""),
                           "move_bp": fw_old.get("move_bp"),
                           "meeting_label": _meet_label}
    else:
        # 來源鏈：期貨價差（自算、自驗）×交叉檢核× Atlanta Fed（官方）
        # → Gemini 擷取 → 沿用前值。
        # Atlanta 每次都打：已啟用時當交叉檢核的裁判與備援；
        # 未啟用（沒設 atlanta_json_path）時做偵察、把端點候選寫進 log。
        _fw = fedwatch_from_futures(rates_series, cfg)
        _at = fetch_atlanta_fedwatch(cfg)
        pct, fw_src, _detail = _pick_fw(_fw, _at)
        move_bp = (_detail or {}).get("move_bp")
        if pct is None:
            pct = fetch_fedwatch(env)
            fw_src = "ai"
        prev = fw_old.get("pct")
        suspect = False
        if pct is None and prev is not None:
            # 本次擷取失敗（429、斷線…）但手上有近幾天的值 → 沿用並標明，
            # 不要讓一次限流就把整顆 chip 打回「—」。超過 4 天就太舊，
            # 寧可顯示「—」也不要掛一個一週前的機率。state 的 date 不動，
            # 下一次執行還會再試。
            try:
                _age = (dt.date.fromisoformat(today)
                        - dt.date.fromisoformat(fw_old.get("date", ""))).days
            except (ValueError, TypeError):
                _age = 99
            # 舊算法算出來的值不沿用：100% 事故的值掛著「沿用」標籤
            # 多活四天，比顯示「—」更糟。
            if _age <= 4 and fw_old.get("method") == FW_METHOD:
                out["fedwatch"] = {"pct": prev, "delta_pp": None,
                                   "suspect": False,
                                   "src": fw_old.get("src", ""),
                                   "move_bp": fw_old.get("move_bp"),
                                   "meeting_label": _meet_label,
                                   "stale_from": fw_old.get("date")}
        elif pct is not None:
            if _jump_suspect(pct, prev, fw_src):
                log.warning("FedWatch 單日跳動 %.0f→%.0f，視為擷取錯誤沿用前值",
                            prev, pct)
                pct, suspect = prev, True
                fw_src = fw_old.get("src", fw_src)
            if fw_src == "futures" and (_detail or {}).get(
                    "delta_pp") is not None:
                # 期貨路徑的 ± 是同一次執行裡「收盤對收盤」算出來的
                #（見 fedwatch_from_futures），跟其他 chip 同口徑，
                # 不經 state、也不需要 20pp 的改基準防護欄。
                delta = _detail["delta_pp"]
            else:
                delta = (round(pct - prev, 1)
                         if (prev is not None and not suspect
                             and fw_old.get("date") != today) else None)
                if delta is not None and abs(delta) > 20:
                    # 差這麼多通常是「正確值取代了事故留下的壞前值」——
                    # 這是改基準，不是市場一天動了幾十個百分點。
                    # 掛「-78.0 pp」只會嚇人，不標日變動、
                    # 讓 chip 顯示隱含利率。
                    log.info("FedWatch %.0f%% 與前值 %.0f%% 差 %.0fpp，"
                             "視為改基準，不標日變動", pct, prev, abs(delta))
                    delta = None
            out["fedwatch"] = {"pct": pct, "delta_pp": delta,
                               "suspect": suspect, "src": fw_src,
                               "move_bp": move_bp,
                               "meeting_label": _meet_label}
            state["fedwatch"] = {"pct": pct, "date": today,
                                 "delta_pp": delta, "suspect": suspect,
                                 "src": fw_src, "move_bp": move_bp,
                                 "method": FW_METHOD}

    # ---- 焦點段（三層）：Yahoo RSS＋內文摘要 → Google News 標題摘要 →
    #      列標題。同一批文章只呼叫一次 AI（雜湊快取）。 ----
    feeds = cfg.get("feeds") or DEFAULT_FEEDS
    exclude = cfg.get("exclude_keywords") or []
    heads = fetch_feed_headlines(feeds, keywords, exclude=exclude)
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
        top = pick_fallback(heads, keywords, n=6, exclude=exclude)
        # 兩層材料：內文名額只給抓得到正文的來源（Google News 是 JS
        # 轉址中介頁、FT／WSJ 是付費牆——先前佔掉名額又必然 0 段）；
        # 付費牆來源改走「標題快訊」層：標題＋RSS 官方摘要直接進材料包。
        body_cand = pick_fallback([x for x in heads
                                   if not _headline_only(x["link"])],
                                  keywords, n=6, exclude=exclude)
        briefs = pick_fallback([x for x in heads
                                if _headline_only(x["link"])],
                               keywords, n=4, exclude=exclude)
        h = hashlib.sha256((mode + "|" + "|".join(
            x["title"] for x in (top + body_cand + briefs)))
                           .encode("utf-8")).hexdigest()[:16]
        if state.get("hash") == h and state.get("text"):
            out["text"] = state["text"]
            out["text_source"] = "cache"
            out["cached_mode"] = ("content"
                                  if state.get("text_source") == "model-content"
                                  else "title")
            out["links"] = state.get("links") or []
        else:
            text, src = "", ""
            if mode == "content":
                # 內文並行抓（各篇獨立的 I/O 等待，串行是慢的主因之一）
                _bodies = _pmap(lambda x: fetch_article_text(x["link"]),
                                body_cand)
                arts = [{"title": x["title"], "body": b,
                         "source": x.get("source", "")}
                        for x, b in zip(body_cand, _bodies) if b]
                if arts or briefs:
                    # 抓到多少內文寫進 log：頁面只標「摘要自內文」，
                    # 摘要品質有疑慮時要能回頭查是不是內文本身太薄。
                    log.info("市場焦點：內文擷取 %d／%d 篇＋標題快訊 %d 則"
                             "（%s）", len(arts), len(body_cand), len(briefs),
                             "、".join(f"{a['title'][:12]}…{len(a['body'])}字"
                                       for a in arts))
                    text, src = summarize_content(arts, keywords, cap, env,
                                                  briefs=briefs)
                    if not text:
                        log.warning("市場焦點：內文摘要退回標題模式（%s）", src)
                else:
                    log.warning("市場焦點：內文全部抓不到，改用標題摘要")
            if not text:
                text, src = summarize(top, cap, env)
            # 顯示用的標題把尾巴的「 - 來源」去掉——旁邊已經另掛來源小標，
            # 留著會變成「…- Yahoo奇摩財經　Yahoo奇摩財經」連講兩次。
            links = [{"title": re.sub(r"\s*[-–—|]\s*[^-–—|]{1,30}$", "",
                                      x["title"]).strip() or x["title"],
                      "link": x["link"],
                      "source": x["source"]} for x in top[:3]]
            if text:
                out["text"], out["text_source"] = text, src
            else:
                # 第三層退路（列標題）不再把標題串成一段假摘要——
                # 下方「來源標題」本來就列著同樣三條，串起來等於同一批字
                # 印兩次（畫面上實際發生過）。text 留空，由首頁改成
                # 直接攤開標題清單並註明「本次 AI 摘要不可用」。
                # text 留空也讓快取不生效，下一次執行會再試 AI。
                log.warning("市場焦點：AI 段落退回列標題（%s）", src)
                out["text"] = ""
                out["text_source"] = "headlines"
            out["links"] = links
            state.update({"hash": h, "text": out["text"], "links": links,
                          "text_source": out["text_source"]})
    else:
        log.warning("市場焦點：沒有抓到任何標題")

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
                                     out["yields"], offline=False)
    except Exception as e:                         # noqa: BLE001
        log.warning("chip 目錄組裝失敗（%s），退回預設呈現", e)
        out["chips"] = []
    return out
