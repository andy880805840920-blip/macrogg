"""2026-10-25 今日主軸 v2：選舉過濾、事件分組、市場訊號、鎖定撞期、事件日期、週報、存檔。
規格：Google 文件「MacroGG 今日主軸規則 v2（2026-10-25 定案）」。"""
import sys, json, pathlib, tempfile, datetime as dt
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.analysis import focus_today as ft      # noqa: E402
from src.pages import home as _home              # noqa: E402

ok = True
U = dt.timezone.utc
TPE = dt.timezone(dt.timedelta(hours=8))


def check(name, cond, detail=""):
    global ok
    print(("通過  " if cond else "失敗  ") + name + (f" — {detail}" if detail and not cond else ""))
    ok &= bool(cond)


# ① 美國期中選舉：要有美國字樣＋市場／政策字樣
check("① 美國選情＋市場 → 收", ft.election_ok("US midterms: investors brace for gridlock as Treasury yields rise"))
check("① 中文：期中選舉＋美債 → 收", ft.election_ok("美國期中選舉倒數，美債殖利率走高"))
check("① 沒有市場影響 → 不收", not ft.election_ok("Republicans hold rally ahead of midterms in Ohio"))
check("① 非美國選舉 → 不收", not ft.election_ok("日本參議院選情緊繃，日圓與股市走弱"))
check("① 不是選舉的標題不受影響", ft.election_ok("Fed holds rates steady"))
check("① 單字 House／Senate 不算選舉詞", not ft._ELECTION_RE.search("House passes spending bill; Senate next"))
check("① election_filter 濾掉不合格的",
      [x["title"] for x in ft.election_filter([{"title": "Midterm campaign ads flood TV"},
                                               {"title": "CPI rises 0.3%"}])] == ["CPI rises 0.3%"])

# ② 事件分組：同一件事（含中英文）歸一組；分數＝最高分＋min(來源數−1, 3)
H = [
    {"title": "US CPI rises 0.4% in September, core at 3.1%", "source": "Reuters", "link": "r1"},
    {"title": "美國 9 月 CPI 月增 0.4%，核心通膨 3.1%", "source": "鉅亨網", "link": "c1"},
    {"title": "Consumer prices up 0.4% as inflation stays sticky", "source": "CNBC", "link": "n1"},
    {"title": "Oil jumps 4% after OPEC surprise cut", "source": "Bloomberg", "link": "b1"},
]
check("② 中英文共享數字＋專有名詞 → 同一件事", ft.same_story(H[0]["title"], H[1]["title"]))
check("② 不同事件不歸一組", not ft.same_story(H[0]["title"], H[3]["title"]))

# ③ 市場訊號：門檻、12 小時、油價照常算
now = dt.datetime(2026, 10, 14, 13, 0, tzinfo=U)
lv = {"d_today": 7, "ts": now - dt.timedelta(hours=1)}
old = {"d_today": 9, "ts": now - dt.timedelta(hours=13)}
spx_old = {"value": 103.0, "prev": 100.0, "ts": now - dt.timedelta(hours=13)}

# ④ 鎖定撞期：看哪個比較常連到美債／殖利率；平手寫再融資
heads = [{"title": "CPI hotter than expected"}, {"title": "Treasury refunding: yields climb on bigger auctions"}]
heads2 = [{"title": "CPI lifts Treasury yields"}, {"title": "Quarterly refunding announcement unchanged"}]
check("④ 主席證詞：兩則以上標題提到才算",
      ft.testimony_today([{"title": "Warsh testimony to Senate Banking"}, {"title": "華許國會聽證：通膨仍高"}])
      and not ft.testimony_today([{"title": "Warsh testimony to Senate Banking"}]))
check("④ 鎖定清單含證詞、再融資、GDP 初值；PPI 等只加分",
      {"testimony", "refunding", "gdp_adv"} <= set(ft.LOCK_EVENTS) and "ppi" not in ft.LOCK_EVENTS)

# ⑤ 事件日期推導
ev = ft.derive_events({"gdp": ["2026-10-29", "2026-11-25"]}, {"fomc_dates": ["2026-10-28"]}, ["2026-11-04"])
check("⑤ GDP 初值＝1/4/7/10 月那次", ev["gdp_adv"] == ["2026-10-29"], ev["gdp_adv"])
check("⑤ 會議紀要＝會後 21 天", ev["fomc_minutes"] == ["2026-11-18"], ev["fomc_minutes"])
check("⑤ 再融資日期帶入", ev["refunding"] == ["2026-11-04"])
d = dt.date(2026, 10, 14)
evc = {"cpi": [d.isoformat()]}
check("⑤ 數據日 20:00（台北）＝尚未公布（預告）",
      not ft.released_yet("cpi", evc, {}, dt.datetime(2026, 10, 14, 20, 0, tzinfo=TPE)))
check("⑤ 數據日 22:00（台北）＝已公布（結果）",
      ft.released_yet("cpi", evc, {}, dt.datetime(2026, 10, 14, 22, 0, tzinfo=TPE)))
check("⑤ 不是今天的事件一律算已公布", ft.released_yet("cpi", {"cpi": ["2026-10-13"]}, {},
                                                dt.datetime(2026, 10, 14, 7, 0, tzinfo=TPE)))
check("⑤ 星期天早上＝週報；星期天下午、星期六都不是",
      ft.is_weekly(dt.datetime(2026, 10, 25, 7, 0, tzinfo=TPE))
      and not ft.is_weekly(dt.datetime(2026, 10, 25, 13, 0, tzinfo=TPE))
      and not ft.is_weekly(dt.datetime(2026, 10, 24, 7, 0, tzinfo=TPE)))
check("⑤ 時間窗 18 → 30 → 60 小時", ft.WINDOW_STEPS == (18, 30, 60))

