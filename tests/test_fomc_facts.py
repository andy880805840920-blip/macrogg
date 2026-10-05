# 聯準會頁改版（2026-10 使用者定案）的回歸測試——不打網路：
#   · 三個分數全部拿掉，改成文件裡的事實（決議、投票、點陣圖、市場路徑）
#   · 政策方向＝決議，維持時看反對票方向（不加權）
#   · 靜默期、SEP／點陣圖、會議紀要量詞、委員名單、官員新聞、記者會只摘主席
#   · AI 只做中文說明，數字鎖擋掉捏造的數字
import sys
import re
import json
import pathlib
import datetime as dt
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.analysis import fomc_extra as fx            # noqa: E402
from src.analysis import fomc_text as ft             # noqa: E402
from src import fomc_source as fs                    # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過 " if cond else "失敗 "), name, ("— " + str(detail)[:200]) if detail else "")
    ok = ok and bool(cond)


# ---- ① 決議解析 ----
d1 = fx.parse_decision("The Committee decided to raise the target range for the federal funds "
                       "rate by 1/4 percentage point to 3-3/4 to 4 percent, in support of ...")
check("① 升息一碼＋新區間", d1 == {"action": "hike", "move_bp": 25, "lower": 3.75, "upper": 4.0}, d1)
d2 = fx.parse_decision("The Committee decided to maintain the target range for the federal "
                       "funds rate at 3‑1/2 to 3‑3/4 percent.")
check("① 不斷行連字號（U+2011）也讀得到", d2["lower"] == 3.5 and d2["upper"] == 3.75
      and d2["action"] == "hold" and d2["move_bp"] == 0, d2)
d3 = fx.parse_decision("the Committee decided to lower the target range for the federal funds "
                       "rate by 1/2 percentage point to 4-1/4 to 4-1/2 percent")
check("① 降息兩碼", fx.move_label(d3["action"], d3["move_bp"]) == "降息兩碼", d3)

# ---- ② 政策方向：只看決議與反對票 ----
v_hawk = {"stated_support": 9, "stated_dissent": 3, "dissents": [
    {"name": "Beth M. Hammack", "direction": "hike"}, {"name": "Neel Kashkari", "direction": "hike"},
    {"name": "Lorie K. Logan", "direction": "hike"}]}
dirn, lab = fx.policy_direction({"action": "hold", "move_bp": 0}, v_hawk)
check("② 維持＋3 票主張升息 → 偏升息", dirn == "hawkish" and lab == "維持不變，3 票主張升息", lab)
dirn, lab = fx.policy_direction({"action": "hike", "move_bp": 25},
                                {"stated_support": 12, "stated_dissent": 0, "dissents": []})
check("② 升息一碼＋全體一致", dirn == "hawkish" and lab == "升息一碼，全體一致", lab)
dirn, _ = fx.policy_direction({"action": "hold", "move_bp": 0},
                              {"stated_support": 12, "stated_dissent": 0, "dissents": []})
check("② 維持＋一致 → 中性", dirn == "neutral")
vs = fx.vote_summary(v_hawk)
check("② 票數與名單", vs["text"] == "9:3，3 票主張升息（Hammack、Kashkari、Logan）", vs["text"])

# ---- ③ 反對方向的寫法 ----
check("③ preferred no change → 維持",
      fs._direction("who preferred no change to the target range for the federal funds rate") == "hold")
check("③ 支持利率但反對資產負債表 → balance_sheet", fs._direction(
    "who supported no change for the federal funds target range but preferred to continue the "
    "current pace of decline in securities holdings") == "balance_sheet")
check("③ 支持維持但反對寬鬆傾向 → no_easing_bias", fs._direction(
    "who supported maintaining the target range for the federal funds rate but did not support "
    "inclusion of an easing bias in the statement at this time") == "no_easing_bias")
