"""流動性頁的內容產生器（P7）。

首卡「Liquidity Now」只留三個趨勢訊號（SRF 動用量、SOFR−IORB、ON RRP
交易量）判斷流動性轉緊或轉鬆，版面比照通膨頁的 Inflation now：一句結論＋
一句判斷邏輯＋三格關鍵數據。其餘內容分三個獨立頁面區塊（跟其他頁面同一套
`<h2 id data-sum>` 收合卡區，不是塞在首卡裡的下拉）：
    Fed 利率走廊   SRF×利率走廊圖、五個名詞的定義、SOFR vs EFFR、RP／RRP、TGCR
    Fed 負債端結構 待補
    市場供需       Fed T-Bills 購買量、RMP 概念
"""

from __future__ import annotations

from ..site import esc
from . import teach, focus_evidence, state_chip


_LEVEL_COLOR = {"severe": "var(--critical)", "tight": "var(--serious)", "easing": "var(--pos)"}

# 利率走廊圖解：由上（名目上限）到下（名目下限）的五個名詞，各自一句定義。
_CORRIDOR_RUNGS = [
    ("SRF", "常備回購機制（名目上限）",
     "Fed 向資金緊缺的金融機構提供隔夜流動性所收取的利率；以前稱為「貼現窗口」，"
     "Fed 在這裡扮演「最後貸款人」。利率訂在走廊最上緣，機構只有在市場借不到、"
     "或市場利率貴過這裡時才會來借——所以 SRF 動用量平常該是零。"),
    ("IORB", "準備金利率（實質上限）",
     "Fed 對商業銀行存在 Fed 的準備金支付的利息。銀行不會用低於這個利率的價格"
     "把錢借給別人——借出去的利息都不如直接放在 Fed 生息，所以 IORB 是市場利率"
     "實際上很少超過的上緣。"),
    ("EFFR／SOFR", "聯邦資金有效利率／擔保隔夜融資利率",
     "EFFR 是商業銀行之間隔夜無擔保拆借的有效利率；SOFR 是金融機構之間以公債"
     "為擔保、隔夜拆借的利率。兩者正常都貼在 IORB 下方幾個基點，是整條走廊"
     "裡市場每天實際成交、最該盯著看的部分。"),
    ("ON RRP", "隔夜逆回購利率（實質下限）",
     "Fed 向有多餘現金的金融機構或貨幣市場基金，以國庫券為抵押吸收資金的隔夜"
     "利率。願意把錢借給 Fed 的一方不會接受比這更低的利率，所以 ON RRP 是"
     "市場利率實際上很少跌破的下緣。"),
]


def _flow_line(a: str, mid: str, b: str, color: str = "var(--muted)") -> str:
    box = ('font-weight:700;background:var(--surface-2);padding:3px 10px;'
          'border-radius:8px;white-space:nowrap;font-size:13px')
    return (f'<div style="display:flex;align-items:center;gap:8px;margin:4px 0">'
            f'<span style="{box}">{esc(a)}</span>'
            f'<span style="flex:1;text-align:center;color:{color};font-size:12px;'
            f'white-space:nowrap">— {esc(mid)} →</span>'
            f'<span style="{box}">{esc(b)}</span></div>')


