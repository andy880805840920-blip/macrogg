"""
殖利率曲線「自選期間」：Python（analysis/longend.window_analysis）與瀏覽器端
（pages/longend._CW_CORE_JS）必須算出**一字不差**的結果——判讀文字、利差、型態。
兩邊各寫一份規則，這個測試是唯一的保險。需要 node；沒有 node 時略過。
"""
import sys, json, pathlib, shutil, subprocess, tempfile, datetime as dt
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.analysis import longend as le          # noqa: E402
from src.pages import longend as LP             # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過  " if cond else "失敗  ") + name + (f" — {detail}" if detail and not cond else ""))
    ok &= bool(cond)


fixture = ROOT / "fixtures" / "rates.json"
if fixture.exists():
    series = json.loads(fixture.read_text(encoding="utf-8"))["series"]
else:
    from src import fixtures_rates
    series = fixtures_rates.build()
# 補一條油價（fixture 沒有），確認油價分支兩邊一致
import random
random.seed(7)
_v, oil = 70.0, []
for r in series["DGS10"][-320:]:
    _v *= 1 + random.gauss(0.001, 0.02)
    oil.append({"date": r["date"], "value": round(_v, 2)})
series = dict(series, DCOILWTICO=oil)
cd = le.curve_data(series, "2025-12-01")
cd["year"] = 2026
last = cd["d"][-1]
cases = [(le.cw_start(cd, k, last, 2026), last) for k, _, _ in le.CW_WINDOWS]
days = cd["d"]
for i in range(0, len(days) - 3, 9):           # 一大堆自訂區間，含週末日期
    a = (dt.date.fromisoformat(days[i]) - dt.timedelta(days=1)).isoformat()
    b = days[min(len(days) - 1, i + 3 + (i * 7) % 60)]
    cases.append((a, b))
cases.append((days[-1], days[-1]))             # 起訖同一天 → 自動往前一天

py = []
for a, b in cases:
    r = le.window_analysis(cd, a, b)
    py.append({"start": r["start"], "end": r["end"], "text": r["text"], "view": le.window_view(r),
               "sp": [[x["key"], le._num(x["a"]), le._num(x["b"]), le._sgn(x["d"], ""), x["code"]] for x in r["spreads"]],
               "ten": [[t["k"], le._sgn(t["d"]) if t["d"] is not None else None] for t in r["tenors"]]})
py_starts = [le.cw_start(cd, k, last, 2026) for k, _, _ in le.CW_WINDOWS]

node = shutil.which("node")
if not node:
    print("略過：沒有 node")
else:
    js = LP._CW_CORE_JS + """
var CD=%s, cases=%s, C=cwCore(CD);
var out=cases.map(function(c){var r=C.analysis(c[0],c[1]);return{start:r.start,end:r.end,text:r.text,view:C.view(r),
 sp:r.spreads.map(function(x){return[x.key,C.num(x.a),C.num(x.b),C.sgn(x.d,''),x.code];}),
 ten:r.tenors.map(function(t){return[t.k,t.d===null?null:C.sgn(t.d)];})};});
var st=['1w','1m','3m','ytd'].map(function(k){return C.startFor(k,%s);});
console.log(JSON.stringify({out:out,st:st}));
""" % (json.dumps(cd), json.dumps(cases), json.dumps(last))
    with tempfile.TemporaryDirectory() as td:
        f = pathlib.Path(td) / "cw.js"
        f.write_text(js, encoding="utf-8")
        res = json.loads(subprocess.run([node, str(f)], capture_output=True, text=True, check=True).stdout)
    diff = [(c, a, b) for c, a, b in zip(cases, py, res["out"]) if a != b]
    check(f"① {len(cases)} 個期間，Python 與 JS 輸出一字不差", not diff, diff[:1])
    check("② 快捷鍵的起點一致（1 週／1 個月／3 個月／年初）", py_starts == res["st"], (py_starts, res["st"]))
