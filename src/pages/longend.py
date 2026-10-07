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
    asof = (f'{d.get("as_of", "—")}（盤中）' if d.get("as_of_live")
            else f'{d.get("as_of", "—")}（{d.get("yield_source", "FRED")} 官方日殖利率）')

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
        txt, cls = (f"<b>趨勢</b>：{z[m1]}在 1、3、12 個月都是最大推力，"
                    f"這不是單月雜訊。"), "trend"
    elif m3 == m12:
        txt, cls = (f"<b>本月偏雜訊</b>：這個月主因是{z[m1]}，但 3 與 12 個月的主因都是"
                    f"{z[m3]}——趨勢仍是後者。"), "noise"
    elif m1 == m3:
        txt, cls = (f"<b>新趨勢成形中</b>：近 1、3 個月主因都是{z[m1]}，"
                    f"12 個月看則是{z[m12]}。"), "turn"
    else:
        txt, cls = (f"<b>方向未定</b>：1、3、12 個月的主因各不相同"
                    f"（{z[m1]}／{z[m3]}／{z[m12]}）。"), "mixed"
    chips = "".join(f'<span><em>{k} 個月</em>{z[mains[k]]}</span>' for k in (1, 3, 12))
    if cls == "trend":            # 三個窗都同一段：標籤列只是重複，不放
        chips = ""
    return (f'<div class="le3-tr {cls}"><p>{txt}</p>'
            + (f'<div class="le3-trc">{chips}</div>' if chips else "") + '</div>')


def decomp(d: dict) -> str:
    """
    長端利率的組成（2026-10 v3，使用者：點開太多層）：
    這一區只回答「本月的主因是趨勢還是雜訊」。首卡已經講了這個月是誰在推，
    這裡不再重複主因句；房貸拿掉；「Fed 跟上曲線」搬到殖利率曲線；
    市場口徑、教學與方法併成一個收合。
    """
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
    mr = L.get("market_ref") or {}
    ref = (f'<p><b>市場口徑</b>：TIPS 實質利率 {mr.get("real") or 0:.2f}%、損益兩平 {mr.get("be") or 0:.2f}%。'
           '兩者各自混了風險溢酬與流動性溢酬，加不出三股力量，只當參考。</p>') if mr.get("real") is not None else ""
    return f"""
    {_trend_line(L)}
    <div class="tabs le-tabs">{tabs}{panes}</div>
    <div class="viz-block"><div class="viz-h">三段的走勢（月均，近 24 個月）</div>
      {L.get('dec_lines', '')}</div>
    <details class="f-more"><summary>怎麼讀・方法與資料</summary>
      <div class="f-detail le3-how">
        <p><b>怎麼讀</b>：10 年期殖利率拆成三段相加——預期實質路徑（政策）、預期通膨、期限溢酬（財政與供給）。
        先看首卡的「本月主因」，再看這裡 1、3、12 個月是否同一段：一致才是趨勢。</p>
        <p><b>期限溢酬</b>：Kim-Wright 模型（FRED THREEFYTP10）。<b>預期通膨</b>：克里夫蘭聯儲 EXPINF10YR（月頻，已扣風險溢酬）。
        <b>預期實質路徑</b>：擬合殖利率 − 期限溢酬 − 預期通膨。<b>殘差</b>：實際 10 年期與模型擬合值的差，照實列出。</p>
        <p>預期通膨是月頻，三段一律用月均對齊，所以跟頁首的日資料變動不會完全一樣；兩個模型出自不同機構，相加是近似。</p>
        {ref}
      </div>
    </details>"""


# ---------------------------------------------------------------------------
# 殖利率曲線（2026-10 v2）
# ---------------------------------------------------------------------------
_RG_CLS = {"bear_steep": "bear", "bear_flat": "bear", "bull_steep": "bull", "bull_flat": "bull",
           "twist_steep": "tw", "twist_flat": "tw", "flat": "fl", "na": "fl"}


def _sbp(v) -> str:
    return "—" if v is None else f"{v:+.0f}".replace("-", "−")


