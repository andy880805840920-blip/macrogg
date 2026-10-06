# 主題補充（依讀者選的前兩個指標換補充新聞）與期中選舉預測（Polymarket）
# 的回歸測試——不打網路。
#
# 由來（2026-10 使用者定案）：
#   · 補充依「選擇」裡前兩個指標換主題；同主題往下找、沒新聞就遞補
#   · 台指期主題可以用台灣新聞（全站排除的「台股」只擋主軸與其他主題）
#   · 每則補充加主題標籤
#   · 首頁加期中選舉預測卡（眾院、參院、權力組合、最接近的四州），附連結
import sys
import json
import pathlib
import tempfile
import datetime as dt

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.analysis import focus_today as ft                    # noqa: E402
from src.analysis import polymarket as pm                     # noqa: E402
from src.pages import home as _home                           # noqa: E402
from src.pages import election as el                          # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過 " if cond else "失敗 "), name, ("— " + str(detail)[:160]) if detail else "")
    ok = ok and bool(cond)


# ---------------------------------------------------------------- 主題對應
specs = ft.topic_specs({})
cmap = ft.chip_topic_map(specs)
check("① 內建八個主題、每個指標都有歸屬",
      len(specs) == 8 and cmap["wti"] == "oil" and cmap["txf"] == "twf"
      and cmap["pm_house"] == "election" and cmap["dgs2"] == "fed"
      and cmap["dgs10"] == "long", cmap)
allt = [s["id"] for s in specs]
check("② 預設指標（2Y、10Y、30Y、機率）→ 聯準會、長天期美債",
      ft.pick_topics(["dgs2", "dgs10", "dgs30", "fedwatch"], cmap, allt)
      == ["fed", "long"])
check("③ 前兩個同主題（10Y、30Y）→ 往下找不同主題（油價）",
      ft.pick_topics(["dgs10", "dgs30", "wti", "txf"], cmap, allt) == ["long", "oil"])
check("④ 主題沒有內容 → 往下一個指標遞補",
      ft.pick_topics(["wti", "sox", "txf"], cmap, ["semi", "twf"]) == ["semi", "twf"])
check("⑤ 全都沒有內容 → 空（由一般補充遞補）",
      ft.pick_topics(["wti"], cmap, []) == [])
_cfg_specs = ft.topic_specs({"topics": [
    {"id": "twf", "label": "台指期", "chips": ["txf"], "keywords": ["台股"],
     "exclude": ["ETF"]},
    {"id": "oil", "label": "油價", "chips": ["wti"], "keywords": ["oil"]}]})
check("⑥ config 的 exclude 取代全站排除詞；沒寫的是 None（用全站）",
      _cfg_specs[0]["exclude"] == ["ETF"] and _cfg_specs[1]["exclude"] is None)

check("⑥b 主題關鍵字是詞組比對：Wall Street 不會被 market 這種單詞拖下水",
      ft._phrase_hit("Wall Street", "Stocks rally on Wall Street")
      and not ft._phrase_hit("bond market", "Stock market rallies")
      and not ft._phrase_hit("Fed", "FedEx shares fall")
      and ft._phrase_hit("台股 外資", "外資買超台股 300 億"))

# ---------------------------------------------------------------- 材料蒐集
_now = dt.datetime(2026, 10, 5, 2, tzinfo=dt.timezone.utc)
_at = (_now - dt.timedelta(hours=3)).isoformat()
pool = [
    {"title": "台股外資賣超 120 億元 加權指數收黑", "link": "https://tw.stock.yahoo.com/a1",
     "source": "Yahoo奇摩股市", "at": _at, "summary": ""},
    {"title": "台股 ETF 存股族怎麼買", "link": "https://tw.stock.yahoo.com/a2",
     "source": "Yahoo奇摩股市", "at": _at, "summary": ""},
    {"title": "Oil prices jump 4% as OPEC signals cuts", "link": "https://finance.yahoo.com/o1",
     "source": "Yahoo Finance", "at": _at, "summary": ""},
    {"title": "Fed's Waller says rate cut not needed", "link": "https://finance.yahoo.com/f1",
     "source": "Yahoo Finance", "at": _at, "summary": ""},
]
_bodies = {"https://tw.stock.yahoo.com/a1": "外資今天賣超 120 億元，加權指數下跌 1.2%。" * 4,
           "https://finance.yahoo.com/o1": "Oil rose 4% to $95 after OPEC said it may cut output." * 3,
           "https://finance.yahoo.com/f1": "Waller said a rate cut is not needed now." * 3}