# ⑥ FedWatch 變化（下一次會議「有動作」的機率，百分點）
st = {}
fw1 = {"next": {"date": "2026-10-28", "outcomes": [(0, 0.7), (25, 0.3)]}}
fw2 = {"next": {"date": "2026-10-28", "outcomes": [(0, 0.55), (25, 0.45)]}}
fw3 = {"next": {"date": "2026-12-09", "outcomes": [(0, 0.9), (25, 0.1)]}}

# ⑦ 選題紀錄只留 30 筆
p = pathlib.Path(tempfile.mkdtemp()) / "focus_log.json"
for i in range(35):
    ft.write_focus_log(p, {"i": i, "at": dt.datetime(2026, 10, 1, tzinfo=U)})
rows = json.loads(p.read_text(encoding="utf-8"))
check("⑦ focus_log 只留最近 30 筆", len(rows) == 30 and rows[0]["i"] == 5 and rows[-1]["i"] == 34)

# ⑧ 週報：下週行事曆＋本週存檔，產出主軸＋下週重點
today = dt.date(2026, 10, 25)
cal = ft.weekly_calendar({"cpi": ["2026-10-28"], "employment": ["2026-11-06"], "gdp": ["2026-10-29"]},
                         {"fomc_dates": ["2026-10-28"]}, today)
check("⑧ 下週行事曆只列明天起 7 天", [x[0] for x in cal] == ["2026-10-28", "2026-10-28", "2026-10-29"]
      and any("FOMC" in x[1] for x in cal), cal)
_seen = []
_good = ("【標題】聯準會按兵不動但釋出鷹派訊號\n"
         "【主軸】" + "本週聯準會官員密集發言，強調通膨仍高於目標，暗示利率將維持高檔更久，市場重新評估降息時點。" * 3 + "\n"
         "【對利率】鷹派發言偏向推升短端利率，10 年期本週 +10bp，市場已在反映。\n"
         "【補充】\n10/28 FOMC 利率決策，市場關注會後聲明對通膨的措辭。\n"
         "10/29 GDP 初值公布，市場關注消費支出的力道。\n"
         "【來源】1")


def _ca(src, system, env=None, **kw):
    _seen.append((src, system, kw.get("model")))
    return _good, ""


_orig = ft._call_ai
ft._call_ai = _ca
try:
    _q = []
    rows10 = [{"date": f"2026-10-{d:02d}", "value": v} for d, v in
              zip(range(12, 25), [4.0, 4.01, 4.02, 4.03, 4.04, 4.06, 4.08, 4.1, 4.12, 4.14, 4.16, 4.18, 4.2])]
    rs = {"DGS10": rows10, "DGS2": rows10}
    arch = {"2026-10-20": {"headline": "CPI 高於預期", "text": "九月 CPI 月增 0.4%", "at": "x"},
            "2026-10-23": {"headline": "財政部擴大標售", "text": "財政部宣布擴大十年期標售", "at": "x"}}
    res, err = ft.write_weekly({}, ["Fed"], [], rs, None, {"cpi": ["2026-10-28"], "gdp": ["2026-10-29"]},
                               {"fomc_dates": ["2026-10-28"]}, {},
                               dt.datetime(2026, 10, 25, 7, 0, tzinfo=TPE), model=ft.FOCUS_MODEL,
                               archive=arch,
                               _fetch=lambda kws, hours=30: _q.append((kws, hours)) or [{"title": "Fed officials signal higher for longer",
                                                              "link": "https://reuters/x", "source": "Reuters",
                                                              "at": dt.datetime.now(U).isoformat()}])
    check("⑧ 週報產出（主軸＋2 則下週重點）", res and len(res["text"].splitlines()) == 3, err)
    check("⑧ 週報用 Sonnet", _seen and _seen[0][2] == ft.FOCUS_MODEL)
    check("⑧ 材料含本週存檔與下週行事曆", _seen and "10/20 主軸" in _seen[0][0] and "下週官方行事曆" in _seen[0][0])
    check("⑧ 數字鎖仍有效：下週重點的日期都來自行事曆", res and "10/29" in res["text"])
    check("⑧ 提示詞禁止預估值", _seen and "不要寫任何預估值" in _seen[0][1])
    check("⑧ Google News 查近 7 天（when:7d）", _q and all(k.endswith(" when:7d") for k in _q[0][0]) and _q[0][1] >= 168, _q)
finally:
    ft._call_ai = _orig

# ⑨ 首頁：週報的 kicker 與「下週重點」標籤；過去的週報在日期面板標「本週回顧」
f = {"yields": [], "links": [], "fedwatch": None, "layout": "main", "weekly": True,
     "headline": "聯準會按兵不動", "rate_note": "x", "text": "回顧一¶回顧二\n10/28 FOMC\n10/29 GDP",
     "text_source": "model-weekly", "topics": [], "chips": []}
h = _home._focus_strip(f)
check("⑨ 週報 kicker＝本週回顧與下週重點", "本週回顧與下週重點" in h and "今日主軸</div>" not in h)
check("⑨ 補充標「下週重點」", h.count("下週重點</span>") == 2)
h2 = _home._focus_strip(dict(f, weekly=False))
check("⑨ 平日照舊「今日主軸」", "今日主軸" in h2 and "下週重點</span>" not in h2)

# ⑩ 模型分工
from src.analysis import polish as _pl, forecasts as _fc   # noqa: E402
check("⑩ 主軸＝Sonnet、主題補充與潤稿＝Haiku",
      ft.FOCUS_MODEL.startswith("claude-sonnet") and _pl.PROVIDERS["anthropic"]["model"].startswith("claude-haiku"))
