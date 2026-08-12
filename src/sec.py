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

from . import clock

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

# 代表「這家公司**真的發了債**」的表格類型。
#
# 只收兩種：
#   424B2 / 424B5  定價後的公開說明書補充——債券發行文件本身，定價當日申報。
#                  一筆交易對應一份，是唯一乾淨的「一份文件＝一筆發行」關係。
#
# 以下三種先前有收，現在刻意排除——它們都不是「真的有發行」：
#   FWP     自由書寫公開說明書，本質是**行銷文件**。一筆債通常會發兩到三份
#           （初步條款表、最終條款表、定價補充），全部列出來會讓一筆
#           125 億的發行看起來像三筆，合計金額也跟著灌水。
#   424B3   多半是**再售**登記與生效後更新的說明書，賣的是既有股東手上的
#           證券，公司沒有拿到新錢——跟債券供給無關。
#   8-K 1.01「簽訂重大確定性協議」是 8-K 裡最寬的萬用項：供應合約、合資、
#           租約、循環額度修訂都走這一項。真正是發債的比例極低，
#           收進來等於用雜訊稀釋整張表。
DEBT_FORMS = {"424B2", "424B5"}

# 8-K 只認 2.03「產生直接財務義務」。
#
# 它跟 424B 的關係要講清楚：同一筆公開發行通常**兩者都會申報**
#（424B 定價當日、8-K 在四個營業日內），所以直接兩邊都列會重複計算。
# 處理方式是把 8-K 2.03 當**補漏**用——只有在找不到對應的 424B 時才單獨
# 成為一筆，那種情況通常是銀行貸款、定期貸款或私募，本來就不會有 424B。
DEBT_8K_ITEMS = ("2.03",)

