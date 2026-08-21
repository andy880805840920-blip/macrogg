# 今日市場焦點：確定性部分的回歸測試（不打任何網路）
import sys
import pathlib
import datetime as dt

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.analysis import focus_today as ft                # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過 " if cond else "失敗 "), name, ("— " + str(detail)[:90]) if detail else "")
    ok = ok and bool(cond)


# ① 殖利率 chip：最新值＋較前一交易日的變動（基點）
rows = [{"date": "2026-08-19", "value": 4.67},
        {"date": "2026-08-20", "value": 4.69}]
c = ft._yield_chip(rows, "10 年期")
check("① 殖利率變動以基點計", c["delta_bp"] == 2 and c["value"] == 4.69, c)
check("①b 少於兩筆不硬算", ft._yield_chip(rows[:1], "x") is None)

# ② 數字防護欄：輸出的數字必須出現在標題裡
src = "- [路透] 川普再批聯準會，10 年期殖利率升至 4.7%"
check("② 標題裡有的數字放行", ft._digits_ok("殖利率升至 4.7%", src))
check("②b 編出來的數字擋下", not ft._digits_ok("市場預期年底降至 3.5%", src))

# ③ 確定性退回挑選：關鍵字命中多者優先、同分保持新的在前
now = dt.datetime.now(dt.timezone.utc)
hs = [
    {"title": "美股收漲", "link": "", "source": "", "at": (now).isoformat()},
    {"title": "川普點名 Kevin Warsh 接任聯準會主席", "link": "", "source": "",
     "at": (now - dt.timedelta(hours=2)).isoformat()},
    {"title": "貝森特談美國財政部發債計畫", "link": "", "source": "",
     "at": (now - dt.timedelta(hours=1)).isoformat()},
]
kw = ["川普 聯準會", "Kevin Warsh", "貝森特", "美國財政部"]
picked = ft.pick_fallback(hs, kw, n=2)
check("③ 命中關鍵字的標題排前面", picked[0]["title"].startswith("川普點名"),
      [p["title"][:12] for p in picked])
check("③b 不相關的標題被擠掉", all("美股" not in p["title"] for p in picked))

# ④ RSS 解析：假的回應也要能走完（含去重與時間過濾）
_XML = """<rss><channel>
<item><title>川普再批聯準會 - 路透</title><link>http://a</link>
  <pubDate>{new}</pubDate><source>路透</source></item>
<item><title>川普再批聯準會 - 中央社</title><link>http://b</link>
  <pubDate>{new}</pubDate><source>中央社</source></item>
<item><title>三個月前的舊聞</title><link>http://c</link>
  <pubDate>{old}</pubDate><source>x</source></item>
</channel></rss>"""


class _Fake:
    def __init__(self, content):
        self.content = content.encode("utf-8")

    def raise_for_status(self):
        pass


_new = now.strftime("%a, %d %b %Y %H:%M:%S GMT")
_old = (now - dt.timedelta(days=90)).strftime("%a, %d %b %Y %H:%M:%S GMT")
out = ft.fetch_headlines(["川普"], _get=lambda u: _Fake(
    _XML.format(new=_new, old=_old)))
check("④ 同一則新聞不同來源只留一則", len(out) == 1,
      [o["title"] for o in out])
check("④b 超過時間窗的舊聞被濾掉", all("舊聞" not in o["title"] for o in out))

# ⑤ 近似重複的標題只選一則：同一件事在不同媒體改幾個字，完全比對擋不住
hs2 = [
    {"title": "川普再度砲轟聯準會主席，暗示將撤換 - 路透", "link": "", "source": "",
     "at": now.isoformat()},
    {"title": "川普再度砲轟聯準會主席 暗示撤換 - Yahoo奇摩財經", "link": "",
     "source": "", "at": (now - dt.timedelta(minutes=5)).isoformat()},
    {"title": "貝森特談美國財政部發債計畫 - 中央社", "link": "", "source": "",
     "at": (now - dt.timedelta(hours=1)).isoformat()},
]
p2 = ft.pick_fallback(hs2, ["川普 聯準會", "貝森特"], n=2)
check("⑤ 近似重複標題只留一則", len(p2) == 2
      and sum(1 for x in p2 if "川普" in x["title"]) == 1,
      [x["title"][:14] for x in p2])

