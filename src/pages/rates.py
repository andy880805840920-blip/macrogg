"""長端利率與債務供給頁的內容產生器（P5）。"""

from __future__ import annotations

from ..site import esc
from .labor import _light_card, _stats, STATUS_ICON, STATUS_TEXT
from .. import charts


def _ref_table(ref: dict | None) -> str:
    """燈卡裡的歷史對照小表（期限溢酬的財政／供給事件、實質利率的升降息循環）。"""
    if not ref or not ref.get("rows"):
        return ""
    # 燈卡很窄（桌機四欄、手機一欄），四欄表格會撐破卡片；改成一筆一塊：
    # 第一行「時點 · 背景」，第二行把數字欄配上欄名。
    head = ref.get("head") or []
    items = []
    for r in ref["rows"]:
        r = [str(c) for c in r]
        nums = "".join(f'<span><em>{esc(head[j])}</em>{esc(r[j])}</span>'
                       for j in range(2, len(r)) if j < len(head) and r[j] and r[j] != "—")
        items.append(f'<li><b>{esc(r[0])}</b><span class="lx-ref-ctx">{esc(r[1])}</span>'
                     f'<div class="lx-ref-n">{nums}</div></li>')
    return f'<div class="lx-k">{esc(ref.get("title") or "歷史對照")}</div><ul class="lx-ref">{"".join(items)}</ul>'


def _explained_card(lt, href: str, ex: dict | None) -> str:
    """長端頁燈卡：說明拆成「現況／量什麼／為什麼重要／門檻／依據」，目前所在的門檻列標亮。
    沒有 explain 設定的燈退回共用燈卡。"""
    if not ex:
        return _light_card(lt, href)
    arrow = {"up": "↑", "down": "↓", "flat": "→"}[lt.delta_dir]
    strip = charts.status_strip(getattr(lt, "history", []) or [])
    note = getattr(lt, "note", "") or ""
    lv = ex.get("levels") or []
    rows = "".join(
        f'<li class="{st}{" on" if st == lt.status else ""}"><span class="lx-tag">{STATUS_ICON[st]} {STATUS_TEXT[st]}</span>'
        f'<span class="lx-rng">{esc(rng)}</span>{"<em>目前</em>" if st == lt.status else ""}</li>'
        for st, rng in zip(("good", "warning", "critical"), lv))
    parts = [f'<p class="lx-now"><b>現況</b>{esc(note)}</p>' if note else "",
             f'<p class="lx-what">{esc(ex.get("what", ""))}</p>',
             f'<div class="lx-k">為什麼重要</div><p>{esc(ex.get("why", ""))}</p>' if ex.get("why") else "",
             f'<div class="lx-k">門檻</div><ul class="lx-lv">{rows}</ul>' if rows else "",
             f'<p class="lx-basis">依據：{esc(ex["basis"])}</p>' if ex.get("basis") else "",
             _ref_table(ex.get("ref")),
             f'<a class="l-link" href="{href}">完整脈絡 →</a>' if href else ""]
    return f"""<div class="light {lt.status}">
  <div class="l-top"><span class="l-icon">{STATUS_ICON[lt.status]}</span>{esc(lt.label)}</div>
  <div class="l-value">{esc(lt.display)} <span style="font-size:13px;color:var(--muted)">{arrow}</span></div>
  <div class="l-state">{STATUS_TEXT[lt.status]}</div>
  {strip}
  <details class="l-more"><summary>這在量什麼</summary>
    <div class="l-desc lx">{"".join(parts)}</div></details>
</div>"""
from . import compact_full, focus_evidence, state_chip, teach, gloss_more
from . import longend as LE


# eSLR 說明（2026-10；規則有變動時要更新這段，日期與數字取自聯邦公報與 FDIC）
X_ESLR = (
    '<details class="f-more flw-eslr"><summary>eSLR 是什麼、2025 年的改革與對市場的影響</summary><div class="f-detail">'
    '<h4>定義</h4>'
    '<p><b>補充槓桿率（SLR）</b>＝第一類資本 ÷ 總槓桿曝險。曝險包含資產負債表上所有資產（公債、存在 Fed 的準備金也算）'
    '與部分表外項目，<b>不看風險權重</b>。大型銀行最低 3%；美國 8 家全球系統性重要銀行（GSIB）另有加碼要求——'
    '控股公司再加 2% 緩衝（合計 5%）、旗下銀行要 6% 才算資本適足，這就是「強化版」SLR（eSLR）。</p>'
    '<p>問題在於：公債、準備金這類低風險資產，吃的槓桿資本跟其他資產一樣。當 eSLR 變成銀行真正綁住的限制時，'
    '交易商就少了持有公債、做附買回中介與造市的空間——2020 年 3 月公債市場失序時特別明顯'
    '（當時曾暫時把公債與準備金排除在曝險之外，2021 年 3 月到期）。</p>'
    '<h4>2025 年的改革</h4>'
    '<ul><li>2025 年 6 月提案，<b>2025/11/25</b> 聯準會、FDIC、OCC 定案（2025/12/1 刊登聯邦公報），'
    '<b>2026/4/1 生效</b>，銀行可自 2026/1/1 提前適用。</li>'
    '<li>控股公司：固定 2% 緩衝改為<b>GSIB 方法一附加資本的 50%</b>。</li>'
    '<li>旗下銀行：資本適足門檻由 6% 改為 3%＋同樣的緩衝，<b>緩衝上限 1%</b>。</li>'
    '<li>總損失吸收能力（TLAC）的槓桿緩衝與長期債要求同步改用這個緩衝。</li>'
    '<li><b>公債與準備金沒有被排除</b>在曝險之外——放寬的是門檻，不是計算方式。</li>'
    '<li>FDIC 估計：GSIB 控股公司第一類資本要求減少約 130 億美元（不到 2%），主要銀行子公司約 2,190 億美元（28%）。</li></ul>'
    '<h4>可能的市場影響</h4>'
    '<ul><li><b>現券承接</b>：資本限制鬆綁後，交易商可以持有更多公債現券、擴大附買回中介，造市深度與壓力時吸收拋售的能力提高。</li>'
    '<li><b>期貨的對手換人</b>：資產管理在期貨上做多久期，過去主要由避險基金的基差交易對做（買現券、空期貨）。'
    '2025 年 4 月關稅衝擊時，市場普遍認為部分基差交易被迫平倉；之後空方逐漸有更多由交易商承接。'
    '交易商受資本與風控約束，但不像槓桿基金那樣在保證金升高時被迫平倉，對價格波動相對沒那麼敏感，'
    '有助降低「踩踏式」去槓桿的風險。上方矩陣與圖的「交易商佔淨空比重」就是在量這件事。</li>'
    '<li><b>長端供給</b>：交易商能多吸收一些新債，邊際上減輕發債對期限溢酬的壓力。</li>'
    '<li><b>限制</b>：公債仍計入曝險；釋出的資本空間是否真的用在公債中介（而不是其他業務），要看銀行自己的選擇，'
    '也受 GSIB 附加資本計算的變動影響。所以要搭配下方的交易商庫存與拍賣承接比例一起看。</li></ul>'
    '<p class="cw-panel-note">來源：<a href="https://www.federalregister.gov/documents/2025/12/01/2025-21626" target="_blank" rel="noopener">聯邦公報 2025-21626</a>、'
    '<a href="https://www.occ.gov/news-issuances/news-releases/2025/nr-ia-2025-112a.pdf" target="_blank" rel="noopener">OCC／聯準會／FDIC 新聞稿</a>、'
    'FDIC 理事會資料。</p></div></details>')


