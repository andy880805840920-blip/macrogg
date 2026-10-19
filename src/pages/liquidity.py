"""流動性頁的內容產生器（P7）。

首卡「Liquidity Now」只留三個趨勢訊號（SRF 動用量、SOFR−IORB、ON RRP
交易量）判斷流動性轉緊或轉鬆，版面比照通膨頁的 Inflation now：一句結論＋
一句判斷邏輯＋三格關鍵數據。其餘內容分三個獨立頁面區塊（跟其他頁面同一套
`<h2 id data-sum>` 收合卡區，不是塞在首卡裡的下拉）：
    Fed 利率走廊   SRF×利率走廊圖、五個名詞的定義、SOFR vs EFFR、RP／RRP、TGCR
    Fed 負債端結構 H.4.1 四大項（貨幣、準備金、TGA、RRP）＋白話定義
    市場供需       T-Bills 淨發行（Fed vs 私人市場）、Fed T-Bills 購買量、RMP 概念
"""

from __future__ import annotations

import re

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
            f'<span class="rp-flow-mid" style="color:{color}">— {esc(mid)} →</span>'
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
    return f'<div class="stat-row rp-row">{rp}{rrp}</div>'


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


def _sgn_yi(v) -> str:
    """十億美元 → 帶正負號的億美元字串。"""
    return "—" if v is None else f"{v * 10:+,.0f} 億美元"


def _bill_net_stats(last, mtd, qra) -> str:
    cells = []
    if last:
        cells.append(f'<div class="stat"><div class="s-label">{esc(last["period"])} 淨發行</div>'
                     f'<div class="s-value">{esc(_sgn_yi(last["net"]))}</div>'
                     f'<div class="s-note">私人市場 {esc(_sgn_yi(last["private"]))}</div>'
                     f'<div class="s-note">Fed 買下 {esc(_yi(last["fed"]))}</div></div>')
    if mtd:
        cells.append(f'<div class="stat"><div class="s-label">{esc(mtd["month"].replace("-", "/"))} 月初至今</div>'
                     f'<div class="s-value">{esc(_sgn_yi(mtd["net"]))}</div>'
                     f'<div class="s-note">私人市場 {esc(_sgn_yi(mtd["private"]))}</div>'
                     f'<div class="s-note">DTS 至 {esc(_md(mtd["end"]))}</div></div>')
    if qra:
        cells.append(f'<div class="stat"><div class="s-label">{esc(qra["quarter"][:7])} QRA 隱含</div>'
                     f'<div class="s-value">{esc(_sgn_yi(qra["bills"]))}</div>'
                     f'<div class="s-note">整季、未計買回</div>'
                     f'<div class="s-note">本站推算</div></div>')
    return f'<div class="stat-row">{"".join(cells)}</div>' if cells else ""


def _bill_net_method(rows, qra) -> str:
    tbl = "".join(
        f'<tr><td>{esc(r["period"])}</td><td>{r["net"] * 10:+,.0f}</td>'
        f'<td>{r["rmp"] * 10:,.0f}</td><td>{r["mbs"] * 10:,.0f}</td>'
        f'<td><b>{r["private"] * 10:+,.0f}</b></td></tr>'
        for r in reversed(rows))
    q = ""
    if qra:
        q = (f'<p class="hint"><b>未來：</b>財政部 {esc(qra["date"][5:].replace("-", "/"))} 公布 {esc(qra["quarter"])}'
             f'私人持有淨借款 {qra["borrowing"] * 10:,.0f} 億美元（假設季末現金 {qra["cash_end"] * 10:,.0f} 億）。'
             f'本站以暫定拍賣排程 × 現行規模推算本季 coupon 毛發行約 {qra["gross_coupon"] * 10:,.0f} 億、'
             f'私人持有到期約 {qra["coupon_maturing"] * 10:,.0f} 億，coupon 淨發行約 {qra["net_coupon"] * 10:,.0f} 億，'
             f'剩下約 <b>{qra["bills"] * 10:,.0f} 億</b>要靠 T-Bills。買回的舊券也由新發行補上，'
             f'所以實際 T-Bills 淨發行會再加上本季買回金額。下一次再融資 {esc(_md(qra.get("next", "")))}，'
             f'<a href="{esc(qra["url"])}" target="_blank" rel="noopener">財政部原文</a>。</p>')
    return (f'<p class="hint">財政部每週發行的 T-Bills 毛額超過 4,000 億美元，但大部分只是償還同週到期的舊券；'
            f'真正新增的供給是<b>發行 − 到期贖回</b>，也就是月底 Bills 存量的變化。'
            f'再扣掉 Fed 在次級市場實際買走的量（RMP＋MBS 到期再投入），剩下才是私人市場（貨幣基金、'
            f'銀行、海外等）要淨吸收的量。4 月、9 月等稅收月財政部現金充裕，淨發行常是負的，'
            f'這時私人市場是拿回現金的一方。</p>'
            f'<p class="hint">Fed 的實際成交只公布總額；RMP／MBS 的拆分依該筆購買所在期別的官方計畫金額比例分配。'
            f'日曆月口徑，跟上方 Fed 計畫金額的期別（例如 10/15–11/13）不同。</p>'
            f'<div class="tscroll"><table><thead><tr><th>月份</th><th>淨發行</th><th>Fed RMP</th>'
            f'<th>Fed MBS</th><th>私人市場</th></tr></thead><tbody>{tbl}</tbody></table></div>'
            f'<p class="hint">單位：億美元。</p>{q}')


# 這兩項以兆美元顯示（規模都在 2–3 兆，億美元的五位數不好讀）
_TRILLION = ("currency", "reserves")


def _liab_value(it: dict, short: bool = False) -> str:
    if it["key"] in _TRILLION:
        return f'{it["value"] / 1000:,.2f} 兆' + ("" if short else "美元")
    return f'{it["value"] * 10:,.0f} 億' + ("" if short else "美元")


def _liab_note(it: dict, qra: dict | None, source: str) -> str:
    """最新值下方：1 個月前、半年前的水位與淨變化（小字）；資料日期（更小字）。"""
    lines = []
    for tag, name in (("m1", "1 個月前"), ("m6", "半年前")):
        r = it.get(tag)
        if r:
            if it["key"] in _TRILLION:
                # 水位用兆，淨變化仍用億——幾十億的週變化換成兆只剩 +0.01，看不出大小
                lines.append(f'{name} {r["value"] / 1000:,.2f} 兆（{r["chg"] * 10:+,.0f} 億）')
            else:
                lines.append(f'{name} {r["value"] * 10:,.0f}（{r["chg"] * 10:+,.0f}）')
    if it["key"] == "tga" and qra and qra.get("cash_end") is not None:
        mo = int((qra.get("cash_end_date") or "0000-12")[5:7])
        lines.append(f'QRA {mo} 月底目標 {qra["cash_end"] * 10:,.0f}'
                     f'（差 {(qra["cash_end"] - it["value"]) * 10:+,.0f}）')
    if it["key"] == "rrp":
        lines.append(f'國內 ON RRP {it["dom"] * 10:,.0f}｜國外 {it["for"] * 10:,.0f}')
    asof = f'資料 {_md(it["date"])}' + ("" if source in ("", "H.4.1") else f"・{source}")
    return ("<br>".join(esc(x) for x in lines)
            + f'<br><span style="font-size:10px;color:var(--muted)">{esc(asof)}</span>')


def _small(txt: str) -> str:
    return f'<span style="font-size:10px;color:var(--muted)">{esc(txt)}</span>'


def _ratio_cells(v: dict) -> str:
    if not v:
        return '<div class="empty">H.4.1／H.8 資料本次取得失敗</div>'
    lines = []
    for tag, name in (("m1", "1 個月前"), ("m6", "半年前")):
        r = v.get(tag)
        if r:
            lines.append(f'{name} {r["value"]:.2f}%（{r["chg"]:+.2f} 個百分點）')
    note = "<br>".join(esc(x) for x in lines) + "<br>" + _small(f'資料 {_md(v["date"])}（H.8 比 H.4.1 晚約一週）')
    cells = state_chip("準備金 ÷ 商業銀行總資產", f'{v["value"]:.2f}%', note,
                       "watch" if v.get("below_alert") else "neutral")
    lo = v.get("low2019")
    if lo:
        cells += state_chip("2019 年最低", f'{lo["ratio"]:.2f}%',
                            esc(f'{lo["date"][:4]}/{_md(lo["date"])} 當週') + "<br>"
                            + esc(f'距警戒線 {v["alert"]:.0f}%：目前高 {v["value"] - v["alert"]:+.2f} 個百分點'),
                            "neutral")
    return f'<div class="focus-grid liab-grid">{cells}</div>'