def _repo_diagram() -> str:
    rp = (f'<div class="stat" style="text-align:left">'
         f'<div class="s-label" style="font-size:14.5px;color:var(--brand-ink)">RP（正回購）</div>'
         f'<div class="s-note" style="margin-bottom:8px">銀行抵押公債、向 Fed 借入資金——'
         f'Fed 把資金放出去，對體系是<b>注入</b>流動性。</div>'
         f'<div style="font-size:11.5px;color:var(--muted);margin:8px 0 2px">期初（Value Date）</div>'
         f'{_flow_line("銀行", "抵押公債", "Fed", "var(--muted)")}'
         f'{_flow_line("Fed", "撥付資金", "銀行", "var(--pos)")}'
         f'<div style="font-size:11.5px;color:var(--muted);margin:10px 0 2px">期末（Maturity Date）</div>'
         f'{_flow_line("銀行", "償還資金＋利息", "Fed", "var(--neg)")}'
         f'{_flow_line("Fed", "交還公債", "銀行", "var(--muted)")}'
         f'</div>')
    rrp = (f'<div class="stat" style="text-align:left">'
          f'<div class="s-label" style="font-size:14.5px;color:var(--brand-ink)">RRP（逆回購）</div>'
          f'<div class="s-note" style="margin-bottom:8px">Fed 抵押國庫券、向交易對手借出資金——'
          f'Fed 把資金收回來，對體系是<b>抽走</b>流動性。</div>'
          f'<div style="font-size:11.5px;color:var(--muted);margin:8px 0 2px">期初（Value Date）</div>'
          f'{_flow_line("Fed", "抵押國庫券", "交易對手", "var(--muted)")}'
          f'{_flow_line("交易對手", "撥付資金", "Fed", "var(--neg)")}'
          f'<div style="font-size:11.5px;color:var(--muted);margin:10px 0 2px">期末（Maturity Date）</div>'
          f'{_flow_line("Fed", "償還資金＋利息", "交易對手", "var(--pos)")}'
          f'{_flow_line("交易對手", "交還國庫券", "Fed", "var(--muted)")}'
          f'</div>')
    return f'<div class="stat-row">{rp}{rrp}</div>'


def _vol_compare(vc: dict) -> str:
    if not vc:
        return ""
    ratio = f'約 {vc["ratio"]:.0f} 倍' if vc.get("ratio") else "—"
    return (f'<div class="stat-row" style="margin:10px 0">'
           f'<div class="stat"><div class="s-label">SOFR 單日成交量</div>'
           f'<div class="s-value">{esc(vc["sofr_zh"])}</div>'
           f'<div class="s-note">{esc(vc["date"][5:].replace("-", "/"))}</div></div>'
           f'<div class="stat"><div class="s-label">EFFR 單日成交量</div>'
           f'<div class="s-value">{esc(vc["effr_zh"])}</div>'
           f'<div class="s-note">{esc(vc["date"][5:].replace("-", "/"))}</div></div>'
           f'<div class="stat"><div class="s-label">SOFR ／ EFFR</div>'
           f'<div class="s-value">{esc(ratio)}</div>'
           f'<div class="s-note">交易量比例</div></div>'
           f'</div>'
           f'<p class="hint">2008 年金融海嘯後，大型商業銀行的監管收緊，全球融資擴張因而轉向'
           f'非銀行金融機構（NBFIs，如避險基金、資產管理公司）；這些機構的融資管道主要透過'
           f'SOFR 代表的擔保回購市場，而非銀行間無擔保拆借（EFFR 的範疇）。適用對象更廣泛、'
           f'規模更大，使 SOFR 的實際成交量遠高於 EFFR——這是 SOFR 被視為比政策利率 EFFR'
           f'更能代表「市場實際成交」隔夜融資成本的原因。</p>')


def _corridor_rungs_html() -> str:
    """五個名詞由上（名目上限）到下（名目下限），點開看定義——附圖 2 的那組圖例。"""
    rows = "".join(
        f'<details class="f-more" style="border-left:3px solid var(--line-1);'
        f'margin:0 0 6px;padding-left:10px">'
        f'<summary><b>{esc(name)}</b>　{esc(sub)}</summary>'
        f'<div class="f-detail">{esc(body)}</div></details>'
        for name, sub, body in _CORRIDOR_RUNGS)
    return f'<p class="hint">由上到下點開看定義。</p>{rows}'