def _cw_tenors(ten: list[dict], start: str, end: str) -> str:
    date_label = lambda d: f"{int(d[5:7])}/{int(d[8:10])}"
    out = [f'<table class="cw-compact" aria-label="所選期間利率變化">'
           f'<thead><tr><th scope="col">天期</th><th scope="col">{date_label(start)}</th>'
           f'<th scope="col">{date_label(end)}</th><th scope="col">變動</th></tr></thead><tbody>']
    for t in ten:
        fmt = lambda v: "—" if v is None else le._num(v, 2) + "%"
        delta = "—" if t["d"] is None else le._sgn(t["d"])
        cls = "up" if (t["d"] or 0) > 0 else "dn" if (t["d"] or 0) < 0 else "flat"
        out.append(f'<tr><th scope="row">{esc(t["zh"])}期</th><td>{fmt(t["a"])}</td>'
                   f'<td>{fmt(t["b"])}</td><td class="{cls}">{delta}</td></tr>')
    return "".join(out) + "</tbody></table>"


def _cw_explain(r: dict, weekly: str = "") -> str:
    view = le.window_view(r)
    out = [f'<p class="cw-headline">{esc(view["headline"])}</p><div class="cw-panels">']
    for i, panel in enumerate(view["panels"], 1):
        out.append(f'<details class="cw-panel cw-fold" data-panel="{i}"><summary>'
                   f'<span class="cw-fold-number">{i:02d}</span><span class="cw-fold-title">'
                   f'<b>{esc(panel["title"])}</b><span class="cw-fold-reading">{esc(panel["verdict"])}</span>'
                   f'</span></summary><div class="cw-panel-content"><dl class="cw-metrics">')
        for m in panel["metrics"]:
            out.append(f'<div><dt>{esc(m["label"])}</dt><dd><b>{esc(m["value"])}</b>'
                       f'<small>{esc(m["note"])}</small></dd></div>')
        out.append(f'</dl><small class="cw-panel-note">{esc(panel["note"])}</small></div>'
                   + (weekly if i == 1 else "") + '</details>')
    return "".join(out) + "</div>"


def _cw_spreads(sp: list[dict]) -> str:
    """利差表三列。markup 與 _CW_JS 的 spreads() 相同。"""
    return "".join(
        f'<div class="cw-sr"><span class="cw-sk">{x["key"]}</span>'
        f'<span class="cw-sab">{le._num(x["a"])} → {le._num(x["b"])}</span>'
        f'<span class="cw-sd">{le._sgn(x["d"], "")}</span>'
        f'<span class="le3-rg {_RG_CLS.get(x["code"], "fl")}">{x["zh"]}'
        + (f'<small>{x["lead"]}</small>' if x["lead"] else "") + '</span></div>'
        for x in sp)


