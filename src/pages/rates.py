"""長端利率與債務供給頁的內容產生器（P5）。"""

from __future__ import annotations

from ..site import esc
from .labor import _light_card, _stats
from . import compact_full, focus_evidence, state_chip, teach


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

    # ---- 近期發債申報 ----
    # 這是時效補丁：季報最久落後 135 天，發債當天就要申報。
    # 放在科技巨頭卡的最上方，因為它直接影響「下方那些季報數字
    # 下一期會往哪邊走」——不先講，讀者會以為 83% 是最新狀態。
    # ---- 前瞻資本支出指引 ----
    # 放在科技巨頭卡的最上方，位置比實績還前面：這一頁的論點是
    #「AI 資本支出推高長端供給」，那個故事的主角是接下來要花多少，
    # 不是上一季花了多少。實績是驗證，指引是主詞。
    gd = d.get("guidance") or {}
    guidance_html = ""
    if gd.get("available"):
        # 小卡並排取代表格。先前的三欄表格「公司／指引／備註」有兩個排版
        # 問題：備註只有一家有字、其他列空一大塊；單值（2,000）與區間
        # （1,750–1,850）混排把欄寬撐得參差。小卡跟頁首的指標卡同一套
        # 視覺語言，備註與方法說明收進展開層。
        _cmp = ""
        if gd.get("ratio_display"):
            _cmp = f'　·　年化實績的 {esc(gd["ratio_display"])}'
        chips = "".join(
            f'<div class="focus-metric"><span>{esc(r["name"])}</span>'
            f'<b>{esc(r["value"].replace(" 億美元", ""))}</b>'
            f'<small>億美元</small></div>'
            for r in gd["rows"])
        _notes = "".join(
            f'<li><b>{esc(r["name"])}</b>：{esc(r["note"])}</li>'
            for r in gd["rows"] if r.get("note"))
        _miss_li = (f'<li><b>{esc(gd["missing"])}</b>：未提供年度指引，'
                    f'不在合計內。</li>' if gd.get("missing") else "")
        guidance_html = f"""<h3 style="margin-top:4px">{esc(str(gd['year']))} 年資本支出計畫
      <span class="asof">指引更新於 {esc(gd['as_of'])}</span></h3>
    <p class="hint" style="margin:4px 0 10px">合計 <b>{esc(gd['total_display'])}</b>{_cmp}
      ——<b>還沒花、但已經承諾的錢</b>；推高長端供給的是這個。</p>
    <div class="focus-grid">{chips}</div>
    <details class="f-more"><summary>備註與資料來源</summary>
      <div class="f-detail"><ul style="margin:8px 0;padding-left:18px">
        {_notes}{_miss_li}</ul>
        <b>這幾個數字為什麼要手動維護</b>：前瞻指引不在任何申報欄位裡，
        它是法說會與新聞稿裡用自然語言講的（「approximately」
        「in the range of」），每家寫法不同、每季還會改。
        硬解析的失敗方式是安靜地少一家或抓到錯的口徑。
        更新於 {esc(gd['as_of'])}　·　{esc(gd['source'])}</div>
    </details>"""

    # ---- 財報新聞稿的時效 ----
    # 只在「新聞稿已經公布、但下方表格還沒更新到那一季」時出現。
    # 兩者同季時這一區不顯示——沒有落差就沒有話要講。
    ea = d.get("earnings") or {}
    earnings_html = ""
    if ea.get("available") and ea.get("ahead_n"):
        _erows = "".join(
            f'<tr><td>{esc(r["name"])}</td>'
            f'<td class="muted-cell">{esc(r["date"])}</td>'
            f'<td class="muted-cell">'
            + ("下方表格尚未涵蓋" if r["ahead"] else esc(r["lag_display"]))
            + '</td><td class="muted-cell">'
            + (f'<a href="{esc(r["url"])}" target="_blank" rel="noopener">'
               f'8-K</a>' if r["url"] else "—")
            + '</td></tr>'
            for r in ea["rows"])
        earnings_html = f"""<details class="f-more tline"><summary>
      <b>{esc(ea['ahead_names'])} 已公布新一季財報</b>，表格待 10-Q（約慢兩週）</summary>
      <div class="f-detail">
      財報新聞稿約在季末後三週申報，10-Q 的結構化數字要再等兩週左右。
      這一頁的表格只用 10-Q 的原始標記，所以會慢那兩週。</div>
        <div class="tscroll" style="margin-top:10px"><table>
          <thead><tr><th>公司</th><th>公布日</th><th>對照下方表格</th>
            <th>原文</th></tr></thead>
          <tbody>{_erows}</tbody></table></div>
        <p class="hint" style="margin-top:10px">
          <b>只取日期與連結，不解析新聞稿裡的數字</b>：新聞稿是非結構化文字，
          各家的口徑（是否含融資租賃、GAAP 或 non-GAAP）寫法都不同，
          硬解會拿到一個不知道是什麼的數字混進表格。兩週後 XBRL 就會給出
          經審核、標記明確的版本——寧可慢兩週，不要一個來路不明的數字。</p>
    </details>"""

    off = d.get("offerings") or {}
    offerings_html = ""
    if off.get("available"):
        # 金額欄以**原幣為主、美元為輔**：原幣是說明書封面上白紙黑字的
        # 數字，美元是我們用某一天的匯率換算出來的。把換算值當主角，
        # 等於讓一個會隨匯率漂動的數字蓋掉一個歷史事實。
        def _off_row(r) -> str:
            amt = ('<td class="muted-cell">' if r.get("pending") else "<td>")
            amt += esc(r["amount"])
            if r.get("usd_note"):
                amt += f'<span class="dnote">{esc(r["usd_note"])}</span>'
            amt += "</td>"
            src = ('<td class="muted-cell">'
                   + (f'<a href="{esc(r["url"])}" target="_blank" '
                      f'rel="noopener">{esc(r["form"])}</a>'
                      if r["url"] else esc(r["form"]))
                   + "</td>")
            return (f'<tr><td>{esc(r["name"])}</td>'
                    f'<td class="muted-cell">{esc(r["date"])}</td>'
                    f'<td class="muted-cell">{esc(r["kind"])}</td>'
                    + amt + src + "</tr>")

        _rows = "".join(_off_row(r) for r in off["rows"])
        # 筆數與金額分開講：「5 筆交易、其中 4 筆已確認金額」比
        #「5 筆申報、合計 X（另有 1 筆無法解析）」好讀，而且不會讓人
        # 把合計誤讀成全部。
        if off.get("insane"):
            # 解析結果跟季報數字差太多 → 寧可不報金額。這一段的價值在時效，
            # 沒有金額仍然成立；報一個錯了好幾倍的合計會毀掉整頁的可信度。
            _known = ("金額暫不顯示：解析出的合計與季報申報值差距過大，"
                      "多半是封面解析出錯。逐筆的原文連結仍可查")
            _ratio = _unknown = ""
        else:
            _known = (f"{off['known_n']} 筆已確認金額，合計 "
                      f"{esc(off['total_display'])}")
            _unknown = (f"；另 {off['unknown_n']} 筆金額待確認"
                        if off["unknown_n"] else "")
            _ratio = (f"，相當於最新一季申報發債（{esc(off['ref_display'])}）的 "
                      f"{off['ratio_display']}" if off.get("ratio_display") else "")
        # 預估版不算交易，但要講出來——「還有幾筆正在路上」對供給面是資訊
        _prelim = (f"另有 {off['prelim_n']} 筆已宣布、尚未定價。"
                   if off.get("prelim_n") else "")
        # 被排除的（股票發行、ATM 增發、銀行貸款額度）用**一句話**交代，
        # 不再逐列列出來。
        #
        # 這一區問的是長端供給，而股票與貸款額度不進債市。先前把它們也列進
        # 明細（標「不計入發債」），本意是「讓你看到我看過、也知道為什麼
        # 排除」，實際效果是七筆非債券混在十幾列裡、「金額」欄一半寫著
        # 「不計入發債」——讀者要一列一列篩才找得到真正的債券。
        # 為了證明沒有遺漏而讓主線更難讀，是划不來的交易。
        _other = (f"另有 {off['other_n']} 件非債券的融資申報（股票發行、"
                  f"ATM 增發或貸款額度），不進債市，明細不列。"
                  if off.get("other_n") else "")
        _ccy = (f"幣別分布：{esc(off['ccy_note'])}。"
                if off.get("multi_ccy") else "")
        _nofx = (f"其中 {off['no_fx']} 筆換不到匯率，不進合計。"
                 if off.get("no_fx") else "")
        # 摘要句只留一行（筆數＋合計＋佔比），幣別分布、待確認、預估版、
        # 非債券排除這些第二層資訊全部收進展開——它們有價值，但不值得
        # 每天佔著常駐版面。
        _head_line = (f"合計 {esc(off['total_display'])}"
                      + (f"（季報的 {esc(off['ratio_display'])}）"
                         if off.get("ratio_display") and not off.get("insane")
                         else ""))
        if off.get("insane"):
            _head_line = "金額暫不顯示（解析異常）"
        offerings_html = f"""<details class="f-more tline"><summary>
      <b>近 120 天 {off['count']} 筆已定價發債</b>，{_head_line}，尚未入下方季報</summary>
      <div class="f-detail">
      {_known}{_ratio}{_unknown}。{_ccy}{_nofx}{_prelim}{_other}最近一筆在
      {esc(off['latest'])}。</div>
      <details class="f-more" style="margin-top:6px"><summary>逐筆債券明細</summary>
        <div class="tscroll" style="margin-top:10px"><table>
          <thead><tr><th>公司</th><th>日期</th><th>類型</th>
            <th>金額（原幣）</th><th>原文</th></tr></thead>
          <tbody>{_rows}</tbody></table></div>
        <p class="hint" style="margin-top:10px">
          <b>表格號不代表證券種類</b>：424B2／424B5 只代表「定價後的公開
          說明書補充」，賣的可能是債券、普通股、特別股、存託股或 ATM 增發
          計畫。這裡是<b>讀文件內容</b>來分類的——要出現
          <code>aggregate principal amount</code>、<code>Senior Notes</code>
          或 <code>Notes due 20xx</code> 這類證據才算債券。<br>
          <b>這張表只列債券</b>：股票發行、ATM 增發、銀行貸款與循環額度
          （8-K 項目 2.03）既不計入金額，也**不列在明細裡**——它們不進債市，
          對長端供給沒有貢獻。上方那句話會告訴你被排除了幾件、是哪幾類，
          知道有這回事就夠了，不必逐列翻過去。<br>
          <b>預估版不計入筆數與金額</b>：同一筆債會先申報一份尚未定價的
          預估版（封面的定價欄是空的），兩三天後才有定價版。兩份都算的話
          同一筆會被數兩次。已經有對應定價版的預估版直接不列。<br>
          <b>金額以原幣為準</b>：分券金額逐檔相加，同一檔券在文件裡重複
          出現只算一次（依幣別、金額、到期年、票息去重）。<br>
          <b>美元等值一律用「該筆定價日當天」的匯率換算</b>（FRED 每日匯率；
          碰到週末或假日往前取最近一個交易日）。不是用今天的匯率——發行人
          在定價那天就把金額鎖住了，用今天的匯率會讓一筆已經完成的發行
          <b>每天早上都變一個數字</b>，而變動的原因跟債券市場無關；上面那個
          「相當於最新一季申報發債的百分之幾」也會變成拿重估值去除歷史值。
          規則固定，所以每一列都可以自己去 FRED 對，不必逐列重印匯率。
          只有匯率取自跟定價日差七天以上的日期時（資料有缺口），
          那一列才會單獨標出來。<br>
          <b>資料來源只有 SEC 申報</b>：這裡是「依 SEC filings 偵測之公開
          融資事件」，不是「全球所有債券發行」。部分海外發行（歐洲、日本
          市場的當地發行）不一定會產生可辨識的 SEC 申報。</p>
      </details>
    </details>"""

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

    # 資料來源逐家列出，附上 EDGAR 的申報清單連結，讓讀者能自己核對。
    # 這一區的每個結論都建立在這五家的數字上，沒有連結就等於要人相信我。
    _srcs = " ".join(
        (f'<a href="{esc(c["filings_url"])}" target="_blank" rel="noopener">'
         f'{esc(c["name"])}</a>' if c.get("filings_url") else esc(c["name"]))
        for c in hs.companies)
    hs_source_html = (
        f'<div class="src">資料來源：SEC EDGAR 的 XBRL 申報（10-Q／10-K 現金流量表'
        f'原始標記）　·　{_srcs}　·　'
        f'{esc(hs.period_span) if hs.period_span else "期別未標示"}'
        f'　·　{hs.n_from_sec} / {len(hs.companies)} 家取自 SEC</div>')

    # 退回後備值時要分辨「部分」與「全部」——兩者的嚴重程度差很多，
    # 而先前兩種情況的畫面長得一模一樣。全部退回代表整區的數字都是
    # 幾個月前手填的，那時候畫面上的任何結論都不該被當成當前狀況。
    unverified = ""
    if not hs.verified:
        _all_stale = hs.n_from_sec == 0
        unverified = (
            '<div class="warnbox" style="margin-top:14px'
            + ('；border-left-color:var(--critical)' if _all_stale else '')
            + '">'
            + ('<b>這一區的數字全部不是最新的</b><br>'
               '五家公司<b>全部</b>擷取失敗，整區改用 '
               '<code>config/rates.yaml</code> 的手動後備值——那是上一次人工'
               '填入的數字，不是最新一季的財報。上方的比率與結論都是照這批'
               '舊數字算的，請先不要據以判斷。<br>'
               '最常見的原因是 SEC 擋掉了請求（<code>SEC_USER_AGENT</code> '
               '沒設定時會送出空的 User-Agent）。執行紀錄裡會有一行 '
               '<code>科技巨頭：N 家全部擷取失敗</code>。'
               if _all_stale else
               '<b>部分數字未取自 SEC</b><br>'
               '正常情況下這一區的數字由 SEC EDGAR 的 XBRL 申報自動擷取。'
               '本次有公司抓取失敗（或設定為離線／手動模式），'
               '該公司改用 <code>config/rates.yaml</code> 的後備值，'
               '在表格裡標為「未取自 SEC」。')
            + '</div>')

    return f"""
<div class="verdict {lean_cls}">
  <div class="v-eyebrow">{esc(d['as_of'])}　·　一句話結論</div>
  <div class="v-main">{esc(title)}</div>
  <div class="v-why">{esc(why)}</div>
  {pressure_axis}
  <div class="v-count">
    這一頁看的是<b>長端</b>。前面三個模組決定政策利率的方向，
    但 30 年期殖利率還受債券供給與期限溢酬影響，並非只由政策利率決定。
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="decomp" data-open="1" data-sum="{esc(_dec_sum)}">長端利率的組成</h2>
    <p class="hint"><b>期限溢酬（持有長債多要求的補償）不一定會隨政策利率同步下降</b>——這一頁在追那一段。</p>
    {decomp_impact}
    {decomp_head_html}
    <div class="stat-row" style="margin-top:18px">{_stats(d['decomp_stats'])}</div>
    {teach(
        "把 10 年期／30 年期殖利率拆成三塊：市場預期的短率路徑、通膨補償、以及「多承擔長天期」要求的額外報酬（期限溢酬）。",
        "長端利率不是聯準會直接決定的。降息了長端卻不跌的情況一再發生——多半是期限溢酬在漲，也就是市場對「長期借錢給政府」要求更高的補償。",
        "看哪一塊在動：預期路徑動＝在賭聯準會；期限溢酬動＝在反映供需與財政，跟降不降息可以無關。")}
    <details data-m-collapse><summary>三種上升的意義有什麼不同</summary>
      <p class="hint" style="margin:10px 0 0">{esc(d['decomp_note'])}</p>
      <dl class="gloss" style="margin-top:10px">
        <dt>實質利率上升</dt>
        <dd>市場預期實質成長或資金需求增強。對股市未必是壞事，
          但會壓抑利率敏感的產業。</dd>
        <dt>通膨補償上升</dt>
        <dd>市場預期通膨走高。這是聯準會的責任範圍，會提高升息的可能性。</dd>
        <dt>期限溢酬上升</dt>
        <dd>是投資人持有長債要求的額外補償，可能反映利率、通膨與模型不確定性，
          也可能受到債券供給與財政疑慮影響。
          <b>它不一定會隨聯準會降息同步下降。</b></dd>
        <dt>三段為什麼不能相加</dt>
        <dd>名目殖利率 ＝ 實質利率 ＋ 通膨補償，這兩段是完整的拆解。
          期限溢酬是<b>另一個角度</b>的拆解，衡量的是投資人持有長債要求的
          額外補償，跟前兩段有重疊。三個數字加起來不會等於名目殖利率，
          也不該這樣用。</dd>
      </dl>
    </details>
  </div>
</div>
{supply_html}
<div class="grid g2">
  <div class="card">
    <h2 id="demand" data-sum="{esc(_dem_sum)}">債券需求：信用利差</h2>
    <p class="hint">供給增加不必然推高利率——信用利差是買方的溫度計。</p>
    {demand_html}
    <div class="stat-row" style="margin-top:16px">{_stats(d['credit_stats'])}</div>
    <div style="margin-top:16px">{d['credit_chart']}</div>
    {teach(
        "供給暴增的另一半問題：買方（銀行、外國央行、基金）承接的意願與能力。",
        "同樣的發行量，買盤強就相安無事，買盤縮手殖利率就得升到有人願意接為止。拍賣結果是最直接的溫度計。",
        "看拍賣的投標倍數與尾差：連續幾場疲弱，代表市場開始要求更高的補償，長端要另外加壓。")}
    {demand_more}
  </div>

  <div class="card">
    <h2 id="priced" data-sum="{esc(_pr_sum)}">供給壓力 vs 市場定價</h2>
    <p class="hint">市場已經替這些壓力定了多少價。</p>
    {priced_html}
    <div class="stat-row" style="margin-top:16px">{_stats(d['curve_stats'])}</div>
    {teach(
        "把「供給面算出來的壓力」跟「市場價格已經反映的壓力」放在同一把尺上比。",
        "壓力大不代表利率會漲——市場早就定價完的利空，落地時反而不動。會動的是「還沒被反映」的那一段，所以兩個分數的差距比各自的水準重要。",
        "差距超過 ±0.8 才有意義：供給分數高於已反映＝上行風險還在後面；已反映高於供給＝價格可能超前，供給不再惡化就有回落空間。")}
    <details data-m-collapse><summary>其他天期</summary>
      <div class="stat-row" style="margin-top:12px">{_stats(d['curve_short'])}</div>
      <p class="hint" style="margin-top:12px">短天期由政策利率預期決定，
        見<a href="/fomc/">聯準會文本</a>頁。</p>
    </details>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="debt" data-sum="{esc(_debt_sum)}">供給端細節一：政府財政</h2>
    <p class="hint">重點不是債務總額，是<b>會不會失控</b>。</p>
    {debt_impact}
    <div class="stat-row" style="margin-top:14px">{_stats(_debt_stats)}</div>
    <h3 style="margin-top:18px">聯邦債務佔 GDP 比（{esc(d.get('debt_span', ''))}）</h3>
    {d['debt_chart']}
    {teach(
        "美國政府的赤字規模、利息負擔，以及由此推算的公債發行需求。",
        "財政赤字是長端供給的最大來源，而且跟景氣循環脫鉤了——就算經濟好赤字也降不下來，代表這股供給壓力是結構性的。",
        "盯「利息支出佔比」：利息越滾越大會迫使發債更多，形成自我強化；那是長端利率的長期地心引力。")}
    <details data-m-collapse><summary>財政損益兩平的算法</summary>
      <div class="stat-row" style="margin-top:12px">{_stats(d['debt_steps'])}</div>
      <dl class="gloss" style="margin-top:14px">
        <dt>公式</dt>
        <dd>穩定所需的基本盈餘 ≈ 債務比 × (有效利率 − 名目成長) ÷ (1 + 名目成長)</dd>
        <dt>基本盈餘</dt>
        <dd>排除利息支出後的財政餘額（也就是「不算利息的話，政府是賺是賠」）。
          利息是過去累積的結果，把它排除才看得出當期財政的實際狀況。</dd>
        <dt>有效利率</dt>
        <dd>政府整體債務實際付出的平均利率＝利息支出 ÷ 債務總額。
          新債換舊債時它會慢慢往市場利率靠攏，所以升息的痛是分好幾年到的。</dd>
        <dt>為什麼利率高於成長很危險</dt>
        <dd>當有效利率超過名目成長，利息負擔的成長速度會超過稅基，
          債務比就會自我累積——即使財政收支平衡也一樣。</dd>
      </dl>
      <p class="hint" style="margin-top:10px">{esc(d['debt_note'])}</p>
      {(f'<p class="hint" style="margin-top:12px">{esc(d["debt_divergence"])}</p>'
        if d.get('debt_divergence') else '')}
      {(f'<p class="hint" style="margin-top:8px">{esc(d["debt_growth_note"])}</p>'
        if d.get('debt_growth_note') else '')}
    </details>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="hyperscalers" data-sum="{esc(_hs_sum)}">供給端細節二：科技巨頭</h2>
    <p class="hint">關鍵不是金額，是<b>融資方式</b>——
      這幾家從債市<b>買方</b>變成<b>賣方</b>的轉折點。</p>
    {hs_impact}
    {guidance_html}
    <div class="tlines">
      <div class="tlines-k">資料時效</div>
      {earnings_html}
      {offerings_html}
    </div>
    {teach(
        "幾家大型科技公司為了 AI 基礎建設花多少錢、自己的現金流夠不夠、缺口是不是靠發債補。",
        "這些公司過去是債券市場的買方（現金太多），AI 資本支出讓它們變成賣方。買方變賣方是雙重打擊——少了買盤、多了供給。",
        "盯「資本支出佔營運現金流」：接近或超過 100%，代表花的比賺的多，缺口只能靠發債，供給壓力就會持續。")}
    <details data-m-collapse><summary>五家公司的明細</summary>
      <p class="hint" style="margin:10px 0 0">{esc(hs_desc)}</p>
      <div class="stat-row" style="margin-top:12px">{_stats(d['hs_stats'])}</div>
      <div class="tscroll" style="margin-top:16px">
        <table>
          <thead><tr><th>公司</th><th>資本支出</th><th>年增</th>
            <th>營運現金流</th><th>佔營運現金流</th><th>佔營收</th>
            <th>單季發債</th></tr></thead>
          <tbody>{hs_rows}</tbody></table>
      </div>
      <div class="src">金額單位：億美元　·　公司名稱下方是該公司自己的
        <b>會計季末日</b>（各家年度起點不同，同一列不是同一季）　·
        「年增」是本季對<b>去年同一季</b>，不是對上一季，也不是全年指引　·
        「佔營運現金流」＝資本支出 ÷ 營運現金流，超過 100% 代表依
        「營運現金流 − 現金資本支出」的簡化口徑自由現金流為負　·
        「佔營收」＝同一季的資本支出 ÷ 營收，用來比較規模不同的公司
        誰擴張得比較猛　·　所有百分比都由左邊的原始金額算出來，
        沒有手填的百分比</div>
      {hs_source_html}
    </details>
    {unverified}
  </div>
</div>

<div class="grid g2">
  <div class="card">
    <h2 id="lights" data-sum="{esc(light_summary.rstrip('。').replace('項指標：', '項：'))}">關鍵指標檢核</h2>
    <p class="hint">目前的整體狀態（不限本月）：逐項對照警戒線。</p>
    {lights_impact}
    <details data-m-collapse open><summary>逐項展開</summary>
      <div class="lights" style="margin-top:12px">{lights_html}</div>
    </details>
    {teach(
        "長端市場的幾個壓力指標逐一對照警戒線。",
        "單看殖利率水準分不出「經濟強」還是「供給壓垮」，一排指標一起看才分得出漲的原因。",
        "紅燈集中在供給類（發行量、期限溢酬）＝結構性壓力；集中在預期類＝在賭政策，兩者的應對完全不同。")}
  </div>

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
      <dt>基本盈餘</dt>
      <dd>排除利息支出後的財政餘額。用來衡量「當期財政」的狀況，
        不受過去累積的債務干擾。</dd>
      <dt>r 減 g</dt>
      <dd>實質利率減實質經濟成長率。大於零時，債務會在財政收支平衡的情況下
        仍然自我累積。</dd>
      <dt>利差（OAS）</dt>
      <dd>公司債殖利率高於同天期公債的部分，也就是投資人要求的信用風險補償。</dd>
      <dt>基點（bps）</dt>
      <dd>利率的最小慣用單位，英文縮寫 bp／bps：1 bp＝0.01 個百分點。
        「升 25 個基點」就是升 0.25%，也就是「一碼」。</dd>
      <dt>存續期間需求</dt>
      <dd>市場願意買進長天期債券的總量。政府與企業發債競爭的就是這一池資金，
        供給超過需求時長端殖利率就會被推高。</dd>

      <dt>為什麼財政與科技公司會在同一頁</dt>
      <dd>政府發公債、科技巨頭發投資級公司債，兩者搶的是同一批買盤——
        退休基金、保險公司、外國央行。第三個來源是聯準會縮表：
        到期不續作的公債改由私人市場接手，對買盤而言跟財政部多發債是同一件事。</dd>
      <dt>供給壓力分數怎麼算</dt>
      <dd>只由供給來源構成（政府財政缺口、科技巨頭融資缺口、聯準會縮表）。
        期限溢酬與 30 年減 10 年斜率是被這些供給推高的<b>價格</b>、不是原因，
        算進同一個分數等於重複計算，所以改列成「供給壓力 vs 市場定價」。
        兩者背離時（壓力大但價格還沒反映），那個落差本身就是訊號。</dd>
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
        金額由說明書封面解析，只認「$金額 ＋ 票息 ＋ Notes due 年份」這種
        分券寫法並加總；<b>刻意不取封面上最大的數字</b>——那個往往是
        貨架註冊額度（"up to $40,000,000,000"），不是這一筆的規模，
        而且同一個額度在每份文件上都會再被讀成一筆新交易。
        解析不到就標「待確認」，<b>不用推估值填補</b>，也不計入合計。<br>
        這些交易<b>不進</b>供給壓力分數：分數維持由經審核的季報數字決定，
        否則同一筆發債下一季會被算第二次，歷史可比性也會斷掉。</dd>
      <dt>資本支出指引</dt>
      <dd>各公司在法說會上對<b>整年</b>資本支出的公開承諾，跟下方表格的
        「上一季實際花掉的」是兩件事。長端供給壓力來自還沒花的那一段——
        承諾要花而現金流不夠，差額就得到債市籌。<br>
        這幾個數字<b>不在任何申報欄位裡</b>，是用自然語言講的
        （「approximately」「in the range of」），所以由人工季更，
        來源與更新日標在指引區塊裡。沒有指引的公司會單獨列出，
        不會被默默算成零。<br>
        跟實績的對照用的是<b>最新一季 × 4</b> 的年化推估。資本支出有季節性
        （第四季通常最重），所以這個倍數是量級參考，不是精確的年對年。</dd>
      <dt>財報新聞稿的時效</dt>
      <dd>財報新聞稿（8-K 項目 2.02）約在季末後三週申報，10-Q 的結構化
        數字（XBRL）要再等兩週左右。下方表格只用 10-Q 的原始標記，
        所以中間那兩週會落後一季。<br>
        這一區只取<b>公布日期與原文連結</b>，<b>不解析新聞稿裡的數字</b>：
        新聞稿是非結構化文字，各家口徑不同，硬解會拿到一個不知道是什麼的
        數字混進表格。判斷「新聞稿是不是講下一季」只比對兩個日期——
        新聞稿日期比該公司自己的季末日晚 60 天以上就是下一季
        （一季約 91 天、新聞稿約季末後 20–30 天，60 天在兩群中間）。</dd>
    </dl>
  </div>
</div>
"""


