"""
首頁 — 五個模組的摘要，以及目前的情境結論。

設計原則：首頁只回答「現在是什麼狀況、為什麼」，細節都在各分頁。
任何模組缺資料時，畫面上明確標示缺哪一塊，不假裝結論已經完整。
"""

from __future__ import annotations

import datetime as dt
import re

from .. import clock
from .story_ui import STORY_BTN, story_html
from .forecasts_ui import section as _fc_section

from ..site import esc, next_first_friday, next_cpi_release
from . import compact_full, state_chip, section_learn
from ..analysis import changes as chg_mod
from ..analysis import brief as brief_mod
from ..analysis import scenario as scenario_mod
from .election import election_tile as _election_tile
from .ai_events import ai_tile as _ai_tile

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
            f'兩者不一定同向——例如勞動參與率上升是數字變高，'
            f'但勞動供給增加會減輕薪資壓力，方向偏降息。</p>'
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


def _brief_pieces(text: str):
    """把整體情勢的行式文本拆成（本次更新、三則 bullet、其餘行、重點句）。
    組裝版與 AI 生成版共用同一種行式結構，這裡不用分辨來源。"""
    whatsnew, takeaway, bullets, rest = "", "", [], []
    for ln in [x.strip() for x in (text or "").splitlines() if x.strip()]:
        if ln.startswith("本次更新："):
            whatsnew = ln
        elif ln.startswith("重點："):
            takeaway = ln[len("重點："):].strip()
        else:
            for lb in ("勞動市場", "通膨", "聯準會"):
                if ln.startswith(lb + "："):
                    bullets.append((lb, ln[len(lb) + 1:].strip()))
                    break
            else:
                rest.append(ln)
    return whatsnew, bullets, rest, takeaway


def _brief_card(ctxs: dict) -> str:
    """
    整體情勢：本次更新（規則）→ 三則 bullet（AI 依判定包生成，
    數字鎖／方向鎖／結構鎖把關；後備為規則組裝）→ 重點句（規則、
    三態模板）。bullet 各自成塊，取代先前的連寫散文——
    使用者的原話：用三個 bullet point 方便閱讀。
    """
    b = ctxs.get("_brief") or brief_mod.compose(ctxs)
    txt = b.get("text") or ""
    if not txt:
        return ""
    whatsnew, bullets, rest, takeaway = _brief_pieces(txt)
    new_html = (f'<p class="brief-new">{esc(whatsnew)}</p>' if whatsnew else "")
    body_html = ('<ul class="brief-list">'
                 + "".join(f'<li><b>{esc(lb)}</b>｜{esc(tx)}</li>'
                           for lb, tx in bullets) + '</ul>') if bullets else ""
    rest_html = "".join(f'<p class="brief-t">{esc(x)}</p>' for x in rest)
    key_html = (f'<p class="brief-key">重點：{esc(takeaway)}</p>'
                if takeaway else "")
    return f"""
<div class="grid">
  <div class="card brief">
    <div class="brief-k">整體情勢</div>
    {new_html}{body_html}{rest_html}
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
        cards.append(_module_card("/inflation/", "通膨", "資料待更新", "—",
                                  "CPI／PPI／PCE 分項貢獻分解", "P2", pending=True))

    if fom and not fom.get("empty"):
        shift = fom.get("shift", {})
        # 2026-10 起不再有任何合成分數：大數字是政策利率區間，
        # 副標是這次的決議與反對票（文件裡的事實），再加靜默期倒數——
        # 靜默期間官員不公開談政策，讀者知道就不會一直等消息。
        _d = shift.get("direction", "")
        dirs.append(("聯準會", _d))
        _nm = fom.get("next_meeting") or {}
        _note = shift.get("decision_label") or f"本次 {fom['changed_count']} 處改動"
        if _nm.get("blackout_text"):
            _note += f"　·　{_nm['blackout_text']}"
        cards.append(_module_card(
            "/fomc/", "聯準會", f"{fom['latest_date']} 決議",
            fom.get("rate_range", "—"), _note,
            "看點陣圖、委員發言與聲明逐句比對", direction=_d))
    else:
        cards.append(_module_card("/fomc/", "聯準會文本", "資料待更新", "—",
                                  "決議、點陣圖、聲明逐句比對", "P3",
                                  pending=True))

    rat = ctxs.get("rates")
    if rat:
        sp = rat["pressure"]
        from ..analysis.rates import pressure_label as _pl
        lvl, _tone = _pl(sp)
        c = rat["curve"]
        y30 = (c.levels or {}).get("30Y")
        # 長端的「方向」講的是供給壓力，不是政策利率——壓力大＝
        # 長端不容易跟著降，效果上與利升息同向，所以對應到同一組詞。
        # 2026-10：色調改看期限溢酬的上升速度（與長端頁燈號一致），水準偏高但沒加速不再標成警示
        _d = _tone
        # 長端不進共識票數：曲線形狀不是政策方向。它在總述的最後一句
        # 單獨交代（財政與 AI 一起推長端供給）。
        cards.append(_module_card(
            "/rates/", "長端與債務", f"{rat['as_of']} 資料",
            (f"{y30:.2f}%" if y30 is not None else "—"),
            f"30 年期　·　期限溢酬{lvl}"
            + (f"　·　本月主因：{sp.main}" if getattr(sp, "main", "") else ""),
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
    from ..analysis.rates import pressure_label as _pl
    p_text, p_tone = _pl(pressure) if pressure else ("資料不足", "neutral")
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
        state_chip("FOMC 會議結論", f_text, shift.get("decision_label", ""), f_dir),
        state_chip("期限溢酬（財政與供給）", p_text,
                   (f"本月主因：{pressure.main}；不進九宮格" if getattr(pressure, "main", "") else "不進九宮格"),
                   "watch" if p_tone == "hawkish" else "neutral"),
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
            f'<p class="focus-sub">{esc(sc.description)} 結論綜合就業、通膨、政策與長端利率的最新變化。</p>'
            f'<div class="focus-grid">{metrics}</div>{logic}{tags}</div></div>')
    return hero + compact_full(_home_body_full(ctxs), "各模組摘要、變化與追蹤清單")


def _fmt_pct(value, digits: int = 1) -> str:
    return "—" if value is None else f"{value:.{digits}f}%"


def _brief_content(ctxs: dict) -> str:
    """主卡內的整體情勢：跟 _brief_card 同一套行式結構，bullet 版式。"""
    b = ctxs.get("_brief") or brief_mod.compose(ctxs)
    text = (b.get("text") or "").strip()
    if not text:
        return '<p class="home-brief-empty">目前沒有足夠資料產生整體情勢。</p>'
    whatsnew, bullets, rest, takeaway = _brief_pieces(text)

    new_html = (f'<p class="brief-new">{esc(whatsnew)}</p>' if whatsnew else "")
    body_html = ('<ul class="brief-list">'
                 + "".join(f'<li><b>{esc(lb)}</b>｜{esc(tx)}</li>'
                           for lb, tx in bullets) + '</ul>') if bullets else ""
    rest_html = "".join(f'<p class="home-brief-text">{esc(x)}</p>'
                        for x in rest)
    key_html = (f'<p class="home-brief-key">重點：{esc(takeaway)}</p>'
                if takeaway else "")
    return ('<div class="home-brief-label">整體情勢</div>'
            f'{new_html}{body_html}{rest_html}{key_html}')


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
    # 第十八批：首頁只說數據要怎麼變（plain），不寫「還差 0.1 個百分點」
    return name, ("條件已觸發" if trigger.met else (trigger.plain or trigger.distance))


def _module_rows(ctxs: dict, sc, f_text: str, f_dir: str,
                 p_text: str, p_level: str) -> str:
    lab, inf = ctxs.get("labor") or {}, ctxs.get("inflation") or {}
    fom, rates = ctxs.get("fomc") or {}, ctxs.get("rates") or {}
    lk, ik = lab.get("kpi") or {}, inf.get("kpi") or {}
    isum = inf.get("summary")
    curve = rates.get("curve")
    levels = getattr(curve, "levels", {}) if curve else {}
    term = getattr(curve, "term_premium", None) if curve else None
    _fsh = fom.get("shift") or {}
    _fnm = fom.get("next_meeting") or {}
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
         (f"政策利率 {fom.get('rate_range', '—')}；{fom.get('latest_date', '')} "
          f"{_fsh.get('decision_label', '')}。"
          + (f"下次會議 {_fnm['span']}，{_fnm['blackout_text']}。"
             if _fnm.get("blackout_text") else "")),
         [("政策利率", fom.get("rate_range", "—")),
          ("本次決議", _fsh.get("decision_label") or "—"),
          ("下次會議", (f"{_fnm.get('span') or _fnm.get('date', '')}（{_fnm['days']} 天後）"
                       if _fnm.get("days") is not None else "—")),
          ("靜默期", (("進行中" if _fnm.get("blackout_status") == "in"
                      else f"{int(_fnm['blackout_start'][5:7])}/{int(_fnm['blackout_start'][8:])} 起")
                     if _fnm.get("blackout_start") else "—"))]),
        ("/rates/", "財政與長端", p_text,
         p_tone,
         f"10 年期 {_fmt_pct(levels.get('10Y'), 2)}、30 年期 {_fmt_pct(levels.get('30Y'), 2)}；期限溢酬{p_text}。",
         [("10 年期", _fmt_pct(levels.get("10Y"), 2)), ("30 年期", _fmt_pct(levels.get("30Y"), 2)),
          ("期限溢酬", _fmt_pct(term, 2)),
          ("資料截止", (f"{rates.get('as_of', '—')}（盤中）"
                        if rates.get("as_of_live") else rates.get("as_of", "—")))]),
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
    「接下來看什麼」——本週＋下週會發布的數據（台灣時間），標影響高／中，
    各配一句「它會動什麼」。日期、時間、分級規則在 analysis/watch_calendar。

    這一區取代原本的「資料狀態」：那一區只有一行更新時間（跟頁尾重複），
    而整個網站最欠的正是**前瞻**——讀者看完知道「現在是傾向緊縮」，
    卻不知道下一個可能改變判定的時刻是哪一天。日期優先取官方行事曆
    （FRED 或 config/releases_calendar.yaml），拿不到官方日期的項目
    退回可推導的慣例；「會動什麼」直接引用既有的觸發門檻，不新增判斷規則。
    """
    today = clock.today()
    fom = ctxs.get("fomc") or {}

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

    from ..analysis import watch_calendar as wc
    _fl = ((fom.get("focus")) or {}).get("label", "")
    rows = wc.watch_rows(
        ctxs.get("_schedule") or wc.merge_schedule(
            {}, ctxs.get("_calendar") or {}, {}, today),
        fomc_next=((fom.get("next_meeting")) or {}).get("date"),
        fomc_desc=("聲明與投票可能改變重心" + (f"（目前：{_fl}）" if _fl else "")
                   + "——重心一翻，同一格的結論就不同。"),
        trig={"employment": _trig_near("就業轉"), "cpi": _trig_near("通膨轉")})
    if not rows:
        return '<p class="home-empty">本週與下週沒有排定的重要發布。</p>'
    out, grp = [], None
    for e in rows:
        if e["group"] != grp:
            grp = e["group"]
            out.append(f'<div class="hn-group">{grp}</div>')
        imp = wc.IMPACT_LABEL[e["impact"]]
        desc = f'<span>{esc(e["desc"])}</span>' if e["desc"] else ""
        out.append(
            f'<div class="hn-row"><div class="hn-date"><b>{e["label"]}</b>'
            f'<span>{esc(e["when"])}</span></div>'
            f'<div class="hn-main"><b>{esc(e["name"])}'
            f'<em class="hn-imp {e["impact"]}">{imp}</em></b>{desc}</div>'
            f'<div class="hn-src">{esc(e["src"])}</div></div>')
    return "".join(out)


def _fw_chip_html(f: dict, off: str = "") -> str:
    """下次 FOMC 機率 chip（目錄組裝失敗時的後備呈現用）。
    內容與目錄裡的 fedwatch chip 同一套（focus_today.fw_chips）。"""
    from ..analysis.focus_today import fw_chips
    c = fw_chips((f or {}).get("fedwatch"))[0]
    when = (f'<small class="fs-when">{esc(c["date"])}</small>'
            if c.get("date") else "")
    return (f'<div class="fs-chip{off}" data-chip="fedwatch">'
            f'<span>{esc(c["label"])}</span><b>{esc(c["value"])}</b>'
            f'<i class="{c["dir"]}">{esc(c["delta"])}</i>{when}</div>')


# 盤中報價：開著首頁時每 60 秒問一次 /api/quotes（netlify/functions/
# quotes.mjs），只在分頁看得見時問。規則（與建置端同一套）：
#   · 日期新者勝：報價日早於 chip 的資料日（data-d）就不動
#   · 45 分鐘內的報價才標「盤中・延遲 HH:MM」（台灣時間）；更舊的
#     （休市）只有在比 chip 新時才更新，小字回到「月-日」
#   · 殖利率與畫面上的值差逾 0.6 個百分點視為報價鏈出錯，不動
#   · 失敗一律安靜，畫面保留建置時的數字；每次載入最多問 240 次（4 小時）
# 格式化對應 focus_today 的 _pct_chip／_level_chip／_txf_chip。
_LIVE_JS = ('<script>(function(){var box=document.querySelector(".fs-chips");'
            'if(!box||!window.fetch)return;var N=0,M=240,last=0;'
            'function z(n){return(n<10?"0":"")+n;}'
            'function hm(ts){var d=new Date((ts+28800)*1000);'
            'return z(d.getUTCHours())+":"+z(d.getUTCMinutes());}'
            'function g(n){return Math.round(Math.abs(n)).toString()'
            '.replace(/\\B(?=(\\d{3})+(?!\\d))/g,",");}'
            'function fmt(q){var dv=q.v-q.p,dir=dv>0?"up":(dv<0?"dn":"");'
            'if(q.k==="pct"){var b=Math.round(dv*100);'
            'return[q.v.toFixed(2)+"%",(b>=0?"+":"")+b+" bp",'
            'b>0?"up":(b<0?"dn":"")];}'
            # 報價板（2026-10）：指數的變動只寫點數（漲跌幅在點擊說明裡），
            # 美元計價改成「$89.8」——跟伺服器端產生的格式一致
            'if(q.k==="idx"){var r=Math.round(dv);'
            'return[g(q.v),(r<0?"-":"+")+g(dv),dir];}'
            'if(q.k==="fx")return[q.v.toFixed(3)+" 元",(dv>0?"貶":dv<0?"升":"持平")+Math.abs(dv).toFixed(3),dir];'
            'if(q.dp!==undefined)return[(q.u&&q.u.indexOf("美元")>=0?"$":"")+q.v.toFixed(q.dp),(dv>=0?"+":"")+dv.toFixed(q.dp),dir];'
            'var s=dv.toFixed(1),u=q.u||"";'
            'return[(u.indexOf("美元")>=0?"$"+q.v.toFixed(1):q.v.toFixed(1)+u),'
            '(s.charAt(0)==="-"?"":"+")+s,dir];}'
            'function ap(r){var now=r.t||Date.now()/1000;'
            'Object.keys(r.q||{}).forEach(function(id){if(["dgs3mo","dgs2","dgs5","dgs7","dgs10","dgs20","dgs30"].indexOf(id)>=0)return;var q=r.q[id];'
            'var ch=box.querySelector(\'[data-chip="\'+id+\'"]\');if(!ch)return;'
            'var dd=ch.getAttribute("data-d")||"";if(dd&&q.d<dd)return;'
            'var fr=(now-q.ts)<=2700;if(!fr&&!(q.d>dd))return;'
            'var b=ch.querySelector("b"),i=ch.querySelector("i"),'
            'w=ch.querySelector(".fs-when");'
            'if(q.k==="pct"&&b){var o=parseFloat(b.textContent);'
            'if(isFinite(o)&&Math.abs(q.v-o)>0.6)return;}'
            'var f=fmt(q);if(b)b.textContent=f[0];'
            'if(!i){i=document.createElement("i");ch.insertBefore(i,b);}'
            'i.textContent=f[1];i.className=f[2]||"fl";'

            'if(!w){w=document.createElement("small");w.className="fs-when";'
            'var nm=ch.querySelector(".fs-nm")||ch;nm.appendChild(w);}'
            'w.textContent=fr?((q.s||"盤中")+"・延遲 "+hm(q.ts))'
            ':((q.s?q.s+" ":"")+q.d.slice(5).replace("-","/"));'
            'ch.setAttribute("data-d",q.d);ch.setAttribute("data-v",q.v);if(q.p)ch.setAttribute("data-pv",q.p);'
            'if(window.fsReMode)window.fsReMode(ch);});}'
            'function tk(){if(document.visibilityState!=="visible"||N>=M)return;'
            'N++;last=Date.now();fetch("/api/quotes").then(function(r){'
            'return r.ok?r.json():null;}).then(function(r){if(r)ap(r);})'
            '.catch(function(){});}'
            'tk();setInterval(tk,60000);'
            'document.addEventListener("visibilitychange",function(){'
            'if(document.visibilityState==="visible"&&Date.now()-last>60000)tk();});'
            '})();</script>')


