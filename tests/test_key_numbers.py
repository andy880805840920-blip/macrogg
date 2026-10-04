# 就業頁「關鍵數字」（2026-10 改版）的回歸測試（不打網路）
#
# 由來（使用者指出）：
#   · 非農卡不宜用「歷史規律推估」當預期——改放民間／政府拆分
#   · 失業率的分母是勞動力（有工作＋正在找工作），先前文字寫錯
#   · 低度就業（U-6）整組移除
#   · 平均時薪要能看實質（用 CPI-U 平減）
#   · 失業率基準統一用 SEP（拿掉 CBO 自然失業率）
#   · 失業原因看比重變化，不只看人數
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src import build, fixtures                              # noqa: E402
from src.analysis import regime, rules, surprise as sp      # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過 " if cond else "失敗 "), name, ("— " + str(detail)[:140]) if detail else "")
    ok = ok and bool(cond)


def mrows(vals, y0=2025, m0=1):
    out = []
    for i, v in enumerate(vals):
        y, m = y0 + (m0 - 1 + i) // 12, (m0 - 1 + i) % 12 + 1
        out.append({"date": f"{y}-{m:02d}-01", "value": v})
    return out


# ① 實質薪資：用兩者都有的最新月份；(1+w)/(1+p)−1
ahe = mrows([100.0] + [100.0] * 11 + [103.2, 103.3])          # 2025-01 … 2026-02
cpi = mrows([300.0] + [300.0] * 11 + [308.7])                 # 只到 2026-01
r = build._real_wage(ahe, cpi)
check("① 時薪比 CPI 早一個月：實質薪資只算到兩者都有的月份",
      r is not None and r["month"] == "2026-01", r)
check("①b 公式＝(1.032/1.029)−1", abs(r["real"] - ((1.032 / 1.029) - 1) * 100) < 1e-9, r)
check("①c 缺 CPI → None", build._real_wage(ahe, []) is None)

# ② 非農不再用時間序列模型冒充預期
s = sp.evaluate("非農", mrows([100, 120, 90, 150, 130]), None, "none",
                allow_model=False)
check("② 沒填市場共識 → 不產生預期值", s.expected is None and s.source == "none")

# ③ 低度就業（U-6）與隱藏性失業整組移除
check("③ U-6 不在綜合分數權重裡", "U6RATE" not in regime.DEFAULT_WEIGHTS)
check("③b 隱藏性失業規則已移除",
      all(f.__name__ != "r_u6_gap_widening" for f in rules.RULES))

# ④ 用示範資料組一次完整的就業頁 context
import yaml                                                  # noqa: E402
ROOT = pathlib.Path(__file__).resolve().parents[1]
cfg = yaml.safe_load((ROOT / "config" / "indicators.yaml").read_text(encoding="utf-8"))
ser = fixtures.build()
labels, inverts = {}, {}
for grp in cfg.values():
    if isinstance(grp, list):
        for it in grp:
            if isinstance(it, dict) and "id" in it:
                labels[it["id"]] = it.get("label", it["id"])
                inverts[it["id"]] = it.get("invert", False)
ctx = build.build_labor_context(cfg, ser, fixtures.build_vintages(), labels, inverts,
                                [], True)
k = ctx["kpi"]
check("④ 非農副標＝民間／政府拆分", k["nfp_sub"].startswith("民間 ")
      and "政府" in k["nfp_sub"], k["nfp_sub"])
check("④b 民間＋政府＝非農", abs((k["nfp_priv"] + k["nfp_gov"])
                               - (ser["PAYEMS"][-1]["value"] - ser["PAYEMS"][-2]["value"])) < 1e-6)
check("④c 失業率白話：分母是勞動力", "勞動力" in k["u3_plain"]
      and "有在找工作的人裡" not in k["u3_plain"], k["u3_plain"])
check("④d 失業率副標沒有低度就業", "低度就業" not in k["u3_sub"], k["u3_sub"])
check("④e 時薪副標有實質薪資（CPI-U 平減）", "實質" in k["ahe_sub"]
      and "CPI-U" in k["ahe_sub"], k["ahe_sub"])
check("④f 失業缺口改用 SEP", ctx["ustar"].get("lo") is not None, ctx["ustar"])
us = ctx["unemp_structure"]
check("④g 失業結構有比重與比重變化", all("share_yoy_display" in r for r in us["rows"]))

# ⑤ 頁面
from src.pages import labor as L                            # noqa: E402
html = L._labor_body_full({**ctx, "asof": {}, "mini": {}})
check("⑤ 頁面沒有「歷史規律推估」與「預期值目前來自時間序列模型」",
      "歷史規律" not in html and "時間序列模型" not in html)
check("⑤b 頁面沒有 CBO 自然失業率", "CBO" not in html)
check("⑤c 名詞解釋的失業率分母寫對", "勞動力（有工作的人＋正在找工作的人）" in html)

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
