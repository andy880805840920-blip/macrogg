"""
SEC EDGAR XBRL 擷取 — 科技巨頭的資本支出、營運現金流、營收與發債。

為什麼用 SEC 而不是財經網站
--------------------------
這幾個數字原本是手動維護的（一季更新一次，很容易忘記或填錯）。
SEC 的 XBRL API 是**公司自己申報的原始標記**，免費、無需金鑰、
每季自動更新，而且每一筆都能回溯到具體的 10-Q 文件編號。

    https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json

三個必須處理的坑
----------------
1. **10-Q 的現金流量表多半是「年初至今累計」，不是單季。**
   例如亞馬遜 Q3 的營運現金流是 1～9 月的累計數。直接拿來當單季會
   高估兩三倍。這裡的做法是：優先取本來就是單季（期間 80–100 天）的
   標記；沒有的話，用同一會計年度內相鄰兩筆累計值相減還原單季。

2. **各家用的標記不一樣。** 亞馬遜的資本支出標 PaymentsToAcquire
   ProductiveAssets，其餘四家標 PaymentsToAcquirePropertyPlantAndEquipment。
   所以每個指標都準備一組候選標記，依序嘗試。

3. **會計年度起點不同。** 微軟 6 月底、甲骨文 5 月底、其餘為曆年。
   所以「最新一季」對各家而言是不同的期間，畫面上要標出各自的期末日，
   不能假裝是同一季。

抓取失敗時退回 config 的手動值，並在畫面上標示未驗證。
"""

from __future__ import annotations

import os
import re
import time
import json
import html as html_mod
import logging
import datetime as dt

import requests

log = logging.getLogger(__name__)

CONCEPT_URL = ("https://data.sec.gov/api/xbrl/companyconcept/"
               "CIK{cik:010d}/us-gaap/{tag}.json")
# 近期申報清單（表格類型、日期、文件）。用來補 XBRL 的時效缺口：
# 10-Q 是季末後約 45 天才申報，所以一筆新發債最久要等 135 天才會進到
# 季報數字裡。發債本身則有即時的申報義務，這個端點當天就看得到。
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
# 申報文件的目錄（accession 去掉連字號當路徑）
ARCHIVE_DOC = ("https://www.sec.gov/Archives/edgar/data/{cik}/"
               "{acc_nodash}/{doc}")

# 代表「這家公司在發債」的表格類型。
#   424B2 / 424B5  公開說明書補充——債券發行文件本身，定價當日申報
#   FWP            自由書寫公開說明書（條件清單），同樣是定價當日
#   8-K            只在項目含 2.03（產生直接財務義務）或 1.01（重大確定協議）時才算
DEBT_FORMS = {"424B2", "424B5", "424B3", "FWP"}
DEBT_8K_ITEMS = ("2.03", "1.01")
# 只看最近這麼多天的申報。超過這個範圍的多半已經反映在最新一季的財報裡。
RECENT_DAYS = 120

# SEC 要求帶可聯絡的 User-Agent，否則會擋。
# 可用環境變數覆寫成自己的信箱（SEC 的使用規範建議這麼做）。
USER_AGENT = os.environ.get(
    "SEC_USER_AGENT", "macro-dashboard (contact: dashboard@example.com)")

TIMEOUT = 30
MAX_RETRIES = 3
THROTTLE = 0.15          # SEC 限制每秒 10 次請求

# 每個指標的候選標記，依序嘗試第一個有資料的
METRIC_TAGS = {
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",              # Amazon
        "PaymentsToAcquirePropertyPlantAndEquipmentExcludingCapitalizedInterest",
    ],
    "ocf": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
    ],
    "debt_issued": [
        "ProceedsFromIssuanceOfLongTermDebt",
        "ProceedsFromIssuanceOfSeniorLongTermDebt",
        "ProceedsFromIssuanceOfUnsecuredDebt",
        "ProceedsFromNotesPayable",
    ],
}


