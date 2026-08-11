"""
首頁「政策方向一致度」的迴歸測試（長端另計、不進票數）。

那段有分支邏輯（全部一致／分歧／對半／只有單邊），而分支寫錯的後果是
在首頁最顯眼的位置印出一句錯的結論。這裡把每個分支都釘住。

    python tests/test_home_consensus.py
"""
import sys, pathlib, re
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from src.pages.home import _consensus_row

def note(dirs):
    html = _consensus_row(dirs)
    m = re.search(r'class="cons-note">(.*?)</div>', html, re.S)
    return re.sub(r"<[^>]+>", "", m.group(1)) if m else ""

D, H, N = "dovish", "hawkish", "neutral"
cases = [
    ("全部偏鷹", [("a", H)] * 4, ["全部指向利升息", "強度最高"]),
    ("全部偏鴿", [("a", D)] * 4, ["全部指向利降息", "強度最高"]),
    ("三鷹一鴿", [("a", H), ("b", H), ("c", H), ("d", D)],
     ["3 個偏利升息", "1 個偏利降息", "分歧"]),
    ("三鴿一鷹", [("a", D), ("b", D), ("c", D), ("d", H)],
     ["3 個偏利降息", "1 個偏利升息", "分歧"]),
    ("正好對半", [("a", H), ("b", H), ("c", D), ("d", D)],
     ["正好對半", "不該只信其中一邊"]),
    ("兩鷹兩中性", [("a", H), ("b", H), ("c", N), ("d", N)],
     ["2 個偏利升息", "沒有反向訊號"]),
    ("全部中性", [("a", N)] * 4, ["4 個模組都沒有明確方向"]),
    ("三個模組全中性", [("a", N)] * 3, ["3 個模組都沒有明確方向"]),
]
ok = True
for name, dirs, wants in cases:
    got = note(dirs)
    hit = all(w in got for w in wants)
    print(f"{'通過' if hit else '失敗'}  {name:8s} → {got[:56]}")
    ok &= hit

# 模組不足兩個時不該畫這一區（畫出來只是一個沒有比較對象的孤島）
for n in (0, 1):
    r = _consensus_row([("a", H)] * n)
    print(f"{'通過' if r == '' else '失敗'}  {n} 個模組 → 不顯示")
    ok &= (r == "")

# 方向字串出乎預期時不能爆掉，也不能印出原始英文
r = _consensus_row([("a", "???"), ("b", H)])
bad = "???" in r
print(f"{'通過' if not bad else '失敗'}  未知方向字串 → 不外洩到畫面")
ok &= not bad

# ---- 長端不進票數 ----
# 三個政策模組全鷹 ＋ 長端也偏鷹，票數仍然只能是 3；
# 若哪天有人把 curve 併回 dirs，這裡會抓到「4 個模組」。
r = _consensus_row([("a", H)] * 3, ("長端", H))
n1 = note([("a", H)] * 3)
hit = ("3 個模組" in n1 or "全部指向" in n1) and "4 個模組" not in r
print(f"{'通過' if hit else '失敗'}  長端偏鷹 → 不計入政策票數")
ok &= hit

# 但長端仍要出現在畫面上，而且要說明自己是另一個軸
r = _consensus_row([("a", H), ("b", D)], ("長端", H))
hit = "長端" in r and "曲線形狀" in r
print(f"{'通過' if hit else '失敗'}  長端仍然顯示，並標明是另一個軸")
ok &= hit

# 沒有長端資料時不該留下空殼
r = _consensus_row([("a", H), ("b", D)], None)
hit = "cons-aside" not in r
print(f"{'通過' if hit else '失敗'}  無長端資料 → 不畫空的附註區")
ok &= hit

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
