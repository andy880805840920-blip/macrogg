"""通膨頁的內容產生器（P2）。版面與勞動頁一致，讀者同樣是投資人。"""

from __future__ import annotations

from .. import charts
from ..site import esc
from .labor import _kpi_card, _light_card, _flag_row, _stats
from . import compact_full, focus_evidence, state_chip, teach


VERDICT_COPY = {
    "dovish": ("通膨面：利降息",
               "通膨降溫的訊號多於升溫。物價壓力減輕會讓聯準會更有空間降息，"
               "對債券價格通常是正面的。"),
    "hawkish": ("通膨面：利升息",
                "通膨的壓力高於預期。物價降不下來會讓聯準會不敢降息、"
                "甚至重新考慮緊縮，這對債券價格通常是負面的。"),
    "balanced": ("通膨面：本期方向不明",
                 "升溫與降溫的訊號互相抵消，這份數據不足以改變聯準會的方向。"),
}

# 這三句講的都是**本期新訊號的方向**，不是通膨的**水準**。
# 兩者不分清楚會出現「通膨頁說方向不明、九宮格說通膨高」這種看起來
# 自相矛盾的畫面——實際上兩者可以同時成立（卡在高檔但這個月沒有新推力）。
AXIS_NOTE = ("上面那句講的是<b>本期變化的方向</b>。通膨的<b>水準</b>"
             "（離 2% 目標多遠、落在九宮格哪一欄）與跟就業合併之後的結論，"
             "見<a href=\"/scenario/#grid\">情境合成</a>頁——"
             "水準高但本期方向不明，兩者可以同時成立。")


def _tilt(flags) -> dict:
    w = {"alert": 2.0, "watch": 1.0, "info": 0.5}
    dov = sum(w.get(f.severity, .5) for f in flags if f.lean == "dovish")
    haw = sum(w.get(f.severity, .5) for f in flags if f.lean == "hawkish")
    net = haw - dov
    t = "hawkish" if net > 1 else ("dovish" if net < -1 else "balanced")
    return {"dovish": dov, "hawkish": haw, "net": net, "tilt": t}


def _target_axis(tg: dict) -> str:
    """
    離 2% 目標多遠。

    通膨頁沒有勞動頁那種合成分數，但它有一個更硬的錨：聯準會的目標。
    這個數字先前只出現在第三張 KPI 卡的副標裡——它其實是整頁的定調，
    所有其他數字都是在回答「離它多遠、往哪邊走」。
    軸的範圍取 1%–4%：低於 1% 是通縮風險、高於 4% 是明確失控，
    這個區間涵蓋了所有需要細看的狀態。
    """
    v, gap = tg.get("value"), tg.get("gap")
    if v is None or gap is None:
        return ""
    lo, hi = 1.0, 4.0
    pos = max(0.0, min(100.0, (v - lo) / (hi - lo) * 100))
    tpos = (tg["target"] - lo) / (hi - lo) * 100
    color = ("var(--critical)" if gap > 0.75 else
             ("var(--warning)" if gap > 0.25 else "var(--good)"))
    mom = tg.get("momentum")
    mom_txt = ""
    if mom is not None:
        # 水準只講「現在在哪」，動能才講「往哪邊走」。少了後者，
        # 3.0% 這個數字沒辦法判斷是正在收斂還是正在惡化。
        d = mom - v
        word = "正在往目標靠近" if d < -0.15 else (
            "正在往反方向走" if d > 0.15 else "大致持平")
        mom_txt = f"　·　近三個月年化 {mom:.1f}%，{word}"
    return f"""<div class="sax compact">
  <div class="sax-head">
    <span class="sax-label">{esc(tg.get('label', ''))}離 2% 目標</span>
    <span class="sax-val" style="color:{color}">{gap:+.2f}</span>
    <span class="sax-delta">個百分點{esc(mom_txt)}</span>
  </div>
  <div class="tgt-bar">
    <span class="tgt-mark" style="left:{tpos:.1f}%"></span>
    <i style="left:{min(pos, tpos):.1f}%;width:{abs(pos - tpos):.1f}%;background:{color}"></i>
    <span class="tgt-dot" style="left:{pos:.1f}%;background:{color}"></span>
  </div>
  <div class="sax-scale"><span>1%</span><span>2% 目標</span><span>4%</span></div>
</div>"""


