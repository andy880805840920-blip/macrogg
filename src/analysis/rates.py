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

from .core import value_at


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
        # 只留一句提醒。完整說明在頁尾「三段為什麼不能相加」那一則。
        c.note = "期限溢酬與上面兩項有重疊，不可直接相加。"
    return c


# ---------------------------------------------------------------------------
# 二、政府債務動態
# ---------------------------------------------------------------------------
@dataclass
class DebtState:
    debt_gdp: float | None = None
    # 債務佔 GDP 的資料期別（季頻、財政部＋BEA，發布落後一至兩季）。
    # 這張卡先前完全沒標日期——讀者會把一個上上季的比率當成當下的。
    debt_gdp_asof: str = ""
    deficit_gdp: float | None = None
    interest_gdp: float | None = None
    interest_to_revenue: float | None = None
    effective_rate: float | None = None       # 債務的有效利率 i
    nominal_growth: float | None = None       # 名目 GDP 成長 g
    real_growth: float | None = None          # 實質 GDP 成長（r−g 的 g）
    real_growth_assumed: bool = False         # True = 取不到實質 GDP，用了假設值
    r_minus_g: float | None = None            # 前瞻：市場實質利率 − 實質成長
    i_minus_g: float | None = None            # 目前：有效利率 − 名目成長
    gap_divergence: str = ""                  # 兩個缺口方向不一致時的說明
    stabilizing_pb: float | None = None       # 穩定債務比所需的基本盈餘（% GDP）
    actual_pb: float | None = None            # 實際基本盈餘（% GDP）
    pb_gap: float | None = None               # 實際減穩定水準；負值才是缺口
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
    debt_gdp = s.get("GFDEGDQ188S") or []  # %（季頻，落後一至兩季）
    interest = s.get("A091RC1Q027SBEA") or []   # 十億，年率
    receipts = s.get("FGRECPT") or []
    outlays = s.get("FGEXPND") or []
    gdp = s.get("GDP") or []               # 十億，年率

    d.debt_gdp = value_at(debt_gdp)
    d.debt_gdp_asof = (debt_gdp[-1]["date"] if debt_gdp else "")

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

    # r 減 g 的 g：優先用實質 GDP 年增，取不到才退回呼叫端給的假設值。
    # 寫死的成長率會讓 r−g 與 i−g 在資料變動時各說各話。
    real_gdp = s.get("GDPC1") or []
    if len(real_gdp) > 4 and real_gdp[-5]["value"]:
        d.real_growth = (value_at(real_gdp) / real_gdp[-5]["value"] - 1) * 100
        d.real_growth_assumed = False
    elif real_growth is not None:
        d.real_growth = real_growth
        d.real_growth_assumed = True

    if real_10y is not None and d.real_growth is not None:
        d.r_minus_g = real_10y - d.real_growth

    # 兩個缺口方向不一致時要講清楚，否則同一頁上兩個數字互相打臉。
    # i−g 是「已發行債務的當前成本」，r−g 是「用市場現在的利率再融資後」——
    # 存量利率還在往市場利率爬，所以前者小於後者是正常的，不是矛盾。
    if d.i_minus_g is not None and d.r_minus_g is not None:
        if (d.i_minus_g > 0) != (d.r_minus_g > 0):
            worse = "前瞻" if d.r_minus_g > d.i_minus_g else "當前"
            d.gap_divergence = (
                "兩個缺口方向不同：當前缺口用的是已發行債務的平均利率（存量），"
                "前瞻缺口用的是市場現在的實質利率（增量）。"
                f"{worse}的那個為正，代表壓力還在後面——"
                "舊債每到期換成新利率，存量利率就往市場利率靠攏一步。")

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
# 逐家的申報清單頁，給畫面當「去核對原始資料」的連結用。
# 用 EDGAR 的公司頁而不是單一份文件：文件的 accession 每季都會變，
# 公司頁的網址固定，而且點進去看得到全部的 10-Q／10-K。
FILINGS_URL = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
               "&CIK={cik:010d}&type=10-Q&dateb=&owner=include&count=10")


@dataclass
class Hyperscalers:
    as_of: str = ""
    total_capex: float = 0.0
    total_ocf: float = 0.0
    total_issued: float = 0.0
    capex_yoy: float | None = None
    capex_to_ocf: float | None = None
    n_cash_negative: int = 0          # 依 OCF − CapEx 的簡化口徑為負的家數
    ig_share: float | None = None     # 發債佔投資級市場比重
    companies: list = field(default_factory=list)
    verdict: str = "unknown"
    verified: bool = False
    note: str = ""
    n_from_sec: int = 0               # 五家裡有幾家真的取自 SEC
    period_span: str = ""             # 各家期末日的實際範圍（不是「本季」）


