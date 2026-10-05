"""2026-10 圖表改版：近 5 期、精簡走勢、瀑布、數線、傳導鏈、零軸細柱。"""
import sys
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import charts  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過  " if cond else "失敗  ") + name + (f" — {detail}" if detail and not cond else ""))
    ok = ok and bool(cond)


def mon(vals, y=2024, m=1):
    out = []
    for v in vals:
        out.append({"date": f"{y}-{m:02d}-01", "value": v})
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


# ---- 近 5 期 ----
h = charts.kpi_history(mon([0.1, 0.3, -0.04, 0.2, 0.25, 0.4, 0.1]), kind="change",
                       unit="%", fmt=lambda v: f"{v:+.1f}", ref=0.2, ref_label="0.2% 目標步速")
check("① 變動類只畫 5 期、用柱", h.count('class="kh-col"') == 5 and "kh-bar" in h
      and "kh-dot" not in h)
check("① 最新一期標 last", h.count("kh-bar last") == 1)
check("① -0.04 四捨五入後寫 0.0，不寫 -0.0", "-0.0" not in h and ">0.0<" in h)
check("① 有比較基準虛線與圖例", "kh-ref" in h and "0.2% 目標步速" in h)
h = charts.kpi_history(mon([4.1, 4.2, 4.3, 4.3, 4.4, 4.3]), kind="level", unit="%",
                       band=(4.0, 4.3), band_label="區間")
check("② 水準類用點＋連線、有區間淡底", h.count("kh-dot") == 5 and "polyline" in h
      and "kh-band" in h)
check("② 少於兩期不畫", charts.kpi_history(mon([1.0]), kind="level") == "")

# ---- 24 個月窗 ----
rows = mon([float(i) for i in range(40)])
lm = charts.last_months(rows, 24)
check("③ last_months 取 24 個月", len(lm) == 24 and lm[-1]["value"] == 39.0)

# ---- 精簡走勢 ----
h = charts.compact_lines([
    {"label": "A", "color": "#000", "points": mon([3, 3.2, 3.4, 3.1] * 10)},
    {"label": "B", "color": "#111", "points": mon([2.5, 2.6, 3.6, 2.4] * 10)},
], refs=[{"value": 3.5, "label": "參考"}], fill_between={"a": 0, "b": 1, "label": "A>B"})
check("④ 一張圖兩條線、一個 y 軸（刻度只有一組）",
      h.count("<polyline") == 2 and h.count('class="cl-x"') == 1)
check("④ 線下不塗面積（只有 fill_between 的多邊形）",
      all("var(--fillb" in m for m in re.findall(r"<polygon[^>]*>", h)))
check("④ hover 切片 24 個、圖例有最新值", h.count('class="cl-hit"') == 24 and "<b>3.1%</b>" in h)
check("④ 參考線標籤", "參考" in h)
check("④ 資料不足", "資料不足" in charts.compact_lines([{"label": "x", "color": "#0",
                                                          "points": mon([1])}]))

# ---- 瀑布 ----
h = charts.waterfall([{"label": "住房", "value": 0.1}, {"label": "能源", "value": -0.2},
                      {"label": "服務", "value": 0.3}])
names = re.findall(r'class="wf-name">([^<]+)', h)
check("⑤ 推升由大到小在前、壓低在後", names == ["服務", "住房", "能源"], names)
check("⑤ 推升紅、壓低藍", h.count("wf-seg up") == 2 and h.count("wf-seg dn") == 1)

# ---- 數線 ----
h = charts.number_line([{"label": "核心", "value": 2.45, "color": "#1"},
                        {"label": "中位數", "value": 2.58, "color": "#2"}], target=2.0,
                       target_label="2% 目標", digits=2)
check("⑥ 數線：點、目標、分列標籤", h.count("nl-dot") == 2 and "2% 目標" in h
      and h.count('class="nl-lab"') == 2)

# ---- 傳導鏈 ----
h = charts.chain([{"label": "a", "value": "1"}, {"label": "b", "value": "2"},
                  {"label": "c", "value": "3", "tone": "up"}], links=["x", "y"])
check("⑦ 傳導鏈三格兩箭頭", h.count('class="ch-step') == 3 and h.count("ch-arrow") == 2)

# ---- 零軸細柱 ----
h = charts.gap_columns(mon([0.5, -0.2, 1.0, 0.3] * 8), up_label="上", down_label="下")
check("⑧ 差距柱 24 期、正紅負藍、最新一期加深",
      h.count('class="gc-col"') == 24 and "gc-bar up on" in h and "gc-bar dn" in h)
h = charts.gap_columns([{"label": str(i), "value": 0.1 * i} for i in range(5)],
                       labels=True, highlight="4", digits=2, unit="")
check("⑧ 全部同號時零軸貼底", 'gc-zero" style="top:100%' in h and "gc-bar up on" in h)

if not ok:
    sys.exit(1)
print("\n全部通過")
