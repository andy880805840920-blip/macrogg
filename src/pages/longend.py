"""
長端與債務頁的新區塊（2026-10 改版）：三股力量、曲線、全球長端、供給、拍賣、信用利差。

版面原則（跟通膨頁一致）：
  · 先一句結論、再圖、最後才是方法——方法一律收進折疊
  · 一張圖一個 y 軸；走勢 24 個月；手機上用卡片不用寬表格
  · 只放事實與寫明規則的判定，不做加權總分
"""

from __future__ import annotations
import logging
log = logging.getLogger(__name__)

from ..analysis import longend as le
from ..site import esc
from .. import fmt
from . import teach

CCOL = {"real": "var(--line-1)", "infl": "var(--line-2)", "tp": "#1baf7a"}


def _bp(v, d=0) -> str:
    return "—" if v is None else f"{fmt.signed(v, d)}bp"


def _md(iso: str) -> str:
    try:
        return f"{int(iso[5:7])}/{int(iso[8:10])}"
    except (ValueError, IndexError):
        return iso


# ---------------------------------------------------------------------------
# 頂部結論卡
# ---------------------------------------------------------------------------
def _chg3(c: dict) -> str:
    """DTD／MTD／YTD 三行小字（bp）。"""
    def one(tag, lab):
        v = c.get(tag)
        cls = "up" if (v or 0) > 0 else "dn" if (v or 0) < 0 else ""
        return f'<em class="{cls}">{lab} {_bp(v)}</em>'
    return one("dtd", "DTD") + one("mtd", "MTD") + one("ytd", "YTD")


def hero(d: dict) -> str:
    """
    首卡「Long End Driver」（2026-10 v4）：
      10／20／30 年報價（DTD／MTD／YTD）→ 本月驅動因素一句 →
      10Y ＝ TIPS ＋ BEI 組成條，下方平行一條 ACM 期限溢酬（長度依實際數字對比）→
      三個組成份的小表（最新值＋MTD／YTD，點一行看白話）→ 近 12 個月日資料走勢。
    """
    L = d.get("le") or {}
    D = L.get("drv") or {}
    c1 = (L.get("contrib") or {}).get("mtd")
    y10 = D.get("y10") or {}

    def _q(name, c):
        if not c:
            return ""
        return (f'<div class="le2-qi"><span>{name}</span><b>{c["value"]:.2f}%</b>'
                f'<div class="le2-chg">{_chg3(c)}</div></div>')
    top = ""
    if y10:
        top = (f'<div class="le2-q">{_q("10 年期", y10)}{_q("20 年期", D.get("y20"))}{_q("30 年期", D.get("y30"))}</div>'
               f'<div class="le2-asof">資料 {esc(y10.get("date", ""))}（{esc(d.get("yield_source", "FRED"))} 官方日殖利率）</div>')
    main = (c1 or {}).get("main")
    title = (f'本月驅動因素：{le.COMP_ZH[main]} {_bp(c1["parts"][main])}' if main else "長端殖利率的組成")
    sub = ""
    if c1 and main:
        sub = (f'10Y 本月（至 {_md(c1.get("to") or "")}）{_bp(c1["nominal"])} ＝ 實質利率 {_bp(c1["parts"]["real"])} ＋ 損益兩平 {_bp(c1["parts"]["infl"])}'
               + (f'；期限溢酬（ACM）{_bp(c1["parts"]["tp"])}' if c1["parts"].get("tp") is not None else "")
               + "。")
    table = ""
    comp = {k: D.get(k) or {} for k in ("real", "infl", "tp")}
    if comp["real"] and comp["infl"]:
        from .. import charts
        shade = {"real": "var(--brand-navy)", "infl": "#8b97a8"}
        if main in shade:
            shade[main] = "var(--brand-orange-fill)"
        seg = charts.segbar([{"label": "實質利率（TIPS）", "value": comp["real"]["value"], "color": shade["real"]},
                             {"label": "損益兩平通膨率（BEI）", "value": comp["infl"]["value"], "color": shade["infl"]}])
        tpv = comp["tp"].get("value")
        tot = (comp["real"]["value"] + comp["infl"]["value"]) or 1
        tpbar = ""
        if tpv is not None:
            w = max(0.0, min(100.0, tpv / tot * 100))
            tpbar = (f'<div class="le2-tpbar"><div class="le2-tpt"><span style="width:{w:.2f}%;'
                     f'background:{"var(--brand-orange-fill)" if main == "tp" else "#1baf7a"}"'
                     f' data-tip="期限溢酬（NY Fed ACM）｜{tpv:.2f}%"></span></div>'
                     f'<div class="le2-tpl">期限溢酬（NY Fed ACM）<b>{tpv:.2f}%</b>'
                     f'<small>與 TIPS、BEI 重疊（TIPS 含實質期限溢酬、BEI 含通膨風險溢酬），長度依占 10Y 的比例</small></div></div>')
        rows = ""
        cy = (L.get("contrib") or {}).get("ytd") or {}
        for k in ("real", "infl", "tp"):
            c = dict(comp[k])
            if not c:
                continue
            # MTD／YTD 用跟標題同一組起訖（名目與 TIPS 對齊的那一天），表格與標題的數字才會一致
            if c1 and (c1.get("parts") or {}).get(k) is not None:
                c["mtd"] = c1["parts"][k]
            if (cy.get("parts") or {}).get(k) is not None:
                c["ytd"] = cy["parts"][k]
            is_main = main == k
            src = {"real": "TIPS", "infl": "BEI", "tp": "ACM"}[k]
            rows += (f'<div class="le2-r{" main" if is_main else ""}" title="{esc(le.NATURE[k])}">'
                     f'<div class="le2-n"><span><i class="le2-sw" style="background:'
                     f'{shade.get(k, "#1baf7a") if k != "tp" else ("var(--brand-orange-fill)" if is_main else "#1baf7a")}"></i>'
                     f'{esc(le.COMP_ZH[k])}<em class="le2-src">{src}</em>'
                     + ('<em>本月驅動</em>' if is_main else "") + '</span>'
                     f'<small>{esc(le.PRESSURE_ZH[k])}</small></div>'
                     f'<div class="le2-v"><b>{c["value"]:.2f}%</b>'
                     f'<small>MTD {_bp(c.get("mtd"))}　YTD {_bp(c.get("ytd"))}</small></div></div>')
        table = (f'<div class="le2-seg">{seg}{tpbar}</div><div class="le2-t"><div class="le2-h">'
                 f'<span>10Y 組成（{esc(_md(comp["real"].get("date", "")))}）</span><span>最新｜MTD／YTD</span></div>{rows}</div>'
                 '<p class="le2-tip">點一行看白話說明</p>'
                 f'<div class="viz-block"><div class="viz-h">10Y 名目殖利率與三個組成份（日資料，近 12 個月）</div>'
                 f'{L.get("drv_chart", "")}</div>')
    js = ('<script>(function(){document.querySelectorAll(".le2-r[title]").forEach(function(r){'
          'r.addEventListener("click",function(){r.classList.toggle("tip-on");});});})();</script>')
    return (f'<div class="grid"><div class="card focus-card"><div class="focus-eyebrow">Long End Driver</div>'
            f'<div class="le-hero le2">'
            f'{top}<h2 class="focus-title">{esc(title)}</h2>'
            + (f'<p class="focus-sub">{esc(sub)}</p>' if sub else "")
            + f'{table}{_evidence()}{events(L)}</div></div></div>{js}')


def _evidence() -> str:
    """首卡的「判斷依據」：三個組成份各自用什麼量、怎麼判斷驅動因素。"""
    from . import focus_evidence
    steps = "".join(
        f'<div class="logic-step"><b>{esc(p)}</b><span>{esc(src)}</span></div>'
        for p, src in (
            ("實質利率＝10 年期 TIPS 殖利率", "財政部實質殖利率曲線（FRED DFII10），每日；含預期實質利率路徑＋實質期限溢酬"),
            ("損益兩平通膨率＝10Y 名目 − TIPS", "DGS10 − DFII10（同一天），含預期平均通膨＋通膨風險溢酬；兩項相加恰好等於名目"),
            ("期限溢酬＝NY Fed ACM 10 年", "紐約聯儲 ACM 模型每日估計；含實質期限溢酬＋通膨風險溢酬，跟上面兩項重疊、不相加")))
    return focus_evidence(f'<div class="logic-strip">{steps}</div>'
                          '<p class="hint" style="margin-top:8px">MTD 基期＝上月最後一個交易日、YTD 基期＝去年最後一個交易日；<br>'
                          'TIPS 晚一天公布，拆解的終點取名目與 TIPS 都有資料的最後一天。<br>'
                          '本月驅動因素＝三項中跟 10Y 同方向、MTD 變動最大的那一項（10Y 幾乎沒動時三項一起比）。</p>'
                          '<p class="teach-more"><a href="#decomp">更詳細的解析：01 長端利率的組成 →</a></p>',
                          "查看三個組成份怎麼量")


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
def _trend_line(L: dict) -> str:
    """
    「趨勢還是雜訊」：1、3、12 個月的主因是否一致（規則判定，2026-10）。
      三個窗主因相同          → 趨勢
      1 個月不同、3 與 12 相同 → 本月是短期雜訊，趨勢仍是 3／12 個月那一段
      其他                    → 方向未定
    """
    c = L.get("contrib") or {}
    mains = {k: (c.get(k) or {}).get("main") for k in (1, 3, 12)}
    if not all(mains.values()):
        return ""
    m1, m3, m12 = mains[1], mains[3], mains[12]
    z = le.COMP_ZH
    if m1 == m3 == m12:
        txt, cls = (f"<b>趨勢</b>：{z[m1]}在 1、3、12 個月都是主要驅動因素，"
                    f"這不是單月雜訊。"), "trend"
    elif m3 == m12:
        txt, cls = (f"<b>近期偏雜訊</b>：近 1 個月的驅動因素是{z[m1]}，但 3 與 12 個月都是"
                    f"{z[m3]}——趨勢仍是後者。"), "noise"
    elif m1 == m3:
        txt, cls = (f"<b>新趨勢成形中</b>：近 1、3 個月的驅動因素都是{z[m1]}，"
                    f"12 個月看則是{z[m12]}。"), "turn"
    else:
        txt, cls = (f"<b>方向未定</b>：1、3、12 個月的驅動因素各不相同"
                    f"（{z[m1]}／{z[m3]}／{z[m12]}）。"), "mixed"
    chips = "".join(f'<span><em>{k} 個月</em>{z[mains[k]]}</span>' for k in (1, 3, 12))
    if cls == "trend":            # 三個窗都同一段：標籤列只是重複，不放
        chips = ""
    return (f'<div class="le3-tr {cls}"><p>{txt}</p>'
            + (f'<div class="le3-trc">{chips}</div>' if chips else "") + '</div>')



def _eq_terms(f: str) -> str:
    """
    把公式切成一項一項（在 = ≈ ≡ ⇒ ＋ − 前斷開），每項不可再斷、項與項之間可以換行。
    手機寬度下長公式改成兩三行，不必左右滑；桌機寬度仍是一行。
    運算子留在下一項的開頭（數學排版慣例），一眼看得出是接續上一行。
    """
    import re as _re
    parts = _re.split(r"(\s(?:=|≈|≡|＋|−)\s|　⇒　)", f)
    out, cur = [], parts[0]
    for k in range(1, len(parts), 2):
        out.append(cur)
        cur = parts[k].strip() + " " + parts[k + 1]
    out.append(cur)
    return "".join(f'<span class="eq-t">{t}</span>' for t in out if t.strip())

