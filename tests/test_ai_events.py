"""AI 大事（2026-10-29）＋首頁兩張小卡＋今日主軸收合。"""
import sys, re, pathlib, json, tempfile, datetime as dt
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import clock                                    # noqa: E402
from src.analysis import ai_events as A                 # noqa: E402
from src.pages import ai_events as P, home, election     # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過  " if cond else "失敗  ") + name + (f" — {detail}" if detail and not cond else ""))
    ok &= bool(cond)


_n0, _t0 = clock.now, clock.today
T = dt.datetime(2026, 10, 29, 9, 0, tzinfo=clock.TAIPEI)
clock.now, clock.today = (lambda: T), (lambda: T.date())


def item(title, src, day):
    d = dt.date(2026, 10, day)
    return (f"<item><title>{title} - {src}</title><link>https://n/{abs(hash(title))}</link>"
            f"<pubDate>{d.strftime('%a, %d %b %Y')} 10:00:00 GMT</pubDate><source>{src}</source></item>")


RSS = {"Alphabet": item("Alphabet capex hits $51.4 billion as cloud doubles", "Reuters", 28)
       + item("Alphabet stock: 3 reasons to buy", "Motley Fool", 28) + item("Old Alphabet news", "Reuters", 1),
       "Anthropic": item("Anthropic files for IPO on Nasdaq", "Bloomberg", 26)}
SEC = json.dumps({"filings": {"recent": {"form": ["S-1", "DRS/A", "DRS"], "filingDate": ["2026-10-26", "2026-10-09", "2026-06-01"]}}})


def fake_get(url):
    if "data.sec.gov" in url:
        return SEC
    for k, v in RSS.items():
        if k in url:
            return f"<rss>{v}</rss>"
    return "<rss></rss>"


calls = []


def fake_ai(src, sy):
    calls.append(sy[:10])
    d = json.loads(src)
    if "headlines" in d:
        evs = []
        for h in d["headlines"]:
            if "capex" in h["title"]:
                evs.append({"type": "資本支出", "zh": "Q3 資本支出 514 億美元", "ids": [h["id"]]})
            if "IPO" in h["title"]:
                evs.append({"type": "融資／IPO", "zh": "遞交上市申請", "ids": [h["id"]]})
            if "buy" in h["title"]:
                evs.append({"type": "股價", "zh": "分析師看好", "ids": [h["id"]]})     # 不在五類 → 丟掉
        return json.dumps({"events": evs})
    return d["company"] + " 的事件偏向推升公司債供給。"


# ① 標題解析
heads = A.parse_rss("<rss>" + RSS["Alphabet"] + "</rss>", ["Alphabet"], dt.date(2026, 10, 15))
check("① 只留窗內、含公司名的標題；主要媒體在前", [h["source"] for h in heads] == ["Reuters", "Motley Fool"], heads)
# ② IPO 進度
st = A.ipo_stage([{"form": "S-1", "date": "2026-10-26"}, {"form": "S-1/A", "date": "2026-11-05"}, {"form": "S-1/A", "date": "2026-11-12"}])
check("② IPO：遞交 S-1、修正版取最近一次、未掛牌＝進行中", st["steps"][0]["date"] == "2026-10-26"
      and st["steps"][1]["date"] == "2026-11-12" and st["active"] and not st["listed"], st)