# ⑥ 來源白名單：只留 yahoo 系；全部沒命中時退回不過濾（在 build 層）
hs3 = [
    {"title": "A", "source": "Yahoo奇摩財經"},
    {"title": "B", "source": "Yahoo Finance"},
    {"title": "C", "source": "路透"},
]
_srcs = ["yahoo"]
hits = [h for h in hs3 if any(w in h["source"].lower() for w in _srcs)]
check("⑥ 白名單命中 Yahoo 系來源", [h["title"] for h in hits] == ["A", "B"])
check("⑥b 沒命中時退回全部（邏輯）",
      ([h for h in [{"title": "C", "source": "路透"}]
        if any(w in h["source"].lower() for w in _srcs)] or hs3) == hs3)

# ⑦ FedWatch 期貨自算：FedWatch／WIRP 同款公式
_RATES = {"DFEDTARL": [{"date": "2026-08-20", "value": 3.50}],
          "DFEDTARU": [{"date": "2026-08-20", "value": 3.75}]}


class _FakeYq:
    def __init__(self, px):
        self._px = px

    def raise_for_status(self):
        pass

    def json(self):
        return {"chart": {"result": [{"meta": {"regularMarketPrice": self._px}}]}}


# 期貨價 96.31 → 隱含 3.69%；中點 3.625 → (3.69−3.625)/0.25 = 26%
r = ft.fedwatch_from_futures(_RATES, {}, _get=lambda u: _FakeYq(96.31))
check("⑦ 期貨自算：96.31 → 26%（附隱含利率）",
      r is not None and abs(r[0] - 26.0) < 0.5 and abs(r[1] - 3.69) < 0.001, r)
# 隱含低於中點（市場偏降息）→ 機率鎖在 0，不會出現負數
r = ft.fedwatch_from_futures(_RATES, {}, _get=lambda u: _FakeYq(96.60))
check("⑦b 偏降息時鎖 0", r is not None and r[0] == 0.0, r)
# 報價離譜（抓錯商品）→ 不採用
check("⑦c 報價超出 90–100 不採用",
      ft.fedwatch_from_futures(_RATES, {}, _get=lambda u: _FakeYq(85.0)) is None)
# 隱含利率偏離中點 >1.5pp（合約年份寫錯）→ 不採用
check("⑦d 偏離中點過大不採用",
      ft.fedwatch_from_futures(_RATES, {}, _get=lambda u: _FakeYq(94.0)) is None)
# 抓不到目標區間 → 不硬算
check("⑦e 缺目標區間回 None",
      ft.fedwatch_from_futures({}, {}, _get=lambda u: _FakeYq(96.31)) is None)
# 100% 事故的回歸：隱含超過中點＋0.40（疑為遠月陳舊報價）→ 不採用退備援
check("⑦f 隱含 4.10%（中點＋0.475）視為陳舊報價",
      ft.fedwatch_from_futures(_RATES, {}, _get=lambda u: _FakeYq(95.90)) is None)


# ⑦g 價格優先取日收盤（結算價），不是可能陳舊的「最新成交價」
class _FakeYq2:
    def raise_for_status(self):
        pass

    def json(self):
        return {"chart": {"result": [{
            "meta": {"regularMarketPrice": 95.90},          # 陳舊成交
            "indicators": {"quote": [{"close": [96.30, None, 96.31]}]}}]}}


check("⑦g 優先用日收盤而非陳舊成交價",
      ft.fetch_zq_implied("ZQF27.CBT", _get=lambda u: _FakeYq2()) == 3.69)

