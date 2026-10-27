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
cl = ft.cluster_events(H, lambda h: 5.0 if "CPI" in h["title"] else 4.0)
check("② CPI 三則歸一組、排第一", len(cl[0]["items"]) >= 2 and "CPI" in cl[0]["lead"]["title"], cl[0])
check("② 事件分數＝領頭分＋1.5×min(來源−1,3)（v2.3）", cl[0]["score"] == 5.0 + 1.5 * min(cl[0]["sources"] - 1, 3), cl[0])
cl2 = ft.cluster_events([dict(H[0], source=f"S{i}", link=str(i)) for i in range(6)], lambda h: 1.0)
check("② 來源加成最多 +4.5（v2.3）", cl2[0]["score"] == 5.5, cl2[0]["score"])

# ③ 市場訊號：門檻、12 小時、油價照常算
now = dt.datetime(2026, 10, 14, 13, 0, tzinfo=U)
lv = {"d_today": 7, "ts": now - dt.timedelta(hours=1)}
sig = ft.market_signals(lv, {}, {"value": 103.5, "prev": 100.0}, {"value": 101.0, "prev": 100.0}, 12.0, now)
check("③ 10Y ±6bp、油 ±3%、FedWatch ±10pp 觸發；S&P 未過 1.5% 不觸發",
      set(sig) == {"rates", "oil", "policy"}, sig)
old = {"d_today": 9, "ts": now - dt.timedelta(hours=13)}
spx_old = {"value": 103.0, "prev": 100.0, "ts": now - dt.timedelta(hours=13)}
sig2 = ft.market_signals(old, {}, {"value": 104.0, "prev": 100.0}, spx_old, None, now)
check("③ 報價超過 12 小時 → 10Y、S&P 不加分；油價照常算", set(sig2) == {"oil"}, sig2)
check("③ 訊號加分 +3 給提到該市場的標題", ft.signal_bonus("Treasury yields jump", {"rates": "x"}) == 3.0
      and ft.signal_bonus("Apple earnings", {"rates": "x"}) == 0.0)

# ④ 鎖定撞期：看哪個比較常連到美債／殖利率；平手寫再融資
heads = [{"title": "CPI hotter than expected"}, {"title": "Treasury refunding: yields climb on bigger auctions"}]
check("④ 再融資標題連到殖利率較多 → 寫再融資", ft.resolve_locks(["cpi", "refunding"], heads) == (["refunding"], ["cpi"]))
heads2 = [{"title": "CPI lifts Treasury yields"}, {"title": "Quarterly refunding announcement unchanged"}]
check("④ CPI 連到殖利率較多 → 寫 CPI", ft.resolve_locks(["cpi", "refunding"], heads2)[0] == ["cpi"])
check("④ 平手 → 再融資", ft.resolve_locks(["cpi", "refunding"], [{"title": "x"}])[0] == ["refunding"])
check("④ 只有一個鎖定 → 不動", ft.resolve_locks(["fomc"], []) == (["fomc"], []))
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
check("⑥ 第一天沒有前值 → None", ft.fw_change(st, fw1, "2026-10-13") is None)
check("⑥ 隔天 +15pp", ft.fw_change(st, fw2, "2026-10-14") == 15.0, st)
fw3 = {"next": {"date": "2026-12-09", "outcomes": [(0, 0.9), (25, 0.1)]}}
check("⑥ 會議換了不比較", ft.fw_change(st, fw3, "2026-10-29") is None)

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
check("⑪ 提示詞版本已更新", ft.FOCUS_PROMPT_VERSION != "f14-official-release-dates")
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
check("⑬ 法國、歐洲央行、中國算外國（沒提美國）", ft.is_foreign("French Bond Rout Puts Crisis at Heart of ECB Succession")
      and not ft.is_foreign("European selloff drags US Treasuries"))
_p = {}
ft.rank_score({"title": "Euro zone GDP grows 0.3% in third quarter"}, ["GDP"], events=["gdp_adv"],
              lock_events=["gdp_adv"], parts=_p)
_p2 = {}
ft.rank_score({"title": "US GDP grows 2.8% in third quarter"}, ["GDP"], events=["gdp_adv"],
              lock_events=["gdp_adv"], parts=_p2)
check("⑬ 外國的同類數據只拿 +2，美國的拿鎖定 +8", _p.get("發布日") == 2.0 and "鎖定" not in _p and _p2.get("鎖定") == 8.0, (_p, _p2))
check("⑬ 分數明細的加總＝分數", abs(sum(_p2.values()) - ft.rank_score({"title": "US GDP grows 2.8% in third quarter"}, ["GDP"],
      events=["gdp_adv"], lock_events=["gdp_adv"])) < 1e-9)
