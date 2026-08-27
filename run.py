#!/usr/bin/env python3
"""
美國總經儀表板 — 主流程

用法
----
    export FRED_API_KEY=你的key
    python run.py                     # 抓真實資料，產出整個網站到 output/
    python run.py --offline           # 用示範資料，不連網（先看畫面長相）
    python run.py --only labor        # 只重跑某個模組（labor/inflation/fomc）
    python run.py --json              # 額外輸出 output/latest.json 供其他程式使用

架構
----
    config/*.yaml     指標與門檻設定 — 日常調整只需要改這裡
    src/analysis/     分析邏輯（歸因、規則引擎、文本分析、情境合成）
    src/build.py      資料 → 畫面用結構
    src/pages/        各分頁的內容產生器
    src/site.py       版面、導覽列、CSS
    output/           產出的整個靜態網站（Netlify 的 publish 目錄）
"""

from __future__ import annotations

import os
import sys
import json
import datetime as dt
import logging
import argparse
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))

from src import site, build, clock                                # noqa: E402
from src.analysis import changes as chg                           # noqa: E402
from src.analysis import freshness                                # noqa: E402
from src.analysis import series_quality                             # noqa: E402
from src.analysis import brief as brief_mod                        # noqa: E402
from src.analysis import focus_today                               # noqa: E402
from src.pages import labor as labor_page, home as home_page      # noqa: E402
from src.pages import inflation as infl_page, fomc as fomc_page   # noqa: E402
from src.pages import scenario as scen_page                       # noqa: E402
from src.pages import rates as rates_page                         # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("run")

ROOT = Path(__file__).parent
OUT_DIR = ROOT / "output"
# 快照要進 git，這樣 GitHub Actions 上跑也比得出「跟上期的差異」
STATE_FILE = ROOT / "state" / "snapshot.json"
# 抓取起點。圖表只畫 2025 之後（見 build.CHART_START），但統計量
# （z-score、年增率、Sahm 法則）需要更長的歷史才有意義，所以抓得比畫的早。
# 2023 起約三年，足夠讓 z-score 有 36 個月的分母；再往前拉對這套
# 「近期體制」的判讀沒有增益，只是拖慢抓取。
HISTORY_START = "2023-01-01"
SAVE_FIXTURES = False
REAL_MODULES: list[str] = []
FOMC_YEARS_BACK = 4


# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------
def load_config(name: str) -> dict:
    p = ROOT / "config" / name
    if not p.exists():
        log.warning("找不到設定檔 %s，跳過該模組", name)
        return {}
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def series_ids(cfg: dict, groups: tuple[str, ...]) -> tuple[list, dict, dict]:
    """從設定檔取出要抓的序列。回傳 (ids, 標籤, 反向旗標)"""
    ids, labels, inverts = [], {}, {}
    for g in groups:
        for item in cfg.get(g) or []:
            if item.get("enabled") is False:
                continue
            # 推導序列（例如核心服務除住房）不在 FRED 上，去抓只會多一筆
            # 失敗紀錄。它仍然留在 meta 裡供貢獻分解使用，值由 build 算出來。
            if item.get("derived"):
                continue
            ids.append(item["id"])
            labels[item["id"]] = item.get("label", item["id"])
            inverts[item["id"]] = bool(item.get("invert"))
    seen, out = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out, labels, inverts


def infl_series_ids(cfg: dict) -> tuple[list, dict, dict]:
    """
    通膨模組的抓取清單 ＝ 各 group 的序列 ＋ **推導原料**。

    supercore_derive 的兩條原料不屬於任何 group，而 series_ids 只掃
    group——這正是 Actions 上「核心服務除住房推導失敗」**每一次**都出現
    的根因：當初把九宮格那格從 CUSR0000SASLE 換成推導序列 CPISUPERCORE
    （derived: true，正確地不去抓）時，原料 SASLE 也從 cpi_components
    移走了，從此沒有任何地方把它放進抓取清單。線上每次執行 series 裡
    都沒有它 → 推導必失敗 → supercore KPI、黏性訊號、薪資傳導、
    核心 PCE 成分法整串連鎖缺值。更陰的是**離線模式的示範資料有這條**，
    本機怎麼跑都是好的，只有線上壞——看起來就像隨機的抓取失敗。
    住房（CUSR0000SAH1）本來就在 cpi_components 裡，去重後不會抓兩次。
    """
    ids, labels, inverts = series_ids(cfg, INFL_GROUPS)
    sd = cfg.get("supercore_derive") or {}
    for key, lab in (("core_services", "核心服務含住房（推導原料）"),
                     ("shelter", "住房（推導原料）")):
        sid = sd.get(key)
        if sid and sid not in ids:
            ids.append(sid)
            labels[sid] = lab
            inverts[sid] = False
    return ids, labels, inverts


LABOR_GROUPS = ("headline", "unemployment_structure", "wages", "jolts",
                "claims", "reference", "special_series", "industries")
INFL_GROUPS = ("headline", "cpi_components", "shelter_detail", "stickiness",
               "trend_measures", "energy", "expectations", "sep",
               # PPI 成分：PPI 卡與核心 PCE 成分法推估的原料
               "ppi_components")
RATES_GROUPS = ("yields", "real_and_breakeven", "term_premium", "credit", "debt",
                # 匯率：只為了把海外發債的原幣金額換算成美元等值。
                # 少了這一組，非美元的發債仍然會列出原幣金額，
                # 只是旁邊少一句「約合多少美元」——不會壞，只是少一點資訊。
                "fx")


# ---------------------------------------------------------------------------
# 擷取
# ---------------------------------------------------------------------------
# 正式執行時存下的真實序列快照。離線模式優先讀這裡，
# 讀不到才退回程式生成的示範序列。
FIXTURE_DIR = ROOT / "fixtures"


