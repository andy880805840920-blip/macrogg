"""情境合成頁的內容產生器（P4）。"""

from __future__ import annotations

from ..site import esc

LEAN_TEXT = {"dovish": "利降息", "hawkish": "利升息", "neutral": "中性"}


def _grid(cells) -> str:
    head = ('<div class="axis"></div>'
            + "".join(f'<div class="axis">通膨{esc(i)}</div>'
                      for i in ("低", "中", "高")))
    rows = []
    for row in cells:
        label = row[0]["labor"]
        rows.append(f'<div class="axis row">就業{esc(label)}</div>')
        for c in row:
            badge = ""
            if c["current"]:
                badge = '<div class="sbadge">目前位置</div>'
                if c.get("overridden"):
                    badge += ('<div class="sbadge alt">結論已依重心修正</div>')
            rows.append(
                f'<div class="scell {c["lean"]}{" on" if c["current"] else ""}">'
                f'<div class="sname">{esc(c["name"])}</div>'
                f'<div class="sdesc">{esc(c["desc"])}</div>{badge}</div>'
            )
    return f'<div class="sgrid">{head}{"".join(rows)}</div>'


def _triggers(trigs) -> str:
    if not trigs:
        return '<div class="empty">資料不足，無法計算觸發距離</div>'
    out = []
    for t in trigs:
        # 約束條件那一軸要標出來：在通膨優先的體制下，勞動那幾條就算
        # 全部觸發也不會單獨改變政策方向，讀者該盯的是通膨那條。
        tag = ('<span class="tbind">關鍵</span>'
               if getattr(t, "binding", False) else "")
        out.append(
            f'<div class="trig{" met" if t.met else ""}">'
            f'<div class="tname">{esc(t.label)}{tag}</div>'
            f'<div class="tdist">{esc("已觸發" if t.met else t.distance)}</div>'
            f'<div class="tnow">目前 {esc(t.current)}　·　{esc(t.threshold)}</div>'
            f"</div>"
        )
    return "".join(out)


PRESSURE_LABEL = {"high": "偏高", "moderate": "中性", "low": "偏低"}


def _rates_line(r: dict | None) -> str:
    """長端供給壓力：刻意不併入九宮格，因為它決定的是曲線形狀而非政策方向。"""
    if not r:
        return ""
    cls = {"high": "hawkish", "low": "dovish"}.get(r["level"], "balanced")
    parts = "".join(
        f'<div class="cmove"><div>{esc(p["label"])}</div>'
        f'<div class="cm-delta {"up" if p["score"] > 0 else "down"}">{p["score"]:+.2f}</div>'
        f'<div class="cm-val">{esc(p["detail"])}</div></div>'
        for p in r["parts"]
    )
    return f"""
<div class="grid">
  <div class="card">
    <h2 id="curve-pressure">長端供給壓力（不進九宮格）</h2>
    <p class="hint">九宮格決定的是<b>政策利率往哪走</b>；長端供給壓力決定的是
      <b>曲線的形狀</b>。兩者由不同的力量驅動，硬合成會把
      「降息但長端不降」這種最需要看見的情況抹掉，所以分開列。</p>
    <div class="verdict {cls}" style="margin:14px 0 0">
      <div class="v-eyebrow">供給壓力 {esc(PRESSURE_LABEL.get(r['level'], '—'))}　·　綜合分數 {r['score']:+.2f}</div>
      <div class="v-main">{esc(r['curve_title'])}</div>
      <div class="v-why">{esc(r['curve_desc'])}</div>
      <div class="v-count">{esc(r['desc'])}</div>
    </div>
    <p class="hint" style="margin-top:18px">壓力分數的前三大來源：</p>
    <div class="cmoves" style="border-top:none;padding-top:0">{parts}</div>
    <div class="src">完整拆解、殖利率曲線、政府債務動態與科技巨頭發債請見
      <a href="/rates/">長端與債務</a>頁。</div>
  </div>
</div>
"""