# ⑧ Yahoo 即時殖利率：×10 慣例規範化、±bp 對昨收、異常值不採用
class _FakeYt:
    def __init__(self, cur, prev, ts=1787300000):
        self._m = {"regularMarketPrice": cur, "chartPreviousClose": prev,
                   "regularMarketTime": ts}

    def raise_for_status(self):
        pass

    def json(self):
        return {"chart": {"result": [{"meta": self._m}]}}


# CBOE ×10 慣例：42.83／42.61 → 4.28%、+2 bp
c = ft.fetch_yahoo_yield("^TNX", "10 年期", _get=lambda u: _FakeYt(42.83, 42.61))
check("⑧ ×10 慣例規範化＋對昨收", c is not None and c["value"] == 4.28
      and c["delta_bp"] == 2 and c["live"], c)
# 直接百分比格式也吃得下
c = ft.fetch_yahoo_yield("^TNX", "10 年期", _get=lambda u: _FakeYt(4.28, 4.26))
check("⑧b 百分比格式", c is not None and c["value"] == 4.28 and c["delta_bp"] == 2)
# 異常值（負利率、爆表）不採用 → 呼叫端退回 FRED
check("⑧c 異常值不採用",
      ft.fetch_yahoo_yield("^TNX", "x", _get=lambda u: _FakeYt(0.02, 0.02)) is None)

# ⑨ Yahoo feed：只留標題命中關鍵字的項目、來源標籤由 feed 推得
_FEED_XML = """<rss><channel>
<item><title>川普再批聯準會，殖利率走高</title><link>http://a</link>
  <pubDate>{new}</pubDate></item>
<item><title>台股收盤上漲三百點</title><link>http://b</link>
  <pubDate>{new}</pubDate></item>
</channel></rss>""".format(new=_new)
fh = ft.fetch_feed_headlines(["https://tw.news.yahoo.com/rss/finance"],
                             ["川普 聯準會"],
                             _get=lambda u: _Fake(_FEED_XML))
check("⑨ feed 只留關鍵字命中", len(fh) == 1 and "川普" in fh[0]["title"], fh)
check("⑨b 來源標籤由 feed 推得", fh and fh[0]["source"] == "Yahoo奇摩新聞")

# ⑩ 內文擷取：砍 script、抽 <p>、太短回空
_PAGE = ("<html><script>var x='這段程式碼不是內文'+'不該被抽出來的長字串"
         + "Ｘ" * 200 + "';</script><body>"
         + "<p>導覽列</p>"
         + "<p>" + "美國財政部宣布調整發債結構，市場關注十年期殖利率走勢。" * 6 + "</p>"
         + "<p>" + "聯準會官員表示通膨仍高於目標，九月會議前進入噤聲期。" * 5 + "</p>"
         + "</body></html>")


class _FakePage:
    def __init__(self, t):
        self.text = t

    def raise_for_status(self):
        pass


body = ft.fetch_article_text("http://a", _get=lambda u: _FakePage(_PAGE))
check("⑩ 內文抽出且不含程式碼", "發債結構" in body and "程式碼" not in body
      and "導覽列" not in body, body[:40])
check("⑩b 太短的頁面回空",
      ft.fetch_article_text("http://a",
                            _get=lambda u: _FakePage("<p>只有一句話而已</p>")) == "")

# ⑪ 內文摘要的數字鎖：輸出的數字必須出現在內文裡
from src.analysis import polish as _pl
_orig_gc = _pl._gemini_call
_pl._gemini_call = lambda *a, **k: "財政部調整發債結構，市場關注十年期殖利率。"
t, s = ft.summarize_content([{"title": "x", "body": body, "source": "y"}],
                            ["美國財政部"], 120, {"GEMINI_API_KEY": "F"})
check("⑪ 內文摘要通過", t != "" and s == "model-content", s)
_pl._gemini_call = lambda *a, **k: "市場預期年底利率降至 2.75%。"
t, s = ft.summarize_content([{"title": "x", "body": body, "source": "y"}],
                            ["美國財政部"], 120, {"GEMINI_API_KEY": "F"})
check("⑪b 編造數字被擋", t == "" and "沒有的數字" in s, s)
_pl._gemini_call = _orig_gc

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
