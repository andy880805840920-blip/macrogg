"""已確認的資料邏輯錯誤之回歸測試。"""
import datetime as dt
import pathlib
import sys
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from src import build
from src.analysis import inflation, rates
from src.fomc_source import FomcSource

ok = True
def check(name, cond, detail=""):
    global ok
    print(f"{'通過' if cond else '失敗'}  {name}" + (f" — {detail}" if detail else ""))
    ok &= bool(cond)

def rows(values, start_year=2025):
    out = []
    for i, value in enumerate(values):
        y, m = start_year + i // 12, i % 12 + 1
        out.append({"date": f"{y:04d}-{m:02d}-01", "value": value})
    return out

# NROU 尾端包含遠期預測，只能取不晚於當期失業率的最近季度。
u = [{"date": "2026-07-01", "value": 4.1}]
nrou = [
    {"date": "2026-04-01", "value": 4.40},
    {"date": "2026-07-01", "value": 4.39},
    {"date": "2036-10-01", "value": 4.16},
]
ug = build._ustar_gap(u, nrou)
check("① 自然失業率不會抓到 2036 預測", ug["as_of"] == "2026-07-01", str(ug))
check("② 當期失業缺口判為偏緊", ug["state"] == "緊", str(ug))

# A-11 四個大類互斥；不得再使用永久／暫時解雇子項重複加總。
series = {
    "LNS13023621": rows([3000] * 13),
    "LNS13023705": rows([800] * 13),
    "LNS13023557": rows([2000] * 13),
    "LNS13023569": rows([700] * 13),
}
us = build._unemp_structure(series)
labels = {r["label"] for r in us["rows"]}
check("③ 失業原因使用四個互斥大類", len(us["rows"]) == 4, str(labels))
check("④ 失業原因占比加總 100%", abs(sum(r["share"] for r in us["rows"]) - 100) < 1e-9)
check("⑤ 正確使用 Reentrants 序列", "重新進入" in labels)

# CPI 分項缺資料時要回報覆蓋率。
meta = [
    {"id": "a", "label": "A", "weight": 75.0, "group": "core_goods"},
    {"id": "b", "label": "B", "weight": 25.0, "group": "core_services"},
]
att = inflation.attribute_cpi(rows([100, 101]), {"a": rows([100, 101])}, meta)
check("⑧ CPI 歸因回報 75% 覆蓋率", att.aggregates["coverage_weight"] == 75.0)
check("⑨ CPI 歸因列出缺漏分項", att.aggregates["missing_labels"] == ["B"])

# 正的 pb_gap 是緩衝；負的才是缺口。
debt = rates.DebtState(pb_gap=1.85)
sp = rates.supply_pressure(rates.CurveState(), debt, rates.Hyperscalers(), None)
check("⑩ 正 pb_gap 標示為財政緩衝", sp.parts[0]["label"] == "政府財政緩衝", str(sp.parts[0]))
check("11 財政緩衝降低供給壓力", sp.parts[0]["score"] < 0, str(sp.parts[0]))

# 策略框架公告即使提到 Committee，也不是利率政策聲明。
class FakeFomc(FomcSource):
    def _get(self, url, binary=False):
        return ("<p>The Committee approved updates to its longer-run goals and strategy. "
                + "Transparency and accountability remain important. " * 20 + "</p>")

fake = FakeFomc()
check("12 長期策略公告不列入政策會議", fake.statement(dt.date(2025, 8, 22)) is None)

if not ok:
    sys.exit(1)
print("\n全部資料邏輯回歸測試通過。")
