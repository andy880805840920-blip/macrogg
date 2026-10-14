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
check("⑩ 原始數字直接比、不四捨五入：GS 0.3 誤差 0 唯一命中；Cleveland 0.26 不再進位成 0.3",
      sc["best"] == ["GS"] and sc["err"]["Cleveland Fed"] == 0.04, sc)
check("⑪ 方向命中：GS、JPM、Cleveland 高於共識且實際也高於 → 對", sc["dir"] == {"GS": True, "JPM": True, "Cleveland Fed": True}, sc["dir"])
e_raw = {"key": "cpi", "actual": {"cpi_mom": 0.6}, "actual_raw": {"cpi_mom": 0.57}, "cons": {"cpi_mom": 0.6},
         "clev": {"cpi_mom": 0.53}, "banks": {"BofA": {"cpi_mom": 0.58}, "JPM": {"cpi_mom": 0.55}, "MS": {"cpi_mom": 0.62},
                                              "GS": {"cpi_mom": 0.59}}}
s2 = F.score(e_raw)["cpi_mom"]
check("⑪b 實際值用未四捨五入 0.57：只有 BofA 0.58 命中（不再一欄五顆星）；共識 0.6 當 0.60",
      s2["best"] == ["BofA"] and s2["err"]["市場共識"] == 0.03, s2)
check("⑪c 方向：實際 0.57 低於共識 0.60；BofA 0.58、JPM 0.55 低於 → 對，MS 0.62 → 錯",
      s2["dir"]["BofA"] and s2["dir"]["JPM"] and not s2["dir"]["MS"], s2["dir"])
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

# ㉘–㊱ 圖表自動讀取（假圖片、假 AI；表格數字照 WSJ 9 月 CPI 預測表）
import struct  # noqa: E402
IMG_TABLE = "https://investinglive.com/cms/media/images/us-september-2026-cpi-foreacsts-14-october-2026.jpg?width=1024&format=webp"
IMG_FEAT = "https://investinglive.com/cms/media/Processed/Categories/featured/cpi-featured.jpg?width=768"
IMG_SMALL = "https://investinglive.com/cms/media/images/chart-small.jpg"
IMG_PHOTO = "https://investinglive.com/cms/media/images/trader-photo.jpg"


def png(w, h):
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", w, h) + b"\x08\x02\x00\x00\x00" + b"\x00" * 64


def jpg(w, h):
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\xff\xc0\x00\x11\x08" + struct.pack(">HH", h, w) + b"\x03" + b"\x00" * 40


check("㉘ 不靠 Pillow 讀圖片尺寸（PNG、JPEG）", F.img_info(png(1024, 1183))[:2] == (1024, 1183)
      and F.img_info(jpg(1024, 1183)) == (1024, 1183, "image/jpeg"))
PAGE2 = ("<html><body><article><h1>US CPI preview</h1>"
         f'<figure><img src="{IMG_FEAT}" alt="A quiet trading desk"></figure>'
         + "".join(f"<p>{l}</p>" for l in ART.splitlines() if l)
         + f'<figure><img src="{IMG_PHOTO}" alt="trader at desk"></figure>'
         + f'<figure><img src="{IMG_SMALL}" alt="small"></figure>'
         + f'<figure><img src="{IMG_TABLE}" alt="us-september-2026-cpi-foreacsts-14-october-2026.jpg"></figure>'
         + "<p>The table above lists each forecaster's call.</p></article></body></html>")
imgs = [d["url"] for d in F.body_images(PAGE2)]
check("㉙ 只取內文圖片、排除主視覺；像預測表的排第一", imgs and imgs[0] == IMG_TABLE and IMG_FEAT not in imgs, imgs)

WSJ = [("Bank of America", .58, 3.6, .23, 2.5), ("Barclays", .58, 3.7, .24, 2.5), ("BNP Paribas", .56, 3.6, .23, 2.5),
       ("Citadel Securities", None, 3.6, .19, 2.4), ("Citigroup", None, 3.6, .18, 2.4), ("Deutsche Bank", .57, 3.6, .16, 2.4),
       ("Employ America", .63, None, .26, None), ("Goldman Sachs", .59, 3.7, .24, 2.5), ("Jefferies", .56, 3.6, .19, 2.4),
       ("JP Morgan", .55, 3.6, .18, 2.4), ("Morgan Stanley", .62, 3.7, .24, 2.5), ("Nomura", .58, 3.6, .23, 2.5),
       ("TD Securities", .57, 3.6, .20, 2.4), ("UBS", .56, 3.6, .19, 2.4)]


def table_json(rows=WSJ, median=(.58, 3.6, .22, 2.4), title="September CPI forecasts"):
    ks = ("cpi_mom", "cpi_yoy", "core_mom", "core_yoy")
    return json.dumps({"table": True, "title": title, "release": "CPI", "month": "September",
                       "rows": [dict(name=r[0], **dict(zip(ks, r[1:]))) for r in rows],
                       "median": dict(zip(ks, median))})