check("② 掛牌（8-A12B）後就不算進行中", not A.ipo_stage([{"form": "S-1", "date": "2026-10-26"}, {"form": "8-A12B", "date": "2026-12-01"}])["active"])
# ③ 整個流程
tmp = pathlib.Path(tempfile.mkdtemp()) / "ai.json"
r = A.build({}, tmp, False, _get=fake_get, call=fake_ai)
cos = {e["co"]: e for e in r["events"]}
check("③ 五類以外（股價評論）丟掉；Alphabet、Anthropic 各一則", set(cos) == {"Alphabet", "Anthropic"} and len(r["events"]) == 2, r["events"])
check("③ 每則附原文連結", all(e["links"] and e["links"][0]["url"] for e in r["events"]))
check("③ 有事件的公司寫「對市場的影響」", set(r["impact"]) == {"Alphabet", "Anthropic"})
check("③ IPO 進度從 SEC 申報來", r["ipo"]["active"] and r["ipo"]["steps"][0]["date"] == "2026-10-26")
n = len(calls)
r2 = A.build({}, tmp, False, _get=fake_get, call=fake_ai)
check("③ 第二次執行：看過的標題不再送 AI、事件沒變不重寫影響", len(calls) == n and len(r2["events"]) == 2, (n, len(calls)))
check("③ 離線：沿用存檔、不呼叫", A.build({}, tmp, True, _get=fake_get, call=fake_ai)["events"] and len(calls) == n)
# ④ 畫面
tile, panel = P.ai_tile(r)
check("④ AI 小卡：近 14 天 N 則、最新一則", "AI 大事" in tile and "近 14 天 2 則" in tile and "最新：Alphabet" in tile)
check("④ 視窗：十家公司小卡、一次只開一家、IPO 進度、依時間看全部",
      len(re.findall(r'class="ai-tile(?: on)?"', panel)) == 10 and panel.count('class="ai-pane"') == 10 and panel.count('" hidden><div class="ai-pane-h">') == 9
      and "進行中・Anthropic IPO" in panel and "依時間看全部" in panel)
check("④ 沒有事件的公司寫「無近期事件」、近 3 天的事件加小圓點", "無近期事件" in panel and 'class="ai-new"' in panel)
e = {"election_date": "2026-11-03", "days_to": 5, "date": "2026-10-29",
     "house": {"dem": .925, "rep": .075, "hist": [], "url": "u"}, "senate": {"dem": .675, "rep": .325, "hist": [], "url": "u"}}
et, ep = election.election_tile(e)
check("④ 選舉小卡：還有幾天、兩院機率（一行）；視窗內是原本的選舉卡", "還有 5 天" in et and "民主黨 眾 <b>93%</b>・參 <b>68%</b>" in et and "el-card" in ep)
duo = home._duo({"_election": e, "_ai_events": r})
check("④ 首頁兩張小卡並排、內容藏在視窗用的面板裡", duo.count('class="duo-card"') == 2 and duo.count('class="duo-panel"') == 2
      and "duo-modal" in duo)
check("④ 都沒有資料時不出現", home._duo({}) == "")
# ⑤ 今日主軸收合
f = {"yields": [], "links": [], "fedwatch": None, "layout": "main", "headline": "標題", "rate_note": "r",
     "text": "主軸\n補充", "text_source": "model-content", "topics": [], "chips": []}
h = home._focus_strip(f)
check("⑤ 今日主軸：標題下露出四行、再接「展開全文」", 'class="fs-tog"' in h and '<div class="fs-more fs-clip">' in h
      and h.index("標題") < h.index("fs-more") < h.index('class="fs-tog"'))
check("⑤ 沒有標題時不收合", 'class="fs-tog"' not in home._focus_strip(dict(f, headline="")))

# ⑥ 2026-10-29 晚：一張卡中間一條線、時間軸、來源獨立一行、視窗放回頁面主體、今日結論收合
check("⑥ 依時間看全部：時間軸列（每天第一則標 day＋日期）、類型選單在標題列", 'class="ai-r day"' in panel
      and '<label class="ai-sel"><select' in panel and panel.index('ai-sel') < panel.index('</summary>', panel.index('ai-all')) and 'class="ai-s"' in panel)
