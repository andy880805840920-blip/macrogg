"""長端利率與債務供給頁的內容產生器（P5）。"""

from __future__ import annotations

from ..site import esc
from .labor import _light_card, _stats
from . import compact_full, focus_evidence, state_chip, teach
from . import longend as LE


def _rates_body_full(d: dict) -> str:
    sp = d["pressure"]
    title, why = d["pressure_text"]
    lean_cls = {"high": "hawkish", "low": "dovish"}.get(sp.level, "balanced")
    hs = d["hyperscalers"]
    hs_title, hs_desc = d["hs_text"]
    debt_title, debt_desc = d["debt_text"]
    lights_html = "".join(_light_card(l) for l in d["lights"])
    # 摺疊起來時摘要列要講出狀態分布，否則卡片看起來是空的
    _lc = {}
    for l in d["lights"]:
        _lc[l.status] = _lc.get(l.status, 0) + 1
    _order = [("critical", "警戒"), ("warning", "留意"),
              ("good", "正常"), ("unknown", "無資料")]
    light_summary = (f'{len(d["lights"])} 項指標：'
                     + "、".join(f"{n} 項{lab}" for k, lab in _order
                                 if (n := _lc.get(k)))
                     + "。") if d["lights"] else ""
    # 檢核卡的一句結論：只由紅黃燈數量推出，跟勞動頁的檢核卡同一套做法。
    _crit, _warn = _lc.get("critical", 0), _lc.get("warning", 0)
    if _crit:
        _li_lean = "hawkish"
        _li_txt = "供給端的壓力已經反映在市場指標上，不只是算出來的。"
    elif _warn:
        _li_lean = "neutral"
        _li_txt = "壓力在累積，但還沒有越線。"
    else:
        _li_lean = "neutral"
        _li_txt = "長端目前沒有額外的供給警訊。"
    lights_impact = (f'<div class="impact {_li_lean}">'
                     f'{esc(light_summary.rstrip("。"))}——{esc(_li_txt)}</div>'
                     if d["lights"] else "")

    # 收合摘要：一律取這一區已經算出來的結論。
    _dh = d.get("decomp_head") or {}
    _dec_sum = (f'名目 10 年期 {_dh["nominal"]}　·　其中期限溢酬 {_dh["value"]}'
                if _dh else "名目利率的三段拆解")
    _ss = d.get("supply_side") or {}
    _sup_sum = (f'政府年赤字 {_ss["gov_display"]}　·　'
                f'科技巨頭年化 {_ss["hs_display"]}' if _ss else "供給來源與壓力分數")
    _dm = (sp.demand or [{}])[0]
    _dem_sum = (f'{_dm["label"]} {_dm["value"]}　·　{_dm["detail"]}'
                if _dm else "需求端的溫度計")
    _pr_sum = (f'已反映 {sp.priced_score:+.2f}　·　供給壓力 {sp.score:+.2f}'
               if sp.priced else "價格已經反映多少")
    _dg = d.get("debt_gap") or {}
    _debt_sum = (f'財政缺口 {_dg["value"]}　·　{debt_title}' if _dg else debt_title)
    # 收合摘要把「前瞻」放在最前面：整卡的主詞是接下來要花多少，
    # 佔比與發債都是那個承諾的後果。
    #
    # 摘要有 45 字的上限（test_sections 釘住），所以加了指引就要讓出位置：
    # 讓的是發債筆數——它在卡片展開後有自己的區塊，而「承諾要花多少
    # vs 現金流撐不撐得住」這一組對照，收合時看不到就沒別的地方看得到。
    _gd = d.get("guidance") or {}
    _off_av = bool((d.get("offerings") or {}).get("available"))
    _hs_ratio = (f'佔營運現金流 {hs.capex_to_ocf:.0f}%'
                 if hs.capex_to_ocf is not None else "")
    if _gd.get("available"):
        _hs_sum = (f'{_gd["year"]} 年計畫 {_gd["total_display"]}'
                   + (f'　·　{_hs_ratio}' if _hs_ratio else f'　·　{hs_title}'))
    else:
        _hs_sum = ((f'資本支出{_hs_ratio}　·　{hs_title}'
                    if _hs_ratio else hs_title)
                   + (f'　·　近 120 天 {d["offerings"]["count"]} 筆發債交易'
                      if _off_av else ""))

    def _cmoves(items) -> str:
        return "".join(
            f'<div class="cmove"><div>{esc(p["label"])}</div>'
            f'<div class="cm-delta {"up" if p["score"] > 0 else "down"}">{p["score"]:+.2f}</div>'
            f'<div class="cm-val">{esc(p["detail"])}</div></div>'
            for p in items)

    parts = _cmoves(sp.parts)

    # ---- 結論卡的刻度軸 ----
    # 「+1.16」單看沒有刻度感。軸範圍取 −3～+3：這個分數只由兩個
    # 供給來源構成，各自的合理區間約在 ±1.5 之內。
    _lo, _hi = -3.0, 3.0
    _pct = max(0, min(100, (sp.score - _lo) / (_hi - _lo) * 100))
    _col = ("var(--serious)" if sp.level == "high" else
            ("var(--series-1)" if sp.level == "low" else "var(--muted)"))
    pressure_axis = f"""<div class="sax compact">
  <div class="sax-head">
    <span class="sax-label">供給壓力分數</span>
    <span class="sax-val" style="color:{_col}">{sp.score:+.2f}</span>
    <span class="sax-delta">只由供給來源構成，不含已反映在價格上的部分</span>
  </div>
  <div class="score-bar">
    <i style="left:{min(50, _pct):.1f}%;width:{abs(_pct - 50):.1f}%;background:{_col}"></i>
    <span class="score-mid"></span>
  </div>
  <div class="sax-scale"><span>−3 壓力小</span><span>0 中性</span><span>+3 壓力大</span></div>
</div>"""

    # ---- 期限溢酬：這一頁的主角 ----
    dh = d.get("decomp_head") or {}
    decomp_head_html = (
        f'<div class="bkgap" style="color:{dh["color"]};margin-top:4px;'
        f'padding-top:0;border-top:none">'
        f'<span class="bk-label">名目 10 年期 {esc(dh["nominal"])}　其中期限溢酬</span>'
        f'<span class="bk-val">{esc(dh["value"])}</span>'
        f'<span class="bk-verdict" style="font-weight:400;font-size:12.5px;'
        f'color:var(--muted)">{esc(dh["change"])}</span></div>'
        if dh else "")

    # 這張卡自己的一句結論。門檻沿用 decomp_head 的配色邏輯（0.6／0.2），
    # 不另立一套標準——同一個數字不能在同一張卡上被兩套門檻評價。
    _cv = d.get("curve")
    _tp = getattr(_cv, "term_premium", None) if _cv is not None else None
    decomp_impact = ""
    if _tp is not None:
        _chg = f"（{dh['change']}）" if dh.get("change") else ""
        if _tp > 0.6:
            decomp_impact = (
                f'<div class="impact hawkish">期限溢酬 {_tp:+.2f}%{esc(_chg)}，'
                f'高於 0.40% 的中性參考——市場對長期持債要求的補償偏高，'
                f'這一段降息壓不下來。</div>')
        elif _tp < 0.2:
            decomp_impact = (
                f'<div class="impact dovish">期限溢酬 {_tp:+.2f}%{esc(_chg)}，'
                f'低於中性參考——長端目前沒有要求額外補償，'
                f'利率主要跟著政策預期走。</div>')
        else:
            decomp_impact = (
                f'<div class="impact neutral">期限溢酬 {_tp:+.2f}%{esc(_chg)}，'
                f'在中性區間——供給壓力存在，但市場還沒要求明顯的額外補償。</div>')

    # ---- 供給端：政府 vs 科技巨頭 ----
    # 這張卡是整頁的關鍵連結。沒有它，債務動態與科技巨頭就只是
    # 剛好被放在同一頁的兩個主題。
    ss = d.get("supply_side") or {}
    supply_html = ""
    if ss:
        _sum = ss.get("summary", "")
        _sum_html = "".join(
            (f"<b>{esc(s)}</b>" if i % 2 else esc(s))
            for i, s in enumerate(_sum.split("**")))
        # 來源數量不能寫死：縮表那一項在 TREAST 抓不到時不會出現，
        # 寫死「兩個來源」而畫面上列了三項，讀者會以為少看了什麼。
        _n_parts = "一二三四五六"[max(0, len(sp.parts) - 1)]
        supply_html = f"""
<div class="grid">
  <div class="card">
    <h2 id="supply" data-sum="{esc(_sup_sum)}">債券供給：政府與科技巨頭</h2>
    <p class="hint">政府、科技巨頭與聯準會縮表（到期的公債不再買回去），
      <b>三個來源競爭的是同一批固定收益買盤</b>。</p>
    {f'<div class="impact {lean_cls}">{_sum_html}</div>' if _sum else ''}
    <div class="stat-row" style="margin-top:14px">
      <div class="stat"><div class="s-label">政府：年度赤字</div>
        <div class="s-value">{esc(ss['gov_display'])}</div>
        <div class="s-note">{esc(ss['gov_note'])}</div></div>
      <div class="stat"><div class="s-label">科技巨頭：年化發債</div>
        <div class="s-value">{esc(ss['hs_display'])}</div>
        <div class="s-note">{esc(ss['hs_note'])}</div></div>
    </div>
    {(f'<div class="bkgap" style="color:var(--text-primary)">'
      f'<span class="bk-label">科技巨頭相對政府的規模</span>'
      f'<span class="bk-val">{esc(ss["ratio_display"])}</span></div>')
     if ss.get('ratio_display') else ''}
    <p class="hint" style="margin-top:12px">壓力分數的{esc(_n_parts)}個來源：</p>
    <div class="cmoves" style="border-top:none;padding-top:0">{parts}</div>
    {teach(
        "最近誰在大量發行長天期債券：政府（財政赤字）與科技巨頭（AI 資本支出）。",
        "債券多到買不完，價格就跌、殖利率就升——跟任何市場一樣是供需。長端的供給壓力大，降息也壓不下長端利率。",
        "把政府與企業的發行量加起來看方向：兩邊同時放量，長端承壓最重；這也是「降息但房貸利率不降」的常見原因。")}
    <div class="src">單位：億美元。年化＝單季 × 4，只用來比較量級。</div>
  </div>
</div>"""

    # ---- 需求端 ----
    dem = (sp.demand or [{}])[0]
    demand_html = demand_more = ""
    if dem:
        # 一句結論用統一的 .impact 框；「為什麼利差是溫度計」的完整說明
        # 收進卡尾展開——說明文字要跟著判定走。先前寫死「它沒有走闊」，
        # 一旦利差真的走闊，同一張卡就會出現自相矛盾。
        _tight = bool(dem.get("tight"))
        if _tight:
            _why = ("利差是買方要求的風險補償。它<b>已經走闊</b>——"
                    "買方開始要求更高的補償才願意接下新供給，"
                    "這是需求端吃不下的第一個訊號。供給若沒有同步收斂，"
                    "壓力會直接落到長端殖利率上。")
        else:
            _why = ("利差是買方要求的風險補償。它<b>還沒走闊</b>——"
                    "代表目前的新增供給仍被吸收得掉；"
                    "一旦走闊，就是買盤開始吃不下的第一個訊號。")
        demand_html = (
            f'<div class="impact {"hawkish" if _tight else "neutral"}">'
            f'{esc(dem["label"])} {esc(dem["value"])}——{esc(dem["detail"])}。</div>')
        demand_more = (
            '<details class="f-more"><summary>利差為什麼是買方的溫度計</summary>'
            f'<div class="f-detail">{_why}</div></details>')

    # ---- 已反映多少 ----
    # 一句結論直接用 gap_note（原因與結果的落差判定），傾向由同一個
    # 差值推出：門檻 ±0.8 跟 analysis/rates.py 產生 gap_note 的門檻一致。
    priced_html = ""
    if sp.priced:
        _gap = sp.score - sp.priced_score
        _pl = "hawkish" if _gap > 0.8 else ("dovish" if _gap < -0.8 else "neutral")
        priced_html = (
            f'<div class="impact {_pl}">{esc(sp.gap_note)}</div>'
            f'<div class="bkgap" style="color:var(--text-primary)">'
            f'<span class="bk-label">供給壓力分數 {sp.score:+.2f}　vs　已反映分數</span>'
            f'<span class="bk-val">{sp.priced_score:+.2f}</span></div>'
            f'<div class="cmoves" style="border-top:none;padding-top:0">'
            f'{_cmoves(sp.priced)}</div>')

    # ---- 科技巨頭的頭條數字：一句結論框 ----
    # 傾向沿用 hs.verdict 的判定；分段門檻（100／70）跟 hs_verdict() 一致。
    # 完整敘述（hs_desc）收進「五家公司的明細」，常駐只留一句。
    _ratio = hs.capex_to_ocf
    _hs_lean = ("hawkish" if getattr(hs, "verdict", "") == "debt_funded"
                else "neutral")
    hs_impact = ""
    if _ratio is not None:
        _tail = ("，超過本業賺進來的現金——缺口靠發債補，長端供給壓力持續。"
                 if _ratio > 100 else
                 ("，逼近本業現金能支應的上限。" if _ratio > 70 else
                  "，本業現金仍蓋得住，對債市的供給壓力有限。"))
        hs_impact = (f'<div class="impact {_hs_lean}">{esc(hs_title)}——'
                     f'合計資本支出已達同期營運現金流的 {_ratio:.0f}%{_tail}</div>')

    # ---- 方法與資料來源（2026-10 v2，使用者：收合裡文字雜亂）----
    # 拆成三小塊，各用表格：① 資料時效（一家一列）② 近期發債（最近 5 筆，其餘再展開）
    # ③ 方法（4 條重點）。先前的長段落說明全部濃縮進 ③。
    gd = d.get("guidance") or {}
    ea = d.get("earnings") or {}
    off = d.get("offerings") or {}
    _ea = {r["name"]: r for r in (ea.get("rows") or [])} if ea.get("available") else {}
    _gdr = {r["name"]: r for r in (gd.get("rows") or [])} if gd.get("available") else {}

    def _md(x: str) -> str:
        x = str(x or "")
        return f"{int(x[5:7])}/{int(x[8:10])}" if len(x) >= 10 and x[4] == "-" else (x or "—")
    _fresh_rows = ""
    for c in hs.companies:
        e = _ea.get(c["name"])
        g = _gdr.get(c["name"])
        if e and e.get("ahead"):
            st, stc = "新財報已公布，表格待 10-Q", "wait"
        elif not c.get("from_sec"):
            st, stc = "後備值", "off"
        else:
            st, stc = "最新", "ok"
        _pe = _md(c.get("period_end")) if c.get("period_end") else "—"
        if stc == "wait":
            _d8 = esc(_md(e["date"]))
            st = ('待 10-Q<small>財報稿 '
                  + (f'<a href="{esc(e["url"])}" target="_blank" rel="noopener">{_d8}</a>' if e.get("url") else _d8)
                  + '</small>')
        else:
            st = esc(st)
        _gv = esc(g["value"].replace(" 億美元", "")) if g else "—"
        # 一家一列：桌機是四欄；手機兩行（公司＋狀態／季末・計畫）
        _fresh_rows += (f'<div class="hs5-r"><b class="hs5-n">{esc(c["name"])}</b>'
                        f'<span class="hs5-m"><span><em>季末</em>{esc(_pe)}</span>'
                        f'<span><em>{esc(str(gd.get("year", "")))} 計畫</em>{_gv}</span></span>'
                        f'<span class="hs4-st {stc}"><i></i><span>{st}</span></span></div>')
    fresh_html = (f'<div class="hs4-sec"><div class="hs4-h">資料時效</div>'
                  f'<div class="hs5 hs5-f"><div class="hs5-r hs5-hd"><span>公司</span>'
                  f'<span class="hs5-m"><span>表格季末</span><span>{esc(str(gd.get("year", "")))} 計畫（億美元）</span></span>'
                  f'<span>狀態</span></div>{_fresh_rows}</div>'
                  + (f'<p class="hs4-n">計畫更新於 {esc(_md(gd.get("as_of", "")))}；表格只用 10-Q（約比財報稿晚兩週）。</p>'
                     if gd.get("available") else "")
                  + '</div>')

    offerings_html = ""
    if off.get("available") and off.get("rows"):
        def _off_row(r) -> str:
            amt = esc(r["amount"]) + (f'<small>{esc(r["usd_note"])}</small>' if r.get("usd_note") else "")
            src = (f'<a href="{esc(r["url"])}" target="_blank" rel="noopener">{esc(r["form"])}</a>'
                   if r.get("url") else esc(r["form"]))
            # 一筆一列：桌機五欄；手機兩行（公司＋金額／日期・類型・原文）
            return (f'<div class="hs5-r"><b class="hs5-n">{esc(r["name"])}</b>'
                    f'<span class="hs5-m"><span>{esc(_md(r["date"]))}</span><span>{esc(r["kind"])}</span>'
                    f'<span>{src}</span></span>'
                    f'<span class="hs5-a{" pend" if r.get("pending") else ""}">{amt}</span></div>')
        _head = ('<div class="hs5-r hs5-hd"><span class="hs5-n">公司</span><span class="hs5-m"><span>日期</span>'
                 '<span>類型</span><span>原文</span></span><span class="hs5-a">金額（原幣）</span></div>')
        rows = off["rows"]
        top = "".join(_off_row(r) for r in rows[:5])
        more = ""
        if rows[5:]:
            more = (f'<details class="f-more"><summary>其餘 {len(rows) - 5} 筆</summary>'
                    f'<div class="hs5 hs5-o">' + "".join(_off_row(r) for r in rows[5:]) + '</div></details>')
        if off.get("insane"):
            _line = f"近 120 天 {off['count']} 筆已定價；金額解析異常，暫不顯示合計"
        else:
            _line = (f"近 120 天 {off['count']} 筆已定價，合計 {esc(off['total_display'])}"
                     + (f"（季報發債的 {esc(off['ratio_display'])}）" if off.get("ratio_display") else "")
                     + "，尚未進季報")
        _extra = "　".join(x for x in (
            f"另 {off['unknown_n']} 筆金額待確認。" if off.get("unknown_n") and not off.get("insane") else "",
            f"另 {off['prelim_n']} 筆已宣布、未定價。" if off.get("prelim_n") else "",
            f"另 {off['other_n']} 件非債券融資不列。" if off.get("other_n") else "") if x)
        offerings_html = (f'<div class="hs4-sec"><div class="hs4-h">近期發債</div>'
                          f'<p class="hs4-lead">{_line}。</p>'
                          f'<div class="hs5 hs5-o">{_head}{top}</div>'
                          + (f'<p class="hs4-n">{_extra}</p>' if _extra else "") + more + '</div>')

    # ---- 財政：一句結論＋缺口併進 stat-row ----
    # 傾向直接沿用 debt.verdict 的判定（widening／drifting／stable），
    # 不在頁面層另算一套。widening 對長端是升壓＝hawkish；其餘中性。
    dg = d.get("debt_gap") or {}
    _debt_lean = ("hawkish" if getattr(d.get("debt"), "verdict", "") == "widening"
                  else "neutral")
    debt_impact = (f'<div class="impact {_debt_lean}">{esc(debt_title)}——'
                   f'{esc(debt_desc)}</div>') if debt_desc else ""
    _debt_stats = list(d["debt_stats"])
    if dg:
        _debt_stats.append({"label": "財政缺口", "value": dg["value"],
                            "color": dg["color"], "note": dg["note"]})

    def _hs_row(c: dict) -> str:
        yoy_txt = "—" if c.get("capex_yoy") is None else f'{c["capex_yoy"]:+.0f}%'
        ratio = c.get("capex_to_ocf")
        ratio_txt = "—" if ratio is None else f"{ratio:.0f}%"
        cls = "neg" if c.get("cash_negative") else ""
        # 期末日逐家標示：各家會計年度不同，同一列的「最新一季」不是同一季。
        # 沒有期末日代表這一列是 config 的手動後備值——那要明講，不能留白，
        # 因為留白看起來只是「少標一個日期」，而不是「這個數字沒被核對過」。
        pe = c.get("period_end") or ""
        tag = esc(pe) if pe else "未取自 SEC"
        name = f'{esc(c["name"])}<span class="dnote">{tag}</span>'
        # 資本支出佔營收：規模差五倍的兩家公司，同樣的「資本支出 200 億」
        # 代表的擴張強度完全不同。營收本來就跟 capex／ocf 一起從 EDGAR 抓，
        # 只是沒印出來——加一欄就把「絕對金額」變成可以互相比較的比率。
        rev = c.get("revenue") or 0
        cap_rev = f"{c['capex'] / rev * 100:.0f}%" if rev else "—"
        return (f'<tr><td>{name}</td>'
                f'<td>{c["capex"] * 10:,.0f}</td>'
                f'<td class="muted-cell">{yoy_txt}</td>'
                f'<td class="muted-cell">{c["ocf"] * 10:,.0f}</td>'
                f'<td class="{cls}">{ratio_txt}</td>'
                f'<td class="muted-cell">{cap_rev}</td>'
                f'<td>{c["issued"] * 10:,.0f}</td></tr>')

    hs_rows = "".join(_hs_row(c) for c in hs.companies)
    # 三個常駐數字（2026-10）：季資本支出合計、佔營運現金流、單季發債合計
    _hs_q = "".join(
        f'<div><span>{esc(x["label"])}</span><b'
        + (' class="over"' if x["label"] == "佔營運現金流" and (hs.capex_to_ocf or 0) > 100 else "")
        + f'>{esc(x["value"])}</b><small>{esc(x.get("note", ""))}</small></div>'
        for x in d["hs_stats"][:3])
    _gn = "".join(f'<li><b>{esc(r["name"])}</b>：{esc(r["note"])}</li>'
                  for r in gd.get("rows") or [] if r.get("note"))
    if gd.get("missing"):
        _gn += f'<li><b>{esc(gd["missing"])}</b>：未提供年度指引，不在合計內。</li>'

    # 資料來源逐家列出，附上 EDGAR 的申報清單連結，讓讀者能自己核對。
    # 這一區的每個結論都建立在這五家的數字上，沒有連結就等於要人相信我。
    _srcs = " ".join(
        (f'<a href="{esc(c["filings_url"])}" target="_blank" rel="noopener">'
         f'{esc(c["name"])}</a>' if c.get("filings_url") else esc(c["name"]))
        for c in hs.companies)
    hs_source_html = (
        f'<div class="src">資料來源：SEC EDGAR 公司申報（10-Q／10-K 現金流量表'
        f'）　·　{_srcs}　·　'
        f'{esc(hs.period_span) if hs.period_span else "期別未標示"}'
        f'　·　{hs.n_from_sec} / {len(hs.companies)} 家取自 SEC</div>')

    # 退回後備值時要分辨「部分」與「全部」——兩者的嚴重程度差很多，
    # 而先前兩種情況的畫面長得一模一樣。全部退回代表整區的數字都是
    # 幾個月前手填的，那時候畫面上的任何結論都不該被當成當前狀況。
    unverified = ""
    if not hs.verified:
        all_stale = hs.n_from_sec == 0
        note = (
            '<b>本區資料尚未更新</b><br>'
            '目前顯示先前整理的資料，並非最新一季財報。'
            '請查看表格標示的期別；上方比率與判讀也以這批資料為依據。'
            if all_stale else
            '<b>部分公司資料尚未更新</b><br>'
            '標為「未取自 SEC」的公司目前顯示先前整理的資料。'
            '請核對表格期別與公司原始財報。')
        unverified = '<div class="warnbox" style="margin-top:14px">' + note + '</div>'

    # ---- 2026-10 改版：各區收合摘要與財政三張事實卡 ----
    _L = d.get("le") or {}
    _c1 = (_L.get("contrib") or {}).get(1)
    _dec_sum = (f'主因：{LE.le.COMP_ZH[_c1["main"]]} {_c1["parts"][_c1["main"]]:+.0f}bp'
                f'　·　10Y 月均 {_c1["nominal"]:+.0f}bp' if _c1 else "三股力量的拆解")
    _sl = {x["label"]: x for x in _L.get("slopes") or []}
    _crv_sum = "　·　".join(f'{k} {v["value"]:+.0f}bp' for k, v in _sl.items()) or "殖利率曲線"
    _gr = (_L.get("global") or {}).get("rows") or []
    _glb_sum = "　·　".join(f'{r["name"]} {r["value"]:.2f}%' for r in _gr[:3]) or "全球長端"
    _wm = _L.get("wam") or {}
    _sup_sum = ((f'Fed WAM {_wm["soma"]["value"]:.1f} 年　·　市場 {_wm["market"]["value"]:.1f} 年')
                if (_wm.get("soma") or {}).get("value") is not None
                and (_wm.get("market") or {}).get("value") is not None else "財政部發行路徑與 Fed 資產端")
    _rc = _L.get("auction_recent") or {}
    _auc_sum = (f'近 3 週：偏弱 {_rc.get("偏弱", 0)}、中性 {_rc.get("中性", 0)}、偏強 {_rc.get("偏強", 0)}'
                if _L.get("auction_recent_n") else "最近各天期的拍賣結果")
    _cs = d.get("credit_stats") or []
    _dem_sum = "　·　".join(f'{x["label"]} {x["value"]}' for x in _cs[:2]) or "信用利差"
    _db = d.get("debt")
    _itr = getattr(_db, "interest_to_revenue", None)
    _rg = getattr(_db, "r_minus_g", None)
    _dfg = getattr(_db, "deficit_gdp", None)
    _debt_stats = [
        {"label": "利息佔稅收", "value": f"{_itr:.1f}%" if _itr is not None else "—",
         "color": ("var(--critical)" if (_itr or 0) > 20 else "inherit"),
         "note": "每收 100 元稅拿去付利息的比例（警戒線 20%）"},
        {"label": "赤字佔 GDP", "value": f"{abs(_dfg):.1f}%" if _dfg is not None else "—",
         "note": "需靠淨發行公債填補的部分"},
        {"label": "r − g（前瞻）", "value": f"{_rg:+.2f}%" if _rg is not None else "—",
         "color": ("var(--critical)" if (_rg or -1) > 0 else "var(--good)"),
         "note": "市場實質利率 − 實質成長；大於零＝債務自我累積"},
    ]
    if _itr is not None and _rg is not None:
        _dl = "hawkish" if (_rg > 0 or _itr > 20) else "neutral"
        debt_impact = (f'<div class="impact {_dl}">利息佔稅收 {_itr:.1f}%，r − g {_rg:+.2f}%——'
                       + ("利率高於成長，債務比會自我累積，長端供給的壓力是結構性的。" if _rg > 0 else
                          "成長仍高於實質利率，債務比不會自己滾大。") + '</div>')
    _debt_sum = (f'利息佔稅收 {_itr:.1f}%　·　r − g {_rg:+.2f}%'
                 if _itr is not None and _rg is not None else "政府財政")

    return f"""
<div class="grid">
  <div class="card">
    <h2 id="decomp" data-open="1" data-sum="{esc(_dec_sum)}">長端利率的組成</h2>
    {LE.decomp(d)}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="hyperscalers" data-sum="{esc(_hs_sum)}">科技巨頭：AI 資本支出與發債</h2>
    <p class="hint">AI 資本支出讓這幾家公司從債市的<b>買方</b>變成<b>賣方</b>——長端供給的另一個來源。</p>
    {hs_impact}
    <div class="hs3-q">{_hs_q}</div>
    {LE.hs_agg_chart(d)}
    {LE.hs_table(d)}
    {unverified}
    {LE.guidance_stale(d).replace('class="warnbox"', 'class="hs3-stale"')}
    <details class="f-more hs4"><summary>資料時效與近期發債</summary>
      {fresh_html}
      {offerings_html}
    </details>
    <details class="f-more hs4"><summary>方法與資料來源</summary>
      <ul class="hs4-m">
        <li><b>口徑</b>：取自 10-Q／10-K 現金流量表；年增對去年同季；佔營運現金流＝合計 ÷ 合計。</li>
        <li><b>季末不同</b>：各家會計年度不同，同一列不是同一季；加總圖依「最近第幾季」對齊。財報新聞稿附日期與原文連結供查閱；表格數字以正式季報為準。</li>
        <li><b>年度計畫</b>：公司法說會公布的資本支出指引。{('<ul>' + _gn + '</ul>') if _gn else ''}</li>
        <li><b>發債</b>：讀說明書判斷是否為債券；預估版不計；美元以定價日匯率換算；只含 SEC 申報。</li>
      </ul>
      {hs_source_html}
    </details>
    {teach(
        "幾家大型科技公司為了 AI 基礎建設花多少錢、自己的現金流夠不夠、缺口是不是靠發債補。",
        "這些公司過去是債券市場的買方（現金太多），AI 資本支出讓它們變成賣方。買方變賣方是雙重打擊——少了買盤、多了供給。",
        "盯加總圖裡「柱子追上橫線」：資本支出超過營運現金流，缺口只能靠發債，供給壓力就會持續。")}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="curve" data-sum="{esc(_crv_sum)}">殖利率曲線</h2>
    {LE.curve(d)}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="global" data-sum="{esc(_glb_sum)}">全球長端</h2>
    {LE.global_(d)}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="supply" data-sum="{esc(_sup_sum)}">債券供給：財政部與 Fed</h2>
    {LE.supply(d)}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="auctions" data-sum="{esc(_auc_sum)}">Coupon 拍賣結果</h2>
    {LE.auctions(d)}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="demand" data-sum="{esc(_dem_sum)}">債券需求：信用利差</h2>
    {LE.credit(d)}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="debt" data-sum="{esc(_debt_sum)}">政府財政</h2>
    <p class="hint">重點不是債務總額，是<b>利息負擔會不會自我累積</b>。</p>
    {debt_impact}
    <div class="stat-row" style="margin-top:14px">{_stats(_debt_stats)}</div>
    <div class="viz-block"><div class="viz-h">聯邦債務佔 GDP（季資料，近 3 年）</div></div>
    {d['debt_chart']}
    {teach(
        "美國政府的赤字規模、利息負擔，以及由此推算的公債發行需求。",
        "財政赤字是長端供給的最大來源，而且跟景氣循環脫鉤了——就算經濟好赤字也降不下來，代表這股供給壓力是結構性的。",
        "盯「利息支出佔比」：利息越滾越大會迫使發債更多，形成自我強化；那是長端利率的長期地心引力。")}
    <details data-m-collapse><summary>名詞：有效利率與 r − g</summary>
      <dl class="gloss" style="margin-top:10px">
        <dt>有效利率</dt>
        <dd>政府整體債務實際付出的平均利率＝利息支出 ÷ 債務總額。
          新債換舊債時它會慢慢往市場利率靠攏，所以升息的痛是分好幾年到的。</dd>
        <dt>r − g</dt>
        <dd>市場實質利率減實質經濟成長。大於零時，就算財政收支平衡，債務佔 GDP 也會自我累積。</dd>
      </dl>
      {(f'<p class="hint" style="margin-top:8px">{esc(d["debt_growth_note"])}</p>'
        if d.get('debt_growth_note') else '')}
    </details>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="lights" data-sum="{esc(light_summary.rstrip('。').replace('項指標：', '項：'))}">關鍵指標檢核</h2>
    <p class="hint">依三股力量分組；本月推動 10Y 最多的那一組排第一。不另設權重——權重由市場這個月的貢獻決定。</p>
    {lights_impact}
    {LE.lights_grouped(d, _light_card)}
    {teach(
        "長端市場的幾個壓力指標逐一對照警戒線。",
        "單看殖利率水準分不出「經濟強」還是「供給壓垮」，一排指標一起看才分得出漲的原因。",
        "紅燈集中在供給類（發行量、期限溢酬）＝結構性壓力；集中在預期類＝在賭政策，兩者的應對完全不同。")}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="glossary" data-sum="這一頁出現的專有名詞與計算方式">名詞解釋</h2>
        <dl class="gloss">
      <dt>期限溢酬</dt>
      <dd>投資人因為承擔「長期持有」的風險而要求的額外補償。
        它與利率預期無關——即使大家預期利率不變，供給過多也會推高它。</dd>
      <dt>通膨損益兩平率</dt>
      <dd>名目公債殖利率減同天期抗通膨債券的殖利率，代表市場對未來平均通膨的定價。
        超過這個數字，買抗通膨債券才划算。</dd>
      <dt>實質利率</dt>
      <dd>剔除通膨補償後的真實資金成本。抗通膨債券（TIPS）的殖利率就是它。</dd>
      <dt>r 減 g</dt>
      <dd>實質利率減實質經濟成長率。大於零時，債務會在財政收支平衡的情況下
        仍然自我累積。</dd>
      <dt>信用利差</dt>
      <dd>公司債殖利率高於同天期公債的部分，也就是投資人要求的信用風險補償。
        本頁指的是廣義的信用利差。</dd>
      <dt>OAS（選擇權調整利差）</dt>
      <dd>針對<b>內含選擇權</b>的債券（例如發行人可提前贖回的公司債），把選擇權的價值扣掉之後的利差。
        ICE BofA 公司債指數裡有很多可贖回債，所以指數用 OAS 表示；本頁把它當作廣義信用利差來讀。</dd>
      <dt>WAM（加權平均剩餘年限）</dt>
      <dd>一籃債券依面額加權的平均剩餘到期年數。Fed 的 WAM 縮短，代表長天期的利率風險留給私人市場。</dd>
      <dt>Tail／Stop-through</dt>
      <dd>拍賣得標殖利率高於拍賣當下市場價＝tail（需求弱）；低於＝stop-through（需求強）。本頁用當日收盤近似，標「≈」。</dd>
      <dt>Indirect／Direct／Primary Dealers</dt>
      <dd>Indirect 多為海外央行與機構透過交易商下單；Direct 是直接投標的國內投資人；Primary Dealers 有義務投標，
        承接剩下的部分——比例越高代表終端需求越弱。</dd>
      <dt>基點（bps）</dt>
      <dd>利率的最小慣用單位，英文縮寫 bp／bps：1 bp＝0.01 個百分點。
        「升 25 個基點」就是升 0.25%，也就是「一碼」。</dd>
      <dt>存續期間需求</dt>
      <dd>市場願意買進長天期債券的總量。政府與企業發債競爭的就是這一池資金，
        供給超過需求時長端殖利率就會被推高。</dd>

      <dt>為什麼財政與科技公司會在同一頁</dt>
      <dd>政府發公債、科技巨頭發投資級公司債，兩者搶的是同一批買盤——
        退休基金、保險公司、外國央行。Fed 雖然已停止縮表，但把到期的 MBS 換成 T-Bills、縮短持有年限，
        長天期的部分一樣要由私人市場吸收。</dd>
      <dt>科技巨頭的年化發債</dt>
      <dd>把單季發債乘以四。發債是機會式的（挑市場條件好的時候一次發）、
        不是每季均勻，所以這個數字只用來比較<b>量級</b>，不宜當成精確預測。</dd>
      <dt>近期發債交易怎麼來的</dt>
      <dd>來源是 SEC EDGAR 的申報清單，只收 424B2／424B5（定價當日的債券發行
        說明書）與配不到說明書的 8-K 項目 2.03（銀行貸款、私募這一類）。
        FWP 是行銷用的條款表、一筆債會發好幾份，424B3 多半是再售登記、
        公司沒拿到新錢，兩者都不計入。<br>
        同一家公司十天以內的申報視為<b>同一筆交易</b>——一筆債會先出預估版、
        再出定價版，多幣別還會分開申報，不合併的話同一筆會被數兩三次。
        合併後的金額是群組內<b>相異</b>金額的總和：多幣別分券要相加，
        但同一個數字重複出現（重新申報、預估與定價金額相同）只算一次。<br>
        金額採債券說明書確認的實際發行規模；貨架註冊額度不計入。
        尚無法確認的交易標示「待確認」，不計入合計。<br>
        這些交易<b>不進</b>供給壓力分數：分數維持由經審核的季報數字決定，
        否則同一筆發債下一季會被算第二次，歷史可比性也會斷掉。</dd>
      <dt>資本支出指引</dt>
      <dd>各公司在法說會上對<b>整年</b>資本支出的公開承諾，跟下方表格的
        「上一季實際花掉的」是兩件事。長端供給壓力來自還沒花的那一段——
        承諾要花而現金流不夠，差額就得到債市籌。<br>
        年度指引取自公司法說會，來源與更新日標在指引區塊裡。
        未公布指引的公司另列，不計入合計。<br>
        跟實績的對照用的是<b>最新一季 × 4</b> 的年化推估。資本支出有季節性
        （第四季通常最重），所以這個倍數是量級參考，不是精確的年對年。</dd>
      <dt>財報新聞稿的時效</dt>
      <dd>公司通常先公布財報新聞稿，再提交正式季報。
        表格以正式季報的現金流量表為準，因此可能晚於新聞稿更新。
        可由公布日期與原文連結查看最新消息，並核對各公司的資料期別。</dd>
    </dl>
  </div>
</div>
"""


