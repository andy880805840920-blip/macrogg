"""
偷懶頁（/ask/）的判讀與內容測試。

判讀器只有一份（src/pages/ask_match.js，頁面內嵌、這裡用 node 跑同一份），
所以題庫測的就是使用者實際會遇到的結果。需要 node；沒有 node 時判讀題庫略過，
其餘（設定檔一致性、卡片產生不會炸）照跑。

    python tests/test_ask.py
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.analysis import ask  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過 " if cond else "失敗 ") + name + ("" if cond else f"　{detail}"))
    ok = ok and bool(cond)


# ---------------------------------------------------------------------------
# 1. 設定檔一致性
# ---------------------------------------------------------------------------
cfg, L = ask.load_config()
cards = cfg["cards"]
ids = [c["id"] for c in cards]
check("卡片 id 不重複", len(ids) == len(set(ids)), [i for i in ids if ids.count(i) > 1])
check("分類都在清單內", all(c["c"] in ask.CATS for c in cards), {c["c"] for c in cards} - set(ask.CATS))
check("每張卡都有教學主題", all(c.get("l") in L for c in cards), [c["id"] for c in cards if c.get("l") not in L])
allids = set(ids) | {f"t_{k}" for k in cfg["terms"]}
check("相關問題都指得到", all(r in allids for c in cards for r in c.get("r") or []),
      [(c["id"], r) for c in cards for r in c.get("r") or [] if r not in allids])
check("每個教學主題都有名詞卡", set(L) == set(cfg["terms"]), set(L) ^ set(cfg["terms"]))
check("每張卡都有資料來源", all(c.get("src") for c in cards), [c["id"] for c in cards if not c.get("src")])
check("自訂卡的函式都存在", all(c["src"]["fn"] in ask.FNS for c in cards if "fn" in c["src"]),
      [c["src"]["fn"] for c in cards if "fn" in c["src"] and c["src"]["fn"] not in ask.FNS])
s2t = cfg["s2t"].replace(" ", "")
check("簡轉繁成對", len(s2t) % 2 == 0)
for k, t in L.items():
    q = t.get("quiz") or {}
    if not (len(q.get("opts") or []) == 3 and q.get("ans") in (0, 1, 2) and t.get("one") and t.get("chain")):
        check(f"教學 {k} 欄位齊全", False, t.get("title"))
check("教學頁尾與出處", all(t.get("source") for t in L.values()))

# ---------------------------------------------------------------------------
# 2. 沒有任何資料時，每張卡都要能產生（顯示「本次沒有取得資料」而不是炸掉）
# ---------------------------------------------------------------------------
res = ask.build({}, {})
check("空資料也產生全部卡片", len(res["frags"]) == len(res["index"]["cards"]),
      (len(res["frags"]), len(res["index"]["cards"])))
check("空資料時資料卡顯示缺資料", all("本次沒有取得資料" in res["frags"][i] for i in ids))
check("名詞卡不依賴資料", all("① 一句話" in res["frags"][f"t_{k}"] for k in cfg["terms"]))
check("每張卡都有教學區", all("這個指標怎麼看" in res["frags"][i] for i in ids))
check("每張卡都有跳轉連結", all('class="ask-go"' in res["frags"][i] for i in ids))

# 練習模板：欄位缺就整段不顯示，不能出現沒填的大括號
for i, h in res["frags"].items():
    if "{" in h.replace("{ctx:", "") and "⑥" in h:
        check(f"{i} 練習題沒有殘留欄位", False)
check("練習題缺欄位時隱藏", ask.fill_practice("A {x} B", {}) is None and ask.fill_practice("A {x}", {"x": 1}) == "A 1")

# ---------------------------------------------------------------------------
# 3. 序列轉換
# ---------------------------------------------------------------------------
rows = [{"date": f"2025-{m:02d}-01", "value": 100 + m} for m in range(1, 13)] + \
       [{"date": f"2026-{m:02d}-01", "value": 112 + m} for m in range(1, 4)]
yoy = ask.transform(rows, "yoy")
check("年增率對同月", abs(yoy[-1]["value"] - (115 / 103 - 1) * 100) < 1e-9, yoy[-1])
d = ask.transform(rows, "d", 0.1)
check("差分乘倍數", abs(d[-1]["value"] - 0.1) < 1e-9, d[-1])
a3 = ask.transform(rows, "a3")
check("三月年化", abs(a3[-1]["value"] - ((115 / 112) ** 4 - 1) * 100) < 1e-9)
check("頻率判斷：月", ask.freq_of(rows) == "m")
daily = [{"date": f"2026-01-{i:02d}", "value": i} for i in range(1, 29)]
check("頻率判斷：日", ask.freq_of(daily) == "d")

# 第二十一批：格式、過期標示、期貨失敗、日程越界、依問法補句
check("變動為零寫持平", ask.chg_text(0.04, 1, "%") == "持平" and ask.chg_text(-0.7, 1, "%") == "-0.7 個百分點")
check("變動帶單位", ask.chg_text(1.25, 1, "萬人") == "+1.2 萬人" or ask.chg_text(1.25, 1, "萬人") == "+1.3 萬人")
_ch = {"k": "a2", "num": 102.21, "pv": 102.209, "pc": True, "u": ""}
check("報價變動為零寫持平", ask._chip_delta(_ch, _ch["pv"]) == "持平")
check("報價變動帶單位", ask._chip_delta({"k": "a0", "num": 3.0, "u": " 億"}, 476.0) == "-473 億")
check("bp 報價", ask._chip_delta({"k": "bp0", "num": -5.0}, -4.0) == "-1 bp")
import datetime as _dt
from src import clock as _clock
_t = _clock.today()
check("過期資料標示", ask.stale_note((_t - _dt.timedelta(days=60)).isoformat(), "d").startswith("（資料停在")
      and ask.stale_note(_t.isoformat(), "d") == "")
check("期貨抓取失敗不當成答案", not ask._fw_ok({"value": "—", "delta": "本次擷取失敗"}) and ask._fw_ok({"value": "維持 81%", "delta": "升一碼 19%"}))
from src.analysis import watch_calendar as _wc
check("日程往後查八週不越界", isinstance(_wc._group(_t + _dt.timedelta(days=50), _t - _dt.timedelta(days=_t.weekday())), str))
rows8 = [{"date": f"2025-{m:02d}-01", "value": 4.0 + m / 100} for m in range(1, 13)] + [{"date": "2026-01-01", "value": 4.3}]
_card = {"id": "x", "q": "測試", "c": "就業", "src": {"s": "X", "tf": "lv", "u": "%", "dg": 1, "lab": "測試"}}
_o = ask.series_card(_card, {"X": rows8}, {})
check("數值卡附變化句與年初以來（隱藏，問到才露出）", 'data-int="變化" hidden' in _o["ans"] and 'data-per="y" hidden' in _o["ans"])
check("數值卡表格有去年底", "去年底" in _o["table"][0])

# ---------------------------------------------------------------------------
# 4. 判讀題庫（node 跑頁面上同一份判讀器）
# ---------------------------------------------------------------------------
# 每張卡自己的標題與範例問句都要直接命中自己
SELF = [(q, c["i"]) for c in res["index"]["cards"] for q in [c["q"]] + (c.get("x") or [])]

# 使用者會打的說法：期望值是卡片 id，或 guess／oos／none
BANK = [
    ("失業率多少", "unrate"), ("現在失業率幾趴", "unrate"), ("美國失業率是多少啊", "unrate"),
    ("失業率為什麼上升", "unrate_why"), ("失業率為何下降", "unrate_why"),
    ("什麼是失業率", "t_unrate"), ("失業率怎麼看", "t_unrate"),
    ("失業", "guess"), ("失業率和CPI", "guess"), ("降息", "guess"),
    ("非農", "nfp"), ("非農為什麼這麼少", "nfp_why"), ("非農下修多少", "revisions"),
    ("時薪年增率", "ahe"), ("薪水漲多少", "ahe"), ("初領", "claims"), ("續領", "cont_claims"),
    ("jolts", "jolts_open"), ("離職率", "quits"), ("薩姆規則", "sahm"),
    ("cpi", "cpi"), ("CPI多少", "cpi"), ("CPI月增", "cpi_mom"), ("核心CPI", "core_cpi"),
    ("核心PCE", "core_pce"), ("核心 PCE 三個月年化", "core_pce_3m"), ("pce", "pce"),
    ("超級核心", "supercore"), ("什麼是supercore", "t_supercore"), ("住房通膨", "shelter"),
    ("房租漲多少", "shelter"), ("ppi", "ppi"), ("通膨預期", "infl_expect"),
    ("通膨", "infl_now"), ("通膨為什麼還這麼高", "infl_why"), ("什麼是CPI", "t_cpi"),
    ("就業", "labor_now"), ("美國經濟現在怎麼樣", "brief"),
    ("10年期殖利率", "dgs10"), ("美債殖利率為什麼上升", "longend_why"), ("30-2利差這週怎麼變", "spread_30_2"),
    ("10-2利差", "spread_10_2"), ("期限溢酬多少", "term_premium"), ("期限溢酬是什麼", "t_term_premium"),
    ("損益兩平", "breakeven10"), ("再融資", "refunding"), ("公司債利差", "ig_spread"), ("高收益債", "hy_spread"),
    ("赤字", "deficit"), ("房貸利率", "mortgage"), ("sofr", "sofr"), ("逆回購", "onrrp"),
    ("AI資本支出", "hs_capex"), ("30年期", "dgs30"), ("2年期", "dgs2"),
    ("現在在九宮格哪一格", "cell"), ("九宮格", "cell"), ("存續期間", "duration_card"),
    ("下次FOMC升降息機率？", "fedwatch"), ("聯準會會降息嗎", "fedwatch"), ("下次FOMC什麼時候", "next_fomc"),
    ("現在利率多少", "fed_rate"), ("Fed rate", "fed_rate"), ("什麼是點陣圖", "t_dots"),
    ("誰投反對票", "vote"), ("誰是票委", "officials"), ("靜默期", "blackout"), ("終端利率", "terminal"),
    ("標普今年漲多少", "spx"), ("那斯達克", "ixic"), ("道瓊", "dji"), ("費半", "sox"), ("台股", "twii"),
    ("台指期", "txf"), ("vix", "vix"), ("油價", "wti"), ("布蘭特", "brent"), ("黃金今年漲多少", "gold"),
    ("金價", "gold"), ("美元", "dxy"), ("日圓", "usdjpy"), ("歐元", "eurusd"), ("人民幣", "usdcnh"), ("台幣", "twd"),
    ("本週有什麼數據", "week_data"), ("CPI什麼時候公布", "next_cpi"), ("就業報告什麼時候", "next_nfp"),
    ("這週有哪些官員要講話", "speakers"), ("期中選舉", "election"), ("今天市場怎麼了", "focus_today"),
    ("比特幣會漲嗎", "oos"), ("天氣如何", "oos"), ("樂透號碼", "oos"), ("日本央行會升息嗎", "oos"),
    ("asdfgh", "none"),
    ("CPI為什麼漲", "infl_why"), ("核心PCE為什麼這麼高", "infl_why"), ("油價跌了多少", "wti"),
    ("黃金今年漲多少", "gold"), ("10年期殖利率為什麼漲", "longend_why"),
]


def run_node(qs):
    node = shutil.which("node")
    if not node:
        return None
    with tempfile.TemporaryDirectory() as td:
        ixp, qp, jp = Path(td) / "ix.json", Path(td) / "q.json", Path(td) / "run.js"
        ixp.write_text(json.dumps(res["index"], ensure_ascii=False), encoding="utf-8")
        qp.write_text(json.dumps(qs, ensure_ascii=False), encoding="utf-8")
        jp.write_text(
            "const M=require(" + json.dumps(str(ROOT / "src/pages/ask_match.js")) + ");"
            "const fs=require('fs');const ix=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));"
            "const qs=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));const m=new M(ix);"
            "process.stdout.write(JSON.stringify(qs.map(q=>{const r=m.ask(q);"
            "const rl=m.related(q).ids;"
            "return {mode:r.mode,card:r.card,list:r.list.map(x=>x.id),rel:rl};})));", encoding="utf-8")
        out = subprocess.run([node, str(jp), str(ixp), str(qp)], capture_output=True, text=True,
                             encoding="utf-8", check=True).stdout
        return json.loads(out)


qs = [q for q, _ in SELF] + [q for q, _ in BANK]
got = run_node(qs)
if got is None:
    print("略過 判讀題庫（找不到 node）")
else:
    bad = [(q, e, g) for (q, e), g in zip(SELF, got[:len(SELF)]) if g["card"] != e]
    check(f"每張卡的標題與範例問句都命中自己（{len(SELF)} 題）", not bad, bad[:8])
    bad = []
    for (q, e), g in zip(BANK, got[len(SELF):]):
        if e in ("guess", "oos", "none"):
            if g["mode"] != e:
                bad.append((q, e, g["mode"], g["card"]))
        elif g["card"] != e:
            bad.append((q, e, g["mode"], g["card"], g["list"][:3]))
    check(f"常見說法題庫（{len(BANK)} 題）", not bad, bad)
    # 網站沒有的東西：一定給三個替代問題
    oo = [g for (q, e), g in zip(BANK, got[len(SELF):]) if e == "oos"]
    check("沒有的資料會推薦三題", all(len(g["list"]) >= 3 for g in oo), oo)
    # 我猜你想問：至少三題
    gg = [g for (q, e), g in zip(BANK, got[len(SELF):]) if e == "guess"]
    check("我猜你想問至少三題", all(len(g["list"]) >= 3 for g in gg), gg)
    # 2026-10：泛稱詞（「利率」）列出所有相關題目——包含式比對，名詞卡排最後
    rr = run_node(["利率", "政策利率", "殖利率"])
    r0 = rr[0]["rel"]
    tcards = {c["i"] for c in res["index"]["cards"] if c.get("t")}
    check("「利率」相關題目至少 20 題，含房貸利率、10 年期殖利率、SOFR",
          len(r0) >= 20 and {"fed_rate", "mortgage", "dgs10", "sofr"} <= set(r0), r0)
    check("名詞卡排在一般題目之後",
          all(r0.index(t) > max(r0.index(x) for x in r0 if x not in tcards) for t in r0 if t in tcards), r0)
    check("打得具體時第一題仍是直接命中（政策利率 → fed_rate）", rr[1]["rel"][:1] == ["fed_rate"], rr[1]["rel"][:3])
    check("殖利率的相關題目不含政策利率卡", "fed_rate" not in rr[2]["rel"], rr[2]["rel"])

# ---------------------------------------------------------------------------
# 5. 頁面
# ---------------------------------------------------------------------------
from src.pages import ask as ask_page  # noqa: E402
body = ask_page.ask_body(res["index"])
check("頁面只有一行說明", body.count('class="ask-hint"') == 1 and ask_page.HINT in body)
check("搜尋框範例", "例如：失業率為什麼上升" in body)
check("判讀器內嵌", "AskMatch" in body and 'id="ask-ix"' in body)
check("打字即時提示", 'id="ask-sug"' in body and "drawSug" in body)
check("索引不會提早結束 script", "</script>" not in body.split('id="ask-ix">', 1)[1].split("</script>", 1)[0])
from src import site  # noqa: E402
check("導覽列：偷懶在總覽後面", [n[1] for n in site.NAV][:2] == ["總覽", "偷懶"])

print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