mat = ft.gather_topic_material(
    _cfg_specs + [{"id": "fed", "label": "聯準會", "chips": [], "keywords": ["Fed"],
                   "exclude": None, "search": []}],
    pool, global_exclude=["台股", "ETF"],
    main_titles=["Fed's Waller says rate cut not needed - Reuters"], now=_now,
    _fetch=lambda *a, **k: [], _body=lambda u: _bodies.get(u, ""))
check("⑦ 台指期主題放行「台股」新聞（全站排除詞不套用），但擋 ETF 理財文",
      "twf" in mat and [a["title"] for a in mat["twf"]["arts"]]
      == ["台股外資賣超 120 億元 加權指數收黑"], mat.get("twf"))
check("⑧ 油價主題用全站排除詞、抓到內文", "oil" in mat and mat["oil"]["arts"])
check("⑨ 跟主軸同一件事的新聞剔除（聯準會主題沒有別的新聞 → 不出現）",
      "fed" not in mat, list(mat))

# ---------------------------------------------------------------- 生成與驗證
_seen = []


def _fake_ai(replies):
    def _ca(src, system, env=None):
        _seen.append((src, system))
        return replies[min(len(_seen) - 1, len(replies) - 1)], ""
    return _ca


_orig = ft._call_ai
_good_twf = "外資今天賣超 120 億元，加權指數下跌 1.2%，賣壓集中在電子權值股，市場擔心美債殖利率走高壓抑科技股評價。"
_good_oil = "OPEC 表示可能減產，油價上漲 4% 至每桶 95 美元，能源價格走高推升市場的通膨預期，也讓降息路徑更難預料。"
try:
    _seen.clear()
    ft._call_ai = _fake_ai([f"twf｜{_good_twf}\noil｜油價週線大漲 8.3%，布蘭特原油升至"
                            "每桶 101 美元，能源股同步走強，市場重新評估通膨前景與降息時點。",  # 8.3／101 不在材料裡
                            f"oil｜{_good_oil}"])
    got = ft.summarize_topics({k: mat[k] for k in ("twf", "oil")},
                              {"twf": "台指期", "oil": "油價"}, "主軸內容")
    check("⑩ 數字鎖逐主題：油價那則有材料外的數字 → 只重寫油價",
          len(_seen) == 2 and "=== twf" not in _seen[1][0] and "=== oil" in _seen[1][0]
          and got == {"twf": _good_twf, "oil": _good_oil}, got)
    check("⑪ 提示詞：不重複主軸、不能只重述標題、代號｜內容格式",
          "不要跟主軸講同一件事" in _seen[0][1] and "不能只重述標題" in _seen[0][1]
          and "代號｜內容" in _seen[0][1])
    _seen.clear()
    ft._call_ai = _fake_ai([f"twf｜外資賣超\noil｜略", f"twf｜{_good_twf}"])
    got = ft.summarize_topics({k: mat[k] for k in ("twf", "oil")},
                              {"twf": "台指期", "oil": "油價"}, "主軸內容")
    check("⑫ 太短像標題 → 重寫；「略」＝這個主題不顯示",
          got == {"twf": _good_twf} and "像在列標題" in _seen[1][0], got)

    # 整條流程＋快取
    _seen.clear()
    ft._call_ai = _fake_ai([f"twf｜{_good_twf}\noil｜{_good_oil}"])
    st = {}
    cfg = {"topics": [dict(s, search=[]) for s in ft.DEFAULT_TOPICS],
           "exclude_keywords": ["台股", "ETF"]}
    _orig_body = ft.fetch_article_text
    ft.fetch_article_text = lambda u, **k: _bodies.get(u, "")
    r1 = ft.build_topics(cfg, pool, "主軸", ["Fed's Waller says rate cut not needed"],
                         st, now=_now)
    r2 = ft.build_topics(cfg, pool, "主軸", ["Fed's Waller says rate cut not needed"],
                         st, now=_now + dt.timedelta(hours=2))
    ft.fetch_article_text = _orig_body
    check("⑬ build_topics：產出照主題順序、附連結與對應表",
          [x["id"] for x in r1["items"]] == ["oil", "twf"]
          and r1["items"][0]["links"] and r1["map"]["wti"] == "oil", r1["items"])
    check("⑭ 材料沒變、12 小時內 → 沿用快取（不再呼叫 AI）",
          len(_seen) == 1 and r2["items"] == r1["items"])