_REGIME_ZH = (("abundant", "充裕（Abundant）"), ("ample", "充足（Ample）"), ("scarce", "稀缺（Scarce）"))


def _rde_cells(v: dict) -> str:
    if not v:
        return '<div class="empty">紐約聯儲 RDE 資料本次取得失敗</div>'
    lines = []
    for tag, name in (("m1", "1 個月前"), ("m6", "半年前")):
        r = v.get(tag)
        if r:
            lines.append(f'{name} {r["value"]:+.2f}（{r["chg"]:+.2f}）')
    lines.append(f'95% 信賴區間 {v["lo95"]:+.2f} ～ {v["hi95"]:+.2f}')
    rel = re.sub(r"^.*?ET\s*", "", v.get("release") or "")
    note = ("<br>".join(esc(x) for x in lines) + "<br>"
            + _small(f'估計日 {_md(v["date"])}・紐約聯儲 {rel} 發布（每月更新）'))
    cells = state_chip("準備金需求彈性（RDE）", f'{v["value"]:+.2f}', note, "neutral")
    verdict = next((zh for en, zh in _REGIME_ZH
                    if any(en in b.lower() for b in (v.get("bullets") or [])[1:2])), "")
    sig = ("統計上與 0 無差異：利率對準備金變動不敏感" if v.get("zero_in_ci")
           else "顯著為負：利率已開始對準備金變動有反應")
    cells += state_chip("紐約聯儲判讀", verdict or "—",
                        esc(sig) + "<br>" + _small(v.get("update") or ""), "neutral")
    return f'<div class="focus-grid liab-grid">{cells}</div>'


def _demand_curve_svg() -> str:
    """示意的準備金需求曲線：x＝準備金供給，y＝聯邦資金利率；三個區段＋同樣的供給減少在兩端造成的利率變化。"""
    import math
    W, H, x0, y0 = 640, 240, 48, 200
    f = lambda x: 200 - 140 / (1 + math.exp((x - 190) / 38))   # x：48–620
    pts = " ".join(f"{x},{f(x):.1f}" for x in range(x0, 621, 4))
    reg = [(x0, 250, "稀缺 Scarce", "var(--neg)"), (250, 420, "充足 Ample", "var(--muted-bar)"),
           (420, 620, "充裕 Abundant", "var(--pos)")]
    bands = "".join(f'<rect x="{a}" y="16" width="{b - a}" height="{y0 - 16}" fill="{c}" opacity=".10"/>'
                    f'<text x="{(a + b) / 2}" y="34" text-anchor="middle" font-size="13" font-weight="700" '
                    f'fill="var(--text-primary)">{t}</text>' for a, b, t, c in reg)

    def shift(xa, xb, lab, ly):
        ya, yb = f(xa), f(xb)
        return (f'<line x1="{xa}" y1="{y0}" x2="{xa}" y2="{ya:.1f}" stroke="var(--text-secondary)" stroke-dasharray="3 3"/>'
                f'<line x1="{xb}" y1="{y0}" x2="{xb}" y2="{yb:.1f}" stroke="var(--text-secondary)" stroke-dasharray="3 3"/>'
                f'<circle cx="{xa}" cy="{ya:.1f}" r="4" fill="var(--line-2)"/>'
                f'<circle cx="{xb}" cy="{yb:.1f}" r="4" fill="var(--line-1)"/>'
                f'<text x="{(xa + xb) / 2}" y="{ly}" text-anchor="middle" font-size="11.5" '
                f'fill="var(--text-secondary)">{lab}</text>')
    return (f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="準備金需求曲線示意圖" '
            f'style="max-width:680px;display:block;margin:8px auto">'
            f'{bands}'
            f'<line x1="{x0}" y1="{y0}" x2="626" y2="{y0}" stroke="var(--text-secondary)"/>'
            f'<line x1="{x0}" y1="16" x2="{x0}" y2="{y0}" stroke="var(--text-secondary)"/>'
            f'<polyline points="{pts}" fill="none" stroke="var(--line-1)" stroke-width="3"/>'
            + shift(170, 210, "準備金少一點 → 利率大跳", 64)
            + shift(500, 540, "準備金少一點 → 利率幾乎不動", 168)
            + f'<text x="337" y="226" text-anchor="middle" font-size="12" fill="var(--text-secondary)">'
              f'準備金供給（右邊＝越多）</text>'
              f'<text x="14" y="108" text-anchor="middle" font-size="12" fill="var(--text-secondary)" '
              f'transform="rotate(-90 14 108)">聯邦資金利率</text></svg>')


def _rmp_status(d: dict) -> str:
    """RMP 現況一句話（跟著紐約聯儲最新一期公布走）。"""
    rl, since = d.get("rmp_last") or {}, d.get("rmp_paused_since") or ""
    if not rl:
        return ""
    per = f'{_md(rl.get("start", ""))}–{_md(rl.get("end", ""))}'
    if since:
        return (f'<p><b>RMP 現況：</b>自 {_md(since)} 起的那一期暫停 RMP，最新一期（{per}）只有 MBS 到期再投入 '
                f'{rl.get("mbs", 0) * 10:,.0f} 億美元——代表 Fed 暫時不認為需要額外補準備金。</p>')
    return (f'<p><b>RMP 現況：</b>最新一期（{per}）RMP {rl.get("rmp", 0) * 10:,.0f} 億美元，'
            f'加上 MBS 到期再投入 {rl.get("mbs", 0) * 10:,.0f} 億美元。</p>')


