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

# ⑦ FedWatch：WIRP 同款**逐會議**算法（使用者提供的規格＋驗收 unit test）
_FOMC26 = ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
           "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09"]

# —— 驗收 unit test：Nov 96.215＋Dec 96.140 → Dec +25bp ≈ 42.27% ——
_c = ft.calculate_meeting_probability(
    {"2026-11": 96.215, "2026-12": 96.140}, _FOMC26, "2026-12-09")
check("⑦ 驗收：Dec +25bp 機率 ≈ 42.27%",
      _c is not None and abs(_c["pct"] - 42.27) < 0.01, _c and _c["pct"])
check("⑦a2 中間值：Dec_Start=Nov_Avg=3.785、Dec_End=3.8906818",
      abs(_c["months"]["2026-12"]["start"] - 3.785) < 1e-6
      and abs(_c["months"]["2026-12"]["end"] - 3.8906818) < 1e-4,
      _c["months"]["2026-12"])
check("⑦a3 中間值：move=10.568bp、N=9 M=22 D=31",
      abs(_c["move_bp"] - 10.56818) < 0.001
      and _c["months"]["2026-12"]["N"] == 9
      and _c["months"]["2026-12"]["M"] == 22
      and _c["months"]["2026-12"]["D"] == 31)
check("⑦a4 outcome 拆解：0bp 57.7%／+25bp 42.3%",
      abs(_c["outcomes"][0] - 0.5773) < 0.001
      and abs(_c["outcomes"][25] - 0.4227) < 0.001, _c["outcomes"])

# 超過一碼：move=31bp → +25bp 76%／+50bp 24%，顯示 % 不封頂（124%）
_c2 = ft.calculate_meeting_probability(
    {"2026-11": 96.215, "2026-12": 95.995}, _FOMC26, "2026-12-09")
check("⑦b 31bp → P(+25)=76%、P(+50)=24%、顯示 124%（不 clamp）",
      _c2 is not None and abs(_c2["move_bp"] - 31.0) < 0.05
      and abs(_c2["outcomes"][25] - 0.76) < 0.01
      and abs(_c2["outcomes"][50] - 0.24) < 0.01
      and abs(_c2["pct"] - 124.0) < 0.2, _c2 and _c2["outcomes"])

# 降息：move=−18bp → P(−25)=72%、P(0)=28%、顯示 −72%
_c3 = ft.calculate_meeting_probability(
    {"2026-11": 96.215, "2026-12": 96.342742}, _FOMC26, "2026-12-09")
check("⑦c −18bp → P(−25)=72%、P(0)=28%、pct=−72",
      _c3 is not None and abs(_c3["move_bp"] + 18.0) < 0.01
      and abs(_c3["outcomes"][-25] - 0.72) < 0.005
      and abs(_c3["outcomes"][0] - 0.28) < 0.005
      and abs(_c3["pct"] + 72.0) < 0.1, _c3 and _c3["outcomes"])

# 跨月反推鏈：假設 11/05 也有會議（10 月沒有）→ 錨月退到 10 月，
# Nov End 由日曆日加權反推、接成 Dec Start
_c4 = ft.calculate_meeting_probability(
    {"2026-10": 96.215, "2026-11": 96.20, "2026-12": 96.14},
    ["2026-11-05", "2026-12-09"], "2026-12-09")
check("⑦d 連續會議月往回找錨月並逐月反推",
      _c4 is not None and _c4["anchor"] == "2026-10"
      and abs(_c4["months"]["2026-11"]["end"] - 3.803) < 0.001
      and abs(_c4["pct"] - 32.13) < 0.05, _c4 and _c4["pct"])

# 缺月份報價 → 誠實回 None
check("⑦e 缺月份不硬算",
      ft.calculate_meeting_probability({"2026-12": 96.14}, _FOMC26,
                                       "2026-12-09") is None)

# —— 抓取層 fedwatch_from_futures：合約自動推＋健康檢查＋停滯偵測 ——
_RATES = {"DFEDTARL": [{"date": "2026-08-20", "value": 3.50}],
          "DFEDTARU": [{"date": "2026-08-20", "value": 3.75}]}
_FWCFG = {"fedwatch_meeting": "2026-12-09", "fomc_dates": _FOMC26,
          "fedwatch_health_contract": "ZQQ26.CBT"}


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