def _tgcr_detail(chart: str) -> str:
    chart = chart or '<div class="empty">資料不足</div>'
    return (
        '<p class="hint">TGCR 只計入「三方回購」（主要由少數清算銀行撮合、交易對手集中在'
        '大型銀行與主要交易商），是擔保隔夜融資市場裡樣本較小的工具，但也因此對資金吃緊'
        '反應得比涵蓋範圍更廣的 SOFR 更快——這是它被拿來當流動性觀察指標的原因。</p>'
        f'{chart}'
        '<p class="hint"><b>TGCR 與 SOFR 的差異：</b>SOFR 把三方回購（TGCR 的範圍）、雙邊回購'
        '與 GCF 回購都算進去，交易對手涵蓋避險基金等非銀行機構，樣本遠比 TGCR 廣，'
        '日成交量也因此遠大於 TGCR（見上方「SOFR vs EFFR」成交量對照的數量級）；'
        '兩者長期該貼得很近，一旦走開就代表某一段擔保融資管道出了狀況。</p>'
        '<p class="hint"><b>TGCR／SOFR 未來可能取代 EFFR 成為政策利率的原因：</b>EFFR 只計'
        '銀行間無擔保拆借，隨監管收緊、這塊市場規模持續萎縮，用一個交易量越來越小的利率'
        '當政策錨，代表性會越來越弱；TGCR、SOFR 代表的擔保回購市場規模大、參與者廣，'
        '更貼近當今金融體系真正的資金成本——這也是 Fed 在 2018 年後把 SOFR 推成主要'
        '參考利率的理由。</p>')


def _other_liquidity_tools() -> str:
    return (
        '<p class="hint"><b>貼現窗口（Discount Window）：</b>12 家地區聯邦準備銀行各自'
        '經營的放款窗口，對象是銀行等存款機構（不是像 SRF 那樣開放更廣泛的交易對手），'
        '主要項目「Primary Credit」只給財務狀況健全的銀行使用，利率參照聯邦資金目標'
        '區間訂定、要用合格擔保品抵押，動用沒有用途限制。它存在的目的是讓單一銀行的'
        '短期流動性缺口不會演變成被迫拋售資產或倒閉；但因為歷史上跟「這家銀行出問題」'
        '畫上等號，銀行即使真的缺錢也會盡量避免使用（所謂的「汙名化」stigma），這跟'
        'SRF 刻意設計成「不帶汙名、對所有合格交易對手開放」的常態操作正好相反。</p>'
        '<p class="hint"><b>FIMA 附買回機制（FIMA Repo Facility）：</b>對象是外國與國際'
        '貨幣當局（FIMA，各國央行、主權基金等在紐約聯儲開戶的機構），讓它們把帳上的'
        '美國公債暫時換成美元現金，到期再換回來並支付利息——用途是應付全球美元融資'
        '市場的壓力，讓這些機構不必在市場緊張時直接拋售公債換現金（那樣反而會加重'
        '公債市場的賣壓、波及美國國內的金融狀況）。換句話說，SRF 服務的是美國國內的'
        '金融機構，FIMA 服務的是海外央行，兩者用同一套「公債換現金」邏輯處理不同'
        '對象的美元荒。</p>'
        '<p class="hint"><b>央行流動性互換（Central Bank Liquidity Swaps）：</b>Fed 跟'
        '另外五家主要央行（歐洲央行、日本銀行、英格蘭銀行、加拿大銀行、瑞士央行）'
        '之間常態互設的雙邊換匯額度。運作方式是兩家央行暫時互換本國貨幣：外國央行'
        '用本國貨幣跟 Fed 換美元，再把美元撥貸給自己轄下、缺美元的銀行，到期後換'
        '回來並支付利息。市場壓力大時啟用，用意是讓美元融資壓力不必集中湧回美國'
        '公債與貨幣市場，由外國央行就近紓解自己轄下機構的美元缺口——是跟 FIMA 互補'
        '的另一條管道：FIMA 讓外國央行拿既有的公債部位換美元，換匯額度則是讓外國'
        '央行完全不需要持有美元資產也能取得美元。</p>')


