"""每週利差變化長條圖：10−2／30−10／30−2 可切換，週五比週五；觸控與鍵盤可查看明細。"""
from __future__ import annotations
import datetime as dt
import json
import math
from .. import clock
from ..site import esc
from ..analysis.curve_weekly import weekly_spreads, SPREAD_LEGS
from ..analysis.longend import _sgn, _num

# 跟 analysis/curve_weekly.weekly_spreads 同一套規則（tests/test_curve_window.py 比對）
WEEKLY_CORE_JS = r"""
function cwWeekly(CD,start,end,cutoff,key,weeks){
 var LEG={'10-2':['y10','y2'],'30-10':['y30','y10'],'30-2':['y30','y2']}[key||'30-2'];
 function day(s){return new Date(s+'T00:00:00Z');}function iso(d){return d.toISOString().slice(0,10);}
 function shift(s,n){var d=day(s);d.setUTCDate(d.getUTCDate()+n);return iso(d);}
 function fri(s){var d=day(s);return shift(s,-((d.getUTCDay()-5+7)%7));}
 var anchored=!!start,e0=end||cutoff;e0=e0<cutoff?e0:cutoff;
 if(anchored){end=e0;}else{end=fri(e0);start=shift(end,-7*((weeks||6)-1));}
 if(start>end)throw new Error('開始日期須早於或等於結束日期');
 var points=[];(CD.d||[]).forEach(function(date,i){var a=(CD[LEG[1]]||[])[i],b=(CD[LEG[0]]||[])[i];
  if(date<=cutoff&&a!==null&&b!==null&&typeof a==='number'&&typeof b==='number'&&isFinite(a)&&isFinite(b))points.push({date:date,value:Math.round((b-a)*100*1e8)/1e8});});
 points.sort(function(a,b){return a.date.localeCompare(b.date);});
 function point(target){var lo=0,hi=points.length;while(lo<hi){var m=(lo+hi)>>1;if(points[m].date<=target)lo=m+1;else hi=m;}
  var p=points[lo-1];return !p||(day(target)-day(p.date))/86400000>7?null:p;}
 var spans=[],t;
 if(anchored){for(t=start;t<end;t=shift(t,7)){var t1=shift(t,7);spans.push([t,t1<end?t1:end]);}
  if(spans.length>52)throw new Error('期間最多 52 週');}
 else{for(t=end;t>=start;t=shift(t,-7))spans.push([shift(t,-7),t]);spans.reverse();}
 var rows=spans.map(function(s){var a=point(s[0]),b=point(s[1]),valid=!!(a&&b&&a.date<b.date);
  return{target:s[1],begin:s[0],days:Math.round((day(s[1])-day(s[0]))/86400000),from:a?a.date:null,to:b?b.date:null,previous:valid?a.value:null,value:valid?b.value:null,change:valid?Math.round((b.value-a.value)*1e8)/1e8:null};});
 return{start:start,end:end,rows:rows,key:key||'30-2',anchored:anchored};}
"""