def _yq3(health=96.375, nov=96.215, dec=96.140, nov_closes=None):
    """三張合約各給價：ZQQ26 健康檢查、ZQX26＝11 月、ZQZ26＝12 月。"""
    def get(u):
        if "ZQQ26" in u:
            return _FakeYq(health)
        if "ZQX26" in u:
            return _FakeYq(nov, nov_closes)
        return _FakeYq(dec)
    return get


# 健康 96.375 → 3.625%（＝FRED 中點，通過）；Nov/Dec 用驗收價
r = ft.fedwatch_from_futures(_RATES, _FWCFG, _get=_yq3())
check("⑦f 抓取層整合：自動推 ZQX26/ZQZ26 → 42.27%",
      r is not None and abs(r["pct"] - 42.27) < 0.01
      and abs(r["move_bp"] - 10.568) < 0.01
      and r["meeting"] == "2026-12-09", r and r["pct"])
check("⑦g2 缺目標區間 → 不硬算",
      ft.fedwatch_from_futures({}, _FWCFG, _get=_yq3()) is None)
check("⑦h 健康檢查：當月隱含偏離中點 >0.15 → 報價鏈判壞、整批不採用",
      ft.fedwatch_from_futures(_RATES, _FWCFG, _get=_yq3(health=96.00)) is None)
check("⑦i 健康合約抓不到 → 無法驗證，不硬算",
      ft.fedwatch_from_futures(_RATES, _FWCFG, _get=_yq3(health=85.0)) is None)
check("⑦j 合約代號自動滾（含健康合約按月推）",
      ft._zq_symbol("2026-11") == "ZQX26.CBT"
      and ft._zq_symbol("2026-12") == "ZQZ26.CBT"
      and ft._zq_symbol("2027-01") == "ZQF27.CBT"
      and ft._anchor_symbol(dt.date(2026, 8, 21)) == "ZQQ26.CBT")

# ⑦f2 chip 的 ± 是「收盤對收盤」：同一次執行用前一日收盤再算一次機率
# 相減，不依賴 state 歷史。12 月合約前一日 96.155、當日 96.140（跌了
# 1.5 tick、多定價一點升息）——期望值直接用同一顆算法對兩組價位
# 算出來比（測的是接線，不重複手算）。
def _yq_cc(u):
    if "ZQQ26" in u:
        return _FakeYq(96.375)
    if "ZQX26" in u:
        return _FakeYq(96.215, [96.220, 96.215])
    return _FakeYq(96.140, [96.155, 96.140])


# 11 月無會議＝錨月，抓的合約是 ZQX26（11 月）＋ZQZ26（12 月）
_fd = [str(x) for x in _FWCFG["fomc_dates"]]
_cur = {"2026-11": 96.215, "2026-12": 96.140}
_prv = {"2026-11": 96.220, "2026-12": 96.155}
_want_d = round(
    ft.calculate_meeting_probability(_cur, _fd, "2026-12-09")["pct"]
    - ft.calculate_meeting_probability(_prv, _fd, "2026-12-09")["pct"], 1)
_r2 = ft.fedwatch_from_futures(_RATES, _FWCFG, _get=_yq_cc)
check("⑦f2 delta_pp＝收盤對收盤（同算法兩組價位相減、非零）",
      _r2 is not None and _r2.get("delta_pp") == _want_d and _want_d != 0,
      (_r2 and _r2.get("delta_pp"), _want_d))
check("⑦f3 前一日收盤壞值（出範圍）→ delta 不標、機率照算",
      (lambda r: r is not None and r.get("delta_pp") is None
       and abs(r["pct"] - 42.27) < 0.01)(
          ft.fedwatch_from_futures(
              _RATES, _FWCFG,
              _get=_yq3(nov_closes=[96.220, 85.0, 96.215]))))

# 停滯偵測（+0.0 pp 事故的回歸）：會議相關合約五天收盤一模一樣＝報價
# 死掉，整批不採用；健康合約平盤不受影響（⑦f 的 closes 本來就會動）
check("⑦q 合約收盤五天不動 → 判報價死掉不採用",
      ft.fedwatch_from_futures(
          _RATES, _FWCFG, _get=_yq3(nov_closes=[96.215] * 5)) is None)
check("⑦r 合約只有一筆收盤 → 不採用",
      ft.fedwatch_from_futures(
          _RATES, _FWCFG,
          _get=_yq3(nov_closes=[None, None, 96.215])) is None)
