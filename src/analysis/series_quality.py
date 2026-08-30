"""時間序列完整性規則：日期、排序、重複、未來值與缺值。

未來日期分三類處理
------------------
① **一般序列（預設）**：零容忍。`clock.today()` 取的是台北日期，台北比
   美國早 12–15 小時，所以美國口徑的序列日期正常情況下**永遠不可能**
   超過台北的今天——一旦出現就是很強的異常訊號，值得停止發布。

② **預測路徑**（`forecast_ids`）：SEP、CBO 這類本來就是未來值，
   長期預測會延伸好幾年，無上限放行。

③ **行政設定利率**（`administered_ids`）：IORB 與政策利率區間上下緣。
   這類利率由聯準會直接訂定、生效前數值就已知，FRED 因此照實往前貼——
   實例：2026-08-28（週五）就貼出 2026-08-31（週一）的 IORB，於是
   週末的排程全部撞上「未來資料」而停止發布。允許超前，但**有上限**：
   超前幾天是正常，掛著明年的日期仍然是真的壞掉，照樣要擋。

   判準是「這個數字是**先被決定**、還是**先被觀測到**」：SOFR、ON RRP、
   SRF 是事後統計（隔天才公布），殖利率是市場收盤價——結構上不可能
   超前，一律不列入。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from .. import clock


# 行政利率容許超前的天數。合法的最長超前是跨長假——週五貼出下一個
# 營業日的值，遇到週一放假就是 +4 天（實際遇到的是 +3）。7 天容得下
# 感恩節、聖誕節那種連假群，又離「壞掉的日期」（動輒幾個月、幾年）
# 很遠。這是資料來源的性質、不是可以調校的偏好，所以寫在程式裡，
# 不放進 config。
ADMINISTERED_FUTURE_DAYS = 7


@dataclass(frozen=True)
class SeriesIssue:
    series_id: str
    kind: str
    detail: str
    severity: str = "error"          # error＝停止發布／info＝只記錄


def validate_series(series_id: str, rows: list[dict], *,
                    today: dt.date | None = None,
                    allow_future: bool = False,
                    future_days: int = 0) -> list[SeriesIssue]:
    """
    單一序列的檢查。`allow_future` 是無上限放行（預測路徑），
    `future_days` 是有上限的容許（行政設定利率）——兩者不同層級，
    不要混用。超前但在容許內會留下一筆 severity="info" 的紀錄，
    讓執行紀錄說得出「為什麼這條序列有未來日期」。
    """
    today = today or clock.today()
    issues: list[SeriesIssue] = []
    parsed: list[tuple[dt.date, int]] = []
    ahead_days = 0
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
            ahead = (day - today).days
            if ahead > future_days:
                # 訊息把差距與容許值都寫出來：日後在 Actions log 一眼
                # 就能判斷是正常超前、還是這條序列真的壞了。
                issues.append(SeriesIssue(
                    series_id, "future_actual",
                    f"{raw} 晚於今天 {today}" if not future_days else
                    f"{raw} 超前今天 {today} 共 {ahead} 天，"
                    f"超出容許的 {future_days} 天"))
            else:
                ahead_days = max(ahead_days, ahead)

    if ahead_days:
        issues.append(SeriesIssue(
            series_id, "future_ahead",
            f"最新一筆超前今天 {today} {ahead_days} 天"
            f"（行政設定利率，容許 {future_days} 天內）",
            severity="info"))

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
                 forecast_ids: set[str] | None = None,
                 administered_ids: set[str] | None = None) -> list[SeriesIssue]:
    """整批檢查。回傳的清單同時含 error 與 info，呼叫端自己分流。"""
    forecast_ids = forecast_ids or set()
    administered_ids = administered_ids or set()
    issues: list[SeriesIssue] = []
    for sid, rows in series.items():
        if not rows:
            continue
        issues.extend(validate_series(
            sid, rows, today=today,
            allow_future=sid in forecast_ids,
            future_days=(ADMINISTERED_FUTURE_DAYS
                         if sid in administered_ids else 0)))
    return issues


def errors(issues: list[SeriesIssue]) -> list[SeriesIssue]:
    """只留會停止發布的那些（info 不算）。"""
    return [x for x in issues if x.severity == "error"]


def assert_clean(series: dict[str, list[dict]], **kwargs) -> None:
    errs = errors(audit_bundle(series, **kwargs))
    if errs:
        msg = "；".join(f"{x.series_id}/{x.kind}: {x.detail}" for x in errs[:8])
        raise ValueError(f"時間序列完整性檢查失敗：{msg}")