class SecClient:
    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
        })
        self.failed: list[tuple[str, str]] = []

    # ------------------------------------------------------------------
    def concept(self, cik: int, tag: str) -> dict | None:
        url = CONCEPT_URL.format(cik=cik, tag=tag)
        last = None
        for attempt in range(MAX_RETRIES):
            try:
                r = self.session.get(url, timeout=TIMEOUT)
                if r.status_code == 404:      # 這家沒用這個標記，正常
                    return None
                r.raise_for_status()
                time.sleep(THROTTLE)
                return r.json()
            except Exception as e:            # noqa: BLE001
                last = e
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1.0 * (attempt + 1))
        self.failed.append((f"SEC {tag}", str(last)))
        return None

    # ------------------------------------------------------------------
    def metric(self, cik: int, metric: str) -> list[dict]:
        """
        回傳該指標的單季序列（時間升冪），每筆 {end, val, form, accn, tag}。

        **必須比較所有候選標記，取資料最新的那個**，不能拿第一個有資料的就走。
        公司會換標記，而舊標記的歷史資料還留在 XBRL 裡：亞馬遜的
        PaymentsToAcquirePropertyPlantAndEquipment 停在 2017-03-31，
        現行用的是 PaymentsToAcquireProductiveAssets。取第一個有資料的
        會抓到停用九年的舊值，而且畫面上看起來像正常數字。
        """
        best: list[dict] = []
        best_end = ""
        for tag in METRIC_TAGS.get(metric, []):
            js = self.concept(cik, tag)
            if not js:
                continue
            rows = quarterly_series(js)
            if not rows:
                continue
            if rows[-1]["end"] > best_end:
                best_end = rows[-1]["end"]
                for r in rows:
                    r["tag"] = tag
                best = rows
        return best

    # ------------------------------------------------------------------
    def _json(self, url: str, label: str) -> dict | None:
        last = None
        for attempt in range(MAX_RETRIES):
            try:
                r = self.session.get(url, timeout=TIMEOUT)
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                time.sleep(THROTTLE)
                return r.json()
            except Exception as e:                 # noqa: BLE001
                last = e
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1.0 * (attempt + 1))
        self.failed.append((label, str(last)))
        return None

    # ------------------------------------------------------------------
    def debt_filings(self, cik: int, days: int = RECENT_DAYS) -> list[dict]:
        """
        近期的發債相關申報。回傳 [{form, date, items, doc_url, accession}]，時間降冪。

        為什麼需要這個
        --------------
        XBRL 只到 10-Q，而 10-Q 是季末後約 45 天才申報——一筆七月的發債
        最久要等到十一月才會出現在數字裡。但發債本身當天就要申報：
        424B2／424B5 是債券發行文件本身，8-K 項目 2.03 是「產生直接財務義務」。

        防禦性寫法
        ----------
        submissions 端點的欄位名稱無法在離線環境驗證（檔案太大、
        查詢介面被 robots.txt 擋）。所以這裡把缺欄位一律當成
        「解析不出來」處理：記錄並回傳空清單，畫面上該區塊就不顯示。
        寧可少一個區塊，也不要憑對資料結構的假設印東西出去。
        """
        js = self._json(SUBMISSIONS_URL.format(cik=cik), f"SEC submissions {cik}")
        if not js:
            return []
        recent = ((js.get("filings") or {}).get("recent")) or {}
        forms = recent.get("form")
        dates = recent.get("filingDate")
        if not isinstance(forms, list) or not isinstance(dates, list):
            log.warning("SEC submissions 的欄位與預期不符（CIK %s），略過發債申報", cik)
            self.failed.append((f"SEC submissions {cik}", "欄位結構與預期不符"))
            return []

        items = recent.get("items") or []
        accs = recent.get("accessionNumber") or []
        docs = recent.get("primaryDocument") or []
        descs = recent.get("primaryDocDescription") or []

        def _at(arr, i):
            return arr[i] if isinstance(arr, list) and i < len(arr) else ""

        cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
        out = []
        for i, form in enumerate(forms):
            date = _at(dates, i)
            if not date or date < cutoff:
                continue
            it = _at(items, i) or ""
            if form in DEBT_FORMS:
                kind = "offering"
            elif form.startswith("8-K") and any(x in it for x in DEBT_8K_ITEMS):
                kind = "event"
            else:
                continue
            acc = _at(accs, i)
            doc = _at(docs, i)
            url = ""
            if acc and doc:
                url = ARCHIVE_DOC.format(cik=cik, acc_nodash=acc.replace("-", ""),
                                         doc=doc)
            out.append({"form": form, "date": date, "items": it,
                        "accession": acc, "doc_url": url,
                        "desc": _at(descs, i), "kind": kind})
        out.sort(key=lambda x: x["date"], reverse=True)
        return out

    # ------------------------------------------------------------------
    def offering_amount(self, doc_url: str) -> float | None:
        """
        從公開說明書補充的封面抓總發行金額（回傳十億美元）。

        封面的格式大致是「$3,000,000,000 / 4.125% Notes due 2035」或
        「aggregate principal amount of $2,500,000,000」。這裡只認
        **十億等級以上**的美元數字並取最大的一個——封面上還會有票息、
        年份、每股價格等其他數字，取最大值可以避開它們。

        解析不出來就回 None。這個數字只是輔助，抓不到就只列事件，
        絕不用猜的補上——一個錯的發債金額比沒有金額糟得多。
        """
        if not doc_url:
            return None
        try:
            r = self.session.get(doc_url, timeout=TIMEOUT)
            r.raise_for_status()
            time.sleep(THROTTLE)
        except Exception as e:                     # noqa: BLE001
            self.failed.append(("SEC 說明書封面", str(e)))
            return None
        # 只看前 40000 字元：封面在最前面，往後全是條款細節，
        # 裡面的數字（票息計算例、面額）會干擾判斷
        text = re.sub(r"<[^>]+>", " ", r.text[:40000])
        text = html_mod.unescape(text)
        best = None
        for m in re.finditer(r"\$\s?([\d,]{11,})", text):
            try:
                v = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            # 合理範圍：1 億～2000 億美元。超出就不是發行金額
            if 1e8 <= v <= 2e11 and (best is None or v > best):
                best = v
        return best / 1e9 if best else None