def _reserve_adequacy(d: dict) -> str:
    rv, dv = d.get("ratio_view") or {}, d.get("rde_view") or {}
    lo, s19 = rv.get("low2019") or {}, dv.get("sep2019") or {}
    ratio_txt = f"""
      <p><b>定義：</b>銀行存在 Fed 的準備金（H.4.1 週三水位）÷ 全體商業銀行總資產（H.8，季調週資料）。
      看的是銀行資產裡有多少是「隨時能拿來付款清算」的最高流動性資產。用比例而不用絕對金額，是因為銀行體系規模每年在長大，
      同樣 3 兆美元的準備金，在 17 兆資產和 26 兆資產的銀行體系裡，寬鬆程度完全不同；紐約聯儲估算 RDE 也是用同一個分母。</p>
      <p><b>判斷邏輯：</b>比例越低，銀行手上的「緩衝現金」越薄，越容易為了湊足每日清算需要的準備金而互相搶錢。
      2019 年 9 月回購危機發生時，這個比例一度降到 10% 以下（週資料最低 {lo.get("ratio", 0):.1f}%，{lo.get("date", "")[:4]}/{_md(lo.get("date", ""))} 當週）：
      9/16 企業季中繳稅與公債交割同時抽走大量準備金，9/17 SOFR 從 2% 出頭一天跳到 5.25%，Fed 被迫重啟回購操作注資，
      之後再開始買國庫券把準備金補回來。紐約聯儲的研究也發現，比例高於約 13% 時（2012–17 年、2020 年中以後）RDE 幾乎是 0。
      所以實務上：<b>13% 以上很寬鬆、10%–13% 要開始留意、10% 以下就是 2019 年那種危險區</b>。</p>"""
    verdict = next((zh for en, zh in _REGIME_ZH
                    if any(en in b.lower() for b in (dv.get("bullets") or [])[1:2])), "")
    rde_txt = f"""
      <p><b>定義：</b>RDE 是紐約聯儲估計的「準備金需求曲線斜率」：當準備金增加相當於銀行總資產 1% 時，
      聯邦資金利率相對 IORB 的利差會變動幾個 bp（單位：bp／百分點）。數值接近 0＝準備金多到利率不在乎增減；
      負得越深＝曲線越陡，準備金少一點點，借錢成本就會明顯上升。紐約聯儲每月第三個週四更新，檔內是約每 5 個營業日一筆的即時估計。</p>
      <p><b>判斷邏輯：</b>同時看數值與信賴區間。中位數接近 0、95% 信賴區間包含 0 → 準備金充裕；
      持續為負且區間不含 0 → 已進入充足區、往稀缺靠近。2019 年 9 月回購危機前後，RDE 降到約 {s19.get("median", 0):.2f}
      （當年最低 {(dv.get("low2019") or {}).get("median", 0):.2f}，{_md((dv.get("low2019") or {}).get("date", ""))}），95% 信賴區間整段都在 0 以下——
      準備金已經進入曲線陡峭的那一段，所以一次繳稅加公債交割就足以讓回購利率暴衝。
      目前 RDE {dv.get("value", 0):+.2f}，信賴區間 {dv.get("lo95", 0):+.2f} ～ {dv.get("hi95", 0):+.2f}；紐約聯儲本月判讀為「{verdict or "—"}」。</p>
      <p><b>三種準備金狀態</b>（下圖是示意的準備金需求曲線，橫軸是準備金供給、縱軸是聯邦資金利率）：</p>
      {_demand_curve_svg()}
      <dl class="gloss">
        <dt>稀缺（Scarce）</dt><dd>曲線最陡的左段。銀行手上準備金不夠，供給少一點利率就大漲、多一點就大跌，
          Fed 必須每天用公開市場操作精準調整準備金數量，才能把利率壓在目標上——這是 2008 年以前的做法，也是 2019 年 9 月差點滑進去的區域。</dd>
        <dt>充足（Ample）</dt><dd>曲線開始變平但還有一點斜度的中段。準備金的日常增減（繳稅、TGA 進出）只會讓利率小幅移動，
          Fed 不需要每天調整準備金，只要設定 IORB、ON RRP 等「行政利率」就能把政策利率控制在目標區間內。</dd>
        <dt>充裕（Abundant）</dt><dd>曲線完全平坦的右段。銀行對準備金的需求已經飽和，供給增減對利率幾乎沒有影響；
          利率控制最穩，但代價是 Fed 的資產負債表很大，持有大量公債與 MBS（期限風險、對市場的影響、政治上的質疑）。</dd>
      </dl>
      <p><b>Fed 目前的政策框架：</b>維持準備金在<b>充足（Ample）</b>的水準——「充足準備金框架」（ample reserves framework）：
      準備金多到利率不受日常波動影響，靠行政利率就能控制政策利率，但不需要多到充裕區那麼大的資產負債表。
      問題是準備金不會自己停在原地：流通在外貨幣、TGA 這些其他負債會隨經濟與財政規模長期成長，每成長一塊就從準備金抽走一塊。
      縮表結束後如果什麼都不做，準備金會慢慢從充足滑向稀缺，重演 2019 年的情況。
      所以 Fed 在 2025 年 12 月停止縮表後，改做<b>準備金管理購買（RMP）</b>：在次級市場買國庫券，補上被其他負債吃掉的準備金，
      讓準備金停在充足區——目的不是像 QE 那樣壓低長期利率，而是維持貨幣市場的運作（見下方「市場供需」的 RMP 說明）。</p>
      {_rmp_status(d)}"""
    return f"""<details class="f-more"><summary>準備金 ÷ 商業銀行總資產</summary><div class="f-detail">
      {_ratio_cells(rv)}
      <div class="viz-block"><div class="viz-h">近 15 年（%，週）</div>{d.get("ratio_chart") or ""}</div>
      {ratio_txt}
      <p class="hint">準備金：Fed 理事會 H.4.1；總資產：H.8 全體商業銀行（季調，B1151NCBA）。</p>
    </div></details>
    <details class="f-more"><summary>準備金需求彈性（RDE）</summary><div class="f-detail">
      {_rde_cells(dv)}
      <div class="viz-block"><div class="viz-h">近 15 年（bp／百分點，中位數估計）</div>{d.get("rde_chart") or ""}</div>
      {rde_txt}
      <p class="hint">紐約聯儲 Reserve Demand Elasticity（Afonso、Giannone、La Spada、Williams 方法）。</p>
    </div></details>"""


def _mmf_cells(v: dict, bills_out: float | None) -> str:
    L = (v or {}).get("latest")
    if not L:
        return '<div class="empty">SEC MMF 統計本次取得失敗</div>'
    a, f, y = L["assets"], L["flows"], L["yields"]
    mo = L["month"].replace("-", "/")
    sm = lambda t: _small(t)
    gov_all = (a.get("gov") or 0) + (a.get("treasury") or 0)
    c1 = state_chip("MMF 總資產", f'{(a.get("total") or 0) / 1000:,.2f} 兆美元',
                    esc(f'Government {(a.get("gov") or 0) / 1000:.2f} 兆｜Treasury {(a.get("treasury") or 0) / 1000:.2f} 兆')
                    + "<br>" + esc(f'Prime {(a.get("prime") or 0) * 10:,.0f} 億｜政府型占 {gov_all / (a.get("total") or 1) * 100:.0f}%')
                    + "<br>" + sm(f"資料 {mo}（SEC，月）"), "neutral")
    c2 = state_chip(f"{int(L['month'][5:])} 月淨流量", f'{(f.get("total") or 0) * 10:+,.0f} 億美元',
                    esc(f'Government {(f.get("gov") or 0) * 10:+,.0f}｜Treasury {(f.get("treasury") or 0) * 10:+,.0f}')
                    + "<br>" + esc(f'Prime {(f.get("prime") or 0) * 10:+,.0f}｜Tax Exempt {(f.get("taxex") or 0) * 10:+,.0f}')
                    + "<br>" + sm(f"資料 {mo}（申購 − 贖回）"), "neutral")
    c3 = state_chip("7 日淨收益率（Government）", f'{y.get("gov", 0):.2f}%',
                    esc(f'Treasury {y.get("treasury", 0):.2f}%｜Prime {y.get("prime", 0):.2f}%')
                    + "<br>" + sm(f"資料 {mo}（資產加權，扣費後）"), "neutral")
    sp = L.get("spread")
    c4 = state_chip("比銀行存款多賺", f'{sp:+.2f} 個百分點' if sp is not None else "—",
                    esc(f'FDIC 全國儲蓄存款利率 {L["fdic"]:.2f}%' if L.get("fdic") is not None else "FDIC 資料缺")
                    + "<br>" + sm(f"資料 {mo}（Government MMF − 儲蓄存款）"), "neutral")
    return f'<div class="focus-grid liab-grid">{c1}{c2}{c3}{c4}</div>'