def scenario_body(d: dict) -> str:
    sc = d["scenario"]

    incomplete = ""
    if sc.incomplete:
        incomplete = (
            '<div class="v-count" style="border-top:none;padding-top:0;margin-top:12px">'
            f'⚠️ 以下模組尚無資料，這個判定並不完整：{esc("、".join(sc.incomplete))}。'
            "</div>"
        )

    drivers = "".join(f"<li>{esc(x)}</li>" for x in sc.drivers)
    drivers_html = (f'<ul style="margin:10px 0 0;padding-left:20px;font-size:14px;'
                    f'line-height:1.9;color:var(--text-secondary)">{drivers}</ul>'
                    if drivers else "")

    pos_rows = "".join(
        f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>"
        for k, v in (sc.positioning or {}).items()
    )
    pos_note = (f'<div class="warnbox" style="margin:0 0 14px">'
                f'{esc(sc.positioning_note)}</div>'
                if getattr(sc, "positioning_note", "") else "")

    # 只有真的有某一軸被標成「關鍵」時才解釋這個標記——
    # 「兩邊並重」與「無法判定」時沒有任何一條會被標，
    # 這時還寫「標關鍵的那一軸…」等於叫讀者去找不存在的東西。
    has_binding = any(getattr(t, "binding", False) for t in sc.triggers)
    binding_hint = (
        "標「關鍵」的那一軸是目前的約束條件；另一軸就算觸發，"
        "在現在的反應函數下也不會單獨改變政策方向。"
        if has_binding else
        "目前聯準會沒有明顯偏向任何一邊，兩軸都可能主導——"
        "哪一邊先觸發，哪一邊就會決定方向。")

    fomc_note = (f'<div class="v-why" style="margin-top:14px">{esc(sc.fomc_note)}</div>'
                 if sc.fomc_note else "")

    # ---- 反應函數：聯準會目前把哪一邊擺在前面 ----
    focus = sc.focus or {}
    focus_cls = {"inflation": "hawkish", "employment": "dovish"}.get(
        focus.get("focus", ""), "balanced")
    focus_ev = ""
    if focus.get("evidence"):
        focus_ev = ('<div class="src">判定依據：'
                    + esc("、".join(focus["evidence"]))
                    + "　·　來源為聲明制式句與投票紀錄，不用模型。</div>")
    focus_block = f"""
<div class="grid">
  <div class="card">
    <h2 id="focus">聯準會目前的重心</h2>
    <p class="hint">九宮格如果用固定的對照表，等於假設雙重使命的權重永遠一樣。
      實際上反應函數會移動——2020 年是就業優先，現在明顯不是。
      同一格在兩種體制下的結論可能完全相反，所以先判定重心，再修正結論。</p>
    <div class="verdict {focus_cls}" style="margin-top:4px">
      <div class="v-eyebrow">目前重心</div>
      <div class="v-main" style="font-size:22px">{esc(focus.get('label', '無法判定'))}</div>
      <div class="v-why">{esc(focus.get('note', ''))}</div>
      {f'<div class="v-count">{esc(sc.focus_note)}</div>' if sc.focus_note else ''}
    </div>
    {focus_ev}
  </div>
</div>"""

    # 方向被反應函數改寫時，標題用修正後的結論，並把原始格位另外標明，
    # 讀者才不會看到「標題寫轉向降息、傾向卻是中性」這種矛盾。
    override_line = ""
    if sc.overridden:
        override_line = (
            f'<div class="v-count" style="border-top:none;padding-top:0;'
            f'margin-top:10px">九宮格原始定位是「{esc(sc.name)}」'
            f'（就業{esc(sc.labor_state)} × 通膨{esc(sc.infl_state)}），'
            f'已依聯準會目前重心「{esc(focus.get("label", ""))}」修正為上方的結論。</div>')

    return f"""
<div class="verdict {sc.lean}">
  <div class="v-eyebrow">{esc(d['as_of'])}　·　目前情境</div>
  <div class="v-main">{esc(sc.verdict_name or sc.name)}</div>
  <div class="v-why">{esc(sc.verdict_desc or sc.description)}</div>
  {override_line}
  {fomc_note}
  <div class="v-count">
    定位：就業{esc(sc.labor_state)}　×　通膨{esc(sc.infl_state)}　·
    政策傾向 {esc(LEAN_TEXT.get(sc.lean, ''))}<br>
    這裡刻意不給機率。機率市場早就定價了，有價值的是「我的判讀跟市場定價差在哪」。
  </div>
  {incomplete}
</div>
{focus_block}
<div class="grid">
  <div class="card">
    <h2 id="grid">九宮格定位</h2>
    <p class="hint">聯準會有兩個目標：充分就業與物價穩定。
      同一份就業數據，在通膨高和通膨低的環境下會導向完全相反的決定，
      所以要把兩邊擺在一起看。</p>
    {_grid(d['cells'])}
    <p class="hint" style="margin-top:16px">
      左下角（就業弱、通膨低）是降息最順的情況；右下角（就業弱、通膨高）
      是停滯性通膨，兩個目標互相打架，聯準會最難處理。<br>
      格子本身是固定的框架，最終的政策傾向還會依上方的「目前重心」修正。
    </p>
  </div>
</div>
{_rates_line(d.get('rates_line'))}
<div class="grid g2">
  <div class="card">
    <h2 id="drivers">主要驅動因素</h2>
    <p class="hint">來自兩個模組的規則引擎，依嚴重度排序。</p>
    {drivers_html or '<div class="empty">尚無資料</div>'}
    <div class="src">完整清單請見勞動市場頁與通膨頁。</div>
  </div>

  <div class="card">
    <h2 id="triggers">情境轉換門檻</h2>
    <p class="hint">不給機率，但給明確的門檻與目前的距離——
      這比機率誠實，也更能直接拿來盯。{binding_hint}</p>
    {_triggers(sc.triggers)}
  </div>
</div>

<div class="grid g2">
  <div class="card">
    <h2 id="positioning">固定收益部位對照</h2>
    <p class="hint">情境到部位的映射框架。這是方向性的參考，不是進出場訊號。</p>
    {pos_note}
    <dl class="gloss">{pos_rows or '<dt>尚無資料</dt><dd>—</dd>'}</dl>
    <div class="src">
      本頁僅為分析框架，不構成投資建議。實際部位決策仍需自行判斷。
    </div>
  </div>

  <div class="card">
    <h2 id="market">市場定價對照</h2>
    <p class="hint">研究的價值在於找出自己的判讀與市場的分歧。</p>
    <div class="soonbox" style="margin-top:0;padding:26px 18px;box-shadow:none;
      border-style:dashed">
      <h3>尚未接入</h3>
      <p>規劃使用亞特蘭大聯準銀行的 Market Probability Tracker，
        它從聯邦資金利率選擇權推導出市場對各次會議的隱含機率，公開且免費。
        接上之後這一區會並列「模型判讀」與「市場定價」，並標出差異的來源。</p>
    </div>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="howto">判讀說明</h2>
    <dl class="gloss">
      <dt>為什麼不給機率</dt>
      <dd>市場已經有現成的機率報價了，複述它沒有附加價值。
        有價值的是指出「我算出來偏鴿，但市場定價偏鷹，差異來自市場低估了修正值」
        這類具體的分歧。</dd>
      <dt>格子會怎麼移動</dt>
      <dd>通常是一次移動一格，而且往往是通膨先動、就業後動。
        跳格（例如從「按兵不動」直接到「衰退式降息」）多半發生在有外生衝擊時。</dd>
      <dt>長端為什麼不進九宮格</dt>
      <dd>九宮格回答的是「聯準會會不會動、往哪動」，那是政策利率。
        30 年期殖利率則由債券供給、財政狀況與期限溢酬決定，聯準會控制不了。
        把兩者合成一個分數，會讓「降息但長端不降」這種最關鍵的組合消失，
        所以它獨立列在上方。</dd>
      <dt>殖利率曲線變陡／變平</dt>
      <dd>「變陡」是短天期利率降得比長天期多，通常出現在降息初期；
        「變平」是短天期被推高或長天期被壓低，通常出現在升息或景氣疑慮升高時。</dd>
      <dt>存續期間（久期）</dt>
      <dd>債券對利率變動的敏感度。存續期間越長，利率一動、價格波動越大。
        預期降息時拉長存續期間，賺的就是價格上漲。</dd>
      <dt>抗通膨債券</dt>
      <dd>本金會隨通膨調整的公債（TIPS）。通膨預期升高時它會比一般公債強。</dd>
      <dt>公司債利差</dt>
      <dd>公司債殖利率高於同天期公債的部分，也就是投資人要求的風險補償。
        景氣轉差時利差走闊，公司債價格相對承壓。</dd>
      <dt>文本的角色</dt>
      <dd>聯準會的措辭用來校準，不是決定格子的位置。
        當措辭與數據方向不一致時，通常代表官員看到了數據還沒反映的東西，
        或反過來——他們還沒承認數據已經轉向。</dd>
    </dl>
  </div>
</div>
"""


def scenario_footer(d: dict) -> str:
    return (
        "情境分類由固定規則產生：勞動綜合分數 × 核心 PCE 與三月年化的加權水準，"
        "再由聯準會文本語氣校準。<br>"
        "長端供給壓力另行計算，不併入九宮格——它影響的是曲線形狀，不是政策方向。<br>"
        "本頁僅為分析框架，不構成投資建議。"
    )
