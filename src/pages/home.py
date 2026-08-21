"""
首頁 — 五個模組的摘要，以及目前的情境結論。

設計原則：首頁只回答「現在是什麼狀況、為什麼」，細節都在各分頁。
任何模組缺資料時，畫面上明確標示缺哪一塊，不假裝結論已經完整。
"""

from __future__ import annotations

import datetime as dt

from .. import clock

from ..site import esc, next_first_friday, next_cpi_release
from . import compact_full, state_chip
from ..analysis import changes as chg_mod
from ..analysis import brief as brief_mod
from ..analysis import scenario as scenario_mod

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
    ③ **對照的是每個模組自己的上一期發布，而且結果會留到下一次發布。**
       先前的比較視窗只有 24 小時：發布當天亮、隔天快照被覆蓋就熄了，
       讀者在發布後第三天打開網站等於完全錯過。而且三個模組的節奏不同
       （就業每月第一個週五、CPI 每月中、FOMC 每 6–8 週），
       共用一個「上期」本來就對不齊。
    """
    if cs is None:
        return ""
    if not cs.has_previous:
        return ('<div class="chg"><div class="chead">'
                '這是第一次執行，還沒有可以比對的上期資料。</div>'
                '<div class="v-count" style="border-top:none;padding-top:8px">'
                '下次有新資料時，這裡會列出情境移動、訊號的增減與關鍵數字的變化。'
                '</div></div>')

    base = chg_mod.basis_text(cs)

    # 「這是幾天前的事」要講。內容會一直留到下一次發布，所以讀者可能是在
    # 發布後第 10 天看到這張卡——不標的話會誤以為是今天的新聞。
    age = ""
    if cs.days_since is not None:
        age = ("今天發布" if cs.days_since <= 0 else
               f"{cs.days_since} 天前發布")

    # 真的什麼都沒變才走這一條（同一期資料重新產生、或兩期之間確實無異動）。
    quiet = (not cs.scenario_moved and not cs.new_flags
             and not cs.resolved_flags and not cs.metric_moves)
    if quiet:
        return (f'<div class="chg quiet"><span class="ctitle">本期變化</span>'
                f'<span>{esc(cs.headline)}</span>'
                f'<span class="ctitle">{esc(base)}</span></div>')

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
    # **全部列出來，不截斷。**
    #
    # 先前是 `cs.metric_moves[:8]`，但標題寫的是 `len(cs.metric_moves)`——
    # 於是標題說「10 項」、底下只畫 8 條。使用者數得出來，而數不對的第一
    # 反應是「這區的數字有問題」，連帶懷疑其他還對的數字。
    # 這一區本來就收在摺疊裡，長度不是問題；靜靜砍掉兩條才是問題。
    _LEAN_TAG = {"hawkish": "利升息", "dovish": "利降息"}
    moves = []
    for m in cs.metric_moves:
        # 顏色是「這個變動對利率的意思」，不是「數字漲了還是跌了」。
        # 但**顏色不該是唯一的載體**：紅綠對色覺障礙的讀者沒有資訊，
        # 對其他人也要先讀完下面那段說明才知道紅色代表什麼。直接寫字。
        cls = m.get("lean") or "flat"
        dunit = m.get("delta_unit") or m.get("unit", "")
        tag = _LEAN_TAG.get(m.get("lean"), "")
        moves.append(
            f'<div class="cmove"><div>{esc(m["label"])}</div>'
            f'<div class="cm-delta {cls}">'
            + (f'<span class="cm-tag">{esc(tag)}</span>' if tag else "")
            + f'{m["delta"]:+.2f}{esc(dunit)}</div>'
            f'<div class="cm-val">{m["from"]:,.2f} → {m["to"]:,.2f}{esc(m["unit"])}</div>'
            f"</div>")
    moves_html = ""
    if moves:
        moves_html = (
            f'<details class="f-more"><summary>關鍵數字的變動'
            f'（{len(cs.metric_moves)} 項）</summary>'
            f'<div class="cmoves">{"".join(moves)}</div>'
            f'<p class="hint" style="margin:10px 0 0">'
            f'「利升息／利降息」講的是這個變動<b>對利率的意思</b>，不是數字漲跌。'
            f'兩者不一定同向——損益兩平就業增速變高，代表同樣的非農其實'
            f'更弱，數字往上但方向偏降息。</p>'
            f'</details>')

    tail = []
    # +0.00 不是資訊，是雜訊——小於顯示精度就不要佔一格
    if cs.labor_score_delta is not None and abs(cs.labor_score_delta) >= 0.005:
        tail.append(f"勞動綜合分數 {cs.labor_score_delta:+.2f}")
    if cs.persisting:
        tail.append(f"{cs.persisting} 項訊號延續")
    if base:
        tail.append(base)

    return f"""<div class="chg{' moved' if cs.scenario_moved else ''}">
  <div class="chead">{esc(cs.headline)}</div>
  {f'<div class="cage">{esc(age)}</div>' if age else ''}
  {net_html}{items_html}{moves_html}
  <div class="src" style="margin-top:12px">{esc('　·　'.join(tail))}</div>
