"""
首頁 — 五個模組的摘要，以及目前的情境結論。

設計原則：首頁只回答「現在是什麼狀況、為什麼」，細節都在各分頁。
任何模組缺資料時，畫面上明確標示缺哪一塊，不假裝結論已經完整。
"""

from __future__ import annotations

import datetime as dt

from ..site import esc, next_first_friday, next_cpi_release
from ..analysis import changes as chg_mod

LEAN_TEXT = {"dovish": "利降息", "hawkish": "利升息",
             "neutral": "中性", "balanced": "多空拉鋸"}
SEV_ICON = {"alert": "■", "watch": "▲", "info": "●"}


# 各模組的方向 → 顯示用的標籤。各模組的原始欄位型別不同
#（勞動／通膨是 tilt、聯準會是 direction、長端是 pressure level），
# 這裡統一翻成同一組詞，四個並排才有比較的意義。
DIR_CHIP = {
    "dovish": ("利降息", "dovish"),
    "hawkish": ("利升息", "hawkish"),
    "balanced": ("方向不明", "neutral"),
    "neutral": ("中性", "neutral"),
}


def _module_card(href, name, when, value, note, more,
                 pending=False, direction=None) -> str:
    """
    模組入口卡。

    副標刻意只留一段：先前是三段用「·」串起來的資訊
    （失業率 4.1% · 時薪年增 3.2% · 利降息），五張卡就是十五個小數字，
    而那些數字在首頁沒有任何可以比較的對象。細節留給分頁。

    方向章是新加的：五個模組原本各報一個不同單位的數字
    （萬人／%／分數／利率水準），彼此無法比較。統一標上
    利升息／利降息之後，四張卡才變成同一個維度上的四個觀點。
    """
    cls = "modcard pending" if pending else "modcard"
    chip = ""
    if direction and direction in DIR_CHIP:
        label, kind = DIR_CHIP[direction]
        chip = f'<span class="m-dir {kind}">{esc(label)}</span>'
    return f"""<a class="{cls}" href="{href}">
  <div class="m-top"><span class="m-name">{esc(name)}</span>
    <span class="m-when">{esc(when)}</span></div>
  <div class="m-value">{esc(value)}{chip}</div>
  <div class="m-note">{esc(note)}</div>
  <div class="m-more">{esc(more)} →</div>
</a>"""


VINTAGE_LABEL = {"labor": "就業報告", "inflation": " CPI", "fomc": "聲明"}


def _vintage_text(v: dict) -> str:
    """把資料版本寫成人看得懂的一行：「7 月就業報告　·　7 月 CPI　·　7/29 聲明」。"""
    if not v:
        return ""
    out = []
    for key in ("labor", "inflation", "fomc"):
        raw = v.get(key)
        if not raw:
            continue
        if key == "fomc":                       # YYYY-MM-DD
            parts = raw.split("-")
            out.append(f"{int(parts[1])}/{int(parts[2])} 聲明"
                       if len(parts) == 3 else f"{raw} 聲明")
        else:                                   # YYYY-MM
            m = raw.split("-")
            out.append(f"{int(m[1])} 月{VINTAGE_LABEL[key]}"
                       if len(m) == 2 else f"{raw} {VINTAGE_LABEL[key]}")
    # 「7 月 CPI」的空格：中文接英文縮寫要留白，否則會黏成「7 月CPI」
    return "　·　".join(out)


