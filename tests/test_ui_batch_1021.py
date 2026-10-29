"""2026-10-21 批次：快報預估後備、今明兩天排序、各家預測收合、x 軸標籤疏化、折線圖放大資料、大卡一次只開一個。"""
import sys, pathlib, datetime as dt, json, re
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.analysis import stories as st          # noqa: E402
from src.pages import forecasts_ui as FU        # noqa: E402
from src import charts, site                    # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過  " if cond else "失敗  ") + name + (f" — {detail}" if detail and not cond else ""))
    ok &= bool(cond)


# ① PPI：ForexFactory 週曆已查不到 → 用存檔的預估
ctx = {"inflation": {"ppi": {"mom": 1.3, "core_mom_1d": 0.7, "period": "2026-09",
                             "cons": {"ppi_mom": 0.6, "core_ppi_mom": 0.3}}, "kpi": {}},
       "_watch_extra": {"consensus": {}}}
rel = {"ppi": {"first_seen": "2026-10-16T20:40:00+08:00"}}
L = st.latest_release(ctx, rel)
check("① PPI 預估過週後改用存檔：預估 0.6%、高於預估", L and L["rows"][0]["forecast"] == "0.6%" and L["rows"][0]["vs"] == "高於預估", L)
# ② CPI：用各家預測的市場共識（期別要對）
ctx2 = {"inflation": {"kpi": {"core_display": "0.3%", "headline_display": "0.6%"}, "data_month": "2026-09"},
        "_forecasts": {"releases": {"cpi|2026-09": {"key": "cpi", "period": "2026-09", "date": "2026-10-14",
                                                    "cons": {"core_mom": 0.2, "cpi_mom": 0.6}},
                                    "cpi|2026-08": {"key": "cpi", "period": "2026-08", "date": "2026-09-11",
                                                    "cons": {"core_mom": 0.4, "cpi_mom": 0.1}}}}}
L2 = st.latest_release(ctx2, {"inflation": {"first_seen": "2026-10-14T20:35:00+08:00"}})
check("② CPI 預估後備：核心 0.2%（高於）、CPI 0.6%（符合）",
      L2 and L2["rows"][0]["forecast"] == "0.2%" and L2["rows"][0]["vs"] == "高於預估"
      and L2["rows"][1]["vs"] == "符合預估", L2)
# ③ 非農：千人 → 萬
ctx3 = {"labor": {"kpi": {"nfp_display": "+11.9 萬人", "u3_display": "4.1%"}, "data_month": "2026-09"},
        "_forecasts": {"releases": {"e": {"key": "employment", "period": "2026-09", "cons": {"nfp": 50, "u3": 4.2}}}}}
L3 = st.latest_release(ctx3, {"labor": {"first_seen": "2026-10-03T20:35:00+08:00"}})
check("③ 非農預估換成萬：+5.0 萬、高於預估；失業率 4.2% 低於預估",
      L3 and L3["rows"][0]["forecast"] == "+5.0 萬" and L3["rows"][0]["vs"] == "高於預估"
      and L3["rows"][1]["vs"] == "低於預估", L3)

# ④ 今明兩天依時間排序（休市在前、時間未定在後）
src = (ROOT / "src" / "pages" / "home.py").read_text(encoding="utf-8")
check("④ 今明兩天：建置端依時間排序", '_up.sort(key=lambda x: (x["date"], 0 if x["k"] == "h"' in src)

# ⑤ 各家預測：公布當天、隔天自動展開；其他天收合＋一句摘要
rel5 = {"cpi|2026-09": {"key": "cpi", "period": "2026-09", "date": "2026-10-14", "cons": {"cpi_mom": 0.6}},
        "pce|2026-09": {"key": "pce", "period": "2026-09", "date": "2026-10-29"}}
d5 = FU.open_days(rel5)
check("⑤ 展開日：CPI 10/14、10/15；PCE 10/29、10/30",
      d5.get("2026-10-14") == "cpi" and d5.get("2026-10-15") == "cpi" and d5.get("2026-10-30") == "pce" and "2026-10-16" not in d5, d5)
h_open = FU.section({"releases": rel5}, dt.date(2026, 10, 15))
h_shut = FU.section({"releases": rel5}, dt.date(2026, 10, 21))
check("⑥ 2026-10-29 起一律預設收合：公布隔天只先切到 CPI 分頁；平常收合、有摘要",
      'class="fc-fold" open' not in h_open and 'class="fc-fold" data-open' in h_open and 'id="fc-t-cpi" class="fc-in" checked' in h_open
      and 'class="fc-fold" data-open' in h_shut and 'class="fc-sum"' in h_shut and "PCE 10/29" in h_shut)

# ⑦ x 軸疏化：16 年的年份標籤，手機只留 ≤5 個
pts = [{"date": f"{2011 + i // 12}-{i % 12 + 1:02d}-01", "value": i % 7} for i in range(190)]
h7 = charts.compact_lines([{"label": "a", "color": "red", "points": pts}], months=190, xmonths=True)
spans = re.findall(r'<span class="([^"]*)" style="left:[^"]*">(\d{4})</span>', h7)
mob = [y for c, y in spans if not c]
check("⑦ 長期圖年份：手機顯示 ≤5 個、最後一年一定保留", 0 < len(mob) <= 5 and spans[-1][0] == "", spans)
# ⑧ 放大：資料層帶原始值與 data-zoom
check("⑧ 折線圖資料層帶 v 與 data-zoom", 'data-zoom=' in h7 and '&quot;v&quot;:' in h7)
check("⑨ 柱狀圖日期標籤疏化", " xm" in charts.diverging_stacked(
    [{"date": f"2025-{m:02d}-01", "a": 1, "net": 1} for m in range(1, 13)] * 2, [("a", "A", "red")], ("net", "N", "black")))
js = site.__dict__.get("_JS") or ""
srcs = (ROOT / "src" / "site.py").read_text(encoding="utf-8")
check("⑩ 大卡一次只開一個（排除展開全部、錨點、讀者沒點的）",
      "details.card.sect[open]" in srcs and "bulkUntil" in srcs and "userOpen" in srcs)
check("⑪ 放大手勢：雙擊、雙點、兩指", "dblclick" in srcs and "pinch" in srcs and "zoomIn(el" in srcs)

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
