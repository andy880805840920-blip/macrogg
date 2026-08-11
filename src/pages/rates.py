"""長端利率與債務供給頁的內容產生器（P5）。"""

from __future__ import annotations

from ..site import esc
from .labor import _light_card, _stats


def rates_body(d: dict) -> str:
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
    <h2 id="supply">誰在發債</h2>
    <p class="hint">政府發公債、科技巨頭發投資級公司債，
      <b>兩者競爭的是同一批固定收益買盤</b>——退休基金、保險公司、外國央行。
      這就是為什麼美國財政與幾家科技公司的財報會出現在同一頁。
      第三個來源是聯準會縮表：到期不續作的公債，等於改由私人市場接手，
      對買盤來說跟財政部多發債是同一件事。</p>
    <div class="stat-row">
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
    <p class="hint" style="margin-top:14px">{_sum_html}</p>
    <p class="hint" style="margin-top:12px">壓力分數的{esc(_n_parts)}個來源：</p>
    <div class="cmoves" style="border-top:none;padding-top:0">{parts}</div>
    <div class="src">科技巨頭的年化是把單季發債乘以四。發債是機會式的
      （挑市場條件好的時候一次發），不是每季均勻，所以這個數字只用來
      比較<b>量級</b>，不宜當成精確預測。</div>
  </div>
</div>"""

    # ---- 需求端 ----
    dem = (sp.demand or [{}])[0]
    demand_html = ""
    if dem:
        # 說明文字要跟著判定走。先前寫死「它沒有走闊」，
        # 一旦利差真的走闊，同一張卡就會出現
        # 「走闊，買方開始要求更高補償…它沒有走闊」這種自相矛盾。
        if dem.get("tight"):
            _why = ("利差是買方要求的風險補償。它<b>已經走闊</b>——"
                    "買方開始要求更高的補償才願意接下新供給，"
                    "這是需求端吃不下的第一個訊號。供給若沒有同步收斂，"
                    "壓力會直接落到長端殖利率上。")
        else:
            _why = ("利差是買方要求的風險補償。它<b>還沒走闊</b>——"
                    "代表目前的新增供給仍被吸收得掉；"
                    "一旦走闊，就是買盤開始吃不下的第一個訊號。")
        demand_html = (
            f'<div class="verdict {"hawkish" if dem.get("tight") else "balanced"}"'
            f' style="margin-top:4px">'
            f'<div class="v-main" style="font-size:19px">{esc(dem["detail"])}</div>'
            f'<div class="v-why" style="margin-top:8px">'
            f'{esc(dem["label"])} {esc(dem["value"])}。{_why}</div></div>')

    # ---- 已反映多少 ----
    priced_html = (
        f'<div class="cmoves" style="border-top:none;padding-top:0">'
        f'{_cmoves(sp.priced)}</div>'
        f'<p class="hint" style="margin-top:12px">'
        f'已反映分數 {sp.priced_score:+.2f}　·　供給壓力分數 {sp.score:+.2f}<br>'
        f'{esc(sp.gap_note)}</p>'
        if sp.priced else "")

    # ---- 科技巨頭的頭條數字 ----
    _ratio = hs.capex_to_ocf
    hs_head_html = ""
    if _ratio is not None:
        _c = ("var(--critical)" if _ratio > 100 else
              ("var(--serious)" if _ratio > 80 else "var(--text-primary)"))
        hs_head_html = (
            f'<div class="bkgap" style="color:{_c};margin-top:4px;'
            f'padding-top:0;border-top:none">'
            f'<span class="bk-label">資本支出佔營運現金流</span>'
            f'<span class="bk-val">{_ratio:.0f}%</span>'
            f'<span class="bk-verdict" style="font-weight:400;font-size:12.5px;'
            f'color:var(--muted)">超過 100% 代表自由現金流轉負，擴張必須舉債</span></div>')

    # ---- 近期發債申報 ----
    # 這是時效補丁：季報最久落後 135 天，發債當天就要申報。
    # 放在科技巨頭卡的最上方，因為它直接影響「下方那些季報數字
    # 下一期會往哪邊走」——不先講，讀者會以為 83% 是最新狀態。
    off = d.get("offerings") or {}
    offerings_html = ""
    if off.get("available"):
        _rows = "".join(
            f'<tr><td>{esc(r["name"])}</td>'
            f'<td class="muted-cell">{esc(r["date"])}</td>'
            f'<td class="muted-cell">{esc(r["kind"])}</td>'
            f'<td>{esc(r["amount"])}</td>'
            f'<td class="muted-cell">'
            + (f'<a href="{esc(r["url"])}" target="_blank" rel="noopener">'
               f'{esc(r["form"])}</a>' if r["url"] else esc(r["form"]))
            + '</td></tr>'
            for r in off["rows"])
        _unknown = (f'，其中 {off["unknown_n"]} 筆的金額無法從申報書解析'
                    if off["unknown_n"] else "")
        _ratio = (f'，相當於最新一季申報發債（{esc(off["ref_display"])}）的 '
                  f'{off["ratio_display"]}' if off.get("ratio_display") else "")
        offerings_html = f"""<div class="warnbox" style="margin:0 0 16px">
      <b>近 120 天有 {off['count']} 筆發債申報，尚未反映在下方的季報數字裡</b><br>
      已解析到金額的合計 {esc(off['total_display'])}{_unknown}{_ratio}。
      最近一筆在 {esc(off['latest'])}。
      <details class="f-more" style="margin-top:10px"><summary>逐筆明細</summary>
        <div class="tscroll" style="margin-top:10px"><table>
          <thead><tr><th>公司</th><th>申報日</th><th>文件</th>
            <th>金額</th><th>原文</th></tr></thead>
          <tbody>{_rows}</tbody></table></div>
        <p class="hint" style="margin-top:10px">
          來源：SEC EDGAR 的申報清單。424B2／424B5 是債券發行說明書本身
          （定價當日申報），8-K 項目 2.03 是「產生直接財務義務」（四個營業日內）。
          金額由說明書封面解析，解析不到就留空——<b>不會用推估值填補</b>。
          這些事件<b>不計入</b>上方的供給壓力分數：分數維持由經審核的季報數字
          決定，否則同一筆發債下一季會被算第二次。</p>
      </details>
    </div>"""

    # ---- 財政缺口 ----
    dg = d.get("debt_gap") or {}
    debt_gap_html = (
        f'<div class="bkgap" style="color:{dg["color"]}">'
        f'<span class="bk-label">財政缺口</span>'
        f'<span class="bk-val">{esc(dg["value"])}</span>'
        f'<span class="bk-verdict" style="font-weight:400;font-size:12.5px;'
        f'color:var(--muted)">{esc(dg["note"])}</span></div>'
        if dg else "")

    def _hs_row(c: dict) -> str:
        yoy_txt = "—" if c.get("capex_yoy") is None else f'{c["capex_yoy"]:+.0f}%'
        ratio = c.get("capex_to_ocf")
        ratio_txt = "—" if ratio is None else f"{ratio:.0f}%"
        cls = "neg" if c.get("cash_negative") else ""
        # 期末日逐家標示：各家會計年度不同，同一列的「最新一季」不是同一季
        pe = c.get("period_end") or ""
        name = (f'{esc(c["name"])}<span class="dnote">{esc(pe)}</span>'
                if pe else esc(c["name"]))
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

    unverified = ""
    if not hs.verified:
        unverified = ('<div class="warnbox" style="margin-top:14px">'
                      '<b>部分數字未取自 SEC</b><br>'
                      '正常情況下這一區的數字由 SEC EDGAR 的 XBRL 申報自動擷取。'
                      '本次有公司抓取失敗（或設定為離線／手動模式），'
                      '該公司改用 <code>config/rates.yaml</code> 的後備值。</div>')

    return f"""