# 月份間價差過大（抓錯合約／年份）→ 不採用
check("⑦s 月份間隱含差 >1.5pp → 不採用",
      ft.fedwatch_from_futures(_RATES, _FWCFG, _get=_yq3(nov=94.0)) is None)
# 單場會議 |move|>100bp → 壞資料
check("⑦t 單場會議定價超過四碼 → 判壞資料",
      ft.fedwatch_from_futures(_RATES, _FWCFG, _get=_yq3(dec=95.0)) is None)

# ⑦u 交叉檢核：期貨與官方差逾 25pp → 期貨端判壞、改用官方值
_FWD = {"pct": 42.27, "move_bp": 10.568, "meeting": "2026-12-09"}
check("⑦u 差逾 25pp 改用官方值",
      ft._pick_fw({"pct": 124.0, "move_bp": 31.0}, 40.0)
      == (40.0, "atlanta", None))
check("⑦v 差距在範圍內 → 用期貨（附明細）",
      ft._pick_fw(_FWD, 45.0) == (42.27, "futures", _FWD))
check("⑦w 期貨掛了 → 官方值", ft._pick_fw(None, 31.0) == (31.0, "atlanta", None))
check("⑦x 兩邊都沒有 → 退 AI 層", ft._pick_fw(None, None) == (None, "", None))
check("⑦y 降息定價（pct 負）與官方比對取絕對值",
      ft._pick_fw({"pct": -30.0, "move_bp": -7.5}, 20.0)[1] == "futures")

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

# ⑧d–⑧h 長端序列升級成即時：all-or-nothing、跳動上限、同日不疊
import datetime as _dt

_TS = int(_dt.datetime(2026, 8, 26, 14, 0,
                       tzinfo=_dt.timezone.utc).timestamp())


def _mk_series():
    return {"DGS10": [{"date": "2026-08-21", "value": 4.68},
                      {"date": "2026-08-24", "value": 4.70}],
            "DGS30": [{"date": "2026-08-21", "value": 5.20},
                      {"date": "2026-08-24", "value": 5.23}]}


def _yget(quotes):
    def get(url):
        for sym, (cur, prev) in quotes.items():
            if sym in url:
                return _FakeYt(cur, prev, ts=_TS)
        raise RuntimeError("no quote")
    return get


_s = _mk_series()
_msg = ft.upgrade_yields_live(_s, _get=_yget(
    {"%5ETNX": (46.6, 47.0), "%5ETYX": (51.9, 52.3)}))
check("⑧d 兩檔都成功 → 各附加一列 live",
      len(_msg) == 2 and _s["DGS10"][-1] == {"date": "2026-08-26",
                                             "value": 4.66, "live": True}
      and _s["DGS30"][-1]["value"] == 5.19, (_msg, _s["DGS10"][-1]))

from src.analysis import rates as _rt
_cv = _rt.curve_state(_s)
check("⑧e 升級後 curve_state 用即時值、30−10 斜率同日一致",
      _cv.levels["10Y"] == 4.66 and _cv.levels["30Y"] == 5.19
      and abs(_cv.slope_30_10 - 0.53) < 1e-9, _cv.levels)

_s = _mk_series()
_msg = ft.upgrade_yields_live(_s, _get=_yget({"%5ETNX": (46.6, 47.0)}))
check("⑧f 只有一檔成功 → 整組放棄（all-or-nothing）",
      _msg == [] and len(_s["DGS10"]) == 2 and len(_s["DGS30"]) == 2)

_s = _mk_series()
_msg = ft.upgrade_yields_live(_s, _get=_yget(
    {"%5ETNX": (54.0, 47.0), "%5ETYX": (51.9, 52.3)}))
check("⑧g 與收盤差逾 0.6 個百分點 → 判定報價鏈出錯、整組放棄",
      _msg == [] and len(_s["DGS10"]) == 2)

_s = _mk_series()
_s["DGS10"][-1]["date"] = _s["DGS30"][-1]["date"] = "2026-08-26"
_msg = ft.upgrade_yields_live(_s, _get=_yget(
    {"%5ETNX": (46.6, 47.0), "%5ETYX": (51.9, 52.3)}))
check("⑧h FRED 收盤已是同日 → 不疊", _msg == [] and len(_s["DGS10"]) == 2)

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

# ⑫ 跨供應商：Anthropic 主力（兩把都設時先走它），Gemini 備援。
# 這批測試把 Gemini 炸掉：主力正常時根本輪不到它，數字鎖照樣把關
_orig_pg, _orig_pa = ft._post_gemini_hardy, _pl._post_anthropic