check("⑩ 預測表讀圖 Sonnet 優先", _fc.VISION_MODEL["anthropic"].startswith("claude-sonnet"))
src = (ROOT / "src/analysis/fomc_extra.py").read_text(encoding="utf-8")
check("⑩ FOMC 筆記用 FOCUS_MODEL", "model=FOCUS_MODEL" in src)

# ⑪ 主題補充快取鍵不吃主軸文字（主軸每次重寫，新聞沒變就沿用主題補充）
src2 = (ROOT / "src/analysis/focus_today.py").read_text(encoding="utf-8")
check("⑪ 主題補充快取鍵改用主軸來源標題", '_stance + "|" + _mk + "|"' in src2)
check("⑪ 不再有「前一兩次寫過就換題」", "前一兩次主軸已經寫過" not in src2)

# ⑫ 2026-10-26：數字鎖放寬、月份對照、FOMC 日程進材料、全文 6 篇、盧比算外國
check("⑫ 英文月份算數字：December → 12 月不算編造",
      ft._missing_digits("聯準會 12 月會議受關注", "Fed Meeting Focus Turns to Warsh With December in Mind") == [])
check("⑫ Dec. 縮寫也認得", ft._missing_digits("12 月", "Fed eyes Dec. hike") == [])
check("⑫ 真的沒出處的數字照樣列出", ft._missing_digits("殖利率升到 9.99%", "Yields rise") == ["9.99"])
_fb = ft._fomc_block({"fomc_dates": ["2026-10-28", "2026-12-09", "2027-03-17"]}, dt.date(2026, 10, 26))
check("⑫ 近 45 天的 FOMC 會議日放進材料", "10/28" in _fb and "12/9" in _fb and "3/17" not in _fb, _fb)
check("⑫ 全文篇數恢復 6 篇", ft.BODY_SLOTS == 6)
check("⑫ 盧比、澳洲央行算外國新聞（扣分）",
      ft._FOREIGN.search("Oil prices, Fed policy decision to steer rupee") and ft._FOREIGN.search("RBA's Hunter says"))

_calls = []
_bad = ("【標題】聯準會本週會議聚焦華許的訊息傳遞\n【主軸】" + "聯準會本週召開會議，市場關注主席華許如何傳達政策訊息，並評估後續升息的可能。" * 3
        + "，殖利率升到 9.99%。\n【對利率】偏向推升短端利率，取決於會後聲明。\n【補充】\n金價走穩，市場等待聯準會會議結果。\n銅價延續跌勢，人工智慧類股走弱拖累。\n【來源】1")


def _ca12(src, system, env=None, **kw):
    _calls.append(src)
    return _bad, ""


_o12 = ft._call_ai
ft._call_ai = _ca12
try:
    _r12, _e12 = ft._generate_main("【報導1】Fed meeting focus turns to Warsh", "sys", {},
                                   caps=[250, 80, 80], mins=[200, 40, 40])
finally:
    ft._call_ai = _o12
check("⑫ 數字鎖不再一票否決：第一次帶原因重寫", len(_calls) == 2 and "9.99" in _calls[1], len(_calls))
check("⑫ 重寫後仍有 → 照樣採用（不退回列標題）", _r12 is not None and _e12 == "", _e12)

# ⑬ 2026-10-27 v2.2：選題與寫作修正
# 多字關鍵字整段比對
check("⑬ 多字關鍵字整段比對：Wall Street 不會因為 street 命中", ft._kw_hit("Wall Street", "Stocks slump on Wall Street")
      and not ft._kw_hit("Wall Street", "Street protests in Paris") and ft._kw_words(["debt ceiling"]) == ["debt ceiling"])
# 轉載重複保留權重高的來源
_feed = lambda items: type("R", (), {"content": ("<rss><channel>" + "".join(
    f"<item><title>{t}</title><link>{l}</link><pubDate>{dt.datetime.now(U).strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate></item>"
    for t, l in items) + "</channel></rss>").encode(), "raise_for_status": lambda self: None})()
_urls = {"https://tw.news.yahoo.com/rss/finance": [("Fed holds rates as inflation cools", "https://tw.news.yahoo.com/a")],
         "https://news.google.com/rss/search?q=site:reuters.com": [("Fed holds rates as inflation cools", "https://news.google.com/x")]}
_hs = ft.fetch_feed_headlines(list(_urls), ["Fed"], hours=30, _get=lambda u: _feed(_urls[u]))
check("⑬ 同一則轉載只留一則、保留權重高的路透", len(_hs) == 1 and _hs[0]["link"] == "https://news.google.com/x",
      [(h["source"], h["link"]) for h in _hs])
# 雜訊頁
check("⑬ 股價頁、影片頁、個股清單直接排除",
      ft.is_junk("Chumporn Palm Oil Industry PCL (CPI.BK) | Stock Price & Latest News - Reuters")
      and ft.is_junk("Watch Fed Looks Set to Pause After September Rate Hike - Bloomberg.com")
      and ft.is_junk("The Fed, Inflation, Verizon, Boeing, Alphabet, and Many More Stocks to Watch")
      and not ft.is_junk("Fed Meeting Focus Turns to Warsh Messaging With December in Mind"))
# 外國新聞清單擴充；鎖定 +8 不給外國
_p = {}
_p2 = {}
ft.apply_selection_cfg({"selection": {"foreign_extra": ["Narnia"], "junk_patterns": ["Sponsored"]}})
ft.apply_selection_cfg({})
# 油價訊號要有價格字樣
# 證詞預告
check("⑬ 「下週將赴國會作證」不算今天的證詞",
      not ft.testimony_today([{"title": "Warsh will testify to Senate Banking next week"}, {"title": "華許下週將赴國會聽證"}])
      and ft.testimony_today([{"title": "Warsh testifies to Senate Banking committee"}, {"title": "華許國會聽證：通膨仍高"}]))