</div>"""


def _chip(k: str, d: str, extra: str = "") -> str:
    return (f'<div class="cons-i{extra}"><span class="cons-k">{esc(k)}</span>'
            f'<span class="cons-v {DIR_CHIP.get(d, ("", "neutral"))[1]}">'
            f'{esc(DIR_CHIP.get(d, ("—", ""))[0])}</span></div>')


def _brief_card(ctxs: dict) -> str:
    """
    整體總述：一段約 150 字的散文，把五個模組的結論串成一件事。

    為什麼放在結論卡正下方：結論卡回答「現在是什麼情境」，總述回答
    「為什麼、各方向的細節是什麼」。讀者的下一個問題就是後者，
    中間不該再隔著四張模組入口卡。

    共識列（三個色塊 ＋ 一句話 ＋ 長端）先前佔掉結論卡的一半（358／711px），
    卻只顯示十幾個字，而且跟定位列講同一件事。它回答的是「各模組同不同意」，
    現在併進總述的第一句。
    """
    b = ctxs.get("_brief") or brief_mod.compose(ctxs)
    txt = b.get("text") or ""
    if not txt:
        return ""
    # 重點句拆成獨立一行加粗。它是整段的結論（下一步是升還是降、
    # 解鎖條件是什麼），埋在段尾會被掃視略過。「重點：」前綴由
    # polish.validate 強制保留，所以這個拆法對組裝版與潤稿版都成立。
    key_html = ""
    if "重點：" in txt:
        txt, _, key = txt.rpartition("重點：")
        key_html = f'<p class="brief-key">重點：{esc(key.strip())}</p>'

    # 「本次更新：⋯⋯」拆成獨立一段。
    #
    # 它跟後面那段回答的**不是同一個問題**：前者是「這一次新拿到什麼」、
    # 後者是「整體現在是什麼狀況」。黏在同一段裡，讀者要讀到第三個句號才
    # 分得出來哪裡結束——而多數日子根本沒有前者，段落的開頭就變成兩種樣子。
    # 拆開之後，有新資料的日子第一眼就看得到，沒有的日子也不會少一塊。
    new_html = ""
    if txt.lstrip().startswith("本次更新："):
        _first, _sep, _rest = txt.partition("。")
        if _sep and _rest.strip():
            new_html = f'<p class="brief-new">{esc(_first.strip())}。</p>'
            txt = _rest
    return f"""
<div class="grid">
  <div class="card brief">
    <div class="brief-k">整體情勢</div>
    {new_html}<p class="brief-t">{esc(txt.strip())}</p>
    {key_html}
  </div>
