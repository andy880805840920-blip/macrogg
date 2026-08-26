"""
情境合成（P4）。

把勞動與通膨兩條腿合成一個政策情境。

為什麼要這樣做
--------------
聯準會是雙重使命。同一份就業數據，在通膨 2.0% 和 3.5% 的環境下
會導向完全相反的決定。所以任何只看單邊的結論都是不完整的——
這一層就是把兩邊擺在一起看。

九宮格內部再用 FOMC 的**客觀訊號**校準（政策行動、反對票、聲明的風險用語），
不用措辭語氣分數——語氣會隨主席文風改變，拿來加信心並不可靠。

輸出刻意**不給機率**。理由：機率市場早就定價了，研究員的價值在於
指出「我的判讀與市場定價哪裡不同」，而不是複述市場價格。
"""

from __future__ import annotations

from dataclasses import dataclass, field


LABOR_LEVELS = ["弱", "中", "強"]
INFL_LEVELS = ["低", "中", "高"]


# ---------------------------------------------------------------------------
# 三張九宮格：一個體制一張
# ---------------------------------------------------------------------------
# 為什麼是三張而不是一張加註解
# ----------------------------
# 先前是一張固定的格子，再用「反應函數」事後改寫方向，並在畫面上用
# 格名／修正後標題／「結論已依重心修正」徽章／部位對照落差說明**四個地方**
# 解釋那個改寫。但那套機制實際上只改變九格裡的一格——工做得很少，
# 畫面卻很亂，而且「標題寫轉向降息、傾向卻是中性」這種矛盾一直要靠文字補救。
#
# 改成三張之後，格子裡寫什麼就是結論，不需要任何事後解釋。
#
# 哪幾格會變、哪幾格不會
# ----------------------
# 把每一格拆開看「就業要求什麼、通膨要求什麼」，真正衝突的只有三格：
#
#   中×高   就業中性 vs 通膨要緊    → 通膨優先才緊縮
#   弱×中   就業要降 vs 通膨中性    → 通膨優先時降不了
#   弱×高   就業要降 vs 通膨要緊    → 完全相反，衝突最強
#
# 其餘六格兩個使命同向（強×高 同向鷹、弱×低 同向鴿）或都不極端，
# 所以三張格子裡完全一樣。這件事本身是有用的資訊：
# 重心只在那三格有影響，畫面上會標出來。
_BASE = {
    ("強", "低"): ("溫和成長", "就業穩、通膨低。聯準會沒有壓力，可以慢慢來。", "neutral"),
    ("強", "中"): ("小心觀望", "就業穩但通膨還沒回到目標，聯準會會傾向按兵不動。", "neutral"),
    ("強", "高"): ("升息壓力", "經濟過熱。就業強加上通膨高，兩個使命同向指向緊縮。", "hawkish"),
    ("中", "低"): ("預防性降息", "通膨已受控，就業開始鬆動。聯準會有空間先降息保險。", "dovish"),
    ("中", "中"): ("按兵不動", "兩邊都不極端，這份數據不足以改變方向。", "neutral"),
    ("弱", "低"): ("衰退式降息", "就業明顯轉弱、通膨不是問題。兩個使命同向指向寬鬆。", "dovish"),
}

