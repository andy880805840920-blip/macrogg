# 「接下來看什麼」行事曆的回歸測試（不打網路）
#
# 釘住：來源優先序（FRED → yaml → 慣例）、標售的 API＋暫定表接續、
# 本週／下週分組、已發布場次移除、台灣時間換算（夏令／冬令）、
# 每週重複事件只說明一次、首頁渲染、焦點區事件字典。
import sys
import pathlib
import datetime as dt

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src import clock                                       # noqa: E402
from src.analysis import watch_calendar as wc               # noqa: E402

ok = True
TPE = clock.TAIPEI


def check(name, cond, detail=""):
    global ok
    print(("通過 " if cond else "失敗 "), name, ("— " + str(detail)[:120]) if detail else "")
    ok = ok and bool(cond)


TODAY = dt.date(2026, 10, 4)                                # 週日（台北）
CAL = {"cpi": {"2026-09": "2026-10-14"},
       "ppi": {"2026-09": "2026-10-15"},
       "jolts": {"2026-08": "2026-09-29", "2026-09": "2026-11-03"},
       "retail": {"2026-09": "2026-10-15"},
       "auction_10y": {"2026-10": "2026-10-07", "2026-11": "2026-11-10"},
       "auction_30y": {"2026-10": "2026-10-08"}}

# ① FRED 有未來日期 → 整組用 FRED；沒有 → yaml；都沒有 → 慣例（就業／CPI／失業金）
s = wc.merge_schedule({"cpi": ["2026-10-14"],
                       "claims": ["2026-10-01", "2026-10-08", "2026-10-15"]},
                      CAL, {}, TODAY)
check("① CPI 取 FRED", s["cpi"] == [("2026-10-14", wc.SRC_FRED)], s.get("cpi"))
check("①b PPI 取 yaml", s["ppi"] == [("2026-10-15", wc.SRC_YAML)])
check("①c 失業金含三天內剛發布的（給焦點區）＋之後的",
      [d for d, _ in s["claims"]] == ["2026-10-01", "2026-10-08", "2026-10-15"])
check("①d 就業報告無來源 → 慣例推估（11 月第一個週五）",
      s["employment"] == [("2026-11-06", wc.SRC_CONV)], s.get("employment"))
check("①e JOLTS 舊的（9/29，超過三天）不列",
      s["jolts"] == [("2026-11-03", wc.SRC_YAML)], s.get("jolts"))
s2 = wc.merge_schedule({}, {}, {}, TODAY)
check("①f 全無來源：失業金推每週四",
      [d for d, _ in s2["claims"]] == ["2026-10-08", "2026-10-15", "2026-10-22"]
      and s2["claims"][0][1] == wc.SRC_CONV)
check("①g 全無來源：沒有慣例可推的（PPI、GDP）就不列",
      "ppi" not in s2 and "gdp" not in s2)

# ② 標售：API 已公告的優先，超出公告範圍才接 yaml 暫定表
s3 = wc.merge_schedule({}, CAL, {"auction_10y": ["2026-10-07"]}, TODAY)
check("② 10Y：API 10/7＋暫定表 11/10",
      s3["auction_10y"] == [("2026-10-07", wc.SRC_TSY),
                            ("2026-11-10", wc.SRC_TSY_TENT)], s3["auction_10y"])
check("②b 30Y 只有暫定表", s3["auction_30y"] == [("2026-10-08", wc.SRC_TSY_TENT)])


class _R:
    def __init__(self, rows):
        self.rows = rows

    def raise_for_status(self):
        pass

    def json(self):
        return {"data": self.rows}


_rows = [
    {"security_type": "Note", "security_term": "9-Year 10-Month", "auction_date": "2026-10-07"},
    {"security_type": "Bond", "security_term": "29-Year 10-Month", "auction_date": "2026-10-08"},
    {"security_type": "Note", "security_term": "3-Year", "auction_date": "2026-10-06"},
    {"security_type": "Bond", "security_term": "20-Year", "auction_date": "2026-10-20"},
    {"security_type": "Note", "security_term": "10-Year", "auction_date": "2024-11-05"},
]
_a = wc.fetch_auctions(_get=lambda u, p: _R(_rows), today=TODAY)
check("③ 財政部 API：增額發行（9-Year 10-Month）也算 10Y；3Y／20Y／過期的不算",
      _a == {"auction_10y": ["2026-10-07"], "auction_30y": ["2026-10-08"]}, _a)


def _boom(u, p):
    raise OSError("network down")


check("③b API 失敗回 {}", wc.fetch_auctions(_get=_boom, today=TODAY) == {})

# ④ 台灣時間：10/14 夏令（08:30 EDT＝20:30）；11/10 冬令（08:30 EST＝21:30）；
#    FOMC 14:00 EDT＝隔天 02:00
check("④ 夏令 08:30 → 台灣 20:30",
      wc.taipei_time(dt.date(2026, 10, 14), (8, 30)).strftime("%m-%d %H:%M") == "10-14 20:30")
check("④b 冬令 08:30 → 台灣 21:30",
      wc.taipei_time(dt.date(2026, 11, 10), (8, 30)).strftime("%m-%d %H:%M") == "11-10 21:30")