vs2 = fx.vote_summary({"stated_support": 8, "stated_dissent": 4, "dissents": [
    {"name": "Stephen I. Miran", "direction": "cut"},
    {"name": "Beth M. Hammack", "direction": "no_easing_bias"}]})
check("③ 其他事項的反對票照實寫出", "1 票反對聲明加入寬鬆傾向（Hammack）" in vs2["text"], vs2["text"])

# ---- ④ 靜默期 ----
s, e = fx.blackout(dt.date(2026, 10, 27), dt.date(2026, 10, 28))
check("④ 10/27–28 → 10/17 起、10/29 止", (s, e) == (dt.date(2026, 10, 17), dt.date(2026, 10, 29)), (s, e))
s, e = fx.blackout(dt.date(2025, 12, 9), dt.date(2025, 12, 10))
check("④ 2025-12-09 開會 → 11/29 起", s == dt.date(2025, 11, 29), s)
nm = fx.next_meeting_info([(dt.date(2026, 10, 27), dt.date(2026, 10, 28)),
                           (dt.date(2026, 12, 8), dt.date(2026, 12, 9))], dt.date(2026, 10, 20))
check("④ 靜默期中的狀態", nm["blackout_status"] == "in" and "靜默期中" in nm["blackout_text"], nm)
nm = fx.next_meeting_info([(dt.date(2026, 10, 27), dt.date(2026, 10, 28))], dt.date(2026, 10, 5))
check("④ 靜默期前的倒數", nm["blackout_text"] == "靜默期 10/17 起（12 天後）" and nm["days"] == 23, nm)

# ---- ⑤ 行事曆：紀要公布日、表決紀錄不能當成會議 ----
cal = ("<h4>2026 FOMC Meetings</h4> July 28-29 Statement Minutes: PDF | HTML "
       "(Released August 19, 2026) August 22 (notation vote) September 15-16* "
       "October 27-28 Note: A two-day meeting is scheduled for January 25-26, 2028.")
src = fs.FomcSource.__new__(fs.FomcSource)
src._cal, src.failed = cal, []
sp = src.calendar_spans()
check("⑤ 只剩真正的會議", [(a.isoformat(), b.isoformat()) for a, b in sp] == [
    ("2026-07-28", "2026-07-29"), ("2026-09-15", "2026-09-16"), ("2026-10-27", "2026-10-28")], sp)

# ---- ⑥ SEP／點陣圖 ----
SEP_HTML = """<h4>Table 1. Economic projections</h4><table><thead>
<tr><th>Variable</th><th colspan=5>Median</th><th colspan=5>Central</th><th colspan=5>Range</th></tr>
<tr>""" + "".join(f"<th>{y}</th>" for y in ["2026", "2027", "2028", "2029", "Longer run"] * 3) + """</tr>
</thead><tbody>
<tr><th>Unemployment rate</th>""" + "".join(f"<td>{x}</td>" for x in
    ["4.1", "4.1", "4.1", "4.1", "4.2"] + ["a"] * 10) + """</tr>
<tr><th>June projection</th>""" + "".join(f"<td>{x}</td>" for x in
    ["4.3", "4.3", "4.2", "&nbsp;", "4.2"] + ["a"] * 10) + """</tr>
<tr><th>Core PCE inflation<sup>4</sup></th>""" + "".join(f"<td>{x}</td>" for x in
    ["3.4", "2.5", "2.2", "2.0", "&nbsp;"] + ["a"] * 10) + """</tr>
<tr><th>Federal funds rate</th>""" + "".join(f"<td>{x}</td>" for x in
    ["4.1", "4.1", "3.9", "3.6", "3.2"] + ["a"] * 10) + """</tr>
<tr><th>June projection</th>""" + "".join(f"<td>{x}</td>" for x in
    ["3.8", "3.6", "3.4", "&nbsp;", "3.1"] + ["a"] * 10) + """</tr>
</tbody></table>
<h4>Figure 2. dots</h4><table><thead><tr><th>Midpoint</th><th>2026</th><th>2027</th></tr></thead>
<tbody><tr><th>4.375</th><td>4</td><td>8</td></tr><tr><th>4.125</th><td>12</td><td>6</td></tr>
<tr><th>3.875</th><td>2</td><td>&nbsp;</td></tr><tr><th>3.625</th><td>&nbsp;</td><td>3</td></tr>
<tr><th>3.125</th><td>&nbsp;</td><td>1</td></tr></tbody></table>"""
sep = fx.parse_sep(SEP_HTML, "2026-09-16")
check("⑥ 表 1 中位數與前一季", sep and sep["vars"]["ffr"]["median"][0] == 4.1
      and sep["vars"]["ffr"]["prev"][0] == 3.8 and sep["prev_label"] == "June", sep and sep["vars"]["ffr"])
