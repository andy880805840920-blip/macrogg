"""
各模組的「資料 → 畫面用結構」轉換層。

一個模組 = 一個 build_*_context()，輸入原始序列，輸出畫面需要的字典。
分析邏輯在 src/analysis/，版面在 src/pages/，這裡只負責把兩邊接起來。

新增模組時只要在這裡加一個 build_*_context()，
再到 src/pages/ 加一個對應的頁面產生器即可。
"""

from __future__ import annotations

import logging

from . import charts, fmt, clock
from .analysis import (attribution, regime, revisions, rules,
                       inflation as infl_an, rules_inflation, fomc_text,
                       scenario, breakeven as be, surprise as sp,
                       passthrough as pt)
from .analysis.core import (diff_series, moving_avg, value_at, yoy, diff,
                           annualized, yoy_series, annualized_series,
                           since, span_label)

# 全站圖表的顯示起點。資料本身可能抓得更早（統計量需要），
# 但畫出來的一律從這裡開始，讓所有圖表的時間軸一致。
log = logging.getLogger(__name__)

CHART_START = "2025-01-01"



# ---------------------------------------------------------------------------
# 「上一期」的重算工具
#
# 都長成「把序列的最後一筆砍掉，再用完全相同的函式算一次」。
# 重點在**同一條程式路徑**：只要跟本期共用同一個函式，口徑就一定一致，
# 不會出現「本期用新演算法、上期用舊演算法」那種假變動。
# ---------------------------------------------------------------------------
def _kpi_leans(level: float | None, target: float | None,
               cur: float | None, prev: float | None,
               up_is: str = "hawkish", band: float = 0.05,
               level_word: tuple[str, str, str] = ("高於目標", "接近目標",
                                                   "低於目標")) -> list:
    """
    一張 KPI 卡的兩個鷹鴿標籤：**水準**一個、**本期變化**一個。

    為什麼一定要分開：同一張卡可以同時是「仍高於目標」（利升息）與
    「本期在降」（利降息），兩件事都成立。擠進一個標籤就得二選一，
    而選哪一個都會讓另一半的資訊消失——讀者看到「利降息」會以為已經沒事，
    看到「利升息」又看不出正在改善。

    `band` 是變化的雜訊門檻：小於它一律當持平，不標方向。月度資料本來
    就有這個量級的雜訊，標了只是每期在紅綠之間跳。
    """
    out = []
    if level is not None and target is not None:
        gap = level - target
        if abs(gap) <= 0.25:
            out.append((f"水準：{level_word[1]}", "neutral"))
        elif gap > 0:
            out.append((f"水準：{level_word[0]}",
                        up_is if up_is else "hawkish"))
        else:
            out.append((f"水準：{level_word[2]}",
                        _invert_lean(up_is)))
    if cur is not None and prev is not None:
        d = cur - prev
        if abs(d) < band:
            out.append(("本期：持平", "neutral"))
        else:
            word = "上升" if d > 0 else "下降"
            kind = up_is if d > 0 else _invert_lean(up_is)
            out.append((f"本期：{word} {abs(d):.2f}", kind))
    return out


def _invert_lean(k: str) -> str:
    return {"hawkish": "dovish", "dovish": "hawkish"}.get(k, "neutral")


def _prev_yoy(series: dict, sid: str):
    rows = series.get(sid) or []
    return yoy(rows[:-1]) if len(rows) > 13 else None


def _prev_yoy_nsa(series: dict, nsa_id: str, sa_id: str):
    """年增率優先用未季調，抓不到才退季調——跟本期的 _yoy_nsa 同一套規則。"""
    v = _prev_yoy(series, nsa_id)
    return v if v is not None else _prev_yoy(series, sa_id)


def _prev_ann(series: dict, sid: str, months: int):
    rows = series.get(sid) or []
    return annualized(rows[:-1], months) if len(rows) > months + 1 else None


# Sahm 法則的觸發門檻。出自 Claudia Sahm 的原始論文（失業率三月移動平均
# 比過去十二個月的最低值高 0.50 個百分點以上），不是這個專案選的。
SAHM_TRIGGER = 0.50


def _sahm_value(lights) -> float | None:
    """紅綠燈清單裡的 Sahm 值。lights 是 Light 物件的 list，不是 dict。"""
    for lt in lights or []:
        if getattr(lt, "key", None) == "sahm":
            return getattr(lt, "value", None)
    return None


