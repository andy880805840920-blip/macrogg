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


def _ddp_csv(url: str, tries: int = 4) -> list[list[str]]:
    """
    理事會 DDP 下載。實測這個端點偶爾回 200 但內容是空的（連續請求時常見），
    重試幾次就會拿到完整檔案；全部失敗才往外丟。
    """
    import csv
    import io
    import time
    for i in range(tries):
        r = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        if r.text.strip():
            return list(csv.reader(io.StringIO(r.text)))
        time.sleep(2 + i * 2)
    raise ValueError("DDP 回傳空內容")


def _ddp_columns(rows: list[list[str]], keys: dict) -> list[dict]:
    """DDP 的 seriescolumn 格式 → [{date, key: 原始數值}]（缺任何一欄的日期略過）。"""
    hdr = next(row for row in rows if row and row[0] == "Time Period")
    ix = {k: hdr.index(v) for k, v in keys.items()}
    out = []
    for row in rows[rows.index(hdr) + 1:]:
        if not row or not re.match(r"\d{4}-\d{2}-\d{2}$", row[0]):
            continue
        vals = {k: _f(row[i]) for k, i in ix.items()}
        if all(v is not None for v in vals.values()):
            out.append({"date": row[0], **vals})
    return out


def h41_liabilities(weeks: int = 820) -> dict:
    """
    逐週（週三水位）Fed 負債端主要項目，十億美元：
    {"source": "H.4.1"|"FRED", "rows": [{date, currency, reserves, tga, rrp, rrp_dom, rrp_for}]}
    先抓理事會官方 DDP；失敗才用 FRED 同一組序列（FRED 是 H.4.1 的轉載）。
    """
    try:
        raw = _ddp_columns(_ddp_csv(H41_DDP.format(n=weeks)), {k: v[0] for k, v in H41_KEYS.items()})
        out = [{"date": r["date"], **{k: r[k] / 1e3 for k in H41_KEYS}} for r in raw]
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


# H.8（商業銀行資產負債）：全體商業銀行、季調、週資料的總資產（B1151NCBA，
# 單位百萬美元）。紐約聯儲 RDE 用的分母就是這一條（FRED 的 TLAACBW027SBOG）。
H8_DDP = ("https://www.federalreserve.gov/datadownload/Output.aspx?rel=H8"
          "&series=17951c643555bee48d63bb6957a4a92e&lastobs={n}&from=&to="
          "&filetype=csv&label=include&layout=seriescolumn&type=package")


def bank_assets(weeks: int = 820) -> list[dict]:
    """全體商業銀行總資產（季調，週三），[{date, value}]，十億美元。官方失敗才用 FRED。"""
    try:
        raw = _ddp_columns(_ddp_csv(H8_DDP.format(n=weeks)), {"v": "B1151NCBA"})
        if len(raw) > 50:
            return [{"date": r["date"], "value": r["v"] / 1e3} for r in raw]
    except Exception as e:                         # noqa: BLE001
        log.warning("H.8 官方下載失敗（%s），改用 FRED 轉載", e)
    txt = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=TLAACBW027SBOG",
                       timeout=40, headers=UA).text
    out = []
    for line in txt.splitlines()[1:]:
        d, _, v = line.partition(",")
        if _f(v) is not None:
            out.append({"date": d, "value": _f(v)})
    return out[-weeks:]


# 紐約聯儲「Reserve Demand Elasticity」：每月第三個週四 10:00（美東）更新，
# 檔內是約每 5 個營業日一筆的即時估計（2010 年起），單位 bp／百分點。
RDE_CSV = "https://www.newyorkfed.org/medialibrary/research/interactives/data/elasticity/elasticity-data.csv"
RDE_CONTENT = ("https://www.newyorkfed.org/medialibrary/research/interactives/data/"
               "elasticity/elasticity-content.json")


