"""情境合成頁的內容產生器（P4）。"""

from __future__ import annotations

from ..site import esc
from ..analysis import scenario as scenario_mod
from . import compact_full, focus_evidence, state_chip, teach

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
            # 「目前位置」是唯一需要的徽章。先前還有一個
            # 「結論已依重心修正」——那是舊的事後改寫機制留下的補救說明，
            # 三張格子之後格名本身就是結論，不需要再解釋一次。
            badge = '<div class="sbadge">目前位置</div>' if c["current"] else ""
            cls = " on" if c["current"] else ""
            # 會隨體制改變的三格標一個小記號：其餘六格不管誰優先都一樣，
            # 讀者不必為那六格擔心重心翻轉的風險。
            cls += " conflict" if c.get("conflict") else ""
            # 「停滯性通膨：通膨優先」這種帶冒號的複合名，在 360px 的
            # 一格裡會折成三行，讓整個底列比其他兩列高出兩倍多。
            # 冒號後面是限定語不是主詞，拆成小一級的第二行——
            # 高度降下來，而且「主情境 ＋ 哪一邊優先」的層次反而更清楚。
            _n = c["name"]
            if "：" in _n:
                _head, _qual = _n.split("：", 1)
                name_html = (f'{esc(_head)}'
                             f'<span class="sn-qual">{esc(_qual)}</span>')
            else:
                name_html = esc(_n)
            # 格子裡**只有格名**。逐格的一句說明收在卡尾「九格各代表什麼」，
            # 目前格的說明則以頁首結論卡為主場——先前目前格常駐一段、
            # 其餘八格各藏一個收合，三張頁籤共 24 個收合＋一段跟頁首
            # 一字不差的重複文，正是這張卡「排版混亂」的最大來源。
            rows.append(
                f'<div class="scell {c["lean"]}{cls}">'
                f'<div class="sname">{name_html}</div>'
                f'{badge}</div>'
            )
    return f'<div class="sgrid">{head}{"".join(rows)}</div>'


def _grid_tabs(d: dict, sc) -> tuple[str, str, str]:
    """
    三張九宮格＋切換。純 CSS（radio + 相鄰選擇器），不依賴 JS。

    為什麼要能切換
    --------------
    這一頁最有價值的反事實問題是「如果聯準會的重心翻轉，我這一格會變成什麼」。
    只顯示當前那張的話，讀者看不到答案；三張並排又會讓相同的六格重複三次。
    頁籤讓預設就是目前偵測到的體制，想看別的自己切。

    回傳 (格子區 html, 翻轉對照的收合列標題, 翻轉對照的內容)——
    對照內容不再自帶 details 外框，由卡尾與「重心怎麼判定」併成同一個收合。
    """
    metas = d.get("regime_meta") or []
    grids = d.get("grids") or {}
    if not metas or not grids:
        return _grid(d.get("cells") or []), "", ""

    tabs, panels = [], []
    for i, m in enumerate(metas):
        rid = f"rg-{m['key']}"
        checked = " checked" if m["current"] else ""
        cur_tag = '<span class="rt-now">目前</span>' if m["current"] else ""
        tabs.append(
            f'<input type="radio" name="regime" id="{rid}"{checked}'
            f' class="rtab-in">'
            f'<label for="{rid}" class="rtab">{esc(m["label"])}{cur_tag}</label>')
        # 切到非當前體制時，要提醒這是假設情況，不是現況
        note = ("" if m["current"] else
                f'<div class="rt-hypo">這是<b>假設</b>聯準會改以'
                f'{esc(m["label"])}時的對照，不是目前的判定。</div>')
        panels.append(
            f'<div class="rpanel">{note}'
            f'<p class="hint" style="margin:0 0 12px">'
            f'<b>{esc(m["label"])}的規則：</b>{esc(m["rule"])}</p>'
            f'{_grid(grids[m["key"]])}</div>')

    # 目前這一格在三種體制下分別是什麼——直接回答「翻轉會怎樣」
    cur_row = "".join(
        f'<div class="rcmp{" on" if m["current"] else ""}">'
        f'<div class="rcmp-k">{esc(m["label"])}</div>'
        f'<div class="rcmp-v {m["cell_lean"]}">{esc(m["cell_name"])}</div>'
        f'<div class="rcmp-l">{esc(LEAN_TEXT.get(m["cell_lean"], ""))}</div></div>'
        for m in metas)
    # 這一整段是「反事實」：重心翻轉的話這一格會變成什麼。
    # 它是追問，不是主線——主線是上面那張格子。所以收起來，
    # 但**答案要寫在摺疊列上**，讀者不點開也知道結論是什麼。
    if d.get("cell_is_conflict"):
        # 有差異時，把「會變成什麼」直接寫進摺疊列
        _alt = [m for m in metas if not m["current"]]
        _names = []
        for m in _alt:
            if m["cell_name"] not in _names:
                _names.append(m["cell_name"])
        cmp_head = ("重心若翻轉，這一格會變成"
                    + "或".join(f'「{n}」' for n in _names[:2]))
        cmp_note = ("下面三列是同一格在三種體制下的結論。"
                    "重心是由聲明、投票與記者會判定的，會隨會議改變——"
                    "所以這一格的結論帶著一個額外的風險，要跟數據本身一起盯。")
    else:
        cmp_head = "重心翻轉也不影響這一格"
        cmp_note = ("兩個使命指向同一邊，所以不管誰優先，結論都一樣——"
                    "少一個需要擔心的變數。下面三列可以核對。")

    # 上方三個情境頁籤（純 CSS radio），預設選中目前偵測到的重心，
    # 一次只顯示一張格子。翻轉對照的三列不再自帶收合框——
    # 它跟「重心怎麼判定」是同一個主題，由卡尾併成一個收合。
    grid_html = (f'<div class="rtabs">{"".join(tabs)}'
                 f'<div class="rpanels">{"".join(panels)}</div></div>')
    cmp_body = (f'<p class="hint" style="margin:10px 0 10px">{cmp_note}</p>'
                f'{cur_row}')
    return grid_html, cmp_head, cmp_body


