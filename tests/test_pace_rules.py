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

# ⑦ 軸心級訊號：失業率回升階梯（rules.r_sahm）與月步速訊號（r_pace）
from types import SimpleNamespace as NS
from src.analysis import rules as R                       # noqa: E402
from src.analysis import rules_inflation as RI            # noqa: E402


def sahm_flag(v):
    ctx = R.RuleContext(lights=[NS(key="sahm", value=v)])
    return R.RULES[0](ctx)                                # r_sahm 註冊在第 0 位


check("⑦ 0.25 → u3_rising（留意）、數字＝紅綠燈值",
      (lambda f: f is not None and f.key == "u3_rising"
       and f.severity == "watch" and "0.25" in f.headline)(sahm_flag(0.25)))
check("⑦b 0.32 → 接近門檻（原有階梯不變）",
      sahm_flag(0.32).key == "sahm_approaching")
check("⑦c 0.55 → 觸發（alert）", sahm_flag(0.55).severity == "alert")
check("⑦d 0.15 → 未達本站門檻，無訊號", sahm_flag(0.15) is None)
check("⑦e 軸心規則註冊在最前（同級排序才會排第一）",
      R.RULES[0].__name__ == "r_sahm"
      and RI.RULES[0].__name__ == "r_pace")


def pace_flag(vals):
    ctx = NS(series={"CPILFESL": idx(vals)}, s=None, att=None, lights=[])
    return RI.RULES[0](ctx)


# 連 6 個月 +0.3% → pace_hot（重要）
check("⑦f 連 6 個月以上超標 → 重要級（8 期資料＝連 7 個月）",
      (lambda f: f is not None and f.key == "pace_hot"
       and f.severity == "alert" and "7 個月" in f.headline)(
          pace_flag([100 * 1.003 ** i for i in range(8)])))
# 連 3 個月 +0.3%（之前守著）→ pace_above（留意）
check("⑦g 連 3 個月超標 → 留意級",
      (lambda f: f is not None and f.key == "pace_above"
       and f.severity == "watch")(
          pace_flag([100.0, 100.1, 100.2, 100.3,
                     100.6, 100.9, 101.2])))
# 連 3 個月守住 ≤0.2 → 降溫參考訊號
check("⑦h 連 3 個月守住 → 參考級降溫訊號",
      (lambda f: f is not None and f.key == "pace_ontrack"
       and f.severity == "info")(
          pace_flag([100.0, 100.5, 100.65, 100.8, 100.95])))
check("⑦i 資料不足 → 無訊號", pace_flag([100.0, 100.2]) is None)

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
