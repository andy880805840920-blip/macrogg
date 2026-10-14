"""
總覽「04 各家預測」（2026-10）：資料更新、首次公布值、計分、防抓錯。不連網。
"""
import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.analysis import forecasts as F  # noqa: E402

FAIL = []


def check(name, ok, info=""):
    print(("通過  " if ok else "失敗  ") + name + ("" if ok else f" — {info}"))
    if not ok:
        FAIL.append(name)


check("① 半進位（0.25→0.3、-0.25→-0.3）", F.round_half(0.25, 1) == 0.3 and F.round_half(-0.25, 1) == -0.3)
check("② 共識字串解析（+10.0 萬→100 千人、0.3%→0.3）",
      F.parse_ff("nfp", "+10.0 萬") == 100 and F.parse_ff("core_mom", "0.3%") == 0.3)


def rows(start, vals):
    y, m = map(int, start.split("-"))
    out = []
    for v in vals:
        out.append({"date": f"{y:04d}-{m:02d}-01", "value": v})
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


S = {"CPIAUCSL": rows("2025-08", [100 + i * 0.3 for i in range(13)] + [100 + 12 * 0.3 + 0.52]),
     "CPILFESL": rows("2025-08", [200 + i * 0.4 for i in range(14)]),
     "CPIAUCNS": rows("2025-08", [100] * 2 + [100.5] * 12),
     "CPILFENS": rows("2025-08", [100] * 2 + [102.4] * 12),
     "PAYEMS": rows("2026-07", [159000, 159073, 159102]),
     "UNRATE": rows("2026-07", [4.3, 4.3, 4.2]), "CES0500000003": rows("2026-07", [36.0, 36.1, 36.25])}
per, a = F.actuals(S, "cpi")
check("③ CPI 實際值：最新期、月增與年增", per == "2026-09" and a["cpi_yoy"] == 0.5 and "cpi_mom" in a, (per, a))
per, a = F.actuals(S, "employment")
check("④ 就業實際值：非農差分（千人）、失業率、時薪月增",
      per == "2026-09" and a == {"nfp": 29, "u3": 4.2, "ahe_mom": 0.4}, (per, a))

# ⑤ 更新：公布前抓共識；公布後記首次公布值並凍結
tmp = Path(tempfile.mkdtemp()) / "fc.json"
ctx = {"_schedule": {"employment": [("2026-10-02", "x")]},
       "_watch_extra": {"consensus": {"employment|2026-10-02": [
           {"label": "非農新增", "forecast": "+5.0 萬", "previous": ""},
           {"label": "失業率", "forecast": "4.3%", "previous": ""}]}},
       "_all_series": {}}
man = {"employment|2026-09": {"GS": {"nfp": 40.0, "u3": 4.3}, "JPM": {"nfp": 400.0, "u3": 4.2}}}
r = F.update(ctx, False, tmp, manual=man, clev={}, today=dt.date(2026, 9, 30), do_auto=False)
e = r["releases"]["employment|2026-09"]
check("⑤ 公布前抓到市場共識（非農 50 千人、失業率 4.3）", e["cons"] == {"nfp": 50.0, "u3": 4.3}, e)
check("⑥ 防抓錯：JPM 非農 40 萬跟共識差太多→不採用，失業率仍採用",
      {k: v for k, v in e["banks"]["JPM"].items() if k not in ("src", "meta")} == {"u3": 4.2}
      and any("JPM nfp" in b for b in e["bad"]), e["banks"])