def _change_card(cs) -> str:
    """
    本期變化摘要——對每期都追的人，這裡的邊際資訊量最高。

    三個刻意的選擇
    --------------
    ① **按變化的方向分組，不按新觸發／已解除分組。** 一條已解除的鷹派訊號
       是鴿派的變化；照「新出現／消失」分組會把它跟真正的鷹派變化排在一起。
       讀者要的是「本期整體往哪邊移」，不是訊號的異動流水帳。
    ② **顏色只有一組語意：對利率的方向。** 先前橘色同時代表「新觸發」與
       「利升息」、藍色同時代表「已解除」與「利降息」，於是
       「已解除（藍）… 利升息（橘）」一列裡兩個顏色互相打架。
       新觸發／已解除改用 ＋／− 符號，不佔顏色。
    ③ **對照的是資料版本，不是執行時間。** 排程每天跑、資料一個月出一次，
       「對照 08-11 05:01」會讓人以為核心 CPI 在一小時內掉了半個百分點。
    """
    if cs is None:
        return ""
    if not cs.has_previous:
        return ('<div class="chg"><div class="chead">'
                '這是第一次執行，還沒有可以比對的上期資料。</div>'
                '<div class="v-count" style="border-top:none;padding-top:8px">'
                '下次有新資料時，這裡會列出情境移動、訊號的增減與關鍵數字的變化。'
                '</div></div>')

    prev_v = _vintage_text(cs.prev_vintage)
    base = f"對照 {prev_v}" if prev_v else f"對照 {cs.prev_at}"

    # 資料月份沒變 ＝ 這次執行只是重新產生同一份頁面。與其顯示一堆
    # 因為重跑而產生的微小差異，不如直接講「沒有新資料」。
    quiet = (not cs.scenario_moved and not cs.new_flags
             and not cs.resolved_flags and not cs.metric_moves)
    if quiet or not cs.data_changed:
        # 沒有新資料時，訊息本身已經把資料版本講完了，右邊不必再重複一次。
        if not cs.data_changed:
            msg, tailchip = f"自 {prev_v or cs.prev_at} 以來沒有新資料發布", ""
        else:
            msg, tailchip = cs.headline, f'<span class="ctitle">{esc(base)}</span>'
        return (f'<div class="chg quiet"><span class="ctitle">本期變化</span>'
                f'<span>{esc(msg)}</span>{tailchip}</div>')

    # ---- 訊號變化：按方向分兩欄 ----
    def _row(f: dict) -> str:
        mark = "＋" if f.get("kind") == "new" else "－"
        tip = "本期新出現" if f.get("kind") == "new" else "上期有、本期不再成立"
        return (f'<div class="citem"><span class="cmark" title="{tip}">{mark}</span>'
                f'<span class="ctext">{esc(f["title"])}</span>'
                f'<span class="cmod">{esc(f["module"])}</span></div>')

    all_flags = cs.new_flags + cs.resolved_flags
    cols = []
    for lean, label in (("dovish", "偏降息的變化"), ("hawkish", "偏升息的變化")):
        rows = [f for f in all_flags if f["change_lean"] == lean]
        if not rows:
            continue
        cols.append(
            f'<div class="ccol {lean}"><div class="ccol-h">{label}'
            f'<span class="ccol-n">{len(rows)}</span></div>'
            + "".join(_row(f) for f in rows[:6]) + "</div>")
    neutral = [f for f in all_flags if f["change_lean"] not in ("dovish", "hawkish")]
    if neutral:
        cols.append('<div class="ccol neutral"><div class="ccol-h">方向不明</div>'
                    + "".join(_row(f) for f in neutral[:4]) + "</div>")
    items_html = (f'<div class="ccols">{"".join(cols)}</div>'
                  f'<div class="clegend">＋ 本期新出現　　－ 上期有、本期不再成立</div>'
                  if cols else "")

    net = chg_mod.net_line(cs)
    net_html = ""
    if net:
        _n = "".join((f"<b>{esc(s)}</b>" if i % 2 else esc(s))
                     for i, s in enumerate(net.split("**")))
        net_html = f'<div class="cnet {cs.net_lean}">{_n}</div>'

    # ---- 數字變化：收進摺疊 ----
    moves = []
    for m in cs.metric_moves[:8]:
        # 顏色是「這個變動對利率的意思」，不是「數字漲了還是跌了」。
        cls = m.get("lean") or "flat"
        dunit = m.get("delta_unit") or m.get("unit", "")
        moves.append(
            f'<div class="cmove"><div>{esc(m["label"])}</div>'
            f'<div class="cm-delta {cls}">{m["delta"]:+.2f}{esc(dunit)}</div>'
            f'<div class="cm-val">{m["from"]:,.2f} → {m["to"]:,.2f}{esc(m["unit"])}</div>'
            f"</div>")
    moves_html = ""
    if moves:
        moves_html = (
            f'<details class="f-more"><summary>關鍵數字的變動'
            f'（{len(cs.metric_moves)} 項）</summary>'
            f'<div class="cmoves">{"".join(moves)}</div>'
            f'<p class="hint" style="margin:10px 0 0">'
            f'顏色是這個變動<b>對利率的意思</b>，不是數字漲跌。'
            f'兩者不一定同向——損益兩平就業增速變高，代表同樣的非農其實'
            f'更弱，數字往上但方向偏降息。</p>'
            f'</details>')

    tail = []
    # +0.00 不是資訊，是雜訊——小於顯示精度就不要佔一格
    if cs.labor_score_delta is not None and abs(cs.labor_score_delta) >= 0.005:
        tail.append(f"勞動綜合分數 {cs.labor_score_delta:+.2f}")
    if cs.persisting:
        tail.append(f"{cs.persisting} 項訊號延續")
    tail.append(base)

    return f"""<div class="chg{' moved' if cs.scenario_moved else ''}">
  <div class="chead">{esc(cs.headline)}</div>
  {net_html}{items_html}{moves_html}
  <div class="src" style="margin-top:12px">{esc('　·　'.join(tail))}</div>
</div>"""


