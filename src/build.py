"""
各模組的「資料 → 畫面用結構」轉換層。

一個模組 = 一個 build_*_context()，輸入原始序列，輸出畫面需要的字典。
分析邏輯在 src/analysis/，版面在 src/pages/，這裡只負責把兩邊接起來。

新增模組時只要在這裡加一個 build_*_context()，
再到 src/pages/ 加一個對應的頁面產生器即可。
"""

from __future__ import annotations

import datetime as dt

from . import charts, fmt
from .analysis import (attribution, regime, revisions, rules,
                       inflation as infl_an, rules_inflation, fomc_text,
                       scenario, breakeven as be, surprise as sp,
                       passthrough as pt)
from .analysis.core import (diff_series, moving_avg, value_at, yoy, diff,
                           annualized, yoy_series, annualized_series,
                           since, span_label)

# 全站圖表的顯示起點。資料本身可能抓得更早（統計量需要），
# 但畫出來的一律從這裡開始，讓所有圖表的時間軸一致。
CHART_START = "2025-01-01"


def build_labor_context(cfg: dict, series: dict, vintages: dict,
                        labels: dict, inverts: dict, failed: list, offline: bool,
                        consensus: dict | None = None) -> dict:
    payems = series.get("PAYEMS", [])
    nfp_changes = diff_series(payems)
    data_month = payems[-1]["date"][:7] if payems else "—"

    # ---------------- 修正追蹤 ----------------
    rev = revisions.RevisionResult(series_id="PAYEMS")
    v = vintages.get("PAYEMS")
    if v and "__snapshot__" in v:
        rev = revisions.from_snapshots("PAYEMS", v["__snapshot__"], payems)
    elif v:
        rev = revisions.from_vintages("PAYEMS", v, payems)

    source_note = {
        "alfred": "ALFRED 官方歷史版本",
        "snapshot": "本地快照比對（尚無 ALFRED 資料）",
        "none": "尚無修正資料 — 第二次執行後才會出現",
    }[rev.source]

    # ---------------- 產業歸因 ----------------
    ind_meta = cfg.get("industries") or []
    ind_rows = {m["id"]: series.get(m["id"], []) for m in ind_meta
                if series.get(m["id"])}
    att = attribution.attribute_payrolls(payems, ind_rows, ind_meta)

    # ---------------- 失業率分解 ----------------
    # 注意：就業要用家庭調查（CE16OV），與失業率同一份調查，分解才會閉合
    dec = attribution.attribute_unemployment_rate(
        series.get("UNRATE", []), series.get("CE16OV", []), series.get("CLF16OV", [])
    )
    verdict_map = {
        "bad_decline": ("勞動力退出所致", "var(--critical)"),
        "good_decline": ("就業增加所致", "var(--good)"),
        "bad_rise": ("就業減少所致", "var(--critical)"),
        "supply_rise": ("勞動力擴張所致", "var(--warning)"),
        "neutral": ("大致持平", "var(--text-secondary)"),
    }
    if dec:
        t, c = verdict_map.get(dec["verdict"], ("—", "var(--muted)"))
        dec["verdict_text"], dec["verdict_color"] = t, c

    # ---------------- 薪資組成 ----------------
    wage = attribution.attribute_wage_composition(
        series.get("CES0500000003", []), series.get("AHETPI", [])
    )

    # ---------------- 損益兩平就業增速 ----------------
    # 沒有這條線，非農的絕對數字無法解讀
    bkev = be.estimate(series.get("CNP16OV", []), series.get("CIVPART", []),
                       payems, series.get("CE16OV", []))

    # ---------------- 意外值 ----------------
    exp_month = payems[-1]["date"][:7] if payems else ""
    exp = ((consensus or {}).get("expectations") or {}).get(exp_month) or {}
    nfp_chg_series = diff_series(payems)
    surprises = [
        sp.evaluate("非農就業月變動", nfp_chg_series, exp.get("PAYEMS"),
                    "manual" if exp.get("PAYEMS") is not None else "none",
                    unit=" 千人", higher_is_better=True),
        sp.evaluate("失業率", series.get("UNRATE", []), exp.get("UNRATE"),
                    "manual" if exp.get("UNRATE") is not None else "none",
                    unit="%", higher_is_better=False),
    ]

    # ---------------- 燈號與分數 ----------------
    lights = regime.build_lights(series, cfg.get("regime_lights") or [])
    score = regime.composite_score(series, labels, inverts)

    # ---------------- 規則引擎 ----------------
    ctx = rules.RuleContext(series=series, attribution=att, unrate_decomp=dec,
                            revisions=rev, wage_comp=wage, lights=lights)
    flags = rules.run_rules(ctx)
    tilt = rules.lean_balance(flags)

    # ---------------- KPI ----------------
    nfp_now = value_at(nfp_changes, 0)
    ma3 = moving_avg(nfp_changes, 3)
    ma12 = moving_avg(nfp_changes, 12)
    u3 = series.get("UNRATE", [])
    lfpr = series.get("CIVPART", [])
    ahe = series.get("CES0500000003", [])
    ahe_yoy = yoy(ahe)

    # 白話說明：把數字翻譯成一句人話，給非專業讀者看
    u3_now = value_at(u3)
    lfpr_now = value_at(lfpr)
    ahe_now = value_at(ahe)
    plain_nfp = "—"
    if nfp_now is not None:
        verb = "增加" if nfp_now >= 0 else "減少"
        # 單位統一用「萬人」——同一張卡的副標與數值列都是萬人，
        # 白話句不能自己改用「萬個」。
        plain_nfp = f"美國整體就業這個月{verb}約 {fmt.wan_abs(nfp_now)}。"
        if ma3 is not None:
            plain_nfp += (f"近三個月平均每月{'增加' if ma3 >= 0 else '減少'}"
                          f" {fmt.wan_abs(ma3)}。")
    plain_u3 = ("—" if u3_now is None else
                f"每 100 個有在找工作的人裡，約 {u3_now:.1f} 人還沒找到。"
                "已經放棄找工作的人不算在這個數字裡。")
    plain_ahe = ("—" if ahe_yoy is None else
                 f"薪水一年漲 {ahe_yoy:.1f}%，目前平均每小時 "
                 f"{ahe_now:,.2f} 美元。" if ahe_now else f"薪水一年漲 {ahe_yoy:.1f}%。")
    plain_lfpr = ("—" if lfpr_now is None else
                  f"16 歲以上的人裡，有 {lfpr_now:.1f}% 在工作或正在找工作，"
                  "其餘是退休、就學或已放棄找工作。")

    kpi = {
        "nfp_display": fmt.wan(nfp_now),
        "nfp_sub": (f"近三個月平均 {fmt.wan(ma3)}　·　近一年平均 {fmt.wan(ma12)}"
                    if ma3 is not None and ma12 is not None else ""),
        "nfp_plain": plain_nfp,
        "u3_plain": plain_u3,
        "ahe_plain": plain_ahe,
        "lfpr_plain": plain_lfpr,
        "nfp_spark": [r["value"] for r in
                      since(nfp_changes, CHART_START, 12)],
        "nfp_flag": (f"前兩月合計修正 {fmt.wan(rev.two_month_net)}"
                     if rev.two_month_net is not None else None),
        "nfp_flag_kind": ("neg" if (rev.two_month_net or 0) < 0 else "pos"),

        "u3_display": f"{value_at(u3):.1f}%" if u3 else "—",
        "u3_sub": (f"較上月 {diff(u3):+.1f} 個百分點"
                   f"　·　含低度就業 {value_at(series.get('U6RATE', [])):.1f}%"
                   if u3 and series.get("U6RATE") else ""),
        "u3_spark": [r["value"] for r in since(u3, CHART_START, 12)],
        "u3_flag": dec.get("verdict_text") if dec else None,
        "u3_flag_kind": ("neg" if dec.get("verdict") in ("bad_decline", "bad_rise") else "pos") if dec else "",

        "ahe_display": f"{ahe_yoy:.1f}%" if ahe_yoy is not None else "—",
        "ahe_sub": (f"基層員工 {wage['yoy_production']:.1f}%　·　"
                    f"差距 {wage['gap']:+.2f} 個百分點" if wage else ""),
        # 平均時薪是水準值（美元），直接畫是一條斜線 → 改畫年增率
        "ahe_spark": [r["value"] for r in
                      since(yoy_series(ahe), CHART_START, 12)],
        "ahe_flag": ("組成效果推高總體時薪" if wage.get("composition_bias") == "overstated"
                     else ("基層薪資壓力較大" if wage.get("composition_bias") == "understated" else None)),
        "ahe_flag_kind": "neg" if wage.get("composition_bias") == "overstated" else "",

        "lfpr_display": f"{value_at(lfpr):.1f}%" if lfpr else "—",
        "lfpr_sub": (f"較上月 {diff(lfpr):+.1f} 個百分點　·　"
                     f"25-54 歲 {value_at(series.get('LNS11300060', [])):.1f}%"
                     if lfpr and series.get("LNS11300060") else ""),
        "lfpr_spark": [r["value"] for r in since(lfpr, CHART_START, 12)],
        "lfpr_flag": None,
        "lfpr_flag_kind": "",
    }

    # ---------------- 修正卡片 ----------------
    rev_rows = [{"label": r.obs_date[:7], "original": r.original, "current": r.current}
                for r in rev.recent[-7:]]
    rev_stats = [
        {"label": "前兩月合計修正",
         "value": fmt.wan(rev.two_month_net),
         "color": "var(--critical)" if (rev.two_month_net or 0) < 0 else "var(--good)",
         "note": ("相對上次發布"
                  + (f"；相對初值累計 {fmt.wan(rev.cumulative_net)}"
                     if rev.cumulative_net is not None
                     and abs((rev.cumulative_net or 0) - (rev.two_month_net or 0)) > 1
                     else ""))},
        {"label": "近三個月平均新增",
         "value": fmt.wan(rev.ma3_now),
         "note": (f"若沒有這次修正，應為 {fmt.wan(rev.ma3_before_revision)}"
                  if rev.ma3_before_revision is not None else "")},
        {"label": "近一年修正傾向",
         "value": (f"{fmt.wan(rev.bias_12m)}/月" if rev.bias_12m is not None else "—"),
         "color": "var(--warning)" if rev.bias_direction == "systematically_down" else "inherit",
         "note": {"systematically_down": "初值偏樂觀，應打折看待",
                  "systematically_up": "初值偏保守",
                  "neutral": "沒有明顯偏向",
                  "unknown": "資料不足"}[rev.bias_direction]},
    ]

    # ---------------- 貢獻度卡片 ----------------
    shown, other_sum, other_n = att.display_set(n=5)
    wf_items = [{
        "label": c.label,
        "value": c.value,
        "muted": c.noncyclical,
        "notable": c.notable,
        "note": ("不受景氣影響" if c.noncyclical else None),
        "tip": (f"{c.label}｜{fmt.people(c.value)} 人"
                + (f"｜相對自身歷史 {c.zscore:+.1f} 個標準差" if c.zscore is not None else "")),
    } for c in shown]
    if other_n:
        wf_items.append({"label": f"其他 {other_n} 個行業", "value": other_sum,
                         "muted": True, "note": "多個行業加總",
                         "tip": f"其餘 {other_n} 個行業合計 {fmt.people(other_sum)} 人"})
    agg = att.aggregates
    n_ind = len(att.contributions)
    att_stats = [
        {"label": "全體合計", "value": fmt.wan(att.total)},
        {"label": "扣掉醫療與政府",
         "value": fmt.wan(agg.get("cyclical", 0)),
         "color": "var(--critical)" if agg.get("cyclical", 0) < 0 else "var(--good)",
         "note": "跟景氣連動的部分"},
        {"label": "有增加人力的行業",
         "value": f"{round(agg.get('breadth', 0)*n_ind/100)} / {n_ind} 個",
         "note": f"佔 {agg.get('breadth', 0):.0f}%"},
    ]
    # 地方政府教育單獨列出：它是地方政府的子項（已含在上面，不重複計入瀑布圖），
    # 但 7 月的季節性爭議就在這裡，值得單獨標示。
    lge = series.get("CES9093161101", [])
    if lge:
        lge_d = diff(lge)
        if lge_d is not None:
            att_stats.append({
                "label": "其中：地方政府教育",
                "value": fmt.wan(lge_d),
                "color": "var(--warning)" if abs(lge_d) > 25 else "inherit",
                "note": "學期結束的季節性因素，不一定代表真的裁員",
            })
    att_table = [
        {"label": c.label, "value": c.value,
         "share": "—（總變動過小，比例失真）" if att.share_suppressed
                  else (f"{c.share:+.0f}%" if c.share is not None else "—")}
        for c in att.contributions
    ]

    # ---------------- JOLTS ----------------
    jolts_rows = []
    for sid, unit in [("JTSJOL", "K"), ("JTSHIR", "%"), ("JTSQUR", "%"), ("JTSLDR", "%")]:
        rows = series.get(sid, [])
        if not rows:
            continue
        cur, dd = value_at(rows), diff(rows)
        # 職缺數的單位是「個」不是「人」——一個雇主可以同時開多個職缺
        vfmt = f"{cur/10:,.1f} 萬個" if unit == "K" else f"{cur:.1f}%"
        if dd is None:
            dfmt = "—"
        elif unit == "K":
            dfmt = f"{dd/10:+,.1f} 萬個"
        else:
            dfmt = "持平" if abs(dd) < 0.005 else f"{dd:+.2f} 個百分點"
        jolts_rows.append({"label": labels.get(sid, sid), "value": vfmt, "chg": dfmt})

    jolts_date = series.get("JTSJOL", [{}])[-1].get("date", "")[:7] if series.get("JTSJOL") else "—"
    # 落後幾期要算出來，不能寫死「約兩個月」——旁邊就印著兩個資料月份，
    # 讀者一眼就能對照，寫死的那句話有一半的時候是錯的。
    def _month_gap(a_date: str, b_date: str) -> int | None:
        try:
            ay, am = int(a_date[:4]), int(a_date[5:7])
            by, bm = int(b_date[:4]), int(b_date[5:7])
        except (ValueError, IndexError):
            return None
        return (ay - by) * 12 + (am - bm)
    _lag = _month_gap(data_month, jolts_date) if jolts_date != "—" else None
    jolts_lag_text = (f"較就業報告落後 {_lag} 個月" if _lag and _lag > 0
                      else "與就業報告同月份")

    return {
        "release_name": (cfg.get("meta") or {}).get("release_name", "Employment Situation"),
        "data_month": data_month,
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "offline": offline,
        "failed": failed,
        "kpi": kpi,
        "revision": {"stats": rev_stats,
                     "table": charts.revision_table(rev_rows, fmt=fmt.people),
                     "source_note": source_note},
        "attribution": {"stats": att_stats,
                        "bars": charts.diverging_bars(wf_items, fmt=fmt.people),
                        "table": att_table,
                        "total_count": n_ind},
        "decomp": dec,
        "lights": lights,
        "flags": flags,
        "tilt": tilt,
        "score": {"score": score.score, "delta": score.delta,
                  "window": score.window,
                  # z 要送「已調整方向」的值，否則表格數字與下方
                  # 「正值＝就業強」的說明相反（失業率上升會顯示成正分）
                  "items": [{"label": i.label,
                             "z": (-i.z if i.inverted else i.z),
                             "inverted": i.inverted, "weight": i.weight,
                             "window": i.window,
                             "contribution": i.contribution} for i in score.items]},
        "jolts": jolts_rows,
        "jolts_note": f"資料月份 {jolts_date}（{jolts_lag_text}）",
        "breakeven": _breakeven_block(bkev),
        "surprises": _surprise_block(surprises),
        "asof": {
            "labor": payems[-1]["date"] if payems else "",
            "jolts": (series.get("JTSJOL") or [{}])[-1].get("date", ""),
            "claims": (series.get("CCSA") or [{}])[-1].get("date", ""),
        },
        "mini": {
            # 「萬人」抽到單位列，六格的數字才不會互相疊在一起
            "nfp": charts.mini_series(nfp_chg_series, unit="萬人",
                                      fmt=lambda v: f"{v/10:+,.1f}"),
            "u3": charts.mini_series(u3, fmt=lambda v: f"{v:.1f}%"),
            "ahe": charts.mini_series(yoy_series(ahe), fmt=lambda v: f"{v:.1f}%"),
            "lfpr": charts.mini_series(lfpr, fmt=lambda v: f"{v:.1f}%"),
        },
        # 給「本期變化摘要」比對用。人數一律以「萬人」呈現，與全站口徑一致。
        "key_metrics": {
            "nfp": {"label": "非農就業月變動",
                    "value": None if nfp_now is None else nfp_now / 10,
                    "unit": "萬人", "threshold": 1},
            "nfp_3m": {"label": "非農三個月均",
                       "value": None if ma3 is None else ma3 / 10,
                       "unit": "萬人", "threshold": 1},
            "u3": {"label": "失業率", "value": value_at(u3),
                   "unit": "%", "delta_unit": " 個百分點", "threshold": 0.05},
            "lfpr": {"label": "勞動參與率", "value": value_at(lfpr),
                     "unit": "%", "delta_unit": " 個百分點", "threshold": 0.05},
            "ahe_yoy": {"label": "平均時薪年增", "value": ahe_yoy,
                        "unit": "%", "delta_unit": " 個百分點", "threshold": 0.05},
            "breakeven": {"label": "損益兩平就業增速",
                          "value": None if bkev.monthly is None else bkev.monthly / 10,
                          "unit": "萬人", "threshold": 0.5},
        },
    }


