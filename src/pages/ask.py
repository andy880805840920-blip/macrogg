"""
偷懶頁（/ask/）：打關鍵字或整句話，從全站資料找答案。不經 AI。

頁面本身只有：搜尋框、一行說明、結果區、分類清單（底線分頁＋三列高的捲動框）。
判讀索引（約 50KB）內嵌在頁面；每張答案卡是獨立的小檔（/ask/c/<id>.html），
點到才載入，所以全站兩百張卡不會讓這一頁變重。
"""

from __future__ import annotations

import json
from pathlib import Path

HINT = "可以打關鍵字或整句話；答案依本站最新資料自動產生，不經 AI，每天更新三次。"
PLACEHOLDER = "例如：失業率為什麼上升"

CSS = """
.ask{max-width:820px;margin:0 auto}
.ask-box{display:flex;gap:8px;margin:4px 0 6px}
.ask-box input{flex:1;min-width:0;font:inherit;font-size:16px;padding:12px 14px;border:1.5px solid var(--brand-navy);border-radius:12px;background:var(--surface-1);color:var(--text-primary)}
.ask-box button{font:inherit;font-weight:700;padding:0 18px;border:0;border-radius:12px;background:var(--brand-orange);color:#fff;cursor:pointer}
.ask-hint{font-size:12.5px;color:var(--muted);margin:0 0 14px}
.ask .ask-box{position:relative}
.ask-sug{border:1px solid var(--border);border-radius:12px;background:var(--surface-1);margin:-2px 0 8px;overflow-x:hidden;overflow-y:auto;max-height:262px;overscroll-behavior:contain;-webkit-overflow-scrolling:touch;box-shadow:0 6px 18px rgba(0,0,0,.08)}
.ask-sug a.ask-sug-all{justify-content:center;color:var(--brand-orange-ink,#ad4f27);font-weight:700;font-size:14px;background:var(--surface-2)}
.ask-sug a{display:flex;justify-content:space-between;gap:10px;padding:10px 14px;border-bottom:1px solid var(--grid);color:var(--text-primary);text-decoration:none;font-size:15px;cursor:pointer}
.ask-sug a:last-child{border-bottom:0}
.ask-sug a.on,.ask-sug a:hover{background:var(--surface-2)}
.ask-sug a small{color:var(--muted);font-size:12.5px;white-space:nowrap;align-self:center}
.ask-sug mark{background:#fde3d6;color:inherit;border-radius:3px;padding:0 2px}
.ask-x a{color:var(--brand-orange);font-weight:700;cursor:pointer}
.ask-k{font-size:12.5px;font-weight:800;color:var(--muted);letter-spacing:.04em;margin:18px 0 8px}
.ask-qs{display:flex;flex-wrap:wrap;gap:8px}
.ask-qs a{font-size:14px;padding:8px 12px;border-radius:10px;background:var(--surface-2);color:var(--text-primary);text-decoration:none;cursor:pointer}
.ask-parse{font-size:12.5px;color:var(--muted);margin:0 0 10px}
.ask-parse b{color:var(--brand-ink);font-weight:700}
.ask-card{border:1px solid var(--border);border-radius:14px;background:var(--surface-1);padding:18px 18px 8px;border-left:4px solid var(--brand-navy)}
.ask-card h2{font-size:20px;margin:0 0 4px;color:var(--brand-ink)}
.ask-meta{font-size:12.5px;color:var(--muted);margin-bottom:10px}
.ask-ans{font-size:15.5px;line-height:1.85;margin:0 0 12px}
.ask-ans b{color:var(--brand-ink)}
.ask-ans .on{background:#fde3d6;border-radius:4px;padding:0 3px}
.ask-ch{margin:6px 0 4px}
.ask-pt{display:flex;gap:4px;justify-content:flex-end;margin-bottom:2px}
.ask-pt button{font:inherit;font-size:12px;font-weight:700;padding:3px 10px;border-radius:999px;border:1px solid var(--border);background:var(--surface-1);color:var(--muted);cursor:pointer}
.ask-pt button.on{background:var(--brand-navy);border-color:var(--brand-navy);color:#fff}
.ask-tw{overflow-x:auto;-webkit-overflow-scrolling:touch}
.ask-tbl{width:100%;border-collapse:collapse;font-size:14px;margin:8px 0 12px;font-variant-numeric:tabular-nums}
.ask-tbl th{font-size:12px;color:var(--muted);font-weight:600;text-align:right;padding:6px 8px;border-bottom:1px solid var(--grid);white-space:nowrap}
.ask-tbl th:first-child,.ask-tbl td:first-child{text-align:left}
.ask-tbl td{text-align:right;padding:7px 8px;border-bottom:1px solid var(--grid)}
.ask-note{font-size:12px;color:var(--muted);margin:-4px 0 8px;line-height:1.6}
.ask-go{display:block;margin:10px 0 12px;font-weight:700;color:var(--brand-orange);text-decoration:none}
.ask-learn{border-top:1px solid var(--grid);margin-top:4px;padding-top:0}
.ask-learn>summary{list-style:none;cursor:pointer;padding:12px 0;display:flex;gap:10px;align-items:baseline}
.ask-learn>summary::-webkit-details-marker{display:none}
.ask-learn>summary b{font-size:15px;color:var(--brand-ink);white-space:nowrap}
.ask-learn>summary span{font-size:13.5px;color:var(--text-secondary);flex:1;min-width:0}
.ask-learn>summary::after{content:"展開 ▾";font-size:13px;font-weight:700;color:var(--brand-orange);white-space:nowrap}
.ask-learn[open]>summary::after{content:"收合 ▴"}
.ask-flat{border-top:0}
.ask-l{display:grid;grid-template-columns:118px 1fr;gap:4px 14px;padding:10px 0;border-top:1px dashed var(--grid)}
.ask-l h4{margin:0;font-size:13px;color:var(--brand-orange);font-weight:800}
.ask-l p{margin:0;font-size:14.5px;line-height:1.8}
.ask-chain{display:flex;flex-wrap:wrap;gap:4px 6px;align-items:center;font-size:14px}.ask-chain+.ask-chain{margin-top:6px}
.ask-chain i{font-style:normal;padding:3px 8px;border-radius:6px;background:var(--surface-2)}
.ask-chain em{font-style:normal;color:var(--brand-orange);font-weight:700}
.ask-src{font-size:11.5px;color:var(--muted);margin:8px 0 6px;line-height:1.6}
.ask-quiz{margin:12px 0 6px;padding:12px 14px;border-radius:12px;background:var(--surface-2);border:1px solid var(--border)}
.ask-quiz b{display:block;margin-bottom:8px;font-size:14.5px}
.ask-opt{display:block;width:100%;text-align:left;font:inherit;padding:8px 10px;margin:6px 0;border-radius:8px;border:1px solid var(--border);background:var(--surface-1);color:var(--text-primary);font-size:14px;cursor:pointer}
.ask-opt.ok{border-color:#2f8a4f;background:#eef8f1;color:#1d5c33}
.ask-opt.ok::after{content:"  ✓ 正解";font-weight:700}
.ask-opt.no{border-color:#c0392b;background:#fdf0ee;color:#8c2a1f}
.ask-why{font-size:13.5px;line-height:1.7;color:var(--text-secondary);margin-top:6px}
.ask-rel{margin:18px 0}
.ask-guess{border:1px solid var(--border);border-radius:14px;background:var(--surface-1);padding:16px 18px}
.ask-guess h2{font-size:18px;margin:0 0 10px;color:var(--brand-ink)}
.ask-none{font-size:14.5px;line-height:1.8;margin:0 0 6px}
/* 2026-10：只准左右滑。overflow-x:auto 會讓 y 也變成可捲，按鈕底線外推 1px 就讓 iPhone 能在框裡上下捲、字被切掉 */
.ask-flt{display:flex;overflow-x:auto;overflow-y:hidden;overscroll-behavior-x:contain;touch-action:pan-x pan-y;scrollbar-width:none;box-shadow:inset 0 -1px 0 var(--grid);margin:22px 0 10px;-webkit-overflow-scrolling:touch}
.ask-flt::-webkit-scrollbar{display:none}
.ask-flt.fr{-webkit-mask-image:linear-gradient(to right,#000 82%,transparent);mask-image:linear-gradient(to right,#000 82%,transparent)}
.ask-flt.fl{-webkit-mask-image:linear-gradient(to left,#000 82%,transparent);mask-image:linear-gradient(to left,#000 82%,transparent)}
.ask-flt.fl.fr{-webkit-mask-image:linear-gradient(to right,transparent,#000 14%,#000 86%,transparent);mask-image:linear-gradient(to right,transparent,#000 14%,#000 86%,transparent)}
.ask-flt button{flex:none;font:inherit;padding:9px 13px 11px;font-size:14px;font-weight:700;color:var(--muted);border:0;margin:0;background:none;white-space:nowrap;cursor:pointer}
.ask-flt button.on{color:var(--brand-ink);box-shadow:inset 0 -2px 0 var(--brand-orange)}
.ask-list{position:relative;max-height:276px;overflow-y:auto;overscroll-behavior:contain;-webkit-overflow-scrolling:touch;
  border:1px solid var(--border);border-radius:12px;background:var(--surface-1);padding:0 12px}
.ask-list.fade{-webkit-mask-image:linear-gradient(to bottom,#000 76%,transparent);mask-image:linear-gradient(to bottom,#000 76%,transparent)}
.ask-guess .ask-list{border:0;padding:0;border-radius:0}
.ask-all .ask-list{max-height:min(60vh,440px)}
#ask-lst .ask-list{height:276px;max-height:none;box-sizing:border-box}
.ask-list a{display:flex;justify-content:space-between;gap:10px;padding:11px 2px;border-bottom:1px solid var(--grid);color:var(--text-primary);text-decoration:none;font-size:15px;cursor:pointer}
.ask-list a:last-child{border-bottom:0}
.ask-list a span{flex:1;min-width:0}
.ask-list a small{color:var(--muted);font-size:12.5px;white-space:nowrap;align-self:center}
.ask-list a::after{content:"›";color:var(--muted);font-size:18px;line-height:1}
.ask-list mark{background:#fde3d6;color:inherit;border-radius:3px;padding:0 2px}
.ask-more{font-size:12px;color:var(--muted);margin:6px 2px 0;text-align:right}
.ask-load{font-size:14px;color:var(--muted);padding:14px 0}
@media(max-width:760px){.ask-l{grid-template-columns:1fr}.ask-card{padding:16px 14px 6px}.ask-card h2{font-size:18px}}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .ask-opt.ok{background:#173d26;color:#bfe8cc}
 :root:not([data-theme="light"]) .ask-opt.no{background:#43201b;color:#f5c6bf}
 :root:not([data-theme="light"]) .ask-list mark,:root:not([data-theme="light"]) .ask-ans .on{background:#5a3524}}
:root[data-theme="dark"] .ask-opt.ok{background:#173d26;color:#bfe8cc}
:root[data-theme="dark"] .ask-opt.no{background:#43201b;color:#f5c6bf}
:root[data-theme="dark"] .ask-list mark,:root[data-theme="dark"] .ask-ans .on{background:#5a3524}
"""

