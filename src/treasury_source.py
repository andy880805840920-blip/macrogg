"""
長端頁的財政部／紐約聯儲資料（2026-10 新增）。

    TreasuryDirect 拍賣 API     coupon 拍賣結果（得標殖利率、投標倍數、得標者組成）
                                與未來已排程的拍賣
    紐約聯儲 SOMA API           Fed 持有資產的組成（週）與逐券明細（算 WAM）
    財政部 Fiscal Data（MSPD）  流通在外可交易公債逐券明細（月，算 WAM）

全部是官方免費公開資料，不需要金鑰。任何一個來源失敗都只讓對應的區塊顯示
「本次取得失敗」，不擋主流程。WAM 的歷史要逐月抓，結果快取在 state/，
每次只補新的月份。
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import pathlib

import requests

log = logging.getLogger(__name__)

TD = "https://www.treasurydirect.gov/TA_WS/securities"
NYF = "https://markets.newyorkfed.org/api/soma"
MSPD = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/"
        "debt/mspd/mspd_table_3_market")
UA = {"User-Agent": "MACROGG dashboard (macrogg.netlify.app)"}

# 名目 coupon 的標準天期（TIPS、FRN 不列在拍賣卡片，WAM 仍然算進去）
TENORS = ["2-Year", "3-Year", "5-Year", "7-Year", "10-Year", "20-Year", "30-Year"]
TENOR_ZH = {"2-Year": "2 年", "3-Year": "3 年", "5-Year": "5 年", "7-Year": "7 年",
            "10-Year": "10 年", "20-Year": "20 年", "30-Year": "30 年"}


def _get(url: str, timeout: int = 40):
    r = requests.get(url, timeout=timeout, headers=UA)
    r.raise_for_status()
    return r.json()


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 拍賣
# ---------------------------------------------------------------------------
def normalize_auction(a: dict) -> dict:
    """TreasuryDirect 一筆拍賣 → 頁面要用的欄位（金額一律換成十億美元）。"""
    b = 1e9
    term = a.get("originalSecurityTerm") or a.get("securityTerm") or ""
    return {
        "date": (a.get("auctionDate") or "")[:10],
        "announce": (a.get("announcementDate") or "")[:10],
        "issue": (a.get("issueDate") or "")[:10],
        "maturity": (a.get("maturityDate") or "")[:10],
        "term": term,
        "security_term": a.get("securityTerm") or term,
        "reopening": (a.get("reopening") == "Yes"
                      or (a.get("securityTerm") or term) != term),
        "tips": a.get("inflationIndexSecurity") == "Yes",
        "frn": a.get("floatingRate") == "Yes" or a.get("securityType") == "FRN",
        "type": a.get("securityType") or "",
        "cusip": a.get("cusip") or "",
        "offering": (_f(a.get("offeringAmount")) or 0) / b or None,
        "high": _f(a.get("highYield")),
        "median": _f(a.get("averageMedianYield")),
        "low": _f(a.get("lowYield")),
        "btc": _f(a.get("bidToCoverRatio")),
        "comp_acc": (_f(a.get("competitiveAccepted")) or 0) / b or None,
        "pd": (_f(a.get("primaryDealerAccepted")) or 0) / b,
        "direct": (_f(a.get("directBidderAccepted")) or 0) / b,
        "indirect": (_f(a.get("indirectBidderAccepted")) or 0) / b,
        "soma": (_f(a.get("somaAccepted")) or 0) / b,
    }


def coupon_auctions(pagesize: int = 250) -> list[dict]:
    """近兩年的 Note／Bond 拍賣（含 TIPS 標記），日期由舊到新。"""
    rows = []
    for typ in ("Note", "Bond"):
        js = _get(f"{TD}/auctioned?format=json&type={typ}&pagesize={pagesize}")
        rows += [normalize_auction(a) for a in js or []]
    rows = [r for r in rows if r["date"] and r["high"] is not None]
    rows.sort(key=lambda r: r["date"])
    return rows


def upcoming_auctions() -> list[dict]:
    """已排程的拍賣（含 bill）；金額在公告日之前可能是空的。"""
    js = _get(f"{TD}/upcoming?format=json")
    out = [normalize_auction(a) for a in js or []]
    return sorted([r for r in out if r["date"]], key=lambda r: r["date"])


# ---------------------------------------------------------------------------
# SOMA（Fed 持有的資產）
# ---------------------------------------------------------------------------
def soma_summary(weeks: int = 130) -> list[dict]:
    """週頻：{date, bills, notesbonds, tips, frn, mbs, cmbs, agencies}（十億美元）。"""
    js = _get(f"{NYF}/summary.json")
    out = []
    for r in ((js or {}).get("soma") or {}).get("summary") or []:
        row = {"date": r.get("asOfDate", "")}
        for k in ("bills", "notesbonds", "tips", "frn", "mbs", "cmbs", "agencies"):
            row[k] = (_f(r.get(k)) or 0.0) / 1e9
        out.append(row)
    out.sort(key=lambda r: r["date"])
    return out[-weeks:]


def _years(d0: dt.date, mat: str) -> float | None:
    try:
        return (dt.date.fromisoformat(mat[:10]) - d0).days / 365.25
    except (TypeError, ValueError):
        return None


def wam(rows: list[tuple[str, float]], asof: str) -> float | None:
    """[(到期日, 面額)] → 加權平均剩餘年限（年）。"""
    d0 = dt.date.fromisoformat(asof[:10])
    num = den = 0.0
    for mat, par in rows:
        y = _years(d0, mat)
        if y is None or par is None or par <= 0 or y < 0:
            continue
        num += y * par
        den += par
    return num / den if den else None


def soma_wam(asof: str) -> float | None:
    js = _get(f"{NYF}/tsy/get/asof/{asof}.json")
    hold = ((js or {}).get("soma") or {}).get("holdings") or []
    return wam([(h.get("maturityDate", ""), _f(h.get("parValue"))) for h in hold], asof)


def soma_dates() -> list[str]:
    js = _get(f"{NYF}/asofdates/list.json")
    return sorted(((js or {}).get("soma") or {}).get("asOfDates") or [])


def mspd_wam(record_date: str) -> float | None:
    """流通在外可交易公債（bills／notes／bonds／TIPS／FRN）的 WAM。"""
    js = _get(f"{MSPD}?filter=record_date:eq:{record_date}&page%5Bsize%5D=10000"
              "&fields=security_class1_desc,security_class2_desc,maturity_date,outstanding_amt")
    rows = []
    for r in (js or {}).get("data") or []:
        cus = r.get("security_class2_desc") or ""
        if len(cus) != 9:              # 小計列、合計列沒有 CUSIP
            continue
        rows.append((r.get("maturity_date") or "", _f(r.get("outstanding_amt"))))
    return wam(rows, record_date)


def _month_ends(n: int, today: dt.date) -> list[str]:
    out, y, m = [], today.year, today.month
    for _ in range(n + 1):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        nxt = dt.date(y + (m == 12), (m % 12) + 1, 1)
        out.append((nxt - dt.timedelta(days=1)).isoformat())
    return sorted(out)


def wam_history(cache_path: pathlib.Path, months: int = 24,
                today: dt.date | None = None) -> dict:
    """
    逐月的 WAM：{"soma": [{date, value}], "market": [{date, value}]}。
    已經算過的月份從快取拿，只補新的。MSPD 約在次月第 4 個工作日發布，
    抓不到的月份就留到下次。
    """
    from . import clock
    today = today or clock.today()
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    cache.setdefault("soma", {})
    cache.setdefault("market", {})
    ends = _month_ends(months, today)
    try:
        sd = soma_dates()
    except Exception as e:                         # noqa: BLE001
        log.warning("SOMA 日期清單取得失敗（%s）", e)
        sd = []
    for me in ends:
        key = me[:7]
        if key not in cache["soma"] and sd:
            cand = [d for d in sd if d[:7] == key]
            if cand:
                try:
                    v = soma_wam(cand[-1])
                    if v is not None:
                        cache["soma"][key] = {"date": cand[-1], "value": round(v, 3)}
                except Exception as e:             # noqa: BLE001
                    log.warning("SOMA %s WAM 失敗（%s）", key, e)
        if key not in cache["market"]:
            try:
                v = mspd_wam(me)
                if v is not None:
                    cache["market"][key] = {"date": me, "value": round(v, 3)}
            except Exception as e:                 # noqa: BLE001
                log.warning("MSPD %s WAM 失敗（%s）", key, e)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    return {k: [cache[k][m] for m in sorted(cache[k])][-months:] for k in ("soma", "market")}


# ---------------------------------------------------------------------------
# 一次抓齊（給 run.py）
# ---------------------------------------------------------------------------
def gather(offline: bool, state_dir: pathlib.Path, fixture: pathlib.Path | None = None) -> dict:
    """{auctions, upcoming, soma, wam, failed}。離線時讀 fixture（沒有就是空的）。"""
    if offline:
        try:
            return json.loads(fixture.read_text(encoding="utf-8")) if fixture else {}
        except (OSError, ValueError, AttributeError):
            return {}
    out, failed = {}, []
    for key, fn in (("auctions", coupon_auctions), ("upcoming", upcoming_auctions),
                    ("soma", soma_summary)):
        try:
            out[key] = fn()
        except Exception as e:                     # noqa: BLE001
            log.warning("長端資料 %s 取得失敗（%s）", key, e)
            failed.append(key)
            out[key] = []
    try:
        out["wam"] = wam_history(state_dir / "wam_cache.json")
    except Exception as e:                         # noqa: BLE001
        log.warning("WAM 計算失敗（%s）", e)
        out["wam"] = {"soma": [], "market": []}
        failed.append("wam")
    out["failed"] = failed
    return out