def _mmf_explain(v: dict, bills_out: float | None) -> str:
    h = (v or {}).get("hold_last") or {}
    hold_txt = ""
    if h:
        hold_txt = (f'以 {h["month"].replace("-", "/")} 為例，MMF 持有美國公債 {h["treasury"] / 1000:.2f} 兆美元'
                    + (f'（同期流通在外 T-Bills {bills_out / 1000:.2f} 兆）' if bills_out else "")
                    + f'，借出回購 {h["repo"] / 1000:.2f} 兆美元，其中放在 Fed ON RRP 的只剩 {h["rp_fed"] * 10:,.0f} 億。')
    items = [
        ("為什麼 MMF 是貨幣市場最重要的參與者",
         f"<p>MMF 把企業、個人與機構的閒置現金集中起來，只能投資期限很短、信用很高的資產：T-Bills、隔夜與短期回購、"
         f"銀行 CD 與商業本票，以及 Fed 的 ON RRP。這讓它同時是<b>T-Bills 最大的買家</b>和<b>回購市場最大的現金借出方</b>。"
         f"{esc(hold_txt)}</p>"
         f"<p>所以 MMF 的錢往哪裡走，就決定了貨幣市場哪裡有錢：MMF 把錢從 ON RRP 移去買 T-Bills 或借給交易商，"
         f"等於把「閒置在 Fed 的錢」送回市場；反過來，MMF 被贖回或集體縮手，交易商在回購市場就借不到錢，"
         f"SOFR 會被推高，甚至要轉向 Fed 的 SRF。</p>"),
        ("三種 MMF：Treasury、Government、Prime",
         "<dl class=\"gloss\"><dt>Treasury MMF</dt><dd>幾乎只投資美國公債與以公債為擔保的回購，最保守，T-Bills 供給變化對它的影響最直接。</dd>"
         "<dt>Government MMF</dt><dd>至少 99.5% 投資政府證券（公債、機構債）、現金與以這些為擔保的回購，是目前規模最大的一類，"
         "也是 ON RRP 與 FICC 集中清算回購的主要參與者。（SEC 統計裡的 Government 不含 Treasury，兩者分開列。）</dd>"
         "<dt>Prime MMF</dt><dd>可以買銀行 CD、商業本票等民間短期債務，收益率較高但有信用風險；"
         "機構型 Prime 在壓力時期會被大量贖回（2008 年、2020 年 3 月），是銀行短期美元融資的重要來源。</dd></dl>"),
        ("怎麼從這些數據判斷",
         "<p><b>資金流向：</b>持續淨流入代表市場上有更多現金要找短期出路，回購與 T-Bills 需求穩健；"
         "4、6、9、12 月的報稅日前後常見淨流出（企業提款繳稅），這時 MMF 的回購放款縮手，SOFR 容易季節性走高。</p>"
         "<p><b>收益率 vs 銀行存款：</b>MMF 收益率幾乎跟著政策利率即時變動，銀行存款利率調得又慢又少。"
         "升息循環裡兩者差距拉大，錢從銀行流向 MMF；降息時 MMF 收益率先降、差距收窄，流入就會放緩——"
         "差距收窄到接近 0 時，MMF 的資金來源就可能轉為流出。</p>"
         "<p><b>政策預期：</b>市場預期降息時，MMF 會拉長持有期限（買較長的 T-Bills、定期回購）鎖住收益，"
         "隔夜回購的現金供給變少；預期升息或不確定時則縮短期限，偏好隔夜回購與 ON RRP。"
         "上方的加權平均到期天數（WAM）就是這個態度的量化：法規上限 60 天，"
         "2022 年 Fed 快速升息時，Government MMF 的 WAM 從年初約 30 天一路縮到 2023 年 1 月的 9 天；"
         "2023 年下半年市場判斷升息到頂，WAM 又拉回 30 天以上，提前鎖住高利率。"
         "看的是方向與變化速度：連續幾個月拉長＝押注降息，快速縮短＝防範升息或不確定性升高。</p>"
         "<p><b>風險偏好：</b>Prime 資產與流量的變化反映投資人對信用風險的胃口；壓力時期錢會從 Prime 逃向 Government／Treasury，"
         "銀行的 CD 與商業本票融資跟著收緊。</p>"
         "<p><b>部位配置：</b>看回購的交易對手——ON RRP 幾乎歸零代表緩衝已用完，MMF 的每一塊錢都已經在市場上；"
         "FICC 集中清算回購快速增加，則反映 SEC 公債集中清算新規逐步上路，回購交易往清算所集中。"
         "季底外國銀行為了美化資產負債表縮減回購借款，MMF 的現金會暫時回流 ON RRP。</p>"),
    ]
    return "".join(f'<details class="f-more"><summary>{esc(t)}</summary><div class="f-detail">{b}</div></details>'
                   for t, b in items)


def _ym(m: str) -> str:
    return f"{m[:4]}/{int(m[5:7])}"


def _last_n(d: dict, n: int) -> list:
    return list((d or {}).items())[-n:]


def _split_label(label: str) -> str:
    """「SOFR − IORB（近 5 日均）」→ 主標＋小字副標，避免窄欄裡括號斷在奇怪的位置。"""
    if "（" in label and label.endswith("）"):
        main, sub = label[:-1].split("（", 1)
        return f"<b>{esc(main)}</b><small>{esc(sub)}</small>"
    return f"<b>{esc(label)}</b>"


def _core_detail(d: dict) -> str:
    """核心三指標的下拉補充：三個問題一張表，再用三個勾叉推到結論。"""
    L = {l.key: l for l in d.get("liq_lights") or []}
    T = d.get("liq_trend") or {}
    vd = d.get("liq_verdict") or {}

    def peak(k, fmt):
        s = T.get(k) or {}
        if not s:
            return "—"
        m, v = max(s.items(), key=lambda kv: kv[1])
        return f"{_ym(m)} {fmt(v)}"
    si = T.get("sofr_iorb") or {}
    si_recent = "、".join(f"{int(m[5:])}月 {v:+.1f}" for m, v in _last_n(si, 3))
    rr = T.get("rrp") or {}
    since = ""
    for m, v in reversed(list(rr.items())):
        if v >= 100:
            break
        since = m
    srf_now = L["srf"].value if L.get("srf") else None
    srf_note = (f"近 5 日均 {srf_now * 10:,.0f} 億，有機構在向 Fed 借錢" if (srf_now or 0) > 0.05
                else "近期未動用")
    rrp_now = L["rrp"].value if L.get("rrp") else None
    rows = [
        ("sofr_iorb", "價格", "錢有沒有變貴？",
         f"近 3 月月均 {si_recent}bp；最緊 {peak('sofr_iorb', lambda v: f'{v:+.1f}bp')}"),
        ("srf", "後援", "有人借不到錢、只好找 Fed？",
         f"月均最高 {peak('srf', lambda v: f'{v * 10:,.0f} 億')}；{srf_note}"),
        ("rrp", "緩衝", "還有閒置現金可以先被抽走？",
         (f"{_ym(since)} 起月均都 < 1,000 億，已見底" if since
          else f"仍有約 {(rrp_now or 0) * 10:,.0f} 億可先被抽走")),
    ]
    trs = "".join(
        f'<tr><td class="k" data-label="指標">{_split_label(L[k].label)}</td>'
        f'<td data-label="角色"><b>{role}</b>：{esc(q)}</td>'
        f'<td data-label="現在"><span class="st {L[k].status}">{esc(L[k].display)}</span></td>'
        f'<td data-label="近期">{esc(note)}</td></tr>'
        for k, role, q, note in rows if k in L)
    st = lambda k: L[k].status if L.get(k) else "unknown"
    ok = lambda k: st(k) == "good"
    PRICE = {"good": "SOFR 低於 IORB，錢不貴", "warning": "SOFR 貼近或略高於 IORB，錢開始變貴",
             "critical": "SOFR 明顯高於 IORB，資金緊俏", "unknown": "資料不足"}
    BACK = {"good": "沒有人向 Fed 借錢", "warning": "開始有機構向 Fed 借錢",
            "critical": "大量向 Fed 借錢，市場的錢不夠", "unknown": "資料不足"}
    BUF = {"good": "還有閒置現金可以先被抽走", "warning": "見底，下一次抽水直接扣準備金",
           "critical": "見底，下一次抽水直接扣準備金", "unknown": "資料不足"}
    steps = [(ok("sofr_iorb"), "價格", PRICE[st("sofr_iorb")]),
             (ok("srf"), "後援", BACK[st("srf")]),
             (ok("rrp"), "緩衝", BUF[st("rrp")])]
    lab = vd.get("label", "")
    if lab in ("嚴重轉緊", "轉緊"):
        concl = ("資金已經變貴或有機構開始向 Fed 借錢——看季底、繳稅日是否讓情況擴大，"
                 "以及 Fed 是否重啟或加大 RMP、動用其他工具。")
    elif lab == "充裕穩定":
        concl = "價格、後援、緩衝都正常：資金不貴、沒人找 Fed，體系還有閒置現金可以吸收下一次抽水。"
    else:
        concl = (f"現在沒有資金緊俏（{PRICE[st('sofr_iorb')]}、{BACK[st('srf')]}），"
                 f"但{vd.get('reason', '緩衝偏薄')}，體系承受下一次抽水的能力較低。")
    si3 = [v for _, v in _last_n(si, 3)]
    pk = max(si.values()) if si else None
    if si3 and pk is not None and pk > 5 and max(si3) < pk - 3:
        bg = (f"背景：資料期間內最緊的是 {peak('sofr_iorb', lambda v: f'{v:+.1f}bp')}（2025 年第四季 SOFR 經常高於 IORB，"
              f"Fed 因此在 2025 年 12 月停止縮表、改做 RMP）；近 3 個月月均 {si_recent}bp，已明顯低於那段高點。")
    else:
        bg = ""
    chk = "".join(f'<li class="{"ok" if g else "ng"}"><span>{"✓" if g else "✕"}</span><b>{t}</b>{esc(x)}</li>'
                  for g, t, x in steps)
    return f"""<details class="f-more"><summary>三個指標怎麼讀、怎麼推出結論</summary><div class="f-detail">
      <p><b>讀法順序：</b>價格最先反應 → 後援被動用代表已經不只是變貴 → 緩衝決定下一次抽水（T-Bills 淨發行、TGA 回補、季底）先吃閒置現金還是直接扣準備金。</p>
      <table class="lq-tbl"><thead><tr><th>指標</th><th>角色</th><th>現在</th><th>近期</th></tr></thead><tbody>{trs}</tbody></table>
      <ul class="lq-check">{chk}</ul>
      <p class="lq-concl">結論：<b>{esc(lab or "—")}</b>——{esc(concl)}{(" " + esc(bg)) if bg else ""}</p>
    </div></details>"""