def _derivation() -> str:
    """長端殖利率拆解推導（Fisher、Lutz、Hicks）——公式用 HTML，不靠外部數學套件。"""
    E = '<i>E</i><sub>t</sub>'
    S = '∑<sub>j=0</sub><sup>n−1</sup>'
    y = 'y<sub>t</sub><sup>(n)</sup>'
    path_i = f'(1/n)·{E}[{S} i<sub>t+j</sub>]'
    path_r = f'(1/n)·{E}[{S} r<sub>t+j</sub>]'
    path_p = f'(1/n)·{E}[{S} π<sub>t+j+1</sub>]'
    tp, rtp, irp = 'TP<sub>t</sub><sup>(n)</sup>', 'RTP<sub>t</sub><sup>(n)</sup>', 'IRP<sub>t</sub><sup>(n)</sup>'
    steps = [
        ("純粹預期理論（Fisher 1896、Lutz 1940）",
         "沒有套利時，長天期殖利率等於各期短期利率的複利結果，近似於預期短率的平均。",
         f'(1 + {y})<sup>n</sup> = {E}[(1+i<sub>t</sub>)(1+i<sub>t+1</sub>)…(1+i<sub>t+n−1</sub>)]　⇒　{y} ≈ {path_i}'),
        ("流動性溢酬理論（Hicks 1939）",
         "持有長債要承擔較大的價格風險（加上違約、通膨風險），需要額外補償＝期限溢酬。",
         f'{y} = {path_i}<span class="eq-l">預期利率路徑</span> ＋ {tp}<span class="eq-l">期限溢酬</span>'),
        ("費雪關係式（Fisher 1930）拆預期利率路徑",
         "名目利率＝實質利率＋預期通膨。",
         f'{path_i} = {path_r}<span class="eq-l">預期實質利率路徑</span> ＋ {path_p}<span class="eq-l">預期平均通膨</span>'),
        ("TIPS 殖利率也有自己的期限溢酬",
         "TIPS 是實質殖利率；持有長天期實質債同樣要求補償＝實質期限溢酬（RTP）。",
         f'y<sub>t</sub><sup>(n),R</sup> = {path_r} ＋ {rtp}'),
        ("通膨風險溢酬",
         "名目期限溢酬與實質期限溢酬的差＝通膨風險溢酬（IRP）。",
         f'{irp} ≡ {tp} − {rtp}'),
        ("名目殖利率拆成四項",
         "代回第 2 步：預期利率路徑與期限溢酬兩項裡，都有「通膨」的影子。",
         f'{y} = {path_r} ＋ {path_p} ＋ {rtp} ＋ {irp}'),
        ("損益兩平通膨率（BEI）",
         "同天期名目殖利率減 TIPS 殖利率；忽略 TIPS 相對名目公債的流動性溢酬（正常市況下很小）。",
         f'BEI<sub>t</sub><sup>(n)</sup> ≡ {y} − y<sub>t</sub><sup>(n),R</sup> = {path_p} ＋ {irp}'),
    ]
    rows = "".join(f'<li><b>{esc(t)}</b><p>{esc(x)}</p><div class="eq">{_eq_terms(f)}</div></li>' for t, x, f in steps)
    return (f'<details class="f-more"><summary>推導：長端殖利率怎麼拆（Fisher、Hicks）</summary><div class="f-detail">'
            f'<ol class="le-deriv">{rows}</ol>'
            '<table class="lq-tbl le-map"><thead><tr><th>市場看得到的</th><th>包含的成分</th></tr></thead><tbody>'
            '<tr><td class="k" data-label="價格"><b>TIPS 實質殖利率</b></td><td data-label="成分">預期實質利率路徑 ＋ 實質期限溢酬</td></tr>'
            '<tr><td class="k" data-label="價格"><b>損益兩平通膨率（BEI）</b></td><td data-label="成分">預期平均通膨 ＋ 通膨風險溢酬</td></tr>'
            '<tr><td class="k" data-label="價格"><b>期限溢酬（模型估計）</b></td><td data-label="成分">實質期限溢酬 ＋ 通膨風險溢酬（再細分可含流動性、財政溢價）</td></tr>'
            '</tbody></table>'
            '<p class="hint">所以實際可觀察、而且能恆等相加的拆法是 <b>名目 ＝ TIPS ＋ BEI</b>；期限溢酬只能靠模型估計，'
            '跟 TIPS、BEI 都有重疊，另外並列。在 Fed 預期長期通膨維持 2% 的背景下，BEI 穩定代表通膨風險溢酬沒有上揚、'
            'Fed 對抗通膨的公信力仍在。</p></div></details>')


def decomp(d: dict) -> str:
    """
    長端利率的組成（2026-10 v4）：
      推導（收合）→ 1／3／12 個月／年初至今的利率橋（市場拆解＋模型拆解）→
      年初至今變化分解（Fig. 5 樣式）→ 三個模型的期限溢酬（近 10 年日資料）。
    """
    L = d.get("le") or {}
    br = L.get("bridges") or {}
    if not br:
        return '<div class="empty">拆解資料不足</div>'
    labs = {1: "1 個月", 3: "3 個月", 12: "12 個月", "ytd": "年初至今"}
    tabs, panes = "", ""
    for i, k in enumerate(k for k in (1, 3, 12, "ytd") if k in br):
        tabs += (f'<input type="radio" name="le-br" id="le-br{k}"{" checked" if i == 0 else ""}>'
                 f'<label for="le-br{k}">{labs[k]}</label>')
        panes += f'<div class="tabp p{k}">{br[k]}</div>'
    D = L.get("drv") or {}
    tpn = "　·　".join(f'{n} {D[k]["value"]:.2f}%（{_md(D[k]["date"])}）'
                      for k, n in (("tp", "ACM"), ("tp_sf", "SF Fed"), ("tp_kw", "Kim-Wright")) if D.get(k))
    return f"""
    {_trend_line(L)}
    {_derivation()}
    <div class="tabs le-tabs">{tabs}{panes}</div>
    <div class="viz-block"><div class="viz-h">年初至今變化分解：市場拆解（bp）</div>
      <p class="viz-sub">10Y 的變化恰好等於 TIPS 與 BEI 變化的和。</p>{L.get('ytd_market', '')}</div>
    <div class="viz-block"><div class="viz-h">年初至今變化分解：模型拆解（bp）</div>
      <p class="viz-sub">預期利率路徑＝10Y − ACM 期限溢酬；兩者變化相加等於 10Y 的變化。</p>{L.get('ytd_model', '')}</div>
    <div class="viz-block"><div class="viz-h">10 年期期限溢酬：三個模型（日資料，近 10 年）</div>
      {(f'<p class="viz-sub">最新：{esc(tpn)}</p>' if tpn else "")}{L.get('tp_models', '')}</div>
    <details class="f-more"><summary>怎麼讀・方法與資料</summary>
      <div class="f-detail le3-how">
        <p><b>怎麼讀</b>：先看首卡的「本月驅動因素」，再看這裡 1、3、12 個月的驅動因素是否同一項：一致才是趨勢。
        市場拆解（TIPS＋BEI）是可交易價格、恆等相加；模型拆解（預期利率路徑＋期限溢酬）回答「是預期在變，還是補償在變」。</p>
        <p><b>資料</b>：名目殖利率 DGS10（財政部）；TIPS 實質殖利率 DFII10（財政部實質殖利率曲線）；BEI＝DGS10 − DFII10。
        期限溢酬：紐約聯儲 ACM（每日，主要口徑）、舊金山聯儲 Christensen–Rudebusch 模型（每日）、Kim-Wright（FRED THREEFYTP10）。
        三個模型的水準差很多，看變化方向比看水準重要。</p>
        <p><b>時間</b>：TIPS 晚名目一天公布；ACM 約晚一個交易日、Kim-Wright 約晚一週。利率橋的終點各自標出資料日期。</p>
      </div>
    </details>"""


# ---------------------------------------------------------------------------
# 殖利率曲線（2026-10 v2）
# ---------------------------------------------------------------------------
_RG_CLS = {"bear_steep": "bear", "bear_flat": "bear", "bull_steep": "bull", "bull_flat": "bull",
           "twist_steep": "tw", "twist_flat": "tw", "flat": "fl", "na": "fl"}


def _sbp(v) -> str:
    return "—" if v is None else fmt.signed(v).replace("-", "−")


_TEN = (("y2", "2", "2Y"), ("y10", "10", "10Y"), ("y30", "30", "30Y"))
_SPK = (("10-2", "10−2"), ("30-10", "30−10"), ("30-2", "30−2"))


def _cls(v) -> str:
    return "flat" if v is None or abs(v) < 0.5 else "up" if v > 0 else "dn"


