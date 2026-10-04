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

# 失業率基準統一用 FOMC 的 SEP（2026-10：CBO 的自然失業率不再用）
u = [{"date": "2026-06-01", "value": 4.2}, {"date": "2026-07-01", "value": 3.9}]
mid = [{"date": "2026-06-17", "value": 4.2}]
lo_ = [{"date": "2026-06-17", "value": 4.0}]
hi_ = [{"date": "2026-06-17", "value": 4.3}]
ug = build._ustar_gap(u, mid, lo_, hi_)
check("① 基準取 SEP 中位數與中央趨勢", ug["ustar"] == 4.2 and ug["lo"] == 4.0
      and ug["as_of"] == "2026-06-17", str(ug))
check("② 低於中央趨勢下緣判為偏緊（跟格位同口徑）", ug["state"] == "緊", str(ug))
check("②b 缺 SEP 就不顯示", build._ustar_gap(u, [], lo_, hi_) == {})

# A-11 四個大類互斥；不得再使用永久／暫時解雇子項重複加總。
series = {
    "LNS13023621": rows([3000] * 13),
    "LNS13023705": rows([800] * 13),
    "LNS13023557": rows([2000] * 13),
    "LNS13023569": rows([700] * 13),
    # 比重用 BLS 官方序列（跟失去工作者訊號同一條）
    "LNS13023622": rows([46.0] * 12 + [46.2]),
    "LNS13023706": rows([12.3] * 13),
    "LNS13023558": rows([30.8] * 13),
    "LNS13023570": rows([10.9] * 12 + [10.7]),
}
us = build._unemp_structure(series)
labels = {r["label"] for r in us["rows"]}
check("③ 失業原因使用四個互斥大類", len(us["rows"]) == 4, str(labels))
check("④ 失業原因占比加總 100%", abs(sum(r["share"] for r in us["rows"]) - 100) < 1e-9)
check("④b 比重一年變化用個百分點表示",
      next(r for r in us["rows"] if r["kind"] == "bad")["share_yoy_display"]
      == "+0.2 個百分點")
check("④c 比重一年變化不到 1 個百分點 → 結構沒有明顯變化", "沒有明顯變化" in us["verdict"])
check("④d 失業結構附時間軸圖", "<svg" in us["chart"])
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
