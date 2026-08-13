"""通膨頁的內容產生器（P2）。版面與勞動頁一致，讀者同樣是投資人。"""

from __future__ import annotations

from .. import charts
from ..site import esc
from .labor import _kpi_card, _light_card, _flag_row, _stats


VERDICT_COPY = {
    "dovish": ("通膨面：利降息",
               "通膨降溫的訊號多於升溫。物價壓力減輕會讓聯準會更有空間降息，"
               "對債券價格通常是正面的。"),
    "hawkish": ("通膨面：利升息",
                "通膨的壓力高於預期。物價降不下來會讓聯準會不敢降息、"
                "甚至重新考慮緊縮，這對債券價格通常是負面的。"),
    "balanced": ("通膨面：本期方向不明",
                 "升溫與降溫的訊號互相抵消，這份數據不足以改變聯準會的方向。"),
}

# 這三句講的都是**本期新訊號的方向**，不是通膨的**水準**。
# 兩者不分清楚會出現「通膨頁說方向不明、九宮格說通膨高」這種看起來
# 自相矛盾的畫面——實際上兩者可以同時成立（卡在高檔但這個月沒有新推力）。
AXIS_NOTE = ("上面那句講的是<b>本期變化的方向</b>。通膨的<b>水準</b>"
             "（離 2% 目標多遠、落在九宮格哪一欄）與跟就業合併之後的結論，"
             "見<a href=\"/scenario/#grid\">情境合成</a>頁——"
             "水準高但本期方向不明，兩者可以同時成立。")


def _tilt(flags) -> dict:
    w = {"alert": 2.0, "watch": 1.0, "info": 0.5}
    dov = sum(w.get(f.severity, .5) for f in flags if f.lean == "dovish")
    haw = sum(w.get(f.severity, .5) for f in flags if f.lean == "hawkish")
    net = haw - dov
    t = "hawkish" if net > 1 else ("dovish" if net < -1 else "balanced")
    return {"dovish": dov, "hawkish": haw, "net": net, "tilt": t}


def _target_axis(tg: dict) -> str:
    """
    離 2% 目標多遠。

    通膨頁沒有勞動頁那種合成分數，但它有一個更硬的錨：聯準會的目標。
    這個數字先前只出現在第三張 KPI 卡的副標裡——它其實是整頁的定調，
    所有其他數字都是在回答「離它多遠、往哪邊走」。
    軸的範圍取 1%–4%：低於 1% 是通縮風險、高於 4% 是明確失控，
    這個區間涵蓋了所有需要細看的狀態。
    """
    v, gap = tg.get("value"), tg.get("gap")
    if v is None or gap is None:
        return ""
    lo, hi = 1.0, 4.0
    pos = max(0.0, min(100.0, (v - lo) / (hi - lo) * 100))
    tpos = (tg["target"] - lo) / (hi - lo) * 100
    color = ("var(--critical)" if gap > 0.75 else
             ("var(--warning)" if gap > 0.25 else "var(--good)"))
    mom = tg.get("momentum")
    mom_txt = ""
    if mom is not None:
        # 水準只講「現在在哪」，動能才講「往哪邊走」。少了後者，
        # 3.0% 這個數字沒辦法判斷是正在收斂還是正在惡化。
        d = mom - v
        word = "正在往目標靠近" if d < -0.15 else (
            "正在往反方向走" if d > 0.15 else "大致持平")
        mom_txt = f"　·　近三個月年化 {mom:.1f}%，{word}"
    return f"""<div class="sax compact">
  <div class="sax-head">
    <span class="sax-label">{esc(tg.get('label', ''))}離 2% 目標</span>
    <span class="sax-val" style="color:{color}">{gap:+.2f}</span>
    <span class="sax-delta">個百分點{esc(mom_txt)}</span>
  </div>
  <div class="tgt-bar">
    <span class="tgt-mark" style="left:{tpos:.1f}%"></span>
    <i style="left:{min(pos, tpos):.1f}%;width:{abs(pos - tpos):.1f}%;background:{color}"></i>
    <span class="tgt-dot" style="left:{pos:.1f}%;background:{color}"></span>
  </div>
  <div class="sax-scale"><span>1%</span><span>2% 目標</span><span>4%</span></div>
</div>"""