def _fixture_path(module: str):
    return FIXTURE_DIR / f"{module}.json"


def save_real_fixtures(module: str, series: dict, vintages: dict) -> None:
    """把這次抓到的真實資料存成離線素材。"""
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "saved_at": clock.iso(),
        "module": module,
        "series": series,
        "vintages": vintages or {},
    }
    _fixture_path(module).write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    log.info("已存下 %s 模組的真實資料快照（%d 個序列）→ %s",
             module, len(series), _fixture_path(module))


def _load_real_fixtures(module: str):
    """回傳 (series, vintages, saved_at) 或 None。"""
    p = _fixture_path(module)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d.get("series") or {}, d.get("vintages") or {}, d.get("saved_at", "")
    except Exception as e:                        # noqa: BLE001
        log.warning("讀取 %s 失敗（%s），改用生成的示範資料", p, e)
        return None


def _restore_from_snapshot(series: dict, store, failed: list) -> list[str]:
    """
    快照後備：抓取（含 fetch_all 的打撈段）之後還是空手的序列，
    退回本機 SQLite 裡上一次成功抓到的值。

    為什麼需要第三層防線：限流已經用抓取節奏＋補抓擋掉大半，但 FRED
    偶爾整條序列短暫回空、或整站短暫掛掉——而缺一條原料的代價是下游
    連鎖缺值。實例：CUSR0000SASLE 缺了，「核心服務除住房」推導不出來，
    supercore KPI、黏性訊號、核心 PCE 成分法整串跟著空。
    沿用上次的值不是造假：值本來就是同一條官方序列上次的版本，
    freshness 照觀測日期照常判停更，頁尾的失敗清單也會標明是沿用。

    回傳沿用了哪些序列 id；同時把 failed 裡對應的訊息補上沿用標記。
    """
    restored: list[str] = []
    for sid, rows in series.items():
        if rows:
            continue
        try:
            prev = store.series(sid)
        except Exception:                          # noqa: BLE001
            prev = []
        if prev:
            series[sid] = prev
            restored.append(sid)
    if restored:
        rs = set(restored)
        failed[:] = [(s, m + "（已沿用上次執行的本機快照）") if s in rs
                     else (s, m) for s, m in failed]
        log.warning("有 %d 條序列本次抓不到，沿用本機快照：%s",
                    len(restored), "、".join(restored))
    return restored


def gather_fred(offline: bool, ids: list[str], module: str,
                vintage_ids: tuple[str, ...] = ()):
    """回傳 (series, vintages, failed)"""
    if offline:
        real = _load_real_fixtures(module)
        if real:
            series, vintages, saved_at = real
            log.info("%s 模組：使用 %s 存下的真實資料快照", module, saved_at[:16])
            REAL_MODULES.append({"labor": "勞動", "inflation": "通膨",
                                 "rates": "長端"}.get(module, module))
            return series, vintages, []
        if module == "labor":
            from src import fixtures
            return fixtures.build(), fixtures.build_vintages(), []
        if module == "rates":
            from src import fixtures_rates
            return fixtures_rates.build(), {}, []
        if module == "liquidity":
            from src import fixtures_liquidity
            return fixtures_liquidity.build(), {}, []
        from src import fixtures_inflation
        return fixtures_inflation.build(), {}, []

    from src.fred import FredClient, fetch_all
    from src.store import Store

    client = FredClient()
    store = Store(ROOT / "data" / f"{module}.db")
    run_id = store.start_run(note=module)

    series = fetch_all(client, ids, start=HISTORY_START)
    # 補抓之後還缺的，退回上次執行的本機快照（沿用的不再寫回 store，
    # 免得把舊資料誤記成「這一次抓到的」）。
    _restored = set(_restore_from_snapshot(series, store, client.failed))

    # BLS 快速通道：CPI 與就業報告都是 BLS 08:30 發布，而 FRED 是轉載，
    # 當天可能要等好幾個小時才同步（實測 8/12 的 7 月 CPI，兩小時後
    # FRED 仍停在 6 月）。這裡在 FRED 的結果上補最新的那幾期，
    # 每一點都標 provisional，畫面上會標成速報值。
    #
    # 對帳失敗或同組只更新一部分時整組不採用——寧可跟 FRED 一樣慢，
    # 也不要接一條來源不明或期別對不齊的數字。
    if module in ("labor", "inflation"):
        try:
            from src import bls
            bls_res = bls.merge(series)
        except Exception as e:                     # noqa: BLE001
            # 快速通道壞掉**絕對不能**讓整個模組跟著壞——它只是提早幾小時，
            # 不是必要條件。任何例外都吞掉，安靜地退回純 FRED 的結果。
            log.warning("BLS 快速通道失敗（%s），全部改用 FRED", e)
            bls_res = None
        if bls_res and bls_res.get("added"):
            log.info("%s 模組：%d 條序列採用 BLS 速報值（%s）",
                     module, len(bls_res["added"]),
                     ", ".join(sorted(bls_res["added"]))[:80])

    for sid, rows in series.items():
        if rows and sid not in _restored:
            store.write(run_id, sid, rows)

    vintages: dict = {}
    for sid in vintage_ids:
        v = client.vintages(sid, start="2024-01-01", n_vintages=6)
        if v:
            vintages[sid] = v
        else:
            prev = store.previous_snapshot(sid, before_run=run_id)
            if prev:
                vintages[sid] = {"__snapshot__": prev}

    store.finish_run(run_id, client.failed)
    store.close()
    if SAVE_FIXTURES:
        save_real_fixtures(module, series, vintages)
    return series, vintages, client.failed