def build_labor_context(cfg: dict, series: dict, vintages: dict,
                        labels: dict, inverts: dict, failed: list, offline: bool,
                        consensus: dict | None = None) -> dict:
    payems = series.get("PAYEMS", [])
    nfp_changes = diff_series(payems)
    data_month = payems[-1]["date"][:7] if payems else "—"
    # 最新一期是不是 BLS 速報值（FRED 還沒同步）。畫面上要標——
    # 讀者有權知道這個數字的來源跟其他期不同，而且下一次執行會被
    # FRED 的正式值取代。
    provisional = bool(payems and payems[-1].get("provisional"))

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
    # 上一期的同一個數字，用同一個函式再算一次（見 key_metrics_prev）
    _nfp_prev = value_at(nfp_changes, 1)
    _ma3_prev = moving_avg(nfp_changes[:-1], 3) if len(nfp_changes) > 3 else None
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
        "provisional": provisional,
        "generated_at": clock.stamp(),
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
        # 九宮格就業軸的判定材料。全部是外部標準：
        #   u_lo/u_hi  FOMC 對長期失業率的中央趨勢（＝聯準會認定的充分就業）
        #   sahm       Sahm 法則（原始論文的 0.50 門檻）
        #   breakeven  三月均非農 vs 損益兩平（由人口成長推導，不是選的門檻）
        "axis": {
            "unrate": value_at(u3),
            "u_lo": value_at(series.get("UNRATECTLLR", [])),
            "u_hi": value_at(series.get("UNRATECTHLR", [])),
            "u_mid": value_at(series.get("UNRATEMDLR", [])),
            "sahm": _sahm_value(lights),
            "sahm_triggered": (_sahm_value(lights) or 0) >= SAHM_TRIGGER,
            "nfp_3m": bkev.nfp_3m,
            "breakeven": bkev.monthly,
            "below_breakeven": (bkev.gap is not None and bkev.gap < 0),
        },
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
        # up_is：這個指標**往上**代表偏鷹還是偏鴿。首頁的「本期變化」用它
        # 決定變動要標成什麼顏色——用漲跌上色會出錯，例如損益兩平就業增速
        # 變高其實是偏鴿的（同樣的非農代表更弱的就業），跟核心 CPI 上升
        # 剛好相反，卻會被標成同一個顏色。
        "key_metrics": {
            "nfp": {"label": "非農就業月變動", "en": "Nonfarm Payrolls, m/m",
                    "value": None if nfp_now is None else nfp_now / 10,
                    "unit": "萬人", "threshold": 1, "up_is": "hawkish"},
            "nfp_3m": {"label": "非農三個月均", "en": "Payrolls, 3-mo avg",
                       "value": None if ma3 is None else ma3 / 10,
                       "unit": "萬人", "threshold": 1, "up_is": "hawkish"},
            "u3": {"label": "失業率", "en": "Unemployment Rate (U-3)", "value": value_at(u3),
                   "unit": "%", "delta_unit": " 個百分點", "threshold": 0.05,
                   "up_is": "dovish"},
            # 參與率上升＝勞動供給增加＝薪資壓力減輕
            "lfpr": {"label": "勞動參與率", "en": "Labor Force Participation", "value": value_at(lfpr),
                     "unit": "%", "delta_unit": " 個百分點", "threshold": 0.05,
                     "up_is": "dovish"},
            "ahe_yoy": {"label": "平均時薪年增", "en": "Avg Hourly Earnings, y/y", "value": ahe_yoy,
                        "unit": "%", "delta_unit": " 個百分點", "threshold": 0.05,
                        "up_is": "hawkish"},
            # 門檻變高 → 同樣的非農代表更弱的就業 → 偏鴿
            "breakeven": {"label": "損益兩平就業增速", "en": "Breakeven Payrolls",
                          "value": None if bkev.monthly is None else bkev.monthly / 10,
                          "unit": "萬人", "threshold": 0.5, "up_is": "dovish"},
        },
        # 見通膨模組同名欄位的說明：計算方法換版那一期的比較基準。
        # 損益兩平就業增速沒放進來——它是好幾條序列合成的，重算一次要把
        # 整個 breakeven 模組再跑一遍，成本跟收益不成比例。缺的那一項
        # 在換版那一期不顯示變動，其餘照舊。
        "key_metrics_prev": {
            "nfp": {"value": None if _nfp_prev is None else _nfp_prev / 10},
            "nfp_3m": {"value": (None if _ma3_prev is None else _ma3_prev / 10)},
            "u3": {"value": value_at(u3, 1)},
            "lfpr": {"value": value_at(lfpr, 1)},
            "ahe_yoy": {"value": _prev_yoy(series, "CES0500000003")},
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
    provisional = bool(headline and headline[-1].get("provisional"))

    # ---- 推導「核心服務除住房」----
    # 一定要在 summarize 之前：KPI 卡、黏性連續月數、薪資傳導分析全都讀它。
    # 推不出來時就讓它是空的——下游每一處都已經有「缺資料就不顯示」的分支，
    # 這比塞一條口徑錯誤的序列進去安全得多（那正是先前的問題：
    # 用含住房的核心服務去講「除掉住房還是很黏」）。
    _sd = cfg.get("supercore_derive") or {}
    if _sd:
        _der = infl_an.derive_supercore(
            series.get(_sd.get("core_services", ""), []),
            series.get(_sd.get("shelter", ""), []),
            float(_sd.get("core_services_weight") or 0),
            float(_sd.get("shelter_weight") or 0))
        if _der:
            series["CPISUPERCORE"] = _der
            log.info("核心服務除住房：%s 減 %s 推導出 %d 個月",
                     _sd.get("core_services"), _sd.get("shelter"), len(_der))
        else:
            log.warning("核心服務除住房推導失敗——檢查 config 的 supercore_derive。"
                        "這次的 supercore KPI 與黏性訊號會缺值。")

    summ = infl_an.summarize(series, comp_meta)

    # ---- 核心 PCE 的即時推估 ----
    # 九宮格的通膨軸吃這個。PCE 落後 CPI 兩週，不補的話每個月都有一段
    # 時間九宮格用的是一個月前的世界。換算成 PCE 口徑再送，門檻才對得上。
    _pce_nowcast = infl_an.nowcast_core_pce(
        series.get("PCEPILFE", []),
        series.get("CPILFENS") or series.get("CPILFESL", []))
    if _pce_nowcast.get("estimated"):
        log.info("核心 PCE %s 尚未公布，用 %s 的核心 CPI 推估 %.2f%%"
                 "（近 %d 個月 CPI−PCE 平均差 %.2f 個百分點）",
                 _pce_nowcast["asof"][:7], _pce_nowcast["source_month"][:7],
                 _pce_nowcast["value"], infl_an.NOWCAST_GAP_MONTHS,
                 _pce_nowcast["gap"])

    # ---- 意外值 ----
    # 只用手動填入的預期，不退回模型外推（見 surprise.evaluate 的 allow_model）。
    exp = ((consensus or {}).get("expectations") or {}).get(data_month) or {}
    cpi_surprises = [
        sp.evaluate("CPI 年增率",
                    yoy_series(series.get("CPIAUCNS") or headline),
                    exp.get("CPIAUCSL_YOY"),
                    "manual" if exp.get("CPIAUCSL_YOY") is not None else "none",
                    unit="%", higher_is_better=False, allow_model=False),
        sp.evaluate("核心 CPI 年增率",
                    yoy_series(series.get("CPILFENS")
                               or series.get("CPILFESL", [])),
                    exp.get("CPILFESL_YOY"),
                    "manual" if exp.get("CPILFESL_YOY") is not None else "none",
                    unit="%", higher_is_better=False, allow_model=False),
    ]

    # ---- 分項貢獻（看三個月，單月雜訊太大）----
    comp_rows = {m["id"]: series.get(m["id"], []) for m in comp_meta
                 if series.get(m["id"])}
    att = infl_an.attribute_cpi(
        headline, comp_rows, comp_meta, months=3,
        # 官方的 All Items Less Shelter 指數。剔除住房後的漲幅要用它算，
        # 不是拿總數減住房貢獻去反推——見 attribute_cpi 的說明。
        ex_shelter_rows=series.get("CUSR0000SA0L2", []))

    # ---- 燈號 ----
    computed = infl_an.light_values(series, summ)
    lights = _lights_from(computed, cfg.get("regime_lights") or [])

    # ---- 規則 ----
    ctx = rules_inflation.InflationContext(series, summ, att, lights)
    flags = rules_inflation.run_rules(ctx)

    from .pages.inflation import _tilt
    tilt = _tilt(flags)

    # ---- KPI ----
    def rate_spark(sid, kind="yoy", fallback=None):
        """
        走勢縮圖畫的是「變化率」，不是指數水準。
        指數水準只會一路往上，畫出來是一條斜線，沒有資訊量。

        `fallback` 給年增率用：優先未季調，抓不到才退回季調——
        跟卡片上的大數字走同一套規則（見 inflation._yoy_nsa），
        否則會出現「3.4% 的數字配 3.5% 的線」。
        """
        rows = series.get(sid, []) or (series.get(fallback, []) if fallback else [])
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
                          + (f"　·　高於 2% {summ.headline_yoy - PCE_TARGET:+.1f} 個百分點"
                             if summ.headline_yoy is not None else ""))
                         if headline else ""),
        "headline_plain": (
            f"你買的東西平均比一年前貴 {summ.headline_yoy:.1f}%。"
            "這個數字包含食物和能源，所以起伏會比較大。"
            "聯準會的 2% 目標指的是核心 PCE，CPI 沒有官方目標，"
            "而且結構上通常比 PCE 高 0.3 個百分點左右。"
            if summ.headline_yoy is not None else "—"),
        # 年增率一律用未季調（跟大數字同一個口徑，見 inflation._yoy_nsa）。
        # 混用的話卡片上的 3.4% 會配一條 3.5% 的走勢線，看起來像資料錯亂。
        "headline_spark": rate_spark("CPIAUCNS", fallback="CPIAUCSL"),

        "core_display": _pct(summ.core_yoy),
        # 四張 KPI 的副標統一成「短期動能 · 離目標」兩段，每張都回答
        # 同一組問題：現在跑多快、離 2% 還差多遠。原本四張各講各的
        # （一張講三月年化、一張講三月＋六月＋圖說、一張講目標、一張講密大），
        # 讀者每讀一張就要重新找節奏。
        "core_sub": (f"近三個月年化 {_pct(summ.core_3m)}　·　"
                     + (f"高於 2% {summ.core_yoy - PCE_TARGET:+.1f} 個百分點"
                        if summ.core_yoy is not None else "")),
        "core_plain": (
            f"剔除波動大的食物與能源後，物價一年漲 {summ.core_yoy:.1f}%。"
            "聯準會看趨勢時主要看這一類數字。"
            if summ.core_yoy is not None else "—"),
        "core_spark": rate_spark("CPILFENS", fallback="CPILFESL"),
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
    _cm = {m["id"]: m for m in comp_meta}
    # 漲幅（%）與貢獻（個百分點）是兩種東西，先前四格等權並排、
    # 長得一模一樣，讀者分不出哪個是總數哪個是其中一塊。
    # 改成「總數在上、三塊分項在下、相加等於總數」的分解結構。
    _shelter = agg.get("shelter", 0) or 0
    _food_energy = agg.get("food_energy", 0) or 0
    # 「其他所有項目」**由下而上加**，不是拿總數倒推。
    #
    # 先前寫的是 `att.total - _shelter - _food_energy`，那讓這三塊**永遠**
    # 加得回總數——因為第三塊就是差額本身。代價是對帳誤差被默默吸收掉，
    # 而同一個畫面下方的「各類別明細」是真的由下而上算的，於是出現：
    #     上面　其他所有項目 +0.08
    #     下面　其他核心服務 +0.15、核心商品 −0.00
    # 同一件事兩個數字、差 0.07，五條明細加起來 +0.19 卻寫著總漲幅 +0.12。
    # 使用者看得到，程式看不到。
    #
    # **加得起來不等於算得對。** 改成由下而上之後三塊可能加不回總數，
    # 那個差額本身就是要給人看的東西——見下面的 recon。
    _rest = sum(c.value for c in att.contributions
                if (_cm.get(c.key, {}).get("group") in ("core_services",
                                                        "core_goods")
                    and not _cm.get(c.key, {}).get("laggy")))
    infl_parts = [
        {"label": "住房", "value": _shelter, "note": "算法落後市場行情約一年"},
        {"label": "食物與能源", "value": _food_energy, "note": "波動大，核心已剔除"},
        {"label": "其他所有項目", "value": _rest, "note": "核心裡的非住房部分"},
    ]
    # 估算合計。**這不是拿來跟實際漲幅對帳的。**
    #
    # 先前這裡算一個 residual、超過門檻就在畫面上寫「三塊相加是 X，跟實際
    # 的 Y 差 Z，權重過期或四捨五入會讓兩邊對不上」。那個框法是錯的：
    #
    #   BLS 的 CPI 不是「單一時點權重 × 累計變化」加總出來的，它是分層
    #   鏈式聚合、權重在期間內本身也會動。所以估算合計 ≠ 實際漲幅是
    #   **方法上的必然**，不是計算錯誤，也不主要來自四捨五入。
    #
    # 實測佐證：換上官方 relative importance（BLS 2025 年 12 月表）之後，
    # 2026-04→07 的估算合計 +0.17pp、實際 +0.12%，仍差 0.05——權重、指數、
    # 時間窗全部正確。把它寫成「對不上」只會讓讀者以為模型算錯，
    # 而這一區真正要回答的是「哪些類別在推升、哪些在壓低」。
    #
    # 差額仍然留在 att.unexplained 供程式端診斷，也仍然印進執行紀錄
    # （debug 用），但**不進畫面**。
    _sum_est = _shelter + _food_energy + _rest
    log.debug("分項估算合計 %+.3f pp、實際三個月漲幅 %+.3f%%、差 %+.3f"
              "（近似法的必然差異，非錯誤）",
              _sum_est, att.total, att.total - _sum_est)
    att_stats = [
        # 左右兩格是**兩種不同口徑的東西**，刻意不放等號、不算差額。
        # 下方會有一句小字講清楚它們不需要相等。
        {"label": "估算分項淨貢獻", "value": f"{_sum_est:+.2f}pp",
         "note": "四大類的估算貢獻加總"},
        # 三個月的**累計**漲幅，不是年化——attribute_cpi 走的是
        # _pct_change（cur/old − 1），沒有做 **4。標成「年化」會跟同一頁
        # KPI 卡的「近三個月年化」打架（1.0012⁴ 才是年率）。
        {"label": "實際 CPI 三個月漲幅", "value": f"{att.total:+.2f}%",
         "note": f"換算年率約 {((1 + att.total / 100) ** 4 - 1) * 100:+.1f}%"},
        {"label": "剔除住房後",
         "value": (f"{agg['ex_shelter']:+.2f}%"
                   if agg.get("ex_shelter") is not None else "—"),
         "color": ("var(--good)"
                   if (agg.get("ex_shelter") or 9) < 0.6 else "inherit"),
         "note": ("官方 All Items Less Shelter 指數"
                  if not agg.get("ex_shelter_derived")
                  else "抓不到官方指數，由權重反推（僅供參考）")},
    ]
    # 剔除住房後跟含住房比，哪一邊高。這句話每期都可能出現，而且每次都會
    # 被誤讀成算錯——它其實是這一區最有價值的一句話：**價格壓力集中在哪裡。**
    #
    # 措辭刻意不做預測。先前寫「這一塊之後會自然回落」——住房項落後市場
    # 租金是事實，但「一定會回落」是預測，而這個專案的原則是只講已算出來的
    # 判定。落後性只保證「反映得慢」，不保證方向。
    shelter_note = ""
    _ex = agg.get("ex_shelter")
    if _ex is not None and att.total is not None:
        _sw = agg.get("shelter_weight")
        _srate = (_shelter / (_sw / 100)) if _sw else None
        if _ex > att.total + 0.02:
            shelter_note = (
                f"剔除住房後（約 {_ex:+.2f}%）**高於**整體 CPI（{att.total:+.2f}%），"
                "代表住房正在把整體通膨往下拉"
                + (f"——住房自己只漲 {_srate:+.2f}%，低於非住房的 {_ex:+.2f}%。"
                   if _srate is not None else "。")
                + "由於 CPI 住房項目對市場租金變化的反映具有明顯落後性，"
                "後續仍需觀察這條下拉力量是否延續。")
        elif _ex < att.total - 0.02:
            shelter_note = (
                f"剔除住房後（約 {_ex:+.2f}%）**低於**整體 CPI（{att.total:+.2f}%），"
                "代表近三個月的價格壓力主要集中在住房。"
                "由於 CPI 住房項目對市場租金變化的反映具有明顯落後性，"
                "後續仍需觀察住房通膨是否持續降溫。")

    # ---- 趨勢型指標 ----
    trend_rows, _trend_vals = [], []
    # 黏性核心 CPI 不在這裡：它問的是「價格多久調整一次」（慣性），
    # 中位數與截尾平均問的是「多少項目在漲」（廣度）——兩個不同的問題。
    # 一個經濟體可以廣度低但黏性高（漲的項目不多，但都是很少調價的），
    # 那對聯準會反而更難處理，混在同一區會被讀成「還好」。
    # 黏性移到專屬的「核心服務的黏性」那一區，跟彈性核心 CPI 對照。
    for sid, label, note in [
        ("MEDCPIM159SFRBCLE", "中位數 CPI", "取漲幅正中間的項目，不受極端值影響"),
        ("TRMMEANCPIM159SFRBCLE", "截尾平均 CPI", "剔除漲跌最極端的項目後平均"),
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
        "provisional": provisional,
        "generated_at": clock.stamp(),
        "offline": offline,
        "failed": failed,
        "summary": summ,
        # 九宮格通膨軸的兩條門檻。放在通膨 context 裡是因為它需要的
        # SEP 序列由這個模組抓；情境層直接取用，不必再算一次。
        "bands": infl_an.inflation_bands(summ),
        "kpi": kpi,
        "flags": flags,
        "tilt": tilt,
        "lights": lights,
        "attribution": {
            "stats": att_stats,
            # 單位一律標 pp（個百分點），跟「漲幅 %」在視覺上分開——
            # 兩者混寫是這一區最容易產生的誤讀：+0.20% 跟 +0.20pp
            # 是完全不同的兩件事。
            "bars": charts.diverging_bars(items, fmt=lambda v: f"{v:+.2f}pp"),
            "parts": infl_parts,
            "total": att.total,
            "parts_sum": _sum_est,
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
        "stickiness": _stickiness_block(summ),
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
            "headline": charts.mini_series(
                yoy_series(series.get("CPIAUCNS")
                           or series.get("CPIAUCSL", [])),
                                           unit="%", fmt=lambda v: f"{v:.1f}"),
            "core": charts.mini_series(
                yoy_series(series.get("CPILFENS")
                           or series.get("CPILFESL", [])),
                                       unit="%", fmt=lambda v: f"{v:.1f}"),
            "pce": charts.mini_series(yoy_series(series.get("PCEPILFE", [])),
                                      unit="%", fmt=lambda v: f"{v:.1f}"),
            # 日頻序列：從最新一筆往回每 7 個交易日取一點（[::7] 從頭取
            # 會讓最後一格不是最新值），並標到「月/日」避免三格都寫同一個月
            "exp": charts.mini_series(
                since(series.get("T5YIFR", []), CHART_START, 40)[::-1][::7][::-1],
                unit="%", fmt=lambda v: f"{v:.2f}", daily=True),
        },
        # 通膨這幾條一律「往上＝偏鷹」，沒有例外
        "key_metrics": {
            # 頭條 CPI 排第一。CPI 發布日新聞標題上的那個數字就是它——
            # 先前這裡只有核心，結果 CPI 出爐當天的「本次更新」講得出核心、
            # 講不出讀者真正在找的那一個。
            "cpi_yoy": {"label": "CPI 年增", "en": "Headline CPI, y/y", "value": summ.headline_yoy,
                        "unit": "%", "delta_unit": " 個百分點",
                        "threshold": 0.05, "up_is": "hawkish"},
            "core_cpi_yoy": {"label": "核心 CPI 年增", "en": "Core CPI, y/y", "value": summ.core_yoy,
                             "unit": "%", "delta_unit": " 個百分點",
                             "threshold": 0.05, "up_is": "hawkish"},
            "core_cpi_3m": {"label": "核心 CPI 三月年化", "en": "Core CPI, 3-mo ann.", "value": summ.core_3m,
                            "unit": "%", "delta_unit": " 個百分點",
                            "threshold": 0.1, "up_is": "hawkish"},
            "core_pce": {"label": "核心 PCE 年增", "en": "Core PCE, y/y", "value": summ.pce_core_yoy,
                         "unit": "%", "delta_unit": " 個百分點",
                         "threshold": 0.05, "up_is": "hawkish"},
            "supercore": {"label": "核心服務除住房", "en": "Supercore (core svcs ex-shelter), 3-mo ann.", "value": summ.supercore_3m,
                          "unit": "%", "delta_unit": " 個百分點",
                          "threshold": 0.1, "up_is": "hawkish"},
            "exp5y5y": {"label": "長期通膨預期", "en": "5y5y Inflation Breakeven", "value": summ.expect_5y5y,
                        "unit": "%", "delta_unit": " 個百分點",
                        "threshold": 0.03, "up_is": "hawkish"},
        },
        # 用**現行程式**回頭算的上一期。只有在計算方法換版時才會被拿去當
        # 比較基準（見 changes.METHOD_VERSION）——那一期快照裡存的是舊程式
        # 算的值，直接相減會把口徑差異報成真實變動。
        #
        # 一律用「序列砍掉最後一筆再算一次」，跟本期走完全相同的程式路徑，
        # 兩邊口徑才保證一致。
        # KPI 卡上的鷹鴿標籤：水準一個、本期變化一個。
        # 門檻用 2%——但要講清楚那是**核心 PCE 的**目標；CPI 沒有官方目標，
        # 結構上又比 PCE 高 0.3 個百分點左右，所以 CPI 那兩張用 2.3 當參考線，
        # 不然每一期都會標成「高於目標」而失去資訊。
        # 核心 PCE 的即時推估。PCE 已經跟上時 estimated=False，畫面照舊。
        "pce_nowcast": _pce_nowcast,
        "kpi_lean": {
            "headline": _kpi_leans(
                summ.headline_yoy, 2.3, summ.headline_yoy,
                _prev_yoy_nsa(series, "CPIAUCNS", "CPIAUCSL"),
                level_word=("高於 PCE 目標對應水準", "接近目標對應水準",
                            "低於目標對應水準")),
            "core": _kpi_leans(
                summ.core_yoy, 2.3, summ.core_yoy,
                _prev_yoy_nsa(series, "CPILFENS", "CPILFESL"),
                level_word=("高於 PCE 目標對應水準", "接近目標對應水準",
                            "低於目標對應水準")),
            "pce": _kpi_leans(summ.pce_core_yoy, PCE_TARGET, summ.pce_core_yoy,
                              _prev_yoy(series, "PCEPILFE")),
            "exp": _kpi_leans(summ.expect_5y5y, 2.3, summ.expect_5y5y,
                              value_at(series.get("T5YIFR", []), 1),
                              band=0.03,
                              level_word=("偏離目標偏高", "與目標一致",
                                          "偏離目標偏低")),
        },
        "key_metrics_prev": {
            "cpi_yoy": {"value": _prev_yoy_nsa(series, "CPIAUCNS", "CPIAUCSL")},
            "core_cpi_yoy": {"value": _prev_yoy_nsa(series, "CPILFENS",
                                                    "CPILFESL")},
            "core_cpi_3m": {"value": _prev_ann(series, "CPILFESL", 3)},
            "core_pce": {"value": _prev_yoy(series, "PCEPILFE")},
            "supercore": {"value": _prev_ann(series, "CPISUPERCORE", 3)},
            "exp5y5y": {"value": value_at(series.get("T5YIFR", []), 1)},
        },
    }


