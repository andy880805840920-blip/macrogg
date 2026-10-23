"""
首頁「今日快報」限時動態的畫面與動畫（2026-10）。資料由 analysis/stories.py 組好。

  何時播：每個「版本日期」第一次打開首頁播一次（看內容是哪一天的版本，不看打開的時間）；網址帶 #錨點或 ?q= 不播；
          系統設定「減少動態效果」不自動播。標題旁的「快報」圓鈕可隨時重看，
          網址加 ?story=1 也會播（分享、測試用）。
  操作：  點右側下一則、點左側上一則、按住暫停、往下滑或 ✕／Esc 關閉、方向鍵切換。
"""
from __future__ import annotations

import json

STORY_BTN = ('<button type="button" class="fs-story-btn" hidden aria-label="播放今日快報">'
             '<span class="fs-story-ring"><span>快報</span></span></button>')

CSS = r"""
.fs-story-btn{margin-left:8px;border:0;background:none;padding:0;cursor:pointer;vertical-align:middle}
.fs-story-ring{display:inline-flex;align-items:center;justify-content:center;width:38px;height:38px;border-radius:50%;
  background:conic-gradient(#E67143,#ffb36b,#12233B,#E67143);padding:2px;animation:styspin 6s linear infinite}
.fs-story-ring span{display:flex;align-items:center;justify-content:center;width:100%;height:100%;border-radius:50%;
  background:var(--surface-1);color:var(--brand-ink);font-size:11px;font-weight:800;letter-spacing:.02em;animation:styspin 6s linear infinite reverse}
.fs-story-btn.seen .fs-story-ring{background:var(--border);animation:none}.fs-story-btn.seen .fs-story-ring span{animation:none}
@keyframes styspin{to{transform:rotate(360deg)}}
.sty{position:fixed;inset:0;z-index:9999;background:rgba(8,14,26,.84);-webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);
  display:flex;align-items:center;justify-content:center;animation:styfade .25s ease both}
.sty[hidden]{display:none}
@keyframes styfade{from{opacity:0}}
.sty-stage{position:relative;width:min(100vw,430px);height:min(100dvh,860px);overflow:hidden;color:#fff;background:#12233B;
  user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;touch-action:none}
@media(min-width:600px){.sty-stage{border-radius:22px;box-shadow:0 30px 80px rgba(0,0,0,.5)}}
.sty-num,.sty-card .v,.sty-row .v,.sty-it em,.sty-top small{font-family:"Montserrat",system-ui,sans-serif}
/* 進度條與頁首（開場那一則不顯示） */
.sty-bars{position:absolute;top:10px;left:12px;right:12px;display:flex;gap:4px;z-index:6;transition:opacity .3s}
.sty-bars i{flex:1;height:3px;border-radius:3px;background:rgba(255,255,255,.3);overflow:hidden}
.sty-bars b{display:block;height:100%;width:0;background:#fff;border-radius:3px}
.sty-top{position:absolute;top:22px;left:16px;right:8px;display:flex;align-items:center;gap:10px;z-index:7;transition:opacity .3s}
.sty-top img{height:22px;width:auto;display:block}
.sty-top .lt{display:none}
.sty-top small{font-size:11.5px;opacity:.8;font-weight:600}
.sty-x{margin-left:auto;border:0;background:none;color:inherit;font-size:28px;line-height:1;padding:6px 10px;cursor:pointer}
.sty-intro .sty-bars,.sty-intro .sty-top{opacity:0;pointer-events:none}
.sty-light{color:#12233B}
.sty-light .sty-bars i{background:rgba(18,35,59,.18)}.sty-light .sty-bars b{background:#E67143}
.sty-light .sty-top .dk{display:none}.sty-light .sty-top .lt{display:block}
/* 每一則 */
.sty-s{position:absolute;inset:0;padding:88px 26px 40px;display:flex;flex-direction:column;opacity:0;visibility:hidden;
  transform:translateX(26px);transition:opacity .35s ease,transform .45s cubic-bezier(.2,.9,.3,1),visibility 0s .35s;overflow:hidden}
.sty-s.on{opacity:1;visibility:visible;transform:none;transition:opacity .35s ease,transform .45s cubic-bezier(.2,.9,.3,1)}
.sty-s.out{transform:translateX(-26px)}
.sty-s.s1,.sty-s.s2,.sty-s.s3,.sty-s.s4{justify-content:center;padding-bottom:110px}
/* 品牌底色：藏青與日出橘之間變化 */
.sty-s.s0{background:#12233B;justify-content:center;align-items:center;padding:0}
.sty-s.s1{background:linear-gradient(170deg,#12233B 0%,#1a3358 100%)}
.sty-s.s2{background:linear-gradient(165deg,#E67143 0%,#d65f33 60%,#b8481f 100%)}
.sty-s.s3{background:linear-gradient(180deg,#0b1626 0%,#12233B 100%)}
.sty-s.s4{background:linear-gradient(170deg,#12233B 0%,#3a2c3a 62%,#a24f30 100%)}
.sty-s.s5{background:#f7f2ea;color:#12233B}
/* 品牌圖形：點陣底紋、日出半圓、走勢線 */
.sty-dots{position:absolute;inset:0;pointer-events:none;opacity:.10;
  background-image:radial-gradient(currentColor 1px,transparent 1.2px);background-size:18px 18px}
.sty-sun{position:absolute;left:50%;bottom:-150px;width:300px;height:300px;margin-left:-150px;border-radius:50%;pointer-events:none;
  background:#E67143;opacity:.9;transform:translateY(80px)}
.sty-s.on .sty-sun{animation:stysun 1.4s cubic-bezier(.2,.9,.3,1) .1s forwards}
@keyframes stysun{to{transform:translateY(0)}}
.s2 .sty-sun{background:#12233B;opacity:.9}
.s3 .sty-sun,.s1 .sty-sun{opacity:.85}
.s5 .sty-sun{width:220px;height:220px;margin-left:-110px;bottom:-130px}
.sty-hz{position:absolute;left:0;right:0;bottom:0;height:2px;background:currentColor;opacity:.25;pointer-events:none}
.sty-ln{position:absolute;left:0;right:0;bottom:86px;height:90px;pointer-events:none;opacity:.55}
.sty-ln path{fill:none;stroke:#E67143;stroke-width:3;stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:900;stroke-dashoffset:900}
.s2 .sty-ln path{stroke:#fff}
.sty-s.on .sty-ln path{animation:styln 2.2s ease-out .3s forwards}
@keyframes styln{to{stroke-dashoffset:0}}
/* 換頁時一道橘色細條掃過 */
.sty-sweep{position:absolute;top:0;bottom:0;left:-30%;width:22%;z-index:8;pointer-events:none;opacity:0;
  background:linear-gradient(90deg,transparent,rgba(230,113,67,.9),transparent);transform:skewX(-12deg)}
.sty-sweep.go{animation:stysweep .55s ease-out}
@keyframes stysweep{0%{opacity:1;left:-30%}100%{opacity:1;left:110%}}
/* 開場：日出＋LOGO 由左揭露 */
.sty-intro-box{position:relative;z-index:2;text-align:center;width:100%}
.sty-intro-box img{width:78%;max-width:340px;height:auto;clip-path:inset(0 100% 0 0)}
.sty-s0.on .sty-intro-box img,.s0.on .sty-intro-box img{animation:styreveal .8s cubic-bezier(.6,0,.2,1) .15s forwards}
@keyframes styreveal{to{clip-path:inset(0 0 0 0)}}
.sty-intro-d{margin-top:18px;font-size:15px;font-weight:800;letter-spacing:.12em;opacity:0}
.s0.on .sty-intro-d{animation:stypop .5s ease .7s both}
.s0 .sty-sun{width:420px;height:420px;margin-left:-210px;bottom:-250px}
/* 文字 */
.sty-k{display:inline-flex;align-self:flex-start;align-items:baseline;gap:8px;font-size:14px;font-weight:800;letter-spacing:.06em;position:relative;z-index:2}
.sty-k b{font-family:"Montserrat",system-ui,sans-serif;font-size:22px;font-weight:800;color:#E67143;letter-spacing:0}
.s2 .sty-k b{color:#12233B}
.sty-greet{margin:14px 0 0;font-size:17px;font-weight:700;opacity:.8;position:relative;z-index:2}
.sty-h{font-size:30px;font-weight:900;line-height:1.28;margin:14px 0 0;letter-spacing:.01em;position:relative;z-index:2}
.sty-p{font-size:16px;line-height:1.7;opacity:.92;margin:14px 0 0;position:relative;z-index:2}
.sty-a{opacity:0}
.sty-s.on .sty-a{animation:stypop .6s cubic-bezier(.2,1.5,.4,1) both;animation-delay:var(--d,0s)}
@keyframes stypop{from{opacity:0;transform:translateY(22px) scale(.94)}to{opacity:1;transform:none}}
/* 1 你的指標 */
.sty-cards{display:flex;flex-direction:column;gap:14px;margin-top:20px;position:relative;z-index:2}
.sty-card{background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.18);border-left:4px solid #E67143;border-radius:16px;padding:16px 20px}
.sty-card .l{font-size:14px;font-weight:700;opacity:.85}
.sty-card .v{font-size:44px;font-weight:800;line-height:1.15;margin-top:4px;font-variant-numeric:tabular-nums;letter-spacing:-.01em}
.sty-card .c{display:inline-flex;align-items:center;gap:6px;margin-top:6px;font-size:16px;font-weight:800;border-radius:999px;padding:3px 12px;background:rgba(255,255,255,.12)}
.sty-card .c.up{color:#ffb3b3}.sty-card .c.dn{color:#9df0b8}
.sty-arr{display:inline-block;animation:stybob 1s ease-in-out infinite}
.sty-card .c.dn .sty-arr{animation-name:stybobd}
@keyframes stybob{50%{transform:translateY(-4px)}}@keyframes stybobd{50%{transform:translateY(4px)}}
/* 2 今日主軸：藏青螢光筆 */
.sty-mark{background:linear-gradient(transparent 60%,rgba(18,35,59,.45) 60%) no-repeat;background-size:0 100%}
.sty-s.on .sty-mark{animation:stymark 1.1s .5s ease forwards}
@keyframes stymark{to{background-size:100% 100%}}
/* 3 對利率：橘色儀表 */
.sty-dial{width:170px;height:170px;border-radius:50%;margin:26px auto 6px;display:flex;align-items:center;justify-content:center;
  background:radial-gradient(circle,rgba(230,113,67,.28),rgba(230,113,67,.05));border:3px solid #E67143;position:relative;z-index:2}
.sty-dial::after{content:"";position:absolute;inset:-12px;border-radius:50%;border:2px dashed rgba(230,113,67,.55);animation:styspin 14s linear infinite}
.sty-big{font-size:88px;font-weight:900;line-height:1;color:#fff}
.sty-s.on .sty-big.up{animation:styup 1.4s cubic-bezier(.2,1.4,.4,1) .3s both}
.sty-s.on .sty-big.down{animation:stydn 1.4s cubic-bezier(.2,1.4,.4,1) .3s both}
.sty-s.on .sty-big.flat,.sty-s.on .sty-big.unclear{animation:stywig 1.6s ease-in-out .3s both}
@keyframes styup{from{opacity:0;transform:translateY(60px)}to{opacity:1;transform:none}}
@keyframes stydn{from{opacity:0;transform:translateY(-60px)}to{opacity:1;transform:none}}
@keyframes stywig{0%{opacity:0;transform:rotate(-12deg)}40%{opacity:1;transform:rotate(10deg)}70%{transform:rotate(-6deg)}100%{transform:none}}
.sty-tag{display:block;text-align:center;font-size:22px;font-weight:900;margin-top:10px;color:#ffb38f;position:relative;z-index:2}
/* 4 最新數據 */
.sty-row{margin-top:16px;background:rgba(255,255,255,.09);border:1px solid rgba(255,255,255,.16);border-radius:16px;padding:14px 18px;position:relative;z-index:2}
.sty-row .l{font-size:14px;font-weight:700;opacity:.85}
.sty-row .v{font-size:40px;font-weight:800;line-height:1.2;font-variant-numeric:tabular-nums}
.sty-pills{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px}
.sty-pills span{font-size:13px;font-weight:700;background:rgba(255,255,255,.14);border-radius:999px;padding:3px 10px}
.sty-stamp{position:absolute;right:14px;top:14px;font-size:14px;font-weight:900;color:#fff;background:#E67143;border-radius:8px;
  padding:4px 9px;transform:rotate(-6deg);box-shadow:0 4px 12px rgba(0,0,0,.25)}
.sty-s.on .sty-stamp{animation:stystamp .5s cubic-bezier(.2,1.6,.4,1) 1.1s both}
@keyframes stystamp{from{opacity:0;transform:rotate(-30deg) scale(2.2)}to{opacity:1;transform:rotate(-6deg) scale(1)}}
/* 5 今明兩天（米白紙底＋藏青字） */
.sty-day{margin-top:14px;position:relative;z-index:2}
.sty-day h4{margin:0 0 4px;font-size:15px;font-weight:900;display:flex;align-items:center;gap:8px}
.sty-day h4 small{font-size:12px;font-weight:700;opacity:.6}
.sty-it{display:flex;align-items:center;gap:10px;padding:8px 12px;margin-top:6px;background:#fff;border:1px solid rgba(18,35,59,.10);border-radius:12px;font-size:15px;font-weight:700}
.sty-it em{font-style:normal;margin-left:auto;font-size:13px;opacity:.75;font-variant-numeric:tabular-nums}
.sty-it small{display:block;font-size:12px;font-weight:500;opacity:.7}
.sty-ic{flex:none;width:12px;height:12px}
.sty-ic.d{border-radius:50%;background:#E67143}.sty-ic.d.lo{background:none;border:2px solid #E67143;box-sizing:border-box}
.sty-ic.s{background:#1f5fae;border-radius:2px}
.sty-ic.p{background:#077c07;clip-path:polygon(50% 0,100% 100%,0 100%)}
.sty-ic.h{width:auto;height:auto;font-size:10px;font-weight:900;font-style:normal;border:1.5px solid #12233B;border-radius:4px;padding:0 3px;line-height:1.4}
.sty-none{margin-top:6px;font-size:14px;opacity:.75}
.sty-it.past{opacity:.5}.sty-it.past em{opacity:1;font-family:inherit;font-weight:700}
.sty-live{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.sty-x:focus-visible,.sty-cta:focus-visible{outline:3px solid #E67143;outline-offset:2px}
.sty-end{margin-top:auto;display:flex;flex-direction:column;align-items:center;gap:12px;position:relative;z-index:3;padding-bottom:6px}
.sty-s.on .sty-end{z-index:5}   /* 蓋過左右點按區，「進入網站」「存成今日市場圖」才按得到 */
.sty-end img{width:62%;max-width:250px;height:auto}
.sty-cta{border:0;border-radius:999px;background:#E67143;color:#fff;font:inherit;font-size:16px;font-weight:900;
  padding:12px 34px;cursor:pointer;box-shadow:0 10px 24px rgba(230,113,67,.35);position:relative;z-index:7}
.sty-s.on .sty-cta{animation:stypop .6s cubic-bezier(.2,1.5,.4,1) 1.2s both,stypulse 1.6s ease-in-out 2s infinite}
@keyframes stypulse{50%{transform:scale(1.05)}}
.sty-foot{font-size:12px;opacity:.65}
.sty-hint{position:absolute;left:0;right:0;bottom:24px;text-align:center;font-size:12.5px;opacity:.75;z-index:2}
.sty-s.on .sty-hint{animation:styblink 2.4s ease-in-out 1.2s infinite}
@keyframes styblink{50%{opacity:.35}}
.sty-tap{position:absolute;top:70px;bottom:0;z-index:4}.sty-prev{left:0;width:30%}.sty-next{right:0;width:70%}
.sty-paused .sty-s.on .sty-a,.sty-paused .sty-s.on .sty-ln path,.sty-paused .sty-s.on .sty-sun{animation-play-state:paused}
@media(prefers-reduced-motion:reduce){.sty-a,.sty-s,.sty-sun,.sty-ln path,.sty-intro-box img{animation:none!important;transition:none!important;opacity:1;clip-path:none!important;stroke-dashoffset:0!important;transform:none!important}}
"""