def hyperscalers(cfg: dict, ig_quarterly: float | None = None,
                 ig_verified: bool = False) -> Hyperscalers:
    """
    關鍵不是資本支出的絕對金額，是**融資方式**。

    capex ÷ 營運現金流 超過 100% 代表（依 OCF − CapEx 的簡化口徑）
    自由現金流轉負，這一季的資本支出必須靠本業以外的來源支應——
    帳上現金、發債、融資租賃、供應商融資或股權融資都有可能。
    那正是這幾家從「現金充裕的買方」變成「投資級市場大型供給方」的
    轉折點——它們開始跟公債競爭同一批買盤。

    **總體比率是 SUM(capex) ÷ SUM(ocf)，不是各家百分比取平均。**
    取平均會讓規模最小的公司跟最大的一樣重：甲骨文的營運現金流不到
    微軟的四分之一，它 171% 的比率在平均法下會把總體拉高十幾個百分點，
    而那不是市場實際要吸收的金額比例。
    """
    h = Hyperscalers(as_of=cfg.get("as_of", ""), verified=bool(cfg.get("verified")))
    comps = cfg.get("companies") or []
    if not comps:
        h.note = "尚未填入資料"
        return h

    weighted_yoy_num = 0.0
    weighted_yoy_den = 0.0
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
            weighted_yoy_den += capex          # 分母只累計「有年增資料」的公司
        h.companies.append({
            "name": c.get("name", ""), "ticker": c.get("ticker", ""),
            "capex": capex, "ocf": ocf, "issued": issued,
            "revenue": float(c.get("revenue") or 0),
            "capex_yoy": c.get("capex_yoy"),
            "capex_to_ocf": ratio,
            # 自由現金流用的是**簡化口徑**：營運現金流 − 現金資本支出。
            # 不扣股息、不扣庫藏股買回、不含融資租賃的本金償還——這一頁要
            # 回答的是「本業賺的現金夠不夠付這一季的機器」，不是完整的 FCF。
            # 畫面上必須標明口徑，否則會跟券商報告的 FCF 對不起來。
            "fcf": ocf - capex,
            "cash_negative": ratio is not None and ratio > 100,
            # 各家會計年度起點不同（微軟 6 月底、甲骨文 5 月底、其餘曆年），
            # 所以「最新一季」的期末日必須逐家標示，不能假裝是同一季
            "period_end": c.get("period_end", ""),
            # 這一列是不是真的來自 SEC。**逐列**標示，因為「五家裡一家退回
            # 手動值」跟「五家全部退回手動值」在讀者眼中是完全不同的兩件事，
            # 而先前這兩種情況的畫面長得一模一樣。
            "from_sec": bool(c.get("from_sec")),
            # 去核對原始申報的連結。只由 cik 決定，所以離線／退回手動值時
            # 一樣給得出來——「數字可能是舊的」跟「你查不到原始資料」
            # 是兩回事，後者沒有理由發生。
            "filings_url": (FILINGS_URL.format(cik=int(c["cik"]))
                            if str(c.get("cik") or "").isdigit() else ""),
        })

    # 分母不能用 total_capex：沒有年增資料的公司被排除在分子外卻留在分母裡，
    # 會把加權平均往零壓（少一家 Meta 就低估十個百分點以上）。
    if weighted_yoy_den:
        h.capex_yoy = weighted_yoy_num / weighted_yoy_den
    if h.total_ocf:
        h.capex_to_ocf = h.total_capex / h.total_ocf * 100
    h.n_from_sec = sum(1 for c in h.companies if c["from_sec"])

    # 期間範圍：各家會計年度不同，最新一季的期末日不是同一天。
    # 印出實際的範圍（最早～最晚），而不是含糊的「本季」。
    _pes = sorted(c["period_end"] for c in h.companies if c["period_end"])
    if _pes:
        h.period_span = _pes[0] if _pes[0] == _pes[-1] else f"{_pes[0]}～{_pes[-1]}"

    # 發債佔投資級市場的比重：只有在分母**經過人工確認**時才算。
    #
    # 為什麼要這個條件：分子是五家**不同會計期別**的單季發債相加，
    # 分母是某一個曆季的市場總發行量。兩者的期間本來就對不齊，
    # 已經是量級參考而非精確比率；如果分母還是個沒人核對過的數字
    #（config 的 ig_market.verified: false），那就是拿不確定去除以不確定，
    # 印出來的百分比看起來精確、實際上沒有意義。寧可不顯示。
    if ig_quarterly and ig_verified:
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


# 「其他資金來源」要講完整：把「資本支出超過營運現金流」直接等同於
# 「必須舉債」是錯的推論。公司還可以動用帳上現金、走融資租賃、
# 供應商融資、客戶預付款，或發股票。舉債只是其中一條路——雖然對這一頁
# 關心的長端供給來說是最相關的一條。
_OTHER_FUNDING = "外部融資、既有現金與其他資金來源"