finally:
    ft._call_ai = _orig

# ---------------------------------------------------------------- 首頁渲染
cat = [ft._mk(c, c.upper(), "1", "+0", "", "2026-10-05", on=c in ft.DEFAULT_CHIPS)
       for c in ("dgs2", "dgs10", "dgs30", "fedwatch", "wti", "txf")]
f = {"chips": cat, "text": "主軸¶第二段\n一般補充甲\n一般補充乙", "layout": "main",
     "text_source": "model-content", "fedwatch": None,
     "links": [{"title": "主軸新聞", "link": "https://x/1", "source": "Reuters"}],
     "topics": [{"id": "fed", "label": "聯準會", "text": "聯準會補充",
                 "links": [{"title": "聯準會新聞", "link": "https://x/2", "source": "CNBC"}]},
                {"id": "oil", "label": "油價", "text": "油價補充",
                 "links": [{"title": "油價新聞", "link": "https://x/3", "source": "Bloomberg"}]}],
     "topic_map": cmap}
h = _home._focus_strip(f)
ul = h.split('<ul class="fs-list">')[1].split("</ul>")[0]
check("⑮ 預設指標 → 聯準會補充顯示（帶標籤）、長天期美債沒內容 → 一般補充遞補一則",
      '<li class="fs-text fs-topic" data-topic="fed"><span class="fs-tag">聯準會</span>'
      '聯準會補充</li>' in ul
      and 'fs-off" data-topic="oil"' in ul
      and ul.count('data-gen="1">') == 2 and ul.count('fs-off" data-gen') == 1, ul)
check("⑯ 主題連結：顯示中的主題才露出、來源列含該主題來源",
      'data-tlink="fed"' in h and 'fs-link fs-off" data-tlink="oil"' in h
      and "新聞：Reuters、CNBC" in h)
check("⑰ JS：指標→主題對應、有內容的主題、先勾的排前面",
      '"wti": "oil"' in h and 'var TA=["fed", "oil"]' in h
      and "box.appendChild(ch)" in h and "<em>補充新聞</em>" in h)

# ---------------------------------------------------------------- Polymarket
def mk_market(name, p, vol=1000, d1=None, token="t"):
    return {"groupItemTitle": name, "outcomes": json.dumps(["Yes", "No"]),
            "outcomePrices": json.dumps([str(p), str(round(1 - p, 4))]) if p is not None else "[]",
            "volume": str(vol), "oneDayPriceChange": d1,
            "clobTokenIds": json.dumps([token, token + "n"]), "closed": False}


house = {"slug": "h", "volume": "5000000", "markets": [
    mk_market("Democratic Party", 0.925, d1=-0.01, token="hd"),
    mk_market("Republican Party", 0.075), mk_market("Party A", None)]}
bad_sum = {"slug": "s", "volume": "5000000", "markets": [
    mk_market("Democratic Party", 0.9), mk_market("Republican Party", 0.6)]}
bal = {"slug": "b", "volume": "9000000", "markets": [
    mk_market("Democrats Sweep", 0.665), mk_market("D Senate, R House", 0.0065),
    mk_market("R Senate, D House", 0.275), mk_market("Republicans Sweep", 0.075),
    mk_market("Other", 0.0015)]}
