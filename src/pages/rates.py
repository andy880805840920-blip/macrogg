"""長端利率與債務供給頁的內容產生器（P5）。"""

from __future__ import annotations

from ..site import esc
from .labor import _light_card, _stats


def rates_body(d: dict) -> str:
    sp = d["pressure"]
    title, why = d["pressure_text"]
    lean_cls = {"high": "hawkish", "low": "dovish"}.get(sp.level, "balanced")

    parts = "".join(
        f'<div class="cmove"><div>{esc(p["label"])}</div>'
        f'<div class="cm-delta {"up" if p["score"] > 0 else "down"}">{p["score"]:+.2f}</div>'
        f'<div class="cm-val">{esc(p["detail"])}</div></div>'
        for p in sp.parts
    )

    lights_html = "".join(_light_card(l) for l in d["lights"])
    hs = d["hyperscalers"]
    hs_title, hs_desc = d["hs_text"]
    debt_title, debt_desc = d["debt_text"]

    def _hs_row(c: dict) -> str:
        yoy_txt = "—" if c.get("capex_yoy") is None else f'{c["capex_yoy"]:+.0f}%'
        ratio = c.get("capex_to_ocf")
        ratio_txt = "—" if ratio is None else f"{ratio:.0f}%"
        cls = "neg" if c.get("cash_negative") else ""
        # 期末日逐家標示：各家會計年度不同，同一列的「最新一季」不是同一季
        pe = c.get("period_end") or ""
        name = (f'{esc(c["name"])}<span class="dnote">{esc(pe)}</span>'
                if pe else esc(c["name"]))
        return (f'<tr><td>{name}</td>'
                f'<td>{c["capex"] * 10:,.0f}</td>'
                f'<td class="muted-cell">{yoy_txt}</td>'
                f'<td class="muted-cell">{c["ocf"] * 10:,.0f}</td>'
                f'<td class="{cls}">{ratio_txt}</td>'
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
  <div class="v-count">
    這一頁看的是<b>長端</b>。前面三個模組決定政策利率的方向，
    但 30 年期殖利率由債券供給與期限溢酬決定，聯準會控制不了。<br>
    綜合分數 {sp.score:+.2f}（刻度：0＝中性，正＝供給壓力大、負＝壓力小）
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="pressure">供給壓力的組成</h2>
    <p class="hint">每個來源各自計分並列出貢獻，避免變成不可解釋的黑箱。下方各列相加即為總分。</p>
    <div class="cmoves" style="border-top:none;padding-top:0">{parts}</div>
  </div>
</div>

<div class="grid g2">
  <div class="card">
    <h2 id="curve">殖利率曲線</h2>
    <p class="hint">各天期的水準與近一個月變動。長短端的走勢分歧本身就是訊號。</p>
    <div class="stat-row">{_stats(d['curve_stats'])}</div>
  </div>

  <div class="card">
    <h2 id="decomp">名目利率的拆解</h2>
    <p class="hint">殖利率上升可能來自三種完全不同的原因，政策意涵也完全不同。</p>
    <div class="stat-row">{_stats(d['decomp_stats'])}</div>
    <p class="hint" style="margin-top:16px">{esc(d['decomp_note'])}</p>
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

<div class="grid">
  <div class="card">
    <h2 id="debt">政府債務動態</h2>
    <p class="hint">重點不是債務總額，是<b>會不會失控</b>。
      債務比會不會上升，取決於利率、成長與基本盈餘三者的關係。</p>
    <div class="stat-row">{_stats(d['debt_stats'])}</div>
    <div class="warnbox" style="border-left-color:var(--series-1);margin-top:16px">
      <b>{esc(debt_title)}</b><br>{esc(debt_desc)}
    </div>
    {(f'<p class="hint" style="margin-top:14px">{esc(d["debt_divergence"])}</p>'
      if d.get('debt_divergence') else '')}
    {(f'<p class="hint" style="margin-top:8px">{esc(d["debt_growth_note"])}</p>'
      if d.get('debt_growth_note') else '')}
    <h3 style="margin-top:18px">聯邦債務佔 GDP 比（{esc(d.get('debt_span', ''))}）</h3>
    {d['debt_chart']}
    <details data-m-collapse><summary>財政損益兩平的算法</summary>
      <dl class="gloss" style="margin-top:10px">
        <dt>公式</dt>
        <dd>穩定所需的基本盈餘 ≈ 債務比 × (有效利率 − 名目成長) ÷ (1 + 名目成長)</dd>
        <dt>基本盈餘</dt>
        <dd>排除利息支出後的財政餘額。利息是過去累積的結果，
          把它排除才看得出當期財政的實際狀況。</dd>
        <dt>為什麼利率高於成長很危險</dt>
        <dd>當有效利率超過名目成長，利息負擔的成長速度會超過稅基，
          債務比就會自我累積——即使財政收支平衡也一樣。</dd>
        <dt>利息佔稅收比重</dt>
        <dd>比債務總額更能說明壓力：每收 100 元稅，有多少直接拿去付利息，
          就有多少不能用在其他地方。</dd>
      </dl>
      <p class="hint" style="margin-top:10px">{esc(d['debt_note'])}</p>
    </details>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="hyperscalers">科技巨頭的資本支出與發債</h2>
    <p class="hint">關鍵不是資本支出的絕對金額，是<b>融資方式</b>。
      資本支出超過營運現金流時，自由現金流轉負，擴張就必須舉債——
      那正是這幾家從現金充裕的買方，變成投資級市場大型供給方的轉折點。</p>
    <div class="stat-row">{_stats(d['hs_stats'])}</div>
    <div class="warnbox" style="border-left-color:var(--serious);margin-top:16px">
      <b>{esc(hs_title)}</b><br>{esc(hs_desc)}
    </div>
    <div class="tscroll" style="margin-top:18px">
      <table>
        <thead><tr><th>公司</th><th>資本支出</th><th>年增</th>
          <th>營運現金流</th><th>佔比</th><th>本季發債</th></tr></thead>
        <tbody>{hs_rows}</tbody></table>
    </div>
    <div class="src">單位：億美元　·　資料截止 {esc(hs.as_of)}　·　{esc(d['hs_source'])}</div>
    {unverified}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="lights">關鍵指標檢核</h2>
    <p class="hint">八項指標的當期狀態。門檻設定於 config/rates.yaml。</p>
    <details data-m-collapse open><summary>八項指標</summary>
      <div class="lights" style="margin-top:12px">{lights_html}</div>
    </details>
  </div>
</div>

<div class="grid g2">
  <div class="card">
    <h2 id="credit">信用市場</h2>
    <p class="hint">企業融資成本。利差走闊代表市場對信用風險要求更高的補償。</p>
    <div class="stat-row">{_stats(d['credit_stats'])}</div>
    <div style="margin-top:16px">{d['credit_chart']}</div>
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
