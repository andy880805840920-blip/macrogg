"""
勞動市場頁的內容產生器。

版面順序（手機優先）：
    結論 → 四個關鍵數字 → 這次告訴我們什麼 → 失業率為什麼變 →
    行業增減 → 修正 → 健康檢查 → （折疊）名詞解釋、分數、JOLTS

標記 data-m-collapse 的 <details> 在窄螢幕上預設收合，桌面展開。
"""

from __future__ import annotations

from .. import charts, fmt
from ..site import esc

STATUS_ICON = {"good": "●", "warning": "▲", "critical": "■", "unknown": "○"}
STATUS_TEXT = {"good": "正常", "warning": "留意", "critical": "警戒", "unknown": "無資料"}
SEV_ICON = {"alert": "■", "watch": "▲", "info": "●"}
SEV_TEXT = {"alert": "重要", "watch": "留意", "info": "參考"}
LEAN_TEXT = {"dovish": "利降息", "hawkish": "利升息",
             "neutral": "中性", "balanced": "多空拉鋸"}


# ---------------------------------------------------------------------------
def _kpi_card(label, value, sub, plain, spark_html="", flag=None, flag_kind="",
              mini="", asof="") -> str:
    flag_html = f'<div class="k-flag {flag_kind}">{esc(flag)}</div>' if flag else ""
    plain_html = f'<div class="k-plain">{esc(plain)}</div>' if plain else ""
    asof_html = f'<span class="asof">{esc(asof)}</span>' if asof else ""
    return f"""<div class="card kpi">
  <div class="k-label">{esc(label)}{asof_html}</div>
  <div class="k-value">{esc(value)}</div>
  <div class="k-sub">{esc(sub)}</div>
  {plain_html}{flag_html}{spark_html}{mini}
</div>"""


def _light_card(lt) -> str:
    arrow = {"up": "↑", "down": "↓", "flat": "→"}[lt.delta_dir]
    strip = charts.status_strip(getattr(lt, "history", []) or [])
    return f"""<div class="light {lt.status}">
  <div class="l-top"><span class="l-icon">{STATUS_ICON[lt.status]}</span>{esc(lt.label)}</div>
  <div class="l-value">{esc(lt.display)} <span style="font-size:13px;color:var(--muted)">{arrow}</span></div>
  <div class="l-state">{STATUS_TEXT[lt.status]}</div>
  {strip}
  <div class="l-desc">{esc(lt.desc)}</div>
</div>"""


def _flag_row(f) -> str:
    impact = ""
    if f.impact:
        impact = (f'<div class="impact {f.lean}">'
                  f'{esc(LEAN_TEXT.get(f.lean, ""))}　{esc(f.impact)}</div>')
    return f"""<div class="flag {f.severity}">
  <span class="f-icon">{SEV_ICON.get(f.severity,'●')}</span>
  <div>
    <div class="f-head">{esc(f.headline)}
      <span class="f-tag">{SEV_TEXT.get(f.severity,'')}</span></div>
    <div class="f-detail">{esc(f.detail)}</div>
    {impact}
  </div>
</div>"""


def _stats(items) -> str:
    return "".join(
        f'<div class="stat"><div class="s-label">{esc(s["label"])}</div>'
        f'<div class="s-value" style="color:{s.get("color","inherit")}">{esc(s["value"])}</div>'
        + (f'<div class="s-note">{esc(s["note"])}</div>' if s.get("note") else "")
        + "</div>"
        for s in items
    )


def _surprise(sb) -> str:
    if not sb or not sb.get("has_any"):
        return ('<div class="warnbox"><b>尚未填入市場預期</b><br>'
                '在 config/consensus.yaml 填入發布前的市場預期，'
                '這一區就會顯示實際值與預期的差距，以及標準化後的意外值。'
                '未填入時系統會退回時間序列模型推估，並明確標示來源。</div>')
    warn = ""
    if sb.get("model_only"):
        warn = ('<div class="warnbox" style="margin-top:12px"><b>目前使用模型推估</b><br>'
                '這不是市場預期，而是「若照歷史規律外推應該是多少」。'
                '兩者意義不同，請勿當成市場共識解讀。</div>')
    notes = "　·　".join(sb.get("notes") or [])
    notes_html = f"　·　{esc(notes)}" if notes else ""
    return (f'<div class="surp">{sb["boxes"]}</div>'
            f'<div class="src">預期來源：{esc(sb["sources"])}{notes_html}</div>{warn}')