def _chip(k: str, d: str, extra: str = "") -> str:
    return (f'<div class="cons-i{extra}"><span class="cons-k">{esc(k)}</span>'
            f'<span class="cons-v {DIR_CHIP.get(d, ("", "neutral"))[1]}">'
            f'{esc(DIR_CHIP.get(d, ("—", ""))[0])}</span></div>')


def _consensus_row(dirs: list, curve: tuple | None = None) -> str:
    """
    三個**政策方向**模組並排 ＋ 一句共識度，長端另外一格。

    這是首頁獨有、分頁做不到的事：分頁只能講自己那一塊，
    只有總覽能回答「這幾個觀點彼此同意嗎」。全部一致與彼此打架，
    是完全不同強度的訊息，而先前這件事完全沒有呈現——
    五張模組卡各報一個不同單位的數字，讀者根本無從比較。

    長端刻意**不計入票數**：就業、物價、聯準會三者回答的是同一個問題
    （政策利率往哪走），可以互相佐證；長端供給壓力回答的是曲線形狀，
    跟政策方向是兩個軸。把它算成第四票，等於在首頁做了 README
    與 `scenario.py` 都明講不該做的加總——「供給壓力偏高」會被
    當成一張鷹派票，讓「四個模組全部指向升息」這種最強語氣，
    在其實只有三個政策訊號同向時就被觸發。它仍然顯示，
    因為讀者需要知道曲線那一側在說什麼，只是分開講。
    """
    if len(dirs) < 2:
        return ""
    chips = "".join(_chip(k, d) for k, d in dirs)

    haw = sum(1 for _, d in dirs if d == "hawkish")
    dov = sum(1 for _, d in dirs if d == "dovish")
    n = len(dirs)
    if haw == n:
        note = f"{n} 個模組全部指向利升息——方向一致，訊息強度最高。"
    elif dov == n:
        note = f"{n} 個模組全部指向利降息——方向一致，訊息強度最高。"
    elif haw and dov:
        lead = ("利升息", haw) if haw > dov else (
            ("利降息", dov) if dov > haw else (None, 0))
        if lead[0]:
            note = (f"{n} 個模組裡 {lead[1]} 個偏{lead[0]}、"
                    f"{dov if lead[0] == '利升息' else haw} 個偏"
                    f"{'利降息' if lead[0] == '利升息' else '利升息'}"
                    "——方向分歧，任何單一模組的結論都要打折。")
        else:
            note = (f"{haw} 個偏利升息、{dov} 個偏利降息，正好對半——"
                    "這種時候不該只信其中一邊。")
    else:
        side = "利升息" if haw else ("利降息" if dov else "")
        note = (f"{n} 個模組裡 {max(haw, dov)} 個偏{side}，其餘中性——"
                f"沒有反向訊號。" if side else f"{n} 個模組都沒有明確方向。")
    note = "政策方向：" + note

    aside = ""
    if curve:
        ck, cd = curve
        cnote = {
            "hawkish": "長端供給壓力偏高——即使政策利率往下，長端也不容易跟著降。",
            "dovish": "長端供給壓力偏低——長端比較跟得上政策利率的方向。",
        }.get(cd, "長端供給壓力中性。")
        aside = (f'<div class="cons-aside"><div class="cons-row">'
                 f'{_chip(ck, cd, " aside")}</div>'
                 f'<div class="cons-note">{esc(cnote)}'
                 f'不算進上面的票數：它回答的是曲線形狀，不是政策方向。'
                 f'</div></div>')

    return (f'<div class="cons"><div class="cons-row">{chips}</div>'
            f'<div class="cons-note">{esc(note)}</div>{aside}</div>')