UI_JS = r"""
(function(){
"use strict";
var IX = JSON.parse(document.getElementById("ask-ix").textContent);
var M = new AskMatch(IX);
var byId = {}; IX.cards.forEach(function(c){ byId[c.i] = c; });
var $ = function(s){ return document.querySelector(s); };
var inp = $("#ask-q"), res = $("#ask-res"), cache = {};
var INT_ZH = {"定義":"定義","數值":"數值","原因":"原因","變化":"變化","影響":"影響","時間":"時間","比較":"比較","名單":"名單"};
function esc(s){ return String(s).replace(/[&<>"]/g, function(c){ return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]; }); }
function mark(t, ents){
  var s = esc(t);
  (ents||[]).forEach(function(e){
    if(!e || e.length < 1) return;
    var re = new RegExp("(" + e.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig");
    s = s.replace(re, "<mark>$1</mark>");
  });
  return s;
}
function row(c, ents, showCat){
  return '<a data-id="' + esc(c.id || c.i) + '"><span>' + mark(c.q, ents) + '</span>' + (showCat ? '<small>' + esc(c.cat || c.c) + '</small>' : '') + '</a>';
}
function listBox(items, ents, showCat){
  var h = '<div class="ask-list' + (items.length > 6 ? ' fade' : '') + '">' + items.map(function(c){ return row(c, ents, showCat); }).join("") + '</div>';
  h += '<div class="ask-more"' + (items.length > 6 ? '' : ' style="visibility:hidden"') + '>還有 ' + Math.max(0, items.length - 6) + ' 題 ↓</div>';
  return h;
}
function wireList(root){
  root.querySelectorAll(".ask-list").forEach(function(L){
    var more = L.nextElementSibling;
    L.addEventListener("scroll", function(){
      var end = L.scrollTop + L.clientHeight >= L.scrollHeight - 4;
      L.classList.toggle("fade", !end);
      if(more && more.classList.contains("ask-more")) more.style.visibility = end ? "hidden" : "";
    });
  });
}
function setURL(q){
  try { var u = new URL(location.href); if(q) u.searchParams.set("q", q); else u.searchParams.delete("q"); history.replaceState(null, "", u); } catch(e) {}
}
function parseLine(r, card){
  // 2026-10：原本的「判讀：主體…・意圖…」像除錯訊息，改成一行小字；問法跟題目一樣就不顯示
  if(!card) return "";
  var q = (inp.value || "").trim();
  if(!q || q === card.q) return "";
  return '<div class="ask-parse">依「<b>' + esc(q) + '</b>」找到這題</div>';
}
function fetchCard(id){
  if(cache[id]) return Promise.resolve(cache[id]);
  return fetch("/ask/c/" + encodeURIComponent(id) + ".html", {cache: "no-cache"}).then(function(r){
    if(!r.ok) throw new Error(r.status); return r.text();
  }).then(function(t){ cache[id] = t; return t; });
}
function related(card){
  if(card.t) return "";
  var rs = (card.r || []).map(function(i){ return byId[i]; }).filter(Boolean);
  if(!rs.length) return "";
  return '<div class="ask-rel"><div class="ask-k">相關問題</div><div class="ask-qs">' +
    rs.map(function(c){ return '<a data-id="' + esc(c.i) + '">' + esc(c.q) + '</a>'; }).join("") + '</div></div>';
}
function showCard(id, r){
  var card = byId[id]; if(!card) return;
  res.innerHTML = (r ? parseLine(r, card) : "") + '<div class="ask-load">載入中…</div>';
  fetchCard(id).then(function(h){
    res.innerHTML = (r ? parseLine(r, card) : "") + h + related(card);
    var art = res.querySelector(".ask-card");
    var p = r ? r.parse : {ints: [], per: ""};
    var lr = art && art.querySelector("details.ask-learn");
    if(lr && p.ints.indexOf("定義") >= 0) lr.open = true;
    if(p.per === "l"){ var b = art && art.querySelector('.ask-pt button[data-p="l"]'); if(b) b.click(); }
    if(p.per && p.per !== "l" && art){ art.querySelectorAll('[data-per="' + p.per + '"]').forEach(function(s){ s.hidden = false; s.classList.add("on"); }); }
    // 依問法補一句：問變化就露出「比三個月前、一年前」，問原因就露出拆解原因的那張卡
    if(art) p.ints.forEach(function(n){ art.querySelectorAll('.ask-x[data-int="' + n + '"]').forEach(function(s){ s.hidden = false; }); });
    // 動態載入的圖：補上「點選圖表查看數值」的提示（全站的圖在頁面載入時才補）
    if(art) art.querySelectorAll(".chart-inspector").forEach(function(el){
      var host = el.closest(".cl,.lwrap,.kh,.gc,.wf,.br,.sg,.nl,.dbars,.sstrip,.heatwrap,.hs3") || el.parentElement.parentElement;
      if(!host.querySelector(":scope > .chart-readout")){ var d = document.createElement("div"); d.className = "chart-readout"; d.setAttribute("role", "status"); d.setAttribute("aria-live", "polite"); d.textContent = "點選圖表查看數值；可左右拖動或使用方向鍵。"; host.appendChild(d); }
    });
  }).catch(function(){
    res.innerHTML = '<div class="ask-guess"><p class="ask-none">這張卡暫時載入不了（網路或網站更新中），請稍後再試，或直接看<a href="' + "/" + '">總覽</a>。</p></div>';
  });
}
function run(q, push, listAll){
  q = (q || "").trim();
  if(push !== false) setURL(q);
  if(!q){ res.innerHTML = ""; return; }
  var rel = M.related(q), r = rel.res;
  if(r.mode === "direct" && !listAll){ showCard(r.card, r); return; }
  var ents = r.parse.ents.length ? r.parse.ents : [r.parse.s];
  var full = rel.ids.filter(function(id){ return byId[id]; }).map(function(id){ var c = byId[id]; return {id: c.i, q: c.q, cat: c.c}; });
  var h = "";
  if(r.mode === "oos"){
    h = '<div class="ask-guess"><h2>網站目前沒有這項資料</h2><p class="ask-none">本站涵蓋美國就業、通膨、聯準會、美債與資金市場，以及總覽報價板的股市、匯率、原物料。最接近的問題：</p>' + listBox(r.list.slice(0, 3), [], true) + '</div>';
  } else if((r.mode === "none" || !r.list.length) && !full.length){
    h = '<div class="ask-guess"><h2>沒有找到相關問題</h2><p class="ask-none">換個說法試試，或從下面的分類找。</p></div>';
  } else {
    h = parseLine(r) + '<div class="ask-guess' + (listAll ? ' ask-all' : '') + '"><h2>' + (listAll ? '「' + esc(q) + '」相關的 ' + full.length + ' 題' : '我猜你想問？') + '</h2>'
      + listBox(full.length ? full : r.list, ents, true) + '</div>';
  }
  res.innerHTML = h; wireList(res);
}
// 分類清單
var CATS = ["全部"].concat(IX.cats || []);
var flt = $("#ask-flt"), lst = $("#ask-lst"), curCat = "全部";
function drawCat(cat){
  curCat = cat;
  flt.innerHTML = CATS.map(function(c){ return '<button type="button" class="' + (c === cat ? "on" : "") + '" data-c="' + esc(c) + '">' + esc(c) + '</button>'; }).join("");
  var items = IX.cards.filter(function(c){ return cat === "全部" ? !c.t : (c.c === cat || c.c2 === cat); });
  lst.innerHTML = listBox(items, [], cat === "全部"); wireList(lst);
}
flt.addEventListener("click", function(e){ var b = e.target.closest("button"); if(!b) return; drawCat(b.getAttribute("data-c"));
  var nb = flt.querySelector("button.on"); if(nb && nb.scrollIntoView) nb.scrollIntoView({block: "nearest", inline: "nearest", behavior: "smooth"}); });
// 選單列放不下時，左右邊緣淡出，提示還能滑（2026-10）
function edge(){ var m = flt.scrollWidth - flt.clientWidth;
  flt.classList.toggle("fl", flt.scrollLeft > 4); flt.classList.toggle("fr", m > 4 && flt.scrollLeft < m - 4); }
flt.addEventListener("scroll", edge, {passive: true}); window.addEventListener("resize", edge);
document.addEventListener("click", function(e){
  var a = e.target.closest("a[data-id]");
  if(a && byId[a.getAttribute("data-id")]){
    e.preventDefault(); var c = byId[a.getAttribute("data-id")];
    inp.value = c.q; setURL(c.q); showCard(c.i, null);
    window.scrollTo({top: Math.max(0, $(".ask").getBoundingClientRect().top + window.scrollY - 70), behavior: "smooth"});
    return;
  }
  var a2 = e.target.closest("a[data-card]");
  if(a2){ e.preventDefault(); var c2 = byId[a2.getAttribute("data-card")]; if(c2){ inp.value = c2.q; setURL(c2.q); showCard(c2.i, null); } return; }
  var o = e.target.closest(".ask-opt");
  if(o){
    var box = o.closest(".ask-quiz");
    box.querySelectorAll(".ask-opt").forEach(function(x){ if(x.getAttribute("data-ok") === "1") x.classList.add("ok"); });
    if(o.getAttribute("data-ok") !== "1") o.classList.add("no");
    var w = box.querySelector(".ask-why"); if(w) w.hidden = false;
    return;
  }
  var pb = e.target.closest(".ask-pt button");
  if(pb){
    var ch = pb.closest(".ask-ch"), v = pb.getAttribute("data-p");
    ch.querySelectorAll(".ask-pt button").forEach(function(x){ x.classList.toggle("on", x === pb); });
    ch.querySelectorAll(".ask-cv").forEach(function(x){ x.hidden = x.getAttribute("data-v") !== v; });
  }
});
// 打字時即時提示：最多八題（清單內可捲動），超過再給「看全部 N 題」；方向鍵選、Enter 送出、Esc 關閉
var sug = $("#ask-sug"), sugI = -1, sugT = null;
function hideSug(){ clearTimeout(sugT); sug.hidden = true; sug.innerHTML = ""; sugI = -1; }
// 送出後收起手機鍵盤（答案卡才不會被擋住），也取消還沒跑的即時提示
function done(){ hideSug(); inp.blur(); }
function drawSug(){
  if(document.activeElement !== inp) return;   // 已經送出、鍵盤收起，就不再跳出提示
  var q = inp.value.trim();
  if(!q){ hideSug(); return; }
  var rel = M.related(q), r = rel.res, all = rel.ids.filter(function(id){ return byId[id]; });
  var ids = all.slice(0, 8);
  if(!ids.length){ hideSug(); return; }
  var hl = r.parse.ents.length ? r.parse.ents : [r.parse.s];
  sug.innerHTML = ids.map(function(id, i){ var c = byId[id]; return '<a data-sug="' + esc(id) + '" class="' + (i === sugI ? "on" : "") + '"><span>' + mark(c.q, hl) + '</span><small>' + esc(c.c) + '</small></a>'; }).join("")
    + (all.length > ids.length ? '<a data-all="1" class="ask-sug-all">看全部 ' + all.length + ' 題 →</a>' : '');
  sug.hidden = false; sug.scrollTop = 0;
}
inp.addEventListener("input", function(){ sugI = -1; clearTimeout(sugT); sugT = setTimeout(drawSug, 120); });
inp.addEventListener("keydown", function(e){
  var items = sug.hidden ? [] : sug.querySelectorAll("a");
  if(e.key === "ArrowDown" && items.length){ e.preventDefault(); sugI = (sugI + 1) % items.length; }
  else if(e.key === "ArrowUp" && items.length){ e.preventDefault(); sugI = (sugI - 1 + items.length) % items.length; }
  else if(e.key === "Escape"){ hideSug(); return; }
  else return;
  items.forEach(function(a, i){ a.classList.toggle("on", i === sugI); });
  if(items[sugI] && items[sugI].scrollIntoView) items[sugI].scrollIntoView({block: "nearest"});
});
sug.addEventListener("mousedown", function(e){
  if(e.target.closest("a[data-all]")){ e.preventDefault(); done(); run(inp.value, true, true); return; }
  var a = e.target.closest("a[data-sug]"); if(!a) return;
  e.preventDefault(); var c = byId[a.getAttribute("data-sug")];
  inp.value = c.q; done(); setURL(c.q); showCard(c.i, null);
});
inp.addEventListener("blur", function(){ setTimeout(hideSug, 150); });
$("#ask-form").addEventListener("submit", function(e){
  e.preventDefault();
  var items = sug.hidden ? [] : sug.querySelectorAll("a");
  if(sugI >= 0 && items[sugI] && items[sugI].hasAttribute("data-all")){ done(); run(inp.value, true, true); return; }
  if(sugI >= 0 && items[sugI]){ var c = byId[items[sugI].getAttribute("data-sug")]; inp.value = c.q; done(); setURL(c.q); showCard(c.i, null); return; }
  done(); run(inp.value);
});
drawCat("全部"); edge();
var q0 = ""; try { q0 = new URL(location.href).searchParams.get("q") || ""; } catch(e) {}
if(q0){ inp.value = q0; run(q0, false); }
})();
"""


def _match_js() -> str:
    return (Path(__file__).with_name("ask_match.js")).read_text(encoding="utf-8")


def ask_body(index: dict) -> str:
    from ..site import esc
    ix = json.dumps(index, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return (f'<style>{CSS}</style>'
            '<div class="ask">'
            '<form class="ask-box" id="ask-form" role="search">'
            f'<input id="ask-q" type="search" autocomplete="off" enterkeyhint="search" placeholder="{esc(PLACEHOLDER)}" aria-label="輸入問題">'
            '<button type="submit">問</button></form>'
            '<div class="ask-sug" id="ask-sug" role="listbox" hidden></div>'
            f'<p class="ask-hint">{esc(HINT)}</p>'
            '<div id="ask-res" aria-live="polite"></div>'
            '<div class="ask-flt" id="ask-flt" role="tablist" aria-label="分類"></div>'
            '<div id="ask-lst"></div>'
            '</div>'
            f'<script type="application/json" id="ask-ix">{ix}</script>'
            f'<script>{_match_js()}</script><script>{UI_JS}</script>')


def fragment_page(html: str) -> str:
    """答案卡小檔：只有卡片本身（頁面用 fetch 插進結果區）。"""
    return html