def _cell_gloss(cells) -> str:
    """九格各代表什麼——逐格一句，依格子順序（左上到右下）。"""
    if not cells:
        return ""
    items = []
    for row in cells:
        for c in row:
            mark = "◆" if c.get("conflict") else ""
            cur = "（目前位置）" if c.get("current") else ""
            items.append(
                f'<dt>就業{esc(c["labor"])} × 通膨{esc(c["infl"])}：'
                f'{esc(c["name"])}{mark}{cur}</dt>'
                f'<dd>{esc(c["desc"])}</dd>')
    return ('<details class="f-more"><summary>九格各代表什麼</summary>'
            '<p class="hint" style="margin:10px 0 0">依目前重心的那張格子；'
            '標 ◆ 的三格在其他重心下名稱與結論會不同（切上方頁籤看）。</p>'
            f'<dl class="gloss" style="margin-top:10px">{"".join(items)}</dl>'
            '</details>')


def _triggers(trigs, drift=None) -> str:
    if not trigs:
        return '<div class="empty">資料不足，無法計算觸發距離</div>'
    out = []
    # 相鄰格的條件排前面——那是格子實際會先動到的方向。
    ordered = sorted(trigs, key=lambda x: not getattr(x, "adjacent", True))
    for t in ordered:
        # 兩種標籤回答兩個不同的問題：
        #   下一格＝九宮格的相鄰格（格子會先動到哪）
        #   關鍵　＝政策解鎖條件（在目前的重心下，方向要翻需要它）
        # 先前只有「關鍵」一種，而它可能指向對角另一端，讀者把它當成
        # 下一格就會覺得「跳了兩格」。
        tags = ""
        if getattr(t, "adjacent", True):
            tags += '<span class="tadj">下一格</span>'
        # 跟該軸數據漂移方向一致的門檻標「動能指向」——
        # 「可能下一格」就是從這些條裡挑距離最近的。
        if (drift and getattr(t, "direction", "") and not t.met
                and (drift.get(t.axis) or (None,))[0] == t.direction):
            tags += '<span class="tdir">動能指向</span>'
        if getattr(t, "binding", False):
            tags += '<span class="tbind">關鍵</span>'
        out.append(
            f'<div class="trig{" met" if t.met else ""}">'
            f'<div class="tname">{esc(t.label)}{tags}</div>'
            f'<div class="tdist">{esc("已觸發" if t.met else t.distance)}</div>'
            f'<div class="tnow">目前 {esc(t.current)}　·　{esc(t.threshold)}</div>'
            f"</div>"
        )
    # 這一段是教學不是結論，收進 teach 層——常駐的話會把方法論擺在
    # 門檻列前面（散文稽核也會超標）。
    from . import teach
    out.append(teach(
        "每一條門檻代表九宮格的一種移動：現在的數字離那條線多遠。",
        "「下一格」是相鄰的格子，門檻一到格子就先移過去；「關鍵」是政策"
        "方向真正的解鎖條件——在通膨優先的重心下，就業再弱也要等通膨"
        "回到「低」才換得到降息，所以兩者可能不是同一條。",
        "「動能指向」標在跟當期數據方向一致的門檻上——「可能下一格」"
        "就是從這些條裡挑距離最近的；離得近但方向相反的門檻不會被當成預測。"
        "平常只要盯「關鍵」那條的距離有沒有在縮小。注意口徑：通膨門檻的判定值"
        "是「綜合水準」＝0.6×年增＋0.4×三月年化（轉格要看得夠早，所以把"
        "動能一起計入）；上方格位判定只用年增。兩個數字不同是口徑不同，"
        "不是算錯。"))
    return "".join(out)


PRESSURE_LABEL = {"high": "偏高", "moderate": "中性", "low": "偏低"}


def _rates_line(r: dict | None) -> str:
    """
    長端供給壓力：刻意不併入九宮格，因為它決定的是曲線形狀而非政策方向。

    這裡**只留結論**。先前把長端頁的三個分項（含「每月減持約 37 十億美元
    公債…」這種說明句）整段逐字搬過來，等於同一份拆解在兩頁各印一次；
    從首頁走到這裡的讀者，得先讀完兩段看過的東西才走得到真正的新內容
    （部位對照、市場定價對照）。分項屬於長端頁，這裡給連結就好。
    """
    if not r:
        return ""
    cls = {"high": "hawkish", "low": "dovish"}.get(r["level"], "balanced")
    return f"""
<div class="grid">
  <div class="card">
    <h2 id="curve-pressure" data-sum="供給壓力 {esc(PRESSURE_LABEL.get(r['level'], '—'))}　·　{esc(r['curve_title'])}">長端供給壓力（不進九宮格）</h2>
    <p class="hint">九宮格講<b>政策利率往哪走</b>，這裡講<b>曲線的形狀</b>——
      兩件事，所以分開列。</p>
    <div class="verdict {cls}" style="margin:14px 0 0">
      <div class="v-eyebrow">供給壓力 {esc(PRESSURE_LABEL.get(r['level'], '—'))}　·　綜合分數 {r['score']:+.2f}</div>
      <div class="v-main">{esc(r['curve_title'])}</div>
      <div class="v-why">{esc(r['curve_desc'])}</div>
      <div class="v-count">{esc(r['desc'])}</div>
    </div>
    <div class="src">三項分數的逐項拆解與債務動態見
      <a href="/rates/#priced">長端與債務</a>頁。</div>
  </div>
</div>
"""


