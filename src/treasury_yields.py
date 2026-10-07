"""Official US Treasury daily nominal par yields, with FRED history/fallback.

Accept complete curve days atomically. Never append a live quote or carry an
individual tenor forward to a newer date. Cache only validated Treasury days.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import json
import logging
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import requests
from . import clock

log = logging.getLogger(__name__)
FIELDS = {"DGS3MO": "BC_3MONTH", "DGS1": "BC_1YEAR", "DGS2": "BC_2YEAR",
          "DGS5": "BC_5YEAR", "DGS7": "BC_7YEAR", "DGS10": "BC_10YEAR",
          "DGS20": "BC_20YEAR", "DGS30": "BC_30YEAR"}
URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
       "pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value={year}")
TIMEOUT = 15


def _value(v):
    if v is None or isinstance(v, bool):
        raise ValueError("missing/non-numeric yield")
    n = float(v)
    if not math.isfinite(n) or not -5 <= n <= 25:
        raise ValueError("invalid yield")
    return n


def _day(date, values, today):
    day = dt.date.fromisoformat(str(date)[:10])
    if day > today or day.weekday() > 4:
        raise ValueError("invalid observation date")
    return {"date": day.isoformat(), "values": {k: _value(values[k]) for k in FIELDS}}


def parse_xml(data: bytes | str, today: dt.date) -> list[dict]:
    """Namespace-independent parser; reject an entire day if any tenor is absent."""
    days = {}
    for element in ET.fromstring(data).iter():
        if element.tag.rsplit("}", 1)[-1] != "properties":
            continue
        p = {x.tag.rsplit("}", 1)[-1]: x.text for x in element}
        try:
            row = _day(p["NEW_DATE"], {k: p.get(v) for k, v in FIELDS.items()}, today)
        except (KeyError, ValueError, TypeError):
            continue
        days[row["date"]] = row
    return [days[d] for d in sorted(days)]


def _read_cache(path: Path | None, today: dt.date) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path else {}
        if data.get("version") != 1:
            return []
        return [_day(r["date"], r["values"], today) for r in data["days"]]
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return []


def _save_cache(path: Path | None, days: list[dict]):
    if not path or not days:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps({"version": 1, "days": days}, separators=(",", ":")), encoding="utf-8")
        temp.replace(path)
    except OSError as exc:
        log.warning("財政部日資料快取寫入失敗：%s", exc)


def merge(series: dict, cache_path: Path | None = None, *, _get=None,
          today: dt.date | None = None) -> dict:
    """Mutate only eight nominal series. Returns source date and updated IDs.

    Two calendar years cover the year-start comparison, including January.
    Recent FRED days remain eligible when newer than Treasury/cache. Finally
    align all tenors to the latest complete common observation date.
    """
    today = today or clock.today()
    get = _get or requests.get
    cached = _read_cache(cache_path, today)
    days = {r["date"]: r for r in cached if int(r["date"][:4]) >= today.year - 1}

    def fetch(year):
        try:
            response = get(URL.format(year=year), headers={"User-Agent": "MACROGG (macrogg.netlify.app)"}, timeout=TIMEOUT)
            response.raise_for_status()
            result = parse_xml(response.content, today)
            return [r for r in result if int(r["date"][:4]) == year]
        except Exception as exc:  # A failed official feed must not fail the build.
            log.warning("財政部 %s 日殖利率擷取失敗，沿用快取／FRED：%s", year, exc)
            return []

    with ThreadPoolExecutor(max_workers=2) as pool:
        for rows in pool.map(fetch, (today.year - 1, today.year)):
            for r in rows:
                days[r["date"]] = r
    ordered = [days[d] for d in sorted(days)]
    _save_cache(cache_path, ordered)
    updated = []
    for sid in FIELDS:
        values = {}
        for row in series.get(sid) or []:
            if row.get("live"):
                continue
            try:
                day = dt.date.fromisoformat(row["date"][:10])
                value = _value(row.get("value"))
                if day > today:
                    continue
            except (KeyError, ValueError, TypeError):
                continue
            values[day.isoformat()] = {**row, "date": day.isoformat(), "value": value,
                                      "source": row.get("source") or "FRED"}
        for r in ordered:
            values[r["date"]] = {"date": r["date"], "value": r["values"][sid], "source": "Treasury"}
        series[sid] = [values[d] for d in sorted(values)]
        if ordered:
            updated.append(sid)
    common = set.intersection(*(set(r["date"] for r in series[k]) for k in FIELDS))
    last = max(common) if common else ""
    if last:
        for sid in FIELDS:
            series[sid] = [r for r in series[sid] if r["date"] <= last]
    return {"updated": updated, "date": last,
            "source": (series["DGS10"][-1].get("source") if last else ""),
            "treasury_date": ordered[-1]["date"] if ordered else ""}
