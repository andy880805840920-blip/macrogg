"""30−2 weekly bar chart; independent date selection with touch and keyboard details."""
from __future__ import annotations
import datetime as dt
import json
import math
from .. import clock
from ..site import esc
from ..analysis.curve_weekly import weekly_spreads
from ..analysis.longend import _sgn, _num

WEEKLY_CORE_JS = r"""
function cwWeekly(CD,start,end,cutoff){
 function day(s){return new Date(s+'T00:00:00Z');}function iso(d){return d.toISOString().slice(0,10);}
 function shift(s,n){var d=day(s);d.setUTCDate(d.getUTCDate()+n);return iso(d);}
 end=end<cutoff?end:cutoff;start=start||shift(end,-35);
 var points=[];(CD.d||[]).forEach(function(date,i){var a=(CD.y2||[])[i],b=(CD.y30||[])[i];
  if(date<=cutoff&&a!==null&&b!==null&&typeof a==='number'&&typeof b==='number'&&isFinite(a)&&isFinite(b))points.push({date:date,value:Math.round((b-a)*100*1e8)/1e8});});
 points.sort(function(a,b){return a.date.localeCompare(b.date);});
 function point(target){var lo=0,hi=points.length;while(lo<hi){var m=(lo+hi)>>1;if(points[m].date<=target)lo=m+1;else hi=m;}
  var p=points[lo-1];return !p||(day(target)-day(p.date))/86400000>7?null:p;}
 var rows=[];for(var t=end;t>=start;t=shift(t,-7)){var a=point(shift(t,-7)),b=point(t),valid=!!(a&&b&&a.date<b.date);
  rows.push({target:t,from:a?a.date:null,to:b?b.date:null,previous:valid?a.value:null,value:valid?b.value:null,change:valid?Math.round((b.value-a.value)*1e8)/1e8:null});}
 return{start:start,end:end,rows:rows.reverse()};}
"""

WEEKLY_JS = r"""
(function(){var root=document.querySelector('.cw-weekly');if(!root)return;
var CD=JSON.parse(root.querySelector('.ww-data').textContent),cutoff=root.dataset.cutoff;
var start=root.querySelector('.ww-from'),end=root.querySelector('.ww-to'),custom=root.querySelector('.ww-custom'),err=root.querySelector('.ww-error');
function safe(s){return String(s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function md(s){return parseInt(s.slice(5,7),10)+'/'+parseInt(s.slice(8,10),10);}
function signed(v){var n=Math.round(v*10)/10;return(n>0?'+':'')+n.toFixed(1).replace('-','−');}
var rows=[],selected=0;
function select(i){var r=rows[i];if(!r)return;selected=i;root.querySelectorAll('.ww-bar').forEach(function(b,j){b.setAttribute('aria-pressed',String(i===j));});
 var detail=root.querySelector('.ww-readout');if(r.change===null){detail.textContent=r.target+'：比較資料不足';return;}
 var change=r.change>0?'擴大':r.change<0?'縮小':'持平';detail.innerHTML='<span>'+safe(r.from)+' → '+safe(r.to)+'</span><div><span>30−2 利差 <b>'+signed(r.previous).replace(/^\+/,'')+' → '+signed(r.value).replace(/^\+/,'')+' bp</b></span><strong class="'+(r.change>=0?'up':'dn')+'">'+change+' '+Math.abs(r.change).toFixed(1)+' bp</strong></div>';}
function render(a,b){err.hidden=true;if(!a||!b||a>b||a<start.min||b>end.max){err.textContent='請選擇可用範圍內的開始與結束日期，開始日期不可晚於結束日期。';err.hidden=false;return;}
 var res=cwWeekly(CD,a,b,cutoff);rows=res.rows;var valid=rows.filter(function(r){return r.change!==null;});
 var max=Math.max.apply(null,[5].concat(valid.map(function(r){return Math.abs(r.change);}))),top=Math.ceil(max/5)*5;
 var y=function(v){return(1-v/top)/2*100;},html='<div class="ww-y">';
 [top,top/2,0,-top/2,-top].forEach(function(v){html+='<span style="top:'+y(v)+'%">'+signed(v).replace('.0','')+'</span>';});html+='</div><div class="ww-plot" style="--ww-n:'+rows.length+'">';
 [25,50,75].forEach(function(t){html+='<i class="ww-grid'+(t===50?' zero':'')+'" style="top:'+t+'%"></i>';});
 var sparse=Math.max(1,Math.ceil(rows.length/6));rows.forEach(function(r,i){var v=r.change,h=v===null?0:Math.abs(v)/top*50;
  var pos=v===null?50:Math.min(50,y(v));html+='<button type="button" class="ww-bar" data-week="'+i+'" aria-pressed="false" aria-label="'+safe(r.to||r.target)+' '+(v===null?'比較資料不足':signed(v)+' bp')+'"><span class="ww-mark '+(v>=0?'up':'dn')+'" style="top:'+pos+'%;height:'+h+'%"></span>';
  if(rows.length<=8)html+='<span class="ww-value" style="top:'+(v===null?50:y(v))+'%;transform:translateY('+(v>=0?'-140%':'20%')+')">'+(v===null?'—':signed(v).replace('.0',''))+'</span>';
  html+='<span class="ww-date">'+(i%sparse===0||i===rows.length-1?md(r.target):'')+'</span></button>';});html+='</div>';
 root.querySelector('.ww-chart').innerHTML=html;root.querySelectorAll('.ww-bar').forEach(function(bar,i){bar.addEventListener('click',function(){select(i);});bar.addEventListener('focus',function(){select(i);});});
 var plot=root.querySelector('.ww-plot');plot.addEventListener('pointermove',function(e){if(e.pointerType==='touch')return;var b=plot.getBoundingClientRect();select(Math.min(rows.length-1,Math.max(0,Math.floor((e.clientX-b.left)/b.width*rows.length))));});
 selected=rows.length-1;select(selected);
 root.querySelector('.ww-period').textContent=res.start+' → '+res.end+'・'+rows.length+' 週'+(valid.length<rows.length?'（'+(rows.length-valid.length)+' 次資料不足）':'');}
root.querySelector('.ww-six').addEventListener('click',function(){custom.hidden=true;root.querySelector('.ww-six').setAttribute('aria-pressed','true');root.querySelector('.ww-choose').setAttribute('aria-pressed','false');var d=new Date(cutoff+'T00:00:00Z');d.setUTCDate(d.getUTCDate()-35);start.value=d.toISOString().slice(0,10);end.value=cutoff;render(start.value,end.value);});
root.querySelector('.ww-choose').addEventListener('click',function(){custom.hidden=false;root.querySelector('.ww-six').setAttribute('aria-pressed','false');root.querySelector('.ww-choose').setAttribute('aria-pressed','true');});
root.querySelector('.ww-apply').addEventListener('click',function(){render(start.value,end.value);});
root.addEventListener('keydown',function(e){if(e.target.classList.contains('ww-bar')&&(e.key==='ArrowLeft'||e.key==='ArrowRight')){e.preventDefault();var i=Math.max(0,Math.min(rows.length-1,selected+(e.key==='ArrowRight'?1:-1)));root.querySelectorAll('.ww-bar')[i].focus();}});
render(start.value,end.value);
})();
"""