def rde() -> dict:
    """
    {"rows": [{date, median, lo95, hi95, lo68, hi68}], "release": 'October 15, 2026',
     "update": 'October 2026 Update', "bullets": [...英文原文]}
    """
    import csv
    import io
    r = requests.get(RDE_CSV, timeout=40, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    rows = []
    for x in list(csv.reader(io.StringIO(r.text)))[1:]:
        try:
            d = dt.datetime.strptime(x[0], "%m/%d/%Y").date().isoformat()
            rows.append({"date": d, "median": float(x[1]), "lo95": float(x[2]), "hi95": float(x[3]),
                         "lo68": float(x[4]), "hi68": float(x[5])})
        except (ValueError, IndexError):
            continue
    out = {"rows": sorted(rows, key=lambda q: q["date"])}
    try:
        c = requests.get(RDE_CONTENT, timeout=30, headers={"User-Agent": "Mozilla/5.0"}).json()
        it = c.get("interactive") or {}
        out["release"] = ((it.get("latestRelease") or {}).get("info") or "").strip()
        out["update"] = ((it.get("bullets") or {}).get("title") or "").strip()
        out["bullets"] = [b.strip() for b in (it.get("bullets") or {}).get("items") or []]
    except Exception as e:                         # noqa: BLE001
        log.warning("RDE 說明文字取得失敗（%s）", e)
    return out


# ---------------------------------------------------------------------------
# 貨幣市場基金（MMF）
# ---------------------------------------------------------------------------
# 三個免費官方來源（ICI 週資料可免費瀏覽，但網站擋自動下載；Crane Data 是付費的）：
#   SEC Money Market Fund Statistics  依 Form N-MFP 彙整，月資料、約晚 6 週：
#       各類型淨資產、淨流量、7 日淨收益率（Government／Treasury／Prime／Tax Exempt）
#   OFR U.S. Money Market Fund Monitor（API）  同樣來自 N-MFP、約晚 2 週：
#       持有部位（公債、機構債、回購、銀行相關、其他），回購再拆交易對手（Fed、FICC…）
#   FDIC 全國儲蓄存款利率：2021-04 起的 SNDR 走 FRED 主流程（config/liquidity.yaml），
#       之前停發的 SAVNRNJ 固定存在 config/fdic_savings_legacy.json
SEC_MMF_PAGE = "https://www.sec.gov/data-research/investment-management-data/money-market-fund-statistics"
OFR_API = "https://data.financialresearch.gov/v1/series/timeseries?mnemonic={m}"
OFR_MMF = {"treasury": "MMF-MMF_T_TOT-M", "agency": "MMF-MMF_AG_TOT-M", "repo": "MMF-MMF_RP_TOT-M",
           "bank": "MMF-MMF_BRA_TOT-M", "other": "MMF-MMF_OA_TOT-M", "total": "MMF-MMF_TOT-M",
           "rp_fed": "MMF-MMF_RP_wFR-M", "rp_ficc": "MMF-MMF_RP_wFICC-M",
           "rp_us": "MMF-MMF_RP_wDFI-M", "rp_foreign": "MMF-MMF_RP_wFFI-M", "rp_other": "MMF-MMF_RP_wOCP-M"}


def _xlsx_sheets(blob: bytes, want: set) -> dict:
    """
    只用標準函式庫讀 .xlsx 指定工作表 → {name: [[儲存格值…], …]}。
    SEC 的檔案一個月一份、約 1MB，為這一個用途加一個套件依賴不划算。
    數字回 float、文字回 str；日期是 Excel 序號（1900 系統），由呼叫端轉。
    """
    import io
    import zipfile
    from xml.etree import ElementTree as ET
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    t_tag = "{%s}t" % ns["m"]
    z = zipfile.ZipFile(io.BytesIO(blob))
    ss = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
            ss.append("".join(t.text or "" for t in si.iter(t_tag)))
    rmap = {r.get("Id"): r.get("Target")
            for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    out = {}
    for sh in ET.fromstring(z.read("xl/workbook.xml")).find("m:sheets", ns):
        name = sh.get("name")
        if name not in want:
            continue
        tgt = rmap[sh.get("{%s}id" % ns["r"])].lstrip("/")
        tgt = tgt if tgt.startswith("xl/") else "xl/" + tgt
        rows = []
        for row in ET.fromstring(z.read(tgt)).iter("{%s}row" % ns["m"]):
            vals = {}
            for c in row.findall("m:c", ns):
                col = 0
                for ch in re.match(r"[A-Z]+", c.get("r")).group(0):
                    col = col * 26 + ord(ch) - 64
                v = c.find("m:v", ns)
                if v is None:
                    isv = c.find("m:is", ns)
                    vals[col] = "".join(t.text or "" for t in isv.iter(t_tag)) if isv is not None else None
                    continue
                typ = c.get("t")
                vals[col] = (ss[int(v.text)] if typ == "s"
                             else v.text if typ in ("str", "inlineStr") else float(v.text))
            if vals:
                rows.append([vals.get(i) for i in range(1, max(vals) + 1)])
        out[name] = rows
    return out


def _xl_month(serial) -> str | None:
    if not isinstance(serial, float):
        return None
    return (dt.date(1899, 12, 30) + dt.timedelta(days=int(serial))).isoformat()[:7]


def _sec_table(rows: list, key_cols: int) -> dict:
    """SEC 表格（第一列是月份）→ {('Government','Treasury'): {'2026-08': v, …}}。"""
    if not rows:
        return {}
    months = [_xl_month(c) for c in rows[0]]
    out = {}
    for r in rows[1:]:
        if not r or not isinstance(r[0], str) or r[0].startswith("Return"):
            continue
        key = tuple(r[:key_cols])
        out[key] = {m: r[i] for i, m in enumerate(months)
                    if m and i < len(r) and isinstance(r[i], float)}
    return out


def sec_mmf() -> dict:
    """
    SEC 最新一份 supporting data（xlsx）→ 月資料（十億美元／%）：
      assets  {month: {gov, treasury, prime_inst, prime_retail, taxex, total}}  淨資產（Tab.2.1）
      flows   同上的淨流量（Tab.3.9）
      yields  {month: {gov, treasury, prime}}  資產加權 7 日淨收益率（Tab.4.3H＋4.3）
    """
    from .sec import USER_AGENT
    hdr = {"User-Agent": USER_AGENT}
    page = requests.get(SEC_MMF_PAGE, timeout=40, headers=hdr)
    page.raise_for_status()
    m = re.search(r'href="(/files/investment/mmf-statistics-supporting-data-(\d{2})-(\d{4})\.xlsx)"', page.text)
    if not m:
        raise ValueError("SEC 頁面找不到 supporting data 連結")
    url = "https://www.sec.gov" + m.group(1)
    blob = requests.get(url, timeout=90, headers=hdr)
    blob.raise_for_status()
    sh = _xlsx_sheets(blob.content, {"Tab.2.1", "Tab.3.9", "Tab.4.3", "Tab.4.3H", "Tab.5.1", "Tab.5.1H"})
    keymap = {("Government", "Government"): "gov", ("Government", "Treasury"): "treasury",
              ("Prime", "Institutional"): "prime_inst", ("Prime", "Retail"): "prime_retail",
              ("Prime", "Subtotal"): "prime", ("Tax Exempt", "Subtotal"): "taxex", ("Total", "Total"): "total"}

    def by_month(tab):
        out: dict = {}
        for key, ser in _sec_table(sh.get(tab) or [], 2).items():
            k = keymap.get(key)
            if k:
                for mo, v in ser.items():
                    out.setdefault(mo, {})[k] = v
        return out
    assets, flows = by_month("Tab.2.1"), by_month("Tab.3.9")
    def by_type(hist_tab, tab):
        """
        Government／Treasury／Prime 三條：2016-10 以前用 *H 表（Prime 不分機構／零售），
        之後 Prime 用機構型與零售型的淨資產加權（SEC 2016 年後才分開申報）。
        """
        out: dict = {}
        for (name,), ser in _sec_table(sh.get(hist_tab) or [], 1).items():
            k = {"Government": "gov", "Treasury": "treasury", "Prime": "prime"}.get(name)
            for mo, v in (ser.items() if k else []):
                out.setdefault(mo, {})[k] = v
        for mo, v in by_month(tab).items():
            y = {"gov": v.get("gov"), "treasury": v.get("treasury")}
            a = assets.get(mo) or {}
            wi, wr = a.get("prime_inst") or 0, a.get("prime_retail") or 0
            if v.get("prime_inst") and v.get("prime_retail") and wi + wr:
                y["prime"] = (v["prime_inst"] * wi + v["prime_retail"] * wr) / (wi + wr)
            out.setdefault(mo, {}).update({k: x for k, x in y.items() if x is not None})
        return out
    # 7 日淨收益率（%）；WAM 加權平均到期天數（天，Tab.5.1：資產加權）
    return {"url": url, "report": f"{m.group(3)}-{m.group(2)}", "assets": assets, "flows": flows,
            "yields": by_type("Tab.4.3H", "Tab.4.3"), "wam": by_type("Tab.5.1H", "Tab.5.1")}


def ofr_mmf() -> dict:
    """OFR MMF Monitor：月底持有部位（十億美元），{month: {treasury, agency, repo, …}}。"""
    out: dict = {}
    for k, mn in OFR_MMF.items():
        for d, v in _get(OFR_API.format(m=mn)) or []:
            if v is not None:
                out.setdefault(d[:7], {})[k] = v / 1e9
    return {m: v for m, v in sorted(out.items()) if len(v) == len(OFR_MMF)}


# ---------------------------------------------------------------------------
# 每季再融資（QRA）：借款估計＋本站推算的 coupon 淨發行（每次更新自動重算）
# ---------------------------------------------------------------------------
QRA_PAGE = ("https://home.treasury.gov/policy-issues/financing-the-government/"
            "quarterly-refunding/most-recent-quarterly-refunding-documents")
_MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July",
                                       "August", "September", "October", "November", "December"], 1)}