def _pg_boom(*a, **k):
    raise RuntimeError("全模型 429")


ft._post_gemini_hardy = _pg_boom
_pl._post_anthropic = (lambda key, model, text, system=None, temperature=None:
                       "財政部調整發債結構，市場關注十年期殖利率。")
t, s = ft.summarize_content([{"title": "x", "body": body, "source": "y"}],
                            ["美國財政部"], 120,
                            {"GEMINI_API_KEY": "F", "ANTHROPIC_API_KEY": "A"})
check("⑫ 兩把都設 → Anthropic 主力產出（Gemini 掛著也沒差）",
      t != "" and s == "model-content", s)
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
# 主力掛掉 → Gemini 備援接手
def _pa_boom(*a, **k):
    raise RuntimeError("HTTP 529")
_pl._post_anthropic = _pa_boom
ft._post_gemini_hardy = (lambda key, model, text, system=None:
                         "財政部調整發債結構，市場關注十年期殖利率。")
t, s = ft.summarize_content([{"title": "x", "body": body, "source": "y"}],
                            ["美國財政部"], 120,
                            {"GEMINI_API_KEY": "F", "ANTHROPIC_API_KEY": "A"})
check("⑫e Anthropic 掛掉 → Gemini 備援接手",
      t != "" and s == "model-content", s)
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

# ⑭ 全文重新論述：英文來源、分段渲染、來源標籤
check("⑭ 英文關鍵詞不分大小寫", ft._kw_hit("Fed", "FED signals rate pause")
      and ft._kw_hit("yields", "Treasury Yields climb")
      and not ft._kw_hit("Fed", "confused market 里的中文"))
check("⑭b 中文詞照原樣比對", ft._kw_hit("美債", "美債殖利率走高")
      and not ft._kw_hit("美債", "美國股市上漲"))
check("⑭c FT／WSJ 的來源標籤", ft._feed_label("https://www.ft.com/rss/home")
      == "Financial Times"
      and ft._feed_label("https://feeds.a.dj.com/rss/RSSMarketsMain.xml")
      == "Wall Street Journal")

# 英文標題經 feed 過濾要進得來
_EN_XML = """<rss><channel>
<item><title>Fed officials split on rate path as yields climb</title>
  <link>http://e</link><pubDate>{new}</pubDate></item>
<item><title>Local sports team wins championship</title>
  <link>http://f</link><pubDate>{new}</pubDate></item>
</channel></rss>""".format(new=_new)
fe2 = ft.fetch_feed_headlines(["https://www.ft.com/rss/home"],
                              ["Fed rate", "Treasury yields"],
                              _get=lambda u: _Fake(_EN_XML))
check("⑭d 英文標題命中關鍵字進標題池", len(fe2) == 1
      and fe2[0]["source"] == "Financial Times", fe2)

# 分段輸出被完整保留（首頁逐段包 <p>，見 home._focus_strip）
_orig_gc2 = _pl._gemini_call
_pl._gemini_call = (lambda *a, **k:
                    "財政部調整發債結構，市場關注十年期殖利率。\n\n"
                    "聯準會官員表示通膨仍高於目標，九月會議前進入噤聲期。")
t14, s14 = ft.summarize_content([{"title": "x", "body": body, "source": "y"}],
                                ["美國財政部"], 400, {"GEMINI_API_KEY": "F"})
check("⑭e 分段的論述通過驗證且保留換行",
      s14 == "model-content" and "\n" in t14, repr(t14[:40]))
_pl._gemini_call = _orig_gc2

from src.pages import home as _home
_h = _home._focus_strip({"yields": [], "links": [], "fedwatch": None,
                         "text": "第一段。\n\n第二段。",
                         "text_source": "model-content"})
check("⑭f 首頁逐段渲染（兩個 <p> 一個容器框）",
      _h.count('class="fs-text"') == 2 and _h.count('fs-body') == 1)

