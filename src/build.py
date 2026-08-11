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
        # 「值得注意」的原因要直接寫在標籤旁，不能只放在 hover 提示裡——
        # 手機沒有 hover，點下去什麼都不會發生。
        "notable_why": (f"相對自身歷史 {c.zscore:+.1f} 個標準差"
                        if c.notable and c.zscore is not None else None),
        "note": ("不受景氣影響" if c.noncyclical else None),
        "tip": (f"{c.label}｜{fmt.wan(c.value)}"
                + (f"｜相對自身歷史 {c.zscore:+.1f} 個標準差" if c.zscore is not None else "")),
    } for c in shown]
    if other_n:
        wf_items.append({"label": f"其他 {other_n} 個行業", "value": other_sum,
                         "muted": True, "note": "多個行業加總",
                         "tip": f"其餘 {other_n} 個行業合計 {fmt.wan(other_sum)}"})
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
    # 「佔總變動」改成「佔同向總額」：淨額只有 −2.3 萬時，用淨額當分母會
    # 讓正貢獻算出 −165%、最大的減項算出 +204%，所以原本整欄關掉、
    # 十七列都印同一句「總變動過小，比例失真」。改用同向總額當分母之後
    # 數字永遠成立，而且直接講出這個月真正的樣子：增減兩邊都很大、互相抵消。
    att_table = [
        {"label": c.label, "value": c.value,
         # 只寫百分比。方向由左邊「增減」欄的正負決定，
         # 再寫一次「佔增加的／佔減少的」會把欄寬撐爆、在手機上被截掉。
         "share": (f"{c.gross_share:.0f}%" if c.gross_share is not None else "—"),
         "own": (f"{c.own_pct:+.2f}%" if c.own_pct is not None else "—")}
        for c in att.contributions
    ]
    _gross = att.positive_sum + abs(att.negative_sum)
    att_gross = {
        "positive": att.positive_sum, "negative": att.negative_sum,
        "explained": att.positive_sum + att.negative_sum,
        "unexplained": att.unexplained,
        # 淨額遠小於毛額時要講出來——那代表「互相抵消」，
        # 不是「這個月沒事發生」，兩者的政策意涵完全不同。
        # 分母用毛額（增加＋減少的絕對值），不是只用增加的那一邊。
        "offsetting": (abs(att.total) < 0.35 * _gross) if _gross else False,
    }

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
                        # 長條的單位跟卡片上方的「全體合計 −2.3 萬人」一致。
                        # 先前長條寫「-47,000」、卡片寫「-2.3 萬人」，
                        # 同一張卡裡兩種單位，讀者要自己換算。
                        "bars": charts.diverging_bars(
                            wf_items, fmt=lambda v: fmt.wan(v, digits=1)),
                        "table": att_table,
                        "gross": att_gross,
                        "total_count": n_ind},
        "decomp": dec,
        "ustar": _ustar_gap(u3, series.get("NROU", [])),
        "claims": _claims_block(series),
        "unemp_structure": _unemp_structure(series),
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
        # 首頁也要用算出來的，不能各自寫死——先前首頁寫「約兩個月」、
        # 這裡算出來是 1 個月，同一份資料兩種說法
        "jolts_lag_text": f"JOLTS {jolts_lag_text}",
        "breakeven": _breakeven_block(bkev),
        "surprises": _surprise_block(surprises),
        "asof": {
            "labor": payems[-1]["date"] if payems else "",
            "jolts": (series.get("JTSJOL") or [{}])[-1].get("date", ""),
            "claims": (series.get("CCSA") or [{}])[-1].get("date", ""),
        },
        "mini": {
            # 單位一律抽到上方只寫一次：格子裡不重複，數字才不會互相疊。
            # 四張卡都要有這一列——只有一張有的話，那張卡的走勢圖與數值列
            # 會比另外三張高 21px，一整排看過去參差不齊。
            "nfp": charts.mini_series(nfp_chg_series, unit="萬人",
                                      fmt=lambda v: f"{v/10:+,.1f}"),
            "u3": charts.mini_series(u3, unit="%", fmt=lambda v: f"{v:.1f}"),
            "ahe": charts.mini_series(yoy_series(ahe), unit="%",
                                      fmt=lambda v: f"{v:.1f}"),
            "lfpr": charts.mini_series(lfpr, unit="%", fmt=lambda v: f"{v:.1f}"),
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


def _claims_block(series: dict) -> dict:
    """
    每週失業金申請。

    為什麼值得一個獨立區塊
    ----------------------
    這是整個模組裡**唯一的週頻資料**。就業報告一個月出一次，JOLTS 還要
    再落後一到兩個月；在兩次就業報告之間的四五週裡，初領與續領是唯一會
    更新的勞動市場訊號。先前它只以一盞紅綠燈與一條綜合分數的權重存在，
    等於把最即時的那條資料藏在最抽象的兩個地方。

    兩條的分工要講清楚，否則讀者會以為是同一件事的兩種說法：
      初領（ICSA）＝ 這週**新**失去工作的人 → 裁員的速度
      續領（CCSA）＝ 還在領補助的人 → 再就業的難度
    裁員沒增加但續領一直爬，是典型的「沒有人被裁、但被裁的人找不到工作」，
    那是勞動市場轉弱最早的形態之一，只看初領完全看不到。

    初領一律看四週移動平均：單週會被假期、罷工與州政府的行政作業
    甩出很大的雜訊，逐週解讀幾乎必然過度反應。
    """
    ic = series.get("ICSA") or []
    cc = series.get("CCSA") or []
    if len(ic) < 8 or len(cc) < 8:
        return {}

    def ma4(rows: list, back: int = 0) -> float | None:
        end = len(rows) - back
        if end < 4:
            return None
        return sum(r["value"] for r in rows[end - 4:end]) / 4

    # DOL 自己就發布四週移動平均（IC4WSA），優先用官方那條：
    # 它跟新聞稿引用的是同一個數字，自己算會因為修正時點不同而差幾百件，
    # 讀者拿去對照會以為我們算錯。抓不到才退回自己算。
    ic4 = series.get("IC4WSA") or []
    if len(ic4) >= 5:
        ic_ma, ic_ma_prev = value_at(ic4), value_at(ic4, 4)
        ma_source = "DOL 發布的四週移動平均（IC4WSA）"
    else:
        ic_ma, ic_ma_prev = ma4(ic), ma4(ic, 4)
        ma_source = "由每週初領件數自行計算的四週平均"
    cc_now, cc_prev = value_at(cc), value_at(cc, 4)

    # 「近一年的第幾百分位」比「較上週 ±N」有用得多：申請件數的絕對水準
    # 隨勞動力規模漂移，單週變化又幾乎都是雜訊，位置才是訊息。
    def pct_rank(rows: list, v: float | None, n: int = 52) -> int | None:
        if v is None or len(rows) < n:
            return None
        window = [r["value"] for r in rows[-n:]]
        return round(sum(1 for x in window if x < v) / len(window) * 100)

    stats = [
        {"label": "初領：四週移動平均", "value": fmt.persons_to_wan(ic_ma, digits=1)
         if ic_ma else "—",
         "note": (f"較四週前 {(ic_ma - ic_ma_prev) / ic_ma_prev * 100:+.1f}%"
                  if ic_ma and ic_ma_prev else "")},
        {"label": "續領：最新一週", "value": fmt.persons_to_wan(cc_now, digits=1)
         if cc_now else "—",
         "note": (f"較四週前 {(cc_now - cc_prev) / cc_prev * 100:+.1f}%"
                  if cc_now and cc_prev else "")},
    ]

    ic_rank, cc_rank = pct_rank(ic, ic_ma), pct_rank(cc, cc_now)
    verdict, lean = "—", "neutral"
    if ic_rank is not None and cc_rank is not None:
        if cc_rank >= 80 and ic_rank < 60:
            verdict = ("裁員沒有加速，但被裁的人找不到工作——"
                       "續領在近一年的高位，初領還在中段。"
                       "這是勞動市場轉弱最早出現的形態。")
            lean = "dovish"
        elif ic_rank >= 80 and cc_rank >= 80:
            verdict = "初領與續領同時在近一年高位，裁員與再就業兩邊都在惡化。"
            lean = "dovish"
        elif ic_rank <= 30 and cc_rank <= 30:
            verdict = "初領與續領都在近一年低位，勞動市場仍然緊。"
            lean = "hawkish"
        else:
            verdict = (f"初領位在近一年的第 {ic_rank} 百分位、"
                       f"續領第 {cc_rank} 百分位，都還在區間內。")

    # 失業持續期間中位數：申請件數講的是「多少人」，這條講的是「多久」。
    # 續領人數會被勞動力規模與補助資格變動影響，持續期間不會——
    # 兩條同時往上，再就業變難這件事才算被兩個獨立角度確認。
    med = series.get("UEMPMED") or []
    if len(med) >= 13:
        m_now, m_prev = value_at(med), value_at(med, 12)
        stats.append({
            "label": "失業持續期間中位數",
            "value": f"{m_now:.1f} 週" if m_now is not None else "—",
            "note": (f"較一年前 {m_now - m_prev:+.1f} 週"
                     if m_now is not None and m_prev is not None else "")})

    return {
        "stats": stats,
        "verdict": verdict,
        "lean": lean,
        "ma_source": ma_source,
        "as_of": ic[-1]["date"],
        "ic_rank": ic_rank, "cc_rank": cc_rank,
        # 圖畫續領：它比初領平滑，而且是「再就業難度」這條主線的載體
        "chart": charts.line_chart(
            [{"date": r["date"], "value": r["value"] / 10000}
             for r in cc[-104:]],
            unit=" 萬人", height=130, digits=1),
    }


def _unemp_structure(series: dict) -> dict:
    """
    失業結構：失業的人是怎麼變成失業的。

    為什麼重要
    ----------
    失業率上升 0.2 個百分點，可以是完全相反的兩件事：
      永久性失業者增加   → 企業真的在裁員，需求端在收縮
      重新進入／新進入者 → 有人被景氣吸引回來找工作，供給端在擴張
    後者伴隨的通常是勞動參與率同步上升，那是**好**的失業率上升。
    失業率的分解（就業效果 vs 勞動力效果）回答的是會計恆等式那一層，
    這裡回答的是行為那一層——同樣一個數字，成因不同則政策意涵相反。

    這一整組（七條 LNS 序列 ＋ 長期失業）先前一直有抓、卻沒有任何地方讀，
    等於白抓；而它回答的問題在這一頁其他地方也沒有人回答。

    分母用「合計」而不是總失業人數：CPS 的失業原因分類不完全互斥，
    幾條加起來跟 UNEMPLOY 對不齊，用總數當分母會讓佔比加總不等於 100%。
    """
    parts = [
        ("LNS13023621", "永久性失業", "bad",
         "被裁掉、沒有回聘承諾。需求端真的在收縮時，先漲的是這一條。"),
        ("LNS13026638", "暫時解雇", "bad",
         "有回聘承諾。通常反映的是短期的產能調整，不是結構性收縮。"),
        ("LNS13023653", "自願離職", "good",
         "主動辭職還沒找到下一份。這條要上升，人得對再就業有信心。"),
        ("LNS13023705", "重新進入", "good",
         "離開勞動力之後又回來找工作。景氣把人吸回來時會增加。"),
        ("LNS13023569", "新進入", "good",
         "第一次找工作。人口與畢業季的影響大於景氣。"),
    ]
    rows, total = [], 0.0
    for sid, label, kind, note in parts:
        rows_s = series.get(sid) or []
        if len(rows_s) < 13:
            continue
        cur, yr = value_at(rows_s), value_at(rows_s, 12)
        if cur is None:
            continue
        total += cur
        rows.append({"label": label, "kind": kind, "note": note,
                     "value": cur,
                     "yoy": (cur - yr) if yr is not None else None})
    if len(rows) < 4 or not total:
        return {}
    for r in rows:
        r["share"] = r["value"] / total * 100
        r["display"] = fmt.persons_to_wan(r["value"] * 1000, digits=1)
        r["yoy_display"] = ("—" if r["yoy"] is None
                            else fmt.wan(r["yoy"], digits=1))

    # 結論看的是**變化**不是水準：永久性失業長期就是最大的一塊，
    # 「它佔四成」本身不是訊息，「它是這一年增加最多的一塊」才是。
    bad_d = sum(r["yoy"] or 0 for r in rows if r["kind"] == "bad")
    good_d = sum(r["yoy"] or 0 for r in rows if r["kind"] == "good")
    if bad_d > 0 and bad_d > abs(good_d):
        verdict, lean = ("這一年的增量主要來自被裁掉的人——需求端在收縮，"
                         "是「壞」的失業率上升。"), "dovish"
    elif good_d > 0 and good_d > abs(bad_d):
        verdict, lean = ("這一年的增量主要來自重新進入與自願離職——"
                         "人是被景氣吸引回來找工作的，是「好」的失業率上升。"), "hawkish"
    elif bad_d < 0 and abs(bad_d) > abs(good_d):
        verdict, lean = "被裁掉的人減少，失業結構在改善。", "hawkish"
    else:
        verdict, lean = "各類別的變化互相抵消，結構沒有明顯方向。", "neutral"

    long_term = series.get("UEMP27OV") or []
    lt_note = ""
    if len(long_term) >= 13:
        lt_cur, lt_yr = value_at(long_term), value_at(long_term, 12)
        if lt_cur is not None:
            lt_note = (f"長期失業（27 週以上）{fmt.persons_to_wan(lt_cur * 1000, digits=1)}"
                       + (f"，較一年前 {fmt.wan(lt_cur - lt_yr, digits=1)}"
                          if lt_yr is not None else "") + "。")
    return {"rows": rows, "verdict": verdict, "lean": lean, "lt_note": lt_note}


def _ustar_gap(u3: list, nrou: list) -> dict:
    """
    失業缺口 u − u*：目前失業率離「不會加速通膨的失業率」多遠。

    為什麼值得單獨列一行
    --------------------
    「失業率 4.3%」本身沒有基準，讀者無從判斷那是緊還是鬆。
    u* 是 CBO 對長期自然失業率的估計，兩者相減才有方向：
      u < u*  → 勞動市場仍偏緊，薪資壓力偏上行 → 對聯準會是通膨那一側的理由
      u > u*  → 已經出現閒置，通常伴隨就業下行風險
    這也是聯準會自己在談雙重使命時的參照框架。

    NROU 本來就有抓（config/indicators.yaml 的 reference 段），
    但一直沒有任何地方讀它——量測到的東西沒被用上，等於白抓。

    注意 u* 是**季頻的模型估計值**，而且會被回溯修正；
    它不是觀測值，所以缺口只當方向參考，不拿去下門檻式的結論。
    """
    u_now, ustar_now = value_at(u3), value_at(nrou)
    if u_now is None or ustar_now is None:
        return {}
    gap = u_now - ustar_now
    # ±0.2 個百分點以內視為「差不多在 u* 上」：u* 的估計誤差本來就有這個量級，
    # 比它小的缺口拿來講鬆緊是過度解讀。
    if gap > 0.2:
        state, note = "鬆", "失業率高於自然失業率，勞動市場已經出現閒置。"
    elif gap < -0.2:
        state, note = "緊", "失業率低於自然失業率，勞動市場仍偏緊、薪資壓力偏上行。"
    else:
        state, note = "中性", "失業率大致就在自然失業率上，兩邊都不構成壓力。"
    return {
        "u": u_now, "ustar": ustar_now, "gap": gap, "state": state,
        "note": note,
        "as_of": (nrou[-1]["date"] if nrou else ""),
        "display": f"{gap:+.2f} 個百分點",
        "color": ("var(--critical)" if gap > 0.5 else
                  "var(--warning)" if gap < -0.5 else "inherit"),
    }


def _breakeven_block(b) -> dict:
    """損益兩平就業增速的畫面資料。"""
    label, note = be.VERDICT_TEXT.get(b.verdict, ("—", ""))
    # 缺口是這張卡的結論，人口成長與參與率只是算它的輸入。
    # 四格等大並排時，缺口排第三、輸入值佔掉一樣的版面，
    # 讀者的視線會先落在跟結論無關的數字上。
    stats = [
        {"label": "實際：非農三個月均", "value": fmt.wan(b.nfp_3m)},
        {"label": "需要：損益兩平", "value": fmt.wan(b.monthly),
         "note": "維持失業率不變所需的每月就業增加"},
    ]
    tol = b.tolerance or 25.0
    gap_color = ("var(--critical)" if (b.gap or 0) < -tol else
                 ("var(--good)" if (b.gap or 0) > tol else "var(--text-primary)"))
    inputs = (f"每月人口成長 {fmt.wan(b.pop_growth)}"
              + (f"　·　參與率 {b.participation:.1f}%" if b.participation else "")
              + f"　·　判定容差 ±{tol/10:,.1f} 萬人")
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
            "gap_display": fmt.wan(b.gap), "gap_color": gap_color,
            "inputs": inputs,
            "monthly": b.monthly, "gap": b.gap}