check("⑥ 註腳上標不影響變數辨識", sep and sep["vars"]["core_pce"]["median"][1] == 2.5)
dv = fx.dot_views(sep, 0, 3.875)
check("⑥ 點陣圖：16 高、2 持平、精確中位數 4.125",
      (dv["up"], dv["same"], dv["down"], dv["median_exact"]) == (16, 2, 0, 4.125), dv)

# ---- ⑦ 會議紀要量詞 ----
MIN_HTML = ("<p>Staff Review of the Economic Situation: the staff said many things about it.</p>"
            "<p>Participants' Views on Current Conditions and the Economic Outlook "
            "Participants acknowledged that inflation remained elevated. Most participants "
            "anticipated that inflation would step down. A few participants highlighted credit "
            "risks in the AI sector and leverage.</p>"
            "<p>Many participants assessed that policy tightening would likely be necessary if "
            "inflation did not decline. Most participants commented on balance sheet policy.</p>"
            "<p>Committee Policy Actions In support of the Committee's goals, nine members agreed "
            "to maintain the target range.</p>")
mn = fx.parse_minutes(MIN_HTML)
rows = {r["text"][:20]: (r["level"], r["topic"]) for r in mn["rows"]}
check("⑦ 不加量詞＝普遍", rows.get("Participants acknowl") == ("普遍", "通膨"), rows)
check("⑦ Many＋policy → 許多／政策路徑", rows.get("Many participants as") == ("許多", "政策路徑"), rows)
check("⑦ balance sheet policy 歸資產負債表", rows.get("Most participants co") == ("多數", "資產負債表"), rows)
check("⑦ 決議段（Committee Policy Actions）不讀", not any("nine members" in r["text"] for r in mn["rows"]))
check("⑦ 幕僚報告段不讀", not any("staff" in r["text"].lower() for r in mn["rows"]))
grp = fx.minutes_by_topic(mn["rows"])
check("⑦ 政策路徑排第一", grp and grp[0][0] == "政策路徑", [g[0] for g in grp])

# ---- ⑧ 委員名單與分層 ----
ROSTER = ("<h4>2026 Committee Members</h4><ul>"
          + "".join(f"<li><a>{n}</a>, {a}</li>" for n, a in [
              ("Kevin Warsh", "Board of Governors, Chairman"), ("John C. Williams", "New York, Vice Chair"),
              ("Michael S. Barr", "Board of Governors"), ("Michelle W. Bowman", "Board of Governors"),
              ("Lisa D. Cook", "Board of Governors"), ("Beth M. Hammack", "Cleveland"),
              ("Philip N. Jefferson", "Board of Governors"), ("Neel Kashkari", "Minneapolis"),
              ("Lorie K. Logan", "Dallas"), ("Anna Paulson", "Philadelphia"),
              ("Jerome H. Powell", "Board of Governors"), ("Christopher J. Waller", "Board of Governors")])
          + "</ul><h4>Alternate Members</h4><ul><li><a>Sushmita Shukla</a>, First Vice President, "
            "New York</li><li><a>Cheryl Venable</a>, Interim President, Atlanta</li></ul>")
