# 就業頁「本期關鍵訊號」的分級（第二十二批）：只用一套「對結論的影響」
#   重要／留意／參考 改成依「對結論的影響」分級（格位／方向／背景），取代舊的小標＋寫死的嚴重度。
# 不打網路。  python tests/test_signal_impact.py
import sys
import pathlib
from types import SimpleNamespace as NS

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from src.analysis import rules as R  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過 " if cond else "失敗 "), name, ("— " + str(detail)[:160]) if detail else "")
    ok = ok and bool(cond)


def F(key, sev="watch"):
    return R.Flag(key, sev, key, "")


AX_EDGE = {"unrate": 4.1, "u_lo": 4.0, "u_hi": 4.3}    # 離下緣 0.1：貼近門檻
AX_MID = {"unrate": 4.2, "u_lo": 4.0, "u_hi": 4.4}     # 兩邊都還有 0.2
check("被裁員比重警戒＝影響格位（九宮格會往弱推一格）", R.impact_level(F("jl_alert", "alert"), AX_MID) == "grid")
check("失業率成因：貼近門檻＝影響格位", R.impact_level(F("bad_decline", "info"), AX_EDGE) == "grid")
check("失業率成因：區間中段＝影響方向", R.impact_level(F("bad_decline", "info"), AX_MID) == "dir")
check("失業率成因：已在區間外＝影響格位", R.impact_level(F("bad_rise"), {"unrate": 4.6, "u_lo": 4.0, "u_hi": 4.3}) == "grid")
check("沒有區間資料時不升級", R.impact_level(F("bad_rise"), {}) == "dir")
check("趨勢類＝影響方向", all(R.impact_level(F(k), AX_MID) == "dir" for k in R.DIR_KEYS))
check("薪資組成、調查分歧＝背景",
      all(R.impact_level(F(k), AX_MID) == "bg" for k in ("wage_overstated", "wage_understated", "survey_divergence")))
fl = [F("wage_overstated", "alert"), F("continuing_claims_high", "alert"), F("bad_decline", "info"), F("jl_alert", "alert")]
g = R.by_impact(fl, AX_EDGE)
check("分組順序：格位→方向→背景", [k for k, _ in g] == ["grid", "dir", "bg"], g)
check("同層維持原先後", [f.key for f in g[0][1]] == ["bad_decline", "jl_alert"], [f.key for f in g[0][1]])
check("嚴重度不被改（鷹鴿淨值靠它）", fl[2].severity == "info" and fl[0].severity == "alert")
check("標籤名稱沿用重要／留意／參考", [R.IMPACT_LABEL[k] for k in ("grid", "dir", "bg")] == ["重要", "留意", "參考"])

# 頁面：沒有「重要／留意／參考」與舊小標；前三則以外收合
from src.pages import labor as LP  # noqa: E402
html = LP._flag_row(F("continuing_claims_high", "alert"), "dir")
check("標籤跟著影響層級，不跟嚴重度（嚴重度是重要，影響是留意）", ">留意<" in html and ">重要<" not in html)
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