check("④c FOMC 14:00 → 台灣隔天 02:00",
      wc.taipei_time(dt.date(2026, 10, 28), (14, 0)).strftime("%m-%d %H:%M") == "10-29 02:00")

# ⑤ watch_rows：週一 07:00（台北）執行
NOW = dt.datetime(2026, 10, 5, 7, 0, tzinfo=TPE)
sched = wc.merge_schedule({"claims": ["2026-10-08", "2026-10-15", "2026-10-22"],
                           "cpi": ["2026-10-14"]}, CAL,
                          {"auction_10y": ["2026-10-07"],
                           "auction_30y": ["2026-10-08"]}, NOW.date())
rows = wc.watch_rows(sched, fomc_next="2026-10-28", now=NOW)
keys = [(r["group"], r["key"], r["date"].isoformat()) for r in rows]
check("⑤ 本週：10Y 標售 10/7、失業金 10/8、30Y 標售 10/8（依台灣時間排序）",
      keys[:3] == [("本週　10/05–10/11", "auction_10y", "2026-10-07"),
                   ("本週　10/05–10/11", "claims", "2026-10-08"),
                   ("本週　10/05–10/11", "auction_30y", "2026-10-08")], keys)
check("⑤b 下週：CPI 10/14 在 PPI、零售、失業金 10/15 之前",
      [k for g, k, _ in keys if g.startswith("下週")][:1] == ["cpi"]
      and {k for g, k, _ in keys if g.startswith("下週")} >= {"cpi", "ppi", "retail", "claims"}, keys)
check("⑤c 下下週（10/22 失業金、10/28 FOMC）不列",
      all(r["date"] <= dt.date(2026, 10, 18) for r in rows))
_cl = [r for r in rows if r["key"] == "claims"]
check("⑤d 失業金第二次出現不重複說明", _cl[0]["desc"] and _cl[1]["desc"] == "")
_cpi = [r for r in rows if r["key"] == "cpi"][0]
check("⑤e CPI 高影響、標示「10/14（三）」「台灣 20:30」",
      _cpi["impact"] == "high" and _cpi["label"] == "10/14（三）"
      and _cpi["when"] == "台灣 20:30", (_cpi["label"], _cpi["when"]))
check("⑤f 標售中影響、出處＝財政部公告",
      rows[0]["impact"] == "mid" and rows[0]["src"] == wc.SRC_TSY)

# ⑥ 當晚 22:45 執行：20:30 已發布的 CPI 不列、標「今天」的只剩還沒到的
NIGHT = dt.datetime(2026, 10, 14, 22, 45, tzinfo=TPE)
r2 = wc.watch_rows(sched, fomc_next="2026-10-28", now=NIGHT)
check("⑥ 已發布的 CPI（台灣 20:30）在 22:45 不列", all(r["key"] != "cpi" for r in r2))
r3 = wc.watch_rows(sched, now=dt.datetime(2026, 10, 14, 16, 0, tzinfo=TPE))
_c3 = [r for r in r3 if r["key"] == "cpi"][0]
check("⑥b 16:00 執行：CPI 標「今天 台灣 20:30」", _c3["when"] == "今天 台灣 20:30", _c3["when"])
r4 = wc.watch_rows({}, fomc_next="2026-10-28",
                   now=dt.datetime(2026, 10, 26, 7, 0, tzinfo=TPE))
check("⑥c FOMC 標「台灣隔天 02:00」、高影響",
      r4 and r4[0]["when"] == "台灣隔天 02:00" and r4[0]["impact"] == "high",
      r4 and r4[0])

# ⑥d 週日執行：本週已過，改看下週＋下下週（含 10/14 CPI）
r5 = wc.watch_rows(sched, now=dt.datetime(2026, 10, 4, 7, 0, tzinfo=TPE))
_g5 = sorted({r["group"] for r in r5})
check("⑥d 週日：分組＝下週 10/05–10/11、下下週 10/12–10/18",
      _g5 == ["下下週　10/12–10/18", "下週　10/05–10/11"]
      and any(r["key"] == "cpi" for r in r5), _g5)

# ⑦ 焦點區事件字典：含剛發布的、FOMC 從 config 讀
ev = wc.event_dates(sched, ["2026-10-28", "2026-12-09"])
check("⑦ event_dates", ev["cpi"] == ["2026-10-14"] and ev["fomc"] == ["2026-10-28", "2026-12-09"])

# ⑧ 首頁渲染：分組標題、影響小標、說明只出現一次
import src.pages.home as home                               # noqa: E402
_orig = clock.now
clock.now = lambda: NOW
clock.today = lambda: NOW.date()
try:
    html = home._watch_rows({"_schedule": sched,
                             "fomc": {"next_meeting": {"date": "2026-10-28"}}}, None)
finally:
    clock.now = _orig
check("⑧ 本週／下週分組標題各一次",
      html.count('<div class="hn-group">本週　10/05–10/11</div>') == 1
      and html.count('<div class="hn-group">下週　10/12–10/18</div>') == 1)
check("⑧b 影響小標（高＋中都有）",
      'class="hn-imp high">高<' in html and 'class="hn-imp mid">中<' in html)
check("⑧c 失業金說明只出現一次", html.count("兩次就業報告之間最即時") == 1)
check("⑧d 台灣時間與星期", "10/14（三）" in html and "台灣 20:30" in html)

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