DIR_TEXT = {
    "accel": ("重新加速", "hawkish"),
    "decel": ("穩定減速", "dovish"),
    "flat": ("卡在原地", "hawkish"),
}


def _ladder(v12, v6, v3, label: str) -> list[dict]:
    """12m / 6m / 3m 年化並排。單一數字看不出方向，這三個並排才看得出。"""
    return [
        {"label": f"{label}　近 12 個月", "value": _pct(v12, 2)},
        {"label": f"{label}　近 6 個月年化", "value": _pct(v6, 2)},
        {"label": f"{label}　近 3 個月年化", "value": _pct(v3, 2)},
    ]


def _stickiness_block(summ) -> dict:
    """
    核心服務的黏性 — 降息時間表卡最久的那一塊。

    為什麼要獨立一區
    ----------------
    先前只有一個數字（三月年化）與一條純水準的規則（>4% 警戒）。
    那回答的是「現在多高」，不是「降不降得下來」——而後者才是
    這一塊真正的問題。3.9% 且在加速，跟 4.1% 且在減速，
    前者其實比較該擔心，但純水準的門檻只會報後者。

    三個角度
    --------
    ① 動能階梯（12m / 6m / 3m）：方向。聯準會官員講話時引用的就是這個形式。
    ② 卡了幾個月：黏性最直接的量度——「該降的降不下來」有多久了。
    ③ 黏性 vs 彈性（Atlanta Fed）：彈性項先反應、黏性項最後才動。
       兩者收斂，這一輪通膨才算走完；差距還大就代表路還沒走完。

    CPI 與 PCE 並列：聯準會的目標是核心 PCE，兩者權重差很多
    （醫療在 PCE 裡權重大得多），背離時要以 PCE 那一側為準。
    """
    if summ.supercore_3m is None:
        return {}
    label, lean = DIR_TEXT.get(summ.supercore_dir, ("方向不明", "neutral"))

    # 結論句：方向 ＋ 卡了多久 ＋ 對降息時間表的意思
    if summ.supercore_dir == "decel":
        verdict = (f"核心服務**{label}**——3 個月年化低於 12 個月，"
                   "通膨的慣性正在鬆動。這是降息時間表往前挪的必要條件。")
    elif summ.supercore_dir == "accel":
        verdict = (f"核心服務**{label}**——3 個月年化高於 12 個月。"
                   "這一塊的成本主體是人力，重新加速代表降息時間表要往後推。")
    else:
        verdict = (f"核心服務**{label}**——長短天期的年化差不多，"
                   "既沒有進一步惡化，也看不到回落的跡象。")
    _n = summ.supercore_streak
    if _n:
        _at_least = "至少" if _n < 0 else ""
        verdict += f"三個月年化已經連續{_at_least} {abs(_n)} 個月高於 2.5%。"

    stats = _ladder(summ.supercore_12m, summ.supercore_6m, summ.supercore_3m, "CPI")
    if summ.pce_supercore_3m is not None:
        stats += _ladder(summ.pce_supercore_12m, summ.pce_supercore_6m,
                         summ.pce_supercore_3m, "PCE")

    # 兩邊背離時要講：聯準會看的是 PCE 那一側
    diverge = ""
    if (summ.pce_supercore_3m is not None and summ.supercore_3m is not None):
        gap = summ.supercore_3m - summ.pce_supercore_3m
        if abs(gap) > 0.5:
            hi, lo = ("CPI", "PCE") if gap > 0 else ("PCE", "CPI")
            diverge = (f"{hi} 版比 {lo} 版高 {abs(gap):.2f} 個百分點。"
                       "兩者的權重差很多——醫療在 PCE 裡權重大得多，"
                       "因為它含雇主付的部分。**聯準會的目標是核心 PCE，"
                       "背離時以 PCE 那一側為準。**")

    # 黏性 vs 彈性
    sf = {}
    if summ.sticky_cpi is not None and summ.flex_cpi is not None:
        g = summ.sticky_cpi - summ.flex_cpi
        if g > 1.5:
            note = ("彈性項已經降完、黏性項還卡著——這是這一輪通膨的典型形態。"
                    "剩下的路要靠黏性項自己慢慢走，而它們一年才調一次價。")
            kind = "hawkish"
        elif g > 0.5:
            note = "兩者仍有差距，黏性項還沒跟上彈性項的回落。"
            kind = "neutral"
        elif g < -0.5:
            note = ("彈性項高於黏性項——通常代表新的價格衝擊正在進來"
                    "（能源、關稅、供應鏈），而不是舊的通膨還沒走完。")
            kind = "hawkish"
        else:
            note = "兩者已經收斂，代表這一輪通膨大致走完了。"
            kind = "dovish"
        sf = {"sticky": summ.sticky_cpi, "flex": summ.flex_cpi,
              "gap": g, "note": note, "kind": kind,
              "stats": [
                  {"label": "黏性核心 CPI", "value": _pct(summ.sticky_cpi, 1),
                   "note": "價格很少調整的項目（房租、保險、醫療）"},
                  {"label": "彈性核心 CPI", "value": _pct(summ.flex_cpi, 1),
                   "note": "價格調整很快的項目（機票、二手車、旅館）"},
                  {"label": "差距", "value": f"{g:+.1f} 個百分點",
                   "color": ("var(--serious)" if g > 1.5 else "inherit"),
                   "note": "收斂才代表這一輪走完"},
              ]}

    return {"stats": stats, "verdict": verdict, "lean": lean,
            "dir_label": label, "streak": abs(summ.supercore_streak),
            "diverge": diverge, "sticky_flex": sf,
            "sum": (f"3 個月年化 {summ.supercore_3m:.2f}%　·　{label}"
                    + (f"　·　已卡{'至少' if _n < 0 else ''} {abs(_n)} 個月"
                       if _n else ""))}


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
        days = (nxt - clock.today()).days
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
    # 政策利率區間**優先取 FRED**（DFEDTARL／DFEDTARU），抓不到才退回 config。
    #
    # 為什麼要改成自動：這兩個數字先前只由人工填在 config/fomc.yaml，而操作手冊
    # 寫的是「只用於畫面顯示」——但它其實在下面算 gap，直接決定「市場定價偏降息
    # 還是偏向再緊縮」這個判定。忘記更新一次降息（25 個基點）就會讓 gap 平移
    # 0.25 個百分點，足以把結論翻成反的，而畫面上完全看不出來。這是整份專案裡
    # 唯一一個「漏更新會默默給出反向結論」的手動項，所以優先自動化。
    _rs = rates_series or {}
    _lo = value_at(_rs.get("DFEDTARL") or [])
    _hi = value_at(_rs.get("DFEDTARU") or [])
    rate_auto = _lo is not None and _hi is not None
    if not rate_auto:
        _lo, _hi = rate_cfg.get("lower"), rate_cfg.get("upper")
    _d2 = value_at(_rs.get("DGS2") or [])
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
        "generated_at": clock.stamp(),
        "shift": fomc_text.shift(docs),
        "regime": fomc_text.regime_change(docs),
        "vote": latest.vote,
        "rate_range": (f"{_lo:.2f}–{_hi:.2f}%"
                       if _lo is not None and _hi is not None else "—"),
        # 畫面要標出這個區間是自動抓的還是 config 的後備值——
        # 後備值可能已經過時，而讀者無從分辨。
        "rate_auto": rate_auto,
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