def _ladder_rows(rows) -> str:
    """
    動能階梯：每個指數一列「12 → 6 → 3 個月年化」。

    最右（最新的 3 個月年化）字級大一號，並依「對 12 個月的差距」上色：
    門檻 ±0.3 跟黏性卡本身「差距小於 0.3 一律當卡在原地」同一套，
    不另立標準。
    """
    def pv(v):
        return f"{v:.2f}%" if v is not None else "—"
    out = []
    for r in rows or []:
        cls = ""
        if r.get("v3") is not None and r.get("v12") is not None:
            _d = r["v3"] - r["v12"]
            cls = " accel" if _d > 0.3 else (" decel" if _d < -0.3 else "")
        out.append(
            f'<div class="ld-row"><span class="ld-k">{esc(r["label"])}</span>'
            f'<span class="ld-v">{esc(pv(r.get("v12")))}</span>'
            f'<span class="ld-a">→</span>'
            f'<span class="ld-v">{esc(pv(r.get("v6")))}</span>'
            f'<span class="ld-a">→</span>'
            f'<span class="ld-v last{cls}">{esc(pv(r.get("v3")))}</span></div>')
    if not out:
        return ""
    return (f'<div class="ladder">{"".join(out)}'
            '<div class="ld-cap">近 12 → 6 → 3 個月年化；越靠右越新，'
            '右邊高於左邊＝在加速（±0.3 內視為持平）</div></div>')


def _sticky_card(k: dict | None) -> str:
    """
    核心服務的黏性。排在關鍵訊號之後，因為它是降息時間表的主要阻力——
    這一塊不鬆，前面所有的好消息都換不到降息。

    主軸是**方向**不是水準：3.9% 且在加速，比 4.1% 且在減速更該擔心。
    所以動能階梯（12m/6m/3m）放在最上面，水準只是它的其中一格。
    """
    if not k:
        return ""
    _v = "".join((f"<b>{esc(s)}</b>" if i % 2 else esc(s))
                 for i, s in enumerate(k["verdict"].split("**")))
    # 黏性 vs 彈性收進展開層：常駐兩個結論框＋兩排數字，正是「同一張卡
    # 要重新學兩次哪行是重點」的排版問題。它的結論寫在收合列上。
    sf = k.get("sticky_flex") or {}
    sf_html = ""
    if sf:
        sf_html = f"""
    <details data-m-collapse><summary>黏性 vs 彈性：{esc(sf['note'])}</summary>
      <p class="hint" style="margin:10px 0 0">彈性項先反應、黏性項最後才動，
        <b>兩者收斂才算走完</b>。</p>
      <div class="stat-row" style="margin-top:10px">{_stats(sf['stats'])}</div>
    </details>"""

    # CPI 版與 PCE 版背離的解釋是方法說明（權重差在哪、以哪邊為準），
    # 常駐會擋在數字前面——收進下方「為什麼看三個時間尺度」的方法層。
    _dv = ""
    if k.get("diverge"):
        _d = "".join((f"<b>{esc(s)}</b>" if i % 2 else esc(s))
                     for i, s in enumerate(k["diverge"].split("**")))
        _dv = f'<br>{_d}'

    return f"""<div class="grid">
  <div class="card">
    <h2 id="sticky" data-sum="{esc(k['sum'])}">核心服務的黏性</h2>
    <p class="hint">降息時間表卡最久的一塊。看的是<b>方向</b>不是水準。</p>
    <div class="impact {k['lean']}" style="margin-bottom:14px">{_v}</div>
    {_ladder_rows(k.get('ladders'))}
    {teach(
        "服務類（剔除住房）的物價還在以多快的速度上漲、已經連續多久降不下來。",
        "商品價格漲了會回落，服務價格漲了很難回頭——它的成本主要是人的薪水，而薪水幾乎不會降。這一塊不鬆，聯準會就不敢降息，所以它是降息時間表卡最久的關卡。",
        "先看方向（在加速還是減速），再看連續高於門檻的月數——月數越多代表卡得越久，別只看單月數字。")}
    {sf_html}
    <details class="f-more"><summary>為什麼看三個時間尺度、為什麼是 2.5%</summary>
      <div class="f-detail">
        單一個數字看不出方向。12 個月是趨勢、3 個月是當下，
        <b>短天期低於長天期就是在減速</b>，反過來就是重新加速——
        聯準會官員談這一塊時引用的也是這個形式。差距小於 0.3 個百分點時
        一律當「卡在原地」，因為月度資料的雜訊就有這個量級。{_dv}<br>
        「連續幾個月高於 2.5%」用的是三個月年化。門檻不取 2%（目標值）
        是因為月度雜訊會讓它頻繁穿越，數字會失去意義；2.5% 才代表真的卡住，
        而不是在目標附近正常擺盪。<br>
        薪資是這一塊的上游——往下捲的
        <a href="#passthrough">薪資到服務業通膨的傳導</a>是同一條線。
      </div>
    </details>
  </div>
</div>"""