# 同一家公司、金額相同、日期相差在這個範圍內 → 視為同一筆交易。
# 定價日與 8-K 申報日之間隔四個營業日，遇連假可能拉到七八天，取十天有餘裕。
DEDUP_DAYS = 10
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

        cutoff = (clock.today() - dt.timedelta(days=days)).isoformat()
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
    def cover_info(self, doc_url: str) -> dict:
        """
        讀說明書封面，回傳 {"amount": 十億美元|None, "preliminary": bool}。

        ── 為什麼要分辨預估版 ────────────────────────────────
        424B2／424B5 **同時涵蓋預估版與定價版**，光看表格號分不出來。
        實測過的真實文件：一份檔名 `preliminary-prospectus-suppl.htm`
        的文件，表格號就是 424B2。

        分辨的依據是 Rule 430B／430C 強制要求的封面法定用語：

            「The information in this preliminary prospectus supplement
              is not complete and may be changed」
            「Subject to Completion, Dated <日期>」

        定價版沒有這段。這兩句的字面高度固定（大小寫不一定），
        是目前唯一穩定的判別方式。

        不分辨的後果：同一筆債會被算兩次（宣布日一份、定價日一份），
        而且預估版的封面定價表格是**空的**，解析器抓不到金額就回 None，
        於是畫面上出現一堆「金額待確認」——那些其實不是抓取失敗，
        是它們本來就還沒有金額。

        ── 為什麼金額改成加總 tranche ────────────────────────
        先前的做法是「封面上 1 億～2000 億之間取最大值」。但封面上最大的
        數字往往是**貨架註冊額度**（"up to $40,000,000,000 of debt
        securities"），不是這一筆的規模。實際跑出來的症狀：Alphabet 在
        相隔兩個月的兩份文件上各被讀出一次「400 億」——同一個數字出現兩次，
        那不是兩筆交易，是同一個貨架額度被讀了兩次。近 120 天的合計因此
        灌到季報申報值的四倍。

        改成只認標準的分券格式並加總：

            $1,000,000,000  4.125% Notes due 2029
            $1,500,000,000  4.500% Notes due 2032

        抓不到就回 None——**不退回取最大值**。一個錯的發債金額比沒有金額
        糟得多，而「取最大值」正是錯得最有系統的那一種。
        """
        if not doc_url:
            return {"amount": None, "preliminary": False}
        try:
            r = self.session.get(doc_url, timeout=TIMEOUT)
            r.raise_for_status()
            time.sleep(THROTTLE)
        except Exception as e:                     # noqa: BLE001
            self.failed.append(("SEC 說明書封面", str(e)))
            return {"amount": None, "preliminary": False}
        # 只看前 40000 字元：封面在最前面，往後全是條款細節
        text = re.sub(r"<[^>]+>", " ", r.text[:40000])
        text = html_mod.unescape(text)
        return {"amount": parse_offering_amount(text),
                "preliminary": is_preliminary(text)}

    def offering_amount(self, doc_url: str) -> float | None:
        """只要金額時的薄包裝。保留是為了不讓呼叫端都得改成讀 dict。"""
        return self.cover_info(doc_url)["amount"]


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
        stale_days = (clock.today()
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


def _days_apart(a: str, b: str) -> int | None:
    try:
        return abs((dt.date.fromisoformat(a) - dt.date.fromisoformat(b)).days)
    except (ValueError, TypeError):
        return None


# 預估版的法定用語（Rule 430B／430C）。大小寫不一，實測看過全大寫與句首大寫。
# 兩句任一命中就算預估版——正式定價版兩句都不會有。
_PRELIM_RE = re.compile(
    r"subject\s+to\s+completion"
    r"|information\s+in\s+this\s+preliminary\s+prospectus"
    r"|not\s+complete\s+and\s+may\s+be\s+changed",
    re.I)

# 分券格式：金額 ＋（票息／浮動）＋ Notes/Debentures/Bonds due YYYY。
# 中間允許 80 字元的雜訊（"aggregate principal amount of"、"Senior"、
# 空白與換行），但不允許再出現一個 $——不然會從貨架額度一路跨到分券那一行。
_TRANCHE_RE = re.compile(
    r"\$\s?([\d,]{11,})(?:(?!\$)[^\n]){0,80}?"
    r"(?:Notes|Debentures|Bonds)\s+due\s+20\d\d",
    re.I)

# 沒有分券格式時的備案：明講 aggregate principal amount 的那個數字。
_AGG_RE = re.compile(r"\$\s?([\d,]{11,})\s+aggregate\s+principal\s+amount",
                     re.I)

AMOUNT_MIN, AMOUNT_MAX = 1e8, 2e11        # 1 億～2000 億美元


def is_preliminary(cover_text: str) -> bool:
    """封面是不是預估版（尚未定價）。"""
    return bool(_PRELIM_RE.search(cover_text or ""))


def _amounts(pattern, text) -> list[float]:
    out = []
    for m in pattern.finditer(text):
        try:
            v = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if AMOUNT_MIN <= v <= AMOUNT_MAX:
            out.append(v)
    return out


def parse_offering_amount(cover_text: str) -> float | None:
    """
    從封面文字解析這一筆的發行總額（十億美元）。

    先找分券格式並**加總**；一筆多年期或多幣別的交易，封面會逐券列出，
    加起來才是這一筆的規模。找不到分券才退回 aggregate principal amount
    那一種寫法，並取最大的一個。

    兩種都找不到就回 None。**刻意不退回「封面最大的數字」**——
    那個備案會抓到貨架註冊額度，而且錯得很有系統（同一個額度每次都被讀成
    一筆新的交易），比沒有數字糟得多。

    分券與 aggregate 不相加：封面常常兩者都寫（先講總額再逐券列），
    相加會直接翻倍。
    """
    text = cover_text or ""
    tranches = _amounts(_TRANCHE_RE, text)
    if tranches:
        return sum(tranches) / 1e9
    agg = _amounts(_AGG_RE, text)
    if agg:
        return max(agg) / 1e9
    return None


def dedupe_deals(rows: list[dict]) -> list[dict]:
    """
    把「申報」收斂成「交易」。

    為什麼要做
    ----------
    同一筆債會產生**三到四份**申報：預估版 424B（宣布日）、定價版 424B
    （定價日）、8-K 2.03（四個營業日內），多幣別的話再加一份。
    全部列出來的話，同一筆債會被算三次，而金額合計正是這一段唯一有
    交易意涵的數字——實際跑出來灌到季報申報值的四倍。

    規則
    ----
    1. **預估版不算一筆交易。** 它是同一筆的前身，通常兩三天內就會有
       定價版。仍然保留在明細裡並標示，因為「有一筆正在路上」對供給面
       本身就是資訊。
    2. 同一家公司、日期相差 DEDUP_DAYS 天以內的定價版 424B **視為同一筆
       交易**——不再要求金額相同。先前要求同金額，結果預估版（金額 None
       或貨架額度）跟定價版（真實金額）配不起來，兩份都被留下。
    3. 一筆交易的金額 ＝ 群組內**相異**金額的總和。相異是必要的：
       多幣別 tranche 分開申報要相加，但同一個數字重複出現
       （重新申報、預估與定價金額相同）不能算兩次。
    4. 8-K 2.03 只在**配不到任何 424B** 時才成為獨立的一筆。
       配不到的通常是銀行貸款、定期貸款或私募——那些本來就不發 424B。
    """
    offerings = [r for r in rows if r.get("kind") == "offering"]
    events = [r for r in rows if r.get("kind") != "offering"]

    # ---- ① 預估版：不成為交易，但留在明細 ----
    prelim = [r for r in offerings if r.get("preliminary")]
    priced = [r for r in offerings if not r.get("preliminary")]

    # ---- ② 定價版：同公司、時間相近 → 併成一筆交易 ----
    priced.sort(key=lambda r: r["date"])          # 由舊到新
    groups: list[list[dict]] = []
    for r in priced:
        for g in groups:
            if g[0]["name"] != r["name"]:
                continue
            gap = _days_apart(g[-1]["date"], r["date"])
            if gap is not None and gap <= DEDUP_DAYS:
                g.append(r)
                break
        else:
            groups.append([r])

    kept: list[dict] = []
    for g in groups:
        # 代表這一筆的是**最後一份**申報：定價版比宣布版晚，
        # 而最後一份的日期才是交易真正完成的日子。
        lead = dict(g[-1])
        amts = []
        for r in g:
            a = r.get("amount")
            if a is not None and a not in amts:
                amts.append(a)
        lead["amount"] = sum(amts) if amts else None
        lead["merged"] = len(g)
        kept.append(lead)

    # ---- ③ 8-K 2.03：配不到 424B 才留 ----
    for e in events:
        if any(k["name"] == e["name"]
               and (_days_apart(k["date"], e["date"]) or 999) <= DEDUP_DAYS
               for k in kept):
            continue                                  # 同一筆交易，已由 424B 代表
        kept.append(e)

    # ---- ④ 預估版接回明細，但標記成不計數 ----
    for r in prelim:
        # 已經有對應的定價版就不必再列——那只是同一筆的前身
        if any(k["name"] == r["name"]
               and (_days_apart(k["date"], r["date"]) or 999) <= DEDUP_DAYS
               for k in kept):
            continue
        kept.append({**r, "amount": None})

    kept.sort(key=lambda r: r["date"], reverse=True)
    return kept


def fetch_recent_offerings(cfg: dict, client: SecClient | None = None,
                           parse_amount: bool = True) -> list[dict]:
    """
    各家近期**真正發生的發債交易**。回傳 [{name, form, date, amount, ...}]，時間降冪。

    這一段補的是**時效缺口**：季報數字最久落後 135 天，而發債當天就要申報。
    金額從說明書封面解析，解析不出來就留 None——只列事件，不用猜的補。

    顯示的單位是「交易」不是「申報」：同一筆債的 424B 與 8-K 會先合併
    （見 dedupe_deals），否則畫面上的筆數與合計金額都會重複計算。

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
            amt, prelim = None, False
            # 只對「發行文件本身」讀封面。8-K 是事件通知，
            # 沒有標準化的金額欄位，硬解會抓到不相干的數字。
            if parse_amount and f["kind"] == "offering":
                info = client.cover_info(f["doc_url"])
                amt, prelim = info["amount"], info["preliminary"]
            out.append({**f, "name": name, "ticker": c.get("ticker", ""),
                        "amount": amt, "preliminary": prelim})
    raw_n = len(out)
    n_prelim = sum(1 for x in out if x.get("preliminary"))
    out = dedupe_deals(out)
    n_deals = sum(1 for x in out if not x.get("preliminary"))
    if out or raw_n:
        log.info("SEC 發債：近 %d 天 %d 份申報（其中 %d 份是預估版）"
                 " → %d 筆交易（%d 筆有金額）",
                 RECENT_DAYS, raw_n, n_prelim, n_deals,
                 sum(1 for x in out
                     if x["amount"] is not None and not x.get("preliminary")))
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
