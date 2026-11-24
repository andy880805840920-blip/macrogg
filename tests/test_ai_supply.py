"""
AI 大事「AI 供需」與 OpenAI IPO、首頁「02 本期變化」歷史長條（2026-11）。

    python tests/test_ai_supply.py
"""
import copy
import datetime as dt
import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
import yaml                                          # noqa: E402
from src.analysis import ai_supply as S              # noqa: E402
from src.analysis import chg_hist as H               # noqa: E402
from src.analysis import ipo_docs                    # noqa: E402
from src.pages import ai_events as P                 # noqa: E402
from src.pages import home                           # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(f"{'通過' if cond else '失敗'}  {name}" + (f" — {detail}" if detail else ""))
    ok &= bool(cond)


cfg = yaml.safe_load((ROOT / "config" / "ai_supply.yaml").read_text(encoding="utf-8"))

# ① 每 GW 每年需要賺多少：伺服器 550×0.7÷5.6＋機房 550×0.3÷20＋電費 9.64¢×8.76TWh＋資金 550×5.5%×0.6
c = S.per_gw_cost(cfg["cost"])
check("① 每 GW 每年需賺約 104 億", abs(c["total"] - 103.6) < 0.2, f'{c["total"]:.2f}')
check("① 分項：伺服器 68.75、機房 8.25、電費 8.44、資金 18.15",
      abs(c["server"] - 68.75) < .01 and abs(c["shell"] - 8.25) < .01 and abs(c["power"] - 8.44) < .01
      and abs(c["capital"] - 18.15) < .01)

# ② 主計算
r = S.build(cfg)
check("② 近 4 季出貨約 12.3 GW", abs(r["gw4"] - 12.28) < 0.05, f'{r["gw4"]:.2f}')
check("② 已上線算力只算 9 個月以前、近 6 年內", r["lag"] == "2026-01-28" and r["start"] == "2020-10-28"
      and abs(r["fleet"] - 13.92) < 0.05, f'{r["fleet"]:.2f}')
check("② 需求＝Anthropic＋OpenAI（不加文章的其他模型假設）", r["demand"] == 1310)
check("② 隱含利用率約 91%", abs(r["util"] - 90.85) < 0.2, f'{r["util"]:.2f}')
check("② 每月新增 ARR 約 100 億、需要約 106 億", abs(r["net_mo"] - 100) < 0.5 and abs(r["needed_mo"] - 106) < 0.5)
check("② 判斷：追不上", r["tone"] == "bad" and r["verdict"].startswith("需求還追不上"))
check("② 年度數字不算進近 4 季", all(v["l4"] < 4000 for v in r["vendors"]))

# ③ 判斷門檻
c2 = copy.deepcopy(cfg)
c2["arr"][0]["pts"][-1]["v"] = 900                   # 需求變多 → 利用率 ≥ 95%
check("③ 利用率 ≥ 95%＝大致打平", S.build(c2)["tone"] == "mid", f'{S.build(c2)["util"]:.1f}')
c2["arr"][0]["pts"][-1]["v"] = 1200
check("③ 利用率 ≥ 100% 且新增夠＝跟得上", S.build(c2)["tone"] == "ok")
check("③ 設定缺資料回 None", S.build({}) is None and S.build({"vendors": []}) is None)

# ④ 畫面：AI 大事視窗最上面、導覽「供需」第一個；OpenAI IPO 在 Anthropic 結束後放最下面、導覽最後
dc = {"total": {"2027": {"mw": 20819.3}, "2028": {"mw": 32840.3}}}
hs = [{"label": "Q2", "capex": 2000, "ocf": 2100, "debt": 300}, {"label": "Q3", "capex": 2304, "ocf": 1986, "debt": 771}]
ev = {"events": [{"co": "Nvidia", "type": "財報", "date": "2026-11-20", "zh": "財報", "id": "x"}],
      "companies": ["Nvidia"], "window_days": 14, "new_since": "2026-11-20",
      "ipo": {"name": "Anthropic", "active": False, "listed": True},
      "ipo2": {"name": "OpenAI", "active": True, "confidential": True, "steps": []},
      "ipo2_x": {"filings": [], "valuations": [{"date": "2026-11-20", "median": 1000, "lo": 900, "hi": 1100, "n": 2,
                                                 "items": [{"source": "Reuters", "title": "t", "url": "u", "value": 1000}]}]}}
tile, panel = P.ai_tile(ev, hs, dc, r)
i_nav, i_sd, i_co, i_oai, i_why = (panel.find(k) for k in ('class="ai-nav"', 'data-sec="sd"', 'data-sec="co"',
                                                          'data-sec="oai"', 'class="ai-why"'))
check("④ 順序：供需 → 各公司 → OpenAI IPO → 跟利率的關係", 0 <= i_nav < i_sd < i_co < i_oai < i_why)
nav = panel[i_nav:panel.find("</nav>")]
check("④ 導覽：供需第一個、OpenAI 最後一個", nav.find('data-go="sd"') < nav.find('data-go="co"') < nav.find('data-go="oai"')
      and nav.rstrip().endswith("OpenAI</button>"))