ctx2 = dict(ctx, _all_series=S)
ctx2["_watch_extra"] = {"consensus": {"employment|2026-10-02": [{"label": "非農新增", "forecast": "+9.0 萬", "previous": ""}]}}
r = F.update(ctx2, False, tmp, manual=man, clev={}, today=dt.date(2026, 10, 2), do_auto=False)
e = r["releases"]["employment|2026-09"]
check("⑦ 公布當天：最後一版共識（+9 萬）、記下首次公布值", e["cons"]["nfp"] == 90.0 and e["actual"]["nfp"] == 29, e)
S2 = dict(S, PAYEMS=rows("2026-07", [159000, 159073, 159150]))
ctx3 = dict(ctx2, _all_series=S2)
ctx3["_watch_extra"] = {"consensus": {"employment|2026-10-02": [{"label": "非農新增", "forecast": "+1.0 萬", "previous": ""}]}}
r = F.update(ctx3, False, tmp, manual=man, clev={}, today=dt.date(2026, 10, 5), do_auto=False)
e = r["releases"]["employment|2026-09"]
check("⑧ 公布後凍結：修正值與新共識都不覆蓋", e["actual"]["nfp"] == 29 and e["cons"]["nfp"] == 90.0, e)
check("⑨ 狀態檔有寫出", json.loads(tmp.read_text())["releases"]["employment|2026-09"]["actual"]["nfp"] == 29)

# ⑩ 計分：四捨五入到實際值位數、同分一起命中、方向命中
e = {"key": "cpi", "actual": {"core_mom": 0.3}, "cons": {"core_mom": 0.2},
     "clev": {"core_mom": 0.26}, "banks": {"GS": {"core_mom": 0.3}, "MS": {"core_mom": 0.2}, "JPM": {"core_mom": 0.4}}}
sc = F.score(e)["core_mom"]
check("⑩ Cleveland 0.26 四捨五入成 0.3，跟 GS 同樣命中", sorted(sc["best"]) == ["Cleveland Fed", "GS"], sc)
check("⑪ 方向命中：GS、JPM、Cleveland 高於共識且實際也高於 → 對", sc["dir"] == {"GS": True, "JPM": True, "Cleveland Fed": True}, sc["dir"])
lb = F.leaderboard({"a": e}, "inflation")
check("⑫ 排行榜：命中數排序、市場共識與 Cleveland Fed 一起排",
      lb["periods"] == 1 and lb["rows"][0]["name"] in ("GS", "Cleveland Fed") and
      any(r["name"] == "市場共識" for r in lb["rows"]), lb)

# ⑬ 挑哪一期
rel = {"a": {"key": "cpi", "date": "2026-10-15", "period": "2026-09"},
       "b": {"key": "cpi", "date": "2026-09-11", "period": "2026-08", "actual": {"cpi_mom": 0.4}}}
check("⑬ 10 天內即將公布的優先", F.pick(rel, "cpi", dt.date(2026, 10, 10))["period"] == "2026-09")
check("⑭ 沒有即將公布的就顯示最近已公布的", F.pick(rel, "cpi", dt.date(2026, 10, 1))["period"] == "2026-08")

# ⑮ 手動設定檔
y = Path(tempfile.mkdtemp()) / "b.yaml"
y.write_text('cpi:\n  "2026-09":\n    GS: {core_mom: 0.2, src: https://x}\n    Foo: {core_mom: 0.3}\n    JPM: {bad_key: 1}\n', encoding="utf-8")
m = F.load_manual(y)
check("⑮ 設定檔：只認五家縮寫與既有欄位", m == {"cpi|2026-09": {"GS": {"core_mom": 0.2, "src": "https://x"}}}, m)

# ⑯ 頁面能產生
from src.pages import forecasts_ui  # noqa: E402
html = forecasts_ui.section({"releases": {"x": dict(e, period="2026-09", date="2026-10-15", key="cpi")}}, dt.date(2026, 10, 14))
check("⑯ 04 區：五家縮寫、市場共識、Cleveland Fed、無資料、★、誰最準",
      all(t in html for t in ("BofA", "Citi", "JPM", "MS", "GS", "市場共識", "Cleveland Fed", "無資料", "★", "誰最準")))

