"""
長端與債務頁的新區塊（2026-10 改版）：三股力量、曲線、全球長端、供給、拍賣、信用利差。

版面原則（跟通膨頁一致）：
  · 先一句結論、再圖、最後才是方法——方法一律收進折疊
  · 一張圖一個 y 軸；走勢 24 個月；手機上用卡片不用寬表格
  · 只放事實與寫明規則的判定，不做加權總分
"""

from __future__ import annotations

from ..analysis import longend as le
from ..site import esc
from . import teach

CCOL = {"real": "var(--line-1)", "infl": "var(--line-2)", "tp": "#1baf7a"}


def _bp(v, d=0) -> str:
    return "—" if v is None else f"{v:+.{d}f}bp"


def _md(iso: str) -> str:
    try:
        return f"{int(iso[5:7])}/{int(iso[8:10])}"
    except (ValueError, IndexError):
        return iso


# ---------------------------------------------------------------------------
# 頂部結論卡
# ---------------------------------------------------------------------------
def hero(d: dict) -> str:
    """
    首卡（2026-10 第三版，使用者：「畫得亂七八糟、文字太多」）：
      一行報價（10Y／30Y）→ 本月主因一句 → 三段組成的小表（點一行看白話）。
    顏色只在主因那一行（品牌橘左邊線）；藍橘綠三色與大卡全部拿掉。
    """
    L = d.get("le") or {}
    curve = d.get("curve")
    y10 = curve.levels.get("10Y") if curve else None
    y30 = curve.levels.get("30Y") if curve else None
    ch10 = (curve.changes_1m.get("10Y") * 100) if curve and "10Y" in curve.changes_1m else None
    ch30 = (curve.changes_1m.get("30Y") * 100) if curve and "30Y" in curve.changes_1m else None
    c1 = (L.get("contrib") or {}).get(1)
    dec = (L.get("dec") or [None])[-1] if L.get("dec") else None
    asof = (f'{d.get("as_of", "—")}（盤中）' if d.get("as_of_live") else d.get("as_of", "—"))

    def _q(name, v, ch):
        cls = "up" if (ch or 0) > 0 else "dn" if (ch or 0) < 0 else ""
        return (f'<div class="le2-qi"><span>{name}</span><b>{v:.2f}%</b>'
                f'<em class="{cls}">近 1 月 {_bp(ch)}</em></div>')
    top = ""
    if y10 is not None and y30 is not None:
        top = (f'<div class="le2-q">{_q("10 年期", y10, ch10)}{_q("30 年期", y30, ch30)}</div>'
               f'<div class="le2-asof">資料 {esc(asof)}</div>')
    title = (f'本月主因：{le.COMP_ZH[c1["main"]]} {c1["parts"][c1["main"]]:+.0f}bp' if c1
             else "長端利率的三股力量")
    sub = (f'{le.PRESSURE_ZH[c1["main"]]}推高長端——{le.NATURE[c1["main"]]}。' if c1 else "")
    table = ""
    if dec:
        from .. import charts
        # 組成比例條保留（使用者 2026-10）：只用品牌色——主因那段橘、其餘兩段藏青深淺
        _main = c1["main"] if c1 else None
        _shade = iter(("var(--brand-navy)", "#8b97a8"))
        col = {k: ("var(--brand-orange)" if k == _main else next(_shade)) for k in ("real", "infl", "tp")}
        seg = charts.segbar([{"label": le.COMP_ZH[k], "value": dec[k], "color": col[k]}
                             for k in ("real", "infl", "tp")])
        rows = ""
        for k in ("real", "infl", "tp"):
            dv = c1["parts"][k] if c1 else None
            main = bool(c1 and c1["main"] == k)
            cls = "up" if (dv or 0) > 0 else "dn" if (dv or 0) < 0 else "fl"
            rows += (f'<div class="le2-r{" main" if main else ""}" title="{esc(le.NATURE[k])}">'
                     f'<div class="le2-n"><span><i class="le2-sw" style="background:{col[k]}"></i>{esc(le.COMP_ZH[k])}'
                     + ('<em>本月主因</em>' if main else "") + '</span>'
                     f'<small>{esc(le.PRESSURE_ZH[k])}</small></div>'
                     f'<b>{dec[k]:.2f}%</b><i class="{cls}">{_bp(dv)}</i></div>')
        mo = int(dec["month"][5:])
        chg_h = (f'{int(c1["from"][5:])}→{int(c1["to"][5:])} 月' if c1 else "變動")
        table = (f'<div class="le2-seg">{seg}</div><div class="le2-t"><div class="le2-h"><span>10Y 三段組成（{mo} 月均）</span>'
                 f'<span>水準</span><span>{chg_h}</span></div>{rows}</div>'
                 '<p class="le2-tip">點一行看白話說明</p>')
    js = ('<script>(function(){document.querySelectorAll(".le2-r[title]").forEach(function(r){'
          'r.addEventListener("click",function(){r.classList.toggle("tip-on");});});})();</script>')
    return (f'<div class="grid"><div class="card focus-card"><div class="le-hero le2">'
            f'{top}<h2 class="focus-title">{esc(title)}</h2>'
            + (f'<p class="focus-sub">{esc(sub)}</p>' if sub else "")
            + f'{table}{_evidence()}{events(L)}</div></div></div>{js}')


