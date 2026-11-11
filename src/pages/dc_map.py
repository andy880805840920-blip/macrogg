"""
AI 大事視窗「AI資料中心擴張與監管」（2026-11；資料：src/analysis/datacenters.py）。

版面：國會與州長一行 → 期間選單（年度新增 2025–2028／累積 2026–2028）→ 美國地圖（深＝算力多）
＋右側前十州 → 州資訊框（滑鼠移到州、或點選；預設算力最大的州）→ 聯邦監管動向 → 資料說明。
州資訊框在伺服器端先排好（每州一塊、隱藏），瀏覽器只切換顯示與地圖顏色，不在前端組 HTML。
"""
from __future__ import annotations

import json

from ..site import esc

# 色階門檻（H100 等效顆數）：固定門檻，切換期間時顏色可直接比較
BINS = (100_000, 300_000, 1_000_000, 3_000_000, 10_000_000)
PZ = {"D": "民主黨", "R": "共和黨", "I": "獨立", "?": "未定"}
RISK_CLS = {"高": "hi", "中": "md", "低": "lo"}

CSS = r"""
:root{--dc0:#eef2f7;--dc1:#d4e3f4;--dc2:#a9c7e8;--dc3:#6f9fd4;--dc4:#3b72b3;--dc5:#1d4f8a;--dc6:#0f2f57;--dcneg:#e9d9cf}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--dc0:#1a2230;--dc1:#1d3350;--dc2:#22497a;--dc3:#2e64a6;--dc4:#4d88cc;--dc5:#86b4e6;--dc6:#cfe3fa;--dcneg:#4a3428}}
:root[data-theme="dark"]{--dc0:#1a2230;--dc1:#1d3350;--dc2:#22497a;--dc3:#2e64a6;--dc4:#4d88cc;--dc5:#86b4e6;--dc6:#cfe3fa;--dcneg:#4a3428}
.adc{margin-top:6px}
.adc-pol{display:grid;gap:6px;border:1px solid var(--grid);border-radius:12px;padding:10px 12px;background:var(--bg);font-size:12.5px;line-height:1.55}
.adc-pol b{font-weight:700}.adc-pol .adc-tag{display:inline-block;font-size:11px;font-weight:700;padding:1px 7px;border-radius:999px;background:var(--surface-2);margin-right:6px;color:var(--text-secondary)}
.adc-pol .D{color:#2f6db5}.adc-pol .R{color:#c4473a}
.adc-sel{display:flex;flex-wrap:wrap;align-items:center;gap:6px 6px;margin:12px 0 6px}
.adc-sel span{font-size:12px;color:var(--muted);margin-right:2px}
.adc-sel span+button{margin-left:0}
.adc-sel .adc-gap{width:10px}
@media(max-width:700px){.adc-sel .adc-gap{flex-basis:100%;width:auto;height:0}.adc-sel span{width:5.5em;flex:none}}
.adc-sel button{font:inherit;font-size:12px;font-weight:600;padding:4px 11px;min-height:32px;border:1px solid var(--border);border-radius:999px;background:var(--surface-1);color:var(--text-secondary);cursor:pointer}
.adc-sel button[aria-pressed=true]{background:var(--brand-navy);color:#fff;border-color:var(--brand-ink)}
.adc-tot{font-size:12.5px;color:var(--text-secondary);margin:2px 0 8px}
.adc-tot b{color:var(--text-primary)}
.adc-body{display:grid;gap:12px}
@media(min-width:760px){.adc-body{grid-template-columns:minmax(0,1fr) 210px;align-items:start}}
.adc-svg{display:block;width:100%;height:auto}
.adc-svg .st{fill:var(--dc0);stroke:var(--surface-1);stroke-width:.8;cursor:pointer;transition:fill .15s}
.adc-svg .st.q1{fill:var(--dc1)}.adc-svg .st.q2{fill:var(--dc2)}.adc-svg .st.q3{fill:var(--dc3)}
.adc-svg .st.q4{fill:var(--dc4)}.adc-svg .st.q5{fill:var(--dc5)}.adc-svg .st.q6{fill:var(--dc6)}.adc-svg .st.qn{fill:var(--dcneg)}
.adc-svg .st:hover,.adc-svg .st.on{stroke:var(--text-primary);stroke-width:1.8}
.adc-svg .lb{font-size:10.5px;font-weight:700;fill:var(--text-primary);text-anchor:middle;pointer-events:none;stroke:var(--surface-1);stroke-width:2.6px;paint-order:stroke;stroke-linejoin:round}
.adc-svg .fl{fill:none;stroke:var(--brand-orange);stroke-width:2.2;pointer-events:none}
.adc-lg{display:flex;flex-wrap:wrap;align-items:center;gap:4px 10px;font-size:11.5px;color:var(--muted);margin-top:6px}
.adc-lg .ramp{display:inline-flex}.adc-lg .ramp i{width:22px;height:10px;display:inline-block}
.adc-lg .fl{width:11px;height:11px;border-radius:50%;border:2px solid var(--brand-orange);display:inline-block;vertical-align:-1px}
.adc-rank{list-style:none;margin:0;padding:0;font-size:12.5px}
.adc-rank li{display:grid;grid-template-columns:22px 1fr auto;gap:6px;align-items:center;padding:3px 0;cursor:pointer;border-radius:6px}
.adc-rank li:hover{background:var(--surface-2)}
.adc-rank .bar{grid-column:2/4;height:4px;border-radius:2px;background:var(--dc4)}
.adc-rank em{font-style:normal;color:var(--muted);font-size:11px}
.adc-rank b{font-variant-numeric:tabular-nums}
.adc-rk-h{font-size:12px;font-weight:700;color:var(--muted);margin-bottom:4px}
.adc-info{border:1px solid var(--grid);border-radius:12px;padding:12px 14px;margin-top:10px;background:var(--bg);font-size:13px;line-height:1.6}
.adc-info h4{margin:0 0 4px;font-size:15px}
.adc-info .adc-k{font-size:12px;font-weight:700;color:var(--muted);margin:10px 0 4px}
.adc-num{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;font-size:12px}
.adc-num div{background:var(--surface-2);border-radius:8px;padding:6px 8px}
.adc-num b{display:block;font-size:13.5px;font-variant-numeric:tabular-nums}
.adc-num small{color:var(--muted)}
@media(max-width:520px){.adc-num{grid-template-columns:repeat(2,minmax(0,1fr))}}
.adc-risk{display:inline-block;font-size:11px;font-weight:700;padding:1px 8px;border-radius:999px;margin-left:6px}
.adc-risk.hi{background:#f6d5cf;color:#8a2a1c}.adc-risk.md{background:#f7e6c4;color:#7a5410}.adc-risk.lo{background:#d7ead9;color:#1e5b2a}
.adc-site{border-top:1px solid var(--grid);padding:8px 0}
.adc-site:first-of-type{border-top:0}
.adc-site-h{display:flex;flex-wrap:wrap;justify-content:space-between;gap:2px 10px}
.adc-site-h b{font-size:13px}.adc-site-h span{font-size:12px;color:var(--muted)}
.adc-ms{display:flex;gap:4px;overflow-x:auto;padding:6px 0 2px;scrollbar-width:thin}
.adc-ms li{list-style:none;flex:0 0 auto;font-size:11px;line-height:1.35;border-left:2px solid var(--dc4);padding:0 6px;color:var(--text-secondary);font-variant-numeric:tabular-nums}
.adc-ms li.f{border-left-style:dashed;color:var(--muted)}
.adc-ms{margin:0;padding-left:0}
.adc-note{font-size:12px;color:var(--text-secondary);margin-top:2px}
.adc-src{font-size:11.5px;color:var(--muted)}
.adc-src a{color:inherit}
.adc-fed{border:1px solid var(--grid);border-radius:12px;padding:10px 14px;margin-top:10px;background:var(--bg);font-size:13px}
.adc-fed ul{margin:4px 0 0;padding-left:18px}.adc-fed li{margin:3px 0}
.adc-more>summary{cursor:pointer;font-size:12.5px;font-weight:700;color:var(--series-1);padding:6px 0}
.adc-foot{font-size:11.5px;color:var(--muted);margin-top:8px;line-height:1.6}
"""

