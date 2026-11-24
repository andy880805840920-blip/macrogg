"""
首頁「02 本期變化」的歷史（2026-11）：每天最多一點，鴿／鷹／中性的項數有變才多一根。

state/changes_hist.json：[{d, dv, hk, nt, tilt}]，日期由舊到新，保留近 KEEP_DAYS 天。
  同一天再算一次 → 取代當天那一點（取當天最後一次）
  新的一天、項數跟上一點一樣 → 不加
離線建置（write=False）只把今天這點接在畫面上，不寫檔。
2026-10-06～11-21 的舊資料由 output/index.html 的 git 歷史回補。
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)
KEEP_DAYS = 100
_K = ("dv", "hk", "nt")


def load(path) -> list:
    try:
        rows = json.loads(Path(path).read_text(encoding="utf-8"))
        return [r for r in rows if isinstance(r, dict) and r.get("d")]
    except Exception:                                # noqa: BLE001
        return []


def merge(rows: list, point: dict | None) -> list:
    rows = list(rows)
    if point:
        if rows and rows[-1]["d"] == point["d"]:
            rows[-1] = point
            if len(rows) >= 2 and all(rows[-2][k] == point[k] for k in _K):
                rows.pop()                           # 當天又變回跟前一點一樣：這一天不算變化
        elif not rows or any(rows[-1][k] != point[k] for k in _K):
            rows.append(point)
    if rows:
        cut = (dt.date.fromisoformat(rows[-1]["d"]) - dt.timedelta(days=KEEP_DAYS)).isoformat()
        rows = [r for r in rows if r["d"] >= cut]
    return rows


def update(path, point: dict | None, write: bool = False) -> list:
    rows = load(path) if path else []
    new = merge(rows, point)
    if path and write and new != rows:
        try:
            Path(path).write_text(json.dumps(new, ensure_ascii=False, indent=0), encoding="utf-8")
        except OSError as e:
            log.warning("本期變化歷史寫入失敗（%s）", e)
    return new


def point(day: dt.date, n: dict, tilt: str = "") -> dict:
    return {"d": day.isoformat(), "dv": int(n.get("dovish", 0)), "hk": int(n.get("hawkish", 0)),
            "nt": int(n.get("neutral", 0)), "tilt": tilt}