VCALLS = []


def make_vision(first, second=None):
    def v(img, mime, prompt, second_read=False):
        VCALLS.append((mime, second_read))
        if "trader" in prompt:
            pass
        return ((second if second is not None else first) if second_read else first), ""
    return v


def get2(url, **kw):
    if "feed" in url:
        return types.SimpleNamespace(status_code=200, text=FEED, content=FEED.encode())
    if url == LINK:
        return types.SimpleNamespace(status_code=200, text=PAGE2, content=PAGE2.encode())
    if "foreacsts" in url:
        return types.SimpleNamespace(status_code=200, content=jpg(1024, 1183), text="")
    if "small" in url:
        return types.SimpleNamespace(status_code=200, content=png(300, 120), text="")
    if "trader" in url:
        return types.SimpleNamespace(status_code=200, content=jpg(1200, 800), text="")
    return types.SimpleNamespace(status_code=404, text="", content=b"")


def vis_router(table, table2=None):
    """照片回 table:false；表格回 table。"""
    calls = []

    def v(img, mime, prompt, second_read=False):
        calls.append(second_read)
        if F.img_info(img)[:2] == (1200, 800):
            return '{"table": false}', ""
        return ((table2 if table2 is not None else table) if second_read else table), ""
    v.calls = calls
    return v


tables = {}
for name_, rows_, med_, title_ in [("ok", WSJ, (.58, 3.6, .22, 2.4), "September CPI forecasts")]:
    tables[name_] = table_json(rows_, med_, title_)
d0 = json.loads(tables["ok"])
got, notes, why = F.check_table("cpi", "2026-09", d0, {"cpi_mom": 0.6, "cpi_yoy": 3.6, "core_mom": 0.2, "core_yoy": 2.5})
check("㉚ 驗算：四欄中位數都對得上；Citi 整體月增空白→不收", not why and got["GS"]["cpi_mom"][0] == 0.59
      and "cpi_mom" not in got["Citi"] and got["BofA"]["core_mom"][0] == 0.23, (why, notes))
bad_cols = [r[:3] + (r[4], r[3]) for r in WSJ]           # 核心月增、年增兩欄對調
_, n2, why2 = F.check_table("cpi", "2026-09", json.loads(table_json(bad_cols)), {"core_mom": 0.2, "core_yoy": 2.5})
check("㉛ 欄位錯置：核心兩欄中位數驗算不過→那兩欄不採用", not why2 and any("core_mom：中位數驗算不過" in x for x in n2), n2)
_, _, why3 = F.check_table("cpi", "2026-09", json.loads(table_json(title="August CPI forecasts")) | {"month": "August"}, {})
check("㉜ 讀到上個月的表（August）→整張不採用", "月份不符" in why3, why3)
_, _, why4 = F.check_table("cpi", "2026-09", {"table": False}, {})
check("㉝ 不是表格→不採用", why4 == "不是逐家預測表", why4)

