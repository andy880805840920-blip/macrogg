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


series = json.load(open(ROOT / "fixtures" / "rates.json", encoding="utf-8"))["series"]
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
    py.append({"start": r["start"], "end": r["end"], "text": r["text"],
               "sp": [[x["key"], le._num(x["a"]), le._num(x["b"]), le._sgn(x["d"], ""), x["code"]] for x in r["spreads"]],
               "ten": [[t["k"], le._sgn(t["d"]) if t["d"] is not None else None] for t in r["tenors"]]})
py_starts = [le.cw_start(cd, k, last, 2026) for k, _, _ in le.CW_WINDOWS]

node = shutil.which("node")
if not node:
    print("略過：沒有 node")
else:
    js = LP._CW_CORE_JS + """
var CD=%s, cases=%s, C=cwCore(CD);
var out=cases.map(function(c){var r=C.analysis(c[0],c[1]);return{start:r.start,end:r.end,text:r.text,
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

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
