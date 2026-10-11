"""每週利差變化（10−2、30−10、30−2）：週五收盤比前一個週五收盤。

週的定義固定在週五（2026-10）：先前以「昨天」為一週終點，週三看是週三比週三、
週五看是週五比週五，同一週的數字隔天就變。週五休市時取該日之前最近的資料日。
"""
from __future__ import annotations
import bisect
import datetime as dt
import math
from .. import clock

SPREAD_LEGS = {"10-2": ("y10", "y2"), "30-10": ("y30", "y10"), "30-2": ("y30", "y2")}


def last_friday(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=(day.weekday() - 4) % 7)


def weekly_spreads(cd: dict, start: str | None = None, end: str | None = None,
                   weeks: int = 6, cutoff: str | None = None, key: str = "30-2") -> dict:
    cutoff = cutoff or (clock.today() - dt.timedelta(days=1)).isoformat()
    end_day = last_friday(min(dt.date.fromisoformat(end or cutoff), dt.date.fromisoformat(cutoff)))
    start_day = dt.date.fromisoformat(start) if start else end_day - dt.timedelta(days=7 * (weeks - 1))
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
    targets = []
    t = end_day
    while t >= start_day:
        targets.append(t)
        t -= dt.timedelta(days=7)
    rows = []
    for target in reversed(targets):
        a, b = point(target - dt.timedelta(days=7)), point(target)
        valid = bool(a and b and a["date"] < b["date"])
        rows.append({"target": target.isoformat(), "from": a["date"] if a else None,
                     "to": b["date"] if b else None, "previous": a["value"] if valid else None,
                     "value": b["value"] if valid else None,
                     "change": round(b["value"] - a["value"], 8) if valid else None})
    return {"start": start_day.isoformat(), "end": end_day.isoformat(), "rows": rows, "key": key}
