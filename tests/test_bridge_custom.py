"""2026-10-24：長端利率組成的利率橋加「自訂」期間（近 2 年任選起訖日，瀏覽器端計算）。"""
import sys, json, random, pathlib, datetime as dt, re, shutil, subprocess
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.analysis import longend as le      # noqa: E402
from src import build                        # noqa: E402
from src.pages import longend as lp          # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過  " if cond else "失敗  ") + name + (f" — {detail}" if detail and not cond else ""))
    ok &= bool(cond)


# ---- 模擬資料：約 2.5 年的交易日；TIPS 晚名目一天 ----
rnd = random.Random(20261024)
days, d = [], dt.date(2024, 4, 1)
while d <= dt.date(2026, 10, 22):
    if d.weekday() < 5:
        days.append(d.isoformat())
    d += dt.timedelta(days=1)
y, r, t = 4.2, 1.9, 0.4
Y, R, T = [], [], []
for i, x in enumerate(days):
    y += rnd.gauss(0, .045); r += rnd.gauss(0, .035); t += rnd.gauss(0, .02)
    Y.append({"date": x, "value": round(y, 3)})
    if i < len(days) - 1:
        R.append({"date": x, "value": round(r, 3)})
    T.append({"date": x, "value": round(t, 4)})      # ACM 跟名目同一天（比 TIPS 早一天）：只截到迄日
ds = le.driver_series({"DGS10": Y, "DFII10": R}, {"acm": T})
bd = le.bridge_data(ds)
D = le.bridge_ds(bd)
last = Y[-1]["date"]

# ① 範圍：近 2 年
check("① 可選範圍＝近 2 年（最新 10/22 → 2024/10/21 起）", bd["min"] == "2024-10-21" and bd["max"] == last, (bd["min"], bd["max"]))
check("② 資料多放 15 天當基期", bd["y10"][0][0] >= "2024-10-06" and bd["y10"][0][0] <= "2024-10-08", bd["y10"][0][0])

# ② 跟既有分頁同一套規則：起日設成既有分頁的基期，結果一樣
KEYS = ("from", "to", "start", "end", "nominal", "path", "m_start", "m_end", "main", "tp_from", "tp_to")
for mode in (1, 3, "mtd", "ytd"):
    w = le.contribution_window(D, mode)
    c = le.contribution_range(D, w["from"], last)
    same = all(w[k] == c[k] for k in KEYS) and w["parts"] == c["parts"]
    check(f"③ 自訂＝既有「{mode}」的結果（起日＝其基期）", same, {k: (w[k], c[k]) for k in KEYS if w[k] != c[k]})

# ③ 假日、順序、資料不足
sat = "2026-09-26"   # 週六
c = le.contribution_range(D, sat, last)
check("④ 起日遇假日 → 用前一個交易日（週五 9/25）", c and c["from"] == "2026-09-25", c and c["from"])
c2 = le.contribution_range(D, last, "2026-09-25")
check("⑤ 起訖顛倒 → 自動對調", c2 and c2["from"] == "2026-09-25", c2 and c2["from"])
check("⑥ 終點對齊 TIPS（晚名目一天）；ACM 照既有分頁只截到迄日", c["to"] == days[-2] and c["tp_to"] == days[-1], (c["to"], c["tp_to"]))
c3 = le.contribution_range(D, "2026-03-02", "2026-06-30")
check("⑦ 迄日在中間 → 終點是當天或之前最後一筆", c3 and c3["to"] == "2026-06-30", c3 and c3["to"])
check("⑧ 起日＝最新資料日 → 資料不足（None）", le.contribution_range(D, days[-2], last) is None)
check("⑨ 恆等：名目變化＝TIPS＋BEI", abs(c3["nominal"] - c3["parts"]["real"] - c3["parts"]["infl"]) < 1e-6)
check("⑩ 恆等：模型起訖＝預期路徑＋期限溢酬", abs((c3["m_end"] - c3["m_start"]) * 100 - c3["path"] - c3["parts"]["tp"]) < 1e-6)
wl = le.contribution_window(D, 1)
check("⑩b 既有分頁的模型拆解也恆等（ACM 比 TIPS 早一天時，預期路徑不再截到 TIPS 那天）",
      abs((wl["m_end"] - wl["m_start"]) * 100 - wl["path"] - wl["parts"]["tp"]) < 1e-6)

# ④ 瀏覽器端與程式端逐字一致（node 跑頁面上同一份 JS）
RANGES = [(None, last), ("2026-09-25", last), ("2026-03-02", "2026-06-30"), (bd["min"], last),
          ("2025-12-31", "2026-10-20"), (sat, "2026-10-04"), ("2026-06-30", "2026-03-02")]
w1 = le.contribution_window(D, 1)
RANGES[0] = (w1["from"], last)
node = shutil.which("node")
if node:
    prog = (lp._BR_CORE_JS + "\nvar BD=" + json.dumps(bd, ensure_ascii=False) + ",RG=" + json.dumps(RANGES)
            + ";console.log(JSON.stringify(RG.map(function(g){var c=leBridgeCalc(BD,g[0],g[1]);"
              "return c?{c:c,h:leBridgeHtml(BD,c)}:null;})));")
    js = json.loads(subprocess.run([node, "-e", prog], capture_output=True, text=True, check=True).stdout)
    bad = []
    for g, j in zip(RANGES, js):
        c = le.contribution_range(D, *g)
        if c is None or j is None:
            if (c is None) != (j is None):
                bad.append((g, "None 不一致"))
            continue
        if any(c[k] != j["c"][k] for k in KEYS) or c["parts"] != j["c"]["parts"]:
            bad.append((g, "數字不一致"))
        if build.bridge_html(c) != j["h"]:
            bad.append((g, "HTML 不一致"))
    check("⑪ 瀏覽器端 leBridgeCalc／leBridgeHtml 與程式端逐字一致（7 段期間）", not bad, bad)
else:
    print("略過 ⑪（找不到 node）")

# ⑤ 頁面：多一個「自訂」分頁、嵌入資料；年初至今與自訂分頁都有顯示規則
h = lp.decomp({"le": {"bridges": {1: "<i>a</i>", "ytd": "<i>b</i>"}, "br_data": bd, "drv": {}}})
check("⑫ 頁面有「自訂」分頁、起訖日欄（min／max＝近 2 年）與資料",
      'id="le-brc"' in h and '<label for="le-brc">自訂</label>' in h and f'min="{bd["min"]}"' in h
      and f'max="{last}"' in h and 'id="le-br-data"' in h and "leBridgeCalc" in h)
m = re.search(r'<script type="application/json" id="le-br-data">(.*?)</script>', h, re.S)
check("⑬ 嵌入的資料能解析", m and json.loads(m.group(1))["max"] == last)
css = (ROOT / "src" / "site.py").read_text(encoding="utf-8")
check("⑭ CSS：年初至今（原本漏了，點了沒畫面）與自訂分頁都會顯示",
      "#le-brytd:checked~.tabp.pytd" in css and "#le-brc:checked~.tabp.pc" in css)
short = le.bridge_data({k: v[-60:] for k, v in ds.items()})
check("⑮a 資料不滿 2 年：最早只能選到第一筆，選最早那天仍算得出來",
      short["min"] == ds["y10"][-60]["date"] and le.contribution_range(le.bridge_ds(short), short["min"], last) is not None, short["min"])
check("⑮ 沒有資料時不顯示自訂分頁", 'id="le-brc"' not in lp.decomp({"le": {"bridges": {1: "x"}, "drv": {}}}))

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