# 合計金額的合理性上限：解析出的近 120 天總額，相對最新一季申報發債的倍數。
#
# 為什麼要有：這類封面解析一定還會有沒想到的失敗模式。實際發生過的一次是
# 把貨架註冊額度（$40,000,000,000）當成單筆交易讀進來，近 120 天的合計
# 因此灌到季報申報值的 406%——而畫面照樣自信地印出來。
#
# 120 天約當 1.3 季，發債又是機會式的（挑市場好的時候一次發），
# 所以 3 倍已經很寬鬆；超過就幾乎確定是解析出錯，不是真的發那麼多。
OFFERING_SANITY_X = 3.0


def _offerings_block(offerings: list, hs, series: dict | None = None) -> dict:
    """
    近期發債交易的畫面資料。

    這一段的用途是**時效**，不是計分：季報最久落後 135 天，
    而發債當天就要申報。所以它回答的是「下一期的數字會往哪邊走」，
    刻意不動供給壓力分數——否則同一筆發債下一季會被算第二次，
    歷史可比性也會斷掉。

    金額以**原幣為主、美元為輔**。原幣是說明書封面上白紙黑字的那個數字，
    美元是我們用某一天的匯率換算出來的衍生值——把換算值當主角，等於讓
    一個會隨匯率漂動的數字蓋掉一個歷史事實。畫面上兩個都給。

    美元等值一律用**該筆定價日當天**的匯率（假日往前取最近一個交易日），
    不是今天的。發行人在定價那天就把金額鎖住了；用今天的匯率會讓一筆已經
    完成的發行每天早上都變一個數字，而且合計拿去除季報申報值（歷史值）
    就變成兩個口徑相除。匯率與日期不逐列重印——規則寫在頁面註腳講一次，
    每一列都對得回去。只有匯率取自跟定價日差七天以上的日期時才單獨標。
    """
    from .analysis import fx as fxmod

    if not offerings:
        return {"available": False}

    fx = fxmod.rates(series or {})

    # 只有「已定價的債券發行」才算一筆交易。counts 由 sec.dedupe_deals 決定：
    # 股票／ATM 增發、銀行貸款額度、尚未定價的預估版全部是 False。
    deals = [o for o in offerings if o.get("counts")]
    prelim_n = sum(1 for o in offerings
                   if o.get("preliminary") and not o.get("counts"))
    other_n = sum(1 for o in offerings
                  if not o.get("counts") and not o.get("preliminary"))

    # 合計走美元等值，但只加**換得出來**的。換不出來的仍然列在明細裡
    #（原幣金額照樣看得到），只是不進合計——寧可合計少一筆，
    # 也不要用一個假設的匯率把它補進去。
    usd_vals, no_fx = [], 0
    for o in deals:
        if o.get("principal") is None:
            continue
        # 匯率用**這一筆的定價日**，不是今天。合計因此是「當時實際募到多少
        # 美元」，跟下面拿來比的季報申報值同一個口徑，而且不會每天飄。
        conv = fxmod.to_usd(o["principal"], o.get("currency", ""), fx,
                            on=o.get("date", ""))
        if conv["usd"] is None:
            no_fx += 1
        else:
            usd_vals.append(conv["usd"] / 1e9)
    known_n = len(usd_vals)
    unknown_n = len(deals) - known_n
    total = sum(usd_vals)

    # 跟最新一季的申報值比，讀者才知道這批新申報的量級
    ref = hs.total_issued or 0
    ratio = (total / ref * 100) if ref and total else None

    # 合理性檢查：解析結果跟季報數字差太多時，寧可不報金額。
    # 這一段的價值在時效（比季報早三個月看到），沒有金額仍然成立；
    # 但報一個錯了四倍的合計，會直接毀掉整頁的可信度。
    insane = bool(ref and total > ref * OFFERING_SANITY_X)

    # 表格類型對投資人沒有意義，而且**表格號不代表證券種類**——
    # 424B5 可能是債券也可能是 ATM 增發。標籤要講的是「這是什麼」。
    _SEC_LABEL = {"equity": "股票發行", "other": "其他融資", "unknown": "未分類"}

    rows = []
    for o in offerings:
        is_prelim = bool(o.get("preliminary"))
        sec_kind = o.get("security", "unknown")
        counts = bool(o.get("counts"))
        ccy = o.get("currency") or ""
        principal = o.get("principal")

        native = usd_note = ""
        if is_prelim:
            native = "尚未定價"
        elif not counts:
            native = "不計入發債"
        elif principal is None:
            native = "金額待確認"
        else:
            native = fxmod.fmt_native(principal, ccy)
            conv = fxmod.to_usd(principal, ccy, fx, on=o.get("date", ""))
            if ccy != "USD" and conv["usd"] is not None:
                # 只寫金額，不寫匯率與日期。
                #
                # 那串「（匯率 0.7177，2026-08-07）」原本是為了讓人能自己
                # 重算，但它**每一列重複一次**，而換成定價日匯率之後每一列
                # 的日期還都不一樣，只會更亂。規則改成在下方註腳講一次：
                # 「美元等值一律用該筆定價日當天的匯率換算」——規則講清楚了，
                # 任何一列都自己對得回去，不必每列重印。
                usd_note = f'約 US${conv["usd"] / 1e8:,.0f} 億'
                # 例外：匯率取自跟定價日差很遠的日期（資料有缺口）。
                # **有問題的才註記，正常的不需要**——註記的價值來自它稀有。
                if conv.get("stale"):
                    usd_note += f'（匯率取自 {conv["date"]}）'

        kind = ("預估版" if is_prelim else
                _SEC_LABEL.get(sec_kind) if not counts else "債券發行")
        rows.append({"name": o["name"], "date": o["date"], "form": o["form"],
                     "kind": kind, "amount": native, "usd_note": usd_note,
                     "pending": not counts or principal is None,
                     "preliminary": is_prelim,
                     "counts": counts,
                     "security": sec_kind,
                     "currency": ccy,
                     "merged": o.get("merged", 1),
                     "url": o.get("doc_url", ""),
                     "items": o.get("items", "")})

    # 幣別分布：讓「合計美元」不會看起來像是五筆美元債
    by_ccy: dict[str, int] = {}
    for o in deals:
        if o.get("currency"):
            by_ccy[o["currency"]] = by_ccy.get(o["currency"], 0) + 1
    ccy_note = "、".join(f"{c} {n} 筆" for c, n in
                        sorted(by_ccy.items(), key=lambda kv: -kv[1]))

    # ---- 明細只留債券 ----
    #
    # 這一區回答的是**長端供給**：科技巨頭發了多少債，跟財政赤字一起
    # 壓在殖利率曲線的長端上。股票發行、ATM 增發、循環信用額度都不進債市，
    # 對這個問題沒有貢獻。
    #
    # 先前把它們也列出來（標「不計入發債」），本意是「讓你看到我看過、
    # 而且知道我為什麼排除」。實際效果相反：七筆非債券混在十幾列裡，
    # 「金額」欄一半寫著「不計入發債」，讀者要自己一列一列篩才找得到
    # 真正的債券——**為了證明沒有遺漏，反而讓主線更難讀。**
    #
    # 所以改成：明細只留債券（含已宣布未定價的預估版——那也是要來的供給），
    # 非債券的那幾件仍然在上方的摘要句裡交代筆數與種類。
    # 「我看過但排除了」這件事用一句話講，不用十列。
    bond_rows = [r for r in rows
                 if r.get("counts") or r.get("preliminary")]

    return {
        "available": True,
        "rows": bond_rows,
        # 被排除的那幾件仍然要能講出「有幾件、是什麼」，摘要句靠它。
        "excluded_n": len(rows) - len(bond_rows),
        "count": len(deals),
        "prelim_n": prelim_n,
        "other_n": other_n,
        "known_n": known_n,
        "unknown_n": unknown_n,
        "no_fx": no_fx,
        "ccy_note": ccy_note,
        "multi_ccy": len(by_ccy) > 1,
        "insane": insane,
        "show_amount": bool(total) and not insane,
        "total_display": (f"{total * 10:,.0f} 億美元" if total else "—"),
        "ratio_display": (f"{ratio:.0f}%" if ratio is not None else ""),
        "latest": offerings[0]["date"],
        "ref_display": f"{ref * 10:,.0f} 億美元" if ref else "—",
    }