def _verdict_card(d: dict) -> str:
    flags = d["flags"]
    tilt = d["tilt"]
    title, why = VERDICT_COPY.get(tilt["tilt"], VERDICT_COPY["balanced"])
    n_dov = sum(1 for f in flags if f.lean == "dovish")
    n_haw = sum(1 for f in flags if f.lean == "hawkish")
    top = next((f for f in flags if f.severity == "alert"), flags[0] if flags else None)
    lead = f"最主要的訊號是：{top.headline}。" if top else ""
    return f"""<div class="verdict {tilt['tilt']}">
  <div class="v-eyebrow">{esc(d['data_month'])} 物價數據　·　一句話結論</div>
  <div class="v-main">{esc(title)}</div>
  <div class="v-why">{esc(lead)}{esc(why)}</div>
  {_target_axis(d.get('target') or {})}
  <div class="v-count">
    本次共 {len(flags)} 項訊號：{n_dov} 項利降息、{n_haw} 項利升息。
    {AXIS_NOTE}
  </div>
</div>"""


def _passthrough(p) -> str:
    if not p or not p.get("available"):
        return (f'<div class="warnbox"><b>尚無法估計</b><br>'
                f'{esc((p or {}).get("reason", "資料不足"))}</div>')
    # 這一段是在說上面那個判定的分析基礎不成立，不是平行的第二個結論。
    # 先前兩個警示框同等視覺重量地並排，讀者不知道該信哪一個。
    # 改成縮排掛在結論框底下，明確是「但書」。
    # 但書的結論寫在收合列上，統計細節點開才看——它是「要驗算才需要」
    # 的層級，常駐一整段會把方法論擋在數字前面。
    corr_warn = (f'<details class="f-more"><summary>但書：這段樣本不支持'
                 f'「薪資推升通膨」的機制</summary>'
                 f'<div class="f-detail">{esc(p["corr_note"])}</div></details>'
                 if p.get("corr_note") else "")
    # 結論框的傾向沿用 analysis/passthrough.py 的 verdict：
    # 兩個背離方向都是上行風險（機制不同），只有同步才是良性。
    _pt_lean = {"supercore_above": "hawkish", "wage_above": "hawkish",
                "aligned": "neutral"}.get(p.get("verdict", ""), "neutral")
    return f"""<div class="impact {_pt_lean}">{esc(p['verdict_title'])}——{esc(p['verdict_desc'])}</div>
<div class="stat-row" style="margin-top:14px">{_stats(p['stats'])}</div>
<h3>平均時薪年增率</h3>
{p['wage_chart']}
<h3>核心服務除住房年增率</h3>
{p['sc_chart']}
<p class="hint" style="margin-top:14px">
  兩條線分開畫，不用雙軸——不同尺度硬放同一張圖會製造出實際上不存在的關係。
</p>
{teach(
    "薪資漲幅跟服務類物價漲幅的關係：薪資先動、物價多久之後跟上。",
    "服務業最大的成本是人。薪資一直漲，服務價格降不下來；反過來，薪資降溫是服務通膨要降的前提。看薪資等於提前看幾個月後的服務通膨。",
    "兩條線的差距在縮小＝傳導壓力在減；薪資年增若降到 3% 附近，大致與 2% 通膨相容（差額靠生產力吸收）。")}
<details data-m-collapse><summary>領先落後的相關性</summary>
  <table style="margin-top:10px">
    <thead><tr><th>薪資領先期數</th><th>相關係數</th></tr></thead>
    <tbody>{p['lag_rows']}</tbody></table>
  <p class="hint" style="margin-top:10px">{esc(p['note'])}</p>
</details>
{corr_warn}"""