# 「本次更新」要顯示多久。
#
# 只在「抓到新資料的那一次執行」顯示是最嚴格的，但實務上看不到——排程一天
# 跑三次，發布當天你未必打開網站，隔天想看卻已經消失了。
# 72 小時涵蓋「週五發布、週一才看」這種最常見的情況，而「三天內的新數據」
# 叫「本次更新」也還名副其實。
FRESH_HOURS = 72
RELEASES_FILE = ROOT / "state" / "releases.json"


def _fresh_releases(ctxs: dict) -> dict:
    """
    回傳 {模組: 期別字串}，只含**FRESH_HOURS 小時內才首次出現**的期別。

    為什麼要另外存一份而不是用 snapshot：snapshot 記的是「上一期的值是
    多少」（給「跟上期比什麼變了」用），這裡要的是「這一期是什麼時候第一次
    看到的」——是時間，不是數值。硬塞進 snapshot 會讓那邊的語意變混濁。

    檔案讀不到、寫不進去都不影響主流程：最差的情況是這一句不顯示。
    """
    now = clock.now()
    try:
        old = json.loads(RELEASES_FILE.read_text(encoding="utf-8"))
    except Exception:                              # noqa: BLE001
        old = {}

    if not isinstance(old, dict):                  # 檔案被改成別的型別
        old = {}

    out, state = {}, {}
    lab, inf, fom = (ctxs.get("labor") or {}, ctxs.get("inflation") or {},
                     ctxs.get("fomc") or {})
    # 六種發布各自的期別。先前只認就業報告與 CPI，於是「本次更新」
    # 一個月只出現六天；PCE（月底）、失業金（每週四）、JOLTS（月中）、
    # FOMC（會後）都是讀者打開網站想先知道的新東西。
    sources = {
        "labor": lab.get("data_month", ""),
        "inflation": inf.get("data_month", ""),
        "pce": ((inf.get("asof") or {}).get("pce") or "")[:7],
        "claims": ((lab.get("claims") or {}).get("machine") or {}).get("week", ""),
        "jolts": lab.get("jolts_month", ""),
        "fomc": (fom.get("latest_date", "") if not fom.get("empty") else ""),
    }
    for key, month in sources.items():
        if not month:
            continue
        rec = old.get(key)
        # 舊格式或手改壞掉的紀錄都可能不是字典。當成「沒有紀錄」處理：
        # 最差的情況是這一期重新計時，不是整個執行掛掉。
        rec = rec if isinstance(rec, dict) else {}
        if rec.get("month") == month and rec.get("first_seen"):
            state[key] = rec                       # 沿用第一次看到的時間
        else:
            # `advanced` 記的是「這個 first_seen 是不是真的看到期別往前推」。
            #
            # 沒有這個旗標的話，**狀態檔一掉就會謊報**：第一次跑寫下
            # first_seen=現在（那次不算新，靠 old.get(key) 擋掉），
            # 但第二次跑起 rec.month 就等於 month 了，於是沿用那個
            # first_seen——而它在 72 小時內，兩個模組同時被標成「本次更新」。
            # 使用者看到的正是這個：就業報告 8/7 就發了，8/13 還寫著
            # 「本次更新：就業 7 月」。
            state[key] = {"month": month, "first_seen": clock.iso(),
                          "advanced": bool(rec.get("month"))}
        try:
            seen = dt.datetime.fromisoformat(state[key]["first_seen"])
            fresh = (now - seen).total_seconds() <= FRESH_HOURS * 3600
        except (ValueError, TypeError):
            fresh = False
        # 只有「真的看到期別往前推」那一次記下的時間才算數。
        # 第一次跑、換機器、狀態檔遺失都不算——寧可少講一次，
        # 也不要在資料其實是一週前發布的時候寫「本次更新」。
        # 預設 True 是給**舊格式的紀錄**用的：這個旗標是後來才加的，
        # 沿用下來的舊紀錄沒有它。舊版程式能寫出那筆紀錄就代表期別看過了，
        # 當成 advanced 處理是對的。新寫的紀錄一定會明確帶這個欄位，
        # 所以「狀態檔遺失後重建」那條路徑不會被這個預設值放行。
        if fresh and state[key].get("advanced", True):
            out[key] = month

    try:
        RELEASES_FILE.parent.mkdir(parents=True, exist_ok=True)
        RELEASES_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
    except Exception as e:                         # noqa: BLE001
        log.warning("發布時間紀錄寫入失敗（%s），下次「本次更新」可能不顯示", e)
    return out


