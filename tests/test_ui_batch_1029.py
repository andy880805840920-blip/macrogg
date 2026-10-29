"""2026-10-29 批次：主軸保留 7 天（下拉選單）、接下來看什麼補 FOMC（決議、紀要、靜默期）、
政策訊號單欄色條、投票委員依立場、決議卡三列、期中選舉固定說明。"""
import sys, pathlib, datetime as dt, re
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import clock                                   # noqa: E402
from src.pages import home, election                    # noqa: E402
from src.analysis import fomc_extra as fx               # noqa: E402
from src.analysis import focus_today as ft              # noqa: E402
from src import fomc_source as fs                       # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過  " if cond else "失敗  ") + name + (f" — {detail}" if detail and not cond else ""))
    ok &= bool(cond)


TPE = clock.TAIPEI
_now0, _today0 = clock.now, clock.today


def setnow(t):
    clock.now = lambda: t
    clock.today = lambda: t.date()


# ① 今日主軸：首頁保留 7 天，日期改成下拉選單（預設今天）
setnow(dt.datetime(2026, 10, 29, 9, 0, tzinfo=TPE))
arch = [{"date": (dt.date(2026, 10, 29) - dt.timedelta(days=i)).isoformat(), "headline": f"h{i}",
         "text": f"主軸{i}\n補充", "links": [], "weekly": i == 4} for i in range(8)]
f = {"yields": [], "links": [], "fedwatch": None, "layout": "main", "headline": "h0", "rate_note": "",
     "text": "主軸0\n補充", "text_source": "model-content", "topics": [], "chips": [], "archive": arch}
h = home._focus_strip(f)
check("① ARCHIVE_SHOW＝7", ft.ARCHIVE_SHOW == 7)
check("① 日期是下拉選單、預設今天、共 7 天（今天＋過去 6 天）",
      '<select aria-label="主軸日期">' in h and '<option value="cur" selected>10/29（四）</option>' in h
      and h.count("<option") == 7 and h.count('class="fs-day-p"') == 7, h.count("<option"))
check("① 不再列一排膠囊按鈕", 'data-day="cur" aria-pressed' not in h)
check("① 週日版標「本週回顧」", "（日）　本週回顧" in h)

# ② FOMC：決議（美東 14:00＝台北凌晨）公布前都還是「下次會議」
spans = [(dt.date(2026, 10, 27), dt.date(2026, 10, 28)), (dt.date(2026, 12, 8), dt.date(2026, 12, 9))]
src = fs.FomcSource.__new__(fs.FomcSource)
src.calendar_spans = lambda: spans
setnow(dt.datetime(2026, 10, 28, 23, 30, tzinfo=TPE))
check("② 台北 10/28 晚上：下次會議仍是 10/28（原本漏掉）", src.upcoming_spans(2)[0][1] == dt.date(2026, 10, 28))
setnow(dt.datetime(2026, 10, 29, 1, 0, tzinfo=TPE))
nm = fx.next_meeting_info(spans, clock.today())
check("② 台北 10/29 01:00（決議 02:00 前）：仍是 10/28、倒數 0 天", nm["date"] == "2026-10-28" and nm["days"] == 0, nm)
setnow(dt.datetime(2026, 10, 29, 3, 0, tzinfo=TPE))
check("② 決議公布後換成 12/9", src.upcoming_spans(2)[0][1] == dt.date(2026, 12, 9)
      and fx.next_meeting_info(spans, clock.today())["date"] == "2026-12-09")

# ③ 接下來看什麼：FOMC 決議、會議紀要（數據）、靜默期開始（官員談話）
setnow(dt.datetime(2026, 11, 16, 9, 0, tzinfo=TPE))
ctxs = {"fomc": {"next_meeting": fx.next_meeting_info(spans, clock.today()),
                 "agenda": [{"date": "2026-11-18", "kind": "會議紀要", "who": "", "topic": "x", "time": "2:00 p.m."}]},
        "_schedule": {}, "_calendar": {}, "_watch_extra": {}}