def _inflation_body_full(d: dict) -> str:
    k = d["kpi"]
    mini = d.get("mini", {})
    a = d.get("asof", {})
    lean = d.get("kpi_lean", {})
    # 意外值併進卡片。通膨沒有模型推估的後備，所以沒填預期時
    # surp 是空的，卡片上就完全不會出現這一行（見 consensus.yaml 的說明）。
    surp = (d.get("surprises") or {}).get("inline") or {}
    _fresh = bool(d.get("is_fresh"))
    kpis = "".join([
        _kpi_card("CPI 月增率", k["headline_display"], k["headline_sub"],
                  k["headline_plain"], charts.sparkline(k["headline_spark"]),
                  mini=mini.get("headline", ""), asof=(a.get("cpi") or "")[:7],
                  surprise=surp.get("headline"), fresh=_fresh,
                  en="Headline CPI, m/m", leans=lean.get("headline", ())),
        _kpi_card("核心 CPI 月增率", k["core_display"], k["core_sub"],
                  k["core_plain"], charts.sparkline(k["core_spark"]),
                  k.get("core_flag"), k.get("core_flag_kind", ""),
                  mini=mini.get("core", ""), asof=(a.get("cpi") or "")[:7],
                  surprise=surp.get("core"), fresh=_fresh,
                  en="Core CPI, m/m", leans=lean.get("core", ())),
        _kpi_card("核心 PCE 年增率", k["pce_display"], k["pce_sub"],
                  k["pce_plain"], charts.sparkline(k["pce_spark"]),
                  k.get("pce_flag"), k.get("pce_flag_kind", ""),
                  mini=mini.get("pce", ""), asof=(a.get("pce") or "")[:7],
                  fresh=_fresh,
                  en="Core PCE, y/y", leans=lean.get("pce", ())),
        _kpi_card("5年後5年期通膨預期", k["exp_display"], k["exp_sub"],
                  k["exp_plain"], charts.sparkline(k["exp_spark"]),
                  mini=mini.get("exp", ""), asof=(a.get("exp") or "")[:7],
                  fresh=_fresh,
                  en="5y5y Inflation Breakeven", leans=lean.get("exp", ())),
    ])

    flags_html = "".join(_flag_row(f) for f in d["flags"]) or \
        '<div class="empty">本次沒有觸發任何訊號</div>'
    # 每顆燈連回「主場」卡區（同一個數字的完整脈絡在那裡）。
    _anchor_map = [("三月年化", "#kpi"), ("服務除住房", "#sticky"),
                   ("核心 PCE", "#kpi"), ("中位數", "#trend"),
                   ("核心除住房", "#trend"), ("通膨預期", "#kpi"),
                   ("汽油", "#energy"), ("核心商品", "#contrib")]

    def _anchor(label: str) -> str:
        return next((a for k, a in _anchor_map if k in label), "")
    lights_html = "".join(_light_card(l, _anchor(l.label)) for l in d["lights"])
    att = d["attribution"]

    trend_rows = "".join(
        f'<tr><td>{esc(r["label"])}</td><td>{esc(r["value"])}</td>'
        f'<td class="muted-cell">{esc(r["note"])}</td></tr>'
        for r in d["trend_rows"]
    )

    # 有填預期才顯示來源說明。沒填時整段不出現——通膨不退回模型推估，
    # 所以也沒有「這不是市場共識」需要提醒。
    surp_foot = (f'<div class="kpi-foot">預期來源：'
                 f'{esc((d.get("surprises") or {}).get("sources", ""))}</div>'
                 if surp else "")

    # ---- 分項貢獻的分解條 ----
    #
    # 這裡**沒有等號，也不算差額**。
    #
    # 先前寫的是「三塊相加 ＝ +0.05（實際漲幅 +0.12 個百分點）」，再配一段
    # 「權重過期或四捨五入會讓兩邊對不上」。那個框法把讀者的注意力整個
    # 帶到「為什麼加不起來」，而那是錯的問題——BLS 的 CPI 是分層鏈式聚合、
    # 權重在期間內本身也會動，所以「單一時點權重 × 累計變化」的加總本來就
    # 不必等於官方漲幅。用官方權重驗過：估算合計 +0.17pp、實際 +0.12%，
    # 仍差 0.05。那是方法差異，不是計算錯誤。
    #
    # 這一區要回答的是：**哪些類別在推升 CPI、哪些在壓低。**
    parts = att.get("parts") or []
    parts_html = ""
    if parts:
        span = max(abs(x["value"]) for x in parts) or 1
        rows = "".join(
            f'<div class="dc-row">'
            f'<div class="dc-name">{esc(x["label"])}</div>'
            f'<div class="dc-bar"><span class="dc-zero"></span>'
            f'<i style="{"left" if x["value"] >= 0 else "right"}:50%;'
            f'width:{abs(x["value"]) / span * 50:.1f}%"></i></div>'
            f'<div class="dc-val">{x["value"]:+.2f}pp</div></div>'
            # 沒有說明的類別不留空行——五條各掛一行說明會把卡撐成十行
            + (f'<div class="dc-note">{esc(x["note"])}</div>'
               if x.get("note") else "")
            for x in parts
        )
        parts_html = f'<div class="dcomp">{rows}</div>'

    # 「剔除住房後比含住房高」每期都可能出現，而且每次都會被讀成算錯。
    # 它其實是重要訊息（住房在把整體往下拉），所以直接寫成一句話。
    _sn = att.get("shelter_note") or ""
    shelter_html = ""
    if _sn:
        # **粗體** 轉成 <b>，其餘照 esc 處理
        parts_txt = _sn.split("**")
        rendered = "".join(
            (f"<b>{esc(seg)}</b>" if i % 2 else esc(seg))
            for i, seg in enumerate(parts_txt))
        # 它是這張卡的結論，不是警告——用統一的 .impact 框
        shelter_html = f'<div class="impact neutral">{rendered}</div>'

    # ---- 趨勢指標的結論 ----
    # 用統一的 .impact 框，不用大型 verdict 框——每頁只有頁首一個大結論框，
    # 卡內的結論全站都是同一種樣式。
    tv = d.get("trend_verdict") or {}
    _tvk = {"hawkish": "hawkish", "dovish": "dovish"}.get(
        (tv or {}).get("kind", ""), "neutral")
    trend_html = (
        f'<div class="impact {_tvk}">{esc(tv["title"])}——{esc(tv["desc"])}</div>'
        if tv else '<div class="empty">資料不足</div>')

    # ---- 能源對總體的估計影響 ----
    eh = d.get("energy_headline") or {}
    energy_head = (
        f'<div class="bkgap" style="color:{eh["color"]}">'
        f'<span class="bk-label">對總體 CPI 的估計影響</span>'
        f'<span class="bk-val">{esc(eh["value"])}</span>'
        f'<span class="bk-verdict" style="font-weight:400;font-size:12.5px;'
        f'color:var(--muted)">{esc(eh["note"])}</span></div>'
        if eh else "")

    # 收合摘要：一律取這一區已經算出來的結論，不另外造句——
    # 摘要與內文若各說各話，收合狀態反而會誤導。
    _top = next((f for f in d["flags"] if f.severity == "alert"),
                (d["flags"] or [None])[0])
    _sig_sum = (f'{len(d["flags"])} 項　·　{_top.headline}' if _top
                else "本次沒有觸發任何訊號")
    _k = d["kpi"]
    _kpi_sum = (f'CPI 月增 {_k["headline_display"]}　·　核心月增 {_k["core_display"]}'
                f'　·　核心 PCE 年增 {_k["pce_display"]}')
    # 收合摘要改成一句結論（主要推力是誰），不再重印兩個統計數字——
    # 那兩個數字展開後 stat-row 裡就有，印在標題列等於同一數字出現兩次。
    _att_parts = d["attribution"].get("parts") or []
    _att_sum = (f'主要推力：{_att_parts[0]["label"]} '
                f'{_att_parts[0]["value"]:+.2f}pp' if _att_parts
                else "、".join(f'{s["label"]} {s["value"]}'
                               for s in d["attribution"]["stats"][:1]))
    # trend_verdict 是 dict（title/desc/kind），不是字串——直接 esc() 會把
    # 整個 dict 的 repr 印到標題列上。
    _tv = d.get("trend_verdict") or {}
    _trend_sum = esc(_tv.get("title") if isinstance(_tv, dict) else _tv
                     or "剔除極端值後的比較")
    _pt = d.get("passthrough") or {}
    _pt_sum = esc(_pt.get("verdict_title") or "資料不足")
    _en_sum = "　·　".join(f'{s["label"]} {s["value"]}'
                          for s in d["energy_stats"][:2])
    _lt = {}
    for _l in d["lights"]:
        _lt[_l.status] = _lt.get(_l.status, 0) + 1
    _light_sum = "、".join(
        f'{_n} 項{_lab}' for _key, _lab in
        (("critical", "警戒"), ("warning", "留意"), ("good", "正常"),
         ("unknown", "無資料")) if (_n := _lt.get(_key)))
    # 檢核卡的一句結論：只由紅黃燈數量推出，跟勞動、長端頁同一套做法。
    _lt_crit, _lt_warn = _lt.get("critical", 0), _lt.get("warning", 0)
    if _lt_crit:
        _lt_lean, _lt_txt = "hawkish", "通膨壓力已越過警戒線，注意集中在哪一類。"
    elif _lt_warn:
        _lt_lean, _lt_txt = "neutral", "沒有警戒，但有指標貼近門檻，方向要盯。"
    else:
        _lt_lean, _lt_txt = "neutral", "各項都在警戒線內。"
    _lights_impact = (f'<div class="impact {_lt_lean}">{esc(_light_sum)}'
                      f'——{esc(_lt_txt)}</div>' if d["lights"] else "")

    return f"""
{_verdict_card(d)}

<div class="grid">
  <div class="card">
    <h2 id="signals" data-open="1" data-sum="{esc(_sig_sum)}">本期關鍵訊號</h2>
    <p class="hint">這個月<b>新發生</b>的事；目前的整體狀態看最下方「關鍵指標檢核」。點「依據」看支撐的數字。</p>
    {flags_html}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="kpi" data-open="1" data-sum="{esc(_kpi_sum)}">關鍵數字</h2>
    <div class="grid g4 inner">{kpis}</div>
    {surp_foot}
  </div>
</div>

{_sticky_card(d.get('stickiness'))}

{_ppi_card(d.get('ppi'))}

<div class="grid">
  <div class="card">
    <h2 id="contrib" data-sum="{esc(_att_sum)}">分項貢獻分解</h2>
    <p class="hint"><b>本月</b>哪些類別在<b>推升</b> CPI、哪些在<b>壓低</b>。
      單月分項會被一次性項目帶著跑（能源單月 ±5% 很常見），
      趨勢看「關鍵數字」的三個月年化。
      貢獻的單位是<b>個百分點（pp）</b>，跟價格漲幅的 % 不是同一件事。</p>
    {shelter_html}
    <div class="stat-row" style="margin-top:14px">{_stats(att['stats'])}</div>
    {parts_html}
    {teach(
        "這個月物價的漲幅，是住房、食物、能源還是其他項目造成的。",
        "「CPI 漲 0.3%」看不出該擔心什麼。漲的若集中在能源，通常過幾個月自己回落；集中在住房與服務，才是聯準會頭痛的那種通膨。",
        "看哪幾條在零線右邊（推升）、哪幾條在左邊（壓低）。分項加總與官方總數用不同方法計算，不會剛好相等，這是正常的。")}
    <details data-m-collapse><summary>估算方法</summary>
    <p class="hint" style="margin-top:10px">
      估算貢獻 ≈ 該類別的 BLS Relative Importance × 該類別本月價格變化，
      是<b>近似估算</b>，用來看方向與相對大小；官方 CPI 採動態權重與
      分層聚合，所以分項加總不必等於官方漲幅。
      住房占 CPI 權重超過三分之一，即使漲幅不大也會明顯影響整體。</p>
    </details>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="trend" data-sum="{_trend_sum}">通膨廣度：中位數與截尾平均</h2>
    <p class="hint">三個指標用不同方法剔除極端值，再跟核心 CPI 比對。</p>
    {trend_html}
    {teach(
        "把幾百個品項攤開看：是大多數東西都在漲，還是只有少數幾樣在拉高平均。",
        "同樣是 3% 的通膨，「什麼都貴了 3%」跟「只有機票和蛋在暴漲」是兩回事。前者需要升息對付，後者等供給恢復就好。",
        "中位數與截尾平均高＝廣泛在漲；它們低但總數高＝少數項目拉的，讀總數時要打折。")}
    <details data-m-collapse><summary>三個指標的定義與數值</summary>
      <table class="lefty" style="margin-top:10px">
        <thead><tr><th>指標</th><th>目前</th><th>算法</th></tr></thead>
        <tbody>{trend_rows}</tbody></table>
      <dl class="gloss" style="margin-top:14px">
        <dt>中位數 CPI</dt>
        <dd>把所有項目依漲幅排序，取正中間那一個。完全不受極端值影響。</dd>
        <dt>截尾平均</dt>
        <dd>把漲最多和跌最多的項目都剔除後再平均。</dd>
        <dt>黏性 CPI</dt>
        <dd>只看價格很少調整的項目（例如房租、保險）。這些代表通膨的慣性，
          一旦漲上去就很難降下來。</dd>
      </dl>
    </details>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="passthrough" data-sum="{_pt_sum}">薪資到服務業通膨的傳導</h2>
    <p class="hint"><b>薪資走向會在數月後反映到服務類物價</b>，
      是通膨黏性的核心機制。</p>
    {_passthrough(d.get('passthrough'))}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="energy" data-sum="{esc(_en_sum)}">能源價格與傳導</h2>
    <p class="hint">「已經發生但還沒反映到數據裡」的部分。</p>
    <div class="impact neutral">{esc(d.get('energy_core_note', ''))}
      <b>除非久到推高通膨預期</b>，油價不改變利率決策。</div>
    <div class="stat-row" style="margin-top:14px">{_stats(d['energy_stats'])}</div>
    {energy_head}
    <h3 style="margin-top:20px">WTI 原油（{esc(d.get('oil_span', ''))}）</h3>
    <p class="hint" style="margin:0 0 8px">虛線是一個月前的位置。</p>
    {d.get('oil_chart', '')}
    {teach(
        "油價最近的變動，以及它大概會在一到兩個月後對總體 CPI 造成多大影響。",
        "能源只佔 CPI 約 6%，但波動極大，常常是單月 CPI 意外的主因。先知道油價動了多少，下個月 CPI 出爐時就不會被表面數字嚇到。",
        "油價大漲後的 CPI 若只是總數高、核心不高，別急著改判斷——聯準會看的也是剔除能源的核心。")}
    <details data-m-collapse><summary>零售汽油價格（{esc(d.get('gas_span', ''))}）</summary>
      <div style="margin-top:12px">{d.get('gas_chart', '')}</div>
      <p class="hint" style="margin-top:10px">
        汽油是 CPI 能源項裡權重最大的一塊，也是消費者最有感的價格。
        它落後原油約兩到四週。</p>
    </details>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="lights" data-sum="{esc(_light_sum)}">關鍵指標檢核</h2>
    <p class="hint">八項關鍵指標的當期狀態（不限本月）。</p>
    {_lights_impact}
    <details data-m-collapse open><summary>八項指標</summary>
      <div class="lights" style="margin-top:12px">{lights_html}</div>
    </details>
    {teach(
        "八個通膨相關指標逐一對照警戒線，紅黃綠一眼掃完。",
        "單一指標會騙人（基期效應能讓年增率忽高忽低），一排一起看才知道壓力是全面的還是個別的。",
        "數紅燈，並注意紅燈集中在哪一類——集中在服務類比集中在能源類嚴重得多。")}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="glossary" data-sum="這一頁出現的專有名詞">名詞解釋</h2>
        <dl class="gloss">
      <dt>CPI</dt>
      <dd>消費者物價指數。統計一籃子商品與服務的價格變化，是最常被報導的通膨指標。</dd>
      <dt>核心 CPI</dt>
      <dd>剔除食物與能源後的 CPI。這兩項波動太大，剔除後比較看得出趨勢。</dd>
      <dt>PCE / 核心 PCE</dt>
      <dd>另一套物價指數，涵蓋範圍比 CPI 廣，也會反映消費者的替代行為。
        <b>聯準會的 2% 長期目標以總體 PCE 衡量；核心 PCE 用來看基礎趨勢。</b></dd>
      <dt>核心服務除住房</dt>
      <dd>英文常稱 supercore。這一塊的成本主要是人力，所以跟薪資直接連動，
        是聯準會判斷通膨是否真的受控的關鍵。</dd>
      <dt>住房項的落後</dt>
      <dd>CPI 的住房是把所有既有租約一起平均，新簽的租金要一年多才會完全反映進去。
        所以看到的住房數字其實是去年的行情。</dd>
      <dt>三個月年化</dt>
      <dd>把最近三個月的漲幅換算成一年的速度。比年增率更早反映轉折，
        因為年增率會被一年前的舊數字拖住。</dd>
      <dt>通膨預期</dt>
      <dd>市場或民眾認為未來通膨會是多少。一旦大家「相信」通膨會一直高，
        就會反映在定價和薪資談判上，通膨會自我實現——這是聯準會最怕的事。</dd>
    </dl>
  </div>
</div>
"""