ro = fx.parse_roster(ROSTER)
bt = fx.parse_board_titles("Kevin Warsh, Chairman Philip N. Jefferson, Vice Chair Michelle W. Bowman, "
                           "Vice Chair for Supervision Board of Governors Members, 1914-Present "
                           "Governor Barr, Chair and Oversight Governor")
check("⑧ 理事職稱只讀名單段", bt == {"Warsh": "Chairman", "Jefferson": "Vice Chair",
                               "Bowman": "Vice Chair for Supervision"}, bt)
docs = [{"date": "2026-07-29", "vote": v_hawk}]
offs = fx.build_officials(ro, bt, docs, dt.date(2026, 10, 5))
tiers = {o["surname"]: (o["tier"], o["title"]) for o in offs}
check("⑧ 主席第一層、兩位副主席第二層", tiers["Warsh"] == (1, "主席")
      and tiers["Williams"][0] == 2 and tiers["Jefferson"] == (2, "理事會副主席"), tiers)
check("⑧ 候補委員第四層、職稱正確", tiers["Shukla"] == (4, "紐約聯儲第一副總裁")
      and tiers["Venable"] == (4, "亞特蘭大聯儲代理總裁"), tiers)
lg = next(o for o in offs if o["surname"] == "Logan")
check("⑧ 只標已表態的事實（反對票）", lg["dissent_tag"] == "近 12 個月反對：1 次主張升息"
      and lg["lean"] == "hawkish", lg)

# ---- ⑨ 記者會：只摘主席 ----
PRESSER = ("Page 1 of 9 September 16, 2026 Chairman Warsh’s Press Conference FINAL "
           "CHAIRMAN WARSH. Good day. Inflation remains elevated and this Committee will deliver "
           "price stability. And, with that, I’ll take a few of your questions. "
           "MICHELLE SMITH. Richard. "
           "RICHARD ESCOBEDO. Are interest rates now at a level that you would describe as "
           "restrictive or not, and are you focused on the labor market now? "
           "CHAIRMAN WARSH. We remain focused on bringing inflation down to 2 percent.")
op, qa = ft.split_presser(PRESSER)
check("⑨ 以說話者切開場（不靠結尾句）", op.startswith("Good day") and "RICHARD" not in op, op[:80])
ct = ft.chair_text(PRESSER)
check("⑨ 主席文字不含記者提問", "Are interest rates" not in ct and "focused on bringing" in ct)
sm = ft.summarise_presser(PRESSER)
check("⑨ 提問則數不算主持人點名", sm["questions"] == 1, sm)
fo = ft.detect_focus("Inflation remains elevated.", {}, ct)
check("⑨ 記者問「focused on the labor market」不算就業表態",
      not any("勞動市場為優先" in e for e in fo["evidence"]), fo["evidence"])
check("⑨ 依據逐條附原句", any(it["quote"] for it in fo["items"]), fo["items"])

# ---- ⑩ 市場路徑 vs 點陣圖 ----
fw = {"date": "2026-10-05", "r0": 3.877, "meetings": [
    {"date": "2026-10-28", "end": 3.93, "move_bp": 5.3, "outcomes": [(0, .79), (25, .21)]},
    {"date": "2026-12-09", "end": 4.127, "move_bp": 19.7, "outcomes": [(25, .79), (0, .21)]}]}
mv = fx.market_vs_dots(fw, sep, 3.875)
check("⑩ 年底一致 → 中性", mv["lean"] == "neutral" and abs(mv["gap_bp"]) < 1, mv)
fw2 = dict(fw, meetings=[dict(fw["meetings"][0]), dict(fw["meetings"][1], end=3.90)])
mv2 = fx.market_vs_dots(fw2, sep, 3.875)
check("⑩ 市場比點陣圖低一碼 → 偏降息、文字講清楚", mv2["lean"] == "dovish"
      and "低約 0.9 碼" in mv2["text"], mv2.get("text"))