# 事件日期
check("⑬ 事件提示寫明美東日期（隔天早上那次寫前一天）",
      ft.event_day("cpi", {"cpi": ["2026-10-14"]}, {}, dt.datetime(2026, 10, 15, 7, 0, tzinfo=TPE)) == "10/14")
# 同主題相關報導
_mc = {"lead": {"title": "美債殖利率回落！Fed暫停升息理由受考驗 Warsh如何說服市場？", "link": "m"}, "items": []}
_oth = [{"lead": {"title": "Gold Steadies After Weekly Drop as Focus Shifts to Fed Meeting", "link": "g"}},
        {"lead": {"title": "Fed Meeting Focus Turns to Warsh Messaging With December in Mind", "link": "f"}},
        {"lead": {"title": "Copper Extends Drop as AI Stocks Weigh Ahead of Fed Meeting", "link": "c"}}]
check("⑬ 主軸材料最多 4 則、只有標題時下限 120 字", ft.MAIN_MAX_ITEMS == 4 and ft.HEADLINE_ONLY_MIN == 120)
# 寫作：媒體名、指示用語、對利率長度、補充則數
check("⑬ 「CNBC 報導指出，」（中間有空白）會被刪掉", ft._strip_media("CNBC 報導指出，10 年期殖利率升至 5.1%") == "10 年期殖利率升至 5.1%")
check("⑬ 「主軸這件事」會被拿掉", ft._strip_leak("主軸這件事對利率方向不明確：暫停升息") == "方向不明確：暫停升息")
_calls13 = []
_long_rate = "Warsh 暗示暫停升息，偏向壓低短端利率預期" + "，但若市場質疑聯準會抗通膨決心則可能推升長端殖利率" * 5 + "。"
_out13 = ("【標題】聯準會會議前市場聚焦 Warsh 的政策訊息\n【主軸】" + "聯準會會議在即，市場關注主席 Warsh 如何說明暫停升息的理由與後續路徑。" * 4
          + "\n【對利率】" + _long_rate + "\n【補充】\n金價走穩，市場等待聯準會會議結果，投資人觀望氣氛濃厚。\n【來源】1")
ft._call_ai, _o13 = (lambda s, sy, env=None, **k: (_calls13.append(s) or (_out13, ""))), ft._call_ai
try:
    _r13, _ = ft._generate_main("【報導1】Fed meeting focus turns to Warsh", "sys", {}, caps=[250, 80, 80], mins=[200, 40, 40])
finally:
    ft._call_ai = _o13
check("⑬ 對利率超過 90 字、補充少於 2 則 → 帶原因重寫一次",
      len(_calls13) == 2 and "超過 90 字" in _calls13[1] and "補充只有 1 則" in _calls13[1], _calls13[-1][-200:])
check("⑬ 重寫後仍有 → 照樣採用", _r13 is not None)
# Warsh 一律英文
check("⑬ Warsh 一律用英文、跟中文之間留空白",
      ft.normalize_names("聯準會主席華許表示，沃許與Kevin Warsh是同一人") == "聯準會主席 Warsh 表示，Warsh 與 Warsh 是同一人")
# 分享圖：導言一行一行填、至少 3 行；對利率保留 10 年期對照
_ss = (ROOT / "src/pages/story_share.py").read_text(encoding="utf-8")
check("⑬ 分享圖導言至少 3 行、逐行遞減", "LEAD_MIN = 3" in _ss and "else if(lm > LEAD_MIN) lm--" in _ss)
check("⑬ 分享圖對利率保留「10 年期」那句", "function rateLines" in _ss and "rateLines(rateTxt" in _ss)

# ⑭ 2026-10-27 v2.3：概念組、舊文、主題熱度、兩個重點、PCE 各家預估
_p14 = {}
_pg, _pf = {}, {}
_p14b = {}
_cl = [{"lead": {"title": "Fed Meeting Focus Turns to Warsh Messaging"}, "score": 7.0, "items": []},
       {"lead": {"title": "Fed decision looms as gold steadies"}, "score": 7.0, "items": []},
       {"lead": {"title": "Fed officials weigh pause"}, "score": 7.0, "items": []},
       {"lead": {"title": "Asia-focused banks face capital squeeze"}, "score": 8.0, "items": []}]
_now14 = dt.datetime(2026, 10, 27, 4, 0, tzinfo=U)
_old = {"lead": {"title": "Analysis: deficit", "link": "https://www.cnbc.com/a", "at": "2026-10-26T18:33:00+00:00"},
        "items": [{"title": "Analysis: deficit", "link": "https://www.cnbc.com/a", "at": "2026-10-26T18:33:00+00:00"}],
        "score": 9.5}
_new = {"lead": {"title": "Fed news", "link": "https://www.cnbc.com/b", "at": "2026-10-27T02:00:00+00:00"},
        "items": [{"title": "Fed news", "link": "https://www.cnbc.com/b", "at": "2026-10-27T02:00:00+00:00"}],
        "score": 8.0}
_pubs = {"https://www.cnbc.com/a": dt.datetime(2026, 10, 15, 9, 30, tzinfo=U), "https://www.cnbc.com/b": dt.datetime(2026, 10, 27, 1, 0, tzinfo=U)}
_html14 = '<html><head><script type="application/ld+json">{"datePublished":"2026-10-15T09:30:00+0000"}</script></head></html>'
check("⑭ 從網頁讀原始發布時間（datePublished）",
      ft.published_at("x", _get=lambda u: type("R", (), {"text": _html14, "raise_for_status": lambda s: None})()) == dt.datetime(2026, 10, 15, 9, 30, tzinfo=U))
# 重點二
_m = {"lead": {"title": "Fed Meeting Focus Turns to Warsh"}, "score": 10.0}
_o = [{"lead": {"title": "Fed officials weigh pause"}, "score": 9.0},
      {"lead": {"title": "Oil prices jump 4% on OPEC cut"}, "score": 8.0},
      {"lead": {"title": "Gold steadies"}, "score": 7.0}]
