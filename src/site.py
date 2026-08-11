"""
網站層 — 共用版面、導覽列與頁面外殼。

一個頁面 = site.page(標題, 目前分頁, 內容 HTML)
各模組（勞動／通膨／FOMC／情境）只負責產生內容，不碰版面。

版面採「手機優先」：基本樣式寫給窄螢幕，再用 min-width 查詢加寬。
"""

from __future__ import annotations

import html
import datetime as dt

# 導覽列定義：(路徑, 名稱, 是否已完成)
NAV = [
    ("/", "總覽", True),
    ("/labor/", "勞動市場", True),
    ("/inflation/", "通膨", True),
    ("/fomc/", "聯準會文本", True),
    ("/rates/", "長端與債務", True),
    ("/scenario/", "情境合成", True),
    ("/archive/", "存檔", True),
]

# 窄於這個寬度時，標示 data-m-collapse 的區塊預設收合
MOBILE_BREAKPOINT = 760



def esc(s) -> str:
    return html.escape(str(s), quote=True)


CSS = """
*{box-sizing:border-box}
/* 單一淺色主題。圖表繪製表面固定為 --surface-1（卡片），配色依此驗證。 */
.viz-root{
  color-scheme:light;
  --page:#eeede9; --surface-1:#fcfcfb; --surface-2:#f3f3f0;
  --text-primary:#0b0b0b; --text-secondary:#45443f; --muted:#6b6a64;
  --grid:#e3e2db; --baseline:#c3c2b7; --border:rgba(11,11,11,0.13);
  /* 文字用的藍與橘要壓深一點：#2a78d6 在卡片底色上只有 3.97:1，
     而「展開…」這種連結、燈號狀態字全都用它。圖表線條另外留一組亮色，
     線條屬於圖形元素，門檻是 3:1，不必跟著壓深。 */
  --series-1:#266dc2; --series-2:#c25529;
  --line-1:#2a78d6; --line-2:#eb6834;
  --pos:#2a78d6; --neg:#e34948; --muted-bar:#b8b7af;
  /* --warning 從 #936400 再壓深一級：它在白底上是 5.17，剛好過關，
     但疊在有色底（例如 .k-surp 的紅色淡底）上只剩 4.39，掉到 AA 以下。
     文字色要能在**任何**卡片底色上都成立，不能只看白底。 */
  --good:#077c07; --warning:#8a5e00; --serious:#ae5229; --critical:#c22f2f;
  --tint-dov:rgba(42,120,214,.11); --tint-haw:rgba(180,85,43,.12);
  --shadow:0 1px 2px rgba(11,11,11,.05),0 1px 8px rgba(11,11,11,.04);
}

html{-webkit-text-size-adjust:100%}
/* 中文字型（如 Noto Sans CJK）只有 400/500/700 等實體字重。
   若指定 650 這類非標準值，瀏覽器會改用「合成粗體」——筆畫被撐寬但
   前進距離不變，中文就會疊在一起。因此全站只用標準字重，
   並額外加一點字距作為保險。 */
h1,h2,h3,.v-main,.f-head,.m-name,.l-top,.k-label,.gloss dt,
.verdict .v-main,strong,b{letter-spacing:.035em}
body{margin:0;background:var(--page);
  /* CJK 家族一定要點名，而且要用含 "CJK" 的完整家族名。
     只寫 system-ui / sans-serif 時，瀏覽器逐字回退找到的是 Regular 字面，
     粗體只好用「合成粗體」——筆畫塗寬但前進距離不變，中文就疊在一起。
     點名 "Noto Sans CJK TC" 之後會取到真正的 Bold 字面。
     順序：iOS/macOS 走 PingFang，Windows 走微軟正黑，Android/Linux 走 Noto。 */
  font-family:system-ui,-apple-system,"Segoe UI Variable","Segoe UI",
    "PingFang TC","PingFang SC","Hiragino Sans CNS","Microsoft JhengHei",
    "Noto Sans CJK TC","Noto Sans CJK SC","Noto Sans TC",sans-serif;
  color:var(--text-primary);-webkit-font-smoothing:antialiased;
  font-size:15px;line-height:1.6}
.viz-root{max-width:1120px;margin:0 auto;padding:16px 14px 60px}
@media(min-width:760px){.viz-root{padding:22px 20px 70px}}

/* ---------- 頁首 ---------- */
h1{font-size:21px;margin:0;font-weight:700;line-height:1.35}
@media(min-width:760px){h1{font-size:23px}}
.sub{color:var(--muted);font-size:12.5px;margin-top:5px;line-height:1.55}


/* ---------- 導覽列：手機上單行可左右滑 ---------- */
nav.site{display:flex;gap:2px;margin:14px 0 0;background:var(--surface-1);
  border:1px solid var(--border);border-radius:11px;padding:4px;
  box-shadow:var(--shadow);overflow-x:auto;-webkit-overflow-scrolling:touch;
  scrollbar-width:none}
nav.site::-webkit-scrollbar{display:none}
/* 導覽是全站最常按的東西，觸控目標要有 44px（先前 36.9px）。 */
nav.site a{font-size:13.5px;color:var(--text-secondary);text-decoration:none;
  padding:14px 13px;border-radius:8px;white-space:nowrap;flex-shrink:0;
  line-height:1.2}
nav.site a:hover{background:var(--surface-2);color:var(--text-primary)}
nav.site a.on{background:var(--surface-2);color:var(--text-primary);font-weight:700}
nav.site a.soon{color:var(--muted)}
nav.site a.soon::after{content:"·建置中";font-size:10px;margin-left:3px}

.banner{background:var(--surface-1);border:1px solid var(--warning);
  border-left-width:3px;border-radius:10px;padding:11px 14px;margin:14px 0 0;
  font-size:13px;color:var(--text-secondary);line-height:1.7}
.banner b{color:var(--warning)}

/* ---------- 版面網格 ---------- */
.grid{display:grid;gap:13px;margin-top:13px;grid-template-columns:1fr}
/* 網格項目預設 min-width:auto，裡面只要有一個不能再窄的東西（寬表格、
   長串數字），整欄就會被撐開，連帶把整頁推得比視窗寬。歸零之後，
   撐不下的內容由它自己的捲動容器處理，版面不受影響。 */
.grid>*{min-width:0}
@media(min-width:760px){
  .grid{gap:14px;margin-top:14px}
  .g2{grid-template-columns:repeat(2,1fr)}
  .g4{grid-template-columns:repeat(2,1fr)}
  /* 模組卡有五張。四欄會排成 4+1，最後一張孤零零的；三欄的 3+2 比較穩。 */
  .g5{grid-template-columns:repeat(2,1fr)}
}
@media(min-width:1040px){
  .g4{grid-template-columns:repeat(4,1fr)}
  .g5{grid-template-columns:repeat(3,1fr)}
}
@media(min-width:1320px){.g5{grid-template-columns:repeat(5,1fr)}}

.card{background:var(--surface-1);border:1px solid var(--border);
  border-radius:13px;padding:17px 16px;box-shadow:var(--shadow);min-width:0}
@media(min-width:760px){.card{padding:18px 20px}}
.card h2{font-size:17px;margin:0 0 5px;font-weight:700;line-height:1.5}
.card h3{font-size:15px;margin:22px 0 4px;font-weight:700}
.card .hint{font-size:13px;color:var(--muted);margin:0 0 15px;line-height:1.65}
.card .src{font-size:12px;color:var(--muted);margin-top:15px;padding-top:11px;
  border-top:1px solid var(--border);line-height:1.6}

/* ---------- 結論卡 ---------- */
.verdict{background:var(--surface-1);border:1px solid var(--border);
  border-radius:13px;padding:19px 17px;box-shadow:var(--shadow);margin-top:13px;
  border-left:4px solid var(--muted)}
@media(min-width:760px){.verdict{padding:24px 24px}}
.verdict.dovish{border-left-color:var(--series-1)}
.verdict.hawkish{border-left-color:var(--serious)}
.verdict.balanced{border-left-color:var(--muted)}
/* 情境頁的傾向可能是 neutral（反應函數把方向改寫成中性時），
   沒有這條規則那張卡就只剩預設灰邊，看起來像漏了樣式 */
.verdict.neutral{border-left-color:var(--muted)}
.v-eyebrow{font-size:12.5px;color:var(--muted)}
/* 結論卡的字必須大於任何單一 KPI 數字。手機上原本是結論 26px、
   KPI 32px，等於在版面上宣告「單一數字比整體結論重要」——
   讀者的視線會先落在某個指標上，再回頭找結論。 */
.v-main{font-size:29px;font-weight:700;margin-top:9px;line-height:1.4}
@media(min-width:760px){.v-main{font-size:34px}}
/* 360px 上「停滯性通膨：通膨優先」這種長情境名，最後一個字會單獨掉到
   第二行。中文沒有連字號可斷，只能把字級縮一級——孤字比小一點的字礙眼。 */
@media(max-width:400px){.v-main{font-size:26px;letter-spacing:.02em}}
.v-why{font-size:14.5px;color:var(--text-secondary);margin-top:12px;line-height:1.85}
.v-count{font-size:12.5px;color:var(--muted);margin-top:15px;padding-top:13px;
  border-top:1px solid var(--border);line-height:1.75}

/* ---------- KPI ---------- */
.kpi .k-label{font-size:13px;color:var(--text-secondary);font-weight:600}
.kpi .k-value{font-size:26px;font-weight:700;line-height:1.2;margin-top:5px}
@media(min-width:760px){.kpi .k-value{font-size:30px}}
.kpi .k-sub{font-size:12.5px;color:var(--muted);margin-top:6px}
.kpi .k-plain{font-size:13.5px;color:var(--text-primary);margin-top:11px;
  line-height:1.75;background:var(--surface-2);border-radius:9px;padding:10px 12px}
.kpi .k-flag{font-size:12.5px;margin-top:9px;padding:5px 10px;border-radius:7px;
  display:inline-block;background:var(--surface-2);color:var(--text-secondary);
  font-weight:600}
.kpi .k-flag.neg{color:var(--critical)} .kpi .k-flag.pos{color:var(--good)}
/* 四張 KPI 卡被拉成同高，但卡內是普通區塊流，走勢圖與數值列因此
   停在各自不同的位置，一列看過去參差不齊。把卡片改成直向 flex、
   走勢圖以上推到頂，四張卡的圖與數值列就落在同一條線上。 */
.kpi{display:flex;flex-direction:column}
.spark{margin-top:auto;padding-top:11px;display:block;width:100%;height:34px}

/* ---------- 數字組（改用網格，手機兩欄對齊） ---------- */
.stat-row{display:grid;grid-template-columns:repeat(2,1fr);gap:16px 14px;
  margin-bottom:4px}
@media(min-width:760px){
  .stat-row{grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:18px}
}
.stat .s-label{font-size:12.5px;color:var(--muted);line-height:1.45}
/* 數值＋單位不能從中間斷開。「-0.10 個百分點」折成兩行時，
   讀者要多花一拍才確定那個單位屬於上面那個數字。 */
.stat .s-value{font-size:20px;font-weight:700;margin-top:4px;
  font-variant-numeric:tabular-nums;line-height:1.3;white-space:nowrap}
@media(max-width:420px){.stat .s-value{font-size:18px}}
/* 標籤長度不一時，數值會各自對到不同的基線。給標籤兩行的高度，
   同一列的數字才會落在同一條水平線上。
   只在 ≥760px 生效：那裡欄位是 auto-fit、每欄可能窄到讓長標籤折行，
   所以需要預留。手機固定兩欄、每欄約 160px，多數標籤本來就是一行，
   硬撐兩行等於每個 .stat 白白多出 18px——全站數十個 stat 累積起來
   接近一個螢幕高度的空白，而它換來的對齊在手機上根本用不到。 */
@media(min-width:760px){.stat .s-label{min-height:2.9em}}
.stat .s-note{font-size:12.5px;color:var(--text-secondary);margin-top:4px;
  line-height:1.55}

/* ---------- 表格 ---------- */
table{width:100%;border-collapse:collapse;font-size:13.5px;
  font-variant-numeric:tabular-nums}
th,td{text-align:right;padding:9px 5px;border-bottom:1px solid var(--grid)}
th:first-child,td:first-child{text-align:left}
th{color:var(--muted);font-weight:500;font-size:12px}
tbody tr:last-child td{border-bottom:none}
td.pos{color:var(--good)} td.neg{color:var(--critical)}
td.muted-cell{color:var(--muted)}
.revtab td:first-child{font-variant-numeric:normal}
/* 儲存格裡的外部連結（EDGAR 申報書、聲明原文）只有 14–15px 高，
   在手機上幾乎按不到。用 inline-block 加上下內距把觸控區撐到 40px，
   再用等量的負 margin 抵銷，視覺上仍然只是一段文字。 */
td a[target="_blank"],.src a[target="_blank"]{
  display:inline-block;padding:12px 8px;margin:-12px -8px}
/* 欄位多的表格（例如科技巨頭那張六欄表）在 390px 上會把儲存格擠成
   一個字一行。包一層可橫向捲動的容器，寧可讓它滑，也不要把數字折斷。 */
.tscroll{overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:thin}
/* 寫死 min-width 會讓明明放得下的表格也被迫捲動。改成「內容多寬就多寬，
   至少填滿容器」：塞得下就不捲，塞不下才捲。 */
.tscroll>table{width:max-content;min-width:100%}
/* 會捲的表格把左右內距收窄一點，多爭取的空間常常剛好夠讓它不用捲 */
@media(max-width:520px){.tscroll th,.tscroll td{padding:9px 4px;font-size:13px}}

/* ---------- 發散長條（行業增減）---------- */
.dbars{display:flex;flex-direction:column;gap:3px;margin-top:4px}
.drow{display:grid;grid-template-columns:96px 1fr 76px;align-items:center;
  gap:8px;padding:4px 0;border-radius:6px}
@media(min-width:760px){.drow{grid-template-columns:150px 1fr 92px;gap:12px}}
/* 窄螢幕上把行業名稱移到自己一行：96px 的欄寬塞不下「值得注意｜相對自身
   歷史 −2.5 個標準差」，會被折成四行、把整列撐高。名稱獨立一行之後，
   長條也順便變寬，方向更好判讀。 */
@media(max-width:520px){
  .drow{grid-template-columns:1fr 72px;row-gap:3px;padding:7px 0}
  .dlabel{grid-column:1 / -1}
}
.drow:hover{background:var(--surface-2)}
.dlabel{font-size:12.5px;color:var(--text-secondary);line-height:1.35}
@media(min-width:760px){.dlabel{font-size:13.5px}}
/* 標籤帶理由：理由用一般字重接在後面，讓「值得注意」不再是一個
   點下去沒反應的空標籤。窄螢幕上讓它掉到下一行，不要擠壓行業名稱。 */
.dtag{display:inline-block;font-size:10.5px;font-weight:700;color:var(--warning);
  border:1px solid var(--warning);border-radius:4px;padding:0 4px;margin-left:4px;
  vertical-align:1px}
.dtag b{font-weight:400;margin-left:4px;color:var(--text-secondary)}
@media(max-width:520px){.dtag{display:block;margin:3px 0 0;width:fit-content}}
.dnote{display:block;font-size:11.5px;color:var(--muted)}
.dtrack{position:relative;height:15px}
.dzero{position:absolute;left:50%;top:-1px;bottom:-1px;width:1px;
  background:var(--baseline)}
.dfill{position:absolute;top:0;bottom:0;border-radius:3px;min-width:2px}
.dfill.pos{background:var(--pos)} .dfill.neg{background:var(--neg)}
.dfill.muted{background:var(--muted-bar)}
.dval{font-size:12.5px;text-align:right;font-variant-numeric:tabular-nums;
  color:var(--text-secondary)}
@media(min-width:760px){.dval{font-size:13.5px}}
.dval.pos{color:var(--good)} .dval.neg{color:var(--critical)}
.dlegend{display:flex;flex-wrap:wrap;gap:12px;margin-top:12px;padding-top:11px;
  border-top:1px solid var(--grid);font-size:12px;color:var(--muted)}
.dlegend span{display:flex;align-items:center;gap:5px}
.dlegend i{width:10px;height:10px;border-radius:2px;display:inline-block}

/* ---------- 紅綠燈 ---------- */
/* 手機兩欄時每張卡不再被拉高到同列最高——說明文字長度差很多，
   齊高會讓短的那張有三到四成是空白，八張燈累積起來是一整個螢幕。
   ≥1040px 四欄時仍然齊高：那裡卡片小、齊高才看得出是一組。 */
.lights{display:grid;grid-template-columns:repeat(2,1fr);gap:9px;
  align-items:start}
@media(min-width:1040px){.lights{grid-template-columns:repeat(4,1fr);
  align-items:stretch}}
.light{background:var(--surface-2);border-radius:10px;padding:12px 12px;
  border:1px solid var(--border);display:flex;flex-direction:column}
.light .l-top{display:flex;align-items:center;gap:6px;font-size:12.5px;
  color:var(--text-secondary);font-weight:600;line-height:1.35}
.light .l-icon{font-size:10px;flex-shrink:0}
.light.good .l-icon,.light.good .l-state{color:var(--good)}
.light.warning .l-icon,.light.warning .l-state{color:var(--warning)}
.light.critical .l-icon,.light.critical .l-state{color:var(--critical)}
.light.unknown .l-icon,.light.unknown .l-state{color:var(--muted)}
/* 數值與單位不能斷開：「4.3 個百分點」折成兩行時，
   讀者要多花一拍才能確定那個單位屬於上面那個數字。
   手機兩欄只有約 160px 寬，22px 的字放不下較長的值，所以一併縮一級。 */
.light .l-value{font-size:22px;font-weight:700;margin-top:8px;
  font-variant-numeric:tabular-nums;line-height:1.2;white-space:nowrap}
@media(max-width:420px){.light .l-value{font-size:19px}}
.light .l-state{font-size:12px;margin-top:5px;font-weight:700}
.light .l-desc{font-size:12px;color:var(--muted);margin-top:7px;line-height:1.55;
  margin-bottom:0}

/* 失業缺口 u − u*：水準的位置，跟上面那段「變化的成因」是兩件事，
   所以用一條分隔線隔開，而不是再開一張卡。 */
.ugap{margin-top:16px;padding-top:13px;border-top:1px solid var(--border)}
.ug-top{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap}
.ug-label{font-size:12.5px;color:var(--text-secondary);font-weight:600}
.ug-val{font-size:19px;font-weight:700;font-variant-numeric:tabular-nums;
  white-space:nowrap}
.ug-state{font-size:11px;font-weight:700;padding:1px 7px;border-radius:5px;
  background:var(--surface-2);color:var(--text-secondary)}
.ug-note{font-size:12.5px;color:var(--muted);line-height:1.75;margin-top:6px}

/* 失業結構：五個類別各一列。名稱、橫條、數值三欄，
   說明另起一行——手機上四欄並排會把每一欄擠成兩個字一行。 */
.ustruct{margin-top:12px}
.ustr-list{margin-top:12px;display:flex;flex-direction:column;gap:13px}
.ustr{display:grid;grid-template-columns:1fr auto;gap:3px 10px;
  align-items:center}
.us-name{font-size:13px;font-weight:600}
.us-bar{grid-column:1/-1;height:7px;background:var(--surface-2);
  border-radius:4px;overflow:hidden;order:3}
.us-bar i{display:block;height:100%;border-radius:4px;background:var(--muted-bar)}
.ustr.bad .us-bar i{background:var(--neg)}
.ustr.good .us-bar i{background:var(--pos)}
.us-val{font-size:14px;font-weight:700;font-variant-numeric:tabular-nums;
  white-space:nowrap;text-align:right}
.us-share{font-size:11.5px;font-weight:500;color:var(--muted);margin-left:6px}
.us-yoy{grid-column:1/-1;order:4;font-size:12px;color:var(--text-secondary);
  font-variant-numeric:tabular-nums}
.us-note{grid-column:1/-1;order:5;font-size:12px;color:var(--muted);
  line-height:1.6}

/* ---------- 訊號 ---------- */
.flag{display:flex;gap:10px;padding:16px 0;border-bottom:1px solid var(--grid)}
.flag:first-of-type{padding-top:2px}
.flag:last-child{border-bottom:none;padding-bottom:2px}
.flag .f-icon{font-size:10px;margin-top:6px;flex-shrink:0}
.flag.alert .f-icon{color:var(--critical)}
.flag.watch .f-icon{color:var(--warning)}
.flag.info .f-icon{color:var(--muted)}
.flag .f-head{font-size:15.5px;font-weight:700;line-height:1.6}
.flag .f-detail{font-size:14px;color:var(--text-secondary);margin-top:7px;
  line-height:1.85}
.flag .f-tag{font-size:11.5px;color:var(--muted);border:1px solid var(--border);
  border-radius:5px;padding:1px 6px;margin-left:6px;white-space:nowrap;
  font-weight:500;vertical-align:2px}
.impact{display:inline-block;font-size:12.5px;font-weight:700;border-radius:7px;
  padding:5px 10px;margin-top:10px;line-height:1.5}
/* 帶底色的小標籤要另外壓深：在自己的淡底上，一般文字色只有 4.3–4.4:1 */
.impact.dovish{background:var(--tint-dov);color:#2469ba}
.impact.hawkish{background:var(--tint-haw);color:#a44d27}
.impact.neutral{background:var(--surface-2);color:var(--muted)}

/* 說明收合起來之後，「依據」這個開關要小、要低調——
   它是次要動作，不能跟訊號標題搶注意力。 */
.f-more{margin-top:9px;border-top:none;padding-top:0}
/* 觸控目標至少 44px 高（WCAG 2.5.8 / Apple HIG）。字體維持 12.5px，
   靠上下 padding 把可點區域撐到 44px，並用負的 margin 抵銷多出來的
   視覺留白——看起來還是一個小開關，手指卻按得到。
   全站有十個這種開關，每一個都太小的話，收合設計本身就失效了。 */
.f-more>summary{font-size:12.5px;font-weight:500;color:var(--muted);
  padding:13px 0;margin:-7px 0}
.f-more>summary:hover{color:var(--series-1)}
.f-more .f-detail{margin-top:2px}

/* ---------- 分數條 ---------- */
.score-bar{height:9px;background:var(--surface-2);border-radius:5px;
  position:relative;margin:15px 0 8px}
.score-bar i{position:absolute;top:0;bottom:0;border-radius:5px}
.score-mid{position:absolute;top:-3px;bottom:-3px;width:1px;
  background:var(--baseline);left:50%}

/* 分數軸：結論卡裡放 compact 版，明細卡裡放完整版，同一套樣式 */
.sax{margin-top:16px;padding-top:15px;border-top:1px solid var(--border)}
.sax.compact{margin-top:14px;padding-top:13px}
.sax-head{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.sax-label{font-size:12.5px;color:var(--muted)}
.sax-val{font-size:26px;font-weight:700;font-variant-numeric:tabular-nums;
  line-height:1.1}
.sax.compact .sax-val{font-size:22px}
.sax-delta{font-size:12.5px;color:var(--text-secondary)}
.sax-scale{display:flex;justify-content:space-between;font-size:11.5px;
  color:var(--muted)}

/* KPI 卡裡的「vs 預期」一行 */
.k-surp{margin-top:9px;padding:7px 10px;border-radius:8px;font-size:12.5px;
  line-height:1.7;background:var(--surface-2);color:var(--text-secondary)}
.k-surp.beat{background:rgba(7,124,7,.09)}
.k-surp.miss{background:rgba(194,47,47,.09)}
.k-surp .ks-sep{margin:0 6px;color:var(--muted)}
.k-surp .ks-diff{font-weight:700;color:var(--text-primary)}
.k-surp .ks-verdict{display:inline-block;margin-left:7px;font-weight:700}
.k-surp.beat .ks-verdict{color:#036b03}
.k-surp.miss .ks-verdict{color:#ad2929}
.k-surp .ks-z{display:block;font-size:11.5px;color:var(--muted);margin-top:1px}
.k-surp .ks-star{color:var(--warning);font-weight:700}
.k-surp .su{font-size:11px;color:var(--muted);margin-left:1px}
.kpi-foot{font-size:12px;color:var(--muted);line-height:1.7;margin-top:10px;
  padding:0 2px}
.kpi-foot.warn{background:var(--surface-1);border:1px solid var(--border);
  border-left:3px solid var(--warning);border-radius:9px;padding:11px 13px}
.kpi-foot b{color:var(--text-primary)}

/* 失業率變動分解：結論在上、拆解在下，兩項相加等於總變動 */
.dsum{padding-bottom:14px;border-bottom:1px solid var(--grid)}
.dsum-main{font-size:22px;font-weight:700;line-height:1.35}
.dsum-sub{font-size:13px;color:var(--text-secondary);margin-top:5px}
.dcomp{margin-top:14px}
.dc-row{display:grid;grid-template-columns:84px 1fr 62px;align-items:center;
  gap:9px;margin-top:9px}
@media(min-width:760px){.dc-row{grid-template-columns:96px 1fr 70px;gap:12px}}
.dc-name{font-size:12.5px;color:var(--text-secondary)}
.dc-bar{position:relative;height:15px}
.dc-zero{position:absolute;left:50%;top:-1px;bottom:-1px;width:1px;
  background:var(--baseline)}
/* 這兩條刻意用中性色。整張卡的重點就是「正負不等於好壞」——
   勞動力效果是負的（壓低失業率），但成因是有人放棄找工作，那不是好消息。
   上成紅綠會把讀者導向完全相反的結論，方向由左右與文字說明表示。 */
.dc-bar i{position:absolute;top:0;bottom:0;border-radius:3px;min-width:2px;
  background:var(--muted-bar)}
.dc-val{font-size:14.5px;font-weight:700;text-align:right;
  font-variant-numeric:tabular-nums}
.dc-note{font-size:11.5px;color:var(--muted);line-height:1.6;
  margin:3px 0 0 0;padding-left:2px}
@media(min-width:760px){.dc-note{padding-left:108px}}
.dc-total{margin-top:13px;padding-top:11px;border-top:1px solid var(--grid);
  font-size:13px;font-weight:700;text-align:right;
  font-variant-numeric:tabular-nums}

/* 措辭分數降為副：一行橫排，不再跟客觀訊號並列成兩個等大的方塊。
   這一頁的結論明說「以客觀訊號為準」，版面權重要跟著。 */
.tone-row{display:grid;grid-template-columns:auto auto 1fr;align-items:baseline;
  gap:6px 10px;margin-top:12px;padding:12px 14px;border-radius:10px;
  background:var(--surface-2)}
.tone-label{font-size:12.5px;color:var(--text-secondary);font-weight:600}
.tone-val{font-size:19px;font-weight:700;font-variant-numeric:tabular-nums}
.tone-row.hawkish .tone-val{color:var(--serious)}
.tone-row.dovish .tone-val{color:var(--series-1)}
.tone-row.neutral .tone-val{color:var(--muted)}
.tone-delta{font-size:12.5px;color:var(--muted);font-variant-numeric:tabular-nums;
  white-space:nowrap}
/* 三欄（標籤｜分數｜較上次）在 360px 只剩約 32px 給第三欄，
   「較上次 −0.12」會折成三行、每行兩三個字。窄螢幕改成兩欄，
   把變化量放到自己的一整行。 */
@media(max-width:520px){
  .tone-row{grid-template-columns:auto 1fr}
  .tone-delta{grid-column:1 / -1;margin-top:1px}
}
.tone-note{grid-column:1 / -1;font-size:12px;color:var(--muted);line-height:1.7}
.tone-flag{display:inline-block;margin-left:6px;font-size:10.5px;font-weight:700;
  color:var(--warning);border:1px solid var(--warning);border-radius:4px;
  padding:0 4px;vertical-align:1px}
/* 不可靠時把數字本身也調成灰的——它還在，但不該吸引視線 */
.tone-row.stale .tone-val{color:var(--muted)}

/* 離目標軸：跟分數軸共用外框，但刻度上有一個固定的錨點（2% 目標），
   填色是從目標畫到目前值——長度就是差距，方向就是高於還是低於。 */
.tgt-bar{height:9px;background:var(--surface-2);border-radius:5px;
  position:relative;margin:15px 0 8px}
.tgt-bar i{position:absolute;top:0;bottom:0;border-radius:5px}
.tgt-mark{position:absolute;top:-4px;bottom:-4px;width:2px;
  background:var(--text-primary);border-radius:1px;z-index:2}
.tgt-dot{position:absolute;top:50%;width:13px;height:13px;border-radius:50%;
  transform:translate(-50%,-50%);box-shadow:0 0 0 2px var(--surface-1);z-index:3}

/* 但書：掛在結論框裡面、縮排一階，明確是「對上面那句話的但書」，
   不是平行的第二個結論。兩個等重的警示框並排時讀者不知道該信哪個。 */
.caveat{margin-top:12px;padding:10px 12px;border-left:2px solid var(--warning);
  background:var(--surface-2);border-radius:0 8px 8px 0;
  font-size:13px;line-height:1.8;color:var(--text-secondary)}
.caveat b{color:var(--warning)}

/* 文字欄位靠右讀起來很彆扭。這個類別讓最後一欄（說明）改回靠左。 */
.lefty td:last-child,.lefty th:last-child{text-align:left}

/* 損益兩平的缺口：這是整張卡的結論，要比兩個輸入值大 */
.bkgap{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap;
  margin-top:14px;padding-top:13px;border-top:1px solid var(--grid)}
.bk-label{font-size:12.5px;color:var(--muted)}
.bk-val{font-size:26px;font-weight:700;font-variant-numeric:tabular-nums;
  line-height:1.1}
.bk-verdict{font-size:13.5px;font-weight:700}

/* ---------- 首頁 ---------- */
/* .hero / .h-verdict 一族已隨首頁改版移除，樣式一併刪除 */

/* 三個政策模組的方向一致度：首頁獨有的資訊——分頁只能講自己那一塊，
   只有總覽能回答「三個觀點彼此同意嗎」。長端另外一格、不進票數，
   因為它回答的是曲線形狀而不是政策方向（見 README「長端供給壓力不進九宮格」）。 */
.cons{margin-top:15px;padding-top:14px;border-top:1px solid var(--border)}
.cons-row{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}
@media(min-width:560px){.cons-row{grid-template-columns:repeat(3,1fr)}}
.cons-i{background:var(--surface-2);border-radius:9px;padding:9px 10px}
.cons-i.aside{background:transparent;border:1px dashed var(--border)}
.cons-aside{margin-top:9px}
.cons-aside .cons-row{grid-template-columns:1fr}
@media(min-width:560px){.cons-aside .cons-row{grid-template-columns:1fr}}
.cons-k{display:block;font-size:11.5px;color:var(--muted)}
.cons-v{display:block;font-size:14px;font-weight:700;margin-top:3px}
.cons-v.hawkish{color:var(--serious)} .cons-v.dovish{color:var(--series-1)}
.cons-v.neutral{color:var(--text-secondary)}
.cons-note{font-size:13px;color:var(--text-secondary);line-height:1.8;
  margin-top:11px}

/* 倒數：三個並排，日期與可信度說明在下方 */
.cds{display:grid;gap:9px;margin-top:10px}
@media(min-width:560px){.cds{grid-template-columns:repeat(3,1fr)}}
.cd{background:var(--surface-2);border-radius:9px;padding:11px 12px}
.cd-k{font-size:12px;color:var(--muted)}
.cd-d{font-size:19px;font-weight:700;margin-top:3px;
  font-variant-numeric:tabular-nums}
.cd-n{font-size:11.5px;color:var(--muted);margin-top:3px;line-height:1.6}

/* 接下來要盯什麼：門檻與距離 */
.wt{background:var(--surface-2);border-radius:9px;padding:11px 12px;
  margin-bottom:9px}
.wt-k{font-size:12.5px;color:var(--text-secondary);font-weight:600}
.wt-v{font-size:19px;font-weight:700;margin-top:3px;
  font-variant-numeric:tabular-nums}
.wt-n{font-size:11.5px;color:var(--muted);margin-top:3px;line-height:1.6}

/* 模組卡的方向章 */
.m-dir{display:inline-block;margin-left:9px;font-size:11.5px;font-weight:700;
  padding:2px 7px;border-radius:6px;vertical-align:3px;background:var(--surface-2)}
.m-dir.hawkish{color:#a44d27;background:var(--tint-haw)}
.m-dir.dovish{color:#2469ba;background:var(--tint-dov)}
.m-dir.neutral{color:var(--muted)}

.modcard{display:block;text-decoration:none;color:inherit;
  background:var(--surface-1);border:1px solid var(--border);border-radius:13px;
  padding:16px;box-shadow:var(--shadow);transition:border-color .12s}
.modcard:hover{border-color:var(--text-secondary)}
.modcard.pending{opacity:.6}
.modcard .m-top{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.modcard .m-name{font-size:14.5px;font-weight:700}
.modcard .m-when{font-size:11.5px;color:var(--muted);white-space:nowrap}
.modcard .m-value{font-size:27px;font-weight:700;margin-top:9px;line-height:1.2}
/* 13px 時「期限溢酬 +0.78%」剛好多 5px 塞不下，數字會單獨掉到第二行，
   整張卡多一行、同列的另一張卡連結就對不齊了。 */
.modcard .m-note{font-size:12.5px;color:var(--text-secondary);margin-top:7px;
  line-height:1.7}
.modcard .m-more{font-size:12.5px;color:var(--muted);margin-top:12px}

.soonbox{background:var(--surface-1);border:1px solid var(--border);
  border-radius:13px;padding:34px 20px;text-align:center;box-shadow:var(--shadow);
  margin-top:13px}
.soonbox h3{font-size:16px;margin:0 0 10px}
.soonbox p{font-size:14px;color:var(--text-secondary);margin:0 auto;max-width:520px;
  line-height:1.85}

.archive-list{list-style:none;padding:0;margin:0}
.archive-list li{border-bottom:1px solid var(--grid)}
.archive-list li:last-child{border-bottom:none}
.archive-list a{display:flex;justify-content:space-between;gap:12px;padding:13px 2px;
  text-decoration:none;color:var(--text-primary);font-size:14px}
.archive-list a:hover{color:var(--series-1)}
.archive-list .a-meta{color:var(--muted);font-size:12.5px}

/* ---------- 名詞解釋 ---------- */
.gloss{margin:6px 0 0}
.gloss dt{font-weight:700;font-size:13.5px;margin-top:13px}
.gloss dt:first-child{margin-top:0}
.gloss dd{margin:3px 0 0;color:var(--text-secondary);font-size:13px;line-height:1.75}
@media(min-width:760px){
  .gloss{display:grid;grid-template-columns:130px 1fr;gap:11px 18px}
  .gloss dt{margin-top:0} .gloss dd{margin-top:0}
}

/* ---------- 折疊 ---------- */
details{margin-top:14px;border-top:1px solid var(--grid);padding-top:12px}
details[open]{padding-bottom:2px}
/* 展開列是全站最常點的東西，高度要撐到 44px 才好按 */
summary{font-size:13.5px;color:var(--series-1);cursor:pointer;font-weight:600;
  list-style:none;padding:12px 0}
summary::-webkit-details-marker{display:none}
summary::after{content:" ▾";font-size:11px}
details[open]>summary::after{content:" ▴"}
details.plain{border-top:none;padding-top:0}

.empty{font-size:13px;color:var(--muted);padding:22px 0;text-align:center}

#tip{position:fixed;pointer-events:none;background:var(--surface-2);
  border:1px solid var(--border);border-radius:8px;padding:7px 11px;font-size:13px;
  color:var(--text-primary);opacity:0;transition:opacity .1s;z-index:99;
  /* 這個 30% 黑的陰影是深色模式時代留下的，在淺色底上會糊成一團灰塊 */
  box-shadow:0 4px 14px rgba(15,23,42,.13);white-space:nowrap}
@media(hover:none){#tip{display:none}}

footer{margin-top:26px;font-size:12.5px;color:var(--muted);line-height:1.8}

/* ---------- 聲明配對比對 ---------- */
.drow2{border:1px solid var(--border);border-radius:10px;padding:11px 13px;
  margin-bottom:9px;background:var(--surface-1)}
.drow2 .dlabel2{font-size:11.5px;font-weight:700;color:var(--muted);
  letter-spacing:.05em;margin-bottom:7px}
.drow2 .dold,.drow2 .dnew{font-size:13.5px;line-height:1.85;padding:7px 10px;
  border-radius:7px}
.drow2 .dold{background:var(--surface-2);color:var(--muted);margin-bottom:6px}
.drow2 .dnew{background:var(--tint-dov)}
.drow2 .darrow{font-size:11px;color:var(--muted);margin:2px 0 4px}
.drow2.added{border-left:3px solid var(--series-1)}
.drow2.removed{border-left:3px solid var(--muted)}
.drow2.changed{border-left:3px solid var(--serious)}
mark.mo{background:rgba(180,85,43,.18);color:#8d4220;
  text-decoration:line-through;text-decoration-thickness:1px;
  border-radius:3px;padding:0 2px}
mark.mn{background:rgba(42,120,214,.22);color:var(--text-primary);
  font-weight:600;border-radius:3px;padding:0 2px}
.dsame{font-size:12.5px;color:var(--muted);line-height:1.8;padding:5px 12px}
/* 記者會依主題抽出的原句 */
.pline{font-size:13.5px;line-height:1.85;color:var(--text-secondary);
  background:var(--surface-2);border-radius:8px;padding:10px 12px;margin-bottom:7px}

/* ---------- 雙分數並列 ---------- */
.dual{display:grid;grid-template-columns:1fr;gap:11px}
@media(min-width:600px){.dual{grid-template-columns:1fr 1fr}}
.dbox{background:var(--surface-2);border-radius:10px;padding:14px 14px;
  border:1px solid var(--border)}
.dbox.primary{border-color:var(--text-primary);border-width:1.5px}
.dbox .dtitle{font-size:12.5px;color:var(--text-secondary);font-weight:600}
.dbox .dscore{font-size:30px;font-weight:700;margin-top:7px;line-height:1.15;
  font-variant-numeric:tabular-nums}
.dbox .dlab{font-size:12.5px;font-weight:700;margin-top:5px}
.dbox .dnote{font-size:12px;color:var(--muted);margin-top:7px;line-height:1.6}
.dbox.hawkish .dlab{color:var(--serious)}
.dbox.dovish .dlab{color:var(--series-1)}
.dbox.neutral .dlab{color:var(--muted)}
/* 整塊套 opacity 會連內文一起壓暗——量到只剩 2.4:1，遠低於 4.5。
   改成只把數字與標籤調淡，說明文字維持原本的對比。 */
.dbox.stale{background:var(--surface-2);border-style:dashed}
/* 不用 opacity 壓字（會直接壓垮對比），改用虛線框＋底色表示「這一格別當真」 */
.dbox.stale .dscore{color:var(--text-secondary)}

.warnbox{background:var(--surface-1);border:1px solid var(--warning);
  border-left-width:3px;border-radius:10px;padding:13px 15px;margin-top:14px;
  font-size:13px;line-height:1.8;color:var(--text-secondary)}
.warnbox b{color:var(--warning)}

/* ---------- 投票 ---------- */
.votes{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px}
.vchip{font-size:12px;border-radius:7px;padding:5px 10px;border:1px solid var(--border);
  background:var(--surface-2);color:var(--text-secondary)}
.vchip.hike{border-color:var(--serious);color:var(--serious);font-weight:600}
.vchip.cut{border-color:var(--series-1);color:var(--series-1);font-weight:600}

/* ---------- 措辭熱力圖 ---------- */
.heatwrap{overflow-x:auto;-webkit-overflow-scrolling:touch;margin-top:4px}
/* 全站 table{width:100%} 會把這張表撐到卡片寬，多出來的空間全被
   自動版面塞進第一欄——標籤因此跟自己那一列的格子隔了七百多 px，
   看起來像各自獨立的兩塊。改成內容寬即可，太寬時由 .heatwrap 捲動。 */
.heat{border-collapse:separate;border-spacing:3px;font-size:12px;
  width:max-content;min-width:0;max-width:100%}
.heat th{font-weight:500;color:var(--muted);font-size:11.5px;padding:2px 4px;
  white-space:nowrap;text-align:center;border:none}
.heat th.rowhead{text-align:left;position:sticky;left:0;background:var(--surface-1);
  padding-right:9px;min-width:132px;z-index:1}
.heat td{width:30px;height:26px;text-align:center;border-radius:5px;border:none;
  font-variant-numeric:tabular-nums;padding:0}
.heat td.h0{background:var(--surface-2);color:var(--muted)}
.heat td.h1{background:rgba(42,120,214,.28);color:var(--text-primary)}
/* 55% 藍上放白字只有 2.16:1，遠低於 WCAG 的 4.5。中間色階改用深色字，
   最深的那一階把底色加深到 95% 才撐得起白字。 */
.heat td.h2{background:rgba(42,120,214,.5);color:var(--text-primary)}
.heat td.h3{background:rgba(28,86,158,.97);color:#fff}

/* ---------- 體制頁籤（純 CSS，不依賴 JS）----------
   三張九宮格各一個 radio。選中的那個把對應的 .rpanel 顯示出來。
   用 :checked 加 ~ 相鄰選擇器，沒有 JS 也能切；鍵盤操作由 radio 原生支援。 */
.rtabs{margin-top:4px}
.rtab-in{position:absolute;opacity:0;pointer-events:none;width:0;height:0}
/* 頁籤是這一頁唯一的互動元件，觸控目標要有 44px（先前是 40.8px）。 */
.rtab{display:inline-block;font-size:13px;font-weight:600;cursor:pointer;
  padding:11px 14px;border-radius:9px;border:1px solid var(--border);
  background:var(--surface-1);color:var(--text-secondary);
  margin:0 6px 10px 0;white-space:nowrap}
.rtab:hover{border-color:var(--text-secondary);color:var(--text-primary)}
.rtab-in:checked + .rtab{background:var(--text-primary);color:var(--surface-1);
  border-color:var(--text-primary)}
/* 鍵盤 focus 要看得見——radio 本身是隱藏的，所以把外框畫在 label 上 */
.rtab-in:focus-visible + .rtab{outline:2px solid var(--series-1);outline-offset:2px}
.rt-now{display:inline-block;margin-left:6px;font-size:10.5px;font-weight:700;
  padding:0 5px;border-radius:4px;background:var(--surface-2);
  color:var(--text-secondary)}
.rtab-in:checked + .rtab .rt-now{background:rgba(255,255,255,.22);color:#fff}
.rpanels{position:relative}
.rpanel{display:none}
/* 第 n 個 radio 選中 → 顯示第 n 個 panel */
.rtabs > .rtab-in:nth-of-type(1):checked ~ .rpanels > .rpanel:nth-child(1),
.rtabs > .rtab-in:nth-of-type(2):checked ~ .rpanels > .rpanel:nth-child(2),
.rtabs > .rtab-in:nth-of-type(3):checked ~ .rpanels > .rpanel:nth-child(3){display:block}
.rt-hypo{font-size:12.5px;line-height:1.75;color:var(--text-secondary);
  background:var(--surface-2);border-left:2px solid var(--warning);
  border-radius:0 8px 8px 0;padding:9px 12px;margin:0 0 12px}

/* 目前這一格在三種體制下分別是什麼 */
.rcmp-box{margin-top:16px;padding-top:14px;border-top:1px solid var(--border)}
.rcmp{display:grid;grid-template-columns:76px 1fr auto;align-items:center;
  gap:10px;padding:8px 10px;border-radius:8px}
.rcmp.on{background:var(--surface-2)}
.rcmp-k{font-size:12.5px;color:var(--muted)}
.rcmp-v{font-size:14px;font-weight:700}
.rcmp-v.hawkish{color:var(--serious)} .rcmp-v.dovish{color:var(--series-1)}
.rcmp-v.neutral{color:var(--text-secondary)}
.rcmp-l{font-size:12px;color:var(--muted);white-space:nowrap}
.cflag{color:var(--warning);font-weight:700}

/* ---------- 情境九宮格 ---------- */
.sgrid{display:grid;grid-template-columns:auto repeat(3,1fr);gap:5px;margin-top:4px;
  font-size:12px}
.sgrid .axis{color:var(--muted);font-size:12px;display:flex;align-items:center;
  justify-content:center;padding:4px 3px;text-align:center}
.sgrid .axis.row{writing-mode:horizontal-tb;min-width:40px}
/* 手機上 .sdesc 是隱藏的，min-height 若還留著桌機的高度，
   九格會各空掉六成，白白多出四百多 px 的捲動。 */
.scell{background:var(--surface-2);border:1px solid transparent;border-radius:9px;
  padding:9px 8px;min-height:0}
.scell .sname{font-size:12.5px;font-weight:700;line-height:1.4}
/* 複合情境名的限定語（「：通膨優先」）：小一級、獨立一行。
   主情境與「哪一邊優先」是兩層資訊，同一級字時會被讀成一個長字串。 */
.scell .sn-qual{display:block;font-size:11px;font-weight:600;
  color:var(--text-secondary);line-height:1.35;margin-top:1px}
.scell.on .sn-qual{color:inherit}
.scell .sdesc{font-size:12px;color:var(--muted);margin-top:4px;line-height:1.5;
  display:none}
@media(min-width:760px){.scell{padding:12px 11px;min-height:96px}
  .scell .sname{font-size:13.5px}.scell .sdesc{display:block}}
/* 會隨體制改變的三格：右上角一個小記號。
   其餘六格不管誰優先都一樣，讀者不必為它們擔心重心翻轉。 */
.scell.conflict{position:relative}
.scell.conflict::after{content:"◆";position:absolute;top:5px;right:6px;
  font-size:9px;color:var(--warning)}
.scell.on{border-color:var(--text-primary);background:var(--surface-1);
  box-shadow:0 0 0 2px var(--text-primary) inset}
.scell.on .sname{color:var(--text-primary)}
.scell.hawkish .sname{color:var(--serious)}
.scell.dovish .sname{color:var(--series-1)}
.scell.neutral .sname{color:var(--text-secondary)}
.sbadge{display:inline-block;font-size:11px;font-weight:700;margin-top:6px;
  padding:1px 6px;border-radius:5px;background:var(--text-primary);color:var(--surface-1)}
/* 手機：「目前位置」四個字自己佔一整行，會把所在的那一列撐到其他列的
   兩倍半高——而那一列本來就因為情境名較長而偏高，兩件事疊起來整張
   格子看起來是歪的。窄螢幕改成不畫這行字：格子已經有反白底 ＋ 粗框
   ＋ 內陰影三重標示，徽章只是把同一件事再說一次。
   圖說那一行會告訴讀者「反白粗框那一格是目前位置」，語意不會遺失。 */
@media(max-width:759px){.scell .sbadge{display:none}}
/* 圖說裡的小圖例：把樣式做得跟格子一樣，讀者不必猜「反白粗框」長怎樣 */
.lg-on{background:var(--surface-1);color:var(--text-primary);font-weight:700;
  box-shadow:0 0 0 2px var(--text-primary) inset;border-radius:5px;
  padding:1px 5px}
/* .sbadge.alt 已刪除：那是舊的「結論已依重心修正」徽章，
   三張格子之後沒有任何頁面再產生它。 */

/* ---------- 觸發條件 ---------- */
.trig{display:grid;grid-template-columns:1fr auto;gap:6px 12px;font-size:13px;
  padding:11px 0;border-bottom:1px solid var(--grid);align-items:baseline}
.trig:last-child{border-bottom:none}
.trig .tname{font-weight:600}
.trig .tnow{font-size:12px;color:var(--muted);grid-column:1/-1;margin-top:-4px}
.trig .tdist{font-variant-numeric:tabular-nums;color:var(--text-secondary);
  white-space:nowrap}
.trig.met .tdist{color:var(--critical);font-weight:700}
.trig .tbind{font-size:10.5px;font-weight:700;color:var(--warning);
  border:1px solid var(--warning);border-radius:4px;padding:0 5px;margin-left:6px;
  vertical-align:1px;white-space:nowrap}

/* ---------- 折線圖（刻度用 HTML，避免文字被等比縮小） ---------- */
/* 參考線只畫「資料實際的最高／最低值」，各附數值標籤——
   之前的背景中線落在留白後區間的 50%，不對應任何數值，已移除。 */
/* 右邊留 5px：最新值的圓點是 8px、以最後一點為圓心，
   在時間序列的右端會有一半（4px）超出繪圖區。留白比裁掉好，
   裁掉會讓最新的那一點看起來比實際低。 */
.lwrap{margin-top:6px;padding-right:5px}
.lplot{position:relative;border-left:1px solid var(--grid);
  border-bottom:1px solid var(--grid)}
/* 高度由每張圖自己用 style 指定（charts.line_chart 的 height 參數）。
   這裡寫死 150px 會讓要求 120px 的圖被拉高——SVG 是 preserveAspectRatio="none"，
   拉高不會留白，而是把整條線縱向拉長，形狀因此失真。 */
.lchart{display:block;width:100%}
/* 最高／最低值標籤：加不透明底色，讓它壓在線上時仍讀得出來。
   純文字陰影在深色線條上仍會糊成一團。 */
.glab{position:absolute;left:4px;font-size:11.5px;color:var(--muted);
  line-height:1;font-variant-numeric:tabular-nums;pointer-events:none;
  background:var(--surface-1);padding:1px 4px;border-radius:4px;
  box-shadow:0 0 0 1px var(--surface-1)}
/* 最新值的圓點：疊在 SVG 之上，才不會被 preserveAspectRatio="none" 壓扁，
   也不會在右邊界被裁掉一半 */
.ldot{position:absolute;width:8px;height:8px;border-radius:50%;
  transform:translate(-50%,-50%);box-shadow:0 0 0 2px var(--surface-1);
  pointer-events:none}
.lmark{position:absolute;top:3px;transform:translateX(-50%);font-size:11.5px;
  color:var(--muted);white-space:nowrap;pointer-events:none;
  text-shadow:0 0 4px var(--surface-1),0 0 4px var(--surface-1)}
.lxaxis{display:flex;justify-content:space-between;flex-wrap:wrap;gap:6px;
  font-size:12px;color:var(--muted);margin-top:7px;
  font-variant-numeric:tabular-nums}
.lxaxis b{color:var(--text-primary);font-size:12.5px}

/* ---------- 本期變化摘要 ---------- */
.chg{background:var(--surface-1);border:1px solid var(--border);border-radius:13px;
  padding:17px 16px;box-shadow:var(--shadow);margin-top:13px}
@media(min-width:760px){.chg{padding:20px 22px}}
.chg .ctitle{font-size:12.5px;color:var(--muted)}
/* 零變化時的單行版本 */
.chg.quiet{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:baseline;
  padding:12px 16px;font-size:13.5px}
.chg.quiet .ctitle{font-size:12px}
.chg .chead{font-size:19px;font-weight:700;margin-top:7px;line-height:1.5}
@media(min-width:760px){.chg .chead{font-size:21px}}
.chg.moved .chead{color:var(--serious)}
.clist{display:grid;grid-template-columns:1fr;gap:7px;margin-top:14px}
@media(min-width:700px){.clist{grid-template-columns:1fr 1fr}}
.citem{display:flex;gap:8px;align-items:baseline;font-size:13.5px;
  background:var(--surface-2);border-radius:8px;padding:9px 11px;line-height:1.6}
.citem .cmark{font-size:11px;font-weight:700;flex-shrink:0}
.citem.new .cmark{color:var(--serious)}
.citem.gone .cmark{color:var(--series-1)}
.citem .cmod{font-size:11px;color:var(--muted);flex-shrink:0}
.citem .clean{font-size:11px;font-weight:700;flex-shrink:0;margin-left:auto}
.citem .clean.hawkish{color:var(--serious)}
.citem .clean.dovish{color:var(--series-1)}
.cmoves{margin-top:14px;padding-top:12px;border-top:1px solid var(--grid)}
.cmove{display:grid;grid-template-columns:1fr auto;gap:4px 12px;font-size:13px;
  padding:8px 0;border-bottom:1px solid var(--grid);align-items:baseline}
.cmove:last-child{border-bottom:none}
.cmove .cm-val{font-variant-numeric:tabular-nums;color:var(--text-secondary)}
.cmove .cm-delta{font-weight:700;font-variant-numeric:tabular-nums}
.cmove .cm-delta.up{color:var(--serious)} .cmove .cm-delta.down{color:var(--series-1)}

/* ---------- 近 N 期數值列 ---------- */
/* 六格等寬。欄寬用 max-content 當下限，格子才不會被壓到互相疊字；
   單位已經抽到 .munit 只寫一次，所以六格在 390px 上也塞得下。 */
.mwrap{margin-top:10px;border-top:1px solid var(--grid);padding-top:9px}
.munit{font-size:11px;color:var(--muted);text-align:right;margin-bottom:3px}
.mseries{display:grid;grid-auto-flow:column;
  grid-auto-columns:minmax(max-content,1fr);gap:2px;
  overflow-x:auto;scrollbar-width:thin}
.mcell{text-align:center;padding:2px 2px;border-radius:5px;min-width:0}
.mcell.last{background:var(--surface-2)}
/* KPI 卡在桌機四欄下內容寬只有 218px。字級再大一點，
   最寬的那張卡（參與率 61.9%、日期帶年份）就會有一格被切掉半個字，
   而被切掉的數字會讀成另一個數字，那比字小更糟。 */
.mval{font-size:11px;font-variant-numeric:tabular-nums;color:var(--text-secondary);
  line-height:1.3;white-space:nowrap}
.mcell.last .mval{color:var(--text-primary);font-weight:700}
.mdate{font-size:10.5px;color:var(--muted);margin-top:2px;white-space:nowrap}

/* ---------- 狀態軌跡條 ---------- */
.sstrip{display:flex;gap:2px;margin-top:9px}
.sq{flex:1;height:7px;border-radius:2px;background:var(--surface-2)}
.sq.good{background:var(--good)} .sq.warning{background:var(--warning)}
.sq.critical{background:var(--critical)} .sq.unknown{background:var(--muted-bar)}
.sstrip-note{font-size:11px;color:var(--muted);margin-top:4px}

/* ---------- 資料截止日籤 ---------- */
.asof{display:inline-block;font-size:11px;color:var(--muted);
  border:1px solid var(--border);border-radius:4px;padding:0 5px;margin-left:6px;
  vertical-align:2px;font-variant-numeric:tabular-nums;white-space:nowrap}

/* ---------- 頁內錨點導覽 ---------- */
nav.anchors{position:sticky;top:0;z-index:8;display:flex;gap:2px;overflow-x:auto;
  background:var(--page);padding:8px 0 9px;margin:12px 0 0;
  scrollbar-width:none;box-shadow:0 6px 8px -6px rgba(0,0,0,.10)}
nav.anchors::-webkit-scrollbar{display:none}
nav.anchors a{font-size:12.5px;color:var(--text-secondary);text-decoration:none;
  padding:10px 11px;border-radius:7px;white-space:nowrap;flex-shrink:0;
  background:var(--surface-1);border:1px solid var(--border)}
nav.anchors a:hover{color:var(--text-primary);border-color:var(--text-secondary)}
.card h2{scroll-margin-top:60px}

/* ---------- 意外值 ---------- */
.surp{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:4px}
@media(min-width:760px){.surp{gap:10px}}
/* 三格會被拉成同高（最高那格有徽章與註解），其餘兩格因此上半滿、
   下半空。改成垂直置中，視覺重量才平均。 */
.sbox{display:flex;flex-direction:column;justify-content:center;
  background:var(--surface-2);border-radius:9px;padding:12px 8px;
  border:1px solid var(--border);text-align:center}
@media(min-width:760px){.sbox{padding:12px 11px}}
.sbox .sl{font-size:12px;color:var(--muted)}
.sbox .sv{font-size:19px;font-weight:700;margin-top:5px;
  font-variant-numeric:tabular-nums;white-space:nowrap}
@media(min-width:760px){.sbox .sv{font-size:20px}}
.sbox .su{font-size:12px;color:var(--muted);font-weight:400;margin-left:2px}
.sbox.beat .sv{color:var(--good)} .sbox.miss .sv{color:var(--critical)}
.sbadge2{display:inline-block;font-size:11px;font-weight:700;border-radius:6px;
  padding:3px 9px;margin-top:9px}
.sbadge2.beat{background:rgba(7,124,7,.13);color:#036b03}
.sbadge2.miss{background:rgba(194,47,47,.13);color:#ad2929}
.sbadge2.inline{background:var(--surface-2);color:var(--muted)}
.sbox .szn{font-size:11px;color:var(--muted);margin-top:5px;
  font-variant-numeric:tabular-nums}
"""

