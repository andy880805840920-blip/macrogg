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
            rows.append(
                f'<div class="scell {c["lean"]}{cls}">'
                f'<div class="sname">{name_html}</div>'
                f'<div class="sdesc">{esc(c["desc"])}</div>{badge}</div>'
            )
    return f'<div class="sgrid">{head}{"".join(rows)}</div>'


def _grid_tabs(d: dict, sc) -> str:
    """
    三張九宮格＋切換。純 CSS（radio + 相鄰選擇器），不依賴 JS。

    為什麼要能切換
    --------------
    這一頁最有價值的反事實問題是「如果聯準會的重心翻轉，我這一格會變成什麼」。
    只顯示當前那張的話，讀者看不到答案；三張並排又會讓相同的六格重複三次。
    頁籤讓預設就是目前偵測到的體制，想看別的自己切。
    """
    metas = d.get("regime_meta") or []
    grids = d.get("grids") or {}
    if not metas or not grids:
        return _grid(d.get("cells") or [])

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
        cmp_note = ("兩個使命指向同一邊，所以不管誰優先，結論都一樣。"
                    "這是好消息——少一個需要擔心的變數。"
                    "下面三列是同一格在三種體制下的結論，可以核對。")

    return (f'<div class="rtabs">{"".join(tabs)}'
            f'<div class="rpanels">{"".join(panels)}</div></div>'
            f'<details class="f-more rcmp-box"><summary>{esc(cmp_head)}</summary>'
            f'<p class="hint" style="margin:10px 0 10px">{cmp_note}</p>'
            f'{cur_row}</details>')


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

    grid_tabs = _grid_tabs(d, sc)

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
        _cls = {"hawkish": "hawkish", "dovish": "dovish"}.get(mk["lean"], "balanced")
        market_html = f"""<div class="stat-row" style="margin-top:0">
      <div class="stat"><div class="s-label">市場定價的政策路徑</div>
        <div class="s-value">{mk['display']}</div>
        <div class="s-note">2 年期公債殖利率減政策利率中值</div></div>
      <div class="stat"><div class="s-label">本頁判讀</div>
        <div class="s-value" style="font-size:17px">{esc(LEAN_TEXT.get(sc.lean, '—'))}</div>
        <div class="s-note">目前這張九宮格給出的方向</div></div>
    </div>
    <div class="verdict {_cls}" style="margin-top:14px">
      <div class="v-main" style="font-size:19px">{esc(mk['text'])}</div>
      <div class="v-why" style="margin-top:8px">{_agree_html}</div>
    </div>
    <div class="src">用 2 年期殖利率當代理，是粗略估計而非會議層級的機率
      （見判讀說明）。</div>"""
    else:
        market_html = ('<div class="soonbox" style="margin-top:0;padding:26px 18px;'
                       'box-shadow:none;border-style:dashed"><h3>資料不足</h3>'
                       '<p>需要 2 年期公債殖利率與目前的政策利率區間，'
                       '目前缺其中一項。</p></div>')

    # ---- 反應函數：聯準會目前把哪一邊擺在前面 ----
    focus = sc.focus or {}
    focus_cls = {"inflation": "hawkish", "employment": "dovish"}.get(
        focus.get("focus", ""), "balanced")
    focus_ev = ""
    if focus.get("evidence"):
        # 只留這一次真正的判定依據。「來源為聲明制式句與投票紀錄，不用模型」
        # 是方法論、每一期都一樣，已經寫在頁尾的判讀說明裡——
        # 留在這裡等於每次都在證據旁邊把同一句話再講一遍。
        focus_ev = ('<div class="src">判定依據：'
                    + esc("、".join(focus["evidence"])) + "</div>")
    # 判不出重心時要明講：訊號互相抵銷 ≠ 聯準會真的兩邊並重
    assumed_note = ""
    if getattr(sc, "regime_assumed", False):
        assumed_note = ('<div class="caveat"><b>本次判不出重心</b><br>'
                        '聲明、投票與記者會的訊號互相抵銷，也沒有明確說'
                        '「兩邊風險大致平衡」。下面暫用「兩邊並重」那一張對照，'
                        '但那是<b>不知道</b>，不是<b>真的並重</b>——'
                        '兩者的意義不同，判讀時要打折。</div>')

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
    <p class="hint">就業 × 通膨，<b>每個重心各一張格子</b>——目前適用的那張已經選好。</p>
    <div class="verdict {focus_cls}" style="margin:0 0 18px">
      <div class="v-eyebrow">目前重心（決定用哪一張格子）</div>
      <div class="v-main" style="font-size:22px">{esc(focus.get('label', '無法判定'))}</div>
      <div class="v-why">{esc(focus.get('note', ''))}</div>
      {assumed_note}
    </div>
    {focus_ev}
    {grid_tabs}
    <p class="hint" style="margin-top:16px">
      <span class="lg-on">反白粗框</span>＝目前位置　·
      <span class="cflag">◆</span>＝會隨重心改變的三格（其餘六格三種體制都一樣）
    </p>
  </div>