def _sticky_card(k: dict | None) -> str:
    """
    核心服務的黏性。排在關鍵訊號之後，因為它是降息時間表的主要阻力——
    這一塊不鬆，前面所有的好消息都換不到降息。

    主軸是**方向**不是水準：3.9% 且在加速，比 4.1% 且在減速更該擔心。
    所以動能階梯（12m/6m/3m）放在最上面，水準只是它的其中一格。
    """
    if not k:
        return ""
    _v = "".join((f"<b>{esc(s)}</b>" if i % 2 else esc(s))
                 for i, s in enumerate(k["verdict"].split("**")))
    sf = k.get("sticky_flex") or {}
    sf_html = ""
    if sf:
        sf_html = f"""
    <h3>黏性 vs 彈性</h3>
    <p class="hint">彈性項先反應、黏性項最後才動，<b>兩者收斂才算走完</b>。</p>
    <div class="stat-row">{_stats(sf['stats'])}</div>
    <div class="impact {sf['kind']}" style="margin-top:12px">{esc(sf['note'])}</div>"""

    _dv = ""
    if k.get("diverge"):
        _d = "".join((f"<b>{esc(s)}</b>" if i % 2 else esc(s))
                     for i, s in enumerate(k["diverge"].split("**")))
        _dv = f'<div class="caveat" style="margin-top:12px">{_d}</div>'

    return f"""<div class="grid">
  <div class="card">
    <h2 id="sticky" data-sum="{esc(k['sum'])}">核心服務的黏性</h2>
    <p class="hint">降息時間表卡最久的一塊。看的是<b>方向</b>不是水準。</p>
    <div class="impact {k['lean']}" style="margin-bottom:14px">{_v}</div>
    <div class="stat-row">{_stats(k['stats'])}</div>
    {_dv}
    {sf_html}
    <details class="f-more"><summary>為什麼看三個時間尺度、為什麼是 2.5%</summary>
      <div class="f-detail">
        單一個數字看不出方向。12 個月是趨勢、3 個月是當下，
        <b>短天期低於長天期就是在減速</b>，反過來就是重新加速——
        聯準會官員談這一塊時引用的也是這個形式。差距小於 0.3 個百分點時
        一律當「卡在原地」，因為月度資料的雜訊就有這個量級。<br>
        「連續幾個月高於 2.5%」用的是三個月年化。門檻不取 2%（目標值）
        是因為月度雜訊會讓它頻繁穿越，數字會失去意義；2.5% 才代表真的卡住，
        而不是在目標附近正常擺盪。<br>
        這一塊的成本主體是人力，所以它跟薪資直接連動——
        往下捲的<a href="#passthrough">薪資到服務業通膨的傳導</a>是同一條線的上游。
      </div>
    </details>
  </div>
</div>"""


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
  {_target_axis(d.get('target') or {})}
  <div class="v-count">
    本次共 {len(flags)} 項訊號：{n_dov} 項利降息、{n_haw} 項利升息。
    {AXIS_NOTE}
  </div>
</div>"""


def _passthrough(p) -> str:
    if not p or not p.get("available"):
        return (f'<div class="warnbox"><b>尚無法估計</b><br>'
                f'{esc((p or {}).get("reason", "資料不足"))}</div>')
    # 這一段是在說上面那個判定的分析基礎不成立，不是平行的第二個結論。
    # 先前兩個警示框同等視覺重量地並排，讀者不知道該信哪一個。
    # 改成縮排掛在結論框底下，明確是「但書」。
    corr_warn = (f'<div class="caveat"><b>但這段樣本不支持這個機制</b><br>'
                 f'{esc(p["corr_note"])}</div>'
                 if p.get("corr_note") else "")
    return f"""<div class="stat-row">{_stats(p['stats'])}</div>