def _breakeven_block(b) -> dict:
    """損益兩平就業增速的畫面資料。"""
    label, note = be.VERDICT_TEXT.get(b.verdict, ("—", ""))
    stats = [
        {"label": "損益兩平就業增速", "value": fmt.wan(b.monthly),
         "note": "維持失業率不變所需的每月就業增加"},
        {"label": "非農三個月均", "value": fmt.wan(b.nfp_3m)},
        {"label": "缺口", "value": fmt.wan(b.gap),
         "color": ("var(--critical)" if (b.gap or 0) < -25 else
                   ("var(--good)" if (b.gap or 0) > 25 else "inherit")),
         "note": label},
        {"label": "每月人口成長", "value": fmt.wan(b.pop_growth),
         "note": f"參與率 {b.participation:.1f}%" if b.participation else ""},
    ]
    chart = ""
    if b.series:
        # 圖表單位要跟上方數字一致（萬人），否則讀者要自己換算
        merged = [{"date": r["date"], "value": r["value"] / 10}
                  for r in since(b.series, CHART_START, 12)]
        # 萬人的全站慣例是一位小數（fmt.wan），圖上標籤跟著用
        chart = charts.line_chart(merged, unit=" 萬人", height=150,
                                  color="var(--line-2)", digits=1)
    return {"stats": stats, "chart": chart, "note": b.note,
            "verdict": b.verdict, "verdict_label": label, "verdict_note": note,
            "monthly": b.monthly, "gap": b.gap}