# 各頁結論卡上那句話的用詞，用來在對照時原樣引用
_TILT_LABEL = {"hawkish": "利升息", "dovish": "利降息",
               "balanced": "本期方向不明"}
# 哪些組合會讓讀者覺得「這兩頁在打架」
_MISMATCH = {("高", "balanced"), ("高", "dovish"),
             ("低", "balanced"), ("低", "hawkish"),
             ("弱", "balanced"), ("弱", "hawkish"),
             ("強", "balanced"), ("強", "dovish")}


def _mismatch_note(axis: str, state: str, tilt: str | None,
                   net, level_desc: str) -> str:
    """
    「為什麼那一頁寫 A、這裡卻是 B」。

    這是整個說明區真正要解決的問題。讀者在通膨頁看到「本期方向不明」、
    翻到這裡看到「通膨高」，直覺結論是網站在自打嘴巴——但兩者問的
    根本不是同一件事：一個是**本期新訊號把政策往哪推**，
    一個是**水準離目標多遠**。卡在高檔但這個月沒有新推力，
    兩者完全可以同時成立。

    只在真的會被誤讀的組合上印（見 _MISMATCH），同向時不印。
    """
    if not tilt or (state, tilt) not in _MISMATCH:
        return ""
    page = "通膨" if axis == "通膨" else "勞動市場"
    return ('<div class="wx-note"><b>為什麼' + page + "頁寫「" + axis + "面："
            + _TILT_LABEL.get(tilt, tilt) + "」、這裡卻是「" + esc(state)
            + "」</b>：兩者問的不是同一件事。"
            + page + "頁的結論看的是<b>本期新訊號的方向</b>（旗標鷹鴿淨值 "
            + esc(str(net if net is not None else "—"))
            + "）；這一軸看的是<b>水準</b>——" + level_desc
            + "。水準已經在那裡，但這個月沒有新的推力，兩者可以同時成立。</div>")


def _axis_head(axis: str, state: str, lead: str) -> str:
    """
    一條軸的常駐標題列：軸名 ＋ 判定 ＋ 一句話理由，右邊一個展開箭頭。

    為什麼結論不能收合：先前整塊算式包在一個 12.5px 灰色的展開列裡，
    而那一列跟旁邊的圖例說明長得一模一樣（同字級、同顏色、同位置），
    讀者掃過去只會把它歸類成註腳——等於做了跟沒做一樣。
    讀者要的答案是「為什麼是弱／高」，那句話必須永遠看得到；
    收合的應該是**算式**，那才是只有要驗算的人才需要的東西。
    """
    return ('<details class="ax"><summary>'
            f'<span class="ax-k">{esc(axis)}</span>'
            f'<span class="ax-v">{esc(state)}</span>'
            f'<span class="ax-lead">{esc(lead)}</span>'
            "</summary>"
            '<div class="ax-body">')


