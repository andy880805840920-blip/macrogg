"""
「各模組同不同意」那句話的迴歸測試。

這段邏輯搬過家：先前是首頁結論卡上的 `_consensus_row`（三個色塊 ＋ 一句話），
量到它佔掉結論卡的一半（358／711px）卻只顯示十幾個字，而且跟旁邊的定位列
講同一件事。現在併進「整體情勢」總述的第一句（`brief._direction`）。

分支寫錯的後果沒有變：在首頁最顯眼的位置印出一句錯的結論。所以分支照樣要釘住——
尤其是**有模組判不出方向**那一種：如果只印「三方裡兩方偏升息」，
讀者會自己去補那個差額（「第三方呢？偏降息嗎？」），而答案其實是中性。

長端一樣不進票數：曲線形狀不是政策方向。它在總述的最後一句單獨交代
（財政與 AI 一起推長端供給），由 test_brief.py 釘住。

    python tests/test_home_consensus.py
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from src.analysis import brief  # noqa: E402

ok = True
D, H, N = "dovish", "hawkish", "balanced"


class S:
    regime = "inflation"


def line(dirs):
    return brief._direction(S(), [(f"m{i}", d) for i, d in enumerate(dirs)])


cases = [
    ("全部偏鷹", [H, H, H], ["三方一致偏升息"]),
    ("全部偏鴿", [D, D, D], ["三方一致偏降息"]),
    ("兩鷹一鴿", [H, H, D], ["三方裡兩方偏升息", "一方偏降息", "分歧"]),
    ("兩鴿一鷹", [D, D, H], ["三方裡兩方偏降息", "一方偏升息", "分歧"]),
    ("正好對半", [H, D], ["兩方裡一方偏升息", "一方偏降息", "分歧"]),
    ("兩鷹一中性", [H, H, N], ["三方裡兩方偏升息", "其餘中性"]),
    ("一鴿兩中性", [D, N, N], ["三方裡一方偏降息", "其餘中性"]),
]
for name, dirs, wants in cases:
    got = line(dirs)
    hit = all(w in got for w in wants)
    print(f"{'通過' if hit else '失敗'}  {name:10s} → {got[22:]}")
    ok &= hit

# 全部中性 → 不硬掰共識，只留前半句（政策含意由結尾的重點句負責）
got = line([N, N, N])
hit = got.endswith("擺在前面。") and "方裡" not in got
print(f"{'通過' if hit else '失敗'}  全部中性     → {got}")
ok &= hit

# 只有一個模組時沒有「共識」可言
got1 = line([H])
print(f"{'通過' if '方裡' not in got1 else '失敗'}  只有一個模組 → {got1}")
ok &= "方裡" not in got1

# 方向字串出乎預期時不能爆掉，也不能印出原始英文
got2 = line(["???", H])
print(f"{'通過' if '???' not in got2 else '失敗'}  未知方向字串 → 不外洩到畫面")
ok &= "???" not in got2

# 體制決定前半句：三種體制的開場句必須不同，否則「誰優先」這件事沒講出來
uniq = len({brief._REGIME_LEAD[r]
            for r in ("inflation", "employment", "balanced")}) == 3
print(f"{'通過' if uniq else '失敗'}  三種體制各有各的開場句")
ok &= uniq


# 判不出體制時整段不出現——寧可少講一句，也不要印一句沒有依據的話
class NoRegime:
    regime = ""


empty = brief._direction(NoRegime(), [("a", H), ("b", H)]) == ""
print(f"{'通過' if empty else '失敗'}  判不出體制 → 整段不出現")
ok &= empty

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