</div>"""


def _home_body_full(ctxs: dict) -> str:
    lab = ctxs.get("labor")
    inf = ctxs.get("inflation")
    fom = ctxs.get("fomc")
    scn = ctxs.get("scenario")
    sc = (scn or {}).get("scenario")

    # ---------------- 模組入口（四張）----------------
    # 情境合成那張刪掉：它跟頁面最上方的結論卡是同一個內容
    #（同樣的名稱、同樣的就業×通膨定位、同樣的政策傾向），
    # 整段重複一次只是讓讀者多捲一個螢幕。
    #
    # 但「刪掉卡片」不等於「刪掉入口」——先前連結一起沒了，首頁 body 內
    # 通往情境頁的連結變成 0 條（labor×2、inflation×2、fomc×1、rates×1、
    # scenario×0），只剩導覽列上那四個字。而讀者剛在首頁看過同一段結論，
    # 理性推論是「我已經看過了」，於是全站唯一寫著「該怎麼擺部位」的那張表
    # 沒有人會走到。改成在結論卡底部放一條 CTA，並直接 deep link 到
    # #positioning——site.py 的 openTarget() 會自動展開那張收合卡。
    cards = []
    dirs = []          # 三個政策模組的方向，給結論卡的一致度用

    if lab:
        k = lab["kpi"]
        _d = lab["tilt"]["tilt"]
        dirs.append(("就業", _d))
        cards.append(_module_card(
            "/labor/", "勞動市場",
            f"{lab['data_month']} 資料"
            + ("（速報）" if lab.get("provisional") else ""),
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
            "/inflation/", "通膨",
            f"{inf['data_month']} 資料"
            + ("（速報）" if inf.get("provisional") else ""),
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
        # 長端不進共識票數：曲線形狀不是政策方向。它在總述的最後一句
        # 單獨交代（財政與 AI 一起推長端供給）。
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
        # 首頁只給描述的**第一句**，完整那段留在情境頁。
        # 兩頁逐字相同的話，讀者從首頁走過去會覺得「我已經看過了」，
        # 而首頁的工作是「現在是什麼」，情境頁才是「為什麼、所以要怎麼擺」。
        # 每一格的第一句都寫得可以單獨成立（例如「兩個使命指向相反，
        # 而委員會把通膨擺在前面。」），所以切第一個句號是安全的。
        # 「已維持 N 期」：只有累積到兩期以上才講得出來，所以會空一陣子。
        # 這是刻意的——編一個「已維持 1 期」出來只是廢話。
        _tn = ctxs.get("_tenure") or {}
        _ten = (f"　·　已維持 {_tn['periods']} 期"
                if _tn.get("periods", 0) >= 2 else "")
        _why = (sc.description or "").split("。")[0]
        _why = (_why + "。") if _why else (sc.description or "")
        _rl = esc((sc.focus or {}).get("label", ""))
        ovr = (f"　·　九宮格：{_rl}"
               + ("（本次判不出重心，暫用兩邊並重）"
                  if getattr(sc, "regime_assumed", False) else "")
               if _rl else "")
        # 眉標只留「目前情境 ＋ 已維持幾期」。四個資料日期先前排在這裡、
        # 在 390px 下折成兩行，而那些日期在頁尾的「資料月份」已經有了，
        # 頁面副標也寫著更新時間——結論卡的第一行不該花在時間戳上。
        hero = f"""<div class="verdict {lean_cls}">
  <div class="v-eyebrow">目前情境{_ten}</div>
  <div class="v-main">{esc(sc.name)}</div>
  <div class="v-why">{esc(_why)}</div>
  <div class="v-count">
    就業{esc(sc.labor_state)}　×　通膨{esc(sc.infl_state)}　·　{esc(LEAN_TEXT.get(sc.lean, ''))}{ovr}
    {('<br>' + incomplete) if incomplete else ''}
  </div>
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
    today = clock.today()
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

    # ---- 收合摘要 ----
    # 首頁先前是全站**預設最長**的頁（390px 下 4026px），卻是唯一沒有收合的頁——
    # 整站的閱讀模型在入口那一頁不成立。改成跟內容頁一樣：只留關鍵訊號展開，
    # 其餘收合並在標題列帶一句結論。
    # 摘要要帶**結論**，不是方法說明。先前直接沿用卡片副標
    #（「來自就業與物價兩個模組的規則引擎，共 9 條：…依嚴重度排序」），
    # 那是 50 字的方法論，在 390px 下折成三行、而且完全不回答
    # 「這張卡要不要點開」。改成跟各模組頁一致：條數 ＋ 最重要的那一條。
    _top = all_flags[0][1] if all_flags else None
    _flag_sum = (f"{len(all_flags)} 項　·　{_top.headline}" if _top
                 else "本次沒有觸發任何訊號")
    _trig_sum = "資料不足"
    if sc and sc.triggers:
        _b0 = ([x for x in sc.triggers if getattr(x, "binding", False)]
               or sc.triggers[:1])[0]
        _trig_sum = (f"{_b0.label}：{'已觸發' if _b0.met else _b0.distance}")
    if counts:
        _trig_sum += f"　·　最近一次發布 {(counts[0]['date'] - today).days} 天後"
    _chg = ctxs.get("changes")
    # net_line 帶著 ** 的自訂粗體標記（畫面上由 _change_card 轉成 <b>）。
    # data-sum 是純文字屬性，不脫掉的話讀者會直接看到「往**降息**的方向」。
    _chg_sum = ("尚無可比對的上期" if not (_chg and _chg.has_previous)
                else ((chg_mod.net_line(_chg) or "").replace("**", "")
                      or "訊號組成與上期相同"))

    # 模組入口移到結論卡正下方。先前排在整頁最後，390px 下讀者要捲過
    # 4000px 才看得到——首頁的主要功能之一是「往哪走」，那個功能被埋在最底下。
    # 「跟上期比」緊接在整體情勢之後。
    #
    # 先前它排在整頁最後——390px 下位在 2657／2877px，也就是**要捲到 92% 深度**
    # 才看得到。而這一區的價值恰恰對「每期都追的人」最高：對他們來說
    # 「現在是什麼狀態」上期已經看過了，邊際資訊很低，真正的資訊在**變化**。
    # 把全站邊際資訊量最高的一塊放在最底下，等於預設沒有人是回訪者。
    #
    # 現在的順序回答的是讀者依序會問的三件事：
    #   現在是什麼情境（結論卡）→ 為什麼（整體情勢）→ 跟上次比變了什麼
    #   → 有哪些訊號 → 接下來盯什麼 → 各模組細節
    return f"""{hero}

{_brief_card(ctxs)}

<div class="grid">
  <div class="card">
    <h2 id="changed" data-sum="{esc(_chg_sum)}">跟上期比，什麼變了</h2>
    {change_html or '<div class="empty">尚無可比對的上期資料</div>'}
  </div>
</div>

<div class="grid g4">{"".join(cards)}</div>

<div class="grid">
  <div class="card">
    <h2 id="signals" data-open="1" data-sum="{esc(_flag_sum)}">本期關鍵訊號</h2>
    <p class="hint">{esc(flags_sub)}</p>
    {flags_html}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="watch" data-sum="{esc(_trig_sum)}">接下來要盯什麼</h2>
    {trig_html or '<div class="empty">資料不足，無法計算觸發距離</div>'}
    <h3 style="margin-top:20px">下次更新</h3>
    <div class="cds">{counts_html}</div>
  </div>
</div>
"""


