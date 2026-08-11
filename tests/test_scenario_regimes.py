"""
三張九宮格的迴歸測試。

釘住的是這次改版的核心承諾：
  · 三張格子只有三格不同，其餘六格完全一樣
  · 那三格在三種體制下確實給出不同的方向
  · 判不出重心時退回「兩邊並重」並標記為暫用
  · 舊的事後改寫機制（verdict_name / overridden / positioning_note）已經清乾淨

    python tests/test_scenario_regimes.py
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from src.analysis.scenario import (grid_for, REGIMES, CONFLICT_CELLS,
                                   synthesise, Scenario)

ok = True

# ① 只有 CONFLICT_CELLS 那三格會隨體制改變
diff = set()
for cell in grid_for("balanced"):
    names = {grid_for(r)[cell][0] for r in REGIMES}
    leans = {grid_for(r)[cell][2] for r in REGIMES}
    if len(names) > 1 or len(leans) > 1:
        diff.add(cell)
res = diff == set(CONFLICT_CELLS)
print("① 只有三格隨體制改變 :", "通過" if res else f"失敗（實際 {sorted(diff)}）")
ok &= res

# ② 那三格確實給出不同方向
for cell in CONFLICT_CELLS:
    leans = [grid_for(r)[cell][2] for r in REGIMES]
    got = len(set(leans)) >= 2
    print(f"   就業{cell[0]}×通膨{cell[1]}: {leans} →",
          "通過" if got else "失敗（三種體制方向一樣）")
    ok &= got

# ③ 最強衝突那一格在通膨優先與就業優先下方向相反
a = grid_for("inflation")[("弱", "高")][2]
b = grid_for("employment")[("弱", "高")][2]
res = (a, b) == ("hawkish", "dovish")
print("② 停滯性通膨兩體制相反 :", "通過" if res else f"失敗（{a} / {b}）")
ok &= res

# ④ 六格共通內容三張完全一致
same = [c for c in grid_for("balanced") if c not in CONFLICT_CELLS]
res = all(len({grid_for(r)[c] for r in REGIMES}) == 1 for c in same)
print(f"③ 其餘 {len(same)} 格三張一致  :", "通過" if res else "失敗")
ok &= res

# ⑤ 判不出重心 → 退回兩邊並重並標記
LAB = {"score": -1.0, "tilt": {"net": -4}, "flags": []}
INF = {"core_pce_yoy": 3.0, "core_3m": 3.6, "flags": []}
for focus, want_regime, want_assumed in [
        ({"focus": "inflation"}, "inflation", False),
        ({"focus": "employment"}, "employment", False),
        ({"focus": "balanced"}, "balanced", False),
        ({"focus": "unknown"}, "balanced", True),
        ({}, "balanced", True)]:
    sc = synthesise(LAB, INF, {"focus": focus})
    got = (sc.regime, sc.regime_assumed) == (want_regime, want_assumed)
    print(f"④ 重心 {str(focus.get('focus', '(缺)')):10s} → {sc.regime:10s}"
          f" assumed={sc.regime_assumed} :", "通過" if got else "失敗")
    ok &= got

# ⑥ 同一份數據，重心不同 → 結論名稱與方向都不同
n1 = synthesise(LAB, INF, {"focus": {"focus": "inflation"}})
n2 = synthesise(LAB, INF, {"focus": {"focus": "employment"}})
res = n1.name != n2.name and n1.lean != n2.lean
print(f"⑤ 同數據不同重心      : 「{n1.name}」({n1.lean}) vs "
      f"「{n2.name}」({n2.lean}) →", "通過" if res else "失敗")
ok &= res

# ⑦ 舊的事後改寫欄位已經清乾淨
dead = [f for f in ("verdict_name", "verdict_desc", "overridden",
                    "positioning_note")
        if hasattr(Scenario("弱", "高", "x", "y", "neutral"), f)]
print("⑥ 舊 override 欄位已移除:", "通過" if not dead else f"失敗（殘留 {dead}）")
ok &= not dead

# ⑧ 每一個情境名都要有對應的部位表——否則畫面上會出現一張空表
from src.analysis.scenario import POSITIONING
names = {n for r in REGIMES for (n, _, _) in grid_for(r).values()}
miss = sorted(n for n in names if not POSITIONING.get(n))
print("⑦ 部位對照涵蓋所有情境:", "通過" if not miss else f"失敗（缺 {miss}）")
ok &= not miss

# ⑨ 反過來也要成立：部位表不該留下任何查不到的情境名。
# 死鍵不會讓畫面出錯，但會讓人以為某個情境還在用——例如舊的「停滯性通膨」，
# 改成三張格子之後已經分裂成三個體制專屬的名字。
extra = sorted(set(POSITIONING) - names)
print("⑧ 部位對照沒有死鍵    :", "通過" if not extra else f"失敗（多出 {extra}）")
ok &= not extra

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
