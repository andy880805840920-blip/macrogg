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

# ⑦ FedWatch 期貨自算：**雙合約法**（遠月 − 當月價差；FedWatch／WIRP 同款）
_RATES = {"DFEDTARL": [{"date": "2026-08-20", "value": 3.50}],
          "DFEDTARU": [{"date": "2026-08-20", "value": 3.75}]}
_FWCFG = {"fedwatch_contract": "ZQF27.CBT",
          "fedwatch_anchor_contract": "ZQQ26.CBT"}


class _FakeYq:
    """五日收盤有正常波動（倒數第二天差半個 tick）的合約報價。"""

    def __init__(self, px, closes=None):
        self._px = px
        self._closes = closes if closes is not None else [px - 0.005, px]

    def raise_for_status(self):
        pass

    def json(self):
        return {"chart": {"result": [{
            "meta": {"regularMarketPrice": self._px},
            "indicators": {"quote": [{"close": self._closes}]}}]}}


def _yq2(anchor_px, far_px, far_closes=None):
    """兩張合約各給一個價：URL 含 ZQQ26 給當月價、其餘給遠月價。"""
    return lambda u: (_FakeYq(anchor_px) if "ZQQ26" in u
                      else _FakeYq(far_px, far_closes))


# 當月 96.375 → 隱含 3.625%（＝中點，閘門通過）；遠月 96.31 → 3.69%；
# 價差 0.065 ÷ 0.25 = 26%
r = ft.fedwatch_from_futures(_RATES, _FWCFG, _get=_yq2(96.375, 96.31))
check("⑦ 雙合約：價差 0.065 → 26%（附遠月隱含）",
      r is not None and abs(r[0] - 26.0) < 0.5 and abs(r[1] - 3.69) < 0.001, r)
# 遠月低於當月（市場偏降息）→ 機率鎖在 0，不會出現負數
r = ft.fedwatch_from_futures(_RATES, _FWCFG, _get=_yq2(96.375, 96.60))
check("⑦b 偏降息時鎖 0", r is not None and r[0] == 0.0, r)
# 報價離譜（抓錯商品）→ 不採用
check("⑦c 報價超出 90–100 不採用",
      ft.fedwatch_from_futures(_RATES, _FWCFG, _get=_yq2(96.375, 85.0)) is None)
# 價差 >1.5pp（合約年份寫錯）→ 不採用
check("⑦d 價差過大不採用",
      ft.fedwatch_from_futures(_RATES, _FWCFG, _get=_yq2(96.375, 94.0)) is None)
# 抓不到目標區間 → 閘門沒有比對基準，不硬算
check("⑦e 缺目標區間回 None",
      ft.fedwatch_from_futures({}, _FWCFG, _get=_yq2(96.375, 96.31)) is None)
# 100% 事故第一型的回歸：遠月超過當月＋0.40（陳舊報價）→ 不採用退備援
check("⑦f 遠月隱含 4.10%（當月＋0.475）視為陳舊報價",
      ft.fedwatch_from_futures(_RATES, _FWCFG, _get=_yq2(96.375, 95.90)) is None)
# 100% 事故第二型的回歸：遠月「錯得不夠離譜」（隱含 4.00%，落在舊門檻
# 之內）——當月合約的品質閘門要能整批擋下
check("⑦h 當月隱含偏離中點 >0.15 → 報價鏈判壞、整批不採用",
      ft.fedwatch_from_futures(_RATES, _FWCFG, _get=_yq2(96.00, 96.00)) is None)
check("⑦i 當月抓不到 → 無法驗證，不硬算",
      ft.fedwatch_from_futures(_RATES, _FWCFG, _get=_yq2(85.0, 96.31)) is None)
# 當月合約代號按月份自動推
check("⑦j 當月合約代號自動滾",
      ft._anchor_symbol(dt.date(2026, 8, 21)) == "ZQQ26.CBT"
      and ft._anchor_symbol(dt.date(2026, 12, 3)) == "ZQZ26.CBT"
      and ft._anchor_symbol(dt.date(2027, 1, 5)) == "ZQF27.CBT")