def _home_body_legacy(ctxs: dict) -> str:
    """首頁只回答：現在在哪、往哪走、為什麼、什麼會改變。"""
    sd = ctxs.get("scenario") or {}
    sc = sd.get("scenario")
    if sc is None:
        return _home_body_full(ctxs)
    fom = ctxs.get("fomc") or {}
    shift = fom.get("shift") or {}
    rt = ctxs.get("rates") or {}
    pressure = rt.get("pressure")
    p_level = getattr(pressure, "level", "") if pressure else ""
    p_text = {"high": "偏高", "moderate": "中等", "low": "偏低"}.get(p_level, "資料不足")
    f_dir = shift.get("direction", "neutral")
    f_text = {"hawkish": "偏鷹", "dovish": "偏鴿", "neutral": "中性"}.get(f_dir, "資料不足")
    lean = LEAN_TEXT.get(sc.lean, "中性")
    _nx = _pick_next_trigger(sc)
    trig = _nx["trigger"]
    trigger = ("短期傾向原地不動" if _nx["mode"] == "hold" else
               f"{trig.label}：{trig.distance}" if trig else "尚無可計算門檻")
    metrics = "".join([
        state_chip("九宮格位置", f"{sc.labor_state} × {sc.infl_state}", sc.name,
                   "hawkish" if sc.lean == "hawkish" else "dovish" if sc.lean == "dovish" else "neutral"),
        state_chip("兩軸方向", f"{sc.labor_momentum} / {sc.infl_momentum}", "就業 / 通膨"),
        state_chip("FOMC 會議結論", f_text, shift.get("label", ""), f_dir),
        state_chip("長端供給壓力", p_text, "財政＋Hyperscalers；不進九宮格", "watch" if p_level == "high" else "neutral"),
    ])
    parts = brief_mod.compose(ctxs).get("parts", [])
    wanted = [p for p in parts if p.get("key") in ("labor", "inflation", "fomc", "supply")][:3]
    reasons = "".join(f'<div class="logic-step"><b>{esc({"labor":"就業","inflation":"通膨","fomc":"FOMC","supply":"長端"}.get(p["key"], p["key"]))}</b>'
                      f'<span>{esc(p["text"])}</span></div>' for p in wanted)
    logic = (f'<div class="logic-strip">{reasons}</div>' if reasons else "")
    tags = (f'<div class="data-line"><span class="data-tag">{esc(sd.get("as_of", "—"))}</span>'
            f'<span class="data-tag">下一格：{esc(trigger)}</span>'
            '<a class="data-tag" href="/scenario/">開啟完整九宮格 →</a></div>')
    hero = (f'<div class="grid"><div class="card focus-card"><div class="focus-eyebrow">Investment dashboard</div>'
            f'<h2 class="focus-title">{esc(sc.name)}｜{esc(lean)}</h2>'
            f'<p class="focus-sub">{esc(sc.description)} 首頁結論由固定規則產生，AI 不改格位、不改數值。</p>'
            f'<div class="focus-grid">{metrics}</div>{logic}{tags}</div></div>')
    return hero + compact_full(_home_body_full(ctxs), "各模組摘要、變化與追蹤清單")


def home_footer(ctxs: dict) -> str:
    """
    首頁頁尾。

    資料月份先前是頁面最後一張卡——一個只裝了一行灰色小字的空盒子，
    下面緊接著同樣是灰色小字的頁尾，兩塊疊在一起看起來像排版壞掉。
    那一行本來就是頁尾性質的資訊，直接併進來。
    """
    lab, inf, fom = ctxs.get("labor"), ctxs.get("inflation"), ctxs.get("fomc")
    def _d(v: str) -> str:
        return f'<span class="nb">{esc(v)}</span>'

    return (
        f"資料月份：{_d((lab or {}).get('data_month', '—'))}（就業）　·　"
        f"{_d((inf or {}).get('data_month', '—'))}（物價）　·　"
        f"{_d((fom or {}).get('latest_date', '—'))}（聲明）。"
        "每天自動重新產生。<br>"
        "資料來源：FRED（BLS、BEA、DOL 原始資料）與 federalreserve.gov。"
        "所有量化判定由固定規則產生，每次執行結果一致。<br>"
        "本站僅為數據整理，不構成投資建議。")
def _fmt_pct(value, digits: int = 1) -> str:
    return "—" if value is None else f"{value:.{digits}f}%"


def _brief_content(ctxs: dict) -> str:
    """主卡內的整體情勢；長文只收合一次，重點句永遠可見。"""
    b = ctxs.get("_brief") or brief_mod.compose(ctxs)
    text = (b.get("text") or "").strip()
    if not text:
        return '<p class="home-brief-empty">目前沒有足夠資料產生整體情勢。</p>'

    key = ""
    if "重點：" in text:
        text, _, key = text.rpartition("重點：")
        key = key.strip()

    source = b.get("source", "assembled")
    source_label = ("AI 文字整理｜數據與方向由規則鎖定"
                    if source in ("model", "cache") else
                    "規則摘要｜數據與方向由規則鎖定")

    lead, rest = text.strip(), ""
    if brief_mod.cjk_len(lead) > 280:
        chunks = [x.strip() + "。" for x in lead.split("。") if x.strip()]
        shown = []
        while chunks and brief_mod.cjk_len("".join(shown + chunks[:1])) <= 250:
            shown.append(chunks.pop(0))
        if not shown and chunks:
            shown.append(chunks.pop(0))
        lead, rest = "".join(shown), "".join(chunks)

    more = (f'<details class="home-brief-more"><summary>展開完整分析</summary>'
            f'<p>{esc(rest)}</p></details>' if rest else "")
    key_html = f'<p class="home-brief-key">重點：{esc(key)}</p>' if key else ""
    return (f'<div class="home-brief-label">整體情勢<span>{esc(source_label)}</span></div>'
            f'<p class="home-brief-text">{esc(lead)}</p>{more}{key_html}')


def _pick_next_trigger(sc):
    """
    「可能下一格」的挑選。規則本體在 analysis.scenario.pick_next——
    方向優先、距離其次：先前純看距離時，失業率 4.1% 離轉「強」的 4.0
    比離轉「弱」的 4.3 近，畫面說下一格是升息壓力，但數據明明朝弱走。
    首頁與情境頁共用同一個函式，兩頁不會再各挑各的。
    """
    return scenario_mod.pick_next(sc)