check("⑩ 沒有期貨就不比", fx.market_vs_dots(None, sep, 3.875) == {})

# ---- ⑪ 轉向條件 ----
sc = fx.shift_conditions({"focus": "inflation"}, {"label": "黏著不降"}, 4.2, sep)
check("⑪ 三個條件、失業率 4.2>4.1 打勾", len(sc) == 3 and sc[1]["met"] and not sc[0]["met"], sc)

# ---- ⑫ 官員新聞 ----
RSS = ("<rss><item><title>Fed's Logan calls for more rate hikes - Reuters</title><source>Reuters"
       "</source><pubDate>Thu, 01 Oct 2026 10:00:00 GMT</pubDate><link>u1</link></item>"
       "<item><title>Silver Price Today: $66 After a 3.5% Waller Rally - FinanceFeeds</title>"
       "<source>FinanceFeeds</source><pubDate>Tue, 29 Sep 2026 10:00:00 GMT</pubDate></item>"
       "<item><title>Something about Dallas weather</title><source>X</source>"
       "<pubDate>Tue, 29 Sep 2026 10:00:00 GMT</pubDate></item></rss>")
nl = fx.parse_news_rss(RSS, "Logan")
check("⑫ 只收標題含姓氏、去掉來源尾巴", len(nl) == 1 and nl[0]["title"] == "Fed's Logan calls for more rate hikes"
      and nl[0]["policy"], nl)
nw = fx.parse_news_rss(RSS, "Waller")
check("⑫ 「Waller 行情」不算談政策", nw and not nw[0]["policy"], nw)

# ---- ⑬ AI 說明：數字鎖＋快取 ----
payload = {"d0": {"task": "說明", "old": "maintain at 3-1/2", "new": "raise by 1/4 to 3-3/4 to 4"},
           "m0": {"task": "翻譯", "text": "Many participants assessed that tightening was needed."}}
calls = []


def fake(text, system):
    calls.append(1)
    return json.dumps({"d0": "由維持改為升息一碼至 3-3/4 到 4", "m0": "許多與會者認為需要升息 50 個基點"},
                      ensure_ascii=False), ""


with tempfile.TemporaryDirectory() as tmp:
    cp = pathlib.Path(tmp) / "fomc_ai.json"
    notes = fx.ai_notes(payload, cp, offline=False, call=fake)
    check("⑬ 原文找不到的數字（50）整則丟掉", "d0" in notes and "m0" not in notes, notes)
    notes2 = fx.ai_notes(payload, cp, offline=False, call=fake)
    check("⑬ 素材沒變就用快取，不再呼叫", len(calls) == 1 and notes2 == notes, len(calls))
    check("⑬ 離線且沒有快取 → 空", fx.ai_notes({"x": {"text": "a"}}, pathlib.Path(tmp) / "n.json",
                                              offline=True) == {})

# ---- ⑭ 整頁：沒有任何分數字樣 ----
from src import build, fixtures_fomc               # noqa: E402
from src.pages import fomc as fp, home as hp        # noqa: E402
ex = fixtures_fomc.extras()
ctx = build.build_fomc_context(fixtures_fomc.build(), {"lower": 3.75, "upper": 4.0}, [], True,
                               upcoming=fixtures_fomc.upcoming(),
                               rates_series={"DFEDTARL": [{"date": "2026-08-01", "value": 3.5}],
                                             "DFEDTARU": [{"date": "2026-08-01", "value": 3.75}]},
                               extras=ex, ai_cache=None)
check("⑭ FRED 還停在會議前 → 用聲明本文的新區間", ctx["rate_range"] == "3.75–4.00%"
      and ctx["rate_src"] == "statement", (ctx["rate_range"], ctx["rate_src"]))
check("⑭ shift 給文字標籤", ctx["shift"]["decision_label"] == "升息一碼，全體一致"
      and ctx["shift"]["direction"] == "hawkish", ctx["shift"])
