"""
規則引擎 — 確定性的交叉檢查。

設計原則（重要）
----------------
量化與判定一律走這裡的硬規則，**不交給 LLM**。
理由：LLM 每次跑的結果會飄，時間序列就不可比、無法畫圖、無法回測。

文字撰寫原則
------------
讀者是投資人，不是勞動經濟學家。所以：
  * headline 用白話講「發生了什麼」，不用專有名詞
  * detail 補上數字，並解釋這個數字為什麼重要
  * impact 直接講對利率的意義（利升息／利降息），不要讓讀者自己推
專有名詞若非用不可，就在同一句話裡解釋掉。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .core import diff_series, moving_avg, value_at
from .. import fmt


@dataclass
class Flag:
    key: str
    severity: str          # info | watch | alert
    headline: str          # 白話結論
    detail: str            # 數字與解釋
    lean: str = "neutral"  # hawkish=利升息 / dovish=利降息 / neutral
    impact: str = ""       # 對利率的意義，一句話


@dataclass
class RuleContext:
    """規則引擎的輸入。分析模組算完後統一塞進來。"""
    series: dict[str, list[dict]] = field(default_factory=dict)
    attribution: object | None = None
    unrate_decomp: dict = field(default_factory=dict)
    revisions: object | None = None
    wage_comp: dict = field(default_factory=dict)
    lights: list = field(default_factory=list)


RULES: list[Callable[[RuleContext], Flag | None]] = []


def rule(fn):
    RULES.append(fn)
    return fn


# ---------------------------------------------------------------------------
# 1. 失業率下降的品質
# ---------------------------------------------------------------------------
@rule
def r_bad_decline(ctx: RuleContext) -> Flag | None:
    d = ctx.unrate_decomp
    if not d:
        return None

    v = d.get("verdict")
    if v == "bad_decline":
        # bad_decline 只保證「勞動力退出主導」，就業本身可能增也可能減——
        # 文案必須跟著正負號走，不能一律寫「有工作的人少了」。
        de = d.get("delta_employed")
        if de is not None and de < 0:
            emp_clause = f"但真正有工作的人其實少了 {fmt.wan_abs(de)}，"
        elif de is not None:
            emp_clause = f"但就業僅微增 {fmt.wan_abs(de)}，"
        else:
            emp_clause = ""
        return Flag(
            key="bad_decline",
            severity="alert",
            headline="失業率下降源於勞動力退出，而非就業增加",
            detail=(
                f"失業率下降 {abs(d['delta_rate']):.2f} 個百分點，表面上是好消息。"
                f"{emp_clause}"
                f"同時有 {fmt.wan_abs(d['delta_labor_force'])}乾脆放棄找工作、退出職場。"
                "放棄找工作的人不會被算成失業，所以失業率反而被壓低了。"
            ),
            lean="dovish",
            impact="就業市場實際在轉弱",
        )
    if v == "good_decline":
        return Flag(
            key="good_decline",
            severity="info",
            headline="失業率下降由就業增加帶動",
            detail=(
                f"有工作的人增加 {fmt.wan_abs(d['delta_employed'])}，"
                f"失業率因此下降 {abs(d['delta_rate']):.2f} 個百分點。這是健康的下降。"
            ),
            lean="hawkish",
            impact="就業穩健，聯準會沒有急著降息的理由",
        )
    if v == "bad_rise":
        return Flag(
            key="bad_rise",
            severity="alert",
            headline="失業率上升源於就業減少",
            detail=(
                f"有工作的人減少 {fmt.wan_abs(d['delta_employed'])}，"
                f"失業人數增加 {fmt.wan_abs(d['delta_unemployed'])}。"
                "不是因為找工作的人變多，而是實際的工作機會在減少。"
            ),
            lean="dovish",
            impact="工作機會實際在減少",
        )
    if v == "supply_rise":
        return Flag(
            key="supply_rise",
            severity="info",
            headline="失業率上升源於勞動力擴張",
            detail=(
                f"投入職場的人增加 {fmt.wan_abs(d['delta_labor_force'])}，"
                "新加入的人還沒馬上找到工作，所以失業率上升。這通常不是壞事。"
            ),
            lean="neutral",
            impact="不必過度解讀",
        )
    return None


# ---------------------------------------------------------------------------
# 2. 修正
# ---------------------------------------------------------------------------
@rule
def r_revision_swamps(ctx: RuleContext) -> Flag | None:
    rev = ctx.revisions
    if rev is None or rev.two_month_net is None:
        return None
    latest = rev.recent[-1].current if rev.recent else None
    if latest is None:
        return None
    if rev.two_month_net < 0 and abs(rev.two_month_net) > abs(latest):
        return Flag(
            key="revision_swamps",
            severity="alert",
            headline="前兩月大幅下修，實質動能弱於初值",
            detail=(
                f"政府這次把前兩個月的就業人數合計往下修了 "
                f"{fmt.wan_abs(rev.two_month_net)}，比本月的變動量還大。"
                f"把修正算進去後，近三個月平均每月新增從 "
                f"{fmt.wan(rev.ma3_before_revision)}掉到 {fmt.wan(rev.ma3_now)}。"
                "就業數據第一次公布時是估算值，之後兩個月會用更完整的資料重算。"
            ),
            lean="dovish",
            impact="就業動能比初值顯示的更弱",
        )
    return None


@rule
def r_revision_bias(ctx: RuleContext) -> Flag | None:
    rev = ctx.revisions
    if rev is None or rev.bias_12m is None:
        return None
    if rev.bias_direction == "systematically_down":
        return Flag(
            key="revision_bias_down",
            severity="watch",
            headline="初值近一年呈系統性下修",
            detail=(
                f"過去 12 個月，每個月的就業人數平均事後被往下修 "
                f"{fmt.wan_abs(rev.bias_12m)}。"
                "看到剛公布的數字時，要記得它之後很可能被調降。"
            ),
            lean="dovish",
            impact="初值應打折看待",
        )
    if rev.bias_direction == "systematically_up":
        return Flag(
            key="revision_bias_up",
            severity="watch",
            headline="初值近一年呈系統性上修",
            detail=(
                f"過去 12 個月，每個月平均事後被往上修 {fmt.wan_abs(rev.bias_12m)}。"
            ),
            lean="hawkish",
            impact="實際就業可能比初值更強",
        )
    return None


# ---------------------------------------------------------------------------
# 3. 兩份調查分歧
# ---------------------------------------------------------------------------
@rule
def r_survey_divergence(ctx: RuleContext) -> Flag | None:
    ces, cps = ctx.series.get("PAYEMS", []), ctx.series.get("CE16OV", [])
    if len(ces) < 2 or len(cps) < 2:
        return None
    d_ces = ces[-1]["value"] - ces[-2]["value"]
    d_cps = cps[-1]["value"] - cps[-2]["value"]
    if d_ces * d_cps < 0 and abs(d_ces - d_cps) > 200:
        return Flag(
            key="survey_divergence",
            severity="watch",
            headline="機構調查與家庭調查方向背離",
            detail=(
                "美國政府用兩種方式統計就業：問企業（算出非農就業人數）"
                "和問家庭（算出失業率）。"
                f"這次一個顯示 {fmt.wan(d_ces)}、另一個顯示 {fmt.wan(d_cps)}，方向相反。"
                "兩者不一致時，通常要再觀察一兩個月才能確定趨勢。"
            ),
            lean="neutral",
            impact="訊號不明確，建議多觀察",
        )
    return None


# ---------------------------------------------------------------------------
# 4. 就業成長的廣度
# ---------------------------------------------------------------------------
@rule
def r_narrow_growth(ctx: RuleContext) -> Flag | None:
    att = ctx.attribution
    if att is None or not att.contributions:
        return None
    breadth = att.aggregates.get("breadth", 100)
    n = len(att.contributions)
    if breadth < 45:
        return Flag(
            key="narrow_growth",
            severity="watch",
            headline="就業成長廣度不足",
            detail=(
                f"統計的 {n} 個行業裡，只有 {round(breadth*n/100)} 個在增加就業。"
                "景氣好的時候通常是多數行業一起徵人；集中在少數行業，"
                "代表成長的基礎不夠穩固。"
            ),
            lean="dovish",
            impact="成長基礎不夠穩固",
        )
    return None


@rule
def r_cyclical_negative(ctx: RuleContext) -> Flag | None:
    att = ctx.attribution
    if att is None:
        return None
    cyc = att.aggregates.get("cyclical")
    if cyc is not None and cyc < 0 <= att.total:
        return Flag(
            key="cyclical_negative",
            severity="alert",
            headline="剔除非週期性部門後為負成長",
            detail=(
                f"整體看起來增加 {fmt.wan(att.total)}，但醫療、社福與各級政府"
                "的用人比較不受景氣影響，長期都在增加。"
                f"把這些扣掉之後，真正跟景氣連動的行業合計 {fmt.wan(cyc)}。"
            ),
            lean="dovish",
            impact="景氣敏感的行業正在收縮",
        )
    return None


# ---------------------------------------------------------------------------
# 5. 職缺與招聘背離
# ---------------------------------------------------------------------------
@rule
def r_openings_vs_hiring(ctx: RuleContext) -> Flag | None:
    jol, hir = ctx.series.get("JTSJOL", []), ctx.series.get("JTSHIR", [])
    if len(jol) < 2 or len(hir) < 2:
        return None
    d_jol = jol[-1]["value"] - jol[-2]["value"]
    d_hir = hir[-1]["value"] - hir[-2]["value"]
    if d_jol > 0 and d_hir < -0.05:
        return Flag(
            key="openings_vs_hiring",
            severity="watch",
            headline="職缺增加但招聘率同步下降",
            detail=(
                f"公開的職缺數增加 {fmt.wan(d_jol, unit='萬個')}，但實際錄取率反而下降。"
                "代表不少職缺只是掛在網站上，企業沒有急著補人。"
            ),
            lean="dovish",
            impact="求職者實際更難找到工作",
        )
    return None


# ---------------------------------------------------------------------------
# 6. 低招聘低裁員
# ---------------------------------------------------------------------------
@rule
def r_low_hire_low_fire(ctx: RuleContext) -> Flag | None:
    hir, ld = ctx.series.get("JTSHIR", []), ctx.series.get("JTSLDR", [])
    if not hir or not ld:
        return None
    h, l = value_at(hir), value_at(ld)
    if h is None or l is None:
        return None
    if h < 3.5 and l < 1.2:
        return Flag(
            key="low_hire_low_fire",
            severity="info",
            headline="低招聘、低裁員格局延續",
            detail=(
                f"每月錄取的人約佔總就業的 {h:.1f}%、被裁員的約 {l:.1f}%，兩個都在低檔。"
                "對已經有工作的人來說相對安全，但正在找工作的人會非常辛苦。"
            ),
            lean="neutral",
            impact="就業市場凍結，短期影響有限",
        )
    return None


# ---------------------------------------------------------------------------
# 7. 續領失業金
# ---------------------------------------------------------------------------
@rule
def r_continuing_claims(ctx: RuleContext) -> Flag | None:
    cc = ctx.series.get("CCSA", [])
    if len(cc) < 27:
        return None
    cur = cc[-1]["value"]
    prior_max = max(r["value"] for r in cc[-27:-1])
    if cur >= prior_max:
        return Flag(
            key="continuing_claims_high",
            severity="alert",
            headline="續領失業金升至近半年高點",
            detail=(
                f"持續在領失業補助的人數來到 {fmt.persons_to_wan(cur)}，是近半年最高。"
                "這個數字比「新增失業人數」更能看出再就業的難度——"
                "領補助的人一直沒減少，代表他們遲遲找不到新工作。"
            ),
            lean="dovish",
            impact="失業後再就業的難度上升",
        )
    return None


# ---------------------------------------------------------------------------
# 8. 薪資的統計錯覺
# ---------------------------------------------------------------------------
@rule
def r_wage_composition(ctx: RuleContext) -> Flag | None:
    w = ctx.wage_comp
    if not w or w.get("composition_bias") == "neutral":
        return None
    if w["composition_bias"] == "overstated":
        return Flag(
            key="wage_overstated",
            severity="watch",
            headline="平均時薪受組成效果高估",
            detail=(
                f"整體平均時薪年增 {w['yoy_all']:.2f}%，"
                f"但基層員工（不含主管）只有 {w['yoy_production']:.2f}%。"
                "當低薪的工作先消失時，剩下的人平均薪水自然被拉高，"
                "看起來像在加薪，其實不是。實際的薪資通膨壓力比表面小。"
            ),
            lean="dovish",
            impact="薪資通膨沒有表面嚴重",
        )
    return Flag(
        key="wage_understated",
        severity="watch",
        headline="非管理職薪資增速高於總體",
        detail=(
            f"整體平均時薪年增 {w['yoy_all']:.2f}%，"
            f"但基層員工（不含主管）達 {w['yoy_production']:.2f}%。"
            "基層薪資是服務業成本的主要來源，漲得比整體快，"
            "代表薪資推動的通膨壓力比整體數字顯示的更大。"
        ),
        lean="hawkish",
        impact="薪資推動的通膨壓力比表面大",
    )


# ---------------------------------------------------------------------------
# 9. 衰退警訊
# ---------------------------------------------------------------------------
@rule
def r_sahm(ctx: RuleContext) -> Flag | None:
    for lt in ctx.lights:
        if lt.key == "sahm" and lt.value is not None:
            if lt.value >= 0.50:
                return Flag(
                    "sahm_trigger", "alert", "Sahm 法則已觸發衰退門檻",
                    f"這個指標看的是「失業率的近三個月平均，比過去一年的最低點高多少」。"
                    f"目前 +{lt.value:.2f}，超過 0.50 的門檻。"
                    "歷史上每次超過這個門檻，美國都已經進入衰退。",
                    "dovish", "歷史上每次觸發都對應到衰退",
                )
            if lt.value >= 0.30:
                return Flag(
                    "sahm_approaching", "watch", "Sahm 法則接近觸發門檻",
                    f"這個指標看的是「失業率的近三個月平均，比過去一年的最低點高多少」。"
                    f"目前 +{lt.value:.2f}，距離 0.50 的警戒門檻還有 {0.50-lt.value:.2f}。"
                    "歷史上超過門檻時，美國都已經進入衰退。",
                    "dovish", "尚未觸發，但方向偏弱",
                )
    return None


# ---------------------------------------------------------------------------
def run_rules(ctx: RuleContext) -> list[Flag]:
    order = {"alert": 0, "watch": 1, "info": 2}
    flags = [f for f in (r(ctx) for r in RULES) if f is not None]
    flags.sort(key=lambda f: order.get(f.severity, 9))
    return flags


def lean_balance(flags: list[Flag]) -> dict:
    """統計旗標的利率傾向 — 這也是情境合成層（P4）的輸入接口。"""
    w = {"alert": 2.0, "watch": 1.0, "info": 0.5}
    dov = sum(w.get(f.severity, 0.5) for f in flags if f.lean == "dovish")
    haw = sum(w.get(f.severity, 0.5) for f in flags if f.lean == "hawkish")
    net = haw - dov
    if net > 1:
        tilt = "hawkish"
    elif net < -1:
        tilt = "dovish"
    else:
        tilt = "balanced"
    return {"dovish": dov, "hawkish": haw, "net": net, "tilt": tilt}