def _next_cell(sc, trigger) -> tuple[str, str]:
    """把既有相鄰格門檻翻成可讀的下一格名稱，不創造第二套判斷。"""
    if trigger is None:
        return "資料不足", "尚無可計算門檻"
    labor, inflation = sc.labor_state, sc.infl_state
    for value in ("弱", "中", "強"):
        if ((trigger.label.startswith("就業") or trigger.label.startswith("勞動"))
                and f"「{value}」" in trigger.label):
            labor = value
    for value in ("低", "中", "高"):
        if trigger.label.startswith("通膨") and f"「{value}」" in trigger.label:
            inflation = value
    cell = scenario_mod.grid_for(sc.regime).get((labor, inflation))
    name = cell[0] if cell else f"{labor} × {inflation}"
    return name, f"{trigger.label}：{'已觸發' if trigger.met else trigger.distance}"


def _module_rows(ctxs: dict, sc, f_text: str, f_dir: str,
                 p_text: str, p_level: str) -> str:
    lab, inf = ctxs.get("labor") or {}, ctxs.get("inflation") or {}
    fom, rates = ctxs.get("fomc") or {}, ctxs.get("rates") or {}
    lk, ik = lab.get("kpi") or {}, inf.get("kpi") or {}
    isum = inf.get("summary")
    curve = rates.get("curve")
    levels = getattr(curve, "levels", {}) if curve else {}
    term = getattr(curve, "term_premium", None) if curve else None
    objective = (fom.get("shift") or {}).get("objective")
    labor_label = {"弱": "偏弱", "中": "中性", "強": "偏強"}.get(sc.labor_state, sc.labor_state)
    infl_label = {"低": "偏低", "中": "中性", "高": "偏高"}.get(sc.infl_state, sc.infl_state)

    ppi_head = _fmt_pct(getattr(isum, "ppi_headline_yoy", None))
    ppi_core = _fmt_pct(getattr(isum, "ppi_core_yoy", None))
    rows = [
        ("/labor/", "就業", f"{labor_label}｜{sc.labor_momentum}",
         "dovish" if sc.labor_state == "弱" else "hawkish" if sc.labor_state == "強" else "neutral",
         f"非農 {lk.get('nfp_display', '—')}、失業率 {lk.get('u3_display', '—')}；九宮格就業軸為「{labor_label}」。",
         [("非農新增", lk.get("nfp_display", "—")), ("失業率", lk.get("u3_display", "—")),
          ("平均時薪年增", lk.get("ahe_display", "—")), ("資料期別", lab.get("data_month", "—"))]),
        ("/inflation/", "通膨", f"{infl_label}｜{sc.infl_momentum}",
         "hawkish" if sc.infl_state == "高" else "dovish" if sc.infl_state == "低" else "neutral",
         f"CPI {ik.get('headline_display', '—')}、核心 CPI {ik.get('core_display', '—')}、核心 PCE {ik.get('pce_display', '—')}。",
         [("總體 CPI", ik.get("headline_display", "—")), ("核心 CPI", ik.get("core_display", "—")),
          ("PPI／核心 PPI", f"{ppi_head}／{ppi_core}"), ("核心 PCE", ik.get("pce_display", "—"))]),
        ("/fomc/", "FOMC", f_text, f_dir,
         f"政策利率 {fom.get('rate_range', '—')}；本次聲明改動 {fom.get('changed_count', 0)} 處。",
         [("政策利率", fom.get("rate_range", "—")),
          ("客觀訊號", "—" if objective is None else f"{objective:+.2f}"),
          ("聲明改動", f"{fom.get('changed_count', 0)} 處"), ("會議日期", fom.get("latest_date", "—"))]),
        ("/rates/", "財政與長端", p_text,
         "hawkish" if p_level == "high" else "dovish" if p_level == "low" else "neutral",
         f"10 年期 {_fmt_pct(levels.get('10Y'), 2)}、30 年期 {_fmt_pct(levels.get('30Y'), 2)}；供給壓力{p_text}。",
         [("10 年期", _fmt_pct(levels.get("10Y"), 2)), ("30 年期", _fmt_pct(levels.get("30Y"), 2)),
          ("期限溢酬", _fmt_pct(term, 2)), ("資料截止", rates.get("as_of", "—"))]),
    ]
    out = []
    for href, name, status, tone, summary, metrics in rows:
        stats = "".join(f'<div><span>{esc(k)}</span><b>{esc(v)}</b></div>' for k, v in metrics)
        out.append(
            f'<details class="home-module"><summary><span class="home-module-name">{esc(name)}</span>'
            f'<span class="home-status {tone}">{esc(status)}</span>'
            f'<span class="home-module-summary">{esc(summary)}</span>'
            f'<span class="home-module-toggle">查看</span></summary>'
            f'<div class="home-module-body"><div class="home-module-stats">{stats}</div>'
            f'<a class="home-inline-link" href="{href}">前往完整分析 →</a></div></details>')
    return "".join(out)