def _ppi_card(pp: dict | None) -> str:
    """
    生產者物價 PPI——上游價格，也是核心 PCE 成分法推估的原料之一。

    這張卡只回答一個問題：上游的成本壓力有多大（會不會在一兩季後變成
    CPI）。核心 PCE 推估的計算過程（成分表、回測誤差、方法選擇）呈現在
    情境頁四步卡的②步——那個值是判九宮格用的，計算跟著用途走；
    這裡只留一行推估值＋連結。
    """
    if not pp or pp.get("core_yoy") is None:
        return ""
    def pv(v, d=1):
        return f"{v:+.1f}%" if v is not None else "—"
    gap = pp.get("gap_vs_cpi")
    gap_note, _gap_impact = "", ""
    if gap is not None:
        gap_note = ("出廠價漲得比零售價快，企業還沒把成本轉嫁完，"
                    "未來幾季 CPI 有上行壓力。" if gap > 0.3 else
                    ("出廠價漲得比零售價慢，企業利潤在吸收成本，"
                     "下游漲價壓力較小。" if gap < -0.3 else
                     "上下游漲幅相當，管線裡沒有明顯的未轉嫁壓力。"))
        _gl = ("hawkish" if gap > 0.3 else
               "dovish" if gap < -0.3 else "neutral")
        _gap_impact = f'<div class="impact {_gl}">{esc(gap_note)}</div>'
    stats = _stats([
        {"label": "核心 PPI 年增", "value": pv(pp["core_yoy"]),
         "note": f'三月年化 {pv(pp.get("core_3m"))}'},
        {"label": "總體 PPI 年增", "value": pv(pp.get("headline_yoy")),
         "note": "含食物與能源"},
        {"label": "PPI − CPI 差距", "value": (f'{gap:+.1f} 個百分點'
                                             if gap is not None else "—"),
         "note": "正值＝上游漲得比下游快"},
    ])

    # 推估的計算過程（成分表、回測誤差）呈現在情境頁四步卡的②步——
    # 那個值是拿去判九宮格通膨水準用的，計算該跟著用途走。這裡只留一行。
    nc = pp.get("nowcast") or {}
    nc_html = ""
    if nc.get("estimated") and nc.get("value") is not None:
        _ncv = f'{nc["value"]:.2f}%'
        nc_html = (f'<p class="hint" style="margin:12px 0 0">核心 PCE 推估 '
                   f'{esc(_ncv)}，<a href="/scenario/">計算見情境頁②步</a>。</p>')

    return f"""<div class="grid">
  <div class="card">
    <h2 id="ppi" data-sum="核心 PPI {esc(pv(pp['core_yoy']))}　·　PPI−CPI {esc(f'{gap:+.1f}pp' if gap is not None else '—')}">生產者物價 PPI（上游）</h2>
    <p class="hint">企業的出廠價。資料至 {esc((pp.get('asof') or '—')[:7])}。</p>
    {_gap_impact}
    <div class="stat-row" style="margin-top:14px">{stats}</div>
    {nc_html}
    {teach(
        "企業賣給下游的價格（出廠價）漲了多少。CPI 是你我付的零售價，PPI 是它的上游。",
        "物價的傳導有順序：出廠價先動、幾個月後零售價跟上。PPI 還有一個特殊角色——PCE 的醫療與金融服務項直接取自 PPI（PCE 量的是含保險給付的全部費用，CPI 只量自付額），所以月底的 PCE 月中就能推出來。",
        "看 PPI−CPI 差距：正值代表企業還沒轉嫁完、未來 CPI 有上行壓力。本站的核心 PCE 推估值就是從 CPI 與 PPI 組出來的，計算過程在情境頁的「這一格怎麼算」。")}
  </div>
</div>"""


