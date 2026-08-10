"""通膨頁的內容產生器（P2）。版面與勞動頁一致，讀者同樣是投資人。"""

from __future__ import annotations

from .. import charts
from ..site import esc
from .labor import (_kpi_card, _light_card, _flag_row, _stats,
                    STATUS_TEXT, LEAN_TEXT)


VERDICT_COPY = {
    "dovish": ("通膨面：利降息",
               "通膨降溫的訊號多於升溫。物價壓力減輕會讓聯準會更有空間降息，"
               "對債券價格通常是正面的。"),
    "hawkish": ("通膨面：利升息",
                "通膨的壓力高於預期。物價降不下來會讓聯準會不敢降息、"
                "甚至重新考慮緊縮，這對債券價格通常是負面的。"),
    "balanced": ("通膨面：方向不明",
                 "升溫與降溫的訊號互相抵消，這份數據不足以改變聯準會的方向。"),
}


def _tilt(flags) -> dict:
    w = {"alert": 2.0, "watch": 1.0, "info": 0.5}
    dov = sum(w.get(f.severity, .5) for f in flags if f.lean == "dovish")
    haw = sum(w.get(f.severity, .5) for f in flags if f.lean == "hawkish")
    net = haw - dov
    t = "hawkish" if net > 1 else ("dovish" if net < -1 else "balanced")
    return {"dovish": dov, "hawkish": haw, "net": net, "tilt": t}


def _verdict_card(d: dict) -> str:
    flags = d["flags"]
    tilt = d["tilt"]
    title, why = VERDICT_COPY.get(tilt["tilt"], VERDICT_COPY["balanced"])
    n_dov = sum(1 for f in flags if f.lean == "dovish")
    n_haw = sum(1 for f in flags if f.lean == "hawkish")
    top = next((f for f in flags if f.severity == "alert"), flags[0] if flags else None)
    lead = f"最主要的訊號是：{top.headline}。" if top else ""
    return f"""<div class="verdict {tilt['tilt']}">
  <div class="v-eyebrow">{esc(d['data_month'])} 物價數據　·　一句話結論</div>
  <div class="v-main">{esc(title)}</div>
  <div class="v-why">{esc(lead)}{esc(why)}</div>
  <div class="v-count">
    本次共 {len(flags)} 項訊號：{n_dov} 項利降息、{n_haw} 項利升息。<br>
    這是通膨單方面的判斷。聯準會同時要看就業，完整結論請見情境合成頁。
  </div>
</div>"""


def _passthrough(p) -> str:
    if not p or not p.get("available"):
        return (f'<div class="warnbox"><b>尚無法估計</b><br>'
                f'{esc((p or {}).get("reason", "資料不足"))}</div>')
    return f"""<div class="stat-row">{_stats(p['stats'])}</div>
<div class="warnbox" style="border-left-color:var(--series-1);margin-top:16px">
  <b>{esc(p['verdict_title'])}</b><br>{esc(p['verdict_desc'])}
</div>
<h3>平均時薪年增率</h3>
{p['wage_chart']}
<h3>核心服務除住房年增率</h3>
{p['sc_chart']}
<p class="hint" style="margin-top:14px">
  兩條線分開畫，不用雙軸——不同尺度硬放同一張圖會製造出實際上不存在的關係。
</p>
<details data-m-collapse><summary>領先落後的相關性</summary>
  <table style="margin-top:10px">
    <thead><tr><th>薪資領先期數</th><th>相關係數</th></tr></thead>
    <tbody>{p['lag_rows']}</tbody></table>
  <p class="hint" style="margin-top:10px">{esc(p['note'])}</p>
</details>"""