def _why_axes(w: dict) -> str:
    """
    「為什麼落在這一格」——兩條軸的算式、輸入值與門檻出處。

    這一塊解決的是一個**看起來像 bug 的東西**：讀者在通膨頁看到
    「通膨面：方向不明」，翻到情境頁看到「通膨高」，直覺結論是網站在自打嘴巴。
    實際上兩者問的不是同一件事——一個是本期新訊號的**方向**，
    一個是核心 PCE 的**水準**。兩件事必須擺在同一個畫面上對照著講，
    分開講讀者不會自己接起來。

    格式刻意做成「算式」而不是散文：讀者要能自己驗算，
    尤其是門檻——那是整頁權重最大、先前卻完全沒有交代的東西。
    """
    if not w:
        return ""
    inf, lab = w.get("inflation"), w.get("labor")
    # 就業排前面：九宮格的列是就業、欄是通膨，全站的講法也一律是
    # 「就業弱 × 通膨高」。這裡反過來會讓讀者的視線跟格子對不上。
    blocks = []
    order = []

    if inf:
        rows = "".join(
            '<div class="wx-r"><span class="wx-k">' + esc(r["label"])
            + '</span><span class="wx-w">' + esc(r["w"])
            + '</span><span class="wx-v">' + esc(r["value"]) + "</span></div>"
            for r in inf["rows"])
        state = inf["state"]
        if state == "高":
            cmp_txt, thr, src = "＞", esc(inf["high"]), inf["high_src"]
        elif state == "低":
            cmp_txt, thr, src = "＜", esc(inf["low"]), inf["low_src"]
        else:
            cmp_txt = "落在"
            thr = esc(inf["low"]) + " ～ " + esc(inf["high"])
            src = inf["low_src"] + "；" + inf["high_src"]
        warn = "" if inf["auto"] else "　⚠️ 本次沒有取得 FOMC 預測序列，用的是後備值"

        # 方向與水準的對照。這一段是整塊的重點，但只在兩者**看起來打架**時才出現：
        # 水準高而本期方向偏鴿或不明、水準低而本期方向偏鷹或不明。
        # 兩者同向時這段話是廢話，天天印只會被跳過。
        tilt_note = _mismatch_note(
            "通膨", state, inf.get("tilt"), inf.get("tilt_net"),
            "離 2% 目標多遠")

        blocks.append(
            _axis_head("通膨", state, inf.get("lead", "")) + rows
            + '<div class="wx-r wx-sum"><span class="wx-k">格位判定值</span>'
            '<span class="wx-w"></span><span class="wx-v">'
            + esc(inf["level"]) + "</span></div>"
            + '<div class="wx-thr">' + esc(inf["level"]) + "　" + cmp_txt
            + "　門檻 " + thr + "</div>"
            + '<div class="wx-src">門檻出處：' + esc(src) + warn + "</div>"
            # 推估說明放在展開之後、門檻出處旁邊——它跟門檻出處是同一類東西
            #（「這個數字怎麼來的」），不該擠進第一眼那一句。
            + ('<div class="wx-src">' + esc(inf["note"]) + "</div>"
               if inf.get("note") else "")
            + tilt_note + "</div></details>")
        order.append(("inflation", blocks.pop()))

    if lab:
        rows = "".join(
            '<div class="wx-r"><span class="wx-k">' + esc(r["label"])
            + '</span><span class="wx-w">' + esc(r["w"])
            + '</span><span class="wx-v">' + esc(r["value"]) + "</span></div>"
            for r in lab.get("rows") or [])
        basis_txt = {
            "level": "由<b>水準</b>定案：失業率相對 FOMC 自己對長期失業率的判斷；",
            "sahm": "由 <b>Sahm 法則</b>定案（門檻出自原始論文，不是本站選的）；",
            "breakeven": "水準上不算弱，但<b>三月均非農低於損益兩平</b>——"
                         "就業增速已經撐不住目前的失業率，所以往「弱」推一格；",
            "fallback": "⚠️ 沒有取得 FOMC 的長期失業率預測，改用後備規則；",
        }.get(lab.get("basis"), "")
        blocks.append(
            _axis_head("就業", lab["state"], lab.get("lead", "")) + rows
            + '<div class="wx-src" style="margin-top:8px">' + basis_txt
            + "三條依據都是外部標準：FOMC 的長期失業率判斷（中央趨勢的寬度就是"
            "委員彼此的分歧程度）、Sahm 法則的 0.50、以及由人口成長推導出來的"
            "損益兩平。前兩者是外部標準；損益兩平的 12 個月回看期與不確定性"
            "容差是本站的方法選擇，已在就業頁揭露。損益兩平與其他月頻指標只判斷"
            "移動方向，不會改寫當前格位。</div>"
            + _mismatch_note("就業", lab["state"], lab.get("tilt"),
                             lab.get("net"), "失業率離充分就業多遠")
            + "</div></details>")
        order.append(("labor", blocks.pop()))

    seq = dict(order)
    return ('<div class="axg">'
            + "".join(seq[k] for k in ("labor", "inflation") if k in seq)
            + "</div>")


def _four_steps(d: dict, sc, focus: dict) -> str:
    """
    「這一格是怎麼算出來的」——固定四步，每步一行、行末就是結果。

    先前這條計算鏈散在四個地方（hero 的邏輯條、兩條軸的算式、門檻出處、
    重心說明），讀者要自己拼。其實它只有四步，值得用一張固定結構的卡
    一次講完；細節（權重理由、門檻出處、推估方法）收在下方的算式層。
    """
    w = d.get("why") or {}
    lab, inf = w.get("labor") or {}, w.get("inflation") or {}
    rows = []
    if lab.get("lead"):
        rows.append(("① 就業格位", lab["lead"], lab.get("state", "")))
    if inf.get("lead"):
        # lead 可能帶著推估的長註，四步卡只留第一句；完整版在算式層
        rows.append(("② 通膨格位", inf["lead"].split("。")[0], inf.get("state", "")))
    if focus.get("label"):
        rows.append(("③ 目前重心", focus.get("note", "").split("。")[0] or "由聲明、反對票與記者會判定",
                     focus["label"]))
    rows.append(("④ 交叉定位",
                 f"就業{sc.labor_state} × 通膨{sc.infl_state}，在{focus.get('label', '目前重心')}下",
                 sc.name))
    body = "".join(
        f'<div class="step"><span class="step-k">{esc(k)}</span>'
        f'<span class="step-t">{esc(txt)}</span>'
        f'<span class="step-r">{esc(res)}</span></div>'
        for k, txt, res in rows)

    # ②的 PCE 推估不在這裡呈現——它併進卡尾「完整算式與門檻出處」收合
    # （見 _nc_bits），推估值仍寫在那個收合的標題列上。
    # teach 也不放在這裡——它屬於整張「九宮格定位」卡的卡尾。
    return f'<div class="steps">{body}</div>'