sc = type("S", (), {"triggers": []})()
w = home._hm_watch(ctxs, sc, weeks=4)
check("③ 會議紀要列進來（11/18）", "FOMC 會議紀要" in w)
check("③ 靜默期開始列進來（11/28）", "聯準會靜默期開始" in w and "11/28" in w)
setnow(dt.datetime(2026, 12, 1, 9, 0, tzinfo=TPE))
ctxs["fomc"]["next_meeting"] = fx.next_meeting_info(spans, clock.today())
check("③ FOMC 利率決策進入四週內就列出", "FOMC 利率決策" in home._hm_watch(ctxs, sc, weeks=4))

# ④ 期中選舉：標題下方固定說明，附連結；開票後不顯示
setnow(dt.datetime(2026, 10, 29, 9, 0, tzinfo=TPE))
e = {"election_date": "2026-11-03", "days_to": 5, "date": "2026-10-29",
     "house": {"dem": 0.8, "rep": 0.2, "hist": [], "url": "u", "vol": 1e6},
     "outlook": {"title": "若民主黨同時拿下參眾兩院", "text": "說明文字",
                 "links": [{"t": "ING", "u": "https://think.ing.com/x"}]}}
c = election.election_card(e)
check("④ 標題下方有固定說明與參考連結", "el-outlook" in c and "若民主黨同時拿下參眾兩院" in c and "https://think.ing.com/x" in c)
check("④ 開票後不顯示", "el-outlook" not in election.election_card(dict(e, days_to=-1)))
import yaml                                              # noqa: E402
_el = yaml.safe_load(open(ROOT / "config/focus.yaml", encoding="utf-8"))["election"]["outlook"]
check("④ config 的說明不點名機構、但附連結", "ING" not in _el["text"] and "Schwab" not in _el["text"] and len(_el["links"]) >= 2)

# ⑤ 投票委員立場：手動清單在 config，反對票優先
_fc = yaml.safe_load(open(ROOT / "config/fomc.yaml", encoding="utf-8"))
check("⑤ 立場改成事實優先（10/29 下午）：不再有手動清單", "official_stance" not in _fc)

# ⑥ 公布前檢查只看「那件事」：10/29 PCE 公布前，標題「聯準會維持利率不變」（10/28 已公布）不該被刪
check("⑥ PCE 公布前：FOMC 已公布的結果不算", ft._decided_hits("聯準會維持利率不變 Warsh 宣布每年僅 6 次利率表決", "10/29|pce") == [])
check("⑥ FOMC 公布前：決議用語照樣擋", ft._decided_hits("聯準會決議維持利率不變", "10/28|fomc") != [])
check("⑥ 沒帶種類時維持舊行為", ft._decided_hits("聯準會決議維持利率不變", "10/28") != [])
check("⑥ 沒有對應規則的事件（例：國會證詞）不檢查", ft._decided_hits("聯準會決議維持利率不變", "10/29|testimony") == [])
_src6 = (ROOT / "src/analysis/focus_today.py").read_text(encoding="utf-8")
check("⑥ build 傳入的 preview 帶事件種類", '_preview = f"{_d}|{_k}"' in _src6)

# ⑦ 2026-10-29 晚：總覽清爽化
_css7 = (ROOT / "src/site.py").read_text(encoding="utf-8")
check("⑦ 說明與完整教學縮小、拿掉多餘分隔線、膠囊改底線、快報與選擇指標靠右",
      "html body .learn-more{border-top:0" in _css7 and "html body details.hm-c2-more" in _css7
      and "border-bottom:1.5px solid currentColor" in _css7 and ".fs-head .fs-story-btn{margin-left:auto" in _css7)