# ⑦q 停滯偵測（+0.0 pp 事故的回歸）：遠月收盤連續五天一模一樣＝報價
# 鏈死掉，整批不採用；只有一筆收盤、或只剩最新成交價也一樣
check("⑦q 遠月收盤五天不動 → 判報價死掉不採用",
      ft.fedwatch_from_futures(
          _RATES, _FWCFG,
          _get=_yq2(96.375, 96.00, far_closes=[96.00] * 5)) is None)
check("⑦r 遠月只有一筆收盤 → 不採用",
      ft.fedwatch_from_futures(
          _RATES, _FWCFG,
          _get=_yq2(96.375, 96.31, far_closes=[None, None, 96.31])) is None)
check("⑦s 遠月無收盤只剩最新成交價 → 不採用（陳舊成交）",
      ft.fedwatch_from_futures(
          _RATES, _FWCFG, _get=_yq2(96.375, 96.31, far_closes=[])) is None)
# 當月被實際利率釘住、平盤正常——停滯偵測不適用於它
check("⑦t 當月平盤不影響（檢查只針對遠月）",
      ft.fedwatch_from_futures(
          _RATES, _FWCFG,
          _get=lambda u: (_FakeYq(96.375, closes=[96.375] * 5)
                          if "ZQQ26" in u else _FakeYq(96.31)))[0] == 26.0)

# ⑦u 交叉檢核：期貨與官方差逾 25pp → 期貨端判壞、改用官方值
check("⑦u 差逾 25pp 改用官方值",
      ft._pick_fw((100.0, 4.00, 37.5), 20.0) == (20.0, "atlanta", None, None))
check("⑦v 差距在範圍內 → 用期貨（附隱含與價差）",
      ft._pick_fw((26.0, 3.69, 6.5), 30.0) == (26.0, "futures", 3.69, 6.5))
check("⑦w 期貨掛了 → 官方值",
      ft._pick_fw(None, 31.0) == (31.0, "atlanta", None, None))
check("⑦x 兩邊都沒有 → 退 AI 層",
      ft._pick_fw(None, None) == (None, "", None, None))

# ⑦y 定價達一碼以上：機率鎖 100，但價差照實帶回（首頁改講事實用）
_ry = ft.fedwatch_from_futures(_RATES, _FWCFG, _get=_yq2(96.375, 96.115))
check("⑦y 價差 26bp → 機率 100＋spread_bp 26",
      _ry is not None and _ry[0] == 100.0 and abs(_ry[2] - 26.0) < 0.1, _ry)

# ⑦k Atlanta Fed 第二層：沒設取值路徑時只偵察不猜數字；設了才啟用
class _FakeAt:
    def __init__(self, payload):
        self._p = payload
        self.headers = {"Content-Type": "application/json"}
        self.text = str(payload)

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


_AT = {"probabilities": {"hike25": 0.26, "cut25": 0.31}}
check("⑦k 沒設路徑 → 偵察後回 None（不猜數字）",
      ft.fetch_atlanta_fedwatch({}, _get=lambda u: _FakeAt(_AT)) is None)
check("⑦l 設了路徑 → 取值並把 0–1 換算成百分比",
      ft.fetch_atlanta_fedwatch(
          {"atlanta_json_path": ["probabilities", "hike25"]},
          _get=lambda u: _FakeAt(_AT)) == 26.0)
check("⑦m 超出 0–100 不採用",
      ft.fetch_atlanta_fedwatch(
          {"atlanta_json_path": ["probabilities", "hike25"]},
          _get=lambda u: _FakeAt({"probabilities": {"hike25": 260}})) is None)


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

# ⑦n 跳動防護欄只防 AI 擷取：期貨自算的大變動是資訊（或正確值在取代
# 事故留下的壞前值），擋下的話 100% 會永遠取代不掉
check("⑦n 期貨自算 22% vs 前值 100% → 接受新值",
      not ft._jump_suspect(22.0, 100.0, "futures"))
check("⑦o AI 擷取 22% vs 前值 100% → 視為擷取錯誤",
      ft._jump_suspect(22.0, 100.0, "ai"))
check("⑦p 沒有前值就沒有跳動可言",
      not ft._jump_suspect(22.0, None, "ai"))

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