def _nc_bits(d: dict) -> tuple[str, str]:
    """
    ②步的 PCE 推估。回傳 (收合列的後綴, 展開層的內容區塊)。

    PCE 還沒公布時，通膨水準用的是推估值——推估怎麼算、為什麼選這個方法，
    屬於「格子怎麼算」的細節，所以併進「完整算式與門檻出處」那一個收合，
    不再自成一個（一張卡近 30 個收合正是先前混亂的來源）。
    推估值本身寫在收合列上，不點開也看得到。
    """
    nc = d.get("pce_nowcast") or {}
    if not (nc.get("estimated") and nc.get("value") is not None):
        return "", ""
    _mc, _mg = nc.get("mae_components"), nc.get("mae_gap")
    # 標題列只放短名（放全稱會變成「（差距法（核心 CPI − …））」的
    # 雙層括號）；全稱寫在展開後的第一句。
    method_short = ("成分法" if nc.get("method") == "components" else "差距法")
    method_full = ("成分法＝CPI＋PPI 逐項加權"
                   if nc.get("method") == "components"
                   else "差距法＝核心 CPI 減去兩者的歷史平均差距")
    comp_rows = "".join(
        f'<tr><td>{esc(c["label"])}{"（用最新一期頂上）" if c.get("lagged") else ""}</td>'
        f'<td>{c["weight"]:.1f}%</td>'
        f'<td>{c["yoy"]:+.2f}%</td></tr>'
        for c in (nc.get("components") or []) if c.get("yoy") is not None)
    comp_tbl = (f'<table style="margin-top:8px"><thead><tr><th>成分</th>'
                f'<th>權重</th><th>年增</th></tr></thead>'
                f'<tbody>{comp_rows}</tbody></table>' if comp_rows else "")
    _ncv = f'{nc["value"]:.2f}%'
    suffix = f'；含核心 PCE 推估 {_ncv}（{method_short}）'
    detail = f"""<div class="f-detail" style="margin-bottom:10px">
        <b>②的通膨水準是推估值</b>：本期採用<b>{esc(method_full)}</b>。
        PCE 比 CPI 晚兩週公布，空窗期用 CPI 與 PPI 先推——
        PCE 的醫療與金融服務項本來就取自 PPI，所以推得出來。
        兩種方法各自回測近 {nc.get("n_backtest") or "—"} 期、比較平均誤差，
        <b>本期採誤差較小的那個</b>：成分法 {esc(f"±{_mc:.3f}" if _mc is not None else "不可用")}、
        差距法 {esc(f"±{_mg:.3f}" if _mg is not None else "不可用")} 個百分點。
        方法的選擇是規則決定的，每次執行可重現。PCE 一公布就換回實際值。
        {comp_tbl}
      </div>"""
    return suffix, detail


