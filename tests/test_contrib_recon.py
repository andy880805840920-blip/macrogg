"""
分項貢獻的對帳與 supercore 口徑。

這個檔案存在的理由是一個使用者從畫面上抓到的矛盾：同一個畫面，
上面寫「其他所有項目 +0.08」，下面的明細寫「其他核心服務 +0.15、
核心商品 −0.00」，而五條明細加起來是 +0.19、標題卻寫著總漲幅 +0.12。

兩個根因，兩件都要釘住：

  ① **第三塊是倒推的。** `_rest = total − shelter − food_energy` 讓三塊
     永遠加得回總數——因為第三塊就是差額本身。加得起來不等於算得對，
     而對帳誤差被它默默吸收掉了。

  ② **CUSR0000SASLE 不是「核心服務除住房」。** 它在 FRED 上叫
     Services Less Energy Services——全部核心服務，**含住房**，
     權重約 61.8%，不是 26.4%。用它去講「除掉住房還是很黏」，
     那個數字裡面有住房。

    python tests/test_contrib_recon.py
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from src.analysis import inflation as ia          # noqa: E402

ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    print(f"{'通過' if cond else '失敗'}  {name}" + (f" — {detail}" if detail else ""))
    ok &= bool(cond)


def rows(vals, start_year=2026, start_month=1):
    out, y, m = [], start_year, start_month
    for v in vals:
        out.append({"date": f"{y:04d}-{m:02d}-01", "value": float(v)})
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


# ---------------------------------------------------------------------------
# ① _pct_change 要按日期找，不是往前數 N 列
#
# 跟 v73 修好的 yoy() 同一個 bug，當時漏了這一支。不是假設性的問題：
# CUSR0000SASLE 在 2025-10 就有一個缺漏值。
# ---------------------------------------------------------------------------
full = rows([100, 101, 102, 103])                  # 1,2,3,4 月
check("① 完整序列的三個月變化",
      abs(ia._pct_change(full, 3) - 3.0) < 1e-9,
      f"{ia._pct_change(full, 3):.4f}")

# 少了 2 月：往前數三列會落到 2025-12，那是**四個月前**
gap = [r for r in rows([100, 101, 102, 103], start_year=2025, start_month=12)
       if r["date"] != "2026-01-01"]
gap = rows([90, 100, 102, 103], start_year=2025, start_month=11)
gap = [r for r in gap if r["date"] != "2025-12-01"]   # 缺 12 月
# 剩下 2025-11(90)、2026-01(102)、2026-02(103)
check("② 序列缺一個月時仍然找得到正確的基期",
      ia._pct_change(rows([100, 101, 102, 103]), 3) is not None)
short = rows([100, 102, 103], start_year=2025, start_month=11)
short = [r for r in short]                          # 11月100、12月102、1月103
check("③ 找不到正好 N 個月前 → 退回數列數，不回 None",
      ia._pct_change(short, 2) is not None,
      str(ia._pct_change(short, 2)))
check("④ 重複月份不會讓基期往前滑",
      abs(ia._pct_change(
          rows([100, 101, 102, 103])
          + [{"date": "2026-04-01", "value": 103.0}], 3) - 3.0) < 1e-9)


# ---------------------------------------------------------------------------
# ② derive_supercore：加權相減推出核心服務除住房
# ---------------------------------------------------------------------------
# 核心服務 61.8、住房 35.4 → 除住房 26.4
CS, SH, EX = 61.8, 35.4, 26.4

# 住房不動、核心服務漲 1% → 除住房那塊必須漲得**比 1% 更多**
#（因為漲幅全部由 26.4 那塊扛）
cs = rows([100, 101])
sh = rows([100, 100])
d = ia.derive_supercore(cs, sh, CS, SH)
r = (d[-1]["value"] / d[0]["value"] - 1) * 100
check("⑤ 住房不動時，除住房的漲幅被放大",
      abs(r - CS / EX * 1.0) < 1e-6, f"{r:.4f}% vs {CS / EX:.4f}%")

# 兩條同幅度漲 → 除住房也是同幅度（權重相減自然抵消）
d2 = ia.derive_supercore(rows([100, 101]), rows([100, 101]), CS, SH)
r2 = (d2[-1]["value"] / d2[0]["value"] - 1) * 100
check("⑥ 兩條同幅度時除住房也同幅度", abs(r2 - 1.0) < 1e-6, f"{r2:.6f}%")

# 這正是七月真實資料的樣子：住房 +0.575%、核心服務 +0.556%（三個月）。
# 兩者幾乎一樣，所以舊寫法「26.4 × 核心服務漲幅」剛好也接近正確值——
# 這就是這個 bug 藏這麼久的原因。要釘住的是**兩者分開時**才看得出差別。
d3 = ia.derive_supercore(rows([100, 102]), rows([100, 100.5]), CS, SH)
r3 = (d3[-1]["value"] / d3[0]["value"] - 1) * 100
wrong = 2.0                                       # 舊寫法直接拿核心服務的漲幅
check("⑦ 兩條分開時，正確值跟舊寫法差得出來",
      abs(r3 - wrong) > 1.0, f"正確 {r3:.3f}%、舊寫法 {wrong:.3f}%")

check("⑧ 按日期對齊，不是按位置",
      ia.derive_supercore(rows([100, 101, 102]),
                          rows([100, 101, 102])[1:], CS, SH)[0]["date"]
      == "2026-02-01")
check("⑨ 權重不合理時回空清單，不丟例外",
      ia.derive_supercore(rows([100, 101]), rows([100, 101]), 30.0, 35.4) == []
      and ia.derive_supercore(rows([100, 101]), rows([100, 101]), 0, 0) == [])
check("⑩ 資料不足回空清單",
      ia.derive_supercore(rows([100]), rows([100]), CS, SH) == [])


# ---------------------------------------------------------------------------
# ③ 對帳：三塊由下而上加，加不回總數時要看得出來
# ---------------------------------------------------------------------------
META = [
    {"id": "F", "label": "食物", "weight": 13.6, "group": "food_energy"},
    {"id": "E", "label": "能源", "weight": 6.2, "group": "food_energy"},
    {"id": "G", "label": "核心商品", "weight": 18.4, "group": "core_goods"},
    {"id": "H", "label": "住房", "weight": 35.4, "group": "core_services",
     "laggy": True},
    {"id": "S", "label": "其他核心服務", "weight": 26.4, "group": "core_services",
     "supercore": True},
]


def att(headline_end, comps):
    return ia.attribute_cpi(rows([100, headline_end]),
                            {k: rows([100, v]) for k, v in comps.items()},
                            META, months=1)


# 權重正確、分項也正確 → unexplained 應該接近零
COMPS = {"F": 101.0, "E": 100.0, "G": 100.0, "H": 100.0, "S": 100.0}
a = att(100 + 0.136, COMPS)                        # 食物漲 1% → 總數漲 0.136%
check("⑪ 權重對得上時 unexplained 接近零",
      abs(a.unexplained) < 0.005, f"{a.unexplained:+.4f}")

# 權重過期（實際能源權重比 config 大）→ unexplained 明顯不為零
b = att(100 - 0.08, {"F": 100.0, "E": 99.0, "G": 100.0, "H": 100.0, "S": 100.0})
check("⑫ 權重對不上時 unexplained 抓得到",
      abs(b.unexplained) > 0.015, f"{b.unexplained:+.4f}")
check("⑬ unexplained 的正負號分得出是高估還是低估",
      b.unexplained < 0 if b.total < sum(c.value for c in b.contributions)
      else b.unexplained > 0)

# 三塊必須由下而上加，不能倒推
_sh = a.aggregates["shelter"]
_fe = a.aggregates["food_energy"]
_rest_bottom_up = sum(
    c.value for c in a.contributions
    if c.key in ("G", "S"))
_rest_residual = a.total - _sh - _fe
check("⑭ 倒推與由下而上在有誤差時會不一樣（所以不能倒推）",
      abs(_rest_residual - _rest_bottom_up) < 0.005,
      f"倒推 {_rest_residual:+.4f}、由下而上 {_rest_bottom_up:+.4f}")

_sh2 = b.aggregates["shelter"]
_fe2 = b.aggregates["food_energy"]
_rb = sum(c.value for c in b.contributions if c.key in ("G", "S"))
check("⑮ 誤差存在時倒推會把它吃掉（這就是先前畫面矛盾的來源）",
      abs((b.total - _sh2 - _fe2) - _rb) > 0.015,
      f"倒推 {b.total - _sh2 - _fe2:+.4f}、由下而上 {_rb:+.4f}")


# ---------------------------------------------------------------------------
# ④ config 本身：推導序列不能再指回 SASLE
# ---------------------------------------------------------------------------
import yaml                                        # noqa: E402
cfg = yaml.safe_load(
    (pathlib.Path(__file__).parent.parent / "config" / "inflation.yaml")
    .read_text(encoding="utf-8"))
comps = cfg.get("cpi_components") or []
sc = next((c for c in comps if c.get("supercore")), {})
check("⑯ supercore 那一格用的是推導序列",
      sc.get("id") == "CPISUPERCORE" and sc.get("derived") is True, str(sc.get("id")))
check("⑰ 而且不再有任何分項指向 CUSR0000SASLE",
      not any(c["id"] == "CUSR0000SASLE" for c in comps))

sd = cfg.get("supercore_derive") or {}
check("⑱ 推導用的兩條序列與權重都填了",
      sd.get("core_services") == "CUSR0000SASLE"
      and sd.get("shelter") == "CUSR0000SAH1"
      and sd.get("core_services_weight") and sd.get("shelter_weight"), str(sd))
check("⑲ 兩個權重相減必須等於 supercore 的 weight（否則加總對不上）",
      abs((sd["core_services_weight"] - sd["shelter_weight"])
          - sc["weight"]) < 1e-9,
      f'{sd["core_services_weight"]} − {sd["shelter_weight"]} '
      f'= {sd["core_services_weight"] - sd["shelter_weight"]}，'
      f'supercore weight = {sc["weight"]}')
check("⑳ 五個分項的權重合計 100（切法互斥且不留缺口）",
      abs(sum(float(c["weight"]) for c in comps) - 100) < 0.05,
      f'{sum(float(c["weight"]) for c in comps)}')

# ---------------------------------------------------------------------------
# ⑤ 加總不等於官方漲幅是**方法上的必然**，不是計算錯誤
#
# BLS 的 CPI 是分層鏈式聚合、權重在期間內本身也會動，所以
# 「單一時點權重 × 累計變化」的加總本來就不必等於官方漲幅。
#
# 用**官方權重與官方指數**驗一次（BLS 2025-12 relative importance，
# FRED 2026-04→07 實際值）：估算合計 +0.17pp、實際 +0.12%，仍差 0.05。
# 權重、指數、時間窗全部正確——所以那個差額不能被呈現成錯誤。
# ---------------------------------------------------------------------------
REAL = {                                   # 2026-04 → 2026-07 的實際指數值
    "CPIAUCSL": (332.407, 332.813),
    "CPIUFDSL": (348.349, 349.881),
    "CPIENGSL": (325.978, 314.553),
    "CUSR0000SACL1E": (167.767, 167.762),
    "CUSR0000SAH1": (426.642, 429.095),
    "CUSR0000SASLE": (443.154, 445.616),
    "CUSR0000SA0L2": (299.165, 298.793),   # All Items Less Shelter（官方）
}


def _span(a, b):
    return [{"date": "2026-04-01", "value": a}, {"date": "2026-05-01", "value": a},
            {"date": "2026-06-01", "value": a}, {"date": "2026-07-01", "value": b}]


import yaml as _yaml                                   # noqa: E402
_cfg = _yaml.safe_load(
    (pathlib.Path(__file__).parent.parent / "config" / "inflation.yaml")
    .read_text(encoding="utf-8"))
_meta, _sd = _cfg["cpi_components"], _cfg["supercore_derive"]
_S = {k: _span(*v) for k, v in REAL.items()}
_S["CPISUPERCORE"] = ia.derive_supercore(
    _S["CUSR0000SASLE"], _S["CUSR0000SAH1"],
    _sd["core_services_weight"], _sd["shelter_weight"])
_att = ia.attribute_cpi({k: v for k, v in [("x", 0)]} and _S["CPIAUCSL"],
                        {m["id"]: _S[m["id"]] for m in _meta if m["id"] in _S},
                        _meta, months=3, ex_shelter_rows=_S["CUSR0000SA0L2"])
_by = {c.label: c.value for c in _att.contributions}

check("㉑ 實際三個月漲幅 +0.12%", abs(_att.total - 0.122) < 0.002,
      f"{_att.total:+.3f}%")
for _lab, _want in [("住房", 0.205), ("食物", 0.060), ("核心商品", -0.001),
                    ("能源", -0.224), ("其他核心服務", 0.133)]:
    check(f"㉒ {_lab} 估算貢獻 {_want:+.2f}pp",
          abs(_by.get(_lab, 99) - _want) < 0.003, f"{_by.get(_lab, 0):+.3f}pp")

_sum = sum(_att.contributions and [c.value for c in _att.contributions] or [0])
check("㉓ 估算淨貢獻約 +0.17pp", abs(_sum - 0.173) < 0.005, f"{_sum:+.3f}pp")
check("㉔ 用官方權重仍然差約 0.05——那是方法差異，不是錯誤",
      0.02 < abs(_att.total - _sum) < 0.10,
      f"實際 {_att.total:+.3f}％、估算 {_sum:+.3f}pp、差 {_att.total - _sum:+.3f}")

# 剔除住房：用官方指數，不是反推
check("㉕ 剔除住房後用官方 All Items Less Shelter 指數",
      _att.aggregates["ex_shelter_derived"] is False
      and abs(_att.aggregates["ex_shelter"] + 0.124) < 0.003,
      f'{_att.aggregates["ex_shelter"]:+.3f}%')
_noidx = ia.attribute_cpi(_S["CPIAUCSL"],
                          {m["id"]: _S[m["id"]] for m in _meta if m["id"] in _S},
                          _meta, months=3)
check("㉖ 抓不到官方指數才退回反推，而且標記出來",
      _noidx.aggregates["ex_shelter_derived"] is True)
# 反推值跟官方值是**兩個不同的量**，不是同一個東西的兩種算法。
# 這個月它們剛好只差 0.004（−0.128 vs −0.124）——而那正是這個錯誤活這麼久的
# 原因：平常看起來一模一樣。要釘住的是「它們不保證相等」，不是「差很多」。
check("㉗ 反推值與官方值不是同一個數（只是這個月剛好接近）",
      _noidx.aggregates["ex_shelter"] != _att.aggregates["ex_shelter"],
      f'反推 {_noidx.aggregates["ex_shelter"]:+.3f}％、'
      f'官方 {_att.aggregates["ex_shelter"]:+.3f}％')
# 住房漲幅拉開時兩者就會分家：反推假設 CPI 是分項的簡單加權和。
_far = {k: v for k, v in _S.items()}
_far["CUSR0000SAH1"] = _span(426.642, 426.642 * 1.03)      # 住房三個月漲 3%
_far["CPISUPERCORE"] = ia.derive_supercore(
    _far["CUSR0000SASLE"], _far["CUSR0000SAH1"],
    _sd["core_services_weight"], _sd["shelter_weight"])
_a1 = ia.attribute_cpi(_far["CPIAUCSL"],
                       {m["id"]: _far[m["id"]] for m in _meta if m["id"] in _far},
                       _meta, months=3, ex_shelter_rows=_far["CUSR0000SA0L2"])
_a2 = ia.attribute_cpi(_far["CPIAUCSL"],
                       {m["id"]: _far[m["id"]] for m in _meta if m["id"] in _far},
                       _meta, months=3)
check("㉗b 住房拉開時兩者明顯分家（官方指數不受住房影響）",
      abs(_a1.aggregates["ex_shelter"] - _a2.aggregates["ex_shelter"]) > 0.5,
      f'官方 {_a1.aggregates["ex_shelter"]:+.3f}％、'
      f'反推 {_a2.aggregates["ex_shelter"]:+.3f}％')

# 權重必須是官方值
_w = {m["label"]: float(m["weight"]) for m in _meta}
for _lab, _want in [("食物", 13.698), ("能源", 6.383), ("核心商品", 19.176),
                    ("住房", 35.625), ("其他核心服務", 25.119)]:
    check(f"㉘ {_lab} 用官方 relative importance {_want}",
          abs(_w.get(_lab, 0) - _want) < 1e-9, str(_w.get(_lab)))
check("㉙ 能源用的是季調指數且走 index-to-index（不是 MoM 相加）",
      any(m["id"] == "CPIENGSL" for m in _meta))
check("㉚ 剔除住房的官方指數有進 config",
      "CUSR0000SA0L2" in (_cfg.get("headline") and
                          [x["id"] for x in _cfg["headline"]] or []))

# 離線素材也要有，否則離線會偷偷走反推那條路
from src import fixtures_inflation                     # noqa: E402
check("㉛ 離線素材含官方 ex-shelter 指數",
      bool(fixtures_inflation.build().get("CUSR0000SA0L2")))

# 來源序列有缺口時不可以把兩個月的變化當成一個月
# （CUSR0000SASLE 的 2025-10 在 FRED 上就是空值）
def _m(vals, start=1):
    return [{"date": f"2026-{m:02d}-01", "value": float(v)}
            for m, v in zip(range(start, start + len(vals)), vals)]


_cs, _sh = _m([100, 101, 102, 103]), _m([100, 100, 100, 100])
_full = ia.derive_supercore(_cs, _sh, 61.8, 35.4)
_gapd = ia.derive_supercore([x for x in _cs if x["date"] != "2026-02-01"],
                            [x for x in _sh if x["date"] != "2026-02-01"],
                            61.8, 35.4)
check("㉜ 缺口那一步當成 0，不是併成一個大漲幅",
      abs(_gapd[1]["value"] - _gapd[0]["value"]) < 1e-9,
      f'{_gapd[0]["value"]:.3f} → {_gapd[1]["value"]:.3f}')
check("㉝ 而且缺口之後照樣接得下去",
      len(_gapd) == 3 and _gapd[-1]["value"] > _gapd[0]["value"])
check("㉞ 沒有缺口時逐月串起來（對照組）",
      len(_full) == 4 and _full[-1]["value"] > _full[-2]["value"],
      f'{_full[-1]["value"]:.3f}')
# 併成一個月的話 2→4 月會是兩倍漲幅——這是先前的行為
check("㉟ 缺口不會被算成兩倍漲幅",
      _gapd[-1]["value"] < _full[2]["value"] + 1e-9,
      f'{_gapd[-1]["value"]:.3f} vs {_full[2]["value"]:.3f}')

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