def _earnings_block(earnings: list) -> dict:
    """
    財報新聞稿（8-K 項目 2.02）的畫面資料。

    這一段只回答一個問題：**下方那張表是不是已經過期了。**

    10-Q 的 XBRL 是季末後約 40 天才申報，財報新聞稿約三週就出來。
    中間那兩週，表格上寫的還是上一季，讀者卻已經在新聞上看到新一季的
    資本支出——不講清楚的話，這一頁看起來就像沒跟上。

    刻意只有日期與連結，沒有任何數字：新聞稿是非結構化文字，
    各家的口徑不同，硬解會拿到一個不知道是什麼的數字混進表格。
    這裡的價值是「知道已經有更新的數字了、去哪裡看」，不是「幫你讀」。
    """
    if not earnings:
        return {"available": False}
    ahead = [e for e in earnings if e.get("ahead")]
    rows = [{
        "name": e["name"],
        "date": e["date"],
        "period_end": e.get("period_end", ""),
        "ahead": bool(e.get("ahead")),
        # 「季末後 N 天」是讀者判斷這份新聞稿新不新的依據
        "lag_display": (f"季末後 {e['lag']} 天"
                        if e.get("lag") is not None and not e.get("ahead")
                        else ""),
        "url": e.get("doc_url", ""),
    } for e in earnings]
    return {
        "available": True,
        "rows": rows,
        "count": len(earnings),
        "ahead_n": len(ahead),
        "ahead_names": "、".join(e["name"] for e in ahead),
        "latest": earnings[0]["date"],
    }