f7 = {"yields": [], "links": [{"title": "t", "link": "https://x", "source": "CNBC"}], "fedwatch": None, "layout": "main",
      "headline": "標題", "rate_note": "", "text": "主軸\n補充", "text_source": "model-content", "topics": [], "chips": []}
h7 = home._focus_strip(f7)
_m7 = h7.split('<div class="fs-more fs-clip">', 1)[-1].split('<button type="button" class="fs-tog"', 1)[0]
check("⑦ 品牌與來源說明收進「展開全文」", 'class="fs-brand"' in _m7 and 'class="fs-note"' in _m7 and h7.count('class="fs-brand"') == 1)
check("⑦ 沒有標題（不收合）時品牌照舊放卡片底部", 'class="fs-brand"' in home._focus_strip(dict(f7, headline="")))
from src.pages import forecasts_ui as _FU
_h7 = _FU.section({"releases": {"pce|2026-09": {"key": "pce", "period": "2026-09", "date": "2026-10-29"}}}, dt.date(2026, 10, 29))
check("⑦ 各家預測公布當天也預設收合", 'class="fc-fold" open' not in _h7 and 'class="fc-fold"' in _h7)

# ⑧ 2026-10-29 晚：03「接下來看什麼」列表與月曆一致
from src.analysis import fomc_extra as _fx8
_T8 = dt.datetime(2026, 10, 29, 18, 0, tzinfo=clock.TAIPEI)
clock.now, clock.today = (lambda: _T8), (lambda: _T8.date())
_c8 = {"fomc": {"next_meeting": _fx8.next_meeting_info([(dt.date(2026, 12, 8), dt.date(2026, 12, 9))], _T8.date()), "agenda": []},
       "_schedule": {"pce": [("2026-10-29", "官方行事曆")], "gdp": [("2026-10-29", "官方行事曆")]}, "_calendar": {},
       "_watch_extra": {"consensus": {"pce|2026-10-29": [{"label": "核心 PCE 月增", "forecast": "0.3%", "previous": "0.2%"}],
                                      "gdp|2026-10-29": [{"label": "GDP", "forecast": "3.2%", "previous": "1.5%"}]},
                        "auctions": [{"date": "2026-10-29", "name": "7 年期公債標售", "src": "財政部暫定"}],
                        "speeches": [{"et": "2026-10-31T10:00:00", "name": "Daly", "role": "舊金山聯儲總裁", "kind": "談話"}]}}
w8 = home._hm_watch(_c8, type("S", (), {"triggers": []})(), weeks=4)
_hs8 = (ROOT / "src/pages/home.py").read_text(encoding="utf-8")
check("⑧ 列表｜月曆改成膠囊、預設月曆", '<p class="wv-sw wv-pill"><label for="hm-view-list">列表</label><label for="hm-view-cal">月曆</label></p>' in _hs8
      and 'class="hm-view-sw"' not in _hs8 and 'id="hm-view-cal" class="hm-view-in" checked' in w8)
check("⑧ 列表分類有符號、沒有「全部」", '<i class="mk mk-d"></i>數據' in w8 and '<em class="mk-h">休</em>休市' in w8
      and "hm-cat-all" not in w8 and ">全部<" not in w8)
check("⑧ 不再有大卡片與「其他發布」", "其他發布" not in w8 and 'class="wv-ev"' in w8)
check("⑧ 日期列「10/29（四）今天」", '10/29（四）<span>今天</span>' in w8)
check("⑧ GDP 不重複寫成「GDP 預估」", "GDP 預估" not in w8)
check("⑧ 發債名稱不加「標售・」前綴", "標售・7 年期" not in w8 and "7 年期公債標售" in w8)
check("⑧ 月曆分類是顯示／隱藏、標籤為「官員」", 'type="checkbox"' in w8 and "點類別隱藏／顯示" in w8 and ">官員<" in w8)
check("⑧ 月曆當天明細與列表同一套列", 'hc-k-d' in w8 and w8.count('class="wv-dh"') >= 2)