JS = """
(function(){
  // 手機上預設收合標記為 data-m-collapse 的區塊，把首屏壓短
  if(window.innerWidth < %%BP%%){
    document.querySelectorAll('details[data-m-collapse]').forEach(function(d){
      d.removeAttribute('open');
    });
  }
  // 導覽列在窄螢幕上是橫向捲動的。目前所在的那一頁若排在後面，
  // 進站時會停在可視範圍外——讀者看不到自己在哪，也不知道還有別的分頁。
  // 把它捲進視野（只捲導覽列自己，不動整頁）。
  document.querySelectorAll('nav.site,nav.anchors').forEach(function(nav){
    var cur=nav.querySelector('a.on'); if(!cur)return;
    var want=cur.offsetLeft-(nav.clientWidth-cur.offsetWidth)/2;
    if(nav.scrollWidth>nav.clientWidth)nav.scrollLeft=Math.max(0,want);
  });
  // 近 N 期數值列在窄卡片裡會超出可視範圍。捲到最右邊，
  // 讓「最新一期」那一格（.mcell.last）一定看得到——
  // 停在最左邊等於把整列裡最重要的那個數字藏起來。
  document.querySelectorAll('.mseries').forEach(function(m){
    if(m.scrollWidth>m.clientWidth)m.scrollLeft=m.scrollWidth;
  });
  var t=document.getElementById('tip');
  document.addEventListener('mouseover',function(e){
    var el=e.target.closest('[data-tip]'); if(!el||!t)return;
    t.textContent=el.getAttribute('data-tip'); t.style.opacity=1;
  });
  document.addEventListener('mousemove',function(e){
    if(!t||t.style.opacity!=='1')return;
    var x=e.clientX+14,y=e.clientY-34;
    if(x+t.offsetWidth>window.innerWidth-8)x=e.clientX-t.offsetWidth-14;
    if(y<8)y=e.clientY+22;
    t.style.left=x+'px'; t.style.top=y+'px';
  });
  document.addEventListener('mouseout',function(e){
    if(t&&e.target.closest('[data-tip]'))t.style.opacity=0;
  });
})();
""".replace("%%BP%%", str(MOBILE_BREAKPOINT))


