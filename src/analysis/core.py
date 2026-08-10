"""共用的序列運算工具。全部用純 Python，不依賴 pandas，方便在任何環境跑。"""

from __future__ import annotations

from typing import Sequence


def to_map(rows: Sequence[dict]) -> dict[str, float]:
    return {r["date"]: r["value"] for r in rows}


def latest(rows: Sequence[dict], n: int = 1):
    """回傳最後 n 筆（時間升冪）。n=1 時回傳單筆 dict，否則回傳 list。"""
    if not rows:
        return None if n == 1 else []
    tail = list(rows)[-n:]
    return tail[0] if n == 1 else tail


def value_at(rows: Sequence[dict], idx_from_end: int = 0) -> float | None:
    """idx_from_end=0 是最新一筆，1 是前一筆，以此類推。"""
    if not rows or len(rows) <= idx_from_end:
        return None
    return rows[-1 - idx_from_end]["value"]


def diff(rows: Sequence[dict], idx_from_end: int = 0) -> float | None:
    """該期相對前一期的變動。"""
    cur = value_at(rows, idx_from_end)
    prev = value_at(rows, idx_from_end + 1)
    if cur is None or prev is None:
        return None
    return cur - prev


def diff_series(rows: Sequence[dict]) -> list[dict]:
    """把水準值序列轉成月變動序列。"""
    out = []
    for i in range(1, len(rows)):
        out.append({"date": rows[i]["date"], "value": rows[i]["value"] - rows[i - 1]["value"]})
    return out


def yoy(rows: Sequence[dict], periods: int = 12) -> float | None:
    if len(rows) <= periods:
        return None
    cur = rows[-1]["value"]
    old = rows[-1 - periods]["value"]
    if old == 0:
        return None
    return (cur / old - 1) * 100


def mom_pct(rows: Sequence[dict]) -> float | None:
    if len(rows) < 2:
        return None
    cur, prev = rows[-1]["value"], rows[-2]["value"]
    if prev == 0:
        return None
    return (cur / prev - 1) * 100


def annualized(rows: Sequence[dict], months: int) -> float | None:
    """近 N 個月的年化變動率（%）。"""
    if len(rows) <= months:
        return None
    cur = rows[-1]["value"]
    old = rows[-1 - months]["value"]
    if old <= 0:
        return None
    return ((cur / old) ** (12 / months) - 1) * 100


def moving_avg(rows: Sequence[dict], n: int) -> float | None:
    if len(rows) < n:
        return None
    vals = [r["value"] for r in rows[-n:]]
    return sum(vals) / n


def moving_avg_series(rows: Sequence[dict], n: int) -> list[dict]:
    out = []
    for i in range(n - 1, len(rows)):
        window = [r["value"] for r in rows[i - n + 1 : i + 1]]
        out.append({"date": rows[i]["date"], "value": sum(window) / n})
    return out


def sahm_rule(unrate_rows: Sequence[dict]) -> float | None:
    """
    Sahm Rule：近三個月失業率均值 減去 前 12 個月的三個月均值最低點。
    超過 0.50 歷史上代表衰退已經開始。
    """
    ma3 = moving_avg_series(unrate_rows, 3)
    if len(ma3) < 13:
        return None
    current = ma3[-1]["value"]
    trough = min(r["value"] for r in ma3[-13:-1])
    return round(current - trough, 3)


def zscore(rows: Sequence[dict], lookback: int = 60) -> float | None:
    """
    相對近 N 期的標準分數。用於綜合評分。

    實際窗口是 min(lookback, 資料長度)——抓取起點縮短後窗口會跟著變短，
    所以畫面上的說明要用 zscore_window() 取得**實際**期數，
    不能寫死「近五年」，那會變成假話。
    """
    if len(rows) < 12:
        return None
    window = [r["value"] for r in rows[-lookback:]]
    n = len(window)
    mean = sum(window) / n
    var = sum((v - mean) ** 2 for v in window) / max(n - 1, 1)
    sd = var ** 0.5
    if sd == 0:
        return None
    return (rows[-1]["value"] - mean) / sd


def zscore_window(rows: Sequence[dict], lookback: int = 60) -> int:
    """z-score 實際用到的期數，供畫面標示。"""
    return min(len(rows), lookback) if len(rows) >= 12 else 0


def fmt_num(v: float | None, unit: str = "", digits: int = 1) -> str:
    if v is None:
        return "—"
    if unit == "thousands":
        return f"{v:+,.0f}K" if abs(v) < 1000 else f"{v:+,.0f}K"
    if unit == "percent":
        return f"{v:.{digits}f}%"
    if unit == "persons":
        return f"{v:,.0f}"
    return f"{v:,.{digits}f}"


def yoy_series(rows: Sequence[dict], periods: int = 12) -> list[dict]:
    """
    把「指數水準」轉成「年增率」序列。

    為什麼需要：物價指數、平均時薪這類序列只會一路往上，
    直接畫水準值就是一條斜線，看不出任何訊息。
    要畫的是變化率，不是水準。
    """
    out = []
    for i in range(periods, len(rows)):
        old = rows[i - periods]["value"]
        if old:
            out.append({"date": rows[i]["date"],
                        "value": (rows[i]["value"] / old - 1) * 100})
    return out


def annualized_series(rows: Sequence[dict], months: int = 3) -> list[dict]:
    """近 N 個月年化的序列，比年增率更早反映轉折。"""
    out = []
    for i in range(months, len(rows)):
        old = rows[i - months]["value"]
        if old > 0:
            out.append({"date": rows[i]["date"],
                        "value": ((rows[i]["value"] / old) ** (12 / months) - 1) * 100})
    return out


def since(rows: Sequence[dict], start: str, min_points: int = 6) -> list[dict]:
    """
    只取 start（YYYY-MM-DD）之後的資料。

    全站圖表共用同一個起點，否則會出現「就業圖只有今年、財政圖畫到五年前」
    這種各說各話的狀況——讀者無法比對，也不知道哪張圖代表什麼期間。

    不足 min_points 筆時回退到最後 min_points 筆，避免季資料（一年才四筆）
    在起點附近變成一條沒有形狀的線。
    """
    if not rows:
        return []
    cut = [r for r in rows if r["date"] >= start]
    return cut if len(cut) >= min_points else list(rows)[-min_points:]


def span_label(rows: Sequence[dict]) -> str:
    """
    圖表標題用的期間字串，直接由畫出來的資料推得。

    寫死「今年以來」會在兩個地方說謊：全站起點是 2025-01-01 而不是當年年初；
    季資料觸發 since() 的 min_points 回退時，實際起點還會早於 2025 年。
    """
    if not rows:
        return ""
    d = rows[0]["date"]
    return f"{d[:4]} 年 {int(d[5:7])} 月以來"


def since_year_start(rows: Sequence[dict], min_points: int = 6) -> list[dict]:
    """只取今年以來的資料。保留給仍需要「本年度」語意的地方。"""
    if not rows:
        return []
    year = rows[-1]["date"][:4]
    cut = [r for r in rows if r["date"] >= f"{year}-01-01"]
    return cut if len(cut) >= min_points else list(rows)[-min_points:]