# ===========================================================================
# 通膨模組（P2）
# ===========================================================================
# 聯準會的目標是核心 PCE 年增 2%。這是整個通膨頁唯一的硬錨——
# 其他數字都要回答「離這個目標還有多遠、往哪邊走」。
PCE_TARGET = 2.0


def build_inflation_context(cfg: dict, series: dict, failed: list,
                            offline: bool,
                            labor_series: dict | None = None,
                            consensus: dict | None = None) -> dict:
    comp_meta = cfg.get("cpi_components") or []
    headline = series.get("CPIAUCSL", [])
    data_month = headline[-1]["date"][:7] if headline else "—"

    summ = infl_an.summarize(series, comp_meta)

    # ---- 意外值 ----
    # 只用手動填入的預期，不退回模型外推（見 surprise.evaluate 的 allow_model）。
    exp = ((consensus or {}).get("expectations") or {}).get(data_month) or {}
    cpi_surprises = [
        sp.evaluate("CPI 年增率", yoy_series(headline),
                    exp.get("CPIAUCSL_YOY"),
                    "manual" if exp.get("CPIAUCSL_YOY") is not None else "none",
                    unit="%", higher_is_better=False, allow_model=False),
        sp.evaluate("核心 CPI 年增率", yoy_series(series.get("CPILFESL", [])),
                    exp.get("CPILFESL_YOY"),
                    "manual" if exp.get("CPILFESL_YOY") is not None else "none",
                    unit="%", higher_is_better=False, allow_model=False),
    ]

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
        "headline_sub": ((f"近三個月年化 {_pct(annualized(headline, 3))}"
                          + (f"　·　離 2% 目標 {summ.headline_yoy - PCE_TARGET:+.1f} 個百分點"
                             if summ.headline_yoy is not None else ""))
                         if headline else ""),
        "headline_plain": (
            f"你買的東西平均比一年前貴 {summ.headline_yoy:.1f}%。"
            "這個數字包含食物和能源，所以起伏會比較大。"
            if summ.headline_yoy is not None else "—"),
        "headline_spark": rate_spark("CPIAUCSL"),

        "core_display": _pct(summ.core_yoy),
        # 四張 KPI 的副標統一成「短期動能 · 離目標」兩段，每張都回答
        # 同一組問題：現在跑多快、離 2% 還差多遠。原本四張各講各的
        # （一張講三月年化、一張講三月＋六月＋圖說、一張講目標、一張講密大），
        # 讀者每讀一張就要重新找節奏。
        "core_sub": (f"近三個月年化 {_pct(summ.core_3m)}　·　"
                     + (f"離 2% 目標 {summ.core_yoy - PCE_TARGET:+.1f} 個百分點"
                        if summ.core_yoy is not None else "")),
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
        # 這一張是聯準會真正盯的指標，副標維持同一組結構
        "pce_sub": ((f"近三個月年化 {_pct(summ.pce_core_3m)}　·　"
                     if summ.pce_core_3m is not None else "")
                    + (f"離 2% 目標 {summ.pce_core_yoy - PCE_TARGET:+.1f} 個百分點"
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
        # 預期沒有「三個月年化」，短期動能那一段改用密大 1 年預期，
        # 但第二段同樣是「離 2% 多遠」，四張卡的節奏一致
        "exp_sub": (f"密大 1 年預期 {_pct(summ.expect_1y)}　·　"
                    + (f"離 2% 目標 {summ.expect_5y5y - PCE_TARGET:+.2f} 個百分點"
                       if summ.expect_5y5y is not None else "")),
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
    # 漲幅（%）與貢獻（個百分點）是兩種東西，先前四格等權並排、
    # 長得一模一樣，讀者分不出哪個是總數哪個是其中一塊。
    # 改成「總數在上、三塊分項在下、相加等於總數」的分解結構。
    _shelter = agg.get("shelter", 0) or 0
    _food_energy = agg.get("food_energy", 0) or 0
    _rest = att.total - _shelter - _food_energy
    infl_parts = [
        {"label": "住房", "value": _shelter, "note": "算法落後市場行情約一年"},
        {"label": "食物與能源", "value": _food_energy, "note": "波動大，核心已剔除"},
        {"label": "其他所有項目", "value": _rest, "note": "核心裡的非住房部分"},
    ]
    att_stats = [
        # 這裡是三個月的**累計**漲幅，不是年化——attribute_cpi 走的是
        # _pct_change（cur/old − 1），沒有做 **4。標成「年化」會跟同一頁
        # KPI 卡上的「近三個月年化 4.2%」打架（1.0103⁴ = 1.042，同一件事的兩種口徑）。
        {"label": "近三個月累計漲幅", "value": f"{att.total:+.2f}%",
         "note": f"換算年率約 {((1 + att.total / 100) ** 4 - 1) * 100:+.1f}%"},
        {"label": "剔除住房後",
         "value": (f"{agg['ex_shelter']:+.2f}%"
                   if agg.get("ex_shelter") is not None else "—"),
         "color": ("var(--good)"
                   if (agg.get("ex_shelter") or 9) < 0.6 else "inherit"),
         "note": "已按剩餘權重換算回通膨率"},
    ]
    # 「剔除住房後比含住房高」是每期都可能出現、而且每次都會被誤讀成
    # 算錯的一件事。它的意思是住房正在把整體往下拉——那是重要訊息，
    # 不是錯誤，所以直接寫成一句話。
    shelter_note = ""
    _ex = agg.get("ex_shelter")
    if _ex is not None and att.total is not None:
        _sw = agg.get("shelter_weight")
        _srate = (_shelter / (_sw / 100)) if _sw else None
        if _ex > att.total + 0.02:
            shelter_note = (
                f"剔除住房後（{_ex:+.2f}%）比含住房（{att.total:+.2f}%）**高**，"
                "代表住房正在把整體通膨往下拉"
                + (f"——住房自己只漲 {_srate:+.2f}%，低於非住房的 {_ex:+.2f}%。"
                   if _srate is not None else "。")
                + "住房佔籃子三分之一以上，而它的算法落後市場行情約一年，"
                "所以這條下拉力量還會延續一段時間。")
        elif _ex < att.total - 0.02:
            shelter_note = (
                f"剔除住房後（{_ex:+.2f}%）比含住房（{att.total:+.2f}%）**低**，"
                "代表目前的通膨有一部分是住房撐起來的。"
                "住房的算法落後市場行情約一年，這一塊之後會自然回落。")

    # ---- 趨勢型指標 ----
    trend_rows, _trend_vals = [], []
    for sid, label, note in [
        ("MEDCPIM159SFRBCLE", "中位數 CPI", "取漲幅正中間的項目，不受極端值影響"),
        ("TRMMEANCPIM159SFRBCLE", "截尾平均 CPI", "剔除漲跌最極端的項目後平均"),
        ("CORESTICKM159SFRBATL", "黏性核心 CPI", "只看價格很少調整的項目，代表通膨慣性"),
    ]:
        v = value_at(series.get(sid, []))
        if v is not None:
            trend_rows.append({"label": label, "value": f"{v:.1f}%", "note": note})
            _trend_vals.append(v)

    # 這張卡的存在意義就是回答一個問題：這波通膨是少數項目造成的，
    # 還是全面性的？三個指標都貼著核心 CPI＝全面性；明顯低於核心＝
    # 少數項目在拉高。先前只列三個數字、不做這個比較，讀者拿不到結論。
    trend_verdict = {}
    if _trend_vals and summ.core_yoy is not None:
        lo, hi = min(_trend_vals), max(_trend_vals)
        mid = sum(_trend_vals) / len(_trend_vals)
        gap = mid - summ.core_yoy
        if abs(gap) <= 0.3:
            title = "價格上漲是全面性的"
            desc = ("剔除極端值後的三個指標都貼著核心 CPI"
                    f"（{lo:.1f}–{hi:.1f}% vs 核心 {summ.core_yoy:.1f}%），"
                    "代表這波不是少數項目暴漲拉高平均，而是普遍在漲。"
                    "全面性的通膨比較黏，單靠某幾項回落解決不了。")
            kind = "hawkish"
        elif gap < -0.3:
            title = "漲幅集中在少數項目"
            desc = (f"剔除極端值後只剩 {mid:.1f}%，明顯低於核心 CPI "
                    f"{summ.core_yoy:.1f}%，代表平均被少數暴漲的項目拉高。"
                    "這種通膨通常比較快回落。")
            kind = "dovish"
        else:
            title = "多數項目漲得比平均更兇"
            desc = (f"剔除極端值後反而是 {mid:.1f}%，高於核心 CPI "
                    f"{summ.core_yoy:.1f}%，代表平均被少數下跌的項目壓低，"
                    "底層的漲勢比表面數字更廣。")
            kind = "hawkish"
        trend_verdict = {"title": title, "desc": desc, "kind": kind}

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
    # 「對核心 CPI 的影響：無」是定義不是數據（核心本來就剔除能源），
    # 佔掉一整格會把真正的結論「對總體的估計影響」擠到第三順位。
    # 降成卡片下方的一句話。
    energy_core_note = ("能源不進核心 CPI——核心的定義就是剔除食物與能源，"
                        "所以油價漲跌不會直接改變核心的數字。")
    energy_headline = {}
    if summ.oil_1m is not None:
        est = summ.oil_1m * 0.062 * 0.4
        energy_headline = {
            "value": f"{est:+.2f} 個百分點",
            "color": ("var(--serious)" if est > 0.05 else
                      ("var(--series-1)" if est < -0.05 else "var(--text-primary)")),
            "note": "以能源佔比 6.2% 與傳導係數 0.4 粗估",
        }

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
            # 長條上的單位省略「個百分點」——每一列都寫一次會把標籤擠掉，
            # 圖例已經標明單位了
            "bars": charts.diverging_bars(items, fmt=lambda v: f"{v:+.2f}"),
            "parts": infl_parts,
            "total": att.total,
            "shelter_note": shelter_note,
        },
        # 離目標多遠：整個通膨頁唯一的硬錨，放進結論卡
        "target": {
            "value": summ.pce_core_yoy,
            "target": PCE_TARGET,
            "gap": (summ.pce_core_yoy - PCE_TARGET
                    if summ.pce_core_yoy is not None else None),
            "momentum": summ.pce_core_3m,
            "label": "核心 PCE 年增",
        },
        "surprises": _surprise_block(cpi_surprises),
        "trend_rows": trend_rows,
        "trend_verdict": trend_verdict,
        "energy_stats": energy_stats,
        "energy_headline": energy_headline,
        "energy_core_note": energy_core_note,
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
                                           unit="%", fmt=lambda v: f"{v:.1f}"),
            "core": charts.mini_series(yoy_series(series.get("CPILFESL", [])),
                                       unit="%", fmt=lambda v: f"{v:.1f}"),
            "pce": charts.mini_series(yoy_series(series.get("PCEPILFE", [])),
                                      unit="%", fmt=lambda v: f"{v:.1f}"),
            # 日頻序列：從最新一筆往回每 7 個交易日取一點（[::7] 從頭取
            # 會讓最後一格不是最新值），並標到「月/日」避免三格都寫同一個月
            "exp": charts.mini_series(
                since(series.get("T5YIFR", []), CHART_START, 40)[::-1][::7][::-1],
                unit="%", fmt=lambda v: f"{v:.2f}", daily=True),
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
                       failed: list, offline: bool,
                       upcoming: list | None = None,
                       rates_series: dict | None = None) -> dict:
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

    # ---- 下次會議 ----
    # 「距離下次會議還有幾天」決定了這份聲明還會主導市場多久，
    # 是這一頁最該有的一個數字。解析失敗時整區不顯示（見 upcoming_meetings）。
    next_meeting = {}
    if upcoming:
        nxt = upcoming[0]
        days = (nxt - dt.date.today()).days
        next_meeting = {
            "date": nxt.isoformat(),
            "days": days,
            "display": f"{days} 天後",
            "sub": nxt.strftime("%Y-%m-%d"),
            "later": [d.isoformat() for d in upcoming[1:]],
        }

    # ---- 市場定價 vs 聯準會 ----
    # 2 年期公債殖利率 ≈ 市場預期未來兩年的平均政策利率。
    # 它跟目前政策利率中值的差，就是市場定價的政策路徑方向。
    # 這是粗略代理，不是會議層級的機率——畫面上會講清楚。
    market = {}
    _lo, _hi = rate_cfg.get("lower"), rate_cfg.get("upper")
    _d2 = value_at((rates_series or {}).get("DGS2") or [])
    if _lo is not None and _hi is not None and _d2 is not None:
        mid = (_lo + _hi) / 2
        gap = _d2 - mid
        if gap > 0.15:
            lean, txt = "hawkish", "市場定價未來兩年的平均政策利率高於現在——偏向再緊縮"
        elif gap < -0.15:
            lean, txt = "dovish", "市場定價未來兩年的平均政策利率低於現在——偏向降息"
        else:
            lean, txt = "neutral", "市場定價未來兩年的平均政策利率與現在相當——沒有明顯方向"
        # 判讀與市場一致與否，本身就是有價值的資訊
        obj_dir = ("hawkish" if latest.objective_score > 1.0
                   else ("dovish" if latest.objective_score < -1.0 else "neutral"))
        market = {
            "dgs2": _d2, "mid": mid, "gap": gap, "lean": lean, "text": txt,
            "display": f"{gap:+.2f} 個百分點",
            "agree": (lean == obj_dir),
            "obj_dir": obj_dir,
        }

    # ---- 反對票的歷史脈絡 ----
    # 「本次 3 票」單看沒有意義，要知道這在近期算不算多。
    _dis = [len((d.vote or {}).get("dissents") or []) for d in docs]
    dissent_ctx = {}
    if len(_dis) >= 3:
        cur, hist = _dis[-1], _dis[:-1]
        avg = sum(hist) / len(hist)
        if cur > max(hist):
            note = f"是這 {len(_dis)} 次會議裡最多的一次"
        elif cur == 0:
            note = "本次全體一致，近期少見的完全共識" if avg >= 1 else "本次全體一致"
        elif cur > avg + 0.5:
            note = f"高於近 {len(hist)} 次的平均 {avg:.1f} 票"
        elif cur < avg - 0.5:
            note = f"低於近 {len(hist)} 次的平均 {avg:.1f} 票"
        else:
            note = f"與近 {len(hist)} 次的平均 {avg:.1f} 票相當，不算特別"
        dissent_ctx = {"current": cur, "avg": avg, "note": note,
                       "history": _dis}

    # ---- 聲明的穩定度 ----
    # 「只改了 1 句」本身是強訊號（立場穩定），先前只在卡片底部一行小字帶過。
    stability = {}
    if prev is not None:
        n_changed = len(changed)
        if n_changed == 0:
            stability = {"kind": "neutral", "title": "聲明一字未改",
                         "desc": "與上次完全相同。委員會的官方立場沒有任何調整。"}
        elif n_changed <= 2:
            stability = {"kind": "neutral", "title": f"聲明只改了 {n_changed} 處",
                         "desc": "改動極少，代表立場高度穩定——"
                                 "真正的轉向通常會伴隨多處措辭調整。"
                                 "在這種情況下，那少數幾處改動反而值得逐字看。"}
        else:
            stability = {"kind": "hawkish", "title": f"聲明改了 {n_changed} 處",
                         "desc": "改動不少。多處同時調整通常代表委員會正在"
                                 "重新描述經濟狀況或政策方向，值得逐句比對。"}

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
        "next_meeting": next_meeting,
        "market": market,
        "dissent_ctx": dissent_ctx,
        "stability": stability,
        "obj_detail": "；".join(x for x in (obj.get("action_detail"),
                                           obj.get("dissent_detail"),
                                           obj.get("risk_detail")) if x),
        "obj_has_signal": obj.get("has_signal", False),
        "obj_parts": obj,
        # 歷次客觀訊號分數，給 KPI 卡的走勢縮圖用
        "objective_history": [x.objective_score for x in docs],
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