def inflation_body(d: dict) -> str:
    k = d["kpi"]
    s = d["summary"]

    mini = d.get("mini", {})
    a = d.get("asof", {})
    kpis = "".join([
        _kpi_card("CPI 年增率", k["headline_display"], k["headline_sub"],
                  k["headline_plain"], charts.sparkline(k["headline_spark"]),
                  mini=mini.get("headline", ""), asof=(a.get("cpi") or "")[:7]),
        _kpi_card("核心 CPI 年增率", k["core_display"], k["core_sub"],
                  k["core_plain"], charts.sparkline(k["core_spark"]),
                  k.get("core_flag"), k.get("core_flag_kind", ""),
                  mini=mini.get("core", ""), asof=(a.get("cpi") or "")[:7]),
        _kpi_card("核心 PCE 年增率", k["pce_display"], k["pce_sub"],
                  k["pce_plain"], charts.sparkline(k["pce_spark"]),
                  k.get("pce_flag"), k.get("pce_flag_kind", ""),
                  mini=mini.get("pce", ""), asof=(a.get("pce") or "")[:7]),
        _kpi_card("5年後5年期通膨預期", k["exp_display"], k["exp_sub"],
                  k["exp_plain"], charts.sparkline(k["exp_spark"]),
                  mini=mini.get("exp", ""), asof=(a.get("exp") or "")[:7]),
    ])

    flags_html = "".join(_flag_row(f) for f in d["flags"]) or \
        '<div class="empty">本次沒有觸發任何訊號</div>'
    lights_html = "".join(_light_card(l) for l in d["lights"])
    att = d["attribution"]

    trend_rows = "".join(
        f'<tr><td>{esc(r["label"])}</td><td>{esc(r["value"])}</td>'
        f'<td class="muted-cell">{esc(r["note"])}</td></tr>'
        for r in d["trend_rows"]
    )

    return f"""
{_verdict_card(d)}

<div class="grid g4">{kpis}</div>

<div class="grid">
  <div class="card">
    <h2 id="signals">本期關鍵訊號</h2>
    <p class="hint">依固定規則逐項檢查，結果可完整重現。每一項標註其對利率路徑的意涵。</p>
    {flags_html}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="contrib">分項貢獻分解</h2>
    <p class="hint">把物價的漲幅拆成各類別的貢獻。這裡看的是近三個月，
      因為單月數字雜訊太大。灰色的住房項要特別注意——它的算法會落後市場行情約一年。</p>
    <div class="stat-row">{_stats(att['stats'])}</div>
    <details data-m-collapse open><summary>分項貢獻明細</summary>
      <div style="margin-top:14px">{att['bars']}</div>
    <div class="dlegend">
      <span><i style="background:var(--pos)"></i>推升物價</span>
      <span><i style="background:var(--neg)"></i>壓低物價</span>
      <span><i style="background:var(--muted-bar)"></i>落後項（住房）</span>
      <span>單位：百分點</span>
    </div>
    </details>
    <p class="hint" style="margin-top:14px">
      貢獻＝該類別佔物價籃子的比重 × 它自己的漲幅。所以住房只要漲一點點，
      因為它佔了三分之一以上的權重，對整體的影響就很大。
    </p>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="lights">關鍵指標檢核</h2>
    <p class="hint">八項關鍵指標的當期狀態。門檻設定於 config/inflation.yaml。</p>
    <details data-m-collapse open><summary>八項指標</summary>
      <div class="lights" style="margin-top:12px">{lights_html}</div>
    </details>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="passthrough">薪資到服務業通膨的傳導</h2>
    <p class="hint">核心服務除住房的成本主體是人力，所以薪資的走向會在數月後
      反映到這一塊。<b>這是判斷通膨黏性會不會持續的核心機制</b>，
      也是勞動與通膨兩個模組真正的連結。</p>
    {_passthrough(d.get('passthrough'))}
  </div>
</div>

<div class="grid g2">
  <div class="card">
    <h2 id="trend">剔除極端值的趨勢指標</h2>
    <p class="hint">平均數容易被少數暴漲暴跌的項目帶偏。
      下面三個指標用不同方法把極端值拿掉，比較能看出真正的趨勢。</p>
    <table><thead><tr><th>指標</th><th>目前</th><th>說明</th></tr></thead>
    <tbody>{trend_rows}</tbody></table>
    <details data-m-collapse><summary>各項指標的定義</summary>
      <dl class="gloss" style="margin-top:10px">
        <dt>中位數 CPI</dt>
        <dd>把所有項目依漲幅排序，取正中間那一個。完全不受極端值影響。</dd>
        <dt>截尾平均</dt>
        <dd>把漲最多和跌最多的項目都剔除後再平均。</dd>
        <dt>黏性 CPI</dt>
        <dd>只看價格很少調整的項目（例如房租、保險）。這些代表通膨的慣性，
          一旦漲上去就很難降下來。</dd>
      </dl>
    </details>
  </div>

  <div class="card">
    <h2 id="glossary">名詞解釋</h2>
    <p class="hint">這頁出現的專有名詞。</p>
    <details data-m-collapse open class="plain"><summary>展開名詞解釋</summary>
    <dl class="gloss">
      <dt>CPI</dt>
      <dd>消費者物價指數。統計一籃子商品與服務的價格變化，是最常被報導的通膨指標。</dd>
      <dt>核心 CPI</dt>
      <dd>剔除食物與能源後的 CPI。這兩項波動太大，剔除後比較看得出趨勢。</dd>
      <dt>PCE / 核心 PCE</dt>
      <dd>另一套物價指數，涵蓋範圍比 CPI 廣，也會反映消費者的替代行為。
        <b>聯準會的 2% 目標指的是核心 PCE，不是 CPI。</b></dd>
      <dt>核心服務除住房</dt>
      <dd>英文常稱 supercore。這一塊的成本主要是人力，所以跟薪資直接連動，
        是聯準會判斷通膨是否真的受控的關鍵。</dd>
      <dt>住房項的落後</dt>
      <dd>CPI 的住房是把所有既有租約一起平均，新簽的租金要一年多才會完全反映進去。
        所以看到的住房數字其實是去年的行情。</dd>
      <dt>三個月年化</dt>
      <dd>把最近三個月的漲幅換算成一年的速度。比年增率更早反映轉折，
        因為年增率會被一年前的舊數字拖住。</dd>
      <dt>通膨預期</dt>
      <dd>市場或民眾認為未來通膨會是多少。一旦大家「相信」通膨會一直高，
        就會反映在定價和薪資談判上，通膨會自我實現——這是聯準會最怕的事。</dd>
    </dl>
    </details>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="energy">能源價格與傳導</h2>
    <p class="hint">油價會在兩到四週後反映到加油站，再進到物價指數。
      這一區看的是「已經發生但還沒反映到數據裡」的部分——虛線是一個月前的位置。</p>
    <div class="stat-row">{_stats(d['energy_stats'])}</div>

    <h3>WTI 原油（今年以來）</h3>
    {d.get('oil_chart', '')}

    <details data-m-collapse><summary>零售汽油價格（今年以來）</summary>
      <div style="margin-top:12px">{d.get('gas_chart', '')}</div>
      <p class="hint" style="margin-top:10px">
        汽油是 CPI 能源項裡權重最大的一塊，也是消費者最有感的價格。
        它落後原油約兩到四週。</p>
    </details>

    <p class="hint" style="margin-top:16px">
      注意能源只影響總體物價，不影響核心。聯準會看的是核心，
      所以油價漲跌通常不會直接改變利率決策——<b>除非它久到開始推高通膨預期</b>，
      那就會變成核心的問題。
    </p>
  </div>
</div>
"""


def inflation_footer(d: dict) -> str:
    return (
        "資料來源：美國勞工統計局（BLS）、經濟分析局（BEA）、"
        "克里夫蘭聯準銀行與亞特蘭大聯準銀行，經 FRED 取得。<br>"
        f"CPI 權重版本：{esc(d.get('weights_vintage', '—'))}"
        "　·　權重每年一月由 BLS 更新，需同步校準。<br>"
        "本頁僅為數據整理，不構成投資建議。"
    )