# ---------------------------------------------------------------------------
# XBRL 事實 → 單季序列
# ---------------------------------------------------------------------------
def _facts(js: dict) -> list[dict]:
    """取出 USD 計價、來自 10-Q/10-K 的期間型事實，並去除重複申報。"""
    out: dict[tuple[str, str], dict] = {}
    for f in (js.get("units") or {}).get("USD", []):
        if not f.get("start") or not f.get("end"):
            continue                              # 時點型（資產負債表）不要
        if not str(f.get("form", "")).startswith("10-"):
            continue
        key = (f["start"], f["end"])
        prev = out.get(key)
        # 同一期間可能被多次申報（含修正），取最後申報的版本
        if prev is None or str(f.get("filed", "")) > str(prev.get("filed", "")):
            out[key] = f
    return sorted(out.values(), key=lambda f: (f["end"], f["start"]))


def _days(f: dict) -> int:
    return (dt.date.fromisoformat(f["end"])
            - dt.date.fromisoformat(f["start"])).days


def quarterly_series(js: dict) -> list[dict]:
    """
    把 XBRL 事實還原成單季序列。

    兩種來源合併，不能二選一：

      直接取得 — 期間本來就是 80–100 天的事實。
      累計還原 — 同一個 start 代表同一會計年度的累計序列，
                 相鄰兩筆相減就是單季。

    為什麼要合併：累計序列的**第一筆**（例如 1/1–3/31）本身就是 89 天，
    看起來像單季。若因此判定「已經有單季資料」而略過還原，
    後面 Q2、Q3 的累計值就永遠拿不到，最新一季會停在很久以前。
    同一期末日以直接取得的為準（那是公司自己標的，不是我們推算的）。
    """
    facts = _facts(js)
    if not facts:
        return []

    result: dict[str, dict] = {}

    # ---- 1. 本來就是單季 ----
    for f in facts:
        if 80 <= _days(f) <= 100:
            result[f["end"]] = {
                "end": f["end"], "val": float(f["val"]),
                "form": f.get("form", ""), "accn": f.get("accn", ""),
                "derived": False,
            }

    # ---- 2. 從累計值還原 ----
    by_start: dict[str, list[dict]] = {}
    for f in facts:
        if _days(f) > 400:                        # 跨年度的異常期間，跳過
            continue
        by_start.setdefault(f["start"], []).append(f)

    for group in by_start.values():
        group.sort(key=lambda f: f["end"])
        for i in range(1, len(group)):
            prev, cur = group[i - 1], group[i]
            span = (dt.date.fromisoformat(cur["end"])
                    - dt.date.fromisoformat(prev["end"])).days
            if not 80 <= span <= 100:
                continue                          # 不是相鄰季，不能相減
            result.setdefault(cur["end"], {
                "end": cur["end"],
                "val": float(cur["val"]) - float(prev["val"]),
                "form": cur.get("form", ""), "accn": cur.get("accn", ""),
                "derived": True,
            })

    return sorted(result.values(), key=lambda r: r["end"])


def _year_ago(rows: list[dict], end: str) -> float | None:
    """找一年前的同一季（容許 ±20 天）。"""
    target = dt.date.fromisoformat(end) - dt.timedelta(days=365)
    best, best_gap = None, 999
    for r in rows:
        gap = abs((dt.date.fromisoformat(r["end"]) - target).days)
        if gap < best_gap:
            best, best_gap = r, gap
    return best["val"] if best and best_gap <= 20 else None