races = [
    {"title": "Iowa Senate Election Winner", "slug": "iowa", "volume": "725937",
     "markets": [mk_market("Ashley Hinson (R)", 0.575), mk_market("Josh Turek (D)", 0.415),
                 mk_market("Person A", None)]},
    {"title": "Georgia Senate Election Winner", "slug": "ga", "volume": "205738",
     "markets": [mk_market("Jon Ossoff (D)", 0.51), mk_market("Mike Collins (R)", 0.49)]},
    {"title": "Maine Senate Election Winner", "slug": "maine", "volume": "2109568",
     "markets": [mk_market("Troy Jackson (D)", 0.585), mk_market("Susan Collins (R)", 0.42)]},
    {"title": "Alaska Senate Election Winner", "slug": "ak", "volume": "1117162",
     "markets": [mk_market("Mary Peltola", 0.725), mk_market("Sen. Dan Sullivan", 0.275)]},
    {"title": "Arizona Governor Election Winner", "slug": "azg", "volume": "999999",
     "markets": [mk_market("A (D)", 0.5), mk_market("B (R)", 0.5)]},
]

check("⑱ 兩黨價格：空白選項略過、加總接近 100% 才採用",
      pm._party_pair(house)["dem"] == 0.925 and pm._party_pair(bad_sum) is None)
_b = pm._balance(bal)
check("⑲ 權力組合：五個選項、中文標籤", _b and _b[0]["label"] == "民主黨兩院全拿"
      and len(_b) == 5, _b)
_r = [pm._race(e, 300000) for e in races]
check("⑳ 州選戰：交易量不足（喬治亞 20 萬）與州長選舉不採用；名字與黨派拆開",
      _r[1] is None and _r[4] is None and _r[0]["state"] == "愛荷華"
      and _r[0]["lead"] == {"name": "Ashley Hinson", "party": "共", "p": 0.575}
      and _r[3]["other"]["name"] == "Dan Sullivan" and _r[3]["lead"]["party"] == "", _r[0])


class _R:
    def __init__(self, d):
        self.d = d

    def raise_for_status(self):
        pass

    def json(self):
        return self.d


def fake_get(url, params):
    if url.endswith("/events") and params.get("slug"):
        return _R([{"h": house, "s": dict(house, slug="s"), "b": bal}[params["slug"]]])
    if url.endswith("/events"):
        return _R(races if params.get("offset") == 0 else [])
    if "prices-history" in url:
        return _R({"history": [{"t": i, "p": 0.5 + i / 100} for i in range(10)]})
    raise AssertionError(url)


with tempfile.TemporaryDirectory() as td:
    sp = pathlib.Path(td) / "election.json"
    cfgp = {"house": "h", "senate": "s", "balance": "b", "n_races": 2,
            "race_min_volume": 300000, "election_date": "2026-11-03",
            "hide_after": "2026-11-17"}
    _orig_today = pm.clock.today
    pm.clock.today = lambda: dt.date(2026, 10, 5)
    try:
        e = pm.build(cfgp, sp, _get=fake_get)
        check("㉑ build：眾院、參院、權力組合、最接近的兩州（愛荷華、緬因）、30 天走勢",
              e and e["house"]["dem"] == 0.925 and e["balance"]
              and [r["state"] for r in e["races"]] == ["愛荷華", "緬因"]
              and len(e["house"]["hist"]) == 10 and e["days_to"] == 29, e and e.get("races"))
        check("㉒ 每一列都有 Polymarket 連結",
              e["house"]["url"] == "https://polymarket.com/event/h"
              and e["races"][0]["url"].endswith("/event/iowa"))

        def boom(url, params):
            raise RuntimeError("down")
        pm.clock.today = lambda: dt.date(2026, 10, 7)
        e2 = pm.build(cfgp, sp, _get=boom)
        check("㉓ 抓不到 → 沿用上次（3 天內）並標明", e2 and e2["stale_from"] == "2026-10-05"
              and e2["days_to"] == 27)
        pm.clock.today = lambda: dt.date(2026, 10, 12)
        check("㉔ 超過 3 天 → 不顯示", pm.build(cfgp, sp, _get=boom) is None)
        pm.clock.today = lambda: dt.date(2026, 11, 18)
        check("㉕ 過了 hide_after → 整張卡片隱藏", pm.build(cfgp, sp, _get=fake_get) is None)
        pm.clock.today = lambda: dt.date(2026, 10, 5)
        check("㉖ 停用 → None", pm.build({"enabled": False}, sp, _get=fake_get) is None)
    finally:
        pm.clock.today = _orig_today