# 三格會隨體制改變的內容。key 是體制，value 是 {(勞動, 通膨): (名稱, 說明, 傾向)}
_REGIME_CELLS = {
    "inflation": {
        ("中", "高"): ("傾向緊縮",
                       "通膨還高，而就業還沒弱到需要救。在通膨優先的體制下，"
                       "這一格是明確的緊縮方向。", "hawkish"),
        ("弱", "中"): ("降息受阻",
                       "就業轉弱本身指向降息，但通膨還沒回到目標附近。"
                       "在通膨優先的體制下，就業轉弱不會單獨換來降息——"
                       "是「想降但還不能降」，不是真的要降。", "neutral"),
        ("弱", "高"): ("停滯性通膨：通膨優先",
                       "兩個使命指向相反，而委員會把通膨擺在前面。"
                       "降息會助長通膨，所以就算就業繼續惡化，"
                       "寬鬆也要等通膨先降下來。", "hawkish"),
    },
    "employment": {
        ("中", "高"): ("忍受通膨",
                       "通膨還高，但委員會把就業擺在前面，而就業還沒轉弱。"
                       "這一格不會主動緊縮——通膨略高於目標本身不構成升息理由。",
                       "neutral"),
        ("弱", "中"): ("轉向降息",
                       "就業惡化成為主要考量，通膨的阻力正在消退。"
                       "在就業優先的體制下，這一格降息沒有障礙。", "dovish"),
        ("弱", "高"): ("停滯性通膨：救就業",
                       "兩個使命指向相反，而委員會把就業擺在前面。"
                       "即使通膨仍高於目標，勞動市場的惡化才是決定性的——"
                       "會忍受一段時間的高通膨去撐就業。", "dovish"),
    },
    "balanced": {
        ("中", "高"): ("兩難",
                       "通膨還高但就業開始鬆動，兩個使命沒有明確的優先順序。"
                       "哪一邊先出現極端值，哪一邊就會主導。", "hawkish"),
        ("弱", "中"): ("轉向降息",
                       "就業惡化成為主要考量，通膨的阻力正在消退。"
                       "兩邊並重時，這一格由就業那一側主導。", "dovish"),
        ("弱", "高"): ("兩難僵局",
                       "最棘手的情況，而且沒有優先順序可以打破僵局。"
                       "降息會助長通膨、升息會加深衰退，兩股力量互相抵消——"
                       "結果通常是按兵不動，直到某一邊先失控。", "neutral"),
    },
}

REGIMES = ("inflation", "employment", "balanced")

REGIME_LABEL = {
    "inflation": "通膨優先",
    "employment": "就業優先",
    "balanced": "兩邊並重",
}

REGIME_RULE = {
    "inflation": "通膨沒回到目標附近之前，就業轉弱不會單獨換來降息。",
    "employment": "勞動市場的惡化是決定性的；通膨略高於目標不會阻止降息。",
    "balanced": "沒有優先順序。哪一邊先出現極端值，哪一邊就主導。",
}

# 三張格子只有這三格不同，其餘六格完全一樣
CONFLICT_CELLS = (("中", "高"), ("弱", "中"), ("弱", "高"))


def grid_for(regime: str) -> dict:
    """取某個體制的完整九宮格。未知體制退回「兩邊並重」。"""
    cells = _REGIME_CELLS.get(regime) or _REGIME_CELLS["balanced"]
    return {**_BASE, **cells}


# 相容用：舊程式碼引用的 GRID 指向「兩邊並重」那一張（最中性的基準）
GRID = grid_for("balanced")

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
    # 註：原本的「停滯性通膨」單一條目已刪除。改成三張格子之後，
    # 弱×高 這一格在三個體制下是三個不同的名字（通膨優先／救就業／兩難僵局），
    # 沒有任何一張格子再叫「停滯性通膨」，留著只是一筆永遠查不到的死資料。

    # ---- 三張格子引入的新情境名 ----
    # 部位表是按情境名查的。新的體制專屬格名（降息受阻、忍受通膨…）
    # 如果沒有對應項，畫面上會出現一張空的部位表，所以每一個都要補齊。
    "傾向緊縮": {
        "殖利率曲線": "短天期被政策預期推高，曲線傾向變平",
        "債券存續期間": "縮短。緊縮方向下長天期跌幅較大",
        "抗通膨債券": "走強，通膨預期仍高",
        "公司債利差": "偏向走闊"},
    "忍受通膨": {
        "殖利率曲線": "短端被政策按住、長端被通膨推高，曲線偏向變陡",
        "債券存續期間": "縮短。委員會容忍通膨時，長天期承受的通膨風險最大",
        "抗通膨債券": "走強。這是「容忍通膨」最直接受惠的資產",
        "公司債利差": "區間。景氣未惡化，信用面壓力有限"},
    "降息受阻": {
        "殖利率曲線": "區間震盪。市場想定價降息但遲遲等不到",
        "債券存續期間": "中性偏長，但要有等待的準備——"
                        "方向對，時點取決於通膨何時回到目標附近",
        "抗通膨債券": "大致持平",
        "公司債利差": "偏向走闊。就業已在轉弱，信用面開始承壓"},
    "停滯性通膨：通膨優先": {
        "殖利率曲線": "短天期被通膨推高、長天期被衰退壓低，曲線變平（熊平）",
        "債券存續期間": "縮短。委員會以通膨為優先時，寬鬆的時點會一再延後",
        "抗通膨債券": "走強，這是少數同時受惠的資產",
        "公司債利差": "走闊。企業獲利與融資成本兩頭受壓，而且沒有政策救援"},
    "停滯性通膨：救就業": {
        "殖利率曲線": "短天期跟著政策下降、長天期被通膨黏住，曲線明顯變陡（牛陡）",
        "債券存續期間": "偏中天期。長天期會被通膨補償拖住，拉太長賺不到降息的價差",
        "抗通膨債券": "明顯走強。容忍通膨去救就業，通膨預期會被推高",
        "公司債利差": "先走闊後收斂——景氣壓力先到，政策寬鬆後才緩解"},
    "兩難僵局": {
        "殖利率曲線": "區間震盪。兩股力量互相抵消，曲線沒有明確方向",
        "債券存續期間": "中性。方向不明時，拉長或縮短都是在賭僵局往哪邊破",
        "抗通膨債券": "略為走強，通膨仍高於目標",
        "公司債利差": "偏向走闊。就業轉弱而政策不動，信用面得不到支撐"},
}


