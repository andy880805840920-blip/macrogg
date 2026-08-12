"""聯準會文本頁的內容產生器（P3）。"""

from __future__ import annotations

import re

from .. import charts
from ..site import esc
from .labor import _kpi_card, _stats


# 「鷹／鴿」是聯準會語境的標準詞，這頁保留，但首次出現一律加註方向——
# 全站其他頁面說的是「利升息／利降息」，兩套詞要能互相對上。
DIR_COPY = {
    "hawkish": ("本次會議：偏鷹（利升息方向）",
                "客觀訊號指向緊縮——政策行動、反對票或聲明點名的風險方向指向更高的利率。"
                "這通常代表降息會比市場預期更慢，對債券價格不利。"),
    "dovish": ("本次會議：偏鴿（利降息方向）",
               "客觀訊號指向寬鬆——政策行動、反對票或聲明點名的風險方向指向更低的利率。"
               "這通常是降息的前置訊號。"),
    # 中性只代表「客觀訊號淨值落在 ±1 之內」，不代表沒有反對票、
    # 也不代表沒有升降息——降息 −3 加上兩張升息反對票 +4 也會落在這裡。
    # 所以這段不能斷言任何具體事實，實際組成看下方的分數明細。
    "neutral": ("本次會議：方向不明",
                "客觀訊號的正負兩邊大致抵銷，淨值接近中性。"
                "這可能是各項訊號都很弱，也可能是強度相當但方向相反——"
                "實際組成見下方「客觀訊號分數」的拆解。"),
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
        # 引言載明有反對票、名單卻解析不出來時，
        # 不能顯示「全體一致」——那是把解析失敗謊報成事實
        stated = vote.get("stated_dissent")
        if stated:
            chips.append(f'<span class="vchip">聲明載明 {stated} 張反對票，'
                         '名單解析失敗，請以原文為準</span>')
        else:
            chips.append('<span class="vchip">全體一致，沒有反對票</span>')
    return f'<div class="votes">{"".join(chips)}</div>'


def fomc_body(d: dict) -> str:
    sh = d.get("shift") or {}
    direction = sh.get("direction", "neutral")
    title, why = DIR_COPY.get(direction, DIR_COPY["neutral"])
    lean_cls = {"hawkish": "hawkish", "dovish": "dovish"}.get(direction, "balanced")

    vote = d.get("vote") or {}
    # 新版聲明把票數寫在開頭引言（「approved ... by a 9 – 3 vote」），
    # 一致通過時那是唯一的票數來源，所以優先採用。
    n_sup = vote.get("stated_support")
    if n_sup is None:
        n_sup = len(vote.get("supporting", []))
    stated_dis = vote.get("stated_dissent")
    n_dis = len(vote.get("dissents", [])) or (stated_dis or 0)
    hawk = sum(1 for x in vote.get("dissents", []) if x["direction"] == "hike")
    dove = sum(1 for x in vote.get("dissents", []) if x["direction"] == "cut")

    if n_sup:
        head = f"投票 {n_sup} 比 {n_dis}"
    elif n_dis:
        head = f"{n_dis} 票反對（本次聲明未列出贊成名單）"
    else:
        head = ""
    vote_line = (head
                 + (f"，其中 {hawk} 票主張升息" if hawk else "")
                 + (f"，{dove} 票主張降息" if dove else "")) if head else ""
    if vote.get("mismatch"):
        vote_line += ("　⚠ 引言票數與反對者名單不一致，"
                      "可能是聲明格式改變，請以原文為準")

    verdict = f"""<div class="verdict {lean_cls}">
  <div class="v-eyebrow">{esc(d['latest_date'])} 會議　·　一句話結論</div>
  <div class="v-main">{esc(title)}</div>
  <div class="v-why">{esc(why)}</div>
  <div class="v-count">
    {esc(vote_line)}{'　·　' if vote_line else ''}
    政策利率 {esc(d.get('rate_range', '—'))}
  </div>
</div>"""

    # ---- 雙分數 ----
    obj_cls = ("hawkish" if sh.get("objective", 0) > 1 else
               ("dovish" if sh.get("objective", 0) < -1 else "neutral"))
    tone_cls = ("hawkish" if sh.get("tone", 0) > 1 else
                ("dovish" if sh.get("tone", 0) < -1 else "neutral"))
    regime = d.get("regime") or {}
    tone_stale = " stale" if regime.get("detected") else ""

    # 兩個分數的版面權重要跟結論一致。先前兩者都是超大字並排，
    # 但這一頁自己說「以客觀訊號為準、措辭本次不可靠」——
    # 版面在說兩者同等重要，文字在說不是。改成主／副：
    # 客觀訊號保留大字與刻度軸，措辭降成旁邊一行。
    _obj = sh.get("objective", 0)
    _obj_pct = max(0, min(100, (_obj + 8) / 16 * 100))
    _obj_color = ("var(--serious)" if _obj > 1 else
                  ("var(--series-1)" if _obj < -1 else "var(--muted)"))
    _tone_flag = ('<span class="tone-flag">本次不可靠</span>'
                  if regime.get("detected") else "")
    dual = f"""<div class="dbox primary {obj_cls}">
  <div class="dtitle">客觀訊號分數（主要依據）</div>
  <div class="dscore">{_obj:+.2f}</div>
  <div class="dlab">{esc(sh.get('objective_label', ''))}
    <span style="font-weight:400;color:var(--muted)">
    　較上次 {sh.get('objective_delta', 0):+.2f}</span></div>
  <div class="score-bar" style="margin:14px 0 6px">
    <i style="left:{min(50, _obj_pct):.1f}%;width:{abs(_obj_pct - 50):.1f}%;
      background:{_obj_color}"></i><span class="score-mid"></span>
  </div>
  <div class="sax-scale"><span>−8 偏降息</span><span>0 中性</span><span>+8 偏升息</span></div>
  <div class="dnote" style="margin-top:10px">{esc(d.get('obj_detail', ''))}</div>
</div>
<div class="tone-row {tone_cls}{tone_stale}">
  <span class="tone-label">措辭分數（輔助）{_tone_flag}</span>
  <span class="tone-val">{sh.get('tone', 0):+.2f}</span>
  <span class="tone-delta">較上次 {sh.get('tone_delta', 0):+.2f}</span>
  <span class="tone-note">同一刻度。跨主席不可比，只當輔助。</span>
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

    # 比對對象要寫明。若中間某份聲明抓失敗，比對對象會默默換成更早的一份，
    # 不標出來讀者無從察覺「這兩份根本不是相鄰的兩次會議」。
    pair = d.get("diff_pair") or (None, None)
    diff_pair_note = ""
    if pair[0]:
        diff_pair_note = f"比對對象：{esc(pair[0])} → {esc(pair[1])} 的聲明。"
        n = len(d.get("fetched_dates") or [])
        if n:
            diff_pair_note += f"本次共取得 {n} 份聲明。"

    # ---- KPI 區 ----
    # 這一頁先前完全沒有 KPI，從結論卡直接跳進九百多 px 的大卡。
    # 四個現成的頭條數字：政策利率、投票、客觀訊號、下次會議倒數。
    vote = d.get("vote") or {}
    dctx = d.get("dissent_ctx") or {}
    mkt = d.get("market") or {}
    nm = d.get("next_meeting") or {}

    _act = (d.get("obj_parts") or {}).get("action_label") or ""
    kpis = [_kpi_card(
        "政策利率目標區間", d.get("rate_range", "—"),
        f"本次{_act}" if _act else "",
        "聯準會直接設定的短期利率區間。所有其他利率都以它為起點。"
        + ("" if d.get("rate_auto") else
           "　⚠️ 本次沒有取得 FRED 的 DFEDTARL／DFEDTARU，改用設定檔的後備值。"
           "期間若有調整過利率，這個區間與下方「市場定價 vs 聯準會」的"
           "判定都可能已經過時。"))]

    _sup = vote.get("stated_support")
    _dis = vote.get("dissents") or []
    _dis_n = len(_dis)
    if _sup is not None or _dis_n:
        _vv = (f"{_sup} 比 {_dis_n}" if _sup is not None else f"{_dis_n} 票反對")
        # 標籤要放「方向」不是再寫一次票數——票數已經是主數字了。
        # 反對票的方向才是決定鷹鴿的東西。
        _dirs = [x.get("direction") for x in _dis]
        _hike, _cut = _dirs.count("hike"), _dirs.count("cut")
        if _dis_n and _hike == _dis_n:
            _flag, _fk = f"{_dis_n} 票全主張升息", "neg"
        elif _dis_n and _cut == _dis_n:
            _flag, _fk = f"{_dis_n} 票全主張降息", "pos"
        elif _dis_n:
            _flag, _fk = f"{_hike} 票主張升息、{_cut} 票主張降息", ""
        else:
            _flag, _fk = "全體一致", "pos"
        kpis.append(_kpi_card(
            "本次投票", _vv,
            esc(dctx.get("note", "")) if dctx else "",
            "反對票是白紙黑字的事實，不受主席的溝通風格影響，"
            "所以在這一頁的權重最高。",
            flag=_flag, flag_kind=_fk))

    # 客觀訊號給一條歷次走勢：五次會議的分數是現成的，
    # 光看 +6.00 不知道這是常態還是跳動
    _hist = d.get("objective_history") or []
    kpis.append(_kpi_card(
        "客觀訊號分數", f"{sh.get('objective', 0):+.2f}",
        f"較上次 {sh.get('objective_delta', 0):+.2f}",
        "政策行動、反對票與聲明點名的風險方向合計。"
        "正數＝偏升息方向，負數＝偏降息方向。",
        spark_html=(charts.sparkline(_hist, zero_line=True) if len(_hist) > 1 else "")))

    if nm:
        kpis.append(_kpi_card(
            "下次會議", nm["display"], nm["sub"],
            "在那之前，這份聲明就是委員會的官方立場——"
            "距離下次會議越遠，它主導市場的時間越長。",
            flag=(f'之後：{nm["later"][0]}' if nm.get("later") else None)))
    elif mkt:
        kpis.append(_kpi_card(
            "市場定價 vs 現在", mkt["display"], "2 年期公債殖利率減政策利率中值",
            mkt["text"] + "。這是粗略代理，不是會議層級的機率。"))

    kpi_html = "".join(kpis)

    # 收合摘要：一律取這一區已經算出來的結論。
    _sc_sum = (f'客觀訊號 {sh.get("objective", 0):+.2f}'
               f'　·　措辭 {sh.get("tone", 0):+.2f}'
               + ("　·　兩者背離" if sh.get("diverge") else ""))
    _kpi_sum = (f'{esc(d.get("latest_date", ""))} 聲明　·　'
                f'改動 {d.get("changed_count", 0)} 處　·　'
                f'客觀訊號 {sh.get("objective", 0):+.2f}')
    _focus_sum = esc(focus.get("label", "無法判定"))
    _diff_sum = (f'{d.get("changed_count", 0)} 處改動'
                 + (f'（對照 {d["diff_pair"][0]}）'
                    if (d.get("diff_pair") or [None])[0] else ""))
    _n_stmt = len(d.get("fetched_dates") or [])
    _trend_sum = f'近 {_n_stmt} 次會議的分數與反對票'
    _mkt = d.get("market") or {}
    _mkt_sum = (f'差距 {_mkt["display"]}　·　'
                + ("與本次判讀一致" if _mkt.get("agree") else "與本次判讀分歧")
                ) if _mkt else ""

    # 市場定價對照：與本次判讀一致與否，本身就是資訊
    market_html = ""
    if mkt:
        _cls = {"hawkish": "hawkish", "dovish": "dovish"}.get(mkt["lean"], "neutral")
        _agree = ("與本次的客觀訊號方向一致——市場也讀到了同一件事。"
                  if mkt["agree"] else
                  "與本次的客觀訊號方向不一致。分歧本身就是值得追的東西："
                  "要嘛市場還沒反映這次會議，要嘛判讀漏看了什麼。")
        market_html = f"""
<div class="grid">
  <div class="card">
    <h2 id="market" data-sum="{esc(_mkt_sum)}">市場定價 vs 聯準會</h2>
    <p class="hint">2 年期殖利率跟政策利率中值的差，就是市場定價的政策路徑方向。</p>
    <div class="stat-row">{_stats([
        {"label": "2 年期公債殖利率", "value": f"{mkt['dgs2']:.2f}%"},
        {"label": "政策利率中值", "value": f"{mkt['mid']:.2f}%"},
    ])}</div>
    <div class="bkgap" style="color:{'var(--serious)' if mkt['lean'] == 'hawkish'
                                    else ('var(--series-1)' if mkt['lean'] == 'dovish'
                                          else 'var(--text-primary)')}">
      <span class="bk-label">差距</span>
      <span class="bk-val">{esc(mkt['display'])}</span>
    </div>
    <div class="verdict {_cls}" style="margin-top:14px">
      <div class="v-main" style="font-size:19px">{esc(mkt['text'])}</div>
      <div class="v-why" style="margin-top:8px">{esc(_agree)}</div>
    </div>
    <div class="src">粗略代理，不是會議層級的降息機率（見判讀說明）。</div>
  </div>
