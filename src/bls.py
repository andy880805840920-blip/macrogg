"""
BLS 快速通道 — 在 FRED 同步之前，先從資料來源本身拿到最新一期。

為什麼需要這一層
----------------
CPI 與就業報告都是 BLS 在美東 08:30 發布，而 FRED 是**轉載**：它要把
BLS 的原始檔匯進自己的資料庫才會出現在 API 上。實測到的落差：

    2026-08-12 08:30 ET   BLS 發布 7 月 CPI
    2026-08-12 10:35 ET   FRED 的 CPILFESL 仍停在 6 月（最後更新 7/14）

而排程是 09:45 ET 執行——比 FRED 當天的同步還早。也就是說發布當天
那一版網站抓不到剛出爐的數字，要等隔天。這一層就是為了補上那幾個小時。

設計原則：FRED 仍然是真相來源
------------------------------
這裡**只補最新的那幾點**，歷史一律以 FRED 為準。理由有兩個：

1. **修正追蹤靠 FRED 的 vintage（ALFRED）。** 初值 vs 修正值的比對是這個
   專案的核心功能之一，而 BLS 的 API 不提供 vintage。混用兩個來源當歷史，
   那個比對會對不起來。
2. **BLS 補進來的點是「速報」**，下一次執行 FRED 同步好之後就會被正式值
   取代。畫面上會標示，讀者知道那一點的來源不同。

⚠️ 對應表寫錯會**安靜地**換掉一整條序列
----------------------------------------
FRED 的 ID 跟 BLS 的 ID 大多不一樣（PAYEMS ↔ CES0000000001、
UNRATE ↔ LNS14000000），而且長得完全不像。對應錯了不會報錯——它會拿到
一條**看起來很正常但其實是別的東西**的序列，然後接到畫面上。

所以每一條在接上去之前都要**跟 FRED 已有的重疊期間對帳**：BLS 說的
2026-06 必須等於 FRED 說的 2026-06。對不上就整條拒絕並記錄，寧可等
FRED，也不要接一條來源不明的數字。這道檢查同時擋掉三種錯：
對應表寫錯、季調與否搞混、單位不同（千人 vs 人）。

金鑰
----
沒有金鑰也能用（v1，每天 25 次查詢、一次 25 條序列、10 年區間），
這一層只需要近兩年，額度綽綽有餘。註冊一把免費金鑰（v2）可以放寬到
每天 500 次、一次 50 條——序列變多時再設就好。

    BLS_API_KEY   https://data.bls.gov/registrationEngine/
"""

from __future__ import annotations

import os
import logging

import requests

log = logging.getLogger(__name__)

API_V1 = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
API_V2 = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

TIMEOUT = 45
# 一次請求的序列數上限。v1 是 25、v2 是 50，取小的那個當預設批次大小。
BATCH_V1, BATCH_V2 = 25, 50

# 對帳時要比對幾期。一期可能剛好碰上修正，三期才看得出是不是同一條序列。
OVERLAP_CHECK = 3
# 對帳容差（相對）。同一份原始資料，兩邊的小數位數可能不同（FRED 存三位、
# BLS 給一位），所以不能要求完全相等；但也不能鬆到讓別條序列矇混過關。
TOLERANCE = 0.0015