def _evidence() -> str:
    """首卡的「判斷依據」：三股力量各自用什麼量、為什麼這樣分。"""
    from . import focus_evidence
    steps = "".join(
        f'<div class="logic-step"><b>{esc(p)}＝{esc(zh)}</b><span>{esc(src)}</span></div>'
        for p, zh, src in (
            ("政策壓力", "預期實質路徑", "Kim-Wright 擬合殖利率 − 期限溢酬 − 預期通膨；市場對未來實質短率的平均預期"),
            ("通膨壓力", "預期通膨", "克里夫蘭聯儲 10 年預期通膨（模型值，已扣風險溢酬）"),
            ("財政與供給壓力", "期限溢酬", "Kim-Wright 10 年期限溢酬")))
    return focus_evidence(f'<div class="logic-strip">{steps}</div>'
                          '<p class="hint" style="margin-top:8px">三段一律用月均相加，剩下的差列為殘差；'
                          'TIPS 與損益兩平只當參考。本月主因＝三段中變動絕對值最大的那一段。</p>',
                          "查看三股力量怎麼量")


def events(L: dict) -> str:
    ev = L.get("events") or []
    if not ev:
        return ""
    items = "".join(f'<div class="ev"><span class="ev-d">{esc(_md(e["date"]))}</span>'
                    f'<span class="ev-k">{esc(e["kind"])}</span><span class="ev-t">{esc(_ev_text(e))}</span></div>'
                    for e in ev[:6])
    return f'<div class="evs"><div class="evs-h">接下來 4 週</div><div class="ev-grid">{items}</div></div>'


def _amt(a: dict) -> str:
    return f'{a["offering"] * 10:,.0f} 億美元' if a.get("offering") else "金額待公告"


def _ev_text(e: dict) -> str:
    return e["text"]