check("④ OpenAI 保密遞件中：只放一行狀態＋媒體估值", "保密遞件中" in panel and "準備中・OpenAI IPO" in panel
      and "媒體報導的估值預期" in panel)
check("④ 相關數字：資本支出、佔現金流、發債、Epoch 2028", "五家資本支出 2,304 億／季" in panel and "資本支出佔現金流 116%" in panel
      and "單季發債 771 億" in panel and "全美 AI 算力 2028 年 32.8 GW" in panel)
check("④ 手機收合（sd-more）＋桌機明細（sd-det）都在", panel.count('class="sd-more"') == 2 and panel.count('class="sd-det"') == 2)
check("④ 不放文章的門檻與假設", "115" not in panel[i_sd:i_co] and "19%" not in panel[i_sd:i_co])
ev2 = dict(ev, ipo={"name": "Anthropic", "active": True, "steps": []})
_, panel2 = P.ai_tile(ev2, hs, dc, r)
check("④ Anthropic 還在進行中時不放 OpenAI", 'data-sec="oai"' not in panel2 and 'data-sec="ipo"' in panel2)
_, panel3 = P.ai_tile(ev, hs, dc, None)
check("④ 沒有供需資料就不放那一塊", 'data-sec="sd"' not in panel3 and 'data-go="sd"' not in panel3)

# ⑤ IPO 細節：沒有 cik 不抓 SEC，只抓媒體估值
with tempfile.TemporaryDirectory() as td:
    urls = []
    x = ipo_docs.build(None, "OpenAI", pathlib.Path(td) / "o.json", offline=False,
                       _get=lambda u: (urls.append(u), "<rss><channel></channel></rss>")[1])
    check("⑤ 沒有 cik：不連 SEC，只查新聞", urls and not any("sec.gov" in u for u in urls) and x["filings"] == [])

# ⑥ 02 本期變化歷史：同一天取代、項數沒變不加、保留 100 天
p = lambda d, a, b, c, t="": {"d": d, "dv": a, "hk": b, "nt": c, "tilt": t}   # noqa: E731
rows = H.merge([], p("2026-11-01", 3, 2, 1))
rows = H.merge(rows, p("2026-11-02", 3, 2, 1))
check("⑥ 項數沒變不多一根", len(rows) == 1)
rows = H.merge(rows, p("2026-11-03", 4, 2, 1))
rows = H.merge(rows, p("2026-11-03", 5, 2, 1))
check("⑥ 同一天取當天最後一次", len(rows) == 2 and rows[-1]["dv"] == 5)
rows = H.merge(rows, p("2026-11-03", 3, 2, 1))
check("⑥ 當天又變回跟前一點一樣：這天不算", len(rows) == 1)
rows = H.merge([p("2026-07-01", 1, 1, 1)], p("2026-11-03", 3, 2, 1))
check("⑥ 只保留近 100 天", [x["d"] for x in rows] == ["2026-11-03"])
with tempfile.TemporaryDirectory() as td:
    f = pathlib.Path(td) / "h.json"
    f.write_text(json.dumps([p("2026-11-01", 3, 2, 1)]), encoding="utf-8")
    out = H.update(f, p("2026-11-02", 4, 2, 1), write=False)
    check("⑥ 離線：畫面有今天這點、檔案不動", len(out) == 2 and len(json.loads(f.read_text())) == 1)
    H.update(f, p("2026-11-02", 4, 2, 1), write=True)
    check("⑥ 線上：寫進檔案", len(json.loads(f.read_text())) == 2)
seed = json.loads((ROOT / "state" / "changes_hist.json").read_text(encoding="utf-8"))
check("⑥ 舊資料回補：10/6 起、每天最多一點、相鄰兩點項數不同",
      seed[0]["d"] == "2026-10-06" and len({x["d"] for x in seed}) == len(seed)
      and all(any(a[k] != b[k] for k in ("dv", "hk", "nt")) for a, b in zip(seed, seed[1:])), str(len(seed)))

# ⑦ 02 小卡與視窗的長條
hist = seed[-5:]
html = home._ch_hist_html(hist)
check("⑦ 視窗長條：一天一根、可點看數字", html.count('class="ch-c"') == 5 and 'class="ch-rd"' in html
      and "鴿 " in html and "data-tip=" in html)
check("⑦ 只有一點不畫", home._ch_hist_html(hist[:1]) == "")
col = home._ch_col(p("2026-11-03", 3, 2, 0), tip=False)
check("⑦ 三色堆疊改成比例：每根一樣高、項數 0 的顏色不畫", 'class="dovish" style="flex:3"' in col and "neutral" not in col
      and "height" not in col)
check("⑦ 數字顯示比例（加起來 100%）", home._ch_tip(p("2026-11-03", 23, 14, 2)).startswith("11/3：鴿 59%・鷹 36%・中性 5%（共 39 項）"))
check("⑦ 視窗有 50% 參考線", 'ch-g50' in html and "50%" in html)

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