def _scenario_body_full(d: dict) -> str:
    sc = d["scenario"]
    _why_html = _why_axes(d.get("why") or {})

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
    # 部位對照表現在直接對應「目前這張格子的那一格」，
    # 不會再出現「標題寫降息受阻、表格擺存續期間偏長」這種打架，
    # 所以先前那段落差說明整段刪掉。

    # 就業格位不是靠分數、而是靠旗標淨值定案時要講出來——
    # 否則門檻表裡沒有任何一條達標，讀者會以為算錯了。
    basis_note = (f'<div class="warnbox" style="margin:0 0 14px">'
                  f'{esc(sc.labor_basis_note)}</div>'
                  if getattr(sc, "labor_basis_note", "") else "")

    # 只有真的有某一軸被標成「關鍵」時才解釋這個標記——
    # 「兩邊並重」與「無法判定」時沒有任何一條會被標，
    # 這時還寫「標關鍵的那一軸…」等於叫讀者去找不存在的東西。
    has_binding = any(getattr(t, "binding", False) for t in sc.triggers)
    binding_hint = (
        "標「關鍵」的那一軸是目前的約束條件；另一軸就算觸發，"
        "在現在的重心下也不會單獨改變政策方向。"
        if has_binding else
        "目前聯準會沒有明顯偏向任何一邊，兩軸都可能主導——"
        "哪一邊先觸發，哪一邊就會決定方向。")

    fomc_note = (f'<div class="v-why" style="margin-top:14px">{esc(sc.fomc_note)}</div>'
                 if sc.fomc_note else "")

    grid_html, cmp_head, cmp_body = _grid_tabs(d, sc)
    nc_suffix, nc_detail = _nc_bits(d)

    # 收合摘要：一律取這一區已經算出來的結論。
    _grid_sum = (f'就業{sc.labor_state} × 通膨{sc.infl_state}　·　{sc.name}'
                 f'　·　{LEAN_TEXT.get(sc.lean, "")}')
    # drivers 的元素長得像「勞動｜失業率下降源於…」，模組名在收合列上是雜訊，
    # 只取分隔線後面的標題。
    _d0 = (sc.drivers[0].split("｜")[-1] if sc.drivers else "")
    _drv_sum = (f'{len(sc.drivers)} 項　·　{_d0}' if sc.drivers else "尚無資料")
    _met = [x for x in sc.triggers if x.met]
    _bind = next((x for x in sc.triggers if getattr(x, "binding", False)), None)
    _trig_sum = (f'{len(_met)} 項已觸發' if _met else
                 (f'關鍵：{_bind.label}　·　{_bind.distance}' if _bind else
                  (f'{len(sc.triggers)} 項門檻與距離' if sc.triggers else "資料不足")))
    _pos_sum = (f'{sc.name} 對應的四類部位' if sc.positioning else "尚無資料")
    _mk = d.get("market") or {}
    _mkt_sum = ((f'差距 {_mk["display"]}　·　'
                 + ("與本頁判讀一致" if _mk.get("agree") else "與本頁判讀分歧"))
                if _mk else "資料不足")

    # 市場定價：用 2 年期殖利率相對政策利率中值當代理。
    # 這不是會議層級的機率，但它回答了本頁真正在問的問題——
    # 「我的判讀跟市場定價差在哪」。
    mk = d.get("market") or {}
    if mk:
        _agree = ("目前**一致**：兩邊都指向同一個方向。一致不代表沒有機會，"
                  "但代表這個判讀已經反映在價格裡了。"
                  if mk["agree"] else
                  "目前**分歧**：這正是值得追的地方。要嘛市場還沒反映最新的會議，"
                  "要嘛判讀漏看了市場看到的東西。")
        _agree_html = "".join(
            (f"<b>{esc(s)}</b>" if i % 2 else esc(s))
            for i, s in enumerate(_agree.split("**")))
        _cls = {"hawkish": "hawkish", "dovish": "dovish"}.get(mk["lean"], "neutral")
        _ag_short = ("兩邊指向同一個方向，這個判讀已經反映在價格裡"
                     if mk["agree"] else
                     "兩邊分歧——不是市場之後要修正，就是判讀漏看了市場看到的東西")
        market_html = f"""<div class="impact {_cls}">{esc(mk['text'])}。{esc(_ag_short)}。</div>
    <div class="stat-row" style="margin-top:14px">
      <div class="stat"><div class="s-label">市場定價的政策路徑</div>
        <div class="s-value">{mk['display']}</div>
        <div class="s-note">2 年期公債殖利率減政策利率中值</div></div>
      <div class="stat"><div class="s-label">本頁判讀</div>
        <div class="s-value" style="font-size:17px">{esc(LEAN_TEXT.get(sc.lean, '—'))}</div>
        <div class="s-note">目前這張九宮格給出的方向</div></div>
    </div>
    {teach(
        "債券市場用真金白銀押出來的政策方向，跟本頁九宮格的判讀並排對照。",
        "兩者常常不一致——那個落差本身就是資訊：不是市場之後要修正定價，就是聯準會要改口。",
        "這裡用 2 年期殖利率減政策利率當代理，是粗略估計、不是會議層級的機率，差距小於 0.15 個百分點時不要過度解讀。")}
    <details class="f-more"><summary>一致／分歧各代表什麼</summary>
      <div class="f-detail">{_agree_html}</div></details>"""
    else:
        market_html = ('<div class="soonbox" style="margin-top:0;padding:26px 18px;'
                       'box-shadow:none;border-style:dashed"><h3>資料不足</h3>'
                       '<p>需要 2 年期公債殖利率與目前的政策利率區間，'
                       '目前缺其中一項。</p></div>')

    # ---- 反應函數：聯準會目前把哪一邊擺在前面 ----
    # 先前這裡有一個「目前重心」大 verdict 框——資訊與頁首結論卡、
    # 四步的③步、頁籤上方的規則行三重重複，整個刪除。
    # 「判定依據」與「重心若翻轉會怎樣」是同一個主題，併成卡尾一個收合，
    # 翻轉的答案仍寫在收合列上。
    focus = sc.focus or {}
    _fc_parts = []
    if focus.get("evidence"):
        # 只留這一次真正的判定依據。「來源為聲明制式句與投票紀錄，不用模型」
        # 是方法論、每一期都一樣，已經寫在頁尾的判讀說明裡。
        _fc_parts.append('<div class="f-detail"><b>本期判定依據</b>：'
                         + esc("、".join(focus["evidence"])) + '</div>')
    if cmp_body:
        _fc_parts.append(cmp_body)
    _fc_sum = "重心怎麼判定" + (f"；{cmp_head}" if cmp_head else "")
    focus_collapse = (f'<details class="f-more"><summary>{esc(_fc_sum)}</summary>'
                      + "".join(_fc_parts) + '</details>') if _fc_parts else ""
    # 判不出重心時要明講：訊號互相抵銷 ≠ 聯準會真的兩邊並重。
    # 降成四步下方的一行警語（原本佔著大框的一角）。
    assumed_note = ""
    if getattr(sc, "regime_assumed", False):
        assumed_note = ('<div class="caveat"><b>本次判不出重心</b>——'
                        '聲明、投票與記者會的訊號互相抵銷，也沒有明確說'
                        '「兩邊風險大致平衡」。下面暫用「兩邊並重」那一張對照，'
                        '但那是<b>不知道</b>，不是<b>真的並重</b>，判讀時要打折。</div>')

    return f"""
<div class="verdict {sc.lean}">
  <div class="v-eyebrow">{esc(d['as_of'])}　·　目前情境</div>
  <div class="v-main">{esc(sc.name)}</div>
  <div class="v-why">{esc(sc.description)}</div>
  {fomc_note}
  <div class="v-count">
    定位：就業{esc(sc.labor_state)}　×　通膨{esc(sc.infl_state)}　·
    政策傾向 {esc(LEAN_TEXT.get(sc.lean, ''))}<br>
    這裡刻意不給機率。機率市場早就定價了，有價值的是「我的判讀跟市場定價差在哪」。
  </div>
  {incomplete}
</div>

<div class="grid">
  <div class="card">
    <h2 id="grid" data-open="1" data-sum="{esc(_grid_sum)}">九宮格定位</h2>
    <p class="hint">就業 × 通膨。格子由下方四步算出，門檻全部錨在外部標準；
      目前格的完整說明見頁首結論卡。</p>
    {_four_steps(d, sc, focus)}
    {assumed_note}
    {grid_html}
    <p class="hint" style="margin-top:16px">
      <span class="lg-on">反白粗框</span>＝目前位置　·
      <span class="cflag">◆</span>＝會隨重心改變的三格（其餘六格三種體制都一樣）
    </p>
    {teach(
        "格子的位置不是主觀判斷，是四步固定的計算：兩條軸各對照一個外部門檻、判定重心、再交叉。",
        "看得懂這四步，你就能在數據公布的當下自己推出格子會不會動——不用等任何人的解讀。門檻全部錨在外部標準（FOMC 自己的預測），不是本站選的數字。",
        "每一步的細節（權重、門檻出處、PCE 推估方法）都在下方「完整算式」裡，數字全部可以驗算。口徑提醒：②的格位只用**年增率**判；下方「情境轉換門檻」的通膨判定值是綜合水準（0.6×年增＋0.4×三月年化），所以兩處的數字會不一樣——口徑不同，不是算錯。")}
    <details class="f-more" style="margin-top:14px"><summary>完整算式與門檻出處（可驗算）{esc(nc_suffix)}</summary>
      {nc_detail}
      {_why_html}
    </details>
    {focus_collapse}
    {_cell_gloss(d.get('cells'))}
  </div>
</div>
<div class="grid g2">
  <div class="card">
    <h2 id="drivers" data-sum="{esc(_drv_sum)}">主要驅動因素</h2>
    <p class="hint">依嚴重度排序。</p>
    {drivers_html or '<div class="empty">尚無資料</div>'}
    <p class="hint" style="margin:12px 0 0">每一條的完整依據在來源頁：
      <a href="/labor/#signals">勞動市場的本期關鍵訊號</a>　·
      <a href="/inflation/#signals">通膨的本期關鍵訊號</a></p>
  </div>

  <div class="card">
    <h2 id="triggers" data-sum="{esc(_trig_sum)}">情境轉換門檻</h2>
    <p class="hint">{binding_hint}</p>
    {basis_note}
    {_triggers(sc.triggers, sc.drift)}
  </div>
</div>

<div class="grid g2">
  <div class="card">
    <h2 id="positioning" data-sum="{esc(_pos_sum)}">固定收益部位對照</h2>
    <p class="hint">方向性參考，不是進出場訊號。</p>
    <dl class="poslist">{pos_rows or '<dt>尚無資料</dt><dd>—</dd>'}</dl>
  </div>

  <div class="card">
    <h2 id="market" data-sum="{esc(_mkt_sum)}">市場定價對照</h2>
    <p class="hint">自己的判讀與市場定價差在哪。</p>
    {market_html}
  </div>
</div>

{_rates_line(d.get('rates_line'))}
<div class="grid">
  <div class="card">
    <h2 id="howto" data-sum="三張格子的規則、重心怎麼判定、格子怎麼移動">判讀說明</h2>
    <p class="hint">這一頁的規則書：三張格子怎麼來、重心怎麼判、格子怎麼移。
      內容不隨數據變動，<b>看過一次就夠</b>——所以預設收起來。</p>
    <details class="f-more"><summary>展開完整說明（七個問答）</summary>
        <dl class="gloss">
      <dt>為什麼有三張九宮格</dt>
      <dd>聯準會有兩個使命，而它們有時指向相反的方向——就業弱要降息、
        通膨高不能降。誰優先，結論就完全不同。所以三種體制各一張格子，
        由聲明、投票與記者會判定目前適用哪一張。<br>
        九格裡只有三格會隨體制改變（標◆那三格），
        其餘六格兩個使命同向或都不極端，不管誰優先都一樣。</dd>
      <dt>四個角各是什麼意思</dt>
      <dd>左下角（就業弱、通膨低）是降息最順的情況——兩個使命指向同一邊。
        右下角（就業弱、通膨高）是停滯性通膨，兩個目標互相打架，
        聯準會最難處理，也是三張格子差最多的那一格。
        上排（就業強）不論通膨高低都不急著降息，差別只在要不要往緊縮走。</dd>
      <dt>為什麼不給機率</dt>
      <dd>機率市場早就定價了，複述它沒有附加價值。有價值的是指出
        「我算出來偏鴿，但市場定價偏鷹」這類具體的分歧，以及明確的門檻
        與目前的距離——那比較誠實，也更能直接拿來盯。</dd>
      <dt>重心怎麼判定</dt>
      <dd>聲明裡的制式風險句（±2）、聲明對現況的描述
        （±1，「通膨仍高於目標」／「勞動市場已轉弱」，講現況不是講風險，弱一級）、
        反對票的方向與張數（±1～2）、
        記者會裡的明確表態（±1，權重刻意低一級，因為那是即席發言，
        而且逐字稿會後數日才發布、不是每次都抓得到）。
        每一條加分項都有方向相反的對應項，兩側對稱——
        不對稱會變成常數偏誤（「通膨仍偏高」幾乎每次都在）。
        全部是固定的片語比對，不用模型，每次執行結果一致。</dd>
      <dt>格子會怎麼移動</dt>
      <dd>通常是一次移動一格，而且往往是通膨先動、就業後動。
        跳格（例如從「按兵不動」直接到「衰退式降息」）多半發生在有外生衝擊時。</dd>
      <dt>長端為什麼不進九宮格</dt>
      <dd>九宮格回答的是「聯準會會不會動、往哪動」，那是政策利率。
        30 年期殖利率還受債券供給、財政狀況與期限溢酬影響，並非只由政策利率決定。
        把兩者合成一個分數，會讓「降息但長端不降」這種最關鍵的組合消失，
        所以它獨立列在上方。</dd>
      <dt>文本的角色</dt>
      <dd>聯準會的客觀訊號（政策行動、反對票、聲明裡的風險用語）用來校準，
        不是決定格子的位置。這裡刻意不採用措辭語氣分數——語氣會隨主席文風
        改變，主席換人時分數會整段位移，不能用來加減信心。
        當客觀訊號與數據方向不一致時，通常代表官員看到了數據還沒反映的東西，
        或反過來——他們還沒承認數據已經轉向。</dd>
    </dl>
    </details>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="glossary" data-sum="這一頁出現的專有名詞">名詞解釋</h2>
        <dl class="gloss">
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
    </dl>
  </div>
</div>
"""