def offline_banner(real_modules: list | None = None) -> str:
    """
    離線模式的警示條。哪些是真的、哪些是生成的，要講清楚——
    含糊其辭比不標示更糟，讀者會不知道哪些數字能引用。
    """
    real = "、".join(real_modules or [])
    series_note = (f"{real} 的時間序列為正式執行存下的真實資料快照；其餘"
                   if real else "時間序列")
    return ('<div class="banner"><b>離線示範模式</b>　'
            '聯準會聲明與記者會逐字稿為 federalreserve.gov 的真實原文；'
            f'{series_note}為程式生成的示範序列（統計特性接近真實，'
            '但個別數值非實際發布值），不可用於研究引用。'
            '正式執行（不加 --offline）一律使用即時資料。</div>')


# ---------------------------------------------------------------------------
VERDICT_COPY = {
    "dovish": ("就業面：利降息",
               "轉弱訊號多於轉強。勞動市場走軟提高聯準會降息的正當性，"
               "對債券價格偏正面，但同時代表經濟動能流失。"),
    "hawkish": ("就業面：利升息",
                "就業與薪資強度高於預期。勞動市場緊俏降低降息的急迫性，"
                "甚至可能重啟緊縮，對債券價格偏負面。"),
    "balanced": ("就業面：方向不明",
                 "偏強與偏弱訊號互相抵消，本期數據不足以改變政策方向，"
                 "須待下期數據或通膨資料確認。"),
}


def _verdict_card(d: dict) -> str:
    tilt = d["tilt"]
    flags = d["flags"]
    title, why = VERDICT_COPY.get(tilt["tilt"], VERDICT_COPY["balanced"])

    n_dov = sum(1 for f in flags if f.lean == "dovish")
    n_haw = sum(1 for f in flags if f.lean == "hawkish")
    n_neu = len(flags) - n_dov - n_haw

    top = next((f for f in flags if f.severity == "alert"), flags[0] if flags else None)
    lead = f"最主要的訊號是：{top.headline}。" if top else ""

    return f"""<div class="verdict {tilt['tilt']}">
  <div class="v-eyebrow">{esc(d['data_month'])} 就業報告　·　一句話結論</div>
  <div class="v-main">{esc(title)}</div>
  <div class="v-why">{esc(lead)}{esc(why)}</div>
  <div class="v-count">
    本次共 {len(flags)} 項訊號：{n_dov} 項利降息、{n_haw} 項利升息、{n_neu} 項中性。<br>
    這是勞動市場單方面的判斷。聯準會同時要看通膨——兩者合併的結論見「情境合成」頁。
  </div>
</div>"""