def _change_rows(cs) -> str:
    if not cs or not cs.has_previous:
        return '<div class="home-empty">尚無可比對的上期資料；下一次更新後會顯示本期差異。</div>'
    rows = []
    if cs.scenario_moved:
        rows.append(("九宮格位置改變", cs.headline,
                     "重新檢視政策方向與相鄰格門檻", "neutral"))
    for flag in (cs.new_flags + cs.resolved_flags):
        lean = flag.get("change_lean") or "neutral"
        effect = {"hawkish": "提高維持高利率的約束",
                  "dovish": "增加政策寬鬆空間"}.get(lean, "目前不改變政策方向")
        verb = "新增" if flag.get("kind") == "new" else "解除"
        rows.append((f"{verb}｜{flag.get('module', '訊號')}",
                     flag.get("title", "—"), effect, lean))
    for move in cs.metric_moves:
        lean = move.get("lean") or "neutral"
        unit = move.get("unit", "")
        value = f"{move.get('from', 0):,.2f}{unit} → {move.get('to', 0):,.2f}{unit}"
        effect = {"hawkish": "方向偏向利率維持較高",
                  "dovish": "方向偏向增加降息空間"}.get(lean, "政策含義大致中性")
        rows.append((move.get("label", "數據變化"), value, effect, lean))
    if not rows:
        return '<div class="home-empty">主要訊號與上期相同，九宮格位置沒有改變。</div>'
    return "".join(
        f'<div class="home-change"><span class="home-change-dot {esc(tone)}"></span>'
        f'<div><b>{esc(title)}</b><span>{esc(value)}</span></div><p>{esc(effect)}</p></div>'
        for title, value, effect, tone in rows[:4])


def _watch_rows(ctxs: dict, sc) -> str:
    """
    「接下來看什麼」——未來兩三週會發布的數據，各配一句「它會動什麼」。

    這一區取代原本的「資料狀態」：那一區只有一行更新時間（跟頁尾重複），
    而整個網站最欠的正是**前瞻**——讀者看完知道「現在是傾向緊縮」，
    卻不知道下一個可能改變判定的時刻是哪一天。日期優先取官方行事曆
    （FRED 或 config/releases_calendar.yaml），拿不到官方日期的項目
    退回可推導的慣例；「會動什麼」直接引用既有的觸發門檻，不新增判斷規則。
    """
    today = clock.today()
    lab, inf = ctxs.get("labor") or {}, ctxs.get("inflation") or {}
    fom = ctxs.get("fomc") or {}

    def _d(v):
        try:
            return dt.date.fromisoformat(v)
        except (TypeError, ValueError):
            return None

    def _trig_near(prefix: str) -> str:
        if not (sc and sc.triggers):
            return ""
        cand = [t for t in sc.triggers
                if t.label.startswith(prefix) and not t.met]
        if not cand:
            return ""
        import re as _re

        def _gap(x):
            m = _re.search(r"[-+]?\d+(?:\.\d+)?", x.distance or "")
            return abs(float(m.group(0))) if m else 9e9
        t = min(cand, key=_gap)
        return f"最近的門檻：{t.label}（{t.distance}）"

    events = []
    # 每週失業金：DOL 固定週四發布，可推導
    _thu = today + dt.timedelta(days=((3 - today.weekday()) % 7 or 7))
    events.append((_thu, "每週失業金申請", "每週四",
                   "兩次就業報告之間唯一會更新的數據；重點盯續領人數有沒有一路往上爬。"))
    _emp = _d(lab.get("next_release")) or next_first_friday()
    events.append((_emp, "就業報告", "官方行事曆" if lab.get("next_release") else "慣例推估",
                   _trig_near("就業轉") or "失業率決定就業格位，非農與時薪決定方向。"))
    _cpi = _d(inf.get("next_cpi")) or next_cpi_release()
    events.append((_cpi, "CPI", "官方行事曆" if inf.get("next_cpi") else "慣例推估",
                   "先更新通膨軸的推估值與動能。" + _trig_near("通膨轉")))
    _ppi = _d(inf.get("next_ppi"))
    if _ppi:
        events.append((_ppi, "PPI", "官方行事曆",
                       "更新上游成本壓力，也是核心 PCE 推估的原料之一。"))
    _pce = _d(inf.get("next_pce"))
    if _pce:
        events.append((_pce, "PCE", "官方行事曆",
                       "推估值換回實際值，通膨格位以實際值重新判定。"))
    _nm = _d(((fom.get("next_meeting")) or {}).get("date"))
    if _nm:
        _fl = ((fom.get("focus")) or {}).get("label", "")
        events.append((_nm, "FOMC 會議", "官方行事曆",
                       "聲明與投票可能改變重心" + (f"（目前：{_fl}）" if _fl else "")
                       + "——重心一翻，同一格的結論就不同。"))
    events = sorted([e for e in events if e[0] and e[0] >= today],
                    key=lambda e: e[0])[:6]
    return "".join(
        f'<div class="hn-row"><div class="hn-date"><b>{e[0].strftime("%m/%d")}</b>'
        f'<span>{(e[0] - today).days} 天後</span></div>'
        f'<div class="hn-main"><b>{esc(e[1])}</b><span>{esc(e[3])}</span></div>'
        f'<div class="hn-src">{esc(e[2])}</div></div>'
        for e in events)