def _rmp_concept() -> str:
    return (
        '<p class="hint">RMP（Reserve Management Purchases，準備金管理購買）是紐約聯儲在'
        '次級市場買回國庫券的操作，不是 QE——QE 是主動購買長期公債、擴張資產負債表、'
        '壓低長端利率來刺激經濟；RMP 則是購買短端國庫券，進行準備金水位的管理，以維持在'
        '「充裕（Ample）」水準，只用來應對季底、稅款繳納日等季節性波動。</p>'
        '<p class="hint">執行方式：透過 FedTrade Plus 系統、以多重價格標的方式，只跟一級'
        '交易商（Primary Dealers）交易；標的以 1–12 個月期的國庫券為主（1–4 個月占 75%、'
        '4–12 個月占 25%），必要時也可能納入 3 年期以內的其他公債。紐約聯儲根據流動性'
        '現況的評估，每個月中會公布當月 RMP 與 MBS 到期再投入個別的金額'
        '（<a href="https://www.newyorkfed.org/markets/domestic-market-operations/'
        'monetary-policy-implementation/treasury-securities/'
        'treasury-securities-operational-details">Treasury Securities Operational '
        'Details</a>）。</p>'
        '<p class="hint">「到期再投入國庫券」的只有機構證券（Agency Securities，即 MBS'
        '與機構債）到期收到的本金，不含公債（Treasury notes/bonds）。Fed 持有的長端公債'
        '到期後，目前仍會繼續投入、不會拿去買 Bills。</p>'
        '<p class="hint">RMP、MBS 到期再投入都是在管理 Fed 資產端的存量與到期結構——跟'
        '<a href="/rates/#supply">長端與債務「債券供給：財政部與 Fed」</a>的 WAM'
        '（加權平均到期年限）管理是同一件事的兩面：那裡看的是 Fed 持有公債的存量結構，'
        '這裡看的是每月撐住準備金水準的增量操作。</p>')


def _yi(v) -> str:
    """十億美元 → 億美元字串（台灣慣用單位，1 億＝1e8）。"""
    return "—" if v is None else f"{v * 10:,.0f} 億美元"


def _md(iso: str) -> str:
    try:
        return f"{int(iso[5:7])}/{int(iso[8:10])}"
    except (TypeError, ValueError, IndexError):
        return iso or "—"


def _upcoming_bills_html(rows) -> str:
    """已公告金額的 Bill 拍賣清單——視野通常只有一到兩週，是官方本來就還沒
    公布，不是本站漏抓。"""
    if not rows:
        return '<p class="hint">目前沒有已公告金額的 Bill 拍賣。</p>'
    items = "".join(
        f'<div style="display:flex;justify-content:space-between;gap:10px;'
        f'padding:4px 0;border-bottom:1px solid var(--grid);font-size:13.5px">'
        f'<span>{esc(_md(r["date"]))}</span><span>{esc(r["term"])}</span>'
        f'<span style="font-weight:700">{_yi(r["offering"])}</span></div>'
        for r in rows)
    return f'<div style="margin-top:6px">{items}</div>'


def _note_html(s: dict) -> str:
    """三行式備註：近 5／30 日均各一行，資料日期與時效那行字體更小、顏色更淡。"""
    lines = [esc(x) for x in (s.get("avg5"), s.get("avg30")) if x]
    asof = s.get("asof")
    html = "<br>".join(lines)
    if asof:
        asof_span = f'<span style="font-size:10px;color:var(--muted)">{esc(asof)}</span>'
        html = f"{html}<br>{asof_span}" if html else asof_span
    return html


def _method_html() -> str:
    tight = ("SRF 動用量急升、搭配 SOFR 貼近甚至超過 IORB（甚至超過 SRF 利率）"
            "→ 資金全面轉緊")
    easing = "ON RRP 交易量回升 → 機構與 MMF 手上多餘現金增加、市場流動性充裕"
    return (f'<p>{esc(tight)}；<br>{esc(easing)}</p>'
            f'<p>三者看的是近期趨勢，不是單一天的水準。</p>')