@dataclass
class Trigger:
    label: str
    current: str
    threshold: str
    distance: str
    met: bool = False
    binding: bool = False       # 這一軸是不是目前的政策約束條件
    # 觸發後到的是不是**相鄰**的格子。九宮格的「下一格」只能用相鄰的
    # 條件；非相鄰的（例如從「高」直達「低」）是政策解鎖條件，
    # 兩者混在一起就會出現「下一格跳了兩格」的畫面。
    adjacent: bool = True
    # 這條門檻屬於哪一軸、往哪個方向（給「可能下一格」的方向過濾用）：
    #   axis      "labor" / "inflation"
    #   direction 就業軸 "weaker"/"stronger"；通膨軸 "down"/"up"
    axis: str = ""
    direction: str = ""


@dataclass
class Scenario:
    labor_state: str
    infl_state: str
    name: str
    description: str
    lean: str
    labor_momentum: str = "持平"
    infl_momentum: str = "持平"
    positioning: dict = field(default_factory=dict)
    triggers: list[Trigger] = field(default_factory=list)
    drivers: list[str] = field(default_factory=list)
    fomc_note: str = ""
    incomplete: list[str] = field(default_factory=list)
    focus: dict = field(default_factory=dict)   # 聯準會目前的重心
    focus_note: str = ""                        # 重心如何修正這一格的結論
    binding: str = ""                           # 目前的約束條件在哪一軸
    # 結論直接就是「目前體制的那張格子裡的那一格」，不再有事後改寫，
    # 所以不需要 verdict_name / overridden / positioning_note 那一族欄位。
    regime: str = "balanced"                    # 目前適用的九宮格（哪個使命優先）
    regime_assumed: bool = False                # True = 判不出重心，暫用「兩邊並重」
    labor_basis: str = "score"                  # 就業格位是靠分數還是旗標定的
    labor_basis_note: str = ""                  # 靠旗標定案時的說明
    # 各軸目前的數據漂移方向（axis_drift 的結果）。只給「可能下一格」
    # 的挑選用，不參與格位判定。
    drift: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 分數與旗標淨值的舊門檻。只在拿不到 FOMC 長期失業率時才用得到——
# 這兩個數字是這個專案自己選的，沒有外部依據，用到時畫面上會標示。
FALLBACK_SCORE, FALLBACK_NET = 0.45, 3
# 就業「溫和惡化」門檻：Sahm 同款算式（失業率三月均較近一年低點的
# 回升幅度），但 0.20 不是外部標準——0.50 才是原論文的衰退門檻，
# 0.20 只是「開始惡化」的水位，屬本站判斷，畫面上會標示。
# 它取代了損益兩平就業增速（已整組移除）：損益兩平要靠人口與移民
# 假設去「預測」失業率會不會升，這條直接量「有沒有在升」。
MILD_SAHM = 0.20