# ===========================================================================
# 通膨模組（P2）
# ===========================================================================
def build_inflation_context(cfg: dict, series: dict, failed: list,
                            offline: bool,
                            labor_series: dict | None = None) -> dict:
    comp_meta = cfg.get("cpi_components") or []
    headline = series.get("CPIAUCSL", [])
    data_month = headline[-1]["date"][:7] if headline else "—"

    summ = infl_an.summarize(series, comp_meta)

    # ---- 分項貢獻（看三個月，單月雜訊太大）----
    comp_rows = {m["id"]: series.get(m["id"], []) for m in comp_meta
                 if series.get(m["id"])}
    att = infl_an.attribute_cpi(headline, comp_rows, comp_meta, months=3)

    # ---- 燈號 ----
    computed = infl_an.light_values(series, summ)
    lights = _lights_from(computed, cfg.get("regime_lights") or [])

    # ---- 規則 ----
    ctx = rules_inflation.InflationContext(series, summ, att, lights)
    flags = rules_inflation.run_rules(ctx)

    from .pages.inflation import _tilt
    tilt = _tilt(flags)

    # ---- KPI ----
    def rate_spark(sid, kind="yoy"):
        """
        走勢縮圖畫的是「變化率」，不是指數水準。
        指數水準只會一路往上，畫出來是一條斜線，沒有資訊量。
        """
        rows = series.get(sid, [])
        if not rows:
            return []
        r = yoy_series(rows) if kind == "yoy" else annualized_series(rows, 3)
        return [x["value"] for x in since(r, CHART_START, 12)]

    def level_spark(sid):
        """本身就是比率的序列（例如通膨預期）可以直接畫水準值。"""
        rows = series.get(sid, [])
        return [x["value"] for x in since(rows, CHART_START, 20)]

    kpi = {
        "headline_display": _pct(summ.headline_yoy),
        "headline_sub": (f"近三個月年化 {_pct(annualized(headline, 3))}"
                         f"　·　走勢為年增率" if headline else ""),
        "headline_plain": (
            f"你買的東西平均比一年前貴 {summ.headline_yoy:.1f}%。"
            "這個數字包含食物和能源，所以起伏會比較大。"
            if summ.headline_yoy is not None else "—"),
        "headline_spark": rate_spark("CPIAUCSL"),

        "core_display": _pct(summ.core_yoy),
        "core_sub": (f"近三個月年化 {_pct(summ.core_3m)}　·　"
                     f"近六個月年化 {_pct(summ.core_6m)}　·　走勢為年增率"),
        "core_plain": (
            f"剔除波動大的食物與能源後，物價一年漲 {summ.core_yoy:.1f}%。"
            "聯準會看趨勢時主要看這一類數字。"
            if summ.core_yoy is not None else "—"),
        "core_spark": rate_spark("CPILFESL"),
        "core_flag": (f"三個月年化 {summ.core_3m:.1f}%，動能"
                      + ("放緩" if (summ.core_3m or 9) < (summ.core_yoy or 0) else "回升")
                      if summ.core_3m is not None and summ.core_yoy is not None else None),
        "core_flag_kind": ("pos" if (summ.core_3m or 9) < (summ.core_yoy or 0) else "neg"),

        "pce_display": _pct(summ.pce_core_yoy),
        "pce_sub": ("目標 2.0%" + (f"　·　差距 {summ.pce_core_yoy - 2:+.1f} 個百分點"
                                   if summ.pce_core_yoy is not None else "")),
        "pce_plain": (
            f"核心 PCE 年增 {summ.pce_core_yoy:.1f}%。"
            "聯準會講的 2% 目標指的就是這個指標，不是 CPI。"
            if summ.pce_core_yoy is not None else "—"),
        "pce_spark": rate_spark("PCEPILFE"),
        "pce_flag": (("已接近目標" if summ.pce_core_yoy - 2 <= 0.3 else "仍高於目標")
                     if summ.pce_core_yoy is not None else None),
        "pce_flag_kind": ("pos" if (summ.pce_core_yoy or 9) - 2 <= 0.3 else "neg"),

        "exp_display": (f"{summ.expect_5y5y:.2f}%" if summ.expect_5y5y is not None else "—"),
        "exp_sub": (f"密大 1 年預期 {_pct(summ.expect_1y)}"),
        "exp_plain": _expect_plain(summ.expect_5y5y),
        "exp_spark": level_spark("T5YIFR"),
    }

    # ---- 分項長條 ----
    shown, other_sum, other_n = att.display_set(n=5)
    items = [{
        "label": c.label,
        "value": c.value,
        "muted": c.noncyclical,
        "notable": c.notable,
        "note": ("落後項" if c.noncyclical else None),
        "tip": f"{c.label}｜貢獻 {c.value:+.2f} 個百分點",
    } for c in shown]
    if other_n:
        items.append({"label": f"其他 {other_n} 項", "value": other_sum,
                      "muted": True, "note": "多項加總"})

    agg = att.aggregates
    att_stats = [
        {"label": "近三個月漲幅", "value": f"{att.total:+.2f}%"},
        {"label": "其中：住房貢獻", "value": f"{agg.get('shelter', 0):+.2f} 個百分點",
         "note": "算法落後市場行情約一年"},
        {"label": "剔除住房後",
         "value": (f"{agg['ex_shelter']:+.2f}%"
                   if agg.get("ex_shelter") is not None else "—"),
         "color": ("var(--good)"
                   if (agg.get("ex_shelter") or 9) < 0.6 else "inherit"),
         "note": "更接近當下的實際物價（已按剩餘權重換算回通膨率）"},
        {"label": "食物與能源貢獻", "value": f"{agg.get('food_energy', 0):+.2f} 個百分點"},
    ]

    # ---- 趨勢型指標 ----
    trend_rows = []
    for sid, label, note in [
        ("MEDCPIM159SFRBCLE", "中位數 CPI", "取漲幅正中間的項目，不受極端值影響"),
        ("TRMMEANCPIM159SFRBCLE", "截尾平均 CPI", "剔除漲跌最極端的項目後平均"),
        ("CORESTICKM159SFRBATL", "黏性核心 CPI", "只看價格很少調整的項目，代表通膨慣性"),
    ]:
        v = value_at(series.get(sid, []))
        if v is not None:
            trend_rows.append({"label": label, "value": f"{v:.1f}%", "note": note})

    # ---- 能源 ----
    energy_stats = []
    if summ.oil_1m is not None:
        energy_stats.append({
            # 一位小數：整數會讓下方「以能源佔比 6.2% 與傳導係數 0.4 粗估」
            # 這句話算不回同一個答案，也會讓「>8% 才觸發旗標」看起來像壞掉
            "label": "原油近一個月", "value": f"{summ.oil_1m:+.1f}%",
            "color": ("var(--serious)" if summ.oil_1m > 0 else "var(--series-1)"),
            "note": "領先加油站價格約 2–4 週"})
    if summ.gas is not None:
        energy_stats.append({"label": "零售汽油", "value": f"{summ.gas:.2f} 美元／加侖"})
    if summ.oil_1m is not None:
        est = summ.oil_1m * 0.062 * 0.4
        energy_stats.append({
            "label": "對總體 CPI 的估計影響", "value": f"{est:+.2f} 個百分點",
            "note": "以能源佔比 6.2% 與傳導係數 0.4 粗估"})
    energy_stats.append({"label": "對核心 CPI 的影響", "value": "無",
                         "note": "核心已剔除能源"})

    # 油價與汽油走勢圖：油價領先加油站價格 2–4 週，這段落差就是「已發生但還沒進 CPI」
    oil_rows = since(series.get("DCOILWTICO", []), CHART_START, 40)
    gas_rows = since(series.get("GASREGW", []), CHART_START, 12)
    oil_chart = charts.line_chart(
        oil_rows, unit=" 美元", height=150,
        marks=[{"index": max(len(oil_rows) - 22, 0), "label": "一個月前"}]
    ) if len(oil_rows) > 2 else ""
    # 汽油圖也要有「一個月前」的虛線標記。旁邊的說明寫著「虛線是一個月前
    # 的位置」，只有原油那張畫了標記時，讀者會把汽油圖上的高低參考線
    # （那是最高值與最低值）誤讀成一個月前的位置。汽油是週資料，一個月約 4 筆。
    gas_chart = charts.line_chart(
        gas_rows, unit=" 美元", height=130, color="var(--line-2)",
        marks=[{"index": max(len(gas_rows) - 5, 0), "label": "一個月前"}]
    ) if len(gas_rows) > 2 else ""

    # ---- 薪資 → 服務業通膨的傳導（把兩個模組真正接起來的地方）----
    pass_block = _passthrough_block(labor_series or {}, series)

    return {
        "release_name": (cfg.get("meta") or {}).get("release_name", "CPI"),
        "weights_vintage": (cfg.get("meta") or {}).get("weights_vintage", ""),
        "data_month": data_month,
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "offline": offline,
        "failed": failed,
        "summary": summ,
        "kpi": kpi,
        "flags": flags,
        "tilt": tilt,
        "lights": lights,
        "attribution": {
            "stats": att_stats,
            "bars": charts.diverging_bars(items, fmt=lambda v: f"{v:+.2f} 個百分點"),
        },
        "trend_rows": trend_rows,
        "energy_stats": energy_stats,
        "oil_chart": oil_chart,
        "gas_chart": gas_chart,
        # 標題的期間字串由實際畫出來的資料推得，不寫死「今年以來」
        "oil_span": span_label(oil_rows),
        "gas_span": span_label(gas_rows),
        "passthrough": pass_block,
        "asof": {
            "cpi": headline[-1]["date"] if headline else "",
            "pce": (series.get("PCEPILFE") or [{}])[-1].get("date", ""),
            "oil": (series.get("DCOILWTICO") or [{}])[-1].get("date", ""),
            "exp": (series.get("T5YIFR") or [{}])[-1].get("date", ""),
        },
        "mini": {
            "headline": charts.mini_series(yoy_series(series.get("CPIAUCSL", [])),
                                           fmt=lambda v: f"{v:.1f}%"),
            "core": charts.mini_series(yoy_series(series.get("CPILFESL", [])),
                                       fmt=lambda v: f"{v:.1f}%"),
            "pce": charts.mini_series(yoy_series(series.get("PCEPILFE", [])),
                                      fmt=lambda v: f"{v:.1f}%"),
            # 日頻序列：從最新一筆往回每 7 個交易日取一點（[::7] 從頭取
            # 會讓最後一格不是最新值），並標到「月/日」避免三格都寫同一個月
            "exp": charts.mini_series(
                since(series.get("T5YIFR", []), CHART_START, 40)[::-1][::7][::-1],
                fmt=lambda v: f"{v:.2f}%", daily=True),
        },
        "key_metrics": {
            "core_cpi_yoy": {"label": "核心 CPI 年增", "value": summ.core_yoy,
                             "unit": "%", "delta_unit": " 個百分點", "threshold": 0.05},
            "core_cpi_3m": {"label": "核心 CPI 三月年化", "value": summ.core_3m,
                            "unit": "%", "delta_unit": " 個百分點", "threshold": 0.1},
            "core_pce": {"label": "核心 PCE 年增", "value": summ.pce_core_yoy,
                         "unit": "%", "delta_unit": " 個百分點", "threshold": 0.05},
            "supercore": {"label": "核心服務除住房", "value": summ.supercore_3m,
                          "unit": "%", "delta_unit": " 個百分點", "threshold": 0.1},
            "exp5y5y": {"label": "長期通膨預期", "value": summ.expect_5y5y,
                        "unit": "%", "delta_unit": " 個百分點", "threshold": 0.03},
        },
    }


