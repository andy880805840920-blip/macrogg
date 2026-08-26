# 月步速（0.2 準則）與就業「溫和惡化」規則的回歸測試（不打網路）
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.analysis import inflation as ia                  # noqa: E402
from src.analysis import scenario as scn                  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過 " if cond else "失敗 "), name, ("— " + str(detail)[:90]) if detail else "")
    ok = ok and bool(cond)


def idx(vals, y=2026, m=1):
    out = []
    for v in vals:
        out.append({"date": f"{y:04d}-{m:02d}-01", "value": float(v)})
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


# ① 半進位到一位小數：0.25 進 0.3（不能用銀行家捨入把它捨成 0.2）
check("① 半進位：0.25→0.3、0.24→0.2、0.35→0.4",
      ia.round1(0.25) == 0.3 and ia.round1(0.24) == 0.2
      and ia.round1(0.35) == 0.4)
check("①b 負值對稱：−0.25→−0.3", ia.round1(-0.25) == -0.3)

# ② 逐月月增只接相鄰月份（缺月不相減）
rows = idx([100.0, 100.2, 100.4])
rows.append({"date": "2026-06-01", "value": 101.0})       # 缺 4、5 月
ms = ia.mom_series(rows)
check("② 缺月的兩端不相減", len(ms) == 2
      and all(r["date"] != "2026-06-01" for r in ms), [r["date"] for r in ms])

# ③ 近三月平均月增＝月步速；資料不足回 None
rows = idx([100.0, 100.20, 100.40, 100.60, 100.80])       # 每月約 +0.2%
pace = ia.monthly_pace(rows)
check("③ 月步速 ≈ 0.2", pace is not None and abs(pace - 0.2) < 0.01, pace)
check("③b 資料不足回 None", ia.monthly_pace(idx([100.0, 100.2])) is None)

# ④ 連續 ≤0.2 的月數：一個 0.3 就斷
rows = idx([100.0, 100.5, 100.7, 100.9, 101.1])           # +0.5 之後三個 +0.2
check("④ streak 從最新往回數、遇 >0.2 即斷", ia.pace_streak(rows) == 3)

# ⑤ 九宮格通膨動能（0.2 準則）：≤0.2 降溫、0.2–0.3 持平、≥0.3 升溫
check("⑤ 0.18 → 降溫",
      scn.classify_inflation_momentum({"core_cpi_pace3": 0.18}) == "降溫")
check("⑤b 0.25 → 持平（緩衝帶）",
      scn.classify_inflation_momentum({"core_cpi_pace3": 0.25}) == "持平")
check("⑤c 0.32 → 升溫",
      scn.classify_inflation_momentum({"core_cpi_pace3": 0.32}) == "升溫")
check("⑤d 缺資料 → 持平（不硬判）",
      scn.classify_inflation_momentum({}) == "持平")

# ⑥ 就業動能：損益兩平已移除，改「失業率回升」（Sahm 同款算式對 0.20）
check("⑥ 失業率回升 → 轉弱",
      scn.classify_labor_momentum({"u3_rising": True}) == "轉弱")
check("⑥b Sahm 觸發 → 轉弱",
      scn.classify_labor_momentum({"sahm_triggered": True}) == "轉弱")
check("⑥c 都沒有＋訊號偏強 → 轉強",
      scn.classify_labor_momentum(
          {"u3_rising": False, "sahm_triggered": False,
           "tilt": {"tilt": "hawkish"}, "nfp_3m": 20.0}) == "轉強")
check("⑥d 溫和門檻常數存在且低於 Sahm 觸發",
      0 < scn.MILD_SAHM < 0.50)

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