WEEKLY_JS = r"""
(function(){var root=document.querySelector('.cw-weekly');if(!root)return;
var CD=JSON.parse(root.querySelector('.ww-data').textContent),cutoff=root.dataset.cutoff,key='30-2',span='6';
var start=root.querySelector('.ww-from'),end=root.querySelector('.ww-to'),custom=root.querySelector('.ww-custom'),err=root.querySelector('.ww-error');
function safe(s){return String(s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function md(s){return parseInt(s.slice(5,7),10)+'/'+parseInt(s.slice(8,10),10);}
function signed(v){var n=Math.round(v*10)/10;return(n>0?'+':'')+n.toFixed(1).replace('-','−');}
var rows=[],selected=0,anch=false;
function select(i){var r=rows[i];if(!r)return;selected=i;root.querySelectorAll('.ww-bar').forEach(function(b,j){b.setAttribute('aria-pressed',String(i===j));});
 var detail=root.querySelector('.ww-readout');if(r.change===null){detail.textContent=(anch?md(r.begin)+' → '+md(r.target):md(r.target)+' 當週')+'：比較資料不足';return;}
 var change=Math.abs(r.change)<0.05?'持平':r.change>0?'擴大':'收窄';detail.innerHTML='<span>'+safe(r.from)+' → '+safe(r.to)+'（'+(anch?(r.days<7?r.days+' 天，未滿一週':'7 天'):'週五收盤比週五收盤')+'）</span><div><span>'+key.replace('-','−')+' 利差 <b>'+signed(r.previous).replace(/^\+/,'')+' → '+signed(r.value).replace(/^\+/,'')+' bp</b></span><strong class="'+(r.change>=0?'up':'dn')+'">'+change+' '+Math.abs(r.change).toFixed(1)+' bp</strong></div>';}
function render(a,b,n){err.hidden=true;
 if(!n&&(!a||!b||a>=b||a<start.min||b>end.max)){err.textContent='請選擇可用範圍內的開始與結束日期，開始日期須早於結束日期。';err.hidden=false;return;}
 var res;try{res=cwWeekly(CD,n?null:a,b,cutoff,key,n);}catch(x){err.textContent=String(x.message||x).indexOf('52')>=0?'自訂期間最多 52 週（約一年），請縮短期間。':'日期有誤，請重新選擇。';err.hidden=false;return;}
 rows=res.rows;anch=res.anchored;if(!rows.length){err.textContent='期間太短，至少要跨一天。';err.hidden=false;return;}var valid=rows.filter(function(r){return r.change!==null;});
 var max=Math.max.apply(null,[4].concat(valid.map(function(r){return Math.abs(r.change);}))),top=max*1.3>10?Math.ceil(max*1.3/10)*10:Math.ceil(max*1.3/5)*5;
 var y=function(v){return(1-v/top)/2*100;},html='<div class="ww-y">';
 [top,top/2,0,-top/2,-top].forEach(function(v){html+='<span style="top:'+y(v)+'%">'+signed(v).replace('.0','')+'</span>';});html+='</div><div class="ww-plot'+(rows.length>8?' dense':'')+'" style="--ww-n:'+rows.length+'">';
 [25,50,75].forEach(function(t){html+='<i class="ww-grid'+(t===50?' zero':'')+'" style="top:'+t+'%"></i>';});
 var pw=(root.querySelector('.ww-chart')||{}).clientWidth||320,cap=Math.max(3,Math.floor((pw-46)/(anch?54:44))),sparse=Math.max(1,Math.ceil(rows.length/cap));rows.forEach(function(r,i){var v=r.change,h=v===null?0:Math.abs(v)/top*50;
  var pos=v===null?50:Math.min(50,y(v));html+='<button type="button" class="ww-bar" data-week="'+i+'" aria-pressed="false" aria-label="'+safe(r.to||r.target)+' '+(v===null?'比較資料不足':signed(v)+' bp')+'"><span class="ww-mark '+(v>=0?'up':'dn')+'" style="top:'+pos+'%;height:'+h+'%"></span>';
  if(rows.length<=8)html+='<span class="ww-value" style="top:'+(v===null?50:y(v))+'%;transform:translateY('+(v>=0?'-140%':'20%')+')">'+(v===null?'—':signed(v).replace('.0',''))+'</span>';
  var lab=(rows.length-1-i)%sparse===0;html+='<span class="ww-date">'+(lab?md(r.target)+(anch&&r.days<7?'<small>（'+r.days+' 天）</small>':''):'')+'</span></button>';});html+='</div>';
 root.querySelector('.ww-chart').innerHTML=html;root.querySelectorAll('.ww-bar').forEach(function(bar,i){bar.addEventListener('click',function(){select(i);});bar.addEventListener('focus',function(){select(i);});});
 var plot=root.querySelector('.ww-plot');plot.addEventListener('pointermove',function(e){if(e.pointerType==='touch')return;var bb=plot.getBoundingClientRect();select(Math.min(rows.length-1,Math.max(0,Math.floor((e.clientX-bb.left)/bb.width*rows.length))));});
 selected=rows.length-1;select(selected);
 var lastR=rows[rows.length-1],miss=valid.length<rows.length?'（'+(rows.length-valid.length)+' 根資料不足）':'';
 var hs=root.querySelector('.ww-heading>span');if(hs)hs.textContent=anch?'從開始日起每 7 天一根 · bp':'週五收盤比週五收盤 · bp';
 root.querySelector('.ww-period').textContent=anch?md(res.start)+' → '+md(res.end)+'・每 7 天一根，共 '+rows.length+' 根'+(lastR.days<7?'（最後一根 '+lastR.days+' 天）':'')+miss
  :'截至 '+md(res.end)+'（週五）・'+rows.length+' 週'+miss;}
function press(sel,on){root.querySelectorAll(sel).forEach(function(b){b.classList.toggle('on',b===on);b.setAttribute('aria-pressed',String(b===on));});}
function again(){if(span==='custom')render(start.value,end.value);else render(null,cutoff,+span);}
root.querySelectorAll('.ww-key').forEach(function(b){b.addEventListener('click',function(){key=b.dataset.k;press('.ww-key',b);root.querySelector('.ww-title').textContent=key.replace('-','−')+' 利差：每週變化';again();});});
root.querySelectorAll('.ww-span').forEach(function(b){b.addEventListener('click',function(){span=b.dataset.n;press('.ww-span',b);custom.hidden=span!=='custom';if(span!=='custom')again();});});
root.querySelector('.ww-apply').addEventListener('click',function(){render(start.value,end.value);});
root.addEventListener('keydown',function(e){if(e.target.classList.contains('ww-bar')&&(e.key==='ArrowLeft'||e.key==='ArrowRight')){e.preventDefault();var i=Math.max(0,Math.min(rows.length-1,selected+(e.key==='ArrowRight'?1:-1)));root.querySelectorAll('.ww-bar')[i].focus();}});
var _ww=0;window.addEventListener('resize',function(){var w=(root.querySelector('.ww-chart')||{}).clientWidth||0;if(Math.abs(w-_ww)>40){_ww=w;again();}});
again();
})();
"""