def _pct(v, digits=1):
    return "—" if v is None else f"{v:.{digits}f}%"


def _expect_plain(v):
    """白話說明必須隨數字改變——寫死的句子在數字翻轉時會變成錯的。"""
    base = "市場對「五年後起算、之後五年」的通膨定價。"
    if v is None:
        return base
    if v > 2.60:
        return (base + f"目前 {v:.2f}%，明顯高於聯準會 2% 的目標。"
                "預期一旦往上跑，通膨容易自我實現，這是聯準會最緊張的事。")
    if v < 2.20:
        return base + f"目前 {v:.2f}%，甚至低於目標，代表市場對通膨完全不擔心。"
    return base + f"目前 {v:.2f}%，貼近目標，代表預期錨定良好。"


def _lights_from(computed: dict, cfgs: list) -> list:
    """用既有的燈號分類邏輯，但數值來源由呼叫端提供。"""
    out = []
    for cfg in cfgs:
        val, prev, display = computed.get(cfg["key"], (None, None, "—"))
        status = regime._classify(val, cfg)
        if val is not None and prev is not None:
            d = val - prev
            direction = "up" if d > 1e-9 else ("down" if d < -1e-9 else "flat")
        else:
            direction = "flat"
        out.append(regime.Light(key=cfg["key"], label=cfg["label"],
                                desc=cfg.get("desc", ""), value=val, prev=prev,
                                status=status, display=display,
                                delta_dir=direction))
    return out