# 30−2 週報的自訂期間：跟 analysis/longend.brief_window／brief_prose／_brief_text 同一套規則
# （tests/test_curve_window.py 逐字比對；改一邊就要改另一邊）
_CWB_CORE_JS = r"""
function cwBrief(BD){
var TEN=['2','10','30'],SPS=[['10-2','10','2'],['30-10','30','10'],['30-2','30','2']],IDS=['1','2','3','5','7','10','20','30'];
var RGP={bear_steep:'長端升幅大於短端',bull_steep:'短端降幅大於長端',bear_flat:'短端升幅大於長端',bull_flat:'長端降幅大於短端',twist_steep:'短端降、長端升',twist_flat:'短端升、長端降'};
function hu(v,nd){var f=Math.pow(10,nd);return Math.floor(v*f+0.5+1e-10)/f;}
function num(v,nd){nd=nd||0;var r=hu(v,nd);if(r===0)r=0;return r.toFixed(nd).replace('-','−');}
function sgn(v,u,nd){if(u===undefined)u='bp';nd=nd||0;var r=hu(v,nd);if(r===0)return (0).toFixed(nd)+u;return (r>0?'+':'')+num(v,nd)+u;}
function md2(s){return parseInt(s.slice(5,7),10)+'/'+parseInt(s.slice(8,10),10);}
function r6(v){return Math.floor(v*1e6+0.5)/1e6;}
function regime(dl,ds){var x=r6(dl-ds);
 if(Math.abs(x)<2)return{code:'flat',zh:'大致持平',lead:''};
 if(x>0){if(dl>0&&ds<0)return{code:'twist_steep',zh:'扭轉變陡',lead:'兩端反向'};
  if(Math.abs(dl)>=Math.abs(ds))return dl>0?{code:'bear_steep',zh:'熊陡',lead:'長端帶動'}:{code:'bull_steep',zh:'牛陡',lead:'短端帶動'};
  return ds<0?{code:'bull_steep',zh:'牛陡',lead:'短端帶動'}:{code:'bear_steep',zh:'熊陡',lead:'長端帶動'};}
 if(dl<0&&ds>0)return{code:'twist_flat',zh:'扭轉變平',lead:'兩端反向'};
 if(Math.abs(ds)>=Math.abs(dl))return ds>0?{code:'bear_flat',zh:'熊平',lead:'短端帶動'}:{code:'bull_flat',zh:'牛平',lead:'長端帶動'};
 return dl<0?{code:'bull_flat',zh:'牛平',lead:'長端帶動'}:{code:'bear_flat',zh:'熊平',lead:'短端帶動'};}
function fw(y1,n1,y2,n2){var a=Math.pow(1+y1/100,n1),b=Math.pow(1+y2/100,n2);return (Math.pow(b/a,1/(n2-n1))-1)*100;}
function fset(y){var need=['1','2','5','7','10','20','30'];for(var i=0;i<need.length;i++)if(y[need[i]]===null||y[need[i]]===undefined)return null;
 var y3=y['3'],ip=(y3===null||y3===undefined);if(ip)y3=y['2']+(y['5']-y['2'])/3;var y15=(y['10']+y['20'])/2;
 return{'1':{'2':fw(y['1'],1,y3,3),'10':fw(y['1'],1,y['10'],10),'30':fw(y['1'],1,y['30'],30)},
  '5':{'2':fw(y['5'],5,y['7'],7),'10':fw(y['5'],5,y15,15),'30':fw(y['5'],5,y['30'],30)},interp3:ip};}
function day(i){var o={};IDS.forEach(function(k){o[k]=BD.y[k][i];});return o;}
function idx(dt){var i=0;for(var j=0;j<BD.d.length;j++){if(BD.d[j]<=dt)i=j;else break;}return i;}
function win(i0,i1){var Y=BD.y,lv={},sp={},fwd={};
 TEN.forEach(function(k){var a=Y[k][i0],b=Y[k][i1];lv[k]={a:a,b:b,d:(b-a)*100};});
 SPS.forEach(function(p){var a=(lv[p[1]].a-lv[p[2]].a)*100,b=(lv[p[1]].b-lv[p[2]].b)*100,g=regime(lv[p[1]].d,lv[p[2]].d);
  sp[p[0]]={a:a,b:b,d:b-a,code:g.code,zh:g.zh,lead:g.lead};});
 var fn=fset(day(i1)),fp=fset(day(i0));
 if(fn)['1','5'].forEach(function(h){var L=fn[h],spr={},prev=null;SPS.forEach(function(p){spr[p[0]]=(L[p[1]]-L[p[2]])*100;});
  if(fp){prev={};SPS.forEach(function(p){prev[p[0]]=(fp[h][p[1]]-fp[h][p[2]])*100;});}
  fwd[h]={lv:L,sp:spr,prev_sp:prev};});
 var best=null;for(var c=i0+1;c<=i1;c++){var q=c-1,cands=TEN.map(function(k){return[k+' 年',(Y[k][c]-Y[k][q])*100];});
  SPS.forEach(function(p){cands.push([p[0].replace('-','−'),((Y[p[1]][c]-Y[p[2]][c])-(Y[p[1]][q]-Y[p[2]][q]))*100]);});
  cands.forEach(function(x){if(best===null||Math.abs(x[1])>Math.abs(best.d)+1e-9)best={date:BD.d[c],name:x[0],d:x[1]};});}
 return{from:BD.d[i0],to:BD.d[i1],lv:lv,sp:sp,fwd:fwd,move:best,days:i1-i0};}
function verb(v){return Math.abs(r6(v))<1?'幾乎不動':(v>0?'上升 '+num(Math.abs(v))+'bp':'下跌 '+num(Math.abs(v))+'bp');}
function prose(b,events,per,prev){per=per||'本週';prev=prev||'上週';var lv=b.lv,sp=b.sp,fwd=b.fwd,x=sp['30-2'],d2=lv['2'].d,d10=lv['10'].d,d30=lv['30'].d,now=num(x.b),s1;
 if(Math.abs(r6(x.d))<2){var ds=[d2,d10,d30];
  if(ds.every(function(v){return Math.abs(r6(v))<2;}))s1=per+'曲線幾乎沒動：2 年、10 年、30 年變動都在 2bp 以內，30−2 停在 '+now+'bp。';
  else if(ds.every(function(v){return v>0;})||ds.every(function(v){return v<0;})){var ab=ds.map(Math.abs),lo=Math.min.apply(null,ab),hi=Math.max.apply(null,ab);
   var rng=num(lo)!==num(hi)?num(lo)+'–'+num(hi):num(lo);
   s1=per+'曲線大致平行'+(d2>0?'上移':'下移')+'：2 年、10 年、30 年都'+(d2>0?'上升':'下跌')+' '+rng+'bp，形狀幾乎不變，30−2 停在 '+now+'bp。';}
  else s1=per+'曲線形狀幾乎沒變：各天期漲跌互見，30−2 停在 '+now+'bp。';
  var a=sp['10-2'].d,c=sp['30-10'].d;
  if(Math.abs(r6(a))>=2&&Math.abs(r6(c))>=2&&a*c<0)s1=s1.slice(0,-1)+'；不過中段與長段反向（10−2 '+sgn(a)+'、30−10 '+sgn(c)+'），互相抵銷。';}
 else{s1=per+'曲線'+(Math.abs(x.d)>=8?'明顯':'小幅')+(x.d>0?'變陡':'變平')+'：30 年'+verb(d30)+'、2 年'+verb(d2)+(x.lead?'，'+x.lead:'')+'，30−2 '+(x.d>0?'擴大':'收窄')+'到 '+now+'bp。';}
 var out=[s1],mv=b.move;
 if(mv&&Math.abs(mv.d)>=4){var names=[];(events||[]).forEach(function(e){if(e[0]===mv.date&&names.indexOf(e[1])<0)names.push(e[1]);});
  out.push('主要變化集中在 '+md2(mv.date)+'：'+mv.name+'單日'+(mv.d>0?'上升':'下跌')+' '+num(Math.abs(mv.d))+'bp'+(names.length?'，當天有'+names.join('、'):'')+'。');}
 if(fwd['1']&&fwd['5']){var f1=fwd['1'].sp['30-2'],f5=fwd['5'].sp['30-2'],g1=f1-x.b,g5=f5-x.b;
  var c1=g1>5?'up':g1<-5?'dn':'eq',c5=g5>5?'up':g5<-5?'dn':'eq';
  var view={'dn,dn':'市場仍押注曲線未來回平','up,up':'市場押注曲線未來續陡','up,dn':'市場押注一年內續陡、長期回平','dn,up':'市場押注一年內回平、長期再陡',
   'eq,dn':'市場押注一年內大致維持、長期回平','eq,up':'市場押注一年內大致維持、長期更陡','dn,eq':'市場押注一年內回平、之後大致維持','up,eq':'市場押注一年內續陡、之後大致維持','eq,eq':'市場預期曲線大致維持現在的陡度'}[c1+','+c5];
  var s3='市場定價方面，遠期顯示 30−2 一年後約 '+num(f1)+'bp、五年後約 '+num(f5)+'bp，'+view,pv=fwd['1'].prev_sp;
  if(pv){var r=f1-pv['30-2'];s3+=r>2?'；比'+prev+'往變陡修正了 '+num(Math.abs(r))+'bp':r<-2?'；比'+prev+'往變平修正了 '+num(Math.abs(r))+'bp':'，與'+prev+'相近';}
  out.push(s3+'。');}
 return out.join('');}
function text(b,prev){prev=prev||'上週';var lv=b.lv,sp=b.sp,fwd=b.fwd,x=sp['30-2'];
 var move=Math.abs(r6(x.d))<2?'大致持平':x.d>0?'擴大 '+num(Math.abs(x.d))+'bp':'收窄 '+num(Math.abs(x.d))+'bp';
 var s1='30−2 利差 '+num(x.a)+' → '+num(x.b)+'bp（'+move+'）',how;
 var tenors='2Y '+sgn(lv['2'].d)+'、10Y '+sgn(lv['10'].d)+'、30Y '+sgn(lv['30'].d);
 if(x.code==='flat'){var d2=lv['2'].d,d30=lv['30'].d;how=(Math.abs(r6(d2))<2&&Math.abs(r6(d30))<2)?'各天期變動都不大':'兩端同步'+(d2+d30>0?'上行':'下行')+'（大致平行）';}
 else how=x.zh+'：'+(RGP[x.code]||'')+(x.lead&&x.code.indexOf('twist')!==0?'，'+x.lead:'');
 var a=sp['10-2'].d,c=sp['30-10'].d,seg='分段：10−2 '+sgn(a)+'、30−10 '+sgn(c),s3;
 if(Math.abs(r6(x.d))<2)s3=seg+((Math.abs(r6(a))>=2&&Math.abs(r6(c))>=2&&a*c<0)?'，兩段互相抵銷。':'，兩段都沒什麼動。');
 else{var same=[];if(a*x.d>0)same.push([Math.abs(a),'2→10 年段']);if(c*x.d>0)same.push([Math.abs(c),'10→30 年段']);
  var top=same.reduce(function(m,s){return m===null||s[0]>m[0]||(s[0]===m[0]&&s[1]>m[1])?s:m;},null);s3=seg+(top?'，主要來自 '+top[1]+'。':'。');}
 var out=[s1,tenors+'；'+how+'。',s3];
 if(fwd['1']&&fwd['5']){function part(h,zh){var f=fwd[h].sp['30-2'],g=f-x.b,pv=fwd[h].prev_sp;return zh+' 30−2 約 '+num(f)+'bp（比現在 '+sgn(g)+(pv?'，較'+prev+' '+sgn(f-pv['30-2']):'')+'）';}
  out.push('市場隱含：'+part('1','1 年後')+'；'+part('5','5 年後')+'。');
  var g1=fwd['1'].sp['30-2']-x.b,g5=fwd['5'].sp['30-2']-x.b;
  var p1=g1>5?'未來一年續陡':g1<-5?'未來一年回平':'未來一年大致維持',p5=g5>5?'五年後更陡':g5<-5?'五年後更平':'五年後與現在接近',pv=fwd['1'].prev_sp;
  if(pv){var r=fwd['1'].sp['30-2']-pv['30-2'];out.push('定價偏向'+p1+'、'+p5+'；'+(r>2?'較'+prev+'往更陡修正':r<-2?'較'+prev+'往更平修正':'與'+prev+'相近')+'。');}
  else out.push('定價偏向'+p1+'、'+p5+'。');}
 return out;}
return{win:win,prose:prose,text:text,idx:idx,md2:md2};}
"""

_CWB_JS = _CWB_CORE_JS + r"""
(function(){var box=document.querySelector('.cwb');if(!box)return;var el=document.getElementById('cwb-data');if(!el)return;
var BD=JSON.parse(el.textContent),B=cwBrief(BD),fa=box.querySelector('.cwb-from'),fb=box.querySelector('.cwb-to'),cu=box.querySelector('.cwb-cust'),err=box.querySelector('.cwb-err');
var keep={span:box.querySelector('.cwb-span').textContent,prose:box.querySelector('.cwb-prose').textContent,list:box.querySelector('.cwb-more ul').innerHTML};
function safe(v){return String(v).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function press(on){box.querySelectorAll('.cwb-mode').forEach(function(b){b.classList.toggle('on',b===on);b.setAttribute('aria-pressed',String(b===on));});}
function apply(){err.hidden=true;var a=fa.value,b=fb.value;if(!a||!b){err.textContent='請選擇開始與結束日期。';err.hidden=false;return;}
 if(a>b){var t=a;a=b;b=t;}var i0=B.idx(a),i1=B.idx(b);
 if(i1<=i0){err.textContent='期間內至少要有兩個交易日。';err.hidden=false;return;}
 var r=B.win(i0,i1),ev=BD.ev||[];
 box.querySelector('.cwb-span').textContent=B.md2(r.from)+' → '+B.md2(r.to)+'・自訂期間（'+r.from+' 收盤比 '+r.to+' 收盤，'+r.days+' 個交易日）';
 box.querySelector('.cwb-prose').textContent=B.prose(r,ev,'這段期間','期初');
 box.querySelector('.cwb-more ul').innerHTML=B.text(r,'期初').map(function(x){return '<li>'+safe(x)+'</li>';}).join('');}
box.querySelectorAll('.cwb-mode').forEach(function(b){b.addEventListener('click',function(){press(b);
 if(b.dataset.m==='custom'){cu.hidden=false;if(!fa.value){fa.value=BD.d[Math.max(0,BD.d.length-22)];fb.value=BD.d[BD.d.length-1];}apply();}
 else{cu.hidden=true;err.hidden=true;box.querySelector('.cwb-span').textContent=keep.span;box.querySelector('.cwb-prose').textContent=keep.prose;box.querySelector('.cwb-more ul').innerHTML=keep.list;}});});
box.querySelector('.cwb-apply').addEventListener('click',apply);
})();
"""