_sys2 = ft._two_point_system(ft._FOCUS_CONTENT_SYSTEM_A)
check("⑭ 兩個重點的提示詞替換全部成功", all(b in _sys2 for a, b in ft._TWO_POINT_SWAPS) and "{min}" in _sys2)
_r14 = ft._parse_main_output("【標題】t\n【主軸】\n甲事件。\n乙事件。\n【對利率】r\n【補充】\na\nb\n【來源】1,4｜6", 2)
check("⑭ 來源分重點：1,4｜6", _r14["ids"] == [1, 4] and _r14.get("ids2") == [6] and len(_r14["main"]) == 2, _r14)
_calls14 = []
_two = ("【標題】聯準會會議前市場聚焦 Warsh 的政策訊息\n【主軸】\n" + "聯準會會議在即，市場關注主席 Warsh 如何說明暫停升息的理由與後續路徑。" * 2
        + "\n" + "油價因石油輸出國組織減產消息上漲，能源類股走強，投資人評估通膨壓力是否再起。" * 2
        + "\n【對利率】Warsh 暗示暫停升息，偏向壓低短端利率預期。\n【補充】\n金價走穩，市場等待聯準會會議結果，投資人觀望。\n銅價延續跌勢，人工智慧類股走弱拖累金屬需求。\n【來源】1｜2")
ft._call_ai, _o14 = (lambda s, sy, env=None, **k: (_calls14.append(sy) or (_two, ""))), ft._call_ai
try:
    _wr, _we = ft.write_main([{"title": "Fed meeting focus turns to Warsh", "body": "Fed Warsh meeting", "source": "Bloomberg", "link": "https://b/1"},
                              {"title": "Oil prices jump on OPEC cut", "body": "oil OPEC", "source": "Reuters", "link": "https://r/2"}],
                             [], ["Fed"], {}, caps=[250, 80, 80], mins=[200, 40, 40], two_points=True, point_ids=([1], [2]))
finally:
    ft._call_ai = _o14
check("⑭ 兩個重點：產出 points=2、來源標記重點一／重點二", _wr and _wr["points"] == 2
      and [x.get("point") for x in _wr["links"]] == [1, 2], (_we, _wr and _wr.get("links")))
check("⑭ 兩個重點用的提示詞", _calls14 and "剛好兩段" in _calls14[0])
_h14 = _home._focus_strip({"yields": [], "links": [dict(_wr["links"][0]), dict(_wr["links"][1])], "fedwatch": None,
                           "layout": "main", "points": 2, "headline": "h", "rate_note": "r",
                           "text": "甲事件。¶乙事件。\n補一。\n補二。", "text_source": "model-content", "topics": [], "chips": []})
check("⑭ 首頁：兩段直接呈現，主軸和參考報導都不標「重點一／重點二」（v2.4）",
      "重點一" not in _h14 and "重點二" not in _h14 and _h14.count('class="fs-main"') == 2)
from src.analysis import stories as _S
_sto = _S.build_story({"_focus": {"layout": "main", "points": 2, "text": "甲事件。¶乙事件。\n補一。", "headline": "h"}})
check("⑭ 分享圖導言只用重點一", _sto["paras"] == ["甲事件。"], _sto["paras"])
# PCE 各家預估
from src.analysis import forecasts as _F
_rel = dt.datetime(2026, 10, 29, 20, 30, tzinfo=TPE)
_st14 = _F.window_start({"key": "pce", "period": "2026-09"}, {"cpi|2026-09": {"date": "2026-10-14"}})
check("⑭ PCE 時間窗從同一期 CPI 公布開始", _st14 is not None and _st14.date() == dt.date(2026, 10, 14), _st14)
_it = {"title": "Post-PPI sell-side commentary: economists lift core estimates", "pub": dt.datetime(2026, 10, 15, 13, 48, tzinfo=U)}
check("⑭ PCE 那一期提早 20 天建立", "ahead = 20 if key == \"pce\" else 10" in (ROOT / "src/analysis/forecasts.py").read_text(encoding="utf-8"))

# ⑮ 2026-10-27 v2.4：轉載搜尋、主軸只能用指定報導、兩段長度、標題不寫媒體名
_n15 = dt.datetime(2026, 10, 27, 12, 30, tzinfo=U)
_orig = {"title": "Bond investors are thinking less about the Fed and more about AI, deficits - Reuters",
         "link": "https://news.google.com/rss/articles/x", "source": "Reuters", "at": "2026-10-27T10:00:00+00:00"}
_pool = [{"title": "Analysis-Bond investors are thinking less about the Fed and more about AI, deficits",
          "link": "https://finance.yahoo.com/news/bond-investors-1.html", "source": "Yahoo Finance", "at": "2026-10-27T10:30:00+00:00"},
         {"title": "Gold steadies", "link": "https://finance.yahoo.com/news/gold.html", "at": "2026-10-27T10:00:00+00:00"}]
_body15 = "Bond investors are increasingly focused on AI spending and US deficits rather than the Fed, as yields stay high." * 3
_far = [dict(_pool[0], at="2026-10-25T10:00:00+00:00")]
# 主軸只能用指定報導、兩段長度
_seen15 = []
_bad15 = ("【標題】市場押注 10/28 按兵不動、12 月升息機率逾七成\n【主軸】\n" + "調查顯示多數受訪者預期聯準會在會議維持利率，並預期之後升息，市場重新評估路徑。" * 4
          + "\n債券投資人關注焦點轉向 AI 與財政赤字。\n【對利率】偏向推升短端利率。\n【補充】\n甲事件發生了，細節是乙。\n丙事件發生了，細節是丁。\n【來源】3｜1")