# ⑮ 自選 chip 目錄：14 顆、預設組、SRF 零值、利差配對、範圍檢查、渲染
LIQ = {
    "SOFR": [{"date": "2026-08-24", "value": 3.62},
             {"date": "2026-08-25", "value": 3.60}],
    "IORB": [{"date": "2026-08-01", "value": 3.65},
             # 晚於 SOFR 最新日的值不能拿來配（期別倒掛）
             {"date": "2026-08-26", "value": 3.40}],
    "RRPONTSYD": [{"date": "2026-08-24", "value": 0.9},
                  {"date": "2026-08-25", "value": 0.4}],
    "RPONTSYD": [{"date": "2026-08-25", "value": 0.0}],
    "DCOILWTICO": [{"date": "2026-08-18", "value": 90.1},
                   {"date": "2026-08-19", "value": 91.3}],
    "DCOILBRENTEU": [{"date": "2026-08-19", "value": 95.3}],
    "VIXCLS": [{"date": "2026-08-24", "value": 16.9},
               {"date": "2026-08-25", "value": 17.4}],
}
RS = {"DGS3MO": [{"date": "2026-08-24", "value": 3.71},
                 {"date": "2026-08-25", "value": 3.72}],
      "DGS2": [{"date": "2026-08-25", "value": 3.83}],
      "DGS5": [{"date": "2026-08-25", "value": 4.18}],
      "DGS10": [{"date": "2026-08-25", "value": 4.70}],
      "DGS30": [{"date": "2026-08-25", "value": 5.23}]}

cat = ft.build_catalog(RS, LIQ, [], offline=True)
_ids = [c["id"] for c in cat]
check("⑮ 目錄 14 顆、順序固定",
      _ids == ["dgs3mo", "dgs2", "dgs5", "dgs10", "dgs30", "fedwatch",
               "sofr", "sofr_iorb", "onrrp", "srf",
               "wti", "brent", "vix", "move"], _ids)
_by = {c["id"]: c for c in cat}
check("⑮b 預設組＝2Y＋10Y＋30Y＋機率（固定四格湊滿）",
      [c["id"] for c in cat if c.get("on")]
      == ["dgs2", "dgs10", "dgs30", "fedwatch"])
check("⑮c 利差配對不拿晚於 SOFR 日的 IORB（3.60−3.65＝−5 bp）",
      _by["sofr_iorb"]["value"] == "-5 bp", _by["sofr_iorb"])
check("⑮d 利差變動對前一日（−5 −（−3）＝−2 bp）",
      _by["sofr_iorb"]["delta"] == "-2 bp" and _by["sofr_iorb"]["dir"] == "dn")
check("⑮e SRF 零值顯示「未動用」、不上色",
      _by["srf"]["value"] == "0（未動用）" and _by["srf"]["dir"] == "")
check("⑮f ON RRP 換算成億美元（0.4 十億 → 4 億）",
      _by["onrrp"]["value"] == "4 億美元"
      and _by["onrrp"]["delta"] == "-5 億")
check("⑮g 離線退 FRED 後備（WTI 有值、MOVE 標擷取失敗）",
      _by["wti"]["value"] == "91.3 美元"
      and _by["move"]["value"] == "—"
      and _by["move"]["delta"] == "本次擷取失敗")
check("⑮h 小字只有日期（月-日）", _by["sofr"]["date"] == "08-25"
      and _by["dgs2"]["date"] == "08-25")

# SRF 非零 → 轉警示色並標金額
_liq2 = dict(LIQ)
_liq2["RPONTSYD"] = [{"date": "2026-08-24", "value": 0.0},
                     {"date": "2026-08-25", "value": 2.5}]
_c2 = {c["id"]: c for c in ft.build_catalog(RS, _liq2, [], offline=True)}
check("⑮i SRF 非零 → 25 億美元、警示色",
      _c2["srf"]["value"] == "25.0 億美元" and _c2["srf"]["dir"] == "up")

# 泛用報價的範圍檢查（VIX 200 不合理 → None 退後備）
check("⑮j fetch_yahoo_quote 範圍檢查",
      ft.fetch_yahoo_quote("^VIX", 5, 100,
                           _get=lambda u: _FakeYt(200.0, 190.0)) is None
      and ft.fetch_yahoo_quote("^VIX", 5, 100,
                               _get=lambda u: _FakeYt(17.4, 16.9))["value"]
      == 17.4)

# ⑯ 首頁渲染：預設顯示、隱藏 chip 也在 HTML、勾選面板與 JS
_F = {"yields": [], "links": [], "fedwatch": None, "text": "x",
      "text_source": "offline", "generated": "2026-08-26", "chips": cat}
_hs = _home._focus_strip(_F)
import re as _re
_vis = _re.findall(r'<div class="fs-chip" data-chip="([^"]+)"', _hs)
check("⑯ 預設顯示四顆（2Y／10Y／30Y／機率）",
      _vis == ["dgs2", "dgs10", "dgs30", "fedwatch"], _vis)