def _cw_brief(b: dict | None, events=None, bd: dict | None = None) -> str:
    """最上方：一段白話（少數關鍵數字）＋「數字明細」收合。預設滾動一週；可改自訂期間（瀏覽器重算）。"""
    if not b:
        return ""
    import json as _json
    prose = le.brief_prose(b, events)
    detail = "".join(f"<li>{esc(x)}</li>" for x in b["text"])
    span = f"{le._md2(b['from'])} → {le._md2(b['to'])}"
    ctl = cust = data = js = ""
    if bd and len(bd.get("d") or []) > 2:
        lo, hi = bd["d"][0], bd["d"][-1]
        ctl = ('<div class="cw-ctl cwb-modes" role="group" aria-label="週報期間">'
               '<button type="button" class="cw-btn cwb-mode on" data-m="week" aria-pressed="true">最近一週</button>'
               '<button type="button" class="cw-btn cwb-mode" data-m="custom" aria-pressed="false">自訂日期</button></div>')
        cust = (f'<div class="cwb-cust" hidden><label>從 <input type="date" class="cwb-from" min="{lo}" max="{hi}"></label>'
                f'<label>到 <input type="date" class="cwb-to" min="{lo}" max="{hi}"></label>'
                f'<button type="button" class="cwb-apply">套用</button></div><p class="cwb-err" role="alert" hidden></p>')
        payload = {**bd, "ev": [list(e) for e in (events or [])]}
        data = (f'<script type="application/json" id="cwb-data">'
                f'{_json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}</script>')
        js = f"<script>{_CWB_JS}</script>"
    return (f'<section class="cwb" aria-label="30−2 週報"><div class="cwb-h"><b>30−2 週報</b>'
            f'<span class="cwb-span">{span}・滾動一週（最新收盤比 5 個交易日前）</span></div>'
            f'{ctl}{cust}'
            f'<p class="cwb-prose" aria-live="polite">{esc(prose)}</p>'
            f'<details class="cwb-more"><summary>數字明細（各天期、分段、遠期）</summary><ul>{detail}</ul></details>'
            f'{data}{js}</section>')


_ROWS = (("ten", "y2", "2", "2Y"), ("ten", "y10", "10", "10Y"), ("ten", "y30", "30", "30Y"),
         ("sp", "10-2", "10-2", "10−2"), ("sp", "30-10", "30-10", "30−10"), ("sp", "30-2", "30-2", "30−2"))


def _bar(v, scale) -> str:
    """變化欄的細長條：0 在中間，往右＝上升／擴大、往左＝下跌／收窄。"""
    if v is None or not scale:
        return '<i class="cwm-bar"></i>'
    w = min(50.0, abs(v) / scale * 50)
    side = "r" if v > 0 else "l"
    return f'<i class="cwm-bar"><b class="{side} {_cls(v)}" style="width:{w:.1f}%"></b></i>'


def _range(v, lo, hi) -> str:
    """年內位置條：左＝年內最低、右＝年內最高，圓點＝現在。"""
    if v is None or hi is None or lo is None or hi - lo < 1e-9:
        return ""
    p = max(0.0, min(100.0, (v - lo) / (hi - lo) * 100))
    return f'<i class="cwm-rng" title="年內區間"><b style="left:{p:.1f}%"></b></i>'


def _spark(vals) -> str:
    vals = [v for v in vals or [] if v is not None]
    if len(vals) < 5:
        return ""
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    pts = " ".join(f"{i / (len(vals) - 1) * 56:.1f},{14 - (v - lo) / span * 12:.1f}" for i, v in enumerate(vals))
    return (f'<svg class="cwm-spark" viewBox="0 0 56 16" aria-hidden="true">'
            f'<polyline points="{pts}" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>')


def _cw_matrix(b: dict | None, r0: dict, win_label: str) -> str:
    """
    監控表（2026-10 v4）：一列一個標的、從左讀到右。
      現在（含年內位置條）｜週變化｜所選期間（跟期間按鈕連動）｜1 年後隱含｜5 年後隱含
    只有兩個變化欄上色並附細長條；遠期是黑字＋灰色差距＋近 3 個月小走勢線。
    """
    T = {t["k"]: t for t in r0["tenors"]}
    S = {x["key"]: x for x in r0["spreads"]}
    b = b or {}
    lv, sp, fw, yr = b.get("lv") or {}, b.get("sp") or {}, b.get("fwd") or {}, b.get("ytd") or {}
    hist = b.get("fwd_hist") or {}

    def now_of(kind, key):
        if kind == "ten":
            return lv.get(key, {}).get("b")
        return sp.get(key, {}).get("b")

    def week_of(kind, key):
        return (lv if kind == "ten" else sp).get(key, {}).get("d")

    def sel_of(kind, mk):
        return T[mk]["d"] if kind == "ten" else (S[mk]["d"] if mk in S else None)
    scale = {}
    for kind in ("ten", "sp"):
        ks = [r for r in _ROWS if r[0] == kind]
        scale[("w", kind)] = max([abs(week_of(k, key) or 0) for k, _, key, _ in ks] + [2])
        scale[("s", kind)] = max([abs(sel_of(k, mk) or 0) for k, mk, _, _ in ks] + [2])
    head = (f'<thead><tr><th scope="col">標的</th>'
            f'<th scope="col">現在<small>{le._md2(b["to"]) if b else ""}・年內位置</small></th>'
            f'<th scope="col" class="cwm-c">週變化<small>{(le._md2(b["from"]) + " → " + le._md2(b["to"])) if b else ""}</small></th>'
            f'<th scope="col" class="cwm-c cwm-selh">{esc(win_label)}<small class="cwm-when">{le._md2(r0["start"])} → {le._md2(r0["end"])}</small></th>'
            f'<th scope="col" class="cwm-f">1 年後隱含<small>遠期・比現在</small></th>'
            f'<th scope="col" class="cwm-f">5 年後隱含<small>遠期・比現在</small></th></tr></thead>')
    body = []
    for kind, mk, key, zh in _ROWS:
        if kind == "ten" and key == "2":
            body.append('<tr class="cwm-g"><th colspan="6">殖利率（%）</th></tr>')
        if kind == "sp" and key == "10-2":
            body.append('<tr class="cwm-g"><th colspan="6">利差（bp）</th></tr>')
        nv = now_of(kind, key)
        r = yr.get(key) or {}
        now_txt = "—" if nv is None else (le._num(nv, 2) + "%" if kind == "ten" else le._num(nv))
        cells = [f'<th scope="row">{zh}</th>',
                 f'<td class="cwm-now"><span>{now_txt}</span>{_range(nv, r.get("lo"), r.get("hi"))}</td>']
        w = week_of(kind, key)
        cells.append(f'<td class="cwm-c"><span class="{_cls(w)}">{"—" if w is None else le._sgn(w, "")}</span>'
                     f'{_bar(w, scale[("w", kind)])}</td>')
        v = sel_of(kind, mk)
        tag = ""
        if kind == "sp" and mk in S and S[mk]["code"] not in ("na",):
            tag = f'<small class="le3-rg {_RG_CLS.get(S[mk]["code"], "fl")}">{esc(S[mk]["zh"])}</small>'
        cells.append(f'<td class="cwm-c" data-m="{mk}"><span class="{_cls(v)}">{"—" if v is None else le._sgn(v, "")}</span>'
                     f'{_bar(v, scale[("s", kind)])}{tag}</td>')
        for h in ("1", "5"):
            f = fw.get(h)
            if not f or nv is None:
                cells.append('<td class="cwm-f">—</td>')
                continue
            fv = f["lv"][key] if kind == "ten" else f["sp"][key]
            gap = (fv - nv) * 100 if kind == "ten" else fv - nv
            txt = le._num(fv, 2) + "%" if kind == "ten" else le._num(fv)
            cells.append(f'<td class="cwm-f"><span>{txt}</span><small>{le._sgn(gap, "")}</small>'
                         f'{_spark((hist.get(h) or {}).get(key))}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    note = ("變化單位 bp；殖利率為美國財政部官方日資料。年內位置條：左端＝今年最低、右端＝今年最高、圓點＝現在。"
            "遠期由目前曲線推算，含期限溢酬，是市場已定價的路徑、不是預測；小走勢線是近 3 個月的遠期值。"
            "10Y、30Y 遠期以 9 年、29 年（1 年後）與 25 年（5 年後）近似"
            + ("；3 年期資料暫缺，以 2 年與 5 年內插" if b.get("interp3") else "") + "。")
    tog = ('<div class="cw-ctl cwm-tog" role="group" aria-label="表格欄位">'
           '<button type="button" class="cw-btn on" data-v="ch" aria-pressed="true">變化</button>'
           '<button type="button" class="cw-btn" data-v="fw" aria-pressed="false">遠期</button></div>')
    return (f'<div class="cwm" data-v="ch">{tog}<div class="cwm-wrap"><table class="cwm-t" aria-label="2Y、10Y、30Y 與利差監控表">'
            f'{head}<tbody>{"".join(body)}</tbody></table></div>'
            f'<details class="cw-note"><summary>表格說明</summary><p class="cwm-note">{esc(note)}</p></details></div>')


def _cw_folds(r: dict) -> str:
    view = le.window_view(r)
    out = ['<div class="cw-panels">']
    for i, panel in enumerate(view["panels"], 1):
        out.append(f'<details class="cw-panel cw-fold" data-panel="{i}"><summary>'
                   f'<span class="cw-fold-number">{i:02d}</span><span class="cw-fold-title">'
                   f'<b>{esc(panel["title"])}</b><span class="cw-fold-reading">{esc(panel["verdict"])}</span>'
                   f'</span></summary><div class="cw-panel-content"><dl class="cw-metrics">')
        for m in panel["metrics"]:
            out.append(f'<div><dt>{esc(m["label"])}</dt><dd><b>{esc(m["value"])}</b>'
                       f'<small>{esc(m["note"])}</small></dd></div>')
        out.append(f'</dl><small class="cw-panel-note">{esc(panel["note"])}</small></div></details>')
    return "".join(out) + "</div>"


