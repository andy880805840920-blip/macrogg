"""
首頁 — 五個模組的摘要，以及目前的情境結論。

設計原則：首頁只回答「現在是什麼狀況、為什麼」，細節都在各分頁。
任何模組缺資料時，畫面上明確標示缺哪一塊，不假裝結論已經完整。
"""

from __future__ import annotations

import datetime as dt

from ..site import esc, next_first_friday

LEAN_TEXT = {"dovish": "利降息", "hawkish": "利升息",
             "neutral": "中性", "balanced": "多空拉鋸"}
SEV_ICON = {"alert": "■", "watch": "▲", "info": "●"}


def _module_card(href, name, when, value, note, more, pending=False) -> str:
    cls = "modcard pending" if pending else "modcard"
    return f"""<a class="{cls}" href="{href}">
  <div class="m-top"><span class="m-name">{esc(name)}</span>
    <span class="m-when">{esc(when)}</span></div>
  <div class="m-value">{esc(value)}</div>
  <div class="m-note">{esc(note)}</div>
  <div class="m-more">{esc(more)} →</div>
</a>"""


def _change_card(cs) -> str:
    """本期變化摘要——對每期都追的人，這裡的邊際資訊量最高。"""
    if cs is None:
        return ""
    if not cs.has_previous:
        return (f'<div class="chg"><div class="ctitle">本期變化</div>'
                f'<div class="chead">{esc(cs.headline)}</div>'
                f'<div class="v-count" style="border-top:none;padding-top:8px">'
                f'下次執行後，這裡會自動列出情境移動、新增與消失的訊號，'
                f'以及關鍵數字的變化。</div></div>')

    # 什麼都沒變時不值得一整張卡：壓成一行，把版面留給有變化的資訊。
    quiet = (not cs.scenario_moved and not cs.new_flags
             and not cs.resolved_flags and not cs.metric_moves)
    if quiet:
        return (f'<div class="chg quiet"><span class="ctitle">本期變化</span>'
                f'<span>{esc(cs.headline)}</span>'
                f'<span class="ctitle">對照 {esc(cs.prev_at)}</span></div>')

    # 「新增／消失」語意不明——改成「新觸發／已解除」，並掛上該訊號
    # 對利率的方向章，讀者不必點進分頁就知道這條變化偏哪邊。
    def _lean_chip(lean: str) -> str:
        if lean in ("dovish", "hawkish"):
            return (f'<span class="clean {lean}">'
                    f'{LEAN_TEXT.get(lean, "")}</span>')
        return ""

    items = []
    for f in cs.new_flags[:6]:
        items.append(f'<div class="citem new"><span class="cmark">新觸發</span>'
                     f'<span>{esc(f["title"])}</span>'
                     f'<span class="cmod">{esc(f["module"])}</span>'
                     f'{_lean_chip(f.get("lean", ""))}</div>')
    for f in cs.resolved_flags[:6]:
        items.append(f'<div class="citem gone"><span class="cmark">已解除</span>'
                     f'<span>{esc(f["title"])}</span>'
                     f'<span class="cmod">{esc(f["module"])}</span>'
                     f'{_lean_chip(f.get("lean", ""))}</div>')
    items_html = ""
    if items:
        items_html = (
            '<div class="src" style="border-top:none;padding-top:0;margin-top:10px">'
            '「新觸發」＝本期新出現的訊號；「已解除」＝上期有、本期不再成立。</div>'
            f'<div class="clist">{"".join(items)}</div>')

    moves = []
    for m in cs.metric_moves[:8]:
        cls = "up" if m["delta"] > 0 else "down"
        # 兩個「率」相減是**個百分點**，不是 %。用同一個單位字串印水準與變化量，
        # 會讓「失業率 4.1 → 4.3」的變化顯示成「+0.20%」，讀者會當成漲了 0.2%。
        dunit = m.get("delta_unit") or m.get("unit", "")
        moves.append(
            f'<div class="cmove"><div>{esc(m["label"])}</div>'
            f'<div class="cm-delta {cls}">{m["delta"]:+.2f}{esc(dunit)}</div>'
            f'<div class="cm-val">{m["from"]:,.2f} → {m["to"]:,.2f}{esc(m["unit"])}</div>'
            f"</div>")
    moves_html = (f'<div class="cmoves">{"".join(moves)}</div>' if moves else "")

    sub = []
    if cs.labor_score_delta is not None:
        sub.append(f"勞動綜合分數 {cs.labor_score_delta:+.2f}")
    if cs.persisting:
        sub.append(f"{cs.persisting} 項訊號延續")
    sub.append(f"對照 {cs.prev_at}")

    return f"""<div class="chg{' moved' if cs.scenario_moved else ''}">
  <div class="ctitle">本期變化　·　{esc('　·　'.join(sub))}</div>
  <div class="chead">{esc(cs.headline)}</div>
  {items_html}{moves_html}
</div>"""


