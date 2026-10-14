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
r = F.update(ctx, False, tmp, manual=man, clev={}, today=dt.date(2026, 9, 30), do_recon=False)
e = r["releases"]["employment|2026-09"]
check("⑤ 公布前抓到市場共識（非農 50 千人、失業率 4.3）", e["cons"] == {"nfp": 50.0, "u3": 4.3}, e)
check("⑥ 防抓錯：JPM 非農 40 萬跟共識差太多→不採用，失業率仍採用",
      e["banks"]["JPM"] == {"u3": 4.2, "src": ""} and any("JPM nfp" in b for b in e["bad"]), e["banks"])
ctx2 = dict(ctx, _all_series=S)
ctx2["_watch_extra"] = {"consensus": {"employment|2026-10-02": [{"label": "非農新增", "forecast": "+9.0 萬", "previous": ""}]}}
r = F.update(ctx2, False, tmp, manual=man, clev={}, today=dt.date(2026, 10, 2), do_recon=False)
e = r["releases"]["employment|2026-09"]
check("⑦ 公布當天：最後一版共識（+9 萬）、記下首次公布值", e["cons"]["nfp"] == 90.0 and e["actual"]["nfp"] == 29, e)
S2 = dict(S, PAYEMS=rows("2026-07", [159000, 159073, 159150]))
ctx3 = dict(ctx2, _all_series=S2)
ctx3["_watch_extra"] = {"consensus": {"employment|2026-10-02": [{"label": "非農新增", "forecast": "+1.0 萬", "previous": ""}]}}
r = F.update(ctx3, False, tmp, manual=man, clev={}, today=dt.date(2026, 10, 5), do_recon=False)
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

print()
print("有失敗" if FAIL else "全部通過")
sys.exit(1 if FAIL else 0)