check("③ 預設 1 週有三句判讀", len(py[0]["text"]) == 3, py[0]["text"])
check("④ 起訖同一天時自動拉開一天", py[-1]["start"] < py[-1]["end"], py[-1])
check("⑤ 年初至今的起點是去年 12/31（對齊到交易日）", py[3]["start"] <= "2025-12-31", py[3]["start"])

# ---------------------------------------------------------------- 2026-10 v3
from src.analysis import curve_weekly as CWK          # noqa: E402
from src.pages import curve_weekly as CWP             # noqa: E402
# 每週利差：Python 與 JS 一致（三條利差、週五比週五）
wk_cases = [(None, last, k) for k in ("10-2", "30-10", "30-2")] + [
    (days[40], days[120], "30-2"), (days[10], days[-1], "10-2")]
cut = last
pyw = [CWK.weekly_spreads(cd, a, b, cutoff=cut, key=k) for a, b, k in wk_cases]
check("⑥ 每週變化以週五為一週終點", all(dt.date.fromisoformat(r["end"]).weekday() == 4 for r in pyw),
      [r["end"] for r in pyw])
if node:
    js = CWP.WEEKLY_CORE_JS + """
var CD=%s,cases=%s,cut=%s;
console.log(JSON.stringify(cases.map(function(c){return cwWeekly(CD,c[0],c[1],cut,c[2]);})));
""" % (json.dumps(cd), json.dumps(wk_cases), json.dumps(cut))
    with tempfile.TemporaryDirectory() as td:
        f = pathlib.Path(td) / "wk.js"
        f.write_text(js, encoding="utf-8")
        jw = json.loads(subprocess.run([node, str(f)], capture_output=True, text=True, check=True).stdout)
    norm = lambda r: [r["start"], r["end"], [[x["target"], x["from"], x["to"],
                       None if x["change"] is None else round(x["change"], 6)] for x in r["rows"]]]
    check("⑦ 每週變化：Python 與 JS 一致（三條利差、自訂區間）",
          [norm(r) for r in pyw] == [norm(r) for r in jw], (norm(pyw[0]), norm(jw[0])))

# 拆解：實質利率最新一天還沒公布 → 用前一天，不再顯示「資料不足」
lag = {"d": ["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06"],
       "y2": [4.8, 4.81, 4.82, 4.83], "y10": [5.2, 5.25, 5.3, 5.31], "y30": [5.6, 5.65, 5.7, 5.72],
       "be": [2.3, 2.32, 2.34, 2.35], "real": [2.9, 2.93, 2.96, None], "tp": [1.0, None, None, None],
       "y3m": [4.2, 4.2, 4.21, 4.22], "oil": [90, None, None, None]}
rl = le.window_analysis(lag, "2026-10-01", "2026-10-06")
check("⑧ 實質利率晚一天：拆解用 10/1 → 10/5，不是資料不足",
      rl["drivers"]["dates"] == ["2026-10-01", "2026-10-05"] and "資料不足" not in rl["text"][1], rl["drivers"])
check("⑨ 期限溢酬、油價起訖退到同一天 → 顯示「—」（不是 0bp）",
      rl["drivers"]["tp"] is None and rl["drivers"]["oil"] is None)
check("⑩ 開頭判讀以 30−2 為主、附兩段", "30−2" in rl["text"][0] and "10−2" in rl["text"][0]
      and "30−10" in rl["text"][0], rl["text"][0])

# 30−2 週報：遠期算法與文字
def _ser(vals, days):
    return [{"date": d, "value": v} for d, v in zip(days, vals)]