# ---------------------------------------------------------------------------
# FRED ID → BLS ID
#
# 只列**發布當天會變、而且畫面真的在用**的序列。JOLTS（落後五週）、
# ECI（季頻）這種本來就不急，留給 FRED 就好。
#
# 有一批 FRED ID 本身就是 BLS 的 ID（CUSR0000...、CES...、LNS...），
# 那種不必對應，直接用同一個字串——下面的 _bls_id() 會處理。
# ---------------------------------------------------------------------------
MAP = {
    # ---- CPI（每月中旬 08:30 發布）----
    "CPIAUCSL": "CUSR0000SA0",         # 總體 CPI，季調
    "CPILFESL": "CUSR0000SA0L1E",      # 核心 CPI（扣食物與能源），季調
    "CPIUFDSL": "CUSR0000SAF1",        # 食物
    "CPIENGSL": "CUSR0000SA0E",        # 能源

    # ---- 就業報告（每月第一個週五 08:30 發布）----
    "PAYEMS": "CES0000000001",         # 非農就業總數
    "USPRIV": "CES0500000001",         # 民間部門
    "USGOVT": "CES9000000001",         # 政府部門
    "UNRATE": "LNS14000000",           # 失業率
    "U6RATE": "LNS13327709",           # U-6
    "CIVPART": "LNS11300000",          # 勞動參與率
    "UNEMPLOY": "LNS13000000",         # 失業人數
    "CLF16OV": "LNS11000000",          # 勞動力
    "CE16OV": "LNS12000000",           # 就業人數（家庭調查）
    "CNP16OV": "LNS10000000",          # 民間非機構人口
    "UEMP27OV": "LNS13008636",         # 失業 27 週以上
    "UEMPMED": "LNS13008275",          # 失業週數中位數
    "AHETPI": "CES0500000008",         # 生產與非管理職時薪

    # ---- 行業別（跟就業報告同一份新聞稿）----
    # 行業歸因要拿這些去拆解單月變化。它們必須跟 PAYEMS **同時**推進，
    # 否則會出現「七月的總數配六月的行業拆解」——見 GROUPS 的一致性規則。
    "USMINE": "CES1021000001",         # 礦業與伐木
    "USCONS": "CES2000000001",         # 營建
    "MANEMP": "CES3000000001",         # 製造
    "USWTRADE": "CES4142000001",       # 批發
    "USTRADE": "CES4200000001",        # 零售
    "USINFO": "CES5000000001",         # 資訊
    "USFIRE": "CES5500000001",         # 金融活動
    "USPBS": "CES6000000001",          # 專業與商業服務
    "USLAH": "CES7000000001",          # 休閒與住宿餐飲
    "USSERV": "CES8000000001",         # 其他服務
}

# 同一份新聞稿一起發布的序列。
#
# ⚠️ 為什麼需要分組：**部分更新比不更新更危險。** 如果 PAYEMS 推進到 7 月、
# 行業別卻還停在 6 月，行業歸因就會拿「七月的總數」去配「六月的拆解」，
# 算出來的貢獻度全錯——而畫面上完全看不出異狀。
#
# 規則是：原本就同步的那幾條，要嘛一起推進，要嘛一條都不動。
GROUPS = {
    "cpi": ["CPIAUCSL", "CPILFESL", "CPIUFDSL", "CPIENGSL",
            "CUSR0000SACL1E", "CUSR0000SAH1", "CUSR0000SASLE",
            "CUSR0000SEHA", "CUSR0000SEHC"],
    "jobs": ["PAYEMS", "USPRIV", "USGOVT", "UNRATE", "U6RATE", "CIVPART",
             "UNEMPLOY", "CLF16OV", "CE16OV", "CNP16OV", "UEMP27OV",
             "UEMPMED", "AHETPI", "CES0500000003",
             "USMINE", "USCONS", "MANEMP", "USWTRADE", "USTRADE",
             "USINFO", "USFIRE", "USPBS", "USLAH", "USSERV"],
}

# 這些前綴代表「FRED 直接沿用 BLS 的 ID」，不需要對應表。
_PASSTHROUGH = ("CUSR", "CUUR", "CES", "LNS", "JTS", "CIU", "CIS")


def _bls_id(fred_id: str) -> str:
    """FRED ID 對應的 BLS ID；不在涵蓋範圍內就回空字串。"""
    if fred_id in MAP:
        return MAP[fred_id]
    if fred_id.startswith(_PASSTHROUGH):
        return fred_id
    return ""


def covered(fred_ids) -> list[str]:
    """這批序列裡哪些走得了快速通道。"""
    return [i for i in fred_ids if _bls_id(i)]