# ---------------------------------------------------------------------------
# 長端利率的組成
# ---------------------------------------------------------------------------
def decomp(d: dict) -> str:
    L = d.get("le") or {}
    br = L.get("bridges") or {}
    if not br:
        return '<div class="empty">拆解資料不足</div>'
    tabs = ""
    for i, k in enumerate((1, 3, 12)):
        if k not in br:
            continue
        tabs += (f'<input type="radio" name="le-br" id="le-br{k}"{" checked" if i == 0 else ""}>'
                 f'<label for="le-br{k}">{k} 個月</label>')
    panes = "".join(f'<div class="tabp p{k}">{br[k]}</div>' for k in (1, 3, 12) if k in br)
    c1 = (L.get("contrib") or {}).get(1)
    impact = ""
    if c1:
        m = c1["main"]
        lean = "hawkish" if c1["parts"][m] > 0 else "dovish"
        impact = (f'<div class="impact {lean}">{esc(L.get("main_sentence", ""))}。'
                  f'{esc(le.NATURE[m])}。</div>')
    mt = L.get("match")
    match_html = ""
    if mt:
        match_html = (f'<div class="le-match"><div class="viz-h">Fed 跟上曲線了嗎</div>'
                      f'<div class="le-mrow"><div><span>現行利率中點</span><b>{mt["r0"]:.2f}%</b></div>'
                      f'<div><span>期貨隱含 {esc(str(mt["year"]))} 年底</span><b>{mt["market_end"]:.2f}%</b>'
                      f'<em>{_bp(mt["market_bp"])}</em></div>'
                      f'<div><span>點陣圖中位數</span><b>{mt["dot_median"]:.2f}%</b>'
                      f'<em>{_bp(mt["dots_bp"])}</em></div></div>'
                      f'<div class="impact neutral">{esc(mt["verdict"])}'
                      + (f'。近 12 個月預期實質路徑 {_bp(mt["real12_bp"])}' if mt.get("real12_bp") is not None else "")
                      + '。</div></div>')
    mg = L.get("mortgage") or {}
    mort = ""
    if mg.get("value") is not None:
        mort = (f'<div class="viz-block"><div class="viz-h">名目緊縮傳到哪裡：30 年固定房貸 '
                f'{mg["value"]:.2f}%</div>'
                f'<p class="viz-sub">預期通膨推高名目利率時，實質利率沒動，但借貸成本是照名目算的。'
                f'{("近 1 年 " + _bp(mg["chg_1y"])) if mg.get("chg_1y") is not None else ""}'
                f'（Freddie Mac，週資料至 {esc(_md(mg["date"]))}）</p>{mg["chart"]}</div>')
    mr = L.get("market_ref") or {}
    ref = (f'<details data-m-collapse><summary>參考：市場口徑（TIPS 實質利率 {mr.get("real") or 0:.2f}%、'
           f'損益兩平 {mr.get("be") or 0:.2f}%）</summary>'
           '<p class="hint" style="margin-top:10px">名目 10Y − TIPS 殖利率＝損益兩平。損益兩平裡除了預期通膨，'
           '還混了通膨風險溢酬與流動性溢酬；TIPS 殖利率裡也有實質期限溢酬。所以這兩段加不出三股力量，'
           '也分不出誰是主因，這裡只當市場報價的參考。</p></details>') if mr.get("real") is not None else ""
    return f"""
    {impact}
    <div class="tabs le-tabs">{tabs}{panes}</div>
    <div class="viz-block"><div class="viz-h">三段的走勢（月均，近 24 個月）</div>
      <p class="viz-sub">同一個軸、不堆疊——預期實質路徑可能是負值，疊起來會誤導。</p>
      {L.get('dec_lines', '')}</div>
    {match_html}
    {mort}
    {ref}
    {teach(
        "把 10 年期殖利率拆成三段相加：預期實質路徑（政策）、預期通膨、期限溢酬（財政與供給），看這個月是哪一段在推。",
        "三種上升的意義不同：實質路徑上升是市場替 Fed 預先定價，Fed 還沒跟上之前不算真正的緊縮；預期通膨上升是名目緊縮、實質未收緊；期限溢酬上升則不靠 Fed 也會收緊金融條件。",
        "先看「本月主因」那一段，再看它跟 3 個月、12 個月的方向是否一致——一致才是趨勢，不一致是雜訊。")}
    <details data-m-collapse><summary>拆解方法與資料</summary>
      <dl class="gloss" style="margin-top:10px">
        <dt>期限溢酬</dt><dd>Kim-Wright 模型（聯準會理事會）的 10 年期限溢酬，FRED THREEFYTP10。</dd>
        <dt>預期通膨</dt><dd>克里夫蘭聯儲 10 年預期通膨（EXPINF10YR），模型值，已扣除通膨風險溢酬，月頻。</dd>
        <dt>預期實質路徑</dt><dd>Kim-Wright 10 年擬合殖利率 − 期限溢酬 − 預期通膨，也就是市場對未來 10 年實質短率的平均預期。</dd>
        <dt>殘差</dt><dd>實際 10 年期殖利率（附息債）與模型擬合值（零息）的差，照實列出，不分配到三段。</dd>
        <dt>為什麼用月均</dt><dd>預期通膨是月頻，三段一律用月均對齊；所以這裡的變動跟頁首的日資料變動不會完全一樣。</dd>
        <dt>注意</dt><dd>兩個模型出自不同機構，三段相加是近似；它回答「哪一段動得最多」，不是精確會計。</dd>
      </dl>
    </details>"""


# ---------------------------------------------------------------------------
# 殖利率曲線
# ---------------------------------------------------------------------------
def curve(d: dict) -> str:
    L = d.get("le") or {}
    sl = "".join(
        f'<div class="le-slope"><div class="le-sk">{esc(s["label"])}</div>'
        f'<div class="le-sv">{s["value"]:+.0f}<small>bp</small>'
        f'<span>近 1 月 {_bp(s["chg"])}</span></div>{s["chart"]}</div>'
        for s in L.get("slopes") or [])
    return f"""
    <p class="hint">現在、1 個月前、1 年前三條曲線疊在一起：長端翹起來＝期限溢酬與供給在推；整條平移＝政策預期在推。</p>
    {L.get('curve_chart', '')}
    <div class="cl-pair viz-block">{sl}</div>"""


