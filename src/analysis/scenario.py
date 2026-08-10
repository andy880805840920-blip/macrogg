"""
情境合成（P4）。

把勞動與通膨兩條腿合成一個政策情境。

為什麼要這樣做
--------------
聯準會是雙重使命。同一份就業數據，在通膨 2.0% 和 3.5% 的環境下
會導向完全相反的決定。所以任何只看單邊的結論都是不完整的——
這一層就是把兩邊擺在一起看。

九宮格內部再用 FOMC 文本的語氣校準：同一格，聯準會措辭偏鷹或偏鴿
會導向不同的路徑判斷。

輸出刻意**不給機率**。理由：機率市場早就定價了，研究員的價值在於
指出「我的判讀與市場定價哪裡不同」，而不是複述市場價格。
"""

from __future__ import annotations

from dataclasses import dataclass, field


LABOR_LEVELS = ["弱", "中", "強"]
INFL_LEVELS = ["低", "中", "高"]


# 九宮格：(勞動, 通膨) → (情境名稱, 說明, 政策傾向)
GRID = {
    ("強", "低"): ("溫和成長", "就業穩、通膨低。聯準會沒有壓力，可以慢慢來。", "neutral"),
    ("強", "中"): ("小心觀望", "就業穩但通膨還沒回到目標，聯準會會傾向按兵不動。", "neutral"),
    ("強", "高"): ("升息壓力", "經濟過熱。就業強加上通膨高，聯準會可能重新考慮緊縮。", "hawkish"),
    ("中", "低"): ("預防性降息", "通膨已受控，就業開始鬆動。聯準會有空間先降息保險。", "dovish"),
    ("中", "中"): ("按兵不動", "兩邊都不極端，這份數據不足以改變方向。", "neutral"),
    ("中", "高"): ("兩難", "通膨還高但就業轉弱。聯準會會被迫在兩個目標間取捨。", "hawkish"),
    ("弱", "低"): ("衰退式降息", "就業明顯轉弱、通膨不是問題。聯準會會加速降息。", "dovish"),
    ("弱", "中"): ("轉向降息", "就業惡化成為主要考量，通膨的阻力正在消退。", "dovish"),
    ("弱", "高"): ("停滯性通膨", "最棘手的情況。降息會助長通膨，升息會加深衰退。", "hawkish"),
}

# 情境 → 固定收益的部位方向（僅為框架對照，不構成投資建議）
# 部位方向刻意用白話寫。專有名詞（牛陡、熊平）放在括號裡供對照，
# 但主要敘述要讓沒有固收背景的人也讀得懂。
POSITIONING = {
    "衰退式降息": {
        "殖利率曲線": "短天期利率降得比長天期多，曲線變陡（牛陡）",
        "債券存續期間": "拉長。降息時長天期債券漲最多",
        "抗通膨債券": "相對一般公債走弱，因為通膨預期同步下降",
        "公司債利差": "走闊。景氣轉差時投資人要求更高的風險補償"},
    "轉向降息": {
        "殖利率曲線": "偏向變陡",
        "債券存續期間": "偏長",
        "抗通膨債券": "略為走弱",
        "公司債利差": "偏向走闊"},
    "預防性降息": {
        "殖利率曲線": "短天期先降，曲線變陡（牛陡）",
        "債券存續期間": "偏長",
        "抗通膨債券": "大致持平",
        "公司債利差": "偏向收斂，因為景氣還沒壞"},
    "按兵不動": {
        "殖利率曲線": "區間震盪",
        "債券存續期間": "中性",
        "抗通膨債券": "大致持平",
        "公司債利差": "區間，主要賺票息（carry）"},
    "小心觀望": {
        "殖利率曲線": "區間震盪",
        "債券存續期間": "中性",
        "抗通膨債券": "大致持平",
        "公司債利差": "區間，主要賺票息"},
    "溫和成長": {
        "殖利率曲線": "略為變陡",
        "債券存續期間": "中性",
        "抗通膨債券": "略為走弱",
        "公司債利差": "偏向收斂"},
    "兩難": {
        "殖利率曲線": "偏向變平",
        "債券存續期間": "縮短",
        "抗通膨債券": "走強，因為通膨預期升溫",
        "公司債利差": "走闊"},
    "升息壓力": {
        "殖利率曲線": "短天期被推高，曲線變平（熊平）",
        "債券存續期間": "縮短。升息時長天期跌最多",
        "抗通膨債券": "走強",
        "公司債利差": "偏向走闊"},
    "停滯性通膨": {
        "殖利率曲線": "短天期被通膨推高、長天期被衰退壓低，曲線變平（熊平）",
        "債券存續期間": "縮短",
        "抗通膨債券": "走強，這是少數同時受惠的資產",
        "公司債利差": "走闊。企業獲利與融資成本兩頭受壓"},
}


@dataclass
class Trigger:
    label: str
    current: str
    threshold: str
    distance: str
    met: bool = False


@dataclass
class Scenario:
    labor_state: str
    infl_state: str
    name: str
    description: str
    lean: str
    positioning: dict = field(default_factory=dict)
    triggers: list[Trigger] = field(default_factory=list)
    drivers: list[str] = field(default_factory=list)
    fomc_note: str = ""
    incomplete: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