# ⑨c 假朋友：「毛利率」含「利率」但講的是公司財報，不能放進來
#（實際發生過：「聯電Q3毛利率上看36%」被關鍵字「利率」選進市場焦點）
_FF_XML = """<rss><channel>
<item><title>聯電Q3毛利率上看36%！法人上修今明年獲利</title>
  <link>http://u</link><pubDate>{new}</pubDate></item>
<item><title>Fed 官員談利率路徑，市場關注</title>
  <link>http://v</link><pubDate>{new}</pubDate></item>
</channel></rss>""".format(new=_new)
ff = ft.fetch_feed_headlines(["https://tw.news.yahoo.com/rss/finance"],
                             ["Fed 利率"], _get=lambda u: _Fake(_FF_XML))
check("⑨c 「毛利率」不算命中「利率」", len(ff) == 1 and "毛利率" not in ff[0]["title"],
      [x["title"][:14] for x in ff])
check("⑨d 「殖利率」不受假朋友過濾影響（本來就要抓）",
      ft._kw_text("美債殖利率走高") == "美債殖利率走高"
      and "利率" not in ft._kw_text("聯電毛利率上看36%"))
check("⑨e 排序的命中數同一套規則",
      ft.pick_fallback([{"title": "聯電Q3毛利率上看36%", "link": "", "source": "",
                         "at": now.isoformat()},
                        {"title": "Fed 官員談利率路徑", "link": "", "source": "",
                         "at": (now - dt.timedelta(hours=1)).isoformat()}],
                       ["Fed 利率"], n=1)[0]["title"].startswith("Fed"))

# ⑨f 排除關鍵字：真的含關鍵字、但不是總經新聞的標題要整條剔除
#（實際發生過：「專家談美債布局：不如押0050或高股息」——含「美債」，
#  但那是台股 ETF 理財文）
_EXC = ["0050", "高股息", "ETF", "台股"]
_EX_XML = """<rss><channel>
<item><title>美股震盪期創高後恐崩盤？專家談美債布局：長天期沒賺，不如押0050或高股息</title>
  <link>http://w</link><pubDate>{new}</pubDate></item>
<item><title>美債殖利率走高，市場關注財政部標售</title>
  <link>http://x</link><pubDate>{new}</pubDate></item>
</channel></rss>""".format(new=_new)
fe = ft.fetch_feed_headlines(["https://tw.news.yahoo.com/rss/finance"],
                             ["美債 殖利率"], _get=lambda u: _Fake(_EX_XML),
                             exclude=_EXC)
check("⑨f feed 層剔除排除詞", len(fe) == 1 and "0050" not in fe[0]["title"],
      [x["title"][:16] for x in fe])
check("⑨g 挑選層也剔除（標題模式不經過 feed 過濾）",
      all("0050" not in x["title"] for x in ft.pick_fallback(
          [{"title": "專家談美債布局：不如押0050或高股息", "link": "",
            "source": "", "at": now.isoformat()},
           {"title": "美債殖利率走高，市場關注財政部標售", "link": "",
            "source": "", "at": (now - dt.timedelta(hours=1)).isoformat()}],
          ["美債 殖利率"], n=2, exclude=_EXC)))
check("⑨h 沒設排除清單時行為不變",
      not ft._excluded("專家談美債布局", None)
      and ft._excluded("不如押0050或高股息", _EXC))

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

# ⑫ 跨供應商備援：Gemini 整條鏈死掉（例：整把金鑰的模型全數 429）時，
# 設了 ANTHROPIC_API_KEY 就換 Anthropic 接手，數字鎖照樣把關
_orig_pg, _orig_pa = ft._post_gemini_hardy, _pl._post_anthropic


def _pg_boom(*a, **k):
    raise RuntimeError("全模型 429")


ft._post_gemini_hardy = _pg_boom
_pl._post_anthropic = (lambda key, model, text, system=None, temperature=None:
                       "財政部調整發債結構，市場關注十年期殖利率。")
t, s = ft.summarize_content([{"title": "x", "body": body, "source": "y"}],
                            ["美國財政部"], 120,
                            {"GEMINI_API_KEY": "F", "ANTHROPIC_API_KEY": "A"})