JS = r"""<script>(function(){var w=document.querySelector('.adc');if(!w)return;
var B=JSON.parse(w.getAttribute('data-bins')),cur=w.getAttribute('data-p');
function q(v){if(v<0)return 'qn';if(!v)return '';for(var i=0;i<B.length;i++)if(v<=B[i])return 'q'+(i+1);return 'q'+(B.length+1);}
function fmt(v){var a=Math.abs(v),s=v<0?'−':'';return a>=1e6?s+(a/1e6).toFixed(a>=1e7?1:2)+'M':a>=1e3?s+Math.round(a/1e3)+'k':s+Math.round(a);}
function paint(){w.querySelectorAll('.adc-svg .st').forEach(function(p){var v=+(p.getAttribute('data-'+cur)||0);
  p.setAttribute('class','st '+q(v)+(p.classList.contains('on')?' on':''));});
  var rows=[].slice.call(w.querySelectorAll('.adc-svg .st[data-ab]')).map(function(p){return [p.getAttribute('data-ab'),+(p.getAttribute('data-'+cur)||0),p.getAttribute('data-zh')];})
    .filter(function(r){return r[1]!==0;}).sort(function(a,b){return b[1]-a[1];}).slice(0,10);
  var mx=rows.length?Math.max.apply(null,rows.map(function(r){return Math.abs(r[1]);})):1,ol=w.querySelector('.adc-rank');ol.replaceChildren();
  rows.forEach(function(r,i){var li=document.createElement('li');li.setAttribute('data-ab',r[0]);
    var n=document.createElement('em');n.textContent=i+1;var s=document.createElement('span');s.textContent=r[2];var b=document.createElement('b');b.textContent=fmt(r[1]);
    var bar=document.createElement('i');bar.className='bar';bar.style.width=Math.max(2,Math.abs(r[1])/mx*100)+'%';
    li.appendChild(n);li.appendChild(s);li.appendChild(b);li.appendChild(bar);ol.appendChild(li);});
  var t=w.querySelector('.adc-tot');var tt=w.querySelector('.adc-tot-d[data-p="'+cur+'"]');if(t&&tt)t.innerHTML=tt.innerHTML;}
function show(ab){if(!ab)return;w.querySelectorAll('.adc-st').forEach(function(d){d.hidden=d.getAttribute('data-ab')!==ab;});
  w.querySelectorAll('.adc-svg .st').forEach(function(p){p.classList.toggle('on',p.getAttribute('data-ab')===ab);});}
w.querySelectorAll('.adc-sel button').forEach(function(b){b.addEventListener('click',function(){cur=b.getAttribute('data-p');
  w.querySelectorAll('.adc-sel button').forEach(function(x){x.setAttribute('aria-pressed',x===b?'true':'false');});paint();});});
var hov=window.matchMedia('(hover:hover)').matches,pin=w.getAttribute('data-first');
// 滑鼠移過＝預覽；點選＝固定；滑鼠離開地圖或排行就回到固定的那一州（移去按期間時不會被沿路經過的州換掉）
w.addEventListener('mouseover',function(e){if(!hov)return;var p=e.target.closest('.adc-svg [data-ab],.adc-rank [data-ab]');if(p&&w.querySelector('.adc-st[data-ab="'+p.getAttribute('data-ab')+'"]'))show(p.getAttribute('data-ab'));});
w.querySelectorAll('.adc-svg,.adc-rank').forEach(function(z){z.addEventListener('mouseleave',function(){if(hov)show(pin);});});
w.addEventListener('click',function(e){var p=e.target.closest('.adc-svg [data-ab],.adc-rank [data-ab]');if(!p)return;var ab=p.getAttribute('data-ab');
  if(w.querySelector('.adc-st[data-ab="'+ab+'"]')){pin=ab;show(ab);if(!hov){var i=w.querySelector('.adc-info');if(i)i.scrollIntoView({behavior:'smooth',block:'nearest'});}}});
paint();show(pin);})();</script>"""