# 自選期間的瀏覽器端：跟 analysis/longend.window_analysis 同一套規則
# （tests/test_curve_window.py 逐窗比對兩邊輸出）。
_CW_CORE_JS = r"""
function cwCore(CD){var Y=CD.year;
var RG={bear_steep:'bear',bear_flat:'bear',bull_steep:'bull',bull_flat:'bull',twist_steep:'tw',twist_flat:'tw',flat:'fl',na:'fl'};
function idx(dt){var i=0;for(var j=0;j<CD.d.length;j++){if(CD.d[j]<=dt)i=j;else break;}return i;}
function val(k,i){var a=CD[k]||[];for(var j=i;j>Math.max(-1,i-(k==='tp'?6:1));j--){if(j<a.length&&a[j]!==null)return a[j];}return null;}
function hu(v,nd){var f=Math.pow(10,nd);return Math.floor(v*f+0.5+1e-10)/f;}
function num(v,nd){nd=nd||0;var r=hu(v,nd);if(r===0)r=0;return r.toFixed(nd).replace('-','−');}
function sgn(v,u,nd){if(u===undefined)u='bp';nd=nd||0;var r=hu(v,nd);if(r===0)return (0).toFixed(nd)+u;return (r>0?'+':'')+num(v,nd)+u;}
function md2(s){return parseInt(s.slice(5,7),10)+'/'+parseInt(s.slice(8,10),10);}
function regime(dl,ds){if(dl===null||ds===null)return{code:'na',zh:'—',lead:''};var x=dl-ds;
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
 var sp=[],S={};
 [['10-2','y10','y2'],['30-10','y30','y10'],['30-2','y30','y2']].forEach(function(p){var L=T[p[1]],Sh=T[p[2]];
  if(L.a===null||L.b===null||Sh.a===null||Sh.b===null)return;var a=(L.a-Sh.a)*100,b=(L.b-Sh.b)*100,g=regime(L.d,Sh.d);
  var x={key:p[0],a:a,b:b,d:b-a,zh:g.zh,lead:g.lead,code:g.code};sp.push(x);S[p[0]]=x;});
 function dch(k){var a=val(k,ia),b=val(k,ib);return(a===null||b===null)?null:(b-a)*100;}
 var be=dch('be'),real=dch('real'),tp=dch('tp'),y3m=dch('y3m'),oa=val('oil',ia),ob=val('oil',ib);
 var oil=(oa&&ob)?(ob/oa-1)*100:null,txt=[];
 function tpDate(i){var a=CD.tp||[];for(var j=i;j>Math.max(-1,i-6);j--){if(j<a.length&&a[j]!==null)return CD.d[j];}return null;}
 var result={start:da,end:db,tenors:ten,spreads:sp,drivers:{be:be,real:real,tp:tp,oil:oil,y3m:y3m,tp_dates:[tpDate(ia),tpDate(ib)]}};
 var brief=view(result);result.text=[brief.headline,brief.panels[1].verdict,brief.panels[2].verdict];return result;}
function view(r){
 var T={},S={};r.tenors.forEach(function(t){T[t.k]=t;});r.spreads.forEach(function(s){S[s.key]=s;});var D=r.drivers,x=S['10-2'];
 var headline=!x?'資料不足，暫不判定曲線方向。':Math.abs(x.d)<2?'曲線大致持平：10 年與 2 年的利差變動很小。':x.d>0?'曲線變陡：10 年與 2 年的利差擴大。':'曲線變平：10 年與 2 年的利差縮小。';
 var metrics=r.spreads.map(function(x){return{label:x.key.replace('-',' 年 − ')+' 年',value:num(x.a)+' → '+num(x.b)+' bp',note:'變動 '+sgn(x.d)};});
 var panels=[{title:'利差怎麼變',verdict:'長短利差擴大代表曲線變陡，縮小代表變平。',metrics:metrics,note:'比較的是所選期間開始與結束日期的利差。'}];
 var be=D.be,real=D.real,dy=T.y10.d,has=be!==null&&real!==null&&dy!==null,aligned=has&&Math.abs(dy-be-real)<=2;
 var verdict=aligned&&Math.max(Math.abs(dy),Math.abs(be),Math.abs(real))<0.5?'10 年期與拆解指標大致持平。':aligned&&Math.abs(dy)<0.5?'通膨補償與實質利率的變動大致抵銷，10 年期接近持平。':aligned?'10 年期主要由'+(Math.abs(be)>Math.abs(real)?'通膨補償':'實質利率')+'變動帶動。':!has?'所選日期的拆解資料不足，暫不判定主要原因。':'參考指標與 10 年期變動尚未吻合，暫不判定主要原因。';
 function metric(label,v,u){return{label:label,value:v===null?'—':sgn(v,u===undefined?'bp':u),note:'所選期間變動'};}
 var lm=[metric('10 年期',dy),metric('通膨補償',be),metric('實質利率',real)],td=D.tp_dates||[null,null];
 if(D.tp!==null)lm.push({label:'期限溢酬（參考）',value:sgn(D.tp),note:'資料日 '+td[0]+' → '+td[1]});
 if(D.oil!==null)lm.push(metric('油價（參考）',D.oil,'%'));
 panels.push({title:'10 年期為什麼變',verdict:verdict,metrics:lm,note:'期限溢酬僅作參考，不再加到通膨補償與實質利率之上；損益兩平也含風險與流動性因素。'});
 var dy2=T.y2.d,y3m=D.y3m,path=dy2===null||y3m===null?null:dy2-y3m;
 verdict=path===null?'資料不足，暫不判定短端定價方向。':path>5?'2 年期相對短端走高，未來利率偏高的定價增強。':path< -5?'2 年期相對短端走低，未來利率偏低的定價增強。':'2 年期與短端的相對變化不大，定價方向大致未變。';
 panels.push({title:'短端定價怎麼變',verdict:verdict,metrics:[metric('2 年期',dy2),metric('3 個月期',y3m),metric('2 年 − 3 個月利差',path)],note:'這是公債短端的相對變化；年底政策利率方向另看下方期貨定價。'});
 return{headline:headline,panels:panels};}
function startFor(k,end){if(k==='ytd')return(Y-1)+'-12-31';var n={'1w':7,'1m':30,'3m':91}[k];
 var t=new Date(end+'T00:00:00Z');t.setUTCDate(t.getUTCDate()-n);return t.toISOString().slice(0,10);}
return{analysis:analysis,view:view,startFor:startFor,num:num,sgn:sgn,RG:RG};}
"""

