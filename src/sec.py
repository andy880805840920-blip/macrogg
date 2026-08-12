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

# 8-K 項目 2.02「營運成果與財務狀況」＝季度財報新聞稿。
# 這是「這一季的數字什麼時候公布」唯一穩定的標記。
EARNINGS_8K_ITEMS = ("2.02",)

# 同一家公司、金額相同、日期相差在這個範圍內 → 視為同一筆交易。
# 定價日與 8-K 申報日之間隔四個營業日，遇連假可能拉到七八天，取十天有餘裕。
DEDUP_DAYS = 10
# 只看最近這麼多天的申報。超過這個範圍的多半已經反映在最新一季的財報裡。
RECENT_DAYS = 120
# 財報新聞稿要看得比發債遠一點：一季約 91 天，抓 200 天才保證
# 不論執行日落在季週期的哪個位置，都至少涵蓋兩次公布。
EARNINGS_DAYS = 200
# 新聞稿日期比 XBRL 期末日晚超過這麼多天 → 它講的是**下一季**，
# 也就是下方表格還沒更新到的那一季。
#
# 為什麼是 60：一季約 91 天，而新聞稿約在季末後 20–30 天。所以
#「同一季的新聞稿」落在 +20～+30，「下一季的新聞稿」落在 +111～+121。
# 60 天正好在兩群中間，兩邊都有 30 天以上的餘裕。
#
# 為什麼用「相對公司自己的期末日」而不是曆季：微軟的會計季末是 6 月底、
# 甲骨文是 5 月底，用曆季推會把這兩家一路判錯。
EARNINGS_AHEAD_DAYS = 60

