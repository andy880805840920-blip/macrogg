"""2026-10-23：快報「今日數據」只放 48 小時內公布的、日期用官方公布日；FOMC 最新決議不能倒退。"""
import sys, json, pathlib, tempfile, datetime as dt
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.analysis import stories as S        # noqa: E402
from src import fomc_source as fs             # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過  " if cond else "失敗  ") + name + (f" — {detail}" if detail and not cond else ""))
    ok &= bool(cond)


TPE = dt.timezone(dt.timedelta(hours=8))
NOW = dt.datetime(2026, 10, 23, 7, 6, tzinfo=TPE)

# ---- ① 10/22 的實例：FOMC 的「第一次看到」被誤記成 10/22，PPI 是 10/16，初領失業金 10/22 ----
REL = {"fomc": {"month": "2026-09-16", "first_seen": "2026-10-22T15:35:47+08:00"},
       "ppi": {"month": "2026-09", "first_seen": "2026-10-16T17:06:19+08:00"},
       "claims": {"month": "2026-10-17", "first_seen": "2026-10-22T21:07:40+08:00"},
       "inflation": {"month": "2026-09", "first_seen": "2026-10-14T20:50:14+08:00"}}
RD = {"claims": ["2026-10-22", "2026-10-29"], "ppi": ["2026-10-16"], "cpi": ["2026-10-14"]}
CTX = {"fomc": {"latest_date": "2026-09-16", "decision_label": "升息一碼", "rate_range": "3.75–4.00%"},
       "inflation": {"data_month": "2026-09", "kpi": {"core_display": "0.3%", "headline_display": "0.4%"},
                     "ppi": {"mom": 0.7, "period": "2026-09"}},
       "labor": {"claims": {"machine": {"week": "2026-10-17", "ic_now": 228000, "ic_ma": 224500}}},
       "_watch_extra": {"consensus": {"claims|2026-10-22": [{"label": "初領失業金", "forecast": "22.0 萬"}]}}}

o = S.official_at("fomc", None, CTX, RD)
check("① FOMC 官方公布時間＝決策日 14:00 美東", o and o.date().isoformat() == "2026-09-16" and o.hour == 14, o)
c = S.release_candidates(CTX, REL, NOW, RD)
check("② 9/16 的決議不再被當成 10/22 公布；PPI、CPI 超過 48 小時不放 → 只剩初領失業金",
      [x["key"] for x in c] == ["claims"], [x["key"] for x in c])
check("③ 初領失業金：官方公布日 10/22、帶預估", c and c[0]["date"] == "10/22" and c[0]["rows"][0]["actual"] == "22.8 萬"
      and c[0]["rows"][0]["vs"] == "高於預估" and c[0]["rows"][1]["label"] == "4 週平均", c)

# ---- ② 48 小時內有 CPI → CPI 優先，初領失業金排在後面當備選 ----
REL2 = dict(REL, inflation={"month": "2026-10", "first_seen": "2026-11-11T20:45:00+08:00"},
            claims={"month": "2026-11-07", "first_seen": "2026-11-12T21:00:00+08:00"})
RD2 = {"cpi": ["2026-11-11"], "claims": ["2026-11-12"]}
c2 = S.release_candidates(CTX, REL2, dt.datetime(2026, 11, 12, 22, 0, tzinfo=TPE), RD2)
check("④ CPI 在 48 小時內 → CPI 第一、初領失業金第二", [x["key"] for x in c2] == ["inflation", "claims"], [x["key"] for x in c2])
check("⑤ 日期用官方公布日（美東 11/11 08:30），不是第一次看到的時間", c2[0]["date"] == "11/11"
      and c2[0]["at"].startswith("2026-11-11T08:30"), c2[0])