def _focus_strip(f: dict | None) -> str:
    """
    今日市場焦點：hero 之上的窄條。三顆數字（10Y/30Y/FedWatch）＋一段焦點。

    數字的來源分兩級並在畫面上標清楚：殖利率是 FRED 的官方序列（規則）；
    FedWatch 機率是 AI 搜尋擷取（僅供參考）。焦點段由 AI 整理自新聞標題，
    AI 掛掉時這裡收到的已是「直接列標題」的退回版，照樣能顯示。
    """
    if not f:
        return ""
    chips = []
    for y in f.get("yields") or []:
        d = y.get("delta_bp")
        cls = "up" if (d or 0) > 0 else ("dn" if (d or 0) < 0 else "")
        dtxt = f"{d:+d} bps" if d is not None else "—"
        chips.append(f'<div class="fs-chip"><span>{esc(y["label"])}</span>'
                     f'<b>{y["value"]:.2f}%</b>'
                     f'<i class="{cls}">{esc(dtxt)}</i></div>')
    fw = f.get("fedwatch") or {}
    if fw.get("pct") is not None:
        d = fw.get("delta_pp")
        if fw.get("stale_from"):
            # 本次擷取失敗（限流、斷線）沿用近幾天的值——標明日期，
            # 不讓一次 429 就把整顆 chip 打回「—」。
            dtxt = f"沿用 {fw['stale_from'][5:].replace('-', '/')}"
        elif d is not None:
            dtxt = f"{d:+.1f} pp"
        elif fw.get("suspect"):
            dtxt = "擷取異常，沿用前值"
        elif fw.get("src") == "futures" and fw.get("implied") is not None:
            # 期貨自算時把隱含利率標出來：讀者（和我們）能直接驗算
            # (隱含 − 中點) ÷ 0.25，不會再有「100% 但不知道為什麼」的黑箱
            dtxt = f"期貨隱含 {fw['implied']:.2f}%"
        else:
            dtxt = "—"
        cls = "up" if (d or 0) > 0 else ("dn" if (d or 0) < 0 else "")
        chips.append('<div class="fs-chip"><span>2026 年底升息一碼機率</span>'
                     f'<b>{fw["pct"]:.0f}%</b>'
                     f'<i class="{cls}">{esc(dtxt)}</i></div>')
    else:
        chips.append('<div class="fs-chip"><span>2026 年底升息一碼機率</span>'
                     '<b>—</b><i>本次擷取失敗</i></div>')
    text = (f'<p class="fs-text">{esc(f.get("text") or "")}</p>'
            if f.get("text") else "")
    links = ""
    if f.get("links"):
        rows = "".join(
            f'<div class="fs-link"><a href="{esc(x["link"])}" rel="noopener">'
            f'{esc(x["title"])}</a>'
            + (f'<span class="fs-src">{esc(x["source"])}</span>'
               if x.get("source") else "")
            + '</div>' for x in f["links"])
        links = (f'<details class="f-more"><summary>來源標題</summary>'
                 f'<div class="f-detail">{rows}</div></details>')
    # 機率的來源標示跟著實際走的那一層：期貨自算是可驗算的規則、
    # AI 擷取只是備援——兩者的可信度不同，不能共用同一句話。
    if fw.get("pct") is None:
        _fw_note = ""
    elif fw.get("src") == "futures":
        _fw_note = "　·　機率：由聯邦基金期貨反推（FedWatch 同款算法，延遲報價）"
    else:
        _fw_note = "　·　機率：CME FedWatch，AI 擷取僅供參考"
    # 殖利率的來源標示跟著實際來源走：Yahoo 即時（±bp 對昨收）或 FRED 昨收
    _y_live = any(y.get("live") for y in (f.get("yields") or []))
    _y_note = ("殖利率：Yahoo 報價（延遲約 15 分鐘），變動對前一交易日收盤"
               if _y_live else "殖利率：FRED（前一交易日收盤）")
    # 焦點段的來源標示分兩種：內文摘要（新版主線）與標題整理（退回）
    _ts = f.get("text_source") or ""
    if _ts == "model-content" or (_ts == "cache" and f.get("cached_mode") == "content"):
        _t_note = "　·　焦點由 AI 摘要自新聞內文，只取關鍵字相關內容"
    elif _ts in ("model", "cache"):
        _t_note = "　·　焦點由 AI 整理自新聞標題"
    else:
        _t_note = ""
    note = (_y_note + "　·　1 bp＝0.01 個百分點" + _fw_note + _t_note)
    _date = esc((f.get("generated") or "")[:10])
    return ('<section class="home-zone focus-strip" aria-label="今日市場焦點">'
            '<div class="fs-head">今日市場焦點'
            + (f'<span class="fs-date">{_date}</span>' if _date else "")
            + '</div>'
            f'<div class="fs-chips">{"".join(chips)}</div>'
            f'{text}{links}<div class="fs-note">{esc(note)}</div></section>')


