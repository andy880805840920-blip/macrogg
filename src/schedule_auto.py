"""
行事曆與 FOMC 名單的自動維護（2026-10）。

以前要每年手動更新的三樣東西，改成每次執行自動抓、抓到就存檔，抓不到用上次存的，
再抓不到才退回 config 的手動值：

  發布行事曆   FRED release/dates（就業、CPI、PPI、PCE、GDP、零售、JOLTS、密大…）
               ＋BEA 官方的機器可讀行事曆（PCE、GDP；FRED 維護或還沒排進來時補上）
               存 state/release_dates.json——FRED 維護那幾天（2026-10-22 實例）
               首頁「接下來看什麼」照樣有官方日期
  FOMC 會議日  聯準會官網行事曆頁（列到明年）；config/focus.yaml 的 fomc_dates 變成後備
  票委名單     聯準會官網 FOMC 頁：「YYYY Committee Members」＝今年票委、
               「Alternate Members」＝明年輪值的總裁（紐約聯儲的候補是第一副總裁，不算）

每一樣都有合理性檢查，結果不合理就整組不用，寧可沿用舊的，也不要把錯的日期或名單印出去。
"""
from __future__ import annotations

import datetime as dt
import html as _html
import json
import logging
import re
from pathlib import Path

from . import clock

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
RELEASE_CACHE = STATE / "release_dates.json"
FOMC_CACHE = STATE / "fomc_roster.json"

BEA_URL = "https://apps.bea.gov/API/signup/release_dates.json"
BEA_NAMES = {"pce": "Personal Income and Outlays", "gdp": "Gross Domestic Product"}
FOMC_PAGE = "https://www.federalreserve.gov/monetarypolicy/fomc.htm"
UA = {"User-Agent": "Mozilla/5.0 (macro-dashboard)"}
TIMEOUT = 20


