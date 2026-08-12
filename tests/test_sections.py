"""
卡區收合機制的迴歸測試。

為什麼需要這個檔案
------------------
`site._collapse_sections()` 是一段對「已產生的 HTML」做的機械式轉換：
找到 `<div class="card">` 緊接 `<h2 id=...>`，數 div 的層數找到對應的
收標籤，再包成 `<details>`。這種轉換錯了不會拋例外——它只會靜靜地
少包一張卡、或是把收標籤配錯讓半頁內容跑到別的卡裡去，而畫面上
看起來只是「某一區怪怪的」。所以行為要釘住。

    python tests/test_sections.py
"""
import sys
import re
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from src import site  # noqa: E402

ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    print(f"{'通過' if cond else '失敗'}  {name}" + (f" — {detail}" if detail else ""))
    ok &= bool(cond)


C = site._collapse_sections

# ---------------------------------------------------------------------------
# ① 基本轉換
# ---------------------------------------------------------------------------
src = '<div class="card"><h2 id="a">標題</h2><p>內文</p></div>'
got = C(src)
check("① 包成 details", got.startswith('<details class="card sect">'), got[:40])
check("② summary 裡有 h2", '<summary><h2 id="a">標題</h2></summary>' in got)
check("③ 內文進 sect-body", '<div class="sect-body"><p>內文</p></div>' in got)
check("④ 收標籤成對", got.count("<details") == got.count("</details>") == 1)

# ---------------------------------------------------------------------------
# ② 巢狀 div：收標籤必須數層，不能配到第一個 </div>
# ---------------------------------------------------------------------------
src = ('<div class="card"><h2 id="a">標題</h2>'
       '<div class="x"><div class="y">深層</div></div>'
       '</div><p>卡片外面</p>')
got = C(src)
check("⑤ 巢狀 div 不會提早收尾", "深層" in got.split("</details>")[0])
check("⑥ 卡片外的內容留在外面",
      got.endswith("<p>卡片外面</p>") and "卡片外面" not in got.split("</details>")[0])

# ---------------------------------------------------------------------------
# ③ 屬性
# ---------------------------------------------------------------------------
got = C('<div class="card"><h2 id="a" data-open="1">T</h2><p>x</p></div>')
check("⑦ data-open 讓它預設展開", '<details class="card sect" open>' in got)

got = C('<div class="card"><h2 id="a" data-sum="摘要句">T</h2><p>x</p></div>')
check("⑧ data-sum 變成 sect-sum", '<span class="sect-sum">摘要句</span>' in got)
check("⑨ data-sum 不會殘留在 h2 上", 'data-sum' not in got)

got = C('<div class="card"><h2 id="a">T</h2><p>x</p></div>')
check("⑩ 沒有 data-sum 就不畫空的 span", 'sect-sum' not in got)

# ---------------------------------------------------------------------------
# ④ 不該被動到的東西
# ---------------------------------------------------------------------------
# KPI 卡沒有 h2，是「關鍵數字」那一區的內容，不能自己變成一個卡區
src = '<div class="card kpi"><div class="k-value">4.1%</div></div>'
check("⑪ KPI 卡不受影響", C(src) == src)
# 沒有 h2 的一般卡（例如抓取失敗清單）也不動
src = '<div class="card"><details class="plain"><summary>s</summary>x</details></div>'
check("⑫ 沒有 h2 的卡不受影響", C(src) == src)

# ---------------------------------------------------------------------------
# ⑤ 多張卡連續
# ---------------------------------------------------------------------------
src = ('<div class="grid">'
       '<div class="card"><h2 id="a">A</h2><p>1</p></div>'
       '<div class="card"><h2 id="b">B</h2><p>2</p></div>'
       '</div>')
got = C(src)
check("⑬ 兩張卡各包各的", got.count('<details class="card sect"') == 2)
check("⑭ 外層 grid 沒被吃掉",
      got.startswith('<div class="grid">') and got.endswith("</div>"))
check("⑮ 內容沒有錯位",
      "<p>1</p>" in got.split("</details>")[0]
      and "<p>2</p>" in got.split("</details>")[1])

# ---------------------------------------------------------------------------
# ⑥ 實際頁面：每一頁都要恰好一張預設展開的卡，而且每張都有摘要
# ---------------------------------------------------------------------------
OUT = pathlib.Path(__file__).parent.parent / "output"
pages = ["labor", "inflation", "fomc", "rates", "scenario"]
if (OUT / "labor" / "index.html").exists():
    for name in pages:
        h = (OUT / name / "index.html").read_text(encoding="utf-8")
        n = len(re.findall(r'<details class="card sect"', h))
        n_open = len(re.findall(r'<details class="card sect" open', h))
        summaries = re.findall(
            r'<summary><h2 id="[^"]+">.*?</h2>'
            r'(<span class="sect-sum">.*?</span>)?</summary>', h, re.S)
        no_sum = sum(1 for s in summaries if not s)
        check(f"⑯ {name}：卡區數與展開數", n >= 5 and n_open == 1,
              f"{n} 區、展開 {n_open} 區")
        check(f"⑰ {name}：每張都有收合摘要", no_sum == 0,
              f"{no_sum} 張沒有摘要")
        check(f"⑱ {name}：details 成對",
              h.count("<details") == h.count("</details>"),
              f"{h.count('<details')} vs {h.count('</details>')}")
        # 錨點導覽的每個目標都要真的存在，否則點了會停在原地
        anchors = re.findall(r'<nav class="anchors">(.*?)</nav>', h, re.S)
        ids = re.findall(r'href="#([^"]+)"', anchors[0]) if anchors else []
        missing = [i for i in ids if f'id="{i}"' not in h]
        check(f"⑲ {name}：錨點都指得到", not missing, str(missing))
        # 錨點列預設是隱藏的（height:0），由 JS 在展開三個卡區時才顯示。
        # 外框 .anav 少了的話 CSS 全部失效，那一列會變成常駐的裸連結——
        # 而且兩側的漸層是畫在外框上的，沒有外框就會用 mask 挖穿背景。
        check(f"⑳ {name}：錨點列有外框 .anav",
              '<div class="anav"><nav class="anchors">' in h)
        # 附錄類不該佔導覽的格子：讀者不會特地跳去看名詞解釋
        labs = re.findall(r'>([^<]+)</a>', anchors[0]) if anchors else []
        bad = [x for x in labs if x.startswith(("名詞解釋", "判讀說明"))]
        check(f"㉑ {name}：導覽不列附錄", not bad, str(bad))
        # 收合摘要裡「數字 ＋ 單位」與「標籤 ＋ 數字」之間要是不斷行空白。
        # 這一列是拿來掃視的，斷成「時薪年增 ⏎ 3.2%」讀者就得往下跳一行
        # 才確認得了數字——那正是收合設計要省掉的動作。
        sums = re.findall(r'<span class="sect-sum">(.*?)</span>', h, re.S)
        bad_gap = [s for s in sums
                   if re.search(r'[\d%）)] [\u4e00-\u9fff]', s)
                   or re.search(r'[\u4e00-\u9fff：] [+\-\d]', s)]
        check(f"㉒ {name}：摘要的數字與單位不分家", not bad_gap,
              str(bad_gap[:2]))
else:
    print("（output/ 尚未產生，跳過實際頁面的檢查）")

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
