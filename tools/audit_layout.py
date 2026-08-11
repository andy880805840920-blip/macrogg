"""
手機／桌機版面稽核（量測式，不看截圖）。

為什麼要有這個
--------------
版面問題用眼睛看很容易漏：溢出四個像素、觸控目標少了六個像素、
某一列比隔壁高兩倍——這些在截圖上都不明顯，但在手上很明顯。
這支腳本直接量 DOM，把「說得出數字」的問題列出來。

    python tools/audit_layout.py            # 預設 360/390/760/1040/1280
    python tools/audit_layout.py 360 390    # 只量指定寬度

需要 playwright（chromium 已預先安裝）。找不到就直接跳過，不讓它擋住其他測試。
"""
from __future__ import annotations

import sys
import pathlib
import http.server
import socketserver
import threading
import functools

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "output"
PAGES = ["/", "/labor/", "/inflation/", "/fomc/", "/rates/",
         "/scenario/", "/archive/"]
WIDTHS = [int(a) for a in sys.argv[1:]] or [360, 390, 760, 1040, 1280]

# 觸控目標的下限。WCAG 2.5.8（AA）是 24px，Apple HIG 與 Material 都用 44px；
# 這裡取 44 當目標值、40 當硬性下限，因為有些純文字連結撐到 44 會破壞行距。
TAP_MIN = 40

# 量測用的 JS。回傳一包純資料，Python 這邊只負責判讀與排版，
# 這樣新增檢查時不必來回改兩邊的結構。
PROBE = r"""
() => {
  const vw = document.documentElement.clientWidth;
  const out = {overflow: [], tap: [], ratio: [], clipped: []};

  const label = el => {
    const cls = (el.className || "").toString().trim().split(/\s+/)
                  .filter(Boolean).slice(0, 2).join(".");
    return el.tagName.toLowerCase() + (cls ? "." + cls : "");
  };

  // 這個元素是不是被包在「刻意可以橫向捲動」的容器裡。
  // 導覽列、章節跳轉列、寬表格都是這種——它們的子元素超出視窗是設計，
  // 不是 bug。判斷方式是往上找有沒有 overflow-x 為 auto/scroll 的祖先。
  const inScroller = el => {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const ox = getComputedStyle(p).overflowX;
      if (ox === "auto" || ox === "scroll") return true;
    }
    return false;
  };

  // ① 橫向溢出：任何元素的右緣超出視窗
  for (const el of document.querySelectorAll("body *")) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    const style = getComputedStyle(el);
    if (style.position === "fixed") continue;
    if (inScroller(el)) continue;
    if (r.right > vw + 0.5) {
      out.overflow.push({el: label(el), right: +r.right.toFixed(1),
                         over: +(r.right - vw).toFixed(1),
                         text: (el.textContent || "").trim().slice(0, 40)});
    }
  }

  // ② 觸控目標：可點的東西高度不足。
  // 句子中間的行內連結不算——WCAG 2.5.8 明文豁免（"in a sentence"），
  // 而且把它撐到 44px 會破壞行距。判斷方式：display 是 inline，
  // 而且同一個父層裡還有其他非空白的文字節點。
  const inSentence = el => {
    if (!getComputedStyle(el).display.startsWith("inline")) return false;
    const p = el.parentElement;
    if (!p) return false;
    return [...p.childNodes].some(
      n => n.nodeType === 3 && n.textContent.trim().length > 0);
  };
  for (const el of document.querySelectorAll("a, button, summary, label")) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (getComputedStyle(el).display === "none") continue;
    if (inSentence(el)) continue;
    if (r.height < %(tap)d) {
      out.tap.push({el: label(el), h: +r.height.toFixed(1),
                    text: (el.textContent || "").trim().slice(0, 30)});
    }
  }

  // ③ 同一組卡片高度差太多（齊高造成的空白）
  // 九宮格要只比 .scell——它的 children 還包含軸標籤，那本來就矮。
  const groups = [[".lights", null], [".stat-row", null], [".cons-row", null],
                  [".modcards", null], [".kpis", null], [".sgrid", ".scell"]];
  for (const [sel, childSel] of groups) {
    for (const g of document.querySelectorAll(sel)) {
      const raw = childSel ? [...g.querySelectorAll(childSel)] : [...g.children];
      const kids = raw.filter(k => k.getBoundingClientRect().height > 0);
      if (kids.length < 2) continue;
      const hs = kids.map(k => k.getBoundingClientRect().height);
      const lo = Math.min(...hs), hi = Math.max(...hs);
      if (lo > 0 && hi / lo > 2.2) {
        out.ratio.push({el: sel, lo: +lo.toFixed(0), hi: +hi.toFixed(0),
                        ratio: +(hi / lo).toFixed(2)});
      }
    }
  }

  // ④ 內容被容器裁掉（overflow:hidden 但塞不下）
  for (const el of document.querySelectorAll("body *")) {
    const style = getComputedStyle(el);
    if (style.overflow !== "hidden" && style.overflowX !== "hidden") continue;
    if (el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0) {
      out.clipped.push({el: label(el), scroll: el.scrollWidth,
                        client: el.clientWidth});
    }
  }
  return out;
}
""" % {"tap": TAP_MIN}


def serve(directory: pathlib.Path):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(directory))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    httpd.allow_reuse_address = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright 未安裝，跳過版面稽核")
        return 0
    if not (OUT / "index.html").exists():
        print("output/ 還沒有內容，先跑 python run.py --offline")
        return 1

    httpd, port = serve(OUT)
    problems = 0
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for w in WIDTHS:
                page = browser.new_page(viewport={"width": w, "height": 900},
                                        device_scale_factor=2)
                for path in PAGES:
                    page.goto(f"http://127.0.0.1:{port}{path}",
                              wait_until="load")
                    r = page.evaluate(PROBE)
                    hits = []
                    for o in r["overflow"]:
                        hits.append(f"溢出 {o['over']}px  {o['el']}  "
                                    f"{o['text']}")
                    # 觸控目標只在手機寬度檢查
                    if w <= 430:
                        seen = set()
                        for t in r["tap"]:
                            k = (t["el"], t["h"])
                            if k in seen:
                                continue
                            seen.add(k)
                            hits.append(f"觸控 {t['h']}px  {t['el']}  "
                                        f"{t['text']}")
                    for g in r["ratio"]:
                        hits.append(f"高度差 {g['ratio']}×  {g['el']}  "
                                    f"{g['lo']}→{g['hi']}px")
                    for c in r["clipped"]:
                        hits.append(f"被裁切  {c['el']}  "
                                    f"{c['client']}<{c['scroll']}")
                    if hits:
                        problems += len(hits)
                        print(f"\n[{w}px] {path}")
                        for h in hits[:12]:
                            print("   ", h)
                        if len(hits) > 12:
                            print(f"    …另有 {len(hits) - 12} 項")
                page.close()
            browser.close()
    finally:
        httpd.shutdown()

    print()
    print("版面稽核：沒有發現問題" if not problems
          else f"版面稽核：{problems} 項待處理")
    return 0


if __name__ == "__main__":
    sys.exit(main())
