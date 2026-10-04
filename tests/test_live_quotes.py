# 盤中報價（Python 端昨收規則＋首頁輪詢腳本＋Netlify 函式）的回歸測試
#
# 由來：Yahoo chart API 的 chartPreviousClose 是「圖表區間開始前」的收盤，
# range=5d 時可能是五天前——變動欄會變成五日變動。昨收改從日線自己找。
import sys
import shutil
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.analysis import focus_today as ft                  # noqa: E402
from src.pages import home                                  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過 " if cond else "失敗 "), name, ("— " + str(detail)[:100]) if detail else "")
    ok = ok and bool(cond)


DAY, OFF = 86400, -14400
T0 = 1791000000 - 1791000000 % DAY


def res(cur, closes, rmt_day, **meta):
    n = len(closes)
    return {"meta": {"regularMarketPrice": cur, "gmtoffset": OFF,
                     "regularMarketTime": T0 + rmt_day * DAY + 15 * 3600,
                     "chartPreviousClose": 1.0, **meta},
            "timestamp": [T0 + (i - n + 1) * DAY + 48600 for i in range(n)],
            "indicators": {"quote": [{"close": closes}]}}


check("① 盤中：昨收＝倒數第二根（不是 chartPreviousClose）",
      ft._yahoo_prev_close(res(4.30, [4.1, 4.2, 4.25, 4.30], 0)) == 4.25)
check("①b 今天尚無日線：昨收＝最後一根",
      ft._yahoo_prev_close(res(4.31, [4.1, 4.2, 4.25], 1)) == 4.25)
check("①c 期貨夜盤（日期對不上但收盤＝現價）",
      ft._yahoo_prev_close(res(4.25, [4.1, 4.2, 4.25], 1)) == 4.2)
check("①d 沒有日線 → previousClose → chartPreviousClose",
      ft._yahoo_prev_close({"meta": {"previousClose": 4.9, "chartPreviousClose": 1}}) == 4.9
      and ft._yahoo_prev_close({"meta": {"chartPreviousClose": 4.8}}) == 4.8)


class _R:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return {"chart": {"result": [self.body]}}


c = ft.fetch_yahoo_yield("^TNX", "10 年期",
                         _get=lambda u: _R(res(42.8, [42.0, 42.6, 42.8], 0)))
check("② fetch_yahoo_yield 用日線昨收（+2 bp，不是對 chartPreviousClose）",
      c and c["value"] == 4.28 and c["delta_bp"] == 2, c)
q = ft.fetch_yahoo_quote("CL=F", 10, 300,
                         _get=lambda u: _R(res(91.3, [88.0, 90.1, 91.3], 0)))
check("②b fetch_yahoo_quote 同規則", q and q["prev"] == 90.1, q)

# ③ chip 帶完整資料日（給前端比新舊）
_c = ft._mk("wti", "WTI", "1", "+0", "", "2026-10-02")
check("③ _mk 的 iso＝完整日期、date＝月-日", _c["iso"] == "2026-10-02" and _c["date"] == "10-02")
_t = ft._txf_chip({"value": 23250, "prev": 23100, "date": "2026-10-03", "session": "夜盤"})
check("③b 台指期 iso 取盤別日期", _t["iso"] == "2026-10-03" and _t["date"] == "夜盤 10-03")

# ④ 首頁：chip 有 data-d、輪詢腳本在、只問同站 /api/quotes
cat = [ft._mk("dgs10", "10 年期", "4.21%", "+1 bp", "up", "2026-10-02", on=True)]
html = home._focus_strip({"chips": cat, "text": "", "fedwatch": None})
check("④ chip 帶 data-d", 'data-chip="dgs10" data-d="2026-10-02"' in html)
check("④b 輪詢腳本：/api/quotes、60 秒、只在可見時、上限 240 次",
      'fetch("/api/quotes")' in html and "setInterval(tk,60000)" in html
      and "visibilityState" in html and "M=240" in html)
check("④c 不打外部網址", "yahoo" not in home._LIVE_JS.lower() and "taifex" not in home._LIVE_JS.lower())

# ⑤ Netlify 函式（有 node 才跑）
node = shutil.which("node")
if node:
    r = subprocess.run([node, str(ROOT / "tests" / "js" / "test_quotes.mjs")],
                       capture_output=True, text=True, timeout=60)
    check("⑤ netlify/functions/quotes.mjs 離線測試", r.returncode == 0,
          (r.stdout + r.stderr)[-300:])
else:
    print("略過 ⑤：這台機器沒有 node")

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