# ⑨ 2026-10-29 晚：今天已公布的留在原位（不讓本週數據在 20:30 之後整個變空）
_T9 = dt.datetime(2026, 10, 29, 21, 15, tzinfo=clock.TAIPEI)
clock.now, clock.today = (lambda: _T9), (lambda: _T9.date())
from src.analysis import watch_calendar as _wc9
_r9 = _wc9.watch_rows({"pce": [("2026-10-29", "官方行事曆")]}, now=_T9, weeks=4)
_r9k = _wc9.watch_rows({"pce": [("2026-10-29", "官方行事曆")]}, now=_T9, weeks=4, keep_today=True)
check("⑨ watch_rows 預設照舊不列已發布；keep_today 才留著並標 done", _r9 == [] and len(_r9k) == 1 and _r9k[0]["done"])
w9 = home._hm_watch(_c8, type("S", (), {"triggers": []})(), weeks=4)
check("⑨ 總覽：今天已公布的留著、淡化、標「已公布」", 'class="wv-ev wv-done"' in w9 and "已公布" in w9 and "PCE" in w9)
_c9 = dict(_c8, _schedule={"cpi": [("2026-11-10", "官方行事曆")]}, _watch_extra={})
w9b = home._hm_watch(_c9, type("S", (), {"triggers": []})(), weeks=4)
check("⑨ 本週沒有剩下的：說清楚並給「看下週」", "本週剩下沒有排定的附息公債標售或國債回購。" in w9b and 'for="hm-wk-1">看下週 ›' in w9b)
check("⑨ 月曆空白日也標「今天」", '<div class="wv-dh"><b></b><span hidden>今天</span></div>' in w9b)

# ⑩ 2026-10-29 晚：AI 逾時——Anthropic 讀取最多等 120 秒、最多 2 次；Gemini 每顆 90 秒、一次就換
from src.analysis import polish as _pl10
_seen10 = []
_req0 = _pl10.requests.request


class _R10:
    status_code = 200


def _fake10(method, url, **kw):
    _seen10.append(kw.get("timeout"))
    raise _pl10.requests.ReadTimeout("read timed out")


_pl10.requests.request, _sl0 = _fake10, _pl10._SLEEP
_pl10._SLEEP = lambda s: None
try:
    _pl10._http("POST", "https://x", label="t", timeout=(10, 120), tries=2)
except Exception:
    pass
check("⑩ _http 可覆寫等待時間與次數", _seen10 == [(10, 120), (10, 120)])
_seen10.clear()
try:
    _pl10._http("POST", "https://x", label="t")
except Exception:
    pass
check("⑩ 沒指定時照舊（45 秒、3 次）", _seen10 == [45, 45, 45])
_pl10.requests.request, _pl10._SLEEP = _req0, _sl0
check("⑩ 焦點段 AI 呼叫：Anthropic 120 秒×2 次、Gemini 每顆 90 秒×1 次",
      ft.ANTHROPIC_TIMEOUT == (10, 120) and ft.ANTHROPIC_TRIES == 2 and ft.GEMINI_TIMEOUT == (10, 90))

# ⑪ 2026-10-29 晚：核心 PCE 方向、本期變化說法、主軸不重複、今日市場焦點｜今日總覽、六宮格、通膨頁少線
from src.analysis import inflation as _inf11
_S = type("S", (), {})
_s = _S(); _s.pce_core_pace3, _s.pce_core_yoy, _s.pce_core_yoy_prev = 0.15, 3.12, 3.01
check("⑪ 年增上升時不寫「降溫」", _inf11.pce_move(_s) == "持平")
_s.pce_core_yoy_prev = 3.3
check("⑪ 年增下降、三月均月增低於 0.17 才算降溫", _inf11.pce_move(_s) == "降溫")
_s.pce_core_pace3 = 0.24
check("⑪ 三月均月增 0.24（9 月實況）＝持平，跟九宮格同一套", _inf11.pce_move(_s) == "持平")
check("⑪ 通膨頁首卡改用同一套判斷", "_pce_move(s)" in (ROOT / "src/pages/inflation.py").read_text(encoding="utf-8"))
check("⑪ 本期變化：解除改寫成「不再成立」", home._resolved_text("核心 PCE 在降溫：三月年化 2.0%，低於年增 3.0%")
      == "不再成立：核心 PCE 在降溫（上期 三月年化 2.0%，低於年增 3.0%）")