</div>
<div class="grid g2">
  <div class="card">
    <h2 id="drivers" data-sum="{esc(_drv_sum)}">主要驅動因素</h2>
    <p class="hint">依嚴重度排序。</p>
    {drivers_html or '<div class="empty">尚無資料</div>'}
    <div class="src">逐條的計算依據與資料來源：<a href="/labor/#signals">勞動市場</a>
      　·　<a href="/inflation/#signals">通膨</a></div>
  </div>

  <div class="card">
    <h2 id="triggers" data-sum="{esc(_trig_sum)}">情境轉換門檻</h2>
    <p class="hint">{binding_hint}</p>
    {basis_note}
    {_triggers(sc.triggers)}
  </div>
</div>

<div class="grid g2">
  <div class="card">
    <h2 id="positioning" data-sum="{esc(_pos_sum)}">固定收益部位對照</h2>
    <p class="hint">方向性參考，不是進出場訊號。</p>
    <dl class="gloss poslist">{pos_rows or '<dt>尚無資料</dt><dd>—</dd>'}</dl>
    <div class="src">本頁為分析框架，不構成投資建議。</div>
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
    <h2 id="howto" data-sum="三張格子的規則、重心怎麼判定、名詞解釋">判讀說明</h2>
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
      <dt>2 年期為什麼能當市場定價的代理</dt>
      <dd>2 年期殖利率約等於市場預期的「未來兩年平均政策利率」。
        這是<b>粗略</b>代理而不是會議層級的機率——它同時含有期限溢酬，
        不能直接讀成純粹的政策路徑預期。要看逐次會議的隱含機率，
        得用聯邦資金期貨。</dd>
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
      <dd>聯準會的客觀訊號（政策行動、反對票、聲明裡的風險用語）用來校準，
        不是決定格子的位置。這裡刻意不採用措辭語氣分數——語氣會隨主席文風
        改變，主席換人時分數會整段位移，不能用來加減信心。
        當客觀訊號與數據方向不一致時，通常代表官員看到了數據還沒反映的東西，
        或反過來——他們還沒承認數據已經轉向。</dd>
    </dl>
  </div>
</div>
"""


def scenario_footer(d: dict) -> str:
    return (
        "情境分類由固定規則產生：勞動綜合分數 × 核心 PCE 的年增率與三月年化加權後的水準，"
        "決定落在九宮格的哪一格；聯準會的重心（聲明制式句、反對票、記者會表態）"
        "決定用哪一張九宮格。全部是確定性規則，不含模型生成內容。<br>"
        "長端供給壓力另行計算，不併入九宮格——它影響的是曲線形狀，不是政策方向。<br>"
        "本頁僅為分析框架，不構成投資建議。"
    )