check("⑯b 其餘 10 顆帶 .fs-off 隱藏但都在 HTML",
      _hs.count("fs-off") >= 10 and _hs.count("data-chip=") == 14)
check("⑯c 勾選面板 14 個選項＋已選數（上限 4）＋裝置說明",
      _hs.count("data-pick=") == 14 and "已選 4／4" in _hs
      and "選擇存在此裝置" in _hs)
check("⑯d 內嵌 JS 帶預設組、上限與 localStorage 鍵",
      'var D=["dgs2", "dgs10", "dgs30", "fedwatch"]' in _hs
      and "var M=4" in _hs and "localStorage" in _hs)
_hs2 = _home._focus_strip({"yields": [
    {"label": "10 年期", "value": 4.66, "delta_bp": -4, "date": "2026-08-26"}],
    "links": [], "fedwatch": None, "text": "", "text_source": "",
    "generated": "2026-08-26", "chips": []})
check("⑯e 目錄空 → 舊版三顆後備（無勾選面板）",
      "fs-pick" not in _hs2 and _hs2.count("fs-chip") >= 2)

# ⑰ 兩層材料與抓取提速的配套
check("⑰ 付費牆／轉址網域判定",
      ft._headline_only("https://news.google.com/rss/articles/x")
      and ft._headline_only("https://www.ft.com/content/abc")
      and not ft._headline_only("https://finance.yahoo.com/news/x"))

_rows_live = [{"date": "2026-08-26", "value": 4.70},
              {"date": "2026-08-27", "value": 4.66, "live": True}]
_c17 = ft._chip_from_live_rows(_rows_live, "10 年期")
check("⑰b 已升級的序列直接做 chip（不重打 Yahoo）",
      _c17 == {"label": "10 年期", "value": 4.66, "delta_bp": -4,
               "date": "2026-08-27", "live": True}, _c17)
check("⑰c 沒有 live 標記 → 回 None（照舊走抓取）",
      ft._chip_from_live_rows([{"date": "d", "value": 4.7}], "x") is None)

# 標題快訊進材料包＋數字鎖涵蓋快訊文字
_orig_ca = ft._call_ai
_seen_src = {}
def _ca17(src, system, env=None):
    _seen_src["src"] = src
    return "路透報導稱聯準會官員關注殖利率走勢，會後再評估。", ""
ft._call_ai = _ca17
_t17, _s17 = ft.summarize_content(
    [{"title": "殖利率上行", "body": "十年期殖利率走高，市場關注。",
      "source": "Yahoo Finance"}],
    ["殖利率"], 250,
    briefs=[{"title": "Fed seen holding rates", "source": "Reuters",
             "summary": "Officials signal patience on policy."}])
check("⑰d 標題快訊進材料包（帶來源與分節標記）",
      _s17 == "model-content" and "標題快訊" in _seen_src["src"]
      and "Reuters" in _seen_src["src"]
      and "Officials signal patience" in _seen_src["src"], _s17)
ft._call_ai = (lambda src, system, env=None:
               ("彭博稱目標利率 5.25%。", ""))
_t17e, _s17e = ft.summarize_content(
    [{"title": "t", "body": "內文沒有那個數字。", "source": "y"}],
    ["利率"], 250,
    briefs=[{"title": "Fed rate at 3.75%", "source": "Bloomberg",
             "summary": ""}])
check("⑰e 數字鎖涵蓋快訊：快訊沒有的數字照樣擋",
      _t17e == "" and "沒有的數字" in _s17e, _s17e)
ft._call_ai = (lambda src, system, env=None:
               ("彭博報導稱聯準會維持利率於 3.75% 不變，市場靜待後續。", ""))
_t17f, _s17f = ft.summarize_content(
    [{"title": "t", "body": "內文一段。", "source": "y"}],
    ["利率"], 250,
    briefs=[{"title": "Fed rate at 3.75%", "source": "Bloomberg",
             "summary": ""}])
check("⑰f 快訊裡有的數字可以用", _s17f == "model-content", _s17f)
ft._call_ai = _orig_ca