# ===========================================================================
# 聯準會文本模組（P3）
# ===========================================================================
def build_fomc_context(statements: list[dict], rate_cfg: dict,
                       failed: list, offline: bool) -> dict:
    if not statements:
        return {"empty": True, "offline": offline, "failed": failed}

    docs = [fomc_text.analyse(st) for st in statements]
    docs.sort(key=lambda d: d.date)

    latest = docs[-1]
    prev = docs[-2] if len(docs) > 1 else None
    rows = (fomc_text.paired_redline(prev.text_display, latest.text_display)
            if prev else [])
    changed = fomc_text.changed_rows(rows)

    from .pages.fomc import _diff_block, _heatmap

    score_rows = "".join(
        f'<tr><td>{d.date}</td>'
        f'<td>{"0.00" if abs(d.objective_score) < 1e-9 else format(d.objective_score, "+.2f")}</td>'
        f'<td class="muted-cell">{d.tone_score:+.2f}</td>'
        f'<td class="muted-cell">{d.word_count}</td>'
        f'<td>{_vote_cell(d.vote)}</td></tr>'
        for d in reversed(docs)
    )

    hits = []
    for k, v in sorted(latest.hawk_hits.items(), key=lambda x: -x[1]):
        hits.append(f'<tr><td>{k}</td><td style="color:var(--serious)">鷹派</td>'
                    f'<td>{v}</td></tr>')
    for k, v in sorted(latest.dove_hits.items(), key=lambda x: -x[1]):
        hits.append(f'<tr><td>{k}</td><td style="color:var(--series-1)">鴿派</td>'
                    f'<td>{v}</td></tr>')

    presser = statements[-1].get("presser")
    obj = latest.obj_parts

    return {
        "empty": False,
        "offline": offline,
        "failed": failed,
        "latest_date": latest.date,
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "shift": fomc_text.shift(docs),
        "regime": fomc_text.regime_change(docs),
        "vote": latest.vote,
        "rate_range": (f"{rate_cfg.get('lower', 0):.2f}–{rate_cfg.get('upper', 0):.2f}%"
                       if rate_cfg else "—"),
        "obj_detail": "；".join(x for x in (obj.get("action_detail"),
                                           obj.get("dissent_detail"),
                                           obj.get("risk_detail")) if x),
        "obj_has_signal": obj.get("has_signal", False),
        "focus": latest.focus,
        "diff_html": _diff_block(changed),
        "diff_full_html": _diff_block(rows, show_same=True),
        "changed_count": len(changed),
        # 比對的是哪兩份要寫清楚——抓漏一份時比對對象會默默換掉，
        # 不標出來的話讀者無從發現
        "diff_pair": (prev.date if prev else None, latest.date),
        "fetched_dates": [x.date for x in docs],
        "heatmap_html": _heatmap(fomc_text.phrase_matrix(docs)),
        "score_rows": score_rows,
        "hits_rows": "".join(hits) or '<tr><td colspan="3">本次沒有命中任何詞典用語</td></tr>',
        "presser_available": bool(presser),
        "presser_reason": statements[-1].get("presser_error") or "pending",
        "presser_score": latest.presser_score or 0,
        # 逐字稿不再切前 N 個字——那沒有資訊價值。改成依主題抽句，
        # 外加「分數來源句」讓記者會措辭分數可追溯。
        "presser_summary": fomc_text.summarise_presser(presser or ""),
        "docs": docs,
    }