html = fp.fomc_body(ctx)
_body = html.split('id="howto"')[0]          # 判讀說明會交代「為什麼拿掉」，不算
for bad in ("客觀訊號分數", "措辭分數", "記者會措辭分數", "Objective Signal"):
    check(f"⑭ 頁面不再出現「{bad}」", bad not in _body)
for good in ('id="signals"', 'id="next"', 'id="people"', 'id="sep"', 'id="market"',
             'id="minutes"', 'id="presser"', 'id="focus"', 'id="trend"'):
    check(f"⑭ 新區塊 {good}", good in html)
check("⑭ 頂部決議卡寫日期", "FOMC 決議｜2026-09-16 會議" in html and "升息一碼至 3.75–4.00%" in html)
check("⑭ 前次會議也寫出來", "前次 7/29：維持不變，3 票主張升息" in html)
check("⑭ 離線沒有 AI 說明就不出現 AI 標籤內容", 'class="fx-ai"' not in html)
check("⑭ 4 月的寬鬆傾向反對票照實寫", "3 票反對聲明加入寬鬆傾向" in html)
check("⑮ 官員最新發言併進樹狀圖（不再有獨立區塊）",
      'id="speeches"' not in html and 'data-ot' in html and 'class="ot-panel"' in html)
_n_nodes = len(re.findall(r'class="ot-n[ "]', html))
check("⑮ 每位官員一個節點、一個面板，預設只展開主席",
      _n_nodes == len(ctx["officials"]) == html.count('class="od"')
      and html.count('aria-pressed="true"') == 1, (_n_nodes, len(ctx["officials"])))
check("⑮ FOMC 組成：事實卡＋輪值表", 'class="cfs"' in html and 'class="fx-rot"' in html)
check("⑮ SEP 五張小卡、表格收進看完整數字",
      html.count('class="sc"') == 5 and "看完整數字" in html, html.count('class="sc"'))
check("⑮ 輪值：2026 費城／克里夫蘭／達拉斯／明尼亞波利斯；2027 里奇蒙／芝加哥／亞特蘭大／舊金山",
      fx.rotation(2026) == ["Philadelphia", "Cleveland", "Dallas", "Minneapolis"]
      and fx.rotation(2027) == ["Richmond", "Chicago", "Atlanta", "San Francisco"])
_vh = fx.vote_history(
    [{"date": "2026-07-29", "vote": {"supporting": [], "stated_support": 9,
      "dissents": [{"name": "Beth M. Hammack", "direction": "hike"}]}},
     {"date": "2026-01-28", "vote": {"supporting": ["Lisa D. Cook"], "dissents": []}}],
    "Hammack", dt.date(2026, 10, 1), roster_year=2026,
    roster_voters={"Hammack", "Cook", "Warsh", "A", "B", "C", "D", "E", "F", "G", "H", "I"})
check("⑮ 逐場投票：只寫票數的新版聲明依名單推定、反對附方向、名單沒有＝未投票",
      [(v["date"], v["v"], v["label"]) for v in _vh]
      == [("2026-01-28", "none", "未投票"), ("2026-07-29", "against", "主張升息")], _vh)
_vh2 = fx.vote_history(
    [{"date": "2026-07-29", "vote": {"supporting": [], "stated_support": 11,
      "dissents": [{"name": "Beth M. Hammack", "direction": "hike"}]}}],
    "Cook", dt.date(2026, 10, 1), roster_year=2026,
    roster_voters={"Hammack", "Cook", "Warsh", "A", "B", "C", "D", "E", "F", "G", "H", "I"})
check("⑮ 票數＝名單人數才推定贊成（標 inferred）", _vh2 and _vh2[0]["v"] == "for"
      and _vh2[0].get("inferred"), _vh2)
check("⑭ 點陣圖 SVG 有 18 個點", html.count("<circle") == 18 + 18 + 17 + 17 + 18, html.count("<circle"))

if not ok:
    sys.exit(1)
print("\n全部通過")
