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
check("② 事件分數＝領頭分＋min(來源−1,3)", cl[0]["score"] == 5.0 + min(cl[0]["sources"] - 1, 3), cl[0])
cl2 = ft.cluster_events([dict(H[0], source=f"S{i}", link=str(i)) for i in range(6)], lambda h: 1.0)
check("② 來源加成最多 +3", cl2[0]["score"] == 4.0, cl2[0]["score"])

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

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