c = pm.chips(e)
check("㉗ 兩顆 chip：眾院・民主黨 92.5%、一天 −1.0 百分點",
      c[0]["id"] == "pm_house" and c[0]["value"] == "92.5%"
      and c[0]["delta"] == "-1.0 百分點" and pm.chips(None)[1]["value"] == "—", c)
card = el.election_card(e)
check("㉘ 卡片：標題、倒數、民主黨 92.5%、權力組合、兩州、註腳講明不是民調",
      "期中選舉預測" in card and "還有 29 天" in card and "民主黨 92.5%" in card
      and "民主黨兩院全拿" in card and "愛荷華" in card and "不是民調" in card
      and 'href="https://polymarket.com/event/iowa"' in card and "el-spark" in card, card[:300])
card2 = el.election_card({**e, "days_to": -1})
check("㉙ 選舉日之後 → 標題改「期中選舉結果」", "期中選舉結果" in card2)
check("㉚ 沒有資料 → 不輸出", el.election_card(None) == ""
      and el.election_card({"date": "2026-10-05"}) == "")
cat2 = ft.build_catalog({}, {}, [], offline=True, election=e)
check("㉛ chip 目錄帶眾院／參院兩顆（預設不顯示）",
      [x["id"] for x in cat2][-2:] == ["pm_house", "pm_senate"]
      and not cat2[-1]["on"])

# ---------------------------------------------------------------- 各州地圖
ov = {"Mary Peltola": "D"}
check("㉜ 黨派：(D) 標記、設定檔補標、選項名本身（Democrat／Independent）、未知＝?",
      pm._party_of("Troy Jackson (D)", ov) == "D" and pm._party_of("Mary Peltola", ov) == "D"
      and pm._party_of("Democrat", ov) == "D" and pm._party_of("Independent", ov) == "I"
      and pm._party_of("Sen. Dan Sullivan", {"Dan Sullivan": "R"}) == "R"
      and pm._party_of("Somebody", ov) == "?")
check("㉝ 分級：85／65／55 為界",
      [pm.tier_of(x)[0] for x in (0.9, 0.85, 0.7, 0.6, 0.54)]
      == ["safe", "safe", "likely", "lean", "toss"])
_sr = pm.state_race({"title": "Alaska Senate Election Winner  ", "slug": "ak", "volume": "1",
                     "markets": [mk_market("Mary Peltola", 0.725),
                                 mk_market("Sen. Dan Sullivan", 0.275),
                                 mk_market("Person A", None)]},
                    {"Mary Peltola": "D", "Dan Sullivan": "R"})
check("㉞ 州選戰 → 地圖資料（州名、縮寫、分級、差距、連結）",
      _sr and _sr["kind"] == "senate" and _sr["state"] == "阿拉斯加" and _sr["abbr"] == "AK"
      and _sr["tier"] == "likely" and _sr["gap"] == 45.0
      and _sr["other"]["name"] == "Dan Sullivan", _sr)


def _mkr(st, party, p, other_party=None):
    op = other_party or ("R" if party == "D" else "D")
    tk, tz = pm.tier_of(p)
    return {"kind": "senate", "state_en": st, "state": pm.STATES.get(st, st),
            "abbr": pm.ABBR[st], "lead": {"name": "A", "party": party, "p": p},
            "other": {"name": "B", "party": op, "p": round(1 - p, 3)},
            "tier": tk, "tier_zh": tz, "gap": round((2 * p - 1) * 100, 1),
            "vol": 1e6, "url": "u"}


C = pm._cfg({})
sts = list(pm.SENATE_2026)
# 民主黨領先 18、共和黨領先 17 → 34+18 : 31+17 = 52:48
races = {s: _mkr(s, "D" if i < 18 else "R", 0.9) for i, s in enumerate(sts)}
races["Maine"] = _mkr("Maine", "D", 0.585)
races["Nebraska"] = _mkr("Nebraska", "R", 0.575)
t1 = pm.tally("senate", races, C)
s1 = pm.sentence("senate", t1, C)
check("㉟ 參院比分：沒改選 34:31＋領先 18:17＝52:48；一句話講翻轉與最接近的州",
      t1["total"]["D"] == 52 and t1["total"]["R"] == 48
      and "民主黨將以 52:48 翻轉參院" in s1 and "緬因" in s1 and "內布拉斯加" in s1, s1)
