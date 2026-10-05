"""
PCE 細項（BEA 原始檔）：電腦軟體與配件對核心 PCE 的貢獻
==========================================================

為什麼要這一項（2026-10 使用者指出）
-----------------------------------
核心 CPI 與核心 PCE 的短期年化背離，有一塊來自「電腦軟體與配件」：
PCE 版含記憶體、儲存等配件，AI 需求推升 DRAM／Flash 價格時漲得很兇，
而且在 PCE 的權重遠大於 CPI 的同名項目。聯準會 2026-05 的 FEDS Notes
估計，2026 年 3 月這一項就貢獻了核心 PCE 四個月年化約 0.6 個百分點。

BEA 9/30 年度修正起，這一項改用「CPI＋多項 PPI」的綜合指數（見通膨頁的
PCE 方法說明）。這裡用的永遠是 BEA 最新公布的版本。

資料來源
--------
FRED 沒有收這一層細項，所以直接讀 BEA 的 NIPA 月資料原始檔
（apps.bea.gov/national/Release/TXT/NipaDataM.txt，約 35 MB，邊下載邊篩，
只留需要的三條序列）。不需要金鑰。

  DCPSRG  電腦軟體與配件　價格指數（Fisher）
  DCPSRC  電腦軟體與配件　名目支出（百萬美元）
  DPCCRC  核心 PCE（剔除食物與能源）名目支出

貢獻的算法（近似，畫面標「約」）
------------------------------
  權重 w      ＝ 該項名目支出 ÷ 核心 PCE 名目支出（取期初那個月）
  年增貢獻    ＝ w(t−12) × 該項年增率
  三月年化貢獻 ＝ 4 × w(t−3) × 該項三個月變化率
BEA 的鏈式加總不是單純加權，這是一階近似——足以回答「這一項推了多少」，
但不能拿來精確還原官方數字。
"""
from __future__ import annotations

import logging

import requests

log = logging.getLogger(__name__)

BEA_URL = "https://apps.bea.gov/national/Release/TXT/NipaDataM.txt"
CODES = ("DCPSRG", "DCPSRC", "DPCCRC")
TIMEOUT = 90
PREFIX = "BEA:"


def _parse_line(line: str):
    # 格式：SeriesCode,Period,Value  例：DCPSRG,2026M08,"84.552"
    parts = line.split(",", 2)
    if len(parts) < 3:
        return None
    code, period, val = parts[0].strip('"'), parts[1], parts[2]
    if code not in CODES or "M" not in period:
        return None
    try:
        v = float(val.strip().strip('"').replace(",", ""))
    except ValueError:
        return None
    y, m = period.split("M")
    return code, f"{int(y):04d}-{int(m):02d}-01", v


def fetch_bea(_get=None) -> dict:
    """回傳 {"BEA:DCPSRG": [{date, value}], ...}；失敗回空 dict（區塊不顯示）。"""
    out: dict = {PREFIX + c: [] for c in CODES}
    try:
        if _get is not None:
            lines = _get(BEA_URL)
        else:
            r = requests.get(BEA_URL, timeout=TIMEOUT, stream=True,
                             headers={"User-Agent": "Mozilla/5.0 (macro-dashboard)"})
            r.raise_for_status()
            lines = (ln.decode("utf-8", "ignore") if isinstance(ln, bytes) else ln
                     for ln in r.iter_lines())
        for ln in lines:
            p = _parse_line(ln)
            if p:
                out[PREFIX + p[0]].append({"date": p[1], "value": p[2]})
    except Exception as e:                         # noqa: BLE001
        log.warning("BEA 細項抓取失敗（%s），軟體與配件的貢獻本次不顯示", e)
        return {}
    for k in out:
        out[k].sort(key=lambda r: r["date"])
    if not all(out.values()):
        log.warning("BEA 細項有序列沒抓到（%s）",
                    "、".join(k for k, v in out.items() if not v))
        return {}
    log.info("BEA 細項：電腦軟體與配件到 %s", out[PREFIX + "DCPSRG"][-1]["date"])
    return out


def _at(rows: list, date: str):
    return next((r["value"] for r in rows if r["date"] == date), None)


def _shift(date: str, k: int) -> str:
    y, m = int(date[:4]), int(date[5:7])
    n = y * 12 + (m - 1) - k
    return f"{n // 12:04d}-{n % 12 + 1:02d}-01"


def software_contribution(series: dict) -> dict | None:
    """
    回傳 {month, weight, price_yoy, price_3m, contrib_yoy, contrib_3m,
          core_pce_yoy, core_pce_3m, ex_3m}；資料不足回 None。
    core_pce_* 用 FRED 的 PCEPILFE（同一個 BEA 指數），ex_3m＝剔除這一項後的
    核心 PCE 三月年化（近似）。
    """
    p = series.get(PREFIX + "DCPSRG") or []
    c = series.get(PREFIX + "DCPSRC") or []
    core = series.get(PREFIX + "DPCCRC") or []
    if not p or not c or not core:
        return None
    d = p[-1]["date"]
    d3, d12 = _shift(d, 3), _shift(d, 12)
    p0, p3, p12 = _at(p, d), _at(p, d3), _at(p, d12)
    w3 = (_at(c, d3) or 0) / (_at(core, d3) or 1) * 100
    w12 = (_at(c, d12) or 0) / (_at(core, d12) or 1) * 100
    w0 = (_at(c, d) or 0) / (_at(core, d) or 1) * 100
    if None in (p0, p3, p12) or not w3 or not w12:
        return None
    r3 = (p0 / p3 - 1) * 100
    yoy = (p0 / p12 - 1) * 100
    out = {"month": d[:7], "weight": w0,
           "price_yoy": yoy, "price_3m": ((p0 / p3) ** 4 - 1) * 100,
           "contrib_yoy": w12 / 100 * yoy, "contrib_3m": 4 * w3 / 100 * r3}
    pce = {r["date"]: r["value"] for r in series.get("PCEPILFE") or []}
    if d in pce and d3 in pce and d12 in pce:
        out["core_pce_3m"] = ((pce[d] / pce[d3]) ** 4 - 1) * 100
        out["core_pce_yoy"] = (pce[d] / pce[d12] - 1) * 100
        out["ex_3m"] = out["core_pce_3m"] - out["contrib_3m"]
    return out