def classify_labor(score: float | None, tilt: dict | None,
                   lab: dict | None = None) -> tuple[str, str]:
    """
    就業軸：**水準為主，兩條外部錨的動能修正**。回傳 (狀態, 判定依據)。

    水準
    ----
    失業率相對 **FOMC 自己對長期失業率的判斷**（＝聯準會認定的充分就業）：

        u > 中央趨勢上緣  →  弱
        u < 中央趨勢下緣  →  強
        落在區間內        →  中

    為什麼用 FOMC 的而不是 CBO 的 NROU：九宮格問的是「聯準會會怎麼做」，
    而聯準會照**它自己的**估計行動。帶寬也不是選的——直接用中央趨勢的寬度，
    那是 FOMC 成員彼此意見的分歧程度。這樣兩條軸都錨在同一份 SEP 上。

    動能
    ----
    只看水準會犯一個大錯：聯準會 2024 年 9 月降息 2 碼時，失業率約 4.2%，
    **低於**當時多數的自然失業率估計——它降息的理由不是水準，是惡化的速度。
    所以加兩條同樣有外部依據的動能條件：

      · **Sahm 法則觸發**（失業率三月均比過去一年最低點高 0.50 個百分點以上）
        → 直接判「弱」。門檻出自 Sahm 的原始論文，FRED 另有 SAHMREALTIME。
      · **三個月平均非農 < 損益兩平就業增速** → 往「弱」推一格。
        損益兩平是由人口成長 × 參與率 × 機構／家庭調查比推導出來的，
        不是選的門檻；低於它在定義上就是「撐不住目前的失業率」。

    動能只往一個方向推。往「強」推需要對稱的證據，而就業轉強沒有
    對應的公認規則——寧可不推，也不要自己發明一條。

    拿不到 SEP 時才退回舊的綜合分數 ±0.45／旗標淨值 ±3（沒有外部依據）。
    """
    lab = lab or {}
    u = lab.get("unrate")
    lo, hi = lab.get("u_lo"), lab.get("u_hi")

    if u is None or lo is None or hi is None:
        # ---- 後備：舊規則 ----
        if score is None:
            return "中", "fallback"
        if score <= -FALLBACK_SCORE:
            return "弱", "fallback"
        if score >= FALLBACK_SCORE:
            return "強", "fallback"
        net = (tilt or {}).get("net", 0)
        if net <= -FALLBACK_NET:
            return "弱", "fallback"
        if net >= FALLBACK_NET:
            return "強", "fallback"
        return "中", "fallback"

    # ---- ① 水準 ----
    if u > hi:
        state, basis = "弱", "level"
    elif u < lo:
        state, basis = "強", "level"
    else:
        state, basis = "中", "level"

    # ---- ② 動能：只往「弱」推 ----
    if lab.get("sahm_triggered"):
        return "弱", "sahm"
    return state, basis


def classify_labor_momentum(lab: dict | None) -> str:
    """方向與格位分開：失業率開始回升代表轉弱，不直接移動格位。"""
    lab = lab or {}
    if lab.get("sahm_triggered") or lab.get("u3_rising"):
        return "轉弱"
    tilt = (lab.get("tilt") or {}).get("tilt")
    if tilt == "hawkish" and lab.get("nfp_3m") is not None:
        return "轉強"
    return "持平"


def classify_inflation_momentum(infl: dict | None) -> str:
    """
    月步速判定（0.2 準則，使用者指定）：核心 CPI 近三個月平均月增
    ≤0.2%＝降溫（符合 2% 目標換算的月步速）、≥0.3%＝升溫（年化 3.6%，
    明顯過快）、之間＝持平。門檻推導見 inflation.PACE_TARGET 的說明。

    取捨要記錄：先前是 PCE／CPI／PPI 三對「短期 vs 年增」的 2/3 投票
    ——廣度確認換來了穩健，但讀者對不上市場語言。改成單一指標的月步速
    後，穩健性靠三個月平均（單月雜訊已平滑）與 0.2–0.3 的緩衝帶承擔；
    判定用**未捨入**的平均值，避免在單一門檻上月月翻面。
    """
    from .inflation import PACE_TARGET, PACE_HOT
    pace = (infl or {}).get("core_cpi_pace3")
    if pace is None:
        return "持平"
    if pace >= PACE_HOT:
        return "升溫"
    if pace <= PACE_TARGET:
        return "降溫"
    return "持平"


def blended_inflation(core_pce_yoy: float | None,
                      core_pce_3m: float | None) -> float | None:
    """水準與動能的加權值。兩項都必須是核心 PCE，理由見下方。"""
    if core_pce_yoy is None:
        return None
    if core_pce_3m is None:
        return core_pce_yoy
    return 0.6 * core_pce_yoy + 0.4 * core_pce_3m