def liquidity_body(d: dict) -> str:
    v = d.get("verdict") or {}
    title = d.get("headline") or "流動性資料不足"
    sub = v.get("text") or "資料不足，暫時無法判斷流動性現況。"
    _KIND_BY_COLOR = {"var(--critical)": "hawkish", "var(--serious)": "watch", "var(--pos)": "dovish"}
    metrics = "".join(
        state_chip(s["label"], s["value"], _note_html(s),
                  _KIND_BY_COLOR.get(s.get("color"), "neutral"))
        for s in (d.get("stats") or []))

    cc = d.get("corridor_chart") or ""
    rc = d.get("reinvest_chart") or ""
    tc = d.get("tgcr_chart") or ""
    rl = d.get("reinvest_last") or {}
    si = d.get("sofr_iorb") or {}

    detail = focus_evidence(_method_html(), "查看判斷依據")

    hero = f"""<div class="grid">
  <div class="card focus-card">
    <div class="focus-eyebrow">Liquidity now</div>
    <h2 class="focus-title">{esc(title)}</h2>
    <p class="focus-sub" style="color:{_LEVEL_COLOR.get(v.get("level"), "inherit")}">{esc(sub)}</p>
    <div class="focus-grid">{metrics}</div>
    {detail}
    {teach(
        "美元貨幣市場的緊俏程度：體系準備金夠不夠用，金融機構是不是開始要跟 Fed 借錢。",
        "準備金一旦偏緊，隔夜借錢的成本會先漲（SOFR、EFFR 貼近甚至超過 IORB），機構開始"
        "動用常備回購機制（SRF）跟 Fed 借錢；這通常比股市等風險性資產更早反映流動性問題，"
        "也是 Fed 判斷該不該採取動作補充貨幣市場流動性的依據。",
        "SRF 動用量看「有沒有到不得已的程度，跟 Fed 借」；SOFR − IORB 看「借錢成本有沒有"
        "貼近甚至超過準備金利息」。兩個訊號理論上會同時出現。", learn="srf")}
  </div>
</div>"""

    _corridor_sum = f"SOFR−IORB {si['spread']:+.0f}bp" if si else "SRF 動用量 x 利率走廊"
    corridor_section = f"""<div class="grid">
  <div class="card">
    <h2 id="corridor" data-sum="{esc(_corridor_sum)}">Fed 利率走廊</h2>
    <p class="hint">SRF 動用量 x 利率走廊</p>
    {cc}
    {('<div class="src">SRF 動用量本次取得失敗，改用 FRED 後備序列（RPONTSYD）。</div>'
      if not d.get("srf_live") else "")}
    {_corridor_rungs_html()}
    <details class="f-more"><summary>SOFR vs EFFR</summary>
      <div class="f-detail">{_vol_compare(d.get("vol_compare") or {})}</div></details>
    <details class="f-more"><summary>RP（正回購）與 RRP（逆回購）</summary>
      <div class="f-detail">{_repo_diagram()}
        <p class="hint" style="margin-top:12px"><b>為什麼回購市場是當今流動性的根基：</b>
          2008 年後銀行資產負債表受限，避險基金等槓桿機構轉而大量透過回購市場融資，
          最典型的是「國庫券基差交易」——買進現貨公債、放空對應期貨鎖定價差，
          用回購市場借來的錢支應現貨部位、賺取槓桿後的微小價差。這類交易規模已達
          數千億美元，一旦回購市場流動性抽緊（例如 2019 年 9 月的回購利率飆升），
          這些槓桿部位被迫平倉會反過來重創公債市場本身——這是回購市場的管線
          從「後台技術」變成系統性風險觀察重點的原因。</p></div></details>
    <details class="f-more"><summary>TGCR（三方一般擔保利率）</summary>
      <div class="f-detail">{_tgcr_detail(tc)}</div>
    </details>
    <details class="f-more"><summary>其他流動性管理工具</summary>
      <div class="f-detail">{_other_liquidity_tools()}</div>
    </details>
  </div>
</div>"""

    liabilities_section = """<div class="grid">
  <div class="card">
    <h2 id="liabilities" data-sum="內容製作中">Fed 負債端結構</h2>
    <p class="hint">內容製作中。</p>
  </div>
</div>"""

    _supply_sum = (f'最新一期 RMP {_yi(rl.get("rmp"))}' if rl else "Fed T-Bills 購買量")
    bo = d.get("bill_overview") or {}
    supply_section = f"""<div class="grid">
  <div class="card">
    <h2 id="supply_demand" data-sum="{esc(_supply_sum)}">市場供需</h2>
    <p class="hint">財政部 T-Bills 發行時程{
      (f'　·　占整體發行量 <b>{bo["share"]:.0f}%</b>' if bo.get("share") is not None else "")}</p>
    {d.get("bill_trend_chart") or ""}
    {_upcoming_bills_html(d.get("upcoming_bills") or [])}
    <details class="f-more"><summary>T-Bills 占比怎麼看</summary>
      <div class="f-detail">比例越高，代表財政部越依賴短端融資；對照
      <a href="/rates/#supply">長端與債務頁「債券供給：財政部與 Fed」</a>的 Coupon 發行路徑。</div>
    </details>

    <p class="hint" style="margin-top:18px">Fed T-Bills 購買量</p>
    {rc}
    {(f'<div class="src">最新一期（{esc(rl.get("period", ""))}）：'
      f'RMP {_yi(rl.get("rmp"))}　MBS 到期再投入 {_yi(rl.get("mbs"))}　'
      f'合計 {_yi(rl.get("total"))}。</div>'
      if rl else "")}
    <details class="f-more"><summary>RMP（準備金管理購買）</summary>
      <div class="f-detail">{_rmp_concept()}</div></details>

    <p class="hint" style="margin-top:18px">Fed vs 私人市場</p>
    {d.get("bill_flows_chart") or ""}
    <details class="f-more"><summary>私人市場融資怎麼算</summary>
      <div class="f-detail">毛發行量減掉 Fed RMP 與 MBS 再投入買走的部分，剩下才是財政部短端
      融資真正需要貨幣市場吸收的量。時間段跟著 Fed RMP 的公布期別走；還在進行中的最後一期，
      連同更晚已公告的拍賣，合併列成一塊「已公告、Fed 分配未知」（單一顏色），不假裝知道
      Fed 會分走多少。</div>
    </details>
  </div>
</div>"""

    main = hero + corridor_section + liabilities_section + supply_section
    return main