def gather_hyperscalers(cfg: dict, offline: bool) -> list:
    """
    用 SEC EDGAR 就地覆寫 config 的 hyperscalers 數字。回傳失敗清單。

    離線模式或 auto:false 時完全不動 config，直接用手動值。
    抓取成功的公司會被換成 SEC 的實際申報值，並把 verified 設為 True——
    畫面上的「尚未對照財報」警示因此只會在真的沒對照時出現。
    """
    hs = cfg.get("hyperscalers") or {}
    if offline or not hs.get("auto", False) or not hs.get("companies"):
        if offline:
            from src import fixtures_rates
            hs["offerings"] = fixtures_rates.offerings()
            hs["earnings"] = fixtures_rates.earnings(hs.get("companies") or [])
        return []
    from src import sec as _sec
    from src.sec import (SecClient, fetch_hyperscalers, fetch_recent_offerings,
                         fetch_recent_earnings)
    client = SecClient()
    # 印出實際送出的 User-Agent。SEC 擋掉請求時整區會退回手動值，而
    # 「變數沒設」「設在 Secrets 分頁」「workflow 沒把它傳進來」三種情況
    # 先前的 log 長得一模一樣——直接印出來就不必再猜。
    log.info("SEC User-Agent：%s%s", _sec.USER_AGENT,
             "" if _sec.USER_AGENT != _sec.DEFAULT_USER_AGENT
             else "（SEC_USER_AGENT 沒有傳進來，用內建預設值；"
                  "預設值的信箱是假的，SEC 可能限流）")
    log.info("科技巨頭：向 SEC EDGAR 擷取 %d 家的最新一季財報",
             len(hs["companies"]))
    comps, as_of, verified = fetch_hyperscalers(hs, client)
    hs["companies"] = comps
    hs["as_of"] = as_of or hs.get("as_of", "")
    hs["verified"] = verified
    if verified:
        log.info("科技巨頭完成：資料截至 %s，全部來自 SEC 申報", hs["as_of"])
    else:
        log.warning("科技巨頭：部分公司抓取失敗，該公司改用 config 的手動值")

    # 近期發債申報：補季報 45–135 天的時效缺口。
    # 這一段失敗不影響主要數字，所以獨立處理。
    if hs.get("track_offerings", True):
        hs["offerings"] = fetch_recent_offerings(
            hs, client, parse_amount=hs.get("parse_offering_amount", True))

    # 財報新聞稿（8-K 2.02）：補實績從「季末後 40 天」到「約 3 週」的缺口。
    # 必須排在 fetch_hyperscalers 之後——它要拿各家的 period_end 才能判斷
    # 這份新聞稿講的是不是下方表格還沒有的那一季。
    if hs.get("track_earnings", True):
        hs["earnings"] = fetch_recent_earnings(hs, client)
    return client.failed


def fetch_release_dates() -> dict:
    """
    就業報告與 CPI 的下一個**官方**發布日。

    先前這兩個倒數是用「次月第一個週五」「次月第 12 天前後」的慣例推的。
    慣例大多數月份是對的，但一年總有幾次不對——BLS 遇到聯邦假日會挪動。
    FRED 直接提供官方行事曆，沒有理由自己猜。

    任何一步失敗都回傳空 dict，畫面會自動退回慣例推估並照實標示，
    不會因為多了這支呼叫而讓整份報告產不出來。
    """
    try:
        from src.fred import FredClient, RELEASE_IDS
        client = FredClient()
    except Exception as e:                        # noqa: BLE001
        log.warning("發布行事曆：無法建立 FRED 連線（%s），改用慣例推估", e)
        return {}
    out = {}
    for key, rid in RELEASE_IDS.items():
        d = client.next_release(rid)
        if d:
            out[key] = d.isoformat()
    if out:
        log.info("發布行事曆：%s", "、".join(f"{k} {v}" for k, v in out.items()))
    else:
        log.warning("發布行事曆：一個都沒問到，改用慣例推估")
    return out


def release_next(releases: dict, calendar: dict) -> dict:
    """
    每個指標「今天以後最近的一個發布日」，格式 {key: "YYYY-MM-DD"}。

    優先序：FRED 官方行事曆（就業報告、CPI）→ 手動行事曆
    （config/releases_calendar.yaml，PPI／PCE 只有這個來源）。
    全部過期或缺檔就不給——頁面端自己有慣例推估的後備，
    這裡絕不用猜的日期冒充官方日期。
    """
    import datetime as _dt
    today = clock.today()
    out: dict = {}
    for key in ("employment", "cpi", "ppi", "pce"):
        raw = (releases or {}).get(key)
        if raw:
            try:
                if _dt.date.fromisoformat(raw) >= today:
                    out[key] = raw
                    continue
            except ValueError:
                pass
        best = None
        for _ref, d in ((calendar or {}).get(key) or {}).items():
            try:
                dd = _dt.date.fromisoformat(str(d))
            except ValueError:
                continue
            if dd >= today and (best is None or dd < best):
                best = dd
        if best:
            out[key] = best.isoformat()
    return out


def gather_fomc(offline: bool, fetch_cfg: dict):
    """回傳 (statements, upcoming, failed)"""
    if offline:
        from src import fixtures_fomc
        return fixtures_fomc.build(), fixtures_fomc.upcoming(), []
    from src.fomc_source import FomcSource
    src = FomcSource()
    statements = src.collect(fetch_cfg.get("years_back", FOMC_YEARS_BACK),
                             with_presser=fetch_cfg.get("with_presser", True),
                             start=fetch_cfg.get("start"),
                             presser_recent_n=fetch_cfg.get("presser_recent_n", 4))
    # 未來會議要另外解析行事曆表格：collect() 抓的是聲明連結，
    # 而還沒開的會議沒有聲明，連結不存在。
    upcoming = src.upcoming_meetings(3)
    if upcoming:
        log.info("下次會議 %s（另有 %d 場已排定）",
                 upcoming[0].isoformat(), len(upcoming) - 1)
    return statements, upcoming, src.failed