def _nav(active: str) -> str:
    out = []
    for path, name, done in NAV:
        cls = []
        if path == active:
            cls.append("on")
        if not done:
            cls.append("soon")
        c = f' class="{" ".join(cls)}"' if cls else ""
        out.append(f'<a href="{path}"{c}>{esc(name)}</a>')
    return f'<nav class="site">{"".join(out)}</nav>'


def _anchor_nav(body: str) -> str:
    """
    從內文的 <h2 id="..."> 自動產生頁內導覽。
    頁面很長時沒有導覽會很難跳，這條在捲動時固定在頂端。
    """
    import re
    items = re.findall(r'<h2 id="([^"]+)"[^>]*>(.*?)</h2>', body, re.S)
    if len(items) < 3:
        return ""
    links = "".join(
        f'<a href="#{i}">{re.sub(r"<[^>]+>", "", t).strip()}</a>' for i, t in items
    )
    return f'<nav class="anchors">{links}</nav>'


def page(title: str, active: str, body: str, subtitle: str = "",
         footer: str = "", banner: str = "") -> str:
    """組出一個完整的自足 HTML 頁面。"""
    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex, nofollow, noarchive">
<meta name="color-scheme" content="light">
<title>{esc(title)}｜美國總經儀表板</title>
<style>{CSS}</style>
</head>
<body>
<div class="viz-root">

