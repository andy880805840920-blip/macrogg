# 新增的十條關鍵訊號：每條各驗「該亮會亮、不該亮不亮」
import sys
import pathlib
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.analysis import rules as R                        # noqa: E402
from src.analysis import rules_inflation as RI             # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過 " if cond else "失敗 "), name,
          ("— " + str(detail)[:80]) if detail else "")
    ok = ok and bool(cond)


def rows(vals, freq="m"):
    return [{"date": f"2026-{i:02d}", "value": v} for i, v in
            enumerate(vals, 1)] if len(vals) < 99 else [
        {"date": str(i), "value": v} for i, v in enumerate(vals)]


def _find(flags, key):
    return next((f for f in flags if f.key == key), None)


# ---------------- 勞動 ----------------
def lab_ctx(**series):
    return R.RuleContext(series=series)


# ① 續領/初領背離：初領低段＋續領高段才亮
ic_low = rows([205_000] * 59 + [200_000])                          # 最新一筆在低段
cc_high = rows([1_800_000 + i * 8000 for i in range(60)])          # 一路爬
f = R.r_claims_divergence(lab_ctx(ICSA=ic_low, CCSA=cc_high))
check("① 初領低＋續領高 → 背離訊號", f is not None and f.lean == "dovish",
      getattr(f, "headline", None))
cc_low = rows([1_800_000 - i * 5000 for i in range(60)])
check("①b 續領也低就不亮",
      R.r_claims_divergence(lab_ctx(ICSA=ic_low, CCSA=cc_low)) is None)

# ② 失業持續期間創近一年新高
med_hi = rows([9.5, 9.8, 9.6, 9.9, 10.0, 9.7, 9.8, 10.1, 10.2, 10.0,
               10.3, 10.4, 10.8])
check("② 持續期間新高會亮", R.r_duration_high(lab_ctx(UEMPMED=med_hi)) is not None)
med_flat = rows([10.8] * 13)
check("②b 全期同值（沒有真的創高）不亮",
      R.r_duration_high(lab_ctx(UEMPMED=med_flat)) is None)

# ③ 壯年就業比連三個月下滑且累計 ≥0.2pp
epop_slide = rows([80.6, 80.5, 80.4, 80.3])
check("③ 連三滑 0.3pp 會亮", R.r_prime_age_slide(lab_ctx(LNS12300060=epop_slide)) is not None)
epop_noise = rows([80.6, 80.5, 80.6, 80.5])
check("③b 來回震盪不亮", R.r_prime_age_slide(lab_ctx(LNS12300060=epop_noise)) is None)

# ④ U6−U3 差距半年擴大 ≥0.3pp
u3 = rows([4.1] * 7)
u6_wide = rows([7.3, 7.35, 7.4, 7.45, 7.5, 7.55, 7.65])
check("④ 差距擴大會亮", R.r_u6_gap_widening(lab_ctx(U6RATE=u6_wide, UNRATE=u3)) is not None)
u6_flat = rows([7.3] * 7)
check("④b 差距持平不亮", R.r_u6_gap_widening(lab_ctx(U6RATE=u6_flat, UNRATE=u3)) is None)

# ⑤ 派遣年減且惡化才亮
th_worse = rows([3000 - i * 8 for i in range(20)])                 # 年減擴大
f = R.r_temp_help(lab_ctx(TEMPHELPS=th_worse))
check("⑤ 派遣年減惡化會亮", f is not None and "派遣" in f.headline)
# 前段急跌、後段走平：年減仍為負、但比三個月前收斂（在改善）
th_recover = rows([3000 - i * 20 for i in range(10)] + [2820] * 10)
check("⑤b 年減但在改善不亮", R.r_temp_help(lab_ctx(TEMPHELPS=th_recover)) is None)

# ⑥ 製造業工時：近三月均低於近一年均 0.2 小時
wh_cut = rows([40.2] * 9 + [39.8, 39.7, 39.6])
check("⑥ 工時被砍會亮", R.r_factory_hours(lab_ctx(AWHMAN=wh_cut)) is not None)
wh_flat = rows([40.1, 40.2] * 6)
check("⑥b 工時平穩不亮", R.r_factory_hours(lab_ctx(AWHMAN=wh_flat)) is None)


# ---------------- 通膨 ----------------
def inf_ctx(series=None, **s):
    base = dict(ppi_core_yoy=None, core_yoy=None, sticky_cpi=None,
                flex_cpi=None, shelter_3m=None, expect_1y=None,
                expect_5y5y=None)
    base.update(s)
    return RI.InflationContext(series or {}, SimpleNamespace(**base),
                               None, [])


# ⑦ PPI 管線
f = RI.r_ppi_pipeline(inf_ctx(ppi_core_yoy=3.6, core_yoy=3.0))
check("⑦ PPI 高於 CPI 0.6pp → 管線壓力", f is not None and f.lean == "hawkish")
check("⑦b 差距 0.3pp 不亮",
      RI.r_ppi_pipeline(inf_ctx(ppi_core_yoy=3.3, core_yoy=3.0)) is None)
f = RI.r_ppi_pipeline(inf_ctx(ppi_core_yoy=2.4, core_yoy=3.0))
check("⑦c 上游明顯低 → 壓力消退（利降息）", f is not None and f.lean == "dovish")

# ⑧ 黏性鬆動：差距仍大＋半年回落 0.3pp
sticky_rows = rows([4.4, 4.3, 4.3, 4.2, 4.1, 4.1, 4.0])
f = RI.r_sticky_easing(inf_ctx(series={"CORESTICKM159SFRBATL": sticky_rows},
                               sticky_cpi=4.0, flex_cpi=1.9))
check("⑧ 黏性半年降 0.4pp → 鬆動訊號", f is not None and f.lean == "dovish")
sticky_stuck = rows([4.0] * 7)
check("⑧b 黏性卡住不亮",
      RI.r_sticky_easing(inf_ctx(series={"CORESTICKM159SFRBATL": sticky_stuck},
                                 sticky_cpi=4.0, flex_cpi=1.9)) is None)

# ⑨ 住房動能轉折：3m 年化低於年增 0.5pp
sh = rows([100 * (1.045 ** (i / 12)) for i in range(14)])           # 年增約 4.5%
f = RI.r_shelter_turn(inf_ctx(series={"CUSR0000SAH1": sh}, shelter_3m=3.5))
check("⑨ 住房 3m 明顯低於年增 → 轉折", f is not None and f.lean == "dovish")
check("⑨b 動能同速不亮",
      RI.r_shelter_turn(inf_ctx(series={"CUSR0000SAH1": sh}, shelter_3m=4.4))
      is None)

# ⑩ 預期組合
f = RI.r_expect_combo(inf_ctx(expect_1y=3.8, expect_5y5y=2.70))
check("⑩ 短長期同高 → 留意級利升息",
      f is not None and f.severity == "watch" and f.lean == "hawkish")
f = RI.r_expect_combo(inf_ctx(expect_1y=3.8, expect_5y5y=2.30))
check("⑩b 短高長錨定 → 參考級中性",
      f is not None and f.severity == "info" and f.lean == "neutral")
check("⑩c 兩者都正常不亮",
      RI.r_expect_combo(inf_ctx(expect_1y=3.0, expect_5y5y=2.30)) is None)

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
