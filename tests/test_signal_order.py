# 本期關鍵訊號的排序與總結（2026-10 改版）的回歸測試（不打網路）
#
# 由來（使用者指出）：
#   · 「失業率下降源於勞動力退出」推翻頭條數字的解讀，卻因幅度在雜訊內
#     被降成「參考」、排在最後——應該放最前面
#   · 「低招聘、低裁員」是對現況的總結，不是本期新發生的訊號
#   · 「初值近一年下修」講的是月度修正，跟年度基準修正（2025/4–2026/3）
#     是兩件事，不能混著講
import sys
import pathlib
import datetime as dt
from types import SimpleNamespace as NS

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.analysis import rules as R                         # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過 " if cond else "失敗 "), name, ("— " + str(detail)[:140]) if detail else "")
    ok = ok and bool(cond)


# ① 分層排序：層級優先於嚴重度
DEC = {"verdict": "bad_decline", "delta_rate": -0.1, "delta_employed": -555,
       "delta_labor_force": -755, "delta_unemployed": -200,
       "significant": False, "signif_threshold": 0.2}
REV = NS(two_month_net=None, recent=[], bias_12m=-12.0,
         bias_direction="systematically_down")
CC = [{"date": f"2026-{1 + i // 5:02d}-{1 + i % 5 * 5:02d}", "value": 1_800_000 + i * 1000}
      for i in range(30)]
ctx = R.RuleContext(series={"CCSA": CC}, unrate_decomp=DEC, revisions=REV)
fl = R.run_rules(ctx)
keys = [f.key for f in fl]
check("① 勞動力退出（嚴重度只有參考）仍排第一", keys[0] == "bad_decline", keys)
check("①b 續領新高（重要）排在它後面、屬「趨勢轉折」",
      "continuing_claims_high" in keys
      and keys.index("continuing_claims_high") > 0
      and fl[keys.index("continuing_claims_high")].tier == 2, keys)
check("①c 月度修正偏向放最後（結構背景）",
      keys[-1] == "revision_bias_down" and fl[-1].tier == 3, keys)
check("①d 嚴重度沒被改（鷹鴿淨值權重靠它）",
      fl[0].severity == "info")
check("①e 每條訊號都有層級名稱",
      all(f.tier in R.TIERS for f in fl))

# ①f 第一層內：失業率成因排在「前兩月大幅下修（重要）」前面
REV2 = NS(two_month_net=-103, recent=[NS(current=-23)], ma3_before_revision=54,
          ma3_now=20, bias_12m=None, bias_direction="unknown")
_f2 = R.run_rules(R.RuleContext(unrate_decomp=DEC, revisions=REV2))
check("①f 勞動力退出排在重要級的修正前面",
      [f.key for f in _f2][:2] == ["bad_decline", "revision_swamps"],
      [f.key for f in _f2])

# ② 家庭調查抽樣誤差註記
check("② 55.5 萬／75.5 萬：大的那塊超過 ±60 萬 → 不加註",
      "信賴區間" not in fl[0].detail, fl[0].detail)
_small = R.run_rules(R.RuleContext(unrate_decomp={**DEC, "delta_employed": -120,
                                                 "delta_labor_force": -300}))
check("②b 兩塊都在 ±60 萬內 → 加註「在誤差範圍內」",
      "信賴區間約 ±60 萬人" in _small[0].detail, _small[0].detail)

# ③ 同層同級：強度大的排前面
f1 = R.Flag("a", "watch", "a", "", tier=2, strength=1.2)
f2 = R.Flag("b", "watch", "b", "", tier=2, strength=2.5)
_order = {"alert": 0, "watch": 1, "info": 2}
_s = sorted([f1, f2], key=lambda f: (f.tier, _order[f.severity], -f.strength))
check("③ 同層同級時強度 2.5 排在 1.2 前面", [f.key for f in _s] == ["b", "a"])

# ④ 月度修正改名，不再寫「近一年」
_rb = [f for f in fl if f.key == "revision_bias_down"][0]
check("④ 月度修正的標題與說明分清楚兩種修正",
      "月度修正" in _rb.headline and "年度基準修正" in _rb.detail)

# ⑤ 年度基準修正（config 手動維護）
BM = {"published": "2026-08-28", "reference": "2026 年 3 月",
      "period": "2025/4–2026/3", "total": -79, "private": -178, "pct": -0.1,
      "final": "2027 年 2 月"}


def bm_flag(today):
    return R.r_benchmark(R.RuleContext(benchmark=BM, today=today))


f = bm_flag(dt.date(2026, 10, 4))
check("⑤ 公布 37 天後：列為訊號、標題寫出涵蓋期間",
      f is not None and "2025/4–2026/3" in f.headline and "-7.9 萬" in f.headline,
      f and f.headline)
check("⑤b 屬於「改變頭條數字的解讀」、方向利降息",
      f.lean == "dovish" and R.TIER_OF[f.key] == 1)
check("⑤c 公布 75 天後不再列（只留修正卡）", bm_flag(dt.date(2026, 11, 20)) is None)
check("⑤d 沒有設定 → 不列", R.r_benchmark(R.RuleContext()) is None)


# ⑥ 人力流動總結（不是訊號）
def jolts(pre, now):
    rows = [{"date": f"{2015 + i // 12}-{i % 12 + 1:02d}-01", "value": pre}
            for i in range(60)]
    rows.append({"date": "2026-06-01", "value": now})
    return rows


def flow(h, l):
    # 基準取實際的疫情前平均（招聘 3.76、裁員 1.23）
    return R.flow_summary({"JTSHIR": jolts(3.76, h), "JTSLDR": jolts(1.23, l)})


check("⑥ 3.4／1.1 → 低招聘、低裁員", flow(3.4, 1.1)["name"] == "低招聘、低裁員")
check("⑥b 差距 0.1 以內算正常 → 招聘正常、裁員正常",
      flow(3.7, 1.3)["name"] == "招聘正常、裁員正常")
check("⑥c 低招聘＋高裁員 → 收縮型態", "收縮" in flow(3.2, 1.6)["meaning"])
check("⑥d 沒有疫情前資料 → None（不硬判）",
      R.flow_summary({"JTSHIR": jolts(3.8, 3.4)[-3:],
                      "JTSLDR": jolts(1.2, 1.1)[-3:]}) is None)
check("⑥e 低招聘低裁員不再是訊號",
      all(r.__name__ != "r_low_hire_low_fire" for r in R.RULES))

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
