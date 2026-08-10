"""聯準會文本頁的內容產生器（P3）。"""

from __future__ import annotations

from .. import charts
from ..site import esc


# 「鷹／鴿」是聯準會語境的標準詞，這頁保留，但首次出現一律加註方向——
# 全站其他頁面說的是「利升息／利降息」，兩套詞要能互相對上。
DIR_COPY = {
    "hawkish": ("本次會議：偏鷹（利升息方向）",
                "客觀訊號指向緊縮——政策行動、反對票或聲明點名的風險方向指向更高的利率。"
                "這通常代表降息會比市場預期更慢，對債券價格不利。"),
    "dovish": ("本次會議：偏鴿（利降息方向）",
               "客觀訊號指向寬鬆——政策行動、反對票或聲明點名的風險方向指向更低的利率。"
               "這通常是降息的前置訊號。"),
    "neutral": ("本次會議：方向不明",
                "維持利率不變、沒有反對票，聲明也沒有點名特定風險。委員會維持彈性，"
                "方向由後續數據決定。"),
}


def _diff_block(rows, show_same: bool = False) -> str:
    out = []
    for r in rows:
        if r.kind == "same":
            if show_same:
                out.append(f'<div class="dsame">{esc(r.old)}</div>')
            continue
        if r.kind == "changed":
            out.append(
                f'<div class="drow2 changed"><div class="dlabel2">改寫</div>'
                f'<div class="dold">{r.old_html}</div>'
                f'<div class="darrow">↓ 改為</div>'
                f'<div class="dnew">{r.new_html}</div></div>')
        elif r.kind == "added":
            out.append(
                f'<div class="drow2 added"><div class="dlabel2">整句新增</div>'
                f'<div class="dnew">{esc(r.new)}</div></div>')
        else:
            out.append(
                f'<div class="drow2 removed"><div class="dlabel2">整句刪除</div>'
                f'<div class="dold">{esc(r.old)}</div></div>')
    return "".join(out) or '<div class="empty">這次聲明與上次完全相同</div>'


