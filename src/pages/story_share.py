"""
「今日快報」圖卡（2026-10）：離開快報時跳出，在瀏覽器用 canvas 畫一張
1080×1920（9:16）的 PNG，可直接分享到 IG 限動或存到相簿。版面＝設計稿 dir1_face7：

  頂端色條 → 刊頭（LOGO＋日期）→ 主軸標題＋導言（分段、最多 8 行，放不下整段拿掉）
  → 對利率（方向徽章、10 年期、說明、壓低↔推升刻度）
  → 今日數據 2×2（讀者報價板的前兩個指標＋最新公布的數據）＋右側線條人像
  → 今明兩天（依重要性挑 4 項、依時間排；其餘寫「另有 N 項」）→ 頁尾 QR code、網址與更新時間
  區塊間距預設 56px；內容少時多出的高度平均加回間距（每處最多 +40px），
  太多時先把今明兩天減到 3 項、再拿掉導言最後一段。

不用 SVG foreignObject（Safari 會把 canvas 標成跨來源、匯不出 PNG），全部用 canvas 2D 畫。
分享要在點按的當下呼叫（Safari 要求使用者手勢），所以打開快報 1.5 秒後就先在背景把圖畫好。
跳出的動畫（風把圖吹進來）在 story_ui.py 的 showPaper。
"""
from __future__ import annotations

from pathlib import Path

_FACE = (Path(__file__).resolve().parents[2] / "assets" / "brand" / "share-face.svg")


def _face_svg() -> str:
    try:
        return _FACE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


