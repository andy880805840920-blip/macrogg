"""金融條件（聯準會 FCI-G）：CSV 解析、標題的主要成份判定、分解圖。不連網。"""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from src import treasury_source as ts      # noqa: E402
from src import charts                     # noqa: E402
from src.analysis import fci               # noqa: E402

ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    print(f"{'通過' if cond else '失敗'}  {name}" + (f" — {detail}" if detail else ""))
    ok &= bool(cond)


_csv = ("date,FCI-G Index (baseline),FFR,10Yr Treasury,Mortgage Rate,BBB,Stock Market,House Prices,Dollar\n"
        "2025-08-31,-0.917,-0.034,-0.025,-0.048,-0.012,-0.695,-0.032,-0.071\n"
        "2026-07-31,-0.877,-0.052,-0.007,0.017,-0.050,-0.669,0.002,-0.120\n"
        "2026-08-31,-0.886,-0.046,-0.005,0.029,-0.046,-0.702,-0.003,-0.113\n")
_orig = ts._g_get
ts._g_get = lambda url: _csv
try:
    rows = ts.fci_g()
finally:
    ts._g_get = _orig
check("① 解析：三列、欄位對應", len(rows) == 3 and rows[-1]["stock"] == -0.702 and rows[-1]["mort"] == 0.029, str(rows[-1]))
check("② 成份相加＝指數", abs(sum(rows[-1][k] for k, _ in fci.COMPS) - rows[-1]["total"]) < 0.01)

# 13 個月的序列：最新一期與一年前
seq = [dict(rows[0], date=f"2025-{m:02d}-28") for m in range(8, 13)] + \
      [dict(rows[1], date=f"2026-{m:02d}-28") for m in range(1, 8)] + [rows[2]]
sm = fci.summarize(seq)
check("③ 偏鬆、主要來自股市", sm["stance"] == "loose" and sm["main"]["key"] == "stock", sm["headline"])
check("④ 較上月、較一年前", round(sm["m1"], 3) == -0.009 and round(sm["y1"], 3) == 0.031, f'{sm["m1"]} {sm["y1"]}')
check("⑤ 標題含佔比", "佔同方向貢獻" in sm["headline"], sm["headline"])
tight = [dict(r, total=0.6, stock=0.1, ffr=0.4, t10=0.1, mort=0, bbb=0, house=0, dollar=0) for r in seq]
check("⑥ 偏緊時主要成份取同方向最大（聯邦基金利率）", fci.summarize(tight)["main"]["key"] == "ffr",
      fci.summarize(tight)["headline"])
check("⑦ |指數| < 0.1 視為中性", fci.summarize([dict(r, total=0.05) for r in seq])["stance"] == "neutral")

cols = [(k, lab, f"var(--fci-{i + 1})") for i, (k, lab) in enumerate(fci.COMPS)]
html = charts.impulse_chart(seq, cols, total_label="FCI-G 指數")
check("⑧ 圖：每月一欄、讀數含七個成份", html.count('class="ic-col"') == len(seq) and html.count("｜") >= 8 * len(seq))
check("⑨ 圖：沒有「-0.00」", "-0.00" not in html)

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