# 自選期間的瀏覽器端：跟 analysis/longend.window_analysis／window_view 同一套規則
# （tests/test_curve_window.py 逐窗比對兩邊輸出）。
_CW_CORE_JS = r"""
function cwCore(CD){var Y=CD.year;
var RG={bear_steep:'bear',bear_flat:'bear',bull_steep:'bull',bull_flat:'bull',twist_steep:'tw',twist_flat:'tw',flat:'fl',na:'fl'};
function idx(dt){var i=0;for(var j=0;j<CD.d.length;j++){if(CD.d[j]<=dt)i=j;else break;}return i;}
function ok(k,j){var a=CD[k]||[];return j>=0&&j<a.length&&a[j]!==null;}
function val(k,i){var a=CD[k]||[];for(var j=i;j>Math.max(-1,i-(k==='tp'?6:1));j--){if(j<a.length&&a[j]!==null)return a[j];}return null;}
function drvIdx(i){for(var j=i;j>Math.max(-1,i-6);j--){if(ok('y10',j)&&ok('be',j)&&ok('real',j))return j;}return null;}
function lagIdx(k,i){for(var j=i;j>Math.max(-1,i-6);j--){if(ok(k,j))return j;}return null;}
function hu(v,nd){var f=Math.pow(10,nd);return Math.floor(v*f+0.5+1e-10)/f;}
function num(v,nd){nd=nd||0;var r=hu(v,nd);if(r===0)r=0;return r.toFixed(nd).replace('-','−');}
function sgn(v,u,nd){if(u===undefined)u='bp';nd=nd||0;var r=hu(v,nd);if(r===0)return (0).toFixed(nd)+u;return (r>0?'+':'')+num(v,nd)+u;}
function md2(s){return parseInt(s.slice(5,7),10)+'/'+parseInt(s.slice(8,10),10);}
function r6(v){return Math.floor(v*1e6+0.5)/1e6;}
function regime(dl,ds){if(dl===null||ds===null)return{code:'na',zh:'—',lead:''};var x=r6(dl-ds);
 if(Math.abs(x)<2)return{code:'flat',zh:'大致持平',lead:''};
 if(x>0){if(dl>0&&ds<0)return{code:'twist_steep',zh:'扭轉變陡',lead:'兩端反向'};
  if(Math.abs(dl)>=Math.abs(ds))return dl>0?{code:'bear_steep',zh:'熊陡',lead:'長端帶動'}:{code:'bull_steep',zh:'牛陡',lead:'短端帶動'};
  return ds<0?{code:'bull_steep',zh:'牛陡',lead:'短端帶動'}:{code:'bear_steep',zh:'熊陡',lead:'長端帶動'};}
 if(dl<0&&ds>0)return{code:'twist_flat',zh:'扭轉變平',lead:'兩端反向'};
 if(Math.abs(ds)>=Math.abs(dl))return ds>0?{code:'bear_flat',zh:'熊平',lead:'短端帶動'}:{code:'bull_flat',zh:'牛平',lead:'長端帶動'};
 return dl<0?{code:'bull_flat',zh:'牛平',lead:'長端帶動'}:{code:'bear_flat',zh:'熊平',lead:'短端帶動'};}
function analysis(start,end){var ia=idx(start),ib=idx(end);if(ia>=ib)ia=Math.max(0,ib-1);
 var da=CD.d[ia],db=CD.d[ib],ten=[],T={};
 [['y2','2 年'],['y10','10 年'],['y30','30 年']].forEach(function(p){var a=val(p[0],ia),b=val(p[0],ib);
  var t={k:p[0],zh:p[1],a:a,b:b,d:(a===null||b===null)?null:(b-a)*100};ten.push(t);T[p[0]]=t;});
 var sp=[];
 [['10-2','y10','y2'],['30-10','y30','y10'],['30-2','y30','y2']].forEach(function(p){var L=T[p[1]],Sh=T[p[2]];
  if(L.a===null||L.b===null||Sh.a===null||Sh.b===null)return;var a=(L.a-Sh.a)*100,b=(L.b-Sh.b)*100,g=regime(L.d,Sh.d);
  sp.push({key:p[0],a:a,b:b,d:b-a,zh:g.zh,lead:g.lead,code:g.code});});
 var ja=drvIdx(ia),jb=drvIdx(ib),be=null,real=null,d10=null,dd=[null,null];
 if(ja!==null&&jb!==null&&ja<jb){be=(CD.be[jb]-CD.be[ja])*100;real=(CD.real[jb]-CD.real[ja])*100;d10=(CD.y10[jb]-CD.y10[ja])*100;dd=[CD.d[ja],CD.d[jb]];}
 function lagged(k){var a=lagIdx(k,ia),b=lagIdx(k,ib);if(a===null||b===null||a>=b)return null;return[CD[k][a],CD[k][b],[CD.d[a],CD.d[b]]];}
 var t=lagged('tp'),o=lagged('oil'),a3=val('y3m',ia),b3=val('y3m',ib);
 var result={start:da,end:db,ia:ia,ib:ib,tenors:ten,spreads:sp,drivers:{be:be,real:real,d10:d10,dates:dd,
  tp:t?(t[1]-t[0])*100:null,tp_dates:t?t[2]:[null,null],oil:(o&&o[0]&&o[1])?(o[1]/o[0]-1)*100:null,
  y3m:(a3===null||b3===null)?null:(b3-a3)*100}};
 var v=view(result);result.text=[v.headline,v.panels[0].verdict,v.panels[1].verdict];return result;}
function headline(S){var x=S['30-2'],a=S['10-2'],b=S['30-10'];if(!x||!a||!b)return'資料不足，暫不判定曲線方向。';
 var seg='10−2 '+sgn(a.d,'')+'、30−10 '+sgn(b.d,'');
 if(Math.abs(r6(x.d))<2){if(Math.abs(r6(a.d))>=2&&Math.abs(r6(b.d))>=2&&a.d*b.d<0)return'30−2 大致持平（'+sgn(x.d)+'）：'+seg+'，兩段互相抵銷。';
  return'曲線大致持平：30−2 '+sgn(x.d)+'；'+seg+'。';}
 return'曲線'+x.zh+(x.lead?'（'+x.lead+'）':'')+'：30−2 '+(x.d>0?'擴大':'收窄')+' '+num(Math.abs(x.d))+'bp；'+seg+'。';}
function view(r){
 var T={},S={};r.tenors.forEach(function(t){T[t.k]=t;});r.spreads.forEach(function(s){S[s.key]=s;});var D=r.drivers,panels=[];
 var be=D.be,real=D.real,dy=D.d10,has=be!==null&&real!==null&&dy!==null,aligned=has&&Math.abs(dy-be-real)<=2;
 var verdict=aligned&&Math.max(Math.abs(dy),Math.abs(be),Math.abs(real))<0.5?'10 年期與拆解指標大致持平。':aligned&&Math.abs(dy)<0.5?'損益兩平與實質利率的變動大致抵銷，10 年期接近持平。':aligned?'10 年期主要由'+(Math.abs(be)>Math.abs(real)?'損益兩平':'實質利率')+'變動帶動。':!has?'所選期間的拆解資料不足，暫不判定主要原因。':'參考指標與 10 年期變動尚未吻合，暫不判定主要原因。';
 function metric(label,v,u,note){return{label:label,value:v===null?'—':sgn(v,u===undefined?'bp':u),note:note||'所選期間變動'};}
 var dd=D.dates||[null,null],dn=(dd[0]&&dd[1])?'拆解資料 '+md2(dd[0])+' → '+md2(dd[1]):'拆解資料不足',td=D.tp_dates||[null,null];
 var lm=[metric('10 年期',dy,'bp',dn),metric('損益兩平',be,'bp',dn),metric('實質利率',real,'bp',dn),
  metric('期限溢酬（參考）',D.tp,'bp',D.tp!==null?'資料日 '+md2(td[0])+' → '+md2(td[1]):'所選期間尚無新資料（約晚一週公布）')];
 if(D.oil!==null)lm.push(metric('油價（參考）',D.oil,'%'));
 panels.push({title:'10 年期為什麼變',verdict:verdict,metrics:lm,note:'實質利率比殖利率晚一天公布，拆解改用兩端最近都有資料的日子；期限溢酬僅作參考，不加到損益兩平與實質利率之上。'});
 function shortEndVerdict(dy2,y3m){if(dy2===null||y3m===null)return '資料不足，暫不判定短端定價方向。';var p=dy2-y3m;if(Math.abs(p)<=5)return '2 年期與 3 個月期同步變動，短端定價方向大致未變。';if(p<0){if(y3m>5&&dy2>-5)return '3 個月期上升、2 年期沒跟上：近期升息的定價增加，但市場不認為利率會一路走高。';return '2 年期下跌多於 3 個月期：未來兩年的利率定價下修。';}if(y3m< -5&&dy2<5)return '3 個月期下跌、2 年期沒跟著降：近期降息的定價增加，但之後的利率定價沒有一起下修。';return '2 年期上升多於 3 個月期：未來兩年的利率定價上修。';}
 var dy2=T.y2.d,y3m=D.y3m,path=dy2===null||y3m===null?null:dy2-y3m;
 verdict=shortEndVerdict(dy2,y3m);
 panels.push({title:'短端定價怎麼變',verdict:verdict,metrics:[metric('2 年期',dy2),metric('3 個月期',y3m),metric('2 年 − 3 個月利差',path)],note:'這是公債短端的相對變化；年底政策利率方向另看下方期貨定價。'});
 return{headline:headline(S),panels:panels};}
function startFor(k,end){if(k==='ytd')return(Y-1)+'-12-31';var n={'1w':7,'1m':30,'3m':91}[k];
 var t=new Date(end+'T00:00:00Z');t.setUTCDate(t.getUTCDate()-n);return t.toISOString().slice(0,10);}
return{analysis:analysis,view:view,startFor:startFor,num:num,sgn:sgn,RG:RG,idx:idx,md2:md2};}
"""