def _stat(label, value, color="inherit", note=""):
    n = f'<div class="s-note">{note}</div>' if note else ""
    return (f'<div class="stat"><div class="s-label">{label}</div>'
            f'<div class="s-value" style="color:{color}">{value}</div>{n}</div>')


def _vote_cell(vote: dict) -> str:
    ds = vote.get("dissents") or []
    if not ds:
        # 引言載明有反對票但名單解析失敗 → 顯示票數並示警，不能寫「一致」
        stated = vote.get("stated_dissent")
        if stated:
            return (f'<span style="color:var(--warning)">{stated} 反對'
                    f'（未解析）</span>')
        return '<span class="muted-cell">一致</span>'
    h = sum(1 for x in ds if x["direction"] == "hike")
    c = sum(1 for x in ds if x["direction"] == "cut")
    other = len(ds) - h - c        # 主張維持不變（或方向無法判定）的反對票
    parts = []
    if h:
        parts.append(f'<span style="color:var(--serious)">{h} 鷹</span>')
    if c:
        parts.append(f'<span style="color:var(--series-1)">{c} 鴿</span>')
    if other:
        parts.append(f'<span class="muted-cell">{other} 維持</span>')
    return " ".join(parts)


# ===========================================================================
# 情境合成（P4）
# ===========================================================================
CURVE_IMPLICATION = {
    # (政策傾向, 供給壓力) → (標題, 說明)
    ("dovish", "high"): (
        "降息也壓不下長端，曲線會走陡",
        "政策利率往下，但長端由供給與期限溢酬決定。短端跟著政策走、長端黏住不動，"
        "結果是曲線走陡而非整條下移。這種環境下拉長存續期間賺不到預期中的價差，"
        "中天期（5 年附近）通常是效率較高的位置。"),
    ("dovish", "moderate"): (
        "降息可望帶動整條曲線下移",
        "供給面沒有明顯阻力，長端大致跟隨政策利率預期移動，存續期間的效果較接近教科書。"),
    ("dovish", "low"): (
        "降息時長天期的漲幅可能大於短天期",
        "需求充足、供給壓力小，長端有額外的下行空間，拉長存續期間的報酬相對有利。"),
    ("hawkish", "high"): (
        "升息與供給壓力同向，長端承壓最重",
        "政策利率往上，同時投資人要求更高的期限溢酬才願意持有長債。"
        "兩股力量同向，30 年期的上行風險大於 2 年期。"),
    ("hawkish", "moderate"): (
        "升息主要推升短端，曲線傾向走平",
        "長端的供給面壓力有限，升息的效果集中在短天期，曲線傾向平坦化。"),
    ("hawkish", "low"): (
        "升息推升短端，長端相對有支撐",
        "需求充足使長端相對抗跌，曲線平坦化甚至再度倒掛的可能性上升。"),
    ("neutral", "high"): (
        "政策按兵不動，但長端仍可能自己走高",
        "政策利率沒有方向，長端的變動主要來自供給與財政面，"
        "這一段聯準會既不主導、也壓不下來。"),
    ("neutral", "moderate"): (
        "政策與供給面都沒有明確方向",
        "曲線形狀的變動主要來自資料面的意外，而非結構性力量。"),
    ("neutral", "low"): (
        "政策按兵不動，長端有下行空間",
        "供給壓力小、需求充足，長端可能在政策不動的情況下自行走低。"),
}