<header class="top">
  <h1>{esc(title)}</h1>
  <div class="sub">{subtitle}</div>
</header>

{_nav(active)}
{banner}
{_anchor_nav(body)}
{body}

<footer>{footer}</footer>

</div>
<div id="tip"></div>
<script>{JS}</script>
</body>
</html>"""


def soon_page(title: str, active: str, what: str, when: str) -> str:
    body = f"""<div class="soonbox">
  <h3>{esc(title)} — 建置中</h3>
  <p>{esc(what)}</p>
  <p style="margin-top:14px;color:var(--muted)">預計階段：{esc(when)}</p>
</div>"""
    return page(title, active, body, subtitle="尚未建置")


def next_cpi_release(after: dt.date | None = None) -> dt.date:
    """
    估算下一次 CPI 發布日。

    BLS 的慣例是次月的第 10–15 天之間，實務上多落在第二週的週二至週四。
    這裡取「次月第 12 天，遇週末往後推到週一」——跟就業報告的
    「第一個週五」一樣是慣例推估，不是官方行事曆，畫面上會標明是預估。
    """
    after = after or dt.date.today()

    def nth(y: int, m: int) -> dt.date:
        d = dt.date(y, m, 12)
        while d.weekday() >= 5:              # 週末往後推
            d += dt.timedelta(days=1)
        return d

    d = nth(after.year, after.month)
    if d <= after:
        y, m = ((after.year + 1, 1) if after.month == 12
                else (after.year, after.month + 1))
        d = nth(y, m)
    return d


def next_first_friday(after: dt.date | None = None) -> dt.date:
    """
    估算下一次就業報告發布日（慣例為每月第一個週五）。

    注意要先看**本月**的第一個週五：月初執行時（1 號到第一個週五之間），
    下一份報告就在幾天後，不能直接跳到下個月——否則每個月初都會
    顯示「約 31 天後」的錯誤推估。

    這是慣例推估，不是官方行事曆；遇假日或 BLS 調整會有偏差，
    畫面上一律標示為「預估」。
    """
    after = after or dt.date.today()

    def first_friday(y: int, m: int) -> dt.date:
        d = dt.date(y, m, 1)
        while d.weekday() != 4:
            d += dt.timedelta(days=1)
        return d

    d = first_friday(after.year, after.month)
    if d <= after:                       # 本月的已過 → 下個月
        y, m = ((after.year + 1, 1) if after.month == 12
                else (after.year, after.month + 1))
        d = first_friday(y, m)
    return d
