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
    binding: bool = False       # 這一軸是不是目前的政策約束條件


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
    focus: dict = field(default_factory=dict)   # 聯準會目前的重心
    focus_note: str = ""                        # 重心如何修正這一格的結論
    binding: str = ""                           # 目前的約束條件在哪一軸
    # 修正後的結論。九宮格的格名是「座標」，反應函數修正過方向之後，
    # 標題不能再沿用格名——否則會出現「標題寫轉向降息、傾向卻是中性」
    # 這種自相矛盾的畫面。
    verdict_name: str = ""
    verdict_desc: str = ""
    overridden: bool = False                    # 結論是否被反應函數改寫過
    positioning_note: str = ""                  # 部位對照與修正後結論的落差說明


# 反應函數改寫方向之後的標題。(原方向, 修正後方向) → (標題, 說明)
#
# 格子的名字只是座標，不是結論。「就業弱 × 通膨中」這一格叫「轉向降息」，
# 但在通膨優先的體制下實際上降不了息——標題若還寫轉向降息，
# 就會跟下面「政策傾向：中性」自相矛盾。
OVERRIDE_COPY = {
    ("dovish", "neutral"): (
        "降息受阻",
        "數據本身落在偏向降息的位置，但聯準會目前以通膨為優先。"
        "在通膨回到目標附近之前，就業轉弱不會單獨換來降息——"
        "所以實際上是「想降但還不能降」，不是真的要降。"),
    ("hawkish", "neutral"): (
        "升息受阻",
        "數據本身落在偏向升息的位置，但聯準會目前以就業為優先。"
        "勞動市場已經轉弱時，緊縮的門檻會明顯提高——"
        "所以實際上是「該緊但不敢緊」，不是真的要升息。"),
}


# ---------------------------------------------------------------------------
# 反應函數對格子的修正
# ---------------------------------------------------------------------------
def _apply_focus(l_state: str, i_state: str, lean: str,
                 focus: dict | None) -> tuple[str, str, str]:
    """
    用聯準會目前的重心修正政策傾向，並指出哪一軸才是約束條件。

    回傳 (修正後的 lean, 說明, 約束條件所在的軸)。

    為什麼要修正
    ------------
    固定的九宮格假設雙重使命的權重永遠一樣，但反應函數會移動。
    「就業弱 × 通膨中」在就業優先的體制下確實是降息，
    但在通膨優先的體制下，就業再弱也換不到降息——要等通膨先降。
    不修正的話，這一格會給出方向完全相反的結論。
    """
    f = (focus or {}).get("focus")

    if f == "inflation":
        # 通膨沒回到低檔之前，就業轉弱不構成降息理由
        if lean == "dovish" and i_state != "低":
            return ("neutral",
                    "九宮格本身偏向降息，但聯準會目前以通膨為優先——"
                    "在通膨回到目標附近之前，就業轉弱不會單獨換來降息，"
                    "所以實際傾向修正為觀望。",
                    "通膨")
        if lean == "hawkish":
            return (lean,
                    "聯準會目前以通膨為優先，與這一格的方向一致，判讀的信心較高。",
                    "通膨")
        return (lean, "聯準會目前以通膨為優先，降息的門檻比一般情況高。", "通膨")

    if f == "employment":
        # 就業優先：通膨略高不阻止降息
        if lean == "hawkish" and l_state == "弱":
            return ("neutral",
                    "九宮格本身偏向升息，但聯準會目前以就業為優先——"
                    "勞動市場已經轉弱時，緊縮的門檻會明顯提高，"
                    "所以實際傾向修正為觀望。",
                    "就業")
        if lean == "dovish":
            return (lean,
                    "聯準會目前以就業為優先，與這一格的方向一致，判讀的信心較高。",
                    "就業")
        return (lean, "聯準會目前以就業為優先，升息的門檻比一般情況高。", "就業")

    if f == "balanced":
        return (lean,
                "聯準會把兩邊的風險描述為大致平衡，九宮格的判定不做修正——"
                "哪一邊先出現極端值，哪一邊就會主導決策。",
                "兩者")

    return (lean, "本次聲明看不出聯準會的重心，九宮格的判定不做修正。", "")


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

    name, desc, base_lean = GRID[(l_state, i_state)]

    # 反應函數：同一格在「通膨優先」與「就業優先」下的結論可能相反
    focus = (fomc or {}).get("focus") or {}
    lean, focus_note, binding = _apply_focus(l_state, i_state, base_lean, focus)

    # 方向被改寫時，標題要跟著換掉——格名只是座標，不是結論
    overridden = lean != base_lean
    v_name, v_desc = name, desc
    if overridden:
        v_name, v_desc = OVERRIDE_COPY.get(
            (base_lean, lean),
            (name, desc))

    # 部位對照表是按**九宮格原始格名**建的。方向被改寫時它就不再對應
    # 最終結論——「降息受阻／中性」底下擺著「存續期間偏長」這種降息部位，
    # 兩者直接打架。表格保留（它仍是原始情境的完整框架），但要明講落差。
    pos_note = ""
    if overridden:
        pos_note = (
            f"下表對應的是九宮格原始定位「{name}」。聯準會目前以"
            f"{'通膨' if binding == '通膨' else '就業'}為優先，最終結論已修正為"
            f"「{v_name}」，所以實際部位方向應該比下表更靠近中性——"
            "下表可視為「若重心轉回另一邊會走向哪裡」的對照。")

    sc = Scenario(labor_state=l_state, infl_state=i_state, name=name,
                  description=desc, lean=lean,
                  positioning=dict(POSITIONING.get(name, {})),
                  incomplete=incomplete,
                  focus=focus, focus_note=focus_note, binding=binding,
                  verdict_name=v_name, verdict_desc=v_desc,
                  overridden=overridden, positioning_note=pos_note)

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
    sc.triggers = _triggers(labor, inflation, l_state, i_state, binding)
    return sc