# 補充新聞主題選單：對應指標只用來建立選項，新聞選擇不反向改動指標。

WIDE_EXTRA_CHIPS = ["sox", "dxy"]     # 電腦版預設多顯示的兩個指標（費城半導體、美元指數）

_CHIP_SELECT_JS = r"""
(function(){var K="fsChips",NK="fsNewsTopics",MK="fsMode";
var D=FS_CONFIG.defaults,TM=FS_CONFIG.topicMap,TA=FS_CONFIG.available,TOPT=FS_CONFIG.topicOptions;
// 2026-10-29：電腦版一列 3 個，預設 6 個——多放費城半導體與美元指數
if(window.matchMedia&&matchMedia('(min-width:760px)').matches){D=D.slice();(FS_CONFIG.wideExtra||[]).forEach(function(x){if(D.indexOf(x)<0)D.push(x);});}
var st=document.querySelector('.focus-strip'),box=document.querySelector('.fs-chips');if(!box||!st)return;
var ids=Array.prototype.map.call(box.querySelectorAll('[data-chip]'),function(c){return c.dataset.chip;});
var news=[],GT='主軸補充';
function each(q,f){Array.prototype.forEach.call(document.querySelectorAll(q),f);}
function lsg(k){try{return localStorage.getItem(k);}catch(e){return null;}}
function lss(k,v){try{if(v===null)localStorage.removeItem(k);else localStorage.setItem(k,v);}catch(e){}}
function saveNews(){lss(NK,JSON.stringify({chips:sel,topics:news}));}
function showTopics(w){news=w.slice(0,2);var ul=document.querySelector('.fs-news .fs-list');if(!ul)return;
 each('.fs-news [data-topic]',function(li){li.classList.toggle('fs-off',news.indexOf(li.dataset.topic)<0);});
 news.forEach(function(t,k){var li=ul.querySelector('[data-topic="'+t+'"]');if(!li)return;ul.appendChild(li);
  var tg=li.querySelector('.fs-tag');if(!tg)return;tg.classList.add('fs-tagsel');var s=tg.querySelector('select');
  if(!s){s=document.createElement('select');s.innerHTML=TOPT;s.setAttribute('aria-label','換一個補充新聞主題');tg.appendChild(s);
   s.addEventListener('change',function(){var i=+s.dataset.slot,j=news.indexOf(s.value),next=news.slice();
    if(!s.value){next.splice(i,1);showTopics(next);saveNews();return;}
    if(j>=0&&j!==i)next[j]=news[i];next[i]=s.value;showTopics(next);saveNews();});}
  if(!s.querySelector('option[value=""]')&&document.querySelector('.fs-news [data-gen]'))s.insertAdjacentHTML('afterbegin','<option value="">'+GT+'</option>');
  s.value=t;s.dataset.slot=k;});
 var n=0;each('.fs-news [data-gen]',function(li){var on=n<2-news.length;li.classList.toggle('fs-off',!on);if(on)n++;ul.appendChild(li);
  var tg=li.querySelector('.fs-tag');if(!tg||tg.querySelector('select'))return;tg.classList.add('fs-tagsel');
  var g=document.createElement('select');g.innerHTML='<option value="">'+GT+'</option>'+TOPT;g.setAttribute('aria-label','換一個補充新聞主題');g.value='';tg.appendChild(g);
  g.addEventListener('change',function(){var v=g.value;g.value='';if(!v||news.indexOf(v)>=0)return;showTopics(news.concat([v]));saveNews();});});
 each('.fs-news [data-tlink]',function(a){a.classList.toggle('fs-off',news.indexOf(a.dataset.tlink)<0);});
 var xs=[];each('.fs-news .fs-link:not(.fs-off) .fs-src',function(q){var x=q.textContent.trim();if(x&&xs.indexOf(x)<0)xs.push(x);});
 var sp=document.querySelector('.fs-srcs');if(sp)sp.textContent=xs.length?'　·　新聞：'+xs.slice(0,3).join('、'):'';}
function tp(sel){var w=[];sel.forEach(function(c){var t=TM[c];if(t&&TA.indexOf(t)>=0&&w.indexOf(t)<0&&w.length<2)w.push(t);});showTopics(w);}
// 第十八批：勾幾個顯示幾個（不設上限），勾選順序＝顯示順序；至少留一個
function fill(selected){var o=[];(selected||[]).forEach(function(x){if(ids.indexOf(x)>=0&&o.indexOf(x)<0)o.push(x);});
 if(!o.length)D.forEach(function(x){if(ids.indexOf(x)>=0&&o.indexOf(x)<0)o.push(x);});return o;}
function ap(selected,keepNews){Array.prototype.forEach.call(box.querySelectorAll('[data-chip]'),function(ch){ch.classList.toggle('fs-off',selected.indexOf(ch.dataset.chip)<0);ch.classList.remove('slot1','slot2');});
 selected.forEach(function(id,i){var ch=box.querySelector('[data-chip="'+id+'"]');if(!ch)return;box.appendChild(ch);if(i<2)ch.classList.add('slot'+(i+1));});
 each('.fs-pickp input[type=checkbox]',function(cb){var k=selected.indexOf(cb.value);cb.checked=k>=0;cb.disabled=(k>=0&&selected.length===1);
  var o=cb.parentNode.querySelector('.fs-pk-n');if(o)o.textContent=k>=0?String(k+1):'';});
 var c=st.querySelector('.fs-pk-cnt');if(c)c.textContent='已選 '+selected.length+' 個';if(!keepNews)tp(selected);}
function save(){lss(K,JSON.stringify(sel));}
var sel=null;try{sel=JSON.parse(lsg(K)||'null');}catch(e){}
sel=fill(sel instanceof Array?sel:D);ap(sel);
try{var saved=JSON.parse(lsg(NK)||'null');if(saved&&JSON.stringify(saved.chips)===JSON.stringify(sel)&&Array.isArray(saved.topics)){
 var valid=saved.topics.filter(function(t,i,a){return TA.indexOf(t)>=0&&a.indexOf(t)===i;});if(valid.length||!saved.topics.length)showTopics(valid);}}catch(e){}
each('.fs-pickp input[type=checkbox]',function(cb){cb.addEventListener('change',function(){var k=sel.indexOf(cb.value);
 if(cb.checked&&k<0)sel.push(cb.value);else if(!cb.checked&&k>=0&&sel.length>1)sel.splice(k,1);
 save();lss(NK,null);ap(sel);});});
var eb=st.querySelector('.fs-edit-btn');function ed(on){st.classList.toggle('fs-editing',on);if(eb)eb.setAttribute('aria-pressed',on?'true':'false');}
if(eb)eb.addEventListener('click',function(){ed(!st.classList.contains('fs-editing'));});
var dn=st.querySelector('.fs-done');if(dn)dn.addEventListener('click',function(){ed(false);});
// 2026-10：長按一行（手機約 0.3 秒；電腦按住直接拖）上下拖曳調整順序——平常畫面
// 與編輯狀態都可以（使用者：「非編輯情況也能拖移」）。
// 只改報價板順序，補充新聞維持原本的主題（讀者要換新聞用新聞標籤的 ▾）。
// iPhone Safari：手指一動就會被判成捲動、pointer 事件被中斷，所以觸控改用
// touch 事件＋非被動 touchmove：長按成立前移動超過 8px 視為捲動（照常捲），
// 成立後 preventDefault 擋住捲動。
(function(){var row=null,act=false,off=0,timer=null,sx=0,sy=0,pend=null,my=0;
 function vis(){return Array.prototype.filter.call(box.querySelectorAll('[data-chip]'),function(x){return !x.classList.contains('fs-off');});}
 function rowOf(t){while(t&&t!==box){if(t.dataset&&t.dataset.chip)return t.classList.contains('fs-off')?null:t;t=t.parentNode;}return null;}
 function place(y){row.style.transform='';var top=row.getBoundingClientRect().top;row.style.transform='translateY('+(y-off-top)+'px)';}
 function lift(r,y){row=r;act=true;off=y-r.getBoundingClientRect().top;r.classList.add('fs-drag');
  try{if(navigator.vibrate)navigator.vibrate(12);}catch(e){}}
 function move(y){var v=vis(),k=v.indexOf(row),r;
  if(k>0){r=v[k-1].getBoundingClientRect();if(y<r.top+r.height/2)box.insertBefore(row,v[k-1]);}
  if(k<v.length-1){r=v[k+1].getBoundingClientRect();if(y>r.top+r.height/2)box.insertBefore(v[k+1],row);}
  if(y<56)window.scrollBy(0,-14);else if(y>window.innerHeight-56)window.scrollBy(0,14);
  place(y);}
 function drop(){clearTimeout(timer);timer=null;pend=null;if(!act)return;act=false;row.style.transform='';row.classList.remove('fs-drag');
  var o=vis().map(function(x){return x.dataset.chip;});row=null;
  box._dg=Date.now();if(o.join()!==sel.join()){sel=o;save();ap(sel,true);saveNews();}}
 box.addEventListener('touchstart',function(e){if(e.touches.length!==1)return;var r=rowOf(e.target);if(!r)return;
  sx=e.touches[0].clientX;sy=e.touches[0].clientY;clearTimeout(timer);timer=setTimeout(function(){timer=null;lift(r,sy);},300);},{passive:true});
 box.addEventListener('touchmove',function(e){var t=e.touches[0];
  if(act){if(e.cancelable)e.preventDefault();move(t.clientY);return;}
  if(timer&&(Math.abs(t.clientX-sx)>8||Math.abs(t.clientY-sy)>8)){clearTimeout(timer);timer=null;}},{passive:false});
 box.addEventListener('touchend',drop);box.addEventListener('touchcancel',drop);
 box.addEventListener('contextmenu',function(e){if(rowOf(e.target))e.preventDefault();});
 box.addEventListener('mousedown',function(e){if(e.button!==0)return;var r=rowOf(e.target);if(!r)return;pend=r;my=e.clientY;e.preventDefault();});
 document.addEventListener('mousemove',function(e){if(act){move(e.clientY);return;}
  if(pend&&Math.abs(e.clientY-my)>4){lift(pend,my);pend=null;move(e.clientY);}});
 document.addEventListener('mouseup',drop);})();
var r=st.querySelector('.fs-reset');if(r)r.addEventListener('click',function(){sel=fill(D);lss(K,null);lss(NK,null);ap(sel);});
Array.prototype.forEach.call(box.querySelectorAll('.fs-chip[title]'),function(c){c.addEventListener('click',function(){if(Date.now()-(box._dg||0)<500)return;if(!st.classList.contains('fs-editing'))c.classList.toggle('tip-on');});});
// 第十八批：變動欄可切「日／MTD／YTD」（上月底、去年底收盤為基準）
var mode=lsg(MK)||"d";if(["d","m","y"].indexOf(mode)<0)mode="d";
function grp(x){return x.replace(/\B(?=(\d{3})+(?!\d))/g,",");}
function fx(x,n){var a=Math.abs(x).toFixed(n),p=a.split(".");return grp(p[0])+(p[1]?"."+p[1]:"");}
function md(d){return d?(+d.slice(5,7))+"/"+(+d.slice(8,10))+(d.slice(0,4)!==String(new Date().getFullYear())?"（"+d.slice(0,4)+"）":""):"";}
function rd(ch){var i=ch.querySelector('i');if(!i)return;
 if(!ch.hasAttribute('data-dd')){ch.setAttribute('data-dd',i.textContent);ch.setAttribute('data-dc',i.className||'fl');}
 var k=ch.getAttribute('data-k'),v=parseFloat(ch.getAttribute('data-v')),n=k&&k.charAt(0)==="a"?(+k.slice(1)||0):(k==="twd"?3:2);
 var t0=ch.getAttribute('data-tip0')||"";
 // 點開說明：價格類給所選區間的漲跌幅（第十八批：百分比只放這裡）
 if(ch.getAttribute('data-pc')==="1"){var bb=parseFloat(ch.getAttribute(mode==="d"?'data-pv':(mode==="m"?'data-bm':'data-by'))),
   lb=mode==="d"?"日":(mode==="m"?"MTD ":"YTD "),bd=mode==="d"?"前一交易日":md(ch.getAttribute(mode==="m"?'data-bmd':'data-byd'));
  if(isFinite(v)&&isFinite(bb)&&bb){var pc=(v/bb-1)*100;
   ch.setAttribute('title',lb+"漲跌幅 "+(pc>=0?"+":"")+pc.toFixed(2)+"%（對"+(mode==="d"?bd+"收盤":" "+bd+" 收盤 "+fx(bb,n))+"）"+(t0?"｜"+t0:""));}
  else if(t0)ch.setAttribute('title',t0);}
 else if(k){var bd2=md(ch.getAttribute(mode==="m"?'data-bmd':'data-byd'));
  if(mode==="d"){if(t0)ch.setAttribute('title',t0);}
  else ch.setAttribute('title',(mode==="m"?"MTD":"YTD")+" 變動"+(bd2?"（對 "+bd2+"）":"")+(t0?"｜"+t0:""));}
 if(mode==="d"){i.textContent=ch.getAttribute('data-dd');i.className=ch.getAttribute('data-dc');return;}
 var b=parseFloat(ch.getAttribute(mode==="m"?'data-bm':'data-by'));
 if(!k||!isFinite(v)||!isFinite(b)){i.textContent="—";i.className="fl";return;}
 // 變動欄一律寫絕對差距：bp、點數、價差（第十八批 v2）
 var d=v-b,t,x;
 if(k==="bp"){x=Math.round(d*100);t=(x>=0?"+":"")+x+" bp";}
 else if(k==="bp0"){x=Math.round(d);t=(x>=0?"+":"")+x+" bp";}
 else if(k==="pct"){x=d;t=(d<0?"-":"+")+fx(d,0);}
 else if(k==="twd"){x=d;t=(d>0?"貶":d<0?"升":"持平")+Math.abs(d).toFixed(3);}
 else{var a=Math.abs(d).toFixed(n);x=+a===0?0:d;t=(d<0&&+a!==0?"-":"+")+fx(d,n)+(ch.getAttribute('data-u')||"");}
 i.textContent=t;i.className=x>0?"up":(x<0?"dn":"fl");}
function am(){Array.prototype.forEach.call(box.querySelectorAll('[data-chip]'),rd);
 var s=box.querySelector('.fs-mode-sel');if(s)s.value=mode;}
window.fsReMode=function(ch){ch.removeAttribute('data-dd');rd(ch);};
// 表頭「變動」換成原生下拉選單（第十八批：使用者指定 日變動／MTD／YTD）；沒開 JS 時維持文字「變動」
var hd=box.querySelector('.fs-hd span:nth-child(2)');
if(hd){hd.innerHTML='<label class="fs-mode"><select class="fs-mode-sel" aria-label="變動區間">'
 +'<option value="d">日變動</option><option value="m">MTD</option><option value="y">YTD</option></select></label>';
 var sl=hd.querySelector('select');sl.addEventListener('change',function(){mode=sl.value;lss(MK,mode);am();});}
am();
})();
"""

