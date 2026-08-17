"""
歸因引擎 — 把「總變動」拆解成各組成的貢獻。

這一支是整個系統最可重複使用的部分：
  * 現在用來拆非農的產業貢獻
  * P2 的通膨模組會用同一套邏輯拆 CPI 分項貢獻
所以介面刻意寫得通用（components 進，contributions 出）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .core import value_at, diff


@dataclass
class Contribution:
    key: str
    label: str
    value: float                 # 貢獻的絕對量（同總量單位）
    share: float | None = None   # 佔總變動的比例（總變動太小時為 None）
    # 佔「同方向總額」的比例：增項的分母是全部增加的合計，
    # 減項的分母是全部減少的合計。淨額接近零時 share 會爆掉
    # （正貢獻算出 −165%、最大的減項算出 +204%），這一欄不會。
    gross_share: float | None = None
    # 相對這個行業自己的規模變動了多少 %
    own_pct: float | None = None
    noncyclical: bool = False
    order: int = 999
    # 相對「這個行業自己的歷史波動」有多異常。
    # 用途：有些行業規模小，變動絕對值進不了前五大，
    #       但相對它自己的常態已經是極端值，那才是真正的訊號。
    zscore: float | None = None
    notable: bool = False
    # 「異常」翻成人話用的兩個欄位：這次的變動幅度在自己近 N 個月裡
    # 排第幾大、樣本共幾個月。標籤寫「近 5 年來最大單月減幅」比
    # 「−2.5 個標準差」或「平常波動的 2.5 倍」都直觀——排名不需要
    # 任何統計概念，而且讀者可以自己去對歷史資料驗證。
    rank: int | None = None
    rank_window: int | None = None


@dataclass
class AttributionResult:
    total: float
    positive_sum: float = 0.0        # 全部增加的合計
    negative_sum: float = 0.0        # 全部減少的合計（負值）
    contributions: list[Contribution] = field(default_factory=list)
    aggregates: dict[str, float] = field(default_factory=dict)
    share_suppressed: bool = False   # 總變動接近零時，百分比會失真，故隱藏
    unexplained: float = 0.0         # 明細加總與總量的差（四捨五入與未涵蓋產業）

    def top(self, n: int = 5, positive: bool = True) -> list[Contribution]:
        s = sorted(self.contributions, key=lambda c: c.value, reverse=positive)
        return [c for c in s if (c.value > 0) == positive][:n]

    def display_set(self, n: int = 5) -> tuple[list[Contribution], float, int]:
        """
        手機版要顯示的精簡清單。

        規則：增加最多的 n 個 + 減少最多的 n 個 + 任何「相對自身歷史異常」的行業，
        其餘合併成「其他」。第三個條件是重點——小行業的異常變動不會因為
        絕對值小就被藏起來。

        回傳 (要顯示的清單, 其他合計, 其他家數)
        """
        ranked = sorted(self.contributions, key=lambda c: c.value, reverse=True)
        keep_keys = {c.key for c in ranked[:n]}
        keep_keys |= {c.key for c in ranked[-n:]}
        keep_keys |= {c.key for c in self.contributions if c.notable}

        shown = [c for c in ranked if c.key in keep_keys]
        rest = [c for c in ranked if c.key not in keep_keys]
        return shown, sum(c.value for c in rest), len(rest)


# 總變動絕對值低於這個數就不顯示百分比（單位：千人）
# 理由：-23K 的總變動下，某產業 -12K 會變成「佔 52%」，看起來像半數來源，
#       但同期另有 +38K 的正貢獻，百分比完全誤導。
SHARE_FLOOR = 50.0

# 相對自身歷史超過幾個標準差就標記為「值得注意」
NOTABLE_Z = 1.8
# 計算歷史波動用的月數
NOTABLE_LOOKBACK = 24


def _own_history_zscore(rows: list[dict], idx_from_end: int = 0) -> float | None:
    """
    這個行業「本月變動」相對它自己過去 N 個月變動的標準分數。

    為什麼需要：規模小的行業（例如公用事業）變動絕對值永遠進不了前五大，
    但若它自己一向只在 ±1 千人之間跳動，這次卻動了 5 千人，那就是訊號。
    只看絕對值會漏掉這種情況。
    """
    changes = []
    for i in range(1, len(rows)):
        changes.append(rows[i]["value"] - rows[i - 1]["value"])
    if len(changes) < 13:
        return None

    end = len(changes) - idx_from_end
    current = changes[end - 1]
    hist = changes[max(0, end - 1 - NOTABLE_LOOKBACK): end - 1]
    if len(hist) < 12:
        return None

    mean = sum(hist) / len(hist)
    var = sum((v - mean) ** 2 for v in hist) / max(len(hist) - 1, 1)
    sd = var ** 0.5
    if sd == 0:
        return None
    return (current - mean) / sd


def _own_history_rank(rows: list[dict], idx_from_end: int = 0):
    """
    這個行業「本月變動的絕對幅度」在它自己近 N 個月裡排第幾大。

    回傳 (排名, 樣本月數)；資料不足回 (None, None)。
    排名含本月自己：「排第 1」＝近 N 個月裡最大的一次變動。
    用絕對值比，因為要抓的是「動得不尋常地大」，不分方向——
    方向由變動值本身的正負表達。
    """
    changes = []
    for i in range(1, len(rows)):
        changes.append(rows[i]["value"] - rows[i - 1]["value"])
    if len(changes) < 13:
        return None, None
    end = len(changes) - idx_from_end
    current = changes[end - 1]
    window = changes[max(0, end - NOTABLE_LOOKBACK - 1): end]
    rank = sorted((abs(v) for v in window), reverse=True).index(abs(current)) + 1
    return rank, len(window)


def attribute_payrolls(
    total_rows: list[dict],
    industry_rows: dict[str, list[dict]],
    industry_meta: list[dict],
    idx_from_end: int = 0,
) -> AttributionResult:
    """
    把非農總變動拆成產業貢獻。

    total_rows     : PAYEMS 的水準值序列
    industry_rows  : {series_id: 水準值序列}
    industry_meta  : config 裡的 industries 段落
    """
    total = diff(total_rows, idx_from_end)
    if total is None:
        return AttributionResult(total=0.0)

    meta_by_id = {m["id"]: m for m in industry_meta}
    contribs: list[Contribution] = []

    for sid, rows in industry_rows.items():
        d = diff(rows, idx_from_end)
        if d is None:
            continue
        m = meta_by_id.get(sid, {})
        z = _own_history_zscore(rows, idx_from_end)
        rank, rank_win = _own_history_rank(rows, idx_from_end)
        contribs.append(
            Contribution(
                key=sid,
                label=m.get("label", sid),
                value=d,
                noncyclical=bool(m.get("noncyclical")),
                order=m.get("order", 999),
                zscore=z,
                notable=(z is not None and abs(z) >= NOTABLE_Z),
                rank=rank,
                rank_window=rank_win,
            )
        )

    suppress = abs(total) < SHARE_FLOOR
    if not suppress and total != 0:
        for c in contribs:
            c.share = c.value / total * 100

    # 同向占比與自身變動率：這兩個在淨額接近零時仍然成立，
    # 所以不受 SHARE_FLOOR 影響。淨額很小往往正是因為
    # 增減兩邊都很大而互相抵消——那件事本身才是這個月的重點。
    pos_sum = sum(c.value for c in contribs if c.value > 0)
    neg_sum = sum(c.value for c in contribs if c.value < 0)
    for c in contribs:
        base = pos_sum if c.value > 0 else abs(neg_sum)
        if base:
            c.gross_share = abs(c.value) / base * 100
        prev = value_at(industry_rows.get(c.key, []), idx_from_end + 1)
        if prev:
            c.own_pct = c.value / prev * 100

    explained = sum(c.value for c in contribs)

    # ---- 聚合指標：這幾個才是判斷景氣的關鍵 ----
    noncyc = sum(c.value for c in contribs if c.noncyclical)
    aggregates = {
        "explained": explained,
        "noncyclical": noncyc,                 # 醫療社福 + 各級政府
        "cyclical": total - noncyc,            # 剔除後的「真週期性就業」
        "positive_sum": sum(c.value for c in contribs if c.value > 0),
        "negative_sum": sum(c.value for c in contribs if c.value < 0),
        "breadth": (
            sum(1 for c in contribs if c.value > 0) / len(contribs) * 100
            if contribs else 0.0
        ),
    }

    return AttributionResult(
        total=total,
        positive_sum=pos_sum,
        negative_sum=neg_sum,
        contributions=sorted(contribs, key=lambda c: c.value, reverse=True),
        aggregates=aggregates,
        share_suppressed=suppress,
        unexplained=total - explained,
    )


# 失業率月變動的顯著性門檻（百分點）。BLS 的標準：0.2 個百分點才在
# 90% 信賴水準下顯著。低於這個值的變動不該產出 alert 級的結論。
SIGNIF_PP = 0.2
# 分解殘差超過這個值就在畫面上標出來——再小的話讀者看不出差別，
# 標了只是雜訊。
RESID_SHOW = 0.03


def attribute_unemployment_rate(
    unrate_rows: list[dict],
    employed_rows: list[dict],
    labor_force_rows: list[dict],
) -> dict:
    """
    把失業率變動拆成「就業效果」與「勞動力規模效果」。

    推導
    ----
        u = U / L = (L - E) / L = 1 - E/L

        Δu ≈ -ΔE/L + (E/L)·(ΔL/L)
              └ 就業效果      └ 勞動力效果

    直覺
    ----
        * 就業增加 → 失業率下降（就業效果為負）＝ 好的下降
        * 勞動力萎縮 → 失業率也會下降（勞動力效果為負），
          但那是因為人退出勞動力，不是因為找到工作 ＝ 壞的下降

    注意：勞動力「縮小」會把失業率壓低，不是推高。
    常見的直覺錯誤是把它想反（以為分母變小會讓比率變大，
    但分子 U 同時也在減少，且減得更兇）。

    employed_rows 要用家庭調查就業（CE16OV），與失業率同一份調查，
    不能混用機構調查（PAYEMS），否則分解無法閉合。

    統計顯著性
    ----------
    UNRATE 只公布到小數一位，所以 `d_rate` 永遠是 0.1 的倍數。
    先前的判定門檻是 |Δu| > 0.02——那實際上等於「只要不是完全持平就下判定」。

    但 BLS 自己的標準是：失業率的月變動要 **0.2 個百分點**才在 90% 信賴水準下
    顯著（家庭調查的樣本約六萬戶，CE16OV 月變動的標準誤約 ±30 萬人）。
    拿一個統計上不可分辨於零的 0.1 個百分點去產出 alert 級的結論，
    再經由旗標的鷹鴿淨值（權重 2.0）翻動九宮格的列，是這個系統裡
    訊噪比最差的一條路徑。

    所以這裡照樣回傳方向（方向本身仍有參考價值），但另外標出
    `significant`，讓規則層決定要不要降級。
    """
    if len(unrate_rows) < 2 or len(employed_rows) < 2 or len(labor_force_rows) < 2:
        return {}

    d_rate = unrate_rows[-1]["value"] - unrate_rows[-2]["value"]

    E_now, E_prev = employed_rows[-1]["value"], employed_rows[-2]["value"]
    L_now, L_prev = labor_force_rows[-1]["value"], labor_force_rows[-2]["value"]
    if L_prev == 0:
        return {}

    dE, dL = E_now - E_prev, L_now - L_prev
    dU = dL - dE                                    # 失業人數變動

    employment_effect = -dE / L_prev * 100          # 百分點
    laborforce_effect = (E_prev / L_prev) * dL / L_prev * 100

    # ---- 判定 ----
    # 方向的門檻仍用 0.02（只是「不是完全持平」），但另外算顯著性。
    verdict = "neutral"
    if d_rate < -0.02:
        # 下降：看主要驅動力是就業增加，還是勞動力萎縮
        if laborforce_effect < 0 and abs(laborforce_effect) > abs(employment_effect):
            verdict = "bad_decline"
        elif employment_effect < 0:
            verdict = "good_decline"
        else:
            verdict = "bad_decline"
    elif d_rate > 0.02:
        # 上升：就業減少是壞的；勞動力擴張則是健康的供給增加
        if employment_effect > 0 and abs(employment_effect) >= abs(laborforce_effect):
            verdict = "bad_rise"
        else:
            verdict = "supply_rise"

    return {
        "delta_rate": d_rate,
        "employment_effect": employment_effect,
        "laborforce_effect": laborforce_effect,
        "delta_employed": dE,
        "delta_unemployed": dU,
        "delta_labor_force": dL,
        "verdict": verdict,
        "significant": abs(d_rate) >= SIGNIF_PP,
        "signif_threshold": SIGNIF_PP,
        # 近似誤差。Δu ≈ −ΔE/L + (E/L)(ΔL/L) 是一階近似，而且 d_rate 取自
        # 四捨五入到小數一位的 UNRATE、兩個效果取自未四捨五入的 CE16OV／CLF16OV，
        # 所以兩邊本來就不會完全相等。畫面宣稱「兩項相加＝總變動」，
        # 誤差大到會被看出來時要標示。
        "residual": d_rate - (employment_effect + laborforce_effect),
    }


def attribute_wage_composition(
    ahe_all_rows: list[dict],
    ahe_prod_rows: list[dict],
) -> dict:
    """
    用「全體 AHE」與「非管理職 AHE」的年增率差距，估計組成偏誤的方向。

    非管理職佔民間就業約 8 成且不含高階主管，所以：
      全體年增 > 非管理職年增  →  高薪職位權重上升（低薪工作消失），
                                 平均時薪被組成效果推高，通膨訊號被高估
    """
    from .core import yoy

    y_all = yoy(ahe_all_rows)
    y_prod = yoy(ahe_prod_rows)
    if y_all is None or y_prod is None:
        return {}

    gap = y_all - y_prod
    if gap > 0.15:
        bias = "overstated"     # 總體 AHE 高估了真實加薪幅度
    elif gap < -0.15:
        bias = "understated"
    else:
        bias = "neutral"

    return {
        "yoy_all": y_all,
        "yoy_production": y_prod,
        "gap": gap,
        "composition_bias": bias,
    }