def home_body(ctxs: dict) -> str:
    """總覽固定五區：先結論，再門檻、模組、變化與接下來看什麼。"""
    sd = ctxs.get("scenario") or {}
    sc = sd.get("scenario")
    if sc is None:
        return _home_body_full(ctxs)

    lab, inf = ctxs.get("labor") or {}, ctxs.get("inflation") or {}
    fom, rates = ctxs.get("fomc") or {}, ctxs.get("rates") or {}
    shift = fom.get("shift") or {}
    f_dir = shift.get("direction", "neutral")
    f_text = {"hawkish": "偏鷹", "dovish": "偏鴿",
              "neutral": "中性"}.get(f_dir, "資料不足")
    pressure = rates.get("pressure")
    p_level = getattr(pressure, "level", "") if pressure else ""
    p_text = {"high": "偏高", "moderate": "中性",
              "low": "偏低"}.get(p_level, "資料不足")
    lean = LEAN_TEXT.get(sc.lean, "中性")
    labor_label = {"弱": "偏弱", "中": "中性", "強": "偏強"}.get(sc.labor_state, sc.labor_state)
    infl_label = {"低": "偏低", "中": "中性", "高": "偏高"}.get(sc.infl_state, sc.infl_state)

    _nx = _pick_next_trigger(sc)
    trigger, unlock = _nx["trigger"], _nx["unlock"]
    if _nx["mode"] == "hold":
        # 兩軸都在漂移、但都不朝相鄰門檻：誠實說「傾向不動」，
        # 最近的門檻降級成參考，不冒充預測。
        next_name = "傾向原地不動"
        trigger_text = f"{_nx['reason']}——目前都不朝相鄰門檻走"
    else:
        next_name, trigger_text = _next_cell(sc, trigger)
        if _nx["mode"] == "directional" and _nx.get("reason"):
            trigger_text += f"（依據：{_nx['reason']}）"
    _ref = "參考門檻：" if _nx["mode"] == "hold" else ""
    trigger_detail = (f'<span>{esc(_ref)}{esc(trigger.label)}　{esc(trigger.current)}</span>'
                      f'<span>{esc(trigger.threshold)}</span>'
                      if trigger else "")
    unlock_html = (
        f'<div class="home-trigger-unlock"><span>政策解鎖</span>'
        f'{esc(unlock.label)}：{esc("已觸發" if unlock.met else unlock.distance)}</div>'
        if unlock else "")

    status = "".join([
        f'<div><span>就業</span><b>{esc(labor_label)}｜{esc(sc.labor_momentum)}</b></div>',
        f'<div><span>通膨</span><b>{esc(infl_label)}｜{esc(sc.infl_momentum)}</b></div>',
        f'<div><span>FOMC</span><b>{esc(f_text)}</b></div>',
        f'<div><span>長端壓力</span><b>{esc(p_text)}</b></div>',
    ])
    asof = inf.get("asof") or {}
    dates = "｜".join([
        f"就業 {lab.get('data_month', '—')}", f"CPI {(asof.get('cpi') or '—')[:7]}",
        f"PPI {(asof.get('ppi') or '—')[:7]}", f"PCE {(asof.get('pce') or '—')[:7]}",
        f"FOMC {fom.get('latest_date', '—')}",
    ])

    return f"""
<main class="home-dashboard">
  {_focus_strip(ctxs.get('_focus'))}
  <section class="home-hero {esc(sc.lean)}" aria-labelledby="home-now">
    <div class="home-hero-top">
      <div><div class="home-kicker">目前情境</div>
        <h2 id="home-now">就業{esc(labor_label)} × 通膨{esc(infl_label)}</h2></div>
      <div class="home-verdict {esc(sc.lean)}"><span>{esc(sc.name)}</span><b>{esc(lean)}</b></div>
    </div>
    <div class="home-narrative">{_brief_content(ctxs)}</div>
    <div class="home-status-rail">{status}</div>
  </section>

  <section class="home-zone home-transition" aria-labelledby="home-grid">
    <div class="home-zone-head"><div><span class="home-zone-num">02</span>
      <h2 id="home-grid">九宮格與下一格</h2></div>
      <a class="home-primary-link" href="/scenario/">查看完整九宮格 →</a></div>
    <div class="home-transition-grid">
      <div class="home-cell-now"><span>目前位置</span><b>{esc(sc.name)}</b><small>就業{esc(labor_label)} × 通膨{esc(infl_label)}</small></div>
      <div class="home-transition-arrow" aria-hidden="true">→</div>
      <div class="home-cell-next"><span>可能下一格</span><b>{esc(next_name)}</b><small>{esc(trigger_text)}</small></div>
      <div class="home-trigger-detail">{trigger_detail}</div>
    </div>{unlock_html}
    <div class="home-dates">資料期別：{esc(dates)}</div>
  </section>

  <section class="home-zone" aria-labelledby="home-modules">
    <div class="home-zone-head"><div><span class="home-zone-num">03</span>
      <h2 id="home-modules">四大模組摘要</h2></div><p>點選一列查看核心數字</p></div>
    <div class="home-module-list">{_module_rows(ctxs, sc, f_text, f_dir, p_text, p_level)}</div>
  </section>

  <section class="home-zone" aria-labelledby="home-changes">
    <div class="home-zone-head"><div><span class="home-zone-num">04</span>
      <h2 id="home-changes">本期變化與市場含義</h2></div><p>只顯示最多四項重要變化</p></div>
    <div class="home-change-list">{_change_rows(ctxs.get('changes'))}</div>
  </section>

  <section class="home-zone" aria-labelledby="home-next">
    <div class="home-zone-head"><div><span class="home-zone-num">05</span>
      <h2 id="home-next">接下來看什麼</h2></div><p>未來幾週的發布日與它會動什麼</p></div>
    <div class="home-next-list">{_watch_rows(ctxs, sc)}</div>
    <div class="home-next-foot">自動更新：{esc(sd.get('as_of', '—'))}</div>
  </section>
</main>"""


def home_footer(ctxs: dict) -> str:
    lab, inf, fom = ctxs.get("labor"), ctxs.get("inflation"), ctxs.get("fomc")

    def _d(value: str) -> str:
        return f'<span class="nb">{esc(value)}</span>'

    return (
        '<div class="home-footer">'
        '<div><b>資料來源</b><span>FRED、BLS、BEA、DOL、Federal Reserve 與公司財報</span>'
        f'<span>就業 {_d((lab or {}).get("data_month", "—"))}｜物價 {_d((inf or {}).get("data_month", "—"))}｜FOMC {_d((fom or {}).get("latest_date", "—"))}</span></div>'
        '<div><b>使用說明</b><span>九宮格與數字由固定規則產生、每次執行結果一致，AI 只整理文字敘述。本網站僅為資料整理與情境判讀，不構成投資建議。</span>'
        '<span><a href="/scenario/">方法與判斷規則</a>｜<a href="/archive/">歷次存檔</a></span></div>'
        '</div>')

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