<div class="verdict {lean_cls}">
  <div class="v-eyebrow">{esc(d['as_of'])}　·　一句話結論</div>
  <div class="v-main">{esc(title)}</div>
  <div class="v-why">{esc(why)}</div>
  {pressure_axis}
  <div class="v-count">
    這一頁看的是<b>長端</b>。前面三個模組決定政策利率的方向，
    但 30 年期殖利率由債券供給與期限溢酬決定，聯準會控制不了。
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="decomp">長端利率為什麼在這裡</h2>
    <p class="hint">名目殖利率可以拆成三段，三段的政策意涵完全不同。
      <b>只有期限溢酬那一段是供需造成的，也只有那一段聯準會降息壓不下來</b>——
      這一整頁就是在追那一段。</p>
    {decomp_head_html}
    <div class="stat-row" style="margin-top:18px">{_stats(d['decomp_stats'])}</div>
    <p class="hint" style="margin-top:14px">{esc(d['decomp_note'])}</p>
    <details data-m-collapse><summary>三種上升的意義有什麼不同</summary>
      <dl class="gloss" style="margin-top:10px">
        <dt>實質利率上升</dt>
        <dd>市場預期實質成長或資金需求增強。對股市未必是壞事，
          但會壓抑利率敏感的產業。</dd>
        <dt>通膨補償上升</dt>
        <dd>市場預期通膨走高。這是聯準會的責任範圍，會提高升息的可能性。</dd>
        <dt>期限溢酬上升</dt>
        <dd>既不是預期通膨也不是預期成長，純粹是投資人要求更多補償
          才願意持有長債——通常來自供給過多或財政疑慮。
          <b>這一種聯準會降息也壓不下來。</b></dd>
      </dl>
    </details>
  </div>