def hs_verdict(h: Hyperscalers) -> tuple[str, str]:
    """
    結論文案。**依實際比率動態產生**，不是查表拿一句寫死的話。

    先前是三句寫死的文案，其中「再擴張就必須舉債」有兩個問題：
      ① 過度絕對——舉債只是選項之一（見 _OTHER_FUNDING）
      ② 沒有把實際比率講出來，讀者無從判斷「接近上限」是 83% 還是 98%

    現在比率直接寫進句子裡，超過 100% 與否走不同的措辭。
    """
    r = h.capex_to_ocf
    if r is None:
        return "資料不足", ""
    n, tot = h.n_cash_negative, len(h.companies)
    neg = (f"依「營運現金流 − 現金資本支出」的簡化口徑，{tot} 家中有 {n} 家為負。"
           if tot else "")

    if r > 100:
        return ("已轉為舉債支應",
                f"合計資本支出已達同期營運現金流的 {r:.0f}%，超過本業產生的現金。"
                f"{neg}"
                f"AI 基礎設施擴張正在提高這幾家對{_OTHER_FUNDING}的依賴；"
                "就長端而言，它們已成為投資級市場的大型供給方，"
                "與公債競爭同一批存續期間需求。")
    if r > 70:
        return ("正在轉向舉債支應",
                f"合計資本支出已達同期營運現金流的 {r:.0f}%，"
                f"逼近本業現金所能支應的範圍。{neg}"
                f"若 AI 基礎設施投資持續擴張，對{_OTHER_FUNDING}的依賴"
                "可能進一步上升。這是供給壓力的前置訊號，不是既成事實。")
    return ("資本支出仍由現金流支應",
            f"合計資本支出約為同期營運現金流的 {r:.0f}%，本業現金足以覆蓋。"
            f"{neg}對債券市場的供給壓力有限。")


# 舊的查表保留給既有呼叫端當標題來源；敘述已由 hs_verdict() 取代。
HS_VERDICT = {
    "cash_funded": ("資本支出仍由現金流支應", ""),
    "transitioning": ("正在轉向舉債支應", ""),
    "debt_funded": ("已轉為舉債支應", ""),
    "unknown": ("資料不足", ""),
}


# ---------------------------------------------------------------------------
# 四、供給壓力綜合判斷
# ---------------------------------------------------------------------------
@dataclass
class SupplyPressure:
    score: float = 0.0                # 正＝供給壓力大（只由「原因」構成）
    level: str = "moderate"           # low | moderate | high
    parts: list = field(default_factory=list)      # 原因：誰在增加債券供給
    priced: list = field(default_factory=list)     # 結果：價格已經反映多少
    priced_score: float = 0.0
    demand: list = field(default_factory=list)     # 需求端：買盤吃不吃得下
    gap_note: str = ""                # 原因與結果背離時的說明


def fed_holdings_pace(series: dict) -> float | None:
    """
    聯準會持有公債的月均變動（十億美元，負值＝縮表）。

    用近三個月的月均而不是單月：TREAST 是**週頻**，會被單週的到期分布
    甩出很大的雜訊，逐週看幾乎必然過度反應。
    """
    rows = series.get("TREAST") or []
    if len(rows) < 14:
        return None
    # 週頻：13 週約當三個月
    now, then = rows[-1]["value"], rows[-14]["value"]
    if now is None or then is None:
        return None
    return (now - then) / 1000.0 / 3.0        # 百萬 → 十億，再除以三個月