# ⑰–㉔ 投行預估自動擷取（假的 RSS、假的 AI；文章是仿照實際預覽彙整寫的短版）
import types  # noqa: E402
ART = """US CPI preview: forecasters see energy lifting headline
Summary:
- The median forecast sees headline CPI up around 0.6% m/m and 3.6% y/y.
- Core forecasts range from 0.16% at Deutsche Bank to 0.24% at Goldman Sachs, Barclays and Morgan Stanley
Headline forecasts are tightly grouped, with Morgan Stanley at the top on a monthly basis and J.P. Morgan slightly below the pack.
The core picture is less settled. Deutsche Bank has the softest call at 0.16%, with Citigroup and JPMorgan both at 0.18%, while Goldman Sachs, Barclays and Morgan Stanley sit at 0.24%. The difference matters for the annual rate: roughly half of forecasters, including Bank of America, Goldman Sachs and Morgan Stanley, expect core to edge up to 2.5% year on year, while the rest, including Citigroup and JPMorgan, see it holding at 2.4%.
"""
LINK = "https://investinglive.com/news/us-cpi-preview-x/"
FEED = f"""<rss><channel>
<item><title><![CDATA[US CPI preview: forecasters see energy lifting headline]]></title><link>{LINK}</link><pubDate>Tue, 13 Oct 2026 20:00:00 GMT</pubDate></item>
<item><title>US CPI 0.5% vs 0.6% expected</title><link>https://investinglive.com/after/</link><pubDate>Wed, 14 Oct 2026 12:31:00 GMT</pubDate></item>
<item><title>Oil rises on Gulf tensions</title><link>https://investinglive.com/oil/</link><pubDate>Tue, 13 Oct 2026 19:00:00 GMT</pubDate></item>
</channel></rss>"""
PAGE = "<html><body><article><h1>x</h1>" + "".join(f"<p>{l}</p>" for l in ART.splitlines() if l) + "</article></body></html>"
CALLS = []


def fake_get(url, **kw):
    if "feed" in url:
        return types.SimpleNamespace(status_code=200, text=FEED)
    if url == LINK:
        return types.SimpleNamespace(status_code=200, text=PAGE)
    return types.SimpleNamespace(status_code=404, text="")


def fake_ai(text, system):
    CALLS.append(system)
    # GS cpi_mom 0.6＝AI 把中位數算到 GS 頭上；BofA core_mom 0.22＝原文沒有的數字；JPM core_yoy 0.18＝欄位張冠李戴
    return ('```json\n{"GS": {"core_mom": 0.24, "core_yoy": 2.5, "cpi_mom": 0.6}, "MS": {"core_mom": 0.24, "core_yoy": 2.5},'
            ' "Citi": {"core_mom": 0.18, "core_yoy": 2.4}, "JPM": {"core_mom": 0.18, "core_yoy": 0.18},'
            ' "BofA": {"core_yoy": 2.5, "core_mom": 0.22}, "Barclays": {"core_mom": 0.24}}\n```'), ""


it = F.feed_items(FEED)
ra = F.release_dt("cpi", "2026-10-14")
check("⑰ 只挑公布前的預覽文章（公布後的「vs expected」、無關新聞都不算）",
      [x["link"] for x in it if F.is_preview("cpi", x, ra)] == [LINK], [(x["title"], F.is_preview("cpi", x, ra)) for x in it])
tmp2 = Path(tempfile.mkdtemp()) / "fc.json"
ctxa = {"_schedule": {"cpi": [("2026-10-14", "x")]},
        "_watch_extra": {"consensus": {"cpi|2026-10-14": [
            {"label": "核心 CPI 月增", "forecast": "0.2%"}, {"label": "核心 CPI 年增", "forecast": "2.5%"},
            {"label": "CPI 月增", "forecast": "0.6%"}, {"label": "CPI 年增", "forecast": "3.6%"}]}}, "_all_series": {}}
try:
    import trafilatura  # noqa: F401
    HAVE_TF = True
except ImportError:
    HAVE_TF = False
