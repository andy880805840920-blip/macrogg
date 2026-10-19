"""
長端頁的財政部／紐約聯儲資料（2026-10 新增）。

    財政部 Fiscal Data          coupon 拍賣結果（得標殖利率、投標倍數、得標者組成）、
                                已公告的拍賣、MSPD 月底存量、DTS 每日發行／贖回、買回結果
    財政部暫定排程 XML          再融資公布的拍賣與買回排程
    CNBC 5 分鐘 K 棒            買回公告／結果後 1 小時的 10／20／30 年殖利率
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
import re

import requests

log = logging.getLogger(__name__)

TD = "https://www.treasurydirect.gov/TA_WS/securities"
NYF = "https://markets.newyorkfed.org/api/soma"
RP_RESULTS = "https://markets.newyorkfed.org/api/rp/results/search.json"
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
    # auctionDate 現在普遍是空的（TreasuryDirect 這支端點的資料品質問題，
    # 不分 Note／Bond／Bill 都一樣）——retain 用 issueDate 當後備，不然
    # 這裡的 date 全空，下游的日期篩選會把每一筆都濾掉。
    return {
        "date": (a.get("auctionDate") or a.get("issueDate") or "")[:10],
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


FISCAL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
FISCAL_AUCTIONS = f"{FISCAL}/v1/accounting/od/auctions_query"


def normalize_fiscal_auction(a: dict) -> dict:
    """
    財政部 Fiscal Data auctions_query 一筆 → 跟 normalize_auction 相同的欄位。

    2026-10 起 coupon 拍賣改走這裡：TreasuryDirect TA_WS 的 auctionDate
    普遍是空的（只好拿 issueDate 頂替，日期整整差了一週以上），得標者組成
    （primaryDealer／direct／indirect）與中位殖利率也大多是 0 或空的，
    拍賣卡片的交易商比例、分散度因此全錯。Fiscal Data 是同一份官方結標
    紀錄，auction_date 與各欄位都齊。
    """
    b = 1e9
    f = lambda k: _f(None if a.get(k) in (None, "null", "") else a.get(k))
    term = a.get("original_security_term") or a.get("security_term") or ""
    sterm = a.get("security_term") or term
    return {
        "date": (a.get("auction_date") or "")[:10],
        "announce": (a.get("announcemt_date") or "")[:10],
        "issue": (a.get("issue_date") or "")[:10],
        "maturity": (a.get("maturity_date") or "")[:10],
        "term": term,
        "security_term": sterm,
        "reopening": a.get("reopening") == "Yes" or sterm != term,
        "tips": a.get("inflation_index_security") == "Yes",
        "frn": a.get("floating_rate") == "Yes",
        "type": a.get("security_type") or "",
        "cusip": a.get("cusip") or "",
        "offering": (f("offering_amt") or 0) / b or None,
        "high": f("high_yield"),
        "median": f("avg_med_yield"),
        "low": f("low_yield"),
        "btc": f("bid_to_cover_ratio"),
        "comp_acc": (f("comp_accepted") or 0) / b or None,
        "pd": (f("primary_dealer_accepted") or 0) / b,
        "direct": (f("direct_bidder_accepted") or 0) / b,
        "indirect": (f("indirect_bidder_accepted") or 0) / b,
        "soma": (f("soma_accepted") or 0) / b,
    }


def _fiscal_rows(path: str, flt: str, sort: str = "", size: int = 1000) -> list[dict]:
    """Fiscal Data 分頁全抓（filter 用原始字串，逗號分隔多條件）。"""
    out, page = [], 1
    while True:
        js = _get(f"{FISCAL}/{path}?filter={flt}&page%5Bsize%5D={size}&page%5Bnumber%5D={page}"
                  + (f"&sort={sort}" if sort else ""))
        data = (js or {}).get("data") or []
        out += data
        total = int(((js or {}).get("meta") or {}).get("total-pages") or 1)
        if page >= total or not data:
            return out
        page += 1


def coupon_auctions(days: int = 730) -> list[dict]:
    """近兩年已結標的 Note／Bond 拍賣（含 TIPS、FRN 標記），日期由舊到新。"""
    from . import clock
    start = (clock.today() - dt.timedelta(days=days)).isoformat()
    rows = _fiscal_rows("v1/accounting/od/auctions_query",
                        f"security_type:in:(Note,Bond),auction_date:gte:{start}", "auction_date")
    out = [normalize_fiscal_auction(a) for a in rows]
    out = [r for r in out if r["date"] and r["high"] is not None]
    out.sort(key=lambda r: r["date"])
    return out


TENTATIVE_AUCTIONS = "https://home.treasury.gov/system/files/221/Tentative-Auction-Schedule.xml"


def _xml_items(text: str, tag: str) -> list[dict]:
    """把 <tag>…</tag> 的平坦子元素轉成 dict（財政部的排程 XML 都是這種形狀）。"""
    out = []
    for blk in re.findall(rf"<{tag}>(.*?)</{tag}>", text, re.S):
        out.append({k: v.strip() for k, v in re.findall(r"<(\w+)>([^<]*)</\1>", blk)})
    return out


def upcoming_auctions() -> list[dict]:
    """
    還沒結標的拍賣：
      ① Fiscal Data 已公告的（含金額，通常是未來一週內，含 bill）
      ② 財政部每季再融資公布的暫定拍賣排程 XML（只有日期與天期，沒有金額），
         補上①還沒涵蓋到的 coupon 拍賣，標 tentative。
    """
    from . import clock
    today = clock.today().isoformat()
    rows = _fiscal_rows("v1/accounting/od/auctions_query", f"auction_date:gte:{today}", "auction_date")
    out = [normalize_fiscal_auction(a) for a in rows]
    out = [r for r in out if r["date"] and r["high"] is None]
    seen = {(r["date"], r["term"], r["tips"]) for r in out}
    try:
        r = requests.get(TENTATIVE_AUCTIONS, timeout=40, headers=UA)
        r.raise_for_status()
        for it in _xml_items(r.text, "AuctionCalendarDate"):
            d = it.get("AuctionDate") or ""
            typ = (it.get("SecurityType") or "").title()
            if d < today or typ not in ("Note", "Bond"):
                continue
            term = it.get("SecurityTermWeekYear") or ""
            key = (d, term, it.get("TIPS") == "Y")
            if key in seen:
                continue
            out.append({"date": d, "announce": it.get("AnnouncementDate") or "",
                        "issue": it.get("SettlementDate") or "", "term": term,
                        "security_term": term, "reopening": it.get("ReOpeningIndicator") == "Y",
                        "tips": it.get("TIPS") == "Y", "frn": it.get("FloatingRate") == "Y",
                        "type": typ, "offering": None, "tentative": True})
    except Exception as e:                         # noqa: BLE001
        log.warning("暫定拍賣排程取得失敗（%s）", e)
    return sorted(out, key=lambda r: r["date"])


def _bill_rows_all(start: str) -> list[dict]:
    """
    Bill（含現金管理票券 CMB）逐筆拍賣，{date, term, offering}（十億美元）。

    改走財政部 Fiscal Data（跟 MSPD 同一個 API 家族），不是 TreasuryDirect
    的 /auctioned：TreasuryDirect 那支端點對 type=Bill 有兩個問題——
    auctionDate 欄位普遍是空的（Note／Bond 才有），且不管 pagesize／
    startDate 怎麼設，實測回來的筆數都被卡在約 90 筆，拿不到完整一年的
    週頻資料。Fiscal Data 的 auctions_query 兩個問題都沒有：issue_date
    每筆都有，filter 真的有在篩，一次查過去一年＋近期已公告的未來拍賣
    （還沒結標但金額已公布的），一次抓齊不用分開呼叫兩支端點。
    """
    js = _get(f"{FISCAL_AUCTIONS}?filter=issue_date:gte:{start},security_type:eq:Bill"
             f"&page%5Bsize%5D=1000&fields=issue_date,security_term,offering_amt,"
             f"cash_management_bill_cmb")
    out = []
    for r in (js or {}).get("data") or []:
        d = (r.get("issue_date") or "")[:10]
        amt = _f(r.get("offering_amt"))
        if not d or not amt:
            continue
        out.append({"date": d, "term": r.get("security_term") or "", "offering": amt / 1e9})
    out.sort(key=lambda r: r["date"])
    return out


# ---------------------------------------------------------------------------
# T-Bills 淨發行：MSPD（月底存量）＋ DTS（當月至今）＋ Fed 實際購買
# ---------------------------------------------------------------------------
def mspd_marketable(months: int = 18) -> list[dict]:
    """
    MSPD 表一逐月月底存量（十億美元）：{date, bills, marketable}。
    相鄰兩個月 bills 相減＝當月 T-Bills 淨發行（發行 − 到期贖回），
    這是財政部口徑的精確數字（跟 Barclays 等賣方報告用的是同一個）。
    """
    from . import clock
    start = (clock.today() - dt.timedelta(days=31 * (months + 1))).isoformat()
    rows = _fiscal_rows("v1/debt/mspd/mspd_table_1", f"record_date:gte:{start}", "record_date")
    by: dict = {}
    for r in rows:
        d = r.get("record_date") or ""
        v = _f(r.get("total_mil_amt"))
        if not d or v is None:
            continue
        if r.get("security_type_desc") == "Marketable" and r.get("security_class_desc") == "Bills":
            by.setdefault(d, {})["bills"] = v / 1e3
        elif r.get("security_type_desc") == "Total Marketable":
            by.setdefault(d, {})["marketable"] = v / 1e3
    return [{"date": d, **v} for d, v in sorted(by.items())
            if "bills" in v and "marketable" in v]


def dts_bills_mtd() -> dict | None:
    """
    每日國庫報表（DTS）表 IIIA：當月至今 T-Bills 發行與贖回（十億美元）。
    MSPD 要到次月初才出，當月的淨發行只能從這裡看到「月初至今」。
    """
    from . import clock
    start = (clock.today() - dt.timedelta(days=10)).isoformat()
    rows = _fiscal_rows("v1/accounting/dts/public_debt_transactions",
                        f"record_date:gte:{start},security_market:eq:Marketable,security_type:eq:Bills",
                        "-record_date", size=100)
    if not rows:
        return None
    last = max(r["record_date"] for r in rows)
    iss = sum(_f(r.get("transaction_mtd_amt")) or 0 for r in rows
              if r["record_date"] == last and r.get("transaction_type") == "Issues")
    red = sum(_f(r.get("transaction_mtd_amt")) or 0 for r in rows
              if r["record_date"] == last and r.get("transaction_type") == "Redemptions")
    return {"date": last, "issues": iss / 1e3, "redemptions": red / 1e3, "net": (iss - red) / 1e3}


NYF_TSY_PURCHASES = ("https://markets.newyorkfed.org/api/tsy/purchases/results/summary/"
                     "search.json?securityType=treasury")


def fed_bill_purchases(start: str) -> list[dict]:
    """
    紐約聯儲逐筆國庫券購買結果（RMP＋MBS 再投入合在一起，十億美元），
    {date: 交割日, value}。依交割日歸月，才跟 MSPD 月底存量對得上。
    """
    from . import clock
    js = _get(f"{NYF_TSY_PURCHASES}&startDate={start}&endDate={clock.today().isoformat()}")
    ops = ((js or {}).get("treasury") or {}).get("auctions") or []
    out = []
    for o in ops:
        if o.get("operationType") != "Outright Bill Purchase" or o.get("auctionStatus") != "Results":
            continue
        v, d = _f(o.get("totalParAmtAccepted")), o.get("settlementDate")
        if d and v is not None:
            out.append({"date": d, "value": v / 1e9})
    return sorted(out, key=lambda r: r["date"])


# ---------------------------------------------------------------------------
# Fed 負債端（H.4.1，週三水位）
# ---------------------------------------------------------------------------
# 聯準會理事會 Data Download Program：H.4.1「Factors absorbing reserve funds」
# 那一包（package id 是理事會網站產生的固定雜湊）。逆回購拆成 Others（國內：
# 貨幣基金、GSE、交易商的 ON RRP）與 Foreign official and international
# accounts（外國央行與國際機構的 foreign repo pool）兩條，相加＝總額。
H41_DDP = ("https://www.federalreserve.gov/datadownload/Output.aspx?rel=H41"
           "&series=f52e72511be65e16f71d4f5858951312&lastobs={n}&from=&to="
           "&filetype=csv&label=include&layout=seriescolumn&type=package")
H41_KEYS = {"currency": ("RESTBC_N.WW", "WCICL"),       # 流通在外貨幣
            "reserves": ("RESH4R_N.WW", "WRBWFRBL"),    # 存款機構準備金
            "tga": ("RESPPLLDT_N.WW", "WTREGEN"),       # 財政部一般帳戶
            "rrp": ("RESPPLLR_N.WW", "WLRRAL"),         # 逆回購總額
            "rrp_dom": ("RESPPLLRD_N.WW", "WLRRAOL"),   # 國內（ON RRP）
            "rrp_for": ("RESPPLLRF_N.WW", "WLRRAFOIAL")}  # 國外官方與國際帳戶


def h41_liabilities(weeks: int = 270) -> dict:
    """
    逐週（週三水位）Fed 負債端主要項目，十億美元：
    {"source": "H.4.1"|"FRED", "rows": [{date, currency, reserves, tga, rrp, rrp_dom, rrp_for}]}
    先抓理事會官方 DDP；失敗才用 FRED 同一組序列（FRED 是 H.4.1 的轉載）。
    """
    import csv
    import io
    try:
        r = requests.get(H41_DDP.format(n=weeks), timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        rows = list(csv.reader(io.StringIO(r.text)))
        hdr = next(row for row in rows if row and row[0] == "Time Period")
        ix = {k: hdr.index(v[0]) for k, v in H41_KEYS.items()}
        out = []
        for row in rows[rows.index(hdr) + 1:]:
            vals = {k: _f(row[i]) for k, i in ix.items()}
            if row and re.match(r"\d{4}-\d{2}-\d{2}$", row[0]) and all(v is not None for v in vals.values()):
                out.append({"date": row[0], **{k: v / 1e3 for k, v in vals.items()}})
        if len(out) > 50:
            return {"source": "H.4.1", "rows": out}
        raise ValueError(f"DDP 只回來 {len(out)} 筆")
    except Exception as e:                         # noqa: BLE001
        log.warning("H.4.1 官方下載失敗（%s），改用 FRED 轉載", e)
    from . import clock
    start = (clock.today() - dt.timedelta(weeks=weeks)).isoformat()
    by: dict = {}
    for k, (_, fid) in H41_KEYS.items():
        txt = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={fid}&cosd={start}",
                           timeout=40, headers=UA).text
        for line in txt.splitlines()[1:]:
            d, _, v = line.partition(",")
            if _f(v) is not None:
                by.setdefault(d, {})[k] = _f(v) / 1e3
    rows = [{"date": d, **v} for d, v in sorted(by.items()) if len(v) == len(H41_KEYS)]
    return {"source": "FRED", "rows": rows}


# ---------------------------------------------------------------------------
# 財政部買回（Buybacks）
# ---------------------------------------------------------------------------
BB_XML = "https://www.treasurydirect.gov/instit/annceresult/press/preanre/{y}/{f}"
BB_SCHEDULE = "https://home.treasury.gov/system/files/221/Tentative-Buyback-Schedule{q}.xml"


def buyback_operations(start: str) -> list[dict]:
    """
    Fiscal Data buybacks_operations：逐場買回結果（十億美元）。
    {date, type（Liquidity Support／Cash Management）, sec（Nominal Coupons／TIPS）,
     bucket, max, accepted, offered, eligible, n_accepted, start, close, settle, prelim_xml}
    """
    rows = _fiscal_rows("v1/accounting/od/buybacks_operations", f"operation_date:gte:{start}",
                        "operation_date", size=500)
    out = []
    for r in rows:
        g = lambda k: _f(r.get(k))
        out.append({
            "date": r.get("operation_date") or "", "type": r.get("operation_type") or "",
            "sec": r.get("security_type") or "", "bucket": r.get("maturity_bucket") or "",
            "max": (g("max_par_amt_redeemed") or 0) / 1e9,
            "accepted": (g("total_par_amt_accepted") / 1e9) if g("total_par_amt_accepted") is not None else None,
            "offered": (g("total_par_amt_offered") / 1e9) if g("total_par_amt_offered") is not None else None,
            "eligible": int(g("nbr_issues_eligible") or 0), "n_accepted": int(g("nbr_issues_accepted") or 0),
            "start": r.get("operation_start_time_est") or "", "close": r.get("operation_close_time_est") or "",
            "settle": r.get("settlement_date") or "", "prelim_xml": r.get("preliminary_ann_xml") or "",
        })
    return [r for r in out if r["date"]]


def buyback_announce_time(prelim_xml: str, date: str) -> str | None:
    """初步公告（BBPA_*.xml）的 announcementDTM：買回上限第一次公布的時間（ET，ISO）。"""
    if not prelim_xml or prelim_xml == "null":
        return None
    r = requests.get(BB_XML.format(y=date[:4], f=prelim_xml), timeout=30, headers=UA)
    r.raise_for_status()
    m = re.search(r"<announcementDTM>([^<]+)</announcementDTM>", r.text)
    return m.group(1)[:19] if m else None


def buyback_schedule(today: dt.date) -> dict:
    """
    再融資公布的暫定買回排程（XML）。檔名用日曆季（Q32026＝8 月再融資那一份，
    涵蓋到下一次再融資），從本季往前找到第一份抓得到的。
    """
    y, q = today.year, (today.month - 1) // 3 + 1
    for _ in range(3):
        try:
            r = requests.get(BB_SCHEDULE.format(q=f"Q{q}{y}"), timeout=30, headers=UA)
            if r.ok and "<BuyBackCalendar>" in r.text:
                name = (re.search(r"<BuybackCalendarName>([^<]*)<", r.text) or [None, ""])[1]
                ops = []
                for it in _xml_items(r.text, "BuybackCalendarDate"):
                    ops.append({"date": it.get("OperationDate") or "",
                                "announce": it.get("AnnouncementDate") or "",
                                "bucket": it.get("PurchaseBucketName") or "",
                                "type": it.get("OperationType") or "",
                                "max": (_f(it.get("MaximumPurchaseAmountDollars")) or 0) / 1e9})
                return {"name": name, "url": BB_SCHEDULE.format(q=f"Q{q}{y}"),
                        "ops": sorted(ops, key=lambda o: o["date"])}
        except Exception as e:                     # noqa: BLE001
            log.warning("買回排程 Q%s%s 取得失敗（%s）", q, y, e)
        q -= 1
        if q == 0:
            y, q = y - 1, 4
    return {}


CNBC_BARS = ("https://ts-api.cnbc.com/harmony/app/bars/{sym}/5M/{a}/{b}/adjusted/EST5EDT.json")
YIELD_SYMS = {"10Y": "US10Y", "20Y": "US20Y", "30Y": "US30Y"}


def _bars_5m(sym: str, day: str) -> dict:
    """CNBC 5 分鐘殖利率 K 棒（美東時間），{'HH:MM': close}。"""
    d = day.replace("-", "")
    js = requests.get(CNBC_BARS.format(sym=sym, a=f"{d}000000", b=f"{d}235959"),
                      timeout=30, headers={"User-Agent": "Mozilla/5.0"}).json()
    out = {}
    for b in ((js or {}).get("barData") or {}).get("priceBars") or []:
        t, c = b.get("tradeTime") or "", _f(b.get("close"))
        if t[:8] == d and c is not None:
            out[f"{t[8:10]}:{t[10:12]}"] = c
    return out


def _window_bp(bars: dict, t0: str, minutes: int = 60):
    """
    t0 之前最後一根 K 棒的收盤 → t0＋minutes 之前最後一根的收盤，殖利率變化（bp）。
    K 棒時間是該根的開始時間，所以「t0 之前」是開始時間 < t0、「＋60 分鐘」是
    開始時間 ≤ t0＋55（那根在 t0＋60 收）。沒成交的 5 分鐘不會有 K 棒，取最近的。
    """
    h, m = map(int, t0.split(":"))
    m0 = h * 60 + m
    hm = lambda x: f"{x // 60:02d}:{x % 60:02d}"
    pre = [k for k in bars if k < hm(m0)]
    post = [k for k in bars if hm(m0) <= k <= hm(m0 + minutes - 5)]
    if not pre or not post:
        return None
    return round((bars[max(post)] - bars[max(pre)]) * 100, 1)


def buyback_reactions(ops: list[dict], cache_path: pathlib.Path) -> dict:
    """
    每場買回兩個時點後 1 小時的 10／20／30 年殖利率變化（bp），結果快取在 state/：
      announce  初步公告（公布買回上限）：公告時間 → ＋60 分鐘
      result    操作截止（14:00 ET，結果隨即公布）→ ＋60 分鐘
    {date: {"announce_at": iso, "announce": {10Y,20Y,30Y}, "result": {…}}}
    """
    from . import clock
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    today = clock.today().isoformat()
    for o in ops:
        if o["date"] >= today or o.get("accepted") is None:
            continue
        c = cache.get(o["date"]) or {}
        if c.get("done"):
            continue
        try:
            if not c.get("announce_at"):
                c["announce_at"] = buyback_announce_time(o.get("prelim_xml"), o["date"])
            close = dt.datetime.strptime(o.get("close") or "02:00 PM", "%I:%M %p").strftime("%H:%M")
            c["close_at"] = f'{o["date"]}T{close}:00'
            for kind, iso in (("announce", c.get("announce_at")), ("result", c["close_at"])):
                if not iso:
                    continue
                res = {}
                for k, sym in YIELD_SYMS.items():
                    res[k] = _window_bp(_bars_5m(sym, iso[:10]), iso[11:16])
                c[kind] = res
            c["done"] = (all(v is not None for kind in ("announce", "result")
                             for v in (c.get(kind) or {"x": None}).values())
                         or o["date"] < (clock.today() - dt.timedelta(days=10)).isoformat())
        except Exception as e:                     # noqa: BLE001
            log.warning("買回 %s 殖利率反應取得失敗（%s）", o["date"], e)
        cache[o["date"]] = c
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    return cache


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
# 常備回購機制（SRF）：紐約聯儲逐日操作結果
# ---------------------------------------------------------------------------
def srf_operations(start: str, end: str) -> list[dict]:
    """
    SRF（常備回購機制）逐日動用量（十億美元）與當日利率（名目利率走廊上限）：
    紐約聯儲公開市場操作台每天上午、下午各辦一場隔夜回購操作，這裡把同一天
    的動用金額加總，利率取公債擔保那一檔的得標利率（兩場原則上同一天同利率）。

    https://www.newyorkfed.org/markets/desk-operations/repo 背後的資料來源；
    比 FRED 的 RPONTSYD（同一件事的轉載）快，也是這裡的權威版本——
    FRED 序列只在這個來源失敗時當後備（見 build_liquidity_context）。
    """
    js = _get(f"{RP_RESULTS}?startDate={start}&endDate={end}&operationTypes=Repo")
    ops = ((js or {}).get("repo") or {}).get("operations") or []
    by_day: dict[str, float] = {}
    rate_by_day: dict[str, float] = {}
    for o in ops:
        d = o.get("operationDate")
        amt = _f(o.get("totalAmtAccepted"))
        if not d or amt is None:
            continue
        by_day[d] = by_day.get(d, 0.0) + amt / 1e9
        for detail in o.get("details") or []:
            if detail.get("securityType") == "Treasury":
                r = _f(detail.get("percentOfferingRate"))
                if r is not None:
                    rate_by_day[d] = r
    return [{"date": d, "value": round(v, 3), "rate": rate_by_day.get(d)}
           for d, v in sorted(by_day.items())]


RMP_DETAILS_URL = ("https://www.newyorkfed.org/markets/domestic-market-operations/"
                   "monetary-policy-implementation/treasury-securities/"
                   "treasury-securities-operational-details")
_RMP_DATE = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})\s*-\s*\|?(\d{1,2}/\d{1,2}/\d{4})")
_RMP_REINVEST = re.compile(r"approximately \$([\d.]+) billion in reinvestment purchases")
_RMP_RMP = re.compile(r"(no reserve management purchases"
                      r"|approximately \$([\d.]+) billion in reserve management purchases)")


def rmp_schedule() -> list[dict]:
    """
    每期（約一個月，起訖日不對齊月曆，例如 7/14–8/13）Fed 計畫購買的國庫券，
    拆成 RMP（準備金管理購買）與 MBS 到期再投入兩個官方分開公布的金額
    （十億美元）。

    這是唯一有逐期拆開兩者的官方來源——紐約聯儲 Markets Data API 的操作
    紀錄（原本這裡呼叫的 tsy/purchases 端點）只給購買總額，不分誰是誰；
    這個頁面的「Planned Operation Amount」欄位直接寫成一句英文，例如
    「The Desk plans to conduct approximately $17.6 billion in reinvestment
    purchases and an additional approximately $10 billion in reserve
    management purchases」，用正則表達式解析這句話取兩個數字。

    是**計畫金額**不是逐筆結算金額——頁面本身也寫「RMP amounts are not on
    a preset course and may vary from month to month」，所以跟實際成交
    金額可能有落差；但這仍是官方唯一公布 RMP／MBS 拆分的地方。
    """
    r = requests.get(RMP_DETAILS_URL, timeout=40, headers=UA)
    r.raise_for_status()
    rows = re.findall(r"<tr[^>]*>.*?</tr>", r.text, re.S)
    out = []
    for row in rows:
        txt = re.sub(r"<[^>]+>", "|", row)
        dm = _RMP_DATE.search(txt)
        rm = _RMP_REINVEST.search(txt)
        pm = _RMP_RMP.search(txt)
        if not (dm and rm and pm):
            continue
        rmp_amt = 0.0 if pm.group(1) == "no reserve management purchases" else float(pm.group(2))
        start = dt.datetime.strptime(dm.group(1), "%m/%d/%Y").date().isoformat()
        end = dt.datetime.strptime(dm.group(2), "%m/%d/%Y").date().isoformat()
        out.append({"start": start, "end": end, "mbs": float(rm.group(1)), "rmp": rmp_amt})
    out.sort(key=lambda r: r["start"])
    return out


def rate_volume(secured: bool, ratetype: str, start: str, end: str) -> list[dict]:
    """
    官方逐日成交量（十億美元）：SOFR／TGCR／BGCR 走 secured，EFFR／OBFR 走
    unsecured。這是 SOFR 成交量遠大於 EFFR 的出處——2008 年後大型商業銀行
    的監管收緊，全球融資擴張轉向非銀行金融機構（NBFI），這些機構主要透過
    SOFR 這類擔保回購管道融資，使 SOFR 日均成交量達數兆美元，是 EFFR（銀行
    間無擔保拆借，監管收緊後規模萎縮）的二十幾倍。
    """
    base = "secured" if secured else "unsecured"
    js = _get(f"https://markets.newyorkfed.org/api/rates/{base}/{ratetype}/search.json"
             f"?startDate={start}&endDate={end}&type=volume")
    rows = (js or {}).get("refRates") or []
    out = []
    for r in rows:
        d, v = r.get("effectiveDate"), _f(r.get("volumeInBillions"))
        if d and v is not None:
            out.append({"date": d, "value": v})
    return sorted(out, key=lambda r: r["date"])


# ---------------------------------------------------------------------------
# 一次抓齊（給 run.py）
# ---------------------------------------------------------------------------
def gather(offline: bool, state_dir: pathlib.Path, fixture: pathlib.Path | None = None) -> dict:
    """
    {auctions, upcoming, soma, wam, srf, rmp_schedule, sofr_vol, effr_vol,
    bill_auctions, upcoming_bills, mspd, dts_bills, fed_bills, buybacks,
    buyback_schedule, buyback_reactions, h41, failed}。
    離線時讀 fixture（沒有就是空的）。
    """
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
    from . import clock
    end = clock.today()
    start200 = (end - dt.timedelta(days=200)).isoformat()
    end_iso = end.isoformat()
    try:
        out["srf"] = srf_operations(start200, end_iso)
    except Exception as e:                         # noqa: BLE001
        log.warning("SRF 動用量取得失敗（%s），流動性頁改用 FRED 後備", e)
        out["srf"] = []
        failed.append("srf")
    try:
        out["rmp_schedule"] = rmp_schedule()
    except Exception as e:                         # noqa: BLE001
        log.warning("RMP／MBS 再投入排程取得失敗（%s）", e)
        out["rmp_schedule"] = []
        failed.append("rmp_schedule")
    try:
        out["sofr_vol"] = rate_volume(True, "sofr", start200, end_iso)
        out["effr_vol"] = rate_volume(False, "effr", start200, end_iso)
    except Exception as e:                         # noqa: BLE001
        log.warning("SOFR／EFFR 成交量取得失敗（%s）", e)
        out["sofr_vol"], out["effr_vol"] = [], []
        failed.append("rate_volume")
    try:
        # 抓過去約 13 個月（RMP 近 12 期的回溯範圍再加一點緩衝）＋近期已公告的
        # 未來拍賣，一次查完後用「今天」切成已結束／尚未舉行兩份。
        _bill_start = (end - dt.timedelta(days=400)).isoformat()
        _bill_all = _bill_rows_all(_bill_start)
        out["bill_auctions"] = [r for r in _bill_all if r["date"] <= end_iso]
        out["upcoming_bills"] = [r for r in _bill_all if r["date"] > end_iso]
    except Exception as e:                         # noqa: BLE001
        log.warning("Bill 拍賣資料取得失敗（%s）", e)
        out["bill_auctions"], out["upcoming_bills"] = [], []
        failed.append("bill_auctions")
    # T-Bills 淨發行（MSPD 月底存量差＋DTS 當月至今）與 Fed 實際購買
    for key, fn in (("mspd", lambda: mspd_marketable(18)), ("dts_bills", dts_bills_mtd),
                    ("fed_bills", lambda: fed_bill_purchases(
                        (end - dt.timedelta(days=560)).isoformat()))):
        try:
            out[key] = fn()
        except Exception as e:                     # noqa: BLE001
            log.warning("%s 取得失敗（%s）", key, e)
            out[key] = [] if key != "dts_bills" else None
            failed.append(key)
    try:
        out["h41"] = h41_liabilities()
    except Exception as e:                         # noqa: BLE001
        log.warning("Fed 負債端（H.4.1）取得失敗（%s）", e)
        out["h41"] = {}
        failed.append("h41")
    # 財政部買回：近一年逐場結果＋暫定排程＋每場公告／結果後 1 小時殖利率反應
    try:
        out["buybacks"] = buyback_operations((end - dt.timedelta(days=370)).isoformat())
    except Exception as e:                         # noqa: BLE001
        log.warning("買回結果取得失敗（%s）", e)
        out["buybacks"] = []
        failed.append("buybacks")
    out["buyback_schedule"] = buyback_schedule(end)
    try:
        recent = [o for o in out["buybacks"]
                  if o["date"] >= (end - dt.timedelta(days=150)).isoformat()]
        out["buyback_reactions"] = buyback_reactions(recent, state_dir / "buyback_yields.json")
    except Exception as e:                         # noqa: BLE001
        log.warning("買回殖利率反應計算失敗（%s）", e)
        out["buyback_reactions"] = {}
        failed.append("buyback_reactions")
    out["failed"] = failed
    return out