def _h(v: float) -> str:
    """H100 等效顆數 → 「123 萬顆」。"""
    a = abs(v)
    s = "−" if v < 0 else ""
    if a >= 1e8:
        return f"{s}{a / 1e8:.2f} 億顆"
    return f"{s}{a / 1e4:,.0f} 萬顆" if a >= 1e4 else f"{s}{a:,.0f} 顆"


def _mw(v: float) -> str:
    a = abs(v)
    s = "−" if v < 0 else ""
    return f"{s}{a / 1000:.1f} GW" if a >= 1000 else f"{s}{a:,.0f} MW"


def _ym(s: str) -> str:
    return f"{s[:4]}/{int(s[5:7])}" if len(s) >= 7 else s


def _periods(years: list[int]) -> list[tuple[str, str, str, int]]:
    """(代號, 標籤, 種類, 年)：年度新增各年＋累積（第二年起）。"""
    out = [(f"a{y}", f"{y}", "add", y) for y in years]
    out += [(f"c{y}", f"{y}", "lvl", y) for y in years[1:]]
    return out


def _site(x: dict) -> str:
    ms = "".join(f'<li class="{"f" if m["f"] else ""}">{esc(_ym(m["d"]))}<br>{esc(_mw(m["mw"]))}<br>{esc(_h(m["h"]))}</li>'
                 for m in x.get("ms") or [])
    who = x["owner"] + (f" → {x['users']}" if x.get("users") and x["users"] != x["owner"] else "")
    end = f'規劃至 {_ym(x["end_d"])}：{_mw(x["end_mw"])}・{_h(x["end_h"])}' if x.get("end_d") else ""
    return (f'<div class="adc-site"><div class="adc-site-h"><b>{esc(x["name"])}</b><span>{esc(who)}</span></div>'
            f'<div class="adc-src">目前 {esc(_mw(x["now_mw"]))}・{esc(_h(x["now_h"]))}　{esc(end)}</div>'
            + (f'<ul class="adc-ms" aria-label="時間軸（虛線＝Epoch 推估的未來時程）">{ms}</ul>' if ms else "")
            + (f'<div class="adc-note">最新進度（{esc(_ym(x.get("note_d", "")))}）：{esc(x["note"])}</div>' if x.get("note") else "")
            + '</div>')