def _offerings_block(offerings: list, hs) -> dict:
    """
    近期發債申報的畫面資料。

    這一段的用途是**時效**，不是計分：季報最久落後 135 天，
    而發債當天就要申報。所以它回答的是「下一期的數字會往哪邊走」，
    刻意不動供給壓力分數——否則同一筆發債下一季會被算第二次，
    歷史可比性也會斷掉。
    """
    if not offerings:
        return {"available": False}

    # 只有解析到金額的才加總，並標明有幾筆沒解析到，
    # 免得讀者把「已知金額合計」誤讀成「全部發債合計」。
    known = [o for o in offerings if o.get("amount") is not None]
    unknown_n = len(offerings) - len(known)
    total = sum(o["amount"] for o in known)

    # 跟最新一季的申報值比，讀者才知道這批新申報的量級
    ref = hs.total_issued or 0
    ratio = (total / ref * 100) if ref and total else None

    rows = []
    for o in offerings:
        amt = ("—" if o.get("amount") is None
               else f'{o["amount"] * 10:,.0f} 億美元')
        # 表格類型對一般讀者沒有意義，翻成在講什麼
        kind = {"424B2": "債券發行說明書", "424B5": "債券發行說明書",
                "424B3": "債券發行說明書", "FWP": "發行條件清單",
                "8-K": "重大事件公告"}.get(o["form"], o["form"])
        rows.append({"name": o["name"], "date": o["date"], "form": o["form"],
                     "kind": kind, "amount": amt, "url": o.get("doc_url", ""),
                     "items": o.get("items", "")})

    latest = offerings[0]["date"]
    return {
        "available": True,
        "rows": rows,
        "count": len(offerings),
        "known_n": len(known),
        "unknown_n": unknown_n,
        "total_display": (f"{total * 10:,.0f} 億美元" if total else "—"),
        "ratio_display": (f"{ratio:.0f}%" if ratio is not None else ""),
        "latest": latest,
        "ref_display": f"{ref * 10:,.0f} 億美元" if ref else "—",
    }


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
    # 三張格子都送出去：讀者可以切去看「若重心翻轉會怎樣」，
    # 那正是這一頁最有價值的反事實問題。
    cur = (sc.labor_state, sc.infl_state)
    grids = {r: scenario.grid_cells(r, cur) for r in scenario.REGIMES}
    cells = grids[sc.regime]

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
        "grids": grids,
        "regime_meta": [
            {"key": r, "label": scenario.REGIME_LABEL[r],
             "rule": scenario.REGIME_RULE[r],
             "current": r == sc.regime,
             # 讀者最在意的是「切過去之後我這一格會變成什麼」
             "cell_name": scenario.grid_for(r)[cur][0],
             "cell_lean": scenario.grid_for(r)[cur][2]}
            for r in scenario.REGIMES],
        "cell_is_conflict": cur in scenario.CONFLICT_CELLS,
        "rates_line": rates_line,
        # 市場定價：由 FOMC 模組算好（2 年期殖利率 vs 政策利率中值）。
        # 情境頁那張「尚未接入」的空卡就是為了這個留的位置。
        "market": (fomc_ctx or {}).get("market") or {},
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
    # 併進 KPI 卡用的精簡版：一行「預期 X｜意外 Y（判定）」。
    # 意外值本來是獨立一整張卡，但它跟 KPI 講的是同兩個數字，
    # 分成兩塊會逼讀者自己把「−2.3 萬」和「預期 +8.7 萬」對起來。
    inline = {}
    for s in items:
        if s.expected is None:
            continue
        key = {"非農就業月變動": "nfp", "失業率": "u3",
               "CPI 年增率": "headline", "核心 CPI 年增率": "core"}.get(s.label)
        if not key:
            continue
        inline[key] = {
            "expected": val(s, s.expected),
            "diff": val(s, s.diff, signed=True),
            "verdict": VERDICT_TEXT.get(s.verdict, ""),
            "kind": {"beat": "beat", "miss": "miss"}.get(s.verdict, "inline"),
            "z": (f"偏離 {abs(s.z):.1f} 個標準差" if s.z is not None else ""),
            # 來源不能省。模型推估與市場共識的交易意涵不同，
            # 縮成一行之後更需要標，否則讀者會直接當成市場預期。
            "source": s.source_label,
            "is_model": s.source == "model",
        }

    sources = sorted({s.source_label for s in items if s.expected is not None})
    return {"boxes": "".join(boxes), "notes": notes, "inline": inline,
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
    ]
    # 相關性是負的時候，「領先 6 個月」不該掛在最上面當結論——
    # 下方的但書正在說這個數字不能用來佐證傳導機制，
    # 把它放在頭條等於一邊叫讀者別信、一邊把它放在最顯眼的位置。
    # 這種情況改放進折疊區，跟完整的相關係數表擺在一起。
    if p.best_corr >= -0.3:
        stats.append({
            "label": "相關性最強的領先期數", "value": f"{p.best_lag} 個月",
            "note": (f"相關係數 {p.best_corr:+.2f}"
                     + (f"（測試範圍 0–{p.max_lag_evaluated} 個月）"
                        if p.max_lag_evaluated is not None else ""))})

    # 用僱用成本指數（ECI）交叉檢查平均時薪。
    #
    # 平均時薪有**組成偏誤**：低薪職位大量消失時，剩下的人平均薪資會被拉高，
    # 看起來像加薪，其實只是分母換了一批人——這一頁自己在別處就這樣寫。
    # 既然如此，傳導分析拿平均時薪當唯一的薪資來源就自相矛盾。
    # ECI 固定職業與產業權重，正是為了消掉這個偏誤，也是聯準會談薪資壓力時
    # 引用的那一條。它是季頻、落後約一個月，所以不取代平均時薪當主線，
    # 而是擺在旁邊當佐證：兩條同向才算數，背離時要以 ECI 為準。
    # ECI 是**季頻**，年增要退四期不是十二期。用預設的 periods=12
    # 會算出三年的累積漲幅（3.6% → 11.2%），而且外觀完全合理，
    # 只是數字大得離譜——這種錯不會拋例外，只會靜靜地印錯。
    eci = labor_series.get("ECIALLCIV") or []
    eci_yoy = yoy_series(eci, periods=4) if len(eci) > 4 else []
    if eci_yoy:
        e_now = eci_yoy[-1]["value"]
        _div = abs(e_now - p.wage_latest) > 0.7
        stats.insert(1, {
            "label": "僱用成本指數年增（ECI）",
            "value": f"{e_now:.2f}%",
            "color": "var(--serious)" if _div else "inherit",
            "note": ("與平均時薪背離超過 0.7 個百分點，以 ECI 為準"
                     if _div else "固定職業權重，沒有組成偏誤")})
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
            "best_lag": p.best_lag, "best_corr": p.best_corr,
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
    _hs_cfg = cfg.get("hyperscalers") or {}
    hs = rt.hyperscalers(_hs_cfg,
                         (cfg.get("ig_market") or {}).get("quarterly_issuance"))
    # 近期發債申報：補季報 45–135 天的時效缺口。刻意不進供給壓力分數。
    offerings = _hs_cfg.get("offerings") or []
    ig_oas = value_at(series.get("BAMLC0A0CM") or [])
    qt = rt.fed_holdings_pace(series)
    press = rt.supply_pressure(curve, debt, hs, ig_oas, qt_monthly=qt)

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
    # 這一頁講的是長端，3M／2Y／5Y 對供給壓力沒有直接作用。
    # 主線只留 10Y、30Y 與 30−10 斜率，短天期收進摺疊（資料一筆不掉）。
    _LONG = ("10Y", "30Y")
    def _tenor(k, v):
        return {"label": f"{k} 期", "value": f"{v:.2f}%",
                "note": (f"近一個月 {curve.changes_1m[k]*100:+.0f} 基點"
                         if k in curve.changes_1m else "")}
    # 30−10 斜率不放這裡：它已經在「壓力已經反映多少」那一區列過，
    # 同一張卡裡出現兩次會被當成兩個不同的東西。
    curve_stats = [_tenor(k, v) for k, v in curve.levels.items() if k in _LONG]
    curve_short = [_tenor(k, v) for k, v in curve.levels.items() if k not in _LONG]
    # （曲線變化的長條圖已移除——與 curve_stats 每格附注的
    #   「近一個月 ±N 基點」完全重複，留一種呈現就好。）

    dec = curve.decomposition or {}
    # 「名目 10 年期」已經在上方的曲線卡出現過，這裡不重複列——
    # 同一個數字在同一頁出現兩次，讀者會以為是兩個不同的東西。
    decomp_stats = [
        {"label": "實質利率", "value": f"{dec.get('real', 0):.2f}%",
         "note": "抗通膨債券殖利率。反映預期的實質報酬"},
        {"label": "通膨補償", "value": f"{dec.get('breakeven', 0):.2f}%",
         "note": "市場定價的平均通膨。這一段是聯準會的責任範圍"},
    ]
    # 期限溢酬是這一頁的主角：只有它是供需造成的，也只有它聯準會壓不下來。
    # 所以獨立出來，不跟另外兩段並排成三個等大的格子。
    decomp_head = {}
    if curve.term_premium is not None:
        decomp_head = {
            "value": f"{curve.term_premium:+.2f}%",
            "nominal": f"{dec.get('nominal', 0):.2f}%",
            "color": ("var(--serious)" if curve.term_premium > 0.6 else
                      ("var(--series-1)" if curve.term_premium < 0.2 else
                       "var(--text-primary)")),
            "change": (f"近三個月 {curve.tp_change_3m*100:+.0f} 基點"
                       if curve.tp_change_3m is not None else ""),
        }

    # ---- 債務 ----
    debt_stats = [
        {"label": "債務佔 GDP", "value": (f"{debt.debt_gdp:.0f}%"
                                          if debt.debt_gdp else "—")},
        {"label": "利息佔稅收", "value": (f"{debt.interest_to_revenue:.1f}%"
                                          if debt.interest_to_revenue else "—"),
         "color": ("var(--critical)" if (debt.interest_to_revenue or 0) > 20
                   else "inherit"),
         "note": "每收 100 元稅拿去付利息的比例"},
        # i 與 g 兩個被減數本身要看得到。先前只印差值，讀者無從判斷
        # 「+0.35%」是利率太高還是成長太慢——這兩件事的政策意涵完全不同，
        # 而兩個數字都已經算出來了，只是沒有印出來。
        {"label": "當前缺口：有效利率 減 名目成長",
         "value": (f"{debt.i_minus_g:+.2f}%" if debt.i_minus_g is not None else "—"),
         "color": ("var(--critical)" if (debt.i_minus_g or -1) > 0 else "var(--good)"),
         "note": (
             (f"有效利率 {debt.effective_rate:.2f}% － 名目成長 "
              f"{debt.nominal_growth:.2f}%。"
              if debt.effective_rate is not None
              and debt.nominal_growth is not None else "")
             + "大於零時債務會自我累積")},
    ]
    # 「穩定所需 −1.88」「實際 −3.16」「缺口 −1.28」是同一條算式的三個中間值，
    # 只有缺口是結論。三個並排成等大的格子會讓讀者以為是三件事。
    debt_steps = [
        {"label": "穩定債務所需的基本盈餘",
         "value": (f"{debt.stabilizing_pb:+.2f}% GDP"
                   if debt.stabilizing_pb is not None else "—")},
        {"label": "實際基本盈餘",
         "value": (f"{debt.actual_pb:+.2f}% GDP"
                   if debt.actual_pb is not None else "—")},
    ]
    debt_gap = {}
    if debt.pb_gap is not None:
        debt_gap = {
            "value": f"{debt.pb_gap:+.2f}% GDP",
            "color": ("var(--critical)" if debt.pb_gap < -0.5 else "var(--good)"),
            "note": "實際與穩定水準的差距＝財政問題的規模",
        }
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

    # ---- 誰在發債：把政府與科技巨頭放進同一個尺度 ----
    # 這是整頁的關鍵連結。政府發公債、科技巨頭發投資級公司債，
    # 兩者競爭的是同一批固定收益買盤（退休基金、保險、外資）。
    # 先前三塊各自獨立成卡，這句話一個字都沒出現，讀者只能自己猜
    # 它們為什麼被放在同一頁。
    supply_side = {}
    _gdp = value_at(series.get("GDP") or [])
    if _gdp and debt.deficit_gdp is not None:
        gov_yr = abs(debt.deficit_gdp) / 100 * _gdp * 10        # 十億 → 億美元
        # 科技巨頭是單季申報值年化。發債是機會式的（趁市場好的時候一次發），
        # 不是每季均勻，所以年化只是量級對照，畫面上會標明。
        hs_yr = hs.total_issued * 40 if hs.total_issued else None
        supply_side = {
            "gov_year": gov_yr,
            "gov_display": f"{gov_yr/10000:,.2f} 兆美元",
            "gov_note": f"財政赤字 {abs(debt.deficit_gdp):.1f}% GDP，需靠淨發行公債填補",
            "hs_year": hs_yr,
            "hs_display": (f"{hs_yr:,.0f} 億美元" if hs_yr else "—"),
            "hs_note": (f"本季 {hs.total_issued*10:,.0f} 億美元年化"
                        + (f"，佔投資級發行 {hs.ig_share:.0f}%"
                           if hs.ig_share is not None else "")),
            "ratio": (hs_yr / gov_yr * 100 if hs_yr and gov_yr else None),
        }
        if supply_side["ratio"] is not None:
            supply_side["ratio_display"] = f"{supply_side['ratio']:.0f}%"
            supply_side["summary"] = (
                f"科技巨頭的發債規模約是政府年赤字的 "
                f"{supply_side['ratio']:.0f}%。單看比例不大，但方向是關鍵："
                "政府的赤字是結構性的、短期不會消失，而科技巨頭是"
                "**新增**的供給——過去它們是淨買方（帳上現金多到要買公債），"
                "現在轉成淨賣方。同一批買盤要同時吃下兩邊的新增量，"
                "價格（期限溢酬）就是這樣被推上去的。")

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
        "curve_short": curve_short,
        "decomp_stats": decomp_stats,
        "decomp_head": decomp_head,
        "debt_steps": debt_steps,
        "debt_gap": debt_gap,
        "supply_side": supply_side,
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
        "offerings": _offerings_block(offerings, hs),
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