c3 = S.release_candidates(CTX, REL2, dt.datetime(2026, 11, 14, 23, 0, tzinfo=TPE), RD2)
check("⑥ 超過 48 小時全部不放（瀏覽器端改放讀者的四個指標）", c3 == [], [x["key"] for x in c3])
# 第一次看到比官方公布晚很多（例如抓取延誤）：仍以官方公布時間算 48 小時
REL4 = {"inflation": {"month": "2026-10", "first_seen": "2026-11-12T20:00:00+08:00"}}
c4 = S.release_candidates(CTX, REL4, dt.datetime(2026, 11, 13, 7, 0, tzinfo=TPE), {"cpi": ["2026-11-10"]})
check("⑦ 晚看到也不延長：11/10 的 CPI 到 11/13 早上已過 48 小時", c4 == [], c4)
# 行事曆查不到：退回第一次看到的時間
c5 = S.release_candidates(CTX, REL4, dt.datetime(2026, 11, 13, 7, 0, tzinfo=TPE), {})
check("⑧ 行事曆查不到 → 用第一次看到的時間", [x["key"] for x in c5] == ["inflation"], c5)
check("⑨ latest_release 取第一筆", S.latest_release(CTX, REL2, dt.datetime(2026, 11, 12, 22, 0, tzinfo=TPE), RD2)["key"] == "inflation")

# ---- ③ 發布紀錄：期別只能往前走 ----
import run  # noqa: E402
tmp = pathlib.Path(tempfile.mkdtemp())
run.RELEASES_FILE = tmp / "releases.json"
run.RELEASES_FILE.write_text(json.dumps({"fomc": {"month": "2026-09-16", "first_seen": "2026-09-17T04:29:39+08:00",
                                                  "advanced": True}}), encoding="utf-8")
out = run._fresh_releases({"fomc": {"latest_date": "2025-09-17"}})
st = json.loads(run.RELEASES_FILE.read_text(encoding="utf-8"))
check("⑩ 抓到較舊的期別（2025-09-17）→ 沿用舊紀錄、不算新", st["fomc"]["month"] == "2026-09-16"
      and st["fomc"]["first_seen"].startswith("2026-09-17") and "fomc" not in out, st)
run._fresh_releases({"fomc": {"latest_date": "2026-09-16"}})
st = json.loads(run.RELEASES_FILE.read_text(encoding="utf-8"))
check("⑪ 恢復正常後時間不被重設（還是 9/17 第一次看到）", st["fomc"]["first_seen"].startswith("2026-09-17"), st)
run._fresh_releases({"fomc": {"latest_date": "2026-10-28"}})
st = json.loads(run.RELEASES_FILE.read_text(encoding="utf-8"))
check("⑫ 真的有新決議 → 照常更新", st["fomc"]["month"] == "2026-10-28" and st["fomc"]["advanced"] is True, st)

# ---- ④ 聯準會：行事曆抓不到時用已存的官網會議日；最新決議不能倒退 ----
KNOWN = [dt.date(2026, 7, 29), dt.date(2026, 9, 16), dt.date(2026, 10, 28), dt.date(2026, 12, 9)]
U = dt.timezone.utc
check("⑬ 決策日美東下午前不算已公布", fs.expected_latest(KNOWN, dt.datetime(2026, 10, 28, 19, 0, tzinfo=U)) == dt.date(2026, 9, 16))
check("⑭ 決策日 UTC 21:00 後算已公布", fs.expected_latest(KNOWN, dt.datetime(2026, 10, 28, 21, 0, tzinfo=U)) == dt.date(2026, 10, 28))


class Fake:
    def __init__(self, has):
        self.has = has

    def statement(self, d):
        return {"date": d.isoformat(), "text": "x"} if d.isoformat() in self.has else None

    def presser(self, d):
        return None, "pending"


N = dt.datetime(2026, 10, 23, 7, 0, tzinfo=TPE)
old = [{"date": "2025-07-30"}, {"date": "2025-09-17"}]
fixed = run.check_fomc_latest(Fake({"2026-09-16"}), old, KNOWN, N)
check("⑮ 只抓到 2025-09-17 → 補抓 2026-09-16 那一場", fixed[-1]["date"] == "2026-09-16" and len(fixed) == 3, fixed)
try:
    run.check_fomc_latest(Fake(set()), old, KNOWN, N)
    check("⑯ 補抓不到 → 停止發布（FomcStale）", False)
except run.FomcStale:
    check("⑯ 補抓不到 → 停止發布（FomcStale）", True)
