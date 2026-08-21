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

from .core import value_at
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
    # 統計顯著性：UNRATE 只到小數一位，0.1 個百分點的變動在 BLS 自己的標準下
    # 不可分辨於零。方向照樣講，但**不能用 alert 級的口氣講**——
    # alert 在鷹鴿淨值裡權重 2.0，兩條就能翻動九宮格的列。
    sig = d.get("significant", True)
    sev = (lambda s: s if sig else "info")
    thr = d.get("signif_threshold", 0.2)
    # 完整的顯著性說明主場在「失業率變動分解」卡，這裡只留半句
    noise = ("" if sig else
             f"（{abs(d['delta_rate']):.1f} 個百分點低於顯著門檻"
             f" {thr:.1f}，強度別當真。）")

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
            severity=sev("alert"),
            headline="失業率下降源於勞動力退出，而非就業增加",
            detail=(
                f"失業率下降 {abs(d['delta_rate']):.2f} 個百分點，表面上是好消息。"
                f"{emp_clause}"
                f"同時有 {fmt.wan_abs(d['delta_labor_force'])}乾脆放棄找工作、"
                "退出職場——失業率是被這批人壓低的，"
                "完整拆解見下方「失業率變動分解」。" + noise
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
                + noise
            ),
            lean="hawkish",
            impact="就業穩健，聯準會沒有急著降息的理由",
        )
    if v == "bad_rise":
        return Flag(
            key="bad_rise",
            severity=sev("alert"),
            headline="失業率上升源於就業減少",
            detail=(
                f"有工作的人減少 {fmt.wan_abs(d['delta_employed'])}，"
                f"失業人數增加 {fmt.wan_abs(d['delta_unemployed'])}。"
                "不是因為找工作的人變多，而是實際的工作機會在減少。"
                + noise
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
                + noise
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
                f"{fmt.wan(rev.ma3_before_revision)}掉到 {fmt.wan(rev.ma3_now)}"
                "——為什麼會修正，見下方「歷史數據修正」卡。"
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
# 10. 續領／初領背離＋再就業指標（新聞看不到、但最早轉弱的形態）
# ---------------------------------------------------------------------------
@rule
def r_claims_divergence(ctx: RuleContext) -> Flag | None:
    """
    初領還在低段、續領已在高段：沒什麼人被裁，但被裁的人找不到下一份。
    這是勞動市場轉弱最早出現的形態之一，只看初領完全看不到。
    位置用近一年的百分位——申請件數的絕對水準隨勞動力規模漂移，
    水準本身不可比。
    """
    ic, cc = ctx.series.get("ICSA", []), ctx.series.get("CCSA", [])
    if len(ic) < 52 or len(cc) < 52:
        return None

    def _rank(rows):
        window = [r["value"] for r in rows[-52:]]
        return sum(1 for x in window if x < rows[-1]["value"]) / len(window) * 100
    ic_rank, cc_rank = _rank(ic), _rank(cc)
    if cc_rank >= 80 and ic_rank < 60:
        return Flag(
            key="claims_divergence", severity="watch",
            headline="裁員未加速，但被裁的人找不到工作",
            detail=(
                f"初領失業金位在近一年的第 {ic_rank:.0f} 百分位（不高），"
                f"續領卻在第 {cc_rank:.0f} 百分位的高段。"
                "新失業的人沒變多、領補助的人卻一直沒減少——"
                "代表被裁的人遲遲找不到下一份工作。"
            ),
            lean="dovish", impact="再就業難度上升，先於失業率反映",
        )
    return None


@rule
def r_duration_high(ctx: RuleContext) -> Flag | None:
    """失業持續期間中位數創近一年新高：申請件數講「多少人」，這條講「多久」。"""
    med = ctx.series.get("UEMPMED", [])
    if len(med) < 13:
        return None
    cur = med[-1]["value"]
    prior = [r["value"] for r in med[-13:-1]]
    if cur >= max(prior) and cur > min(prior):
        return Flag(
            key="duration_high", severity="watch",
            headline="失業持續期間創近一年新高",
            detail=(
                f"失業者找到下一份工作的中位數時間來到 {cur:.1f} 週，"
                "是近一年最長。它不受勞動力規模與補助資格影響，"
                "跟續領人數是兩個獨立的角度——同時變差，再就業變難才算確認。"
            ),
            lean="dovish", impact="再就業所需時間拉長",
        )
    return None


# ---------------------------------------------------------------------------
# 11. 壯年就業比與隱藏性失業（失業率之外的水溫計）
# ---------------------------------------------------------------------------
@rule
def r_prime_age_slide(ctx: RuleContext) -> Flag | None:
    epop = ctx.series.get("LNS12300060", [])
    if len(epop) < 4:
        return None
    v = [r["value"] for r in epop[-4:]]
    # 連三個月不升、且累計下滑至少 0.2 個百分點（資料只到小數一位，
    # 門檻要壓過捨入雜訊）
    if v[0] - v[3] >= 0.2 and v[0] >= v[1] >= v[2] >= v[3]:
        return Flag(
            key="prime_age_slide", severity="watch",
            headline="壯年就業比例連續三個月下滑",
            detail=(
                f"25–54 歲有工作的比例從 {v[0]:.1f}% 滑到 {v[3]:.1f}%。"
                "這個比例剔除了退休與就學的干擾，是失業率之外最乾淨的"
                "就業水溫計——失業率可以因為錯的原因好看，它比較難。"
            ),
            lean="dovish", impact="核心族群的就業正在轉弱",
        )
    return None


@rule
def r_u6_gap_widening(ctx: RuleContext) -> Flag | None:
    u6, u3 = ctx.series.get("U6RATE", []), ctx.series.get("UNRATE", [])
    if len(u6) < 7 or len(u3) < 7:
        return None
    gap_now = u6[-1]["value"] - u3[-1]["value"]
    gap_then = u6[-7]["value"] - u3[-7]["value"]
    if gap_now - gap_then >= 0.3:
        return Flag(
            key="u6_gap_widening", severity="watch",
            headline="隱藏性失業半年來明顯擴大",
            detail=(
                f"廣義失業率（含想全職只能兼職、想工作但沒在找的人）與"
                f"失業率的差距，半年內從 {gap_then:.1f} 擴大到 {gap_now:.1f} "
                "個百分點。表面失業率還好看，底下的低度就業已經在增加。"
            ),
            lean="dovish", impact="表面失業率低估了實際的鬆動",
        )
    return None


# ---------------------------------------------------------------------------
# 12. 兩條領先型金絲雀：派遣與工時（先於裁員反映）
# ---------------------------------------------------------------------------
@rule
def r_temp_help(ctx: RuleContext) -> Flag | None:
    """
    臨時支援服務就業。企業縮編的順序是：先不續派遣、再砍工時、最後才裁
    正職——派遣年增轉負歷史上領先整體就業轉弱兩三季。
    只在「轉負而且還在惡化」時報：長期小幅為負的常態不佔版面。
    """
    th = ctx.series.get("TEMPHELPS", [])
    if len(th) < 16:
        return None

    def _yoy(back=0):
        cur, base = th[-1 - back]["value"], th[-13 - back]["value"]
        return (cur / base - 1) * 100 if base else None
    y_now, y_prev = _yoy(0), _yoy(3)
    if y_now is None or y_prev is None:
        return None
    if y_now < 0 and y_now < y_prev:
        return Flag(
            key="temp_help_falling", severity="watch",
            headline="派遣就業年減且仍在惡化",
            detail=(
                f"臨時支援服務就業年減 {abs(y_now):.1f}%（三個月前年減 "
                f"{abs(y_prev):.1f}%）。企業縮編會先不續派遣、最後才裁正職，"
                "所以這條歷史上領先整體就業轉弱好幾個季度。"
            ),
            lean="dovish", impact="裁員週期的前導指標在惡化",
        )
    return None


@rule
def r_factory_hours(ctx: RuleContext) -> Flag | None:
    """製造業平均週工時：裁人之前先砍工時。近三月均明顯低於近一年均才報。"""
    wh = ctx.series.get("AWHMAN", [])
    if len(wh) < 12:
        return None
    ma3 = sum(r["value"] for r in wh[-3:]) / 3
    ma12 = sum(r["value"] for r in wh[-12:]) / 12
    if ma12 - ma3 >= 0.2:
        return Flag(
            key="factory_hours_cut", severity="watch",
            headline="製造業週工時被砍",
            detail=(
                f"製造業平均週工時近三個月平均 {ma3:.1f} 小時，低於近一年"
                f"平均的 {ma12:.1f} 小時。企業需求轉弱時會先減班、再裁員——"
                "工時是裁員的前導。"
            ),
            lean="dovish", impact="工時先於裁員反映需求轉弱",
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