def _support_detail(d: dict) -> str:
    """
    輔助指標的下拉補充：把每一項依「當下的數值」分到「抽走現金的壓力」或「支撐資金的力量」，
    標題與結論句跟著綜合判定走——不預設現在是哪一種情況。
    """
    L = {l.key: l for l in d.get("liq_lights") or []}
    vd = d.get("liq_verdict") or {}
    qra, bn = d.get("qra") or {}, d.get("bill_net") or {}
    mtd = bn.get("mtd") or bn.get("last") or {}
    rl, rmp_since = d.get("rmp_last") or {}, d.get("rmp_paused_since") or ""
    rv, dv = d.get("ratio_view") or {}, d.get("rde_view") or {}
    wl = (d.get("mmf") or {}).get("wam_last") or {}
    tga = next((it for it in (d.get("liab") or {}).get("items") or [] if it["key"] == "tga"), None)
    press, hold = [], []
    if mtd:
        lab = f"{int(mtd['month'][5:])} 月" + ("至今" if mtd.get("partial") else "")
        if mtd["private"] > 0:
            press.append(f"<b>T-Bills 淨供給</b>：{lab}淨發行 {mtd['net'] * 10:+,.0f} 億，私人市場要吸收 {mtd['private'] * 10:+,.0f} 億")
        else:
            hold.append(f"<b>T-Bills 淨贖回</b>：{lab}私人市場淨拿回 {-mtd['private'] * 10:,.0f} 億現金")
    if qra.get("bills") is not None:
        (press if qra["bills"] > 0 else hold).append(
            f"<b>本季 T-Bills</b>：再融資隱含淨發行約 {qra['bills'] * 10:+,.0f} 億（未計買回）")
    if rmp_since:
        press.append(f"<b>Fed 暫停 RMP</b>：自 {_md(rmp_since)} 那一期起只剩 MBS 到期再投入（最新一期約 {rl.get('mbs', 0) * 10:,.0f} 億）")
    elif rl:
        hold.append(f"<b>Fed 持續 RMP</b>：最新一期（{esc(rl.get('period', '') or _md(rl.get('start', '')))}）"
                    f"RMP {rl.get('rmp', 0) * 10:,.0f} 億＋MBS 再投入 {rl.get('mbs', 0) * 10:,.0f} 億")
    if tga and qra.get("cash_end") is not None:
        diff = (qra["cash_end"] - tga["value"]) * 10
        if diff > 50:
            press.append(f"<b>TGA 要回補</b>：目前 {tga['value'] * 10:,.0f} 億、季底目標 {qra['cash_end'] * 10:,.0f} 億，還要從市場抽走約 {diff:,.0f} 億")
        elif diff < -50:
            hold.append(f"<b>TGA 會降低</b>：目前 {tga['value'] * 10:,.0f} 億、季底目標 {qra['cash_end'] * 10:,.0f} 億，約 {-diff:,.0f} 億準備金會還給市場")
    if L.get("rrp"):
        (hold if L["rrp"].status == "good" else press).append(
            f"<b>ON RRP 緩衝</b>：近 5 日均 {esc(L['rrp'].display)}"
            + ("，還有閒置現金可以先被抽走" if L["rrp"].status == "good" else "，已見底"))
    if rv:
        r = rv["value"]
        if r >= 13:
            hold.append(f"<b>準備金充足</b>：占銀行總資產 {r:.2f}%，高於 13%")
        else:
            press.append(f"<b>準備金偏低</b>：占銀行總資產 {r:.2f}%，低於 13%"
                         + ("、已跌破 2019 年危機的 10%" if r < 10 else "（仍高於 2019 年危機的 10%）"))
    if dv:
        txt = f"RDE {dv['value']:+.2f}，95% 信賴區間 {dv['lo95']:+.2f}～{dv['hi95']:+.2f}"
        (hold if dv.get("zero_in_ci") else press).append(
            (f"<b>仍在需求曲線平坦段</b>：{txt} 含 0" if dv.get("zero_in_ci")
             else f"<b>已進入需求曲線斜坡</b>：{txt} 整段 < 0，準備金少一點利率就會被推動"))
    if wl.get("gov") is not None and wl.get("gov_3m") is not None:
        dch = wl["gov"] - wl["gov_3m"]
        base = f"Government MMF 平均持有期限 {wl['gov']:.1f} 天（3 個月 {dch:+.1f} 天）"
        if dch <= -2:
            hold.insert(0, f"<b>MMF 把錢留在短端</b>：{base}——面對利率路徑的不確定，資金留在隔夜回購與短天期，接住新的 T-Bills 與回購需求")
        elif dch >= 2:
            press.append(f"<b>MMF 拉長期限</b>：{base}——押注降息、把現金鎖進較長天期，隔夜市場的現金供給變少")
    if L.get("tgcr"):
        (hold if L["tgcr"].status == "good" else press).append(
            f"<b>三方回購</b>：TGCR − IORB {esc(L['tgcr'].display)}"
            + ("，現金提供端平靜" if L["tgcr"].status == "good" else "，現金提供端開始收緊"))
    lab = vd.get("label", "")
    head = lambda x: x.split("</b>")[0][3:]
    # 不比項數（一項的份量差很多），結論只講「判定是什麼、主要靠什麼／主要壓力是什麼」。
    # 支撐的排序：MMF 配置（決定隔夜現金供給）放第一，其餘依上面加入的順序。
    if lab in ("嚴重轉緊", "轉緊"):
        title = "資金為什麼轉緊？壓力與支撐"
        concl = (f"判定<b>{esc(lab)}</b>：壓力已經壓過支撐，最需要盯的是「{esc(head(press[0]))}」。"
                 if press else f"判定<b>{esc(lab)}</b>。")
    else:
        title = "抽走現金的壓力 vs 支撐資金的力量"
        concl = (f"判定<b>{esc(lab or '—')}</b>：壓力仍在（{'、'.join(esc(head(x)) for x in press[:3]) or '不明顯'}），"
                 f"但短端資金沒有變貴，主要靠「{esc(head(hold[0])) if hold else '—'}」撐住。"
                 + ("準備金與 ON RRP 的緩衝都偏薄，這個平衡比較依賴市場參與者的配置選擇，不是體系有多餘的錢。"
                    if lab == "穩定，但緩衝偏薄" else ""))
    li = lambda xs: "".join(f"<li>{x}</li>" for x in xs) or "<li>目前沒有</li>"
    return f"""<details class="f-more"><summary>{esc(title)}</summary><div class="f-detail">
      <div class="lq-2col">
        <div class="lq-box press"><div class="lq-box-h">抽走現金的壓力</div><ul>{li(press)}</ul></div>
        <div class="lq-box hold"><div class="lq-box-h">支撐資金的力量</div><ul>{li(hold)}</ul></div>
      </div>
      <p class="lq-concl">{concl}</p>
    </div></details>"""


