"""情境合成頁的內容產生器（P4）。"""

from __future__ import annotations

import re

from ..site import esc
from ..analysis import scenario as scenario_mod
from . import compact_full, focus_evidence, state_chip, teach

LEAN_TEXT = {"dovish": "利降息", "hawkish": "利升息", "neutral": "中性"}


def _grid(cells, heads: dict | None = None, hypo: bool = False) -> str:
    """
    九宮格（2026-10 第二版，使用者：「太醜、太多顏色、太多字」）。

    只用一個強調色：目前那一格實心深底；相鄰格白底細框（下一步可能去的地方）；
    其餘淡灰。格子裡只放格名，門檻寫進欄列標題，讀者不必再讀兩段準則說明。
    """
    heads = heads or {}
    cur = next(((i, j) for i, row in enumerate(cells) for j, c in enumerate(row)
                if c.get("current")), None)
    out = ['<div class="sx-gk"><span>就業</span><span>通膨</span></div>']
    for j, k in enumerate(("低", "中", "高")):
        on = " cur" if cur and cur[1] == j else ""
        out.append(f'<div class="sx-gh{on}"><b>{k}</b><small>{esc(heads.get("i" + k, ""))}</small></div>')
    for i, row in enumerate(cells):
        lab = row[0]["labor"]
        on = " cur" if cur and cur[0] == i else ""
        out.append(f'<div class="sx-gr{on}"><b>{esc(lab)}</b><small>{esc(heads.get("l" + lab, ""))}</small></div>')
        for j, c in enumerate(row):
            if c["current"]:
                cls = "cur"
            elif cur and abs(i - cur[0]) + abs(j - cur[1]) == 1:
                cls = "adj"
            else:
                cls = "far"
            n = c["name"]
            head, qual = (n.split("：", 1) + [""])[:2]
            tag = (f'<span class="sx-gt">{"假設" if hypo else "目前"}　{esc(LEAN_TEXT.get(c["lean"], ""))}</span>'
                   if c["current"] else "")
            out.append(f'<div class="sx-gx {cls}"><span class="sx-gn">{esc(head)}</span>'
                       + (f'<span class="sx-gq">{esc(qual)}</span>' if qual else "")
                       + f'{tag}</div>')
    return f'<div class="sx-g">{"".join(out)}</div>'