if HAVE_TF:
    _FF.clock.now = lambda: dt.datetime(2026, 10, 14, 7, 3, tzinfo=_FF.clock.TAIPEI)
    try:
        tmp3 = Path(tempfile.mkdtemp()) / "fc.json"
        vr = vis_router(tables["ok"])
        r = F.update(ctxa, False, tmp3, manual={}, clev={}, today=dt.date(2026, 10, 14), get_fn=get2, ai=fake_ai, vision=vr)
        e = r["releases"]["cpi|2026-09"]
        b = e["banks"]
        vals = {n: {k: v for k, v in row.items() if k not in ("src", "meta")} for n, row in b.items()}
        check("㉞ 圖表讀到：五家整體月增／年增（Citi 無整體月增）、BofA 核心月增 0.23；照片判定非表格；小圖不送 AI",
              vals["GS"] == {"cpi_mom": 0.59, "cpi_yoy": 3.7, "core_mom": 0.24, "core_yoy": 2.5}
              and vals["MS"]["cpi_mom"] == 0.62 and vals["JPM"]["cpi_mom"] == 0.55 and "cpi_mom" not in vals["Citi"]
              and vals["BofA"]["core_mom"] == 0.23 and b["GS"]["meta"]["cpi_mom"]["kind"] == "image"
              and e["img_seen"].get(F._norm_img(IMG_PHOTO)) == "不是逐家預測表"
              and e["img_seen"].get(F._norm_img(IMG_SMALL), "").startswith("skip")
              and vr.calls.count(True) == 1, (vals, e["img_seen"], vr.calls))
        n = len(vr.calls)
        F.update(ctxa, False, tmp3, manual={}, clev={}, today=dt.date(2026, 10, 14), get_fn=get2, ai=fake_ai, vision=vr)
        check("㉟ 讀過的圖不再讀（不浪費 token）", len(vr.calls) == n, vr.calls)
        html = forecasts_ui.section({"releases": {"cpi|2026-09": e}}, dt.date(2026, 10, 14))
        check("㊱ 頁面：出處顯示「自動讀圖」與中位數驗算", "自動讀圖・investingLive" in html and "中位數驗算通過" in html)
        # 整列錯位：GS 與 MS 的列互換（中位數不變）→ 複讀（另一家）讀對 → 不一致的格子不採用
        shift = [r if r[0] not in ("Goldman Sachs", "Morgan Stanley") else
                 ((r[0],) + (WSJ[10][1:] if r[0] == "Goldman Sachs" else WSJ[7][1:])) for r in WSJ]
        tmp4 = Path(tempfile.mkdtemp()) / "fc.json"
        vr2 = vis_router(table_json(shift), tables["ok"])
        e4 = F.update(ctxa, False, tmp4, manual={}, clev={}, today=dt.date(2026, 10, 14), get_fn=get2,
                      ai=lambda t, s_: ("{}", ""), vision=vr2)["releases"]["cpi|2026-09"]
        g4 = e4["banks"].get("GS") or {}
        check("㊲ 整列錯位（中位數驗算抓不到）→ 複讀比對抓到，GS 整體月增不採用、其他家照收",
              "cpi_mom" not in g4 and e4["banks"]["JPM"]["cpi_mom"] == 0.55, (g4, [x.get("notes") for x in e4["auto_log"]]))
        # 圖表讀錯、文字有原句：以原文為準
        tmp5 = Path(tempfile.mkdtemp()) / "fc.json"
        wrong = [r if r[0] != "JP Morgan" else (r[0], .55, 3.6, .16, 2.4) for r in WSJ]  # JPM 核心月增讀成 0.16（中位數不變）
        e5 = F.update(ctxa, False, tmp5, manual={}, clev={}, today=dt.date(2026, 10, 14), get_fn=get2,
                      ai=fake_ai, vision=vis_router(table_json(wrong)))["releases"]["cpi|2026-09"]
        check("㊳ 圖表跟原文不一致（JPM 0.16 vs 原文 0.18）→ 以原文為準",
              e5["banks"]["JPM"]["core_mom"] == 0.18 and e5["banks"]["JPM"]["meta"]["core_mom"]["kind"] == "text",
              e5["banks"]["JPM"])
    finally:
        _FF.clock.now = _now
check("㊴ 讀圖沒金鑰：回報原因、不呼叫", F.vision_ai(b"x", "image/png", "p", env={}) == ("", "沒有 AI 金鑰"))

# ㊵–㊷ 第 42 批：別國 CPI 不算、複讀換模型備援、擷取紀錄
check("㊵ 別國的 CPI（China September CPI … expected）不算預覽文章",
      not F.is_preview("cpi", {"title": "China September CPI 0.9% y/y (expected 1%, prior 0.8%)", "pub": None}, None)
      and F.is_preview("cpi", {"title": "US CPI preview: banks expect core 0.2%", "pub": None}, None))
import src.analysis.polish as _P  # noqa: E402
_orig_http = _P._http
HCALLS = []


def fake_http(method, url, *, label, **kw):
    HCALLS.append(label)
    if "generativelanguage" in url:
        return types.SimpleNamespace(status_code=429, raise_for_status=lambda: (_ for _ in ()).throw(RuntimeError("429 Too Many Requests")))
    return types.SimpleNamespace(status_code=200, raise_for_status=lambda: None,
                                 json=lambda: {"content": [{"text": '{"table": false}'}]})


_P._http = fake_http
try:
    out = F.vision_ai(b"x", "image/png", "p", True, env={"ANTHROPIC_API_KEY": "a", "GEMINI_API_KEY": "g"})
finally:
    _P._http = _orig_http
check("㊶ 複讀：優先用 Claude Sonnet（跟初讀的 Haiku 不同模型），不碰 Gemini",
      out == ('{"table": false}', "") and len(HCALLS) == 1 and "sonnet" in HCALLS[0], (out, HCALLS))
HCALLS.clear()