check("⑥ 公司面板的來源獨立一行", '<span class="ai-s">' in panel.split('class="ai-panes"')[1].split('ai-all')[0])
check("⑥ 視窗掛在頁面主體內（兩院左右並排的規則才套得到）", "closest('.viz-root')" in home._DUO_JS)
_css = (ROOT / "src/site.py").read_text(encoding="utf-8")
check("⑥ 兩張小卡合成一張卡、中間一條線", ".duo-grid .duo-card+.duo-card{border-left:1px solid var(--grid)}" in _css)
check("⑥ 今日結論改成六宮格小卡，點進去直接展開", 'class="home-hero hm-hero hm-open hm-in' in (ROOT / "src/pages/home.py").read_text(encoding="utf-8")
      and ".hm-hero:not(.hm-open) .hm-layer" in _css)

# ⑦ 2026-10-30：金額換算檢查與同一件事合併（微軟 250 億美元發債被收成三則、一則寫成 25 億）
check("⑦ billion 換算錯 10 倍：自動改正", A.fix_amount("微軟發行25億美元債券", ["Microsoft Issues $25 Billion in New Bonds"])
      == "微軟發行250億美元債券")
check("⑦ 寫對的不動；bln、trillion 也認得；兆美元", A.fix_amount("SpaceX與xAI簽署400億美元租賃", ["SpaceX agrees USD 40 bln lease"])
      == "SpaceX與xAI簽署400億美元租賃"
      and A.fix_amount("籌資約30億美元，估值125億美元", ["$30 billion round at $1.25 trillion valuation"])
      == "籌資約300億美元，估值1.25 兆美元")
check("⑦ 標題沒有的金額拿掉、重複的「美元美元」清掉", A.fix_amount("某公司發行100億美元債券", ["Company sells bonds"]) == "某公司發行債券"
      and A.fix_amount("計畫發行至少250億美元美元債券", ["At Least $25 Billion"]) == "計畫發行至少250億美元債券")
_ms = [{"id": "a", "co": "微軟", "type": "發債", "date": "2026-10-29", "zh": "微軟啟動自2017年以來首次美元高級債券發行。",
        "links": [{"url": "u1", "title": "Microsoft Kicks Off First US High-Grade Bond Sale Since 2017"}]},
       {"id": "b", "co": "微軟", "type": "發債", "date": "2026-10-29", "zh": "微軟計畫發行至少250億美元債券。",
        "links": [{"url": "u2", "title": "Microsoft Looks to Raise at Least $25 Billion"}]},
       {"id": "c", "co": "微軟", "type": "發債", "date": "2026-10-29", "zh": "微軟發行250億美元債券，用於AI基礎設施建設。",
        "links": [{"url": "u3", "title": "Microsoft Issues $25 Billion"}]},
       {"id": "d", "co": "Nvidia", "type": "算力合約", "date": "2026-10-28", "zh": "Nvidia與Meta深化AI基礎設施合作，投資30億美元。",
        "links": [{"url": "u4"}]},
       {"id": "e", "co": "Nvidia", "type": "算力合約", "date": "2026-10-28", "zh": "Nvidia與Hugging Face達成129億美元交易。",
        "links": [{"url": "u5"}]}]
_mm = A.merge_events(_ms)
_m1 = [e for e in _mm if e["co"] == "微軟"]
check("⑦ 微軟同一筆發債三則併成一則：留有金額、資訊最多的那句，來源合併",
      len(_m1) == 1 and "250億美元" in _m1[0]["zh"] and {l["url"] for l in _m1[0]["links"]} == {"u1", "u2", "u3"}, _m1)
check("⑦ 同一天、同類型但不同的兩件事不合併", len([e for e in _mm if e["co"] == "Nvidia"]) == 2)
_m2 = A.merge_events([dict(_ms[1], date="2026-10-28"), dict(_ms[2], date="2026-10-30", id="c2")])
check("⑦ 延續報導（3 天內同一個金額）只更新那一則、日期取最新", len(_m2) == 1 and _m2[0]["date"] == "2026-10-30")
check("⑦ 提示詞寫明 billion 怎麼換算", "$25 billion＝250 億美元" in A.EVENT_SYSTEM)

clock.now, clock.today = _n0, _t0
print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