_NOW11 = dt.datetime(2026, 10, 29, 13, 0, tzinfo=dt.timezone.utc)
_I11 = lambda h: (_NOW11 - dt.timedelta(hours=h)).isoformat()   # noqa: E731
_g11 = ft.group_events([
    {"title": "Q3 GDP Revs Up As PCE Inflation Gets Hotter", "source": "Bloomberg", "link": "a", "at": _I11(1)},
    {"title": "Third-quarter U.S. GDP increases a better-than-expected 3.4%", "source": "Reuters", "link": "b", "at": _I11(1)},
    {"title": "Oracle sells $18 billion of bonds to fund AI data centers", "source": "Reuters", "link": "c", "at": _I11(2)}],
    ["GDP", "PCE", "bond"], _NOW11)
_p1, _p2, _ = ft.choose_points(_g11, ["pce", "gdp_adv"])
check("⑪ 重點一同時涵蓋 PCE 與 GDP 時，重點二不再寫 GDP", _p1["lead"]["link"] == "a" and (_p2 is None or _p2["lead"]["link"] == "c"),
      str(_p2 and _p2["lead"]["title"]))
_f11 = {"yields": [], "links": [], "fedwatch": None, "layout": "main", "headline": "標題", "rate_note": "",
        "text": "主軸", "text_source": "model-content", "topics": [], "chips": []}
_fs11 = home._focus_strip(_f11, tabbed=True)
check("⑪ 合併卡裡的焦點：不再有自己的標題列文字", _fs11.startswith('<div class="focus-strip fs-in"><div class="fs-head"><button'))
_fx11 = home._fx_card(_fs11, "<b>總覽</b>")
check("⑪ 合併卡：兩個分頁、預設焦點、記住上次、快報未看加橘點",
      'id="mgx-f" class="mgx-in" checked' in _fx11 and "今日市場焦點<i class=\"mgx-dot\"></i>" in _fx11
      and "fxTab" in _fx11 and ".mgx:has(.fs-story-btn:not([hidden]):not(.seen)) .mgx-dot" in _css7)
check("⑪ 六宮格：手機兩欄、電腦三欄、右上角 ›、摘要一行", ".duo-6 .duo-grid{grid-template-columns:repeat(2,minmax(0,1fr))" in _css7
      and ".duo-6 .duo-grid{grid-template-columns:repeat(3,minmax(0,1fr))}" in _css7 and ".duo-6 .duo-card::after" in _css7
      and "text-overflow:ellipsis" in _css7.split(".duo-6 .duo-sum{", 1)[1].split("}", 1)[0])
_wt = {"today": dt.date(2026, 10, 29), "marks": {"2026-10-30": {"s"}, "2026-10-29": {"d"}}}
_mc = home._mini_cal(_wt)
check("⑪ 03 小月曆：今天深色、過去淡化、有事的日子一個點", '<span class="mc-to">29<i class="mc-d"></i></span>' in _mc
      and '<span class="mc-ps">28</span>' in _mc and '<span class="">30<i class="mc-s"></i></span>' in _mc)
from src.pages import forecasts_ui as _fu11
_fc11 = {"releases": {"pce|2026-09": {"key": "pce", "period": "2026-09", "date": "2026-10-29", "cons": {"core_mom": 0.3},
                                      "clev": {"pce_mom": 0.47, "core_mom": 0.28}, "banks": {},
                                      "actual": {"pce_mom": 0.5, "core_mom": 0.3}},
                      "employment|2026-10": {"key": "employment", "period": "2026-10", "date": "2026-11-06", "banks": {}}}}
