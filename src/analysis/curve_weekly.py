"""Calendar-week changes in the aligned official 30Y−2Y daily spread."""
from __future__ import annotations
import bisect
import datetime as dt
import math
from .. import clock


def weekly_spreads(cd: dict, start: str | None = None, end: str | None = None,
                   weeks: int = 6, cutoff: str | None = None) -> dict:
    cutoff = cutoff or (clock.today() - dt.timedelta(days=1)).isoformat()
    end_day = min(dt.date.fromisoformat(end or cutoff), dt.date.fromisoformat(cutoff))
    start_day = dt.date.fromisoformat(start) if start else end_day - dt.timedelta(days=7 * (weeks - 1))
    if start_day > end_day:
        raise ValueError("開始日期須早於或等於結束日期")
    common = {}
    for i, date in enumerate(cd.get("d") or []):
        a, b = cd.get("y2") or [], cd.get("y30") or []
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
    return {"start": start_day.isoformat(), "end": end_day.isoformat(), "rows": rows}