# ---------------------------------------------------------------------------
# 全球長端
# ---------------------------------------------------------------------------
def global_(d: dict) -> str:
    g = (d.get("le") or {}).get("global") or {}
    rows = g.get("rows") or []
    if not rows:
        return '<div class="empty">資料不足</div>'
    cards = "".join(f'<div class="le-g"><span>{esc(r["name"])}</span><b>{r["value"]:.2f}%</b>'
                    f'<em>近 12 月 {_bp(r["chg12"])}</em></div>' for r in rows)
    asof = rows[0]["date"][:7].replace("-", "/")
    return f"""
    <p class="hint">期限溢酬如果是全球一起漲，原因多半是全球的財政與供給；只有美國在漲，才是美國自己的問題。</p>
    <div class="le-gs">{cards}</div>
    <div class="viz-block">{g.get('chart', '')}</div>
    <div class="src">OECD 長期利率（10 年期公債月均），經 FRED 取得，資料至 {esc(asof)}。月資料落後約一個月。</div>"""


# ---------------------------------------------------------------------------
# 債券供給：財政部＋Fed
# ---------------------------------------------------------------------------
def supply(d: dict) -> str:
    L = d.get("le") or {}
    rf = L.get("refunding") or {}
    guide = ""
    if rf:
        guide = (f'<div class="le-quote"><div class="le-qh">最新每季再融資（{esc(rf.get("date", ""))}）'
                 + (f'　·　下一次 {esc(rf.get("next", ""))}' if rf.get("next") else "")
                 + f'</div><blockquote>{esc(rf.get("guidance_en", ""))}</blockquote>'
                 f'<p>{esc(rf.get("guidance_zh", ""))}</p>'
                 + (f'<p class="hint">{esc(rf["buybacks_zh"])}</p>' if rf.get("buybacks_zh") else "")
                 + (f'<a href="{esc(rf["url"])}" target="_blank" rel="noopener">財政部原文</a>' if rf.get("url") else "")
                 + '</div>')
    # 七個天期一張表：一列一個天期，右邊是近 8 個月的迷你柱。規模幾乎不動時，
    # 七張大圖只會重複同一件事（先前「畫面很亂」的主因之一）。
    def _mini(pts):
        m = max(p["value"] for p in pts) or 1
        return "".join(f'<i style="height:{p["value"] / m * 100:.0f}%" '
                       f'data-tip="{esc(p["date"][:7].replace("-", "/"))}｜{p["value"] * 10:,.0f} 億美元"></i>'
                       for p in pts)

    def _chg(s):
        if not s.get("year_ago"):
            return "—"
        d = (s["latest"] - s["year_ago"]) * 10
        return "持平" if abs(d) < 0.5 else f"{d:+,.0f} 億"
    sizes = "".join(
        f'<div class="sz-row"><b>{esc(s["zh"])}</b><span class="sz-v">{s["latest"] * 10:,.0f}</span>'
        f'<span class="sz-c">{esc(_chg(s))}</span><span class="sz-m">{_mini(s["pts"])}</span></div>'
        for s in L.get("sizes") or [])
    sizes = (f'<div class="sz-head"><span>天期</span><span>最新一場（億美元）</span><span>對 1 年前</span>'
             f'<span>近 8 個月</span></div>{sizes}') if sizes else ""
    up = [a for a in L.get("upcoming") or [] if not a.get("frn")]
    tz = L.get("tenor_zh") or {}
    upl = "".join(
        f'<div class="le-up"><span class="ev-d">{esc(_md(a["date"]))}</span>'
        f'<b>{esc(tz.get(a["term"], a["term"]))}{" TIPS" if a.get("tips") else ""}</b>'
        f'<span>{"增發舊券" if a.get("reopening") else "新券"}</span>'
        f'<span>{_amt(a)}</span></div>'
        for a in up) or '<div class="hint">目前沒有已公告的 coupon 拍賣</div>'
    # Fed
    fp = L.get("fed_policy") or {}
    sm = L.get("soma") or {}
    mix = ""
    if sm:
        cols = ["var(--line-1)", "#12233B", "#1baf7a", "#eda100", "var(--muted-bar)"]

        def bar(m, lab):
            segs = "".join(f'<span style="flex:{p:.3f};background:{cols[i]}" data-tip="{esc(n)}｜{p:.1f}%（{v:,.0f} 十億美元）">'
                           + (f'{p:.0f}%' if p >= 6 else "") + '</span>'
                           for i, (n, v, p) in enumerate(m))
            return f'<div class="le-mix"><div class="le-mixk">{esc(lab)}</div><div class="le-mixb">{segs}</div></div>'
        leg = "".join(f'<span><i style="background:{cols[i]};width:10px;height:10px"></i>{esc(n)}</span>'
                      for i, (n, _, _) in enumerate(sm["now"]["mix"]))
        mix = (bar(sm["now"]["mix"], f'現在 {_md(sm["now"]["date"])}')
               + bar(sm["ago"]["mix"], f'1 年前 {_md(sm["ago"]["date"])}')
               + f'<div class="cl-leg">{leg}</div>')
    wm = L.get("wam") or {}
    wam_html = ""
    if wm.get("soma", {}).get("value") is not None and wm.get("market", {}).get("value") is not None:
        wam_html = (f'<div class="le-wam"><div><span>Fed 持有公債</span><b>{wm["soma"]["value"]:.1f}<small> 年</small></b>'
                    f'<em>{esc(_md(wm["soma"]["date"]))}</em></div>'
                    f'<div><span>流通在外可交易公債</span><b>{wm["market"]["value"]:.1f}<small> 年</small></b>'
                    f'<em>{esc(wm["market"]["date"][:7].replace("-", "/"))}</em></div></div>'
                    f'{wm.get("chart", "")}')
    return f"""
    <h3 class="le-h3">財政部：coupon 發行路徑</h3>
    {guide}
    <div class="le-sizes">{sizes}</div>
    <details data-m-collapse open><summary>已排程的 coupon 拍賣</summary><div class="le-ups">{upl}</div></details>
    <h3 class="le-h3">Fed：資產端與 WAM</h3>
    {f'<div class="impact neutral">{esc(fp.get("text_zh", ""))}</div>' if fp.get("text_zh") else ''}
    <div class="viz-block"><div class="viz-h">SOMA 組成：現在 vs 1 年前</div>{mix}</div>
    <div class="viz-block"><div class="viz-h">加權平均剩餘年限（WAM）</div>
      <p class="viz-sub">Fed 持有的公債比市場整體長，代表 Fed 縮短 WAM 時，長天期要由私人市場接手的比例會變高。</p>
      {wam_html}</div>
    <div class="viz-block"><div class="viz-h">MBS 到期 → 轉買 T-Bills（月變動）</div>
      {sm.get('flow_chart', '')}</div>
    {teach(
        "財政部接下來要賣多少長債、Fed 手上的公債組成往哪個方向調整。",
        "長端的供給不只看財政部發多少，也看誰在買：Fed 把到期的 MBS 換成 T-Bills、縮短持有年限，等於把長天期的風險留給私人市場。",
        "盯兩件事：再融資聲明是否改掉「維持規模」的指引，以及 Fed 與市場 WAM 的差距是否持續縮小。")}
    <div class="src">拍賣規模：TreasuryDirect　·　SOMA：紐約聯儲　·　流通在外明細：財政部 MSPD（每月）。
      WAM 由逐券到期日與面額自行計算（不含 MBS）。</div>"""


