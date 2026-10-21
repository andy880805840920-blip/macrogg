"""每週利差變化（10−2、30−10、30−2）：週五收盤比前一個週五收盤。

週的定義固定在週五（2026-10）：先前以「昨天」為一週終點，週三看是週三比週三、
週五看是週五比週五，同一週的數字隔天就變。週五休市時取該日之前最近的資料日。

自訂期間（2026-10 v2）：從使用者選的開始日起算，每 7 天一根（開始日→+7 天→+14 天…），
最後一根到結束日為止；不足 7 天的那根標「（n 天）」。最多 52 根。
"""
from __future__ import annotations
import bisect
import datetime as dt
import math
from .. import clock

MAX_BARS = 52
SPREAD_LEGS = {"10-2": ("y10", "y2"), "30-10": ("y30", "y10"), "30-2": ("y30", "y2")}


def last_friday(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=(day.weekday() - 4) % 7)


def weekly_spreads(cd: dict, start: str | None = None, end: str | None = None,
                   weeks: int = 6, cutoff: str | None = None, key: str = "30-2") -> dict:
    cutoff = cutoff or (clock.today() - dt.timedelta(days=1)).isoformat()
    cut_day = dt.date.fromisoformat(cutoff)
    anchored = bool(start)
    if anchored:                                 # 自訂：從開始日起每 7 天一根，結束日不對齊週五
        end_day = min(dt.date.fromisoformat(end or cutoff), cut_day)
        start_day = dt.date.fromisoformat(start)
    else:
        end_day = last_friday(min(dt.date.fromisoformat(end or cutoff), cut_day))
        start_day = end_day - dt.timedelta(days=7 * (weeks - 1))
    if start_day > end_day:
        raise ValueError("開始日期須早於或等於結束日期")
    lk, sk = SPREAD_LEGS[key]
    common = {}
    for i, date in enumerate(cd.get("d") or []):
        a, b = cd.get(sk) or [], cd.get(lk) or []
        if i >= len(a) or i >= len(b) or a[i] is None or b[i] is None:
            continue
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (a[i], b[i])):
            continue
        if date <= cutoff:
            common[date] = (b[i] - a[i]) * 100
    dates = sorted(common)

    def point(target):
        j = bisect.bisect_right(dates, target.isoformat()) - 1
        if j < 0:
            return None
        actual = dt.date.fromisoformat(dates[j])
        if (target - actual).days > 7:
            return None
        return {"date": dates[j], "value": round(common[dates[j]], 8)}
    spans = []                                   # (起點, 終點)
    if anchored:
        t = start_day
        while t < end_day:
            spans.append((t, min(t + dt.timedelta(days=7), end_day)))
            t += dt.timedelta(days=7)
        if len(spans) > MAX_BARS:
            raise ValueError(f"期間最多 {MAX_BARS} 週")
    else:
        t = end_day
        while t >= start_day:
            spans.append((t - dt.timedelta(days=7), t))
            t -= dt.timedelta(days=7)
        spans.reverse()
    rows = []
    for s0, s1 in spans:
        a, b = point(s0), point(s1)
        valid = bool(a and b and a["date"] < b["date"])
        rows.append({"target": s1.isoformat(), "begin": s0.isoformat(), "days": (s1 - s0).days,
                     "from": a["date"] if a else None,
                     "to": b["date"] if b else None, "previous": a["value"] if valid else None,
                     "value": b["value"] if valid else None,
                     "change": round(b["value"] - a["value"], 8) if valid else None})
    return {"start": start_day.isoformat(), "end": end_day.isoformat(), "rows": rows, "key": key,
            "anchored": anchored}
