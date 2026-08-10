"""
通膨模組的分析層（P2）。

刻意重用勞動模組的歸因引擎——CPI 分項貢獻與產業貢獻的數學結構完全相同：

    貢獻 = 權重 × 變化率

差別只在勞動的「權重」是各產業自己的人數（隱含在水準值裡），
而 CPI 的權重要另外從 BLS 的相對重要性表帶進來。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .core import annualized, yoy, mom_pct, value_at
from .attribution import Contribution, AttributionResult


# 三個月年化低於這個值就不顯示分項百分比（避免總變動接近零時比例失真）
SHARE_FLOOR_PCT = 0.05


# ---------------------------------------------------------------------------
# CPI 分項貢獻
# ---------------------------------------------------------------------------
def attribute_cpi(
    headline_rows: list[dict],
    component_rows: dict[str, list[dict]],
    component_meta: list[dict],
    months: int = 1,
) -> AttributionResult:
    """
    把 CPI 的變化拆成各分項的貢獻（單位：百分點）。

    months=1  → 月變動的分項貢獻
    months=3  → 近三個月的分項貢獻（雜訊較低，建議主看這個）

    貢獻(百分點) = 該分項權重(%) / 100 × 該分項變化率(%)
    """
    total = _pct_change(headline_rows, months)
    if total is None:
        return AttributionResult(total=0.0)

    meta_by_id = {m["id"]: m for m in component_meta}
    contribs: list[Contribution] = []

    for sid, rows in component_rows.items():
        chg = _pct_change(rows, months)
        if chg is None:
            continue
        m = meta_by_id.get(sid, {})
        w = float(m.get("weight", 0))
        contribs.append(
            Contribution(
                key=sid,
                label=m.get("label", sid),
                value=w / 100 * chg,           # 百分點
                noncyclical=bool(m.get("laggy")),   # 借用這個旗標標示「落後項」
                order=m.get("order", 999),
            )
        )

    suppress = abs(total) < SHARE_FLOOR_PCT
    if not suppress and total:
        for c in contribs:
            c.share = c.value / total * 100

    explained = sum(c.value for c in contribs)
    core_services = sum(
        c.value for c in contribs
        if meta_by_id.get(c.key, {}).get("group") == "core_services"
    )
    supercore = sum(
        c.value for c in contribs if meta_by_id.get(c.key, {}).get("supercore")
    )
    shelter = sum(
        c.value for c in contribs if meta_by_id.get(c.key, {}).get("laggy")
    )
    food_energy = sum(
        c.value for c in contribs
        if meta_by_id.get(c.key, {}).get("group") == "food_energy"
    )

    return AttributionResult(
        total=total,
        contributions=sorted(contribs, key=lambda c: c.value, reverse=True),
        aggregates={
            "explained": explained,
            "core_services": core_services,
            "supercore": supercore,
            "shelter": shelter,
            "food_energy": food_energy,
            "ex_shelter": total - shelter,
        },
        share_suppressed=suppress,
        unexplained=total - explained,
    )


def _pct_change(rows: list[dict], months: int) -> float | None:
    """近 N 個月的累計變化率（%）。months=1 就是月變動。"""
    if len(rows) <= months:
        return None
    cur, old = rows[-1]["value"], rows[-1 - months]["value"]
    if old == 0:
        return None
    return (cur / old - 1) * 100


# ---------------------------------------------------------------------------
# 摘要指標
# ---------------------------------------------------------------------------
@dataclass
class InflationSummary:
    headline_yoy: float | None = None
    core_yoy: float | None = None
    core_mom: float | None = None
    core_3m: float | None = None      # 三個月年化
    core_6m: float | None = None
    supercore_3m: float | None = None
    shelter_3m: float | None = None
    core_goods_yoy: float | None = None
    ex_shelter_yoy: float | None = None
    pce_core_yoy: float | None = None
    median_cpi: float | None = None
    trimmed_cpi: float | None = None
    sticky_cpi: float | None = None
    expect_5y5y: float | None = None
    expect_1y: float | None = None
    gas: float | None = None
    oil_1m: float | None = None       # 油價近一個月變化 %
    extras: dict = field(default_factory=dict)


def summarize(series: dict[str, list[dict]], comp_meta: list[dict]) -> InflationSummary:
    s = InflationSummary()
    g = series.get

    s.headline_yoy = yoy(g("CPIAUCSL", []))
    s.core_yoy = yoy(g("CPILFESL", []))
    s.core_mom = mom_pct(g("CPILFESL", []))
    s.core_3m = annualized(g("CPILFESL", []), 3)
    s.core_6m = annualized(g("CPILFESL", []), 6)
    s.supercore_3m = annualized(g("CUSR0000SASLE", []), 3)
    s.shelter_3m = annualized(g("CUSR0000SAH1", []), 3)
    s.core_goods_yoy = yoy(g("CUSR0000SACL1E", []))
    s.pce_core_yoy = yoy(g("PCEPILFE", []))

    s.median_cpi = value_at(g("MEDCPIM158SFRBCLE", []))
    s.trimmed_cpi = value_at(g("TRMMEANCPIM158SFRBCLE", []))
    s.sticky_cpi = value_at(g("CORESTICKM159SFRBATL", []))
    s.expect_5y5y = value_at(g("T5YIFR", []))
    s.expect_1y = value_at(g("MICH", []))
    s.gas = value_at(g("GASREGW", []))

    oil = g("DCOILWTICO", [])
    if len(oil) > 21:
        cur, old = oil[-1]["value"], oil[-22]["value"]
        if old:
            s.oil_1m = (cur / old - 1) * 100

    # 核心除住房：用權重把住房的貢獻扣掉再還原
    core = g("CPILFESL", [])
    shelter = g("CUSR0000SAH1", [])
    if core and shelter:
        w_shelter = next((m.get("weight", 0) for m in comp_meta
                          if m.get("laggy")), 0)
        w_core = 100 - next((m.get("weight", 0) for m in comp_meta
                             if m.get("group") == "food_energy"), 0) \
            - next((m.get("weight", 0) for m in comp_meta
                    if m.get("group") == "food_energy" and m["id"] != "CPIUFDSL"), 0)
        cy, sy = yoy(core), yoy(shelter)
        if cy is not None and sy is not None and w_core > w_shelter > 0:
            # 核心指數裡住房佔的比重
            share = w_shelter / w_core
            s.ex_shelter_yoy = (cy - share * sy) / (1 - share)

    return s


# ---------------------------------------------------------------------------
# 通膨端的紅綠燈數值
# ---------------------------------------------------------------------------
def light_values(series: dict[str, list[dict]], summ: InflationSummary) -> dict[str, tuple]:
    """回傳 {key: (現值, 前值, 顯示字串)}，格式與勞動模組的燈號一致。"""
    out: dict[str, tuple] = {}

    def put(key, cur, prev, disp):
        out[key] = (cur, prev, disp)

    core = series.get("CPILFESL", [])
    if summ.core_3m is not None:
        prev = annualized(core[:-1], 3) if len(core) > 4 else None
        put("core_cpi_3m", summ.core_3m, prev, f"{summ.core_3m:.1f}%")

    sc = series.get("CUSR0000SASLE", [])
    if summ.supercore_3m is not None:
        prev = annualized(sc[:-1], 3) if len(sc) > 4 else None
        put("supercore_3m", summ.supercore_3m, prev, f"{summ.supercore_3m:.1f}%")

    pce = series.get("PCEPILFE", [])
    if summ.pce_core_yoy is not None:
        prev = yoy(pce[:-1]) if len(pce) > 13 else None
        put("core_pce_yoy", summ.pce_core_yoy, prev, f"{summ.pce_core_yoy:.1f}%")

    med = series.get("MEDCPIM158SFRBCLE", [])
    if summ.median_cpi is not None:
        put("median_cpi", summ.median_cpi, value_at(med, 1), f"{summ.median_cpi:.1f}%")

    if summ.ex_shelter_yoy is not None:
        put("core_ex_shelter", summ.ex_shelter_yoy, None, f"{summ.ex_shelter_yoy:.1f}%")

    t = series.get("T5YIFR", [])
    if summ.expect_5y5y is not None:
        put("expect_5y5y", summ.expect_5y5y, value_at(t, 1), f"{summ.expect_5y5y:.2f}%")

    gasr = series.get("GASREGW", [])
    if summ.gas is not None:
        put("gas_price", summ.gas, value_at(gasr, 1), f"${summ.gas:.2f}")

    cg = series.get("CUSR0000SACL1E", [])
    if summ.core_goods_yoy is not None:
        prev = yoy(cg[:-1]) if len(cg) > 13 else None
        put("core_goods_yoy", summ.core_goods_yoy, prev, f"{summ.core_goods_yoy:+.1f}%")

    return out