def classify_inflation(core_pce_yoy: float | None,
                       core_pce_3m: float | None,
                       bands: dict | None = None) -> str:
    """
    以核心 PCE 相對 2% 目標為主軸，再用三個月年化的動能修正。

    只看年增率會太遲鈍（被一年前的基期拖住），
    只看三個月年化又太吵，所以兩個一起看。

    兩條門檻由 `inflation.inflation_bands()` 給，錨在聯準會自己的預測
    （長期目標＋對明年的核心 PCE 預測中位數），不再寫死。
    先前是 2.3／2.9，程式碼與文件裡都沒有任何依據——而它們決定整張
    固定收益部位對照表，那是這個專案裡權重與依據落差最大的一組數字。

    ⚠️ 兩項都必須是**核心 PCE**，不能一個 PCE 一個 CPI。
    先前動能項送進來的是核心 CPI 的三月年化，而核心 CPI 長期比核心 PCE
    高 0.3–0.5 個百分點（住房權重差一倍、醫療口徑不同）。
    混起來的水準因此有約 +0.15 個百分點的**常數偏誤，方向固定往鷹**，
    而這裡的門檻只差 0.6 個百分點——足以把通膨從「中」推成「高」，
    配上就業「弱」，格子就從「轉向降息」跳成「停滯性通膨」，
    整張部位表跟著換掉。同一個指標的水準與動能才可以相加。
    """
    level = core_pce_yoy
    if level is None:
        return "中"
    b = bands or {}
    lo, hi = b.get("low", 2.30), b.get("high", 2.90)
    if level < lo:
        return "低"
    if level > hi:
        return "高"
    return "中"