def _flows(d: dict) -> tuple[str, str]:
    """市場籌碼：期貨 DV01 矩陣＋三年變化圖、eSLR 說明、初級交易商現券庫存。回傳（HTML, 收合摘要）。"""
    from .. import fmt as _fmt
    f = d.get("flows") or {}
    fut, inv = f.get("fut"), f.get("inv")
    if not fut and not inv:
        return '<div class="empty">CFTC／紐約聯儲資料本次取得失敗</div>', "期貨持倉與交易商庫存"
    sg = lambda v, n=0: "—" if v is None else _fmt.signed(v, n)
    _v1 = lambda v: "—" if v is None else format(v, ",.1f")
    _p1 = lambda v: "—" if v is None else format(v, ".1f") + "%"
    md = lambda x: f"{int(x[5:7])}/{int(x[8:10])}" if x else ""
    parts, summ = [], []
    if fut:
        sh = fut.get("share") or {}
        if sh.get("now") is not None:
            summ.append(f'交易商佔淨空 {sh["now"]:.0%}' + (f'（一年前 {sh["ago"]:.0%}）' if sh.get("ago") is not None else ""))
        head = "".join(f'<th>{esc(c["label"])}</th>' for c in fut["matrix"][0]["cells"])
        body = ""
        for r in fut["matrix"]:
            tds = "".join(
                f'<td data-label="{esc(c["label"])}" class="{"tot" if c["code"] == "tot" else ""}">'
                f'<b class="{"pos" if c["v"] > 0.5 else "neg" if c["v"] < -0.5 else ""}">{sg(c["v"])}</b>'
                f'<small>週 {sg(c["w1"])}・4 週 {sg(c["w4"])}</small></td>' for c in r["cells"])
            body += f'<tr><th scope="row">{esc(r["label"])}</th>{tds}</tr>'
        per = "、".join(f"{k} ${v:.0f}" for k, v in fut["per"].items())
        parts.append(
            f'<p class="flw-head"><b>{esc(fut["head"])}</b></p>'
            f'<p class="hint">公債期貨上，誰在做多久期、誰在對做。DV01＝殖利率每變動 1bp 的部位損益（百萬美元）；'
            f'正＝淨多（利率下跌獲利）、負＝淨空。期貨一多一空，每一欄加總為零。</p>'
            f'<div class="viz-h">公債期貨淨 DV01：參與者 × 天期（CFTC，{md(fut["date"])} 部位，百萬美元／bp）</div>'
            f'<div class="flw-wrap"><table class="flw-mx"><thead><tr><th>參與者</th>{head}</tr></thead><tbody>{body}</tbody></table></div>'
            f'<p class="cw-panel-note">週＝比前一週（{md(fut["w1"])}）、4 週＝比 {md(fut["w4"])}。每口 DV01 為近似值（{esc(per)}）：'
            f'以該週對應天期殖利率估算最便宜交割券的 DV01，再除以轉換因子。</p>'
            f'<div class="tabs flw-tabs">'
            f'<input type="radio" name="flw-t" id="flw-t1" checked><label for="flw-t1">累積變化（{esc(md(fut.get("base_date", "")))}＝0）</label>'
            f'<input type="radio" name="flw-t" id="flw-t2"><label for="flw-t2">水準</label>'
            f'<div class="tabp p1"><div class="viz-h">近 3 年：資產管理淨多 vs 槓桿基金、交易商淨空（DV01，百萬美元／bp）</div>{fut.get("chart_chg", "")}</div>'
            f'<div class="tabp p2"><div class="viz-h">近 3 年 DV01 水準（百萬美元／bp）</div>{fut.get("chart_level", "")}</div></div>'
            f'<p class="cw-panel-note">三條線都以正值呈現：資產管理是淨多、槓桿基金與交易商是淨空。資產管理多單增加時，'
            f'看是哪一條空單跟著增加，就知道是誰在對做。</p>')
    parts.append(X_ESLR)
    if inv:
        L = inv["last"]
        summ.append(f'交易商 coupon 庫存 {L["coupons"] * 10:,.0f} 億')
        _y1i = inv.get("y1") or {}
        _bill_y1 = sg(L["bills"] - _y1i["bills"]) if _y1i.get("bills") is not None and L.get("bills") is not None else "—"
        tk = inv.get("take") or {}
        tnow, tago = (tk.get("now") or (None, 0)), (tk.get("ago") or (None, 0))
        stats = (
            f'<div class="flw-stats">'
            f'<div><span>coupon 淨持倉</span><b>{L["coupons"]:,.0f}<small> 十億美元</small></b>'
            f'<em>4 週 {sg(inv.get("chg_4w"))}・一年 {sg(inv.get("chg_1y"))}</em>'
            f'<em>近 3 年第 {inv["pct3y"] * 100:.0f} 百分位</em></div>'
            f'<div><span>T-Bills 淨持倉</span><b>{L["bills"]:,.0f}<small> 十億美元</small></b>'
            f'<em>一年 {_bill_y1}</em></div>'
            f'<div><span>coupon 拍賣交易商承接</span><b>{_p1(tnow[0])}</b>'
            f'<em>{(f"近 3 個月 {tnow[1]} 場；一年前同期 {_p1(tago[0])}") if tnow[1] else "近 3 個月無拍賣資料"}</em></div></div>')
        rows = "".join(
            f'<tr><td data-label="期別"><b>{esc(b["label"])}</b></td><td data-label="淨持倉">{_v1(b["v"])}</td>'
            f'<td data-label="4 週">{sg(b["w4"], 1)}</td><td data-label="一年">{sg(b["y1"], 1)}</td></tr>'
            for b in inv["buckets"])
        parts.append(
            f'<h3 class="flw-h3">初級交易商現券庫存：造市與承接新債的能力</h3>'
            f'<p class="flw-read">{esc(inv["read"])}</p>{stats}'
            f'<table class="lq-tbl flw-inv"><thead><tr><th>剩餘年限</th><th>淨持倉（十億美元，{md(inv["date"])}）</th>'
            f'<th>4 週變化</th><th>一年變化</th></tr></thead><tbody>{rows}</tbody></table>'
            f'<div class="viz-block"><div class="viz-h">近 3 年 coupon 淨持倉，依剩餘年限（十億美元，週資料）</div>{inv.get("chart", "")}</div>'
            f'<details class="f-more"><summary>怎麼讀交易商庫存</summary><div class="f-detail">'
            f'<p>庫存是交易商自己資產負債表上的公債淨部位。<b>庫存上升＋拍賣承接比例上升</b>＝終端需求不足、交易商被迫接手（壓力訊號）；'
            f'<b>庫存上升但承接比例沒升</b>＝交易商主動持有（資產負債表有空間，造市深度變好）；<b>庫存下降</b>＝交易商在去化部位，承接新債的空間相對充裕。</p>'
            f'<p>水位分位以近 3 年 coupon 淨持倉排序；拍賣承接比例＝初級交易商得標量 ÷ 競標得標量，取近 3 個月名目 coupon 拍賣的平均。'
            f'11–21 年與 21 年以上自 2022 年起才分開申報，「3 年以內」＝2 年以內＋2–3 年。</p>'
            f'<p>資料：紐約聯儲初級交易商統計（FR 2004，週三部位、隔週四公布）；財政部 Fiscal Data 拍賣結果。</p></div></details>')
    parts.append('<div class="src">期貨：CFTC Traders in Financial Futures（期貨部分；週二部位、週五公布）。'
                 '現券：紐約聯儲初級交易商統計。殖利率：美國財政部（FRED）。</div>')
    return "".join(parts), "　·　".join(summ) or "期貨持倉與交易商庫存"


