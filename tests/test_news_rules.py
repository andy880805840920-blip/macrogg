"""
第十七批（2026-10）新聞規則：退回 10/6 穩定版選文流程後加上的規則。

  ① 英文關鍵字要完整單字      ② 三則報導計數（轉載只算一次）
  ③ 主軸來源＝AI 實際用到的報導（彭博、路透排前面）
  ④ 粗體標題＋對利率（以主軸事件為主、官方殖利率對照；方向不同要點出落差，否則改用規則句）
  ⑤ 正文不寫媒體名、不寫相對時間、人名統一中文譯名
  ⑥ 數據日鎖定主軸、前一兩次寫過的事件扣分
  ⑦ 補充不重複主軸、失敗主題不顯示（選單變灰）、沒有「暫時無法取得」
  ⑧ 主題設定：匯率／選舉／油價／黃金的必含詞、主軸來源清單
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from src.analysis import focus_today as ft  # noqa: E402
from src.pages import home  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過  " if cond else "失敗  ") + name + (f" — {detail}" if detail and not cond else ""))
    ok = ok and bool(cond)


NOW = dt.datetime.now(dt.timezone.utc)
ISO = lambda h: (NOW - dt.timedelta(hours=h)).isoformat()

# ---------------------------------------------------------------- ① 單字比對
check("① AI 不命中 said／again／chain", not ft._kw_hit("AI", "Powell said again the chain holds"))
check("① AI 命中獨立的 AI", ft._kw_hit("AI", "AI stocks rally"))
check("① Fed 不命中 Federal／FedEx", not ft._kw_hit("Fed", "Federal judge rules on FedEx"))
check("① Fed 命中 Fed's", ft._kw_hit("Fed", "Fed's Waller says"))
check("① 複數也算（tariff → tariffs）", ft._kw_hit("tariff", "New tariffs hit imports"))
check("① 中文照舊子字串", ft._kw_hit("美債", "美債殖利率攀升"))

# ---------------------------------------------------------------- ② 報導計數
_items = [{"title": "Fed's Waller says another hike may be needed - Reuters"},
          {"title": "Fed's Waller says another hike may be needed"},       # 轉載
          {"title": "Treasury yields climb to highest since 2002"},
          {"title": "Oil jumps as hurricane threatens Gulf output"}]
check("② 轉載只算一則（4 篇 → 3 則不同報導）", ft._story_count(_items) == 3,
      ft._story_count(_items))

# ---------------------------------------------------------------- ③ 解析與來源
_out = ("【標題】\n美債殖利率續攀高、30 年期逼近 6%\n【主軸】\n第一段。\n第二段。\n"
        "【對利率】長端上行壓力未退。\n【補充】\n補充甲。\n補充乙。\n【來源】\n3,1")
_p = ft._parse_main_output(_out, 2)
check("③ 解析：標題、兩段主軸、對利率、兩則補充、來源代號",
      _p["headline"] == "美債殖利率續攀高、30 年期逼近 6%" and _p["main"] == ["第一段。", "第二段。"]
      and _p["rate"] == "長端上行壓力未退。" and _p["supp"] == ["補充甲。", "補充乙。"]
      and _p["ids"] == [3, 1], _p)
_p2 = ft._parse_main_output("【標題】只有標題沒有主軸標記\n主軸文字一段。\n補充甲。\n補充乙。", 2)
check("③ 漏寫【主軸】【補充】也切得對（最後兩行是補充）",
      _p2["headline"] == "只有標題沒有主軸標記" and _p2["main"] == ["主軸文字一段。"]
      and _p2["supp"] == ["補充甲。", "補充乙。"], _p2)
_mats = [{"title": "Yahoo story - Yahoo Finance", "link": "https://y/1", "source": "Yahoo Finance"},
         {"title": "CNBC story", "link": "https://c/2", "source": "CNBC"},
         {"title": "Fed hike talk - Reuters", "link": "https://news.google.com/r", "source": "Reuters"},
         {"title": "Unused Bloomberg story", "link": "https://news.google.com/b", "source": "Bloomberg"}]
_lk = ft._pick_links(_mats, [1, 3], 3)
check("③ 來源只列實際用到的（1、3），路透排第一、沒用到的彭博不列",
      [x["source"] for x in _lk] == ["Reuters", "Yahoo Finance"], _lk)
check("③ 連結標題去掉尾巴的「 - 來源」", _lk[0]["title"] == "Fed hike talk", _lk[0])
check("③ AI 沒回報代號 → 退回材料排名（彭博、路透先）",
      [x["source"] for x in ft._pick_links(_mats, [], 3)] == ["Reuters", "Bloomberg", "CNBC"])
_T6 = ["Fed hikes rates again", "Oil jumps on Gulf attack", "Dollar hits 18-month high",
       "Gold slips as yields climb", "Payrolls beat forecasts", "Chipmakers slide on memory glut",
       "Treasury auction draws weak demand", "Housing starts tumble"]
_m6 = [{"title": _T6[i], "link": f"https://news.google.com/{i}", "source": s}
       for i, s in enumerate(["Reuters", "Bloomberg", "Reuters", "Bloomberg"])] + \
      [{"title": _T6[4 + i], "link": f"https://d/{i}", "source": "CNBC"} for i in range(4)]
_l6 = [x["source"] for x in ft._pick_links(_m6, list(range(1, 9)), ft.MAX_MAIN_LINKS, ft.MAIN_LINKS_PER_TIER)]
check("③ 主軸來源最多 6 則：原文與其他各最多 3 則", _l6.count("CNBC") == 3 and len(_l6) == 6, _l6)
check("③ 每層只是上限、不硬湊（只用到 1 則原文＋1 則其他 → 2 則）",
      len(ft._pick_links(_m6, [1, 5], ft.MAX_MAIN_LINKS, ft.MAIN_LINKS_PER_TIER)) == 2)

# ---------------------------------------------------------------- ⑤ 文字規則
check("⑤ 人名：Trump → 川普、Bessent → 貝森特、鮑威爾 → 鮑爾",
      ft.normalize_names("Trump 與 Scott Bessent、鮑威爾會面") == "川普與貝森特、鮑爾會面",
      ft.normalize_names("Trump 與 Scott Bessent、鮑威爾會面"))
check("⑤ 已是標準寫法不會重複（貝森特不變成貝森特特）", ft.normalize_names("貝森特表示") == "貝森特表示")
check("⑤ 公司名不黏字（Nvidia AI → 輝達 AI，不是 NVIDIAAI）",
      ft.normalize_names("Nvidia AI 晶片") == "輝達 AI 晶片", ft.normalize_names("Nvidia AI 晶片"))
check("⑤ config 的 name_map 可以追加", ft.normalize_names(
    "Takaichi 表示", ft._name_map({"name_map": {"高市早苗": ["Takaichi"]}})) == "高市早苗表示")
check("⑤ 偵測媒體名", ft._media_hits("據路透報導，鮑爾表示") == ["路透"])
check("⑤ 刪掉「據路透報導，」這類說法", ft._strip_media("據路透報導，鮑爾表示") == "鮑爾表示")
check("⑤ 偵測相對時間", bool(ft._REL_DATE.search("鮑爾週四表示")) and not ft._REL_DATE.search("鮑爾 10/9 表示"))

# ---------------------------------------------------------------- ④ 對利率
def _rows(vals):
    d0 = dt.date(2026, 10, 1)
    return [{"date": (d0 + dt.timedelta(days=i)).isoformat(), "value": v} for i, v in enumerate(vals)]


_rs = {"DGS2": _rows([4.70, 4.71, 4.72, 4.73, 4.74, 4.75]),
       "DGS10": _rows([5.10, 5.13, 5.16, 5.19, 5.21, 5.22]),
       "DGS30": _rows([5.50, 5.52, 5.54, 5.56, 5.58, 5.60])}
_rc = ft.rate_context(_rs)
check("④ 網站利率判讀：10Y +12bp、2Y +5bp → 熊陡",
      _rc and _rc["d10"] == 12 and _rc["d2"] == 5 and _rc["zh"] == "熊陡", _rc)
check("④ 方向檢查：利率上行時寫「回落」算相反", not ft._rate_consistent("長端利率回落", _rc)
      and ft._rate_consistent("長端上行壓力未退", _rc))
check("④ 規則句含數字與型態", "+12bp" in ft._rate_fallback(_rc) and "熊陡" in ft._rate_fallback(_rc))
_rcd = dict(_rc, d10=-4, d2=-3)
_src = ft._rate_block(_rcd) + " 哈瑪克主張升息，12月升息機率接近88%"
check("④ 新聞偏推升、利率卻下行：點出落差並引用實際變動 → 放行",
      ft._rate_consistent("哈瑪克放鷹，偏向推升短端利率與12月升息預期；不過近一週 10 年期 -4bp，市場還沒反映。", _rcd, _src))
check("④ 方向不同卻沒點出落差 → 退回", not ft._rate_consistent("哈瑪克放鷹，偏向推升短端利率。", _rcd, _src))
check("④ 預測口吻（將會）→ 退回",
      any("預測" in x for x in ft._rate_issues("鷹派言論將會推升利率；不過 10 年期 -4bp，市場還沒反映。", _rcd, _src)))
check("④ 材料沒有的數字 → 退回",
      any("沒有的數字" in x for x in ft._rate_issues("偏向推升利率；不過 10 年期 -4bp、2 年期 -7bp，市場還沒反映。", _rcd, _src)))
check("④ 方向不明確的寫法放行", ft._rate_consistent("油價上漲對利率方向不明確，取決於通膨預期與避險需求孰強。", _rcd, _src))

# ---------------------------------------------------------------- ⑥ 排序
_h = {"title": "CPI rises 0.4% in September", "source": "CNBC", "at": ISO(2)}
_base = ft.rank_score(_h, ["inflation"], now=NOW)
check("⑥ 鎖定級事件（CPI 日）＋8，一般事件＋2",
      ft.rank_score(_h, ["inflation"], now=NOW, events=["cpi"], lock_events=["cpi"]) == _base + 8
      and ft.rank_score(_h, ["inflation"], now=NOW, events=["cpi"]) == _base + 2)
_old = {"title": "10-year Treasury yields at risk of hitting 6%, Pimco says", "at": ISO(2)}
_rec = [ft._norm_title("U.S. 10-year Treasury yields at risk of hitting 6%, Pimco tells FT")]
check("⑥ 前一兩次寫過的同一則報導扣 4 分",
      ft.rank_score(_old, ["Treasury"], now=NOW, recent=_rec)
      == ft.rank_score(_old, ["Treasury"], now=NOW) - 4)

# ---------------------------------------------------------------- write_main 整段
_seen = []


def _fake(replies):
    def _ca(src, system, env=None, **_kw):
        _seen.append((src, system))
        return replies[min(len(_seen) - 1, len(replies) - 1)], ""
    return _ca


_U = "美國十年期公債殖利率升至5.22%，市場關注聯準會後續動作。"     # 25 字
_arts = [{"title": "Treasury yields climb as Fed signals more hikes", "body": "Yields rose to 5.22% " * 20,
          "source": "Yahoo Finance", "link": "https://y/a", "at": ISO(3)}]
_briefs = [{"title": "Fed's Waller backs another hike - Reuters", "source": "Reuters",
            "link": "https://news.google.com/w", "at": ISO(4), "summary": ""},
           {"title": "Bond selloff deepens - Bloomberg", "source": "Bloomberg",
            "link": "https://news.google.com/b", "at": ISO(5), "summary": ""}]
_good = ("【標題】美債殖利率升至5.22%、聯準會釋出升息訊號\n【主軸】\n" + _U * 4 + "\n" + _U * 4
         + "\n【對利率】長端上行壓力未退，曲線熊陡。\n【補充】\n" + _U * 2 + "\n" + _U * 2
         + "\n【來源】\n2,1")
_bad = _good.replace("【主軸】\n", "【主軸】\n據路透報導，").replace("【標題】美債殖利率升至5.22%、聯準會釋出升息訊號\n", "")
_orig_ai = ft._call_ai
try:
    ft._call_ai = _fake([_bad, _good])
    res, err = ft.write_main(_arts, _briefs, ["Treasury"], {}, caps=[250, 80, 80],
                             mins=[200, 40, 40], rate_ctx=_rc)
    check("寫主軸：缺標題、寫了媒體名 → 帶原因重寫一次",
          len(_seen) == 2 and "【標題】" in _seen[1][0] and "媒體名稱" in _seen[1][0],
          _seen[-1][0][-120:] if _seen else "")
    check("寫主軸：結果有標題、對利率、主軸與兩則補充",
          res and res["headline"].startswith("美債殖利率") and res["rate"].startswith("長端上行")
          and len(res["text"].splitlines()) == 3, (res, err))
    check("寫主軸：來源＝代號 2、1（路透先）",
          res and [x["source"] for x in res["links"]] == ["Reuters", "Yahoo Finance"],
          res and res["links"])
    check("寫主軸：材料標了代號、日期與網站利率判讀",
          "【報導1｜Yahoo Finance｜" in _seen[0][0] and "只有標題" in _seen[0][0]
          and "網站利率判讀" in _seen[0][0])
    check("寫主軸：提示詞要求利率主線、標題、對利率、不寫媒體名、月/日",
          all(k in _seen[0][1] for k in ("利率主線", "【標題】", "【對利率】", "媒體名稱", "月/日")))
    _seen.clear()
    _wrong = _good.replace("長端上行壓力未退，曲線熊陡。", "長端利率回落，債市走穩。")
    ft._call_ai = _fake([_wrong, _wrong])
    res, err = ft.write_main(_arts, _briefs, ["Treasury"], {}, caps=[250, 80, 80],
                             mins=[200, 40, 40], rate_ctx=_rc)
    check("寫主軸：對利率方向兩次都相反 → 改用規則句（跟網站判讀一致）",
          res and "熊陡" in res["rate"] and "+12bp" in res["rate"], res and res["rate"])
finally:
    ft._call_ai = _orig_ai

# ---------------------------------------------------------------- build：三則、鎖定、重複
_feed_items = {
    "main": [{"title": "Treasury yields jump as CPI beats forecasts", "link": "https://finance.yahoo.com/x1",
              "source": "Yahoo Finance", "at": ISO(2), "summary": ""},
             {"title": "Fed's Waller backs another hike - Reuters", "link": "https://news.google.com/rss/articles/w",
              "source": "Reuters", "at": ISO(3), "summary": ""}],
    "wide": [{"title": "Bond selloff deepens as inflation sticks - Bloomberg", "link": "https://news.google.com/rss/articles/b",
              "source": "Bloomberg", "at": ISO(40), "summary": ""},
             {"title": "Dollar climbs on Fed bets", "link": "https://finance.yahoo.com/x2",
              "source": "Yahoo Finance", "at": ISO(41), "summary": ""}],
}
_calls = {"hours": []}


def _fetch(feeds, kws, hours=30, exclude=None, raw_out=None, **k):
    _calls["hours"].append(hours)
    items = _feed_items["main"] + (_feed_items["wide"] if hours >= 60 else [])
    if raw_out is not None:
        raw_out.extend(items)
    return [dict(x) for x in items]


_orig = (ft.fetch_feed_headlines, ft.fetch_article_text, ft._call_ai, ft.build_catalog,
         ft.fedwatch_path, ft.fetch_atlanta_fedwatch, ft.build_topics)
try:
    ft.fetch_feed_headlines = _fetch
    ft.fetch_article_text = lambda u, **k: ("Yields rose to 5.22% " * 20) if "yahoo" in u else ""
    ft.build_catalog = lambda *a, **k: []
    ft.fedwatch_path = lambda *a, **k: None
    ft.fetch_atlanta_fedwatch = lambda *a, **k: None
    ft.build_topics = lambda *a, **k: {"items": [], "map": {}}
    _seen.clear()
    ft._call_ai = _fake([_good])
    _sp = pathlib.Path(tempfile.mkdtemp()) / "focus.json"
    _today = __import__("src.clock", fromlist=["today"]).today()
    _cfg = {"keywords": ["Treasury", "Fed", "inflation"], "feeds": ["https://x/rss"]}
    _o = ft.build(_rs, False, _cfg, _sp, env={}, events={"cpi": [_today.isoformat()]})
    check("build：不足三則 → 第二輪放寬到 60 小時", 60 in _calls["hours"], _calls["hours"])
    check("build：CPI 日 → 提示詞寫明主軸鎖定 CPI", _seen and "CPI 通膨數據" in _seen[0][1])
    check("build：輸出含標題與對利率，來源是 AI 用到的",
          _o.get("headline") and _o.get("rate_note") and _o.get("links"), _o)
    _st = json.loads(_sp.read_text(encoding="utf-8"))
    check("build：狀態記下最近一次主軸（給下次避免重複）",
          _st.get("recent_mains") and _st["recent_mains"][-1]["headline"] == _o["headline"])
    # v2（2026-10-25）：同一批新聞、12 小時內再跑 → 仍然重寫（主軸不沿用快取）
    _seen.clear()
    _o2 = ft.build(_rs, False, _cfg, _sp, env={}, events={"cpi": [_today.isoformat()]})
    check("build v2：材料沒變也每次重寫（呼叫 AI、不是 cache）",
          _o2["text_source"] != "cache" and _seen)
    _st = json.loads(_sp.read_text(encoding="utf-8"))
    # 下一次：不是鎖定日 → 提示詞帶「前一兩次已經寫過」
    _st["at"] = (NOW - dt.timedelta(hours=13)).isoformat()
    _sp.write_text(json.dumps(_st, ensure_ascii=False), encoding="utf-8")
    _seen.clear()
    ft.build(_rs, False, _cfg, _sp, env={}, events={})
    check("build v2：提示詞不再要求「前一兩次寫過就換題」", _seen and "前一兩次主軸已經寫過" not in _seen[0][1])
finally:
    (ft.fetch_feed_headlines, ft.fetch_article_text, ft._call_ai, ft.build_catalog,
     ft.fedwatch_path, ft.fetch_atlanta_fedwatch, ft.build_topics) = _orig

# ---------------------------------------------------------------- ⑦ 補充
_main = "美國10年期公債殖利率升至5.25%，Pimco認為進一步升至6%確實可能，30年期觸及5.60%。"
check("⑦ 補充跟主軸同一件事（共用 5.25%、6%）→ 判定重複",
      ft._dup_with_main("Pimco 表示 10 年期殖利率觸及 5.25% 後，升至 6% 確實可能。", _main))
check("⑦ 不同事件不算重複",
      not ft._dup_with_main("聯準會會議紀錄顯示多位官員認為政策利率僅具輕微限制性，12 月升息機率 81.9%。", _main))
_src = (ROOT / "src/analysis/focus_today.py").read_text(encoding="utf-8")
check("⑦ 程式裡沒有「暫時無法取得」這類提示", "暫時無法取得" not in _src
      and "暫時無法取得" not in (ROOT / "src/pages/home.py").read_text(encoding="utf-8"))
_ft = {"chips": [{"id": "wti", "label": "WTI", "value": "$90", "delta": "+1", "dir": "up", "date": "10/9"},
                 {"id": "sofr", "label": "SOFR", "value": "4.3%", "delta": "0", "dir": "", "date": "10/9"}],
       "topic_map": {"wti": "oil", "sofr": "funding"},
       "topics": [{"id": "oil", "label": "油價", "text": "油價上漲。", "links": []}],
       "text": "主軸一段。", "layout": "main", "headline": "今天的標題", "rate_note": "長端上行壓力未退。",
       "text_source": "model-content", "links": [], "fedwatch": None}
_hh = home._focus_strip(_ft)
check("⑦ 首頁：粗體標題與對利率", '<p class="fs-headline">今天的標題</p>' in _hh
      and '<p class="fs-rate"><b>對利率</b>長端上行壓力未退。</p>' in _hh)
check("⑦ 首頁：寫失敗的主題（資金市場）在選單裡變灰、不能選",
      'value=\\"funding\\" disabled' in _hh and 'value=\\"oil\\">' in _hh)

# ---------------------------------------------------------------- ⑧ 設定
cfg = yaml.safe_load((ROOT / "config/focus.yaml").read_text(encoding="utf-8"))
specs = {s["id"]: s for s in ft.topic_specs(cfg)}


def _passes(tid, title):
    m = ft.gather_topic_material([specs[tid]], [{"title": title, "link": "https://x/" + title,
                                                  "source": "X", "at": ISO(1), "summary": ""}],
                                 global_exclude=cfg.get("exclude_keywords"), now=NOW,
                                 _fetch=lambda *a, **k: [], _body=lambda u: "內文" * 80)
    return tid in m


check("⑧ 匯率：「投資 10 億美元」不算匯率新聞", not _passes("fx", "輝達宣布投資10億美元擴建資料中心"))
check("⑧ 匯率：新台幣升值算", _passes("fx", "新台幣升值2角 外資匯入"))
check("⑧ 選舉：「為選情急轉彎！川普解禁俄柴油」不算", not _passes("election", "為選情急轉彎！川普解禁俄柴油 前大使開轟"))
check("⑧ 選舉：期中選舉民調算", _passes("election", "期中選舉民調：民主黨參議院選情拉近"))
check("⑧ 油價：純加薩停火新聞不算", not _passes("oil", "以色列與加薩達成停火協議"))
check("⑧ 油價：伊朗推升油價算", _passes("oil", "伊朗局勢升溫 國際油價大漲3%"))
check("⑧ 黃金：金礦股、婚嫁換金不算",
      not _passes("gold", "UBS Picks Top Gold Mining Stocks as Sector Faces Cost Pressures")
      and not _passes("gold", "黃金價格太貴 新人結婚流行舊金換新金"))
check("⑧ 黃金：金價上漲算", _passes("gold", "Gold rises over 1% as dollar weakens"))
check("⑧ 資金市場：拿掉 market stress", "market stress" not in specs["funding"]["keywords"])
check("⑧ AI 與半導體（第十九批改）：必含國際大廠或產業用詞，台股個股盤勢排除",
      "Nvidia" in specs["semi"]["require"] and "台積電" in specs["semi"]["require"]
      and "三大法人" in specs["semi"]["exclude"] and "AI" in specs["semi"]["keywords"])
check("⑧ AI 與半導體：台塑資料中心、法人買超不算；微軟資本支出算",
      not _passes("semi", "台塑攜手創曦資訊在麥寮建置AI資料中心 三大法人買超逾8.2萬張")
      and _passes("semi", "Microsoft boosts AI capex as data center spending climbs"))
_feeds = json.dumps(cfg["feeds"])
check("⑧ 主軸來源拿掉衛報、BBC、自由時報、FXStreet",
      not any(x in _feeds for x in ("theguardian", "bbci", "ltn.com.tw", "fxstreet")))
check("⑧ FXStreet 只給匯率與黃金", specs["fx"]["feeds"] and specs["gold"]["feeds"]
      and not specs["oil"]["feeds"])
_gn = [f for f in cfg["feeds"] if isinstance(f, str) and "news.google.com" in f]
check("⑧ 彭博、路透各拆成三組短搜尋（每組 ≤ 8 個詞）",
      sum("reuters.com" in f for f in _gn) == 3 and sum("bloomberg.com" in f for f in _gn) == 3
      and all(f.count("%20OR%20") <= 7 for f in _gn))
check("⑧ 主軸關鍵字：利率主線是主級，AI／油價／黃金是次級",
      "Fed" in cfg["keywords"] and "AI" not in cfg["keywords"]
      and {"AI", "油價", "黃金"} <= set(cfg["keywords_secondary"]))

# ---------------------------------------------------------------- ⑥b 鎖定時段、快取鍵
_tw = dt.timezone(dt.timedelta(hours=8))
_ev = {"cpi": ["2026-10-14"]}
check("⑥b CPI 當天鎖定", ft._lock_events(_ev, {}, dt.datetime(2026, 10, 14, 22, 45, tzinfo=_tw)) == ["cpi"])
check("⑥b 隔天早上 07:00 仍鎖定", ft._lock_events(_ev, {}, dt.datetime(2026, 10, 15, 7, 0, tzinfo=_tw)) == ["cpi"])
check("⑥b 隔天下午 16:00 不再鎖定", ft._lock_events(_ev, {}, dt.datetime(2026, 10, 15, 16, 0, tzinfo=_tw)) == [])
check("⑥b FOMC 從 config 的 fomc_dates 也認得",
      ft._lock_events({}, {"fomc_dates": ["2026-10-28"]}, dt.datetime(2026, 10, 29, 7, 0, tzinfo=_tw)) == ["fomc"])


# ⑦ 官方數據發布日：報導日期不是公布日（事故：「BLS 10/19 公布九月 CPI」，實際 10/14）
_cal = {"cpi": {"2026-08": "2026-09-11", "2026-09": "2026-10-14"}, "ppi": {"2026-09": "2026-10-15"},
        "pce": {"2026-09": "2026-10-29"}}
_rd = ft.release_dates(_cal)
_today = dt.date(2026, 10, 20)
_bad = "美國勞動統計局 10/19 公布九月消費者物價指數（CPI），月增率 0.6%。數據公布當天，標普 500 重挫。"
_iss = ft._release_date_issues(_bad, _rd, _today)
check("⑦a 抓到 CPI 公布日寫錯（10/19→10/14）", [(x["kind"], x["wrong"], x["right"]) for x in _iss]
      == [("cpi", "10/19", "10/14")], str(_iss))
check("⑦b 機械改正成官方日期", ft._fix_release_dates(_bad, _iss).startswith("美國勞動統計局 10/14 公布九月"))
check("⑦c 正確日期不報", ft._release_date_issues("9 月 CPI 已於 10/14 公布。", _rd, _today) == [])
check("⑦d 同句兩種數據，各自的官方日都放行",
      ft._release_date_issues("CPI 與 PPI 分別在 10/14、10/15 公布。", _rd, _today) == [])
check("⑦e 不是公布日的日期（官員發言）不報",
      ft._release_date_issues("華許 10/19 表示 CPI 顯示通膨仍需改善。", _rd, _today) == [])
_f = ft.release_facts(_cal, _today, {"cpi": ("2026-09", "整體月增 +0.6%")})
_blk = ft._facts_block(_f)
check("⑦f 權威區塊：已公布／將公布、數字只附在期別相同的那筆",
      "9 月 CPI：美東 10/14（三）已公布；整體月增 +0.6%" in _blk and "9 月 PCE：美東 10/29（四）將公布" in _blk
      and "8 月 CPI" not in _blk, _blk)

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