# RSS description → summary 欄位（FT/WSJ 的官方摘要）
_FEED17 = b"""<rss><channel>
<item><title>Fed weighs Treasury yields path</title>
<link>https://www.ft.com/content/x1</link>
<pubDate>%s</pubDate>
<description>Officials debate the outlook for U.S. Treasury yields
as inflation stays firm across sectors.</description></item>
</channel></rss>""" % (
    __import__("email.utils", fromlist=["x"]).format_datetime(
        __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc)).encode())


class _FR17:
    content = _FEED17
    def raise_for_status(self):
        pass


_fh17 = ft.fetch_feed_headlines(["https://www.ft.com/rss/home"],
                                ["Treasury yields"], _get=lambda u: _FR17())
check("⑰g RSS 官方摘要進 summary 欄位",
      len(_fh17) == 1 and "Officials debate" in _fh17[0].get("summary", ""),
      _fh17 and _fh17[0].get("summary", "")[:40])

# ⑱ 日期新者勝：稀疏合約的舊成交不得冒充即時（2Y 顯示 7/15 的回歸）
_RS18 = {"DGS3MO": [{"date": "2026-08-25", "value": 3.72}],
         "DGS2": [{"date": "2026-08-24", "value": 3.83},
                  {"date": "2026-08-25", "value": 3.84}],
         "DGS5": [{"date": "2026-08-25", "value": 4.18}],
         "DGS10": [{"date": "2026-08-25", "value": 4.70}],
         "DGS30": [{"date": "2026-08-25", "value": 5.23}]}
_TS_OLD = int(_dt.datetime(2026, 7, 15, 14, 0,
                           tzinfo=_dt.timezone.utc).timestamp())
_TS_NEW = int(_dt.datetime(2026, 8, 26, 14, 0,
                           tzinfo=_dt.timezone.utc).timestamp())


def _yg18(u):
    if "2YY" in u:                       # 2YY=F 最後成交停在 7/15
        return _FakeYt(3.80, 3.79, ts=_TS_OLD)
    return _FakeYt(41.8, 41.6, ts=_TS_NEW)


_c18 = {c["id"]: c for c in ft.build_catalog(_RS18, LIQ, [], offline=False,
                                             _get=_yg18)}
check("⑱ 2YY=F 舊成交（7/15）→ 退回 FRED 收盤與其日期",
      _c18["dgs2"]["value"] == "3.84%" and _c18["dgs2"]["date"] == "08-25",
      _c18["dgs2"])
check("⑱b 報價日較新的天期照常採用即時",
      _c18["dgs3mo"]["date"] == "08-26", _c18["dgs3mo"])

# ⑲ 後設偵測、排版清理、關鍵字分級
_META_TXT = ("提供的材料中，與指定關鍵字相關的內容極為有限。"
             "**由於材料缺乏，無法按要求綜合改寫成連貫的財經報導。**")
check("⑲ 後設字眼命中（實際事故的原文）",
      len(ft._meta_hits(_META_TXT)) >= 3, ft._meta_hits(_META_TXT)[:4])
check("⑲b 真新聞不誤殺（「無法」「材料」單獨出現不算）",
      ft._meta_hits("伊朗無法出口原油，半導體材料股大跌。") == [])
check("⑲c 排版清理去掉粗體、保留分段",
      ft._tidy_focus("**重點**一段。\n\n第二段。")
      == "重點一段。\n\n第二段。")

# meta 命中 → 帶原因重試；第二次乾淨 → 過
_orig_ca19 = ft._call_ai
_calls19 = []
def _ca19(src, system, env=None):
    _calls19.append(src)
    if len(_calls19) == 1:
        return _META_TXT, ""
    return "財政部宣布對伊朗實施制裁，債券市場靜待聯準會下一步。", ""
ft._call_ai = _ca19
_t19, _s19 = ft.summarize_content(
    [{"title": "t", "body": "財政部對伊朗制裁，債券市場觀望聯準會。",
      "source": "y"}], ["聯準會"], 300)
check("⑲d meta 命中重試一次、第二次乾淨 → 過",
      _s19 == "model-content" and len(_calls19) == 2
      and "被退回" in _calls19[1], _s19)
# 兩次都 meta → 退回（列標題模式的原因）
_calls19.clear()
ft._call_ai = (lambda src, system, env=None: (_META_TXT, ""))
_t19e, _s19e = ft.summarize_content(
    [{"title": "t", "body": "內文一段。", "source": "y"}], ["聯準會"], 300)
check("⑲e 兩次都後設 → 退回列標題", _t19e == "" and "後設" in _s19e, _s19e)
ft._call_ai = _orig_ca19