ft._call_ai, _o15 = (lambda s, sy, env=None, **k: (_seen15.append(s) or (_bad15, ""))), ft._call_ai
try:
    _r15, _e15 = ft.write_main([{"title": "Bond investors AI deficits", "body": "Bond investors AI deficits " * 5, "source": "Yahoo Finance（Reuters）", "link": "https://y/1"},
                                {"title": "Japan inflation", "body": "Japan trend inflation " * 5, "source": "Reuters", "link": "https://y/2"},
                                {"title": "Fed rate hikes are coming, but not this week: CNBC survey", "body": "93% expect hold, 76% expect December hike " * 3, "source": "CNBC", "link": "https://c/3"}],
                               [], ["Fed"], {}, caps=[250, 80, 80], mins=[200, 40, 40], two_points=True, point_ids=([1], [2]))
finally:
    ft._call_ai = _o15
_w15 = _seen15[1] if len(_seen15) > 1 else ""
check("⑮ 主軸用了排名前兩名以外的報導（CNBC 問卷）→ 帶原因重寫", "主軸用了指定以外的報導（代號 1、3）" in _w15, _w15[-300:])
check("⑮ 兩段長度差太多 → 帶原因重寫", "兩段長度差太多" in _w15)
check("⑮ 標題的數字不是重點一的 → 帶原因重寫", "【標題】的數字" in _w15)
check("⑮ 重寫後仍不符 → 參考報導只列指定的報導", _r15 and [x["link"] for x in _r15["links"]] == ["https://y/1", "https://y/2"],
      _r15 and _r15["links"])
check("⑮ 標題開頭「CNBC 調查：」會被刪掉", ft._strip_media("CNBC 調查：93% 預期聯準會維持利率") == "93% 預期聯準會維持利率")
check("⑮ 每段至少 80 字、兩段相差不超過一倍；重點一只有標題時下限 50、不要求等長",
      ft.POINT_MIN == 80 and ft.POINT_RATIO == 2.0 and ft.POINT_MIN_THIN == 50)
_seen15b = []
_thin = ("【標題】債券投資人關注點轉向 AI 與財政赤字\n【主軸】\n債券投資人關注焦點從聯準會轉向人工智慧支出與財政赤字，認為高殖利率反映的是財政與科技投資需求，而非單純的利率政策路徑。\n"
         + "日本趨勢通膨指標升至三年高點，強化日本央行升息的理由，市場評估升息時點並調整日圓與日債部位，投資人關注後續數據。" * 2
         + "\n【對利率】偏向推升長端利率。\n【補充】\n甲事件發生了，細節是乙丙丁戊己庚辛。\n丙事件發生了，細節是丁戊己庚辛壬癸。\n【來源】2｜1")
ft._call_ai, _o15b = (lambda s, sy, env=None, **k: (_seen15b.append(s) or (_thin, ""))), ft._call_ai
try:
    _r15b, _ = ft.write_main([{"title": "Japan trend inflation index hits 3-year high", "body": "Japan trend inflation BOJ " * 5, "source": "Yahoo", "link": "https://y/2"}],
                             [{"title": "Bond investors are thinking less about the Fed and more about AI, deficits", "source": "Reuters", "link": "https://news.google.com/1"}],
                             ["Fed"], {}, caps=[250, 80, 80], mins=[120, 40, 40], two_points=True, point_ids=([2], [1]), thin=(True, False))
finally:
    ft._call_ai = _o15b
check("⑮ 重點一只有標題（50 字以上）、重點二有內文 → 不因長度不均重寫", _r15b and _r15b["points"] == 2
      and not any("兩段長度差太多" in x or "重點一只有" in x for x in _seen15b[1:]), _seen15b[1:][:1])

# ⑯ 2026-10-28：鎖定事件公布前不准寫成已有結果、媒體名中間夾字、人物簡介頁
_bad16 = ("【標題】聯準會 10/28 決議維持利率不變，官員對金融條件影響分歧\n【主軸】\n"
          "聯準會 10/28（美國時間）公布利率決策，決定維持利率不變。聯準會官員對金融環境緊縮程度的評估並未達成一致看法，這影響了後續政策路徑的判斷。"
          "¶市場關注聯準會接下來將進入觀望模式。路透另一篇報導指出，聯準會可能對利率政策採取等待觀察的態度，評估先前升息的累積效果，以及當前金融環境對經濟與通膨的實際影響。"
          "官員們需要更多時間觀察數據，才能決定是否需要進一步緊縮。\n【對利率】偏向壓低短端利率預期。\n【補充】\n金價走穩，市場等待聯準會會議結果，投資人觀望氣氛濃厚。\n"
          "銅價延續跌勢，人工智慧類股走弱拖累金屬需求，投資人觀望。\n【來源】1")
_seen16 = []
ft._call_ai, _o16 = (lambda s, sy, env=None, **k: (_seen16.append(s) or (_bad16, ""))), ft._call_ai
try:
    _r16, _e16 = ft.write_main([], [{"title": "The AI Fed Votes to Hold Interest Rates Steady", "source": "Bloomberg", "link": "https://news.google.com/1"},
                                    {"title": "Fed officials not aligned on weight of financial conditions", "source": "Reuters", "link": "https://news.google.com/2"},
                                    {"title": "Fed likely to go into wait-and-see mode on rates", "source": "Reuters", "link": "https://news.google.com/3"}],
                               ["Fed"], {}, caps=[250, 80, 80], mins=[120, 40, 40], mode="title", point_ids=([1, 2, 3], ()), preview="10/28")
finally:
    ft._call_ai = _o16
check("⑯ 10/28 晚上實例：FOMC 尚未公布卻寫「決議維持利率不變」→ 帶原因重寫", len(_seen16) == 2 and "事件尚未公布" in _seen16[1], _seen16[-1][-200:])
check("⑯ 重寫後仍有 → 刪掉那幾句、標題不用", _r16 and not ft._decided_hits(_r16["text"] + _r16["headline"], "10/28")
      and _r16["headline"] == "" and "決定維持" not in _r16["text"], _r16)