_days = ["2026-10-0%d" % i for i in (1, 2, 5, 6, 7, 8)]
base = {"DGS1": 4.30, "DGS2": 4.20, "DGS3": 4.25, "DGS5": 4.40, "DGS7": 4.60, "DGS10": 4.80, "DGS20": 5.10, "DGS30": 5.20}
ser = {k: _ser([v] * 6, _days) for k, v in base.items()}
ser["DGS30"][-1]["value"] = 5.32        # 30 年 +12bp、2 年 +2bp → 熊陡、長端帶動
ser["DGS2"][-1]["value"] = 4.22
b = le.curve_brief(ser)
check("⑪ 週報：滾動一週（最新比 5 個交易日前）", b and b["from"] == "2026-10-01" and b["to"] == "2026-10-08", b and (b["from"], b["to"]))
check("⑫ 週報：30−2 擴大 10bp、熊陡、主要來自 10→30 年段",
      b and "擴大 10bp" in b["text"][0] and "熊陡" in b["text"][1] and "10→30 年段" in b["text"][2], b and b["text"])
f1 = b["fwd"]["1"]["lv"]
check("⑬ 遠期：1 年後的 2Y＝1y2y（1Y、3Y）", abs(f1["2"] - le._fwd(4.30, 1, 4.25, 3)) < 1e-9)
check("⑭ 遠期：5 年後的 10Y＝5y10y（15Y 由 10Y、20Y 內插）",
      abs(b["fwd"]["5"]["lv"]["10"] - le._fwd(4.40, 5, (4.80 + 5.10) / 2, 15)) < 1e-9)
check("⑮ 遠期利差＝遠期 30Y − 遠期 2Y（bp）",
      abs(b["fwd"]["1"]["sp"]["30-2"] - (f1["30"] - f1["2"]) * 100) < 1e-9)
check("⑯ 週報有「市場隱含」與「較上週」兩句", any("市場隱含" in t and "較上週" in t for t in b["text"])
      and b["text"][-1].startswith("定價偏向"), b["text"])
del ser["DGS3"]
b2 = le.curve_brief(ser)
check("⑰ 沒有 3 年期 → 由 2Y／5Y 內插並標記", b2["interp3"] is True)

# ---------------------------------------------------------------- v4：白話週報、監控表
check("⑱ 年內區間與遠期歷史有算出來", b["ytd"]["30-2"]["lo"] <= b["sp"]["30-2"]["b"] <= b["ytd"]["30-2"]["hi"]
      and len(b["fwd_hist"]["1"]["30-2"]) >= 5, b.get("ytd"))
check("⑲ 最大單日變動：30 年 10/8 +12bp", b["move"]["date"] == "2026-10-08" and b["move"]["name"] == "30 年"
      and abs(b["move"]["d"] - 12) < 1e-6, b["move"])
pr = le.brief_prose(b, [("2026-10-08", "CPI")])
check("⑳ 白話：變陡、長端帶動、30−2 現在值、當天事件、市場定價",
      "明顯變陡" in pr and "長端帶動" in pr and "到 110bp" in pr and "長期回平" in pr and "當天有CPI" in pr and "市場定價方面" in pr, pr)
flat = {k: _ser([v] * 6, _days) for k, v in base.items()}
pf = le.brief_prose(le.curve_brief(flat))
check("㉑ 白話：完全沒動 → 「幾乎沒動」、不寫單日變動", "幾乎沒動" in pf and "主要變化" not in pf, pf)
html = LP.curve({"le": {"cw": cd, "cw_year": 2026, "brief": b, "cw_events": [["2026-10-08", "CPI"]],
                        "yield_chart": "", "curve_chart": "", "spreads": []}})
check("㉒ 頁面：白話段落＋數字明細收合＋複製按鈕", 'class="cwb-prose"' in html and "數字明細" in html
      and 'class="cwb-copy"' in html)
check("㉓ 監控表：一張表六列（2Y／10Y／30Y、三條利差），有年內位置條與遠期小走勢線",
      html.count('<th scope="row">') == 6 and "cwm-rng" in html and "cwm-spark" in html and "cwm-bar" in html)
check("㉔ 移除重複的判讀句與「實際使用…」小字", 'class="cw-headline"' not in html and 'cw-when"' not in html.replace("cwm-when", ""))
check("㉕ 事件日期進到圖表資料", '"ev":[["2026-10-08","CPI"]]' in html.replace(" ", ""))

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