_CW_JS = _CW_CORE_JS + r"""
(function(){
var root=document.querySelector('.cw');if(!root)return;
var CD=JSON.parse(document.getElementById('cw-data').textContent);
var C=cwCore(CD),analysis=C.analysis,startFor=C.startFor,num=C.num,sgn=C.sgn,RG=C.RG,cur=null,mode='ten';
function safe(v){return String(v).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function cls(v){return v===null||Math.abs(v)<0.5?'flat':v>0?'up':'dn';}
function explain(r){var v=C.view(r);
 v.panels.forEach(function(p,i){var panel=root.querySelector('[data-panel="'+(i+1)+'"]');if(!panel)return;
 panel.querySelector('.cw-fold-reading').textContent=p.verdict;
 panel.querySelector('.cw-panel-content').innerHTML='<dl class="cw-metrics">'+p.metrics.map(function(m){return '<div><dt>'+safe(m.label)+'</dt><dd><b>'+safe(m.value)+'</b><small>'+safe(m.note)+'</small></dd></div>';}).join('')+'</dl><small class="cw-panel-note">'+safe(p.note)+'</small>';});}
function bar(v,sc){if(v===null||!sc)return'<i class="cwm-bar"></i>';var w=Math.min(50,Math.abs(v)/sc*50);return'<i class="cwm-bar"><b class="'+(v>0?'r':'l')+' '+cls(v)+'" style="width:'+w.toFixed(1)+'%"></b></i>';}
function matrix(r,label){root.querySelectorAll('.cwm-when').forEach(function(e){e.textContent=C.md2(r.start)+' → '+C.md2(r.end);});
 var h=root.querySelector('.cwm-selh');if(h&&label)h.firstChild.nodeValue=label;
 var sp={};r.spreads.forEach(function(x){sp[x.key]=x;});
 var st=Math.max.apply(null,[2].concat(r.tenors.map(function(t){return Math.abs(t.d||0);}))),ss=Math.max.apply(null,[2].concat(r.spreads.map(function(x){return Math.abs(x.d||0);})));
 r.tenors.forEach(function(t){var e=root.querySelector('td[data-m="'+t.k+'"]');if(e)e.innerHTML='<span class="'+cls(t.d)+'">'+(t.d===null?'—':safe(sgn(t.d,'')))+'</span>'+bar(t.d,st);});
 ['10-2','30-10','30-2'].forEach(function(k){var e=root.querySelector('td[data-m="'+k+'"]');if(!e)return;var x=sp[k];
  if(!x){e.innerHTML='<span class="flat">—</span>'+bar(null,ss);return;}
  e.innerHTML='<span class="'+cls(x.d)+'">'+safe(sgn(x.d,''))+'</span>'+bar(x.d,ss)+(x.code!=='na'?'<small class="le3-rg '+(RG[x.code]||'fl')+'">'+safe(x.zh)+'</small>':'');});}
var DEF={ten:[['2Y',function(j){return CD.y2[j];},'var(--y2)',1],['10Y',function(j){return CD.y10[j];},'var(--y10)',1],['30Y',function(j){return CD.y30[j];},'var(--y30)',1]],
 sp:[['10−2',function(j){return CD.y10[j]===null||CD.y2[j]===null?null:CD.y10[j]-CD.y2[j];},'var(--line-1)',1],
     ['30−10',function(j){return CD.y30[j]===null||CD.y10[j]===null?null:CD.y30[j]-CD.y10[j];},'var(--line-2)',1],
     ['30−2',function(j){return CD.y30[j]===null||CD.y2[j]===null?null:CD.y30[j]-CD.y2[j];},'var(--brand-ink)',2]]};
function nice(span){var c=[1,2,5,10,20,25,50,100];for(var i=0;i<c.length;i++){if(span/c[i]<=5)return c[i];}return 200;}
var EV=CD.ev||[];
function cum(r){var box=root.querySelector('.cwc-plot');if(!box)return;var ia=r.ia,ib=r.ib,defs=DEF[mode],S=[];
 defs.forEach(function(d){var b0=d[1](ia),pts=[];for(var j=ia;j<=ib;j++){var v=d[1](j);pts.push(v===null||b0===null?null:(v-b0)*100);}S.push({n:d[0],c:d[2],w:d[3],p:pts});});
 var all=[0];S.forEach(function(s){s.p.forEach(function(v){if(v!==null)all.push(v);});});
 var lo=Math.min.apply(null,all),hi=Math.max.apply(null,all),st=nice(Math.max(hi-lo,4));lo=Math.floor(lo/st)*st;hi=Math.ceil(hi/st)*st;if(hi===lo)hi=lo+st;
 var W=Math.max(320,Math.round(box.clientWidth||640)),H=W<560?190:220,L=W<560?34:42,R=W<560?62:76,T=10,B=24,n=Math.max(1,ib-ia);function X(i){return L+(W-L-R)*i/n;}function Yv(v){return T+(H-T-B)*(hi-v)/(hi-lo);}
 var g='';for(var t=lo;t<=hi+1e-9;t+=st){g+='<line x1="'+L+'" x2="'+(W-R)+'" y1="'+Yv(t)+'" y2="'+Yv(t)+'" class="'+(t===0?'cwc-zero':'cwc-grid')+'"/><text x="'+(L-6)+'" y="'+(Yv(t)+4)+'" class="cwc-ax" text-anchor="end">'+(t>0?'+':'')+String(t).replace('-','−')+'</text>';}
 [0,Math.round(n/2),n].forEach(function(i,k){g+='<text x="'+X(i)+'" y="'+(H-6)+'" class="cwc-ax" text-anchor="'+(k===0?'start':k===2?'end':'middle')+'">'+C.md2(CD.d[ia+i])+'</text>';});
 var evs=[];EV.forEach(function(e){for(var j=ia;j<=ib;j++){if(CD.d[j]===e[0]){evs.push([j-ia,e[1]]);break;}}});
 evs.forEach(function(e){g+='<line class="cwc-ev" x1="'+X(e[0])+'" x2="'+X(e[0])+'" y1="'+T+'" y2="'+(H-B)+'"><title>'+safe(C.md2(CD.d[ia+e[0]])+' '+e[1])+'</title></line>';});
 var lab=[];S.forEach(function(s){var d='',pen=false;s.p.forEach(function(v,i){if(v===null){pen=false;return;}d+=(pen?'L':'M')+X(i).toFixed(1)+' '+Yv(v).toFixed(1);pen=true;});
  g+='<path d="'+d+'" fill="none" stroke="'+s.c+'" stroke-width="'+s.w+'" stroke-linejoin="round" stroke-linecap="round"/>';
  var lv=null;for(var i=s.p.length-1;i>=0;i--){if(s.p[i]!==null){lv=s.p[i];break;}}if(lv!==null)lab.push({y:Yv(lv),t:s.n+' '+sgn(lv,''),c:s.c});});
 lab.sort(function(a,b){return a.y-b.y;});for(var i=1;i<lab.length;i++){if(lab[i].y-lab[i-1].y<13)lab[i].y=lab[i-1].y+13;}
 lab.forEach(function(l){g+='<text x="'+(W-R+6)+'" y="'+(l.y+4)+'" class="cwc-lab" fill="'+l.c+'">'+safe(l.t)+'</text>';});
 g+='<line class="cwc-cross" x1="0" x2="0" y1="'+T+'" y2="'+(H-B)+'" visibility="hidden"/><rect class="cwc-hit" x="'+L+'" y="'+T+'" width="'+(W-L-R)+'" height="'+(H-T-B)+'" fill="transparent"/>';
 box.innerHTML='<svg viewBox="0 0 '+W+' '+H+'" role="img" aria-label="所選期間起的累積變動（bp）">'+g+'</svg>';
 var svg=box.querySelector('svg'),cross=svg.querySelector('.cwc-cross'),out=root.querySelector('.cwc-read');
 function at(i){i=Math.max(0,Math.min(n,i));cross.setAttribute('x1',X(i));cross.setAttribute('x2',X(i));cross.setAttribute('visibility','visible');
  var en=evs.filter(function(e){return e[0]===i;}).map(function(e){return e[1];});
  out.innerHTML='<b>'+C.md2(CD.d[ia+i])+'</b>'+(en.length?'<em class="cwc-evn">'+safe(en.join('、'))+'</em>':'')+'　'+S.map(function(s){var v=s.p[i];return '<span style="color:'+s.c+'">'+safe(s.n)+' '+(v===null?'—':safe(sgn(v,'')))+'</span>';}).join('　')+'　<small>bp，相對 '+C.md2(CD.d[ia])+'</small>';}
 function pos(e){var bb=svg.getBoundingClientRect();return Math.round(((e.clientX-bb.left)/bb.width*W-L)/(W-L-R)*n);}
 svg.addEventListener('pointermove',function(e){at(pos(e));});svg.addEventListener('pointerdown',function(e){at(pos(e));});
 at(n);}
function mk(s){return parseInt(s.slice(0,4),10)*12+parseInt(s.slice(5,7),10)-1+(parseInt(s.slice(8,10),10)-1)/31;}
function bands(a,b){root.querySelectorAll('.cl-plot[data-x0]').forEach(function(p){var x0=+p.dataset.x0,x1=+p.dataset.x1,r=(x1-x0)||1;
 var l=Math.max(0,(mk(a)-x0)/r*100),R=Math.min(100,(mk(b)-x0)/r*100);var e=p.querySelector('.cl-band');
 if(!e){e=document.createElement('span');e.className='cl-band';p.insertBefore(e,p.firstChild);}e.style.left=l+'%';e.style.width=Math.max(0.6,R-l)+'%';});}
var LABEL={'1w':'1 週','1m':'1 個月','3m':'3 個月','ytd':'年初至今','custom':'自訂期間'},curk='1m';
function show(r){cur=r;explain(r);matrix(r,LABEL[curk]);cum(r);bands(r.start,r.end);}
root.querySelectorAll('.cwm-tog .cw-btn').forEach(function(b){b.addEventListener('click',function(){var m=root.querySelector('.cwm');m.dataset.v=b.dataset.v;root.querySelectorAll('.cwm-tog .cw-btn').forEach(function(x){x.classList.toggle('on',x===b);x.setAttribute('aria-pressed',String(x===b));});});});
var _rw=0;window.addEventListener('resize',function(){var w=(root.querySelector('.cwc-plot')||{}).clientWidth||0;if(cur&&Math.abs(w-_rw)>30){_rw=w;cum(cur);}});
root.querySelectorAll('.cwc-mode').forEach(function(b){b.addEventListener('click',function(){mode=b.dataset.m;root.querySelectorAll('.cwc-mode').forEach(function(x){x.classList.toggle('on',x===b);x.setAttribute('aria-pressed',String(x===b));});if(cur)cum(cur);});});
var last=CD.d[CD.d.length-1],fa=root.querySelector('.cw-from'),fb=root.querySelector('.cw-to'),cu=root.querySelector('.cw-cust');
function pick(k){curk=k;root.querySelectorAll('.cw-btn[data-w]').forEach(function(b){b.classList.toggle('on',b.dataset.w===k);});
 if(k==='custom'){cu.hidden=false;if(!fa.value){fa.value=startFor('1m',last);fb.value=last;}show(analysis(fa.value,fb.value));return;}
 cu.hidden=true;show(analysis(startFor(k,last),last));}
root.querySelectorAll('.cw-btn[data-w]').forEach(function(b){b.addEventListener('click',function(){pick(b.dataset.w);});});
[fa,fb].forEach(function(e){e.addEventListener('change',function(){if(fa.value&&fb.value)show(analysis(fa.value<fb.value?fa.value:fb.value,fa.value<fb.value?fb.value:fa.value));});});
pick(root.dataset.w||'1m');
})();
"""

CW_DEFAULT = "1m"      # 預設期間：最上方週報已是「最近一週」，下面預設看 1 個月才不重複