same = [{"date": "2026-09-16"}]
check("⑰ 已是最新 → 原封不動", run.check_fomc_latest(Fake(set()), same, KNOWN, N) is same)

fs_known = fs.known_meetings
fs.known_meetings = lambda: KNOWN
try:
    src = fs.FomcSource()
    src._cal = ""                                  # 行事曆頁抓不到
    src.statement = lambda d: None
    md = src.meeting_dates(start="2025-01-01")
    check("⑱ 行事曆抓不到：會議日用已存的官網日期（含 2026-09-16）＋推估補較早年份",
          dt.date(2026, 9, 16) in md and dt.date(2025, 9, 17) in md, md)
    up = src.upcoming_spans(3)
    check("⑲ 行事曆抓不到：下次會議用已存的日期（不再「日期待更新」）", up and up[0][1] > dt.date.today() - dt.timedelta(days=400), up)
finally:
    fs.known_meetings = fs_known

# ---- ⑤ 瀏覽器端：打開當下再篩 48 小時；快報圖格子跳過 10 年期 ----
ui = (ROOT / "src" / "pages" / "story_ui.py").read_text(encoding="utf-8")
sh = (ROOT / "src" / "pages" / "story_share.py").read_text(encoding="utf-8")
check("⑳ 快報第 4 則與圖卡都用打開當下的時間篩 48 小時", ui.count("48 * 3600e3") == 1 and sh.count("48 * 3600e3") == 1
      and "D.latest" not in ui and "D.latest" not in sh)
check("㉑ 圖卡：用 mgPickChips 挑格子（對利率有 10 年期時跳過）", "mgPickChips(Array.prototype.map.call(" in sh
      and "skip10 = !!(ten && (D.rate" in sh)

# ㉒ 補位：讀者勾的（扣掉 10 年期）不到四個 → 用報價板其他指標依序補滿（用 node 跑頁面上同一份函式）
import re, shutil, subprocess  # noqa: E402
from src.pages import story_share  # noqa: E402
node = shutil.which("node")
if node:
    fn = re.search(r"function mgPickChips\(list, skip10\)\{.*?\n\}", story_share.JS, re.S).group(0)
    X = lambda i, off=False, v=True: {"id": i, "off": off, "x": ({"l": i, "v": "1"} if v else None)}
    board = [X("dgs2"), X("dgs10"), X("dgs30"), X("live_dgs10", True), X("sofr", True, v=False),
             X("wti", True), X("spx", True), X("vix", True), X("dgs2", True)]
    cases = {
        "skip": [board, True],                                     # 勾了 2、10、30 年期 → 跳過 10 年期，補 WTI、S&P
        "noskip": [board, False],                                  # 沒有對利率 → 10 年期照放
        "full": [[X("a"), X("b"), X("c"), X("d"), X("e"), X("f", True)], True],   # 讀者勾滿 → 不補
        "few": [[X("dgs10"), X("live_dgs10", True)], True],        # 板上只剩 10 年期 → 空
    }
    prog = fn + "\nvar C = " + json.dumps(cases) + ";var o = {};for (var k in C) o[k] = mgPickChips(C[k][0], C[k][1]).map(function(x){ return x.l; });console.log(JSON.stringify(o));"
    out = json.loads(subprocess.run([node, "-e", prog], capture_output=True, text=True, check=True).stdout)
    check("㉒ 讀者勾的扣掉 10 年期不到四個 → 用報價板其他指標補滿（跳過沒數值、重複的）",
          out["skip"] == ["dgs2", "dgs30", "wti", "spx"], out["skip"])
    check("㉓ 沒有對利率區塊時 10 年期照放、讀者勾的在前", out["noskip"] == ["dgs2", "dgs10", "dgs30", "live_dgs10"], out["noskip"])
    check("㉔ 讀者勾滿四個以上 → 只用讀者的、不補", out["full"] == ["a", "b", "c", "d"], out["full"])
    check("㉕ 板上沒有別的指標 → 不硬塞", out["few"] == [], out["few"])
else:
    print("略過 ㉒–㉕（找不到 node）")

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