def classify_labor(score: float | None, tilt: dict | None) -> str:
    """綜合分數為主，旗標傾向為輔。"""
    if score is None:
        return "中"
    if score <= -0.45:
        return "弱"
    if score >= 0.45:
        return "強"
    # 分數在中間帶時，用旗標的鷹鴿淨值推一把
    net = (tilt or {}).get("net", 0)
    if net <= -3:
        return "弱"
    if net >= 3:
        return "強"
    return "中"


def classify_inflation(core_pce_yoy: float | None,
                       core_3m: float | None) -> str:
    """
    以核心 PCE 相對 2% 目標為主軸，再用三個月年化的動能修正。

    只看年增率會太遲鈍（被一年前的基期拖住），
    只看三個月年化又太吵，所以兩個一起看。
    """
    if core_pce_yoy is None:
        return "中"
    level = core_pce_yoy
    if core_3m is not None:
        # 動能與水準各半，讓轉折早一點反映
        level = 0.6 * core_pce_yoy + 0.4 * core_3m
    if level < 2.3:
        return "低"
    if level > 2.9:
        return "高"
    return "中"


# ---------------------------------------------------------------------------
def synthesise(labor: dict | None, inflation: dict | None,
               fomc: dict | None = None) -> Scenario:
    """
    labor     : {"score": float, "tilt": dict, "flags": [...]}
    inflation : {"core_pce_yoy": float, "core_3m": float, "flags": [...]}
    fomc      : {"direction": str, "label": str, "delta": float}
    任何一項為 None 就標記為「資料不完整」，並在畫面上明示。
    """
    incomplete = []
    if not labor:
        incomplete.append("勞動市場")
    if not inflation:
        incomplete.append("通膨")
    if not fomc:
        incomplete.append("聯準會文本")

    l_state = classify_labor((labor or {}).get("score"), (labor or {}).get("tilt"))
    i_state = classify_inflation((inflation or {}).get("core_pce_yoy"),
                                 (inflation or {}).get("core_3m"))

    name, desc, lean = GRID[(l_state, i_state)]

    sc = Scenario(labor_state=l_state, infl_state=i_state, name=name,
                  description=desc, lean=lean,
                  positioning=dict(POSITIONING.get(name, {})),
                  incomplete=incomplete)

    # ---- 推動這個判定的主要因素 ----
    for f in (labor or {}).get("flags", [])[:2]:
        sc.drivers.append(f"勞動｜{f.headline}")
    for f in (inflation or {}).get("flags", [])[:2]:
        sc.drivers.append(f"通膨｜{f.headline}")

    # ---- FOMC 語氣校準 ----
    if fomc:
        d = fomc.get("direction")
        if d == "hawkish" and lean == "dovish":
            sc.fomc_note = ("聯準會的措辭比數據更鷹。數據雖然偏向降息，"
                            "但官方措辭尚未跟上，實際轉向可能比數據暗示的慢。")
        elif d == "dovish" and lean == "hawkish":
            sc.fomc_note = ("聯準會的措辭比數據更鴿。可能是官員看到了數據還沒反映的訊號，"
                            "值得留意。")
        elif d in ("hawkish", "dovish"):
            trans = {"hawkish": "利升息", "dovish": "利降息"}[d]
            sc.fomc_note = (f"聯準會措辭與數據方向一致"
                            f"（{fomc.get('label', '')}＝{trans}方向），判讀的信心較高。")
        else:
            sc.fomc_note = "聯準會措辭沒有明顯變化，方向主要由數據決定。"

    # ---- 跨入相鄰格的觸發條件 ----
    sc.triggers = _triggers(labor, inflation, l_state, i_state)
    return sc


def _triggers(labor: dict | None, inflation: dict | None,
              l_state: str, i_state: str) -> list[Trigger]:
    out: list[Trigger] = []

    score = (labor or {}).get("score")
    if score is not None:
        if l_state != "弱":
            gap = score - (-0.45)
            out.append(Trigger("勞動轉「弱」", f"綜合分數 {score:+.2f}",
                               "跌破 −0.45", f"還差 {gap:.2f}", gap <= 0))
        if l_state != "強":
            gap = 0.45 - score
            out.append(Trigger("勞動轉「強」", f"綜合分數 {score:+.2f}",
                               "升破 +0.45", f"還差 {gap:.2f}", gap <= 0))

    pce = (inflation or {}).get("core_pce_yoy")
    c3 = (inflation or {}).get("core_3m")
    if pce is not None:
        blended = 0.6 * pce + 0.4 * c3 if c3 is not None else pce
        if i_state != "低":
            gap = blended - 2.3
            out.append(Trigger("通膨轉「低」", f"綜合通膨水準 {blended:.2f}%",
                               "跌破 2.30%", f"還差 {gap:.2f} 個百分點", gap <= 0))
        if i_state != "高":
            gap = 2.9 - blended
            out.append(Trigger("通膨轉「高」", f"綜合通膨水準 {blended:.2f}%",
                               "升破 2.90%", f"還差 {gap:.2f} 個百分點", gap <= 0))
    return out


def grid_cells(current: tuple[str, str] | None = None) -> list[dict]:
    """給畫面用的九宮格資料，列＝勞動由強到弱，欄＝通膨由低到高。"""
    cells = []
    for l in reversed(LABOR_LEVELS):          # 強在上
        row = []
        for i in INFL_LEVELS:
            name, desc, lean = GRID[(l, i)]
            row.append({"labor": l, "infl": i, "name": name,
                        "desc": desc, "lean": lean,
                        "current": current == (l, i)})
        cells.append(row)
    return cells