# ---------------------------------------------------------------------------
# 網站產生
# ---------------------------------------------------------------------------
def write_site(ctxs: dict, offline: bool, only: str | None = None) -> list[Path]:
    """
    only 有值時（--only labor 等）＝局部重跑：只覆寫該模組自己的頁面。

    不能把「模組被跳過」當成「設定檔未載入」處理——否則 --only labor
    會把好端端的通膨、FOMC 頁蓋成「建置中」佔位頁，首頁與情境合成
    也會拿殘缺的 context 產出降級的結論。
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def write(rel: str, content: str) -> None:
        p = OUT_DIR / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        written.append(p)

    def archive(rel: str, content: str) -> None:
        """
        存檔頁只在該資料月份第一次出現時寫入，之後不再覆寫。

        排程是每天跑的，但存檔路徑是按資料月份命名的。若每次都覆寫，
        同一個月會被蓋掉三十次，最後留下的是「這個月最後一次執行看到的樣子」
        ——而 BLS／BEA 在這期間已經修正過數字。那樣存檔頁宣稱的
        「當時我們看到的是什麼」就不成立。只寫第一次，留下的才是發布日原始版本。
        """
        p = OUT_DIR / rel
        if p.exists():
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        written.append(p)

    banner = (labor_page.offline_banner(ctxs.get("_real_modules") or [])
              if offline else "")
    # 停更警告只掛在**相關的那一頁**＋首頁，而且收成一行——
    # 先前是每一頁都放一整塊展開的框，停更的是 DGS30 時，
    # 勞動頁的讀者也被迫看一塊跟本頁結論無關的警告。
    _stale = ctxs.get("_stale") or []

    def _banner(page: str | None = None) -> str:
        return banner + freshness.banner_html(_stale, site.esc, page)
    lab, inf, fom, scn = (ctxs.get("labor"), ctxs.get("inflation"),
                          ctxs.get("fomc"), ctxs.get("scenario"))
    if only:
        scn = None                          # 情境頁需要全部模組，局部重跑不更新

    # ---- 勞動市場 ----
    if lab:
        html = site.page(
            "勞動市場", "/labor/", labor_page.labor_body(lab),
            subtitle=(f"{lab['release_name']}　·　資料月份 {lab['data_month']}"
                      f"　·　更新於 {lab['generated_at']}"),
            footer=labor_page.labor_footer(lab), banner=_banner("labor"))
        write("labor/index.html", html)
        archive(f"archive/labor-{lab['data_month']}/index.html", html)

    # ---- 通膨 ----
    if inf:
        html = site.page(
            "通膨", "/inflation/", infl_page.inflation_body(inf),
            subtitle=(f"{inf['release_name']}　·　資料月份 {inf['data_month']}"
                      f"　·　更新於 {inf['generated_at']}"),
            footer=infl_page.inflation_footer(inf), banner=_banner("inflation"))
        write("inflation/index.html", html)
        archive(f"archive/inflation-{inf['data_month']}/index.html", html)
    elif not only or not (OUT_DIR / "inflation/index.html").exists():
        write("inflation/index.html", site.soon_page(
            "通膨", "/inflation/", "設定檔 config/inflation.yaml 未載入。", "P2"))

    # ---- 聯準會文本 ----
    if fom and not fom.get("empty"):
        write("fomc/index.html", site.page(
            "聯準會文本", "/fomc/", fomc_page.fomc_body(fom),
            subtitle=(f"最新聲明 {fom['latest_date']}　·　更新於 {fom['generated_at']}"),
            footer=fomc_page.fomc_footer(fom), banner=_banner("fomc")))
    elif not only or not (OUT_DIR / "fomc/index.html").exists():
        write("fomc/index.html", site.soon_page(
            "聯準會文本", "/fomc/",
            "尚未取得任何聲明文本。正式執行時會從 federalreserve.gov 抓取近四年的會後聲明。",
            "P3"))

    # ---- 長端利率與債務 ----
    rts = ctxs.get("rates")
    if not rts and not (OUT_DIR / "rates/index.html").exists():
        # 沒有這一頁時導覽列會點出 404，所以至少要有佔位頁
        write("rates/index.html", site.soon_page(
            "長端與債務", "/rates/",
            "設定檔 config/rates.yaml 未載入，或本次為局部重跑。", "P5"))
    if rts:
        write("rates/index.html", site.page(
            "長端與債務", "/rates/", rates_page.rates_body(rts),
            subtitle=(f"{rts['release_name']}　·　資料截止 {rts['as_of']}"
                      f"　·　更新於 {rts['generated_at']}"),
            footer=rates_page.rates_footer(rts), banner=_banner("rates")))

    # ---- 情境合成 ----
    if not scn and not (OUT_DIR / "scenario/index.html").exists():
        write("scenario/index.html", site.soon_page(
            "情境合成", "/scenario/",
            "情境合成需要勞動與通膨模組同時就緒；本次為局部重跑，尚未產生。", "P4"))
    if scn:
        write("scenario/index.html", site.page(
            "情境合成", "/scenario/", scen_page.scenario_body(scn),
            subtitle=f"{scn['as_of']}　·　更新於 {scn['generated_at']}",
            footer=scen_page.scenario_footer(scn), banner=_banner("scenario")))

    # ---- 首頁與全站頁 ----
    # 局部重跑原則上不動這些頁（避免用殘缺 context 產生降級結論），
    # 但頁面若根本還不存在（第一次就下 --only），不寫的話整站 404、
    # 導覽列全部點不動。所以改成「已存在才跳過」。
    if only and (OUT_DIR / "index.html").exists():
        return written
    if only:
        log.info("首次執行即使用 --only：仍產生首頁與存檔頁，避免全站連結失效")

    write("index.html", site.page(
        site.SITE_NAME, "/", home_page.home_body(ctxs),
        # 三地時間：讀者看台北，數據的主場在紐約、歐洲盤在倫敦——
        # 夏令規則在 clock.py 裡自算，不依賴 tzdata
        # 手機一行的配套：時間戳包在 .ws（手機縮字級），前綴「最後更新」
        # 在窄幅改顯示短版「更新」——內容不變、只是省下三個漢字寬。
        subtitle=('<span class="ws"><span class="ws-long">最後更新</span>'
                  '<span class="ws-short">更新</span> '
                  f'{clock.world_stamp()}</span>'),
        footer=home_page.home_footer(ctxs),
        banner=_banner(None)))

    # ---- 存檔 ----
    entries = []
    for p in sorted((OUT_DIR / "archive").glob("*/index.html"), reverse=True):
        name = p.parent.name
        kind, _, month = name.partition("-")
        entries.append({
            "month": month,
            "kind": {"labor": "就業報告", "inflation": "物價數據"}.get(kind, kind),
            "href": f"/archive/{name}/",
            "date": "—",
        })
    write("archive/index.html", site.page(
        "存檔", "/archive/", home_page.archive_body(entries),
        subtitle=f"共 {len(entries)} 期",
        footer="官方會持續修正歷史數字，這裡保留每個資料月份第一次產出時的完整頁面。"))

    # 允許抓取（原本是全站 Disallow）：右上角的 EN 鈕走 Google 翻譯
    # 代理，Google 伺服器要抓得到頁面才能翻。不想被搜尋收錄的部分由
    # 每頁的 <meta name="robots" content="noindex"> 繼續把關——
    # 抓得到但不收錄。
    write("robots.txt", "User-agent: *\nDisallow:\n")
    return written


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="使用示範資料，不連網")
    ap.add_argument("--only", choices=["labor", "inflation", "fomc", "rates"],
                    help="只跑指定模組")
    ap.add_argument("--open", action="store_true", help="產出後開啟")
    ap.add_argument("--json", action="store_true", help="額外輸出 latest.json")
    ap.add_argument("--save-fixtures", action="store_true",
                    help="把這次抓到的真實資料存成離線素材（供 --offline 使用）")
    args = ap.parse_args()

    global SAVE_FIXTURES
    SAVE_FIXTURES = args.save_fixtures
    if SAVE_FIXTURES and args.offline:
        log.error("--save-fixtures 需要抓真實資料，不能與 --offline 併用")
        return 1

    if not args.offline and not os.environ.get("FRED_API_KEY"):
        log.error("找不到 FRED_API_KEY。請先 export FRED_API_KEY=...，"
                  "或用 --offline 看示範畫面。")
        return 1

    def want(m: str) -> bool:
        return args.only in (None, m)

    ctxs: dict = {}
    all_failed: list = []
    labor_series: dict = {}
    # FOMC 頁要用 2 年期殖利率跟政策利率比對「市場定價 vs 聯準會」，
    # 那條序列是長端模組抓的，所以留一份給後面用。
    rates_series: dict = {}
    # 三個模組抓到的序列合在一起做新鮮度檢查。分開檢查會漏掉
    # 「只有長端那組停更」這種情況，而那組的讀者最不會去別頁確認。
    all_series: dict = {}

    # ---- 勞動市場 ----
    if want("labor"):
        cfg = load_config("indicators.yaml")
        ids, labels, inverts = series_ids(cfg, LABOR_GROUPS)
        log.info("勞動模組：%d 個序列", len(ids))
        series, vintages, failed = gather_fred(args.offline, ids, "labor",
                                               vintage_ids=("PAYEMS", "USPRIV"))
        all_failed += failed
        labor_series = series          # 通膨模組的傳導分析要用到薪資序列
        all_series.update(series)
        ctxs["labor"] = build.build_labor_context(
            cfg, series, vintages, labels, inverts, failed, args.offline,
            consensus=load_config("consensus.yaml"))
        log.info("勞動模組完成：%s，%d 項訊號",
                 ctxs["labor"]["data_month"], len(ctxs["labor"]["flags"]))

    # ---- 通膨 ----
    if want("inflation"):
        cfg = load_config("inflation.yaml")
        if cfg:
            ids, labels, inverts = infl_series_ids(cfg)
            log.info("通膨模組：%d 個序列", len(ids))
            series, _, failed = gather_fred(args.offline, ids, "inflation")
            all_series.update(series)
            all_failed += failed
            ctxs["inflation"] = build.build_inflation_context(
                cfg, series, failed, args.offline, labor_series=labor_series,
                consensus=load_config("consensus.yaml"))
            log.info("通膨模組完成：%s，%d 項訊號",
                     ctxs["inflation"]["data_month"],
                     len(ctxs["inflation"]["flags"]))

    # ---- 長端利率與債務供給 ----
    if want("rates"):
        cfg = load_config("rates.yaml")
        if cfg:
            ids, labels, inverts = series_ids(cfg, RATES_GROUPS)
            log.info("長端模組：%d 個序列", len(ids))
            series, _, failed = gather_fred(args.offline, ids, "rates")
            rates_series = series
            all_series.update(series)
            # 科技巨頭的財報改由 SEC EDGAR 自動擷取，就地覆寫 cfg
            failed = failed + gather_hyperscalers(cfg, args.offline)
            all_failed += failed
            # 10Y／30Y 升級成即時報價（跟首頁焦點條同一來源），
            # 讓長端頁不再掛著比焦點條舊一兩天的收盤——同站同數字。
            # 失敗就安靜用 FRED 收盤，規則在 upgrade_yields_live 裡。
            if not args.offline:
                _live = focus_today.upgrade_yields_live(series)
                if _live:
                    log.info("長端殖利率升級為即時：%s", "、".join(_live))
            ctxs["rates"] = build.build_rates_context(
                cfg, series, failed, args.offline)
            p = ctxs["rates"]["pressure"]
            log.info("長端模組完成：供給壓力 %s（分數 %+.2f）", p.level, p.score)

    # ---- 流動性群組（SOFR／IORB／ON RRP／SRF＋油價與 VIX 的 FRED 後備）----
    # 供焦點條的自選 chip 目錄；未來的流動性頁沿用同一組。
    # 放在完整性閘門之前，讓新序列一樣受日期／重複／未來值的檢查。
    # 抓不到不擋主流程，缺哪條哪顆 chip 標缺。
    liq_series: dict = {}
    _liq_cfg = load_config("liquidity.yaml")
    if _liq_cfg:
        try:
            _lids, _, _ = series_ids(_liq_cfg, ("series",))
            log.info("流動性群組：%d 個序列", len(_lids))
            liq_series, _, _lfail = gather_fred(args.offline, _lids,
                                                "liquidity")
            all_series.update(liq_series)
            if _lfail:
                log.warning("流動性群組缺 %d 條：%s",
                            len(_lfail), "、".join(_lfail))
        except Exception as e:                     # noqa: BLE001
            log.warning("流動性群組抓取失敗（%s），相關 chip 本次標缺", e)

    # ---- 聯準會文本 ----
    if want("fomc"):
        fcfg = load_config("fomc.yaml")
        fetch_cfg = fcfg.get("fetch") or {}
        # 記錄真正生效的範圍。fetch.start 若有設定會**蓋過** years_back
        #（見 gather_fomc），先前這行一律印 years_back，
        # 於是設了 start=2025-01-01 的預設情況下，log 說「近 10 年」
        # 而實際只抓 13 次會議——排查資料量不對時第一個看的就是這行。
        _start = fetch_cfg.get("start")
        if _start:
            log.info("聯準會文本：抓取 %s 之後的會後聲明與投票紀錄"
                     "（fetch.start 生效，years_back 不適用）", _start)
        else:
            log.info("聯準會文本：抓取近 %d 年的會後聲明與投票紀錄",
                     fetch_cfg.get("years_back", FOMC_YEARS_BACK))
        statements, upcoming, failed = gather_fomc(args.offline, fetch_cfg)
        all_failed += failed
        ctxs["fomc"] = build.build_fomc_context(
            statements, fcfg.get("policy_rate") or {},
            failed, args.offline, upcoming=upcoming,
            rates_series=rates_series)
        if not ctxs["fomc"].get("empty"):
            log.info("聯準會文本完成：%d 份聲明，最新 %s",
                     len(statements), ctxs["fomc"]["latest_date"])

    # ---- 時間序列完整性閘門 ----
    # 發布前阻擋日期錯序、重複日期、空值與被誤當成實際值的未來資料。
    # SEP 與 CBO 本來就是預測路徑，明列白名單，不與實際發布序列混用。
    _forecast_ids = {
        "NROU", "UNRATECTLLR", "UNRATECTHLR", "UNRATEMDLR",
        "PCECTPIMDLR", "JCXFEMD", "JCXFECTH", "JCXFECTL",
    }
    _series_issues = series_quality.audit_bundle(
        all_series, today=clock.today(), forecast_ids=_forecast_ids)
    ctxs["_series_issues"] = _series_issues
    if _series_issues:
        for _iss in _series_issues[:12]:
            log.error("時間序列 %s/%s：%s", _iss.series_id, _iss.kind, _iss.detail)
        log.error("時間序列完整性檢查失敗，共 %d 項；停止發布", len(_series_issues))
        return 2
    log.info("時間序列完整性：%d 條序列全部通過", len(all_series))

    # ---- 情境合成（缺件也會產出，但畫面上會明示缺哪一塊）----
    ctxs["scenario"] = build.build_scenario_context(
        ctxs.get("labor"), ctxs.get("inflation"), ctxs.get("fomc"),
        ctxs.get("rates"))
    sc = ctxs["scenario"]["scenario"]
    log.info("情境合成：%s（就業%s × 通膨%s，適用「%s」的九宮格%s）",
             sc.name, sc.labor_state, sc.infl_state,
             build.scenario.REGIME_LABEL.get(sc.regime, sc.regime),
             "；本次判不出重心，暫用兩邊並重" if sc.regime_assumed else "")

    # ---- 本期變化摘要：跟上一次執行的快照比 ----
    # 局部重跑（--only）的 context 是殘缺的，比對與存檔都會產生
    # 「情境移動」的假訊號，所以跳過。
    if args.only:
        ctxs["changes"] = None
        log.info("局部重跑（--only %s）：跳過變化比對與快照存檔", args.only)
    else:
        prev_state = chg.load_previous(STATE_FILE)
        cur_snap = chg.snapshot(ctxs)
        # 只有資料期別真的變了才輪替基準——同一期別的重跑會更新 current，
        # 但不會把 previous 往前推。這樣「7 月就業報告帶來的變化」
        # 會一直留到 8 月報告出來，而不是隔天就熄掉。
        cur_state = chg.roll(prev_state, cur_snap)
        ctxs["changes"] = chg.compare(cur_state)
        # 「這一格待了幾期」——首頁的結論卡自己引出來的問題
        ctxs["_tenure"] = chg.tenure(cur_state)
        log.info("變化摘要：%s", ctxs["changes"].headline)
        _tn = ctxs["_tenure"]
        if _tn:
            log.info("情境已維持 %d 期%s", _tn["periods"],
                     f"（前一格：{_tn['from']}）" if _tn.get("from") else "")
        if ctxs["changes"].bases:
            log.info("對照基準：%s", chg.basis_text(ctxs["changes"]))

        ctxs["_fresh"] = _fresh_releases(ctxs)
        # KPI 卡的「與預期比較」只在資料 72 小時內常駐（發布日當下那正是
        # 市場在反應的數字），之後自動退進收合層——旗標帶給頁面端。
        for _k in ("labor", "inflation"):
            if ctxs.get(_k) is not None:
                ctxs[_k]["is_fresh"] = _k in ctxs["_fresh"]

    # ---- 首頁的整體總述：規則組裝 → （選配）模型潤稿 ----
    # 潤稿只在事實變了才呼叫 API；沒設金鑰或離線一律用組裝版。
    _brief = brief_mod.compose(ctxs)
    if _brief["text"]:
        # 三則 bullet 改由 AI 讀「判定包」生成（數字鎖＋方向鎖＋結構鎖，
        # 任何一道沒過退回規則組裝版）；「本次更新」與重點句仍為規則產生。
        # 溫度等設定在 config/brief.yaml 的 polish 段，沿用同一組。
        _bcfg = (load_config("brief.yaml") or {}).get("polish") or {}
        ctxs["_brief"] = brief_mod.generate(
            ctxs, _brief, STATE_FILE.parent / "brief.json",
            offline=args.offline, cfg=_bcfg)
        _bm = ctxs["_brief"].get("model") or ""
        log.info("整體情勢：%s%s（%d 中文字）",
                 {"generated": "AI 生成（三鎖驗證通過）",
                  "model-cache": "AI 生成（沿用快取）",
                  "assembled": "規則組裝"}[ctxs["_brief"]["source"]],
                 f"，{_bm}" if _bm else "",
                 ctxs["_brief"]["chars"])

    ctxs["_real_modules"] = REAL_MODULES
    # 離線模式的示範資料日期是寫死的，一定會被判成停更——那不是訊息，
    # 只會讓每次看離線頁的人以為真的出事了。
    # 官方發布行事曆：能問到就用官方的，問不到才退回慣例推估。
    # 離線模式不打 API（也沒有 key），一律走慣例。
    ctxs["_releases"] = {} if args.offline else fetch_release_dates()
    # 手動維護的官方行事曆（config/releases_calendar.yaml）：
    # PPI／PCE 的唯一日期來源，也是 FRED 行事曆問不到時的後備。
    # 離線模式也載——日期是靜態檔案，不打任何 API。
    ctxs["_calendar"] = load_config("releases_calendar.yaml")
    # 各分頁 hero 的「下一次更新」：優先 FRED 官方行事曆，其次手動行事曆。
    # 挑「今天以後最近的一筆」，全部過期就不標（分頁自己有慣例推估後備）。
    _next = release_next(ctxs["_releases"], ctxs["_calendar"])
    if ctxs.get("labor") is not None and _next.get("employment"):
        ctxs["labor"]["next_release"] = _next["employment"]
    if ctxs.get("inflation") is not None:
        for _k in ("cpi", "ppi", "pce"):
            if _next.get(_k):
                ctxs["inflation"][f"next_{_k}"] = _next[_k]
    # 今日市場焦點（首頁 hero 之上的窄條）。任何一步失敗都不擋主流程。
    try:
        ctxs["_focus"] = focus_today.build(
            rates_series, args.offline, load_config("focus.yaml"),
            STATE_FILE.parent / "focus.json", liq_series=liq_series)
    except Exception as e:                         # noqa: BLE001
        log.warning("今日市場焦點產生失敗（%s），該區塊本次不顯示", e)
        ctxs["_focus"] = None
    ctxs["_stale"] = [] if args.offline else freshness.check(all_series)
    if ctxs["_stale"]:
        log.warning("有 %d 條序列停止更新：%s", len(ctxs["_stale"]),
                    "、".join(f"{s['id']}（{s['days']} 天）"
                              for s in ctxs["_stale"]))
    written = write_site(ctxs, args.offline, only=args.only)
    if not args.only:
        chg.save(STATE_FILE, cur_state)
    log.info("已產出 %d 個頁面至 %s", len(written), OUT_DIR)
    if all_failed:
        log.warning("有 %d 個資料來源抓取失敗，詳見頁面底部清單", len(all_failed))

    # latest.json 是給其他程式吃的，代表全站狀態。局部重跑的 context 殘缺
    # （缺的模組會退回預設值），寫下去會用一份方向可能相反的情境覆蓋掉
    # 正確的舊檔——HTML 那邊已經擋了，這裡也要擋。
    if args.json and args.only:
        log.info("局部重跑（--only %s）：跳過 latest.json，避免覆蓋成殘缺狀態",
                 args.only)
    elif args.json:
        out = {"generated_at": clock.iso()}
        if ctxs.get("labor"):
            l = ctxs["labor"]
            out["labor"] = {"month": l["data_month"], "score": l["score"]["score"],
                            "tilt": l["tilt"],
                            "flags": [f.__dict__ for f in l["flags"]]}
        if ctxs.get("inflation"):
            i = ctxs["inflation"]
            out["inflation"] = {"month": i["data_month"], "tilt": i["tilt"],
                                "flags": [f.__dict__ for f in i["flags"]]}
        # 九宮格改成「一個體制一張」之後，格名本身就是結論，
        # verdict_name 那一族欄位已經移除——這裡忘了跟著改，
        # 導致 --json 直接崩潰，而排程跑的正是 `python run.py --json`。
        out["scenario"] = {"name": sc.name, "labor": sc.labor_state,
                           "inflation": sc.infl_state, "lean": sc.lean,
                           "regime": sc.regime,
                           "regime_assumed": sc.regime_assumed}
        (OUT_DIR / "latest.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8")
        log.info("已輸出 %s", OUT_DIR / "latest.json")

    if args.open:
        import webbrowser
        webbrowser.open(f"file://{(OUT_DIR / 'index.html').resolve()}")
    return 0


if __name__ == "__main__":
    from src.fred import FredAuthError                             # noqa: E402
    try:
        sys.exit(main())
    except FredAuthError as e:
        # 明確失敗並中止，不要產出一份沒有資料的頁面覆蓋掉上一版好的結果
        log.error("%s", e)
        sys.exit(2)