ft.apply_selection_cfg({"selection": {"foreign_extra": ["Narnia"], "junk_patterns": ["Sponsored"]}})
check("⑬ config 的 selection 區可以追加清單", ft.is_foreign("Narnia central bank hikes") and ft.is_junk("Sponsored: buy gold"))
ft.apply_selection_cfg({})
# 油價訊號要有價格字樣
check("⑬ 油價訊號只給提到價格的標題", ft.signal_bonus("Oil prices jump 4% on supply cut", {"oil": "x"}) == 3.0
      and ft.signal_bonus("UAE Shuts More Beaches as It Deals with Oil Spill in Gulf", {"oil": "x"}) == 0.0)
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
_rel, _rest = ft.related_items(_mc, _oth, 3)
check("⑬ 相關報導只收標題主角相同的（Fed 會議那則收，黃金、銅不收）",
      [x["link"] for x in _rel] == ["f"] and len(_rest) == 2, [x["link"] for x in _rel])
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
check("⑬ 提示詞要求主席寫 Warsh", "一律寫英文 Warsh" in ft._NEWS_RULES and ft.FED_CHAIR == "Warsh")
# 分享圖：導言一行一行填、至少 3 行；對利率保留 10 年期對照
_ss = (ROOT / "src/pages/story_share.py").read_text(encoding="utf-8")
check("⑬ 分享圖導言至少 3 行、逐行遞減", "LEAD_MIN = 3" in _ss and "else if(lm > LEAD_MIN) lm--" in _ss)
check("⑬ 分享圖對利率保留「10 年期」那句", "function rateLines" in _ss and "rateLines(rateTxt" in _ss)

# ⑭ 2026-10-27 v2.3：概念組、舊文、主題熱度、兩個重點、PCE 各家預估
_p14 = {}
ft.rank_score({"title": "Analysis: Why a $2 trillion deficit and 5% Treasury yields are becoming a challenge"},
              ["deficit", "Treasury", "yields", "Fed"], parts=_p14)
check("⑭ 同一概念組只算一次（Treasury、yields＝美債）；deficit 在前半段 +2、美債在後半段 +1（原本 +6）",
      _p14.get("主題") == 3.0 and _p14.get("主角") == 2.0, _p14)
_pg, _pf = {}, {}
ft.rank_score({"title": "Gold rises as lower oil prices ease inflation fears ahead of Fed meeting - Reuters", "source": "Reuters"},
              ["inflation", "Fed", "Warsh"], secondary=["gold", "oil"], parts=_pg)
ft.rank_score({"title": "Fed Meeting Focus Turns to Warsh Messaging With December in Mind - Bloomberg.com", "source": "Bloomberg"},
              ["inflation", "Fed", "Warsh"], secondary=["gold", "oil"], parts=_pf)
check("⑭ 主角位置：Fed 是主角的標題贏過只在句尾提到 Fed 的金價新聞", sum(_pf.values()) > sum(_pg.values()), (_pf, _pg))
check("⑭ 亞洲算外國新聞", ft.is_foreign("Asia-focused banks face capital squeeze due to inflation, bond turbulence"))
_p14b = {}
ft.rank_score({"title": "Fed, CPI, payrolls and Treasury yields all in focus"}, ["Fed", "CPI", "payrolls", "Treasury"], parts=_p14b)
check("⑭ 最多算兩組（+4）", _p14b.get("主題") == 4.0, _p14b)
_cl = [{"lead": {"title": "Fed Meeting Focus Turns to Warsh Messaging"}, "score": 7.0, "items": []},
       {"lead": {"title": "Fed decision looms as gold steadies"}, "score": 7.0, "items": []},
       {"lead": {"title": "Fed officials weigh pause"}, "score": 7.0, "items": []},
       {"lead": {"title": "Asia-focused banks face capital squeeze"}, "score": 8.0, "items": []}]
_cl = ft.apply_theme_heat(_cl)
check("⑭ 主題熱度：三則主角都是聯準會 → 各 +1，排到亞洲銀行前面",
      _cl[0]["lead"]["title"].startswith("Fed") and _cl[0]["score"] == 8.0 and _cl[-1]["theme"] == 0, [(g["lead"]["title"][:20], g["score"]) for g in _cl])
_now14 = dt.datetime(2026, 10, 27, 4, 0, tzinfo=U)
_old = {"lead": {"title": "Analysis: deficit", "link": "https://www.cnbc.com/a", "at": "2026-10-26T18:33:00+00:00"},
        "items": [{"title": "Analysis: deficit", "link": "https://www.cnbc.com/a", "at": "2026-10-26T18:33:00+00:00"}],
        "score": 9.5}
_new = {"lead": {"title": "Fed news", "link": "https://www.cnbc.com/b", "at": "2026-10-27T02:00:00+00:00"},
        "items": [{"title": "Fed news", "link": "https://www.cnbc.com/b", "at": "2026-10-27T02:00:00+00:00"}],
        "score": 8.0}