# SEC 要求帶可聯絡的 User-Agent，否則會擋。
# 可用環境變數覆寫成自己的信箱（SEC 的使用規範建議這麼做）。
#
# ⚠️ 這裡**必須**用 `or` 而不是 os.environ.get 的第二個參數。
#
# 踩過的坑：workflow 寫 `SEC_USER_AGENT: ${{ vars.SEC_USER_AGENT }}`，
# 而那個變數沒設定時，GitHub Actions 不是「不設環境變數」，是把它
# **設成空字串**。`os.environ.get(key, default)` 只在 key 不存在時才回
# default——key 存在而值是空的話，回的是空字串。
#
# 結果是送出 `User-Agent: `（空的），SEC 直接擋掉，五家公司**全部**抓取失敗，
# 整區安靜地退回 config 的後備值。畫面上還是有數字、看起來完全正常，
# 只是那是幾個月前手填的數字。這正是實際發生過的事。
DEFAULT_USER_AGENT = "macro-dashboard (contact: dashboard@example.com)"
USER_AGENT = (os.environ.get("SEC_USER_AGENT") or "").strip() or DEFAULT_USER_AGENT

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
        # submissions 端點的回應每家好幾 MB，而發債與財報新聞稿讀的是同一份。
        # 依 cik 存一次，避免同一次執行抓兩遍。
        self._subs: dict[int, list[dict]] = {}

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
    def recent_filings(self, cik: int, days: int = RECENT_DAYS) -> list[dict]:
        """
        近期的**所有**申報，正規化成 [{form, date, items, doc_url, accession, desc}]。

        為什麼獨立出來
        --------------
        發債（424B／8-K 2.03）與財報新聞稿（8-K 2.02）讀的是同一個
        submissions 端點。這個檔案每家有好幾 MB，一次執行為了兩種用途
        抓兩次，等於把 SEC 的請求量與執行時間都乘二——而且兩次之間
        還可能拿到不一致的清單。所以抓一次、依 cik 存在記憶體裡，
        兩邊各自篩自己要的表格類型。

        防禦性寫法
        ----------
        submissions 端點的欄位名稱無法在離線環境驗證（檔案太大、
        查詢介面被 robots.txt 擋）。所以這裡把缺欄位一律當成
        「解析不出來」處理：記錄並回傳空清單，畫面上該區塊就不顯示。
        寧可少一個區塊，也不要憑對資料結構的假設印東西出去。
        """
        cached = self._subs.get(cik)
        if cached is not None:
            return [r for r in cached
                    if r["date"] >= (clock.today()
                                     - dt.timedelta(days=days)).isoformat()]

        js = self._json(SUBMISSIONS_URL.format(cik=cik), f"SEC submissions {cik}")
        if not js:
            return []
        recent = ((js.get("filings") or {}).get("recent")) or {}
        forms = recent.get("form")
        dates = recent.get("filingDate")
        if not isinstance(forms, list) or not isinstance(dates, list):
            log.warning("SEC submissions 的欄位與預期不符（CIK %s），略過近期申報", cik)
            self.failed.append((f"SEC submissions {cik}", "欄位結構與預期不符"))
            self._subs[cik] = []
            return []

        items = recent.get("items") or []
        accs = recent.get("accessionNumber") or []
        docs = recent.get("primaryDocument") or []
        descs = recent.get("primaryDocDescription") or []

        def _at(arr, i):
            return arr[i] if isinstance(arr, list) and i < len(arr) else ""

        # 快取存的是「這個端點回傳的全部」，篩選日期在回傳時才做——
        # 兩個呼叫端的 days 不一樣（發債看 120 天、財報看 200 天），
        # 用最寬的存起來才不會第二個呼叫端拿到被前一個截短的清單。
        rows = []
        for i, form in enumerate(forms):
            date = _at(dates, i)
            if not date:
                continue
            acc = _at(accs, i)
            doc = _at(docs, i)
            url = ""
            if acc and doc:
                url = ARCHIVE_DOC.format(cik=cik, acc_nodash=acc.replace("-", ""),
                                         doc=doc)
            rows.append({"form": form, "date": date, "items": _at(items, i) or "",
                         "accession": acc, "doc_url": url,
                         "desc": _at(descs, i)})
        rows.sort(key=lambda x: x["date"], reverse=True)
        self._subs[cik] = rows
        cutoff = (clock.today() - dt.timedelta(days=days)).isoformat()
        return [r for r in rows if r["date"] >= cutoff]

    # ------------------------------------------------------------------
    def debt_filings(self, cik: int, days: int = RECENT_DAYS) -> list[dict]:
        """
        近期的發債相關申報，時間降冪。

        為什麼需要這個
        --------------
        XBRL 只到 10-Q，而 10-Q 是季末後約 45 天才申報——一筆七月的發債
        最久要等到十一月才會出現在數字裡。但發債本身當天就要申報：
        424B2／424B5 是債券發行文件本身，8-K 項目 2.03 是「產生直接財務義務」。
        """
        out = []
        for r in self.recent_filings(cik, days):
            if r["form"] in DEBT_FORMS:
                kind = "offering"
            elif (r["form"].startswith("8-K")
                  and any(x in r["items"] for x in DEBT_8K_ITEMS)):
                kind = "event"
            else:
                continue
            out.append({**r, "kind": kind})
        return out

    # ------------------------------------------------------------------
    def earnings_filings(self, cik: int,
                         days: int = EARNINGS_DAYS) -> list[dict]:
        """
        近期的財報新聞稿申報（8-K 項目 2.02），時間降冪。

        補的是**實績的時效缺口**：10-Q 的 XBRL 是季末後約 40 天才申報，
        而財報新聞稿約三週就出來——中間那兩週，這一頁的表格顯示的還是
        上一季，讀者卻已經在新聞上看到新一季的資本支出了。

        只取「什麼時候公布的」與原文連結，**刻意不解析裡面的數字**：
        新聞稿是非結構化文字，各家的口徑（GAAP／non-GAAP、是否含融資租賃）
        寫法都不同，硬解會拿到一個不知道是什麼的數字混進表格；
        而兩週後 XBRL 就會給出經審核、標記明確的版本。

        表格類型只認 8-K／8-K/A。項目 2.02 是「營運成果與財務狀況」，
        季度財報新聞稿一律走這一項，是這件事唯一穩定的標記。
        """
        return [r for r in self.recent_filings(cik, days)
                if r["form"].startswith("8-K")
                and any(x in r["items"] for x in EARNINGS_8K_ITEMS)]

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
            return _EMPTY_COVER.copy()
        try:
            r = self.session.get(doc_url, timeout=TIMEOUT)
            r.raise_for_status()
            time.sleep(THROTTLE)
        except Exception as e:                     # noqa: BLE001
            self.failed.append(("SEC 說明書封面", str(e)))
            return _EMPTY_COVER.copy()
        # 只看前 40000 字元：封面在最前面，往後全是條款細節
        text = re.sub(r"<[^>]+>", " ", r.text[:40000])
        text = html_mod.unescape(text)
        return _read_cover(text)

    def offering_amount(self, doc_url: str) -> float | None:
        """只要美元金額時的薄包裝。保留是為了不讓呼叫端都得改成讀 dict。"""
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

    每一列都會帶 `from_sec`：這一家的數字是不是真的來自 SEC。畫面靠它
    逐列標示，因為「五家裡有一家退回手動值」跟「五家全部退回手動值」
    在讀者眼中是完全不同的兩件事，而先前兩者的畫面長得一模一樣。
    """
    client = client or SecClient()
    comps_cfg = cfg.get("companies") or []
    out: list[dict] = []
    ends: list[str] = []
    all_ok = True

    def _fallback(c: dict) -> dict:
        """退回 config 的手動值，並標記它不是來自 SEC。"""
        row = dict(c)
        row["from_sec"] = False
        row["period_end"] = ""          # 手動值沒有可信的期末日，不要假裝有
        return row

    for c in comps_cfg:
        cik = c.get("cik")
        name = c.get("name", c.get("ticker", "?"))
        if not cik:
            log.warning("%s 沒有填 cik，改用手動值", name)
            out.append(_fallback(c))
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
            out.append(_fallback(c))
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
            out.append(_fallback(c))
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
            "from_sec": True,
        })
        log.info("SEC %s：資本支出 %.1f 十億、營運現金流 %.1f 十億（截至 %s）",
                 name, got["capex"], got["ocf"], got["_end"])

    # 全部失敗是一種完全不同的狀況：不是「某一家的標記變了」，
    # 而是「根本連不上 SEC」（憑證、User-Agent 被擋、網路）。
    # 這種時候整區的數字都是幾個月前手填的，必須用 error 等級講出來，
    # 不能混在一堆 warning 裡讓人滑過去。
    if comps_cfg and not ends:
        log.error("科技巨頭：%d 家**全部**擷取失敗，整區改用 config 的手動值。"
                  "常見原因是 SEC_USER_AGENT 沒設或被擋（SEC 會擋空的 "
                  "User-Agent）。目前送出的是：%r", len(comps_cfg), USER_AGENT)

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

# ---------------------------------------------------------------------------
# 證券類型分類
#
# ⚠️ 表格號**不能**當成證券類型。這是這一段最貴的一個教訓：
# 424B2／424B5 只代表「這是一份定價後的公開說明書補充」，賣的東西可能是
# 債券、普通股、特別股、存託股、結構型商品，或 ATM 增發計畫。
# 先前的程式只要看到 424B2／424B5 就當成發債，於是把
#   · Oracle 的 200 億美元 ATM 普通股增發
#   · Alphabet 的 Class A／Class C 股票發行
# 都算成了債券發行，還把金額加進合計。
#
# 現在改成讀文件內容。方向刻意保守：**只有拿到正面證據才算債券**，
# 拿不準一律不算。漏掉一筆債的代價，遠小於把一筆股票增發印成發債。
# ---------------------------------------------------------------------------

# 這是債券的正面證據。少了這些就不算，不管表格號是什麼。
_BOND_POS = re.compile(
    r"aggregate\s+principal\s+amount"
    r"|senior\s+notes"
    r"|(?:notes|debentures|bonds)\s+due\s+20\d\d"
    r"|floating\s+rate\s+notes"
    r"|debt\s+securities",
    re.I)

# 這些是「賣的不是債券」的證據。只在封面標題區判斷——
# 債券說明書的內文常常會順帶提到普通股（「本公司普通股於那斯達克掛牌」），
# 全文比對會把真正的債券發行誤殺。
_NOT_BOND = re.compile(
    r"common\s+stock"
    r"|class\s+[abc]\s+(?:common|capital)\s+stock"
    r"|capital\s+stock"
    r"|preferred\s+stock"
    r"|depositary\s+shares"
    r"|at[-\s]the[-\s]market"
    r"|sales\s+agreement"
    r"|tender\s+offer"
    r"|exchange\s+offer"
    r"|repurchase"
    r"|revolving\s+credit"
    r"|credit\s+agreement"
    r"|(?:delayed\s+draw\s+)?term\s+loan"
    r"|credit\s+facility",
    re.I)

# 封面標題區。說明書把「賣什麼」寫在最前面（金額、證券名稱、發行人），
# 後面才是條款細節與風險因子。3000 字元大致涵蓋封面那一頁。
TITLE_CHARS = 3000

SEC_BOND, SEC_EQUITY, SEC_OTHER, SEC_UNKNOWN = "bond", "equity", "other", "unknown"


def classify_security(cover_text: str) -> str:
    """
    這份說明書賣的是什麼。回傳 bond / equity / other / unknown。

    判斷順序刻意是「先看標題區排除，再看全文找正面證據」：
      ① 標題區出現股票／ATM／貸款額度這類字樣，而且**沒有**債券的正面
         證據 → 不是債券。
      ② 有債券正面證據（aggregate principal amount、Senior Notes、
         Notes due 20xx）→ 債券。
      ③ 其餘 → unknown，不計入發債。
    """
    text = cover_text or ""
    if not text.strip():
        return SEC_UNKNOWN
    head = text[:TITLE_CHARS]
    bond_head = bool(_BOND_POS.search(head))
    not_bond_head = bool(_NOT_BOND.search(head))

    if not_bond_head and not bond_head:
        # 標題區明講賣的是股票／ATM／貸款——這種不必再看內文
        m = _NOT_BOND.search(head)
        kind = (m.group(0) or "").lower()
        return SEC_OTHER if ("loan" in kind or "credit" in kind
                             or "tender" in kind or "exchange" in kind
                             or "repurchase" in kind) else SEC_EQUITY
    if bond_head or _BOND_POS.search(text):
        return SEC_BOND
    return SEC_UNKNOWN


# ---------------------------------------------------------------------------
# 金額解析（多幣別）
#
# 兩個先前的錯誤：
#   ① **同一組分券被加總兩次。** 封面的分券表在「Calculation of Filing Fee」
#      與摘要段落各出現一次，程式把兩次都加進去 → Meta 的 250 億變成 500 億、
#      Amazon 的 250 億變成 500 億、C$140 億變成 280 億。
#      修法：依（幣別、金額、到期年、票息）去重，同一張券只算一次。
#   ② **所有幣別都被當成美元。** 舊的樣式只認 `$`，而 "C$1,250,000,000"
#      裡面就含有 `$1,250,000,000`——加拿大幣直接被讀成美元。
#      修法：幣別記號一起抓，而且 C$／A$／US$ 必須排在 $ 前面比對。
# ---------------------------------------------------------------------------
_CCY_ALT = r"C\$|CA\$|A\$|AU\$|US\$|\$|€|£|¥|CHF|SEK|NOK"
_CCY_MAP = {"C$": "CAD", "CA$": "CAD", "A$": "AUD", "AU$": "AUD",
            "US$": "USD", "$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY",
            "CHF": "CHF", "SEK": "SEK", "NOK": "NOK"}
_SCALE = {"billion": 1e9, "bn": 1e9, "million": 1e6, "mm": 1e6, "": 1.0}

# 數字有兩種寫法：完整位數（1,250,000,000）與帶單位（1.25 billion）
_NUM_ALT = r"(?:[\d][\d,]{6,}|[\d]+(?:\.\d+)?\s*(?:billion|million|bn|mm))"

_TRANCHE_RE = re.compile(
    rf"({_CCY_ALT})\s?({_NUM_ALT})"
    rf"((?:(?!{_CCY_ALT})[^\n]){{0,90}}?)"
    r"(?:Notes|Debentures|Bonds)\s+due\s+(20\d\d)",
    re.I)

# 沒有分券表時的備案：明講 aggregate principal amount 的那一個數字。
_AGG_RE = re.compile(
    rf"({_CCY_ALT})\s?({_NUM_ALT})\s+aggregate\s+principal\s+amount", re.I)

_COUPON_RE = re.compile(r"(\d+\.\d+)\s*%|floating", re.I)

# 原幣的合理區間。下緣擋掉頁碼、CUSIP 這類雜訊；上緣要放得夠寬，
# 因為日圓的面額本來就大（¥576,500,000,000 是合理的一筆）。
# 換算成美元之後還有一道 sanity 檢查（見 build._offerings_block）。
NATIVE_MIN, NATIVE_MAX = 1e7, 1e13


def is_preliminary(cover_text: str) -> bool:
    """封面是不是預估版（尚未定價）。"""
    return bool(_PRELIM_RE.search(cover_text or ""))


def _to_number(raw: str) -> float | None:
    s = (raw or "").replace(",", "").strip().lower()
    scale = 1.0
    for word, mult in _SCALE.items():
        if word and s.endswith(word):
            s, scale = s[:-len(word)].strip(), mult
            break
    try:
        return float(s) * scale
    except ValueError:
        return None


def parse_tranches(cover_text: str) -> list[dict]:
    """
    解析封面的分券表，回傳 [{currency, amount, maturity, coupon}]，**已去重**。

    去重的鍵是（幣別、金額、到期年、票息）。同一張券在文件裡出現幾次都只
    算一次——這正是先前把 250 億讀成 500 億的原因。兩張真正不同的券不可能
    幣別、金額、到期年、票息全部相同，所以這個鍵不會誤併。
    """
    text = cover_text or ""
    out: list[dict] = []
    seen: set[tuple] = set()

    for m in _TRANCHE_RE.finditer(text):
        sym, num, middle, maturity = m.group(1), m.group(2), m.group(3), m.group(4)
        val = _to_number(num)
        if val is None or not (NATIVE_MIN <= val <= NATIVE_MAX):
            continue
        ccy = _CCY_MAP.get(sym.upper().replace("CA$", "C$"), _CCY_MAP.get(sym, ""))
        if not ccy:
            continue
        cm = _COUPON_RE.search(middle or "")
        coupon = (cm.group(0).lower().strip() if cm else "")
        key = (ccy, round(val, 2), maturity, coupon)
        if key in seen:
            continue
        seen.add(key)
        out.append({"currency": ccy, "amount": val,
                    "maturity": maturity, "coupon": coupon})

    if out:
        return out

    # 備案：aggregate principal amount。同樣去重，並取每個幣別的最大值——
    # 這種寫法通常只出現一次總額，重複出現是同一個數字被引用兩次。
    best: dict[str, float] = {}
    for m in _AGG_RE.finditer(text):
        val = _to_number(m.group(2))
        ccy = _CCY_MAP.get(m.group(1).upper().replace("CA$", "C$"),
                           _CCY_MAP.get(m.group(1), ""))
        if val is None or not ccy or not (NATIVE_MIN <= val <= NATIVE_MAX):
            continue
        best[ccy] = max(best.get(ccy, 0.0), val)
    return [{"currency": c, "amount": v, "maturity": "", "coupon": ""}
            for c, v in best.items()]


def totals_by_currency(tranches: list[dict]) -> dict[str, float]:
    out: dict[str, float] = {}
    for t in tranches:
        out[t["currency"]] = out.get(t["currency"], 0.0) + t["amount"]
    return out


def parse_offering_amount(cover_text: str) -> float | None:
    """
    只要「美元金額（十億）」時的薄包裝，保留給既有呼叫端。

    非美元的交易會回 None——不是解析失敗，是**這一筆本來就不是美元計價**。
    要正確處理請改用 parse_tranches()，它保留原始幣別。
    """
    tot = totals_by_currency(parse_tranches(cover_text))
    return tot["USD"] / 1e9 if "USD" in tot else None


# 讀不到封面時的預設值。security 是 unknown 而不是 bond——
# 拿不到內容就不能宣稱它是債券，這是整段分類的預設立場。
_EMPTY_COVER = {"amount": None, "preliminary": False,
                "security": SEC_UNKNOWN, "tranches": [], "totals": {}}


def _read_cover(text: str) -> dict:
    """把封面純文字變成 {amount, preliminary, security, tranches, totals}。"""
    tranches = parse_tranches(text)
    totals = totals_by_currency(tranches)
    return {
        "amount": (totals["USD"] / 1e9 if "USD" in totals else None),
        "preliminary": is_preliminary(text),
        "security": classify_security(text),
        "tranches": tranches,
        "totals": totals,
    }


def _dominant(totals: dict) -> tuple[str, float | None]:
    """一份文件的主要幣別與該幣別的合計。沒有金額時回 ("", None)。"""
    if not totals:
        return "", None
    ccy = max(totals, key=lambda c: totals[c])
    return ccy, totals[ccy]


def dedupe_deals(rows: list[dict]) -> list[dict]:
    """
    把「申報」收斂成「交易」。

    這裡要回答的是一個比表面複雜的問題：**幾筆真正獨立、已定價的債券發行。**
    不是幾份 SEC 申報，也不是幾份 424B。

    規則
    ----
    1. **只有 security == bond 才可能成為一筆發債。** 表格號不算數：
       424B5 可能是普通股、ATM 增發、特別股或存託股。股票與 ATM 完全不進
       筆數與金額（但仍保留一行，讓讀者知道有這件事、可以點連結）。
    2. **預估版不算一筆交易。** 有對應定價版就整個不列；沒有定價版就列出來
       標「尚未定價」，但不計入筆數與金額——「有一筆正在路上」本身是資訊。
    3. **同公司、同幣別、DEDUP_DAYS 天內 → 同一筆交易。**
       幣別必須進分組鍵：Alphabet 在同一週發過 €90 億與 C$85 億，
       那是兩筆不同的交易，合併成一個美元數字會讓兩筆都失真。
    4. 一筆交易的金額 ＝ 群組內**相異分券**的總和。相異的鍵是
       （幣別、金額、到期年、票息）——同一張券在不同申報、或同一份文件的
       不同段落重複出現，都只算一次。這正是先前 250 億被讀成 500 億的原因。
    5. **8-K 2.03 不算發債。** 它是「產生直接財務義務」，涵蓋銀行貸款、
       定期貸款、循環額度——Amazon 的 175 億美元 delayed draw term loan
       就是走這一項。這些是融資事件，不是公開債券發行，另外列、不進合計。
       配得到同期債券交易的則直接不列（同一件事的第二份申報）。
    """
    offerings = [r for r in rows if r.get("kind") == "offering"]
    events = [r for r in rows if r.get("kind") != "offering"]

    bonds = [r for r in offerings if r.get("security") == SEC_BOND]
    nonbond = [r for r in offerings if r.get("security") != SEC_BOND]

    prelim = [r for r in bonds if r.get("preliminary")]
    priced = [r for r in bonds if not r.get("preliminary")]

    # ---- ① 定價版：同公司＋同幣別＋時間相近 → 併成一筆 ----
    priced.sort(key=lambda r: r["date"])          # 由舊到新
    groups: list[list[dict]] = []
    for r in priced:
        rc = r.get("currency") or ""
        for g in groups:
            if g[0]["name"] != r["name"] or (g[0].get("currency") or "") != rc:
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
        seen: set[tuple] = set()
        merged_tranches = []
        for r in g:
            for tr in (r.get("tranches") or []):
                key = (tr["currency"], round(tr["amount"], 2),
                       tr.get("maturity", ""), tr.get("coupon", ""))
                if key in seen:
                    continue
                seen.add(key)
                merged_tranches.append(tr)
        totals = totals_by_currency(merged_tranches)
        ccy, principal = _dominant(totals)
        lead.update({"tranches": merged_tranches, "totals": totals,
                     "currency": ccy or lead.get("currency", ""),
                     "principal": principal,
                     "amount": (totals["USD"] / 1e9 if "USD" in totals else None),
                     "merged": len(g), "counts": True})
        kept.append(lead)

    # ---- ② 8-K 2.03：配得到同期債券交易就不列（同一件事的第二份申報）----
    for e in events:
        if any(k["name"] == e["name"]
               and (_days_apart(k["date"], e["date"]) or 999) <= DEDUP_DAYS
               for k in kept):
            continue
        kept.append({**e, "security": e.get("security") or SEC_OTHER,
                     "amount": None, "principal": None,
                     "counts": False, "merged": 1})

    # ---- ③ 預估版：沒有對應定價版才列，且不計數 ----
    for r in prelim:
        if any(k["name"] == r["name"] and k.get("counts")
               and (_days_apart(k["date"], r["date"]) or 999) <= DEDUP_DAYS
               for k in kept):
            continue
        kept.append({**r, "amount": None, "principal": None,
                     "counts": False, "merged": 1})

    # ---- ④ 非債券（股票、ATM、特別股）：列出來但完全不計數 ----
    # 金額也一併拿掉：一個「不算數但看起來像發債」的數字最容易被誤讀。
    for r in nonbond:
        kept.append({**r, "amount": None, "principal": None,
                     "counts": False, "merged": 1})

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
            row = {**f, "name": name, "ticker": c.get("ticker", ""),
                   "amount": None, "preliminary": False,
                   "security": SEC_OTHER if f["kind"] != "offering" else SEC_UNKNOWN,
                   "tranches": [], "totals": {},
                   "currency": "", "principal": None}
            # 424B 一律要讀封面——**分類靠的是內容，不是表格號**。
            # 8-K 是事件通知，沒有標準化的金額欄位，硬解會抓到不相干的數字，
            # 而且它本來就不計入發債（見 dedupe_deals 的規則 5）。
            if parse_amount and f["kind"] == "offering":
                info = client.cover_info(f["doc_url"])
                ccy, principal = _dominant(info["totals"])
                row.update({"amount": info["amount"],
                            "preliminary": info["preliminary"],
                            "security": info["security"],
                            "tranches": info["tranches"],
                            "totals": info["totals"],
                            "currency": ccy, "principal": principal})
            out.append(row)

    raw_n = len(out)
    n_prelim = sum(1 for x in out if x.get("preliminary"))
    n_nonbond = sum(1 for x in out
                    if x["kind"] == "offering" and x["security"] != SEC_BOND)
    out = dedupe_deals(out)
    deals = [x for x in out if x.get("counts")]
    if out or raw_n:
        log.info("SEC 發債：近 %d 天 %d 份申報（%d 份預估版、%d 份不是債券）"
                 " → %d 筆已定價的債券交易（%d 筆有金額）",
                 RECENT_DAYS, raw_n, n_prelim, n_nonbond, len(deals),
                 sum(1 for x in deals if x.get("principal") is not None))
    return out


def fetch_recent_earnings(cfg: dict,
                          client: SecClient | None = None) -> list[dict]:
    """
    各家**最近一次財報新聞稿**的申報日與原文連結。

    回傳 [{name, ticker, date, doc_url, form, period_end, ahead, lag}]，時間降冪。

    這一段補的是實績的時效缺口：10-Q 的 XBRL 是季末後約 40 天才申報，
    新聞稿約三週——中間那兩週表格顯示的還是上一季。

    `ahead` 是這一段唯一的判斷：新聞稿的日期比同一家 XBRL 的期末日晚
    超過 EARNINGS_AHEAD_DAYS 天 → 它講的是下方表格還沒有的那一季。
    這個判斷只用兩個日期，不碰新聞稿的內容——**內容一個字都不解析**
    （理由見 earnings_filings 的說明）。

    每家只取最近一筆：更早的那些對應的季度早就進 XBRL 了，列出來只是雜訊。
    """
    client = client or SecClient()
    out: list[dict] = []
    for c in cfg.get("companies") or []:
        cik, name = c.get("cik"), c.get("name", c.get("ticker", "?"))
        if not cik:
            continue
        rows = client.earnings_filings(int(cik))
        if not rows:
            continue
        f = rows[0]                                  # 已經是時間降冪
        pe = c.get("period_end") or ""
        lag = _days_apart(f["date"], pe) if pe else None
        out.append({
            "name": name, "ticker": c.get("ticker", ""),
            "date": f["date"], "form": f["form"], "items": f["items"],
            "doc_url": f["doc_url"], "accession": f["accession"],
            "period_end": pe,
            "lag": lag,
            # 日期比較只在新聞稿**晚於**期末日時才有意義。
            # _days_apart 取絕對值，所以要另外確認方向：新聞稿早於期末日
            # 是不可能的（那代表期末日抓錯），這時一律不宣稱領先。
            "ahead": bool(pe and f["date"] > pe
                          and lag is not None and lag > EARNINGS_AHEAD_DAYS),
        })
    out.sort(key=lambda x: x["date"], reverse=True)
    if out:
        log.info("SEC 財報新聞稿：%d 家有 8-K 2.02，其中 %d 家已公布"
                 "下方季報數字尚未涵蓋的一季",
                 len(out), sum(1 for x in out if x["ahead"]))
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