# ---------------------------------------------------------------------------
# Coupon 拍賣結果
# ---------------------------------------------------------------------------
def auctions(d: dict) -> str:
    L = d.get("le") or {}
    rows = L.get("auctions") or []
    if not rows:
        return '<div class="empty">拍賣資料本次取得失敗</div>'
    tz = L.get("tenor_zh") or {}
    rc, n = L.get("auction_recent") or {}, L.get("auction_recent_n") or 0
    head = (f'<div class="impact neutral">近 3 週 {n} 場名目 coupon 拍賣：偏弱 {rc.get("偏弱", 0)}、'
            f'中性 {rc.get("中性", 0)}、偏強 {rc.get("偏強", 0)}。</div>') if n else ""
    cards = []
    for r in rows:
        v = r["verdict"]
        cls = {"偏弱": "weak", "偏強": "strong"}.get(v, "mid")
        tail = r.get("tail_bp")
        btc, ab = r.get("btc"), r.get("avg_btc")
        bpos = None
        if btc is not None and ab is not None:
            bpos = max(0, min(100, 50 + (btc - ab) / 0.5 * 50))
        comp = (f'<div class="au-mix"><span style="flex:{r.get("indirect_pct", 0):.1f};background:var(--line-1)" '
                f'data-tip="Indirect（海外與機構）｜{r.get("indirect_pct", 0):.1f}%"></span>'
                f'<span style="flex:{r.get("direct_pct", 0):.1f};background:#1baf7a" '
                f'data-tip="Direct（國內投資人）｜{r.get("direct_pct", 0):.1f}%"></span>'
                f'<span style="flex:{r.get("dealer_pct", 0):.1f};background:var(--muted-bar)" '
                f'data-tip="Primary Dealers｜{r.get("dealer_pct", 0):.1f}%"></span></div>')
        cards.append(f"""<div class="au {cls}">
  <div class="au-h"><b>{esc(tz.get(r['term'], r['term']))}</b><span>{esc(_md(r['date']))}{'　增發' if r.get('reopening') else ''}</span>
    <span class="au-v">{esc(v)}</span></div>
  <div class="au-y">{r['high']:.3f}%<small>得標</small></div>
  <div class="au-kv"><span>Tail≈</span><b class="{'up' if (tail or 0) > 0 else 'dn'}">{_bp(tail, 1)}</b></div>
  <div class="au-kv"><span>投標倍數</span><b>{btc:.2f}</b><em>近 6 場 {ab:.2f}</em></div>
  {f'<div class="au-gauge"><i style="left:{bpos:.0f}%"></i></div>' if bpos is not None else ''}
  <div class="au-kv"><span>交易商承接</span><b>{r.get('dealer_pct', 0):.1f}%</b><em>近 6 場 {(r.get('avg_dealer') or 0):.1f}%</em></div>
  <div class="au-kv"><span>分散度</span><b>{_bp(r.get('disp_bp'), 1)}</b><em>得標 − 中位</em></div>
  {comp}
</div>""")
    leg = ('<div class="cl-leg"><span><i style="width:10px;height:10px;background:var(--line-1)"></i>Indirect（海外與機構）</span>'
           '<span><i style="width:10px;height:10px;background:#1baf7a"></i>Direct（國內投資人）</span>'
           '<span><i style="width:10px;height:10px;background:var(--muted-bar)"></i>Primary Dealers（承接剩下的）</span></div>')
    return f"""
    {head}
    <div class="aus">{''.join(cards)}</div>
    {leg}
    {teach(
        "財政部每一場長債拍賣的需求強弱：誰買了、買得多踴躍、交易商被迫接了多少。",
        "供給要有人吃得下。需求弱的拍賣會讓得標殖利率高於市場價（tail），交易商被迫承接更多，長端就得再往上找買盤。",
        "看三件事：Tail≈ 是正還是負、投標倍數比近 6 場高還是低、交易商承接比例是否偏高。連續幾場偏弱才是訊號。")}
    <details data-m-collapse><summary>判定規則與 tail 的近似</summary>
      <p class="hint" style="margin-top:10px">{esc(L.get('auction_rule', ''))}</p>
      <p class="hint">Tail 標準算法是得標殖利率減拍賣截止（下午 1 點）當下的 when-issued 殖利率，那是付費報價。
        這裡用<b>當日收盤</b>的固定期限殖利率近似，會混進 1 點之後的市場波動，所以標「≈」，只看方向與大小級距。
        「分散度」是得標殖利率減中位得標殖利率，不需要 when-issued，越大代表投標越分歧。</p>
    </details>
    <div class="src">TreasuryDirect 拍賣結果。比例的分母是競標得標量。</div>"""


