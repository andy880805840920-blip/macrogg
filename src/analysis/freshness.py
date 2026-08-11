"""
資料新鮮度檢查。

要解決的問題
------------
FRED 偶爾會停止更新某條序列（改 series id、來源機關改版、政府停擺），
而這件事**不會報錯**：抓取成功、回傳一整串觀測值，只是最後一筆是三個月前的。
頁面照樣產出、照樣寫著今天的日期，讀者沒有任何線索知道那個數字已經過期。
逐序列容錯保護的是「抓不到」，這裡保護的是「抓得到但是舊的」。

判斷方式
--------
不打額外的 API（FRED 的 series 端點雖然有 last_updated，但那要一條一條問，
而且它回答的是「檔案什麼時候被碰過」，不是「資料到哪一期」）。
改成只看已經抓回來的觀測值：最後一筆的日期，離今天有幾個發布週期。

容忍度要按頻率給，而且要留給發布時差：
    月頻 — 資料月結束後約兩週才發布，所以正常就會落後一個多月
    週頻 — 隔週發布
    季頻 — 季末後一個多月
超過容忍值才算「停更」。這裡刻意寬鬆，寧可漏報也不要每個月月初都跳警告。
"""
from __future__ import annotations

import datetime as dt

# series_id → (中文名, 頻率)
# 只列「過期會讓頁面結論失效」的核心序列。參照用、背景用的序列不列，
# 那些即使舊一點也不影響任何一句結論，列進來只會製造雜訊。
WATCH: dict[str, tuple[str, str]] = {
    "PAYEMS": ("非農就業", "monthly"),
    "UNRATE": ("失業率", "monthly"),
    "CE16OV": ("家庭調查就業", "monthly"),
    "CIVPART": ("勞動參與率", "monthly"),
    "ICSA": ("初領失業金", "weekly"),
    "CCSA": ("續領失業金", "weekly"),
    "CPIAUCSL": ("CPI", "monthly"),
    "CPILFESL": ("核心 CPI", "monthly"),
    "PCEPILFE": ("核心 PCE", "monthly"),
    "DGS10": ("10 年期公債", "daily"),
    "DGS30": ("30 年期公債", "daily"),
}

# 頻率 → 容忍幾天沒有新資料。已經把發布時差算進去。
TOLERANCE = {
    "daily": 12,        # 連假 ＋ 週末，再加一點緩衝
    "weekly": 21,       # 正常落後約 5–12 天
    "monthly": 75,      # 資料月結束後約兩週發布 → 正常落後 30–45 天
    "quarterly": 165,
}


def check(series: dict[str, list[dict]], today: dt.date | None = None) -> list[dict]:
    """
    回傳過期的序列清單：[{id, label, last, days, tolerance}]。

    沒有資料的序列**不算過期**——那是抓取失敗，已經由 failed 清單負責，
    在這裡再報一次會讓同一件事在畫面上出現兩遍。
    """
    today = today or dt.date.today()
    stale = []
    for sid, (label, freq) in WATCH.items():
        rows = series.get(sid) or []
        if not rows:
            continue
        try:
            last = dt.date.fromisoformat(rows[-1]["date"])
        except (ValueError, KeyError, TypeError):
            continue
        tol = TOLERANCE.get(freq, 90)
        days = (today - last).days
        if days > tol:
            stale.append({"id": sid, "label": label, "freq": freq,
                          "last": last.isoformat(), "days": days,
                          "tolerance": tol})
    stale.sort(key=lambda x: x["days"] - x["tolerance"], reverse=True)
    return stale


def banner_html(stale: list[dict], esc) -> str:
    """過期警告條。沒有過期就回傳空字串，不佔版面。"""
    if not stale:
        return ""
    items = "、".join(
        f"{esc(s['label'])}（最新 {esc(s['last'])}，已 {s['days']} 天沒有新資料）"
        for s in stale[:4])
    more = f"，另有 {len(stale) - 4} 條" if len(stale) > 4 else ""
    return (f'<div class="banner"><b>⚠ 有資料序列停止更新</b>：{items}{more}。'
            f'頁面上的結論仍然是照最後一筆資料算的——'
            f'在來源恢復之前，這些數字不代表當前狀況。</div>')
