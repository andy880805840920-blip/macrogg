"""
對比度稽核（WCAG 2.1 AA）。

量的是實際算繪出來的顏色，不是原始碼裡的色票——半透明背景、
繼承來的文字色、疊在卡片上的卡片，這些用讀 CSS 的方式都算不準。
背景會沿著祖先往上找，遇到 alpha 就照 alpha 混色。

門檻：一般文字 4.5、大字（≥18.66px 粗體 或 ≥24px）3.0。

    python tools/audit_contrast.py
"""
from __future__ import annotations

import sys
import pathlib
import http.server
import socketserver
import threading
import functools

OUT = pathlib.Path(__file__).resolve().parent.parent / "output"
PAGES = ["/", "/labor/", "/inflation/", "/fomc/", "/rates/",
         "/scenario/", "/archive/"]

PROBE = r"""
() => {
  const parse = c => {
    const m = c.match(/[\d.]+/g);
    if (!m) return null;
    return [+m[0], +m[1], +m[2], m.length > 3 ? +m[3] : 1];
  };
  // 沿著祖先往上收集所有非全透明的背景層，再**由下往上**依序合成。
  // 收一層混一層是錯的：第一輪會拿同一個顏色跟自己混，
  // 半透明的色塊會被當成不透明，量出來的對比度反而偏樂觀。
  const bgOf = el => {
    const layers = [];
    for (let p = el; p; p = p.parentElement) {
      const c = parse(getComputedStyle(p).backgroundColor);
      if (!c || c[3] === 0) continue;
      layers.push(c);
      if (c[3] >= 1) break;              // 碰到不透明就不必再往上找
    }
    layers.push([255, 255, 255, 1]);     // 最底層當白色
    let out = layers[layers.length - 1];
    for (let i = layers.length - 2; i >= 0; i--) {
      const c = layers[i], a = c[3];
      out = [c[0] * a + out[0] * (1 - a),
             c[1] * a + out[1] * (1 - a),
             c[2] * a + out[2] * (1 - a), 1];
    }
    return out;
  };
  const lum = ([r, g, b]) => {
    const f = v => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const ratio = (a, b) => {
    const l1 = lum(a), l2 = lum(b);
    return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
  };

  const out = [];
  const seen = new Set();
  for (const el of document.querySelectorAll("body *")) {
    // 只看直接含文字的元素
    const own = [...el.childNodes]
      .filter(n => n.nodeType === 3 && n.textContent.trim())
      .map(n => n.textContent.trim()).join(" ");
    if (!own) continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const st = getComputedStyle(el);
    if (st.visibility === "hidden" || +st.opacity === 0) continue;

    const fg = parse(st.color);
    if (!fg) continue;
    let color = fg;
    if (fg[3] < 1) {
      const b = bgOf(el), a = fg[3];
      color = [fg[0] * a + b[0] * (1 - a), fg[1] * a + b[1] * (1 - a),
               fg[2] * a + b[2] * (1 - a), 1];
    }
    const bg = bgOf(el);
    const size = parseFloat(st.fontSize);
    const bold = +st.fontWeight >= 700;
    const large = size >= 24 || (bold && size >= 18.66);
    const need = large ? 3.0 : 4.5;
    const got = ratio(color, bg);
    if (got < need) {
      const cls = (el.className || "").toString().trim()
                    .split(/\s+/).filter(Boolean).slice(0, 2).join(".");
      const key = el.tagName + cls + st.color + size;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({el: el.tagName.toLowerCase() + (cls ? "." + cls : ""),
                got: +got.toFixed(2), need, size,
                fg: st.color, text: own.slice(0, 34)});
    }
  }
  return out;
}
"""


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright 未安裝，跳過對比度稽核")
        return 0
    if not (OUT / "index.html").exists():
        print("output/ 還沒有內容，先跑 python run.py --offline")
        return 1

    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(OUT))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]

    total = 0
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            page = b.new_page(viewport={"width": 390, "height": 900})
            for path in PAGES:
                page.goto(f"http://127.0.0.1:{port}{path}", wait_until="load")
                hits = page.evaluate(PROBE)
                if hits:
                    total += len(hits)
                    print(f"\n{path}")
                    for h in hits:
                        print(f"    {h['got']:>5.2f} / 需 {h['need']}  "
                              f"{h['el']}  {h['fg']}  {h['size']:.0f}px  "
                              f"{h['text']}")
            b.close()
    finally:
        httpd.shutdown()

    print()
    print("對比度：全部通過 AA" if not total else f"對比度：{total} 項不足")
    return 0


if __name__ == "__main__":
    sys.exit(main())
