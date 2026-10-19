"""
流動性頁的判讀文字要跟著當下狀態走，不能寫死某一種情況（2026-10）。
用三組假狀態（緊、穩定但緩衝薄、充裕）跑一次下拉內容，檢查用詞與數字方向一致。
"""
import sys
import re
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.analysis.regime import Light                 # noqa: E402
from src.pages import liquidity as P                   # noqa: E402

ok = True


def check(name, cond, extra=""):
    global ok
    print(("通過  " if cond else "失敗  ") + name + ("" if cond else f" — {extra}"))
    ok = ok and bool(cond)


def L(key, status, value, disp):
    return Light(key, key, "", value, None, status, disp, "flat", [])


def ctx(core, rrp_s, ratio, ci0, wam_chg, label, reason, paused=True, priv=89.1, tga=885.8):
    lights = [L("sofr_iorb", core, -2.0, "-2.0bp"), L("srf", core, 0.0 if core == "good" else 12.0, "x"),
              L("rrp", rrp_s, 0.3 if rrp_s != "good" else 300.0, "y"),
              L("tgcr", core, -3.8, "-3.8bp"), L("ratio", "good" if ratio >= 13 else "warning", ratio, f"{ratio}%"),
              L("rde", "good" if ci0 else "warning", -0.4, "-0.40"), L("wam", "good", wam_chg, "w"),
              L("bills", "good", priv, "b")]
    return {
        "liq_lights": lights, "liq_verdict": {"label": label, "reason": reason},
        "liq_trend": {"sofr_iorb": {"2025-11": 7.8, "2026-08": -0.8, "2026-09": -1.8, "2026-10": -1.8},
                      "srf": {"2025-12": 3.4, "2026-10": 0.0}, "rrp": {"2025-07": 150.0, "2025-08": 50.0, "2026-10": 0.3}},
        "qra": {"bills": 267.6, "cash_end": 850.0, "cash_end_date": "2026-12-31", "next": "2026-11-04"},
        "bill_net": {"mtd": {"month": "2026-10", "net": 94.9, "private": priv, "partial": True}},
        "rmp_last": {"start": "2026-10-15", "end": "2026-11-13", "rmp": 0.0 if paused else 10.0, "mbs": 14.6},
        "rmp_paused_since": "2026-08-14" if paused else "",
        "ratio_view": {"value": ratio}, "rde_view": {"value": -0.4, "lo95": -0.7 if ci0 else -0.9,
                                                    "hi95": 0.03 if ci0 else -0.1, "zero_in_ci": ci0},
        "mmf": {"wam_last": {"gov": 35.7, "gov_3m": 35.7 - wam_chg}},
        "liab": {"items": [{"key": "tga", "value": tga}]},
        "as_of": "2026-10-19",
    }


strip = lambda h: re.sub(r"<[^>]+>", "", h)

# ① 穩定但緩衝偏薄（現況）
d = ctx("good", "warning", 11.58, True, -5.6, "穩定，但緩衝偏薄", "ON RRP 緩衝見底、準備金占比低於 13%")
core, sup, w = strip(P._core_detail(d)), strip(P._support_detail(d)), strip(P._watch_detail(d))
check("① 結論沒有資金緊俏、點出緩衝原因", "現在沒有資金緊俏" in core and "ON RRP 緩衝見底" in core, core[-200:])
check("① MMF 縮短期限列為主要支撐", "主要靠「MMF 把錢留在短端」" in sup, sup[-300:])
check("① 不比項數", "項壓力" not in sup and "支撐大於壓力" not in sup)
check("① RMP 暫停列為壓力、TGA 降低列為支撐", "Fed 暫停 RMP" in sup and "TGA 會降低" in sup)
check("① 盯轉緊條件、重啟 RMP", "轉緊的觸發條件" in w and "重啟 RMP" in w)
check("① 繳稅日月底日正確（12/31）", "12/15–12/31" in w, w)

# ② 轉緊
d = ctx("critical", "warning", 9.5, False, 3.0, "轉緊", "SOFR − IORB", paused=False, tga=700.0)
core, sup, w = strip(P._core_detail(d)), strip(P._support_detail(d)), strip(P._watch_detail(d))
check("② 結論改說資金變貴", "資金已經變貴" in core and "現在沒有資金緊俏" not in core, core[-200:])
check("② 標題改為為什麼轉緊", "資金為什麼轉緊" in sup)
check("② 準備金跌破 10%、MMF 拉長列為壓力", "已跌破 2019 年危機的 10%" in sup and "MMF 拉長期限" in sup)
check("② RMP 持續列為支撐、TGA 回補列為壓力", "Fed 持續 RMP" in sup and "TGA 要回補" in sup)
check("② 盯回到穩定的條件、加大 RMP", "回到穩定的條件" in w and "加大 RMP" in w)

# ③ 充裕
d = ctx("good", "good", 14.2, True, 0.5, "充裕穩定", "核心與輔助指標都在正常區", priv=-50.0)
d["liq_trend"]["rrp"] = {"2026-09": 320.0, "2026-10": 300.0}
core, sup = strip(P._core_detail(d)), strip(P._support_detail(d))
check("③ 結論三者都正常", "價格、後援、緩衝都正常" in core, core[-200:])
check("③ 緩衝仍有餘額、準備金充足、T-Bills 淨贖回列為支撐",
      "仍有約" in core and "準備金充足" in sup and "T-Bills 淨贖回" in sup, sup)
check("③ 不會出現「緩衝偏薄」的句子", "緩衝都偏薄" not in sup)

if not ok:
    sys.exit(1)
print("\n全部通過")