def _grid_heads(d: dict) -> dict:
    """欄列標題上的門檻：通膨看核心 PCE 年增、就業看失業率。"""
    w = d.get("why") or {}
    inf, lab = w.get("inflation") or {}, w.get("labor") or {}
    h = {}
    lo, hi = inf.get("low"), inf.get("high")
    if lo and hi:
        h.update({"i低": f"＜{lo}", "i中": f"{lo[:-1]}–{hi}", "i高": f"＞{hi}"})
    band = next((r["value"] for r in lab.get("rows") or [] if r["label"].startswith("FOMC 長期失業率")), "")
    m = re.match(r"([\d.]+)–([\d.]+)%", band or "")
    if m:
        h.update({"l強": f"＜{m.group(1)}%", "l中": band, "l弱": f"＞{m.group(2)}%"})
    return h


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
        return _grid(d.get("cells") or [], _grid_heads(d)), "", ""

    tabs, panels = [], []
    heads = _grid_heads(d)
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
                f'<div class="rt-hypo">假設聯準會改以{esc(m["label"])}：{esc(m["rule"])}</div>')
        panels.append(f'<div class="rpanel">{note}{_grid(grids[m["key"]], heads, not m["current"])}</div>')

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
        cmp_head = ("重心翻轉時：變成"
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
    grid_html = (f'<div class="rtabs sx-tabs"><span class="sx-tabs-k">聯準會重心</span>{"".join(tabs)}'
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


def _why_axes(w: dict, nc: dict | None = None) -> str:
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
            # 推估的完整計算放在這裡——點開「通膨」就要看得到 3.14% 怎麼來，
            # 不必再去別的地方找（使用者實測回報過找不到）。
            + _nc_calc(nc or {})
            + tilt_note + "</div></details>")
        order.append(("inflation", blocks.pop()))

    if lab:
        rows = "".join(
            '<div class="wx-r"><span class="wx-k">' + esc(r["label"])
            + '</span><span class="wx-w">' + esc(r["w"])
            + '</span><span class="wx-v">' + esc(r["value"]) + "</span></div>"
            for r in lab.get("rows") or [])
        # 說明壓到兩行：定案依據一行＋門檻出處一行。先前還有一段約 110 字
        # 的方法論（回看期、容差、誰不改寫格位…），那些在就業頁已完整揭露，
        # 這裡逐字重印只是把算式擠到讀者找不到（使用者的原話：太冗長）。
        basis_txt = {
            "level": "由<b>水準</b>定案：失業率相對 FOMC 的長期失業率判斷。",
            "job_losers": "由<b>水準</b>定案後，因<b>失去工作者比重警戒</b>往弱推一格。",
            "fallback": "⚠️ 沒有取得 FOMC 的長期失業率預測，改用後備規則。",
        }.get(lab.get("basis"), "")
        blocks.append(
            _axis_head("就業", lab["state"], lab.get("lead", "")) + rows
            + '<div class="wx-src" style="margin-top:8px">' + basis_txt + '</div>'
            + '<div class="wx-src">門檻出處：FOMC 長期失業率（SEP 中央趨勢）'
              '　·　失去工作者比重警戒 3 個百分點、留意 z≥1.5'
              '（本站門檻，1967 年起回測選定，見就業頁）</div>'
            + _mismatch_note("就業", lab["state"], lab.get("tilt"),
                             lab.get("net"), "失業率離充分就業多遠")
            + "</div></details>")
        order.append(("labor", blocks.pop()))

    seq = dict(order)
    return ('<div class="axg">'
            + "".join(seq[k] for k in ("labor", "inflation") if k in seq)
            + "</div>")


def _nc_suffix(d: dict) -> str:
    """「完整算式」收合列的推估後綴——推估值不點開也看得到。"""
    nc = d.get("pce_nowcast") or {}
    if not (nc.get("estimated") and nc.get("value") is not None):
        return ""
    method_short = ("成分法" if nc.get("method") == "components" else "差距法")
    return f'；含核心 PCE 推估 {nc["value"]:.2f}%（{method_short}）'


def _nc_calc(nc: dict) -> str:
    """
    推估值的**實際計算**——放在通膨軸的展開裡（使用者的原話：
    「通膨展開後沒有實際列出怎麼算出推估值」）。

    差距法印出整條算式（核心 CPI − 平均差距 ＝ 推估值），
    成分法在成分表加「貢獻」欄與「加權合計」列——表格自己就是算式。
    說明壓到重點：為什麼能推一句、回測比較一行；「規則決定、可重現」
    這類每期都一樣的話不再印。
    """
    if not (nc.get("estimated") and nc.get("value") is not None):
        return ""
    v = nc["value"]
    _mc, _mg = nc.get("mae_components"), nc.get("mae_gap")
    picked = "成分法" if nc.get("method") == "components" else "差距法"
    # 成分法本期沒被採用而且有具體原因（多半是某條成分序列當次抓失敗）
    # 時，把原因印在畫面上——否則讀者只看到「不可用」，會以為
    # CPI＋PPI 那套被拿掉了，得去翻 log 才知道發生什麼事。
    _cr = (nc.get("comp_reason") or "") if picked == "差距法" else ""
    comp_part = f"±{_mc:.3f}" if _mc is not None else "本期不可用"
    if _cr:
        comp_part += f"（{esc(_cr)}）"
    mae_line = (
        f'回測近 {nc.get("n_backtest") or "—"} 期，取誤差小的：'
        f'成分法 {comp_part}、'
        f'差距法 {f"±{_mg:.3f}" if _mg is not None else "不可用"} 個百分點'
        f'——本期用<b>{picked}</b>。')
    if nc.get("method") == "components":
        rows = [c for c in (nc.get("components") or [])
                if c.get("yoy") is not None]
        comp_rows = "".join(
            f'<tr><td>{esc(c["label"])}'
            + ("（用最新一期頂上）" if c.get("lagged") else "")
            + f'</td><td>{c["weight"]:.1f}%</td>'
            f'<td>{c["yoy"]:+.2f}%</td>'
            f'<td>{c["weight"] * c["yoy"] / 100:+.2f}</td></tr>'
            for c in rows)
        calc = (f'<table style="margin-top:8px"><thead><tr><th>成分</th>'
                f'<th>權重</th><th>年增</th><th>貢獻</th></tr></thead>'
                f'<tbody>{comp_rows}'
                f'<tr><td><b>加權合計 ＝ 推估核心 PCE</b></td><td></td><td></td>'
                f'<td><b>{v:.2f}%</b></td></tr></tbody></table>')
    else:
        gap = nc.get("gap")
        if gap is not None:
            cpi = v + gap
            calc = (f'<div class="wx-thr">核心 CPI 年增 {cpi:.2f}%　−　'
                    f'兩者近 12 個月平均差距 {gap:+.2f} 個百分點　＝　'
                    f'推估核心 PCE <b>{v:.2f}%</b></div>')
        else:
            calc = f'<div class="wx-thr">推估核心 PCE ＝ {v:.2f}%</div>'
    return ('<div class="wx-src" style="margin-top:8px"><b>推估值怎麼算</b>：'
            'PCE 比 CPI 晚兩週公布，空窗期用 CPI／PPI 先推，公布即換回實際值。'
            + mae_line + '</div>' + calc)


# ===========================================================================
# 2026-10 改版：手機優先的情境頁
# ===========================================================================
_NUM = re.compile(r"[-+]?\d+(?:\.\d+)?")
LEAN_ZH = {"hawkish": "偏緊縮", "dovish": "偏寬鬆", "neutral": "大致不動"}
NB = " "          # 收合摘要裡數字與文字之間用不斷行空白


def _num(s: str):
    m = _NUM.findall(s or "")
    return float(m[-1]) if m else None


def _md(iso: str) -> str:
    return f"{int(iso[5:7])}/{int(iso[8:10])}" if iso and len(iso) >= 10 else iso or ""


_WD = "一二三四五六日"


def _md_wd(iso: str) -> str:
    import datetime as _dt
    try:
        return f"{_md(iso)}（{_WD[_dt.date.fromisoformat(iso[:10]).weekday()]}）"
    except ValueError:
        return _md(iso)


def _now_line(d: dict) -> str:
    w = d.get("why") or {}
    lab = {r["label"]: r["value"] for r in (w.get("labor") or {}).get("rows") or []}
    u = next((v for k, v in lab.items() if k.startswith("失業率")), None)
    p = (w.get("inflation") or {}).get("level")
    bits = []
    if u:
        bits.append(f'失業率 <b>{esc(u)}</b>')
    if p:
        bits.append(f'核心 PCE 年增 <b>{esc(p)}</b>')
    return f'<div class="sx-now">目前讀數　{"　·　".join(bits)}</div>' if bits else ""


def _trail(d: dict, sc) -> str:
    tr = d.get("trail") or []
    cells = d.get("cells") or []
    if not tr or not cells:
        return ""
    pos = {}
    for i, row in enumerate(cells):
        for j, c in enumerate(row):
            pos[(c["labor"], c["infl"])] = (i, j)
    items = [(f'{int(t["month"][5:7])} 月', t["labor"], t["infl"], False) for t in tr]
    items.append(("現在", sc.labor_state, sc.infl_state, True))

    def mini(l, i_, now):
        p = pos.get((l, i_))
        sq = "".join(
            f'<i class="{"f" if p == (r, c) else ""}"></i>'
            for r in range(3) for c in range(3))
        return f'<div class="sx-tg{" now" if now else ""}">{sq}</div>'

    blocks = "".join(
        f'<div class="sx-ti{" now" if now else ""}">{mini(l, i_, now)}'
        f'<span>{esc(m)}</span></div>' for m, l, i_, now in items)
    same = all((t["labor"], t["infl"]) == (sc.labor_state, sc.infl_state) for t in tr)
    if same:
        txt = f'近 {len(tr)} 個月都在這一格'
    else:
        moves = []
        prev = None
        for t in tr + [{"month": "現在", "labor": sc.labor_state, "infl": sc.infl_state}]:
            k = (t["labor"], t["infl"])
            if prev and k != prev:
                moves.append(f'{t["month"][5:7].lstrip("0") + " 月" if t["month"] != "現在" else "現在"}'
                             f'移到就業{k[0]} × 通膨{k[1]}')
            prev = k
        txt = "；".join(moves) or "格位有變動"
    return (f'<details class="f-more sx-trail"><summary>格位軌跡：{esc(txt)}</summary>'
            f'<div class="sx-tis">{blocks}</div>'
            '<div class="sx-note">過去月份用目前的門檻回推，不含失去工作者推格；停在核心 PCE 最新一期。</div>'
            '</details>')


# ---- 主要驅動因素：各頁本期關鍵訊號的第一條 ----
def _driver_cards(cards: list) -> str:
    if not cards:
        return '<div class="empty">尚無資料</div>'
    eyebrow = {"就業軸": "就業軸　·　本期關鍵訊號", "通膨軸": "通膨軸　·　本期關鍵訊號",
               "政策": "政策　·　最近一次決議", "曲線形狀": "曲線形狀　·　長端本月主因"}
    sev = {"alert": "警示", "watch": "留意", "info": ""}
    out = []
    for c in cards:
        tag = sev.get(c.get("sev"), "")
        out.append(
            f'<a class="sx-dc {c.get("lean", "neutral")}" href="{esc(c["href"])}">'
            f'<span class="sx-dc-k">{esc(eyebrow.get(c["axis"], c["axis"]))}'
            + (f'<em class="sx-sev {c.get("sev")}">{tag}</em>' if tag else "")
            + f'</span><b class="sx-dc-t">{esc(c["title"])}</b>'
            f'<span class="sx-dc-f"><i class="sx-lean {c.get("lean", "neutral")}">'
            f'{esc(LEAN_TEXT.get(c.get("lean"), "中性"))}</i>來源：{esc(c["page"])}頁 →</span></a>')
    return f'<div class="sx-dcs">{"".join(out)}</div>'


# ---- 情境轉換門檻：距離條 ----
_AXIS_ZH = {"labor": "就業軸", "inflation": "通膨軸"}
_SCALE = 0.5          # 0.5 個百分點以外＝條是空的


def _trigger_bars(trigs, drift=None) -> str:
    if not trigs:
        return '<div class="empty">資料不足，無法計算觸發距離</div>'
    groups = {}
    for t in sorted(trigs, key=lambda x: not getattr(x, "adjacent", True)):
        groups.setdefault(getattr(t, "axis", "") or "labor", []).append(t)
    out = []
    for ax in ("labor", "inflation"):
        rows = []
        for t in groups.get(ax, []):
            cur, thr = _num(t.current), _num(t.threshold)
            dist = 0.0 if t.met else (abs(thr - cur) if cur is not None and thr is not None else None)
            close = 100.0 if t.met else (max(0.0, 1 - dist / _SCALE) * 100 if dist is not None else 0)
            tags = ""
            if getattr(t, "adjacent", True):
                tags += '<span class="tadj">下一格</span>'
            if (drift and t.direction and not t.met
                    and (drift.get(t.axis) or (None,))[0] == t.direction):
                tags += '<span class="tdir">動能指向</span>'
            if getattr(t, "binding", False):
                tags += '<span class="tbind">關鍵</span>'
            rows.append(
                f'<div class="sx-tr{" met" if t.met else ""}{"" if getattr(t, "adjacent", True) else " far"}">'
                f'<div class="sx-tr-h"><b>{esc(t.label)}</b>{tags}'
                f'<span class="sx-tr-d">{esc("已觸發" if t.met else t.distance)}</span></div>'
                f'<div class="sx-tr-bar"><i style="width:{close:.0f}%"></i></div>'
                f'<div class="sx-tr-n">{esc(t.current)}　→　{esc(t.threshold)}</div></div>')
        if rows:
            out.append(f'<div class="sx-tg-h">{_AXIS_ZH[ax]}</div>' + "".join(rows))
    out.append('<div class="sx-note">條越滿＝越接近觸發；差 0.5 個百分點以上是空條。'
               '通膨門檻用「綜合水準」（0.6×年增＋0.4×三月年化），比格位判定早一步反應。</div>')
    return "".join(out)


def _next_releases(rows: list, trigs) -> str:
    if not rows:
        return ""
    near = {}
    for t in trigs or []:
        if t.met or not getattr(t, "adjacent", True):
            continue
        cur, thr = _num(t.current), _num(t.threshold)
        if cur is None or thr is None:
            continue
        k = {"labor": "就業軸", "inflation": "通膨軸"}.get(t.axis)
        if k and (k not in near or abs(thr - cur) < near[k][0]):
            near[k] = (abs(thr - cur), t)
    out = []
    for r in rows:
        n = near.get(r["axis"])
        hint = (f'最近門檻：{n[1].label}　{n[1].distance}' if n else r["why"])
        out.append(f'<div class="sx-nx"><span class="sx-nx-d">{esc(_md_wd(r["date"]))}</span>'
                   f'<div class="sx-nx-b"><b>{esc(r["label"])}</b><span class="sx-nx-a">{esc(r["axis"])}</span>'
                   f'<small>{esc(hint)}</small></div></div>')
    return ('<h3 class="sx-h3">接下來可能移動格子的數據</h3>'
            f'<div class="sx-nxs">{"".join(out)}</div>')


# ---- 固定收益對照 ----
def _fmt_level(r) -> str:
    if r.get("level") is None:
        return ""
    if r["key"] in ("short", "long"):
        return f'{r["level"]:+.0f}bp'
    if r["key"] in ("ig", "hy"):
        return f'{r["level"] * 100:.0f}bp'
    return f'{r["level"]:.2f}%'


def _pos_table(rows: list, name: str) -> str:
    if not rows:
        return '<div class="empty">尚無資料</div>'
    from ..analysis.positioning import MATCH_ZH
    body = []
    for r in rows:
        dl = (f'{r["delta_bp"]:+.0f}bp'.replace("-", "−") if r.get("delta_bp") is not None else "—")
        body.append(
            f'<div class="sx-pr {r["match"]}">'
            f'<div class="sx-pk"><b>{esc(r["label"])}</b><small>{esc(r["sub"])}　{esc(_fmt_level(r))}</small></div>'
            f'<div class="sx-pe"><em>框架預期</em>{esc(r["expect_txt"])}</div>'
            f'<div class="sx-pa"><em>近 1 月實際</em>{esc(r["actual_txt"])}<small>{esc(dl)}</small></div>'
            f'<div class="sx-pm"><span class="sx-m {r["match"]}">{esc(MATCH_ZH[r["match"]])}</span></div></div>')
    head = ('<div class="sx-ph"><span>變數</span><span>框架預期（' + esc(name) + '）</span>'
            '<span>近 1 月實際</span><span>對照</span></div>')
    return f'<div class="sx-pos">{head}{"".join(body)}</div>'


def _pos_summary(rows: list) -> tuple[str, str]:
    from collections import Counter
    c = Counter(r["match"] for r in rows)
    sm = f'一致{c.get("same", 0)}　·　偏離{c.get("off", 0)}　·　相反{c.get("opp", 0)}'
    opp = [r for r in rows if r["match"] == "opp"]
    if opp:
        line = "；".join(f'{r["label"]}：框架預期{r["expect_txt"]}，實際{r["actual_txt"]}'
                        f'（{r["delta_bp"]:+.0f}bp）'.replace("-", "−") for r in opp)
        line = "跟框架<b>相反</b>的：" + esc(line) + "。相反不代表框架錯，常見原因是另一股力量蓋過了政策方向（例如期限溢酬）。"
    else:
        line = "七個變數裡沒有跟框架方向相反的。"
    return sm, line


def _duration(rows: list) -> str:
    if not rows:
        return ""
    tiles = []
    for r in rows:
        cls = "dn" if r["real"] < 0 else "up"
        tiles.append(
            f'<div class="sx-du"><div class="sx-du-h"><b>{esc(r["tenor"])}</b>'
            f'<span>存續期間 {r["D"]:.1f}</span></div>'
            f'<div class="sx-du-v {cls}">{r["real"]:+.2f}%<small>近 1 月殖利率 {r["dy"]:+.0f}bp</small></div>'
            f'<div class="sx-du-s"><span>+25bp　<b>{r["up25"]:+.2f}%</b></span>'
            f'<span>−25bp　<b>{r["dn25"]:+.2f}%</b></span></div></div>')
    return ('<h3 class="sx-h3">存續期間試算：價格變動 ≈ −D×Δy ＋ ½×C×Δy²</h3>'
            f'<div class="sx-dus">{"".join(tiles)}</div>'
            '<div class="sx-note">以當前殖利率的平價債近似（修正存續期間 D、凸性 C）；'
            '「近 1 月」用過去 22 個交易日的殖利率實際變動代入，不含票息收入。'
            '±25bp 是情境試算：凸性讓下跌比上漲少一點。</div>')


# ---- 市場定價：期貨路徑 vs 點陣圖 ----
def _futures(d: dict, sc) -> tuple[str, str]:
    fc = d.get("futures_curve") or {}
    dots = d.get("dots") or {}
    mvd = d.get("mvd") or {}
    mk = d.get("market") or {}
    if not fc.get("points"):
        body = ('<div class="soonbox" style="margin-top:0;padding:22px 18px;box-shadow:none;'
                'border-style:dashed"><h3>本次沒有取得期貨路徑</h3><p>聯邦基金期貨（ZQ）資料暫缺，'
                '取得新資料後更新。</p></div>')
        if mk:
            body += (f'<div class="sx-note">替代參考：2 年期殖利率 − 政策利率中值 '
                     f'{esc(mk.get("display", ""))}（{esc(mk.get("text", ""))}）</div>')
        return body, "本次沒有取得期貨路徑"
    r0, pts = fc["r0"], fc["points"]
    bps = [(p["rate"] - r0) * 100 for p in pts]
    dbp = {y: (v - r0) * 100 for y, v in dots.items()}
    m = max([abs(x) for x in bps] + [abs(v) for y, v in dbp.items() if any(p["month"][:4] == y for p in pts)] + [25])
    term_m = fc["terminal_month"]
    cols = []
    for p, bp in zip(pts, bps):
        y, mo = p["month"][:4], int(p["month"][5:7])
        thin = " thin" if p["month"] >= fc.get("thin_from", "9999") else ""
        on = " on" if p["month"] == term_m else ""
        h = abs(bp) / m * 100
        dot = ""
        if y in dbp:
            dot = f'<span class="sx-fp-dot" style="bottom:{max(dbp[y], 0) / m * 100:.1f}%"></span>'
        lab = ""
        if p is pts[0] or p["month"] == term_m:
            lab = f'<em>{p["rate"]:.2f}</em>'
        xl = (f'{y[2:]}/{mo}' if (mo in (1, 4, 7, 10) or p is pts[0]) else "")
        cols.append(f'<div class="sx-fp-c{thin}{on}" data-tip="{p["month"]}｜{p["rate"]:.3f}%（{bp:+.0f}bp）">'
                    f'<span class="sx-fp-b {"up" if bp >= 0 else "dn"}" style="height:{h:.1f}%">{lab}</span>'
                    f'{dot}<span class="sx-fp-x">{esc(xl)}</span></div>')
    chart = (f'<div class="sx-fp"><div class="sx-fp-y"><span>+{m:.0f}bp</span><span>0</span></div>'
             f'<div class="sx-fp-p">{"".join(cols)}</div></div>'
             '<div class="cl-leg"><span><i class="gc-up"></i>期貨隱含利率（相對現行中點）</span>'
             '<span><i class="sx-lg-dot"></i>點陣圖年底中位數</span>'
             '<span><i class="sx-lg-thin"></i>遠月成交稀、僅供參考</span></div>')
    # 數字列
    tbp = fc["terminal_bp"]
    tiles = [("現行區間中點", f'{r0:.3f}%', "政策利率目標區間的中點"),
             ("期貨終端利率", f'{fc["terminal"]:.2f}%',
              f'{term_m[:4]}/{int(term_m[5:7])}　{tbp:+.0f}bp' + ("，仍在升" if fc.get("open_end") and tbp > 0
                                                               else "，仍在降" if fc.get("open_end") else ""))]
    for y in sorted(dots)[:2]:
        tiles.append((f"點陣圖 {y} 年底", f"{dots[y]:.3f}%", f'較現行 {(dots[y] - r0) * 100:+.0f}bp'))
    tiles_html = "".join(f'<div class="stat"><div class="s-label">{esc(a)}</div>'
                         f'<div class="s-value">{esc(b)}</div><div class="s-note">{esc(c)}</div></div>'
                         for a, b, c in tiles)
    # 一句話：年底一致嗎、明年差多少
    sent = []
    y0 = sorted(dots)[0] if dots else None
    if y0 and mvd.get("market_end") is not None and str(mvd.get("year")) == y0:
        g = (mvd["market_end"] - dots[y0]) * 100
        sent.append(f'到 {y0} 年底，期貨 {mvd["market_end"]:.2f}% 對點陣圖 {dots[y0]:.3f}%'
                    + ("，大致一致" if abs(g) < 12.5 else f"，期貨{'多' if g > 0 else '少'}定價 {abs(g):.0f}bp"))
    last = pts[-1]
    y1 = last["month"][:4]
    if y1 in dots and y1 != y0:
        g = (last["rate"] - dots[y1]) * 100
        sent.append(f'到 {y1}/{int(last["month"][5:7])}，期貨 {last["rate"]:.2f}%，'
                    f'點陣圖 {y1} 年底只有 {dots[y1]:.3f}%——'
                    + (f'市場比聯準會{"多" if g > 0 else "少"}定價約 {abs(g):.0f}bp（{abs(g) / 25:.1f} 碼）'
                       if abs(g) >= 12.5 else "兩者大致一致"))
    if fc.get("open_end"):
        sent.append("期貨路徑在資料窗的最後一個月還在走，真正的終端可能更遠、更高")
    sent_html = f'<div class="impact {"hawkish" if tbp > 12.5 else "dovish" if tbp < -12.5 else "neutral"}">{esc("。".join(sent))}。</div>' if sent else ""
    alt = (f'<div class="sx-note">另一個粗略代理：2 年期殖利率 − 政策利率中值 '
           f'{esc(mk.get("display", ""))}（{esc(mk.get("text", ""))}）。</div>' if mk else "")
    body = (sent_html + f'<div class="stat-row sx-stats">{tiles_html}</div>' + chart + alt
            + teach("聯邦基金期貨每個月的隱含利率連成一條「市場預期的政策路徑」，再跟聯準會自己的點陣圖並排。",
                    "終端利率＝這段期間離現行利率最遠的那一點，代表市場認為這一輪會升（降）到哪裡。"
                    "期貨比點陣圖多定價，代表市場不相信聯準會會停在它說的地方。",
                    "近月合約流動性好，遠月（約半年以後）成交稀，數字會跳，只看方向。"
                    "期貨資料取自交易所報價，可能有 15 分鐘以上延遲。"))
    sm = (f'終端{fc["terminal"]:.2f}%（{term_m[:4]}/{int(term_m[5:7])}，{tbp:+.0f}bp）'
          + (f'　·　點陣圖{y1}年底{dots[y1]:.3f}%' if y1 in dots else ""))
    return body, sm


def _divergence_box(d: dict, sc) -> str:
    dv = d.get("divergence")
    fc = d.get("futures_curve") or {}
    page = LEAN_ZH.get(sc.lean, "—")
    if not dv:
        return (f'<div class="sx-dv na"><div class="sx-dv-c"><span>本站判讀</span><b>{esc(page)}</b>'
                f'<small>{esc(sc.name)}</small></div><div class="sx-dv-vs">—</div>'
                '<div class="sx-dv-c"><span>期貨定價</span><b>本次未取得</b><small>下次更新補上</small></div></div>')
    mkt = LEAN_ZH.get(dv["market"], "—")
    return (f'<div class="sx-dv {"agree" if dv["agree"] else "split"}">'
            f'<div class="sx-dv-c"><span>本站判讀</span><b class="{sc.lean}">{esc(page)}</b>'
            f'<small>{esc(sc.name)}</small></div>'
            f'<div class="sx-dv-vs">{"一致" if dv["agree"] else "分歧"}</div>'
            f'<div class="sx-dv-c"><span>期貨定價</span><b class="{dv["market"]}">{esc(mkt)}</b>'
            f'<small>終端 {fc.get("terminal", 0):.2f}%　{dv["bp"]:+.0f}bp</small></div></div>')


def _scenario_body_full(d: dict) -> str:
    sc = d["scenario"]
    _why_html = _why_axes(d.get("why") or {}, d.get("pce_nowcast") or {})

    incomplete = ""
    if sc.incomplete:
        incomplete = (
            '<div class="v-count" style="border-top:none;padding-top:0;margin-top:12px">'
            f'⚠️ 以下模組尚無資料，這個判定並不完整：{esc("、".join(sc.incomplete))}。'
            "</div>")

    basis_note = (f'<div class="warnbox" style="margin:0 0 14px">'
                  f'{esc(sc.labor_basis_note)}</div>'
                  if getattr(sc, "labor_basis_note", "") else "")
    has_binding = any(getattr(t, "binding", False) for t in sc.triggers)
    binding_hint = (
        "標「關鍵」的是目前重心下真正會改變政策方向的那一軸。"
        if has_binding else
        "聯準會目前沒有明顯偏向任何一邊，哪一軸先觸發，哪一邊就決定方向。")

    grid_html, cmp_head, cmp_body = _grid_tabs(d, sc)
    nc_suffix = _nc_suffix(d)

    _grid_sum = (f'就業{sc.labor_state}×通膨{sc.infl_state}　·　{sc.name}'
                 f'　·　{LEAN_TEXT.get(sc.lean, "")}')
    cards = d.get("driver_cards") or []
    _drv_sum = (f'{len(cards)}項　·　{cards[0]["title"]}' if cards else "尚無資料")
    _met = [x for x in sc.triggers if x.met]
    _adj = sorted([x for x in sc.triggers if not x.met and getattr(x, "adjacent", True)
                   and _num(x.current) is not None and _num(x.threshold) is not None],
                  key=lambda x: abs(_num(x.threshold) - _num(x.current)))
    _trig_sum = (f'{len(_met)}項已觸發' if _met else
                 (f'最近：{_adj[0].label}　·　{_adj[0].distance}' if _adj else
                  (f'{len(sc.triggers)}項門檻與距離' if sc.triggers else "資料不足")))
    _trig_sum = _trig_sum.replace(" ", NB)
    pos_rows = d.get("pos_compare") or []
    _pos_sum, _pos_line = _pos_summary(pos_rows) if pos_rows else ("尚無資料", "")
    market_html, _mkt_sum = _futures(d, sc)
    _mkt_sum = _mkt_sum.replace(" ", NB)

    focus = sc.focus or {}
    _fc_parts = []
    if focus.get("evidence"):
        _fc_parts.append('<div class="f-detail"><b>本期判定依據</b>：'
                         + esc("、".join(focus["evidence"])) + '</div>')
    if cmp_body:
        _fc_parts.append(cmp_body)
    _fc_sum = f'為什麼是「{focus.get("label") or "兩邊並重"}」、翻轉會怎樣'
    focus_collapse = (f'<details class="f-more"><summary>{esc(_fc_sum)}</summary>'
                      + "".join(_fc_parts) + '</details>') if _fc_parts else ""
    assumed_note = ""
    if getattr(sc, "regime_assumed", False):
        assumed_note = ('<div class="caveat"><b>本次判不出重心</b>——'
                        '聲明、投票與記者會的訊號互相抵銷。下面暫用「兩邊並重」那一張對照，'
                        '但那是<b>不知道</b>，不是<b>真的並重</b>，判讀時要打折。</div>')
    from ..analysis.positioning import WHY
    why_rows = "".join(f'<dt>{esc(r["label"])}</dt><dd>{esc(WHY[r["key"]])}</dd>' for r in pos_rows)

    return f"""
<div class="verdict {sc.lean}">
  <div class="v-eyebrow">{esc(d['as_of'])}　·　目前情境</div>
  <div class="v-main">{esc(sc.name)}</div>
  <div class="v-why">{esc(sc.description)}</div>
  {incomplete}
</div>

<div class="grid">
  <div class="card">
    <h2 id="grid" data-open="1" data-sum="{esc(_grid_sum)}">九宮格定位</h2>
    {_now_line(d)}
    {assumed_note}
    {grid_html}
    <p class="sx-note sx-glg"><i class="sx-glg-cur"></i>目前位置　<i class="sx-glg-adj"></i>下一步可能去的格</p>
    {_trail(d, sc)}
    <details class="f-more"><summary>完整算式與門檻出處（可驗算）{esc(nc_suffix)}</summary>
      {_why_html}
    </details>
    {focus_collapse}
    {_cell_gloss(d.get('cells'))}
    {teach(
        "格子的位置是固定的計算：兩條軸各對照一個外部門檻、判定重心、再交叉。",
        "看得懂這套算法，你就能在數據公布的當下自己推出格子會不會動。門檻錨在 FOMC 自己的預測，不是本站選的數字。",
        "格位只用水準判（失業率、核心 PCE 年增）；動能改看 PCE Supercore 三月年化，連兩個月越過 3.7%／2.1% 才推一格。")}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="drivers" data-sum="{esc(_drv_sum)}">主要驅動因素</h2>
    <p class="hint">各頁「本期關鍵訊號」排第一的那條，加上聯準會最近一次決議與長端本月主因。點卡片看完整依據。</p>
    {_driver_cards(cards)}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="triggers" data-sum="{esc(_trig_sum)}">情境轉換門檻</h2>
    <p class="hint">{binding_hint}</p>
    {basis_note}
    {_trigger_bars(sc.triggers, sc.drift)}
    {_next_releases(d.get('next_releases') or [], sc.triggers)}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="positioning" data-sum="{esc(_pos_sum)}">固定收益對照</h2>
    <p class="hint">「{esc(sc.name)}」這一格在教科書上會怎麼反映到債市，對照過去一個月市場實際怎麼走。方向性參考，不是進出場訊號。</p>
    {_pos_table(pos_rows, sc.name)}
    {f'<div class="sx-pos-line">{_pos_line}</div>' if _pos_line else ''}
    <details class="f-more"><summary>每一列為什麼這樣預期</summary>
      <dl class="gloss" style="margin-top:10px">{why_rows}</dl>
      <div class="f-detail">判定規則：近 22 個交易日的變動超過 ±5bp（高收益 ±15bp）才算有方向，否則算「區間」。
        預期與實際同向＝一致；一邊有方向、另一邊區間＝偏離；方向相反＝相反。</div>
    </details>
    {_duration(d.get('duration') or [])}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="market" data-sum="{esc(_mkt_sum)}">市場定價：期貨路徑與點陣圖</h2>
    <p class="hint">市場用真金白銀押出的政策路徑，對照聯準會自己的點陣圖。</p>
    {market_html}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="howto" data-sum="三張格子的規則、重心怎麼判定、格子怎麼移動">判讀說明</h2>
    <p class="hint">這一頁的規則書，內容不隨數據變動，<b>看過一次就夠</b>。</p>
    <details class="f-more"><summary>展開完整說明（七個問答）</summary>
        <dl class="gloss">
      <dt>為什麼有三張九宮格</dt>
      <dd>聯準會有兩個使命，而它們有時指向相反的方向——就業弱要降息、
        通膨高不能降。誰優先，結論就完全不同。所以三種體制各一張格子，
        由聲明、投票與記者會判定目前適用哪一張。九格裡只有三格會隨體制改變（標◆），
        其餘六格不管誰優先都一樣。</dd>
      <dt>通膨的動能為什麼看 Supercore</dt>
      <dd>Supercore（核心服務扣除住房）跟薪資連動最緊、最難靠商品價格回落降下來，
        是聯準會最在意的那一段。它的三月年化連兩個月高於 3.7% 或低於 2.1%
        （1995–2019 年歷史分布的 90／10 百分位附近，中心約 2.9%）才把通膨格位推一格——
        兩個月是為了不被單月雜訊帶著跑。</dd>
      <dt>為什麼不給機率</dt>
      <dd>本頁對照經濟數據與市場利率定價，觀察兩者的分歧，以及改變當前判讀所需的條件。</dd>
      <dt>重心怎麼判定</dt>
      <dd>聲明裡的制式風險句（±2）、聲明對現況的描述（±1）、
        反對票的方向與張數（±1～2）、記者會裡的明確表態（±1）。
        綜合以上資料，觀察聯準會目前更重視通膨還是就業。</dd>
      <dt>格子會怎麼移動</dt>
      <dd>通常一次移動一格，而且往往是通膨先動、就業後動。
        跳格多半發生在有外生衝擊時。上方「格位軌跡」可以看最近半年怎麼走。</dd>
      <dt>固定收益對照怎麼讀</dt>
      <dd>每一格情境對七個市場變數各有一個教科書式的預期方向。跟實際並排，
        「相反」的那幾列最值得看：通常代表有另一股力量（期限溢酬、信用事件、
        發債潮）蓋過了政策方向。長端曲線那一列可對照利率變化與政策方向是否一致。</dd>
      <dt>文本的角色</dt>
      <dd>聯準會的實際決議（升息、降息或維持，以及反對票主張的方向）用來校準，
        不是決定格子的位置。這裡不採用任何措辭分數——語氣會隨主席文風改變。</dd>
    </dl>
    </details>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="glossary" data-sum="這一頁出現的專有名詞">名詞解釋</h2>
        <dl class="gloss">
      <dt>短端／長端曲線變陡、變平</dt>
      <dd>短端看 10 年減 2 年，長端看 30 年減 10 年。「變陡」是長天期相對短天期上升，
        「變平」相反。短端跟著政策預期走；長端還受期限溢酬（財政與供給）影響。</dd>
      <dt>存續期間與凸性</dt>
      <dd>存續期間是債券價格對殖利率的敏感度：殖利率上升 1 個百分點，價格大約下跌「存續期間」個百分比。
        凸性是修正項，讓殖利率大幅變動時，下跌比線性估的少、上漲比線性估的多。</dd>
      <dt>TIPS 與實質殖利率</dt>
      <dd>TIPS 是本金隨通膨調整的公債，它的殖利率就是「實質殖利率」。
        實質殖利率上升，TIPS 價格下跌——跟一般債券一樣是反向關係。</dd>
      <dt>損益兩平通膨率</dt>
      <dd>同天期一般公債殖利率減 TIPS 殖利率，是市場要求的通膨補償。
        它擴大代表市場預期的通膨（加上通膨風險溢酬）上升。</dd>
      <dt>投資級／高收益利差（OAS）</dt>
      <dd>公司債殖利率高於同天期公債的部分，已扣除提前贖回等選擇權的影響。
        投資級反映大型企業（近期受科技巨頭大量發債影響），高收益反映景氣與違約風險。</dd>
      <dt>終端利率</dt>
      <dd>這一輪升息（或降息）循環市場預期最後會停在哪裡。本頁取未來 13 個月期貨隱含利率中
        離現行利率最遠的那一點。</dd>
      <dt>點陣圖</dt>
      <dd>每季的經濟預測摘要（SEP）裡，每位與會者對各年底政策利率的預測，一人一點；本頁取中位數。</dd>
    </dl>
  </div>
</div>
"""


def scenario_body(d: dict) -> str:
    """首卡：九宮格位置、市場是否同意、下一個轉格條件與下一個數據。"""
    sc = d["scenario"]
    lean = LEAN_TEXT.get(sc.lean, "中性")
    labor_text = {"弱": "偏弱", "中": "中性", "強": "偏強"}.get(sc.labor_state, sc.labor_state)
    infl_text = {"低": "偏低", "中": "中性", "高": "偏高"}.get(sc.infl_state, sc.infl_state)
    desc = (sc.description or "").split("。")[0]
    regime = next((m["label"] for m in d.get("regime_meta", []) if m.get("current")), "兩邊並重")
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
        state_chip("FOMC 反應體制", regime, "觀察聯準會更重視通膨還是就業"),
    ])
    nr = (d.get("next_releases") or [])
    nr_text = ("　·　".join(f'{_md(r["date"])} {r["label"]}' for r in nr[:2]) if nr else "—")
    logic = (f'<div class="logic-strip"><div class="logic-step"><b>當前位置</b>'
             f'<span>就業 {sc.labor_state} × 通膨 {sc.infl_state}＝{esc(sc.name)}</span></div>'
             f'<div class="logic-step"><b>下一個轉格條件</b><span>{esc(trigger_text)}</span></div>'
             + (f'<div class="logic-step"><b>政策解鎖條件</b><span>{esc(unlock_text)}</span></div>'
                if unlock_text else "")
             + f'<div class="logic-step"><b>下一個會動格子的數據</b><span>{esc(nr_text)}</span></div></div>')
    logic = focus_evidence(logic)
    notes = (f'<div class="data-line"><span class="data-tag">{esc(d.get("as_of", "—"))}</span>'
             '<span class="data-tag">格位＝水準；動能看 Supercore</span>'
             '<span class="data-tag">長端與信用在「固定收益對照」</span></div>')
    hero = (f'<div class="grid"><div class="card focus-card"><div class="focus-eyebrow">Macro regime</div>'
            f'<h2 class="focus-title">就業{labor_text} × 通膨{infl_text}</h2>'
            f'<p class="focus-sub">{esc(sc.name)}｜{lean}。{esc(desc)}。</p>'
            f'<div class="focus-grid">{metrics}</div>{_divergence_box(d, sc)}{logic}{notes}</div></div>')
    return hero + compact_full(_scenario_body_full(d), "九宮格依據、部位與完整方法")


def scenario_footer(d: dict) -> str:
    from ..site import source_footer
    return source_footer(
        [("就業格位", "失業率相對 FOMC 長期區間", "每月"),
         ("通膨格位", "核心 PCE 年增；Supercore 三月年化連兩月越過門檻才推一格", "每月"),
         ("用哪一張九宮格", "聯準會重心：聲明制式句、反對票、記者會表態", "每次會議"),
         ("固定收益對照", "框架預期是教科書式映射；期貨路徑取自交易所報價", "每日")],
        ["情境依據就業、通膨與聯準會政策資料判讀，詳細條件見各區說明。"],
        cols=("項目", "依據", "更新"),
        head="<b>判讀依據</b> 就業、通膨與聯準會政策",
        disclaimer="本頁僅為分析框架，不構成投資建議。")