CSS = r"""
/* 離開快報時跳出的今日快報圖：風把圖吹進來 → 落定 → 下方操作列 */
.sty-pp{position:absolute;inset:0;z-index:30;color:#fff;--pw:290px;--ph:515px}
.sty-pp-dim{position:absolute;inset:0;background:rgba(10,16,28,0);animation:ppdim .3s ease forwards}
@keyframes ppdim{to{background:rgba(10,16,28,.9)}}
.sty-pp-wind{position:absolute;inset:0;pointer-events:none;overflow:hidden}
.sty-pp-wind i{position:absolute;left:0;height:2px;border-radius:2px;background:linear-gradient(90deg,transparent,rgba(255,255,255,.55),transparent);opacity:0}
.sty-pp.go .sty-pp-wind i{animation:ppgust .7s ease-in forwards}
@keyframes ppgust{0%{opacity:0;transform:translateX(-260px)}20%{opacity:1}100%{opacity:0;transform:translateX(560px)}}
.sty-pp-st{position:absolute;inset:0;perspective:900px;pointer-events:none}
.sty-pp-fly{position:absolute;left:50%;top:56px;width:var(--pw);height:var(--ph);margin-left:calc(var(--pw) / -2);transform-style:preserve-3d;opacity:0}
.sty-pp.go .sty-pp-fly{animation:ppfly 1.3s cubic-bezier(.3,.55,.35,1) forwards,pphide .01s linear 1.32s forwards}
@keyframes ppfly{
 0%{opacity:1;transform:translate(-470px,330px) rotate(-40deg) rotateX(55deg) rotateY(30deg) scale(.55)}
 22%{transform:translate(-170px,-80px) rotate(18deg) rotateX(-35deg) rotateY(28deg) scale(.75)}
 45%{transform:translate(110px,-10px) rotate(-14deg) rotateX(25deg) rotateY(-24deg) scale(.88)}
 66%{transform:translate(-40px,30px) rotate(7deg) rotateX(-12deg) rotateY(10deg) scale(.95)}
 84%{transform:translate(10px,-6px) rotate(-3deg) rotateX(5deg) rotateY(-3deg) scale(1)}
 100%{opacity:1;transform:none}}
@keyframes pphide{to{opacity:0}}
.sty-pp-s{position:absolute;left:0;top:0;height:var(--ph);transform-origin:0 50%;background-size:var(--pw) var(--ph);background-repeat:no-repeat}
/* 落定後換成一張真的圖片（手機可長按儲存） */
.sty-pp-img{position:absolute;left:50%;top:56px;width:var(--pw);height:var(--ph);margin-left:calc(var(--pw) / -2);border-radius:3px;
  box-shadow:0 16px 36px rgba(0,0,0,.5);opacity:0;-webkit-touch-callout:default;user-select:auto;-webkit-user-select:auto}
.sty-pp.go .sty-pp-img{animation:ppshow .01s linear 1.3s forwards}
.sty-pp.still .sty-pp-img{animation:ppshow .35s ease forwards}
@keyframes ppshow{to{opacity:1}}
.sty-pp-x{position:absolute;top:14px;right:8px;border:0;background:none;color:#fff;font-size:28px;line-height:1;padding:6px 10px;cursor:pointer;opacity:0;animation:ppshow .3s ease 1.3s forwards}
.sty-pp.still .sty-pp-x{animation-delay:0s}
.sty-pp-sheet{position:absolute;left:0;right:0;bottom:0;background:#fff;color:#12233B;border-radius:22px 22px 0 0;padding:14px 18px 20px;transform:translateY(105%);box-shadow:0 -10px 30px rgba(0,0,0,.25)}
.sty-pp.go .sty-pp-sheet{animation:ppup .35s cubic-bezier(.2,.9,.3,1) 1.4s forwards}
.sty-pp.still .sty-pp-sheet{animation:ppup .3s ease forwards}
@keyframes ppup{to{transform:none}}
.sty-pp-grab{display:block;width:40px;height:4px;border-radius:2px;background:#d8d4cc;margin:0 auto 10px}
.sty-pp-sheet h4{margin:0;font-size:15px;font-weight:900}.sty-pp-sheet p{margin:2px 0 12px;font-size:12px;color:#6b6a64}
.sty-pp-btns{display:flex;gap:10px}
.sty-pp-btns button{flex:1;height:48px;border-radius:999px;font:inherit;font-size:15px;font-weight:900;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:6px}
.sty-pp-btns .sty-pp-dl{flex:1.4;background:#E67143;color:#fff;border:0}
.sty-pp-dl::before{content:"";width:15px;height:15px;background:currentColor;-webkit-mask:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Cpath d='M8 1v9M4 6l4 4 4-4M2 13h12' fill='none' stroke='%23000' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") center/contain no-repeat;mask:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Cpath d='M8 1v9M4 6l4 4 4-4M2 13h12' fill='none' stroke='%23000' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") center/contain no-repeat}
.sty-pp-btns .sty-pp-share{background:#fff;color:#12233B;border:1.5px solid #12233B}
.sty-pp-btns .sty-pp-share[hidden]{display:none}
.sty-pp-go{display:block;margin:10px auto 0;border:0;background:none;font:inherit;font-size:13px;font-weight:700;color:#12233B;opacity:.8;cursor:pointer;padding:6px 10px}
.sty-pp button:focus-visible{outline:3px solid #E67143;outline-offset:2px}
.sty-pp-toast{position:absolute;left:50%;bottom:190px;transform:translate(-50%,10px);background:#12233B;color:#fff;font-size:13.5px;font-weight:700;padding:9px 16px;border-radius:999px;opacity:0;white-space:nowrap;pointer-events:none}
.sty-pp-toast.on{animation:pptoast 2.2s ease forwards}
@keyframes pptoast{12%{opacity:1;transform:translate(-50%,0)}85%{opacity:1}100%{opacity:0}}
"""

# 頁尾小 QR code：https://macrogg.netlify.app/（ECC M；用 segno 預先算好，瀏覽器只負責畫方格，
# 不必載入 QR 函式庫）。網址改了要重算：segno.make(url, error="m").matrix
QR_ROWS = ['11111110111010011101101111111', '10000010111000110100101000001', '10111010010011110010101011101', '10111010111100001110001011101', '10111010010111000001001011101', '10000010000100100111101000001', '11111110101010101010101111111', '00000000110101100100100000000', '10110111010001101110001001011', '01001001001010011011111110001', '11110111101010110100111110110', '00011001011011110011110000001', '10001110001000001101000101100', '10111000110001000111001000111', '01011110000100100001011110111', '00111000100101010010101010010', '10000010000110000010010111010', '00100100110111000010100101110', '10010010001110000010100110100', '00001000100010011100011100100', '01110111110011010101111111100', '00000000111111110110100011111', '11111110110111001011101011010', '10000010111010001010100011001', '10111010010110110010111110101', '10111010110110101100000111010', '10111010111110111000100100101', '10000010000110001010101111010', '11111110111011010101101010010']