check("⑯ 「市場預期維持利率不變」「押注按兵不動」這類預期說法不受影響",
      ft._decided_hits("市場預期聯準會將維持利率不變。市場押注按兵不動的機率達 93%。", "10/28") == [])
check("⑯ 講過去的決議（9/16 升息一碼、先前已升息）不受影響",
      ft._decided_hits("聯準會 9/16 決議升息一碼後，市場關注本次會議。聯準會先前已升息一碼。", "10/28") == [])
check("⑯ 公布後（preview 空字串）不檢查", ft._decided_hits("") == [])
check("⑯ 「路透另一篇報導指出，」會被刪掉", ft._strip_media("路透另一篇報導指出，聯準會可能觀望。") == "聯準會可能觀望。")
check("⑯ 人物／公司簡介頁直接排除", ft.is_junk("John D Schipfer, Greenville Fed Financial Corp: Profile and Biography - Bloomberg"))

# ⑯b 重點只有標題 → 補同主題、有內文的報導當背景
_it16 = [{"title": "Fed officials not aligned on weight of financial conditions - Reuters", "link": "https://news.google.com/2"}]
_oth16 = [{"lead": {"title": "Gold steadies ahead of Fed", "link": "https://finance.yahoo.com/g"}, "items": [{"title": "Gold steadies ahead of Fed", "link": "https://finance.yahoo.com/g"}], "score": 9},
          {"lead": {"title": "Fed meeting preview: what to expect from Warsh", "link": "https://www.cnbc.com/f"}, "items": [{"title": "Fed meeting preview: what to expect from Warsh", "link": "https://www.cnbc.com/f"}], "score": 8},
          {"lead": {"title": "Fed decision looms - Bloomberg", "link": "https://news.google.com/9"}, "items": [{"title": "Fed decision looms - Bloomberg", "link": "https://news.google.com/9"}], "score": 7}]

# ⑰ 2026-10-28 v2.5 精簡版：計分 4 項＋熱度、鎖定直接指定重點一、材料一條規則、補充不重複
_N17 = dt.datetime(2026, 10, 28, 14, 0, tzinfo=U)
_at = lambda h: (_N17 - dt.timedelta(hours=h)).isoformat()   # noqa: E731
_KW = ["Fed", "inflation", "Treasury", "yields", "deficit"]
_p17 = {}
ft.score_title({"title": "The AI Fed Votes to Hold Interest Rates Steady - Bloomberg.com", "source": "Bloomberg", "at": _at(4)}, _KW, _N17, parts=_p17)
check("⑰ 計分只剩主角、時效、來源、外國：次級關鍵字（AI）不再加分", set(_p17) <= {"主角", "時效", "來源", "外國"}
      and _p17 == {"主角": 4.0, "時效": 2.0, "來源": 3.0}, _p17)
_pg = {}
ft.score_title({"title": "Gold rises as lower oil prices ease inflation fears ahead of Fed meeting - Reuters", "source": "Reuters", "at": _at(4)}, _KW, _N17, parts=_pg)
check("⑰ 只在標題後半段提到利率主線 → 主角 +1", _pg.get("主角") == 1.0, _pg)
_pu = {}
ft.score_title({"title": "UK Budget Tests Bond Markets as Fed, ECB and Oil Risks Loom - Bloomberg.com", "source": "Bloomberg", "at": _at(4)}, _KW, _N17, parts=_pu)
check("⑰ 主角是外國（英國預算）→ −3；後半段提到 Fed 不再豁免", _pu.get("外國") == -3.0, _pu)
check("⑰ 時效：12 小時內 +2、24 小時內 +1、更舊 0", ft._time_pts(5) == 2.0 and ft._time_pts(20) == 1.0 and ft._time_pts(30) == 0.0)
_hs17 = [{"title": "The AI Fed Votes to Hold Interest Rates Steady - Bloomberg.com", "source": "Bloomberg", "link": "https://news.google.com/a", "at": _at(4)},
         {"title": "Fed officials not aligned on weight of financial conditions - Reuters", "source": "Reuters", "link": "https://news.google.com/b", "at": _at(2)},
         {"title": "Fed likely to go into wait-and-see mode on rates - Reuters", "source": "Reuters", "link": "https://news.google.com/c", "at": _at(2)},
         {"title": "聯準會明升息？外媒調查：先按兵不動 12月機率高", "source": "Yahoo奇摩新聞", "link": "https://tw.news.yahoo.com/d", "at": _at(3)},
         {"title": "UK Budget Tests Bond Markets as Fed, ECB and Oil Risks Loom - Bloomberg.com", "source": "Bloomberg", "link": "https://news.google.com/e", "at": _at(4)},
         {"title": "Treasury yields edge higher before refunding announcement - CNBC", "source": "CNBC", "link": "https://www.cnbc.com/f", "at": _at(3)},
         {"title": "Oil prices jump 3% on supply worries - Reuters", "source": "Reuters", "link": "https://news.google.com/g", "at": _at(5)}]