# 指引與實績的比較倍數。低於這個值就不特別強調——資本支出本來就在成長，
# 「明年比今年多」不是新聞；倍數拉開才是這一區想講的事。
GUIDANCE_NOTE_X = 1.15


def _guidance_block(cfg: dict, hs) -> dict:
    """
    前瞻資本支出指引的畫面資料。

    為什麼這一區比下方的實績重要
    ----------------------------
    這一頁的論點是「AI 資本支出把科技巨頭從淨買方變成淨賣方，推高長端供給」。
    那個故事的主角是**接下來要花多少**，不是上一季花了多少。而前瞻指引
    不在任何申報欄位裡——它是法說會上用自然語言講的，所以只能手動維護
    （理由見 config/rates.yaml 的說明）。

    對照組是實績的年化值（最新一季 × 4）。年化是粗的——資本支出有季節性，
    第四季通常最重——所以畫面上要標明它是年化推估，不能當成「今年實際花了多少」。
    """
    if not cfg or not cfg.get("enabled"):
        return {"available": False}
    comps = [c for c in (cfg.get("companies") or [])
             if (c.get("high") or 0) > 0 or (c.get("low") or 0) > 0]
    if not comps:
        return {"available": False}

    lo = sum(float(c.get("low") or c.get("high") or 0) for c in comps)
    hi = sum(float(c.get("high") or c.get("low") or 0) for c in comps)
    # 沒給指引的公司要列出來，否則合計看起來像是全部五家的總和
    missing = [c.get("name", "") for c in (cfg.get("companies") or [])
               if not ((c.get("high") or 0) > 0 or (c.get("low") or 0) > 0)]

    rows = []
    for c in comps:
        a = float(c.get("low") or c.get("high") or 0)
        b = float(c.get("high") or c.get("low") or 0)
        rows.append({
            "name": c.get("name", ""),
            "value": (f"{a * 10:,.0f} 億美元" if abs(a - b) < 1e-9
                      else f"{a * 10:,.0f}–{b * 10:,.0f} 億美元"),
            "note": c.get("note", ""),
        })
    rows.sort(key=lambda r: -float(
        next(c.get("high") or c.get("low") or 0
             for c in comps if c.get("name") == r["name"])))

    # 年化實績：最新一季 × 4。只有在抓得到實績時才做這個對照。
    run_rate = (hs.total_capex or 0) * 4
    ratio = ((hi + lo) / 2 / run_rate) if run_rate else None

    return {
        "available": True,
        "year": cfg.get("year", ""),
        "as_of": cfg.get("as_of", ""),
        "source": cfg.get("source", ""),
        "rows": rows,
        "n": len(rows),
        "missing": "、".join(x for x in missing if x),
        "total_display": (f"{lo * 10:,.0f} 億美元" if abs(hi - lo) < 1e-9
                          else f"{lo * 10:,.0f}–{hi * 10:,.0f} 億美元"),
        "run_rate_display": (f"{run_rate * 10:,.0f} 億美元" if run_rate else ""),
        "ratio_display": (f"{ratio:.1f} 倍" if ratio else ""),
        "notable": bool(ratio and ratio >= GUIDANCE_NOTE_X),
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


def _axis_derivation(sc, labor: dict | None, infl: dict | None,
                     labor_ctx: dict | None, infl_ctx: dict | None) -> dict:
    """
    「這一格是怎麼判出來的」——兩條軸的輸入值、權重、門檻與門檻的出處。

    為什麼一定要有這一塊
    --------------------
    讀者會在通膨頁看到「通膨面：方向不明」，然後在情境頁看到「通膨高」，
    結論是「這個網站在自打嘴巴」。實際上那是兩個不同的問題：

        通膨頁的結論 = **方向**（這一期的新訊號把政策往哪推，看旗標鷹鴿淨值）
        九宮格的軸   = **水準**（離 2% 目標多遠，看核心 PCE）

    「水準很高、但這個月的新訊號互相抵消」完全可能同時成立。
    但畫面上從來沒說這兩件事不一樣，所以讀起來就是矛盾。

    就業那一軸更需要講：它**兩者混用**——綜合分數在 ±0.45 中間帶時，
    會用旗標淨值 ±3 去推。所以「就業弱」可能是分數定的、也可能是旗標定的，
    而先前只有後者才會顯示說明。
    """
    out: dict = {}

    if infl:
        b = infl.get("bands") or {}
        yoy_v, m3 = infl.get("core_pce_yoy"), infl.get("core_pce_3m")
        lvl = scenario.blended_inflation(yoy_v, m3)
        tilt = (infl_ctx or {}).get("tilt") or {}
        src = ("FOMC 對 {y} 年的核心 PCE 預測中位數（{lo:.1f}–{hi:.1f}% 中央趨勢）"
               .format(y=b.get("next_year"), lo=b.get("next_lo") or 0,
                       hi=b.get("next_hi") or 0)
               if b.get("auto") and b.get("next_lo") is not None
               else ("FOMC 對 {y} 年的核心 PCE 預測中位數".format(y=b.get("next_year"))
                     if b.get("auto") else "後備值（沒有外部依據）"))
        # 常駐的一句話：讀者不展開也要知道「高」是怎麼來的。
        # 先前這一整塊是收合的，而收合列長得跟旁邊的圖例一樣（12.5px 灰字），
        # 讀者根本不會發現那裡有答案——等於做了跟沒做一樣。
        _cmp = {"高": f'高於門檻 {b.get("high", 2.90):.2f}%',
                "低": f'低於門檻 {b.get("low", 2.30):.2f}%'}.get(
                    sc.infl_state,
                    f'落在門檻 {b.get("low", 2.30):.2f}–{b.get("high", 2.90):.2f}% 之間')
        # PCE 還沒公布、用 CPI 推估時**一定要講出來**。這個數字會決定
        # 九宮格落在哪一格，而九宮格決定整張固定收益部位對照表——
        # 一個影響部位的數字不能讓讀者以為它是 BEA 公布的官方值。
        _est = "（推估）" if infl.get("pce_estimated") else ""
        # lead 是**常駐的一句話**，只講「這一格是怎麼判出來的」。
        #
        # 先前把整段推估的說明（BEA 什麼時候發、為什麼要換算、CPI 跟 PCE 差
        # 多少）直接接在後面，於是一張本來一行的卡變成七行，整個九宮格區塊
        # 讀起來像一團字。那段說明有價值，但它回答的是「推估怎麼來的」，
        # 屬於展開之後的內容，不屬於第一眼。
        _lead = (f"核心 PCE {_pct(yoy_v)}{_est} 與三月年化 {_pct(m3)} 加權後 "
                 f"{lvl:.2f}%，{_cmp}"
                 if lvl is not None else "資料不足")
        _est_note = ("核心 PCE 這個月還沒公布（BEA 月底才發），上面那個值是用"
                     "已公布的核心 CPI 換算成 PCE 口徑推估的。換算而不是直接"
                     "代入，是因為門檻錨在 FOMC 的 PCE 預測，而核心 CPI 結構上"
                     "比核心 PCE 高 0.3 個百分點左右。PCE 一公布就換回實際值。"
                     if infl.get("pce_estimated") else "")
        out["inflation"] = {
            "state": sc.infl_state,
            "lead": _lead,
            # 展開後才顯示，見上面的說明
            "note": _est_note,
            "rows": [
                {"label": "核心 PCE 年增率（水準）", "value": _pct(yoy_v), "w": "×0.6"},
                {"label": "核心 PCE 三月年化（動能）", "value": _pct(m3), "w": "×0.4"},
            ],
            "level": (f"{lvl:.2f}%" if lvl is not None else "—"),
            "low": f'{b.get("low", 2.30):.2f}%',
            "high": f'{b.get("high", 2.90):.2f}%',
            "auto": bool(b.get("auto")),
            "target": b.get("target"),
            "high_src": src,
            "low_src": (f'長期通膨目標 {b["target"]:.1f}% ＋ 0.25（量測誤差）'
                        if b.get("auto") and b.get("target") is not None
                        else "後備值（沒有外部依據）"),
            # 兩頁的用詞不一致正是讀者覺得矛盾的來源，這裡直接對照著講
            "tilt": tilt.get("tilt"),
            "tilt_net": tilt.get("net"),
        }

    if labor:
        u, lo, hi = labor.get("unrate"), labor.get("u_lo"), labor.get("u_hi")
        net = (labor.get("tilt") or {}).get("net")
        rows = []
        if u is not None and lo is not None:
            lvl = ("高於上緣" if u > hi else
                   ("低於下緣" if u < lo else "落在區間內"))
            rows.append({"label": "失業率（水準）",
                         "value": f"{u:.1f}%", "w": lvl})
            rows.append({"label": "FOMC 長期失業率　中央趨勢",
                         "value": f"{lo:.1f}–{hi:.1f}%", "w": "門檻"})
        sahm = labor.get("sahm")
        if sahm is not None:
            rows.append({"label": "Sahm 法則（動能）", "value": f"{sahm:+.2f}",
                         "w": "觸發" if labor.get("sahm_triggered") else "門檻 0.50"})
        n3, bk = labor.get("nfp_3m"), labor.get("breakeven")
        if n3 is not None and bk is not None:
            rows.append({"label": "三月均非農　vs　損益兩平（動能）",
                         "value": f"{n3/10:+.1f} / {bk/10:+.1f} 萬人",
                         "w": "低於" if labor.get("below_breakeven") else "高於"})
        # 常駐的一句話。分支順序必須跟 scenario.classify_labor 一致，
        # 否則會出現「摘要說水準正常、格位說弱」而沒有解釋的情況。
        _basis = sc.labor_basis
        if _basis == "sahm":
            _lead = (f"Sahm 法則 {labor.get('sahm'):+.2f} 觸發衰退門檻"
                     "（0.50），勞動市場正在快速惡化"
                     if labor.get("sahm") is not None else "Sahm 法則已觸發")
        elif _basis == "breakeven":
            _lead = (f"失業率 {u:.1f}% 仍在充分就業區間，但三月均非農 "
                     f"{n3 / 10:+.1f} 萬低於損益兩平 {bk / 10:+.1f} 萬，"
                     "增速撐不住現有失業率"
                     if None not in (u, n3, bk) else "非農低於損益兩平")
        elif _basis == "fallback":
            _lead = (f"沒有取得 FOMC 的長期失業率預測，改用後備門檻："
                     f"綜合分數 {labor.get('score', 0):+.2f}（±0.45）"
                     "、旗標淨值（±3）——這兩個數字沒有外部依據")
        elif u is not None and lo is not None:
            _lead = {"弱": f"失業率 {u:.1f}% 高於聯準會認定的充分就業上緣 {hi:.1f}%",
                     "強": f"失業率 {u:.1f}% 低於充分就業下緣 {lo:.1f}%",
                     }.get(sc.labor_state,
                           f"失業率 {u:.1f}% 落在充分就業區間 "
                           f"{lo:.1f}–{hi:.1f}% 之內，動能也沒有轉弱")
        else:
            _lead = "資料不足"
        out["labor"] = {
            "state": sc.labor_state,
            "lead": _lead,
            "rows": rows,
            "basis": sc.labor_basis,
            "note": sc.labor_basis_note,
            "score": (f'{labor["score"]:+.2f}'
                      if labor.get("score") is not None else "—"),
            "net": (f"{net:+.0f}" if net is not None else "—"),
            "tilt": ((labor_ctx or {}).get("tilt") or {}).get("tilt"),
        }
    return out


def build_scenario_context(labor_ctx: dict | None, infl_ctx: dict | None,
                           fomc_ctx: dict | None, rates_ctx: dict | None = None) -> dict:
    labor = None
    if labor_ctx:
        labor = {"score": labor_ctx["score"]["score"],
                 "tilt": labor_ctx["tilt"],
                 "flags": labor_ctx["flags"],
                 **(labor_ctx.get("axis") or {})}
    infl = None
    if infl_ctx:
        s = infl_ctx["summary"]
        # 動能項一定要用**核心 PCE** 的三月年化（不是核心 CPI 的）。
        # 兩者長期差 0.3–0.5 個百分點，混用會讓九宮格的通膨軸固定偏鷹。
        # 見 scenario.classify_inflation 的說明。
        # PCE 還沒公布時用 CPI 推估補上（見 inflation.nowcast_core_pce）。
        #
        # 使用者的批評：「九宮格高中低不能只用 PCE，因為 PCE 是落後指標。」
        # 對——CPI 月中發、PCE 月底發，每個月都有兩週九宮格活在一個月前。
        # 但也不能直接把 CPI 塞進來比：門檻錨在 SEP，而 SEP 預測的是 PCE。
        # 所以先把 CPI **換算成 PCE 口徑**再送進原本的判定，兩邊口徑一致。
        _nc = infl_ctx.get("pce_nowcast") or {}
        _pce_for_grid = (_nc.get("value") if _nc.get("estimated")
                         else s.pce_core_yoy)
        infl = {"core_pce_yoy": _pce_for_grid, "core_pce_3m": s.pce_core_3m,
                "bands": infl_ctx.get("bands") or {},
                "pce_estimated": bool(_nc.get("estimated")),
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
        "why": _axis_derivation(sc, labor, infl, labor_ctx, infl_ctx),
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
        "generated_at": clock.stamp(),
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
    sc = infl_series.get("CPISUPERCORE") or []
    if not ahe or not sc:
        # **講清楚缺的是哪一條。** 先前只寫「缺其中一項」，於是這一區空掉時
        # 沒有任何線索可以追——而核心服務除住房是**推導出來的**（見
        # inflation.derive_supercore），它會空掉的原因是上游的兩條之一
        # 沒抓到，而不是這一區自己的問題。
        _miss = []
        if not ahe:
            _miss.append("平均時薪（CES0500000003）")
        if not sc:
            _miss.append("核心服務除住房（由 CUSR0000SASLE 減 CUSR0000SAH1 "
                         "推導，兩條缺一就推不出來）")
        log.warning("薪資傳導分析缺資料：%s", "、".join(_miss))
        return {"available": False,
                "reason": "缺少：" + "、".join(_miss) + "。"}

    w = yoy_series(ahe)
    s = yoy_series(sc)
    p = pt.analyse(w, s)
    if p.best_lag is None:
        return {"available": False, "reason": p.note or "重疊樣本不足"}

    title, desc = pt.VERDICT_TEXT.get(p.verdict, ("—", ""))
    stats = [
        {"label": "平均時薪年增", "value": f"{p.wage_latest:.2f}%"},
        {"label": "核心服務除住房年增", "value": f"{p.supercore_latest:.2f}%"},
        # 顏色只回答「要不要擔心」，不是照正負號塗。
        # 兩個極端**都是**上行風險，只是機制不同：
        #   gap > +0.8  服務業漲價已經超過人力成本，還有薪資以外的推力，
        #               薪資降溫也壓不下來
        #   gap < -0.8  人力成本上升還沒轉嫁到售價，企業後續調價就會補漲
        # 先前 gap < -0.8 塗的是 --series-1（全站的鴿派／利多色），
        # 而旁邊的判定文字同時說「服務業通膨有上行的風險」——
        # 同一格數字，顏色跟註解說相反的話。只有 aligned 才是良性的。
        {"label": "差距", "value": f"{p.gap:+.2f} 個百分點",
         "color": ("var(--serious)" if abs(p.gap) > 0.8 else "inherit"),
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
    _ig_cfg = cfg.get("ig_market") or {}
    hs = rt.hyperscalers(_hs_cfg, _ig_cfg.get("quarterly_issuance"),
                         ig_verified=bool(_ig_cfg.get("verified")))
    # 近期發債申報：補季報 45–135 天的時效缺口。刻意不進供給壓力分數。
    offerings = _hs_cfg.get("offerings") or []
    # 財報新聞稿：補實績從「季末後 40 天」到「約 3 週」的缺口。同樣不計分。
    earnings = _hs_cfg.get("earnings") or []
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
    # 每一格都要講清楚「這是哪一段期間的數字」。各家會計年度不同，
    # 「本季」對五家公司不是同一段時間——period_span 印出實際的期末日範圍。
    _span = hs.period_span or hs.as_of or ""
    _span_note = f"各家最新一季，期末 {_span}" if _span else "期別未標示"
    hs_stats = [
        {"label": "資本支出合計", "value": f"{hs.total_capex * 10:,.0f} 億美元",
         "note": (f"年增 {hs.capex_yoy:+.0f}%（對去年同季）"
                  if hs.capex_yoy is not None else _span_note)},
        {"label": "佔營運現金流",
         "value": (f"{hs.capex_to_ocf:.0f}%" if hs.capex_to_ocf else "—"),
         "color": ("var(--critical)" if (hs.capex_to_ocf or 0) > 100
                   else ("var(--serious)" if (hs.capex_to_ocf or 0) > 80 else "inherit")),
         # 明講是合計除合計。先前只寫「超過 100% 代表自由現金流轉負」，
         # 讀者無從知道這是加總的比率還是五家百分比的平均——兩者差很多。
         "note": "合計 ÷ 合計，非五家平均"},
        # 發債金額的期間**必須**寫在標籤裡。先前寫「本季」——五家的
        # 「本季」是五段不同的期間，這樣寫等於沒有期間定義。
        {"label": f"單季發債合計{f'（期末 {_span}）' if _span else ''}",
         "value": f"{hs.total_issued * 10:,.0f} 億美元",
         # 佔投資級市場的比重只有在分母經人工確認時才顯示（見 rates.hyperscalers）
         "note": (f"佔投資級發行 {hs.ig_share:.0f}%"
                  if hs.ig_share is not None else "分子為五家不同會計期別之和")},
        {"label": "簡化口徑自由現金流為負",
         "value": f"{hs.n_cash_negative} / {len(hs.companies)} 家",
         "note": "營運現金流 − 現金資本支出 < 0"},
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
            # 「本季」對五家公司不是同一段期間，所以標出實際的期末日範圍。
            "hs_note": (f"單季 {hs.total_issued*10:,.0f} 億美元年化"
                        + (f"（期末 {hs.period_span}）" if hs.period_span else "")
                        + (f"，佔投資級發行 {hs.ig_share:.0f}%"
                           if hs.ig_share is not None else "")),
            "ratio": (hs_yr / gov_yr * 100 if hs_yr and gov_yr else None),
        }
        if supply_side["ratio"] is not None:
            supply_side["ratio_display"] = f"{supply_side['ratio']:.0f}%"
            # 只留結論。「為什麼方向比比例重要」是方法論，已經搬進頁尾的
            # 名詞解釋——投資人第一眼要的是那個百分比與它是往哪邊走。
            supply_side["summary"] = (
                f"科技巨頭的發債規模約是政府年赤字的 "
                f"{supply_side['ratio']:.0f}%，而且是**新增**的供給——"
                "這幾家過去是淨買方，現在轉成淨賣方。")

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
        "generated_at": clock.stamp(),
        "offline": offline,
        "failed": failed,
        "curve": curve,
        "debt": debt,
        "hyperscalers": hs,
        "pressure": press,
        "pressure_text": rt.PRESSURE_TEXT.get(press.level, ("—", "")),
        "debt_text": rt.DEBT_VERDICT.get(debt.verdict, ("—", "")),
        "hs_text": rt.hs_verdict(hs),
        # 來源字串現在由 pages/rates.py 依實際擷取狀況組出來（含逐家連結與
        # 「N / 5 家取自 SEC」），config 的這一行只當補充說明。
        "hs_source": (cfg.get("hyperscalers") or {}).get("source", ""),
        "hs_ig": {"issuance": _ig_cfg.get("quarterly_issuance"),
                  "as_of": _ig_cfg.get("as_of", ""),
                  "verified": bool(_ig_cfg.get("verified"))},
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
        "offerings": _offerings_block(offerings, hs, series),
        "earnings": _earnings_block(earnings),
        "guidance": _guidance_block(cfg.get("capex_guidance") or {}, hs),
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