_EST_RE = re.compile(r"During the ([A-Z][a-z]+)\W+([A-Z][a-z]+) (\d{4}) quarter, Treasury expects to borrow "
                     r"\$([\d,]+) billion in privately-held net marketable debt, assuming an end-of-"
                     r"([A-Z][a-z]+) cash balance of \$([\d,]+) billion")
_NEXT_RE = re.compile(r"next quarterly refunding announcement will take place on [A-Z][a-z]+, "
                      r"([A-Z][a-z]+) (\d{1,2}), (\d{4})")
# 再融資聲明（Quarterly Refunding Statement）：日期、coupon 指引原句、買回額度
_STMT_DATE_RE = re.compile(r"Quarterly Refunding Statement of [^|]{0,120}?([A-Z][a-z]+ \d{1,2}, \d{4}) WASHINGTON")
_GUIDE_RE = re.compile(r"((?:Based on [^.]{0,80}, )?Treasury (?:anticipates|intends|expects|plans)[^.]{0,200}"
                       r"(?:coupon|FRN)[^.]{0,160}auction sizes[^.]*\.)")
_BB_RE = re.compile(r"purchase up to \$([\d.,]+) billion[^.]{0,80}?liquidity support"
                    r"(?:[^.]{0,40}?up to \$([\d.,]+) billion[^.]{0,80}?cash management)?")