</div>
{supply_html}
<div class="grid g2">
  <div class="card">
    <h2 id="demand">買盤吃不吃得下</h2>
    <p class="hint">供給增加不必然推高利率——要看需求端撐不撐得住。
      信用利差就是買方的溫度計：走闊代表買方開始要求更高的補償才願意接。</p>
    {demand_html}
    <div class="stat-row" style="margin-top:16px">{_stats(d['credit_stats'])}</div>
    <div style="margin-top:16px">{d['credit_chart']}</div>
  </div>

  <div class="card">
    <h2 id="priced">壓力已經反映多少</h2>
    <p class="hint">上面兩張講的是「供給與需求」，這裡看的是<b>價格</b>——
      期限溢酬與長端內部的斜率，就是市場已經替這些壓力定了多少價。</p>
    {priced_html}
    <div class="stat-row" style="margin-top:16px">{_stats(d['curve_stats'])}</div>
    <details data-m-collapse><summary>其他天期</summary>
      <div class="stat-row" style="margin-top:12px">{_stats(d['curve_short'])}</div>
      <p class="hint" style="margin-top:12px">
        短天期主要由政策利率預期決定，跟這一頁的供給壓力沒有直接關係，
        所以收在這裡。政策利率的方向見<a href="/fomc/">聯準會文本</a>頁。</p>
    </details>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="debt">供給端細節一：政府財政</h2>
    <p class="hint">重點不是債務總額，是<b>會不會失控</b>。
      債務比會不會上升，取決於利率、成長與基本盈餘三者的關係。</p>
    <div class="stat-row">{_stats(d['debt_stats'])}</div>
    <div class="warnbox" style="border-left-color:var(--series-1);margin-top:16px">
      <b>{esc(debt_title)}</b><br>{esc(debt_desc)}
    </div>
    {debt_gap_html}
    <h3 style="margin-top:18px">聯邦債務佔 GDP 比（{esc(d.get('debt_span', ''))}）</h3>
    {d['debt_chart']}
    <details data-m-collapse><summary>財政損益兩平的算法</summary>
      <div class="stat-row" style="margin-top:12px">{_stats(d['debt_steps'])}</div>
      <dl class="gloss" style="margin-top:14px">
        <dt>公式</dt>
        <dd>穩定所需的基本盈餘 ≈ 債務比 × (有效利率 − 名目成長) ÷ (1 + 名目成長)</dd>
        <dt>基本盈餘</dt>
        <dd>排除利息支出後的財政餘額。利息是過去累積的結果，
          把它排除才看得出當期財政的實際狀況。</dd>
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
    <h2 id="hyperscalers">供給端細節二：科技巨頭</h2>
    <p class="hint">關鍵不是資本支出的絕對金額，是<b>融資方式</b>。
      資本支出超過營運現金流時自由現金流轉負，擴張就必須舉債——
      那正是這幾家從現金充裕的<b>買方</b>，變成投資級市場<b>賣方</b>的轉折點。</p>
    {offerings_html}
    {hs_head_html}
    <div class="warnbox" style="border-left-color:var(--serious);margin-top:16px">
      <b>{esc(hs_title)}</b><br>{esc(hs_desc)}
    </div>
    <details data-m-collapse><summary>五家公司的明細</summary>
      <div class="stat-row" style="margin-top:12px">{_stats(d['hs_stats'])}</div>
      <div class="tscroll" style="margin-top:16px">
        <table>
          <thead><tr><th>公司</th><th>資本支出</th><th>年增</th>
            <th>營運現金流</th><th>佔營運現金流</th><th>佔營收</th>
            <th>本季發債</th></tr></thead>
          <tbody>{hs_rows}</tbody></table>
      </div>
      <div class="src">金額單位：億美元　·　「佔營運現金流」超過 100% 代表
        自由現金流轉負　·　「佔營收」是同一季的資本支出除以營收，
        用來比較規模不同的公司誰擴張得比較猛　·
        資料截止 {esc(hs.as_of)}　·　{esc(d['hs_source'])}</div>
    </details>
    {unverified}
  </div>
</div>

<div class="grid g2">
  <div class="card">
    <h2 id="lights">關鍵指標檢核</h2>
    <p class="hint">{light_summary}門檻設定於 config/rates.yaml。</p>
    <details data-m-collapse open><summary>逐項展開</summary>
      <div class="lights" style="margin-top:12px">{lights_html}</div>
    </details>
  </div>

  <div class="card">
    <h2 id="glossary">名詞解釋</h2>
    <p class="hint">這頁出現的專有名詞。</p>
    <details data-m-collapse open class="plain"><summary>展開名詞解釋</summary>
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
      <dt>存續期間需求</dt>
      <dd>市場願意買進長天期債券的總量。政府與企業發債競爭的就是這一池資金，
        供給超過需求時長端殖利率就會被推高。</dd>
    </dl>
    </details>
  </div>
</div>
"""


def rates_footer(d: dict) -> str:
    return (
        "資料來源：FRED（美國財政部、聯準會、BEA、ICE BofA 指數）。<br>"
        "科技巨頭的資本支出、營運現金流與發債取自 SEC EDGAR 的 XBRL 申報，"
        "每季財報一申報就會自動更新。<br>"
        "本頁僅為數據整理，不構成投資建議。"
    )