_CW_JS = _CW_CORE_JS + r"""
(function(){
var root=document.querySelector('.cw');if(!root)return;
var CD=JSON.parse(document.getElementById('cw-data').textContent);
var C=cwCore(CD),analysis=C.analysis,startFor=C.startFor,num=C.num,sgn=C.sgn,RG=C.RG;
function safe(v){return String(v).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function tenors(ten,a,b){function date(s){return parseInt(s.slice(5,7),10)+'/'+parseInt(s.slice(8,10),10);}
 return '<table class="cw-compact" aria-label="所選期間利率變化"><thead><tr><th scope="col">天期</th><th scope="col">'+date(a)+'</th><th scope="col">'+date(b)+'</th><th scope="col">變動</th></tr></thead><tbody>'+ten.map(function(t){var c=t.d>0?'up':t.d<0?'dn':'flat';function pct(v){return v===null?'—':num(v,2)+'%';}
 return '<tr><th scope="row">'+safe(t.zh)+'期</th><td>'+pct(t.a)+'</td><td>'+pct(t.b)+'</td><td class="'+c+'">'+(t.d===null?'—':sgn(t.d))+'</td></tr>';}).join('')+'</tbody></table>';}

function explain(r){var v=C.view(r);root.querySelector('.cw-headline').textContent=v.headline;
 v.panels.forEach(function(p,i){var panel=root.querySelector('[data-panel="'+(i+1)+'"]');if(!panel)return;
 panel.querySelector('.cw-fold-reading').textContent=p.verdict;
 panel.querySelector('.cw-panel-content').innerHTML='<dl class="cw-metrics">'+p.metrics.map(function(m){return '<div><dt>'+safe(m.label)+'</dt><dd><b>'+safe(m.value)+'</b><small>'+safe(m.note)+'</small></dd></div>';}).join('')+'</dl><small class="cw-panel-note">'+safe(p.note)+'</small>';});}

function spreads(sp){return sp.map(function(x){return '<div class="cw-sr"><span class="cw-sk">'+x.key+'</span><span class="cw-sab">'+num(x.a)+' → '+num(x.b)+'</span>'
 +'<span class="cw-sd">'+sgn(x.d,'')+'</span><span class="le3-rg '+(RG[x.code]||'fl')+'">'+x.zh+(x.lead?'<small>'+x.lead+'</small>':'')+'</span></div>';}).join('');}
function mk(s){return parseInt(s.slice(0,4),10)*12+parseInt(s.slice(5,7),10)-1+(parseInt(s.slice(8,10),10)-1)/31;}
function bands(a,b){root.querySelectorAll('.cl-plot[data-x0]').forEach(function(p){var x0=+p.dataset.x0,x1=+p.dataset.x1,r=(x1-x0)||1;
 var l=Math.max(0,(mk(a)-x0)/r*100),R=Math.min(100,(mk(b)-x0)/r*100);var e=p.querySelector('.cl-band');
 if(!e){e=document.createElement('span');e.className='cl-band';p.insertBefore(e,p.firstChild);}e.style.left=l+'%';e.style.width=Math.max(0.6,R-l)+'%';});}
function show(r){explain(r);
 root.querySelector('.cw-db').innerHTML=tenors(r.tenors,r.start,r.end);root.querySelector('.cw-st').innerHTML=spreads(r.spreads);
 root.querySelector('.cw-when').textContent='實際使用 '+r.start.replace(/-/g,'/')+' → '+r.end.replace(/-/g,'/')+' 的官方日殖利率（遇假日取前一個交易日）';bands(r.start,r.end);}
var last=CD.d[CD.d.length-1],fa=root.querySelector('.cw-from'),fb=root.querySelector('.cw-to'),cu=root.querySelector('.cw-cust');
function pick(k){root.querySelectorAll('.cw-btn').forEach(function(b){b.classList.toggle('on',b.dataset.w===k);});
 if(k==='custom'){cu.hidden=false;if(!fa.value){fa.value=startFor('1m',last);fb.value=last;}show(analysis(fa.value,fb.value));return;}
 cu.hidden=true;show(analysis(startFor(k,last),last));}
root.querySelectorAll('.cw-btn').forEach(function(b){b.addEventListener('click',function(){pick(b.dataset.w);});});
[fa,fb].forEach(function(e){e.addEventListener('change',function(){if(fa.value&&fb.value)show(analysis(fa.value<fb.value?fa.value:fb.value,fa.value<fb.value?fb.value:fa.value));});});
pick('1w');
})();
"""