# ---------------------------------------------------------------------------
def fetch_hyperscalers(cfg: dict,
                       client: SecClient | None = None) -> tuple[list[dict], str, bool]:
    """
    依 config 的 companies（需含 cik）抓取各家最新一季數字。

    回傳 (companies, as_of, verified)。單位為**十億美元**，與原本手動填的一致。
    任何一家抓不到就退回該家的手動值，並讓 verified 轉為 False。
    """
    client = client or SecClient()
    comps_cfg = cfg.get("companies") or []
    out: list[dict] = []
    ends: list[str] = []
    all_ok = True

    for c in comps_cfg:
        cik = c.get("cik")
        name = c.get("name", c.get("ticker", "?"))
        if not cik:
            log.warning("%s 沒有填 cik，改用手動值", name)
            out.append(dict(c))
            all_ok = False
            continue

        got: dict = {}
        for metric in ("capex", "ocf", "revenue", "debt_issued"):
            rows = client.metric(int(cik), metric)
            if not rows:
                continue
            latest = rows[-1]
            got[metric] = latest["val"] / 1e9        # → 十億美元
            if metric == "capex":
                got["_end"] = latest["end"]
                got["_tag"] = latest.get("tag", "")
                ya = _year_ago(rows[:-1], latest["end"])
                if ya:
                    got["capex_yoy"] = (latest["val"] / ya - 1) * 100

        # 資本支出與營運現金流是核心，缺任一個就不能用這家的抓取結果
        if "capex" not in got or "ocf" not in got:
            log.warning("%s 的 SEC 資料不完整（缺 capex 或 ocf），改用手動值", name)
            out.append(dict(c))
            all_ok = False
            continue

        # 陳舊防線：財報最慢一季一次，超過 200 天沒更新代表抓到的是
        # 停用標記的歷史資料（或公司停止申報），寧可退回手動值也不要
        # 讓九年前的數字混進來假裝是最新一季。
        stale_days = (dt.date.today()
                      - dt.date.fromisoformat(got["_end"])).days
        if stale_days > 200:
            log.warning("%s 抓到的最新一季是 %s（%d 天前），太舊，改用手動值",
                        name, got["_end"], stale_days)
            client.failed.append(
                (f"SEC {name}", f"最新資料僅到 {got['_end']}，可能是標記已停用"))
            out.append(dict(c))
            all_ok = False
            continue

        ends.append(got["_end"])
        out.append({
            "name": name, "ticker": c.get("ticker", ""), "cik": cik,
            "capex": round(got["capex"], 2),
            "ocf": round(got["ocf"], 2),
            "revenue": round(got.get("revenue", c.get("revenue") or 0), 2),
            # 發債沒抓到就是這一季真的沒發（而不是缺資料），填 0 是對的
            "debt_issued": round(got.get("debt_issued", 0.0), 2),
            "capex_yoy": (round(got["capex_yoy"], 1)
                          if got.get("capex_yoy") is not None else None),
            "period_end": got["_end"],
            "source_tag": got.get("_tag", ""),
        })
        log.info("SEC %s：資本支出 %.1f 十億、營運現金流 %.1f 十億（截至 %s）",
                 name, got["capex"], got["ocf"], got["_end"])

    as_of = max(ends) if ends else cfg.get("as_of", "")
    return out, as_of, all_ok and bool(ends)


def fetch_recent_offerings(cfg: dict, client: SecClient | None = None,
                           parse_amount: bool = True) -> list[dict]:
    """
    各家近期的發債申報。回傳 [{name, form, date, amount, doc_url, ...}]，時間降冪。

    這一段補的是**時效缺口**：季報數字最久落後 135 天，而發債當天就要申報。
    金額從說明書封面解析，解析不出來就留 None——只列事件，不用猜的補。

    刻意不影響供給壓力分數：分數維持由經審核的 XBRL 數字決定，
    否則歷史可比性會斷掉，而且同一筆發債下一季會被算第二次。
    """
    client = client or SecClient()
    out: list[dict] = []
    for c in cfg.get("companies") or []:
        cik, name = c.get("cik"), c.get("name", c.get("ticker", "?"))
        if not cik:
            continue
        for f in client.debt_filings(int(cik)):
            amt = None
            # 只對「發行文件本身」解析金額。8-K 是事件通知，
            # 封面沒有標準化的金額欄位，硬解會抓到不相干的數字。
            if parse_amount and f["kind"] == "offering" and f["form"] != "FWP":
                amt = client.offering_amount(f["doc_url"])
            out.append({**f, "name": name, "ticker": c.get("ticker", ""),
                        "amount": amt})
    out.sort(key=lambda x: x["date"], reverse=True)
    if out:
        log.info("SEC 發債申報：近 %d 天共 %d 筆（%d 筆解析到金額）",
                 RECENT_DAYS, len(out),
                 sum(1 for x in out if x["amount"] is not None))
    return out


def load_cache(path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:                              # noqa: BLE001
        return None


def save_cache(path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")
