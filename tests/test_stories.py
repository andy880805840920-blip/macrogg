"""
今日快報（限時動態）與主軸存檔（2026-10）。不連網，結果固定。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.analysis import focus_today as ft, stories as sto  # noqa: E402

FAIL = []


def check(name, ok, info=""):
    print(("通過  " if ok else "失敗  ") + name + ("" if ok else f" — {info}"))
    if not ok:
        FAIL.append(name)


# ① 主軸存檔：同一天後面的蓋前面、只留 5 天、沒有主軸不存
st = {"text": "A", "layout": "main", "headline": "早上版", "rate_note": "", "links": [],
      "at": "2026-10-12T23:10:00+00:00"}                # 台灣 10/13 07:10
a = ft.update_archive({}, st)
a = ft.update_archive(a, dict(st, headline="晚上版", at="2026-10-13T14:50:00+00:00"))  # 台灣 10/13 22:50
check("① 同一天保留最後一版", list(a) == ["2026-10-13"] and a["2026-10-13"]["headline"] == "晚上版", a)
for d in range(1, 9):
    a[f"2026-10-0{d}"] = {"headline": str(d), "text": "x"}
a = ft.update_archive(a, {})
# v2（2026-10-25）：存檔留 8 天（星期天週報要用整週），首頁只顯示最近 5 天
check("② 只留最近 8 天", list(a) == ["2026-10-13", "2026-10-08", "2026-10-07", "2026-10-06", "2026-10-05",
                                    "2026-10-04", "2026-10-03", "2026-10-02"], list(a))
check("②b 首頁清單只顯示最近 7 天（2026-10-29）", [x["date"] for x in ft.archive_list(a)]
      == ["2026-10-13", "2026-10-08", "2026-10-07", "2026-10-06", "2026-10-05", "2026-10-04", "2026-10-03"])
b = ft.update_archive({}, {"text": "", "layout": "", "at": "2026-10-13T00:00:00+00:00"})
check("③ 沒有主軸不存", b == {}, b)
check("④ 清單新→舊、帶日期", [x["date"] for x in ft.archive_list(a)][:2] == ["2026-10-13", "2026-10-08"])

# ⑤ 對利率方向
cases = {"偏向推升短端利率與 12 月升息預期；不過近一週 10 年期 -4bp，市場還沒反映。": "up",
         "偏向壓低長端殖利率，市場加碼定價降息預期。": "down",
         "油價上漲對利率方向不明確，取決於通膨預期與避險需求孰強。": "unclear",
         "近一週利率大致持平，市場在等下一個訊號。": "flat"}
bad = {k: sto.rate_direction(k) for k, v in cases.items() if sto.rate_direction(k) != v}
check("⑤ 對利率方向判斷（推升／壓低／不明確／持平）", not bad, bad)

# ⑥ 最新數據：挑最近一次公布的，帶市場預估與高低
ctxs = {"labor": {"data_month": "2026-09", "kpi": {"nfp_display": "+15.0 萬人", "u3_display": "4.3%"}},
        "inflation": {"data_month": "2026-09", "kpi": {"core_display": "+0.3%", "headline_display": "+0.4%"}},
        "_watch_extra": {"consensus": {"cpi|2026-10-14": [{"label": "核心 CPI 月增", "forecast": "0.2%", "previous": "0.3%"}]}}}
rel = {"labor": {"first_seen": "2026-10-03T07:05:00+08:00"},
       "inflation": {"first_seen": "2026-10-14T22:45:00+08:00"}}
L = sto.latest_release(ctxs, rel)
check("⑥ 最新數據＝最近一次公布（CPI）", L and L["name"].startswith("CPI") and L["date"] == "10/14", L)
check("⑦ 有預估就標高於預估", L and L["rows"][0]["forecast"] == "0.2%" and L["rows"][0]["vs"] == "高於預估", L)
L2 = sto.latest_release({"labor": ctxs["labor"]}, {})
check("⑧ 沒有發布紀錄時退回依序第一個有資料的", L2 and L2["name"].startswith("就業報告"), L2)

# ⑬ 版本日期：台灣時間往前推 5 小時
import datetime as _dt  # noqa: E402
_tz = _dt.timezone(_dt.timedelta(hours=8))
E = lambda y, m, d, H, M: sto.edition_day(_dt.datetime(y, m, d, H, M, tzinfo=_tz))
check("⑬ 早上準時（07:03）與延遲（08:40）都算當天",
      E(2026, 10, 14, 7, 3) == E(2026, 10, 14, 8, 40) == "2026-10-14")
check("⑭ 晚上那次拖過午夜（00:30）仍算前一天", E(2026, 10, 15, 0, 30) == "2026-10-14")
check("⑮ 22:45 算當天", E(2026, 10, 14, 22, 45) == "2026-10-14")

# ⑪ 最新數據：初領失業金不放（每週公布，會蓋掉更重要的數據）；JOLTS 照常
c2 = {"labor": {"claims": {"machine": {"week": "2026-10-10", "ic_now": 228000, "ic_ma": 224500}},
                "jolts": [{"label": "職缺數", "value": "720.0 萬個"}, {"label": "招聘率", "value": "3.4%"}],
                "jolts_month": "2026-08"},
      "_watch_extra": {"consensus": {"claims|2026-10-16": [{"label": "初領失業金", "forecast": "22.0 萬", "previous": "21.8 萬"}]}}}
L3 = sto.latest_release(c2, {"claims": {"first_seen": "2026-10-16T22:45:00+08:00"},
                              "jolts": {"first_seen": "2026-10-08T07:05:00+08:00"}})
check("⑪ 初領失業金不放進快報（2026-10）：週四公布後仍顯示前一次的 JOLTS",
      L3 and L3["name"].startswith("JOLTS 職缺（8 月）"), L3)
L4 = sto.latest_release(c2, {"jolts": {"first_seen": "2026-10-08T07:05:00+08:00"}})
check("⑫ JOLTS：職缺數與招聘率", L4 and L4["name"].startswith("JOLTS 職缺（8 月）")
      and L4["rows"][0]["actual"] == "720.0 萬個", L4)

# ⑨ 第一則自動寫的那句話（頁面上的 JS，用 node 跑同一份）
import json, re, shutil, subprocess  # noqa: E402
from src.pages import story_ui  # noqa: E402
node = shutil.which("node")
if node:
    js = story_ui.JS
    fn = re.search(r"function sayChips\(ch\)\{.*?\n\}", js, re.S).group(0)
    ad = re.search(r"function addDay\(iso, n\)\{.*?\}\s*\}?", js).group(0)
    C = lambda l, v, d, big=False: {"l": l, "v": v, "d": d, "big": big}
    cases = [
        ([C("2 年期", "3.8%", 2), C("10 年期", "4.6%", 1)], "兩個都往上走"),
        ([C("2 年期", "3.8%", -2), C("10 年期", "4.6%", -1)], "兩個都在往下"),
        ([C("WTI", "$88", -0.7), C("10 年期", "4.6%", 1)], "一漲一跌，各走各的"),
        ([C("WTI", "$88", 3, True), C("10 年期", "4.6%", 1)], "WTI今天動得最多"),
        ([C("2 年期", "3.8%", 6, True), C("10 年期", "4.6%", 7, True)], "兩個都大幅往上"),
        ([C("2 年期", "3.8%", 0), C("10 年期", "4.6%", 0)], "今天很安靜"),
        ([C("2 年期", "3.8%", 0), C("10 年期", "4.6%", 2)], "10 年期往上，另一個沒什麼動"),
        ([C("台幣", "—", 0), C("10 年期", "4.6%", 1)], "10 年期往上走"),
        ([], "挑兩個你想天天看的數字"),
    ]
    prog = fn + "\n" + ad + "\nconst cs=" + json.dumps([c for c, _ in cases], ensure_ascii=False) + \
        ";process.stdout.write(JSON.stringify({s:cs.map(sayChips),d:[addDay('2026-10-31',1),addDay('2026-12-31',1),addDay('2026-10-13',0)]}));"
    out = json.loads(subprocess.run([node, "-e", prog], capture_output=True, text=True, check=True).stdout)
    bad = [(want, got) for (_, want), got in zip(cases, out["s"]) if want != got]
    check("⑨ 第一則依漲跌自動寫的句子", not bad, bad)
    check("⑩ 日期加一天（跨月、跨年）", out["d"] == ["2026-11-01", "2027-01-01", "2026-10-13"], out["d"])
else:
    print("略過 ⑨⑩（找不到 node）")

print()
print("有失敗" if FAIL else "全部通過")
sys.exit(1 if FAIL else 0)
