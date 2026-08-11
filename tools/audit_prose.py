"""
文字密度稽核：讀一個卡區時，有多少字是「方法論」。

這個網站是給投資人看的，打開一張卡先看到的應該是**數字與它對利率的意思**。
方法論、名詞定義、來源註腳都該有，但不該擋在閱讀動線上。這支腳本把每頁的
文字分成四類：

    卡區內文  打開一張卡之後讀到的東西                ← 分母
      └ 方法層  hint／src／gloss 這類解釋性文字        ← 目標 20% 以下
    證據層    卡區內部再摺一層的支撐數字（點開才看到）  ← 中性，不計入分母
    方法區    頁尾整張的「名詞解釋／判讀說明」          ← 本來就該全是方法論

「方法區」單獨列出來不併入比例：那一整張卡的存在目的就是方法論，而且預設
收合在頁尾，它並沒有擋住任何人。把它算進分母只會逼人去刪該留的東西。

    python tools/audit_prose.py       # 摘要
    python tools/audit_prose.py -v    # 附上每頁最長的幾段方法層文字
"""
from __future__ import annotations

import re
import sys
import pathlib

OUT = pathlib.Path(__file__).resolve().parent.parent / "output"
PAGES = ["index.html", "labor/index.html", "inflation/index.html",
         "fomc/index.html", "rates/index.html", "scenario/index.html"]

# 方法層的 class。這些是「解釋怎麼算的、名詞是什麼意思、資料哪裡來的」。
#
# 刻意**不含** dnote：它在 fomc 頁裝的是判定結論（「委員會目前把通膨擺在
# 前面…」）、在 rates 頁裝的是各公司的會計年度期末日——都是內容不是方法，
# 算進來會讓這個指標逼人去刪真正該留的東西。
METHOD_CLASSES = ("hint", "gloss", "src", "cd-n", "ug-note",
                  "us-note", "caveat")

# 整張都是方法論的卡區，單獨計算
METHOD_SECTIONS = ("glossary", "howto")


def strip_tags(s: str) -> str:
    return re.sub(r"\s+", "", re.sub(r"<[^>]+>", " ", s))


def _innermost(s: str):
    """找一個內部不再有 <details> 的區塊。巢狀時必須由內往外剝。"""
    return re.search(r"<details\b((?:(?!<details\b).)*?)</details>", s, re.S)


def analyse(html: str) -> dict:
    # 版面用的東西不算內容
    h = re.sub(r"<style.*?</style>", "", html, flags=re.S)
    h = re.sub(r"<svg.*?</svg>", "", h, flags=re.S)
    h = re.sub(r"<script.*?</script>", "", h, flags=re.S)
    h = re.sub(r"<nav.*?</nav>", "", h, flags=re.S)

    # ---- 先把整張都是方法論的卡區抽掉，單獨計 ----
    gloss_only = 0
    for sid in METHOD_SECTIONS:
        # 起點是這張卡的 <details>，終點要自己數層——它裡面可能還有摺疊區。
        start = h.find(f'<h2 id="{sid}"')
        if start < 0:
            continue
        open_at = h.rfind("<details", 0, start)
        if open_at < 0:
            continue
        depth, end = 0, None
        for m in re.finditer(r"<details\b|</details>", h[open_at:]):
            depth += 1 if m.group(0) == "<details" else -1
            if depth == 0:
                end = open_at + m.end()
                break
        if end is None:
            continue
        block = h[open_at:end]
        inner = re.sub(r"<summary.*?</summary>", "", block, count=1, flags=re.S)
        gloss_only += len(strip_tags(inner))
        h = h[:open_at] + h[end:]

    # ---- 卡區內部的摺疊區 ＝ 證據層，不進分母 ----
    # <details> 會巢狀（卡區裡面還有摺疊區），不能用非貪婪一次配對——
    # 那會從外層的開標籤配到內層的收標籤，把整段切壞。由內往外逐層剝。
    collapsed = 0
    body = h
    while True:
        m = _innermost(body)
        if not m:
            break
        block = m.group(0)
        if 'class="card sect"' in block[:60]:
            # 卡區：內容照算。把 details 標籤脫掉，避免下一輪再撈到同一段。
            body = (body[:m.start()] + re.sub(r"</?details[^>]*>", "", block)
                    + body[m.end():])
            continue
        inner = re.sub(r"<summary.*?</summary>", "", block, flags=re.S)
        collapsed += len(strip_tags(inner))
        body = body[:m.start()] + body[m.end():]

    # 收合摘要是結論的濃縮，而且只在收合時看得到，不算方法層
    body = re.sub(r'<span class="sect-sum">.*?</span>', "", body, flags=re.S)

    visible = len(strip_tags(body))
    method = 0
    hits: list[tuple[str, str]] = []
    for cls in METHOD_CLASSES:
        pat = rf'<(\w+)[^>]*class="[^"]*\b{cls}\b[^"]*"[^>]*>(.*?)</\1>'
        for m in re.finditer(pat, body, re.S):
            txt = strip_tags(m.group(2))
            if not txt:
                continue
            method += len(txt)
            hits.append((cls, re.sub(r"\s+", " ",
                                     re.sub(r"<[^>]+>", "", m.group(2))).strip()))

    return {"visible": visible, "collapsed": collapsed, "method": method,
            "gloss_only": gloss_only,
            "ratio": (method / visible * 100) if visible else 0,
            "hits": sorted(hits, key=lambda x: -len(x[1]))}


def main() -> int:
    verbose = "-v" in sys.argv
    if not (OUT / "index.html").exists():
        print("output/ 還沒有內容，先跑 python run.py --offline")
        return 1
    worst = 0.0
    for p in PAGES:
        r = analyse((OUT / p).read_text(encoding="utf-8"))
        worst = max(worst, r["ratio"])
        flag = "  ←" if r["ratio"] > 20 else ""
        print(f"{p:22s} 卡區內文 {r['visible']:5d} 字　"
              f"方法層 {r['method']:5d} 字（{r['ratio']:4.1f}%）　"
              f"證據層 {r['collapsed']:5d}　方法區 {r['gloss_only']:5d}{flag}")
        if verbose:
            for cls, txt in r["hits"][:6]:
                print(f"      [{cls}] {len(txt):4d} 字  {txt[:64]}")
    print()
    print(f"最高佔比 {worst:.1f}%　"
          + ("（目標 20% 以下）" if worst > 20 else "✓ 全部在 20% 以下"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