def _load(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:                              # noqa: BLE001
        return {}


def _save(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    except Exception as e:                         # noqa: BLE001
        log.warning("自動行事曆存檔失敗（%s）", e)


# ---------------------------------------------------------------------------
# 發布行事曆
# ---------------------------------------------------------------------------
def bea_release_dates(get=None) -> dict:
    """BEA 官方行事曆 → {"pce": [ISO…], "gdp": [ISO…]}。失敗回 {}。"""
    try:
        if get is None:
            import requests
            r = requests.get(BEA_URL, headers=UA, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
        else:
            data = get(BEA_URL)
        out = {}
        for key, name in BEA_NAMES.items():
            ds = sorted({str(x)[:10] for x in ((data.get(name) or {}).get("release_dates") or [])})
            ds = [d for d in ds if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d)]
            if ds:
                out[key] = ds
        return out
    except Exception as e:                         # noqa: BLE001
        log.warning("BEA 行事曆抓取失敗（%s）", e)
        return {}


def merge_release_dates(fred: dict, offline: bool = False, cache_path: Path = RELEASE_CACHE,
                        bea: dict | None = None, today: dt.date | None = None) -> dict:
    """
    FRED 問到的 {key: [ISO…]}，補上 BEA 的 PCE／GDP，並與上次存的合併：
      · 這次有問到的 key：用這次的（官方最新），再併入快取裡更晚的日期（FRED 一次只回 12 筆）
      · 這次沒問到的 key：沿用快取
    回傳從三天前起的日期；離線模式只讀快取、不寫檔。
    """
    today = today or clock.today()
    start = (today - dt.timedelta(days=3)).isoformat()
    cache = _load(cache_path)
    cached = cache.get("dates") if isinstance(cache.get("dates"), dict) else {}
    fresh = {k: list(v) for k, v in (fred or {}).items() if isinstance(v, list) and v}
    if not offline:
        b = bea if bea is not None else bea_release_dates()
        for k, ds in b.items():
            fresh[k] = sorted(set(fresh.get(k, [])) | set(ds))
    out = {}
    for k in set(cached) | set(fresh):
        ds = set(fresh.get(k) or [])
        if not ds:
            ds = set(cached.get(k) or [])
        else:   # 這次有問到：快取裡比這次最後一筆更晚的也留著
            last = max(ds)
            ds |= {d for d in (cached.get(k) or []) if d > last}
        ds = sorted(d for d in ds if d >= start)
        if ds:
            out[k] = ds
    restored = sorted(k for k in out if not fresh.get(k))
    if restored and not offline:
        log.info("發布行事曆：%s 這次沒問到，沿用上次存的官方日期", "、".join(restored))
    if not offline and fresh:
        keep = {k: sorted(set(fresh.get(k) or []) | {d for d in (cached.get(k) or []) if d >= start})
                for k in set(cached) | set(fresh)}
        _save(cache_path, {"saved_at": clock.now().isoformat(timespec="minutes"), "dates": keep})
    return out


def short_calendar(calendar: dict, auto: dict, days: int = 45, today: dt.date | None = None) -> list[str]:
    """手動行事曆在 days 天內用完、而且自動行事曆也沒排到更後面的項目（才需要提醒）。"""
    today = today or clock.today()
    lim = (today + dt.timedelta(days=days)).isoformat()
    out = []
    for k, v in (calendar or {}).items():
        if not isinstance(v, dict) or not v:
            continue
        last = max(str(x)[:10] for x in v.values())
        auto_last = max((str(x)[:10] for x in (auto or {}).get(k) or []), default="")
        if max(last, auto_last) < lim:
            out.append(k)
    return out


# ---------------------------------------------------------------------------
# FOMC 會議日與票委
# ---------------------------------------------------------------------------
def _text(html_doc: str) -> str:
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html_doc or "", flags=re.S | re.I)
    t = _html.unescape(re.sub(r"<[^>]+>", "\n", t))
    t = re.sub(r"[ \t ]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t)


def _surname(full: str) -> str:
    parts = [p for p in re.split(r"\s+", full.strip()) if p and p.rstrip(".") not in ("Jr", "Sr", "II", "III")]
    return parts[-1].strip(",") if parts else ""


def parse_roster(html_doc: str) -> dict | None:
    """
    聯準會 FOMC 頁 →
      {"year": 2026, "board": [姓…], "voters": {"2026": [總裁姓…], "2027": [總裁姓…]}}
    今年票委＝「YYYY Committee Members」裡不是理事的人（含紐約聯儲總裁）；
    明年票委＝紐約聯儲總裁＋「Alternate Members」裡的總裁（紐約的候補是第一副總裁，不算）。
    """
    t = _text(html_doc)
    m = re.search(r"\b(20\d{2})\s+Committee\s+Members\b", t)
    if not m:
        return None
    year = int(m.group(1))
    alt = t.find("Alternate Members", m.end())
    end = t.find("Federal Reserve Bank Rotation", m.end())
    if alt < 0:
        return None
    members_txt = t[m.end():alt]
    alt_txt = t[alt + len("Alternate Members"): end if end > alt else alt + 2000]

    def rows(seg):
        # 「Kevin Warsh\n, Board of Governors, Chairman」→ (姓名, 所屬)
        seg = re.sub(r"\n\s*,", ",", seg)
        out = []
        for line in seg.split("\n"):
            line = line.strip()
            mm = re.match(r"([A-Z][A-Za-z.'\- ]+?),\s*(.+)$", line)
            if mm:
                out.append((mm.group(1).strip(), mm.group(2).strip()))
        return out

    mem, alts = rows(members_txt), rows(alt_txt)
    board = [_surname(n) for n, a in mem if a.startswith("Board of Governors")]
    pres = [(_surname(n), a) for n, a in mem if not a.startswith("Board of Governors")]
    ny = next((s for s, a in pres if a.startswith("New York")), None)
    nxt = ([ny] if ny else []) + [_surname(n) for n, a in alts
                                  if "First Vice President" not in a and not a.startswith("Board of Governors")]
    cur = [s for s, _ in pres]
    # 合理性：理事 5–7 位、今年票委 5 位（含紐約）、明年 4–5 位
    if not (5 <= len(board) <= 7 and len(cur) == 5 and 4 <= len(nxt) <= 5):
        log.warning("FOMC 名單解析結果不合理（理事 %d、今年 %d、明年 %d），沿用舊名單", len(board), len(cur), len(nxt))
        return None
    return {"year": year, "board": board, "voters": {str(year): cur, str(year + 1): nxt}}


def parse_meetings(spans: list[tuple[dt.date, dt.date]], today: dt.date | None = None) -> list[str]:
    """行事曆表格的 (第一天, 最後一天) → 今年起的決策日（最後一天）。不合理回 []。"""
    today = today or clock.today()
    ds = sorted({b for _, b in spans if b.year >= today.year})
    if not ds:
        return []
    by_year: dict[int, int] = {}
    for d in ds:
        by_year[d.year] = by_year.get(d.year, 0) + 1
    gaps = [(b - a).days for a, b in zip(ds, ds[1:])]
    if any(n > 10 for n in by_year.values()) or (gaps and min(gaps) < 21):
        log.warning("FOMC 會議日解析結果不合理（%s），沿用 config", by_year)
        return []
    return [d.isoformat() for d in ds]


def apply_fomc(cfg: dict, offline: bool = False, cache_path: Path = FOMC_CACHE,
               fetch=None, today: dt.date | None = None) -> dict:
    """
    把自動抓到的會議日與票委名單併進 focus.yaml 的設定（回傳新的 dict，不改原本的）。
    優先序：這次抓到 → 上次存的 → config 手動值。會議日以官網為準（年度有官網資料就整年換掉，
    官網還沒列的年份才用 config）；票委名單同理（有自動的年份用自動的）。
    """
    today = today or clock.today()
    cfg = dict(cfg or {})
    cache = _load(cache_path)
    meet, roster = [], None
    if not offline:
        try:
            if fetch is None:
                from .fomc_source import FomcSource
                src = FomcSource()
                meet = parse_meetings(src.calendar_spans(), today)
                page = src._get(FOMC_PAGE) or ""
            else:
                spans, page = fetch()
                meet = parse_meetings(spans, today)
            roster = parse_roster(page)
        except Exception as e:                     # noqa: BLE001
            log.warning("FOMC 行事曆／名單自動抓取失敗（%s），沿用上次存的", e)
    if meet or roster:
        cache = {"saved_at": clock.now().isoformat(timespec="minutes"),
                 "meetings": meet or cache.get("meetings") or [],
                 "roster": roster or cache.get("roster")}
        if not offline:
            _save(cache_path, cache)
    meet = meet or cache.get("meetings") or []
    roster = roster or cache.get("roster")
    if meet:
        auto_years = {d[:4] for d in meet}
        manual = [str(d)[:10] for d in cfg.get("fomc_dates") or []]
        cfg["fomc_dates"] = sorted(set(meet) | {d for d in manual if d[:4] not in auto_years})
        log.info("FOMC 會議日：官網 %d 場（%s）", len(meet), "、".join(sorted(auto_years)))
    if roster:
        cfg["fomc_board"] = roster["board"]
        voters = {str(k): list(v) for k, v in (cfg.get("fomc_voters") or {}).items()}
        voters.update(roster["voters"])
        cfg["fomc_voters"] = voters
        log.info("FOMC 名單：理事 %s；%s",
                 "、".join(roster["board"]),
                 "；".join(f"{y} 票委 {'、'.join(v)}" for y, v in sorted(roster["voters"].items())))
    return cfg