def _triggers(labor: dict | None, inflation: dict | None,
              l_state: str, i_state: str, binding: str = "") -> list[Trigger]:
    """
    各軸離下一格還有多遠。

    binding 指出目前哪一軸才是政策的約束條件——在通膨優先的體制下，
    勞動那幾條就算全部觸發，也不會單獨改變政策方向。標示出來，
    讀者才知道該盯哪一條。
    """
    out: list[Trigger] = []

    score = (labor or {}).get("score")
    if score is not None:
        for label, thr, gap in (
            ("勞動轉「弱」", "需低於 −0.45", score - (-0.45)),
            ("勞動轉「強」", "需高於 +0.45", 0.45 - score),
        ):
            if (label.endswith("「弱」") and l_state == "弱") or \
               (label.endswith("「強」") and l_state == "強"):
                continue
            out.append(Trigger(label, f"綜合分數 {score:+.2f}", thr,
                               f"還差 {gap:.2f}", gap <= 0,
                               binding=(binding == "就業")))

    pce = (inflation or {}).get("core_pce_yoy")
    c3 = (inflation or {}).get("core_3m")
    if pce is not None:
        blended = 0.6 * pce + 0.4 * c3 if c3 is not None else pce
        if i_state != "低":
            gap = blended - 2.3
            out.append(Trigger("通膨轉「低」", f"綜合通膨水準 {blended:.2f}%",
                               "需低於 2.30%", f"還差 {gap:.2f} 個百分點",
                               gap <= 0, binding=(binding == "通膨")))
        if i_state != "高":
            gap = 2.9 - blended
            out.append(Trigger("通膨轉「高」", f"綜合通膨水準 {blended:.2f}%",
                               "需高於 2.90%", f"還差 {gap:.2f} 個百分點",
                               gap <= 0, binding=(binding == "通膨")))
    return out


def grid_cells(current: tuple[str, str] | None = None,
               overridden: bool = False) -> list[dict]:
    """
    給畫面用的九宮格資料，列＝勞動由強到弱，欄＝通膨由低到高。

    格子的名稱與說明是**固定的座標**，不隨反應函數改變——
    它是一張地圖，地名不該每期換。方向被改寫時只在目前這一格標示，
    完整的修正結論由結論卡負責。
    """
    cells = []
    for l in reversed(LABOR_LEVELS):          # 強在上
        row = []
        for i in INFL_LEVELS:
            name, desc, lean = GRID[(l, i)]
            is_cur = current == (l, i)
            row.append({"labor": l, "infl": i, "name": name,
                        "desc": desc, "lean": lean,
                        "current": is_cur,
                        "overridden": is_cur and overridden})
        cells.append(row)
    return cells