# ---------------------------------------------------------------------------
def synthesise(labor: dict | None, inflation: dict | None,
               fomc: dict | None = None) -> Scenario:
    """
    labor     : {"score": float, "tilt": dict, "flags": [...]}
    inflation : {"core_pce_yoy": float, "core_pce_3m": float, "flags": [...]}
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

    l_state, l_basis = classify_labor((labor or {}).get("score"),
                                      (labor or {}).get("tilt"),
                                      labor)
    l_momentum = classify_labor_momentum(labor)
    _bands = (inflation or {}).get("bands") or {}
    i_state = classify_inflation((inflation or {}).get("core_pce_yoy"),
                                 (inflation or {}).get("core_pce_3m"),
                                 _bands)
    i_momentum = classify_inflation_momentum(inflation)

    # ---- 依聯準會目前的重心選一張九宮格 ----
    # 不再「先用固定格子再事後改寫」。格子裡寫什麼就是結論。
    focus = (fomc or {}).get("focus") or {}
    f = focus.get("focus")
    regime = f if f in REGIMES else "balanced"
    # 判不出重心時用「兩邊並重」那一張，但要標明是暫用的——
    # 訊號互相抵銷不等於聯準會真的兩邊並重，這個區別要講清楚。
    regime_assumed = f not in REGIMES

    name, desc, lean = grid_for(regime)[(l_state, i_state)]

    # 這一格會不會隨重心改變？六格不會，三格會。
    # 「不會」本身是有用的資訊：讀者不必去想重心翻轉的風險。
    binding = ""
    if (l_state, i_state) in CONFLICT_CELLS:
        binding = "通膨" if regime == "inflation" else (
            "就業" if regime == "employment" else "兩者")
    focus_note = REGIME_RULE.get(regime, "")

    sc = Scenario(labor_state=l_state, infl_state=i_state,
                  labor_momentum=l_momentum, infl_momentum=i_momentum, name=name,
                  description=desc, lean=lean,
                  positioning=dict(POSITIONING.get(name, {})),
                  incomplete=incomplete,
                  focus=focus, focus_note=focus_note, binding=binding,
                  regime=regime, regime_assumed=regime_assumed,
                  labor_basis=l_basis)

    _lab = labor or {}
    _u, _lo, _hi = _lab.get("unrate"), _lab.get("u_lo"), _lab.get("u_hi")
    if l_basis == "sahm":
        sc.labor_basis_note = (
            f"就業格位定在「弱」不是靠失業率的水準——失業率 {_u:.1f}% "
            f"還在 FOMC 長期判斷的 {_lo:.1f}–{_hi:.1f}% 之內。"
            "是 Sahm 法則觸發（失業率三月均比過去一年最低點高 0.50 個百分點"
            "以上）把它推過去的：那條規則量的是惡化的速度，不是水準。"
            if _u is not None and _lo is not None else
            "就業格位由 Sahm 法則觸發定案。")
    elif l_basis == "fallback":
        _net = (_lab.get("tilt") or {}).get("net", 0)
        _sc = _lab.get("score")
        sc.labor_basis_note = (
            "⚠️ 本次沒有取得 FOMC 對長期失業率的預測（FRED 的 UNRATECTLLR／"
            "UNRATECTHLR），改用後備規則：綜合分數 "
            + (f"{_sc:+.2f}" if _sc is not None else "—")
            + f"（門檻 ±0.45）與旗標鷹鴿淨值 {_net:+.0f}（門檻 ±3）。"
            "這兩個門檻是這個專案自己選的，沒有外部依據。")

    # ---- 推動這個判定的主要因素 ----
    for f in (labor or {}).get("flags", [])[:2]:
        sc.drivers.append(f"勞動｜{f.headline}")
    for f in (inflation or {}).get("flags", [])[:2]:
        sc.drivers.append(f"通膨｜{f.headline}")

    # ---- FOMC 校準 ----
    # 這裡拿到的 direction 來自 fomc_text.shift()，而 shift() 只看
    # **客觀訊號分數**（政策行動＋反對票＋風險用語），完全沒有讀措辭分數。
    # 先前這幾句都寫成「聯準會措辭…」，等於把讀者指向一個沒被用到的輸入——
    # 而聯準會文本頁在同一次執行裡可能正好標著「本次措辭分數不可靠」。
    if fomc:
        d = fomc.get("direction")
        if d == "hawkish" and lean == "dovish":
            sc.fomc_note = ("聯準會的實際動作比數據更鷹（看的是政策行動、反對票"
                            "與聲明的風險用語，不是措辭語氣）。數據雖然偏向降息，"
                            "但官方立場尚未跟上，實際轉向可能比數據暗示的慢。")
        elif d == "dovish" and lean == "hawkish":
            sc.fomc_note = ("聯準會的實際動作比數據更鴿（看的是政策行動、反對票"
                            "與聲明的風險用語，不是措辭語氣）。"
                            "可能是官員看到了數據還沒反映的訊號，值得留意。")
        elif d in ("hawkish", "dovish"):
            trans = {"hawkish": "利升息", "dovish": "利降息"}[d]
            sc.fomc_note = (f"聯準會的客觀訊號與數據方向一致"
                            f"（{fomc.get('label', '')}＝{trans}方向），判讀的信心較高。"
                            "這裡比對的是政策行動、反對票與聲明的風險用語，"
                            "不含措辭語氣分數——語氣會隨主席文風改變，不宜用來加信心。")
        else:
            sc.fomc_note = ("聯準會的客觀訊號（政策行動、反對票、風險用語）"
                            "沒有明顯變化，方向主要由數據決定。")

    # ---- 跨入相鄰格的觸發條件 ----
    sc.triggers = _triggers(labor, inflation, l_state, i_state, binding)
    sc.drift = axis_drift(labor, inflation)
    return sc


def axis_drift(labor: dict | None, inflation: dict | None) -> dict:
    """
    各軸目前的**數據漂移方向**——只給「可能下一格」的挑選用，不動格位。

    跟 classify_*_momentum 的差別：momentum 是格位層級的正式判定，
    容差內一律「持平」；這裡回答的是更軟的問題「數據正往哪邊漂」，
    所以就業軸把訊號引擎的淨方向也算進來——非農轉負、連續下修這些
    訊號會把 tilt 推成 dovish，即使損益兩平缺口還在容差內。
    使用者的原話就是這個情況：「以目前數據來看就業是轉弱的，
    沒有理由下一個可能是轉強」。

    回傳 {"labor": (dir, why) | None, "inflation": (dir, why) | None}，
    dir 用與 Trigger.direction 相同的詞彙。
    """
    lab = labor or {}
    l = None
    if lab.get("sahm_triggered"):
        l = ("weaker", "Sahm 法則已觸發")
    elif lab.get("u3_rising"):
        l = ("weaker", "失業率已較近一年低點回升逾 0.2 個百分點")
    else:
        _t = (lab.get("tilt") or {}).get("tilt")
        if _t == "dovish":
            l = ("weaker", "本期就業訊號淨偏弱")
        elif _t == "hawkish":
            l = ("stronger", "本期就業訊號淨偏強")
    im = classify_inflation_momentum(inflation)
    i = None
    if im == "升溫":
        i = ("up", "通膨動能升溫")
    elif im == "降溫":
        i = ("down", "通膨動能降溫")
    return {"labor": l, "inflation": i}


def pick_next(sc) -> dict:
    """
    「可能下一格」的挑選：**方向優先、距離其次**。

    先前只挑「距離最近的相鄰門檻」，是無方向的——失業率 4.1% 離
    轉「強」的 4.0 比離轉「弱」的 4.3 近，畫面就說下一格是升息壓力，
    但當期數據（非農轉負、連續下修、訊號淨偏降息）明明朝弱走。
    「近」不等於「會到」：門檻在哪是位置，數據往哪走才是方向。

    規則（全部確定性）：
      ① 只保留與該軸漂移方向**一致**的相鄰未觸發門檻，取距離最近的
      ② 兩軸都在漂移、但都不朝任何相鄰門檻 → mode="hold"
        （短期傾向不動），最近門檻降級為參考
      ③ 兩軸方向都判不出來 → 退回距離最近（mode="nearest"）

    回傳 {"trigger", "unlock", "mode", "reason"}；
    unlock＝政策解鎖條件（binding 且非相鄰），與方向無關、照舊另列。
    """
    import re as _re

    def _gap(t) -> float:
        m = _re.search(r"[-+]?\d+(?:\.\d+)?", t.distance or "")
        return abs(float(m.group(0))) if m else 9e9

    adj = [t for t in sc.triggers if t.adjacent and not t.met]
    unlock = next((t for t in sc.triggers
                   if t.binding and not t.adjacent), None)
    drift = sc.drift or {}
    aligned = [t for t in adj
               if t.direction and (drift.get(t.axis) or (None,))[0] == t.direction]
    if aligned:
        t = min(aligned, key=_gap)
        why = (drift.get(t.axis) or ("", ""))[1]
        return {"trigger": t, "unlock": unlock,
                "mode": "directional", "reason": why}
    near = min(adj, key=_gap) if adj else None
    if any(drift.get(a) for a in ("labor", "inflation")):
        whys = "、".join((drift[a] or ("", ""))[1]
                         for a in ("labor", "inflation") if drift.get(a))
        return {"trigger": near, "unlock": unlock, "mode": "hold",
                "reason": whys}
    return {"trigger": near, "unlock": unlock, "mode": "nearest",
            "reason": "兩軸方向中性，取距離最近的門檻"}


def _triggers(labor: dict | None, inflation: dict | None,
              l_state: str, i_state: str, binding: str = "") -> list[Trigger]:
    """
    各軸離**相鄰的下一格**還有多遠，加上政策解鎖條件。

    使用者抓到的 bug：目前在「通膨高」，畫面卻寫「下一個轉格條件：
    通膨轉『低』，還差 0.89 個百分點」。相鄰格是「中」不是「低」——
    先前的寫法只會產生轉「低」與轉「高」兩種條件，**沒有轉「中」**，
    站在兩端時給的一律是跳過中間、直達另一端的門檻，距離被高估整整一格。

    現在每一軸最多兩條：
      · 相鄰格條件（adjacent=True）——九宮格的「下一格」用它
      · 跨到另一端的條件（adjacent=False）——只在它是政策解鎖條件時有意義
        （通膨優先時，降息解鎖的是通膨回到「低」，那本來就不是相鄰格）

    binding 指出目前哪一軸才是政策的約束條件。binding 標籤只掛在
    **指向另一端**的那條（政策要翻向需要的條件）；相鄰格條件是
    「格子會先動到哪」，兩者回答不同的問題，畫面上分開標。

    通膨軸用**加權後的綜合水準**（0.6×年增＋0.4×三月年化），跟格位判定
    同一個口徑——先前這裡用原始年增率，「還差 X」跟軸卡上顯示的
    「加權後 Y%」對不起來，讀者拿計算機驗算會失敗。
    """
    out: list[Trigger] = []

    # ---- 就業軸：門檻＝FOMC 對長期失業率的中央趨勢 ----
    lab = labor or {}
    u, lo, hi = lab.get("unrate"), lab.get("u_lo"), lab.get("u_hi")
    if u is not None and lo is not None and hi is not None:
        cur = f"失業率 {u:.1f}%"
        _b = (binding == "就業")
        if l_state == "強":
            out.append(Trigger("就業轉「中」", cur, f"需高於 {lo:.1f}%",
                               f"還差 {lo - u:.1f} 個百分點", u >= lo,
                               binding=False, adjacent=True,
                               axis="labor", direction="weaker"))
            out.append(Trigger("就業轉「弱」", cur, f"需高於 {hi:.1f}%",
                               f"還差 {hi - u:.1f} 個百分點", u > hi,
                               binding=_b, adjacent=False,
                               axis="labor", direction="weaker"))
        elif l_state == "弱":
            out.append(Trigger("就業轉「中」", cur, f"需低於 {hi:.1f}%",
                               f"還差 {u - hi:.1f} 個百分點", u <= hi,
                               binding=False, adjacent=True,
                               axis="labor", direction="stronger"))
            out.append(Trigger("就業轉「強」", cur, f"需低於 {lo:.1f}%",
                               f"還差 {u - lo:.1f} 個百分點", u < lo,
                               binding=_b, adjacent=False,
                               axis="labor", direction="stronger"))
        else:                                      # 中：兩邊都是相鄰格
            out.append(Trigger("就業轉「弱」", cur, f"需高於 {hi:.1f}%",
                               f"還差 {hi - u:.1f} 個百分點", u > hi,
                               binding=_b, adjacent=True,
                               axis="labor", direction="weaker"))
            out.append(Trigger("就業轉「強」", cur, f"需低於 {lo:.1f}%",
                               f"還差 {u - lo:.1f} 個百分點", u < lo,
                               binding=_b, adjacent=True,
                               axis="labor", direction="stronger"))
    else:
        score = lab.get("score")
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
                                   binding=(binding == "就業"), axis="labor",
                                   direction=("weaker" if label.endswith("「弱」")
                                              else "stronger")))

    # ---- 通膨軸：跟格位判定同口徑的加權水準 ----
    infl = inflation or {}
    level = blended_inflation(infl.get("core_pce_yoy"), infl.get("core_pce_3m"))
    if level is not None:
        b = infl.get("bands") or {}
        lo, hi = b.get("low", 2.30), b.get("high", 2.90)
        cur = f"綜合通膨水準 {level:.2f}%"
        _b = (binding == "通膨")
        if i_state == "高":
            out.append(Trigger("通膨轉「中」", cur, f"需低於 {hi:.2f}%",
                               f"還差 {level - hi:.2f} 個百分點", level <= hi,
                               binding=False, adjacent=True,
                               axis="inflation", direction="down"))
            out.append(Trigger("通膨轉「低」", cur, f"需低於 {lo:.2f}%",
                               f"還差 {level - lo:.2f} 個百分點", level < lo,
                               binding=_b, adjacent=False,
                               axis="inflation", direction="down"))
        elif i_state == "低":
            out.append(Trigger("通膨轉「中」", cur, f"需高於 {lo:.2f}%",
                               f"還差 {lo - level:.2f} 個百分點", level >= lo,
                               binding=False, adjacent=True,
                               axis="inflation", direction="up"))
            out.append(Trigger("通膨轉「高」", cur, f"需高於 {hi:.2f}%",
                               f"還差 {hi - level:.2f} 個百分點", level > hi,
                               binding=_b, adjacent=False,
                               axis="inflation", direction="up"))
        else:                                      # 中：兩邊都是相鄰格
            out.append(Trigger("通膨轉「低」", cur, f"需低於 {lo:.2f}%",
                               f"還差 {level - lo:.2f} 個百分點", level < lo,
                               binding=_b, adjacent=True,
                               axis="inflation", direction="down"))
            out.append(Trigger("通膨轉「高」", cur, f"需高於 {hi:.2f}%",
                               f"還差 {hi - level:.2f} 個百分點", level > hi,
                               binding=_b, adjacent=True,
                               axis="inflation", direction="up"))
    return out


def grid_cells(regime: str, current: tuple[str, str] | None = None) -> list[dict]:
    """
    某個體制的九宮格資料，列＝勞動由強到弱，欄＝通膨由低到高。

    每個體制一張完整的格子。會隨體制改變的三格標上 conflict=True，
    畫面上可以標示「這一格的結論取決於誰優先」——其餘六格不管
    哪個使命優先都一樣，讀者不必為它們擔心重心翻轉。
    """
    grid = grid_for(regime)
    cells = []
    for l in reversed(LABOR_LEVELS):          # 強在上
        row = []
        for i in INFL_LEVELS:
            name, desc, lean = grid[(l, i)]
            row.append({"labor": l, "infl": i, "name": name,
                        "desc": desc, "lean": lean,
                        "current": current == (l, i),
                        "conflict": (l, i) in CONFLICT_CELLS})
        cells.append(row)
    return cells
