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
_m7 = h7.split('<div class="fs-more" hidden>', 1)[-1].split('</div></div><script>', 1)[0]
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
check("⑧ 列表・月曆改小字切換（標題列）", '<p class="wv-sw"><label for="hm-view-list">列表</label>・<label for="hm-view-cal">月曆</label></p>' in _hs8
      and 'class="hm-view-sw"' not in _hs8)
check("⑧ 列表分類有符號、沒有「全部」", '<i class="mk mk-d"></i>數據' in w8 and '<em class="mk-h">休</em>休市' in w8
      and "hm-cat-all" not in w8 and ">全部<" not in w8)
check("⑧ 不再有大卡片與「其他發布」", "其他發布" not in w8 and 'class="wv-ev"' in w8)
check("⑧ 日期列「10/29（四）今天」", '10/29（四）<span>今天</span>' in w8)
check("⑧ GDP 不重複寫成「GDP 預估」", "GDP 預估" not in w8)
check("⑧ 發債名稱不加「標售・」前綴", "標售・7 年期" not in w8 and "7 年期公債標售" in w8)
check("⑧ 月曆分類是顯示／隱藏、標籤為「官員」", 'type="checkbox"' in w8 and "點類別隱藏／顯示" in w8 and ">官員<" in w8)
check("⑧ 月曆當天明細與列表同一套列", 'hc-k-d' in w8 and w8.count('class="wv-dh"') >= 2)

clock.now, clock.today = _now0, _today0
print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