def _gov_line(g: dict) -> str:
    if not g:
        return ""
    b, a = g.get("before", "?"), g.get("after", "?")
    if g.get("status") == "沒改選":
        return f"州長：{PZ.get(b, b)}（2026 年沒改選）"
    who = f"{g.get('name')}，" if g.get("name") else ""
    st = "已確定" if g.get("status") == "定" else ("計票中・領先" if g.get("status") == "領先" else "結果未定")
    flip = "，改由民主黨執政" if g.get("flip") and a == "D" else ("，改由共和黨執政" if g.get("flip") else "")
    return f"州長：{PZ.get(b, b)} → {PZ.get(a, a)}（{who}{st}{flip}；2027 年 1 月就任）"


def _state_panel(ab: str, s: dict, zh: str, years: list[int], g: dict, reg: dict | None) -> str:
    num = "".join(f'<div><small>{y} 年底累積</small><b>{esc(_h(s["lvl"][y]["h"]))}</b>'
                  f'<small>{esc(_mw(s["lvl"][y]["mw"]))}・當年 {esc(_h(s["add"][y]["h"]))}</small></div>'
                  for y in years)
    r = reg or {}
    risk = r.get("risk") or "資料不足"
    rb = f'<span class="adc-risk {RISK_CLS.get(risk, "")}">推遲風險：{esc(risk)}</span>' if risk in RISK_CLS else ""
    links = "・".join(f'<a href="{esc(l["url"])}" target="_blank" rel="noopener">{esc(l.get("source") or "來源")}</a>'
                     for l in r.get("links") or [] if l.get("url"))
    reg_html = ""
    if r.get("policy") or r.get("impact"):
        reg_html = ('<div class="adc-k">監管與政策動向' + rb + '</div>'
                    + (f'<div>{esc(r["policy"])}</div>' if r.get("policy") else "")
                    + (f'<div class="adc-note">對建設時程：{esc(r["impact"])}</div>' if r.get("impact") else "")
                    + (f'<div class="adc-src">AI 依近 30 天新聞標題整理・{links}</div>' if links else ""))
    # 園區多的州（德州十幾個）：前四大直接列，其餘收合
    sites = "".join(_site(x) for x in s["sites"][:4])
    if len(s["sites"]) > 4:
        sites += (f'<details class="adc-more"><summary>其餘 {len(s["sites"]) - 4} 個園區</summary>'
                  + "".join(_site(x) for x in s["sites"][4:]) + '</details>')
    return (f'<div class="adc-st" data-ab="{ab}" hidden><h4>{esc(zh)}（{ab}）</h4>'
            f'<div class="adc-src">{esc(_gov_line(g))}</div>'
            f'<div class="adc-k">算力與電力（H100 等效・IT 電力）</div><div class="adc-num">{num}</div>'
            f'{reg_html}<div class="adc-k">資料中心時間軸（{len(s["sites"])} 個園區）</div>{sites}</div>')