# ---------------------------------------------------------------------------
# 信用利差
# ---------------------------------------------------------------------------
def credit(d: dict) -> str:
    c = (d.get("le") or {}).get("credit") or {}
    return f"""
    <p class="hint">供給增加不必然推高利率——信用利差是買方的溫度計。</p>
    <div class="stat-row">{_stats(d.get('credit_stats') or [])}</div>
    <div class="cl-pair viz-block">
      <div><div class="viz-h">投資級（IG）</div>{c.get('ig', '')}</div>
      <div><div class="viz-h">高收益（HY）</div>{c.get('hy', '')}</div>
    </div>
    <div class="src">ICE BofA 指數的選擇權調整利差（OAS），經 FRED 取得。兩者尺度差很多，所以分兩張圖。</div>"""


def _stats(items) -> str:
    from .labor import _stats as s
    return s(items)


# ---------------------------------------------------------------------------
# 科技巨頭：逐季小圖
# ---------------------------------------------------------------------------
def hs_quarters(d: dict) -> str:
    hh = (d.get("le") or {}).get("hs_hist") or []
    if not hh:
        return ""
    cards = []
    for h in hh:
        r = [x for x in h["ratio"] if x["v"] is not None]
        ratio = (f'<div class="le-hsr">最新一季資本支出佔營運現金流 <b class="{"up" if r[-1]["v"] > 100 else ""}">'
                 f'{r[-1]["v"]:.0f}%</b></div>') if r else ""
        deb = [x for x in h["ratio"] if x["debt"]]
        dtxt = ("、".join(f'{_md(x["end"])} {x["debt"] * 10:,.0f} 億' for x in deb[-3:])
                if deb else "近 8 季沒有申報長期債務發行")
        cards.append(f'<div class="le-hs"><div class="viz-h">{esc(h["name"])}</div>{ratio}{h["capex"]}'
                     f'<div class="le-hsd">發債：{esc(dtxt)}</div></div>')
    return f'<div class="le-hss">{"".join(cards)}</div>'