_g17 = ft.group_events(_hs17, _KW + ["聯準會"], _N17)
_fed = [g for g in _g17 if "聯準會" in g["ents"]]
check("⑰ 熱度：主角都是 Fed 的不同媒體（彭博、路透、Yahoo）→ 各 +2", _fed and all(g["heat"] == 2 for g in _fed), [(g["lead"]["title"][:20], g["heat"], g["ents"]) for g in _g17])
_p1, _p2, _w17 = ft.choose_points(_g17, ["fomc"])
check("⑰ FOMC 鎖定日：重點一是 Fed 的事件；同分時有內文的（Yahoo）優先", "聯準會" in _p1["ents"] and _w17 == "鎖定事件 fomc", (_p1["lead"]["title"], _w17))
check("⑰ 重點二：主角不同、分數夠的（美債），不是英國預算", _p2 is not None and "Treasury" in _p2["lead"]["title"], _p2 and _p2["lead"]["title"])
_oth = [g for g in _g17 if g is not _p1 and g is not _p2]
_it1, _left, _bgl17 = ft.gather_items(_p1, _oth, 3)
check("⑰ 材料兩層：這件事本身在前；本身有內文就不補背景", _it1[0]["link"] == _p1["lead"]["link"]
      and (_bgl17 == set() if ft._has_body(_p1) else len(_bgl17) >= 1), ([x["title"][:20] for x in _it1], _bgl17))
check("⑰ 主角相同的事件全部從補充候選拿掉（補充不會再寫 Fed）", all("聯準會" not in g["ents"] for g in _left), [g["lead"]["title"][:20] for g in _left])
_p1b, _p2b, _ = ft.choose_points(_g17, ["fomc", "refunding"])
check("⑰ 兩個鎖定事件撞期：第二個直接當重點二", _p2b is not None and "refunding" in _p2b["lead"]["title"].lower())
_g17[0]["stale"] = "2026-10-15T09:30"
check("⑰ 舊文不能當重點", ft.choose_points(_g17, [])[0] is not _g17[0])
_st = {"lead": {"title": "Analysis: deficit", "link": "https://www.cnbc.com/z", "at": _at(5)},
       "items": [{"title": "Analysis: deficit", "link": "https://www.cnbc.com/z", "at": _at(5)}], "score": 9.0}
ft.mark_stale_v25([_st], _N17, _pub=lambda u: dt.datetime(2026, 10, 15, tzinfo=U))
check("⑰ 舊文：原始發布超過 48 小時 → 拿掉時效分", _st.get("stale") and _st["score"] == 7.0, _st)
# 補充不能用主軸的報導、不能跟主軸重複
_r17 = ft._parse_main_output("【標題】t\n【主軸】\n甲事件發生了。\n【對利率】r\n【補充】\n乙事件發生了，細節是丙。〔4〕\n丁事件發生了，細節是戊。〔1〕\n【來源】1", 2)
check("⑰ 補充最後的〔代號〕會被讀出並從正文拿掉", _r17["supp_ids"] == [[4], [1]] and not _r17["supp"][0].endswith("〕"), _r17)
check("⑰ 補充用了主軸的報導（代號 1）→ 判定重複", ft._supp_overlap(_r17, "甲事件發生了。", ([1], ())) == [2])
check("⑰ 提示要求補充標〔代號〕、不能用主軸用過的報導", "補充只能寫其他代號的事件" in (ROOT / "src/analysis/focus_today.py").read_text(encoding="utf-8"))
check("⑰ 拿掉的舊規則不存在了", not any(hasattr(ft, n) for n in ("market_signals", "rank_score", "find_copy", "body_backfill",
                                                                 "resolve_locks", "apply_theme_heat", "pick_second")))

# ⑱ 2026-10-28 漏洞修正：主角用關鍵字組辨識、外國形容詞、材料兩層、台指期排除
check("⑱ 主角用關鍵字組：S&P 500 開高（Fed 在後半段）→ 美股；Treasury 部位 → 美債",
      ft.topics_of("S&P 500, Nasdaq open higher as SK Hynix lifts chips; Fed in focus - Reuters") == {"美股"}
      and "美債" in ft.topics_of("US-Friendly Nations Slash Treasury Purchases by 60%, Led by Asia"))
check("⑱ 今晚 55 個認不出主角的例子，現在都認得出（抽查）",
      all(ft.topics_of(t) for t in ["Bloomberg Surveillance: Fed and Tech", "Bond Traders Bet on UK’s Newfound Resilience to Survive Budget",
                                    "US Hits Chinese Trailers With Tariffs to Aid Domestic Producers", "美債不再是「避風港」？野村看好混合資本公司債藏潛力"]))
_pa = {}
ft.score_title({"title": "Australian Inflation Exceeds Estimate Ahead of RBA Meeting - Bloomberg.com", "source": "Bloomberg"}, ["inflation"], None, parts=_pa)
check("⑱ 外國形容詞（Australian）也扣分", _pa.get("外國") == -3.0, _pa)
_gb = {"lead": {"title": "Fed officials not aligned - Reuters", "link": "https://news.google.com/a"},
       "items": [{"title": "Fed officials not aligned - Reuters", "link": "https://news.google.com/a"}], "ents": {"聯準會"}}
_ob = [{"lead": {"title": "投資人關注Fed決策", "link": "https://tw.news.yahoo.com/b"}, "items": [{"title": "投資人關注Fed決策", "link": "https://tw.news.yahoo.com/b"}], "ents": {"聯準會"}},
       {"lead": {"title": "Gold holds", "link": "https://news.google.com/g"}, "items": [{"title": "Gold holds", "link": "https://news.google.com/g"}], "ents": {"黃金"}}]
_ib, _lb, _bgb = ft.gather_items(_gb, _ob, 3)
check("⑱ 這件事本身只有標題 → 補一則同主題有內文的當背景；同主題事件不再當補充",
      [x["link"] for x in _ib] == ["https://news.google.com/a", "https://tw.news.yahoo.com/b"]
      and _bgb == {"https://tw.news.yahoo.com/b"} and [o["lead"]["title"] for o in _lb] == ["Gold holds"])
import yaml as _y
check("⑱ 主軸排除台指期、夜盤盤勢文", {"台指期", "夜盤"} <= set(_y.safe_load(open(ROOT / "config/focus.yaml", encoding="utf-8"))["exclude_keywords"]))

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