# ---------------------------------------------------------------------------
def labor_body(d: dict) -> str:
    k = d["kpi"]
    mini = d.get("mini", {})
    asof = (d.get("asof", {}).get("labor") or "")[:7]
    kpis = "".join([
        _kpi_card("非農就業月變動", k["nfp_display"], k["nfp_sub"], k.get("nfp_plain"),
                  charts.sparkline(k["nfp_spark"], zero_line=True),
                  k.get("nfp_flag"), k.get("nfp_flag_kind", ""),
                  mini=mini.get("nfp", ""), asof=asof),
        _kpi_card("失業率 U-3", k["u3_display"], k["u3_sub"], k.get("u3_plain"),
                  charts.sparkline(k["u3_spark"]),
                  k.get("u3_flag"), k.get("u3_flag_kind", ""),
                  mini=mini.get("u3", ""), asof=asof),
        _kpi_card("平均時薪年增率", k["ahe_display"], k["ahe_sub"], k.get("ahe_plain"),
                  charts.sparkline(k["ahe_spark"]),
                  k.get("ahe_flag"), k.get("ahe_flag_kind", ""),
                  mini=mini.get("ahe", ""), asof=asof),
        _kpi_card("勞動參與率", k["lfpr_display"], k["lfpr_sub"],
                  k.get("lfpr_plain"), charts.sparkline(k["lfpr_spark"]),
                  k.get("lfpr_flag"), k.get("lfpr_flag_kind", ""),
                  mini=mini.get("lfpr", ""), asof=asof),
    ])

    rev, att, dec, sc = d["revision"], d["attribution"], d["decomp"], d["score"]

    flags_html = "".join(_flag_row(f) for f in d["flags"]) or \
        '<div class="empty">本次沒有觸發任何訊號</div>'
    lights_html = "".join(_light_card(l) for l in d["lights"])

    # ---- 失業率為什麼變 ----
    dec_html = '<div class="empty">資料不足</div>'
    if dec:
        dec_html = f"""<div class="stat-row">
  <div class="stat"><div class="s-label">失業率變動</div>
    <div class="s-value">{dec['delta_rate']:+.2f}pp</div></div>
  <div class="stat"><div class="s-label">判定</div>
    <div class="s-value" style="font-size:17px;color:{dec['verdict_color']}">{esc(dec['verdict_text'])}</div></div>
  <div class="stat"><div class="s-label">就業效果</div>
    <div class="s-value">{dec['employment_effect']:+.2f}pp</div>
    <div class="s-note">有工作的人 {esc(fmt.wan(dec['delta_employed']))}</div></div>
  <div class="stat"><div class="s-label">勞動力效果</div>
    <div class="s-value">{dec['laborforce_effect']:+.2f}pp</div>
    <div class="s-note">在找工作的人 {esc(fmt.wan(dec['delta_labor_force']))}</div></div>
</div>
<p class="hint" style="margin:16px 0 0">
  失業率只計算「還在找工作」的人。放棄找工作的人變多時，失業率會下降，
  但那不代表就業變好——上面兩欄就是把這兩種原因拆開來看。
</p>"""

    # ---- 折疊區的表格 ----
    jolts_rows = "".join(
        f'<tr><td>{esc(r["label"])}</td><td>{esc(r["value"])}</td>'
        f'<td>{esc(r["chg"])}</td></tr>' for r in d["jolts"]
    )
    att_rows = "".join(
        f'<tr><td>{esc(r["label"])}</td>'
        f'<td class="{"pos" if r["value"]>=0 else "neg"}">{esc(fmt.people(r["value"]))}</td>'
        f'<td class="muted-cell">{esc(r["share"])}</td></tr>'
        for r in att["table"]
    )
    score_items = "".join(
        f'<tr><td>{esc(i["label"])}</td><td>{i["z"]:+.2f}</td>'
        f'<td class="muted-cell">{i["weight"]:.1f}</td>'
        f'<td class="{"pos" if i["contribution"]>=0 else "neg"}">{i["contribution"]:+.2f}</td></tr>'
        for i in sc["items"]
    )
    pct = max(0, min(100, (sc["score"] + 2.5) / 5 * 100))
    bar_color = "var(--good)" if sc["score"] > 0 else "var(--critical)"
    left = min(50, pct) if sc["score"] < 0 else 50
    width = abs(pct - 50)

    failed_html = ""
    if d.get("failed"):
        items = "".join(f"<li>{esc(a)} — {esc(b)}</li>" for a, b in d["failed"])
        failed_html = (f'<div class="card"><details class="plain"><summary>'
                       f'本次有 {len(d["failed"])} 個資料序列抓取失敗</summary>'
                       f'<ul style="font-size:13px;color:var(--text-secondary)">{items}</ul>'
                       f"</details></div>")

    return f"""
{_verdict_card(d)}

<div class="grid g4">{kpis}</div>

<div class="grid">
  <div class="card">
    <h2 id="surprise">實際 vs 市場預期</h2>
    <p class="hint">市場只對「意外」反應，不對水準反應。
      預期 −5 萬而公布 −2.3 萬是利空出盡；預期 +8.5 萬而公布 −2.3 萬才是重擊。</p>
    {_surprise(d.get('surprises'))}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="signals">本期關鍵訊號</h2>
    <p class="hint">依固定規則逐項檢查，結果可完整重現。每一項標註其對利率路徑的意涵。</p>
    {flags_html}
  </div>
</div>

<div class="grid g2">
  <div class="card">
    <h2 id="unrate">失業率變動分解</h2>
    <p class="hint">將失業率變動拆解為就業效果與勞動力效果。同樣的下降幅度，成因不同則意義相反。</p>
    {dec_html}
  </div>

  <div class="card">
    <h2 id="revision">歷史數據修正</h2>
    <p class="hint">就業數字第一次公布是估算值，之後兩個月會用更完整的資料重算。
      修正幅度常常比當月的變動還大。</p>
    <div class="stat-row">{_stats(rev['stats'])}</div>
    <details data-m-collapse open><summary>逐月修正明細</summary>
      {rev['table']}
      <p class="hint" style="margin-top:10px">
        「修正」欄是相對初次公布的累計差異，與上方 BLS 口徑（相對上次發布）不同。</p>
    </details>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="breakeven">損益兩平就業增速</h2>
    <p class="hint">維持失業率不變，每個月需要新增多少工作。
      <b>沒有這條基準線，非農的絕對數字無法解讀</b>——同樣是月增 2 萬，
      在勞動供給每月增加 10 萬的環境下代表明顯轉弱，在只增加 3 萬的環境下則是大致平衡。</p>
    <div class="stat-row">{_stats(d['breakeven']['stats'])}</div>
    <div style="margin-top:16px">{d['breakeven']['chart']}</div>
    <p class="hint" style="margin-top:14px">
      {esc(d['breakeven']['verdict_note'])}。
      {esc(d['breakeven']['note'])}
    </p>
    <details data-m-collapse><summary>計算方式與注意事項</summary>
      <dl class="gloss" style="margin-top:10px">
        <dt>計算式</dt>
        <dd>每月損益兩平 ≈ 工作年齡人口月增 × 勞動參與率 × 機構調查／家庭調查就業比。
          前兩項決定每月新增多少人想工作，第三項把家庭調查口徑換算成非農口徑。</dd>
        <dt>為什麼會變動</dt>
        <dd>主要來自人口成長率與移民政策。2025 年後移民收緊，勞動供給成長明顯放慢，
          這個門檻從過去的 10–15 萬降到目前的水準。</dd>
        <dt>注意事項</dt>
        <dd>人口序列每年一月會做普查控制調整，出現不連續跳點，計算時已排除一月的變動。
          此為推估值，非官方公布數字。</dd>
      </dl>
    </details>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="industry">行業別貢獻分解</h2>
    <p class="hint">顯示增減幅度最大的各五個行業，加上任何「相對自己過去表現異常」的行業，
      其餘合併為其他。灰色是醫療、社福與各級政府——這些行業用人比較不受景氣影響。</p>
    <div class="stat-row">{_stats(att['stats'])}</div>
    <details data-m-collapse open><summary>行業別明細</summary>
    <div style="margin-top:14px">{att['bars']}</div>
    <div class="dlegend">
      <span><i style="background:var(--pos)"></i>增加</span>
      <span><i style="background:var(--neg)"></i>減少</span>
      <span><i style="background:var(--muted-bar)"></i>不受景氣影響／加總列</span>
      <span>單位：人</span>
    </div>
    </details>
    <details data-m-collapse><summary>全部 {att['total_count']} 個行業</summary>
      <table style="margin-top:10px">
        <thead><tr><th>行業</th><th>增減</th><th>佔總變動</th></tr></thead>
        <tbody>{att_rows}</tbody></table></details>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="lights">關鍵指標檢核</h2>
    <p class="hint">八項關鍵指標的當期狀態。門檻設定於 config/indicators.yaml。</p>
    <details data-m-collapse open><summary>八項指標</summary>
      <div class="lights" style="margin-top:12px">{lights_html}</div>
    </details>
  </div>
</div>

<div class="grid g2">
  <div class="card">
    <h2 id="score">綜合強弱指數</h2>
    <p class="hint">把主要指標換算成同一個尺度後加權合成。
      正數代表比近年平均強、負數代表弱。</p>
    <div style="font-size:36px;font-weight:700;line-height:1.15">
      {sc['score']:+.2f}
      <span style="font-size:14px;color:var(--text-secondary);font-weight:400">
        {'較上月 ' + format(sc['delta'], '+.2f') if sc.get('delta') is not None else ''}</span>
    </div>
    <div class="score-bar">
      <i style="left:{left}%;width:{width}%;background:{bar_color}"></i>
      <span class="score-mid"></span>
    </div>
    <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--muted)">
      <span>−2.5 疲弱</span><span>0 持平</span><span>+2.5 強勁</span></div>
    <details data-m-collapse><summary>各指標貢獻明細</summary>
      <table style="margin-top:10px">
        <thead><tr><th>指標</th><th>標準分數</th><th>權重</th><th>貢獻</th></tr></thead>
        <tbody>{score_items}</tbody></table>
      <p class="hint" style="margin-top:10px">
        標準分數＝目前值比近五年平均高或低幾個標準差，已調整方向讓「正值＝就業強」。
        權重目前為暫定值。</p>
    </details>
    <details data-m-collapse><summary>JOLTS 職缺與人力流動</summary>
      <p class="hint" style="margin:10px 0 8px">{esc(d['jolts_note'])}</p>
      <table><thead><tr><th>指標</th><th>最新值</th><th>較上月</th></tr></thead>
      <tbody>{jolts_rows}</tbody></table></details>
  </div>

  <div class="card">
    <h2 id="glossary">名詞解釋</h2>
    <p class="hint">這頁出現的專有名詞。</p>
    <details data-m-collapse open class="plain"><summary>展開名詞解釋</summary>
    <dl class="gloss">
      <dt>非農就業人數</dt>
      <dd>美國政府向企業調查得出的就業人數，不含農業。最受市場關注的就業指標。</dd>
      <dt>失業率</dt>
      <dd>在「有在找工作的人」當中，找不到工作的比例。已經放棄找工作的人不算在內。</dd>
      <dt>勞動參與率</dt>
      <dd>16 歲以上人口中，有在工作或正在找工作的比例。退休、就學、放棄找工作的人不算。</dd>
      <dt>JOLTS</dt>
      <dd>職缺與人力流動調查。統計市場上有多少職缺、多少人被錄取、多少人主動離職。
        資料比就業報告晚約兩個月。</dd>
      <dt>主動離職率</dt>
      <dd>自己辭職的人佔總就業的比例。敢主動辭職代表對找到下一份工作有信心，
        所以是勞工信心的溫度計。</dd>
      <dt>續領失業補助</dt>
      <dd>持續在領失業給付的人數。比「新增失業人數」更能反映找到新工作的難度。</dd>
      <dt>百分點（pp）</dt>
      <dd>比例之間的差距。失業率從 4.2% 降到 4.1%，是下降 0.1 個百分點。</dd>
      <dt>利升息／利降息</dt>
      <dd>指這項數據會讓聯準會傾向升息或降息。就業轉弱通常利降息，
        就業與薪資過熱則利升息。</dd>
    </dl>
    </details>
  </div>
</div>

{failed_html}
"""


def labor_footer(d: dict) -> str:
    return (
        "資料來源：美國勞工統計局（BLS）與勞工部（DOL），經 FRED 取得，"
        "數字為修正後的最新版本。<br>"
        f"修正追蹤來源：{esc(d['revision']['source_note'])}"
        "　·　所有判定由固定規則產生，每次執行結果一致。<br>"
        "本頁僅為數據整理，不構成投資建議。"
    )