races2 = {s: _mkr(s, "D" if i < 16 else "R", 0.9) for i, s in enumerate(sts)}
s2 = pm.sentence("senate", pm.tally("senate", races2, C), C)
check("㊱ 50:50 → 副總統投票、共和黨掌控；沒有競爭州要講",
      "50:50" in s2 and "副總統" in s2 and "共和黨掌控" in s2 and "沒有勝負接近的州" in s2, s2)
races3 = {s: _mkr(s, "D" if i < 10 else "R", 0.9) for i, s in enumerate(sts)}
s3 = pm.sentence("senate", pm.tally("senate", races3, C), C)
check("㊲ 共和黨過半 → 保住參院", "共和黨將以 56:44 保住參院" in s3, s3)
gr = {s: dict(_mkr("Ohio", "D" if i < 21 else "R", 0.9), state_en=s, kind="governor")
      for i, s in enumerate(pm.GOVERNOR_2026)}
sg = pm.sentence("governor", pm.tally("governor", gr, C), C)
check("㊳ 州長：領先者在前、附改選前比分", "民主黨 27 州 : 共和黨 23 州（改選前共和黨 27:23）" in sg, sg)
check("㊴ 席次分布的區間轉中文",
      pm._bucket_zh("Below 190") == "190 席以下" and pm._bucket_zh("230+") == "230 席以上"
      and pm._bucket_zh("22–23", "州") == "22–23 州" and pm._bucket_zh("≤47") == "≦47 席")
missing = pm.tally("senate", {k: v for k, v in races.items() if k != "Texas"}, C)["missing"]
check("㊵ 有改選但沒盤口的州另外列出", missing == ["Texas"])

e_map = {**e, "maps": {"senate": {"races": races, "tally": t1, "sentence": s1},
                       "governor": {"races": gr, "tally": pm.tally("governor", gr, C),
                                    "sentence": sg},
                       "seats": {"senate": {"label": "≦47 席", "p": 0.385, "url": "u"}}}}
html = el.election_card(e_map)
sec = html.split('<details class="el-map">')[1] if '<details class="el-map">' in html else ""
check("㊶ 地圖預設收合、標題列直接寫比分（參院、州長）",
      sec and "參院 民主黨 52 : 48 共和黨" in sec and "州長 民主黨 27 : 23 共和黨" in sec
      and '<details class="el-map" open' not in html, sec[:200])
check("㊷ 參院／州長切換、州長頁預設隱藏、過半線、市場席次、一句話",
      'class="el-tab" data-k="senate"' in sec and 'data-k="governor" hidden' in sec
      and "過半 51" in sec and "共和黨參院席次・最可能" in sec
      and "≦47 席<small>38.5%</small>" in sec and s1 in sec)
check("㊸ 地圖：51 個州（含 DC）、小州方塊、沒改選的灰、提示文字含候選人",
      sec.count('<path class="st') == 102 and sec.count('class="sb"') == 16
      and "c-off" in sec and "data-tip=\"緬因・微幅" in sec, sec.count('<path class="st'))
check("㊹ 圖例與競爭州列表（短標籤；分級定義收在「比分怎麼算？」）",
      "五五波</li>" in sec and "競爭州<small>領先者低於 65%</small>" in sec
      and "<summary>比分怎麼算？</summary>" in sec and "≥85% 穩拿" in sec)
check("㊺ 手機版：數字磚取代長句、註腳一行＋「說明」收合、州名後是黨＋價格",
      'class="el-stats"' in sec and "el-detail" not in sec
      and '<details class="el-how"><summary>說明</summary>' in html
      and "價格＝下注者的看法，不是民調" in html
      and '<b class="rep">共 57.5%</b>' in html
      # 2026-10 精簡版：長條圖只剩眾參院旁的走勢線
      and "el-bar" not in html.split('<details class="el-map">')[0]
      and "el-stack" not in html and "el-mini" not in html.split('<details class="el-map">')[0],
      html[:100])

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