def guidance_stale(d: dict) -> str:
    """財報已經更新、但資本支出指引還停在上一季 → 黃色提醒。"""
    gd = d.get("guidance") or {}
    hs = d.get("hyperscalers")
    asof = gd.get("as_of") or ""
    ends = [c.get("period_end") for c in (getattr(hs, "companies", None) or []) if c.get("period_end")]
    if not asof or not ends:
        return ""
    late = max(ends)
    if late > asof:
        return (f'<div class="warnbox" style="margin-top:12px"><b>指引待更新</b>　'
                f'最新財報期末到 {esc(late)}，資本支出指引仍是 {esc(asof)} 的版本——'
                f'各家在最新一次法說會可能已經調整，請更新 <code>config/rates.yaml</code> 的 capex_guidance。</div>')
    return ""


# ---------------------------------------------------------------------------
# 指標檢核：依三股力量分組
# ---------------------------------------------------------------------------
GROUPS = [("tp", "財政與供給壓力", ("term_premium", "curve_30_10", "interest_to_revenue", "r_minus_g")),
          ("real", "政策壓力", ("real_10y", "curve_10_2")),
          ("infl", "通膨壓力", ("breakeven_10y",)),
          ("demand", "需求", ("ig_spread",))]


def lights_grouped(d: dict, card_fn) -> str:
    L = d.get("le") or {}
    c1 = (L.get("contrib") or {}).get(1)
    main = c1["main"] if c1 else None
    by = {l.key: l for l in d.get("lights") or []}
    order = sorted(GROUPS, key=lambda g: 0 if g[0] == main else 1)
    out = []
    for key, name, keys in order:
        ls = [by[k] for k in keys if k in by]
        if not ls:
            continue
        badge = '<span class="le-badge">本月主因</span>' if key == main else ""
        out.append(f'<div class="le-lg" style="--k:{len(ls)}"><div class="sig-tier">{esc(name)}{badge}</div>'
                   f'<div class="le-lgc">{"".join(card_fn(l) for l in ls)}</div></div>')
    return f'<div class="le-lgs">{"".join(out)}</div>'



