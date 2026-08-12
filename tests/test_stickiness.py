"""
核心服務黏性的判定測試。

為什麼需要這個檔案
------------------
這一塊回答的是「降不降得下來」，不是「現在多高」——而這兩件事在畫面上
長得很像。判定用的三個東西都很容易寫錯而且錯了看不出來：

  ① 動能階梯的方向（3m 相對 12m）——比錯邊的話「加速」會顯示成「減速」
  ② 連續高於門檻的月數——數到資料盡頭時要講「至少 N」，不能講成剛好 N
  ③ 黏性減彈性的差距——正負號搞反的話，「新的價格衝擊」會被讀成「快走完了」

    python tests/test_stickiness.py
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from src.analysis import inflation as I  # noqa: E402
from src import build  # noqa: E402

ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    print(f"{'通過' if cond else '失敗'}  {name}" + (f" — {detail}" if detail else ""))
    ok &= bool(cond)


def idx(monthly_pct: list[float], start: float = 100.0) -> list[dict]:
    """由「每月漲幅（%）」生出指數序列。最舊的在前面。"""
    out, v = [], start
    for i, m in enumerate(monthly_pct):
        v *= (1 + m / 100)
        out.append({"date": f"2021-{i % 12 + 1:02d}-01", "value": round(v, 4)})
    return out


# ---------------------------------------------------------------------------
# ① 動能階梯的方向
# ---------------------------------------------------------------------------
check("① 3m 明顯低於 12m → 減速", I._direction(5.0, 4.5, 4.0) == "decel")
check("② 3m 明顯高於 12m → 加速", I._direction(4.0, 4.4, 5.0) == "accel")
check("③ 差距在雜訊範圍內 → 卡在原地", I._direction(4.0, 4.1, 4.2) == "flat")
# 6m 跟 3m 反向時不該直接下結論：那是折返，不是趨勢
check("④ 中段反向 → 不當成趨勢", I._direction(4.0, 3.0, 5.0) == "flat",
      I._direction(4.0, 3.0, 5.0))
check("⑤ 缺資料 → 不硬判", I._direction(None, 4.0, 4.0) == "")


# ---------------------------------------------------------------------------
# ② 連續高於門檻的月數
# ---------------------------------------------------------------------------
# 每月 0.5% ≈ 年化 6.2%，一路高於 2.5%
hot = idx([0.5] * 24)
n = I._streak_above(hot, 3, 2.5)
check("⑥ 一路高於門檻 → 回負數（代表「至少」）", n < 0, str(n))
check("⑦ 至少的長度＝可算出的期數", abs(n) == 24 - 3, str(abs(n)))

# 前面低、後面高 → 只數後面那一段
mixed = idx([0.05] * 12 + [0.5] * 6)          # 年化 ~0.6% 然後 ~6.2%
n = I._streak_above(mixed, 3, 2.5)
check("⑧ 中途掉下去過 → 正數，只數最近那一段", 0 < n <= 6, str(n))

cool = idx([0.1] * 20)                         # 年化 ~1.2%
check("⑨ 從來沒高於門檻 → 0", I._streak_above(cool, 3, 2.5) == 0)
check("⑩ 資料太短 → 0", I._streak_above(idx([0.5] * 2), 3, 2.5) == 0)


# ---------------------------------------------------------------------------
# ③ 畫面區塊
# ---------------------------------------------------------------------------
class S:
    supercore_12m = 4.0
    supercore_6m = 4.4
    supercore_3m = 5.0
    supercore_streak = -30
    supercore_dir = "accel"
    pce_supercore_12m = 3.0
    pce_supercore_6m = 3.2
    pce_supercore_3m = 3.4
    sticky_cpi = 3.6
    flex_cpi = 1.9


b = build._stickiness_block(S())
check("⑪ 加速時判為偏鷹", b["lean"] == "hawkish", b["lean"])
check("⑫ 摺疊摘要帶方向與月數",
      "重新加速" in b["sum"] and "至少" in b["sum"], b["sum"])
check("⑬ 階梯是六格（CPI 三格＋PCE 三格）", len(b["stats"]) == 6,
      str(len(b["stats"])))
check("⑭ CPI 高於 PCE 超過 0.5 → 講背離並指向 PCE",
      "以核心 PCE 為準" in b["diverge"] or "PCE 那一側為準" in b["diverge"],
      b["diverge"][:40])
check("⑮ 黏性 − 彈性 差距大 → 判為偏鷹",
      b["sticky_flex"]["kind"] == "hawkish"
      and abs(b["sticky_flex"]["gap"] - 1.7) < 0.01,
      f"{b['sticky_flex']['gap']:.2f}")

S.supercore_12m, S.supercore_6m, S.supercore_3m = 5.0, 4.4, 4.0
S.supercore_dir = "decel"
b = build._stickiness_block(S())
check("⑯ 減速時判為偏鴿", b["lean"] == "dovish", b["lean"])
check("⑰ 減速時的結論句講「必要條件」", "必要條件" in b["verdict"])

# 黏性與彈性收斂 → 這一輪走完了，偏鴿
S.sticky_cpi, S.flex_cpi = 2.4, 2.2
b = build._stickiness_block(S())
check("⑱ 兩者收斂 → 偏鴿", b["sticky_flex"]["kind"] == "dovish",
      b["sticky_flex"]["kind"])

# 彈性高於黏性 ＝ 新的衝擊進來，不是舊通膨還沒走完
S.sticky_cpi, S.flex_cpi = 2.0, 3.5
b = build._stickiness_block(S())
check("⑲ 彈性高於黏性 → 判為新的價格衝擊",
      b["sticky_flex"]["kind"] == "hawkish"
      and "新的價格衝擊" in b["sticky_flex"]["note"],
      b["sticky_flex"]["note"][:24])

# 沒有 supercore 就整區不顯示，不能畫出半張空卡
class Empty:
    supercore_3m = None
check("⑳ 沒有資料 → 整區不顯示", build._stickiness_block(Empty()) == {})

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