# 分級計分：次級命中要排在主級命中之後
_H = [{"title": "AI 資本支出暴增帶動發債", "link": "l1", "source": "y",
       "at": "2026-08-27T01:00:00+00:00", "kw": ""},
      {"title": "聯準會官員談降息路徑", "link": "l2", "source": "y",
       "at": "2026-08-27T00:00:00+00:00", "kw": ""}]
_picked = ft.pick_fallback(_H, ["聯準會 降息"], n=2,
                           secondary=["AI 資本支出", "發債"])
check("⑲f 主級（聯準會）排在次級（AI 資本支出）前面",
      _picked[0]["link"] == "l2", [x["link"] for x in _picked])
check("⑲g 次級仍會入選（不是排除，只是排後）",
      len(_picked) == 2 and _picked[1]["link"] == "l1")

# ⑳ 長度永遠不讓焦點段退回列標題：300 目標／450 底線（測試用 100／150）
_ART20 = [{"title": "t", "body": "十年期殖利率走高，市場關注聯準會。",
           "source": "Yahoo Finance"}]
_U = "殖利率走高，市場關注聯準會的後續動作與財政部發債計畫。"      # 25 字


def _run20(replies, cap=100):
    """replies 依序回傳；回傳 (結果, 來源標記, 送出的提示詞列表)。"""
    seen = []

    def _ca(src, system, env=None):
        seen.append((src, system))
        return replies[min(len(seen) - 1, len(replies) - 1)], ""

    _orig = ft._call_ai
    ft._call_ai = _ca
    try:
        t, sr = ft.summarize_content(_ART20, ["殖利率"], cap)
    finally:
        ft._call_ai = _orig
    return t, sr, seen


# 100–150 之間：直接採用，**不重試**（只呼叫一次）
_t20, _s20, _seen20 = _run20([_U * 5])                      # 125 字
check("⑳ 超過目標但在底線內 → 直接採用，不重新生成",
      _s20 == "model-content" and ft.cjk_len(_t20) == 125
      and len(_seen20) == 1, (_s20, len(_seen20)))
check("⑳b 提示詞要求的是目標值本身（100，不是 100−30）",
      "不超過 100 字" in _seen20[0][1], _seen20[0][1][-60:])

# 超過底線 → 帶字數重寫一次；第二次合格就用第二次
_t20c, _s20c, _seen20c = _run20([_U * 8, _U * 4])           # 200 → 100
check("⑳c 超過底線 → 重寫一次，用第二次的結果",
      _s20c == "model-content" and ft.cjk_len(_t20c) == 100
      and len(_seen20c) == 2 and "太長了" in _seen20c[1][0], len(_seen20c))

# 兩次都超過底線 → 裁切到底線之內，仍然採用（絕不退回列標題）
_LONG = "\n".join([_U * 2] * 4)                             # 4 段 × 50＝200
_t20d, _s20d, _ = _run20([_LONG, _LONG])
check("⑳d 兩次都超過底線 → 裁切後採用，不退回列標題",
      _s20d == "model-content" and ft.cjk_len(_t20d) <= 150
      and _t20d != "", (_s20d, ft.cjk_len(_t20d) if _t20d else 0))
check("⑳e 裁切以整段為單位，句子沒有被切斷",
      _t20d.endswith("。") and _t20d.count("\n") == 2
      and ft.cjk_len(_t20d) == 150, ft.cjk_len(_t20d))

# 裁切函式本身：連第一段都超長時退而砍到最後一個句末標點
_one = "第一句很長。第二句也不短。第三句收尾。"
check("⑳f 單段超長 → 砍到最後一個句末標點",
      ft._trim_to(_one, 12).endswith("。")
      and ft.cjk_len(ft._trim_to(_one, 12)) <= 12,
      ft._trim_to(_one, 12))
check("⑳g 沒超過就原樣不動", ft._trim_to(_one, 999) == _one)

# 正確性防護欄不受影響：數字鎖仍然一票否決（跟長度不同層級）
_t20h, _s20h, _seen20h = _run20(["殖利率升到 9.99%，市場關注。"] * 2)
check("⑳h 數字鎖仍是一票否決（不重試、不採用）",
      _t20h == "" and "沒有的數字" in _s20h and len(_seen20h) == 1, _s20h)
check("⑳i 底線倍數常數存在且合理", 1.0 < ft.HARD_MULT <= 2.0)

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