def supply_pressure(curve: CurveState, debt: DebtState,
                    hs: Hyperscalers, ig_oas: float | None,
                    qt_monthly: float | None = None) -> SupplyPressure:
    """
    分成三層：原因（供給）、結果（價格）、需求端。

    為什麼要分開
    ------------
    先前五項並列相加：期限溢酬、30−10 年斜率、財政缺口、科技巨頭融資缺口、
    投資級利差。但**期限溢酬與斜率是被供給推高的價格，不是推高它的原因**——
    把兩者加進同一個總分等於重複計算（財政缺口大 → 期限溢酬高 → 各算一次），
    而且「30 年減 10 年」貢獻為負卻列在「壓力的組成」裡，讀起來自相矛盾。

    現在總分只由真正的供給來源構成（政府財政缺口 ＋ 科技巨頭融資缺口
    ＋ 聯準會縮表），期限溢酬與斜率改成「已經反映多少」的獨立指標。
    兩者背離時——供給壓力大但價格還沒反映——那個落差本身就是最有價值的訊號。
    """
    sp = SupplyPressure()

    # ---- 原因：誰在增加債券供給 ----
    total = 0.0
    if debt.pb_gap is not None:
        v = min(max(-debt.pb_gap * 0.5, -2.0), 2.0)
        total += v
        if debt.pb_gap < 0:
            label = "政府財政缺口"
            detail = (f"基本盈餘較穩定水準低 {abs(debt.pb_gap):.1f}% GDP，"
                      "增加公債供給壓力")
        else:
            label = "政府財政緩衝"
            detail = (f"基本盈餘較穩定水準高 {debt.pb_gap:.1f}% GDP，"
                      "在本模型中降低公債供給壓力")
        sp.parts.append({"label": label,
                         "detail": detail,
                         "score": v})
    if hs.capex_to_ocf is not None:
        v = (hs.capex_to_ocf - 70) / 25
        total += v
        sp.parts.append({"label": "科技巨頭融資缺口",
                         "detail": f"資本支出佔營運現金流 {hs.capex_to_ocf:.0f}%，"
                                   "超過 100% 時需動用現金、出售資產或外部融資",
                         "score": v})
    # 聯準會縮表：第三個供給來源，先前完全沒有進來。
    #
    # 政府發債的總量不變，但只要聯準會不再把到期的公債換新，
    # 那一部分就必須改由私人市場吸收——對私人部門來說，
    # 「聯準會每月減持 300 億」跟「財政部每月多發 300 億」是同一件事。
    # 這一輪長端上行，縮表是公認的推力之一；一張專門討論長端供給壓力的頁面
    # 把它整個略掉說不過去。
    if qt_monthly is not None:
        # 每月減持 500 億約當一個標準的緊縮步調 → 1 分。
        # 正值（擴表）給負分：那代表聯準會正在幫忙吸收供給。
        v = min(max(-qt_monthly / 50.0, -2.0), 2.0)
        total += v
        # 內部單位是十億美元；顯示換算成「億」——中文讀者的量詞是
        # 億，「37 十億美元」這種混用單位沒人讀得懂。
        if qt_monthly < -5:
            detail = (f"每月減持約 {abs(qt_monthly) * 10:,.0f} 億美元公債，"
                      "這些量得由私人市場接手")
        elif qt_monthly > 5:
            detail = (f"每月增持約 {qt_monthly * 10:,.0f} 億美元公債，"
                      "聯準會正在幫忙吸收供給")
        else:
            detail = "持有量大致持平，對供給既沒有額外推力也沒有幫助"
        sp.parts.append({"label": "聯準會縮表", "detail": detail, "score": v})

    sp.score = total
    # 門檻隨項數調整：兩項時是 0.8，加了縮表變三項，等比放到 1.2
    sp.level = "high" if total > 1.2 else ("low" if total < -0.8 else "moderate")
    sp.parts.sort(key=lambda p: abs(p["score"]), reverse=True)

    # ---- 結果：價格已經反映多少 ----
    priced = 0.0
    if curve.term_premium is not None:
        v = (curve.term_premium - 0.4) * 2.0
        priced += v
        sp.priced.append({"label": "期限溢酬",
                          "detail": f"{curve.term_premium:+.2f}%（中性參考 0.40%）",
                          "score": v})
    if curve.slope_30_10 is not None:
        v = (curve.slope_30_10 - 0.6) * 2.0
        priced += v
        sp.priced.append({"label": "30 年減 10 年利差",
                          "detail": f"{curve.slope_30_10:+.2f}%（中性參考 0.60%）",
                          "score": v})
    sp.priced_score = priced
    sp.priced.sort(key=lambda p: abs(p["score"]), reverse=True)

    # ---- 需求端：買盤還吃不吃得下 ----
    if ig_oas is not None:
        sp.demand.append({
            "label": "投資級利差", "value": f"{ig_oas:.2f}%",
            "detail": ("走闊，買方開始要求更高補償" if ig_oas > 1.3 else
                       ("收斂，買盤積極" if ig_oas < 0.9 else
                        "接近常態，買盤目前還吃得下新供給")),
            "tight": ig_oas > 1.3,
        })

    # ---- 原因與結果的落差 ----
    # 供給壓力大但價格還沒反映，代表壓力還在後面；反過來則是已經反映過頭。
    if sp.parts and sp.priced:
        d = total - priced
        if d > 0.8:
            sp.gap_note = ("供給面的壓力大於價格已經反映的程度——"
                           "期限溢酬還沒完全把新增供給算進去，長端還有上行空間。")
        elif d < -0.8:
            sp.gap_note = ("價格反映的壓力大於供給面實際的程度——"
                           "期限溢酬可能已經超前，供給若沒有繼續惡化，長端有回落空間。")
        else:
            sp.gap_note = ("供給面的壓力與價格已經反映的程度相當，"
                           "目前沒有明顯的錯價。")
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