</div>"""

    # 聲明穩定度：「只改了 N 處」本身是訊號
    stab = d.get("stability") or {}
    stability_html = (
        f'<div class="verdict {stab["kind"]}" style="margin:0 0 16px">'
        f'<div class="v-main" style="font-size:19px">{esc(stab["title"])}</div>'
        f'<div class="v-why" style="margin-top:8px">{esc(stab["desc"])}</div></div>'
        if stab else "")

    # 反對票的歷史脈絡：「本次 3 票」單看沒有意義，
    # 要知道這在近期算不算多，才能決定要給它多少權重。
    dissent_hist = ""
    if dctx:
        _h = "、".join(f"{n}" for n in dctx["history"])
        dissent_hist = (
            f'<p class="hint" style="margin-top:14px">反對票脈絡：本次 '
            f'{dctx["current"]} 票，{esc(dctx["note"])}'
            f'（依序為 {_h} 票）。反對票數本身沒有方向——'
            f'方向要看每張票主張的是升息還是降息，見上方的投票明細。</p>')

    presser_html = ""
    if d.get("presser_available"):
        ps = d.get("presser_summary") or {}

        topics_html = "".join(
            f'<h3>{esc(t["name"])}</h3>'
            + "".join(f'<div class="pline">{esc(s)}</div>' for s in t["sentences"])
            for t in ps.get("topics", [])
        ) or '<div class="empty">逐字稿中找不到可歸類的段落</div>'

        # 分數來源句：把命中的詞標出來，讓分數可以被回推。
        # 標色分兩步：先把命中片段換成不含英文字母的占位符（長詞優先），
        # 全部換完才展開成 <mark>。不能邊換邊插 <mark>——
        # 後續的子詞（"elevated"）會命中已插入的
        # <mark>remains elevated</mark> 內部，產生巢狀錯標。
        score_html = ""
        for ln in ps.get("score_lines", []):
            src_text = ln["text"]
            tokens: dict[str, tuple[str, str]] = {}   # 占位符 → (原文, css class)
            for i, h in enumerate(sorted(ln["hits"], key=lambda x: -len(x["term"]))):
                tok = f"\x01{i}\x02"
                pat = re.compile(r"(?i)(?<![a-z])(" + re.escape(h["term"]) + r")(?![a-z])")
                m = pat.search(src_text)
                if not m:
                    continue
                tokens[tok] = (m.group(1),
                               "mn" if h["tag"] == "hawk" else "mo")
                src_text = src_text[:m.start()] + tok + src_text[m.end():]
            marked = esc(src_text)
            for tok, (orig, cls) in tokens.items():
                marked = marked.replace(
                    tok, f'<mark class="{cls}">{esc(orig)}</mark>')
            tags = "　".join(
                f'{h["term"]}（{"鷹" if h["tag"] == "hawk" else "鴿"} {h["weight"]:.1f}）'
                for h in ln["hits"])
            score_html += (f'<div class="drow2"><div class="dnew">{marked}</div>'
                           f'<div class="dlabel2" style="margin:7px 0 0">'
                           f'{esc(tags)}</div></div>')
        score_html = score_html or '<div class="empty">本場沒有命中任何詞典用語</div>'

        # 只列權重最高的前五句。列了幾句、佔總權重多少要講明，
        # 否則讀者把畫面上的數字加起來對不上總分，會以為分數算錯。
        _tot = ps.get("score_lines_total", 0)
        _shown = len(ps.get("score_lines", []))
        score_cov = ""
        if _tot > _shown:
            score_cov = (f"　這裡只列權重最高的 {_shown} 句（全文共 {_tot} 句命中，"
                         f"這幾句佔總權重約 {ps.get('score_lines_coverage', 0)}%），"
                         "所以逐句加總不會剛好等於分數。")

        words = ps.get("opening_len", 0) + ps.get("qa_len", 0)
        presser_html = f"""
  <div class="card">
    <h2 id="presser" data-sum="措辭分數 {d.get('presser_score', 0):+.2f}　·　逐字稿原句與主題摘要">記者會</h2>
    <p class="hint">市場的實際反應常常來自這裡，而不是聲明本身。以下是逐字稿原句。</p>
    <div class="stat-row">
      <div class="stat"><div class="s-label">記者會措辭分數</div>
        <div class="s-value">{d.get('presser_score', 0):+.2f}</div>
        <div class="s-note">與聲明用同一套詞典</div></div>
      <div class="stat"><div class="s-label">逐字稿長度</div>
        <div class="s-value">{words:,} 字</div>
        <div class="s-note">開場 {ps.get('opening_len', 0):,} ·
          問答 {ps.get('qa_len', 0):,}</div></div>
    </div>

    <h3 style="margin-top:20px">各主題怎麼說</h3>
    <p class="hint">開場聲明優先（那是準備稿），不足才從問答補。</p>
    {topics_html}

    <details data-m-collapse><summary>措辭分數是這幾句貢獻的</summary>
      <p class="hint" style="margin:10px 0 8px">
        藍色是鷹派詞、橘色是鴿派詞，括號內為權重。
        分數 ＝ 命中詞加權後除以每百字，所以長度不同的逐字稿仍可比。{esc(score_cov)}</p>
      {score_html}
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
                    "詳細錯誤只寫在 GitHub Actions 的執行紀錄裡，畫面上不另外列出。")
        else:
            note = ("<b>尚未發布</b><br>"
                    "逐字稿為 PDF，通常在會後數日才發布，所以會議當天無法納入。"
                    "發布後系統會自動補上並重算分數。")
        presser_html = f"""
  <div class="card">
    <h2 id="presser" data-sum="本次逐字稿尚未發布">記者會</h2>
    <p class="hint">會後記者會的逐字稿。市場的實際反應常常來自這裡。</p>
    <div class="warnbox" style="margin-top:4px">
      {note}<br>目前的結論僅根據聲明與投票紀錄。
    </div>
  </div>"""

    return f"""
{verdict}

<div class="grid">
  <div class="card">
    <h2 id="score" data-open="1" data-sum="{esc(_sc_sum)}">政策訊號評分</h2>
    <p class="hint">兩個分數刻意不合成——<b>背離本身就是訊號</b>。</p>
    {dual}
    {warn}{diverge}
    <details data-m-collapse><summary>本次投票明細</summary>
      <div style="margin-top:12px">{_votes(vote)}</div>
      <p class="hint" style="margin-top:12px">反對票是客觀事實、權重最高；
        措辭會隨主席個人偏好變動。</p>
    </details>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="kpi" data-sum="{_kpi_sum}">關鍵數字</h2>
    <div class="grid g4 inner">{kpi_html}</div>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="focus" data-sum="{_focus_sum}">聯準會目前的重心</h2>
    <p class="hint">同一份就業數據，在「通膨優先」與「就業優先」下會導向相反的決定。</p>
    <div class="dbox {focus_cls}" style="margin-top:4px">
      <div class="dtitle">目前重心</div>
      <div class="dlab" style="font-size:19px;margin-top:6px">{esc(focus.get('label', '—'))}</div>
      <div class="dnote">{esc(focus.get('note', ''))}</div>
    </div>
    {focus_ev}
    <div class="src">只用聲明制式句與投票紀錄，不用模型。</div>
  </div>
</div>
{market_html}
<div class="grid">
  <div class="card">
    <h2 id="diff" data-sum="{esc(_diff_sum)}">聲明逐句比對</h2>
    <p class="hint">「舊 → 新」並排，只標實際改動的字。
      橘色刪除線是拿掉的字，藍色是新增的字。</p>
    {stability_html}
    {d['diff_html']}
    <details data-m-collapse><summary>含未改動段落的全文</summary>
      <div style="margin-top:10px">{d['diff_full_html']}</div></details>
    <div class="src">{diff_pair_note}原文為英文。</div>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="trend" data-sum="{esc(_trend_sum)}">歷次分數</h2>
    <p class="hint">刻度相同：0＝中性、正＝偏升息、負＝偏降息。
      <b>措辭分數跨主席不可比</b>。</p>
    <div class="tscroll" style="margin-top:12px"><table>
      <thead><tr><th>會議日期</th><th>客觀訊號</th><th>措辭</th>
        <th>字數</th><th>反對票</th></tr></thead>
      <tbody>{d['score_rows']}</tbody></table></div>
    {dissent_hist}
  </div>
</div>

<div class="grid">
{presser_html}
</div>

<div class="grid">
  <div class="card">
    <h2 id="phrases" data-sum="熱力圖與詞典命中明細，本頁結論不依賴這一區">措辭的支撐材料</h2>
    <p class="hint">措辭分數的原始材料。<b>本頁的結論不依賴這一區</b>。</p>
    <details data-m-collapse><summary>關鍵措辭追蹤（熱力圖）</summary>
      <p class="hint" style="margin:10px 0 0">追蹤固定一組措辭在每次聲明中出現的次數，
        數的是字面出現次數，顏色越深代表出現越多次。
        <b>整排突然變空白，通常代表體例改變而非立場轉變</b>。</p>
      <div style="margin-top:12px">{d['heatmap_html']}</div></details>
    <details data-m-collapse><summary>詞典命中明細</summary>
      <p class="hint" style="margin:10px 0 0">這裡的次數<b>可能少於上方熱力圖</b>，
        兩者算法不同：熱力圖數的是該字面在全文出現幾次；計分為了避免重複扣分，
        同一段文字只算一次、長詞優先——「remains elevated」命中之後，
        裡面的「elevated」就不會再被算一遍。</p>
      <table style="margin-top:10px">
        <thead><tr><th>用語</th><th>方向</th><th>次數</th></tr></thead>
        <tbody>{d['hits_rows']}</tbody></table></details>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="howto" data-sum="計分方式、名詞與注意事項">判讀說明</h2>
        <dl class="gloss">
      <dt>客觀訊號分數怎麼算</dt>
      <dd>政策行動 ±3、每張反對票 ±2、聲明點名的風險方向 ±1，範圍 −8～+8。
        三項都是白紙黑字的事實，不受主席的溝通風格影響，所以跨主席可比。
        措辭分數則是依每百字的加權詞頻計算，只當輔助。</dd>
      <dt>2 年期為什麼能當市場定價的代理</dt>
      <dd>2 年期殖利率約等於市場預期的「未來兩年平均政策利率」，它跟目前
        政策利率中值的差就是市場定價的方向。但這是<b>粗略代理</b>而非會議
        層級的機率——2 年期同時含有期限溢酬，不能直接讀成純粹的政策路徑預期。
        要看逐次會議的隱含機率，得用聯邦資金期貨或亞特蘭大聯準銀行的
        Market Probability Tracker。</dd>
      <dt>措辭分數為什麼跨主席不可比</dt>
      <dd>計分詞典是照 Powell 時代的聲明體例校準的。主席換人、聲明體例改變，
        同樣的立場會得到不同的分數。比較時請以同一位主席任內的區間為準；
        客觀訊號分數（政策行動＋反對票＋風險方向）則不受影響，可以跨主席比。</dd>
      <dt>熱力圖與詞典命中的次數為什麼不一樣</dt>
      <dd>兩者算法不同。熱力圖數的是該字面在全文出現幾次；計分為了避免重複
        扣分，同一段文字只算一次、長詞優先——「remains elevated」命中之後，
        裡面的「elevated」就不會再被算一遍。所以命中明細的次數會少於熱力圖。</dd>
      <dt>記者會的句子是怎麼抽的</dt>
      <dd>依主題（通膨／就業／利率路徑／資產負債表）從逐字稿抽原句，
        開場聲明優先——那是準備稿，比即席問答精確。不做改寫也不用模型，
        每次執行抽到的句子完全一致。</dd>
      <dt>反對票最重要</dt>
      <dd>反對票是白紙黑字的事實，不會因為主席換人或文風改變而失真。
        每張反對票的方向都寫在聲明裡，比任何措辭都清楚。</dd>
      <dt>刪掉的字要小心解讀</dt>
      <dd>聯準會拿掉一個措辭，可能是立場改變，也可能只是主席不想再給指引。
        兩者意思完全不同——所以系統會偵測「大量措辭同時消失」並示警。</dd>
      <dt>分數是相對的</dt>
      <dd>絕對值沒有意義，看的是變化方向與幅度。詞典一旦調整，
        歷史分數必須整批重算。</dd>
      <dt>文本會落後數據</dt>
      <dd>聲明一年只有八次，中間可能已有兩三份就業與物價報告。
        文本用來校準數據判讀，不是取代它。</dd>
      <dt>為什麼沒有完整逐字稿</dt>
      <dd>會議的完整逐字稿依規定延後五年公布，所以這裡分析的是
        會後聲明、投票紀錄與記者會。</dd>
    </dl>
  </div>
</div>
"""


def fomc_footer(d: dict) -> str:
    return (
        "資料來源：美國聯準會（federalreserve.gov）會後聲明、投票紀錄、"
        "與記者會逐字稿。<br>"
        "會議日期取自聯準會行事曆頁；2 年期公債殖利率取自 FRED。<br>"
        "完整會議逐字稿依規定延後五年公布。政策利率區間需在 config/fomc.yaml "
        "手動更新（每次利率決議後）；其餘資料皆自動擷取。<br>"
        "計分與詞頻皆為確定性規則，不含模型生成內容。"
    )