check("⑫ Gemini 全滅 → Anthropic 備援接手", t != "" and s == "model-content", s)
t, s = ft.summarize_content([{"title": "x", "body": body, "source": "y"}],
                            ["美國財政部"], 120, {"GEMINI_API_KEY": "F"})
check("⑫b 沒有備援金鑰就照舊失敗", t == "" and "Gemini" in s, s)
_pl._post_anthropic = (lambda key, model, text, system=None, temperature=None:
                       "市場預期年底利率降至 2.75%。")
t, s = ft.summarize_content([{"title": "x", "body": body, "source": "y"}],
                            ["美國財政部"], 120,
                            {"GEMINI_API_KEY": "F", "ANTHROPIC_API_KEY": "A"})
check("⑫c 備援的輸出一樣要過數字鎖", t == "" and "沒有的數字" in s, s)
# 只有 Anthropic 金鑰（沒有 Gemini）也能跑
_pl._post_anthropic = (lambda key, model, text, system=None, temperature=None:
                       "財政部調整發債結構，市場關注十年期殖利率。")
t, s = ft.summarize_content([{"title": "x", "body": body, "source": "y"}],
                            ["美國財政部"], 120, {"ANTHROPIC_API_KEY": "A"})
check("⑫d 只有 Anthropic 金鑰也能產出", t != "" and s == "model-content", s)
ft._post_gemini_hardy, _pl._post_anthropic = _orig_pg, _orig_pa

# ⑬ 焦點專用呼叫鏈 _post_gemini_hardy：429／5xx／timeout 都換模型再試。
# 潤稿的 polish._post_gemini 已還原成「這些錯直接退組裝版」（見
# test_polish 145／147）——拚到底的政策只住在焦點這條鏈裡。
_LIST = ["gemini-2.5-flash", "gemini-flash-latest", "gemini-flash-lite-latest"]
_orig_gm, _orig_gc2 = _pl._gemini_models, _pl._gemini_call
_pl._gemini_models = lambda key: _LIST


def _he(code):
    e = _pl.requests.HTTPError(str(code))

    class _R:
        status_code = code
        headers = {}
    e.response = _R()
    return e


def _mk_chain(fails):
    seq = []

    def call(key, model, text, system=None, think=True, temperature=None):
        seq.append(model)
        if model in fails:
            raise fails[model]
        return "好文"
    return call, seq


for _name, _exc in [("⑬ 429 換一顆模型接著跑（配額逐模型計）", _he(429)),
                    ("⑬b 503 換一顆模型", _he(503)),
                    ("⑬c timeout 換一顆模型",
                     _pl.requests.ConnectionError("Read timed out"))]:
    _pl._DEAD.clear()
    _call, _seq = _mk_chain({"gemini-flash-latest": _exc})
    _pl._gemini_call = _call
    _out = ft._post_gemini_hardy("k", "gemini-flash-latest", "文", "sys")
    check(_name, _out == "好文" and len(_seq) == 2, str(_seq))

# 400（參數錯）不換——換誰都一樣，直接往上拋
_pl._DEAD.clear()
_call, _seq = _mk_chain({"gemini-flash-latest": _he(400)})
_pl._gemini_call = _call
try:
    ft._post_gemini_hardy("k", "gemini-flash-latest", "文", "sys")
    _hit = False
except _pl.requests.HTTPError:
    _hit = True
check("⑬d 400 直接往上拋、只呼叫一次", _hit and len(_seq) == 1, str(_seq))

# 404 換模型並記黑名單（叫不動是事實，記下來省之後的額度）
_pl._DEAD.clear()
_call, _seq = _mk_chain({"gemini-flash-latest": _he(404)})
_pl._gemini_call = _call
_out = ft._post_gemini_hardy("k", "gemini-flash-latest", "文", "sys")
check("⑬e 404 換模型且記黑名單",
      _out == "好文" and "gemini-flash-latest" in _pl._DEAD, str(_seq))
_pl._DEAD.clear()
_pl._gemini_models, _pl._gemini_call = _orig_gm, _orig_gc2

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
