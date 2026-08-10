"""
長端利率、債務動態與供給壓力（P5）。

一頁的主軸
----------
勞動、通膨、聯準會三個模組解釋的是**政策利率**該往哪走。
但 30 年期公債殖利率不是聯準會決定的——它由**債券供給與期限溢酬**決定。

所以這一頁問的是不同的問題：誰在借錢、借多少、市場要多少補償才願意借。
政府與 hyperscaler 競爭的是同一池的存續期間需求，放在一起才看得出全貌。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .core import value_at, diff


# ---------------------------------------------------------------------------
# 一、殖利率曲線與利率拆解
# ---------------------------------------------------------------------------
@dataclass
class CurveState:
    levels: dict = field(default_factory=dict)        # {label: value}
    changes_1m: dict = field(default_factory=dict)
    slope_10_2: float | None = None
    slope_30_10: float | None = None
    inverted: bool = False
    term_premium: float | None = None
    tp_change_3m: float | None = None
    decomposition: dict = field(default_factory=dict)  # 名目 10Y 的三段拆解
    note: str = ""


def curve_state(s: dict[str, list[dict]]) -> CurveState:
    c = CurveState()
    tenors = [("3M", "DGS3MO"), ("2Y", "DGS2"), ("5Y", "DGS5"),
              ("10Y", "DGS10"), ("30Y", "DGS30")]
    for label, sid in tenors:
        rows = s.get(sid) or []
        if not rows:
            continue
        c.levels[label] = value_at(rows)
        # 一個月前（日頻約 22 個交易日）
        if len(rows) > 23:
            c.changes_1m[label] = rows[-1]["value"] - rows[-23]["value"]

    if "10Y" in c.levels and "2Y" in c.levels:
        c.slope_10_2 = c.levels["10Y"] - c.levels["2Y"]
        c.inverted = c.slope_10_2 < 0
    if "30Y" in c.levels and "10Y" in c.levels:
        c.slope_30_10 = c.levels["30Y"] - c.levels["10Y"]

    tp = s.get("THREEFYTP10") or []
    if tp:
        c.term_premium = value_at(tp)
        if len(tp) > 64:
            c.tp_change_3m = tp[-1]["value"] - tp[-64]["value"]

    # ---- 名目 10Y = 實質 + 通膨補償（期限溢酬含在其中）----
    nom = c.levels.get("10Y")
    real = value_at(s.get("DFII10") or [])
    be = value_at(s.get("T10YIE") or [])
    if nom is not None and real is not None and be is not None:
        c.decomposition = {
            "nominal": nom,
            "real": real,
            "breakeven": be,
            "residual": nom - real - be,      # 應接近零，用來檢查資料一致性
            "term_premium": c.term_premium,
        }
        c.note = ("名目殖利率 ＝ 實質利率 ＋ 通膨補償。"
                  "期限溢酬是另一個角度的拆解，衡量投資人持有長債要求的額外補償，"
                  "與上述兩項有重疊，不可直接相加。")
    return c


# ---------------------------------------------------------------------------
# 二、政府債務動態
# ---------------------------------------------------------------------------
@dataclass
class DebtState:
    debt_gdp: float | None = None
    deficit_gdp: float | None = None
    interest_gdp: float | None = None
    interest_to_revenue: float | None = None
    effective_rate: float | None = None       # 債務的有效利率 i
    nominal_growth: float | None = None       # 名目 GDP 成長 g
    r_minus_g: float | None = None            # 實質利率 − 實質成長
    i_minus_g: float | None = None            # 名目：有效利率 − 名目成長
    stabilizing_pb: float | None = None       # 穩定債務比所需的基本盈餘（% GDP）
    actual_pb: float | None = None            # 實際基本盈餘（% GDP）
    pb_gap: float | None = None               # 差距＝問題的規模
    verdict: str = "unknown"
    note: str = ""


def debt_state(s: dict[str, list[dict]], real_10y: float | None = None,
               real_growth: float | None = None) -> DebtState:
    """
    財政損益兩平：在目前的利率、成長與債務水準下，
    基本盈餘要到多少，債務佔 GDP 才不再上升。

        穩定所需的基本盈餘 ≈ 債務比 × (i − g) / (1 + g)

    i 用債務的有效利率（利息支出 ÷ 債務餘額），g 用名目 GDP 成長。
    實際基本盈餘與這個數字的差距，就是財政缺口的規模。
    """
    d = DebtState()
    debt = s.get("GFDEBTN") or []          # 百萬美元
    debt_gdp = s.get("GFDEGDQ188S") or []  # %
    interest = s.get("A091RC1Q027SBEA") or []   # 十億，年率
    receipts = s.get("FGRECPT") or []
    outlays = s.get("FGEXPND") or []
    gdp = s.get("GDP") or []               # 十億，年率

    d.debt_gdp = value_at(debt_gdp)

    if interest and gdp:
        d.interest_gdp = value_at(interest) / value_at(gdp) * 100
    if interest and receipts and value_at(receipts):
        d.interest_to_revenue = value_at(interest) / value_at(receipts) * 100

    # 有效利率 i = 年化利息支出 ÷ 債務餘額
    if interest and debt:
        debt_bn = value_at(debt) / 1000.0          # 百萬 → 十億
        if debt_bn:
            d.effective_rate = value_at(interest) / debt_bn * 100

    # 名目 GDP 成長（年增）
    if len(gdp) > 4:
        old = gdp[-5]["value"]
        if old:
            d.nominal_growth = (value_at(gdp) / old - 1) * 100

    # 赤字與基本盈餘
    if receipts and outlays and gdp:
        bal = value_at(receipts) - value_at(outlays)
        d.deficit_gdp = bal / value_at(gdp) * 100          # 負值代表赤字
        if d.interest_gdp is not None:
            # 基本盈餘 ＝ 財政餘額 ＋ 利息支出（把利息排除在外）
            d.actual_pb = d.deficit_gdp + d.interest_gdp

    # 財政損益兩平
    if (d.debt_gdp is not None and d.effective_rate is not None
            and d.nominal_growth is not None):
        i, g = d.effective_rate / 100, d.nominal_growth / 100
        d.i_minus_g = (i - g) * 100
        d.stabilizing_pb = d.debt_gdp * (i - g) / (1 + g)
        if d.actual_pb is not None:
            d.pb_gap = d.actual_pb - d.stabilizing_pb

    if real_10y is not None and real_growth is not None:
        d.r_minus_g = real_10y - real_growth

    # 判定
    if d.pb_gap is not None:
        if d.pb_gap < -2.0:
            d.verdict = "widening"
        elif d.pb_gap < -0.5:
            d.verdict = "drifting"
        else:
            d.verdict = "stable"

    d.note = ("穩定所需的基本盈餘 ≈ 債務比 × (有效利率 − 名目成長) ÷ (1 + 名目成長)。"
              "基本盈餘是排除利息支出後的財政餘額——"
              "利息是過去累積的結果，把它排除才看得出當期財政的實際狀況。")
    return d


DEBT_VERDICT = {
    "widening": ("債務比將持續上升",
                 "實際基本盈餘遠低於穩定債務所需的水準，在利率不下降的前提下，"
                 "債務佔 GDP 會持續攀升。這會反映在期限溢酬上。"),
    "drifting": ("債務比緩步上升",
                 "財政缺口存在但不劇烈。若利率下行或成長加速，缺口可能自行收斂。"),
    "stable": ("債務比大致穩定",
               "目前的基本盈餘足以抵消利息負擔與成長的落差。"),
    "unknown": ("資料不足", ""),
}


# ---------------------------------------------------------------------------
# 三、Hyperscaler 資本支出與發債
# ---------------------------------------------------------------------------
@dataclass
class Hyperscalers:
    as_of: str = ""
    total_capex: float = 0.0
    total_ocf: float = 0.0
    total_issued: float = 0.0
    capex_yoy: float | None = None
    capex_to_ocf: float | None = None
    n_cash_negative: int = 0          # 資本支出超過營運現金流的家數
    ig_share: float | None = None     # 發債佔投資級市場比重
    companies: list = field(default_factory=list)
    verdict: str = "unknown"
    verified: bool = False
    note: str = ""


def hyperscalers(cfg: dict, ig_quarterly: float | None = None) -> Hyperscalers:
    """
    關鍵不是資本支出的絕對金額，是**融資方式**。

    capex ÷ 營運現金流 超過 100% 代表自由現金流轉負，資本支出必須靠
    舉債或動用現金支應。那正是這幾家從「現金充裕的買方」變成
    「投資級市場大型供給方」的轉折點——它們開始跟公債競爭同一批買盤。
    """
    h = Hyperscalers(as_of=cfg.get("as_of", ""), verified=bool(cfg.get("verified")))
    comps = cfg.get("companies") or []
    if not comps:
        h.note = "尚未填入資料"
        return h

    weighted_yoy_num = 0.0
    for c in comps:
        capex = float(c.get("capex") or 0)
        ocf = float(c.get("ocf") or 0)
        issued = float(c.get("debt_issued") or 0)
        ratio = (capex / ocf * 100) if ocf else None
        h.total_capex += capex
        h.total_ocf += ocf
        h.total_issued += issued
        if ratio is not None and ratio > 100:
            h.n_cash_negative += 1
        if c.get("capex_yoy") is not None:
            weighted_yoy_num += capex * float(c["capex_yoy"])
        h.companies.append({
            "name": c.get("name", ""), "ticker": c.get("ticker", ""),
            "capex": capex, "ocf": ocf, "issued": issued,
            "revenue": float(c.get("revenue") or 0),
            "capex_yoy": c.get("capex_yoy"),
            "capex_to_ocf": ratio,
            "cash_negative": ratio is not None and ratio > 100,
        })

    if h.total_capex:
        h.capex_yoy = weighted_yoy_num / h.total_capex
    if h.total_ocf:
        h.capex_to_ocf = h.total_capex / h.total_ocf * 100
    if ig_quarterly:
        h.ig_share = h.total_issued / ig_quarterly * 100

    # 判定
    if h.capex_to_ocf is not None:
        if h.n_cash_negative >= 2 or h.capex_to_ocf > 90:
            h.verdict = "debt_funded"
        elif h.capex_to_ocf > 70:
            h.verdict = "transitioning"
        else:
            h.verdict = "cash_funded"

    h.note = ("資本支出 ÷ 營運現金流 超過 100% 代表自由現金流轉負。"
              "這幾家一旦由現金支應轉為舉債支應，就成為投資級市場的大型供給方，"
              "與公債競爭同一批存續期間需求。")
    return h


HS_VERDICT = {
    "cash_funded": ("資本支出仍由現金流支應",
                    "營運現金流足以覆蓋資本支出，對債券市場的供給壓力有限。"),
    "transitioning": ("正在轉向舉債支應",
                      "資本支出已接近營運現金流的上限，再擴張就必須舉債。"
                      "這是供給壓力的前置訊號。"),
    "debt_funded": ("已轉為舉債支應",
                    "資本支出超過營運現金流，多家公司自由現金流轉負。"
                    "這幾家已成為投資級市場的大型供給方，"
                    "與公債競爭同一批存續期間需求，會推升整體長端利率。"),
    "unknown": ("資料不足", ""),
}


# ---------------------------------------------------------------------------
# 四、供給壓力綜合判斷
# ---------------------------------------------------------------------------
@dataclass
class SupplyPressure:
    score: float = 0.0                # 正＝壓力大
    level: str = "moderate"           # low | moderate | high
    parts: list = field(default_factory=list)


def supply_pressure(curve: CurveState, debt: DebtState,
                    hs: Hyperscalers, ig_oas: float | None) -> SupplyPressure:
    """
    四個來源各自給分，並列出貢獻，避免變成不可解釋的黑箱。
    """
    sp = SupplyPressure()
    total = 0.0

    if curve.term_premium is not None:
        v = (curve.term_premium - 0.4) * 2.0
        total += v
        sp.parts.append({"label": "期限溢酬",
                         "detail": f"{curve.term_premium:+.2f}%（基準 0.40%）",
                         "score": v})
    if curve.slope_30_10 is not None:
        v = (curve.slope_30_10 - 0.6) * 2.0
        total += v
        sp.parts.append({"label": "30 年減 10 年",
                         "detail": f"{curve.slope_30_10:+.2f}%（基準 0.60%）",
                         "score": v})
    if debt.pb_gap is not None:
        v = min(max(-debt.pb_gap * 0.5, -2.0), 2.0)
        total += v
        sp.parts.append({"label": "財政缺口",
                         "detail": f"基本盈餘較穩定水準低 {abs(debt.pb_gap):.1f}% GDP",
                         "score": v})
    if hs.capex_to_ocf is not None:
        v = (hs.capex_to_ocf - 70) / 25
        total += v
        sp.parts.append({"label": "科技巨頭融資缺口",
                         "detail": f"資本支出佔營運現金流 {hs.capex_to_ocf:.0f}%",
                         "score": v})
    if ig_oas is not None:
        v = (ig_oas - 1.0) * 1.5
        total += v
        sp.parts.append({"label": "投資級利差",
                         "detail": f"{ig_oas:.2f}%（基準 1.00%）",
                         "score": v})

    sp.score = total
    sp.level = "high" if total > 1.5 else ("low" if total < -1.0 else "moderate")
    sp.parts.sort(key=lambda p: abs(p["score"]), reverse=True)
    return sp


PRESSURE_TEXT = {
    "high": ("長端供給壓力：偏高",
             "債券供給大於需求，投資人要求更高的補償才願意持有長天期債券。"
             "在這種環境下，即使聯準會降息，長端殖利率也可能不跟著下降——"
             "曲線會走陡而非平行下移。"),
    "moderate": ("長端供給壓力：中性",
                 "供給與需求大致平衡，長端主要跟隨政策利率預期移動。"),
    "low": ("長端供給壓力：偏低",
            "需求充足，長端有下行空間。降息時長天期債券的漲幅可能大於短天期。"),
}