# ---------------------------------------------------------------------------
def _to_date(year: str, period: str) -> str:
    """
    BLS 的 (year, period) → FRED 慣用的期初日字串。

    M01–M12 是月份；M13 是年度平均（**要丟掉**，接進月序列會變成一個
    憑空多出來的觀測）。Q01–Q05 是季，S01–S03 是半年，A01 是年度。
    這一層只處理月與季——其餘回空字串代表「不要」。
    """
    p = (period or "").upper()
    try:
        y = int(year)
    except (TypeError, ValueError):
        return ""
    if p.startswith("M"):
        m = int(p[1:] or 0)
        return f"{y:04d}-{m:02d}-01" if 1 <= m <= 12 else ""
    if p.startswith("Q"):
        q = int(p[1:] or 0)
        return f"{y:04d}-{(q - 1) * 3 + 1:02d}-01" if 1 <= q <= 4 else ""
    return ""


class BlsClient:
    def __init__(self, key: str | None = None,
                 session: requests.Session | None = None):
        # 沒有金鑰就走 v1：這一層只要近兩年，25 次／天的額度綽綽有餘。
        self.key = (key if key is not None
                    else (os.environ.get("BLS_API_KEY") or "")).strip()
        self.session = session or requests.Session()
        self.failed: list[tuple[str, str]] = []

    @property
    def url(self) -> str:
        return API_V2 if self.key else API_V1

    @property
    def batch(self) -> int:
        return BATCH_V2 if self.key else BATCH_V1

    def fetch(self, bls_ids: list[str], start_year: int,
              end_year: int) -> dict[str, list[dict]]:
        """
        回傳 {bls_id: [{date, value}]}，時間升冪。抓不到的序列直接不出現。
        """
        out: dict[str, list[dict]] = {}
        ids = list(dict.fromkeys(bls_ids))          # 去重、保序
        for i in range(0, len(ids), self.batch):
            chunk = ids[i:i + self.batch]
            payload = {"seriesid": chunk,
                       "startyear": str(start_year), "endyear": str(end_year)}
            if self.key:
                payload["registrationkey"] = self.key
            try:
                r = self.session.post(self.url, json=payload, timeout=TIMEOUT)
                r.raise_for_status()
                js = r.json()
            except Exception as e:                  # noqa: BLE001
                self.failed.append(("BLS API", str(e)))
                log.warning("BLS 擷取失敗（%s），這一批改用 FRED", e)
                continue
            if (js.get("status") or "").upper() != "REQUEST_SUCCEEDED":
                msg = "；".join(js.get("message") or []) or js.get("status", "")
                self.failed.append(("BLS API", msg))
                log.warning("BLS 回應非成功（%s），這一批改用 FRED", msg)
                continue
            for s in ((js.get("Results") or {}).get("series") or []):
                sid = s.get("seriesID") or ""
                rows = []
                for d in (s.get("data") or []):
                    date = _to_date(d.get("year", ""), d.get("period", ""))
                    if not date:
                        continue
                    try:
                        rows.append({"date": date, "value": float(d["value"])})
                    except (KeyError, TypeError, ValueError):
                        continue
                if rows:
                    rows.sort(key=lambda x: x["date"])
                    out[sid] = rows
        return out


# ---------------------------------------------------------------------------
def _agrees(fred_rows: list[dict], bls_rows: list[dict]) -> tuple[bool, str]:
    """
    重疊期間對帳。回傳 (是否一致, 說明)。

    這是整個模組唯一真正重要的檢查：對應表寫錯、季調與否搞混、單位不同
    （千人 vs 人），三種錯全部在這裡被擋下來。沒有這道檢查的話，一條
    對應錯的序列會安靜地換掉畫面上的數字，而且看起來完全正常。
    """
    fmap = {r["date"]: r["value"] for r in fred_rows}
    checked = 0
    for r in reversed(bls_rows):                    # 由新到舊
        want = fmap.get(r["date"])
        if want is None:
            continue
        if want == 0:
            ok = abs(r["value"]) < 1e-9
        else:
            ok = abs(r["value"] - want) / abs(want) <= TOLERANCE
        if not ok:
            return False, (f"{r['date']} BLS {r['value']:g} "
                           f"≠ FRED {want:g}")
        checked += 1
        if checked >= OVERLAP_CHECK:
            break
    if checked == 0:
        return False, "沒有重疊期間可以對帳"
    return True, f"對帳 {checked} 期一致"