_r11, _s11 = _fu11.tile(_fc11, dt.date(2026, 10, 29))
check("⑪ 04 小卡：超出所有預測、還沒公布寫日期；摘要一行", ("PCE 9 月", "超出預測", True) in _r11
      and ("就業 10 月", "11/6 公布", False) in _r11 and _s11 == "PCE 月增 0.5 超出預測", str((_r11, _s11)))
check("⑪ 04 視窗直接展開（沒有收合）", "<details class=\"fc-fold\"" not in _fu11.section(_fc11, dt.date(2026, 10, 29), modal=True))
from src.pages.labor import _kpi_card as _kc11
_k11 = _kc11("核心 PCE 年增率", "3.1%", "", "白話", leans=[("水準：高於目標", "hawkish"), ("本期：比上月 +0.1", "hawkish")],
             en="Core PCE, y/y", compact=True)
check("⑪ 通膨頁關鍵數字：中文標題、狀態變小標籤、沒有逐行判讀", "Core PCE" not in _k11 and '<span class="k-tag haw">比上月 +0.1</span>' in _k11
      and "kj-r" not in _k11)

# ⑫ 2026-10-29 深夜：01 視窗兩塊預設展開、03 小月曆放大、視窗固定高度、電腦版焦點（一列 3 個、預設 6 個、主軸全文）
_h12 = (ROOT / "src/pages/home.py").read_text(encoding="utf-8")
check("⑫ 01 視窗：整體情勢、四大模組預設展開", '<details class="hm-modx hm-briefx" open>' in _h12 and '<details class="hm-modx" open>' in _h12)
_css12 = (ROOT / "src/site.py").read_text(encoding="utf-8")
check("⑫ 六宮格圖區加高（月曆放大）、視窗固定高度", ".duo-6 .duo-map{height:124px" in _css12 and ".duo-sheet{height:86vh}" in _css12
      and ".duo-sheet{height:90vh}" in _css12)
check("⑫ 電腦版：儀表板一列 3 個、主軸在下方", "grid-template-columns:repeat(3,minmax(0,1fr));gap:0;border:1px solid var(--border)" in _css12
      and ".mgx .focus-strip .fs-grid{grid-template-columns:1fr" in _css12)
check("⑫ 電腦版預設多兩個指標：費城半導體、美元指數", home.WIDE_EXTRA_CHIPS == ["sox", "dxy"] and "FS_CONFIG.wideExtra" in home._CHIP_SELECT_JS)
check("⑫ 電腦版今日主軸預設全文", "min-width:760px" in home._FOLD_JS and "收合 ▴" in home._FOLD_JS)
check("⑫ 手機點過的小卡不會一直反灰（hover 只給滑鼠）", "@media(hover:hover){.viz-root:not(#_) .duo-6 .duo-card:hover" in _css12)

# ⑬ 2026-10-29 深夜：合併卡不再有內層卡（.fx-p 跟匯率頁撞名）、小卡內容撐滿寬
_css13 = (ROOT / "src/site.py").read_text(encoding="utf-8")
check("⑬ 合併卡改用 mgx- 前綴，不再套到匯率頁 .fx-p 的外框", 'class="mgx-p mgx-pf"' in home._fx_card("<i>f</i>", "<i>o</i>")
      and ".fx-p,.fx-sp{border:1px solid var(--border)" in _css13 and "fx-p" not in home._fx_card("<i>f</i>", "<i>o</i>"))
check("⑬ 小卡裡的區塊明確撐滿寬（有些瀏覽器的 button 不會）", ".duo-6 .duo-card>span{display:block;width:100%" in _css13
      and "align-items:stretch;width:100%}" in _css13)

clock.now, clock.today = _now0, _today0
print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