def home_body(ctxs: dict) -> str:
    lab = ctxs.get("labor")
    inf = ctxs.get("inflation")
    fom = ctxs.get("fomc")
    scn = ctxs.get("scenario")
    sc = (scn or {}).get("scenario")

    # ---------------- 模組入口（四張）----------------
    # 情境合成那張刪掉：它跟頁面最上方的結論卡是同一個內容
    #（同樣的名稱、同樣的就業×通膨定位、同樣的政策傾向），
    # 整段重複一次只是讓讀者多捲一個螢幕。導覽列仍然進得去。
    cards = []
    dirs = []          # 三個政策模組的方向，給結論卡的一致度用
    curve_dir = None   # 長端另計：曲線形狀不是政策方向，不進票數

    if lab:
        k = lab["kpi"]
        _d = lab["tilt"]["tilt"]
        dirs.append(("就業", _d))
        cards.append(_module_card(
            "/labor/", "勞動市場", f"{lab['data_month']} 資料",
            k["nfp_display"], f"失業率 {k['u3_display']}",
            "看修正追蹤、行業增減與健康檢查", direction=_d))
    else:
        cards.append(_module_card("/labor/", "勞動市場", "無資料", "—",
                                  "尚未產生", "P1", pending=True))

    if inf:
        k = inf["kpi"]
        _d = inf["tilt"]["tilt"]
        dirs.append(("物價", _d))
        cards.append(_module_card(
            "/inflation/", "通膨", f"{inf['data_month']} 資料",
            k["core_display"], f"核心 PCE {k['pce_display']}",
            "看分項貢獻、住房落後與能源傳導", direction=_d))
    else:
        cards.append(_module_card("/inflation/", "通膨", "建置中", "—",
                                  "CPI／PPI／PCE 分項貢獻分解", "P2", pending=True))

    if fom and not fom.get("empty"):
        shift = fom.get("shift", {})
        # 對外一律報「客觀訊號分數」（政策行動 + 反對票 + 風險方向）。
        # 措辭分數只是輔助，而且在溝通方式改變時會被停用——
        # 首頁若顯示措辭分數，會出現「+0.00 偏鷹」這種自相矛盾的卡片。
        _d = shift.get("direction", "")
        dirs.append(("聯準會", _d))
        cards.append(_module_card(
            "/fomc/", "聯準會文本", f"{fom['latest_date']} 聲明",
            f"{shift.get('objective', 0):+.2f}",
            f"本次 {fom['changed_count']} 處改動",
            "看聲明逐句比對與目前重心", direction=_d))
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
        # 長端的「方向」講的是供給壓力，不是政策利率——壓力大＝
        # 長端不容易跟著降，效果上與利升息同向，所以對應到同一組詞。
        _d = {"high": "hawkish", "low": "dovish"}.get(sp.level, "neutral")
        curve_dir = ("長端", _d)
        cards.append(_module_card(
            "/rates/", "長端與債務", f"{rat['as_of']} 資料",
            (f"{y30:.2f}%" if y30 is not None else "—"),
            f"30 年期　·　供給壓力{lvl}",
            "看曲線拆解、債務動態與科技巨頭發債", direction=_d))
    else:
        cards.append(_module_card("/rates/", "長端與債務", "無資料", "—",
                                  "殖利率曲線、政府債務與發債供給", "P5", pending=True))

    # ---------------- 情境結論 ----------------
    if sc:
        lean_cls = sc.lean
        incomplete = ""
        if sc.incomplete:
            incomplete = (f'⚠️ 以下模組尚無資料，結論並不完整：'
                          f'{esc("、".join(sc.incomplete))}。')
        # 九宮格已改成「一個體制一張」，格名本身就是結論，
        # 不再需要「已依重心修正」這種事後補述。但適用哪一張要講出來。
        _rl = esc((sc.focus or {}).get("label", ""))
        ovr = (f'<br>適用的九宮格：{_rl}'
               + ('（本次判不出重心，暫用兩邊並重的對照）'
                  if getattr(sc, "regime_assumed", False) else "")
               if _rl else "")
        hero = f"""<div class="verdict {lean_cls}">
  <div class="v-eyebrow">{esc((scn or {}).get('as_of', ''))}　·　目前情境</div>
  <div class="v-main">{esc(sc.name)}</div>
  <div class="v-why">{esc(sc.description)}</div>
  <div class="v-count">
    定位：就業{esc(sc.labor_state)}　×　通膨{esc(sc.infl_state)}　·
    政策傾向 {esc(LEAN_TEXT.get(sc.lean, ''))}{ovr}
    {('<br>' + incomplete) if incomplete else ''}
  </div>
  {_consensus_row(dirs, curve_dir)}
</div>"""
    else:
        hero = ('<div class="verdict balanced"><div class="v-main">尚無資料</div>'
                '<div class="v-why">請先執行 python run.py 產生資料。</div></div>')

    # ---------------- 重點訊號 ----------------
    all_flags = []
    if lab:
        all_flags += [("就業", f) for f in lab["flags"]]
    if inf:
        all_flags += [("物價", f) for f in inf["flags"]]
    order = {"alert": 0, "watch": 1, "info": 2}
    all_flags.sort(key=lambda x: order.get(x[1].severity, 9))

    rows = []
    for src, f in all_flags[:6]:
        # 方向章是首頁最該給的東西：五條訊號如果不知道各自往哪邊，
        # 就只是五個標題。分頁上每條都有 impact，先前首頁反而拿掉了。
        impact = ""
        if f.lean in ("dovish", "hawkish"):
            impact = (f'<div class="impact {f.lean}">'
                      f'{esc(LEAN_TEXT.get(f.lean, ""))}'
                      + (f'　{esc(f.impact)}' if f.impact else "") + '</div>')
        rows.append(
            f'<div class="flag {f.severity}">'
            f'<span class="f-icon">{SEV_ICON.get(f.severity, "●")}</span>'
            f'<div><div class="f-head">{esc(f.headline)}'
            f'<span class="f-tag">{esc(src)}</span></div>{impact}</div></div>'
        )
    if len(all_flags) > 6:
        rows.append(f'<div class="src">另有 {len(all_flags)-6} 項，'
                    f'見<a href="/labor/">勞動市場</a>與'
                    f'<a href="/inflation/">通膨</a>頁</div>')
    flags_html = "".join(rows) or '<div class="empty">本次沒有觸發任何訊號</div>'
    n_dov = sum(1 for _, f in all_flags if f.lean == "dovish")
    n_haw = sum(1 for _, f in all_flags if f.lean == "hawkish")
    # 這裡數的是「訊號條數」，上方共識列數的是「模組數」——兩者單位不同，
    # 標題要講清楚來源，否則「4 降 4 升」與「3 鷹 1 鴿」看起來像互相矛盾。
    flags_sub = (f"來自就業與物價兩個模組的規則引擎，共 {len(all_flags)} 條："
                 f"{n_dov} 條利降息、{n_haw} 條利升息、"
                 f"{len(all_flags) - n_dov - n_haw} 條中性。依嚴重度排序。"
                 if all_flags else "")

    # ---------------- 接下來要盯什麼 ----------------
    # 三個倒數。就業報告與 CPI 是慣例推估，FOMC 是官方行事曆解析的實際日期，
    # 三者的可信度不同，所以標示要分開講。
    today = dt.date.today()
    counts = []
    # 官方行事曆優先。FRED 的 release/dates 是 BLS 自己報給 FRED 的排程，
    # 遇到聯邦假日挪動時它會跟著動，慣例推估不會——一年總有幾次不一樣，
    # 而倒數寫錯的那幾天，正好就是讀者最需要它正確的那幾天。
    rel = ctxs.get("_releases") or {}

    def _sched(key: str, label: str, fallback, conv_note: str) -> None:
        raw = rel.get(key)
        if raw:
            try:
                counts.append({"label": label,
                               "date": dt.date.fromisoformat(raw),
                               "note": "取自 FRED 的官方發布行事曆，非推估"})
                return
            except ValueError:
                pass
        counts.append({"label": label, "date": fallback(), "note": conv_note})

    _sched("employment", "下次就業報告", next_first_friday,
           "依「次月第一個週五」慣例推估")
    _sched("cpi", "下次 CPI", next_cpi_release,
           "依「次月第 12 天前後」慣例推估")
    _nm = (fom or {}).get("next_meeting") or {}
    if _nm.get("date"):
        counts.append({"label": "下次 FOMC 會議",
                       "date": dt.date.fromisoformat(_nm["date"]),
                       "note": "取自聯準會官方行事曆，非推估"})
    counts.sort(key=lambda x: x["date"])
    counts_html = "".join(
        f'<div class="cd"><div class="cd-k">{esc(c["label"])}</div>'
        f'<div class="cd-d">{(c["date"] - today).days} 天後</div>'
        f'<div class="cd-n">{c["date"].isoformat()}　·　{esc(c["note"])}</div></div>'
        for c in counts)

    # 情境轉換門檻：全站最有行動性的一句話。只取「關鍵」那一軸——
    # 在通膨優先的體制下，勞動那條就算觸發也不會單獨改變政策方向，
    # 首頁放兩條反而模糊焦點。
    trig_html = ""
    if sc and sc.triggers:
        binding = [x for x in sc.triggers if getattr(x, "binding", False)]
        picked = binding or sc.triggers[:1]
        items = "".join(
            f'<div class="wt"><div class="wt-k">{esc(t.label)}'
            + ('<span class="tbind">關鍵</span>'
               if getattr(t, "binding", False) else "")
            + f'</div><div class="wt-v">'
            f'{esc("已觸發" if t.met else t.distance)}</div>'
            f'<div class="wt-n">目前 {esc(t.current)}　·　{esc(t.threshold)}</div>'
            f'</div>'
            for t in picked[:2])
        _b = "　標「關鍵」的那一軸才是目前的約束條件。" if binding else ""
        trig_html = (f'<p class="hint" style="margin:0 0 12px">'
                     f'情境要換一格，還差多少。{_b}</p>{items}')

    change_html = _change_card(ctxs.get("changes"))

    return f"""{hero}

<div class="grid">
  <div class="card">
    <h2>本期關鍵訊號</h2>
    <p class="hint">{esc(flags_sub)}</p>
    {flags_html}
  </div>
</div>

<div class="grid g2">
  <div class="card">
    <h2>接下來要盯什麼</h2>
    {trig_html or '<div class="empty">資料不足，無法計算觸發距離</div>'}
    <h3 style="margin-top:20px">下次更新</h3>
    <div class="cds">{counts_html}</div>
  </div>

  <div class="card">
    <h2>跟上期比，什麼變了</h2>
    {change_html or '<div class="empty">尚無可比對的上期資料</div>'}
  </div>
</div>

<div class="grid g4">{"".join(cards)}</div>

<div class="card" style="margin-top:13px">
  <div class="src" style="border-top:none;padding-top:0">
    資料月份：{esc((lab or {}).get('data_month', '—'))}（就業）　·　
    {esc((inf or {}).get('data_month', '—'))}（物價）　·　
    {esc((fom or {}).get('latest_date', '—'))}（聲明）。
    {esc((lab or {}).get('jolts_lag_text', 'JOLTS 較就業報告落後數個月'))}。
    每天自動重新產生。
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