def merge(series: dict, client: BlsClient | None = None,
          years: int = 2, today=None) -> dict:
    """
    把 BLS 比 FRED 新的那幾點補進 series（就地修改）。回傳補了什麼的摘要。

    只補**尾端**：BLS 的期別比 FRED 現有的最後一期新，才會被接上去，
    而且每一點都帶 `provisional: True`，畫面上會標成速報值。
    歷史一個字都不動——修正追蹤仍然完全以 FRED 的 vintage 為準。
    """
    from . import clock
    today = today or clock.today()

    ids = covered(series.keys())
    if not ids:
        return {"added": {}, "rejected": {}, "checked": 0}

    client = client or BlsClient()
    got = client.fetch([_bls_id(i) for i in ids], today.year - years, today.year)
    if not got:
        return {"added": {}, "rejected": {}, "checked": 0}

    # ---- ① 逐條算出「可以補哪幾點」，先不動 series ----
    plan: dict[str, list[dict]] = {}
    rejected: dict[str, str] = {}
    for fid in ids:
        rows_b = got.get(_bls_id(fid)) or []
        rows_f = series.get(fid) or []
        if not rows_b or not rows_f:
            continue
        last_f = rows_f[-1]["date"]
        newer = [r for r in rows_b if r["date"] > last_f]
        if not newer:
            continue
        ok, why = _agrees(rows_f, rows_b)
        if not ok:
            # 對不上就整條拒絕。這通常代表對應表寫錯或季調搞混——
            # 那是程式的問題，不是資料的問題，必須看得見。
            rejected[fid] = why
            continue
        plan[fid] = newer

    # ---- ② 一致性：同一份新聞稿的序列要嘛一起推進，要嘛都不動 ----
    #
    # 只看**原本就同步**的那幾條（FRED 的最後一期相同）。它們本來就該
    # 在同一天一起更新，所以其中一條推進、另一條沒推進，就是壞掉的狀態：
    # 行業歸因會拿新的總數去配舊的拆解，算出來的貢獻度全錯而畫面正常。
    dropped: dict[str, str] = {}
    for gname, members in GROUPS.items():
        have = [m for m in members if series.get(m)]
        if not have:
            continue
        base = max(series[m][-1]["date"] for m in have)
        in_step = [m for m in have if series[m][-1]["date"] == base]
        advancing = [m for m in in_step if m in plan]
        if not advancing or len(advancing) == len(in_step):
            continue                                # 都不動、或都動——都一致
        for m in advancing:                         # 只動了一部分 → 全部退掉
            plan.pop(m, None)
            dropped[m] = gname
        log.warning("BLS 快速通道：%s 這一組只有 %d／%d 條拿得到新資料，"
                    "整組不採用（部分更新會讓行業歸因與分項貢獻對不上期別）",
                    gname, len(advancing), len(in_step))

    # ---- ③ 真的寫進去 ----
    added: dict[str, int] = {}
    for fid, newer in plan.items():
        for r in newer:
            series[fid].append({"date": r["date"], "value": r["value"],
                                "provisional": True})
        added[fid] = len(newer)

    if added:
        log.info("BLS 快速通道：%d 條序列補上 FRED 尚未同步的最新期"
                 "（%s），畫面標示為速報值",
                 len(added), "、".join(sorted(added)[:6])
                 + ("…" if len(added) > 6 else ""))
    if rejected:
        log.error("BLS 對帳失敗，這幾條**不採用**（對應表或季調可能寫錯）：%s",
                  "；".join(f"{k}：{v}" for k, v in list(rejected.items())[:5]))
    return {"added": added, "rejected": rejected,
            "dropped": dropped, "checked": len(ids)}