<div class="warnbox" style="border-left-color:var(--series-1);margin-top:16px">
  <b>{esc(p['verdict_title'])}</b><br>{esc(p['verdict_desc'])}
  {corr_warn}
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
    mini = d.get("mini", {})
    a = d.get("asof", {})
    lean = d.get("kpi_lean", {})
    # 意外值併進卡片。通膨沒有模型推估的後備，所以沒填預期時
    # surp 是空的，卡片上就完全不會出現這一行（見 consensus.yaml 的說明）。
    surp = (d.get("surprises") or {}).get("inline") or {}
    kpis = "".join([
        _kpi_card("CPI 年增率", k["headline_display"], k["headline_sub"],
                  k["headline_plain"], charts.sparkline(k["headline_spark"]),
                  mini=mini.get("headline", ""), asof=(a.get("cpi") or "")[:7],
                  surprise=surp.get("headline"),
                  en="Headline CPI, y/y", leans=lean.get("headline", ())),
        _kpi_card("核心 CPI 年增率", k["core_display"], k["core_sub"],
                  k["core_plain"], charts.sparkline(k["core_spark"]),
                  k.get("core_flag"), k.get("core_flag_kind", ""),
                  mini=mini.get("core", ""), asof=(a.get("cpi") or "")[:7],
                  surprise=surp.get("core"),
                  en="Core CPI, y/y", leans=lean.get("core", ())),
        _kpi_card("核心 PCE 年增率", k["pce_display"], k["pce_sub"],
                  k["pce_plain"], charts.sparkline(k["pce_spark"]),
                  k.get("pce_flag"), k.get("pce_flag_kind", ""),
                  mini=mini.get("pce", ""), asof=(a.get("pce") or "")[:7],
                  en="Core PCE, y/y", leans=lean.get("pce", ())),
        _kpi_card("5年後5年期通膨預期", k["exp_display"], k["exp_sub"],
                  k["exp_plain"], charts.sparkline(k["exp_spark"]),
                  mini=mini.get("exp", ""), asof=(a.get("exp") or "")[:7],
                  en="5y5y Inflation Breakeven", leans=lean.get("exp", ())),
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

    # 有填預期才顯示來源說明。沒填時整段不出現——通膨不退回模型推估，
    # 所以也沒有「這不是市場共識」需要提醒。
    surp_foot = (f'<div class="kpi-foot">預期來源：'
                 f'{esc((d.get("surprises") or {}).get("sources", ""))}</div>'
                 if surp else "")

    # ---- 分項貢獻的分解條 ----
    #
    # 這裡**沒有等號，也不算差額**。
    #
    # 先前寫的是「三塊相加 ＝ +0.05（實際漲幅 +0.12 個百分點）」，再配一段
    # 「權重過期或四捨五入會讓兩邊對不上」。那個框法把讀者的注意力整個
    # 帶到「為什麼加不起來」，而那是錯的問題——BLS 的 CPI 是分層鏈式聚合、
    # 權重在期間內本身也會動，所以「單一時點權重 × 累計變化」的加總本來就
    # 不必等於官方漲幅。用官方權重驗過：估算合計 +0.17pp、實際 +0.12%，
    # 仍差 0.05。那是方法差異，不是計算錯誤。
    #
    # 這一區要回答的是：**哪些類別在推升 CPI、哪些在壓低。**
    parts = att.get("parts") or []
    parts_html = ""
    if parts:
        span = max(abs(x["value"]) for x in parts) or 1
        rows = "".join(
            f'<div class="dc-row">'
            f'<div class="dc-name">{esc(x["label"])}</div>'
            f'<div class="dc-bar"><span class="dc-zero"></span>'
            f'<i style="{"left" if x["value"] >= 0 else "right"}:50%;'
            f'width:{abs(x["value"]) / span * 50:.1f}%"></i></div>'
            f'<div class="dc-val">{x["value"]:+.2f}pp</div></div>'
            f'<div class="dc-note">{esc(x["note"])}</div>'
            for x in parts
        )
        parts_html = f'<div class="dcomp">{rows}</div>'

    # 「剔除住房後比含住房高」每期都可能出現，而且每次都會被讀成算錯。
    # 它其實是重要訊息（住房在把整體往下拉），所以直接寫成一句話。
    _sn = att.get("shelter_note") or ""
    shelter_html = ""
    if _sn:
        # **粗體** 轉成 <b>，其餘照 esc 處理
        parts_txt = _sn.split("**")
        rendered = "".join(
            (f"<b>{esc(seg)}</b>" if i % 2 else esc(seg))
            for i, seg in enumerate(parts_txt))
        shelter_html = f'<div class="warnbox" style="margin-top:16px">{rendered}</div>'

    # ---- 趨勢指標的結論 ----
    tv = d.get("trend_verdict") or {}
    trend_html = (
        f'<div class="verdict {tv["kind"]}" style="margin-top:4px">'
        f'<div class="v-main" style="font-size:20px">{esc(tv["title"])}</div>'
        f'<div class="v-why" style="margin-top:8px">{esc(tv["desc"])}</div></div>'
        if tv else '<div class="empty">資料不足</div>')

    # ---- 能源對總體的估計影響 ----
    eh = d.get("energy_headline") or {}
    energy_head = (
        f'<div class="bkgap" style="color:{eh["color"]}">'
        f'<span class="bk-label">對總體 CPI 的估計影響</span>'
        f'<span class="bk-val">{esc(eh["value"])}</span>'
        f'<span class="bk-verdict" style="font-weight:400;font-size:12.5px;'
        f'color:var(--muted)">{esc(eh["note"])}</span></div>'
        if eh else "")

    # 收合摘要：一律取這一區已經算出來的結論，不另外造句——
    # 摘要與內文若各說各話，收合狀態反而會誤導。
    _top = next((f for f in d["flags"] if f.severity == "alert"),
                (d["flags"] or [None])[0])
    _sig_sum = (f'{len(d["flags"])} 項　·　{_top.headline}' if _top
                else "本次沒有觸發任何訊號")
    _k = d["kpi"]
    _kpi_sum = (f'CPI {_k["headline_display"]}　·　核心 {_k["core_display"]}'
                f'　·　核心 PCE {_k["pce_display"]}')
    _att_sum = "　·　".join(f'{s["label"]} {s["value"]}'
                           for s in d["attribution"]["stats"][:2])
    # trend_verdict 是 dict（title/desc/kind），不是字串——直接 esc() 會把
    # 整個 dict 的 repr 印到標題列上。
    _tv = d.get("trend_verdict") or {}
    _trend_sum = esc(_tv.get("title") if isinstance(_tv, dict) else _tv
                     or "剔除極端值後的比較")
    _pt = d.get("passthrough") or {}
    _pt_sum = esc(_pt.get("verdict_title") or "資料不足")
    _en_sum = "　·　".join(f'{s["label"]} {s["value"]}'
                          for s in d["energy_stats"][:2])
    _lt = {}
    for _l in d["lights"]:
        _lt[_l.status] = _lt.get(_l.status, 0) + 1
    _light_sum = "、".join(
        f'{_n} 項{_lab}' for _key, _lab in
        (("critical", "警戒"), ("warning", "留意"), ("good", "正常"),
         ("unknown", "無資料")) if (_n := _lt.get(_key)))

    return f"""
{_verdict_card(d)}

<div class="grid">
  <div class="card">
    <h2 id="signals" data-open="1" data-sum="{esc(_sig_sum)}">本期關鍵訊號</h2>
    <p class="hint">點「依據」看支撐的數字。</p>
    {flags_html}
  </div>
</div>

{_sticky_card(d.get('stickiness'))}

<div class="grid">
  <div class="card">
    <h2 id="kpi" data-sum="{esc(_kpi_sum)}">關鍵數字</h2>
    <div class="grid g4 inner">{kpis}</div>
    {surp_foot}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="contrib" data-sum="{esc(_att_sum)}">分項貢獻分解</h2>
    <p class="hint">近三個月哪些類別在<b>推升</b> CPI、哪些在<b>壓低</b>。
      估算貢獻的單位是<b>個百分點（pp）</b>，跟價格漲幅的 % 不是同一件事。</p>
    <div class="stat-row">{_stats(att['stats'])}</div>
    <p class="hint" style="margin-top:-4px">兩者採不同計算口徑，不需完全相等。</p>
    {parts_html}
    {shelter_html}
    <details data-m-collapse><summary>各類別明細</summary>
    <div style="margin-top:14px">{att['bars']}</div>
    <div class="dlegend">
      <span><i style="background:var(--pos)"></i>推升物價</span>
      <span><i style="background:var(--neg)"></i>壓低物價</span>
      <span><i style="background:var(--muted-bar)"></i>落後項（住房）</span>
      <span>單位：個百分點（pp）</span>
    </div>
    <p class="hint" style="margin-top:14px">
      估算貢獻 ≈ 該類別的 BLS Relative Importance × 該類別期間價格變化。
      住房占 CPI 權重超過三分之一，因此即使漲幅不大，
      也可能對整體 CPI 產生明顯影響。</p>
    <p class="hint" style="margin-top:10px">
      分項貢獻為依 BLS Relative Importance 與各分類價格變化所做的
      <b>近似估算</b>，用於觀察不同類別對通膨的方向與相對影響。由於 CPI
      官方指數採用動態權重與分層聚合方法，估算貢獻加總不一定會與實際
      CPI 漲幅完全相等。</p>
    </details>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="trend" data-sum="{_trend_sum}">是全面在漲，還是少數項目？</h2>
    <p class="hint">三個指標用不同方法剔除極端值，再跟核心 CPI 比對。</p>
    {trend_html}
    <details data-m-collapse><summary>三個指標的定義與數值</summary>
      <table class="lefty" style="margin-top:10px">
        <thead><tr><th>指標</th><th>目前</th><th>算法</th></tr></thead>
        <tbody>{trend_rows}</tbody></table>
      <dl class="gloss" style="margin-top:14px">
        <dt>中位數 CPI</dt>
        <dd>把所有項目依漲幅排序，取正中間那一個。完全不受極端值影響。</dd>
        <dt>截尾平均</dt>
        <dd>把漲最多和跌最多的項目都剔除後再平均。</dd>
        <dt>黏性 CPI</dt>
        <dd>只看價格很少調整的項目（例如房租、保險）。這些代表通膨的慣性，
          一旦漲上去就很難降下來。</dd>
      </dl>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="passthrough" data-sum="{_pt_sum}">薪資到服務業通膨的傳導</h2>
    <p class="hint">這一塊的成本主體是人力。
      <b>薪資走向會在數月後反映到這裡，是通膨黏性的核心機制。</b></p>
    {_passthrough(d.get('passthrough'))}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="energy" data-sum="{esc(_en_sum)}">能源價格與傳導</h2>
    <p class="hint">「已經發生但還沒反映到數據裡」的部分。</p>
    <div class="stat-row">{_stats(d['energy_stats'])}</div>
    {energy_head}
    <p class="hint" style="margin:12px 0 0">{esc(d.get('energy_core_note', ''))}
      <b>除非久到推高通膨預期</b>，油價不改變利率決策。</p>

    <h3 style="margin-top:20px">WTI 原油（{esc(d.get('oil_span', ''))}）</h3>
    <p class="hint" style="margin:0 0 8px">虛線是一個月前的位置。</p>
    {d.get('oil_chart', '')}

    <details data-m-collapse><summary>零售汽油價格（{esc(d.get('gas_span', ''))}）</summary>
      <div style="margin-top:12px">{d.get('gas_chart', '')}</div>
      <p class="hint" style="margin-top:10px">
        汽油是 CPI 能源項裡權重最大的一塊，也是消費者最有感的價格。
        它落後原油約兩到四週。</p>
    </details>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="lights" data-sum="{esc(_light_sum)}">關鍵指標檢核</h2>
    <p class="hint">八項關鍵指標的當期狀態。</p>
    <details data-m-collapse open><summary>八項指標</summary>
      <div class="lights" style="margin-top:12px">{lights_html}</div>
    </details>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="glossary" data-sum="這一頁出現的專有名詞">名詞解釋</h2>
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
"""


def inflation_footer(d: dict) -> str:
    return (
        "資料來源：美國勞工統計局（BLS）、經濟分析局（BEA）、"
        "克里夫蘭聯準銀行與亞特蘭大聯準銀行，經 FRED 取得。<br>"
        f"CPI 權重版本：{esc(d.get('weights_vintage', '—'))}"
        "　·　權重每年一月由 BLS 更新，需同步校準。<br>"
        "本頁僅為數據整理，不構成投資建議。"
    )