def weekly_chart(cd: dict, cutoff: str | None = None) -> str:
    cutoff = cutoff or (clock.today() - dt.timedelta(days=1)).isoformat()
    result = weekly_spreads(cd, cutoff=cutoff)
    rows = result['rows']
    # Static fallback keeps the six comparisons readable without JavaScript.
    top = math.ceil(max([5]+[abs(r['change']) for r in rows if r['change'] is not None])/5)*5
    bars = []
    for r in rows:
        v = r['change']; y = 50 if v is None else (1-v/top)/2*100
        h = 0 if v is None else abs(v)/top*50
        md = f"{int(r['target'][5:7])}/{int(r['target'][8:10])}"
        label = '—' if v is None else _sgn(v, '', 1)
        tip = '比較資料不足' if v is None else f"{r['from']} → {r['to']}｜{_num(r['previous'],1)} → {_num(r['value'],1)} bp｜{label} bp"
        bars.append(f'<button type="button" class="ww-bar" aria-label="{esc(tip)}"><span class="ww-mark {"up" if (v or 0)>=0 else "dn"}" style="top:{min(50,y)}%;height:{h}%"></span><span class="ww-value" style="top:{y}%;transform:translateY({"-140%" if (v or 0)>=0 else "20%"})">{label}</span><span class="ww-date">{md}</span></button>')
    axes = ''.join(f'<span style="top:{(1-v/top)/2*100}%">{_sgn(v,"",0)}</span>' for v in (top,top/2,0,-top/2,-top))
    first = cd['d'][0]
    data = json.dumps({k: cd[k] for k in ('d','y2','y30')},separators=(',',':'))
    return f'''<div class="cw-weekly" data-cutoff="{cutoff}">
      <div class="ww-heading"><h3>30−2 年利差：每週變化</h3><span>每週變化 · bp</span></div>
      <div class="ww-controls"><button type="button" class="ww-six" aria-pressed="true">最近 6 週</button><button type="button" class="ww-choose" aria-pressed="false">自訂期間</button></div>
      <div class="ww-custom" hidden><label>開始日期<input type="date" class="ww-from" value="{result['start']}" min="{first}" max="{cutoff}"></label><label>結束日期<input type="date" class="ww-to" value="{cutoff}" min="{first}" max="{cutoff}"></label><button type="button" class="ww-apply">套用</button></div>
      <p class="ww-period">{result['start']} → {cutoff}・6 週</p>
      <div class="ww-legend"><span><i class="up"></i>向上：利差擴大</span><span><i class="dn"></i>向下：利差縮小</span></div>
      <div class="ww-chart" role="group" aria-label="30−2 年利差每週變化，單位 bp"><div class="ww-y">{axes}</div><div class="ww-plot" style="--ww-n:6"><i class="ww-grid zero" style="top:50%"></i>{''.join(bars)}</div></div>
      <div class="ww-readout" aria-live="polite">點選長條查看比較日期、前後利差及變化。</div>
      <p class="ww-note">每根長條顯示利差相較 7 天前的變化，最新比較截至昨天（台灣時間）。遇假日採前一個兩個天期都有資料的日期；點選可查看實際比較日期。資料來源：美國財政部／FRED。</p>
      <p class="ww-error" role="alert" hidden></p>
      <script type="application/json" class="ww-data">{data}</script><script>{WEEKLY_CORE_JS}{WEEKLY_JS}</script>
    </div>'''
