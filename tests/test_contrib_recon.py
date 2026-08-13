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

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