TOPIC_REP = {"fed": "fedwatch", "long": "dgs10", "funding": "sofr", "oil": "wti",
             "equity": "dji", "semi": "sox", "twf": "txf", "election": "pm_senate", "gold": "gold", "fx": "dxy"}
GEN_TAG = "主軸補充"   # 一般補充（主軸那次一起寫的）的標籤
TOPIC_REP_ORDER = ("fed", "long", "funding", "oil", "equity", "semi", "twf", "election", "gold", "fx")
TOPIC_LABEL = {"fed": "聯準會", "long": "長天期美債", "funding": "資金市場", "oil": "油價",
               "equity": "美股", "semi": "AI 與半導體", "twf": "台指期", "election": "期中選舉", "gold": "黃金", "fx": "匯率"}


def _unify_chip(c: dict) -> dict:
    """
    焦點指標的四欄統一（2026-10 示意）：
      指標＝名稱（必要說明放這裡）　日期＝資料日
      數值＝純數字（帶單位）　　　　變動＝對前一日、同類單位
    原本混在數值／變動欄裡的文字（「維持」「約 +0.8 碼」「（+0.18%）」
    「日盤」）全部移進 tip（滑鼠提示／手機點擊）。
    """
    cid = c.get("id", "")
    label, value, delta = c.get("label", ""), c.get("value", ""), c.get("delta", "") or "—"
    date, d, tip = c.get("date", "") or "", c.get("dir", ""), ""
    date = date.replace("-", "/")
    m = re.match(r"^(日盤|夜盤)\s*(.*)$", date)
    if m:                       # 盤別由即時報價寫在日期列，提示裡不重複
        date = m.group(2)
    if cid in ("dgs3mo", "dgs2", "dgs5", "dgs7", "dgs10", "dgs20", "dgs30"):
        source = {"Treasury": "財政部", "FRED": "FRED", "Snapshot": "官方快照"}.get(c.get("source") or "FRED", "官方日資料")
        date = (source + " " + date) if date else ""
        tip = "官方日殖利率；變動對前一筆有效日資料，日期為美國資料日。固定期限殖利率可能與 Bloomberg PX_LAST 不同。"
    elif cid in ("live_dgs10", "live_dgs30"):
        date = ("Yahoo " + date) if date else ""
        tip = "Yahoo 延遲盤中報價；獨立於官方日殖利率與歷史圖表。"
    elif cid == "fedwatch":
        mv = re.match(r"^(.+?)\s*(\d+)%$", value)
        md = re.search(r"（(\d+/\d+)）", label)
        if mv:
            name, p = mv.group(1), int(mv.group(2))
            label = (f"{md.group(1)} " if md else "") + f"{name}"
            tip = f"{value}｜{delta}"
            pm = re.search(r"前日\s*(\d+)%", delta)
            if pm:
                dp = p - (100 - int(pm.group(1)))
                delta, d = f"{dp:+d}pp", ("up" if dp > 0 else "dn" if dp < 0 else "")
            else:
                delta, d = "—", ""
            value = f"{p}%"
    elif cid in ("fw_h1", "fw_h2", "fw_h3"):
        # 「至 2026 年底（12/9）累計」→ 標籤「至 2026 年底」，會議日進提示
        mh = re.match(r"^至\s*(\d{4})\s*年(底|中)（(\d+/\d+)）", label)
        if mh:
            label = f"至{mh.group(1)}年{mh.group(2)}"
        cur = re.match(r"^([+-]?[\d.]+)", value)
        old = re.search(r"前日\s*([+-]?[\d.]+)", delta)
        tip = delta.split("（")[0] + (f"｜到 {mh.group(3)} 會議為止的累計隱含升降息，聯邦基金期貨推算"
                                       if cid.startswith("fw_h") and mh else "")
        if cur and old:
            dd = float(cur.group(1)) - float(old.group(1))
            delta, d = f"{dd:+.1f} bp", ("up" if dd > 0.05 else "dn" if dd < -0.05 else "")
        else:
            delta = "—"
    elif cid == "srf":
        if value.startswith("0"):
            value, delta, tip = "0 億美元", "—", "未動用（零是常態：體系不缺錢）"
    elif cid in ("gold", "dxy", "twd", "eurusd", "usdjpy", "usdcnh"):
        source = c.get("source") or "Yahoo"
        date = (source + " " + date) if date else ""
        tip = {"gold": "COMEX 黃金期貨（GC=F），美元／盎司；Yahoo 延遲報價。",
               "dxy": "美元指數 DXY（DX-Y.NYB）；Yahoo 延遲報價。",
               "eurusd": "EUR/USD：1 歐元兌多少美元，上升＝歐元升值、美元走弱；Yahoo 延遲報價。",
               "usdjpy": "USD/JPY：1 美元兌多少日圓，上升＝日圓貶值；Yahoo 延遲報價。",
               "usdcnh": "USD/CNH：1 美元兌多少離岸人民幣，上升＝人民幣貶值；Yahoo 延遲報價。",
               "twd": "USD/TWD：1 美元兌多少新台幣。數值上升＝台幣貶值，下降＝台幣升值。FRED 資料為紐約中午買入匯率，非台灣收盤價。"}[cid]
        if cid == "gold" and value != "—":
            value = "$" + value.replace(" 美元／盎司", "")
    elif cid in ("wti", "brent"):
        value = "$" + value.replace(" 美元", "").replace("美元", "")
    elif cid in ("dji", "sox", "txf", "spx", "ixic", "twii"):
        if "（" in delta:
            delta, pct = delta.split("（", 1)
            tip = "漲跌幅 " + pct.rstrip("）")
    elif cid in ("pm_house", "pm_senate"):
        delta = delta.replace(" 個百分點", "pp").replace("個百分點", "pp").replace(" 百分點", "pp")
        label = label.replace("・", " ")
        if not d and re.match(r"^[+-]\d", delta):
            d = "up" if delta.startswith("+") else "dn"
    return {"label": label, "value": value, "delta": delta.strip(), "dir": d,
            "date": date, "tip": tip}


_INDICATOR_GROUPS = (
    ("美債殖利率", ("dgs3mo", "dgs2", "dgs5", "dgs7", "dgs10", "dgs20", "dgs30",
                   "live_dgs10", "live_dgs30")),
    ("聯準會與升降息", ("fedwatch", "fw_h1", "fw_h2", "fw_h3")),
    ("資金市場", ("sofr", "sofr_iorb", "onrrp", "srf")),
    ("股市與台指期", ("dji", "spx", "ixic", "sox", "twii", "txf")),
    ("市場波動", ("vix", "move")),
    ("原油與黃金", ("wti", "brent", "gold")),
    ("匯率", ("dxy", "twd", "eurusd", "usdjpy", "usdcnh")),
    ("期中選舉", ("pm_house", "pm_senate")),
)


def _indicator_options(cat: list[dict]) -> str:
    """Group the native picker; keep every indicator's ID and news mapping."""
    by_id={c["id"]:c for c in cat}
    seen=set()
    groups=[]
    definitions=list(_INDICATOR_GROUPS)+[("其他指標",tuple(by_id))]
    for label,ids in definitions:
        members=[cid for cid in ids if cid in by_id and cid not in seen]
        if not members:
            continue
        seen.update(members)
        options="".join('<option value="'+esc(cid)+'">'+esc(_unify_chip(by_id[cid])["label"])+"</option>" for cid in members)
        groups.append('<optgroup label="'+esc(label)+'">'+options+"</optgroup>")
    return "".join(groups)


def _indicator_checks(cat: list[dict]) -> str:
    """勾選清單（第十八批）：分組、每個指標一個 checkbox，右側小數字是顯示順序。"""
    by_id = {c["id"]: c for c in cat}
    seen, groups = set(), []
    for label, ids in list(_INDICATOR_GROUPS) + [("其他指標", tuple(by_id))]:
        members = [cid for cid in ids if cid in by_id and cid not in seen]
        if not members:
            continue
        seen.update(members)
        boxes = "".join(
            f'<label class="fs-pk"><input type="checkbox" value="{esc(cid)}"'
            + (" checked" if by_id[cid].get("on") else "") + '>'
            f'<span>{esc(_unify_chip(by_id[cid])["label"])}</span><em class="fs-pk-n"></em></label>'
            for cid in members)
        groups.append(f'<fieldset class="fs-pkg"><legend>{esc(label)}</legend>{boxes}</fieldset>')
    return '<div class="fs-pickp">' + "".join(groups) + '</div>'


def _point_tag(f: dict, i: int) -> str:
    """兩個重點不加小標（2026-10-27 v2.4 使用者：主軸不用標示重點一、重點二）；保留函式讓呼叫端不用改。"""
    return ""


# 2026-10-29：固定露出四行內文（第四行淡出）再接「展開全文」；不到四行就整段顯示、不放按鈕。
# 收著的面板（過去日期、另一個分頁）量不到高度，等它出現時再量（window.fsClip）。
_FOLD_JS = ("<script>(function(){var st=document.querySelector('.focus-strip');if(!st)return;"
            "var wide=window.matchMedia&&matchMedia('(min-width:760px)').matches;"
            "window.fsClip=function(){Array.prototype.forEach.call(st.querySelectorAll('.fs-more.fs-clip:not([data-ck])'),function(m){"
            "if(wide){m.setAttribute('data-ck','1');m.classList.remove('fs-clip');var t=m.nextElementSibling;"
            "if(t&&t.classList.contains('fs-tog')){t.textContent='收合 ▴';t.setAttribute('aria-expanded','true');}return;}"
            "if(!m.offsetParent)return;m.setAttribute('data-ck','1');"
            "var p=m.querySelector('.fs-main');if(p){var lh=parseFloat(getComputedStyle(p).lineHeight)||0;"
            "if(lh)m.style.setProperty('--clip',(p.getBoundingClientRect().top-m.getBoundingClientRect().top+lh*4)+'px');}"
            "if(m.scrollHeight<=m.clientHeight+4){m.classList.remove('fs-clip');var b=m.nextElementSibling;if(b&&b.classList.contains('fs-tog'))b.hidden=true;}});};"
            "window.fsClip();"
            "st.addEventListener('click',function(e){var b=e.target.closest('.fs-tog');if(!b)return;"
            "var m=b.previousElementSibling;if(!m)return;var o=m.classList.toggle('fs-clip');"
            "b.setAttribute('aria-expanded',o?'false':'true');"
            "b.textContent=o?'展開全文 ▾':'收合 ▴';});})();</script>")


def _fold(body: str, fold: bool) -> str:
    """今日主軸（2026-10-29）：預設只露標題，內容收進「展開全文」。沒有標題時不收合。"""
    if not body or not fold:
        return body
    return (f'<div class="fs-more fs-clip">{body}</div>'
            '<button type="button" class="fs-tog" aria-expanded="false">展開全文 ▾</button>')


_DUO_JS = r"""<script>(function(){
var d=document.querySelector('.duo');if(!d)return;
var md=document.createElement('div');md.className='duo-modal';md.hidden=true;md.setAttribute('role','dialog');md.setAttribute('aria-modal','true');
md.innerHTML='<div class="duo-sheet"><div class="duo-sheet-h"><b></b><button type="button" class="duo-x" aria-label="關閉">✕</button></div><div class="duo-body"></div></div>';
(d.closest('.viz-root')||document.body).appendChild(md);
var body=md.querySelector('.duo-body'),ttl=md.querySelector('.duo-sheet-h b'),cur=null,last=null;
function shut(){if(md.hidden)return;md.hidden=true;document.body.classList.remove('duo-lock');
 if(cur){while(body.firstChild)cur.appendChild(body.firstChild);}cur=null;if(last)last.focus();}
d.querySelectorAll('.duo-card').forEach(function(c){c.addEventListener('click',function(){
 var p=d.querySelector('.duo-panel[data-t="'+c.getAttribute('data-t')+'"]');if(!p)return;
 cur=p;last=c;while(p.firstChild)body.appendChild(p.firstChild);
 ttl.textContent=c.getAttribute('data-title')||c.querySelector('.duo-t').textContent;md.hidden=false;document.body.classList.add('duo-lock');
 md.querySelector('.duo-sheet').scrollTop=0;md.querySelector('.duo-x').focus();});});
md.addEventListener('click',function(e){if(e.target===md||e.target.closest('.duo-x'))shut();});
document.addEventListener('keydown',function(e){if(e.key==='Escape')shut();});
md.addEventListener('click',function(e){
 if(e.target.closest('.ai-sel')){e.preventDefault();return;}
 var t=e.target.closest('.ai-tile');
 if(t){md.querySelectorAll('.ai-tile').forEach(function(x){var on=x===t;x.classList.toggle('on',on);x.setAttribute('aria-pressed',on?'true':'false');});
  md.querySelectorAll('.ai-pane').forEach(function(p){p.hidden=p.getAttribute('data-co')!==t.getAttribute('data-co');});}});
md.addEventListener('change',function(e){var s=e.target.closest('.ai-sel select');if(!s)return;
 var rs=md.querySelectorAll('.ai-r'),seen={};rs.forEach(function(r){r.hidden=!(s.value==='全部類型'||r.getAttribute('data-ty')===s.value);});
 rs.forEach(function(r){var d=r.querySelector('.ai-r-d');if(!d.dataset.d)d.dataset.d=d.textContent;});
 var cur='';rs.forEach(function(r){var d=r.querySelector('.ai-r-d');if(d.dataset.d)cur=d.dataset.d;if(r.hidden)return;
  var first=!seen[cur];seen[cur]=1;d.textContent=first?cur:'';r.classList.toggle('day',first);});});
})();</script>"""