_pubs = {"https://www.cnbc.com/a": dt.datetime(2026, 10, 15, 9, 30, tzinfo=U), "https://www.cnbc.com/b": dt.datetime(2026, 10, 27, 1, 0, tzinfo=U)}
_ms = ft.mark_stale([_old, _new], _now14, _pub=lambda u: _pubs.get(u))
check("⑭ RSS 寫 10/26 更新、原始發布 10/15 → 舊文：拿掉時效分、標記 stale", _old.get("stale") and _old["score"] == 7.5 and not _new.get("stale"), (_old.get("stale"), _old["score"]))
_html14 = '<html><head><script type="application/ld+json">{"datePublished":"2026-10-15T09:30:00+0000"}</script></head></html>'
check("⑭ 從網頁讀原始發布時間（datePublished）",
      ft.published_at("x", _get=lambda u: type("R", (), {"text": _html14, "raise_for_status": lambda s: None})()) == dt.datetime(2026, 10, 15, 9, 30, tzinfo=U))
# 重點二
_m = {"lead": {"title": "Fed Meeting Focus Turns to Warsh"}, "score": 10.0}
_o = [{"lead": {"title": "Fed officials weigh pause"}, "score": 9.0},
      {"lead": {"title": "Oil prices jump 4% on OPEC cut"}, "score": 8.0},
      {"lead": {"title": "Gold steadies"}, "score": 7.0}]
check("⑭ 重點二：主角不同（跳過另一則 Fed），挑油價", ft.pick_second(_m, _o)["lead"]["title"].startswith("Oil"))
check("⑭ 重點二分數不到重點一的一半 → 不硬湊", ft.pick_second(_m, [{"lead": {"title": "Oil prices jump"}, "score": 4.0}]) is None)
check("⑭ 撞期被降級的鎖定事件優先放重點二",
      ft.pick_second({"lead": {"title": "Treasury refunding: bigger auctions"}, "score": 20.0},
                     [{"lead": {"title": "Oil prices jump"}, "score": 15.0}, {"lead": {"title": "CPI rises 0.4%"}, "score": 3.0}],
                     demoted=["cpi"])["lead"]["title"].startswith("CPI"))
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
check("⑭ PCE：標題是 PPI／CPI 評論文也收（10/15，比公布早兩週）",
      _F.is_preview("pce", _it, _rel, _st14) and not _F.is_preview("pce", _it, _rel))
check("⑭ CPI 不受影響：評論文不收", not _F.is_preview("cpi", _it, _rel, None))
check("⑭ PCE 那一期提早 20 天建立", "ahead = 20 if key == \"pce\" else 10" in (ROOT / "src/analysis/forecasts.py").read_text(encoding="utf-8"))

# ⑮ 2026-10-27 v2.4：轉載搜尋、主軸只能用指定報導、兩段長度、標題不寫媒體名
_n15 = dt.datetime(2026, 10, 27, 12, 30, tzinfo=U)
_orig = {"title": "Bond investors are thinking less about the Fed and more about AI, deficits - Reuters",
         "link": "https://news.google.com/rss/articles/x", "source": "Reuters", "at": "2026-10-27T10:00:00+00:00"}
_pool = [{"title": "Analysis-Bond investors are thinking less about the Fed and more about AI, deficits",
          "link": "https://finance.yahoo.com/news/bond-investors-1.html", "source": "Yahoo Finance", "at": "2026-10-27T10:30:00+00:00"},
         {"title": "Gold steadies", "link": "https://finance.yahoo.com/news/gold.html", "at": "2026-10-27T10:00:00+00:00"}]
_body15 = "Bond investors are increasingly focused on AI spending and US deficits rather than the Fed, as yields stay high." * 3
_c = ft.find_copy(_orig, _pool, _n15, _text=lambda u: _body15, _pub=lambda u: None)
check("⑮ 在新聞池找到同一篇的轉載（去掉 Analysis- 前綴比對）", _c and _c["link"].endswith("bond-investors-1.html")
      and _c["source"] == "Yahoo Finance（Reuters）" and _c["orig_title"].startswith("Bond investors"), _c)
check("⑮ 轉載內文沒有原標題的名字或數字 → 不採用",
      ft.find_copy(_orig, _pool, _n15, _text=lambda u: "Unrelated text about sports. " * 10, _pub=lambda u: None) is None)
check("⑮ 轉載頁原始發布超過 48 小時 → 不採用",
      ft.find_copy(_orig, _pool, _n15, _text=lambda u: _body15, _pub=lambda u: dt.datetime(2026, 10, 20, tzinfo=U)) is None)
_far = [dict(_pool[0], at="2026-10-25T10:00:00+00:00")]
check("⑮ 轉載與原文發布時間相差超過 24 小時 → 不採用", ft.find_copy(_orig, _far, _n15, _text=lambda u: _body15, _pub=lambda u: None) is None)
check("⑮ 參考報導保留原文標題（主題補充比對重複用）", ft._link_of(_c).get("orig_title", "").startswith("Bond investors"))
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
                             ["Fed"], {}, caps=[250, 80, 80], mins=[120, 40, 40], two_points=True, point_ids=([2], [1]), p1_thin=True)
finally:
    ft._call_ai = _o15b
check("⑮ 重點一只有標題（50 字以上）、重點二有內文 → 不因長度不均重寫", _r15b and _r15b["points"] == 2
      and not any("兩段長度差太多" in x or "重點一只有" in x for x in _seen15b[1:]), _seen15b[1:][:1])

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
