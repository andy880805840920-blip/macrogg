# 品牌頁首與置頂主選單（2026-10）的回歸測試——不打網路
import sys
import re
import pathlib
import datetime as dt

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src import site, clock                     # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過 " if cond else "失敗 "), name, ("— " + str(detail)[:200]) if detail else "")
    ok = ok and bool(cond)


U = dt.timezone.utc
w = clock.world_times(dt.datetime(2026, 10, 5, 11, 46, tzinfo=U))
check("① 三地時間（夏令）", w == [("台北", "19:46", "10/05"), ("紐約", "07:46", "10/05"),
                            ("倫敦", "12:46", "10/05")], w)
w = clock.world_times(dt.datetime(2026, 12, 9, 23, 30, tzinfo=U))
check("① 台北已跨日、紐約倫敦還在前一天（冬令）",
      w == [("台北", "07:30", "12/10"), ("紐約", "18:30", "12/09"), ("倫敦", "23:30", "12/09")], w)

h = site.page("通膨", "/inflation/", '<div class="card"><h2 id="a">A</h2><p>x</p></div>',
              subtitle="Consumer Price Index　·　資料月份 2026-08")
check("② 連結縮圖 og:image（絕對網址、1200×630）",
      'property="og:image" content="https://macrogg.netlify.app/brand/og.jpg?v=' in h
      and 'og:image:type" content="image/jpeg"' in h
      and 'og:image:width" content="1200"' in h)
check("② 每頁自己的 og:title 與描述", 'og:title" content="通膨｜MACRO GG"' in h
      and "CPI、PCE、PPI" in h)
check("② 桌面圖示與 manifest", 'rel="apple-touch-icon"' in h and 'rel="manifest"' in h
      and "favicon.ico" in h)
check("② 自架 Montserrat 並預載", 'href="/brand/montserrat-latin.woff2" as="font"' in h
      and 'font-family:"Montserrat",' in h)
check("③ 頁首：完整版與精簡版 LOGO、三地時間、EN",
      "logo-full.svg" in h and "logo-compact.svg" in h and h.count('class="upd-c"') == 3
      and 'class="lang-btn"' in h)
check("③ 頁首在 .viz-root 外（全寬），主選單緊接其後",
      h.index('class="brandwrap"') < h.index('class="bnav"') < h.index('class="viz-root"'))
check("④ 主選單：新名稱、目前分頁、太陽", ">就業</a>" in h and ">聯準會</a>" in h
      and 'href="/inflation/" class="on" aria-current="page"' in h and 'class="bnav-sun"' in h)
check("④ 舊的灰框主選單已移除", 'class="snav"' not in h and 'class="top"' not in h)
check("⑤ 內頁頁名在導覽列下方、副標不再重複更新時間",
      '<div class="pagehead"><h1>通膨</h1>' in h and "更新於" not in h.split("-->", 1)[1])
check("⑤ workflow 的 grep 仍抓得到「更新於」", bool(re.search(r"更新於 [0-9: -]+", h)))
home = site.page(site.SITE_NAME, "/", "<p>x</p>")
check("⑥ 首頁 h1 給螢幕閱讀器、標題是站名＋標語",
      '<h1 class="sr-only">MACRO GG｜明天過後，帶你看總經</h1>' in home
      and "<title>MACRO GG｜明天過後，帶你看總經</title>" in home)
check("⑦ CSS 變數掛在 :root（頁首在 .viz-root 外也拿得到）", ":root,.viz-root{" in site.CSS)
check("⑦ 章節列接在主選單下方、跳轉目標讓出置頂區",
      ".anav{position:sticky;top:var(--navh)" in site.CSS and "scroll-margin-top" in site.CSS)
root = pathlib.Path(__file__).resolve().parents[1] / "assets" / "brand"
need = ["logo-full.svg", "logo-compact.svg", "logo-mark.svg", "og.jpg", "apple-touch-icon.png",
        "icon-192.png", "icon-512.png", "icon-maskable-512.png", "favicon.ico", "favicon.svg",
        "montserrat-latin.woff2", "OFL-Montserrat.txt"]
check("⑧ 品牌素材齊全", all((root / f).exists() for f in need),
      [f for f in need if not (root / f).exists()])
from PIL import Image                           # noqa: E402
check("⑧ 連結縮圖 1200×630、iPhone 圖示 180×180",
      Image.open(root / "og.jpg").size == (1200, 630)
      and Image.open(root / "apple-touch-icon.png").size == (180, 180))

# ---- Threads／FB 縮圖：圖片不帶 noindex、JPEG 不帶 C2PA／XMP ----
import tomllib                                     # noqa: E402
import run                                         # noqa: E402
_nt = tomllib.loads((root.parents[1] / "netlify.toml").read_text(encoding="utf-8"))
_robots = [h["for"] for h in _nt["headers"] if "X-Robots-Tag" in h.get("values", {})]
check("③ noindex 標頭只掛頁面、不掛 /brand/ 與 /*",
      "/*" not in _robots and not any(p.startswith("/brand") for p in _robots)
      and "/" in _robots and "/fomc/*" in _robots, _robots)
_jpg = (b"\xff\xd8" + b"\xff\xe0\x00\x04ab" + b"\xff\xeb\x00\x06c2pa"
        + b"\xff\xe1\x00\x04xm" + b"\xff\xe2\x00\x04ic" + b"\xff\xda\x00\x02DATA\xff\xd9")
_c = run.clean_jpeg(_jpg)
check("③ clean_jpeg 去掉 APP1／APP11、保留 APP0／APP2 與影像資料",
      b"c2pa" not in _c and b"xm" not in _c and b"ab" in _c and b"ic" in _c and _c.endswith(b"DATA\xff\xd9"))
check("③ 不是 JPEG 就原樣回傳", run.clean_jpeg(b"GIF89a") == b"GIF89a")
_og = run.clean_jpeg((root / "og.jpg").read_bytes())
import io                                          # noqa: E402
check("③ 實際的 og.jpg 清完仍是 1200×630", Image.open(io.BytesIO(_og)).size == (1200, 630))

if not ok:
    sys.exit(1)
print("\n全部通過")