def _rates_body_full(d: dict) -> str:
    sp = d["pressure"]
    title, why = d["pressure_text"]
    lean_cls = {"high": "hawkish", "low": "dovish"}.get(sp.level, "balanced")
    hs = d["hyperscalers"]
    hs_title, hs_desc = d["hs_text"]
    debt_title, debt_desc = d["debt_text"]
    lights_html = "".join(_light_card(l, LE.LIGHT_ANCHOR.get(l.key, "")) for l in d["lights"])
    # 摺疊起來時摘要列要講出狀態分布，否則卡片看起來是空的
    _lc = {}
    for l in d["lights"]:
        _lc[l.status] = _lc.get(l.status, 0) + 1
    _order = [("critical", "警戒"), ("warning", "留意"),
              ("good", "正常"), ("unknown", "無資料")]
    light_summary = (f'{len(d["lights"])} 項指標：'
                     + "、".join(f"{n} 項{lab}" for k, lab in _order
                                 if (n := _lc.get(k)))
                     + "。") if d["lights"] else ""
    # 檢核卡的一句結論：只由紅黃燈數量推出，跟勞動頁的檢核卡同一套做法。
    _crit, _warn = _lc.get("critical", 0), _lc.get("warning", 0)
    # 檢核結論（2026-10 改版）：條列警戒與留意的燈，各配一句原因；正常的燈收成一行。
    # 顏色用狀態色（--critical／--warning），底色維持中性，白底與深色模式都讀得清楚。
    _MEAN = {
        "critical": {"term_premium": "上升速度接近過去財政／供給事件，長端被動收緊",
                     "real_10y": "比中性高出 1pp 以上，緊度超過歷次升息尾聲",
                     "curve_30_10": "長端斜率走陡，供給或財政疑慮升溫",
                     "interest_to_revenue": "利息吃掉超過兩成稅收",
                     "r_minus_g": "利率明顯高於成長，債務會自我累積",
                     "breakeven_10y": "長期通膨預期的錨定鬆動",
                     "curve_10_2": "曲線倒掛，歷史上的衰退前兆",
                     "dots_gap": "期貨與點陣圖分歧超過兩碼，之後一方得大幅修正",
                     "ig_spread": "企業融資成本明顯上升"},
        "warning": {"term_premium": "上升速度高於平常，但還沒到財政事件的速度",
                    "real_10y": "比中性高 0.5～1pp，約等於升息尾聲的緊度",
                    "curve_30_10": "長端斜率偏陡",
                    "interest_to_revenue": "利息負擔逐步加重",
                    "r_minus_g": "利率逼近成長，債務自我消化的空間變小",
                    "breakeven_10y": "通膨預期略高於與 2% 相符的區間",
                    "curve_10_2": "曲線偏平，或倒掛後剛轉正",
                    "dots_gap": "期貨與點陣圖差半碼到兩碼",
                    "ig_spread": "信用利差略為走闊"},
    }
    _rows = []
    for _st, _zh in (("critical", "警戒"), ("warning", "留意")):
        for l in d["lights"]:
            if l.status == _st:
                _rows.append(f'<li class="{_st}"><span class="lsum-tag">{STATUS_ICON[_st]} {_zh}</span>'
                             f'<span class="lsum-txt"><b>{esc(l.label)}</b> <span class="lsum-v">{esc(l.display)}</span>'
                             f'<span class="lsum-why">{esc(_MEAN[_st].get(l.key, "越過門檻"))}</span></span></li>')
    _ok = [l.label for l in d["lights"] if l.status == "good"]
    _li_head = ("壓力集中在下面幾項：" if _crit else
                "沒有越過警戒線，但有幾項在累積壓力：" if _warn else "所有指標都在正常範圍，長端沒有額外警訊。")
    lights_impact = (f'<div class="lsum"><p class="lsum-head"><b>{esc(light_summary.rstrip("。"))}</b>'
                     f'<span>{esc(_li_head)}</span></p>'
                     + (f'<ul class="lsum-list">{"".join(_rows)}</ul>' if _rows else "")
                     + (f'<p class="lsum-ok"><span class="lsum-tag good">{STATUS_ICON["good"]} 正常</span>'
                        f'{esc("、".join(_ok))}</p>' if _ok and _rows else "")
                     + '</div>') if d["lights"] else ""

    # 收合摘要：一律取這一區已經算出來的結論。
    _dh = d.get("decomp_head") or {}
    _dec_sum = (f'名目 10 年期 {_dh["nominal"]}　·　其中期限溢酬 {_dh["value"]}'
                if _dh else "名目利率的三段拆解")
    _ss = d.get("supply_side") or {}
    _sup_sum = (f'政府年赤字 {_ss["gov_display"]}　·　'
                f'科技巨頭年化 {_ss["hs_display"]}' if _ss else "供給來源與壓力分數")
    _dm = (sp.demand or [{}])[0]
    _dem_sum = (f'{_dm["label"]} {_dm["value"]}　·　{_dm["detail"]}'
                if _dm else "需求端的溫度計")
    _pr_sum = (f'已反映 {sp.priced_score:+.2f}　·　供給壓力 {sp.score:+.2f}'
               if sp.priced else "價格已經反映多少")
    _dg = d.get("debt_gap") or {}
    _debt_sum = (f'財政缺口 {_dg["value"]}　·　{debt_title}' if _dg else debt_title)
    # 收合摘要把「前瞻」放在最前面：整卡的主詞是接下來要花多少，
    # 佔比與發債都是那個承諾的後果。
    #
    # 摘要有 45 字的上限（test_sections 釘住），所以加了指引就要讓出位置：
    # 讓的是發債筆數——它在卡片展開後有自己的區塊，而「承諾要花多少
    # vs 現金流撐不撐得住」這一組對照，收合時看不到就沒別的地方看得到。
    _gd = d.get("guidance") or {}
    _off_av = bool((d.get("offerings") or {}).get("available"))
    _hs_ratio = (f'佔營運現金流 {hs.capex_to_ocf:.0f}%'
                 if hs.capex_to_ocf is not None else "")
    if _gd.get("available"):
        _hs_sum = (f'{_gd["year"]} 年計畫 {_gd["total_display"]}'
                   + (f'　·　{_hs_ratio}' if _hs_ratio else f'　·　{hs_title}'))
    else:
        _hs_sum = ((f'資本支出{_hs_ratio}　·　{hs_title}'
                    if _hs_ratio else hs_title)
                   + (f'　·　近 120 天 {d["offerings"]["count"]} 筆發債交易'
                      if _off_av else ""))

    def _cmoves(items) -> str:
        return "".join(
            f'<div class="cmove"><div>{esc(p["label"])}</div>'
            f'<div class="cm-delta {"up" if p["score"] > 0 else "down"}">{p["score"]:+.2f}</div>'
            f'<div class="cm-val">{esc(p["detail"])}</div></div>'
            for p in items)

    parts = _cmoves(sp.parts)

    # ---- 結論卡的刻度軸 ----
    # 「+1.16」單看沒有刻度感。軸範圍取 −3～+3：這個分數只由兩個
    # 供給來源構成，各自的合理區間約在 ±1.5 之內。
    _lo, _hi = -3.0, 3.0
    _pct = max(0, min(100, (sp.score - _lo) / (_hi - _lo) * 100))
    _col = ("var(--serious)" if sp.level == "high" else
            ("var(--series-1)" if sp.level == "low" else "var(--muted)"))
    pressure_axis = f"""<div class="sax compact">
  <div class="sax-head">
    <span class="sax-label">供給壓力分數</span>
    <span class="sax-val" style="color:{_col}">{sp.score:+.2f}</span>
    <span class="sax-delta">只由供給來源構成，不含已反映在價格上的部分</span>
  </div>
  <div class="score-bar">
    <i style="left:{min(50, _pct):.1f}%;width:{abs(_pct - 50):.1f}%;background:{_col}"></i>
    <span class="score-mid"></span>
  </div>
  <div class="sax-scale"><span>−3 壓力小</span><span>0 中性</span><span>+3 壓力大</span></div>
</div>"""

    # ---- 期限溢酬：這一頁的主角 ----
    dh = d.get("decomp_head") or {}
    decomp_head_html = (
        f'<div class="bkgap" style="color:{dh["color"]};margin-top:4px;'
        f'padding-top:0;border-top:none">'
        f'<span class="bk-label">名目 10 年期 {esc(dh["nominal"])}　其中期限溢酬</span>'
        f'<span class="bk-val">{esc(dh["value"])}</span>'
        f'<span class="bk-verdict" style="font-weight:400;font-size:12.5px;'
        f'color:var(--muted)">{esc(dh["change"])}</span></div>'
        if dh else "")

    # 這張卡自己的一句結論。門檻沿用 decomp_head 的配色邏輯（0.6／0.2），
    # 不另立一套標準——同一個數字不能在同一張卡上被兩套門檻評價。
    _cv = d.get("curve")
    _tp = getattr(_cv, "term_premium", None) if _cv is not None else None
    decomp_impact = ""
    if _tp is not None:
        _chg = f"（{dh['change']}）" if dh.get("change") else ""
        if _tp > 0.6:
            decomp_impact = (
                f'<div class="impact hawkish">期限溢酬 {_tp:+.2f}%{esc(_chg)}，'
                f'水準偏高（高於 0.60%，ACM 2015 年以來約第 90 百分位）——市場對長期持債要求的補償偏高，'
                f'這一段降息壓不下來。</div>')
        elif _tp < 0.2:
            decomp_impact = (
                f'<div class="impact dovish">期限溢酬 {_tp:+.2f}%{esc(_chg)}，'
                f'低於中性參考——長端目前沒有要求額外補償，'
                f'利率主要跟著政策預期走。</div>')
        else:
            decomp_impact = (
                f'<div class="impact neutral">期限溢酬 {_tp:+.2f}%{esc(_chg)}，'
                f'在中性區間——供給壓力存在，但市場還沒要求明顯的額外補償。</div>')

    # ---- 供給端：政府 vs 科技巨頭 ----
    # 這張卡是整頁的關鍵連結。沒有它，債務動態與科技巨頭就只是
    # 剛好被放在同一頁的兩個主題。
    ss = d.get("supply_side") or {}
    supply_html = ""
    if ss:
        _sum = ss.get("summary", "")
        _sum_html = "".join(
            (f"<b>{esc(s)}</b>" if i % 2 else esc(s))
            for i, s in enumerate(_sum.split("**")))
        # 來源數量不能寫死：縮表那一項在 TREAST 抓不到時不會出現，
        # 寫死「兩個來源」而畫面上列了三項，讀者會以為少看了什麼。
        _n_parts = "一二三四五六"[max(0, len(sp.parts) - 1)]
        supply_html = f"""
<div class="grid">
  <div class="card">
    <h2 id="supply" data-sum="{esc(_sup_sum)}">債券供給：政府與科技巨頭</h2>
    <p class="hint">政府、科技巨頭與聯準會縮表（到期的公債不再買回去），
      <b>三個來源競爭的是同一批固定收益買盤</b>。</p>
    {f'<div class="impact {lean_cls}">{_sum_html}</div>' if _sum else ''}
    <div class="stat-row" style="margin-top:14px">
      <div class="stat"><div class="s-label">政府：年度赤字</div>
        <div class="s-value">{esc(ss['gov_display'])}</div>
        <div class="s-note">{esc(ss['gov_note'])}</div></div>
      <div class="stat"><div class="s-label">科技巨頭：年化發債</div>
        <div class="s-value">{esc(ss['hs_display'])}</div>
        <div class="s-note">{esc(ss['hs_note'])}</div></div>
    </div>
    {(f'<div class="bkgap" style="color:var(--text-primary)">'
      f'<span class="bk-label">科技巨頭相對政府的規模</span>'
      f'<span class="bk-val">{esc(ss["ratio_display"])}</span></div>')
     if ss.get('ratio_display') else ''}
    <p class="hint" style="margin-top:12px">壓力分數的{esc(_n_parts)}個來源：</p>
    <div class="cmoves" style="border-top:none;padding-top:0">{parts}</div>
    {teach(
        "最近誰在大量發行長天期債券：政府（財政赤字）與科技巨頭（AI 資本支出）。",
        "債券多到買不完，價格就跌、殖利率就升——跟任何市場一樣是供需。長端的供給壓力大，降息也壓不下長端利率。",
        "把政府與企業的發行量加起來看方向：兩邊同時放量，長端承壓最重；這也是「降息但房貸利率不降」的常見原因。", learn="refunding")}
    <div class="src">單位：億美元。年化＝單季 × 4，只用來比較量級。</div>
  </div>
</div>"""

    # ---- 需求端 ----
    dem = (sp.demand or [{}])[0]
    demand_html = demand_more = ""
    if dem:
        # 一句結論用統一的 .impact 框；「為什麼利差是溫度計」的完整說明
        # 收進卡尾展開——說明文字要跟著判定走。先前寫死「它沒有走闊」，
        # 一旦利差真的走闊，同一張卡就會出現自相矛盾。
        _tight = bool(dem.get("tight"))
        if _tight:
            _why = ("利差是買方要求的風險補償。它<b>已經走闊</b>——"
                    "買方開始要求更高的補償才願意接下新供給，"
                    "這是需求端吃不下的第一個訊號。供給若沒有同步收斂，"
                    "壓力會直接落到長端殖利率上。")
        else:
            _why = ("利差是買方要求的風險補償。它<b>還沒走闊</b>——"
                    "代表目前的新增供給仍被吸收得掉；"
                    "一旦走闊，就是買盤開始吃不下的第一個訊號。")
        demand_html = (
            f'<div class="impact {"hawkish" if _tight else "neutral"}">'
            f'{esc(dem["label"])} {esc(dem["value"])}——{esc(dem["detail"])}。</div>')
        demand_more = (
            '<details class="f-more"><summary>利差為什麼是買方的溫度計</summary>'
            f'<div class="f-detail">{_why}</div></details>')

    # ---- 已反映多少 ----
    # 一句結論直接用 gap_note（原因與結果的落差判定），傾向由同一個
    # 差值推出：門檻 ±0.8 跟 analysis/rates.py 產生 gap_note 的門檻一致。
    priced_html = ""
    if sp.priced:
        _gap = sp.score - sp.priced_score
        _pl = "hawkish" if _gap > 0.8 else ("dovish" if _gap < -0.8 else "neutral")
        priced_html = (
            f'<div class="impact {_pl}">{esc(sp.gap_note)}</div>'
            f'<div class="bkgap" style="color:var(--text-primary)">'
            f'<span class="bk-label">供給壓力分數 {sp.score:+.2f}　vs　已反映分數</span>'
            f'<span class="bk-val">{sp.priced_score:+.2f}</span></div>'
            f'<div class="cmoves" style="border-top:none;padding-top:0">'
            f'{_cmoves(sp.priced)}</div>')

    # ---- 科技巨頭的頭條數字：一句結論框 ----
    # 傾向沿用 hs.verdict 的判定；分段門檻（100／70）跟 hs_verdict() 一致。
    # 完整敘述（hs_desc）收進「五家公司的明細」，常駐只留一句。
    _ratio = hs.capex_to_ocf
    _hs_lean = ("hawkish" if getattr(hs, "verdict", "") == "debt_funded"
                else "neutral")
    hs_impact = ""
    if _ratio is not None:
        _tail = ("，超過本業賺進來的現金——缺口靠發債補，長端供給壓力持續。"
                 if _ratio > 100 else
                 ("，逼近本業現金能支應的上限。" if _ratio > 70 else
                  "，本業現金仍蓋得住，對債市的供給壓力有限。"))
        hs_impact = (f'<div class="impact {_hs_lean}">{esc(hs_title)}——'
                     f'合計資本支出已達同期營運現金流的 {_ratio:.0f}%{_tail}</div>')

    # ---- 方法與資料來源（2026-10 v2，使用者：收合裡文字雜亂）----
    # 拆成三小塊，各用表格：① 資料時效（一家一列）② 近期發債（最近 5 筆，其餘再展開）
    # ③ 方法（4 條重點）。先前的長段落說明全部濃縮進 ③。
    gd = d.get("guidance") or {}
    ea = d.get("earnings") or {}
    off = d.get("offerings") or {}
    _ea = {r["name"]: r for r in (ea.get("rows") or [])} if ea.get("available") else {}
    _gdr = {r["name"]: r for r in (gd.get("rows") or [])} if gd.get("available") else {}

    def _md(x: str) -> str:
        x = str(x or "")
        return f"{int(x[5:7])}/{int(x[8:10])}" if len(x) >= 10 and x[4] == "-" else (x or "—")
    _fresh_rows = ""
    for c in hs.companies:
        e = _ea.get(c["name"])
        g = _gdr.get(c["name"])
        if e and e.get("ahead"):
            st, stc = "新財報已公布，表格待 10-Q", "wait"
        elif not c.get("from_sec"):
            st, stc = "後備值", "off"
        else:
            st, stc = "最新", "ok"
        _pe = _md(c.get("period_end")) if c.get("period_end") else "—"
        if stc == "wait":
            _d8 = esc(_md(e["date"]))
            st = ('待 10-Q<small>財報稿 '
                  + (f'<a href="{esc(e["url"])}" target="_blank" rel="noopener">{_d8}</a>' if e.get("url") else _d8)
                  + '</small>')
        else:
            st = esc(st)
        _gv = esc(g["value"].replace(" 億美元", "")) if g else "—"
        # 一家一列：桌機是四欄；手機兩行（公司＋狀態／季末・計畫）
        _fresh_rows += (f'<div class="hs5-r"><b class="hs5-n">{esc(c["name"])}</b>'
                        f'<span class="hs5-m"><span><em>季末</em>{esc(_pe)}</span>'
                        f'<span><em>{esc(str(gd.get("year", "")))} 計畫</em>{_gv}</span></span>'
                        f'<span class="hs4-st {stc}"><i></i><span>{st}</span></span></div>')
    fresh_html = (f'<div class="hs4-sec"><div class="hs4-h">資料時效</div>'
                  f'<div class="hs5 hs5-f"><div class="hs5-r hs5-hd"><span>公司</span>'
                  f'<span class="hs5-m"><span>表格季末</span><span>{esc(str(gd.get("year", "")))} 計畫（億美元）</span></span>'
                  f'<span>財報狀態</span></div>{_fresh_rows}</div>'
                  + (f'<p class="hs4-n">計畫更新於 {esc(_md(gd.get("as_of", "")))}；表格只用 10-Q（約比財報稿晚兩週）。</p>'
                     if gd.get("available") else "")
                  + '</div>')

    offerings_html = ""
    if off.get("available") and off.get("rows"):
        def _off_row(r) -> str:
            amt = esc(r["amount"]) + (f'<small>{esc(r["usd_note"])}</small>' if r.get("usd_note") else "")
            src = (f'<a href="{esc(r["url"])}" target="_blank" rel="noopener">{esc(r["form"])}</a>'
                   if r.get("url") else esc(r["form"]))
            # 一筆一列：桌機五欄；手機兩行（公司＋金額／日期・類型・原文）
            return (f'<div class="hs5-r"><b class="hs5-n">{esc(r["name"])}</b>'
                    f'<span class="hs5-m"><span>{esc(_md(r["date"]))}</span><span>{esc(r["kind"])}</span>'
                    f'<span>{src}</span></span>'
                    f'<span class="hs5-a{" pend" if r.get("pending") else ""}">{amt}</span></div>')
        _head = ('<div class="hs5-r hs5-hd"><span class="hs5-n">公司</span><span class="hs5-m"><span>日期</span>'
                 '<span>類型</span><span>原文</span></span><span class="hs5-a">金額（原幣）</span></div>')
        rows = off["rows"]
        top = "".join(_off_row(r) for r in rows[:5])
        more = ""
        if rows[5:]:
            more = (f'<details class="f-more"><summary>其餘 {len(rows) - 5} 筆</summary>'
                    f'<div class="hs5 hs5-o">' + "".join(_off_row(r) for r in rows[5:]) + '</div></details>')
        if off.get("insane"):
            _line = f"近 120 天 {off['count']} 筆已定價；金額解析異常，暫不顯示合計"
        else:
            _line = (f"近 120 天 {off['count']} 筆已定價，合計 {esc(off['total_display'])}"
                     + (f"（季報發債的 {esc(off['ratio_display'])}）" if off.get("ratio_display") else "")
                     + "，尚未進季報")
        _extra = "　".join(x for x in (
            f"另 {off['unknown_n']} 筆金額待確認。" if off.get("unknown_n") and not off.get("insane") else "",
            f"另 {off['prelim_n']} 筆已宣布、未定價。" if off.get("prelim_n") else "",
            f"另 {off['other_n']} 件非債券融資不列。" if off.get("other_n") else "") if x)
        offerings_html = (f'<div class="hs4-sec"><div class="hs4-h">近期發債</div>'
                          f'<p class="hs4-lead">{_line}。</p>'
                          f'<div class="hs5 hs5-o">{_head}{top}</div>'
                          + (f'<p class="hs4-n">{_extra}</p>' if _extra else "") + more + '</div>')

    # ---- 財政：一句結論＋缺口併進 stat-row ----
    # 傾向直接沿用 debt.verdict 的判定（widening／drifting／stable），
    # 不在頁面層另算一套。widening 對長端是升壓＝hawkish；其餘中性。
    dg = d.get("debt_gap") or {}
    _debt_lean = ("hawkish" if getattr(d.get("debt"), "verdict", "") == "widening"
                  else "neutral")
    debt_impact = (f'<div class="impact {_debt_lean}">{esc(debt_title)}——'
                   f'{esc(debt_desc)}</div>') if debt_desc else ""
    _debt_stats = list(d["debt_stats"])
    if dg:
        _debt_stats.append({"label": "財政缺口", "value": dg["value"],
                            "color": dg["color"], "note": dg["note"]})

    def _hs_row(c: dict) -> str:
        yoy_txt = "—" if c.get("capex_yoy") is None else f'{c["capex_yoy"]:+.0f}%'
        ratio = c.get("capex_to_ocf")
        ratio_txt = "—" if ratio is None else f"{ratio:.0f}%"
        cls = "neg" if c.get("cash_negative") else ""
        # 期末日逐家標示：各家會計年度不同，同一列的「最新一季」不是同一季。
        # 沒有期末日代表這一列是 config 的手動後備值——那要明講，不能留白，
        # 因為留白看起來只是「少標一個日期」，而不是「這個數字沒被核對過」。
        pe = c.get("period_end") or ""
        tag = esc(pe) if pe else "未取自 SEC"
        name = f'{esc(c["name"])}<span class="dnote">{tag}</span>'
        # 資本支出佔營收：規模差五倍的兩家公司，同樣的「資本支出 200 億」
        # 代表的擴張強度完全不同。營收本來就跟 capex／ocf 一起從 EDGAR 抓，
        # 只是沒印出來——加一欄就把「絕對金額」變成可以互相比較的比率。
        rev = c.get("revenue") or 0
        cap_rev = f"{c['capex'] / rev * 100:.0f}%" if rev else "—"
        return (f'<tr><td>{name}</td>'
                f'<td>{c["capex"] * 10:,.0f}</td>'
                f'<td class="muted-cell">{yoy_txt}</td>'
                f'<td class="muted-cell">{c["ocf"] * 10:,.0f}</td>'
                f'<td class="{cls}">{ratio_txt}</td>'
                f'<td class="muted-cell">{cap_rev}</td>'
                f'<td>{c["issued"] * 10:,.0f}</td></tr>')

    hs_rows = "".join(_hs_row(c) for c in hs.companies)
    # 三個常駐數字（2026-10）：季資本支出合計、佔營運現金流、單季發債合計
    _hs_q = "".join(
        f'<div><span>{esc(x["label"])}</span><b'
        + (' class="over"' if x["label"] == "佔營運現金流" and (hs.capex_to_ocf or 0) > 100 else "")
        + f'>{esc(x["value"])}</b><small>{esc(x.get("note", ""))}</small></div>'
        for x in d["hs_stats"][:3])
    _gn = "".join(f'<li><b>{esc(r["name"])}</b>：{esc(r["note"])}</li>'
                  for r in gd.get("rows") or [] if r.get("note"))
    if gd.get("missing"):
        _gn += f'<li><b>{esc(gd["missing"])}</b>：未提供年度指引，不在合計內。</li>'

    # 資料來源逐家列出，附上 EDGAR 的申報清單連結，讓讀者能自己核對。
    # 這一區的每個結論都建立在這五家的數字上，沒有連結就等於要人相信我。
    _srcs = " ".join(
        (f'<a href="{esc(c["filings_url"])}" target="_blank" rel="noopener">'
         f'{esc(c["name"])}</a>' if c.get("filings_url") else esc(c["name"]))
        for c in hs.companies)
    hs_source_html = (
        f'<div class="src">資料來源：SEC EDGAR 公司申報（10-Q／10-K 現金流量表'
        f'）　·　{_srcs}　·　'
        f'{esc(hs.period_span) if hs.period_span else "期別未標示"}'
        f'　·　{hs.n_from_sec} / {len(hs.companies)} 家取自 SEC</div>')

    # 退回後備值時要分辨「部分」與「全部」——兩者的嚴重程度差很多，
    # 而先前兩種情況的畫面長得一模一樣。全部退回代表整區的數字都是
    # 幾個月前手填的，那時候畫面上的任何結論都不該被當成當前狀況。
    unverified = ""
    if not hs.verified:
        all_stale = hs.n_from_sec == 0
        note = (
            '<b>本區資料尚未更新</b><br>'
            '目前顯示先前整理的資料，並非最新一季財報。'
            '請查看表格標示的期別；上方比率與判讀也以這批資料為依據。'
            if all_stale else
            '<b>部分公司資料尚未更新</b><br>'
            '標為「未取自 SEC」的公司目前顯示先前整理的資料。'
            '請核對表格期別與公司原始財報。')
        unverified = '<div class="warnbox" style="margin-top:14px">' + note + '</div>'

    # ---- 2026-10 改版：各區收合摘要與財政三張事實卡 ----
    _L = d.get("le") or {}
    _c1 = (_L.get("contrib") or {}).get("mtd")
    _dec_sum = (f'本月驅動：{LE.le.COMP_ZH[_c1["main"]]} {LE._bp(_c1["parts"][_c1["main"]])}'
                f'　·　10Y MTD {LE._bp(_c1["nominal"])}' if _c1 and _c1.get("main") else "10Y＝TIPS＋BEI 與期限溢酬")
    _sl = {x["label"]: x for x in _L.get("slopes") or []}
    _crv_sum = "　·　".join(f'{k} {LE._bp(v["value"])}' for k, v in _sl.items()) or "殖利率曲線"
    _gr = (_L.get("global") or {}).get("rows") or []
    # 收合摘要：八國中 MTD 變化（絕對值）最大的前四檔；沒有日資料（退回月均）的國家不參與排名
    _gm = sorted([r for r in _gr if r.get("daily") and r.get("mtd") is not None],
                 key=lambda r: -abs(round(r["mtd"])))[:4]
    _glb_sum = ("MTD 變化最大：" + "　·　".join(f'{r["name"]} {LE._bp(r["mtd"])}' for r in _gm)
                if _gm else "全球長端")
    _wm = _L.get("wam") or {}
    _sup_sum = ((f'Fed WAM {_wm["soma"]["value"]:.1f} 年　·　市場 {_wm["market"]["value"]:.1f} 年')
                if (_wm.get("soma") or {}).get("value") is not None
                and (_wm.get("market") or {}).get("value") is not None else "財政部發行路徑與 Fed 資產端")
    _rc = _L.get("auction_recent") or {}
    _auc_sum = (f'近 3 週：偏弱 {_rc.get("偏弱", 0)}、中性 {_rc.get("中性", 0)}、偏強 {_rc.get("偏強", 0)}'
                if _L.get("auction_recent_n") else "最近各天期的拍賣結果")
    _cs = d.get("credit_stats") or []
    _dem_sum = "　·　".join(f'{x["label"]} {x["value"]}' for x in _cs[:2]) or "信用利差"
    _db = d.get("debt")
    _itr = getattr(_db, "interest_to_revenue", None)
    _rg = getattr(_db, "r_minus_g", None)
    _dfg = getattr(_db, "deficit_gdp", None)
    _cdg = getattr(_db, "cash_deficit_gdp", None)
    _pg = getattr(_db, "pub_gdp", None)
    _da = getattr(_db, "dd_actual", None) or {}
    _q = lambda x: (f"{str(x)[:4]}Q{(int(str(x)[5:7]) - 1) // 3 + 1}" if x and len(str(x)) >= 7 else "")
    _m = lambda x: (str(x)[:7].replace("-", "/") if x else "")
    _debt_stats = [
        {"label": "利息佔稅收", "value": f"{_itr:.1f}%" if _itr is not None else "—",
         "color": ("var(--critical)" if (_itr or 0) > 20 else "inherit"),
         "note": "每收 100 元稅拿去付利息的比例（警戒線 20%）"},
        ({"label": "赤字佔 GDP", "value": f"{_cdg:.1f}%",
          "note": f"近 12 個月現金赤字（月報至 {_m(getattr(_db, 'cash_deficit_asof', ''))}），要靠淨發債填補"}
         if _cdg is not None else
         {"label": "赤字佔 GDP", "value": f"{abs(_dfg):.1f}%" if _dfg is not None else "—",
          "note": "需靠淨發行公債填補的部分"}),
        {"label": "r − g", "value": f"{_rg:+.2f}pp" if _rg is not None else "—",
         "color": ("var(--critical)" if (_rg or -1) > 1 else "var(--warning)" if (_rg or -1) > 0 else "var(--good)"),
         "note": "10Y 殖利率月均 − 名目 GDP 年增；大於零＝債務自我累積"},
    ]
    if _pg is not None:
        _debt_stats.append({"label": "公眾持有債務佔 GDP", "value": f"{_pg:.1f}%",
                            "color": "var(--critical)" if (_da.get("actual") or 0) > 1 else "inherit",
                            "note": (f"{_q(_da['to'])}，一年 {_da['actual']:+.1f}pp" if _da else
                                     _q(getattr(_db, "pub_gdp_asof", "")))})
    _dde = getattr(_db, "dd_eff", None)
    _ddm = getattr(_db, "dd_mkt", None)
    debt_decomp = ""
    if _da:
        _parts = [("基本赤字", _da["primary"], "近四季現金赤字扣掉利息"),
                  ("利息", _da["interest"], "舊債的實際付息"),
                  ("名目成長", _da["growth"], f"GDP 一年 +{_da['g']:.1f}%，把既有債務比稀釋掉"),
                  ("其他", _da["other"], "主要是財政部現金餘額（TGA）變動、借款時點")]
        _rows = "".join(f'<tr><td class="k" data-label="來源"><b>{esc(n)}</b></td>'
                        f'<td data-label="貢獻"><b class="{"up" if v > 0.05 else "dn" if v < -0.05 else ""}">{v:+.1f}pp</b></td>'
                        f'<td data-label="說明">{esc(t)}</td></tr>' for n, v, t in _parts)
        debt_decomp = (f'<table class="lq-tbl"><thead><tr><th colspan="3">過去一年實際：{_q(_da["from"])} → {_q(_da["to"])} '
                       f'公眾持有債務佔 GDP {_da["actual"]:+.1f}pp</th></tr></thead><tbody>{_rows}</tbody></table>')
    if _dde is not None and getattr(_db, "i_pub", None) is not None and _da:
        debt_decomp += (f'<p class="hint">條件不變的未來一年（用公眾持有債務的平均付息率 '
                        f'{_db.i_pub:.1f}%）：約 <b>{_dde:+.1f}pp</b>'
                        + (f'；若全部按今天的 10Y（{getattr(_db, "r_nom", 0):.2f}%）再融資：約 <b>{_ddm:+.1f}pp</b>'
                           if _ddm is not None else "")
                        + '。舊債還鎖在較低利率，所以實際付息率低於市場利率，差距會隨舊債到期慢慢收斂。</p>')
    if _itr is not None and _rg is not None:
        _dl = "hawkish" if (_rg > 0 or _itr > 20 or (_dde or 0) > 1 or (_da.get("actual") or 0) > 1) else "neutral"
        _why = ""
        if _da:
            _why = (f"過去一年公眾持有債務佔 GDP {_da['actual']:+.1f}pp：基本赤字 {_da['primary']:+.1f}、利息 {_da['interest']:+.1f}、"
                    f"名目成長 {_da['growth']:+.1f}、其他 {_da['other']:+.1f}（主要是財政部現金餘額變動）。")
        if _dde is not None and _da:
            _why += f"條件不變下，未來一年約 {_dde:+.1f}pp。"
        debt_impact = (f'<div class="impact {_dl}">r − g {_rg:+.2f}pp、利息佔稅收 {_itr:.1f}%——'
                       + ("利率高於成長，即使收支平衡債務比也會自我累積。" if _rg > 0 else
                          "成長仍跑贏利率，利息造成的增加大多被名目成長抵掉；債務比能不能降，取決於基本赤字。")
                       + esc(_why) + '</div>')
    _flw_html, _flw_sum = _flows(d)
    _debt_sum = (f'r − g {_rg:+.2f}pp　·　利息佔稅收 {_itr:.1f}%'
                 if _itr is not None and _rg is not None else "政府財政")
    # 三條路徑：降低赤字、壓低利率、提高成長——現在 vs 一年前，往好的方向還是壞的方向
    _prow = ""
    for _p in getattr(_db, "paths", None) or []:
        if _p.get("now") is None:
            continue
        _chg = (_p["now"] - _p["ago"]) if _p.get("ago") is not None else None
        _good = (_chg is not None and ((_chg < -0.05) if _p["better"] == "down" else (_chg > 0.05)))
        _bad = (_chg is not None and ((_chg > 0.05) if _p["better"] == "down" else (_chg < -0.05)))
        _tag = "改善" if _good else "惡化" if _bad else "持平"
        _ago_s = f'{_p["ago"]:.2f}%' if _p.get("ago") is not None else "—"
        _prow += (f'<tr><td class="k" data-label="路徑"><b>{esc(_p["label"])}</b></td>'
                  f'<td data-label="現在">{_p["now"]:.2f}%</td>'
                  f'<td data-label="一年前">{_ago_s}</td>'
                  f'<td data-label="方向"><span class="st {"good" if _good else "critical" if _bad else "warning"}">{_tag}</span></td></tr>')
    debt_paths = (f'<table class="lq-tbl"><thead><tr><th>壓低債務率的三條路</th><th>現在</th><th>一年前</th><th>方向</th></tr></thead>'
                  f'<tbody>{_prow}</tbody></table>') if _prow else ""

    return f"""
<div class="grid">
  <div class="card">
    <h2 id="decomp" data-sum="{esc(_dec_sum)}">長端利率的組成</h2>
    {LE.decomp(d)}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="hyperscalers" data-sum="{esc(_hs_sum)}">科技巨頭：AI 資本支出與發債</h2>
    <p class="hint">AI 資本支出讓這幾家公司從債市的<b>買方</b>變成<b>賣方</b>——長端供給的另一個來源。</p>
    {hs_impact}
    <div class="hs3-q">{_hs_q}</div>
    {LE.hs_agg_chart(d)}
    {LE.hs_table(d)}
    {unverified}
    {LE.guidance_stale(d).replace('class="warnbox"', 'class="hs3-stale"')}
    <details class="f-more hs4"><summary>資料時效與近期發債</summary>
      {fresh_html}
      {offerings_html}
    </details>
    <details class="f-more hs4"><summary>方法與資料來源</summary>
      <ul class="hs4-m">
        <li><b>口徑</b>：取自 10-Q／10-K 現金流量表；年增對去年同季；佔營運現金流＝合計 ÷ 合計。</li>
        <li><b>季末不同</b>：各家會計年度不同，同一列不是同一季；加總圖依「最近第幾季」對齊。財報新聞稿附日期與原文連結供查閱；表格數字以正式季報為準。</li>
        <li><b>年度計畫</b>：公司法說會公布的資本支出指引。{('<ul>' + _gn + '</ul>') if _gn else ''}</li>
        <li><b>發債</b>：讀說明書判斷是否為債券；預估版不計；美元以定價日匯率換算；只含 SEC 申報。</li>
      </ul>
      {hs_source_html}
    </details>
    {teach(
        "幾家大型科技公司為了 AI 基礎建設花多少錢、自己的現金流夠不夠、缺口是不是靠發債補。",
        "這些公司過去是債券市場的買方（現金太多），AI 資本支出讓它們變成賣方。買方變賣方是雙重打擊——少了買盤、多了供給。",
        "盯加總圖裡「柱子追上橫線」：資本支出超過營運現金流，缺口只能靠發債，供給壓力就會持續。", learn="hyperscaler")}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="curve" data-sum="{esc(_crv_sum)}">殖利率曲線</h2>
    {LE.curve(d)}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="global" data-sum="{esc(_glb_sum)}">全球長端</h2>
    {LE.global_(d)}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="supply" data-sum="{esc(_sup_sum)}">債券供給：財政部與 Fed</h2>
    {LE.supply(d)}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="auctions" data-sum="{esc(_auc_sum)}">Coupon 拍賣結果</h2>
    {LE.auctions(d)}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="buybacks" data-sum="{esc(LE.buyback_summary(d))}">財政部 Buybacks</h2>
    {LE.buybacks(d)}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="demand" data-sum="{esc(_dem_sum)}">債券需求：信用利差</h2>
    {LE.credit(d)}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="debt" data-sum="{esc(_debt_sum)}">政府財政</h2>
    <p class="hint">重點不是債務總額，是<b>利息負擔會不會自我累積</b>。</p>
    {debt_impact}
    <div class="stat-row" style="margin-top:14px">{_stats(_debt_stats)}</div>
    <div class="le-eq">債務率變化 ≈ 基本赤字率 ＋ (r − g) × 債務率</div>
    {debt_decomp}
    {debt_paths}
    <div class="viz-block"><div class="viz-h">r − g（季資料：10Y 季均 − 名目 GDP 年增）</div>{d.get('rg_chart') or ''}</div>
    <div class="viz-block"><div class="viz-h">聯邦債務佔 GDP（季資料，近 3 年）：公眾持有 vs 總債務</div></div>
    {d['debt_chart']}
    {teach(
        "美國政府的赤字規模、利息負擔，以及由此推算的公債發行需求。",
        "財政赤字是長端供給的最大來源，而且跟景氣循環脫鉤了——就算經濟好赤字也降不下來，代表這股供給壓力是結構性的。",
        "盯「利息支出佔比」：利息越滾越大會迫使發債更多，形成自我強化；那是長端利率的長期地心引力。", learn="fiscal")}
    <details data-m-collapse><summary>公式與名詞：債務率怎麼變、r − g 怎麼看</summary>
      <dl class="gloss" style="margin-top:10px">
        <dt>債務率變化</dt>
        <dd>債務率變化 ≈ 基本赤字率 ＋ (r − g)/(1 + g) × 債務率（皆為佔 GDP 比例）。要壓下債務率只有三條路：
          降低赤字、壓低利率、提高成長。上表看三條路各自比一年前好還是壞。</dd>
        <dt>r − g</dt>
        <dd>r 用 10 年期公債殖利率的當月月均（新發債的融資成本），g 用名目 GDP 年增，兩邊都是名目。
          r 低於 g，成長就能逐步消化既有債務——1990 年代末生產力推升名目成長，即使 10 年期長期在 5%～6%，
          債務比仍快速下降；r 高於 g，就算收支平衡債務比也會自我累積。</dd>
        <dt>有效利率（i）</dt>
        <dd>政府實際付出的平均利率＝利息支出 ÷ 公眾持有債務。新債換舊債時它會慢慢往市場利率靠攏，
          所以「條件不變的未來一年」用 i 推估、另用 r 算「全部按今天利率再融資」的上限。</dd>
        <dt>公眾持有債務 vs 總債務</dt>
        <dd>總債務含社安等信託基金持有的部分（政府欠自己），不需要市場吸收；公眾持有債務（含 Fed 持有）
          才是債券市場實際要消化的量，債務動態一律用這個口徑。</dd>
        <dt>過去一年實際的拆解</dt>
        <dd>實際變化＝基本赤字＋利息−名目成長的稀釋（d₀·g/(1+g)）＋其他。赤字用財政部月報（MTS）的現金赤字，
          「其他」是扣掉前三項的差額，主要來自財政部現金餘額（TGA）的增減與借款時點。</dd>
      </dl>
      {(f'<p class="hint" style="margin-top:8px">{esc(d["debt_growth_note"])}</p>'
        if d.get('debt_growth_note') else '')}
    </details>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="flows" data-sum="{esc(_flw_sum)}">市場籌碼</h2>
    {_flw_html}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="lights" data-sum="{esc(light_summary.rstrip('。').replace('項指標：', '項：'))}">關鍵指標檢核與綜合判定</h2>
    <p class="hint">依三個組成份分組；本月驅動 10Y 的那一組排第一。不另設權重——權重由市場這個月的變化決定。</p>
    {lights_impact}
    {LE.lights_grouped(d, lambda l, a: _explained_card(l, a, (d.get("light_explain") or {}).get(l.key)))}
    {teach(
        "長端市場的幾個壓力指標逐一對照警戒線。",
        "單看殖利率水準分不出「經濟強」還是「供給壓垮」，一排指標一起看才分得出漲的原因。",
        "紅燈集中在供給類（發行量、期限溢酬）＝結構性壓力；集中在預期類＝在賭政策，兩者的應對完全不同。")}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="glossary" data-sum="這一頁出現的專有名詞與計算方式">名詞解釋</h2>
        <dl class="gloss">
      <dt>期限溢酬</dt>
      <dd>投資人因需「長期持有」債券而要求的額外補償，包括對未來政策利率與通膨路徑的不確定性，
        及供給增加、財政赤字擴張、法幣貶值、流動性等風險。</dd>
      <dt>通膨損益兩平率</dt>
      <dd>名目公債殖利率減同天期抗通膨債券的殖利率，代表市場對未來平均通膨的定價。
        超過這個數字，買抗通膨債券才划算。</dd>
      <dt>實質利率</dt>
      <dd>剔除通膨補償後的真實資金成本。抗通膨債券（TIPS）的殖利率就是它。</dd>
      <dt>r 減 g</dt>
      <dd>10 年期公債殖利率（當月月均）減名目 GDP 年增，兩邊都是名目。大於零時，
        即使財政收支平衡，債務佔 GDP 比仍會自我累積。</dd>
      <dt>信用利差</dt>
      <dd>公司債殖利率高於同天期公債的部分，也就是投資人要求的信用風險補償。
        本頁指的是廣義的信用利差。</dd>
      <dt>OAS（選擇權調整利差）</dt>
      <dd>針對<b>內含選擇權</b>的債券（例如發行人可提前贖回的公司債），把選擇權的價值扣掉之後的利差。
        ICE BofA 公司債指數裡有很多可贖回債，所以指數用 OAS 表示；本頁把它當作廣義信用利差來讀。</dd>
      <dt>WAM（加權平均剩餘年限）</dt>
      <dd>一籃債券依面額加權的平均剩餘到期年數。Fed 的 WAM 縮短，代表長天期的利率風險留給私人市場。</dd>
      <dt>Tail／Stop-through</dt>
      <dd>拍賣得標殖利率高於拍賣當下市場價＝tail（需求弱）；低於＝stop-through（需求強）。本頁用當日收盤近似，標「≈」。</dd>
      <dt>Indirect／Direct／Primary Dealers</dt>
      <dd>Indirect 多為海外央行與機構透過交易商下單；Direct 是直接投標的國內投資人；Primary Dealers 有義務投標，
        承接剩下的部分——比例越高代表終端需求越弱。</dd>
      <dt>基點（bps）</dt>
      <dd>利率的最小慣用單位，英文縮寫 bp／bps：1 bp＝0.01 個百分點。
        「升 25 個基點」就是升 0.25%，也就是「一碼」。</dd>
      <dt>存續期間需求</dt>
      <dd>市場願意買進長天期債券的總量。政府與企業發債競爭的就是這一池資金，
        供給超過需求時長端殖利率就會被推高。</dd>

      <dt>為什麼財政與科技公司會在同一頁</dt>
      <dd>政府發公債、科技巨頭發投資級公司債，兩者搶的是同一批買盤——
        退休基金、保險公司、外國央行。Fed 雖然已停止縮表，但把到期的 MBS 換成 T-Bills、縮短持有年限，
        長天期的部分一樣要由私人市場吸收。</dd>
      <dt>近期發債交易怎麼來的</dt>
      <dd>來源是 SEC EDGAR 的申報清單，只收 424B2／424B5（定價當日的債券發行
        說明書）與配不到說明書的 8-K 項目 2.03（銀行貸款、私募這一類）。
        FWP 是行銷用的條款表、一筆債會發好幾份，424B3 多半是再售登記、
        公司沒拿到新錢，兩者都不計入。<br>
        同一家公司十天以內的申報視為<b>同一筆交易</b>——一筆債會先出預估版、
        再出定價版，多幣別還會分開申報，不合併的話同一筆會被數兩三次。
        合併後的金額是群組內<b>相異</b>金額的總和：多幣別分券要相加，
        但同一個數字重複出現（重新申報、預估與定價金額相同）只算一次。<br>
        金額採債券說明書確認的實際發行規模；貨架註冊額度不計入。
        尚無法確認的交易標示「待確認」，不計入合計。<br>
        這些交易<b>不進</b>上方表格的「單季發債」：表格只用經審核的季報數字，
        否則同一筆發債下一季會被算第二次。</dd>
      <dt>資本支出指引</dt>
      <dd>各公司在法說會上對<b>整年</b>資本支出的公開承諾，跟下方表格的
        「上一季實際花掉的」是兩件事。長端供給壓力來自還沒花的那一段——
        承諾要花而現金流不夠，差額就得到債市籌。<br>
        年度指引取自公司法說會，來源與更新日標在指引區塊裡。
        未公布指引的公司另列，不計入合計。微軟的會計年度到 6 月，這裡用的是它對日曆年的說明。</dd>
      <dt>財報新聞稿的時效</dt>
      <dd>公司通常先公布財報新聞稿，再提交正式季報。
        表格以正式季報的現金流量表為準，因此可能晚於新聞稿更新。
        可由公布日期與原文連結查看最新消息，並核對各公司的資料期別。</dd>
    </dl>
    {gloss_more()}
  </div>
</div>
"""