def rates_body(d: dict) -> str:
    """長端首卡把政府財政與 Hyperscalers 的現金流、CapEx、發債放在同一尺度。"""
    sp, debt, hs = d["pressure"], d["debt"], d["hyperscalers"]
    title, why = d.get("pressure_text", ("供給壓力資料不足", ""))
    why_short = why.split("。")[0] + "。" if why else ""
    level_text = {"high":"偏高","moderate":"中等","low":"偏低"}.get(sp.level, "資料不足")
    curve = d.get("curve")
    y10 = (curve.levels.get("10Y") if curve else None)
    supply = d.get("supply_side") or {}
    def pct(v, signed=False):
        if v is None:
            return "—"
        return f"{v:+.1f}%" if signed else f"{v:.1f}%"
    fiscal_note = ("缺口：基本盈餘低於穩定債務比所需水準" if (debt.pb_gap or 0) < 0
                   else "緩衝：基本盈餘高於穩定債務比所需水準")
    metrics = "".join([
        state_chip("長端供給壓力", level_text, f"綜合分數 {sp.score:+.2f}", "watch" if sp.level == "high" else "neutral"),
        state_chip("10 年期殖利率", f"{y10:.2f}%" if y10 is not None else "—", f"資料日 {d.get('as_of', '—')}"),
        state_chip("美國財政赤字", pct(abs(debt.deficit_gdp) if debt.deficit_gdp is not None else None),
                   "佔 GDP；年度債券供給主體", "watch"),
        state_chip("財政穩定差", pct(debt.pb_gap, True), fiscal_note,
                   "watch" if (debt.pb_gap or 0) < 0 else "neutral"),
    ])
    hs_span = hs.period_span or hs.as_of or "期別待更新"
    flow = (f'<div class="grid-flow"><div class="flow-box"><strong>政府年度融資</strong>'
            f'<div class="flow-values">{esc(supply.get("gov_display", "—"))}<br>{esc(supply.get("gov_note", ""))}</div></div>'
            '<div class="flow-arrow">＋</div>'
            f'<div class="flow-box"><strong>Hyperscalers 資本支出與現金流</strong><div class="flow-values">'
            f'CapEx {hs.total_capex*10:,.0f} 億美元 · OCF {hs.total_ocf*10:,.0f} 億美元<br>'
            f'CapEx / OCF {pct(hs.capex_to_ocf)} · 簡化 FCF 為負 {hs.n_cash_negative}/{len(hs.companies)} 家</div></div>'
            '<div class="flow-arrow">→</div>'
            f'<div class="flow-box"><strong>新增公司債供給</strong><div class="flow-values">'
            f'單季 {hs.total_issued*10:,.0f} 億美元 · 年化 {esc(supply.get("hs_display", "—"))}<br>'
            f'政府赤字規模比 {esc(supply.get("ratio_display", "—"))}</div></div></div>')
    logic = (f'<div class="logic-strip"><div class="logic-step"><b>同一個問題</b><span>政府公債與大型科技公司債競爭同一批固定收益買盤。</span></div>'
             f'<div class="logic-step"><b>目前結論</b><span>{esc(why)}</span></div>'
             '<div class="logic-step"><b>與九宮格的關係</b><span>只影響長端與曲線形狀，不改政策利率格位。</span></div></div>')
    evidence = focus_evidence(flow + logic, "查看供給傳導與判斷依據")
    tags = (f'<div class="data-line"><span class="data-tag">利率 {esc(d.get("as_of", "—"))}</span>'
            f'<span class="data-tag">公司期末 {esc(hs_span)}</span>'
            f'<span class="data-tag">SEC 實際資料 {hs.n_from_sec}/{len(hs.companies)} 家</span></div>')
    hero = (f'<div class="grid"><div class="card focus-card"><div class="focus-eyebrow">Long-end supply</div>'
            f'<h2 class="focus-title">長端供給壓力{level_text}</h2><p class="focus-sub">{esc(why_short)}</p>'
            f'<div class="focus-grid">{metrics}</div>{evidence}{tags}</div></div>')
    return hero + compact_full(_rates_body_full(d), "財政、發債、現金流與利率完整拆解")


def rates_footer(d: dict) -> str:
    return (
        "資料來源：FRED（美國財政部、聯準會、BEA、ICE BofA 指數）。<br>"
        "科技巨頭的資本支出、營運現金流與發債取自 SEC EDGAR 的 XBRL 申報，"
        "每季財報一申報就會自動更新。<br>"
        "本頁僅為數據整理，不構成投資建議。"
    )