def _svg(dc: dict, periods) -> str:
    from .us_map_data import PATHS, LABELS, VIEWBOX
    from ..analysis.polymarket import ABBR, STATES
    sts, gov = dc["states"], dc.get("gov") or {}
    shapes, labels, flips = [], [], []
    for st, d in PATHS.items():
        ab = ABBR.get(st, "")
        s = sts.get(ab)
        attrs = ""
        if s:
            for code, _, kind, y in periods:
                attrs += f' data-{code}="{round(s[kind][y]["h"])}"'
        g = gov.get(ab) or {}
        zh = STATES.get(st, st)
        shapes.append(f'<path class="st" d="{d}" data-ab="{ab}" data-zh="{esc(zh)}"{attrs}>'
                      f'<title>{esc(zh)}</title></path>')
        x, y = LABELS.get(st, (None, None))
        if x is None:
            continue
        if s:
            labels.append(f'<text class="lb" x="{x}" y="{y + 4}">{ab}</text>')
        if g.get("flip") and g.get("after") == "D":
            dash = ' stroke-dasharray="4 3"' if g.get("status") != "定" else ""
            flips.append(f'<circle class="fl" cx="{x}" cy="{y}" r="15"{dash}/>')
    x0, y0, w, h = VIEWBOX
    return (f'<svg class="adc-svg" viewBox="{x0} {y0} {w} {h}" role="img" aria-label="各州 AI 資料中心算力地圖">'
            + "".join(shapes) + "".join(flips) + "".join(labels) + '</svg>')


def _politics(dc: dict) -> str:
    cong, gov = dc.get("congress") or {}, dc.get("gov") or {}
    rows = []
    if cong:
        parts = [f'{c["zh"]} <b class="{c["win"]}">{PZ[c["win"]]}</b>' + ("（已確定）" if c.get("closed") else f'（市場 {c["p"]:.0%}）')
                 for c in cong.values()]
        blue = all(c["win"] == "D" for c in cong.values()) and len(cong) == 2
        rows.append('<div><span class="adc-tag">國會</span>' + "・".join(parts)
                    + ("——Blue Wave：民主黨同時掌握參眾兩院，2027 年 1 月新國會就任" if blue else "") + '</div>')
    if gov:
        bD = sum(1 for g in gov.values() if g["before"] == "D")
        aD = sum(1 for g in gov.values() if g["after"] == "D")
        aR = sum(1 for g in gov.values() if g["after"] == "R")
        fl = [ab for ab, g in gov.items() if g.get("flip") and g["after"] == "D"]
        lead = [ab for ab, g in gov.items() if g.get("status") == "領先"]
        # 算力大州：2028 累積前十，有幾州選後由民主黨執政
        y = dc["years"][-1]
        top = sorted(dc["states"], key=lambda a: -dc["states"][a]["lvl"][y]["h"])[:10]
        tot = sum(dc["states"][a]["lvl"][y]["h"] for a in dc["states"]) or 1
        dshare = sum(dc["states"][a]["lvl"][y]["h"] for a in dc["states"] if (gov.get(a) or {}).get("after") == "D") / tot
        dshare0 = sum(dc["states"][a]["lvl"][y]["h"] for a in dc["states"] if (gov.get(a) or {}).get("before") == "D") / tot
        rows.append('<div><span class="adc-tag">州長</span>'
                    f'選後 <b class="D">民主黨 {aD}</b> : <b class="R">共和黨 {aR}</b>（改選前 {bD} : {50 - bD}）；'
                    + (f'翻為民主黨：{"、".join(fl)}' if fl else "")
                    + (f'（{"、".join(lead)} 計票中，以領先者計）' if lead else "") + '</div>')
        rows.append('<div><span class="adc-tag">算力版圖</span>'
                    f'{y} 年底預估算力中，由民主黨州長執政的州佔 <b>{dshare:.0%}</b>（改選前 {dshare0:.0%}）；'
                    f'前十大州：{"、".join(top)}</div>')
    return f'<div class="adc-pol">{"".join(rows)}</div>' if rows else ""