def curve(d: dict) -> str:
    L = d.get("le") or {}
    cd = L.get("cw") or {}
    if not cd.get("d"):
        return '<div class="empty">資料不足</div>'
    import json as _json
    year = L.get("cw_year") or int(cd["d"][-1][:4])
    last = cd["d"][-1]
    r0 = le.window_analysis(cd, le.cw_start(cd, CW_DEFAULT, last, year), last)
    from .curve_weekly import weekly_chart
    weekly = weekly_chart(cd)
    brief = L.get("brief")
    rows = L.get("spreads") or []
    fwd = L.get("forwards") or []
    rf = L.get("refunding") or {}
    fn = L.get("fomc_next") or ""
    st = le.curve_story(rows, L.get("curve_drivers") or {}, fwd, fomc_next=_md(fn) if fn else "",
                        refunding_next=_md(str(rf.get("next") or "")) if rf.get("next") else "")
    btns = "".join(f'<button type="button" class="cw-btn{" on" if k == CW_DEFAULT else ""}" data-w="{k}">{zh}</button>'
                   for k, zh, _ in le.CW_WINDOWS) + '<button type="button" class="cw-btn" data-w="custom">自訂</button>'
    win_label = {k: zh for k, zh, _ in le.CW_WINDOWS}[CW_DEFAULT]
    first = cd["d"][0] if cd["d"][0] >= f"{year}-01-01" else f"{year - 1}-12-31"
    events = [list(e) for e in (L.get("cw_events") or []) if e and str(e[0]) >= cd["d"][0]]
    data = _json.dumps({**cd, "year": year, "ev": events}, ensure_ascii=False, separators=(",", ":"))
    smalls = "".join(f'<div class="le3-sm"><div class="le3-smh"><b>{esc(x["key"].replace("-", "−"))}</b>'
                     f'<span>{x["value"]:.0f} bp</span></div>{x.get("chart", "")}</div>' for x in rows)
    future = le.future_view(fwd, L.get("match") or d.get("mvd"))
    frows = "".join(
        f'<div class="le3-fr"><span>{esc(x["label"])}</span><b>{x["fwd"]:.2f}%</b>'
        f'<span class="le3-fg {"up" if x["gap_bp"] > 0 else "dn"}">比目前 {esc(x["spot_zh"])} {_sbp(x["gap_bp"])}bp</span>'
        f'<span class="le3-fw">近一月 {_sbp(x.get("mom_bp"))}bp</span>'
        f'<small class="fwd-date">官方資料日 {esc(x.get("date") or "—")}'
        f'{("；月比較 " + esc(x["mom_date"])) if x.get("mom_date") else "；月比較資料不足"}</small>'
        f'<p class="fwd-reading">{("遠期定價高於目前同天期利率。" if x["gap_bp"] > 5 else "遠期定價低於目前同天期利率。" if x["gap_bp"] < -5 else "遠期與目前同天期利率接近。")}</p></div>' for x in fwd)
    policy = future["policy"]
    match_html = '<p class="cw-panel-note">期貨資料不足，暫不判定年底政策利率方向。</p>'
    if policy:
        match_html = (f'<section class="future-policy"><h3>{esc(policy["title"])}</h3><dl class="cw-metrics">'
                      f'<div><dt>現行利率中點</dt><dd><b>{policy["now"]}</b></dd></div>'
                      f'<div><dt>{esc(policy["year"])} 年底期貨隱含</dt><dd><b>{policy["end"]}</b></dd></div>'
                      f'<div><dt>年底相對現在</dt><dd><b>{policy["change"]}</b></dd></div></dl>'
                      f'<p>{esc(policy["text"])}</p></section>')
    mt = L.get("match")
    dg = L.get("dots_gap")
    compare_html = ""
    if dg:
        _tag = {"good": "正常", "warning": "留意", "critical": "警戒"}[dg["status"]]
        _rows = "".join(
            f'<tr><td data-label="年底">{esc(r["year"])} 年底{"（用 " + esc(r["month"].replace("-", "/")) + " 合約，含 12 月會議前的天數）" if r["partial"] else ""}</td>'
            f'<td data-label="點陣圖">{r["dots"]:.2f}%</td><td data-label="期貨">{r["market"]:.2f}%</td><td data-label="差距"><b>{_sbp(r["gap_bp"])}bp</b></td></tr>'
            for r in dg["rows"])
        _hist = "".join(f'<tr><td data-label="時點">{esc(a)}</td><td data-label="當時">{esc(b)}</td><td data-label="差距">{esc(c)}</td><td data-label="結果">{esc(e)}</td></tr>'
                        for a, b, c, e in dg["history"])
        compare_html = (
            f'<section class="future-dots"><h3>期貨定價 vs 點陣圖：{esc(dg["stance"])}</h3>'
            f'<p><span class="st {dg["status"]}">{_tag}</span> 差距 <b>{_sbp(dg["gap_bp"])}bp</b>'
            f'（{esc(dg["main"]["year"])} 年底）——{esc(dg["why"])}。'
            f'{"市場與 Fed 的路徑大致一致，之後不太需要誰去修正。" if dg["status"] == "good" else "差距越大，之後不是期貨往點陣圖靠（短端利率跳動），就是 Fed 在下一份點陣圖往市場靠。"}</p>'
            f'<table class="lq-tbl"><thead><tr><th>年底</th><th>點陣圖中位數</th><th>期貨隱含</th><th>差距</th></tr></thead>'
            f'<tbody>{_rows}</tbody></table>'
            f'<details class="f-more"><summary>判定標準與歷史量級</summary><div class="f-detail">'
            f'<p>{esc(dg["rule"])}Lead the Curve＝期貨定價的動作比點陣圖大（同方向走得更遠）；'
            f'Behind the Curve＝動作比點陣圖小或方向相反。</p>'
            f'<table class="lq-tbl"><thead><tr><th>時點</th><th>當時</th><th>差距</th><th>結果</th></tr></thead>'
            f'<tbody>{_hist}</tbody></table>'
            f'<p class="cw-panel-note">歷史量級為當時 SEP 與期貨定價的約略值；公開免費資料沒有逐日的期貨 vs 點陣圖序列，'
            f'這裡只拿幾次顯著分歧當刻度。</p></div></details></section>')
    elif mt and mt.get("dot_median") is not None:
        compare_html = (f'<details class="f-more"><summary>與 Fed 點陣圖比較</summary>'
                       f'<p>期貨隱含年底 {mt["market_end"]:.2f}%；點陣圖中位數 {mt["dot_median"]:.2f}%。'
                       f'兩者差距 {_sbp((mt["market_end"]-mt["dot_median"])*100)}bp。</p></details>')
    outl = "".join(f'<li class="{"hot" if o["hot"] else ""}"><b>{esc(o["tag"])}</b>{esc(o["text"])}</li>'
                   for o in st["outlook"])
    modes = "".join(f'<button type="button" class="cw-btn cwc-mode{" on" if m == "ten" else ""}" data-m="{m}" '
                    f'aria-pressed="{"true" if m == "ten" else "false"}">{zh}</button>'
                    for m, zh in (("ten", "2Y／10Y／30Y"), ("sp", "三條利差")))
    return f"""
    {_cw_brief(brief, events, L.get("brief_data"))}
    <div class="cw" data-w="{CW_DEFAULT}">
      <div class="cw-ctl" role="group" aria-label="比較期間">{btns}</div>
      <div class="cw-cust" hidden><label>從 <input type="date" class="cw-from" min="{first}" max="{last}"></label>
        <label>到 <input type="date" class="cw-to" min="{first}" max="{last}"></label></div>
      {_cw_matrix(brief, r0, win_label)}
      <div class="tabs cw-tabs">
        <input type="radio" name="cw-tab" id="cw-t1" checked><label for="cw-t1">累積變動</label>
        <input type="radio" name="cw-tab" id="cw-t2"><label for="cw-t2">殖利率水準</label>
        <input type="radio" name="cw-tab" id="cw-t3"><label for="cw-t3">利差水準</label>
        <div class="tabp p1"><div class="cwc"><div class="cw-ctl cwc-modes" role="group" aria-label="累積變動">{modes}</div>
          <div class="cwc-plot"><noscript>需要 JavaScript 才能顯示累積變動圖。</noscript></div>
          <p class="cwc-read" aria-live="polite"></p>
          <details class="cw-note"><summary>圖表說明</summary><p class="cwm-note">所選期間第一天為 0，往後每天相對第一天的變動（bp）。線越往上＝殖利率上升／利差擴大。灰色虛線＝事件日（FOMC、CPI、非農、PCE、公債再融資公告），滑過或點選圖表可看名稱。</p></details></div></div>
        <div class="tabp p2">{L.get("yield_chart", "")}</div>
        <div class="tabp p3"><div class="le3-sms">{smalls}</div><details class="cw-note"><summary>圖表說明</summary><p class="cwm-note">三張小圖各自用貼近資料的刻度，才看得出變化；彼此高度不能直接比較。</p></details></div>
      </div>
      {weekly}
      {_cw_folds(r0)}
      <script type="application/json" id="cw-data">{data}</script>
      <script>{_CW_JS}</script>
    </div>
    <details class="f-more future-section cw-fold"><summary><span class="cw-fold-number">03</span><span class="cw-fold-title"><b>市場怎麼看未來利率</b><span class="cw-fold-reading">{esc(policy["text"] if policy else future["headline"])}</span></span></summary>
      {match_html}{compare_html if dg else ""}
      <section class="future-bonds"><h3>公債遠期定價方向</h3>
        <p class="future-headline">{esc(future["headline"])}</p><p>{esc(future["recent"])}</p>
        <div class="le3-ft" style="margin-top:6px">{frows or '<p>遠期資料不足</p>'}</div>
        <p class="cw-panel-note">各列代表不同的未來區間與期限，不是連續的升降息路徑；遠期值含期限溢酬，不能直接當作 Fed 的未來政策利率。</p>
      </section>{"" if dg else compare_html}</details>
    <details class="f-more"><summary>曲線形狀：現在、1 週前、1 個月前、年初</summary>{L.get('curve_chart', '')}</details>
    <details class="f-more"><summary>接下來看什麼</summary><ul class="le3-ol">{outl}</ul></details>
    <details class="f-more"><summary>方法與限制</summary>
      <div class="f-detail le3-how">
        <p><b>30−2 週報</b>：最新官方收盤比 5 個交易日前（滾動一週），每天都是最新的一週；下方「每週變化」長條圖則固定週五比週五。分段：30−2＝10−2＋30−10，貢獻同方向且較大的那一段標為主要來源。</p>
        <p><b>型態</b>：利差擴大＝變陡、收窄＝變平；看兩端誰動得多決定由哪一端帶動，殖利率上升為熊、下降為牛；兩端反向為扭轉。利差變動 2bp 以內視為持平。</p>
        <p><b>遠期（1 年後、5 年後）</b>：用同一天的官方曲線推算。1 年後的 2Y＝1y2y（1Y、3Y）；10Y、30Y 因沒有 11 年、31 年期，以 1y9y、1y29y 近似。5 年後的 2Y＝5y2y（5Y、7Y）；10Y＝5y10y（15Y 由 10Y、20Y 內插）；30Y 以 5y25y 近似。官方殖利率是平價收益率，結果為近似值；遠期含期限溢酬，是市場已定價的路徑、不是預測。</p>
        <p><b>原因</b>：用損益兩平（FRED T10YIE，即 DGS10 − DFII10）與 TIPS 實質利率（DFII10），兩者相加等於 10 年期；實質利率晚一天公布，拆解用兩端最近都有資料的日子。期限溢酬（NY Fed ACM，約晚一個交易日）跟實質利率、損益兩平都有重疊，當旁證看；起訖退到同一天時顯示「—」。</p>
        <p><b>市場定價的未來</b>：遠期差距及月變動在 ±5bp 內視為接近；年底期貨與現行利率差距在 ±12.5bp 內視為大致持平。</p>
        <p><b>資料口徑</b>：2Y、10Y、30Y 與利差使用美國財政部官方日殖利率，部分資料由 FRED 提供；各天期比較採同一天資料。財政部按約美東 15:30 的指示性買方報價估算固定期限殖利率，與 Bloomberg USGG 指數的 PX_LAST 口徑不同。</p>
        <p><b>自選期間</b>：可查看 {year} 年起的資料；遇假日採前一個有資料的日期，監控表欄位標題會標出實際使用的日期。</p>
        <p><b>事件標記</b>：FOMC 用全年會議日；非農、CPI、PCE 用官方發布行事曆（目前自 2026 年 8 月起）；公債再融資公告用財政部公布的日期。只標有出處的日期，不用慣例推估。週報的「主要變化集中在…」挑這一週最大的單日變動（天期或利差，4bp 以上才寫），同一天有上述事件就一併點出。</p>
        <p><b>年內位置</b>：今年 1/1 起各標的的最低與最高，圓點是現在的位置。</p>
      </div>
    </details>"""


