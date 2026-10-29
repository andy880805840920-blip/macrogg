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
      '<select aria-label="主軸日期">' in h and '<option value="cur" selected>今天</option>' in h
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
check("⑤ config/fomc.yaml 有 official_stance，值只有三種",
      _fc.get("official_stance") and set(_fc["official_stance"].values()) <= {"hawkish", "dovish", "neutral"})

clock.now, clock.today = _now0, _today0
print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