JS = r"""
(function(){
var D; try{ D = JSON.parse(document.getElementById("story-data").textContent); }catch(e){ return; }
var btn = document.querySelector(".fs-story-btn");
function lsg(k){ try{ return localStorage.getItem(k); }catch(e){ return null; } }
function lss(k, v){ try{ localStorage.setItem(k, v); }catch(e){} }
function esc(s){ return String(s == null ? "" : s).replace(/[&<>"]/g, function(c){ return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]; }); }
function tpeDate(ms){ try{ return new Intl.DateTimeFormat("en-CA", {timeZone: "Asia/Taipei"}).format(new Date(ms)); }catch(e){ return D.day; } }
// 每天播一次：比對「這份內容的版本日期」和讀者上次看過的版本日期，不一樣才播。
// 不看讀者打開的時間——GitHub 排程常延遲，早上那次不一定 05:03 準時上線。
// 版本日期由網站產生時決定（台灣時間往前推 5 小時取日期）。
function tpeDay(){ return D.edition || D.day; }
function addDay(iso, n){ var p = iso.split("-").map(Number), d = new Date(Date.UTC(p[0], p[1] - 1, p[2] + n)); return d.toISOString().slice(0, 10); }
var LINE = '<svg class="sty-ln" viewBox="0 0 430 90" preserveAspectRatio="none" aria-hidden="true"><path d="M0 72 L48 64 L92 70 L138 48 L182 56 L226 34 L270 42 L316 22 L360 30 L430 8"/></svg>';
function deco(sun){ return '<i class="sty-dots"></i>' + LINE + (sun === false ? '' : '<i class="sty-sun"></i>') + '<i class="sty-hz"></i>'; }
function kick(n, t, d){ return '<span class="sty-k sty-a" style="--d:' + (d || 0) + 's"><b>0' + n + '</b>' + t + '</span>'; }
function wd(iso){ var p = String(iso).split("-").map(Number), w = new Date(Date.UTC(p[0], p[1] - 1, p[2])).getUTCDay(); return p[1] + "/" + p[2] + "（" + "日一二三四五六".charAt(w) + "）"; }
function chips(){
  var out = [];
  Array.prototype.forEach.call(document.querySelectorAll(".fs-chips [data-chip]:not(.fs-off)"), function(c){
    if(out.length >= 2) return;
    var l = c.querySelector(".fs-nm span"), b = c.querySelector("b"), i = c.querySelector("i");
    if(!b) return;
    var ct = i ? i.textContent.trim() : "", m = ct.replace(/,/g, "").match(/[-+]?\d+(\.\d+)?/), d = m ? parseFloat(m[0]) : 0;
    if(/升/.test(ct)) d = -Math.abs(d); else if(/貶/.test(ct)) d = Math.abs(d);   // 台幣升值＝美元兌台幣往下
    var v = parseFloat(c.getAttribute("data-v")), pv = parseFloat(c.getAttribute("data-pv"));
    // 變動大小：利率看 bp（≥5 算大），其他看百分比（≥1% 算大）
    var bp = /bp/.test(ct), size = bp ? Math.abs(d) / 5 : (isFinite(v) && isFinite(pv) && pv ? Math.abs(v / pv - 1) * 100 : 0);
    out.push({l: l ? l.textContent : "", v: b.textContent.trim(), c: ct, d: d, big: size >= 1, size: size,
              dir: i ? (i.classList.contains("up") ? "up" : i.classList.contains("dn") ? "dn" : "") : ""});
  });
  return out;
}
// 第一則的問候（依台灣時間）與一句話（依兩個指標當天的漲跌自動寫）
function greet(){ var h = 9; try{ h = parseInt(new Intl.DateTimeFormat("en-US", {timeZone: "Asia/Taipei", hour: "numeric", hourCycle: "h23"}).format(new Date()), 10); }catch(e){}
  return h >= 5 && h < 11 ? "早安" : h >= 11 && h < 18 ? "午安" : "晚安"; }
function sayChips(ch){
  ch = ch.filter(function(x){ return x.v && x.v !== "—"; });   // 這次抓不到的指標不拿來寫句子
  if(!ch.length) return "挑兩個你想天天看的數字";
  var s = function(x){ return x.d > 0 ? 1 : x.d < 0 ? -1 : 0; };
  if(ch.length === 1) return ch[0].l + (s(ch[0]) > 0 ? "往上走" : s(ch[0]) < 0 ? "在往下" : "今天沒什麼動");
  var a = ch[0], b = ch[1], sa = s(a), sb = s(b);
  if(!sa && !sb) return "今天很安靜";
  if(a.big !== b.big) return (a.big ? a.l : b.l) + "今天動得最多";
  if(a.big && b.big && sa === sb) return sa > 0 ? "兩個都大幅往上" : "兩個都大幅往下";
  if(sa && sb && sa === sb) return sa > 0 ? "兩個都往上走" : "兩個都在往下";
  if(sa && sb) return "一漲一跌，各走各的";
  var mv = sa ? a : b;
  return mv.l + (s(mv) > 0 ? "往上" : "往下") + "，另一個沒什麼動";
}
function slides(){
  var S = [], ch = chips(), DURS = [];
  var push = function(h, d){ S.push(h); DURS.push(d); };
  // 0 開場：日出＋LOGO（MACRO GG 明天過後，帶你看總經）
  push('<div class="sty-s s0"><i class="sty-dots"></i><i class="sty-sun"></i><div class="sty-intro-box">'
    + '<img src="/brand/logo-full-dark.svg" alt="MACRO GG 明天過後，帶你看總經">'
    + '<div class="sty-intro-d">今日快報・' + esc(wd(tpeDate(Date.now()))) + '</div></div></div>', 1400);
  // 1 你的指標
  push('<div class="sty-s s1">' + deco() + kick(1, "你的指標")
    + '<p class="sty-greet sty-a" style="--d:.05s">' + greet() + '</p>'
    + '<h2 class="sty-h sty-a" style="--d:.15s;margin-top:4px">' + esc(sayChips(ch)) + '</h2><div class="sty-cards">'
    + (ch.length ? ch.map(function(x, k){ return '<div class="sty-card sty-a" style="--d:' + (.25 + k * .2) + 's"><div class="l">' + esc(x.l) + '</div>'
      + '<div class="v" data-count="' + esc(x.v) + '">' + esc(x.v) + '</div>'
      + (x.c ? '<span class="c ' + x.dir + '"><span class="sty-arr">' + (x.dir === "up" ? "▲" : x.dir === "dn" ? "▼" : "•") + '</span>' + esc(x.c) + '</span>' : '') + '</div>'; }).join("")
      : '<p class="sty-p sty-a">按「選擇指標」挑你想天天看的數字。</p>') + '</div><div class="sty-hint">點右側看下一則　·　按住暫停　·　往下滑關閉</div></div>', 5500);
  // 2 今日主軸（橘底）；主軸暫缺就整則跳過
  if(D.headline) push('<div class="sty-s s2">' + deco() + kick(2, "今日主軸")
    + '<h2 class="sty-h sty-a" style="--d:.15s;font-size:31px"><span class="sty-mark">' + esc(D.headline || "今天的主軸還在整理中") + '</span></h2>'
    + (D.lead ? '<p class="sty-p sty-a" style="--d:.9s">' + esc(D.lead) + '</p>' : '') + '</div>', 6000);
  // 3 對利率
  var dir = D.rate_dir || "flat";
  var big = {up: "↑", down: "↓", flat: "→", unclear: "?"}[dir] || "→";
  var tag = {up: "偏向推升利率", down: "偏向壓低利率", flat: "利率大致持平", unclear: "方向還不明確"}[dir] || "";
  if(D.rate) push('<div class="sty-s s3">' + deco(false) + kick(3, "對利率")
    + '<div class="sty-dial sty-a" style="--d:.1s"><span class="sty-big ' + dir + '">' + big + '</span></div>'
    + '<span class="sty-tag sty-a" style="--d:.6s">' + tag + '</span>'
    + '<p class="sty-p sty-a" style="--d:.9s">' + esc(D.rate) + '</p></div>', 6000);
  // 4 最新數據
  // 48 小時內公布的第一筆（建置端已排好優先順序；這裡用打開當下的時間再篩一次）
  var L = (D.rels || []).filter(function(x){ var t = Date.parse(x.at || ""), a = Date.now() - t; return isFinite(t) && a >= 0 && a <= 48 * 3600e3; })[0] || null;
  push('<div class="sty-s s4">' + deco() + kick(4, "最新數據")
    + (L ? '<h2 class="sty-h sty-a" style="--d:.1s">' + esc(L.name) + '</h2>'
      + (L.date ? '<p class="sty-p sty-a" style="--d:.2s;margin-top:4px">' + esc(L.date) + ' 公布</p>' : '')
      + L.rows.map(function(r, k){ return '<div class="sty-row sty-a" style="--d:' + (.35 + k * .25) + 's"><div class="l">' + esc(r.label) + '</div>'
        + '<div class="v" data-count="' + esc(r.actual) + '">' + esc(r.actual) + '</div>'
        + ((r.forecast || r.previous) ? '<div class="sty-pills">' + (r.forecast ? '<span>預估 ' + esc(r.forecast) + '</span>' : '') + (r.previous ? '<span>前值 ' + esc(r.previous) + '</span>' : '') + '</div>' : '')
        + (r.vs ? '<span class="sty-stamp">' + esc(r.vs) + '</span>' : '') + '</div>'; }).join("")
      : '<p class="sty-p sty-a">最近兩天沒有新公布的重要數據。</p>') + '</div>', 6000);
  // 5 今明兩天＋品牌收尾（米白紙底）
  var icon = function(x){ return x.k === "h" ? '<i class="sty-ic h">休</i>' : '<i class="sty-ic ' + x.k + (x.k === "d" && !x.hi ? " lo" : "") + '"></i>'; };
  // 今天／明天依「打開的這一刻」的台灣日期決定；時間已過的變灰、標已公布／已結束、排到後面
  var today = tpeDate(Date.now()), nowMs = Date.now();
  var dayBox = function(k, title){
    var day = addDay(today, k);
    var it = (D.up || []).filter(function(x){ return x.date === day; }).map(function(x){
      var ms = x.at ? Date.parse(x.at) : NaN; return {x: x, past: isFinite(ms) && ms < nowMs}; });
    var rk = function(x){ return x.k === "h" ? 0 : x.at ? 1 : 2; };   // 休市（整天）→ 有時間的依時間 → 時間未定
    it.sort(function(a, b){ return ((a.past ? 1 : 0) - (b.past ? 1 : 0)) || (rk(a.x) - rk(b.x)) || String(a.x.at || "").localeCompare(String(b.x.at || "")); });
    var show = it.slice(0, 4), more = it.length - show.length;
    return '<div class="sty-day sty-a" style="--d:' + (.2 + k * .35) + 's"><h4>' + title + '<small>' + (it.length ? it.length + ' 項' : '') + '</small></h4>'
      + (show.length ? show.map(function(o){ var x = o.x; return '<div class="sty-it' + (o.past ? ' past' : '') + '">' + icon(x) + '<span>' + esc(x.name) + (x.sub ? '<small>' + esc(x.sub) + '</small>' : '') + '</span>'
          + (o.past ? '<em>' + (x.k === "d" ? '已公布' : '已結束') + '</em>' : (x.t ? '<em>' + esc(x.t) + '</em>' : '')) + '</div>'; }).join("")
        + (more > 0 ? '<div class="sty-none">＋' + more + ' 項，進網站看</div>' : '')
        : '<div class="sty-none">沒有排定的重要事項，輕鬆一下。</div>') + '</div>';
  };
  push('<div class="sty-s s5"><i class="sty-dots"></i>' + kick(5, "今明兩天") + dayBox(0, "今天") + dayBox(1, "明天")
    + '<div class="sty-end"><img class="sty-a" style="--d:1s" src="/brand/logo-full.svg" alt="MACRO GG 明天過後，帶你看總經">'
    + '<button type="button" class="sty-cta">進入網站</button><div class="sty-foot sty-a" style="--d:1.4s">● 數據　■ 發債　▲ 官員談話　休 休市</div>'
    + '</div></div>', 8000);
  DUR = DURS;
  return S;
}
var DUR = [];
var root, stage, cur = -1, t0 = 0, acc = 0, raf = 0, paused = false, bars, sweep, live, back = null;
function countUp(el){
  var raw = el.getAttribute("data-count") || "", m = raw.match(/[-+]?\d[\d,]*(\.\d+)?/);
  if(!m) return; var s = m[0], n = parseFloat(s.replace(/,/g, "")), dec = (s.split(".")[1] || "").length, plus = s.charAt(0) === "+";
  var pre = raw.slice(0, m.index), post = raw.slice(m.index + s.length), t1 = performance.now();
  (function step(now){ var k = Math.min(1, (now - t1) / 800), e = 1 - Math.pow(1 - k, 3), v = n * e;
    var txt = Math.abs(v).toFixed(dec).replace(/\B(?=(\d{3})+(?!\d))/g, s.indexOf(",") >= 0 ? "," : "");
    el.textContent = pre + (v < 0 ? "-" : (plus ? "+" : "")) + txt + post; if(k < 1) requestAnimationFrame(step); else el.textContent = raw; })(t1);
}
function go(i){
  var ss = root.querySelectorAll(".sty-s");
  if(i < 0) i = cur <= 1 ? 1 : 0;
  if(i >= ss.length){ close(); return; }
  if(i === 0 && cur > 0) i = 1;
  Array.prototype.forEach.call(ss, function(s, k){ s.classList.toggle("on", k === i); s.classList.toggle("out", k < i); s.setAttribute("aria-hidden", k === i ? "false" : "true"); });
  if(live){ var h = ss[i].querySelector(".sty-h,.sty-k,.sty-tag"); live.textContent = (i ? "第 " + i + " 則，共 " + (ss.length - 1) + " 則：" : "") + (h ? h.textContent : "今日快報"); }
  Array.prototype.forEach.call(bars, function(b, k){ b.style.width = k < i - 1 ? "100%" : "0"; });
  stage.classList.toggle("sty-intro", i === 0); stage.classList.toggle("sty-light", i === ss.length - 1);
  if(cur >= 0 && i !== cur && i > 1){ sweep.classList.remove("go"); void sweep.offsetWidth; sweep.classList.add("go"); }
  cur = i; acc = 0; t0 = performance.now();
  setTimeout(function(){ Array.prototype.forEach.call(ss[i].querySelectorAll("[data-count]"), countUp); }, 350);
}
function tick(now){
  if(!root || root.hidden) return;
  if(!paused){ var el = acc + (now - t0), d = DUR[cur] || 6000; if(cur > 0) bars[cur - 1].style.width = Math.min(100, el / d * 100) + "%"; if(el >= d){ go(cur + 1); } }
  raf = requestAnimationFrame(tick);
}
function pause(p){ if(p === paused) return; if(p){ acc += performance.now() - t0; } else { t0 = performance.now(); } paused = p; root.classList.toggle("sty-paused", p); }
function open(){
  if(!root){
    root = document.createElement("div"); root.className = "sty"; root.setAttribute("role", "dialog"); root.setAttribute("aria-modal", "true"); root.setAttribute("aria-label", "今日快報");
    var S = slides();
    root.innerHTML = '<div class="sty-stage"><div class="sty-bars">' + S.slice(1).map(function(){ return "<i><b></b></i>"; }).join("") + '</div>'
      + '<div class="sty-top"><img class="dk" src="/brand/logo-compact-dark.svg" alt="MACRO GG"><img class="lt" src="/brand/logo-compact.svg" alt="">'
      + '<small>今日快報・' + esc(D.stamp) + '</small><button type="button" class="sty-x" aria-label="關閉">×</button></div>'
      + S.join("") + '<i class="sty-sweep"></i><div class="sty-tap sty-prev" aria-hidden="true"></div><div class="sty-tap sty-next" aria-hidden="true"></div>'
      + '<p class="sty-live" aria-live="polite"></p></div>';
    document.body.appendChild(root); bars = root.querySelectorAll(".sty-bars b"); stage = root.querySelector(".sty-stage"); sweep = root.querySelector(".sty-sweep"); live = root.querySelector(".sty-live");
    var downT = 0, sx = 0, sy = 0, held = null;
    root.querySelector(".sty-x").addEventListener("click", close);
    root.addEventListener("click", function(e){ if(e.target === root) close(); if(e.target.closest(".sty-cta")) close(); });
    stage.addEventListener("pointerdown", function(e){ if(paperOn || e.target.closest(".sty-x,.sty-cta,.sty-pp")) return; downT = performance.now(); sx = e.clientX; sy = e.clientY; held = setTimeout(function(){ pause(true); }, 220); });
    stage.addEventListener("pointerup", function(e){ if(!downT || paperOn) return; clearTimeout(held); var dt = performance.now() - downT, dy = e.clientY - sy, dx = e.clientX - sx; downT = 0;
      if(dy > 90 && Math.abs(dx) < 80){ close(); return; }
      if(paused){ pause(false); if(dt > 220) return; }
      if(Math.abs(dx) > 60){ go(cur + (dx < 0 ? 1 : -1)); return; }
      if(e.target.closest(".sty-prev")) go(cur - 1); else if(e.target.closest(".sty-next")) go(cur + 1); });
    stage.addEventListener("pointercancel", function(){ clearTimeout(held); downT = 0; pause(false); });
  }
  back = document.activeElement;
  paperOn = false; var oldPP = stage.querySelector(".sty-pp"); if(oldPP) oldPP.remove();
  setTimeout(prepShot, 1500);   // 離開時要跳出的今日快報圖，先在背景畫好
  root.hidden = false; document.documentElement.style.overflow = "hidden"; paused = false; root.classList.remove("sty-paused");
  try{ root.querySelector(".sty-x").focus({preventScroll: true}); }catch(e){}
  cur = -1; go(0); cancelAnimationFrame(raf); raf = requestAnimationFrame(tick);
  lss("mgStoryDay", tpeDay()); if(btn) btn.classList.add("seen");
  document.addEventListener("keydown", key);
}
// 今日快報圖（2026-10）：不論按 ✕、往下滑、Esc、點外面、「進入網站」或播完，離開快報時
// 先讓一陣風把今天的圖吹進來，落定後下方滑出「下載圖片／分享／進入網站」。再按 ✕ 才真的離開。
// 圖在打開快報 1.5 秒後就開始在背景畫（分享必須在點按的當下呼叫，Safari 才允許）。
var shot = null, shotP = null, shotURL = "", paperOn = false;
function shotName(){ return "MACROGG-" + (D.edition || D.day || "").replace(/-/g, "") + ".png"; }
function prepShot(){ if(shotP || typeof mgShot !== "function") return shotP;
  shotP = mgShot(D).then(function(b){ shot = b; try{ shotURL = URL.createObjectURL(b); }catch(e){} return b; }, function(){ shotP = null; return null; }); return shotP; }
function finish(){ if(!root) return; paperOn = false; root.hidden = true; document.documentElement.style.overflow = ""; cancelAnimationFrame(raf); document.removeEventListener("keydown", key);
  if(back && back.focus) try{ back.focus({preventScroll: true}); }catch(e){} }
function close(){ if(!root || root.hidden) return;
  if(paperOn){ finish(); return; }
  var p = shot ? Promise.resolve(shot) : prepShot();
  if(!p){ finish(); return; }
  paperOn = true; cancelAnimationFrame(raf); pause(true);
  var pp = document.createElement("div"); pp.className = "sty-pp"; pp.innerHTML = '<div class="sty-pp-dim"></div>'; stage.appendChild(pp);
  var guard = setTimeout(function(){ if(paperOn && !shot) finish(); }, 6000);
  p.then(function(b){ clearTimeout(guard); if(!paperOn) return; if(!b || !shotURL){ finish(); return; } showPaper(pp); });
}
function ppToast(t){ var el = stage.querySelector(".sty-pp-toast"); if(!el) return; el.textContent = t; el.classList.remove("on"); void el.offsetWidth; el.classList.add("on"); }
function shotFile(){ try{ return new File([shot], shotName(), {type: "image/png"}); }catch(e){ return null; } }
function canShareFile(f){ try{ return !!(f && navigator.canShare && navigator.canShare({files: [f]})); }catch(e){ return false; } }
function showPaper(pp){
  var reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  var sw = stage.clientWidth, sh = stage.clientHeight, ph = Math.min(sh - 56 - 214, (sw - 56) * 16 / 9), pw = ph * 9 / 16, N = 10, w = pw / N;
  var dd = String(D.edition || D.day || "").split("-"), md = dd.length === 3 ? parseInt(dd[1], 10) + "/" + parseInt(dd[2], 10) : "";
  pp.style.setProperty("--pw", pw + "px"); pp.style.setProperty("--ph", ph + "px");
  pp.innerHTML = '<div class="sty-pp-dim"></div><div class="sty-pp-wind" aria-hidden="true"></div>'
    + '<div class="sty-pp-st" aria-hidden="true"><div class="sty-pp-fly"></div></div>'
    + '<img class="sty-pp-img" alt="今日快報・' + esc(md) + '" src="' + shotURL + '">'
    + '<button type="button" class="sty-pp-x" aria-label="關閉">×</button>'
    + '<div class="sty-pp-sheet"><i class="sty-pp-grab"></i><h4>今日快報・' + esc(md) + '</h4><p>1080×1920，可直接發 IG 限動</p>'
    + '<div class="sty-pp-btns"><button type="button" class="sty-pp-dl">下載圖片</button><button type="button" class="sty-pp-share">分享</button></div>'
    + '<button type="button" class="sty-pp-go">進入網站 →</button></div><div class="sty-pp-toast" role="status" aria-live="polite"></div>';
  // 圖切成 10 條並排（不巢狀：巢狀 3D 在部分瀏覽器會破洞），每一條的角度＝前面各個「關節」角度
  // 相加，位置一路接上去——疊起來就是被風吹得翻捲的紙；1.3 秒內擺動衰減到攤平。
  var fly = pp.querySelector(".sty-pp-fly"), strips = [];
  for(var i = 0; i < N; i++){ var d = document.createElement("div"); d.className = "sty-pp-s";
    d.style.cssText = "width:" + (w + .5) + "px;background-image:url(" + shotURL + ");background-position:" + (-i * w) + "px 0";
    fly.appendChild(d); strips.push(d); }
  function damp(t){ return t < 0 ? 1.4 : t > 1.3 ? 0 : 1.4 * Math.cos(2 * Math.PI * t / .36) * Math.exp(-2.6 * t) * (1 - t / 1.3); }
  function flap(t){ var th = 0, X = 0, Z = 0;
    for(var k = 0; k < N; k++){ if(k){ X += w * Math.cos(th); Z -= w * Math.sin(th); th += (6 + k * .9) * damp(t - k * .03) * Math.PI / 180; }
      strips[k].style.transform = "translate3d(" + X.toFixed(2) + "px,0," + Z.toFixed(2) + "px) rotateY(" + th.toFixed(4) + "rad)"; } }
  if(!reduce){ var t0f = performance.now(); flap(0);
    (function step(now){ var t = (now - t0f) / 1000; flap(t); if(t < 1.35 && paperOn) requestAnimationFrame(step); })(t0f); }
  var wind = pp.querySelector(".sty-pp-wind");
  [[.22, 0, 150], [.36, .05, 220], [.5, .15, 120], [.62, .1, 260], [.74, .25, 180], [.3, .4, 200], [.56, .55, 140], [.44, .7, 230]].forEach(function(r){
    var l = document.createElement("i"); l.style.cssText = "top:" + (r[0] * 100) + "%;width:" + r[2] + "px;animation-delay:" + r[1] + "s"; wind.appendChild(l); });
  if(!canShareFile(shotFile())) pp.querySelector(".sty-pp-share").hidden = true;
  pp.classList.add(reduce ? "still" : "go");
  pp.addEventListener("click", function(e){
    if(e.target.closest(".sty-pp-x,.sty-pp-go")){ finish(); return; }
    if(e.target.closest(".sty-pp-share")){ var f = shotFile(); if(canShareFile(f)) navigator.share({files: [f], title: "MACRO GG 今日快報"}).catch(function(){}); return; }
    if(e.target.closest(".sty-pp-dl")){
      var f2 = shotFile(), ios = /iP(hone|ad|od)/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
      // iPhone：分享選單裡的「儲存影像」才會進相簿；其他裝置直接下載檔案
      if(ios){ if(canShareFile(f2)) navigator.share({files: [f2]}).catch(function(){}); else ppToast("長按圖片即可儲存"); return; }
      var a = document.createElement("a"); a.href = shotURL; a.download = shotName(); document.body.appendChild(a); a.click(); a.remove(); ppToast("已下載 " + shotName()); }
  });
  setTimeout(function(){ try{ pp.querySelector(".sty-pp-dl").focus({preventScroll: true}); }catch(e){} }, reduce ? 300 : 1700);
}
function key(e){
  // Tab 只在快報裡循環（關閉鈕、最後一則的「進入網站」）
  if(e.key === "Tab"){ var f = paperOn ? Array.prototype.filter.call(stage.querySelectorAll(".sty-pp button"), function(x){ return !x.hidden; })
      : [root.querySelector(".sty-x")], c = paperOn ? null : root.querySelector(".sty-s.on .sty-cta"); if(c) f.push(c); if(!f.length) return;
    var k = f.indexOf(document.activeElement); e.preventDefault(); f[(k + (e.shiftKey ? f.length - 1 : 1)) % f.length].focus(); return; }
  if(e.key === "Escape") close(); else if(paperOn) return; else if(e.key === "ArrowRight") go(cur + 1); else if(e.key === "ArrowLeft") go(cur - 1); else if(e.key === " "){ e.preventDefault(); pause(!paused); } }
document.addEventListener("visibilitychange", function(){ if(root && !root.hidden && !paperOn) pause(document.hidden); });
if(btn){ btn.hidden = false; if(lsg("mgStoryDay") === tpeDay()) btn.classList.add("seen"); btn.addEventListener("click", open); }
var force = /[?&]story=1/.test(location.search);
var skip = location.hash || /[?&]q=/.test(location.search) || (window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
if(force || (!skip && lsg("mgStoryDay") !== tpeDay())) setTimeout(open, 700);
window.mgStory = open;
})();
"""


def story_html(data: dict) -> str:
    from . import story_share
    js_data = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return (f'<style>{CSS}{story_share.CSS}</style>'
            f'<script type="application/json" id="story-data">{js_data}</script>'
            f'<script>{story_share.js()}{JS}</script>')