def fake_http2(method, url, *, label, **kw):
    HCALLS.append(label)
    if url.endswith("/models"):                    # 模型清單：只剩新的 flash
        return types.SimpleNamespace(status_code=200, raise_for_status=lambda: None, json=lambda: {"models": [
            {"name": "models/gemini-3.1-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]}]})
    HCALLS.append(("body", kw.get("json", {}).get("generationConfig")))
    return types.SimpleNamespace(status_code=200, raise_for_status=lambda: None,
                                 json=lambda: {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})


_P._http = fake_http2
try:
    out2 = F.vision_ai(b"x", "image/png", "p", True, env={"GEMINI_API_KEY": "g"})
finally:
    _P._http = _orig_http
check("㊶b Gemini 模型被汰換（404）的對策：先問金鑰能用哪些模型，3.x 不送 thinkingConfig",
      out2 == ("{}", "") and any("gemini-3.1-flash" in str(h) for h in HCALLS)
      and ("body", {"temperature": 0, "maxOutputTokens": 3000}) in HCALLS, HCALLS)
check("㊶c 外匯走勢圖（EURUSD-bullish-chart）不送 AI；檔名有 USD 的預測表照讀",
      [d["url"] for d in F.body_images('<html><body><article><p>' + "US CPI preview text. " * 30 + '</p>'
       '<img src="https://editorial.fxsstatic.com/images/i/EURUSD-bullish-chart.png" alt="">'
       '<p>' + "More text here. " * 30 + '</p><img src="https://x.com/i/USD-forecast-table.png" alt=""></article></body></html>')]
      == ["https://x.com/i/USD-forecast-table.png"])
e_log = {"key": "cpi", "period": "2026-09", "date": "2026-10-14", "cons": {},
         "auto_log": [{"at": "2026-10-14T12:43+08:00", "src": "investingLive（圖表）", "img": "x", "link": "y",
                       "result": "複讀失敗，下次再試：Gemini 429"}]}
html = forecasts_ui.section({"releases": {"cpi|2026-09": e_log}}, dt.date(2026, 10, 14))
check("㊷ 04 區有「自動擷取紀錄」（收合），看得到失敗原因", "自動擷取紀錄" in html and "複讀失敗" in html)

# ㊸–㊺ 第 45 批：未四捨五入的實際值、版面
per_r, a_r = F.actuals(S, "cpi", raw=True)
check("㊸ 未四捨五入實際值：月增與年增兩位小數", per_r == "2026-09" and a_r["cpi_mom"] == round(F.round_half((100 + 12 * .3 + .52) / (100 + 12 * .3) * 100 - 100, 2), 2)
      and a_r["cpi_yoy"] == 0.5, a_r)
tmp6 = Path(tempfile.mkdtemp()) / "fc.json"
r6 = F.update(dict(ctxa, _all_series=S), False, tmp6, manual={}, clev={}, today=dt.date(2026, 10, 15), do_auto=False)
e6 = r6["releases"]["cpi|2026-09"]
check("㊹ 公布後同時記官方值與未四捨五入值", e6["actual"]["cpi_mom"] == 0.5 and e6["actual_raw"] == a_r and e6["actual_raw"]["core_yoy"] == 2.4, (e6["actual"], e6["actual_raw"]))
e7 = {"key": "cpi", "period": "2026-09", "date": "2026-10-14",
      "actual": {"cpi_mom": 0.6, "core_mom": 0.3, "cpi_yoy": 3.7, "core_yoy": 2.6},
      "actual_raw": {"cpi_mom": 0.57, "core_mom": 0.27, "cpi_yoy": 3.66, "core_yoy": 2.58},
      "cons": {"cpi_mom": 0.6, "core_mom": 0.2, "cpi_yoy": 3.6, "core_yoy": 2.5},
      "clev": {"cpi_mom": 0.53, "core_mom": 0.2, "cpi_yoy": 3.6, "core_yoy": 2.39},
      "banks": {"BofA": {"cpi_mom": 0.58, "core_mom": 0.23, "cpi_yoy": 3.6, "core_yoy": 2.5},
                "Citi": {"core_mom": 0.18, "cpi_yoy": 3.6, "core_yoy": 2.4},
                "JPM": {"cpi_mom": 0.55, "core_mom": 0.18, "cpi_yoy": 3.6, "core_yoy": 2.4},
                "MS": {"cpi_mom": 0.62, "core_mom": 0.24, "cpi_yoy": 3.7, "core_yoy": 2.5},
                "GS": {"cpi_mom": 0.59, "core_mom": 0.24, "cpi_yoy": 3.7, "core_yoy": 2.5}}}
h7 = forecasts_ui.section({"releases": {"cpi|2026-09": e7}}, dt.date(2026, 10, 15))
check("㊺ 版面：超出所有預測移到上方提示、實際值只顯示兩位小數（官方值在出處）、對共識 ▼0.03、格子不帶 %、沒有預估區間",
      "核心月增 0.27、核心年增 2.58</b> 高於所有預測" in h7 and "<b>0.57</b></button>" in h7 and "官方公布 0.6" in h7
      and "▼0.03" in h7 and "▲0.07" in h7 and "0.58%" not in h7 and "單位：%" in h7 and "預估區間" not in h7, h7[:0])

print()
print("有失敗" if FAIL else "全部通過")
sys.exit(1 if FAIL else 0)
