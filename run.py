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
import logging
import argparse
import datetime as dt
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))

from src import site, build                                       # noqa: E402
from src.analysis import changes as chg                           # noqa: E402
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
            ids.append(item["id"])
            labels[item["id"]] = item.get("label", item["id"])
            inverts[item["id"]] = bool(item.get("invert"))
    seen, out = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out, labels, inverts


LABOR_GROUPS = ("headline", "unemployment_structure", "wages", "jolts",
                "claims", "reference", "special_series", "industries")
INFL_GROUPS = ("headline", "cpi_components", "shelter_detail",
               "trend_measures", "energy", "expectations")
RATES_GROUPS = ("yields", "real_and_breakeven", "term_premium", "credit", "debt")


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
        "saved_at": dt.datetime.now().isoformat(timespec="seconds"),
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
        from src import fixtures_inflation
        return fixtures_inflation.build(), {}, []

    from src.fred import FredClient, fetch_all
    from src.store import Store

    client = FredClient()
    store = Store(ROOT / "data" / f"{module}.db")
    run_id = store.start_run(note=module)

    series = fetch_all(client, ids, start=HISTORY_START)
    for sid, rows in series.items():
        if rows:
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


def gather_hyperscalers(cfg: dict, offline: bool) -> list:
    """
    用 SEC EDGAR 就地覆寫 config 的 hyperscalers 數字。回傳失敗清單。

    離線模式或 auto:false 時完全不動 config，直接用手動值。
    抓取成功的公司會被換成 SEC 的實際申報值，並把 verified 設為 True——
    畫面上的「尚未對照財報」警示因此只會在真的沒對照時出現。
    """
    hs = cfg.get("hyperscalers") or {}
    if offline or not hs.get("auto", False) or not hs.get("companies"):
        return []
    from src.sec import SecClient, fetch_hyperscalers
    client = SecClient()
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
    return client.failed