def _watch_detail(d: dict) -> str:
    """接下來要盯：依時間排序，標出重要性與「會改變判定的條件」。"""
    import datetime as _dt
    qra = d.get("qra") or {}
    asof = (d.get("as_of") or "")[:10]
    tga = next((it for it in (d.get("liab") or {}).get("items") or [] if it["key"] == "tga"), None)
    LL = {l.key: l for l in d.get("liq_lights") or []}
    rrp_thin = (LL.get("rrp") and LL["rrp"].status != "good")
    lab = (d.get("liq_verdict") or {}).get("label", "")
    rmp_paused = bool(d.get("rmp_paused_since"))
    items = []   # (排序日期, 顯示日期, 重要性, 標題, 內容)
    if qra.get("next") and qra["next"] >= asof:
        items.append((qra["next"], _md(qra["next"]), "高", "季度再融資（QRA）",
                      "下一季 T-Bills 與 coupon 規模、買回上限、季底 TGA 目標——決定未來三個月要從市場抽走多少現金"))
    if asof:
        y, m = int(asof[:4]), int(asof[5:7])
        # 紐約聯儲 RDE：每月第三個週四更新；本月那一天還沒到就是本月，過了就是下個月
        def _third_thu(yy, mm):
            d0 = _dt.date(yy, mm, 1)
            return d0 + _dt.timedelta(days=(3 - d0.weekday()) % 7 + 14)
        third_thu = _third_thu(y, m)
        if third_thu.isoformat() < asof:
            third_thu = _third_thu(y + (m == 12), m % 12 + 1)
        items.append((third_thu.isoformat(), _md(third_thu.isoformat()), "中", "紐約聯儲 RDE 月更新",
                      "看信賴區間是否轉為整段 < 0——那是準備金從充裕滑向充足的第一個統計訊號"))
        # 下一個「季中繳稅日＋季底」窗口（3／6／9／12 月 15 日到月底）；當月還沒過完就算當月
        qm = next((x for x in (3, 6, 9, 12) if x >= m), 3)
        qy = y + (1 if qm < m else 0)
        _last_day = (_dt.date(qy + (qm == 12), qm % 12 + 1, 1) - _dt.timedelta(days=1)).day
        items.append((f"{qy}-{qm:02d}-15", f"{qm}/15–{qm}/{_last_day}", "高", "企業繳稅日＋季底",
                      "稅款湧入 TGA、外國銀行季底縮減回購借款"
                      + ("；ON RRP 緩衝見底，最容易讓 SOFR 短暫衝高" if rrp_thin else "；ON RRP 還有緩衝可先吸收")))
    if tga and qra.get("cash_end") is not None:
        diff = (qra["cash_end"] - tga["value"]) * 10
        items.append(((qra.get("cash_end_date") or "9999"), f"至 {_md(qra.get('cash_end_date', ''))}", "中", "TGA 走向季底目標",
                      f"目前 {tga['value'] * 10:,.0f} 億、目標 {qra['cash_end'] * 10:,.0f} 億（差 {diff:+,.0f} 億）——"
                      + ("TGA 降低會把準備金還給市場" if diff < 0 else "TGA 回補會從市場抽走準備金")))
    items.sort(key=lambda x: x[0])
    if lab in ("嚴重轉緊", "轉緊"):
        items.append(("~", "隨時", "最高", "回到穩定的條件",
                      "SOFR − IORB 回到 0 以下、SRF 停止連續動用；同時看 Fed 是否"
                      + ("重啟 RMP" if rmp_paused else "加大 RMP") + "或動用其他工具"))
    else:
        items.append(("~", "隨時", "最高", "轉緊的觸發條件",
                      "SOFR − IORB 轉正並擴大、SRF 連續多日動用——判定會轉為「轉緊」，接著看 Fed 是否"
                      + ("重啟 RMP" if rmp_paused else "加大 RMP")))
    lis = "".join(f'<li><span class="lq-when">{esc(w)}</span><span class="lq-imp i{ {"最高": 3, "高": 2, "中": 1}.get(imp, 1)}">{esc(imp)}</span>'
                  f'<div><b>{esc(t)}</b><p>{esc(x)}</p></div></li>' for _, w, imp, t, x in items)
    return f"""<details class="f-more"><summary>接下來要盯</summary><div class="f-detail">
      <ol class="lq-watch">{lis}</ol></div></details>"""


def _rules_detail(lights: list) -> str:
    from ..analysis.liquidity import LIGHT_RULES
    trs = "".join(
        f'<tr><td class="k" data-label="指標">{_split_label(l.label)}'
        + (f'<em>{esc(LIGHT_RULES[l.key][3])}</em>' if LIGHT_RULES[l.key][3] else "") + "</td>"
        + "".join(f'<td data-label="{lab}"><span class="st {cls}">{esc(LIGHT_RULES[l.key][i])}</span></td>'
                  for i, (cls, lab) in enumerate((("good", "正常"), ("warning", "留意"), ("critical", "警戒"))))
        + "</tr>"
        for l in lights if l.key in LIGHT_RULES)
    return f"""<details class="f-more"><summary>判定規則與各指標門檻</summary><div class="f-detail">
      <ol class="lq-rule">
        <li><span class="st critical">嚴重轉緊</span>SOFR 衝出 SRF 利率（走廊上限）</li>
        <li><span class="st critical">轉緊</span>核心三指標任一警戒，或 SRF 連續動用／SOFR − IORB 轉正擴大</li>
        <li><span class="st warning">穩定，但緩衝偏薄</span>核心平靜，但 ON RRP、準備金占比、RDE、T-Bills 淨供給任一落在留意區</li>
        <li><span class="st good">充裕穩定</span>全部正常</li>
      </ol>
      <table class="lq-tbl lq-rules"><thead><tr><th>指標</th><th><span class="st good">● 正常</span></th>
        <th><span class="st warning">▲ 留意</span></th><th><span class="st critical">■ 警戒</span></th></tr></thead>
        <tbody>{trs}</tbody></table>
      <p class="hint">門檻是本站依 2019 年 9 月回購危機與 2025 年第四季準備金轉緊校準的規則，不是 Fed 公布的數字。</p>
    </div></details>"""


def _liq_transmission() -> str:
    steps = [("準備金與緩衝不足", "銀行不願借出準備金"),
             ("回購利率飆升", "SOFR、TGCR 衝過 IORB"),
             ("槓桿部位被迫去化", "基差交易、交易商庫存"),
             ("公債流動性惡化", "殖利率與利差亂跳"),
             ("跨資產同步承壓", "信用、股市、美元")]
    flow = "".join(f'<li><span class="n">{i}</span><b>{esc(a)}</b><small>{esc(b)}</small></li>'
                   for i, (a, b) in enumerate(steps, 1))
    assets = [
        ("短端利率", "SOFR、EFFR 跳升，浮動利率貸款與短期融資立刻變貴；T-Bills 相對 OIS 走高。"),
        ("美國公債", "基差交易的回購融資暴增、被迫賣出現貨，交易商又接不住——2019/9、2020/3 連最安全的資產都出現流動性危機。"),
        ("信用市場", "CD、商業本票利率上升，Prime MMF 被贖回，企業改提用銀行額度；信用利差走闊，低評等先借不到錢。"),
        ("股市與風險資產", "融資成本與保證金追繳迫使去槓桿，波動率上升；股債可能同跌，分散效果失靈。"),
        ("美元與海外", "全球美元融資變貴，美元走強、換匯基差更負，新興市場資金外流；外國央行轉向 Fed 換匯額度與 FIMA。"),
        ("Fed 的回應", "SRF 先接住 → 停止縮表、RMP 補準備金 → 嚴重時推出緊急工具。出手前，資產價格往往已先修正一輪。"),
    ]
    cards = "".join(f'<div class="lq-card"><b>{esc(t)}</b><p>{esc(x)}</p></div>' for t, x in assets)
    return f"""<p class="lq-lead"><b>利率決定錢的價格，流動性決定錢借不借得到。</b>
      準備金一旦不夠，市場利率會衝出 Fed 的利率走廊，政策利率失去控制力；而且流動性問題通常比經濟數據更早、更快反映在價格上，幾天內就從貨幣市場擴散到所有資產。</p>
    <ol class="lq-flow">{flow}</ol>
    <div class="lq-cards">{cards}</div>"""