def refunding_statement(ids: list[str]) -> dict:
    """最新一次再融資聲明：{date, url, guidance_en, bb_liq, bb_cash}（十億美元）。找不到回空。"""
    for sid in ids:
        url = f"https://home.treasury.gov/news/press-releases/{sid}"
        try:
            t = _page_text(url)
        except Exception:                          # noqa: BLE001
            continue
        m = _STMT_DATE_RE.search(t)
        if not m:
            continue
        out = {"date": dt.datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat(), "url": url}
        g = _GUIDE_RE.search(t)
        if g:
            out["guidance_en"] = g.group(1).strip()
        b = _BB_RE.search(t)
        if b:
            out["bb_liq"] = float(b.group(1).replace(",", ""))
            if b.group(2):
                out["bb_cash"] = float(b.group(2).replace(",", ""))
        return out
    return {}


def _page_text(url: str) -> str:
    import html as _html
    r = requests.get(url, timeout=40, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    t = re.sub(r"<script.*?</script>", " ", r.text, flags=re.S)
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", t)))


def _coupon_sizes(start: str) -> list[dict]:
    """
    Note／Bond 每一場的規模（含 TIPS、FRN），不篩得標殖利率——FRN 沒有 high_yield，
    coupon_auctions() 為了拍賣卡片會把它濾掉，這裡算發行量不能少掉它。
    """
    rows = _fiscal_rows("v1/accounting/od/auctions_query",
                        f"security_type:in:(Note,Bond),issue_date:gte:{start}", "issue_date")
    out = []
    for a in rows:
        n = normalize_fiscal_auction(a)
        if n["issue"] and n["offering"]:
            out.append(n)
    return out


def qra_estimate(today: dt.date | None = None) -> dict:
    """
    最新一次再融資的財政部原文數字（本季私人持有淨借款、季底現金假設、下一次公告日），
    與本站推算的本季 coupon 淨發行：
      毛發行  本季交割的 coupon 拍賣：已公告／已結標用實際規模，其餘用暫定排程 × 同天期最近一場規模
      到期    本季到期的 coupon（MSPD 表三，取本季開始前最後一個月底）扣掉 Fed SOMA 持有＝私人持有到期
      淨發行  毛發行 − 私人持有到期；T-Bills 隱含淨發行＝淨借款 − coupon 淨發行（未計買回）
    """
    from . import clock
    today = today or clock.today()
    page = requests.get(QRA_PAGE, timeout=40, headers={"User-Agent": "Mozilla/5.0"})
    page.raise_for_status()
    ids = list(dict.fromkeys(re.findall(r"/news/press-releases/(sb\d+)", page.text)))
    ests, nxt, est_url, est_date = [], None, "", ""
    for sid in ids:
        url = f"https://home.treasury.gov/news/press-releases/{sid}"
        try:
            t = _page_text(url)
        except Exception as e:                     # noqa: BLE001
            log.warning("QRA 新聞稿 %s 取得失敗（%s）", sid, e)
            continue
        found = _EST_RE.findall(t)
        if found and not ests:
            ests, est_url = found, url
            m = re.search(r"Borrowing Estimates\s+([A-Z][a-z]+ \d{1,2}, \d{4})", t)
            if m:
                est_date = dt.datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat()
        n = _NEXT_RE.search(t)
        if n and not nxt:
            nxt = dt.date(int(n.group(3)), _MONTHS[n.group(1)], int(n.group(2))).isoformat()
    if not ests:
        raise ValueError("QRA 頁面找不到借款估計新聞稿")
    quarters = []
    for m1, m2, y, bor, cm, cash in ests:
        y = int(y)
        q0 = dt.date(y, _MONTHS[m1], 1)
        e_m = _MONTHS[m2]
        q1 = (dt.date(y + (e_m == 12), e_m % 12 + 1, 1) - dt.timedelta(days=1))
        quarters.append({"start": q0.isoformat(), "end": q1.isoformat(),
                         "quarter": f"{y} Q{(q0.month - 1) // 3 + 1}（{q0.month}–{e_m} 月）",
                         "borrowing": float(bor.replace(",", "")), "cash_end": float(cash.replace(",", "")),
                         "cash_end_date": q1.isoformat()})
    iso = today.isoformat()
    cur = next((q for q in quarters if q["start"] <= iso <= q["end"]), quarters[-1])
    out = {**cur, "date": est_date, "url": est_url, "next": nxt}
    try:
        out["statement"] = refunding_statement(ids)
    except Exception as e:                         # noqa: BLE001
        log.warning("再融資聲明解析失敗（%s）", e)
    # ---- coupon 毛發行 ----
    hist = _coupon_sizes((dt.date.fromisoformat(cur["start"]) - dt.timedelta(days=400)).isoformat())
    last: dict = {}
    for a in sorted(hist, key=lambda r: r["date"] or r["issue"]):
        last[(a["term"], a["tips"], a["frn"], a["reopening"])] = a["offering"]
        last[(a["term"], a["tips"], a["frn"])] = a["offering"]
    known = [a for a in hist if cur["start"] <= a["issue"] <= cur["end"]]
    gross = sum(a["offering"] for a in known)
    seen = {(a["issue"], a["term"], a["tips"], a["frn"]) for a in known}
    r = requests.get(TENTATIVE_AUCTIONS, timeout=40, headers=UA)
    r.raise_for_status()
    for it in _xml_items(r.text, "AuctionCalendarDate"):
        st = it.get("SettlementDate") or ""
        if not (cur["start"] <= st <= cur["end"]) or it.get("SecurityType") not in ("NOTE", "BOND"):
            continue
        key = (it.get("SecurityTermWeekYear") or "", it.get("TIPS") == "Y", it.get("FloatingRate") == "Y")
        if (st, *key) in seen:
            continue
        size = last.get(key + (it.get("ReOpeningIndicator") == "Y",)) or last.get(key)
        gross += size or 0
    # ---- 私人持有到期 ----
    q0 = dt.date.fromisoformat(cur["start"])
    rec = (q0 - dt.timedelta(days=1)).isoformat()
    mrows = _fiscal_rows("v1/debt/mspd/mspd_table_3_market",
                         f"record_date:eq:{rec},maturity_date:gte:{cur['start']},maturity_date:lte:{cur['end']}")
    mat = {}
    for m in mrows:
        if (m.get("security_class1_desc") or "") in ("Notes", "Bonds", "Inflation-Protected Securities",
                                                     "Floating Rate Notes"):
            v = _f(m.get("outstanding_amt"))
            if v:
                mat[m.get("security_class2_desc") or ""] = mat.get(m.get("security_class2_desc") or "", 0) + v / 1e3
    soma = {}
    try:
        sd = [d for d in soma_dates() if d <= cur["start"]]
        if sd:
            js = _get(f"{NYF}/tsy/get/asof/{sd[-1]}.json")
            for h in ((js or {}).get("soma") or {}).get("holdings") or []:
                soma[h.get("cusip")] = (_f(h.get("parValue")) or 0) / 1e9
    except Exception as e:                         # noqa: BLE001
        log.warning("SOMA 逐券持有取得失敗（%s），到期量不扣 Fed 持有", e)
    maturing = sum(max(0.0, v - soma.get(c, 0.0)) for c, v in mat.items())
    if not mrows:
        raise ValueError(f"MSPD {rec} 尚無資料")
    out.update({"gross_coupon": round(gross, 1), "coupon_maturing": round(maturing, 1),
                "net_coupon": round(gross - maturing, 1), "mspd_date": rec})
    return out


# ---------------------------------------------------------------------------
# 期限溢酬模型（2026-10）：紐約聯儲 ACM、舊金山聯儲（Christensen–Rudebusch）
# Kim-Wright 走 FRED（THREEFYTP10），不在這裡
# ---------------------------------------------------------------------------
ACM_XLS = "https://www.newyorkfed.org/medialibrary/media/research/data_indicators/ACMTermPremium.xls"
SF_TP_XLSX = "https://www.frbsf.org/wp-content/uploads/FRBSF_Term_Web_Chart_Data.xlsx"


def term_premia(years: int = 11) -> dict:
    """
    10 年期期限溢酬日資料（%）：{"acm": [{date, value}], "sf": [{date, value}],
    "sf_exp": [{date, value}]（舊金山聯儲同一模型的 10 年預期短率平均）}。
    ACM 只有舊版 .xls（約 10MB，「ACM Daily」工作表、ACMTP10 欄），用 xlrd 讀；
    舊金山聯儲的網站圖表資料是 .xlsx（Ten_year_decomposition 工作表），用標準函式庫讀。
    """
    from . import clock
    start = dt.date(clock.today().year - years, 1, 1).isoformat()
    out: dict = {}
    try:
        import xlrd
        blob = None
        for i_try in range(3):                     # 約 10MB，偶爾讀到一半逾時，重試即可
            try:
                r = requests.get(ACM_XLS, timeout=(20, 240),
                                 headers={"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/130.0"})
                r.raise_for_status()
                blob = r.content
                break
            except requests.RequestException:
                if i_try == 2:
                    raise
        sh = xlrd.open_workbook(file_contents=blob).sheet_by_name("ACM Daily")
        hdr = [str(c).strip() for c in sh.row_values(0)]
        i = hdr.index("ACMTP10")
        rows = []
        for n in range(1, sh.nrows):
            row = sh.row_values(n)
            try:
                d = dt.datetime.strptime(str(row[0]).strip(), "%d-%b-%Y").date().isoformat()
            except ValueError:
                continue
            v = _f(row[i])
            if d >= start and v is not None:
                rows.append({"date": d, "value": round(v, 4)})
        out["acm"] = rows
    except Exception as e:                         # noqa: BLE001
        log.warning("ACM 期限溢酬取得失敗（%s）", e)
    try:
        r = requests.get(SF_TP_XLSX, timeout=90, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        rows = _xlsx_sheets(r.content, {"Ten_year_decomposition"}).get("Ten_year_decomposition") or []
        hdr = [str(c or "").strip() for c in rows[0]]
        it, ie = hdr.index("ZCTERM10YR"), hdr.index("AVGEXP10YR")
        tp, ex = [], []
        for row in rows[1:]:
            if not row or not isinstance(row[0], float):
                continue
            d = (dt.date(1899, 12, 30) + dt.timedelta(days=int(row[0]))).isoformat()
            if d < start:
                continue
            if it < len(row) and isinstance(row[it], float):
                tp.append({"date": d, "value": round(row[it], 4)})
            if ie < len(row) and isinstance(row[ie], float):
                ex.append({"date": d, "value": round(row[ie], 4)})
        out["sf"], out["sf_exp"] = tp, ex
    except Exception as e:                         # noqa: BLE001
        log.warning("舊金山聯儲期限溢酬取得失敗（%s）", e)
    if not out.get("acm") and not out.get("sf"):
        raise ValueError("兩個期限溢酬模型都取得失敗")
    return out


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
    buyback_schedule, buyback_reactions, h41, bank_assets, rde, sec_mmf, ofr_mmf, failed}。
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
    for key, fn in (("bank_assets", bank_assets), ("rde", rde), ("sec_mmf", sec_mmf),
                    ("ofr_mmf", ofr_mmf)):
        try:
            out[key] = fn()
        except Exception as e:                     # noqa: BLE001
            log.warning("%s 取得失敗（%s）", key, e)
            out[key] = [] if key == "bank_assets" else {}
            failed.append(key)
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
    try:
        out["term_premia"] = term_premia()
    except Exception as e:                         # noqa: BLE001
        log.warning("期限溢酬模型取得失敗（%s）", e)
        out["term_premia"] = {}
        failed.append("term_premia")
    # 全球 10 年期公債（日資料）：德國 Bundesbank、英國 BoE、日本財務省；各自獨立，一個失敗不影響其他
    out["global10"] = {}
    for key, fn in (("de", bund_10y), ("uk", gilt_10y), ("jp", jgb_10y), ("ca", boc_10y),
                    ("fr", lambda e: cnbc_daily("FR10Y-FR", e)), ("au", lambda e: cnbc_daily("AU10Y-AU", e)),
                    ("cn", cgb_10y)):
        try:
            out["global10"][key] = fn(end)
        except Exception as e:                     # noqa: BLE001
            log.warning("%s 10 年期日資料取得失敗（%s）", key.upper(), e)
    if len(out["global10"]) < 7:
        failed.append("global10")
    try:
        out["qra"] = qra_estimate(end)
    except Exception as e:                         # noqa: BLE001
        log.warning("QRA 借款估計取得失敗（%s）", e)
        out["qra"] = {}
        failed.append("qra")
    _with_last_good(out, failed, state_dir / "treasury_cache.json", end.isoformat())
    out["failed"] = failed
    return out


# 週／月頻、改版少的來源：抓取失敗或回空時沿用上一次成功的版本，頁面不會整區空白
# （畫面上各數字本來就標資料日期，沿用舊值時日期自然是舊的）。只在內容有變時才
# 寫檔，避免每次更新都產生一個大的 state 差異。
LAST_GOOD_KEYS = ("h41", "bank_assets", "rde", "sec_mmf", "ofr_mmf", "rmp_schedule", "qra", "term_premia", "global10",
                  "mspd", "fed_bills", "buybacks", "buyback_schedule", "auctions", "soma")


def _with_last_good(out: dict, failed: list, path: pathlib.Path, today: str) -> None:
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    changed = False
    for k in LAST_GOOD_KEYS:
        v = out.get(k)
        empty = not v or (isinstance(v, dict) and not any(v.values()))
        if k in failed or empty:
            if k in cache:
                out[k] = cache[k]["value"]
                out.setdefault("stale", {})[k] = cache[k]["saved"]
                log.warning("%s 沿用 %s 的最後成功版本", k, cache[k]["saved"])
        elif (cache.get(k) or {}).get("value") != json.loads(json.dumps(v)):
            cache[k] = {"saved": today, "value": v}
            changed = True
    if changed:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        except OSError:
            pass


# ---------------------------------------------------------------------------
# 全球 10 年期公債殖利率（日資料，2026-10）：取代 OECD 月均（落後約一個月）
#   德國：Bundesbank 上市聯邦證券利率期限結構（Svensson），剩餘 10 年，每日
#   英國：Bank of England 名目平價殖利率 10 年（IUDMNPY），每日，約晚 2–3 個營業日
#   日本：財務省 JGB 各天期利率（當月檔＋歷史檔），10 年，每日
#   回傳 [{date, value}]，從去年 12 月起（算 YTD 要去年最後一筆）
# ---------------------------------------------------------------------------
BUND_URL = ("https://api.statistiken.bundesbank.de/rest/data/BBSIS/"
            "D.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A?format=csv&lang=en&startPeriod={start}")
GILT_URL = ("https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp?csv.x=yes"
            "&Datefrom={start}&Dateto=now&SeriesCodes=IUDMNPY&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N")
JGB_CUR = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv"
JGB_ALL = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv"


def _g_start(end: dt.date) -> dt.date:
    return dt.date(end.year - 1, 12, 1) if end.month > 1 else dt.date(end.year - 2, 12, 1)


def _g_get(url: str) -> str:
    for k in range(3):
        try:
            r = requests.get(url, timeout=(20, 90), headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            return r.content.decode("utf-8-sig", "ignore")
        except Exception:                          # noqa: BLE001
            if k == 2:
                raise
    return ""


def bund_10y(end: dt.date) -> list[dict]:
    start = min(_g_start(end), end - dt.timedelta(days=400)).isoformat()
    out = []
    for line in _g_get(BUND_URL.format(start=start)).splitlines():
        p = [x.strip('"') for x in line.split(",")]
        if len(p) >= 2 and re.match(r"\d{4}-\d{2}-\d{2}$", p[0]):
            try:
                out.append({"date": p[0], "value": float(p[1])})
            except ValueError:
                pass                               # 假日是「.」
    if not out:
        raise ValueError("Bundesbank 回傳沒有資料")
    return out


def gilt_10y(end: dt.date) -> list[dict]:
    st = min(_g_start(end), end - dt.timedelta(days=400))
    out = []
    for line in _g_get(GILT_URL.format(start=st.strftime("%d/%b/%Y"))).splitlines():
        p = [x.strip() for x in line.split(",")]
        if len(p) >= 2:
            try:
                d = dt.datetime.strptime(p[0], "%d %b %Y").date()
                out.append({"date": d.isoformat(), "value": float(p[1])})
            except ValueError:
                pass
    if not out:
        raise ValueError("BoE 回傳沒有資料（可能被阻擋）")
    return sorted(out, key=lambda r: r["date"])


def _jgb_parse(text: str) -> list[dict]:
    rows, col = [], None
    for line in text.splitlines():
        p = [x.strip() for x in line.split(",")]
        if p and p[0] == "Date":
            col = p.index("10Y") if "10Y" in p else None
            continue
        if col is None or len(p) <= col:
            continue
        m = re.match(r"(\d{4})/(\d{1,2})/(\d{1,2})$", p[0])
        if not m:
            continue
        try:
            rows.append({"date": dt.date(int(m[1]), int(m[2]), int(m[3])).isoformat(), "value": float(p[col])})
        except ValueError:
            pass                                   # 「-」＝沒有報價
    return rows


def jgb_10y(end: dt.date) -> list[dict]:
    start = min(_g_start(end), end - dt.timedelta(days=400)).isoformat()
    hist = [r for r in _jgb_parse(_g_get(JGB_ALL)) if r["date"] >= start]
    try:
        cur = _jgb_parse(_g_get(JGB_CUR))          # 當月（歷史檔只到上個月底）
    except Exception as e:                         # noqa: BLE001
        log.warning("JGB 當月檔取得失敗（%s），只用歷史檔", e)
        cur = []
    by = {r["date"]: r for r in hist + cur}
    if not by:
        raise ValueError("財務省 JGB 檔案沒有資料")
    return [by[d] for d in sorted(by)]

# 加拿大：Bank of Canada Valet（BD.CDN.10YR.DQ.YLD，基準 10 年期公債殖利率，每日）
BOC_URL = "https://www.bankofcanada.ca/valet/observations/BD.CDN.10YR.DQ.YLD/csv?start_date={start}"


def boc_10y(end: dt.date) -> list[dict]:
    start = min(_g_start(end), end - dt.timedelta(days=400)).isoformat()
    out = []
    for line in _g_get(BOC_URL.format(start=start)).splitlines():
        p = [x.strip().strip('"') for x in line.split(",")]
        if len(p) >= 2 and re.match(r"\d{4}-\d{2}-\d{2}$", p[0]) and p[1]:
            try:
                out.append({"date": p[0], "value": float(p[1])})
            except ValueError:
                pass
    if not out:
        raise ValueError("Bank of Canada 回傳沒有資料")
    return out


# 法國、澳洲：沒有可直接取用的官方日資料 API（澳洲央行擋自動抓取、ECB 沒有法國日序列），
# 改用 CNBC 的每日收盤報價。已與 OECD 月均比對：法國差約 1bp、澳洲約 2bp。
# CNBC 會在週末與假日補一筆與前一日相同的值，要濾掉，否則 DTD 會變成 0。
CNBC_DAILY = "https://ts-api.cnbc.com/harmony/app/charts/1Y.json?symbol={sym}"


def cnbc_daily(sym: str, end: dt.date) -> list[dict]:
    start = min(_g_start(end), end - dt.timedelta(days=400)).isoformat()
    js = json.loads(_g_get(CNBC_DAILY.format(sym=sym)))
    out, prev = [], None
    for b in ((js.get("barData") or {}).get("priceBars") or []):
        t = str(b.get("tradeTime") or "")
        try:
            d = dt.date(int(t[:4]), int(t[4:6]), int(t[6:8]))
            ohlc = tuple(float(b[k]) for k in ("open", "high", "low", "close"))
        except (ValueError, KeyError, TypeError):
            continue
        if d.weekday() >= 5 or d.isoformat() < start or ohlc == prev:
            prev = ohlc
            continue
        prev = ohlc
        out.append({"date": d.isoformat(), "value": ohlc[3]})
    if not out:
        raise ValueError(f"CNBC {sym} 回傳沒有資料")
    return out

# 中國：財政部「中國國債收益率曲線」（中債估值中心編製）10 年，每日。
# 不用 CNBC：它的中國報價是零星成交價，單日跳 5～8bp，而且調休的週六上班日會被當成週末濾掉。
# 這個查詢一次最多一年。
CGB_URL = ("https://yield.chinabond.com.cn/cbweb-czb-web/czb/historyQuery?startDate={a}&endDate={b}"
           "&gjqx=10&locale=cn_ZH&qxmc=1")


def cgb_10y(end: dt.date) -> list[dict]:
    a = (end - dt.timedelta(days=364)).isoformat()
    js = json.loads(_g_get(CGB_URL.format(a=a, b=end.isoformat())))
    out = []
    for r in js.get("heList") or []:
        try:
            out.append({"date": str(r["workTime"])[:10], "value": float(r["tenYear"])})
        except (KeyError, TypeError, ValueError):
            continue
    if not out:
        raise ValueError("財政部國債收益率曲線回傳沒有資料")
    return sorted(out, key=lambda r: r["date"])