def build_scenario_context(labor_ctx: dict | None, infl_ctx: dict | None,
                           fomc_ctx: dict | None, rates_ctx: dict | None = None) -> dict:
    labor = None
    if labor_ctx:
        labor = {"score": labor_ctx["score"]["score"],
                 "tilt": labor_ctx["tilt"],
                 "flags": labor_ctx["flags"]}
    infl = None
    if infl_ctx:
        s = infl_ctx["summary"]
        infl = {"core_pce_yoy": s.pce_core_yoy, "core_3m": s.core_3m,
                "flags": infl_ctx["flags"]}
    fomc = None
    if fomc_ctx and not fomc_ctx.get("empty"):
        # 反應函數要一起帶進情境：同一格在通膨優先與就業優先下結論可能相反
        fomc = dict(fomc_ctx.get("shift") or {})
        fomc["focus"] = fomc_ctx.get("focus") or {}

    sc = scenario.synthesise(labor, infl, fomc)
    cells = scenario.grid_cells((sc.labor_state, sc.infl_state), sc.overridden)

    parts = []
    if labor_ctx:
        parts.append(f"就業 {labor_ctx['data_month']}")
    if infl_ctx:
        parts.append(f"物價 {infl_ctx['data_month']}")
    if fomc and fomc.get("cur_date"):
        parts.append(f"聲明 {fomc['cur_date']}")

    # ---- 長端供給壓力：不進九宮格，但要並排看 ----
    # 九宮格決定的是政策利率的方向；長端供給壓力決定的是曲線形狀。
    # 兩者互相獨立，硬合成會把「降息但長端不降」這種最重要的情況抹掉。
    rates_line = None
    if rates_ctx:
        from .analysis.rates import PRESSURE_TEXT
        sp = rates_ctx["pressure"]
        p_title, p_desc = PRESSURE_TEXT.get(sp.level, ("—", ""))
        c_title, c_desc = CURVE_IMPLICATION.get(
            (sc.lean, sp.level),
            ("尚無對照", "政策方向或供給壓力其中一項資料不足。"))
        top = sorted(sp.parts, key=lambda x: -abs(x["score"]))[:3]
        rates_line = {
            "level": sp.level,
            "score": sp.score,
            "title": p_title,
            "desc": p_desc,
            "curve_title": c_title,
            "curve_desc": c_desc,
            "parts": top,
        }
        if rates_ctx.get("as_of"):
            parts.append(f"利率 {rates_ctx['as_of']}")

        # 部位對照表是教科書式的映射，預設長端會跟著政策走。
        # 供給壓力偏高時這個前提不成立，必須在同一頁講清楚，否則兩段敘述互相矛盾。
        if sp.level == "high" and sc.positioning.get("殖利率曲線"):
            sc.positioning["殖利率曲線"] += (
                "。但目前長端供給壓力偏高，期限溢酬可能抵銷這個方向，"
                "平坦化的力道會比一般情況小")
        elif sp.level == "low" and sc.positioning.get("殖利率曲線"):
            sc.positioning["殖利率曲線"] += "。目前供給壓力偏低，長端的反應可能比一般情況更順"

    return {
        "scenario": sc,
        "cells": cells,
        "rates_line": rates_line,
        "as_of": "　·　".join(parts) or "—",
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def _surprise_block(items) -> dict:
    """
    意外值面板。預期值的來源一律標示，不把模型推估當成市場預期。

    只產一組卡片（實際／預期／意外＋判定），判定直接放在意外值卡裡——
    先前卡片下方還有一張同數字的表格，資訊完全重複，已移除。
    人數口徑統一為「萬人」，與 KPI 一致（內部資料為千人，這裡換算）。
    """
    from .analysis.surprise import VERDICT_TEXT

    def val(s, v, signed=False) -> str:
        if v is None:
            return "—"
        if "千人" in s.unit:
            return f'{v/10:+,.1f}<span class="su">萬人</span>'
        num = f"{v:+,.1f}" if signed else f"{v:,.1f}"
        # 兩個「率」相減的差是**個百分點**，不是 %——
        # 失業率 4.1% 對預期 4.2%，意外是 −0.1 個百分點
        unit = "個百分點" if (signed and s.unit == "%") else s.unit.strip()
        return f'{num}<span class="su">{unit}</span>'

    boxes, notes = [], []
    for s in items:
        if s.expected is None:
            notes.append(f"{s.label}：無預期資料")
            continue
        cls = {"beat": "beat", "miss": "miss"}.get(s.verdict, "")
        badge = (f'<div class="sbadge2 {cls or "inline"}">'
                 f'{VERDICT_TEXT.get(s.verdict, "")}</div>')
        if s.z is not None:
            badge += f'<div class="szn">偏離 {abs(s.z):.1f} 個標準差</div>'
        boxes.append(
            f'<div class="sbox"><div class="sl">{s.label}｜實際</div>'
            f'<div class="sv">{val(s, s.actual)}</div></div>'
            f'<div class="sbox"><div class="sl">預期</div>'
            f'<div class="sv">{val(s, s.expected)}</div></div>'
            f'<div class="sbox {cls}"><div class="sl">意外值</div>'
            f'<div class="sv">{val(s, s.diff, signed=True)}</div>{badge}</div>'
        )
    sources = sorted({s.source_label for s in items if s.expected is not None})
    return {"boxes": "".join(boxes), "notes": notes,
            "sources": "、".join(sources) or "無預期資料",
            "model_only": all(s.source == "model" for s in items if s.expected is not None),
            "has_any": any(s.expected is not None for s in items)}


def _passthrough_block(labor_series: dict, infl_series: dict) -> dict:
    """薪資 → 服務業通膨的傳導。缺任一邊就回傳空區塊，畫面上會說明原因。"""
    ahe = labor_series.get("CES0500000003") or []
    sc = infl_series.get("CUSR0000SASLE") or []
    if not ahe or not sc:
        return {"available": False,
                "reason": "需要同時有薪資與核心服務除住房的資料，目前缺其中一項。"}

    w = yoy_series(ahe)
    s = yoy_series(sc)
    p = pt.analyse(w, s)
    if p.best_lag is None:
        return {"available": False, "reason": p.note or "重疊樣本不足"}

    title, desc = pt.VERDICT_TEXT.get(p.verdict, ("—", ""))
    stats = [
        {"label": "平均時薪年增", "value": f"{p.wage_latest:.2f}%"},
        {"label": "核心服務除住房年增", "value": f"{p.supercore_latest:.2f}%"},
        {"label": "差距", "value": f"{p.gap:+.2f} 個百分點",
         "color": ("var(--serious)" if p.gap > 0.8 else
                   ("var(--series-1)" if p.gap < -0.8 else "inherit")),
         "note": title},
        {"label": "相關性最強的領先期數", "value": f"{p.best_lag} 個月",
         # 負相關要標紅：它是在反駁傳導機制，不是佐證
         "color": ("var(--critical)" if p.best_corr < -0.3 else "inherit"),
         "note": (f"相關係數 {p.best_corr:+.2f}"
                  + (f"（測試範圍 0–{p.max_lag_evaluated} 個月）"
                     if p.max_lag_evaluated is not None else ""))},
    ]

    # 兩條線疊圖：分別畫，避免雙軸（不同尺度硬放同一張圖會誤導）
    _pass_rows = since([{"date": r["date"], "value": r["wage"]} for r in p.series],
                       CHART_START, 12)
    _sc_rows = since([{"date": r["date"], "value": r["supercore"]} for r in p.series],
                     CHART_START, 12)
    wage_chart = charts.line_chart(_pass_rows, unit="%", height=120)
    sc_chart = charts.line_chart(_sc_rows, unit="%", height=120,
                                 color="var(--line-2)")

    lag_rows = "".join(
        f'<tr><td>{c["lag"]} 個月</td><td>{c["corr"]:+.2f}</td></tr>'
        for c in p.corr_by_lag
        if c["lag"] % 3 == 0 or c["lag"] == p.best_lag
    )

    return {"available": True, "stats": stats, "wage_chart": wage_chart,
            "sc_chart": sc_chart, "lag_rows": lag_rows, "note": p.note,
            "corr_note": p.corr_note,
            "verdict_title": title, "verdict_desc": desc}


# ===========================================================================
# 長端利率與債務供給（P5）
# ===========================================================================
def build_rates_context(cfg: dict, series: dict, failed: list, offline: bool,
                        real_growth: float | None = None) -> dict:
    from .analysis import rates as rt

    curve = rt.curve_state(series)
    real10 = (curve.decomposition or {}).get("real")
    debt = rt.debt_state(series, real_10y=real10, real_growth=real_growth or 1.8)
    hs = rt.hyperscalers(cfg.get("hyperscalers") or {},
                         (cfg.get("ig_market") or {}).get("quarterly_issuance"))
    ig_oas = value_at(series.get("BAMLC0A0CM") or [])
    press = rt.supply_pressure(curve, debt, hs, ig_oas)

    # ---- 燈號 ----
    computed = {}
    if curve.term_premium is not None:
        tp = series.get("THREEFYTP10") or []
        computed["term_premium"] = (curve.term_premium, value_at(tp, 1),
                                    f"{curve.term_premium:+.2f}%")
    if curve.slope_10_2 is not None:
        computed["curve_10_2"] = (curve.slope_10_2, None, f"{curve.slope_10_2:+.2f}%")
    if curve.slope_30_10 is not None:
        computed["curve_30_10"] = (curve.slope_30_10, None, f"{curve.slope_30_10:+.2f}%")
    if real10 is not None:
        computed["real_10y"] = (real10, None, f"{real10:.2f}%")
    be10 = value_at(series.get("T10YIE") or [])
    if be10 is not None:
        computed["breakeven_10y"] = (be10, None, f"{be10:.2f}%")
    if debt.interest_to_revenue is not None:
        computed["interest_to_revenue"] = (debt.interest_to_revenue, None,
                                           f"{debt.interest_to_revenue:.1f}%")
    if debt.r_minus_g is not None:
        computed["r_minus_g"] = (debt.r_minus_g, None, f"{debt.r_minus_g:+.2f}%")
    if ig_oas is not None:
        computed["ig_spread"] = (ig_oas, value_at(series.get("BAMLC0A0CM") or [], 1),
                                 f"{ig_oas:.2f}%")
    lights = _lights_from(computed, cfg.get("regime_lights") or [])

    # ---- 曲線 ----
    curve_stats = [
        {"label": f"{k} 期", "value": f"{v:.2f}%",
         "note": (f"近一個月 {curve.changes_1m[k]*100:+.0f} 基點"
                  if k in curve.changes_1m else "")}
        for k, v in curve.levels.items()
    ]
    # （曲線變化的長條圖已移除——與 curve_stats 每格附注的
    #   「近一個月 ±N 基點」完全重複，留一種呈現就好。）

    dec = curve.decomposition or {}
    decomp_stats = [
        {"label": "名目 10 年期", "value": f"{dec.get('nominal', 0):.2f}%"},
        {"label": "實質利率", "value": f"{dec.get('real', 0):.2f}%",
         "note": "抗通膨債券殖利率"},
        {"label": "通膨補償", "value": f"{dec.get('breakeven', 0):.2f}%",
         "note": "市場定價的平均通膨"},
        {"label": "期限溢酬", "value": (f"{curve.term_premium:+.2f}%"
                                        if curve.term_premium is not None else "—"),
         "color": ("var(--serious)" if (curve.term_premium or 0) > 0.6 else "inherit"),
         "note": "另一個角度的拆解，不可與上兩項相加"},
    ]

    # ---- 債務 ----
    debt_stats = [
        {"label": "債務佔 GDP", "value": (f"{debt.debt_gdp:.0f}%"
                                          if debt.debt_gdp else "—")},
        {"label": "利息佔稅收", "value": (f"{debt.interest_to_revenue:.1f}%"
                                          if debt.interest_to_revenue else "—"),
         "color": ("var(--critical)" if (debt.interest_to_revenue or 0) > 20
                   else "inherit"),
         "note": "每收 100 元稅拿去付利息的比例"},
        {"label": "當前缺口：有效利率 減 名目成長",
         "value": (f"{debt.i_minus_g:+.2f}%" if debt.i_minus_g is not None else "—"),
         "color": ("var(--critical)" if (debt.i_minus_g or -1) > 0 else "var(--good)"),
         "note": "已發行債務的平均利率；大於零時債務會自我累積"},
        {"label": "穩定債務所需基本盈餘",
         "value": (f"{debt.stabilizing_pb:+.2f}% GDP"
                   if debt.stabilizing_pb is not None else "—")},
        {"label": "實際基本盈餘",
         "value": (f"{debt.actual_pb:+.2f}% GDP"
                   if debt.actual_pb is not None else "—")},
        {"label": "財政缺口",
         "value": (f"{debt.pb_gap:+.2f}% GDP" if debt.pb_gap is not None else "—"),
         "color": ("var(--critical)" if (debt.pb_gap or 0) < -0.5 else "var(--good)"),
         "note": "實際與穩定水準的差距"},
    ]
    # 債務比是季資料，一年才四筆，min_points 放寬一點才有形狀。
    # 這也代表實際起點可能早於 CHART_START，所以期間要標出來。
    debt_rows = since(series.get("GFDEGDQ188S") or [], CHART_START, 6)
    debt_chart = charts.line_chart(
        debt_rows, unit="%", height=150, color="var(--line-2)")
    debt_span = span_label(debt_rows)

    # ---- Hyperscaler ----
    # 單位一律換算成「億美元」。原始財報是 billion，但中文語境讀 10 億／十億
    # 容易誤讀成十位數，而且在手機上會換行；統一乘以 10 寫成億。
    hs_stats = [
        {"label": "資本支出合計", "value": f"{hs.total_capex * 10:,.0f} 億美元",
         "note": f"年增 {hs.capex_yoy:+.0f}%" if hs.capex_yoy is not None else ""},
        {"label": "佔營運現金流",
         "value": (f"{hs.capex_to_ocf:.0f}%" if hs.capex_to_ocf else "—"),
         "color": ("var(--critical)" if (hs.capex_to_ocf or 0) > 100
                   else ("var(--serious)" if (hs.capex_to_ocf or 0) > 80 else "inherit")),
         "note": "超過 100% 代表自由現金流轉負"},
        {"label": "本季發債", "value": f"{hs.total_issued * 10:,.0f} 億美元",
         "note": (f"佔投資級發行 {hs.ig_share:.0f}%"
                  if hs.ig_share is not None else "")},
        {"label": "現金流轉負家數", "value": f"{hs.n_cash_negative} / {len(hs.companies)} 家"},
    ]

    credit_stats = []
    for sid, label in (("BAMLC0A0CM", "投資級利差"), ("BAMLC0A4CBBB", "BBB 級利差"),
                       ("BAMLH0A0HYM2", "高收益利差")):
        rows = series.get(sid) or []
        if rows:
            dv = (rows[-1]["value"] - rows[-23]["value"]) if len(rows) > 23 else None
            credit_stats.append({
                "label": label, "value": f"{rows[-1]['value']:.2f}%",
                "note": (f"近一個月 {dv*100:+.0f} 基點" if dv is not None else "")})
    credit_chart = charts.line_chart(
        since(series.get("BAMLC0A0CM") or [], CHART_START, 40), unit="%", height=140)

    as_of = (series.get("DGS10") or [{}])[-1].get("date", "")

    return {
        "release_name": (cfg.get("meta") or {}).get("release_name", "Rates"),
        "as_of": as_of,
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "offline": offline,
        "failed": failed,
        "curve": curve,
        "debt": debt,
        "hyperscalers": hs,
        "pressure": press,
        "pressure_text": rt.PRESSURE_TEXT.get(press.level, ("—", "")),
        "debt_text": rt.DEBT_VERDICT.get(debt.verdict, ("—", "")),
        "hs_text": rt.HS_VERDICT.get(hs.verdict, ("—", "")),
        "hs_source": (cfg.get("hyperscalers") or {}).get("source", ""),
        "lights": lights,
        "curve_stats": curve_stats,
        "decomp_stats": decomp_stats,
        "decomp_note": curve.note,
        "debt_stats": debt_stats,
        "debt_chart": debt_chart,
        "debt_span": debt_span,
        "debt_note": debt.note,
        "debt_divergence": debt.gap_divergence,
        "debt_growth_note": (
            f"r 減 g 的成長率用實質 GDP 年增 {debt.real_growth:.1f}%"
            if debt.real_growth is not None and not debt.real_growth_assumed
            else (f"取不到實質 GDP，r 減 g 的成長率暫用 {debt.real_growth:.1f}% 假設值"
                  if debt.real_growth is not None else "")),
        "hs_stats": hs_stats,
        "credit_stats": credit_stats,
        "credit_chart": credit_chart,
        "key_metrics": {
            "dgs10": {"label": "10 年期殖利率", "value": curve.levels.get("10Y"),
                      "unit": "%", "delta_unit": " 個百分點", "threshold": 0.05},
            "dgs30": {"label": "30 年期殖利率", "value": curve.levels.get("30Y"),
                      "unit": "%", "delta_unit": " 個百分點", "threshold": 0.05},
            "term_premium": {"label": "期限溢酬", "value": curve.term_premium,
                             "unit": "%", "delta_unit": " 個百分點", "threshold": 0.05},
            "ig_oas": {"label": "投資級利差", "value": ig_oas,
                       "unit": "%", "threshold": 0.05},
        },
    }