def dc_block(dc: dict | None) -> str:
    if not dc or not dc.get("states"):
        return ""
    from ..analysis.polymarket import ABBR, STATES
    zh_of = {ab: STATES.get(st, st) for st, ab in ABBR.items()}
    years = dc["years"]
    periods = _periods(years)
    default = f"c{years[-1]}"
    sel = ('<div class="adc-sel" role="group" aria-label="期間"><span>年度新增</span>'
           + "".join(f'<button type="button" data-p="{c}" aria-pressed="{"true" if c == default else "false"}">{lab}</button>'
                     for c, lab, k, _ in periods if k == "add")
           + '<i class="adc-gap"></i><span>累積至年底</span>'
           + "".join(f'<button type="button" data-p="{c}" aria-pressed="{"true" if c == default else "false"}">{lab}</button>'
                     for c, lab, k, _ in periods if k == "lvl") + '</div>')
    tot = dc["total"]
    tots = "".join(
        f'<div class="adc-tot-d" data-p="{c}" hidden>'
        + (f'全美（Epoch 涵蓋的 AI 園區）{y} 年新增 <b>{esc(_h(tot[y]["h"] - tot[y - 1]["h"]))}</b> H100 等效、'
           f'{esc(_mw(tot[y]["mw"] - tot[y - 1]["mw"]))}' if k == "add" else
           f'全美（Epoch 涵蓋的 AI 園區）{y} 年底累積 <b>{esc(_h(tot[y]["h"]))}</b> H100 等效、{esc(_mw(tot[y]["mw"]))}')
        + '</div>' for c, _, k, y in periods)
    ramp = "".join(f'<i style="background:var(--dc{i})"></i>' for i in range(1, 7))
    legend = (f'<div class="adc-lg"><span>H100 等效</span><span class="ramp">{ramp}</span>'
              '<span>10 萬 → 1,000 萬顆以上</span><span><i class="fl"></i> 州長改由民主黨執政（虛線＝計票中、依領先者）</span></div>')
    y = years[-1]
    first = max(dc["states"], key=lambda a: dc["states"][a]["lvl"][y]["h"])
    panels = "".join(_state_panel(ab, s, zh_of.get(ab, ab), years, (dc.get("gov") or {}).get(ab, {}), (dc.get("reg") or {}).get(ab))
                     for ab, s in dc["states"].items())
    fed = dc.get("fed") or {}
    fed_html = ""
    if fed.get("points"):
        lis = "".join(f'<li>{esc(p["zh"])}' + (' <span class="adc-src">（' + "・".join(
            f'<a href="{esc(l["url"])}" target="_blank" rel="noopener">{esc(l["source"])}</a>' for l in p.get("links") or [])
            + '）</span>' if p.get("links") else "") + '</li>' for p in fed["points"])
        fed_html = f'<div class="adc-fed"><b>聯邦層級 AI 監管動向</b><span class="adc-src">　AI 依近兩週新聞標題整理</span><ul>{lis}</ul></div>'
    foot = ('<p class="adc-foot">算力與電力：<a href="' + esc(dc.get("source", "")) + '" target="_blank" rel="noopener">Epoch AI '
            'Frontier Data Centers</a>（CC BY 4.0，資料日 ' + esc(dc.get("epoch_at", "")) + '）。只涵蓋前沿 AI 資料中心園區，不是全美所有機房；'
            '未來時程（時間軸虛線）是 Epoch 依公告、許可文件與衛星影像推估，可能延後。H100 等效＝把各種 AI 晶片的運算力換算成 Nvidia H100 的顆數；'
            '「當年新增」＝年底累積減前一年底，可能為負（時程下修）。州長：改選前現任＋Polymarket 已結算盤口；監管動向與推遲風險由 AI 依新聞標題整理，附原文連結，數字須在標題中找得到。</p>')
    return ('<div class="ai-sec-h"><h3>AI資料中心擴張與監管</h3><span>滑鼠移到州（手機點選）看時間軸與監管</span></div>'
            f'<style>{CSS}</style>'
            f'<div class="adc" data-p="{default}" data-first="{first}" data-bins="{json.dumps(list(BINS))}">'
            + _politics(dc) + sel + '<div class="adc-tot"></div>' + tots
            + '<div class="adc-body"><div>' + _svg(dc, periods) + legend + '</div>'
            + '<div><div class="adc-rk-h">前十州（所選期間）</div><ol class="adc-rank"></ol></div></div>'
            + f'<div class="adc-info" aria-live="polite">{panels}</div>' + fed_html + foot + '</div>' + JS)