def home_body(ctxs: dict) -> str:
    lab = ctxs.get("labor")
    inf = ctxs.get("inflation")
    fom = ctxs.get("fomc")
    scn = ctxs.get("scenario")
    sc = (scn or {}).get("scenario")

    # ---------------- 情境結論 ----------------
    if sc:
        lean_cls = sc.lean
        incomplete = ""
        if sc.incomplete:
            incomplete = (f'⚠️ 以下模組尚無資料，結論並不完整：'
                          f'{esc("、".join(sc.incomplete))}。')
        drivers = "<br>".join(esc(x) for x in sc.drivers[:3])
        # 結論被反應函數改寫時，首頁標題也要用修正後的版本
        ovr = ""
        if getattr(sc, "overridden", False):
            ovr = (f'<br>九宮格原始定位「{esc(sc.name)}」，'
                   f'已依聯準會目前重心'
                   f'「{esc((sc.focus or {}).get("label", ""))}」修正。')
        hero = f"""<div class="verdict {lean_cls}">
  <div class="v-eyebrow">{esc((scn or {}).get('as_of', ''))}　·　目前情境</div>
  <div class="v-main">{esc(sc.verdict_name or sc.name)}</div>
  <div class="v-why">{esc(sc.verdict_desc or sc.description)}</div>
  <div class="v-count">
    定位：就業{esc(sc.labor_state)}　×　通膨{esc(sc.infl_state)}　·
    政策傾向 {esc(LEAN_TEXT.get(sc.lean, ''))}{ovr}
    {('<br>' + drivers) if drivers else ''}
    {('<br>' + incomplete) if incomplete else ''}
  </div>
</div>"""
    else:
        hero = ('<div class="verdict balanced"><div class="v-main">尚無資料</div>'
                '<div class="v-why">請先執行 python run.py 產生資料。</div></div>')

    # ---------------- 五張模組卡 ----------------
    cards = []

    if lab:
        k = lab["kpi"]
        cards.append(_module_card(
            "/labor/", "勞動市場", f"{lab['data_month']} 資料",
            k["nfp_display"],
            f"失業率 {k['u3_display']}　·　時薪年增 {k['ahe_display']}　·　"
            f"{LEAN_TEXT.get(lab['tilt']['tilt'], '')}",
            "看修正追蹤、行業增減與健康檢查"))
    else:
        cards.append(_module_card("/labor/", "勞動市場", "無資料", "—",
                                  "尚未產生", "P1", pending=True))

    if inf:
        k = inf["kpi"]
        cards.append(_module_card(
            "/inflation/", "通膨", f"{inf['data_month']} 資料",
            k["core_display"],
            f"核心 PCE {k['pce_display']}　·　長期預期 {k['exp_display']}　·　"
            f"{LEAN_TEXT.get(inf['tilt']['tilt'], '')}",
            "看分項貢獻、住房落後與能源傳導"))
    else:
        cards.append(_module_card("/inflation/", "通膨", "建置中", "—",
                                  "CPI／PPI／PCE 分項貢獻分解", "P2", pending=True))

    if fom and not fom.get("empty"):
        shift = fom.get("shift", {})
        # 對外一律報「客觀訊號分數」（政策行動 + 反對票 + 風險方向）。
        # 措辭分數只是輔助，而且在溝通方式改變時會被停用——
        # 首頁若顯示措辭分數，會出現「+0.00 偏鷹」這種自相矛盾的卡片。
        # 首頁說的是「利升息／利降息」語言，鷹鴿要帶翻譯
        lean_note = {"hawkish": "（利升息）", "dovish": "（利降息）"}.get(
            shift.get("direction", ""), "")
        cards.append(_module_card(
            "/fomc/", "聯準會文本", f"{fom['latest_date']} 聲明",
            f"{shift.get('objective', 0):+.2f}",
            f"{esc(shift.get('label', ''))}{lean_note}　·　"
            f"本次 {fom['changed_count']} 處改動",
            "看聲明逐句比對與措辭熱力圖"))
    else:
        cards.append(_module_card("/fomc/", "聯準會文本", "建置中", "—",
                                  "聲明紅線比對、措辭熱力圖、鷹鴿計分", "P3",
                                  pending=True))

    rat = ctxs.get("rates")
    if rat:
        sp = rat["pressure"]
        lvl = {"high": "偏高", "moderate": "中性", "low": "偏低"}.get(sp.level, "—")
        c = rat["curve"]
        y30 = (c.levels or {}).get("30Y")
        y10 = (c.levels or {}).get("10Y")
        cards.append(_module_card(
            "/rates/", "長端與債務", f"{rat['as_of']} 資料",
            (f"{y30:.2f}%" if y30 is not None else "—"),
            (f"10 年 {y10:.2f}%　·　" if y10 is not None else "")
            + f"供給壓力{lvl}　·　期限溢酬 "
            + (f"{c.term_premium:+.2f}%" if c.term_premium is not None else "—"),
            "看曲線拆解、債務動態與科技巨頭發債"))
    else:
        cards.append(_module_card("/rates/", "長端與債務", "無資料", "—",
                                  "殖利率曲線、政府債務與發債供給", "P5", pending=True))

    if sc:
        cards.append(_module_card(
            "/scenario/", "情境合成", "即時",
            sc.verdict_name or sc.name,
            f"就業{sc.labor_state} × 通膨{sc.infl_state}　·　"
            f"{LEAN_TEXT.get(sc.lean, '')}",
            "看九宮格定位與觸發距離"))
    else:
        cards.append(_module_card("/scenario/", "情境合成", "建置中", "—",
                                  "勞動 × 通膨 九宮格", "P4", pending=True))

    # ---------------- 重點訊號 ----------------
    all_flags = []
    if lab:
        all_flags += [("就業", f) for f in lab["flags"]]
    if inf:
        all_flags += [("物價", f) for f in inf["flags"]]
    order = {"alert": 0, "watch": 1, "info": 2}
    all_flags.sort(key=lambda x: order.get(x[1].severity, 9))

    rows = []
    for src, f in all_flags[:5]:
        rows.append(
            f'<div class="flag {f.severity}">'
            f'<span class="f-icon">{SEV_ICON.get(f.severity, "●")}</span>'
            f'<div><div class="f-head">{esc(f.headline)}'
            f'<span class="f-tag">{esc(src)}</span></div></div></div>'
        )
    if len(all_flags) > 5:
        rows.append(f'<div class="src">另有 {len(all_flags)-5} 項，見各分頁</div>')
    flags_html = "".join(rows) or '<div class="empty">本次沒有觸發任何訊號</div>'

    # ---------------- 發布節奏 ----------------
    nxt = next_first_friday()
    days = (nxt - dt.date.today()).days
    pace = [
        {"label": "下次就業報告（推估）", "value": nxt.isoformat(),
         "note": f"約 {days} 天後　·　依「次月第一個週五」慣例推估"},
    ]
    if lab:
        pace.append({"label": "就業資料月份", "value": lab["data_month"],
                     "note": "JOLTS 另落後約兩個月"})
    if inf:
        pace.append({"label": "物價資料月份", "value": inf["data_month"],
                     "note": "PCE 較 CPI 晚約兩週"})
    if fom and not fom.get("empty"):
        pace.append({"label": "最新聲明", "value": fom["latest_date"],
                     "note": "FOMC 一年開會八次"})

    pace_html = "".join(
        f'<div class="stat"><div class="s-label">{esc(p["label"])}</div>'
        f'<div class="s-value">{esc(p["value"])}</div>'
        f'<div class="s-note">{esc(p["note"])}</div></div>' for p in pace
    )

    change_html = _change_card(ctxs.get("changes"))

    return f"""{hero}

{change_html}

<div class="grid g5">{"".join(cards)}</div>

<div class="grid g2">
  <div class="card">
    <h2>本期關鍵訊號</h2>
    <p class="hint">跨模組彙整，依嚴重度排序。完整清單在各分頁。</p>
    {flags_html}
  </div>
  <div class="card">
    <h2>資料發布時程</h2>
    <p class="hint">下次更新時間與各資料的落後幅度。</p>
    <div class="stat-row">{pace_html}</div>
    <div class="src">頁面每天自動重新產生；存檔頁則每個資料月份只保留第一份，
      作為未修正前的原始版本。</div>
  </div>
</div>"""


def archive_body(entries: list[dict]) -> str:
    if not entries:
        return ('<div class="soonbox"><h3>尚無存檔</h3>'
                '<p>每個資料月份第一次產出時會把當期報告存進這裡，'
                '日後可回頭查「當時看到的是什麼數字」。</p>'
                "</div>")
    items = "".join(
        f'<li><a href="{e["href"]}">'
        f'<span>{esc(e.get("kind", ""))}　{esc(e["month"])}</span>'
        f'<span class="a-meta">開啟</span></a></li>'
        for e in entries
    )
    return f"""<div class="card">
  <h2>歷次存檔</h2>
  <p class="hint">每個資料月份保留一份，內容是<b>該月份第一次產出時</b>的樣子，
    之後的每日執行不會覆蓋它。因為 BLS 與 BEA 會持續回頭修正歷史數字，
    留下的才是發布當下的原始版本——日後可以回頭查
    「當時我們看到的是什麼」，以及後來被改了多少。</p>
  <ul class="archive-list">{items}</ul>
</div>"""