if HAVE_TF:
    import src.analysis.forecasts as _FF
    _now = _FF.clock.now
    _FF.clock.now = lambda: dt.datetime(2026, 10, 14, 7, 3, tzinfo=_FF.clock.TAIPEI)
    try:
        r = F.update(ctxa, False, tmp2, manual={"cpi|2026-09": {"Citi": {"core_mom": 0.2, "src": "https://m"}}},
                     clev={}, today=dt.date(2026, 10, 14), get_fn=fake_get, ai=fake_ai)
        e = r["releases"]["cpi|2026-09"]
        b = e["banks"]
        vals = {n: {k: v for k, v in row.items() if k not in ("src", "meta")} for n, row in b.items()}
        check("⑱ 自動擷取：GS／MS 0.24 與 2.5、JPM 0.18、BofA 年增 2.5",
              vals.get("GS") == {"core_mom": 0.24, "core_yoy": 2.5} and vals.get("MS") == {"core_mom": 0.24, "core_yoy": 2.5}
              and vals.get("JPM") == {"core_mom": 0.18} and vals.get("BofA") == {"core_yoy": 2.5}, vals)
        bad = e["auto_log"][-1]["bad"]
        check("⑲ 擋下 AI 編的數字（BofA 0.22）、欄位錯置（JPM 年增 0.18）、把共識算到 GS（CPI 月增 0.6 原文沒寫給 GS）",
              any("BofA core_mom" in x for x in bad) and any("JPM core_yoy" in x for x in bad)
              and any("GS cpi_mom" in x for x in bad), bad)
        check("⑳ 非五家（Barclays）不收", "Barclays" not in b)
        check("㉑ 手動逐欄優先：Citi 月增用手動 0.2、年增仍是自動 2.4",
              vals.get("Citi") == {"core_mom": 0.2, "core_yoy": 2.4} and b["Citi"]["meta"]["core_mom"]["via"] == "manual"
              and b["Citi"]["meta"]["core_yoy"]["via"] == "auto", b.get("Citi"))
        check("㉒ 出處：網址、來源名、原句", b["GS"]["meta"]["core_mom"]["src"] == LINK and b["GS"]["meta"]["core_mom"]["name"] == "investingLive"
              and "Goldman" in b["GS"]["meta"]["core_mom"]["q"], b["GS"]["meta"])
        n = len(CALLS)
        F.update(ctxa, False, tmp2, manual={}, clev={}, today=dt.date(2026, 10, 14), get_fn=fake_get, ai=fake_ai)
        check("㉓ 同一篇內容沒變就不再問 AI", len(CALLS) == n, len(CALLS))
        _FF.clock.now = lambda: dt.datetime(2026, 10, 14, 21, 0, tzinfo=_FF.clock.TAIPEI)
        e2 = F.update(ctxa, False, tmp2, manual={}, clev={}, today=dt.date(2026, 10, 14),
                      get_fn=fake_get, ai=lambda t, s: ('{"GS": {"core_mom": 0.16}}', ""))["releases"]["cpi|2026-09"]
        check("㉔ 公布時刻之後不再擷取（GS 仍是 0.24）", e2["banks"]["GS"]["core_mom"] == 0.24, e2["banks"].get("GS"))
        html = forecasts_ui.section({"releases": {"cpi|2026-09": e2}}, dt.date(2026, 10, 14))
        check("㉕ 頁面：點格子看得到「自動擷取・investingLive」與原句", "自動擷取・investingLive" in html and "Goldman Sachs" in html)
    finally:
        _FF.clock.now = _now
else:
    print("（略過 ⑱–㉕：沒有安裝 trafilatura）")
check("㉖ AI 沒金鑰／失敗：什麼都不採用、不記雜湊",
      F.extract("cpi", "2026-09", ART, {}, ai=lambda t, s: ("", "沒有 AI 金鑰")) == ({}, ["AI 失敗：沒有 AI 金鑰"]))
_S = F.sentences(ART)
check("㉗ 同一句多家：數字要跟該家在同一子句（JPM 0.24、GS 0.16、GS 年增 2.4 都不算）",
      not F.evidence("cpi", "JPM", "core_mom", 0.24, _S) and not F.evidence("cpi", "GS", "core_mom", 0.16, _S)
      and not F.evidence("cpi", "GS", "core_yoy", 2.4, _S) and F.evidence("cpi", "JPM", "core_mom", 0.18, _S))

print()
print("有失敗" if FAIL else "全部通過")
sys.exit(1 if FAIL else 0)