def weekly_chart(cd: dict, cutoff: str | None = None) -> str:
    cutoff = cutoff or (clock.today() - dt.timedelta(days=1)).isoformat()
    result = weekly_spreads(cd, cutoff=cutoff, key="30-2")
    rows = result['rows']
    # 沒有 JS 時的靜態版：最近 6 週的 30−2
    _mx = max([4] + [abs(r['change']) for r in rows if r['change'] is not None]) * 1.3
    top = math.ceil(_mx / 10) * 10 if _mx > 10 else math.ceil(_mx / 5) * 5      # 半格是整數，刻度不會出現 12.5
    bars = []
    for r in rows:
        v = r['change']; y = 50 if v is None else (1 - v / top) / 2 * 100
        h = 0 if v is None else abs(v) / top * 50
        md = f"{int(r['target'][5:7])}/{int(r['target'][8:10])}"
        label = '—' if v is None else _sgn(v, '', 1)
        tip = '比較資料不足' if v is None else f"{r['from']} → {r['to']}｜{_num(r['previous'], 1)} → {_num(r['value'], 1)} bp｜{label} bp"
        bars.append(f'<button type="button" class="ww-bar" aria-label="{esc(tip)}"><span class="ww-mark {"up" if (v or 0) >= 0 else "dn"}" style="top:{min(50, y)}%;height:{h}%"></span><span class="ww-value" style="top:{y}%;transform:translateY({"-140%" if (v or 0) >= 0 else "20%"})">{label}</span><span class="ww-date">{md}</span></button>')
    axes = ''.join(f'<span style="top:{(1 - v / top) / 2 * 100}%">{_sgn(v, "", 0)}</span>' for v in (top, top / 2, 0, -top / 2, -top))
    first = cd['d'][0]
    data = json.dumps({k: cd[k] for k in ('d', 'y2', 'y10', 'y30')}, separators=(',', ':'))
    keys = "".join(f'<button type="button" class="cw-btn ww-key{" on" if k == "30-2" else ""}" data-k="{k}" '
                   f'aria-pressed="{"true" if k == "30-2" else "false"}">{k.replace("-", "−")}</button>'
                   for k in SPREAD_LEGS)
    spans = "".join(f'<button type="button" class="cw-btn ww-span{" on" if n == "6" else ""}" data-n="{n}" '
                    f'aria-pressed="{"true" if n == "6" else "false"}">{zh}</button>'
                    for n, zh in (("6", "最近 6 週"), ("13", "最近 13 週"), ("custom", "自訂")))
    end_md = f"{int(result['end'][5:7])}/{int(result['end'][8:10])}"
    return f'''<div class="cw-weekly" data-cutoff="{cutoff}">
      <div class="ww-heading"><h3 class="ww-title">30−2 利差：每週變化</h3><span>週五收盤比週五收盤 · bp</span></div>
      <div class="ww-controls"><div class="cw-ctl" role="group" aria-label="利差">{keys}</div><div class="cw-ctl" role="group" aria-label="期間">{spans}</div></div>
      <div class="ww-custom" hidden><label>開始日期<input type="date" class="ww-from" value="{result['start']}" min="{first}" max="{cutoff}"></label><label>結束日期<input type="date" class="ww-to" value="{cutoff}" min="{first}" max="{cutoff}"></label><button type="button" class="ww-apply">套用</button></div>
      <p class="ww-period">截至 {end_md}（週五）・{len(rows)} 週</p>
      <div class="ww-legend"><span><i class="up"></i>向上：利差擴大（變陡）</span><span><i class="dn"></i>向下：利差收窄（變平）</span></div>
      <div class="ww-chart" role="group" aria-label="利差每週變化，單位 bp"><div class="ww-y">{axes}</div><div class="ww-plot" style="--ww-n:{len(rows)}"><i class="ww-grid zero" style="top:50%"></i>{''.join(bars)}</div></div>
      <div class="ww-readout" aria-live="polite">點選長條查看比較日期、前後利差及變化。</div>
      <details class="cw-note"><summary>圖表說明</summary><p class="ww-note">每根長條是該週五收盤相較前一個週五收盤的利差變化；週五休市時取之前最近的資料日。本週還沒到週五的變化，請看最上方的週報（滾動一週）。自訂期間改成從開始日起每 7 天一根（例如 9/3→9/10→9/17…），最後一根到結束日為止，不足 7 天的那根會標出天數；最多 52 根。資料來源：美國財政部／FRED。</p></details>
      <p class="ww-error" role="alert" hidden></p>
      <script type="application/json" class="ww-data">{data}</script><script>{WEEKLY_CORE_JS}{WEEKLY_JS}</script>
    </div>'''