# ---------------------------------------------------------------------------
# 全球長端
# ---------------------------------------------------------------------------
def global_(d: dict) -> str:
    g = (d.get("le") or {}).get("global") or {}
    rows = g.get("rows") or []
    if not rows:
        return '<div class="empty">資料不足</div>'
    def _card(r):
        if r.get("daily"):
            chg = "".join(f'<em><i>{k}</i>{_bp(r.get(f))}</em>' for k, f in (("DTD", "dtd"), ("MTD", "mtd"), ("YTD", "ytd")))
            when = f'{esc(_md(r["date"]))}'
        else:
            chg = '<em><i>月均</i>無日資料</em>'
            when = esc(r["date"][:7].replace("-", "/")) + " 月均"
        return (f'<div class="le-g"><span>{esc(r["name"])}<small>{when}</small></span>'
                f'<b>{r["value"]:.2f}%</b>{chg}</div>')
    cards = "".join(_card(r) for r in rows)
    # 圖下說明（2026-10 改版）：來源一國一列（含最新資料日）、變化定義條列、時效另起一行
    _latest = max((x["date"] for x in rows if x.get("daily")), default="")
    lag = [r["name"] for r in rows if r.get("daily") and r["date"] < _latest]
    src_rows = "".join(
        f'<li><b>{esc(r["name"])}</b><span>{esc(r["src"])}</span>'
        f'<em class="{"late" if r["name"] in lag else ""}">{esc(_md(r["date"]) if r.get("daily") else r["date"][:7].replace("-", "/") + " 月均")}</em></li>'
        for r in rows)
    lag_note = ("、".join(lag) + "的最新資料日較早（左表黃字）" + ("；英國央行約晚 2～3 個營業日公布" if "英國" in lag else "") + "。") if lag else ""
    return f"""
    <p class="hint">期限溢酬如果是全球一起漲，原因多半是全球的財政與供給；只有美國在漲，才是美國自己的問題。</p>
    <div class="le-gs">{cards}</div>
    <div class="viz-block"><div class="viz-h">10 年期公債殖利率（日資料，近一年）</div>{g.get('chart', '')}</div>
    <div class="gsrc">
      <div class="gsrc-col">
        <div class="gsrc-h">資料來源（10 年期公債，日資料）</div>
        <ul class="gsrc-list">{src_rows}</ul>
      </div>
      <div class="gsrc-col">
        <div class="gsrc-h">變化怎麼算（bp）</div>
        <dl class="gsrc-def"><div><dt>DTD</dt><dd>比前一個交易日</dd></div>
          <div><dt>MTD</dt><dd>比上月最後一個交易日</dd></div>
          <div><dt>YTD</dt><dd>比去年最後一個交易日</dd></div></dl>
        <p class="gsrc-note">各國休市日與公布時間不同，各卡右上是該國最新一筆的日期。{esc(lag_note)}</p>
      </div>
    </div>"""


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
                 + (f'<p>{esc(rf["guidance_zh"])}</p>' if rf.get("guidance_zh") else
                    ('<p class="hint">本季聲明為自動擷取，句型與過去不同，請以上方原文為準。</p>' if rf.get("auto") else ""))
                 + (f'<p class="hint">{esc(rf["buybacks_zh"])}'
                    + (f'{esc((rf.get("bb_note") or {}).get("text") or "")}' if rf.get("bb_note") else "")
                    + '</p>' if rf.get("buybacks_zh") else "")
                 + (f'<a class="le-src-link" href="{esc(rf["url"])}" target="_blank" rel="noopener">財政部原文 →</a>' if rf.get("url") else "")
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
        f'<span>{"暫定排程" if a.get("tentative") else _amt(a)}</span></div>'
        for a in up[:14]) or '<div class="hint">目前沒有已公告的 coupon 拍賣</div>'
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
    <div class="src">拍賣規模與已公告拍賣：財政部 Fiscal Data（auctions_query）＋暫定拍賣排程　·　SOMA：紐約聯儲　·　流通在外明細：財政部 MSPD（每月）。
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
    <div class="src">財政部 Fiscal Data 拍賣結果（auctions_query）。比例的分母是競標得標量。</div>"""


# ---------------------------------------------------------------------------
# 財政部買回（Buybacks）
# ---------------------------------------------------------------------------
def _yi_b(v, sign=False) -> str:
    """十億美元 → 億美元。"""
    if v is None:
        return "—"
    nd = 0 if abs(v * 10 - round(v * 10)) < 0.05 else 1      # TIPS 7.5 億這種要留小數
    return f"{v * 10:+,.{nd}f}" if sign else f"{v * 10:,.{nd}f}"


def _rx(r: dict) -> str:
    vals = [r.get(k) for k in ("10Y", "20Y", "30Y")]
    if all(v is None for v in vals):
        return '<span class="muted">—</span>'
    return "／".join(f'<b class="{"up" if (v or 0) > 0 else "dn" if (v or 0) < 0 else ""}">'
                     f'{"—" if v is None else f"{v:+.1f}"}</b>' for v in vals)


def buyback_summary(d: dict) -> str:
    b = (d.get("le") or {}).get("buybacks") or {}
    x = b.get("latest")
    if not x:
        return "財政部買回"
    return (f'{_md(x["date"])} {x["bucket_zh"]}：買回 {_yi_b(x["accepted"])} 億／上限 {_yi_b(x["max"])} 億')


def buybacks(d: dict) -> str:
    b = (d.get("le") or {}).get("buybacks") or {}
    rows = b.get("rows") or []
    if not rows:
        return '<div class="empty">買回資料本次取得失敗</div>'
    x = b["latest"]
    q = b.get("quarter") or {}
    stats = (
        f'<div class="stat-row">'
        f'<div class="stat"><div class="s-label">最新一場　{esc(_md(x["date"]))} {esc(x["bucket_zh"])}</div>'
        f'<div class="s-value">{_yi_b(x["accepted"])}<small> 億美元</small></div>'
        f'<div class="s-note">上限 {_yi_b(x["max"])} 億　·　{esc(x["type_zh"])}</div></div>'
        f'<div class="stat"><div class="s-label">投標 ÷ 上限</div>'
        f'<div class="s-value">{(x["cover"] or 0):.1f}<small> 倍</small></div>'
        f'<div class="s-note">投標 {_yi_b(x["offered"])} 億</div></div>'
        f'<div class="stat"><div class="s-label">本季累計（{esc(_md(b.get("quarter_from", "")))} 起）</div>'
        f'<div class="s-value">{_yi_b(sum(q.values()))}<small> 億美元</small></div>'
        f'<div class="s-note">' + "　".join(f'{esc(k)} {_yi_b(v)} 億' for k, v in q.items()) + '</div></div>'
        f'</div>')
    caps = "".join(f'<span class="bb-cap"><b>{esc(c["bucket_zh"])}'
                   f'{"" if c["type_zh"] == "流動性支援" else "（" + c["type_zh"] + "）"}</b>{_yi_b(c["max"])} 億</span>'
                   for c in b.get("caps") or [])
    _bbn = ((d.get("le") or {}).get("refunding") or {}).get("bb_note") or {}
    how = f"""<dl class="gloss">
      <dt>操作天期</dt><dd>流動性支援：名目 coupon 依剩餘年限分段輪流買回（1 個月–2 年、2–3、3–5、5–7、7–10、10–20、20–30 年）與 TIPS 兩段；
        現金管理：1 個月–2 年，集中在 4、6、9、12 月稅收日前後。</dd>
      <dt>每場上限</dt><dd><div class="bb-caps">{caps}</div>
        {esc(_bbn.get("text") or "")}</dd>
      <dt>執行方式</dt><dd>反向拍賣：操作前一個營業日 11:00（美東）初步公告上限與合格券，當日 11:00 最終公告；
        13:40–14:00 接受一級交易商報價（每 100 美元面額的價格），多重價格得標，截止後公布結果；T+1 交割，買回的券直接註銷。</dd>
      <dt>融資來源</dt><dd>財政部的現金與新發行公債（31 U.S.C. §3111）。QRA 原文：「buybacks are not expected to significantly
        affect privately-held net marketable borrowing as new issuance replaces securities that are bought back」——買回多少就多發多少，
        實務上由 T-Bills 補上，所以買回是把長天期舊券換成短天期 bill，不改變總借款。</dd>
    </dl>"""
    # 歷次結果只列近 90 天（約一季），更早的操作留在資料裡、不上頁面
    import datetime as _dt
    _cut = (_dt.date.today() - _dt.timedelta(days=90)).isoformat()
    recent = [r for r in rows if str(r.get("date") or "") >= _cut]
    trs = "".join(
        f'<tr><td class="bb-k" data-label="操作日"><b>{esc(_md(r["date"]))}</b> <span>{esc(r["bucket_zh"])}・{esc(r["type_zh"])}</span></td>'
        f'<td class="bb-hide-m" data-label="天期"><span class="bb-v">{esc(r["bucket_zh"])}</span></td><td class="bb-hide-m" data-label="類型"><span class="bb-v">{esc(r["type_zh"])}</span></td>'
        f'<td data-label="上限"><span class="bb-v">{_yi_b(r["max"])}</span></td><td data-label="實際買回"><span class="bb-v"><b>{_yi_b(r["accepted"])}</b></span></td>'
        f'<td data-label="投標"><span class="bb-v">{_yi_b(r["offered"])}</span></td>'
        f'<td class="bb-rx" data-label="公布後 1 小時"><span class="bb-v">{_rx(r["announce"])}</span></td>'
        f'<td class="bb-rx" data-label="結果後 1 小時"><span class="bb-v">{_rx(r["result"])}</span></td></tr>'
        for r in recent)
    table = (f'<div class="tscroll"><table class="bb-tb"><thead><tr><th>操作日</th><th>天期</th><th>類型</th>'
             f'<th>上限</th><th>實際買回</th><th>投標</th><th>上限公布後 1 小時<br><small>10／20／30 年，bp</small></th>'
             f'<th>結果公布後 1 小時<br><small>10／20／30 年，bp</small></th></tr></thead><tbody>{trs}</tbody></table></div>')
    up = b.get("upcoming") or []
    ups = "".join(
        f'<tr><td class="bb-k" data-label="操作日"><b>{esc(_md(u["date"]))}</b> <span>{esc(u["bucket_zh"])}</span></td>'
        f'<td data-label="上限公布"><span class="bb-v">{esc(_md(u["announce"]))}</span></td><td class="bb-hide-m" data-label="天期"><span class="bb-v">{esc(u["bucket_zh"])}</span></td>'
        f'<td data-label="類型"><span class="bb-v">{esc(u["type_zh"])}</span></td><td data-label="排程上限"><span class="bb-v">{_yi_b(u["max"])}'
        + (f'<small class="muted">（近期實際 {_yi_b(u["recent_max"])}）</small>' if u.get("recent_max") else "")
        + '</span></td></tr>' for u in up)
    up_html = (f'<div class="tscroll"><table class="bb-tb"><thead><tr><th>操作日</th><th>上限公布</th><th>天期</th>'
               f'<th>類型</th><th>排程上限</th></tr></thead><tbody>{ups}</tbody></table></div>'
               if ups else '<p class="hint">本季暫定排程已全部執行完畢，下一季排程隨再融資公布。</p>')
    return f"""
    <p class="hint">買回流動性較差的舊券、用新發行補上——長端供給的減法。</p>
    {stats}
    {how}
    <details data-m-collapse><summary>近 90 天買回結果與殖利率反應（{len(recent)} 場，億美元）</summary>
      {('<p class="bb-m-note">殖利率反應依序為 10／20／30 年，單位 bp；正值＝殖利率上升。</p>' + table) if recent else '<p class="hint">近 90 天沒有買回操作。</p>'}</details>
    <details data-m-collapse open><summary>未來排程（{esc(b.get("schedule_name") or "暫定買回排程")}）</summary>
      {up_html}</details>
    <details data-m-collapse><summary>殖利率反應怎麼量</summary>
      <p class="hint" style="margin-top:10px">上限公布：初步公告時間（操作前一個營業日 11:00 美東）前最後一根 5 分鐘 K 棒收盤 →
        公告後 60 分鐘那根的收盤。結果公布：操作截止 14:00 → 15:00，結果在截止後幾分鐘內公布，落在這個窗口裡。
        正值＝殖利率上升（價格下跌）。同一小時內也可能有其他消息（經濟數據、拍賣、Fed 官員談話），
        單一場的變化不能全部歸因於買回；要看的是同一類操作反覆出現的方向。</p>
    </details>
    <div class="src">財政部 Fiscal Data、TreasuryDirect 公告 XML、暫定買回排程；盤中殖利率：CNBC 5 分 K。</div>"""


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
    # 只比有年度計畫的公司：Oracle 不給年度指引、會計年度也不同，它的新季報不代表計畫過時
    _has = {r.get("name") for r in gd.get("rows") or []}
    ends = [c.get("period_end") for c in (getattr(hs, "companies", None) or [])
            if c.get("period_end") and (not _has or c.get("name") in _has)]
    if not asof or not ends:
        return ""
    late = max(ends)
    if late > asof:
        # 給讀者看的版本：不提設定檔（維護提醒寫在執行紀錄）
        log.warning("資本支出指引待更新：財報期末 %s、指引 %s（config/rates.yaml capex_guidance）", late, asof)
        return (f'<div class="warnbox" style="margin-top:12px"><b>計畫可能已過時</b>　'
                f'年度計畫是 {esc(_md(asof))} 的版本，財報已更新到 {esc(_md(late))}。</div>')
    return ""


# ---------------------------------------------------------------------------
# 指標檢核：依三股力量分組
# ---------------------------------------------------------------------------
GROUPS = [("tp", "期限溢酬：不確定性補償", ("term_premium", "curve_30_10", "interest_to_revenue", "r_minus_g")),
          ("real", "實質利率：政策預期", ("real_10y", "curve_10_2", "dots_gap")),
          ("infl", "損益兩平：通膨預期", ("breakeven_10y",)),
          ("demand", "需求", ("ig_spread",))]


# 每顆燈的「完整脈絡」：連回本頁對應的區塊（比照流動性頁）
LIGHT_ANCHOR = {"term_premium": "#decomp", "real_10y": "#decomp", "breakeven_10y": "#decomp",
                "curve_10_2": "#curve", "curve_30_10": "#curve", "dots_gap": "#curve",
                "interest_to_revenue": "#debt", "r_minus_g": "#debt", "ig_spread": "#demand"}


def lights_grouped(d: dict, card_fn) -> str:
    L = d.get("le") or {}
    c1 = (L.get("contrib") or {}).get("mtd")
    main = c1.get("main") if c1 else None
    by = {l.key: l for l in d.get("lights") or []}
    order = sorted(GROUPS, key=lambda g: 0 if g[0] == main else 1)
    out = []
    for key, name, keys in order:
        ls = [by[k] for k in keys if k in by]
        if not ls:
            continue
        badge = '<span class="le-badge">本月驅動</span>' if key == main else ""
        out.append(f'<div class="le-lg" data-k="{min(len(ls), 4)}" style="--k:{len(ls)}"><div class="sig-tier">{esc(name)}{badge}</div>'
                   f'<div class="le-lgc">{"".join(card_fn(l, LIGHT_ANCHOR.get(l.key, "")) for l in ls)}</div></div>')
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
            '<p class="hs3-note">柱子高過橫線＝現金不夠付資本支出，缺口靠發債。</p></div>')


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
            + f'{bar}</span><i class="hs3-br"></i>'
            f'<span class="hs3-v"><em>單季發債</em>{c["issued"] * 10:,.0f}</span>'
            f'<span class="hs3-v"><em>{esc(str(gd.get("year", "")))} 年計畫</em>{esc(g)}</span>'
            f'</summary><div class="hs3-body">{body}</div></details>')
    head = ('<div class="hs3-hd"><span>公司</span><span>本季資本支出</span><span>年增</span>'
            '<span>佔營運現金流</span><span>單季發債</span>'
            f'<span>{esc(str(gd.get("year", "")))} 年資本支出計畫</span></div>')
    return (f'<div class="hs3-t">{head}{"".join(rows)}</div>'
            '<p class="hs3-note">億美元・點一家看近 8 季・超過 100% 標紅</p>')