def gather_fomc(offline: bool, fetch_cfg: dict):
    """回傳 (statements, failed)"""
    if offline:
        from src import fixtures_fomc
        return fixtures_fomc.build(), []
    from src.fomc_source import FomcSource
    src = FomcSource()
    return (src.collect(fetch_cfg.get("years_back", FOMC_YEARS_BACK),
                        with_presser=fetch_cfg.get("with_presser", True),
                        start=fetch_cfg.get("start"),
                        presser_recent_n=fetch_cfg.get("presser_recent_n", 4)),
            src.failed)


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
            footer=labor_page.labor_footer(lab), banner=banner)
        write("labor/index.html", html)
        archive(f"archive/labor-{lab['data_month']}/index.html", html)

    # ---- 通膨 ----
    if inf:
        html = site.page(
            "通膨", "/inflation/", infl_page.inflation_body(inf),
            subtitle=(f"{inf['release_name']}　·　資料月份 {inf['data_month']}"
                      f"　·　更新於 {inf['generated_at']}"),
            footer=infl_page.inflation_footer(inf), banner=banner)
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
            footer=fomc_page.fomc_footer(fom), banner=banner))
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
            footer=rates_page.rates_footer(rts), banner=banner))

    # ---- 情境合成 ----
    if not scn and not (OUT_DIR / "scenario/index.html").exists():
        write("scenario/index.html", site.soon_page(
            "情境合成", "/scenario/",
            "情境合成需要勞動與通膨模組同時就緒；本次為局部重跑，尚未產生。", "P4"))
    if scn:
        write("scenario/index.html", site.page(
            "情境合成", "/scenario/", scen_page.scenario_body(scn),
            subtitle=f"{scn['as_of']}　·　更新於 {scn['generated_at']}",
            footer=scen_page.scenario_footer(scn), banner=banner))

    # ---- 首頁與全站頁 ----
    # 局部重跑原則上不動這些頁（避免用殘缺 context 產生降級結論），
    # 但頁面若根本還不存在（第一次就下 --only），不寫的話整站 404、
    # 導覽列全部點不動。所以改成「已存在才跳過」。
    if only and (OUT_DIR / "index.html").exists():
        return written
    if only:
        log.info("首次執行即使用 --only：仍產生首頁與存檔頁，避免全站連結失效")

    write("index.html", site.page(
        "美國總經儀表板", "/", home_page.home_body(ctxs),
        subtitle=f"最後更新 {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}",
        footer=("資料來源：FRED（BLS、BEA、DOL 原始資料）與 federalreserve.gov。"
                "所有量化判定由固定規則產生，每次執行結果一致。<br>"
                "本站僅為數據整理，不構成投資建議。"),
        banner=banner))

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

    write("robots.txt", "User-agent: *\nDisallow: /\n")
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

    # ---- 勞動市場 ----
    if want("labor"):
        cfg = load_config("indicators.yaml")
        ids, labels, inverts = series_ids(cfg, LABOR_GROUPS)
        log.info("勞動模組：%d 個序列", len(ids))
        series, vintages, failed = gather_fred(args.offline, ids, "labor",
                                               vintage_ids=("PAYEMS", "USPRIV"))
        all_failed += failed
        labor_series = series          # 通膨模組的傳導分析要用到薪資序列
        ctxs["labor"] = build.build_labor_context(
            cfg, series, vintages, labels, inverts, failed, args.offline,
            consensus=load_config("consensus.yaml"))
        log.info("勞動模組完成：%s，%d 項訊號",
                 ctxs["labor"]["data_month"], len(ctxs["labor"]["flags"]))

    # ---- 通膨 ----
    if want("inflation"):
        cfg = load_config("inflation.yaml")
        if cfg:
            ids, labels, inverts = series_ids(cfg, INFL_GROUPS)
            log.info("通膨模組：%d 個序列", len(ids))
            series, _, failed = gather_fred(args.offline, ids, "inflation")
            all_failed += failed
            ctxs["inflation"] = build.build_inflation_context(
                cfg, series, failed, args.offline, labor_series=labor_series)
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
            # 科技巨頭的財報改由 SEC EDGAR 自動擷取，就地覆寫 cfg
            failed = failed + gather_hyperscalers(cfg, args.offline)
            all_failed += failed
            ctxs["rates"] = build.build_rates_context(
                cfg, series, failed, args.offline)
            p = ctxs["rates"]["pressure"]
            log.info("長端模組完成：供給壓力 %s（分數 %+.2f）", p.level, p.score)

    # ---- 聯準會文本 ----
    if want("fomc"):
        fcfg = load_config("fomc.yaml")
        fetch_cfg = fcfg.get("fetch") or {}
        log.info("聯準會文本：抓取近 %d 年的會後聲明與投票紀錄",
                 fetch_cfg.get("years_back", FOMC_YEARS_BACK))
        statements, failed = gather_fomc(args.offline, fetch_cfg)
        all_failed += failed
        ctxs["fomc"] = build.build_fomc_context(
            statements, fcfg.get("policy_rate") or {},
            failed, args.offline)
        if not ctxs["fomc"].get("empty"):
            log.info("聯準會文本完成：%d 份聲明，最新 %s",
                     len(statements), ctxs["fomc"]["latest_date"])

    # ---- 情境合成（缺件也會產出，但畫面上會明示缺哪一塊）----
    ctxs["scenario"] = build.build_scenario_context(
        ctxs.get("labor"), ctxs.get("inflation"), ctxs.get("fomc"),
        ctxs.get("rates"))
    sc = ctxs["scenario"]["scenario"]
    log.info("情境合成：%s（就業%s × 通膨%s）%s",
             sc.verdict_name or sc.name, sc.labor_state, sc.infl_state,
             f"　※ 原始格位 {sc.name}，已依聯準會重心修正" if sc.overridden else "")

    # ---- 本期變化摘要：跟上一次執行的快照比 ----
    # 局部重跑（--only）的 context 是殘缺的，比對與存檔都會產生
    # 「情境移動」的假訊號，所以跳過。
    if args.only:
        ctxs["changes"] = None
        log.info("局部重跑（--only %s）：跳過變化比對與快照存檔", args.only)
    else:
        prev_snap = chg.load_previous(STATE_FILE)
        cur_snap = chg.snapshot(ctxs)
        ctxs["changes"] = chg.compare(cur_snap, prev_snap)
        log.info("變化摘要：%s", ctxs["changes"].headline)

    ctxs["_real_modules"] = REAL_MODULES
    written = write_site(ctxs, args.offline, only=args.only)
    if not args.only:
        chg.save(STATE_FILE, cur_snap)
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
        out = {"generated_at": dt.datetime.now().isoformat(timespec="seconds")}
        if ctxs.get("labor"):
            l = ctxs["labor"]
            out["labor"] = {"month": l["data_month"], "score": l["score"]["score"],
                            "tilt": l["tilt"],
                            "flags": [f.__dict__ for f in l["flags"]]}
        if ctxs.get("inflation"):
            i = ctxs["inflation"]
            out["inflation"] = {"month": i["data_month"], "tilt": i["tilt"],
                                "flags": [f.__dict__ for f in i["flags"]]}
        out["scenario"] = {"name": sc.verdict_name or sc.name,
                           "grid_name": sc.name, "labor": sc.labor_state,
                           "inflation": sc.infl_state, "lean": sc.lean}
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