def _liab_defs() -> str:
    items = [
        ("流通在外貨幣（Currency in circulation）",
         "<p>Fed 印的紙鈔，在民眾、企業與海外手上的現金。現金要多少是大眾決定的，Fed 被動供應："
         "民眾從銀行提領現金時，銀行要用自己在 Fed 的準備金去換，所以<b>現金增加 1 元、準備金就少 1 元</b>。"
         "它長期穩定成長、年底節慶前季節性升高，很少是流動性變化的主因，但它是負債端最大、最穩定的一塊。</p>"),
        ("準備金（Reserve balances）",
         "<p>商業銀行存在 Fed 的存款，是銀行之間付款清算的最終工具，Fed 對它付準備金利率（IORB）。"
         "這是整個銀行體系最底層的流動性：準備金不夠時，銀行彼此搶錢，回購利率就會往上衝"
         "（2019 年 9 月回購利率飆升就是準備金降到不夠用）。</p>"
         "<p><b>貨幣乘數效果：</b>銀行拿到 1 元準備金，可以把其中大部分放款出去；借款人把錢存進另一家銀行，"
         "那家銀行又能再放款——一輪一輪下來，1 元準備金可以撐起好幾元的存款與放款。舊制下若法定準備率 10%，"
         "理論上限是 10 倍（1 ÷ 10%）。所以準備金的增減，會被放大成整體貨幣與信用的增減。"
         "2020 年起美國法定準備率降為 0、準備金又充裕，乘數實際上更受銀行資本、監管比率與放款需求限制，"
         "但準備金仍是這座信用金字塔的地基——地基變薄時，上面整座金字塔都會收縮。</p>"),
        ("財政部一般帳戶（TGA）",
         "<p>財政部在 Fed 開的支票帳戶。稅收、發債拿到的錢流進來，政府支出、還債付出去。</p>"
         "<p><b>與準備金的抵換關係：</b>Fed 資產端不變時，負債端加總也不變，所以 TGA 多 1 元，"
         "其他負債（準備金或 ON RRP）就得少 1 元——民眾繳稅、投資人買新發的公債，錢從銀行帳戶轉進 TGA，"
         "銀行的準備金就被抽走；反過來，財政部花錢時，錢從 TGA 回到銀行，準備金增加。"
         "所以 4 月、9 月、12 月稅收日，以及財政部大量發債「回補 TGA」時（例如 2023 年債務上限解除後，"
         "TGA 從不到 1,000 億美元補回 7,000 億以上），都是準備金被抽走的時點。"
         "財政部每季在再融資（QRA）公布季底目標餘額，目標比現在高多少，就代表接下來要從市場抽走多少。</p>"),
        ("逆回購（RRP：國內 ON RRP＋國外）",
         "<p>國內部分是隔夜逆回購（ON RRP）：貨幣基金、GSE、交易商把多餘現金借給 Fed 一晚，拿公債當抵押，"
         "賺 ON RRP 利率（利率走廊下緣）。國外部分是外國央行與國際機構放在紐約聯儲的 foreign repo pool，"
         "金額穩定（約 3,000 多億），跟國內貨幣市場的鬆緊關係不大。看流動性主要看國內那一條。</p>"
         "<p><b>緩衝效果：</b>ON RRP 裡有錢時，等於體系裡有一筆「閒置的多餘現金」。財政部回補 TGA 或 Fed 縮表"
         "需要市場拿出錢時，貨幣基金會先把錢從 ON RRP 拿出來去買新發的國庫券，抽走的是 ON RRP，"
         "<b>準備金不必下降</b>；等 ON RRP 見底，接下來的抽水才會直接扣到準備金。</p>"
         "<p><b>經典例子：2022–2025 年縮表（QT）。</b>疫情期間大規模 QE 讓貨幣市場資金過剩，多出來的錢停在 ON RRP，"
         "國內 ON RRP 在 2022 年 9 月底（週三水位）達 2.37 兆美元。從 2022 年 6 月縮表開始到 2025 年 11 月底，"
         "國內 ON RRP 從約 1.97 兆降到幾乎為 0，準備金只從約 3.36 兆降到約 2.90 兆——縮表的衝擊絕大部分先由 ON RRP 吸收，"
         "所以 Fed 縮了好幾年都沒有引發資金危機。ON RRP 耗盡之後緩衝就沒了，"
         "這也是 Fed 2025 年底停止縮表、改做準備金管理購買（RMP）的原因。</p>"),
    ]
    return "".join(f'<details class="f-more"><summary>{esc(t)}</summary><div class="f-detail">{b}</div></details>'
                   for t, b in items)


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

    lb = d.get("liab") or {}
    _li = {it["key"]: it for it in lb.get("items") or []}
    _liab_sum = ("　·　".join(f'{it["label"]} {_liab_value(it, short=True)}'
                             for it in (lb.get("items") or [])[1:3]) or "Fed 負債端")
    liab_cells = "".join(state_chip(it["label"], _liab_value(it),
                                    _liab_note(it, d.get("qra"), lb.get("source", "")), "neutral")
                         for it in lb.get("items") or [])
    liabilities_section = f"""<div class="grid">
  <div class="card">
    <h2 id="liabilities" data-sum="{esc(_liab_sum)}">Fed 負債端結構</h2>
    {(f'<div class="focus-grid liab-grid">{liab_cells}</div>' if liab_cells
      else '<div class="empty">H.4.1 資料本次取得失敗</div>')}
    <div class="viz-block"><div class="viz-h">四大項近 5 年（億美元，週三水位）</div>
      {d.get("liab_chart") or ""}</div>
    <div class="viz-block"><div class="viz-h">逆回購拆分：國內 ON RRP vs 國外（億美元）</div>
      {d.get("rrp_split_chart") or ""}</div>
    <div class="src">Fed 理事會 H.4.1（Factors Affecting Reserve Balances）表 1，週三水位，每週四美東 16:30 公布。</div>
    {_liab_defs()}
    {_reserve_adequacy(d)}
  </div>
</div>"""

    bn = d.get("bill_net") or {}
    _last, _mtd, qra = bn.get("last"), bn.get("mtd"), d.get("qra")
    _supply_sum = (f'{int(_last["month"][5:])} 月 T-Bills 淨發行 {_last["net"] * 10:+,.0f} 億'
                   f'　·　私人 {_last["private"] * 10:+,.0f} 億'
                   if _last else "T-Bills 淨發行與 Fed 購買")
    supply_section = f"""<div class="grid">
  <div class="card">
    <h2 id="supply_demand" data-sum="{esc(_supply_sum)}">市場供需</h2>
    <p class="hint">財政部 T-Bills 淨發行（發行 − 到期贖回）{
      (f'　·　占可交易公債 <b>{bn["share"]:.1f}%</b>（{_md(bn["share_asof"])}）'
       if bn.get("share") is not None else "")}</p>
    {_bill_net_stats(_last, _mtd, qra)}
    <div class="viz-block"><div class="viz-h">T-Bills 每月淨發行：Fed vs 私人市場</div>
      {d.get("bill_net_chart") or '<div class="empty">資料本次取得失敗</div>'}</div>
    <div class="src">淨發行：財政部 MSPD 月底 Bills 存量的月變動（當月：每日國庫報表 DTS 月初至今）。
      Fed：紐約聯儲國庫券購買實際成交額（依交割日歸月）。</div>
    <details class="f-more"><summary>淨發行與私人市場怎麼算</summary>
      <div class="f-detail">{_bill_net_method(bn.get("rows") or [], qra)}</div>
    </details>
    <details class="f-more"><summary>已公告的 T-Bills 拍賣（毛額）</summary>
      <div class="f-detail">{_upcoming_bills_html(d.get("upcoming_bills") or [])}
      <p class="hint">這是每場拍賣的毛額，大部分用來償還同一週到期的舊券；淨增加多少要看上方的淨發行。</p></div>
    </details>
    <details class="f-more"><summary>T-Bills 占比怎麼看</summary>
      <div class="f-detail">分母是全部可交易公債（MSPD 表一 Total Marketable）。財政部借款顧問委員會（TBAC）
      長期建議的區間是 15%–20%；高於區間代表財政部更依賴短端融資，長天期供給相對受控，對照
      <a href="/rates/#supply">長端與債務頁「債券供給：財政部與 Fed」</a>的 Coupon 發行路徑。</div>
    </details>

    <p class="hint" style="margin-top:18px">Fed T-Bills 購買量（計畫金額）</p>
    {rc}
    {(f'<div class="src">最新一期（{esc(rl.get("period", ""))}）：'
      f'RMP {_yi(rl.get("rmp"))}　MBS 到期再投入 {_yi(rl.get("mbs"))}　'
      f'合計 {_yi(rl.get("total"))}。</div>'
      if rl else "")}
    <details class="f-more"><summary>RMP（準備金管理購買）</summary>
      <div class="f-detail">{_rmp_concept()}</div></details>
  </div>
</div>"""

    mv = d.get("mmf") or {}
    _ml = mv.get("latest") or {}
    _bills_out = ((d.get("bill_net") or {}).get("last") or {}).get("bills")
    _mmf_sum = (f'{int(_ml["month"][5:])} 月淨流量 {(_ml["flows"].get("total") or 0) * 10:+,.0f} 億'
                f'　·　Government 收益率 {_ml["yields"].get("gov", 0):.2f}%' if _ml else "MMF 資金流向與部位")
    mmf_section = f"""<div class="grid">
  <div class="card">
    <h2 id="mmf" data-sum="{esc(_mmf_sum)}">MMF 動向</h2>
    <p class="hint">貨幣市場基金（MMF）是回購市場最大的現金借出方、T-Bills 最大的買家——它的錢往哪走，貨幣市場的流動性就在哪裡。</p>
    {_mmf_cells(mv, _bills_out)}
    <div class="viz-block"><div class="viz-h">年初至今累計淨流量（億美元）</div>{d.get("mmf_ytd_chart") or ""}</div>
    <div class="viz-block"><div class="viz-h">各類型每月淨流量（億美元）</div>{d.get("mmf_flow_chart") or ""}</div>
    <div class="viz-block"><div class="viz-h">平均持有期限：加權平均到期天數（WAM，天）</div>
      {(f'<p class="viz-sub">{esc(d["mmf_wam_text"])}</p>' if d.get("mmf_wam_text") else "")}
      {d.get("mmf_wam_chart") or ""}</div>
    <div class="viz-block"><div class="viz-h">7 日淨收益率 vs 銀行儲蓄存款（%）</div>{d.get("mmf_yield_chart") or ""}</div>
    <div class="viz-block"><div class="viz-h">MMF 比銀行存款多賺多少（百分點）</div>{d.get("mmf_spread_chart") or ""}</div>
    <div class="viz-block"><div class="viz-h">持有部位月變動（億美元）</div>{d.get("mmf_hold_chart") or ""}</div>
    <div class="viz-block"><div class="viz-h">公債與回購部位：交易對手（億美元，近 5 年）</div>{d.get("mmf_repo_chart") or ""}</div>
    <div class="src">流量、淨資產、收益率：SEC Money Market Fund Statistics（{esc(mv.get("report", ""))} 版）；
      持有部位：OFR MMF Monitor；存款利率：FDIC。</div>
    {_mmf_explain(mv, _bills_out)}
  </div>
</div>"""

    from .labor import _light_card
    _lights = d.get("liq_lights") or []
    _anchor = {"sofr_iorb": "#corridor", "srf": "#corridor", "rrp": "#liabilities", "tgcr": "#corridor",
               "ratio": "#liabilities", "rde": "#liabilities", "wam": "#mmf", "bills": "#supply_demand"}
    _lt = {}
    for _l in _lights:
        _lt[_l.status] = _lt.get(_l.status, 0) + 1
    _light_sum = "、".join(f"{_n} 項{_lab}" for _k, _lab in
                           (("critical", "警戒"), ("warning", "留意"), ("good", "正常"), ("unknown", "無資料"))
                           if (_n := _lt.get(_k)))
    _lv = d.get("liq_verdict") or {}
    _cards = lambda ls: "".join(_light_card(l, _anchor.get(l.key, "")) for l in ls)
    lights_section = f"""<div class="grid">
  <div class="card">
    <h2 id="lights" data-sum="{esc(_light_sum)}{('　·　綜合判定：' + esc(_lv['label'])) if _lv.get('label') else ''}">關鍵指標檢核與綜合判定</h2>
    <p class="hint">目前的整體狀態：逐項對照警戒線，再下結論。</p>
    {(f'<div class="impact {_lv.get("lean", "neutral")}">綜合判定：{esc(_lv["label"])}（{esc(_lv.get("reason", ""))}）　·　{esc(_light_sum)}</div>'
      if _lv.get("label") else "")}
    <details data-m-collapse open><summary>核心三指標</summary>
      <div class="lights" style="margin-top:12px">{_cards(_lights[:3])}</div>
      {_core_detail(d)}</details>
    <details data-m-collapse open><summary>輔助指標：準備金、回購、MMF、T-Bills 供給</summary>
      <div class="lights" style="margin-top:12px">{_cards(_lights[3:])}</div>
      {_support_detail(d)}</details>
    {_watch_detail(d)}
    {_rules_detail(_lights)}
    <h3 class="le-h3" style="margin-top:22px">為什麼要關注流動性：緊缺時的跨資產傳導</h3>
    {_liq_transmission()}
  </div>
</div>"""

    main = hero + corridor_section + liabilities_section + supply_section + mmf_section + lights_section
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
         ("T-Bills 淨發行（月底存量差）、占可交易公債比例", "財政部 MSPD 表一", "每月（次月初）"),
         ("T-Bills 當月至今發行與贖回", "財政部每日國庫報表（DTS）表 IIIA", "每日"),
         ("Fed 國庫券購買實際成交", "紐約聯儲 Treasury Securities Purchases 結果", "每筆操作"),
         ("已公告的 T-Bills 拍賣", "財政部 Fiscal Data（auctions_query）", "拍賣前幾天公布金額"),
         ("私人持有淨借款估計、TGA 季底目標", "財政部每季再融資（QRA）借款估計", "每季"),
         ("Fed 負債端：流通在外貨幣、準備金、TGA、逆回購（國內／國外）",
          "Fed 理事會 H.4.1 Data Download Program（週三水位）；FRED 轉載後備", "每週四"),
         ("商業銀行總資產（準備金占比的分母）", "Fed 理事會 H.8 全體商業銀行（季調，週）；FRED 後備", "每週五"),
         ("準備金需求彈性（RDE）", "紐約聯儲 Reserve Demand Elasticity", "每月第三個週四"),
         ("MMF 淨資產、淨流量、7 日淨收益率", "SEC Money Market Fund Statistics（Form N-MFP）", "每月（約晚 6 週）"),
         ("MMF 持有部位與回購交易對手", "OFR U.S. Money Market Fund Monitor（Form N-MFP）", "每月（約晚 2 週）"),
         ("銀行儲蓄存款利率", "FDIC 全國儲蓄存款利率（經 FRED：SNDR；2021 年前 SAVNRNJ）", "每月")],
        ["三個趨勢訊號（近 5 日均 vs 近 30 日均）：SRF 動用量升溫、SOFR−IORB 走闊、"
         "ON RRP 交易量回升。SOFR 衝出 SRF 利率（走廊上限）視為最嚴重的轉緊訊號。",
         "RMP、MBS 到期再投入兩個計畫金額直接來自紐約聯儲官方逐期公布的拆分。再投入只適用 MBS"
         "（機構證券），不含長端公債——公債到期後直接從資產負債表消失，不會被拿去買回 Bills。",
         "私人市場淨吸收＝T-Bills 淨發行（發行 − 到期贖回）減掉 Fed 實際買走的量，日曆月口徑；"
         "Fed 實際成交只有總額，RMP／MBS 依該期計畫金額比例拆分。QRA 隱含的季度 T-Bills "
         "淨發行是本站推算（私人持有淨借款 − 推算的 coupon 淨發行），未計買回。"],
        head="<b>資料來源</b> 紐約聯儲、財政部 Fiscal Data／MSPD／DTS、FRED")