def rates_body(d: dict) -> str:
    """
    首卡（2026-10 改版）：10Y／30Y 與近 1 月變動、本月主因一句話、10Y 由三段組成的分段條、
    三股力量各一張小卡、接下來 4 週的事件。其餘完整內容收在下方。
    """
    return LE.hero(d) + compact_full(_rates_body_full(d), "長端拆解、供給、拍賣與財政")


def rates_footer(d: dict) -> str:
    from ..site import source_footer
    _ten = "官方每日資料；與盤中報價分開呈現"
    return source_footer(
        [("公債殖利率", "美國財政部／FRED 每日殖利率", "每日・" + _ten),
         ("損益兩平、TIPS", "FRED（T10YIE、DFII 系列）", "每日・依實際資料日"),
         ("期限溢酬", "聯準會 Kim-Wright 模型（FRED）", "每日・約晚一週"),
         ("預期通膨（模型）", "克里夫蘭聯儲（FRED）", "每月"),
         ("油價", "EIA（FRED）", "每日"),
         ("信用利差", "ICE BofA 指數（FRED）", "每日"),
         ("拍賣結果", "TreasuryDirect", "每次拍賣"),
         ("流通在外、WAM、Fed 持有", "財政部 MSPD、紐約聯儲 SOMA", "每月／每週"),
         ("政府財政", "財政部、BEA（FRED）", "每月／每季"),
         ("全球長端", "OECD（FRED）", "每月・晚約一個月"),
         ("科技巨頭資本支出與發債", "SEC EDGAR（XBRL 申報、說明書）", "財報一申報即更新")],
        ["利率判讀依據通膨、實質利率與期限溢酬的變化；詳細方法見各區說明。",
         "科技巨頭的年度資本支出計畫來自公司法說會。"],
        head="<b>資料來源</b> FRED、TreasuryDirect、紐約聯儲、SEC EDGAR")

