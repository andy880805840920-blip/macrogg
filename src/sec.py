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
import time
import json
import logging
import datetime as dt

import requests

log = logging.getLogger(__name__)

CONCEPT_URL = ("https://data.sec.gov/api/xbrl/companyconcept/"
               "CIK{cik:010d}/us-gaap/{tag}.json")

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


def load_cache(path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:                              # noqa: BLE001
        return None


def save_cache(path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")