JS = r"""
var MG_FACE = %%FACE%%;
var MG_QR = %%QR%%;
function mgShot(D){
  var W = 1080, H = 1920, M = 72, CW = W - 2 * M;
  var INK = "#12233B", OR = "#E67143", PAPER = "#f7f4ed", RULE = "#ddd6c8", MUTE = "#6b6a64", UP = "#b82828", DN = "#0b7a3b", SOFT = "#55585e";
  var CJK = '"PingFang TC","Noto Sans TC","Noto Sans CJK TC","Microsoft JhengHei","Heiti TC",sans-serif', MS = '"Montserrat",' + CJK;
  function tpe(fmt){ try{ return new Intl.DateTimeFormat("en-US", Object.assign({timeZone: "Asia/Taipei"}, fmt)).format(new Date()); }catch(e){ return ""; } }
  function tpeISO(ms){ try{ return new Intl.DateTimeFormat("en-CA", {timeZone: "Asia/Taipei"}).format(new Date(ms)); }catch(e){ return D.day; } }
  function addDay(iso, n){ var p = iso.split("-").map(Number), d = new Date(Date.UTC(p[0], p[1] - 1, p[2] + n)); return d.toISOString().slice(0, 10); }
  function wkZh(iso){ var p = iso.split("-").map(Number); return "週" + "日一二三四五六".charAt(new Date(Date.UTC(p[0], p[1] - 1, p[2])).getUTCDay()); }
  function load(src){ return new Promise(function(ok){ var im = new Image(); im.onload = function(){ ok(im); }; im.onerror = function(){ ok(null); }; im.src = src; }); }
  function fonts(){ if(!document.fonts || !document.fonts.load) return Promise.resolve();
    var t = new Promise(function(ok){ setTimeout(ok, 1500); });
    return Promise.race([t, Promise.all(["800 66px Montserrat", "700 22px Montserrat", "400 23px Montserrat"].map(function(f){ return document.fonts.load(f, "0123456789/%"); }))]).catch(function(){}); }
  // ---- 讀畫面上的資料：報價板（讀者選的前兩個＋10 年期）----
  function chip(el){ if(!el) return null; var l = el.querySelector(".fs-nm span"), b = el.querySelector("b"), i = el.querySelector("i");
    var v = b ? b.textContent.trim() : ""; if(!v || v === "—") return null;
    return {l: l ? l.textContent.trim() : "", v: v, c: i ? i.textContent.trim() : "", dir: i ? (i.classList.contains("up") ? "up" : i.classList.contains("dn") ? "dn" : "") : ""}; }
  var mine = [];
  Array.prototype.forEach.call(document.querySelectorAll(".fs-chips [data-chip]:not(.fs-off)"), function(c){ var x = chip(c); if(x && mine.length < 4) mine.push(x); });
  var ten = chip(document.querySelector('.fs-chips [data-chip="live_dgs10"]')) || chip(document.querySelector('.fs-chips [data-chip="dgs10"]'));
  // ---- 2×2：前兩格＝讀者的指標，後兩格＝最新公布的數據（沒有就用報價板第 3、4 個）----
  var cells = mine.slice(0, 2).map(function(x){ return {l: x.l, v: x.v, c: x.c || "持平", cls: x.dir === "up" ? "up" : x.dir === "dn" ? "dn" : "fl"}; });
  var L = D.latest, mo = L && /（(\d+) 月）/.exec(L.name || "");
  (L ? L.rows : []).slice(0, 2).forEach(function(r){
    var c = r.vs && r.forecast ? r.vs + " " + r.forecast : r.forecast ? "預估 " + r.forecast : r.previous ? "前值 " + r.previous : (L.date ? L.date + " 公布" : "");
    cells.push({l: (mo ? mo[1] + " 月" + (/^[A-Za-z0-9]/.test(r.label) ? " " : "") : "") + r.label, v: r.actual, c: c, cls: /高於/.test(r.vs) ? "up" : /低於/.test(r.vs) ? "dn" : "fl"}); });
  mine.slice(2).forEach(function(x){ if(cells.length < 4) cells.push({l: x.l, v: x.v, c: x.c || "持平", cls: x.dir === "up" ? "up" : x.dir === "dn" ? "dn" : "fl"}); });
  cells = cells.slice(0, 4);
  // ---- 今明兩天：重要的先挑 4 項，再依時間排 ----
  var today = tpeISO(Date.now()), nowMs = Date.now(), days = [today, addDay(today, 1)];
  var evs = (D.up || []).filter(function(x){ if(days.indexOf(x.date) < 0) return false; var ms = x.at ? Date.parse(x.at) : NaN; return !(isFinite(ms) && ms < nowMs); });
  var pr = function(x){ return x.k === "d" ? (x.hi ? 0 : 1) : x.k === "p" ? 2 : x.k === "s" ? 3 : 4; };
  var rk = function(x){ return x.k === "h" ? 0 : x.at ? 1 : 2; };
  var pick = evs.slice().sort(function(a, b){ return (pr(a) - pr(b)) || String(a.date + (a.at || "")).localeCompare(String(b.date + (b.at || ""))); });
  var more = Math.max(0, pick.length - 4); pick = pick.slice(0, 4);
  pick.sort(function(a, b){ return a.date.localeCompare(b.date) || (rk(a) - rk(b)) || String(a.at || "").localeCompare(String(b.at || "")); });
  var TAG = {d: "數據", s: "發債", p: "談話", h: "休市"};
  // ---- 畫圖工具 ----
  var cv = document.createElement("canvas"); cv.width = W; cv.height = H; var g = cv.getContext("2d");
  function font(w, s, fam){ g.font = w + " " + s + "px " + (fam || CJK); }
  function spaced(t, x, y, sp){ for(var i = 0; i < t.length; i++){ g.fillText(t[i], x, y); x += g.measureText(t[i]).width + sp; } return x; }
  function tokens(t){ return String(t || "").match(/[A-Za-z0-9.,%+\-−/:()$]+|\s+|./g) || []; }
  var NOHEAD = "，。、：；！？）」』%…".split("");
  function wrap(t, maxW, maxL){
    var tk = tokens(t), lines = [], cur = "";
    for(var i = 0; i < tk.length; i++){
      var nx = cur + tk[i];
      if(g.measureText(nx).width <= maxW || !cur || NOHEAD.indexOf(tk[i]) >= 0){ cur = nx; continue; }
      lines.push(cur.replace(/\s+$/, "")); cur = tk[i].replace(/^\s+/, "");
    }
    if(cur) lines.push(cur);
    if(maxL && lines.length > maxL){ var last = lines[maxL - 1]; lines = lines.slice(0, maxL);
      while(last && g.measureText(last + "…").width > maxW) last = last.slice(0, -1);
      lines[maxL - 1] = last.replace(/[，、。：；\s]+$/, "") + "…"; }
    return lines;
  }
  function fit(t, w, s, fam, maxW, min){ var z = s; font(w, z, fam); while(z > (min || 12) && g.measureText(t).width > maxW){ z -= 1; font(w, z, fam); } return z; }
  function ell(t, maxW){ t = String(t || ""); if(g.measureText(t).width <= maxW) return t; while(t && g.measureText(t + "…").width > maxW) t = t.slice(0, -1); return t + "…"; }
  function rrect(x, y, w, h, r){ g.beginPath(); g.moveTo(x + r[0], y); g.lineTo(x + w - r[1], y); g.quadraticCurveTo(x + w, y, x + w, y + r[1]);
    g.lineTo(x + w, y + h - r[2]); g.quadraticCurveTo(x + w, y + h, x + w - r[2], y + h); g.lineTo(x + r[3], y + h); g.quadraticCurveTo(x, y + h, x, y + h - r[3]);
    g.lineTo(x, y + r[0]); g.quadraticCurveTo(x, y, x + r[0], y); g.closePath(); }
  function label(t, y){ g.fillStyle = OR; font(800, 23); g.textBaseline = "middle"; var x = spaced(t, M, y + 16, 23 * .22);
    g.fillStyle = RULE; g.fillRect(x + 10, y + 16, W - M - x - 10, 1.5); g.textBaseline = "top"; return y + 33; }
  var rateTxt = (D.rate || "").trim(), dir = D.rate_dir || "flat";
  // 導言分段（2026-10）：最多 8 行；優先用原文段落，只有一段時依句號切，每段最多 3 行。
  // 放不下就整段拿掉（不在句子中間截斷）；只有第一段也放不下時才加「…」。
  var LEAD_MAX = 8, PGAP = 14, LH = 46.4;
  function leadParas(){
    font(500, 29);
    var src = (D.paras && D.paras.length > 1) ? D.paras.slice() : [((D.paras && D.paras[0]) || D.para || D.lead || "").trim()];
    var out = [];
    src.forEach(function(t){
      if(!t) return;
      if(src.length > 1){ out.push(t); return; }
      var ss = t.match(/[^。！？]+[。！？」）]*/g) || [t], cur = "";
      ss.forEach(function(x){ var nx = cur + x; if(cur && wrap(nx, CW).length > 3){ out.push(cur); cur = x; } else cur = nx; });
      if(cur) out.push(cur);
    });
    return out;
  }
  var PARAS = null;
  function layout(draw, leadMax, evMax, imgs, G){
    g.textBaseline = "top"; var y;
    if(draw){ g.fillStyle = PAPER; g.fillRect(0, 0, W, H); g.fillStyle = INK; g.fillRect(0, 0, W * .7, 14); g.fillStyle = OR; g.fillRect(W * .7, 0, W * .3, 14);
      // 刊頭
      var yr = tpe({year: "numeric"}), wd = tpe({weekday: "short"}).toUpperCase(), md = tpe({month: "numeric", day: "numeric"});
      g.fillStyle = MUTE; font(700, 22, MS); var st = yr + " · " + wd, sw = 0; for(var i = 0; i < st.length; i++) sw += g.measureText(st[i]).width + 22 * .24;
      spaced(st, W - M - sw + 22 * .24, 54, 22 * .24);
      g.fillStyle = INK; font(800, 66, MS); g.textAlign = "right"; g.fillText(md, W - M, 82); g.textAlign = "left";
      if(imgs.logo){ var lh = 64, lw = imgs.logo.width / imgs.logo.height * lh || 240; g.drawImage(imgs.logo, M, 148 - lh, lw, lh); }
      g.fillStyle = INK; g.fillRect(M, 170, CW, 5); }
    y = 175 + 38;
    // 主軸
    font(900, 64); var hl = wrap(D.headline || "今日市場重點", CW, 3);
    if(draw){ g.fillStyle = INK; hl.forEach(function(t, i){ g.fillText(t, M, y + i * 81 + 8); }); }
    y += hl.length * 81;
    if(!PARAS) PARAS = leadParas();
    if(PARAS.length && leadMax > 0){ y += 16; font(500, 29); var used = 0;
      for(var pi = 0; pi < Math.min(leadMax, PARAS.length); pi++){
        var ll = wrap(PARAS[pi], CW);
        if(used + ll.length > LEAD_MAX){ if(pi) break; ll = wrap(PARAS[pi], CW, LEAD_MAX); }
        if(pi) y += PGAP;
        if(draw){ g.fillStyle = "#2d3a4d"; ll.forEach(function(t, i){ g.fillText(t, M, y + i * LH + 8); }); }
        y += ll.length * LH; used += ll.length; } }
    // 對利率
    if(rateTxt){ y += G; if(draw) label("對利率", y); y += 33 + 16;
      font(600, 28); var rl = wrap(rateTxt, CW - 8 - 48, 3), bh = 16 + 40 + 8 + rl.length * 42 + 12 + 6 + 8 + 26 + 12;
      if(draw){
        g.fillStyle = "#efebe2"; rrect(M, y, CW, bh, [0, 18, 18, 0]); g.fill(); g.fillStyle = INK; g.fillRect(M, y, 8, bh);
        var bx = M + 8 + 24, by = y + 16;
        var B = {up: ["↑", "偏向推升利率", UP, "#f3dede"], down: ["↓", "偏向壓低利率", DN, "#dcefe3"], flat: ["→", "利率大致持平", "#8a8880", "#e6e3dc"], unclear: ["?", "方向不明確", "#8a8880", "#e6e3dc"]}[dir] || ["→", "利率大致持平", "#8a8880", "#e6e3dc"];
        font(800, 22); var bw = 6 + 28 + 8 + g.measureText(B[1]).width + 14;
        g.fillStyle = B[3]; rrect(bx, by + 2, bw, 36, [18, 18, 18, 18]); g.fill();
        g.fillStyle = B[2]; g.beginPath(); g.arc(bx + 6 + 14, by + 20, 14, 0, Math.PI * 2); g.fill();
        g.fillStyle = "#fff"; font(900, 19, MS); g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(B[0], bx + 20, by + 21);
        g.textAlign = "left"; g.fillStyle = B[2] === "#8a8880" ? "#4d4c47" : B[2]; font(800, 22); g.fillText(B[1], bx + 6 + 28 + 8, by + 21);
        if(ten){ var rx = M + CW - 24; g.textAlign = "right";
          var dc = ten.dir === "up" ? UP : ten.dir === "dn" ? DN : MUTE;
          if(ten.c){ font(800, 26, MS); g.fillStyle = dc; g.fillText(ten.c, rx, by + 21); rx -= g.measureText(ten.c).width + 8; }
          font(800, 32, MS); g.fillStyle = INK; g.fillText(ten.v, rx, by + 20); rx -= g.measureText(ten.v).width + 6;
          font(700, 22); g.fillStyle = MUTE; g.fillText("10 年期", rx, by + 21); g.textAlign = "left"; }
        g.textBaseline = "top"; g.fillStyle = INK; font(600, 28); rl.forEach(function(t, i){ g.fillText(t, bx, by + 40 + 8 + i * 42 + 6); });
        var gy = by + 40 + 8 + rl.length * 42 + 12, gw = CW - 8 - 48, gr = g.createLinearGradient(bx, 0, bx + gw, 0);
        gr.addColorStop(0, "#3f9f6a"); gr.addColorStop(.5, "#a3a7ae"); gr.addColorStop(1, "#d0574f");
        g.fillStyle = gr; rrect(bx, gy, gw, 6, [3, 3, 3, 3]); g.fill();
        var pos = dir === "up" ? .82 : dir === "down" ? .18 : .5;
        g.fillStyle = "#fff"; g.strokeStyle = INK; g.lineWidth = 4; g.beginPath(); g.arc(bx + gw * pos, gy + 3, 9, 0, Math.PI * 2); g.fill(); g.stroke();
        font(700, 19); g.fillStyle = MUTE; g.fillText("壓低", bx, gy + 6 + 8); g.textAlign = "right"; g.fillText("推升", bx + gw, gy + 6 + 8); g.textAlign = "left"; }
      y += bh; }
    // 今日數據＋人像
    if(cells.length){ y += G; if(draw) label("今日數據", y); y += 33;
      var FW = 300, FH = 375, GW = CW - FW - 24, half = GW / 2, CH = 174, rows = Math.ceil(cells.length / 2), gh = 6 + rows * CH, blk = Math.max(gh, FH);
      if(draw){
        var gy0 = y + 6 + (blk - gh) / 2;
        cells.forEach(function(c, i){ var col = i % 2, row = (i / 2) | 0, x = col ? M + half + 26 : M, w = half - (col ? 26 : 24), cy = gy0 + row * CH;
          if(row){ g.fillStyle = RULE; g.fillRect(M, cy, GW, 1.5); }
          if(!col){ g.fillStyle = RULE; g.fillRect(M + half, cy, 1.5, CH); }
          g.fillStyle = MUTE; fit(c.l, 600, 23, CJK, w, 16); g.fillText(ell(c.l, w), x, cy + 22 + 4);
          g.fillStyle = INK; fit(c.v, 800, 50, MS, w, 28); g.fillText(c.v, x, cy + 22 + 33 + 4 + 2);
          g.fillStyle = c.cls === "up" ? UP : c.cls === "dn" ? DN : MUTE; fit(c.c, 700, 24, CJK, w, 15); g.fillText(ell(c.c, w), x, cy + 22 + 33 + 4 + 56 + 2 + 4); });
        if(imgs.face) g.drawImage(imgs.face, W - M - FW, y + (blk - FH) / 2, FW, FH); }
      y += blk; }
    // 今明兩天
    y += G; if(draw) label("今明兩天", y); y += 33;
    var shown = pick.slice(0, evMax), extra = more + (pick.length - shown.length), lastD = "";
    if(!shown.length){ if(draw){ font(400, 24); g.fillStyle = SOFT; g.fillText("今明兩天沒有排定的重要事項。", M, y + 14); } y += 56; }
    shown.forEach(function(x){
      if(draw){ g.fillStyle = SOFT;
        if(x.date !== lastD){ font(400, 23, MS); var dd = parseInt(x.date.slice(5, 7), 10) + "/" + parseInt(x.date.slice(8, 10), 10); g.fillText(dd, M, y + 14);
          var dw = g.measureText(dd + " ").width; font(400, 19); g.fillText(wkZh(x.date), M + dw, y + 17); }
        font(400, 23, MS); g.fillText(x.k === "h" ? "全天" : (x.t || "未定"), M + 164, y + 14);
        font(400, 20); g.textAlign = "right"; g.fillText(TAG[x.k] || "", W - M, y + 16); var tw = g.measureText(TAG[x.k] || "").width; g.textAlign = "left";
        font(400, 24); g.fillText(ell(x.name + (x.sub ? "（" + x.sub + "）" : ""), W - M - tw - 16 - (M + 258)), M + 258, y + 13);
        g.fillStyle = RULE; g.fillRect(M, y + 55, CW, 1); }
      lastD = x.date; y += 56; });
    if(extra > 0){ if(draw){ font(400, 22); g.fillStyle = MUTE; g.fillText("另有 " + extra + " 項，詳見網站「接下來看什麼」", M, y + 14); } y += 50; }
    // 頁尾：左下小 QR code＋網址，右下更新時間
    var QS = 108, fy = H - 34 - QS - 18;
    if(draw){ g.fillStyle = INK; g.fillRect(M, fy, CW, 1.5);
      var qy = fy + 18, n = MG_QR.length, cell = QS / (n + 2);
      g.fillStyle = "#fff"; g.fillRect(M, qy, QS, QS); g.fillStyle = INK;
      for(var r2 = 0; r2 < n; r2++) for(var c2 = 0; c2 < n; c2++) if(MG_QR[r2].charAt(c2) === "1")
        g.fillRect(Math.round(M + (c2 + 1) * cell), Math.round(qy + (r2 + 1) * cell), Math.ceil(cell), Math.ceil(cell));
      var hn = location.hostname; if(!hn || /^(localhost|127\.|0\.0\.0\.0)/.test(hn)) hn = "macrogg.netlify.app";
      font(700, 24, MS); g.fillStyle = INK; g.fillText(hn, M + QS + 20, qy + 26);
      font(600, 20); g.fillStyle = MUTE; g.fillText("掃描看完整內容", M + QS + 20, qy + 62);
      font(600, 21); g.textAlign = "right"; g.fillText("台北時間 " + (D.stamp || "") + " 更新", W - M, qy + 62); g.textAlign = "left"; }
    return {end: y, limit: fy - 24};
  }
  return Promise.all([fonts(), load("/brand/logo-full.svg"), MG_FACE ? load("data:image/svg+xml;charset=utf-8," + encodeURIComponent(MG_FACE)) : Promise.resolve(null)]).then(function(r){
    var imgs = {logo: r[1], face: r[2]}, lm = 9, em = 4, G0 = 56, m;
    // 太長：先把今明兩天減到 3 項，再拿掉導言最後一段（標題、數據不動）
    for(var k = 0; k < 16; k++){ m = layout(false, lm, em, imgs, G0); if(m.end <= m.limit) break;
      if(em > 3) em--; else if(lm > 1){ lm = Math.min(lm, (PARAS || []).length) - 1; if(lm < 1) lm = 1; } else if(em > 1) em--; else break; }
    // 太短：多出來的高度平均加回區塊間距（每處最多 +40），再多就留在底部
    var nG = (rateTxt ? 1 : 0) + (cells.length ? 1 : 0) + 1, G = G0;
    if(m.end < m.limit) G = G0 + Math.min(40, Math.floor((m.limit - m.end) / nG));
    layout(true, lm, em, imgs, G);
    return new Promise(function(ok){ cv.toBlob(function(b){ ok(b); }, "image/png"); });
  });
}
"""


def js() -> str:
    import json
    return JS.replace("%%FACE%%", json.dumps(_face_svg())).replace("%%QR%%", json.dumps(QR_ROWS))
