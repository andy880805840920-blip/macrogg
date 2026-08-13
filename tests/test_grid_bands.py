"""
九宮格兩條軸的門檻與「為什麼落在這一格」的說明。

為什麼需要這個檔案
------------------
通膨軸的門檻先前是寫死的 2.3／2.9，程式碼與文件裡**沒有任何依據**——
而它決定整張固定收益部位對照表（跨過去，存續期間建議從「中性偏長」
變成「縮短」）。現在改成錨在聯準會自己給的兩個數字：

    低 = 長期通膨目標（PCECTPIMDLR）+ 0.25
    高 = FOMC 對「明年」的核心 PCE 預測中位數（JCXFEMD）

三件事錯了會很難發現：

  ① 取到「今年」而不是「明年」的預測 → 門檻大幅放寬。2026 年 6 月的 SEP
     把 2026 年核心 PCE 預測在 3.2–3.5%，而實際也在 3.3%——用今年的預測
     當門檻會判成「不高」，但同一份聲明裡有三票主張升息。
  ② 預測收斂到 2.0 時 high 掉到 low 底下 → 兩條門檻交叉，中間帶消失
  ③ 抓不到 SEP 時沒有退路 → 整頁失效

另外釘住「方向 vs 水準」的對照說明：那是讀者覺得
「通膨頁說方向不明、九宮格說通膨高」是 bug 的唯一解釋，
只在真的會被誤讀的組合上出現，同向時不能印。

    python tests/test_grid_bands.py
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from src.analysis import inflation as infl          # noqa: E402
from src.analysis import scenario as scn            # noqa: E402
from src.pages.scenario import _mismatch_note       # noqa: E402

ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    print(f"{'通過' if cond else '失敗'}  {name}" + (f" — {detail}" if detail else ""))
    ok &= bool(cond)


def summ(target=2.0, nxt=2.5, year=2027, lo=2.3, hi=2.6):
    s = infl.InflationSummary()
    s.sep_target, s.sep_next = target, nxt
    s.sep_next_year, s.sep_next_lo, s.sep_next_hi = year, lo, hi
    return s


# ---------------------------------------------------------------------------
# ① 門檻取值
# ---------------------------------------------------------------------------
b = infl.inflation_bands(summ())
check("① 低＝長期目標 + 0.25", abs(b["low"] - 2.25) < 1e-9, str(b["low"]))
check("② 高＝明年的預測中位數", abs(b["high"] - 2.50) < 1e-9, str(b["high"]))
check("③ 標記為自動取得", b["auto"] is True)
check("④ 出處字串寫得出來", "2027" in b["why"] and "長期目標" in b["why"], b["why"])

# 預測收斂到目標時，兩條門檻不能交叉
b2 = infl.inflation_bands(summ(nxt=2.0))
check("⑤ 預測收斂時門檻不交叉", b2["high"] > b2["low"],
      f'low {b2["low"]} / high {b2["high"]}')
check("⑥ 交叉時保留最小帶寬", abs(b2["high"] - 2.50) < 1e-9, str(b2["high"]))

# 抓不到 SEP → 退回後備並標示
b3 = infl.inflation_bands(summ(target=None))
check("⑦ 缺 SEP → 退回後備", (b3["low"], b3["high"]) == (2.30, 2.90), str(b3))
check("⑧ 後備要標示成沒有依據",
      b3["auto"] is False and "無外部依據" in b3["why"], b3["why"])
check("⑨ 缺明年的預測也一樣退回",
      infl.inflation_bands(summ(nxt=None))["auto"] is False)


# ---------------------------------------------------------------------------
# ② 分類
# ---------------------------------------------------------------------------
B = infl.inflation_bands(summ())          # 低 2.25 / 高 2.50
cases = [
    ("⑩ 遠高於門檻 → 高", 3.3, 3.5, "高"),
    ("⑪ 剛好在帶內 → 中", 2.4, 2.4, "中"),
    ("⑫ 回到目標 → 低", 2.0, 2.1, "低"),
    ("⑬ 邊界上緣不算高", 2.50, 2.50, "中"),
    ("⑭ 邊界下緣不算低", 2.25, 2.25, "中"),
]
for name, y, m, want in cases:
    got = scn.classify_inflation(y, m, B)
    check(name, got == want, f"{y}/{m} → {got}，預期 {want}")

# 加權：0.6 水準 + 0.4 動能
check("⑮ 加權算式", abs(scn.blended_inflation(3.0, 3.6) - 3.24) < 1e-9,
      str(scn.blended_inflation(3.0, 3.6)))
check("⑯ 沒有動能就只用水準", scn.blended_inflation(3.0, None) == 3.0)
check("⑰ 完全沒資料 → 中", scn.classify_inflation(None, None, B) == "中")

# 這是修過的 bug：動能項若送核心 CPI（長期比核心 PCE 高 0.3–0.5 個百分點），
# 混合水準會有固定往鷹的偏誤。這裡釘住「同一筆資料換成 CPI 會不會翻格」。
core_cpi_3m, core_pce_3m = 2.9, 2.3     # 典型的 CPI > PCE 楔子
check("⑱ 混用 CPI 動能會翻格（所以不能混）",
      scn.classify_inflation(2.4, core_cpi_3m, B) == "中"
      and scn.classify_inflation(2.4, core_pce_3m, B) == "中",
      f"CPI→{scn.classify_inflation(2.4, core_cpi_3m, B)}　"
      f"PCE→{scn.classify_inflation(2.4, core_pce_3m, B)}")


# ---------------------------------------------------------------------------
# ③ 「方向 vs 水準」的對照說明
# ---------------------------------------------------------------------------
n = _mismatch_note("通膨", "高", "balanced", 0, "離 2% 目標多遠")
check("⑲ 方向不明 × 水準高 → 要解釋", bool(n) and "不是同一件事" in n)
check("⑳ 解釋裡要同時出現兩邊的用詞",
      "本期方向不明" in n and "「高」" in n, n[:90])
check("㉑ 方向與水準同向 → 不印",
      _mismatch_note("通膨", "高", "hawkish", 3, "x") == "")
check("㉒ 水準高但方向偏鴿 → 也要解釋",
      bool(_mismatch_note("通膨", "高", "dovish", -3, "x")))
check("㉓ 水準中 → 不印（中跟任何方向都相容）",
      _mismatch_note("通膨", "中", "balanced", 0, "x") == "")
check("㉔ 就業側同樣成立",
      bool(_mismatch_note("就業", "弱", "hawkish", 2, "x"))
      and _mismatch_note("就業", "弱", "dovish", -4, "x") == "")
check("㉕ 沒有 tilt 不會爆", _mismatch_note("通膨", "高", None, None, "x") == "")


# ---------------------------------------------------------------------------
# ④ 就業軸：水準為主 ＋ 兩條外部錨的動能修正
#
# 三條依據都是外部標準，不是本站選的：
#   FOMC 對長期失業率的中央趨勢（＝聯準會認定的充分就業，帶寬＝委員的分歧）
#   Sahm 法則的 0.50（原始論文）
#   損益兩平就業增速（由人口成長 × 參與率 × 機構／家庭調查比推導）
#
# 最容易錯的一條：**只看水準**。聯準會 2024 年 9 月降息 2 碼時失業率約 4.2%，
# 低於當時多數的自然失業率估計——降息的理由是惡化的速度，不是水準。
# 純水準規則會完全錯過那一段，所以動能修正不能省。
# ---------------------------------------------------------------------------
def lab(u=4.1, lo=4.0, hi=4.3, sahm=0.13, under=False, score=-0.35, net=-4):
    return {"unrate": u, "u_lo": lo, "u_hi": hi,
            "sahm": sahm, "sahm_triggered": sahm >= 0.50,
            "below_breakeven": under,
            "score": score, "tilt": {"net": net}}


L = scn.classify_labor
cases = [
    ("㉖ 高於中央趨勢上緣 → 弱", lab(u=4.6), "弱", "level"),
    ("㉗ 低於中央趨勢下緣 → 強", lab(u=3.7), "強", "level"),
    ("㉘ 落在區間內 → 中", lab(u=4.1), "中", "level"),
    ("㉙ Sahm 觸發 → 直接弱（不管水準）", lab(u=3.7, sahm=0.6), "弱", "sahm"),
    ("㉚ 非農低於損益兩平不改中格", lab(u=4.1, under=True), "中", "level"),
    ("㉛ 非農低於損益兩平不改強格", lab(u=3.7, under=True), "強", "level"),
    ("㉜ 已經是弱就不再推", lab(u=4.6, under=True), "弱", "level"),
]
for name, d, want_s, want_b in cases:
    s, b = L(d["score"], d["tilt"], d)
    check(name, (s, b) == (want_s, want_b), f"得到 {s}／{b}")

# 動能只往「弱」推：就業轉強沒有公認規則，不能自己發明一條
check("㉝ 動能不會把「中」推成「強」",
      L(-0.35, {"net": 4}, lab(u=4.1))[0] == "中")

# 拿不到 SEP → 退回舊規則，而且要標示成 fallback（畫面靠它印警告）
nosep = lab()
nosep["u_lo"] = nosep["u_hi"] = None
s, b = L(-0.5, {"net": 0}, nosep)
check("㉞ 缺 SEP → 退回舊規則", (s, b) == ("弱", "fallback"), f"{s}／{b}")
s, b = L(-0.1, {"net": -4}, nosep)
check("㉟ 後備仍保留旗標淨值那一路", (s, b) == ("弱", "fallback"), f"{s}／{b}")
s, b = L(None, None, nosep)
check("㊱ 完全沒資料 → 中，不硬判", (s, b) == ("中", "fallback"), f"{s}／{b}")

# 這是換掉舊規則的理由：同一筆資料，舊規則靠自訂門檻、新規則靠外部標準
check("㊲ 新規則的依據不會是自訂門檻",
      L(-0.35, {"net": -4}, lab(u=4.1, under=True))[1] in
      ("level", "sahm"))

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