def liquidity_footer(d: dict) -> str:
    from ..site import source_footer
    return source_footer(
        [("SOFR／EFFR／IORB／ON RRP 利率、TGCR", "FRED（紐約聯儲、聯準會理事會）", "每日"),
         ("SOFR／EFFR 官方成交量", "紐約聯儲 Reference Rates API", "每日"),
         ("SRF 動用量（常備回購機制）", "紐約聯儲逐日操作結果；FRED（RPONTSYD）後備", "每日"),
         ("ON RRP 餘額", "FRED（RRPONTSYD）", "每日"),
         ("Fed T-Bills 購買量：RMP、MBS 到期再投入", "紐約聯儲 Treasury Securities "
          "Operational Details（計畫金額，逐期公布）", "每期（約一個月）"),
         ("T-Bills 發行時程與已公告拍賣", "TreasuryDirect（已完成拍賣＋已公告的即將拍賣）",
          "拍賣前幾天公布金額")],
        ["三個趨勢訊號（近 5 日均 vs 近 30 日均）：SRF 動用量升溫、SOFR−IORB 走闊、"
         "ON RRP 交易量回升。SOFR 衝出 SRF 利率（走廊上限）視為最嚴重的轉緊訊號。",
         "RMP、MBS 到期再投入兩個金額直接來自紐約聯儲官方逐期公布的拆分，不是本站"
         "推算的估計值；是計畫金額，可能跟實際成交有落差。再投入只適用 MBS（機構"
         "證券），不含長端公債——公債到期後直接從資產負債表消失，不會被拿去買回 Bills。",
         "私人市場融資＝T-Bills 毛發行量減掉 Fed RMP 與 MBS 再投入買走的部分；"
         "最新一期之後 Fed 分配未知，只列財政部已公告的毛發行量。"],
        head="<b>資料來源</b> 紐約聯儲、財政部 TreasuryDirect、FRED")