def _duo(ctxs: dict, extra: list | None = None) -> str:
    """
    期中選舉＋AI 大事兩張小卡（2026-10-29）：點了跳出視窗看完整內容。
    2026-10-29 晚：extra＝[(代號, 小卡, 視窗內容)]——01–04 也收進來，成為「今日總覽」六宮格
    （手機 2×3、電腦 3×2，一張卡、線分隔、六格等大）。
    """
    tiles, panels = [], []
    pairs = [("el", _election_tile(ctxs.get("_election"))), ("ai", _ai_tile(ctxs.get("_ai_events")))]
    pairs += [(t, (tile, panel)) for t, tile, panel in (extra or [])]
    for t, (tile, panel) in pairs:
        if tile:
            tiles.append(tile)
            panels.append(f'<div class="duo-panel" data-t="{t}" hidden>{panel}</div>')
    if not tiles:
        return ""
    return (f'<section class="duo{" duo-1" if len(tiles) == 1 else ""}{" duo-6" if extra else ""}" aria-label="今日總覽">'
            f'<div class="duo-grid">{"".join(tiles)}</div>{"".join(panels)}{_DUO_JS}</section>')


def _tile(t: str, kick: str, title: str, gfx: str, summ: str, modal_title: str) -> str:
    """六宮格的一格：上方小字・標題・圖區（固定高）・一行摘要；右上角 › 表示可點。"""
    return (f'<button type="button" class="duo-card" data-t="{t}" data-title="{esc(modal_title)}" aria-haspopup="dialog">'
            f'<span class="duo-k">{esc(kick)}</span><span class="duo-t">{esc(title)}</span>'
            f'<span class="duo-map duo-gfx">{gfx}</span><span class="duo-sum">{summ}</span></button>')


def _next_step(nx: dict, sc) -> str:
    """01 小卡摘要：「可能下一格」那條門檻翻成一句白話（2026-10-29）。"""
    t = nx.get("trigger")
    if nx.get("mode") == "hold" or t is None:
        return "兩軸都還離門檻很遠"
    lb = t.label
    if lb.startswith(("就業", "勞動")):
        if "「弱」" in lb:
            return "下一步：就業會不會轉弱"
        if "「強」" in lb:
            return "下一步：就業會不會轉強"
        return "下一步：就業能否回穩" if sc.labor_state == "弱" else "下一步：就業會不會降溫"
    if lb.startswith("通膨"):
        if "「高」" in lb:
            return "下一步：通膨會不會升溫"
        if "「低」" in lb:
            return "下一步：通膨能否降到目標"
        return "下一步：通膨能否降溫" if sc.infl_state == "高" else "下一步：通膨會不會回升"
    return ""


def _mini_cal(wt: dict) -> str:
    """03 小卡的小月曆：這個月、過去日期淡化、今天深色方塊、有事的日子下方一個小點。"""
    import calendar as _cal
    today = wt.get("today") or clock.today()
    marks = wt.get("marks") or {}
    out = "".join(f'<span class="mc-w">{w}</span>' for w in "一二三四五六日")
    for wk in _cal.Calendar(firstweekday=0).monthdatescalendar(today.year, today.month):
        for d in wk:
            if d.month != today.month:
                out += '<span></span>'
                continue
            ks = marks.get(d.isoformat()) or set()
            k = next((x for x in ("d", "s", "p") if x in ks), "")
            cls = "mc-to" if d == today else ("mc-ps" if d < today else "")
            out += (f'<span class="{cls}">{d.day}' + (f'<i class="mc-{k}"></i>' if k and d >= today else "")
                    + '</span>')
    return f'<span class="mc">{out}</span>'


def _overview_tiles(ctxs: dict, sc, lean: str, labor_label: str, infl_label: str, nx: dict, chg: dict) -> list:
    """01–04 四格小卡（2026-10-29）。"""
    t01 = _tile("n01", "01 今日結論", f"{sc.name}・{lean}",
                f'<span class="ud2"><span><span>就業</span><span>{esc(labor_label)}</span></span><em>×</em>'
                f'<span><span>通膨</span><span>{esc(infl_label)}</span></span></span>',
                esc(_next_step(nx, sc)), "今日結論")
    n = chg.get("n") or {}
    if chg.get("total"):
        bar = "".join(f'<i class="{k}" style="flex:{n[k]}"></i>' for k in ("dovish", "hawkish", "neutral") if n.get(k))
        g02 = (f'<span class="t-bar">{bar}</span><span class="t-lg"><span class="dovish">鴿 {n.get("dovish", 0)}</span>'
               f'<span class="hawkish">鷹 {n.get("hawkish", 0)}</span><span class="neutral">中性 {n.get("neutral", 0)}</span></span>')
        t02 = _tile("n02", "02 本期變化", chg.get("tilt", ""), f'<span class="t-chg">{g02}</span>',
                    f'本期 {chg["total"]} 項變動', "本期變化")
    else:
        t02 = _tile("n02", "02 本期變化", "沒有新變動", "", "跟上一期相同", "本期變化")
    wt = ctxs.get("_watch_tile") or {}
    td = wt.get("today") or clock.today()
    t03 = _tile("n03", "03 接下來看什麼", f"{td.month} 月", _mini_cal(wt), esc(wt.get("next") or "近期沒有排定的事項"),
                "接下來看什麼")
    from .forecasts_ui import tile as _fc_tile
    try:
        rows, summ = _fc_tile(ctxs.get("_forecasts"))
    except Exception:                              # noqa: BLE001
        rows, summ = [], ""
    _em = ' class="em"'
    g04 = '<span class="t-rows">' + "".join(
        f'<span><span>{esc(a)}</span><b{_em if em else ""}>{esc(b)}</b></span>' for a, b, em in rows) + '</span>'
    t04 = _tile("n04", "04 各家預測", "預估 vs 實際", g04, esc(summ), "各家預測")
    return [t01, t02, t03, t04]


def _fx_card(focus: str, overview: str) -> str:
    """
    「今日市場焦點｜今日總覽」合併卡（2026-10-29）：深藍標題列左右兩個分頁，中間一條線；
    選中的白字＋橘色短底線。預設焦點，記住上次選的；快報還沒看時焦點分頁右上角一個橘點。
    """
    if not focus:
        return (f'<section class="mgx mgx-solo"><div class="mgx-tabs"><span class="mgx-l on">今日總覽</span></div>'
                f'<div class="mgx-p">{overview}</div></section>')
    return ('<section class="mgx" aria-label="今日市場焦點與今日總覽">'
            '<input type="radio" name="fx-t" id="mgx-f" class="mgx-in" checked>'
            '<input type="radio" name="fx-t" id="mgx-o" class="mgx-in">'
            '<div class="mgx-tabs" role="tablist"><label for="mgx-f" class="mgx-l mgx-lf">今日市場焦點<i class="mgx-dot"></i></label>'
            '<b class="mgx-sep"></b><label for="mgx-o" class="mgx-l mgx-lo">今日總覽</label></div>'
            f'<div class="mgx-p mgx-pf">{focus}</div><div class="mgx-p mgx-po">{overview}</div>'
            + _FX_JS + '</section>')


_FX_JS = r"""<script>(function(){var f=document.getElementById('mgx-f'),o=document.getElementById('mgx-o');if(!f||!o)return;
function lsg(k){try{return localStorage.getItem(k);}catch(e){return null;}}
function lss(k,v){try{localStorage.setItem(k,v);}catch(e){}}
if(lsg('fxTab')==='o')o.checked=true;
[f,o].forEach(function(r){r.addEventListener('change',function(){lss('fxTab',o.checked?'o':'f');if(window.fsClip)window.fsClip();});});
})();</script>"""


def _archive_days(f: dict) -> tuple[str, str]:
    """
    主軸存檔（2026-10）：今天＋過去最多 6 個有發布的日子（共 7 天）。回傳 (日期選單, 過去幾天的面板)。
    2026-10-29 起日期改成下拉選單（預設今天），不再列一排膠囊。只有一天（還沒累積）就不顯示。
    """
    arch = [x for x in (f.get("archive") or []) if x.get("text")]
    if not arch:
        return "", ""
    cur = next((x for x in arch if x.get("text") == f.get("text")), None)
    past = [x for x in arch if x is not cur][:6]
    if not past:
        return "", ""
    today = clock.today().isoformat()

    def lab(d):
        dd = dt.date.fromisoformat(d)
        return f"{dd.month}/{dd.day}（{'一二三四五六日'[dd.weekday()]}）"
    # 2026-10-29：選單一律寫日期（星期幾），預設選中最新一版（今天打開就是今天）
    cur_lab = lab(cur["date"]) if cur else lab(today)
    opts = (f'<option value="cur" selected>{esc(cur_lab)}</option>'
            + "".join(f'<option value="{esc(x["date"])}">{esc(lab(x["date"]))}'
                      f'{"　本週回顧" if x.get("weekly") else ""}</option>' for x in past))
    panels = ""
    for x in past:
        paras = [p.strip() for p in (x.get("text") or "").split("\n") if p.strip()]
        mains = [m.strip() for m in (paras[0] if paras else "").split("¶") if m.strip()]
        _ptg = lambda i: _point_tag(x, i)   # noqa: E731
        lk = "".join(f'<li><a href="{esc(l.get("link", ""))}" rel="noopener">{esc(l.get("title", ""))}</a>'
                     f'<span class="fs-src">{esc(l.get("source", ""))}</span></li>'
                     for l in (x.get("links") or []) if l.get("link"))
        _hx = ("本週回顧｜" if x.get("weekly") else "") + (x.get("headline") or "")
        _body = ("".join(f'<p class="fs-main">{_ptg(i)}{esc(m)}</p>' for i, m in enumerate(mains))
                 + (f'<p class="fs-rate"><b>對利率</b>{esc(x["rate_note"])}</p>' if x.get("rate_note") else "")
                 + (f'<div class="fs-day-src"><b>參考報導</b><ul>{lk}</ul></div>' if lk else ""))
        panels += (f'<div class="fs-day-p" data-day="{esc(x["date"])}" hidden>'
                   + (f'<p class="fs-headline">{esc(_hx)}</p>' if _hx else "")
                   + _fold(_body, bool(_hx)) + '</div>')
    js = ("<script>(function(){var st=document.querySelector('.focus-strip');if(!st)return;"
          "var sel=st.querySelector('.fs-days select');if(!sel)return;"
          "sel.addEventListener('change',function(){var d=sel.value;"
          "Array.prototype.forEach.call(st.querySelectorAll('.fs-day-p'),function(p){p.hidden=p.getAttribute('data-day')!==d;});"
          "st.classList.toggle('fs-past',d!=='cur');if(window.fsClip)window.fsClip();});})();</script>")
    return (f'<label class="fs-days"><span>日期</span><select aria-label="主軸日期">{opts}</select></label>{js}',
            panels)