def inflation_body(d: dict) -> str:
    """決策優先：首卡串起 PPI → CPI → PCE，其餘完整保留在單一收合。"""
    s, a = d["summary"], d.get("asof", {})
    def pv(v):
        return f"{v:.1f}%" if v is not None else "—"
    def move(short, long):
        if short is None or long is None:
            return "資料不足"
        return "升溫" if short > long + .2 else ("降溫" if short < long - .2 else "持平")
    pce_move = move(s.pce_core_3m, s.pce_core_yoy)
    ppi_move = move(s.ppi_core_3m, s.ppi_core_yoy)
    title = f"核心 PCE {pce_move}，PPI 壓力{ppi_move}"
    metrics = "".join([
        state_chip("總體 CPI｜民眾體感", pv(s.headline_yoy), "含食物與能源"),
        state_chip("核心 CPI｜消費端趨勢", pv(s.core_yoy), f"3M 年化 {pv(s.core_3m)}"),
        state_chip("總體 PCE｜Fed 2% 目標", pv(s.pce_headline_yoy), f"3M 年化 {pv(s.pce_headline_3m)}"),
        state_chip("核心 PCE｜九宮格水準", pv(s.pce_core_yoy), f"動能 {pce_move}",
                   "hawkish" if pce_move == "升溫" else "dovish" if pce_move == "降溫" else "neutral"),
    ])
    chain = f'''<div class="grid-flow">
      <div class="flow-box"><strong>PPI｜企業上游</strong><div class="flow-values">
        總體 {pv(s.ppi_headline_yoy)} · 核心 {pv(s.ppi_core_yoy)} · 3M {pv(s.ppi_core_3m)}<br>
        只判斷成本壓力，不直接移動九宮格。</div></div><div class="flow-arrow">→</div>
      <div class="flow-box"><strong>CPI｜消費者價格</strong><div class="flow-values">
        總體 {pv(s.headline_yoy)} · 核心 {pv(s.core_yoy)} · 3M {pv(s.core_3m)}<br>
        最早確認消費端轉折與分項來源。</div></div><div class="flow-arrow">→</div>
      <div class="flow-box"><strong>PCE｜政策口徑</strong><div class="flow-values">
        總體 {pv(s.pce_headline_yoy)} · 核心 {pv(s.pce_core_yoy)} · 3M {pv(s.pce_core_3m)}<br>
        核心年增決定格位；方向由核心 CPI 月步速（0.2 準則）決定。</div></div></div>'''
    chain = focus_evidence(chain, "查看 PPI、CPI、PCE 傳導")
    def _next_tag(key: str, label: str) -> str:
        v = d.get(f"next_{key}")
        return (f'<span class="data-tag next">下次 {label} '
                f'{esc(v[5:].replace("-", "/"))}</span>' if v else "")
    tags = (f'<div class="data-line"><span class="data-tag">CPI {(a.get("cpi") or "—")[:7]}</span>'
            f'<span class="data-tag">PPI {(a.get("ppi") or "—")[:7]}</span>'
            f'<span class="data-tag">PCE {(a.get("pce") or "—")[:7]}</span>'
            '<span class="data-tag">CPI 口徑：月增（季調）；動能：月步速對 0.2</span>'
            + _next_tag("cpi", "CPI") + _next_tag("pce", "PCE") + '</div>')
    hero = (f'<div class="grid"><div class="card focus-card"><div class="focus-eyebrow">Inflation now</div>'
            f'<h2 class="focus-title">{esc(title)}</h2><p class="focus-sub">'
            '先看核心 PCE 的格位與方向，再用 CPI 拆消費端、PPI 看上游風險；三者不混成單一分數。</p>'
            f'<div class="focus-grid">{metrics}</div>{chain}{tags}</div></div>')
    return hero + compact_full(_inflation_body_full(d), "完整通膨拆解")


def inflation_footer(d: dict) -> str:
    return (
        "資料來源：美國勞工統計局（BLS）、經濟分析局（BEA）、"
        "克里夫蘭聯準銀行與亞特蘭大聯準銀行，經 FRED 取得。<br>"
        f"CPI 權重版本：{esc(d.get('weights_vintage', '—'))}"
        "　·　權重每年一月由 BLS 更新，需同步校準。<br>"
        "本頁僅為數據整理，不構成投資建議。"
    )
