"""時間序列完整性規則：日期、排序、重複、未來值與缺值。"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from .. import clock



@dataclass(frozen=True)
class SeriesIssue:
    series_id: str
    kind: str
    detail: str
    severity: str = "error"


def validate_series(series_id: str, rows: list[dict], *,
                    today: dt.date | None = None,
                    allow_future: bool = False) -> list[SeriesIssue]:
    today = today or clock.today()
    issues: list[SeriesIssue] = []
    parsed: list[tuple[dt.date, int]] = []
    for i, row in enumerate(rows):
        raw = str(row.get("date") or "")
        try:
            day = dt.date.fromisoformat(raw[:10])
            parsed.append((day, i))
        except ValueError:
            issues.append(SeriesIssue(series_id, "invalid_date", f"第 {i+1} 筆日期 {raw!r} 無效"))
            continue
        value = row.get("value")
        if value is None:
            issues.append(SeriesIssue(series_id, "missing_value", f"{raw} 沒有數值"))
        elif not isinstance(value, (int, float)):
            issues.append(SeriesIssue(series_id, "invalid_value", f"{raw} 的數值不是數字"))
        if day > today and not allow_future:
            issues.append(SeriesIssue(series_id, "future_actual", f"{raw} 晚於今天 {today}"))

    dates = [x[0] for x in parsed]
    if dates != sorted(dates):
        issues.append(SeriesIssue(series_id, "out_of_order", "日期不是由舊到新排序"))
    seen: set[dt.date] = set()
    dupes: list[str] = []
    for day in dates:
        if day in seen:
            dupes.append(day.isoformat())
        seen.add(day)
    if dupes:
        issues.append(SeriesIssue(series_id, "duplicate_date", "重複日期：" + "、".join(sorted(set(dupes)))))
    return issues


def audit_bundle(series: dict[str, list[dict]], *,
                 today: dt.date | None = None,
                 forecast_ids: set[str] | None = None) -> list[SeriesIssue]:
    forecast_ids = forecast_ids or set()
    issues: list[SeriesIssue] = []
    for sid, rows in series.items():
        if not rows:
            continue
        issues.extend(validate_series(sid, rows, today=today,
                                      allow_future=sid in forecast_ids))
    return issues


def assert_clean(series: dict[str, list[dict]], **kwargs) -> None:
    issues = audit_bundle(series, **kwargs)
    errors = [x for x in issues if x.severity == "error"]
    if errors:
        msg = "；".join(f"{x.series_id}/{x.kind}: {x.detail}" for x in errors[:8])
        raise ValueError(f"時間序列完整性檢查失敗：{msg}")