def curve(d: dict) -> str:
    L = d.get("le") or {}
    cd = L.get("cw") or {}
    if not cd.get("d"):
        return '<div class="empty">資料不足</div>'
    import json as _json
    year = L.get("cw_year") or int(cd["d"][-1][:4])
    last = cd["d"][-1]
    r0 = le.window_analysis(cd, le.cw_start(cd, "1w", last, year), last)
    from .curve_weekly import weekly_chart
    weekly = weekly_chart(cd)
    rows = L.get("spreads") or []
    fwd = L.get("forwards") or []
    rf = L.get("refunding") or {}
    fn = L.get("fomc_next") or ""
    st = le.curve_story(rows, L.get("curve_drivers") or {}, fwd, fomc_next=_md(fn) if fn else "",
                        refunding_next=_md(str(rf.get("next") or "")) if rf.get("next") else "")
    btns = "".join(f'<button type="button" class="cw-btn{" on" if k == "1w" else ""}" data-w="{k}">{zh}</button>'
                   for k, zh, _ in le.CW_WINDOWS) + '<button type="button" class="cw-btn" data-w="custom">自訂</button>'
    first = cd["d"][0] if cd["d"][0] >= f"{year}-01-01" else f"{year - 1}-12-31"
    data = _json.dumps({**cd, "year": year}, ensure_ascii=False, separators=(",", ":"))
    smalls = "".join(f'<div class="le3-sm"><div class="le3-smh"><b>{esc(x["key"])}</b>'
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
    compare_html = ""
    if mt and mt.get("dot_median") is not None:
        compare_html = (f'<details class="f-more"><summary>與 Fed 點陣圖比較</summary>'
                       f'<p>期貨隱含年底 {mt["market_end"]:.2f}%；點陣圖中位數 {mt["dot_median"]:.2f}%。'
                       f'兩者差距 {_sbp((mt["market_end"]-mt["dot_median"])*100)}bp。</p></details>')
    outl = "".join(f'<li class="{"hot" if o["hot"] else ""}"><b>{esc(o["tag"])}</b>{esc(o["text"])}</li>'
                   for o in st["outlook"])
    return f"""
    <div class="cw">
      <div class="cw-ctl" role="group" aria-label="比較期間">{btns}</div>
      <div class="cw-cust" hidden><label>從 <input type="date" class="cw-from" min="{first}" max="{last}"></label>
        <label>到 <input type="date" class="cw-to" min="{first}" max="{last}"></label></div>
      <div class="cw-blk"><div class="cw-h">所選期間利率變化</div><div class="cw-db">{_cw_tenors(r0["tenors"], r0["start"], r0["end"])}</div></div>
      <div class="cw-text">{_cw_explain(r0, weekly)}</div>
      <details class="f-more"><summary>利差型態補充</summary><div class="cw-st">{_cw_spreads(r0["spreads"])}</div></details>
      <div class="tabs cw-tabs">
        <input type="radio" name="cw-tab" id="cw-t1" checked><label for="cw-t1">殖利率</label>
        <input type="radio" name="cw-tab" id="cw-t2"><label for="cw-t2">利差</label>
        <div class="tabp p1">{L.get("yield_chart", "")}</div>
        <div class="tabp p2"><div class="le3-sms">{smalls}</div></div>
      </div>
      <p class="le3-cap cw-when">實際使用 {r0["start"].replace("-", "/")} → {r0["end"].replace("-", "/")} 的官方日殖利率（遇假日取前一個交易日）</p>
      <script type="application/json" id="cw-data">{data}</script>
      <script>{_CW_JS}</script>
    </div>
    <details class="f-more"><summary>曲線形狀：現在、1 週前、1 個月前、年初</summary>{L.get('curve_chart', '')}</details>
    <details class="f-more future-section cw-fold"><summary><span class="cw-fold-number">04</span><span class="cw-fold-title"><b>市場怎麼看未來利率</b><span class="cw-fold-reading">{esc(policy["text"] if policy else future["headline"])}</span></span></summary>
      {match_html}
      <section class="future-bonds"><h3>公債遠期定價方向</h3>
        <p class="future-headline">{esc(future["headline"])}</p><p>{esc(future["recent"])}</p>
        <div class="le3-ft" style="margin-top:6px">{frows or '<p>遠期資料不足</p>'}</div>
        <p class="cw-panel-note">各列代表不同的未來區間與期限，不是連續的升降息路徑；遠期值含期限溢酬，不能直接當作 Fed 的未來政策利率。</p>
      </section>{compare_html}</details>
    <details class="f-more"><summary>接下來看什麼</summary><ul class="le3-ol">{outl}</ul></details>
    <details class="f-more"><summary>方法與限制</summary>
      <div class="f-detail le3-how">
        <p><b>型態</b>：利差擴大＝變陡、收窄＝變平；看兩端誰動得多決定由哪一端帶動，殖利率上升為熊、下降為牛；兩端反向為扭轉。利差變動 2bp 以內視為持平。</p>
        <p><b>原因</b>：用市場口徑的損益兩平（T10YIE）與 TIPS 實質利率（DFII10），兩者相加約等於 10 年期；期限溢酬（Kim-Wright，約晚一週公布）跟實質利率有重疊，當旁證看。</p>
        <p><b>市場定價的未來</b>：用目前的公債殖利率算遠期利率，是市場「已經定價」的路徑，含期限溢酬，不是預測；殖利率為平價收益率，計算為近似值；3 年期比較基準由 2 年與 5 年期內插。各區間使用同日資料，超過 7 日仍找不到各天期同日資料時，暫不判讀。遠期差距及月變動在 ±5bp 內視為接近；年底期貨與現行利率差距在 ±12.5bp 內視為大致持平。</p>
        <p><b>資料口徑</b>：首頁主要公債利率、歷史曲線與利差使用美國財政部官方日殖利率，部分資料由 FRED 提供；各天期比較採同一天資料。財政部按約美東 15:30 的指示性買方報價估算固定期限殖利率，與 Bloomberg USGG 指數的 PX_LAST 口徑不同。實質利率、損益兩平及期限溢酬仍由 FRED 提供；當日拆解資料未齊時暫不判讀。盤中報價另列；歷史圖使用官方每日資料，日期以美國資料日為準。</p>
        <p><b>自選期間</b>：可查看 2026 年起的資料；遇假日採前一個有資料的日期。</p>
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
        # 給讀者看的版本：不提設定檔（維護提醒寫在執行紀錄）
        log.warning("資本支出指引待更新：財報期末 %s、指引 %s（config/rates.yaml capex_guidance）", late, asof)
        return (f'<div class="warnbox" style="margin-top:12px"><b>計畫可能已過時</b>　'
                f'年度計畫是 {esc(_md(asof))} 的版本，財報已更新到 {esc(_md(late))}。</div>')
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