def rates_body(d: dict) -> str:
    """
    首卡「Long End Driver」（2026-10 v4）：10／20／30Y 與 DTD／MTD／YTD、本月驅動因素、
    10Y＝TIPS＋BEI 組成條與 ACM 期限溢酬、三個組成份小表與走勢、接下來 4 週的事件。
    """
    return LE.hero(d) + compact_full(_rates_body_full(d), "長端拆解、供給、拍賣與財政")


def rates_footer(d: dict) -> str:
    from ..site import source_footer
    _ten = "官方每日資料；與盤中報價分開呈現"
    return source_footer(
        [("公債殖利率", "美國財政部／FRED 每日殖利率", "每日・" + _ten),
         ("TIPS 實質殖利率、損益兩平", "財政部實質殖利率曲線（FRED DFII10）；BEI＝DGS10 − DFII10", "每日・晚名目一天"),
         ("期限溢酬", "紐約聯儲 ACM（主要）、舊金山聯儲、Kim-Wright（FRED）", "每日・ACM 晚約一個交易日"),
         ("油價", "EIA（FRED）", "每日"),
         ("信用利差", "ICE BofA 指數（FRED）", "每日"),
         ("拍賣結果、買回結果", "財政部 Fiscal Data（auctions_query、buybacks）、TreasuryDirect 暫定排程", "每次拍賣／買回"),
         ("每季再融資聲明", "財政部新聞稿（自動擷取 coupon 指引與買回額度）", "每季"),
         ("流通在外、WAM、Fed 持有", "財政部 MSPD、紐約聯儲 SOMA", "每月／每週"),
         ("聯邦基金期貨、點陣圖", "CBOT 聯邦基金期貨（ZQ）結算價，經 Yahoo Finance 取得；Fed SEP", "每日／每季"),
         ("政府財政", "財政部月報 MTS、公眾持有債務、BEA（FRED）", "每月／每季"),
         ("公債期貨持倉（市場籌碼）", "CFTC Traders in Financial Futures；DV01 為本站以殖利率近似換算", "每週・週二部位、週五公布"),
         ("初級交易商現券庫存", "紐約聯儲初級交易商統計（FR 2004）", "每週・約晚一週"),
         ("全球長端（10 年期）", "財政部、Bundesbank、Bank of England、日本財務省", "每日・英國晚約 2～3 個營業日"),
         ("科技巨頭資本支出與發債", "SEC EDGAR（XBRL 申報、說明書）", "財報一申報即更新")],
        ["利率判讀依據通膨、實質利率與期限溢酬的變化；詳細方法見各區說明。",
         "科技巨頭的年度資本支出計畫來自公司法說會。"],
        head="<b>資料來源</b> FRED、財政部、紐約聯儲、Fed、SEC EDGAR")