def _focus_strip(f: dict | None, tabbed: bool = False) -> str:
    """
    今日市場焦點：hero 之上的窄條。自選 chip 目錄＋一段焦點。

    目錄共 19 顆（各天期利率、升降息三顆、SOFR／利差／ON RRP／SRF、
    油價、VIX／MOVE、道瓊／費半／台指期），**全部**渲染進 HTML；預設只顯示 2Y＋10Y＋30Y＋機率，
    其餘掛 .fs-off 隱藏。「自訂」勾選面板＋幾行原生 JS 切換顯示、
    localStorage 記住選擇——關 JS 或初次造訪就是預設組，畫面不會壞。
    每顆 chip 的小字只放資料日；一句話說明集中在頁尾（手機沒有 hover）。
    """
    if not f:
        return ""
    import json as _json
    fw = f.get("fedwatch") or {}
    cat = f.get("chips") or []
    picker = script = editbar = ""
    # 主題補充：每個主題的一則補充都放進 HTML，依指標順序挑兩則顯示
    from ..analysis.focus_today import pick_topics
    topics = [x for x in (f.get("topics") or []) if x.get("text")]
    topic_map = f.get("topic_map") or {}
    avail = [x["id"] for x in topics]
    _default_sel = [c["id"] for c in cat if c.get("on")]
    shown = pick_topics(_default_sel, topic_map, avail)
    if cat:
        chips, defaults, opts = [], [], []
        for c in cat:
            off = "" if c.get("on") else " fs-off"
            if c.get("on"):
                defaults.append(c["id"])
            when = (f'<small class="fs-when">{esc(c["date"])}</small>'
                    if c.get("date") else "")
            # 報價板一行一格（2026-10）：四欄意義統一——數值＝純數字、
            # 變動＝對前一日（同單位），說明文字一律進提示（見 _unify_chip）
            u = _unify_chip(c)
            when = (f'<small class="fs-when">{esc(u["date"])}</small>' if u["date"] else "")
            delta = f'<i class="{u["dir"] or "fl"}">{esc(u["delta"])}</i>'
            # MTD／YTD（第十八批）：目前值與上月底、去年底基準給前端算
            _mv = ""
            if c.get("num") is not None and c.get("k"):
                _mv = (f' data-v="{c["num"]}" data-k="{esc(c["k"])}"'
                       + (f' data-bm="{c["bm"]}" data-bmd="{esc(c.get("bmd", ""))}"' if c.get("bm") is not None else "")
                       + (f' data-by="{c["by"]}" data-byd="{esc(c.get("byd", ""))}"' if c.get("by") is not None else "")
                       + (f' data-pv="{c["pv"]}"' if c.get("pv") is not None else "")
                       + (' data-pc="1"' if c.get("pc") else "")
                       + (f' data-u="{esc(c["u"])}"' if c.get("u") else ""))
                # 價格類：點開說明＝日漲跌幅（JS 會依「日變動／MTD／YTD」改寫），後接原本的說明
                _t0 = u["tip"] if not (u["tip"] or "").startswith("漲跌幅") else ""
                _mv += f' data-tip0="{esc(_t0)}"'
                if c.get("pc") and c.get("pv"):
                    _pct = (c["num"] / c["pv"] - 1) * 100
                    u = dict(u, tip=f"日漲跌幅 {_pct:+.2f}%（對前一交易日收盤）" + (f"｜{_t0}" if _t0 else ""))
            chips.append(f'<div class="fs-chip{off}" data-chip="{c["id"]}"'
                         f' data-d="{esc(c.get("iso") or "")}"' + _mv
                         + (f' title="{esc(u["tip"])}"' if u["tip"] else "") + '>'
                         f'<div class="fs-nm"><span>{esc(u["label"])}</span>{when}</div>'
                         f'{delta}<b>{esc(u["value"])}</b></div>')
            opts.append((c["id"], c["label"], c.get("on")))
        # 2026-10 改版（使用者：「直接從下方四個去選，沒必要再跳出一個篩選器」）：
        # 按「選擇指標」→ 報價板進入編輯狀態，點任一行就是原生選單、選了換掉
        # 那一行（選到已在板上的就兩行互換）；前兩行標「補充新聞」。
        # 新聞主題可獨立更換；只有調整指標時才重新依序選新聞。
        # 第十八批：改成勾選清單——勾幾個顯示幾個（不設上限），勾選順序就是
        # 顯示順序；前兩個決定補充新聞。
        picker = ('<button type="button" class="fs-edit-btn">選擇指標</button>')
        editbar = ('<div class="fs-editbar"><span>勾選要顯示的指標，不限數量；長按一行、上下拖曳調整順序'
                   '（不影響補充新聞，新聞用標籤的 ▾ 換）<b class="fs-pk-cnt"></b></span>'
                   '<button type="button" class="fs-reset">恢復預設</button>'
                   '<button type="button" class="fs-done">完成</button>'
                   + _indicator_checks(cat) + '</div>')
        _tl = {x["id"]: x["label"] for x in topics}
        _topt = "".join(
            f'<option value="{tid}"' + ("" if tid in avail else " disabled") + '>'
            + esc(_tl.get(tid) or TOPIC_LABEL.get(tid, tid)) + ("" if tid in avail else "（新聞暫缺）")
            + '</option>' for tid in TOPIC_REP_ORDER)
        script = ('<script>var FS_CONFIG=' + _json.dumps({"defaults": defaults, "wideExtra": WIDE_EXTRA_CHIPS, "topicMap": topic_map,
                  "available": avail, "topicOptions": _topt}, ensure_ascii=False)
                  + ';' + _CHIP_SELECT_JS + '</script>' + _LIVE_JS)

    else:
        # 目錄組裝失敗的後備：照舊三顆（10Y／30Y／機率），行為與舊版一致。
        chips = []
        for y in f.get("yields") or []:
            d = y.get("delta_bp")
            cls = "up" if (d or 0) > 0 else ("dn" if (d or 0) < 0 else "")
            dtxt = f"{d:+d} bps" if d is not None else "—"
            chips.append(f'<div class="fs-chip"><span>{esc(y["label"])}</span>'
                         f'<b>{y["value"]:.2f}%</b>'
                         f'<i class="{cls}">{esc(dtxt)}</i></div>')
        chips.append(_fw_chip_html(f))
    # 焦點是 N 則重點（一行一則）——逐則包 <li>，不能整坨塞進一個段落
    # （esc 會把換行吃掉，幾則變成一大塊）。
    _paras = [s.strip() for s in (f.get("text") or "").split("\n") if s.strip()]
    if _paras and f.get("layout") == "main":
        # 版式 A：第一行是主軸（一段話），其餘是補充（逐則 <li>）
        # 主軸可分 2–3 段（內部以 ¶ 串成一行，見 focus_today.MAIN_PARA）
        _mp = [s.strip() for s in _paras[0].split("¶") if s.strip()]
        # 補充：主題補充（依指標挑兩則）在前，一般補充（主軸那次一起寫的）
        # 只在主題不足兩則時遞補。預設畫面＝預設指標組的結果，JS 再依讀者
        # 的選擇重排；關 JS 也看得到合理的內容。
        _by = {x["id"]: x for x in topics}
        _tl = [f'<li class="fs-text fs-topic" data-topic="{esc(tid)}">'
               f'<span class="fs-tag">{esc(_by[tid]["label"])}</span>'
               f'{esc(_by[tid]["text"])}</li>' for tid in shown]
        _tl += [f'<li class="fs-text fs-topic fs-off" data-topic="{esc(x["id"])}">'
                f'<span class="fs-tag">{esc(x["label"])}</span>{esc(x["text"])}</li>'
                for x in topics if x["id"] not in shown]
        # 一般補充也掛標籤「主軸補充 ▾」（2026-10）：主題新聞不足兩則時由它遞補，
        # 以前沒有標籤、換不了；現在一樣可以從選單換成有新聞的主題。
        _gl = [f'<li class="fs-text{"" if i < 2 - len(shown) else " fs-off"}"'
               f' data-gen="1"><span class="fs-tag">{GEN_TAG}</span>{esc(s)}</li>'
               for i, s in enumerate(_paras[1:])]
        _items = _tl + _gl
        _weekly = bool(f.get("weekly"))
        if _weekly:
            # v2 星期天早上：主軸＝本週回顧，補充＝下週重點（全部顯示、不跟主題選單互換）
            _items = [f'<li class="fs-text fs-next"><span class="fs-tag">下週重點</span>{esc(s)}</li>'
                      for s in _paras[1:]] + _tl
        _hl = (f.get("headline") or "").strip()
        _rn = (f.get("rate_note") or "").strip()
        _days, _past = _archive_days(f)
        # 2026-10-29：日期選單移到「今日主軸」同一列右上；預設只露標題，其餘收合（沒有標題時全部展開）
        _cur = ("".join('<p class="fs-main">' + _point_tag(f, i) + esc(s) + '</p>' for i, s in enumerate(_mp))
                + (f'<p class="fs-rate"><b>對利率</b>{esc(_rn)}</p>' if _rn else "")
                + ('<ul class="fs-list">' + "".join(_items) + '</ul>' if _items else ""))
        text = ('<div class="fs-body"><div class="fs-top"><div class="fs-kicker">'
                + ("本週回顧與下週重點" if _weekly else "今日主軸") + '</div>' + _days + '</div>'
                + '<div class="fs-day-p" data-day="cur">'
                + (f'<p class="fs-headline">{esc(_hl)}</p>' if _hl else "")
                + _fold(_cur + "<!--FS_BRAND-->", bool(_hl))
                + '</div>' + _past + _FOLD_JS + '</div>')
    else:
        text = ('<ul class="fs-body fs-list">'
                + "".join(f'<li class="fs-text">{esc(s)}</li>' for s in _paras)
                + '</ul>') if _paras else ""
    # 主軸摘要暫缺也保留獨立主題新聞，避免一項摘要失敗使全部補充消失。
    if topics and not (_paras and f.get("layout") == "main"):
        _topic_rows = [
            f'<li class="fs-text fs-topic{"" if x["id"] in shown else " fs-off"}"'
            f' data-topic="{esc(x["id"])}"><span class="fs-tag">{esc(x["label"])}</span>'
            f'{esc(x["text"])}</li>' for x in topics]
        text += '<ul class="fs-list">' + "".join(_topic_rows) + '</ul>'
    # 列標題模式：AI 摘要不可用，標題清單就是內容——收合預設打開，
    # 不再另外把標題串成一段假摘要（同一批字印兩次）。
    _headline_mode = (f.get("text_source") == "headlines")
    links = ""
    if f.get("links") or topics:
        def _lk(x, tid=""):
            when = ""
            try:
                stamp = dt.datetime.fromisoformat(str(x.get("at") or ""))
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=dt.timezone.utc)
                when = stamp.astimezone(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
            except (ValueError, TypeError):
                pass
            return (f'<div class="fs-link{"" if not tid or tid in shown else " fs-off"}"'
                    + (f' data-tlink="{esc(tid)}"' if tid else "") + '>'
                    + (f'<span class="fs-tag">{esc(_lbl.get(tid, ""))}</span>' if tid else "")

                    + f'<a href="{esc(x["link"])}" rel="noopener">{esc(x["title"])}</a>'
                    + (f'<span class="fs-src">{esc(x["source"])}</span>'
                       if x.get("source") else "")
                    + (f'<span class="fs-src">{esc(when)} 報導</span>'
                       if when else "")
                    + '</div>')
        _lbl = {x["id"]: x["label"] for x in topics}
        rows = ("".join(_lk(x) for x in f.get("links") or [])
                + "".join(_lk(x, t["id"]) for t in topics
                          for x in (t.get("links") or [])[:1]))
        links = (f'<details class="f-more fs-reflinks"{" open" if _headline_mode else ""}>'
                 f'<summary>參考報導</summary>'
                 f'<div class="f-detail">{rows}</div></details>')
    # 機率的來源標示跟著實際走的那一層：期貨自算是可驗算的規則、
    # AI 擷取只是備援——兩者的可信度不同，不能共用同一句話。
    # 來源列壓成一短行（先前膨脹到近三行被使用者嫌冗長）——
    # 完整說明（WIRP 算法、延遲報價、各指標一句話解釋）住在頁尾的
    # 「焦點條指標」收合區，這裡只留最低限度的標示與指路。
    _ts = f.get("text_source") or ""
    if _ts == "headlines":
        _t_note = "・新聞摘要暫缺，可查看參考報導"
    elif _ts == "publisher-excerpt":
        _t_note = "・新聞重點摘錄自參考報導"
    elif _ts in ("model", "cache", "model-content"):
        _t_note = "・焦點由 AI 綜合報導改寫"
    else:
        _t_note = ""
    _fw_note = ("・機率由期貨反推" if fw.get("src") == "futures"
                else "・機率：官方值" if fw.get("src") == "atlanta"
                else "")
    note = ("利率：美國財政部／FRED 每日資料；來源與日期見各指標" + _fw_note + _t_note
            + "｜指標與方法說明見頁尾")
    # 品牌列（2026-10）：這一區是使用者每天截圖發社群的部分——截出去的圖
    # 要自己說得清楚「誰做的、哪一天、新聞從哪來」，不能靠頁面其他地方。
    # 標題旁仍不放日期（使用者先前指定移除），時間放在這一列。
    _srcs = []
    for x in (list(f.get("links") or [])
              + [(t.get("links") or [{}])[0] for t in topics if t["id"] in shown]):
        s = (x.get("source") or "").strip()
        if s and s not in _srcs:
            _srcs.append(s)
    from ..site import SITE_NAME, TAGLINE
    brand = ('<div class="fs-brand"><span class="fs-brand-name">'
             f'<b>{esc(SITE_NAME)}</b>{esc(TAGLINE)}</span>'
             f'<span class="fs-brand-meta">{esc(clock.stamp())}'
             + '<span class="fs-srcs">'
             + (f'　·　新聞：{esc("、".join(_srcs[:3]))}' if _srcs else "")
             + '</span></span></div>')
    # 2026-10-29：品牌與來源說明收進「展開全文」；沒有收合（沒有標題）時照舊放在卡片最下方
    _bn = f'{brand}<div class="fs-note">{esc(note)}</div>'
    if "<!--FS_BRAND-->" in text:
        # 2026-10-29：參考報導也收進「展開全文」（在品牌說明之上）
        _text, _tail = text.replace("<!--FS_BRAND-->", links + _bn, 1), ""
        links = ""
    else:
        _text, _tail = text, _bn
    # 桌機兩欄：左邊 2×2 數據磚、右邊新聞——截圖是一張緊湊的橫幅；
    # 手機上下堆疊。
    # 2026-10-29：tabbed＝放進「今日市場焦點｜今日總覽」合併卡，標題由分頁列負責，這裡只留快報與選擇指標
    _open, _close = (('<div class="focus-strip fs-in">', '</div>') if tabbed else
                     ('<section class="home-zone focus-strip" aria-label="今日市場焦點">', '</section>'))
    return (_open + '<div class="fs-head">' + ("" if tabbed else "今日市場焦點")
            + STORY_BTN + picker + '</div>' + editbar +
            '<div class="fs-grid">'
            '<div class="fs-chips"><div class="fs-hd"><span>指標</span>'
            '<span>變動</span><span>數值</span></div>' + "".join(chips) + '</div>'
            f'<div class="fs-news">{_text}{links}</div></div>'
            f'{_tail}'
            + script + _close)


# ===========================================================================
# 總覽第二版（2026-10）：市場焦點置頂 → 選舉 → 今日結論主卡（藏青品牌帶，
# 第二層整體情勢＋四大模組收合）→ 本期變化 → 接下來看什麼（四週）。
# 閱讀舒適度優先：白底細線分隔、顏色只用品牌藏青與橘，紅藍只留在方向小圓點。
# ===========================================================================
_TONE_DOT = {"hawkish": "haw", "dovish": "dov"}


def _hm_modules(ctxs: dict, sc, f_text: str, f_dir: str, p_text: str, p_level: str) -> str:
    from ..analysis.rates import pressure_label as _pl
    _pr = (ctxs.get("rates") or {}).get("pressure")
    p_tone = _pl(_pr)[1] if _pr is not None else "neutral"
    lab, inf = ctxs.get("labor") or {}, ctxs.get("inflation") or {}
    fom, rates = ctxs.get("fomc") or {}, ctxs.get("rates") or {}
    lk, ik = lab.get("kpi") or {}, inf.get("kpi") or {}
    curve = rates.get("curve")
    levels = getattr(curve, "levels", {}) if curve else {}
    term = getattr(curve, "term_premium", None) if curve else None
    _fnm = fom.get("next_meeting") or {}
    labor_label = {"弱": "偏弱", "中": "中性", "強": "偏強"}.get(sc.labor_state, sc.labor_state)
    infl_label = {"低": "偏低", "中": "中性", "高": "偏高"}.get(sc.infl_state, sc.infl_state)
    tiles = [
        ("/labor/", "就業", f"{labor_label}　{sc.labor_momentum}",
         "dovish" if sc.labor_state == "弱" else "hawkish" if sc.labor_state == "強" else "neutral",
         [("失業率", lk.get("u3_display", "—")), ("非農月增", lk.get("nfp_display", "—"))]),
        ("/inflation/", "通膨", f"{infl_label}　{sc.infl_momentum}",
         "hawkish" if sc.infl_state == "高" else "dovish" if sc.infl_state == "低" else "neutral",
         [("核心 PCE 年增", ik.get("pce_display", "—")), ("核心 CPI 月增", ik.get("core_display", "—"))]),
        ("/fomc/", "聯準會", f_text, f_dir,
         [("政策利率", fom.get("rate_range", "—")),
          ("下次會議", _fnm.get("span") or _fnm.get("date") or "—")]),
        ("/rates/", "長端與債務", f"期限溢酬{p_text}",
         p_tone,
         [("10 年期", _fmt_pct(levels.get("10Y"), 2)), ("期限溢酬", _fmt_pct(term, 2))]),
    ]
    out = []
    for href, name, status, tone, kv in tiles:
        nums = "".join(f'<span><em>{esc(k)}</em><b>{esc(v)}</b></span>' for k, v in kv)
        out.append(f'<a class="hm-mr" href="{href}"><span class="hm-mr-l"><b>{esc(name)}</b>'
                   f'<span class="hm-st"><i class="hm-dot {_TONE_DOT.get(tone, "")}"></i>{esc(status.replace("　", "・"))}</span></span>'
                   f'<span class="hm-mr-v">{nums}</span><span class="hm-mr-go">›</span></a>')
    return f'<div class="hm-mrs">{"".join(out)}</div>'


def _hm_brief(ctxs: dict) -> tuple[str, str]:
    b = ctxs.get("_brief") or brief_mod.compose(ctxs)
    whatsnew, bullets, rest, takeaway = _brief_pieces((b.get("text") or "").strip())
    rows = "".join(f'<div class="hm-br"><b>{esc(lb)}</b><p>{esc(tx)}</p></div>' for lb, tx in bullets)
    rows += "".join(f'<div class="hm-br"><b></b><p>{esc(x)}</p></div>' for x in rest)
    new = ""
    if whatsnew:
        items = [x.strip() for x in whatsnew[len("本次更新："):].replace("；", "；\n").split("\n") if x.strip()]
        head, tail = (items[0], items[1:]) if items else ("", [])
        new = (f'<details class="hm-new"><summary><span>本次更新</span>{esc(head.rstrip("；"))}'
               + (f'<em>＋{len(tail)} 項數字</em>' if tail else "") + '</summary>'
               + "".join(f'<span class="hm-new-i">{esc(t.rstrip("；。"))}</span>' for t in tail)
               + '</details>')
    return takeaway, f'<div class="hm-brs">{rows}</div>{new}'


def _resolved_text(title: str) -> str:
    """解除的訊號（2026-10-29）：「解除：核心 PCE 在降溫：三月年化 2.0%…」讀起來像「正在降溫」，
    改成「不再成立：核心 PCE 在降溫（上期 三月年化 2.0%…）」。"""
    head, sep, tail = str(title).partition("：")
    return f"不再成立：{head}（上期 {tail}）" if sep and tail else f"不再成立：{title}"


def _hm_changes(cs, regime: str = "", out: dict | None = None) -> str:
    """
    本期變化（2026-10 v2，使用者：太雜）：
      ① 一條比例條＋一句傾向（偏鴿／偏鷹／中性各幾項）
      ② 只列最重要的 5 項，一項一行：方向點・模組・內容
         排序：格位移動 → 數字變動（依「動了幾倍雜訊門檻」）→ 新出現的訊號 → 解除的訊號
      ③ 其餘收進「其他 N 項」，展開後依方向分三小段
    """
    if not cs or not cs.has_previous:
        return '<div class="home-empty">尚無可比對的上期資料；下一次更新後會顯示本期差異。</div>'
    items = []   # (rank, lean, module, text)
    for f in cs.new_flags:
        items.append((2, f.get("change_lean") or "neutral", f.get("module", "訊號"), f.get("title", "—")))
    for f in cs.resolved_flags:
        items.append((3, f.get("change_lean") or "neutral", f.get("module", "訊號"), _resolved_text(f.get("title", "—"))))
    _ml = {"labor": "就業", "inflation": "物價", "claims": "就業", "jolts": "就業", "ppi": "物價", "market": "市場"}
    moves = sorted(cs.metric_moves, key=lambda m: -abs(m.get("delta", 0)) / (m.get("threshold") or 1))
    for i, m in enumerate(moves):
        u = m.get("unit", "")
        # 數字只取前 3 名進「重點」，其餘排在訊號之後——否則 5 格常被數字佔滿，新訊號上不來
        items.append(((1 if i < 3 else 4) + i * 0.001, m.get("lean") or "neutral", _ml.get(m.get("module"), "數據"),
                      f"{m.get('label', '數據')} {m.get('from', 0):,.2f}{u} → {m.get('to', 0):,.2f}{u}"))
    if not items and not cs.scenario_moved:
        return '<div class="home-empty">主要訊號與上期相同，情境格位沒有改變。</div>'
    n = {k: sum(1 for x in items if x[1] == k) for k in ("dovish", "hawkish", "neutral")}
    total = len(items)
    # 第十八批：依聯準會目前的重心加權——重心那一軸的變動算兩倍。
    # 只數條數會讓就業（條目多）壓過通膨，而聯準會現在看的是通膨。
    _pri = {"inflation": "物價", "employment": "就業"}.get(regime, "")
    _w = lambda x: 2 if _pri and x[2] == _pri else 1
    wd = sum(_w(x) for x in items if x[1] == "dovish")
    wh = sum(_w(x) for x in items if x[1] == "hawkish")
    tilt = ("整體偏鴿" if wd > wh + 1 else "整體偏鷹" if wh > wd + 1 else "鷹鴿大致抵銷")
    _wnote = (f"{'通膨' if _pri == '物價' else '就業'}訊號加權 ×2（聯準會重心）" if _pri else "")
    if out is not None:          # 六宮格小卡用
        out.update(tilt=tilt, n=n, total=total)
    # 重點 5 項：重心那一軸優先（最多 3 項），其餘照原排序補滿
    if _pri:
        items.sort(key=lambda x: x[0])
        _p = [x for x in items if x[2] == _pri][:3]
        _rest = [x for x in items if x not in _p]
        items = [(i * 0.001, *x[1:]) for i, x in enumerate(_p + _rest)]
    bar = "".join(f'<i class="{k}" style="flex:{n[k]}"></i>' for k in ("dovish", "hawkish", "neutral") if n[k])
    head = (f'<div class="hm-c2-h"><p><b>{esc(tilt)}</b><span>本期 {total} 項變動'
            + (f'　·　{esc(_wnote)}' if _wnote else '') + '</span></p>'
            f'<div class="hm-c2-bar">{bar}</div>'
            f'<div class="hm-c2-lg"><span><i class="dovish"></i>偏鴿 {n["dovish"]}</span>'
            f'<span><i class="hawkish"></i>偏鷹 {n["hawkish"]}</span>'
            f'<span><i class="neutral"></i>中性 {n["neutral"]}</span></div></div>')
    items.sort(key=lambda x: x[0])
    _zh = {"dovish": "偏鴿", "hawkish": "偏鷹", "neutral": "中性"}

    def row(x):
        return (f'<li><i class="hm-c2-d {x[1]}" title="{_zh.get(x[1], "")}"></i>'
                f'<span class="hm-c2-m">{esc(x[2])}</span><span class="hm-c2-t">{esc(x[3])}</span></li>')
    top = items[:5]
    lead = ""
    if cs.scenario_moved:
        lead = (f'<li class="hm-c2-sc"><i class="hm-c2-d"></i><span class="hm-c2-m">格位</span>'
                f'<span class="hm-c2-t">{esc(cs.headline)}</span></li>')
        top = items[:4]
    body = f'<ul class="hm-c2">{lead}{"".join(row(x) for x in top)}</ul>'
    rest = items[len(top):]
    if rest:
        grp = ""
        for k in ("dovish", "hawkish", "neutral"):
            g = [x for x in rest if x[1] == k]
            if g:
                grp += (f'<div class="hm-c2-g"><div class="hm-c2-gh"><i class="hm-c2-d {k}"></i>{_zh[k]} {len(g)} 項</div>'
                        f'<ul class="hm-c2">{"".join(row(x) for x in g)}</ul></div>')
        body += (f'<details class="hm-c2-more"><summary>其他 {len(rest)} 項</summary>'
                 f'<div class="hm-c2-gs">{grp}</div></details>')
    return head + body


def _hm_when(tpe: dt.datetime, d_et: dt.date, today: dt.date) -> str:
    # 第十九批：日期一律寫台灣日期，不再出現「台灣隔天」（美東日期＋隔天容易看錯）
    return f"{'今天 ' if tpe.date() == today else ''}台灣 {tpe.strftime('%H:%M')}"


def _hm_label(d: dt.date) -> str:
    return f"{d.month:02d}/{d.day:02d}（{'一二三四五六日'[d.weekday()]}）"


def _hm_watch(ctxs: dict, sc, weeks: int = 4) -> str:
    """
    接下來看什麼：一次一週，‹ › 換週（純 CSS radio，不靠 JS）。
    第十八批：上方篩選——數據（原本的）、發債（標售＋回購）、官員談話、休市（2026-10）；
    數據列帶市場預估與前值（ForexFactory，只有本週），沒有預估時給前值＋近 6 期走勢。
    """
    from ..analysis import watch_calendar as wc
    today = clock.today()
    now = clock.now()
    fom = ctxs.get("fomc") or {}
    wx = ctxs.get("_watch_extra") or {}
    cons = wx.get("consensus") or {}
    import re as _re

    def _trig(prefix):
        c = [t for t in (sc.triggers or []) if t.label.startswith(prefix) and not t.met]
        if not c:
            return ""
        t = min(c, key=lambda x: abs(float((_re.search(r"[-+]?\d+(?:\.\d+)?", x.distance or "") or [9e9])[0])))
        return f"{t.label}的條件：{t.plain or t.distance}。"
    # 2026-10-29：FOMC 會議紀要列進「數據」，日期取自聯準會官網行事曆
    _sched = dict(ctxs.get("_schedule") or wc.merge_schedule({}, ctxs.get("_calendar") or {}, {}, today))
    _mins = sorted({a["date"] for a in fom.get("agenda") or [] if a.get("kind") == "會議紀要" and a.get("date")})
    if _mins:
        _sched["fomc_minutes"] = [(d, wc.SRC_FED) for d in _mins]
    rows = wc.watch_rows(
        _sched,
        fomc_next=((fom.get("next_meeting")) or {}).get("date"),
        fomc_desc="聲明與投票可能改變重心——重心一翻，同一格的結論就不同。",
        trig={"employment": _trig("就業轉"), "cpi": _trig("通膨轉"),
              "pce": _trig("通膨轉")}, weeks=weeks, keep_today=True)
    # 發債／官員談話也照數據列的格式：week、label、when、name、sub
    mon = today - dt.timedelta(days=today.weekday())
    start = mon + dt.timedelta(days=7 if today.weekday() >= 5 else 0)
    end = start + dt.timedelta(days=7 * weeks - 1)

    def _wk(d):
        return (d - start).days // 7

    # 數據列也改用台灣日期：標籤、時間、週別都依台北時間重算
    for e in rows:
        _td = e["tpe"].date()
        e["label"], e["week"] = _hm_label(_td), _wk(_td)
        e["when"] = _hm_when(e["tpe"], e["date"], today)

    supply = []
    for a in wx.get("auctions") or []:
        try:
            d = dt.date.fromisoformat(a["date"])
        except (TypeError, ValueError):
            continue
        tpe = wc.taipei_time(d, (13, 0))
        if (tpe <= now and tpe.date() != today) or not start <= d <= end:   # 今天已過的留著、標已結束
            continue
        sub = ("已公告" + (f"・{a['amount']}" if a.get("amount") else "")
               if a.get("src") == "財政部公告" else "財政部暫定時程")
        supply.append({"week": _wk(tpe.date()), "tpe": tpe, "label": _hm_label(tpe.date()),
                       "when": _hm_when(tpe, d, today), "name": a.get("name", "公債標售"),
                       "sub": sub, "tag": "標售", "done": tpe <= now})
    for b in wx.get("buybacks") or []:
        try:
            d = dt.date.fromisoformat(b["date"])
        except (TypeError, ValueError):
            continue
        tpe = wc.taipei_time(d, tuple(b.get("end") or (14, 0)))
        if (tpe <= now and tpe.date() != today) or not start <= d <= end:
            continue
        supply.append({"week": _wk(tpe.date()), "tpe": tpe, "label": _hm_label(tpe.date()),
                       "when": _hm_when(tpe, d, today),
                       "name": f"國債回購・{b.get('segment', '')}",
                       "sub": f"{b.get('purpose', '')}・{b.get('max', '')}・財政部暫定時程",
                       "tag": "回購", "done": tpe <= now})
    speeches = []
    for x in wx.get("speeches") or []:
        et = x.get("et")
        if isinstance(et, str):
            try:
                et = dt.datetime.fromisoformat(et)
            except ValueError:
                continue
        d = et.date()
        tpe = wc.taipei_time(d, (et.hour, et.minute))
        if (tpe <= now and tpe.date() != today) or not start <= d <= end:
            continue
        # 第十九批（使用者指定）：官員名字寫英文
        who = f"{x.get('role', '')} {x.get('name', '') or x.get('zh', '')}".strip()
        sub = "・".join(v for v in (x.get("kind", ""), x.get("topic", "")) if v)
        speeches.append({"week": _wk(tpe.date()), "tpe": tpe, "label": _hm_label(tpe.date()),
                         "when": _hm_when(tpe, d, today) if x.get("time_known", True) else "時間未定",
                         "name": who, "sub": sub, "voter": x.get("voter"),
                         "src": x.get("src", ""), "done": tpe <= now})
    # 2026-10-29：靜默期開始列進「官員談話」（美東當天 00:00 起，官員不再公開談貨幣政策）
    _nm = fom.get("next_meeting") or {}
    if _nm.get("blackout_start"):
        try:
            _bd = dt.date.fromisoformat(_nm["blackout_start"])
            _btp = wc.taipei_time(_bd, (0, 0))
            if _btp > now and start <= _bd <= end:
                _be = _nm.get("blackout_end", "")
                speeches.append({"week": _wk(_btp.date()), "tpe": _btp, "label": _hm_label(_btp.date()),
                                 "when": _hm_when(_btp, _bd, today) + " 起",
                                 "name": "聯準會靜默期開始",
                                 "sub": "官員不公開談貨幣政策" + (f"，至 {int(_be[5:7])}/{int(_be[8:10])}" if _be else ""),
                                 "src": "聯準會規則"})
        except (TypeError, ValueError):
            pass
    # 10Y／30Y 標售原本混在數據列（財政部 upcoming＋yaml 暫定表）：搬到「發債」；
    # 附加資料抓不到時拿它們當後備
    _auc = [e for e in rows if str(e.get("key", "")).startswith("auction_")]
    rows = [e for e in rows if not str(e.get("key", "")).startswith("auction_")]
    if not wx.get("auctions"):
        supply += [{"week": e["week"], "tpe": e["tpe"], "label": e["label"], "when": e["when"],
                    "name": e["name"], "sub": e.get("src", ""), "tag": "標售"} for e in _auc]
    supply.sort(key=lambda e: e["tpe"])
    speeches.sort(key=lambda e: e["tpe"])

    lk = (ctxs.get("labor") or {})
    ik = (ctxs.get("inflation") or {})
    _prev = {"employment": f"前值：非農 {(lk.get('kpi') or {}).get('nfp_display', '—')}、"
                           f"失業率 {(lk.get('kpi') or {}).get('u3_display', '—')}",
             "cpi": f"前值：核心 CPI 月增 {(ik.get('kpi') or {}).get('core_display', '—')}",
             "pce": f"前值：核心 PCE 年增 {(ik.get('kpi') or {}).get('pce_display', '—')}"}
    _trend = {"employment": (lk.get("mini") or {}).get("nfp6", ""),
              "cpi": (ik.get("mini") or {}).get("core6", ""),
              "pce": (ik.get("mini") or {}).get("pcemom6", "")}

    # 休市（2026-10）：七個市場的休市與提早收盤，分股／債／匯
    from ..analysis import market_holidays as mh
    hols = mh.market_events(start, end)

    def _hgroups(evs):
        """同一天、全部休市、沒有額外說明的市場併成一列（「中國、香港、日本 元旦」）。"""
        out = []
        for e in evs:
            tag, _ = mh.status_text(e)
            plain = tag == "全部休市" and not e.get("note")
            g = next((x for x in out if plain and x.get("_plain") and x["date"] == e["date"]), None)
            if g:
                g["mk_zh"] += "、" + e["mk_zh"]
                if e["name"] not in g["_names"]:
                    g["_names"].append(e["name"])
                    g["name"] = "、".join(g["_names"])
                continue
            out.append(dict(e, _plain=plain, _names=[e["name"]]))
        return out

    def _st_html(t):
        """「＝台灣 隔日 02:00」整段不斷行。"""
        head, sep, tw = t.partition("＝台灣")
        return esc(head) + (f'<span class="hm-hol-tw">{esc(sep + tw)}</span>' if sep else "")

    # ---- 2026-10-29：列表與月曆共用同一種事件列（時間・符號・名稱・預估前值），依日期分組 ----
    def _wv_row(t, mk, name, sub="", tag="", extra="", done=""):
        # done：今天已經過了的（「已公布」「已結束」），整列淡化、留在原位
        if done:
            tag = f'<em class="wv-dn">{done}</em>' + tag
        return (f'<div class="wv-ev{" wv-done" if done else ""}"><span class="wv-t">{esc(t)}</span>{mk}<div class="wv-b">'
                f'<span class="wv-nm">{esc(name)}{tag}</span>'
                + (f'<span class="wv-cs">{sub}</span>' if sub else "") + extra + '</div></div>')

    def _wv_data(e):
        c = cons.get(f"{e['key']}|{e['date'].isoformat()}") or []
        if c:
            def _lb(x):        # 項目名稱跟事件名稱重複（GDP、初領）就不寫
                lb = x.get("label") or ""
                return "" if not lb or lb in e["name"] or e["name"] in lb else lb + " "
            sub = "・".join(f'{esc(_lb(x))}預估 <b>{esc(x["forecast"] or "—")}</b>・前值 {esc(x["previous"] or "—")}'
                           for x in c[:2])
        else:
            sub = esc(_prev.get(e["key"], ""))
        hi = e.get("impact") == "high"
        extra = (f'<details class="wv-tr"><summary>近 6 期走勢</summary>{_trend[e["key"]]}</details>'
                 if hi and _trend.get(e["key"]) else "")
        return _wv_row(e["tpe"].strftime("%H:%M"), f'<i class="mk mk-d{"" if hi else " mk-o"}"></i>', e["name"], sub,
                       '<em class="wv-hi">高影響</em>' if hi else "", extra, "已公布" if e.get("done") else "")

    def _wv_x(e, k):
        t = "未定" if e.get("when") == "時間未定" else e["tpe"].strftime("%H:%M")
        name = e["name"]
        return _wv_row(t, f'<i class="mk mk-{k}"></i>', name, esc(e.get("sub") or ""),
                       '<em class="wv-vt">票委</em>' if e.get("voter") else "", "", "已結束" if e.get("done") else "")

    def _wv_hol(e):
        tag, st_ = mh.status_text(e)
        sub = "・".join(x for x in (esc(e["name"]), _st_html(st_) if st_ else "", esc(e.get("note") or "")) if x)
        return _wv_row("全天", '<em class="mk-h">休</em>', f'{e["mk_zh"]} {tag}', sub)

    def _wv_days(items):
        """items：[(日期, html)] → 依日期分組；今天在日期後加橘字「今天」。"""
        out, cur = [], None
        for d, h in sorted(items, key=lambda x: x[0]):
            if d != cur:
                if cur is not None:
                    out.append('</div>')
                cur = d
                out.append(f'<div class="wv-day"><div class="wv-dh">{esc(_hm_label(d))}'
                           + ('<span>今天</span>' if d == today else "") + '</div>')
            out.append(h)
        if cur is not None:
            out.append('</div>')
        return "".join(out)

    radios, panels = [], []
    for w in range(weeks):
        a_ = start + dt.timedelta(days=7 * w)
        b_ = a_ + dt.timedelta(days=6)
        name = (wc._GROUPS[(a_ - mon).days // 7] if (a_ - mon).days // 7 < len(wc._GROUPS) else f"第 {w + 1} 週")
        wk = [e for e in rows if e.get("week") == w]
        # 2026-10-29：不再用大卡區分高影響，同一天的依時間排成同一種列
        body = _wv_days([(e["tpe"].date(), _wv_data(e)) for e in sorted(wk, key=lambda e: e["tpe"])])
        # 本週剩下的都過了：說清楚、給一個「看下週」
        _nx = '<label class="wv-nx" for="hm-wk-1">看下週 ›</label>' if w == 0 and weeks > 1 else ""
        if not wk:
            body = f'<p class="home-empty">{"本週剩下沒有排定的數據發布。" if w == 0 else "這一週沒有排定的重要發布。"}{_nx}</p>'
        sw = [e for e in supply if e["week"] == w]
        pw = [e for e in speeches if e["week"] == w]
        sup_html = (_wv_days([(e["tpe"].date(), _wv_x(e, "s")) for e in sw]) if sw else
                    f'<p class="home-empty">{"本週剩下" if w == 0 else "這一週"}沒有排定的附息公債標售或國債回購。{_nx}</p>')
        spk_html = (_wv_days([(e["tpe"].date(), _wv_x(e, "p")) for e in pw]) if pw else
                    '<p class="home-empty">' + ("目前只排得到理事會成員的行程；地區聯儲總裁的談話要到該週才公布。"
                                                if w >= 1 else "本週剩下沒有排定的官員談話。") + _nx + '</p>')
        hw = _hgroups([e for e in hols if a_ <= e["date"] <= b_])
        hol_html = (_wv_days([(e["date"], _wv_hol(e)) for e in hw])
                    if hw else '<p class="home-empty">這一週七個市場都正常交易。</p>')
        prev_l = (f'<label class="hm-wk-a" for="hm-wk-{w - 1}" aria-label="上一週">‹</label>'
                  if w else '<span class="hm-wk-a off">‹</span>')
        next_l = (f'<label class="hm-wk-a" for="hm-wk-{w + 1}" aria-label="下一週">›</label>'
                  if w < weeks - 1 else '<span class="hm-wk-a off">›</span>')
        dots = "".join(f'<i class="{"on" if j == w else ""}"></i>' for j in range(weeks))
        cnt = (f'<span class="hm-cnt hm-cnt-data">{len(wk)} 場</span>'
               f'<span class="hm-cnt hm-cnt-sup">{len(sw)} 場</span>'
               f'<span class="hm-cnt hm-cnt-spk">{len(pw)} 場</span>'
               f'<span class="hm-cnt hm-cnt-hol">{len(hw)} 項</span>')
        radios.append(f'<input type="radio" name="hm-wk" id="hm-wk-{w}" class="hm-wk-in"{" checked" if w == 0 else ""}>')
        panels.append(f'<div class="hm-wk-p"><div class="hm-wk-h">{prev_l}<div class="hm-wk-t"><b>{esc(name)}</b>'
                      f'<span class="hm-wk-dots">{dots}</span></div>{next_l}</div>'
                      f'<div class="hm-cat hm-cat-data">{body}</div>'
                      f'<div class="hm-cat hm-cat-sup">{sup_html}</div>'
                      f'<div class="hm-cat hm-cat-spk">{spk_html}</div>'
                      f'<div class="hm-cat hm-cat-hol">{hol_html}</div>'
                      f'<p class="wv-cnt">{esc(name)} {a_.month}/{a_.day}–{b_.month}/{b_.day}・{cnt}・台灣時間</p></div>')
    cats = ('<input type="radio" name="hm-cat" id="hm-cat-data" class="hm-cat-in" checked>'
            '<input type="radio" name="hm-cat" id="hm-cat-sup" class="hm-cat-in">'
            '<input type="radio" name="hm-cat" id="hm-cat-spk" class="hm-cat-in">'
            '<input type="radio" name="hm-cat" id="hm-cat-hol" class="hm-cat-in">'
            '<div class="hm-cats" role="group" aria-label="篩選">'
            '<label for="hm-cat-data"><i class="mk mk-d"></i>數據</label><label for="hm-cat-sup"><i class="mk mk-s"></i>發債</label>'
            '<label for="hm-cat-spk"><i class="mk mk-p"></i>官員談話</label><label for="hm-cat-hol"><em class="mk-h">休</em>休市</label></div>')
    listing = (f'<div class="hm-wkx">{cats}<div class="hm-wk">{"".join(radios)}'
               f'<div class="hm-wk-ps">{"".join(panels)}</div></div></div>')
    # 今日快報（限時動態）第五則：存「完整日期與時間」，由瀏覽器依當下台灣時間判斷
    # 哪些是今天／明天、哪些已經過了（週日不更新、或過了午夜才打開，日期才不會錯一天）。
    # 多帶一天備用。
    _up = []
    for k_ in range(3):
        d_ = today + dt.timedelta(days=k_)
        for e in rows:
            if e["tpe"].date() == d_:
                _up.append({"date": d_.isoformat(), "at": e["tpe"].isoformat(), "k": "d",
                            "t": e["tpe"].strftime("%H:%M"), "name": e["name"],
                            "hi": e.get("impact") == "high"})
        for e in supply:
            if e["tpe"].date() == d_:
                _up.append({"date": d_.isoformat(), "at": e["tpe"].isoformat(), "k": "s",
                            "t": e["tpe"].strftime("%H:%M"), "name": e["name"]})
        for e in speeches:
            if e["tpe"].date() == d_:
                _known = e.get("when") != "時間未定"
                _up.append({"date": d_.isoformat(), "at": e["tpe"].isoformat() if _known else "",
                            "k": "p", "t": e["tpe"].strftime("%H:%M") if _known else "", "name": e["name"]})
        for e in _hgroups([h for h in hols if h["date"] == d_]):
            _up.append({"date": d_.isoformat(), "at": "", "k": "h", "t": "",
                        "name": f'{e["mk_zh"]}{mh.status_text(e)[0]}', "sub": e["name"]})
    # 依時間排序（2026-10：先前是「數據→發債→談話→休市」分類疊在一起，時間前後顛倒）。
    # 休市（整天）排在當天最前面，時間未定的談話排最後。
    _up.sort(key=lambda x: (x["date"], 0 if x["k"] == "h" else 1 if x.get("at") else 2, x.get("at") or ""))
    ctxs["_story_up"] = _up
    # 2026-10：「列表／月曆」切換（使用者：做一個總月曆，四種內容都要表示）
    def _cal_day(d, ev):
        items = ([(d, _wv_data(e)) for e in sorted(ev["d"], key=lambda e: e["tpe"])]
                 + [(d, _wv_x(e, "s")) for e in ev["s"]] + [(d, _wv_x(e, "p")) for e in ev["p"]]
                 + [(d, _wv_hol(e)) for e in _hgroups(ev["h"])])
        kinds = ["d"] * len(ev["d"]) + ["s"] * len(ev["s"]) + ["p"] * len(ev["p"]) + ["h"] * len(_hgroups(ev["h"]))
        html = _wv_days(items)
        # 每一列標上種類，月曆的開關才隱藏得到
        for k in kinds:
            html = html.replace('<div class="wv-ev">', f'<div class="wv-ev hc-k-{k}">', 1)
        return html
    cal = _hm_calendar(today, start, end, rows, supply, speeches, hols, _cal_day)
    # 2026-10-29 六宮格小卡：這個月每天有哪些種類＋下一件事（一行）
    _marks: dict = {}
    for k_, evs_ in (("d", rows), ("s", supply), ("p", speeches)):
        for e in evs_:
            _marks.setdefault(e["tpe"].date().isoformat(), set()).add(k_)
    _nxt = sorted([e for e in rows + supply + speeches if e["tpe"] > now], key=lambda e: e["tpe"])
    if _nxt:
        _d0 = _nxt[0]["tpe"].date()
        _w0 = ("今天" if _d0 == today else "明天" if _d0 == today + dt.timedelta(days=1)
               else f"{_d0.month}/{_d0.day}")
        _nt = f"{_w0}：{_nxt[0]['name']}"
    else:
        _nt = ""
    ctxs["_watch_tile"] = {"today": today, "marks": _marks, "next": _nt}
    # 2026-10-29：預設月曆（記住讀者上次選列表的話照舊）
    return ('<div class="hm-view">'
            '<input type="radio" name="hm-view" id="hm-view-list" class="hm-view-in">'
            '<input type="radio" name="hm-view" id="hm-view-cal" class="hm-view-in" checked>'
            + listing + cal + _hm_notes(end) + '</div>' + _HM_CAL_JS)


def _hm_notes(end) -> str:
    """「接下來看什麼」底下的解釋文字全部收進「說明」（2026-10，使用者指定）。
    月曆專用的那段只在月曆模式顯示。"""
    return ('<details class="f-more hm-notes"><summary>說明</summary>'
            '<p class="hm-foot hc-note">月曆：● 數據（實心＝高影響、空心＝中影響）、■ 發債、▲ 官員談話，'
            f'數字＝當天場數；數據、發債、官員談話排到 {end.month}/{end.day}。「休」＝美國或台灣全部休市、'
            '「半」＝部分休市或提早收盤，其他市場點日期看。點圖例可隱藏該類。</p>'
            '<p class="hm-foot">高影響：可能改變整體經濟與利率判讀；中影響：主要影響個別指標。'
            '市場預估與地區聯儲總裁行程取自 ForexFactory（非官方，只有本週）；標售與回購取自美國財政部；'
            '理事會行程取自聯準會官網。</p>'
            '<p class="hm-foot">休市：涵蓋美、英、台、中、港、日、韓；匯市＝當地貨幣交割。'
            '依交易所與各國假日表計算，颱風等臨時休市不列。</p></details>')


# 月曆：點日期看當天全部內容；記住讀者上次選的是列表還是月曆
_HM_CAL_JS = r"""<script>
(function(){var root=document.querySelector('.hm-cal');if(!root)return;
function lsg(k){try{return localStorage.getItem(k);}catch(e){return null;}}
function lss(k,v){try{localStorage.setItem(k,v);}catch(e){}}
var vl=document.getElementById('hm-view-list'),vc=document.getElementById('hm-view-cal');
if(lsg('hmView')==='list'&&vl)vl.checked=true;
[vl,vc].forEach(function(r){if(r)r.addEventListener('change',function(){lss('hmView',vc.checked?'cal':'list');});});
var dds=root.querySelectorAll('.hc-dd'),empty=root.querySelector('.hc-dd-none');
function pick(d,btn){Array.prototype.forEach.call(root.querySelectorAll('.hc-d.hc-sel'),function(x){x.classList.remove('hc-sel');});
 if(btn)btn.classList.add('hc-sel');var hit=false;
 Array.prototype.forEach.call(dds,function(x){var on=x.getAttribute('data-d')===d;x.hidden=!on;if(on)hit=true;});
 if(empty){empty.hidden=hit;var h=empty.querySelector('b'),s=empty.querySelector('.wv-dh span');if(h&&btn)h.textContent=btn.getAttribute('data-l')||'';
 if(s&&btn)s.hidden=!btn.classList.contains('hc-today');}}
root.addEventListener('click',function(e){var b=e.target.closest?e.target.closest('.hc-d[data-d]'):null;if(!b)return;
 pick(b.getAttribute('data-d'),b);});
var first=root.querySelector('.hc-d.hc-today')||root.querySelector('.hc-d[data-d]');
if(first)pick(first.getAttribute('data-d'),first);})();
</script>"""


def _hm_calendar(today, start, end, rows, supply, speeches, hols, render_day) -> str:
    """
    月曆（2026-10）：數據 ●（高影響實心、中影響空心）、發債 ■、官員談話 ▲；
    美國或台灣全部休市＝整格淺灰＋「休」，部分休市或提早收盤＝「半」
    （其他五個市場點日期才看得到）。上方圖例兼篩選（純 CSS checkbox）。
    """
    import calendar as _cal
    by: dict = {}

    def put(d, k, e):
        by.setdefault(d, {"d": [], "s": [], "p": [], "h": []})[k].append(e)
    for e in rows:
        put(e["tpe"].date(), "d", e)
    for e in supply:
        put(e["tpe"].date(), "s", e)
    for e in speeches:
        put(e["tpe"].date(), "p", e)
    from ..analysis import market_holidays as mh
    m0 = dt.date(start.year, start.month, 1)
    last_m = dt.date(end.year, end.month, 1)
    months = []
    m = m0
    while m <= last_m:
        months.append(m)
        m = dt.date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    h_end = dt.date(last_m.year, last_m.month, _cal.monthrange(last_m.year, last_m.month)[1])
    hol_all = mh.market_events(m0, h_end)
    for e in hol_all:
        put(e["date"], "h", e)

    def mark(k, items):
        if not items:
            return ""
        cls = "mk-" + k
        if k == "d" and not any(x.get("impact") == "high" for x in items):
            cls += " mk-o"
        n = f"<small>{len(items)}</small>" if len(items) > 1 else ""
        return f'<span class="mk-w"><i class="mk {cls}"></i>{n}</span>'

    wd = "一二三四五六日"
    radios, panels = [], []
    for i, m in enumerate(months):
        weeks_ = _cal.Calendar(firstweekday=0).monthdatescalendar(m.year, m.month)
        cells = "".join(f'<span class="hc-wd{" hc-we" if j >= 5 else ""}">{wd[j]}</span>' for j in range(7))
        for wk in weeks_:
            for j, d in enumerate(wk):
                if d.month != m.month:
                    cells += '<span class="hc-d hc-out"></span>'
                    continue
                ev = by.get(d) or {"d": [], "s": [], "p": [], "h": []}
                ust = [x for x in ev["h"] if x["mk"] in ("US", "TW")]
                full = any(len(x["closed"]) == 3 for x in ust)
                badge = ("休" if full else "半") if ust else ""
                cls = ["hc-d"]
                if j >= 5:
                    cls.append("hc-we")
                if d == today:
                    cls.append("hc-today")
                if d < today:
                    cls.append("hc-past")
                if full:
                    cls.append("hc-gray")
                summ = "、".join(f"{n} {len(ev[k])}" for k, n in (("d", "數據"), ("s", "發債"), ("p", "談話"))
                                if ev[k])
                if ev["h"]:
                    summ += ("、" if summ else "") + "休市 " + "、".join(dict.fromkeys(x["mk_zh"] for x in ev["h"]))
                lab = _hm_label(d)
                cells += (f'<button type="button" class="{" ".join(cls)}" data-d="{d.isoformat()}"'
                          f' data-l="{esc(lab)}" aria-label="{esc(lab + ("：" + summ if summ else ""))}">'
                          f'<span class="hc-n">{d.day}</span>'
                          + (f'<em class="hc-h">{badge}</em>' if badge else "")
                          + '<span class="hc-m">' + mark("d", ev["d"]) + mark("s", ev["s"])
                          + mark("p", ev["p"]) + '</span></button>')
        prev_l = (f'<label class="hm-wk-a" for="hc-m-{i - 1}" aria-label="上個月">‹</label>'
                  if i else '<span class="hm-wk-a off">‹</span>')
        next_l = (f'<label class="hm-wk-a" for="hc-m-{i + 1}" aria-label="下個月">›</label>'
                  if i < len(months) - 1 else '<span class="hm-wk-a off">›</span>')
        radios.append(f'<input type="radio" name="hc-m" id="hc-m-{i}" class="hc-m-in"{" checked" if i == 0 else ""}>')
        panels.append(f'<div class="hc-mp"><div class="hm-wk-h">{prev_l}<div class="hm-wk-t">'
                      f'<b>{m.month} 月</b></div>{next_l}</div>'
                      f'<div class="hc-grid">{cells}</div></div>')
    # 每一天的明細（點日期才顯示）
    dds = []
    for d in sorted(by):
        dds.append(f'<div class="hc-dd" data-d="{d.isoformat()}" hidden>{render_day(d, by[d])}</div>')
    filt = ('<input type="checkbox" id="hc-f-d" class="hc-f-in" checked>'
            '<input type="checkbox" id="hc-f-s" class="hc-f-in" checked>'
            '<input type="checkbox" id="hc-f-p" class="hc-f-in" checked>'
            '<input type="checkbox" id="hc-f-h" class="hc-f-in" checked>'
            '<div class="hc-lg" role="group" aria-label="圖例與篩選">'
            '<label for="hc-f-d"><i class="mk mk-d"></i>數據</label>'
            '<label for="hc-f-s"><i class="mk mk-s"></i>發債</label>'
            '<label for="hc-f-p"><i class="mk mk-p"></i>官員</label>'
            '<label for="hc-f-h"><em class="mk-h">休</em>休市</label></div>')
    return ('<div class="hm-cal">' + filt + "".join(radios)
            + f'<div class="hc-ms">{"".join(panels)}</div>'
            + f'<div class="hc-dds">{"".join(dds)}'
            + '<div class="hc-dd hc-dd-none" hidden><div class="wv-dh"><b></b><span hidden>今天</span></div>'
              '<p class="home-empty">這一天沒有排定的事項。</p></div></div>'
            + '<p class="wv-cnt">點類別隱藏／顯示・點日期看當天・台灣時間</p></div>')


def forecasts_section(fc: dict | None, modal: bool = False) -> str:
    """總覽 04 各家預測。組不出來就不放，不影響首頁。"""
    try:
        return _fc_section(fc, modal=modal)
    except Exception as e:                         # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("04 各家預測組裝失敗（%s），本次不顯示", e)
        return ""


def _story(ctxs: dict) -> str:
    """今日快報（限時動態）。資料組不出來就不放，不影響首頁。"""
    try:
        from ..analysis.stories import build_story
        return story_html(build_story(ctxs))
    except Exception as e:                         # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning("今日快報組裝失敗（%s），本次不顯示", e)
        return ""


def home_body(ctxs: dict) -> str:
    sd = ctxs.get("scenario") or {}
    sc = sd.get("scenario")
    if sc is None:
        return _home_body_full(ctxs)
    lab, inf = ctxs.get("labor") or {}, ctxs.get("inflation") or {}
    fom, rates = ctxs.get("fomc") or {}, ctxs.get("rates") or {}
    f_dir = (fom.get("shift") or {}).get("direction", "neutral")
    f_text = {"hawkish": "偏鷹", "dovish": "偏鴿", "neutral": "中性"}.get(f_dir, "資料不足")
    pressure = rates.get("pressure")
    p_level = getattr(pressure, "level", "") if pressure else ""
    from ..analysis.rates import pressure_label as _pl
    p_text, p_tone = _pl(pressure) if pressure else ("資料不足", "neutral")
    lean = LEAN_TEXT.get(sc.lean, "中性")
    labor_label = {"弱": "偏弱", "中": "中性", "強": "偏強"}.get(sc.labor_state, sc.labor_state)
    infl_label = {"低": "偏低", "中": "中性", "高": "偏高"}.get(sc.infl_state, sc.infl_state)

    _nx = _pick_next_trigger(sc)
    trigger = _nx["trigger"]
    if _nx["mode"] == "hold":
        next_name, trigger_text = "傾向原地不動", f"{_nx['reason']}——兩軸都不朝相鄰門檻走"
    else:
        next_name, trigger_text = _next_cell(sc, trigger)
    takeaway, brief_html = _hm_brief(ctxs)
    _mod_strip = "".join(
        f'<span><i class="hm-dot {_TONE_DOT.get(t, "")}"></i>{esc(n)} {esc(v)}</span>'
        for n, v, t in (("就業", labor_label, "dovish" if sc.labor_state == "弱" else "hawkish" if sc.labor_state == "強" else ""),
                        ("通膨", infl_label, "hawkish" if sc.infl_state == "高" else "dovish" if sc.infl_state == "低" else ""),
                        ("聯準會", f_text, f_dir), ("期限溢酬", p_text.replace("水準", ""), p_tone if p_tone != "neutral" else "")))
    asof = inf.get("asof") or {}
    dates = "　·　".join([
        f"就業 {lab.get('data_month', '—')}", f"CPI {(asof.get('cpi') or '—')[:7]}",
        f"PCE {(asof.get('pce') or '—')[:7]}", f"FOMC {fom.get('latest_date', '—')}",
        f"利率 {rates.get('as_of', '—')}"])
    # 下一格距離條已移除（2026-10 使用者：橘線沒有意義）
    # ---- 2026-10-29：「今日市場焦點｜今日總覽」合併卡；01–04 收成六宮格，點了跳視窗 ----
    _chg: dict = {}
    _regime = getattr(sc, "regime", "")
    # 整體情勢三段各加狀態點（跟四大模組同一套顏色）
    for _nm, _tn in (("勞動市場", "dovish" if sc.labor_state == "弱" else "hawkish" if sc.labor_state == "強" else ""),
                     ("通膨", "hawkish" if sc.infl_state == "高" else "dovish" if sc.infl_state == "低" else ""),
                     ("聯準會", f_dir)):
        brief_html = brief_html.replace(f'<div class="hm-br"><b>{_nm}</b>',
                                        f'<div class="hm-br"><b><i class="hm-dot {_TONE_DOT.get(_tn, "")}"></i>{_nm}</b>', 1)
    changes_html = _hm_changes(ctxs.get('changes'), _regime, _chg)
    watch_html = _hm_watch(ctxs, sc)
    s01 = f"""<section class="home-hero hm-hero hm-open hm-in {esc(sc.lean)}" aria-label="今日結論">
    <div class="hm-band">
      <div class="hm-vrow"><h2 id="home-now">就業{esc(labor_label)} × 通膨{esc(infl_label)}</h2>
        <div class="hm-verdict"><b>{esc(sc.name)}</b><span>{esc(lean)}</span></div></div>
      {f'<p class="hm-key">{esc(takeaway)}</p>' if takeaway else ''}
      <a class="hm-next" href="/scenario/"><span>可能下一格</span><b>{esc(next_name)}</b>
        <small>{esc(trigger_text)}</small><em>完整九宮格 →</em></a>
    </div>
    <div class="hm-layer">
      <details class="hm-modx hm-briefx" open><summary><span class="hm-modx-k">整體情勢</span>
        <span class="hm-modx-s"><span>勞動市場・通膨・聯準會</span></span></summary>
      <div class="hm-modx-b">{brief_html}</div></details>
      <details class="hm-modx" open><summary><span class="hm-modx-k">四大模組</span>
        <span class="hm-modx-s hm-ms4">{_mod_strip}</span></summary>
      <div class="hm-modx-b">{_hm_modules(ctxs, sc, f_text, f_dir, p_text, p_level)}</div></details>
    </div>
    {section_learn("/", "home-now")}
  </section>"""
    s02 = f"""<section class="home-zone hm-zone hm-in" aria-label="本期變化">
    <p class="hm-in-sub">跟上一期比，新增或解除的訊號</p>
    <div class="hm-chs">{changes_html}</div>
    {section_learn("/", "home-changes")}
  </section>"""
    s03 = f"""<section class="home-zone hm-zone hm-in" aria-label="接下來看什麼">
    <p class="wv-sw wv-pill"><label for="hm-view-list">列表</label><label for="hm-view-cal">月曆</label></p>
    {watch_html}
    {section_learn("/", "home-next")}
  </section>"""
    s04 = forecasts_section(ctxs.get('_forecasts'), modal=True)
    tiles = _overview_tiles(ctxs, sc, lean, labor_label, infl_label, _nx, _chg)
    overview = _duo(ctxs, extra=[("n01", tiles[0], s01), ("n02", tiles[1], s02),
                                 ("n03", tiles[2], s03), ("n04", tiles[3], s04)])
    focus = _focus_strip(ctxs.get('_focus'), tabbed=True)

    return f"""
<main class="home-dashboard hm">
  {_fx_card(focus, overview)}
  {_story(ctxs)}

  <div class="hm-sign"><span class="hm-sign-gg">GG</span><div><b>MACRO GG</b>
    <span>明天過後，帶你看總經</span></div><small>資料期別　{esc(dates)}</small></div>
</main>"""


def home_footer(ctxs: dict) -> str:
    from ..site import source_footer
    lab, inf, fom = ctxs.get("labor") or {}, ctxs.get("inflation") or {}, ctxs.get("fomc") or {}
    return source_footer(
        [("首頁公債殖利率、歷史與曲線", "美國財政部／FRED 每日殖利率；日期以美國資料日為準", "每日更新 3 次"),
         ("10 年期／30 年期盤中（可選）", "Yahoo 延遲報價；與每日利率分開顯示", "開著頁面每分鐘"),
         ("油價、波動率、道瓊、費半", "Yahoo 延遲報價；部分每日資料由 FRED 提供", "開著頁面每分鐘"),
         ("黃金期貨、美元指數 DXY", "Yahoo 延遲報價；黃金為 GC=F，美元為 DX-Y.NYB", "開著頁面每分鐘"),
         ("台幣 USD/TWD", "Yahoo 延遲匯率／FRED 紐約中午參考匯率；來源與日期見指標", "開著頁面每分鐘"),
         ("台指期", "期交所行情（日盤與夜盤取較新一盤）", "每分鐘"),
         ("升降息機率", "依聯邦基金期貨推算各次會議的利率定價", "每日"),
         ("SOFR、ON RRP、SRF", "紐約聯儲（經 FRED）", "每日"),
         ("今日焦點與補充新聞", "彭博、路透、Yahoo 等；AI 綜合改寫", "每天 3 次"),
         ("期中選舉", "Polymarket 預測市場（下注者看法，不是民調）", "每天 3 次"),
         ("就業、物價、聯準會", f"BLS、BEA、聯準會（就業 {esc(lab.get('data_month', '—'))}・物價 {esc(inf.get('data_month', '—'))}・FOMC {esc(fom.get('latest_date', '—'))}）", "依發布")],
        ["官方日利率變動對前一個有效資料日；盤中報價變動對昨收。1 bp＝0.01 個百分點，1 碼＝25 bp。",
         "SOFR−IORB 轉正代表準備金趨緊；ON RRP 接近零代表縮表開始直接抽銀行準備金；SRF 非零代表有人向央行借急錢；MOVE＝美債版 VIX。",
         "新聞焦點由 AI 整理，附報導來源供查閱；付費內容以公開標題與摘要為依據。",
         "補充新聞依所選指標順序取兩個不同主題；手動更換新聞不會改動指標，下次調整指標時再聯動新聞。",
         "黃金期貨以美元／盎司計；美元指數為 DXY。USD/TWD 是 1 美元兌多少新台幣，上升＝台幣貶值、下降＝升值；FRED 資料為紐約中午買入匯率。",
         "情境判讀綜合就業、通膨與政策資料，詳細依據見情境頁。"],
        head="<b>資料來源</b> FRED、BLS、BEA、DOL、聯準會、公司財報、Polymarket",
        disclaimer="本網站僅為資料整理與情境判讀，不構成投資建議。",
        links='<span><a href="/scenario/">方法與判斷規則</a>｜<a href="/archive/">歷次存檔</a></span>')

def archive_body(entries: list[dict]) -> str:
    if not entries:
        return ('<div class="soonbox"><h3>尚無存檔</h3>'
                '<p>這裡將保留各月份首次發布的報告，'
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
  <p class="hint">每個資料月份保留一份，內容是<b>該月份首次發布時</b>的內容，
    之後的更新仍保留這份版本。因為 BLS 與 BEA 會持續回頭修正歷史數字，
    留下的才是發布當下的原始版本——日後可以回頭查
    「當時我們看到的是什麼」，以及後來被改了多少。</p>
  <ul class="archive-list">{items}</ul>
</div>"""