def scenario_body(d: dict) -> str:
    """總覽的核心：九宮格、移動方向、政策傾向與下一個觸發同屏。"""
    sc = d["scenario"]
    lean = LEAN_TEXT.get(sc.lean, "中性")
    labor_text = {"弱": "偏弱", "中": "中性", "強": "偏強"}.get(sc.labor_state, sc.labor_state)
    infl_text = {"低": "偏低", "中": "中性", "高": "偏高"}.get(sc.infl_state, sc.infl_state)
    desc = (sc.description or "").split("。")[0]
    regime = next((m["label"] for m in d.get("regime_meta", []) if m.get("current")), "兩邊並重")
    # 「下一個轉格條件」用共用的 pick_next（analysis.scenario）：
    # 方向優先、距離其次——只挑跟數據漂移方向一致的相鄰門檻；
    # 兩軸都不朝相鄰門檻時誠實寫「傾向不動」。首頁同一個函式。
    _nx = scenario_mod.pick_next(sc)
    trig, _unlock = _nx["trigger"], _nx["unlock"]
    if _nx["mode"] == "hold":
        trigger_text = (f"短期傾向原地不動（{_nx['reason']}）"
                        + (f"；參考門檻：{trig.label}：{trig.distance}" if trig else ""))
    elif trig:
        trigger_text = f"{trig.label}：{trig.distance}"
        if _nx["mode"] == "directional" and _nx.get("reason"):
            trigger_text += f"（依據：{_nx['reason']}）"
    else:
        trigger_text = "目前沒有可計算門檻"
    unlock_text = (f"{_unlock.label}：{_unlock.distance}" if _unlock else "")
    metrics = "".join([
        state_chip("就業格位", sc.labor_state, f"方向 {sc.labor_momentum}",
                   "dovish" if sc.labor_state == "弱" else "hawkish" if sc.labor_state == "強" else "neutral"),
        state_chip("通膨格位", sc.infl_state, f"方向 {sc.infl_momentum}",
                   "hawkish" if sc.infl_state == "高" else "dovish" if sc.infl_state == "低" else "neutral"),
        state_chip("政策傾向", lean, sc.name,
                   "hawkish" if sc.lean == "hawkish" else "dovish" if sc.lean == "dovish" else "neutral"),
        state_chip("FOMC 反應體制", regime, "只改政策解讀，不改兩軸資料"),
    ])
    rates = d.get("rates_line") or {}
    # title 本身就是「長端供給壓力：偏高」的完整句，前面不能再冠一次
    # 「長端供給壓力：」——先前畫面出現「長端供給壓力：長端供給壓力：偏高」。
    overlay = (f"{rates.get('title', '長端供給壓力：資料不足')}；{rates.get('curve_title', '')}"
               if rates else "長端供給資料不足")
    logic = (f'<div class="logic-strip"><div class="logic-step"><b>當前位置</b>'
             f'<span>就業 {sc.labor_state} × 通膨 {sc.infl_state}＝{esc(sc.name)}</span></div>'
             f'<div class="logic-step"><b>下一個轉格條件</b><span>{esc(trigger_text)}</span></div>'
             + (f'<div class="logic-step"><b>政策解鎖條件</b><span>{esc(unlock_text)}</span></div>'
                if unlock_text else "")
             + f'<div class="logic-step"><b>格外覆蓋層</b><span>{esc(overlay)}</span></div></div>')
    logic = focus_evidence(logic)
    notes = (f'<div class="data-line"><span class="data-tag">{esc(d.get("as_of", "—"))}</span>'
             '<span class="data-tag">格位＝水準；箭頭＝動能；兩者不得混算</span>'
             '<span class="data-tag">PPI、財政、AI 發債不直接移格</span></div>')
    hero = (f'<div class="grid"><div class="card focus-card"><div class="focus-eyebrow">Macro regime</div>'
            f'<h2 class="focus-title">就業{labor_text} × 通膨{infl_text}</h2><p class="focus-sub">{esc(sc.name)}｜{lean}。{esc(desc)}。</p>'
            f'<div class="focus-grid">{metrics}</div>{logic}{notes}</div></div>')
    return hero + compact_full(_scenario_body_full(d), "九宮格依據、部位與完整方法")


def scenario_footer(d: dict) -> str:
    return (
        "情境分類由固定規則產生：失業率相對 FOMC 長期區間決定就業格位，"
        "核心 PCE 年增決定通膨格位；短期指標只決定移動方向。聯準會的重心"
        "（聲明制式句、反對票、記者會表態）"
        "決定用哪一張九宮格。全部是確定性規則，不含模型生成內容。<br>"
        "長端供給壓力另行計算，不併入九宮格——它影響的是曲線形狀，不是政策方向。<br>"
        "本頁僅為分析框架，不構成投資建議。"
    )