def _heatmap(matrix: dict) -> str:
    if not matrix.get("phrases"):
        return '<div class="empty">資料不足</div>'
    head = "".join(f"<th>{esc(d[2:7])}</th>" for d in matrix["dates"])
    rows = []
    for p, vals in zip(matrix["phrases"], matrix["grid"]):
        cells = "".join(
            f'<td class="h{min(v,3)}" data-tip="{esc(p)}｜{esc(dte)}｜出現 {v} 次">'
            f'{v if v else ""}</td>'
            for v, dte in zip(vals, matrix["dates"])
        )
        rows.append(f'<tr><th class="rowhead">{esc(p)}</th>{cells}</tr>')
    return (f'<div class="heatwrap"><table class="heat">'
            f'<thead><tr><th class="rowhead"></th>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def _votes(vote: dict) -> str:
    chips = []
    for d in vote.get("dissents", []):
        word = {"hike": "贊成升息", "cut": "贊成降息",
                "hold": "主張維持不變"}.get(d["direction"], "反對")
        chips.append(f'<span class="vchip {d["direction"]}">'
                     f'{esc(d["name"])}　{word}</span>')
    if not chips:
        chips.append('<span class="vchip">全體一致，沒有反對票</span>')
    return f'<div class="votes">{"".join(chips)}</div>'


def fomc_body(d: dict) -> str:
    sh = d.get("shift") or {}
    direction = sh.get("direction", "neutral")
    title, why = DIR_COPY.get(direction, DIR_COPY["neutral"])
    lean_cls = {"hawkish": "hawkish", "dovish": "dovish"}.get(direction, "balanced")

    vote = d.get("vote") or {}
    n_sup = len(vote.get("supporting", []))
    n_dis = len(vote.get("dissents", []))
    hawk = sum(1 for x in vote.get("dissents", []) if x["direction"] == "hike")
    dove = sum(1 for x in vote.get("dissents", []) if x["direction"] == "cut")

    # 2026 年 6 月起的新版聲明在有反對票時只列反對者、不列贊成名單，
    # 這時 n_sup 會是 0——不能寫成「投票 0 比 3」，那是假的票數。
    if n_sup:
        head = f"投票 {n_sup} 比 {n_dis}"
    elif n_dis:
        head = f"{n_dis} 票反對（本次聲明未列出贊成名單）"
    else:
        head = ""
    vote_line = (head
                 + (f"，其中 {hawk} 票主張升息" if hawk else "")
                 + (f"，{dove} 票主張降息" if dove else "")) if head else ""

    verdict = f"""<div class="verdict {lean_cls}">
  <div class="v-eyebrow">{esc(d['latest_date'])} 會議　·　一句話結論</div>
  <div class="v-main">{esc(title)}</div>
  <div class="v-why">{esc(why)}</div>
  <div class="v-count">
    {esc(vote_line)}{'　·　' if vote_line else ''}
    政策利率 {esc(d.get('rate_range', '—'))}<br>
    ⓘ 完整會議逐字稿依規定延後五年公布，所以這裡分析的是會後聲明、投票紀錄與記者會。
  </div>
</div>"""

    # ---- 雙分數 ----
    obj_cls = ("hawkish" if sh.get("objective", 0) > 1 else
               ("dovish" if sh.get("objective", 0) < -1 else "neutral"))
    tone_cls = ("hawkish" if sh.get("tone", 0) > 1 else
                ("dovish" if sh.get("tone", 0) < -1 else "neutral"))
    regime = d.get("regime") or {}
    tone_stale = " stale" if regime.get("detected") else ""

    dual = f"""<div class="dual">
  <div class="dbox primary {obj_cls}">
    <div class="dtitle">客觀訊號分數（主要依據）</div>
    <div class="dscore">{sh.get('objective', 0):+.2f}</div>
    <div class="dlab">{esc(sh.get('objective_label', ''))}
      <span style="font-weight:400;color:var(--muted)">
      　較上次 {sh.get('objective_delta', 0):+.2f}</span></div>
    <div class="dnote">刻度：0＝中性，正＝偏升息、負＝偏降息。
      政策行動 ±3、每張反對票 ±2、聲明點名的風險方向 ±1。<br>{esc(d.get('obj_detail', ''))}</div>
  </div>
  <div class="dbox {tone_cls}{tone_stale}">
    <div class="dtitle">措辭分數（輔助）{'　⚠ 本次不可靠' if regime.get('detected') else ''}</div>
    <div class="dscore">{sh.get('tone', 0):+.2f}</div>
    <div class="dlab">{esc(sh.get('tone_label', ''))}
      <span style="font-weight:400;color:var(--muted)">
      　較上次 {sh.get('tone_delta', 0):+.2f}</span></div>
    <div class="dnote">刻度同左：0＝中性，正＝措辭偏緊縮（依每百字的加權詞頻計算）。
      詞典為 Powell 時代的聲明體例校準，主席更迭或體例改變時可比性下降。</div>
  </div>
</div>"""

    warn = ""
    if regime.get("detected"):
        warn = (f'<div class="warnbox"><b>偵測到溝通方式改變</b><br>'
                f'{esc(regime.get("note", ""))}</div>')

    diverge = ""
    if sh.get("diverge"):
        diverge = ('<div class="warnbox"><b>兩個分數背離</b><br>'
                   '客觀訊號與措辭指向相反的方向。這種背離本身就是訊號——'
                   '通常代表委員會內部的分歧還沒反映到官方措辭上。'
                   '歷史上市場多半跟著客觀訊號走。</div>')

    # ---- 反應函數（聯準會目前的重心）----
    focus = d.get("focus") or {}
    focus_cls = {"inflation": "hawkish", "employment": "dovish"}.get(
        focus.get("focus", ""), "neutral")
    focus_ev = ""
    if focus.get("evidence"):
        focus_ev = ('<div class="src" style="border-top:none;padding-top:10px">'
                    '判定依據：' + esc("、".join(focus["evidence"])) + "</div>")

    presser_html = ""
    if d.get("presser_available"):
        presser_html = f"""
  <div class="card">
    <h2 id="presser">記者會</h2>
    <p class="hint">會後記者會的逐字稿。市場的實際反應常常來自這裡，而不是聲明本身。</p>
    <div class="stat-row">
      <div class="stat"><div class="s-label">記者會措辭分數</div>
        <div class="s-value">{d.get('presser_score', 0):+.2f}</div>
        <div class="s-note">與聲明用同一套詞典</div></div>
      <div class="stat"><div class="s-label">取得狀態</div>
        <div class="s-value" style="font-size:15px">已取得</div>
        <div class="s-note">逐字稿為 PDF，會後數日發布</div></div>
    </div>
    <details data-m-collapse><summary>逐字稿摘錄</summary>
      <div class="dsame" style="margin-top:10px">{esc(d.get('presser_excerpt', ''))}</div>
    </details>
  </div>"""
    else:
        # 取不到的原因不同，讀者要採取的行動也不同——
        # 「還沒發布」等就好，「缺套件」不處理就永遠不會有。
        reason = d.get("presser_reason", "pending")
        if reason == "no_pdfplumber":
            note = ("<b>環境缺少 PDF 解析套件</b><br>"
                    "逐字稿是 PDF，需要 <code>pdfplumber</code> 才能讀取，"
                    "目前的執行環境沒有安裝，所以這一區不會有資料——"
                    "這不是等待，不處理就不會自動出現。"
                    "請確認 <code>requirements.txt</code> 含有 pdfplumber 並重新執行。")
        elif reason == "parse_failed":
            note = ("<b>逐字稿解析失敗</b><br>"
                    "PDF 已下載但無法解析，可能是聯準會改了檔案格式。"
                    "詳細錯誤列在頁面底部的失敗清單。")
        else:
            note = ("<b>尚未發布</b><br>"
                    "逐字稿為 PDF，通常在會後數日才發布，所以會議當天無法納入。"
                    "發布後系統會自動補上並重算分數。")
        presser_html = f"""
  <div class="card">
    <h2 id="presser">記者會</h2>
    <p class="hint">會後記者會的逐字稿。市場的實際反應常常來自這裡。</p>
    <div class="warnbox" style="margin-top:4px">
      {note}<br>目前的結論僅根據聲明與投票紀錄。
    </div>
  </div>"""

    return f"""
{verdict}

<div class="grid">
  <div class="card">
    <h2 id="score">政策訊號評分</h2>
    <p class="hint">合成會掩蓋最有價值的資訊。兩者背離時，背離本身就是訊號。</p>
    {dual}
    {warn}{diverge}
    <h3>本次投票</h3>
    {_votes(vote)}
    <div class="src">
      反對票是客觀事實，不受主席的溝通風格影響，所以權重最高；
      措辭則會隨主席個人偏好變動。
    </div>
  </div>
</div>

<div class="grid g2">
  <div class="card">
    <h2 id="diff">聲明逐句比對</h2>
    <p class="hint">同一列並排「舊 → 新」，只有實際改動的字會被標示。
      橘色刪除線是拿掉的字，藍色是新增的字。</p>
    {d['diff_html']}
    <details data-m-collapse><summary>含未改動段落的全文</summary>
      <div style="margin-top:10px">{d['diff_full_html']}</div></details>
    <div class="src">本次共 {d['changed_count']} 處改動。原文為英文，未翻譯以免失真。</div>
  </div>

  <div class="card">
    <h2 id="focus">聯準會目前的重心</h2>
    <p class="hint">雙重使命的權重會隨時間移動。同一份就業數據，
      在「通膨優先」與「就業優先」下會導向相反的決定，
      所以情境合成頁的九宮格會依這個判定調整結論。</p>
    <div class="dbox {focus_cls}" style="margin-top:4px">
      <div class="dtitle">目前重心</div>
      <div class="dlab" style="font-size:19px;margin-top:6px">{esc(focus.get('label', '—'))}</div>
      <div class="dnote">{esc(focus.get('note', ''))}</div>
    </div>
    {focus_ev}
    <div class="src">判定只用聲明裡的制式句與投票紀錄，不用模型，每次執行結果一致。</div>
  </div>
</div>

<div class="grid">
{presser_html}
</div>

<div class="grid">
  <div class="card">
    <h2 id="trend">分數走勢</h2>
    <p class="hint">兩個分數的歷史軌跡，刻度相同：0＝中性，正＝偏升息方向、負＝偏降息方向。
      措辭分數在主席更迭處會有斷點，已標示。</p>
    <details data-m-collapse open><summary>歷次分數明細</summary>
      <table style="margin-top:12px">
        <thead><tr><th>會議日期</th><th>客觀訊號</th><th>措辭</th>
          <th>字數</th><th>反對票</th></tr></thead>
        <tbody>{d['score_rows']}</tbody></table>
    </details>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="phrases">關鍵措辭追蹤</h2>
    <p class="hint">追蹤固定一組措辭在每次聲明中出現的次數。
      顏色越深代表出現越多次。<b>整排突然變空白，通常代表體例改變而非立場轉變</b>。</p>
    <details data-m-collapse open><summary>展開熱力圖</summary>
      <div style="margin-top:12px">{d['heatmap_html']}</div></details>
  </div>
</div>

<div class="grid g2">
  <div class="card">
    <h2 id="hits">詞典命中明細</h2>
    <p class="hint">詞典命中明細，用來檢查措辭分數是怎麼算出來的。</p>
    <details data-m-collapse><summary>命中明細</summary>
      <table style="margin-top:10px">
        <thead><tr><th>用語</th><th>方向</th><th>次數</th></tr></thead>
        <tbody>{d['hits_rows']}</tbody></table></details>
  </div>

  <div class="card">
    <h2 id="howto">判讀說明</h2>
    <dl class="gloss">
      <dt>反對票最重要</dt>
      <dd>反對票是白紙黑字的事實，不會因為主席換人或文風改變而失真。
        三票主張升息，比任何措辭都清楚。</dd>
      <dt>刪掉的字要小心解讀</dt>
      <dd>聯準會拿掉一個措辭，可能是立場改變，也可能只是主席不想再給指引。
        兩者意思完全不同——所以系統會偵測「大量措辭同時消失」並示警。</dd>
      <dt>分數是相對的</dt>
      <dd>絕對值沒有意義，看的是變化方向與幅度。詞典一旦調整，
        歷史分數必須整批重算。</dd>
      <dt>文本會落後數據</dt>
      <dd>聲明一年只有八次，中間可能已有兩三份就業與物價報告。
        文本用來校準數據判讀，不是取代它。</dd>
    </dl>
  </div>
</div>
"""


def fomc_footer(d: dict) -> str:
    return (
        "資料來源：美國聯準會（federalreserve.gov）會後聲明、投票紀錄、"
        "與記者會逐字稿。<br>"
        "完整會議逐字稿依規定延後五年公布。本模組無須手動維護資料。<br>"
        "計分與詞頻皆為確定性規則，不含模型生成內容。"
    )