# ---------------------------------------------------------------------------
# 科技巨頭（2026-10 第三版）：三個數字＋一張加總圖＋一家一列的公司表
# ---------------------------------------------------------------------------
def hs_agg_chart(d: dict) -> str:
    """五家加總：每季資本支出（柱）對營運現金流（橫線），同一個軸。"""
    agg = (d.get("le") or {}).get("hs_agg") or []
    if len(agg) < 2:
        return ""
    top = max(max(a["capex"], a["ocf"]) for a in agg) * 1.08
    cols = []
    for i, a in enumerate(agg):
        last = i == len(agg) - 1
        over = a["capex"] >= a["ocf"]
        cols.append(
            f'<div class="hs3-c{" on" if last else ""}" data-tip="{esc(a["label"])}｜資本支出 {a["capex"]:,.0f}｜'
            f'營運現金流 {a["ocf"]:,.0f}｜{a["capex"] / a["ocf"] * 100:.0f}%">'
            f'<span class="hs3-b{" over" if over else ""}" style="height:{a["capex"] / top * 100:.1f}%">'
            + '</span>'
            f'<span class="hs3-o" style="bottom:{a["ocf"] / top * 100:.1f}%">'
            + '</span>'
            f'<span class="hs3-x">{esc(a["label"])}</span></div>')
    la = agg[-1]
    latest = (f'<div class="hs3-last">最新一季（{esc(la["label"])}）：資本支出 <b>{la["capex"]:,.0f}</b>'
              f'　營運現金流 <b>{la["ocf"]:,.0f}</b>　佔 <b class="{"over" if la["capex"] > la["ocf"] else ""}">'
              f'{la["capex"] / la["ocf"] * 100:.0f}%</b></div>')
    return ('<div class="hs3-chart"><div class="hs3-ch">五家加總・每季（億美元）</div>' + latest +
            f'<div class="hs3-p">{"".join(cols)}</div>'
            '<div class="cl-leg"><span><i class="hs3-lg-b"></i>資本支出</span>'
            '<span><i class="hs3-lg-o"></i>營運現金流</span></div>'
            '<p class="hs3-note">柱子追上橫線＝本業現金不夠付資本支出，缺口要靠發債。'
            '各家會計季末不同，依「最近第幾季」對齊相加。</p></div>')


def hs_table(d: dict) -> str:
    """一家一列：本季資本支出、年增、佔營運現金流（小橫條）、單季發債、年度指引；點一列看 8 季。"""
    hs = d.get("hyperscalers")
    comps = getattr(hs, "companies", None) or []
    if not comps:
        return ""
    gd = d.get("guidance") or {}
    guide = {r["name"]: r["value"].replace(" 億美元", "") for r in gd.get("rows") or []}
    hist = {h["name"]: h for h in (d.get("le") or {}).get("hs_hist") or []}
    rows = []
    for c in comps:
        ratio = c.get("capex_to_ocf")
        yoy = "—" if c.get("capex_yoy") is None else f'{c["capex_yoy"]:+.0f}%'
        pe = c.get("period_end") or ""
        when = esc(pe) if pe else "未取自 SEC"
        bar = ""
        if ratio is not None:
            bar = (f'<span class="hs3-rb"><i class="{"over" if ratio > 100 else ""}" '
                   f'style="width:{min(ratio, 150) / 150 * 100:.1f}%"></i><u></u></span>')
        g = guide.get(c["name"]) or ("未提供" if gd.get("available") else "—")
        h = hist.get(c["name"])
        deb = [x for x in (h or {}).get("ratio", []) if x["debt"]]
        dtxt = ("、".join(f'{_md(x["end"])} {x["debt"] * 10:,.0f} 億' for x in deb[-4:])
                if deb else "近 8 季沒有申報長期債務發行")
        body = ((h["capex"] if h else "") + f'<p class="hs3-deb">發債紀錄：{esc(dtxt)}</p>')
        rows.append(
            f'<details class="hs3-r"><summary>'
            f'<span class="hs3-n"><b>{esc(c["name"])}</b><small>{when}</small></span>'
            f'<span class="hs3-v"><em>本季資本支出</em>{c["capex"] * 10:,.0f}</span>'
            f'<span class="hs3-v"><em>年增</em>{yoy}</span>'
            f'<span class="hs3-v hs3-ratio"><em>佔營運現金流</em>'
            + (f'<b class="{"over" if ratio > 100 else ""}">{ratio:.0f}%</b>' if ratio is not None else "—")
            + f'{bar}</span>'
            f'<span class="hs3-v"><em>單季發債</em>{c["issued"] * 10:,.0f}</span>'
            f'<span class="hs3-v"><em>{esc(str(gd.get("year", "")))} 年計畫</em>{esc(g)}</span>'
            f'</summary><div class="hs3-body">{body}</div></details>')
    head = ('<div class="hs3-hd"><span>公司</span><span>本季資本支出</span><span>年增</span>'
            '<span>佔營運現金流</span><span>單季發債</span>'
            f'<span>{esc(str(gd.get("year", "")))} 年資本支出計畫</span></div>')
    return (f'<div class="hs3-t">{head}{"".join(rows)}</div>'
            '<p class="hs3-note">金額單位：億美元・點一家看近 8 季資本支出與發債紀錄・'
            '佔營運現金流超過 100% 以紅字標示</p>')
