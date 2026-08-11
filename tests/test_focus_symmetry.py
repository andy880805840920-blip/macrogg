"""
反應函數（detect_focus）的計分對稱性測試。

為什麼要有這個檔
----------------
detect_focus 是「三張九宮格要用哪一張」的唯一決定者，而它是純片語比對——
少一條對應項，判定就會有系統性偏誤，而且完全看不出來：每一次執行都一致，
只是一致地偏向同一邊。先前就發生過這件事：「通膨仍高於目標」有 +1，
就業側卻沒有對應的 −1，而那句話幾乎每份聲明都在。

    python tests/test_focus_symmetry.py
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from src.analysis.fomc_text import detect_focus, _EMPL_SOFT, _INFL_ABOVE  # noqa: E402

ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    print(f"{'通過' if cond else '失敗'}  {name}" + (f" — {detail}" if detail else ""))
    ok &= bool(cond)


# ---------------------------------------------------------------------------
# ① 片語比對本身不能誤判方向
# ---------------------------------------------------------------------------
# 失業率是「升＝弱」、就業增速是「降＝弱」，方向相反。
# 這兩組如果混在同一個字組裡，強勢聲明會被讀成轉弱。
SOFT_CASES = [
    ("Job gains have slowed and the unemployment rate has moved up.", True),
    ("The labor market has softened.", True),
    ("Payroll growth has moderated.", True),
    ("Hiring has cooled notably.", True),
    ("The unemployment rate ticked up to 4.3 percent.", True),
    # 以下都是**偏強**或與就業無關，不能命中
    ("Job gains have increased and the unemployment rate has declined.", False),
    ("The unemployment rate has remained low and job gains have been solid.", False),
    ("Labor market conditions remain solid; inflation has eased.", False),
    ("Inflation has eased over the past year but remains elevated.", False),
    ("Economic activity has continued to expand at a solid pace.", False),
]
bad = [t for t, want in SOFT_CASES if bool(_EMPL_SOFT.search(t)) != want]
check("① 就業轉弱片語不誤判", not bad, f"誤判 {len(bad)} 句" if bad else "10 句全對")

INFL_CASES = [
    ("Inflation remains somewhat elevated.", True),
    ("Inflation is still above the Committee's 2 percent objective.", True),
    ("Inflation has returned to the Committee's 2 percent objective.", False),
]
bad = [t for t, want in INFL_CASES if bool(_INFL_ABOVE.search(t)) != want]
check("② 通膨偏高片語不誤判", not bad)


# ---------------------------------------------------------------------------
# ② 對稱性：把一份聲明的兩側對調，分數必須反號
# ---------------------------------------------------------------------------
# 這是最重要的一條。任何只加在單邊的條款都會讓這個檢查失敗。
# 用聲明真正的制式句，不要自己造句——比對表收的就是這些固定片語。
HAWK = ("The Committee sees upside risks to inflation. "
        "Inflation remains elevated relative to the 2 percent objective.")
DOVE = ("The Committee sees downside risks to employment. "
        "Job gains have slowed and the labor market has softened.")

h = detect_focus(HAWK, {})
d = detect_focus(DOVE, {})
check("③ 鏡像聲明分數反號", h["score"] == -d["score"],
      f"{h['score']:+d} vs {d['score']:+d}")
check("④ 鏡像聲明判定相反",
      {h["focus"], d["focus"]} == {"inflation", "employment"},
      f"{h['focus']} vs {d['focus']}")

# 兩側同時出現時要互相抵消，不能因為單邊多一條而殘留淨值。
# 注意分數歸零 ≠「兩邊並重」——後者只在聲明明講 risks are in balance 時成立，
# 訊號互相抵銷是「無法判定」，這兩者的中文說明完全不同。
both = detect_focus(HAWK + " " + DOVE, {})
check("⑤ 兩側都提到 → 淨值為零", both["score"] == 0, f"{both['score']:+d}")
check("⑥ 抵銷判為無法判定、不是並重", both["focus"] == "unknown", both["focus"])

# 真的說「兩邊風險大致平衡」時才是 balanced
bal = detect_focus(
    "The risks to achieving its employment and inflation goals are "
    "roughly in balance.", {})
check("⑦ 聲明明講平衡 → 兩邊並重", bal["focus"] == "balanced", bal["focus"])


# ---------------------------------------------------------------------------
# ③ 現況描述的權重必須低於風險制式句
# ---------------------------------------------------------------------------
# 「通膨仍偏高」是現況陳述，「通膨上行風險」是委員會的風險判斷，
# 後者才是重心的直接證據。如果兩者同分，一份只描述現況的聲明
# 會跟一份明確點名風險的聲明得到一樣的判定。
only_state = detect_focus("Inflation remains elevated.", {})
only_risk = detect_focus("The Committee sees upside risks to inflation.", {})
check("⑧ 現況描述權重低於風險句",
      0 < only_state["score"] < only_risk["score"],
      f"現況 {only_state['score']:+d} < 風險 {only_risk['score']:+d}")


# ---------------------------------------------------------------------------
# ④ 沒有線索時不能硬給答案
# ---------------------------------------------------------------------------
blank = detect_focus("", {})
check("⑨ 空聲明 → 不硬判", blank["focus"] == "unknown", blank["focus"])

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
