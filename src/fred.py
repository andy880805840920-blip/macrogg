"""
FRED / ALFRED 資料擷取層。

設計重點
--------
1. 所有抓取結果都寫進 SQLite，並記錄 `fetched_at`。
   這樣從第二次執行開始，就算 ALFRED 掛掉也能靠本地快照做修正追蹤。
2. 單一序列抓不到時「記錄並跳過」，不讓整個流程崩掉。
   （FRED 偶爾會改 series id，或某些序列需要不同權限）
3. API key 從環境變數 FRED_API_KEY 讀取，不寫進程式碼。
"""

from __future__ import annotations

import os
import time
import logging
import datetime as dt
from typing import Any

import requests

from . import clock

log = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred"
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0


class FredError(RuntimeError):
    pass


class FredAuthError(FredError):
    """API key 本身被 FRED 拒絕。這種錯誤重試沒有意義，也不該逐序列吞掉。"""


class FredClient:
    def __init__(self, api_key: str | None = None, session: requests.Session | None = None):
        # 一定要 strip()。從網頁複製 key 時很容易帶到尾端空白或換行，
        # 這種 key 送出去會被 FRED 判為無效，而且錯誤訊息看不出原因。
        self.api_key = (api_key or os.environ.get("FRED_API_KEY", "")).strip()
        if not self.api_key:
            raise FredError(
                "找不到 FRED API key。請設定環境變數 FRED_API_KEY，"
                "或在建立 FredClient 時傳入 api_key。"
            )
        self.session = session or requests.Session()
        self.failed: list[tuple[str, str]] = []   # (series_id, 錯誤訊息)

    # ------------------------------------------------------------------
    # 底層請求
    # ------------------------------------------------------------------
    def _get(self, endpoint: str, params: dict[str, Any]) -> dict:
        params = {**params, "api_key": self.api_key, "file_type": "json"}
        url = f"{FRED_BASE}/{endpoint}"
        last_err: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                r = self.session.get(url, params=params, timeout=DEFAULT_TIMEOUT)
                if r.status_code == 429:          # 觸發限流，等久一點再試
                    time.sleep(RETRY_BACKOFF * (attempt + 2))
                    continue
                # FRED 對「key 無效」回的是 400，不是 401。這種錯誤重試沒有意義，
                # 而且若照一般失敗處理，56 個序列會各噴一次同樣的訊息，
                # 最後還產出一份沒有資料的頁面覆蓋掉上一版——比直接失敗更糟。
                if r.status_code == 400:
                    msg = ""
                    try:
                        msg = (r.json() or {}).get("error_message", "")
                    except Exception:             # noqa: BLE001
                        msg = r.text[:200]
                    if "api_key" in msg.lower():
                        raise FredAuthError(
                            f"FRED 拒絕這組 API key（{msg}）。"
                            "請確認 FRED_API_KEY 的值正確、沒有多餘空白，"
                            "且已在 fredaccount.stlouisfed.org 啟用。"
                        )
                r.raise_for_status()
                return r.json()
            except FredAuthError:                 # 直接往上拋，不重試也不記錄
                raise
            except Exception as e:                # noqa: BLE001
                last_err = e
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF * (attempt + 1))
        raise FredError(f"{endpoint} 請求失敗：{last_err}")

    # ------------------------------------------------------------------
    # 觀測值
    # ------------------------------------------------------------------
    def observations(
        self,
        series_id: str,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict]:
        """取得單一序列的最新（已修正）觀測值。"""
        params: dict[str, Any] = {"series_id": series_id, "sort_order": "asc"}
        if start:
            params["observation_start"] = start
        if end:
            params["observation_end"] = end

        data = self._get("series/observations", params)
        out = []
        for obs in data.get("observations", []):
            v = obs.get("value")
            if v in (".", "", None):              # FRED 用 "." 表示缺值
                continue
            try:
                out.append({"date": obs["date"], "value": float(v)})
            except (TypeError, ValueError):
                continue
        return out

    def observations_safe(self, series_id: str, **kw) -> list[dict]:
        """抓不到就回空陣列並記錄，不中斷流程。"""
        try:
            rows = self.observations(series_id, **kw)
            if not rows:
                self.failed.append((series_id, "回傳空資料"))
            return rows
        except FredAuthError:                     # key 有問題就不必再試其他序列
            raise
        except Exception as e:                    # noqa: BLE001
            log.warning("序列 %s 抓取失敗：%s", series_id, e)
            self.failed.append((series_id, str(e)))
            return []

    # ------------------------------------------------------------------
    # ALFRED — 歷史版本（修正追蹤的命脈）
    # ------------------------------------------------------------------
    def vintages(self, series_id: str, start: str, n_vintages: int = 6) -> dict[str, dict[str, float]]:
        """
        取得最近幾個發布版本的資料。

        回傳 {vintage_date: {obs_date: value}}

        用 output_type=2（每個 vintage 一欄）。為了控制 payload，
        observation_start 一定要給，而且只取最近幾個 vintage。
        """
        try:
            vd = self._get("series/vintagedates", {"series_id": series_id, "sort_order": "desc"})
            all_dates = vd.get("vintage_dates", [])
            if not all_dates:
                return {}
            picked = sorted(all_dates[:n_vintages])
        except Exception as e:                    # noqa: BLE001
            log.warning("%s 的 vintage 日期抓取失敗：%s", series_id, e)
            return {}

        try:
            data = self._get(
                "series/observations",
                {
                    "series_id": series_id,
                    "observation_start": start,
                    "output_type": 2,             # 每個 vintage 一欄
                    "vintage_dates": ",".join(picked),
                    "sort_order": "asc",
                },
            )
        except Exception as e:                    # noqa: BLE001
            log.warning("%s 的 vintage 觀測值抓取失敗：%s", series_id, e)
            return {}

        # 回傳格式的欄名長這樣：PAYEMS_20260807
        result: dict[str, dict[str, float]] = {}
        for obs in data.get("observations", []):
            obs_date = obs.get("date")
            for k, v in obs.items():
                if k == "date" or not k.startswith(series_id + "_"):
                    continue
                raw = k.split("_", 1)[1]
                try:
                    vdate = dt.datetime.strptime(raw, "%Y%m%d").date().isoformat()
                except ValueError:
                    vdate = raw
                if v in (".", "", None):
                    continue
                try:
                    result.setdefault(vdate, {})[obs_date] = float(v)
                except (TypeError, ValueError):
                    continue
        return result

    # ------------------------------------------------------------------
    # 序列的中繼資料（用來抓「資料截止日」與「最後更新時間」）
    # ------------------------------------------------------------------
    def series_meta(self, series_id: str) -> dict:
        try:
            data = self._get("series", {"series_id": series_id})
            s = (data.get("seriess") or [{}])[0]
            return {
                "id": series_id,
                "title": s.get("title", ""),
                "units": s.get("units_short", ""),
                "frequency": s.get("frequency_short", ""),
                "last_updated": s.get("last_updated", ""),
                "observation_end": s.get("observation_end", ""),
            }
        except Exception as e:                    # noqa: BLE001
            log.warning("%s 的中繼資料抓取失敗：%s", series_id, e)
            return {"id": series_id}

    # ------------------------------------------------------------------
    # 官方發布行事曆
    # ------------------------------------------------------------------
    def next_release(self, release_id: int, after: dt.date | None = None
                     ) -> dt.date | None:
        """
        某個 FRED release 的下一個發布日。抓不到就回 None，由呼叫端退回慣例推估。

        為什麼要打這支：先前的倒數是用「次月第一個週五」「次月第 12 天前後」
        這種**慣例**推的。慣例大多數月份是對的，但一年總有幾次不對——
        BLS 遇到聯邦假日會挪動，2026 年 1 月的就業報告就不在第一個週五。
        FRED 直接提供官方行事曆（release/dates），沒有理由自己猜。

        release_id：就業報告 50、CPI 10（見 RELEASE_IDS）。
        """
        after = after or clock.today()
        try:
            data = self._get("release/dates", {
                "release_id": release_id,
                "realtime_start": after.isoformat(),
                # FRED 預設只回「已經發生」的日期，要未來的必須明講
                "include_release_dates_with_no_data": "true",
                "sort_order": "asc",
                "limit": 12,
            })
            for row in data.get("release_dates") or []:
                d = dt.date.fromisoformat(row["date"])
                if d > after:
                    return d
        except Exception as e:                    # noqa: BLE001
            log.warning("release %s 的行事曆抓取失敗：%s", release_id, e)
        return None


# FRED release id。改這裡之前先用
#   https://api.stlouisfed.org/fred/releases?api_key=…&file_type=json
# 確認 id 沒有變。
RELEASE_IDS = {
    "employment": 50,      # Employment Situation（就業報告）
    "cpi": 10,             # Consumer Price Index
}


def fetch_all(client: FredClient, series_ids: list[str], start: str) -> dict[str, list[dict]]:
    """批次抓取，逐一容錯。回傳 {series_id: observations}"""
    out: dict[str, list[dict]] = {}
    for i, sid in enumerate(series_ids, 1):
        out[sid] = client.observations_safe(sid, start=start)
        log.info("[%d/%d] %s — %d 筆", i, len(series_ids), sid, len(out[sid]))
        time.sleep(0.12)      # 對 FRED 客氣一點
    return out
