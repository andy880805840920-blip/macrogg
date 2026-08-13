"""
通膨模組的分析層（P2）。

刻意重用勞動模組的歸因引擎——CPI 分項貢獻與產業貢獻的數學結構完全相同：

    貢獻 = 權重 × 變化率

差別只在勞動的「權重」是各產業自己的人數（隱含在水準值裡），
而 CPI 的權重要另外從 BLS 的相對重要性表帶進來。
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

from dataclasses import dataclass, field

from .core import (annualized, annualized_series, yoy, yoy_series, mom_pct,
                   value_at,
                   _shift_months, _at_date)
from .attribution import Contribution, AttributionResult
from .. import clock


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
    ex_shelter_rows: list[dict] | None = None,
) -> AttributionResult:
    """
    把 CPI 的變化拆成各分項的**近似**貢獻（單位：個百分點 pp）。

    months=1  → 月變動；months=3 → 近三個月（雜訊較低，建議主看這個）

        估算貢獻(pp) ≈ 該分項的 BLS relative importance(%) / 100
                       × 該分項的期間累計變化率(%)

    ⚠️ **「近似」兩個字是重點，不是客套。**

    BLS 的 CPI 不是「單一時點權重 × 累計變化」加總出來的——它是分層鏈式
    聚合，權重在期間內本身也會動。所以

        sum(各類別估算貢獻)  ≠  headline CPI 的累計變化

    是**方法上的必然，不是計算錯誤**。實測：換上官方的 relative importance
    （2025 年 12 月表）之後，2026-04→07 的估算合計是 +0.17pp、實際是
    +0.12%，仍差 0.05——權重、指數、時間窗全部正確的情況下。

    這個差額仍然算在 `unexplained` 裡供程式端診斷，但**不該呈現成
    「兩邊對不上」**：那會讓讀者以為模型算錯，而真正該看的是「哪些類別在
    推升、哪些在壓低」。

    `ex_shelter_rows` 是官方的「All Items Less Shelter」指數。給了就用它算
    剔除住房後的漲幅——那才是正確做法。ex-shelter 是把住房拿掉後**重新
    聚合**的指數，不能用「總數減住房貢獻再除以剩餘權重」反推出來。
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

    present_ids = {c.key for c in contribs}
    coverage_weight = sum(float(meta_by_id.get(c.key, {}).get("weight", 0))
                          for c in contribs)
    expected_weight = sum(float(m.get("weight", 0)) for m in component_meta)
    missing_labels = [m.get("label", m["id"]) for m in component_meta
                      if m["id"] not in present_ids and float(m.get("weight", 0)) > 0]

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

    shelter_w = sum(
        float(meta_by_id.get(c.key, {}).get("weight", 0))
        for c in contribs if meta_by_id.get(c.key, {}).get("laggy")
    )
    # 「剔除住房後」用**官方的 All Items Less Shelter 指數**算。
    #
    # 先前是拿「(總漲幅 − 住房貢獻) ÷ (1 − 住房權重)」反推。那等於假設
    # CPI 是各分項的簡單加權和，而 ex-shelter 其實是把住房整個拿掉之後
    # **重新聚合**出來的指數——兩者不等價，反推出來的數字沒有對應的官方值。
    #
    # 抓不到官方指數才退回反推，並且標記出來（`ex_shelter_derived`），
    # 因為那是退路不是常態。
    ex_shelter = _pct_change(ex_shelter_rows or [], months)
    ex_shelter_derived = False
    if ex_shelter is None:
        ex_shelter_derived = True
        ex_shelter = ((total - shelter) / (1 - shelter_w / 100)
                      if shelter_w < 100 else None)

    return AttributionResult(
        total=total,
        contributions=sorted(contribs, key=lambda c: c.value, reverse=True),
        aggregates={
            "explained": explained,
            "coverage_weight": coverage_weight,
            "expected_weight": expected_weight,
            "missing_labels": missing_labels,
            "core_services": core_services,
            "supercore": supercore,
            "shelter": shelter,
            "food_energy": food_energy,
            "ex_shelter": ex_shelter,
            "ex_shelter_derived": ex_shelter_derived,
            # 住房權重（%）。畫面上要用它把住房的「貢獻」還原成
            # 住房自己的漲幅，才能跟非住房的漲幅並排比較。
            "shelter_weight": shelter_w,
        },
        share_suppressed=suppress,
        unexplained=total - explained,
    )


def _pct_change(rows: list[dict], months: int) -> float | None:
    """
    近 N 個月的累計變化率（%）。months=1 就是月變動。

    **除數用日期找，不是往前數 N 列。** 這跟 v73 修好的 `yoy()` 是同一個
    bug，只是當時漏了這一支：`rows[-1-months]` 數的是**列**，序列只要少一個
    月或多一筆重複，往前數三列就不是三個月前。

    這不是假設性的問題——`CUSR0000SASLE` 在 2025-10 就有一個缺漏值
    （FRED 上是「.」）。今天它落在四個月之外所以沒出事，但它會隨著時間
    往回滑進任何一個回看視窗，而出事的樣子是「數字看起來很正常，只是
    多算了一個月」——沒有任何東西會報錯。

    找不到正好 N 個月前那一筆時才退回數列數，並且只在那個日期真的不存在時。
    """
    if len(rows) <= months:
        return None
    cur = rows[-1]["value"]
    old = _at_date(rows, _shift_months(rows[-1]["date"], months))
    if old is None:
        old = rows[-1 - months]["value"]
    if not old:
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
    core_3m: float | None = None      # 核心 CPI 三個月年化
    core_6m: float | None = None
    # ---- 核心服務的黏性 ----
    # 只有一個時間尺度是不夠的：「三月年化 4.7%」本身不告訴你在加速還是
    # 減速。12m / 6m / 3m 並排才看得出方向，而方向才是降息時間表的關鍵。
    supercore_12m: float | None = None
    supercore_6m: float | None = None
    supercore_3m: float | None = None
    supercore_streak: int = 0          # 三月年化連續高於門檻的月數
    supercore_dir: str = ""            # accel / decel / flat
    pce_supercore_12m: float | None = None
    pce_supercore_6m: float | None = None
    pce_supercore_3m: float | None = None
    flex_cpi: float | None = None      # 彈性核心 CPI（黏性的對照組）
    shelter_3m: float | None = None
    core_goods_yoy: float | None = None
    ex_shelter_yoy: float | None = None
    pce_headline_yoy: float | None = None
    pce_headline_3m: float | None = None
    pce_core_yoy: float | None = None
    pce_core_3m: float | None = None   # 核心 PCE 三個月年化（KPI 副標的短期動能）
    ppi_headline_yoy: float | None = None
    ppi_headline_mom: float | None = None
    ppi_headline_3m: float | None = None
    ppi_core_yoy: float | None = None
    ppi_core_mom: float | None = None
    ppi_core_3m: float | None = None
    median_cpi: float | None = None
    trimmed_cpi: float | None = None
    sticky_cpi: float | None = None
    expect_5y5y: float | None = None
    expect_1y: float | None = None
    gas: float | None = None
    oil_1m: float | None = None       # 油價近一個月變化 %
    # ---- 聯準會自己的預測（SEP）：九宮格通膨軸的門檻來源 ----
    sep_target: float | None = None       # 長期通膨目標（中位數）
    sep_next: float | None = None         # 對「明年」的核心 PCE 預測中位數
    sep_next_lo: float | None = None      # 同上，中央趨勢下緣
    sep_next_hi: float | None = None      # 同上，中央趨勢上緣
    sep_next_year: int | None = None      # 「明年」是哪一年
    extras: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 核心服務除住房（supercore）——**沒有現成序列，只能自己推**
# ---------------------------------------------------------------------------
# 這一段是為了修一個安靜了很久的口徑錯誤。
#
# 先前全站的「核心服務除住房」直接用 `CUSR0000SASLE`，而那條序列在 FRED 上的
# 正式名稱是 **Services Less Energy Services**——也就是**全部**核心服務，
# **含住房**，權重約 61.8%，不是除掉住房之後的 26.4%。
#
# 為什麼一直沒被發現：住房佔核心服務的 57%，所以兩條線長得很像、方向幾乎
# 一致，圖表看起來完全正常。但被它影響的三個地方講的都是結論：
#   ① 分項貢獻裡的「其他核心服務」
#   ② KPI 卡與黏性訊號（「已連 N 個月高於目標」）
#   ③ 首頁整體情勢那句「核心服務除住房已連 64 個月高於目標」
# ——那句話講的其實是含住房的核心服務，而住房正是它最黏的那一塊。
# 換句話說，**用來證明「除掉住房還是很黏」的那個數字，裡面有住房。**
#
# BLS 沒有發布「核心服務除住房」的指數（`SASL2RS` 是「服務除房租」，
# 含能源服務，會跟能源那一格重複計算），所以只能推。推法就是加權相減，
# 跟 `ex_shelter_yoy` 已經在用的公式同一條：
#
#     r_除住房 = (w_核心服務 × r_核心服務 − w_住房 × r_住房) / w_除住房
#
# 再把逐月的變化率串成指數，下游的年增率、年化、連續月數就都能照用。
def derive_supercore(core_services: list[dict], shelter: list[dict],
                     w_cs: float, w_sh: float,
                     base: float = 100.0) -> list[dict]:
    """
    用加權相減推出「核心服務除住房」的指數序列。

    兩條輸入序列**按日期對齊**，任一邊缺當月就從那裡截斷——寧可短一點，
    也不要把兩個不同月份的變化相減（那會產生一個看起來正常的假數字）。

    回傳 [{"date", "value"}]，指數基期是輸入序列第一個共同月份 = `base`。
    水準本身沒有意義（它不是官方指數），有意義的是它的**變化率**。
    """
    w_ex = w_cs - w_sh
    if w_ex <= 0 or w_cs <= 0:
        return []
    by_sh = {r["date"]: r["value"] for r in shelter}
    pairs = [(r["date"], r["value"], by_sh[r["date"]])
             for r in core_services if r["date"] in by_sh]
    if len(pairs) < 2:
        return []

    out = [{"date": pairs[0][0], "value": base}]
    skipped = 0
    for (d0, cs0, sh0), (d1, cs1, sh1) in zip(pairs, pairs[1:]):
        if not cs0 or not sh0:
            break
        # **只接相鄰的月份。** FRED 的來源序列會有缺漏（實例：CUSR0000SASLE
        # 的 2025-10 是空值），而缺一個月的話 d0→d1 其實是兩個月的變化，
        # 當成一個月串進指數會憑空多出一段漲幅——那個指數看起來完全正常，
        # 只是每一期都偏掉。寧可斷開重新起算，也不要接一段假的變化。
        if _shift_months(d1, 1) != d0:
            skipped += 1
            out.append({"date": d1, "value": out[-1]["value"]})
            continue
        r_cs = (cs1 / cs0 - 1) * 100
        r_sh = (sh1 / sh0 - 1) * 100
        r_ex = (w_cs * r_cs - w_sh * r_sh) / w_ex
        out.append({"date": d1, "value": out[-1]["value"] * (1 + r_ex / 100)})
    if skipped:
        log.warning("核心服務除住房：來源序列有 %d 個月不連續，那幾個月的變化"
                    "當成 0 處理（缺口前後不能直接相減）。檢查 %s 與 %s 在 "
                    "FRED 上是不是有空值。", skipped, "CUSR0000SASLE",
                    "CUSR0000SAH1")
    return out


# ---------------------------------------------------------------------------
# 核心 PCE 的即時推估：用最新的 CPI 補上還沒公布的那個月
# ---------------------------------------------------------------------------
# 使用者的批評：「九宮格高中低不能只用 PCE，因為 PCE 是落後指標。」
#
# 具體有多落後：CPI 是 BLS 月中發、核心 PCE 是 BEA 月底發，中間差兩週。
# 所以每個月都有一段時間，畫面上有 7 月 CPI 但九宮格用的是 6 月 PCE——
# **九宮格活在一個月前的世界**，而那兩週正好是市場對通膨反應最大的時候。
#
# 為什麼不能直接把 CPI 塞進去比
# ----------------------------
# 九宮格的高／中／低門檻錨在 FOMC 自己的 SEP 預測，而 **SEP 預測的是核心
# PCE**。核心 CPI 結構上比核心 PCE 高 0.3–0.5 個百分點（住房權重差一倍、
# 醫療口徑不同），直接送進去等於把門檻無故收緊那麼多——`classify_inflation`
# 的說明裡已經記著這個坑被踩過一次。
#
# 做法：**先把 CPI 換算成 PCE 口徑**，再送進原本的判定。
#
#     推估的核心 PCE 年增 = 最新的核心 CPI 年增 − 近 N 個月兩者的平均差距
#
# 差距用滾動平均而不是寫死的 0.3：兩者的落差本身會隨住房與醫療的相對
# 走勢變動，寫死一個常數只是把偏誤換個地方藏。
#
# 這只是**補上還沒公布的那一個月**。PCE 一公布就用實際值，推估值退場；
# 而且推估期間畫面上會明講「這是用 CPI 推估的」——一個影響部位表的數字
# 不能讓讀者以為它是官方公布值。
NOWCAST_GAP_MONTHS = 12


def nowcast_core_pce(pce_rows: list[dict], cpi_rows: list[dict],
                     months: int = NOWCAST_GAP_MONTHS) -> dict:
    """
    PCE 落後 CPI 時，用 CPI 推估最新一期的核心 PCE 年增率。

    回傳 {"value", "estimated", "gap", "asof", "source_month"}：
      estimated=False  → PCE 已經跟上，value 就是實際值，其餘欄位僅供參考
      estimated=True   → value 是推估值，asof 是被推估的那個月

    任何一邊資料不足就回實際值並且 estimated=False——**寧可用舊的真實
    數字，也不要用一個算不出信賴度的推估值**。
    """
    out = {"value": None, "estimated": False, "gap": None,
           "asof": "", "source_month": ""}
    if not pce_rows:
        return out
    out["value"] = yoy(pce_rows)
    out["asof"] = pce_rows[-1]["date"]
    if not cpi_rows or len(cpi_rows) <= 12 or len(pce_rows) <= 12:
        return out
    # CPI 沒有比 PCE 新 → 沒有東西好補
    if cpi_rows[-1]["date"] <= pce_rows[-1]["date"]:
        return out

    # 兩者在**重疊月份**上的年增率差距，取最近 months 個月的平均。
    py = {r["date"]: r["value"] for r in yoy_series(pce_rows)}
    cy = {r["date"]: r["value"] for r in yoy_series(cpi_rows)}
    common = sorted(d for d in py if d in cy
                    and py[d] is not None and cy[d] is not None)
    if len(common) < 6:                            # 樣本太少，不推估
        return out
    recent = common[-months:]
    gap = sum(cy[d] - py[d] for d in recent) / len(recent)

    latest_cpi = cy.get(cpi_rows[-1]["date"])
    if latest_cpi is None:
        return out
    out.update({"value": latest_cpi - gap, "estimated": True, "gap": gap,
                "asof": cpi_rows[-1]["date"],
                "source_month": cpi_rows[-1]["date"]})
    return out


# 「黏著」的門檻。2% 是目標，但月度資料的雜訊讓 2.0 太容易被穿越；
# 取 2.5 是為了讓「連續 N 個月高於門檻」這個數字代表真的卡住，
# 而不是在目標附近正常擺盪。
STICKY_THRESHOLD = 2.5


def _streak_above(rows: list[dict], months: int, threshold: float) -> int:
    """
    三月年化連續高於門檻幾個月。

    黏性的定義就是「該降的降不下來」，而「卡了多久」是它最直接的量度——
    比水準本身更能回答「降息時間表要不要往後推」。從最新一期往回數，
    一碰到低於門檻就停。
    """
    ann = annualized_series(rows, months)
    n = 0
    for r in reversed(ann):
        if r["value"] is None or r["value"] <= threshold:
            break
        n += 1
    # 數到底都沒有掉下去 → 回傳負數，讓上層知道這是「至少 N 個月」。
    # 抓取範圍是 config 的 fetch start 決定的，數到頭不代表真的只有這麼久，
    # 不標出來會把「至少 64」寫成「剛好 64」。
    return -n if ann and n == len(ann) else n


def _direction(v12: float | None, v6: float | None, v3: float | None) -> str:
    """
    動能階梯的方向。看的是短天期相對長天期，不是單期的漲跌。

    12m → 6m → 3m 一路往下 ＝ 穩定減速；一路往上 ＝ 重新加速。
    門檻 0.3 個百分點是為了濾掉月度雜訊：差距比這個小的時候，
    講「在減速」會是過度解讀。
    """
    if v3 is None or v12 is None:
        return ""
    gap = v3 - v12
    mid_ok = v6 is None or (v6 - v12) * gap >= 0     # 6m 沒有跟 3m 反向
    if gap < -0.3 and mid_ok:
        return "decel"
    if gap > 0.3 and mid_ok:
        return "accel"
    return "flat"


def _sep_year(rows: list[dict], year: int) -> float | None:
    """SEP 年頻序列裡對某一年的預測值。觀測日是那一年的 1 月 1 日。"""
    for r in rows or []:
        if str(r.get("date", ""))[:4] == str(year):
            return r.get("value")
    return None


# 抓不到 SEP 時的後備門檻。這兩個數字沒有外部依據——保留只是為了
# 「畫面不要因為一條序列抓不到就整頁失效」，而且用到時會在畫面上標示。
FALLBACK_LOW, FALLBACK_HIGH = 2.30, 2.90
# 「已經回到目標」不能卡在 2.00 這個點上：BEA 對核心 PCE 年增率的年度
# 修正常在 ±0.1–0.2 個百分點，取 0.25 是把量測誤差算進去。
# 這個 0.25 是判斷，不是外部標準——所以要寫出來。
TARGET_TOL = 0.25
# 「中」這一帶至少要有多寬。若聯準會對明年的預測已經收斂到 2.0，
# high 會落到 low 底下；這條下限保證兩條門檻不會交叉。
MIN_BAND = 0.25


def inflation_bands(s: "InflationSummary") -> dict:
    """
    九宮格通膨軸的兩條門檻，錨在聯準會自己給的數字。

        低 = 長期通膨目標 + 0.25
        高 = FOMC 對「明年」的核心 PCE 預測中位數

    回傳 {"low", "high", "auto", "why", "target", "next", "next_year", ...}，
    畫面直接照這個印，讀者才看得出門檻是哪來的。
    """
    t, n = s.sep_target, s.sep_next
    if t is None or n is None:
        return {"low": FALLBACK_LOW, "high": FALLBACK_HIGH, "auto": False,
                "target": t, "next": n, "next_year": s.sep_next_year,
                "next_lo": s.sep_next_lo, "next_hi": s.sep_next_hi,
                "why": "沒有取得 FOMC 預測序列，改用後備門檻（無外部依據）"}
    low = t + TARGET_TOL
    high = max(n, low + MIN_BAND)
    return {"low": low, "high": high, "auto": True,
            "target": t, "next": n, "next_year": s.sep_next_year,
            "next_lo": s.sep_next_lo, "next_hi": s.sep_next_hi,
            "clamped": high > n,
            "why": (f"低＝長期目標 {t:.2f}% ＋ 0.25（量測誤差）；"
                    f"高＝FOMC 對 {s.sep_next_year} 年的核心 PCE 預測中位數 "
                    f"{n:.2f}%")}


def _yoy_nsa(nsa: list, sa: list, label: str = "") -> float | None:
    """
    年增率：優先用未季調，抓不到才退回季調。

    為什麼分開：**月增率與年增率該用不同的序列。**
      月增率／年化 → 季調。月與月之間本來就要剔除季節性才可比。
      年增率       → 未季調。前後相隔十二個月，季節性自己抵消掉了；
                     而且 BLS 公布的那個數字就是這樣算的。

    還有一個實務理由：季調指數在原始發布後最長五年內都可能因為季節因子
    重估而被回溯修改，未季調則永遠不動。

    ⚠️ **退回季調時一定要出聲。** 這個退路曾經安靜地吃掉一次真正的錯：
    未季調的序列代號打錯（用了 FRED 上不存在的 CUUR0000SA0L1E），抓不到
    資料，於是每次都退回季調——畫面照樣有數字，只是跟 BLS 差 0.3 個百分點，
    而且沒有任何跡象顯示修正沒有生效。安靜的退路會把 bug 藏起來。
    """
    v = yoy(nsa)
    if v is not None:
        return v
    sav = yoy(sa)
    if sav is not None:
        log.warning("%s 抓不到未季調序列，年增率退回季調——這會跟 BLS 公布的"
                    "數字差 0.1–0.3 個百分點。檢查 config/inflation.yaml 的"
                    "CPIAUCNS／CPILFENS 是否抓得到。", label or "CPI")
    return sav


def _log_yoy(label: str, rows: list, val) -> None:
    """把年增率用到的兩個觀測印進執行紀錄，方便跟官方數字核對。"""
    if not rows or val is None:
        return
    from .core import _shift_months, _at_date
    d1 = rows[-1]["date"]
    d0 = _shift_months(d1, 12)
    v0 = _at_date(rows, d0)
    log.info("%s 年增 %.2f%%：%s %.3f ÷ %s %s", label, val, d1,
             rows[-1]["value"], d0,
             f"{v0:.3f}" if v0 is not None
             else f"（找不到，退回往前數 12 列的 {rows[-13]['value']:.3f}）")


def summarize(series: dict[str, list[dict]], comp_meta: list[dict]) -> InflationSummary:
    s = InflationSummary()
    g = series.get

    # 年增率一律用**未季調**：BLS 新聞稿上的「年增 3.4%」就是這樣算的。
    # 用季調算會系統性地差 0.1–0.3 個百分點，畫面上就跟所有媒體對不上。
    # 抓不到未季調時退回季調——少 0.2 個百分點，總比整個數字消失好，
    # 但那是退路不是常態。
    s.headline_yoy = _yoy_nsa(g("CPIAUCNS", []), g("CPIAUCSL", []), "總體 CPI")
    s.core_yoy = _yoy_nsa(g("CPILFENS", []), g("CPILFESL", []), "核心 CPI")
    # 把年增率用到的兩個點印出來。這一段跟 BLS 公布的數字差 0.1 個百分點
    # 就會被讀者抓到，而反推除數很費事——直接印出來，一眼就能核對。
    _log_yoy("總體 CPI", g("CPIAUCNS", []) or g("CPIAUCSL", []), s.headline_yoy)
    _log_yoy("核心 CPI", g("CPILFENS", []) or g("CPILFESL", []), s.core_yoy)
    s.core_mom = mom_pct(g("CPILFESL", []))
    s.core_3m = annualized(g("CPILFESL", []), 3)
    s.core_6m = annualized(g("CPILFESL", []), 6)
    _sc = g("CPISUPERCORE", [])
    s.supercore_12m = annualized(_sc, 12)
    s.supercore_6m = annualized(_sc, 6)
    s.supercore_3m = annualized(_sc, 3)
    s.supercore_streak = _streak_above(_sc, 3, STICKY_THRESHOLD)
    s.supercore_dir = _direction(s.supercore_12m, s.supercore_6m, s.supercore_3m)

    _pcesc = g("IA001260M", [])
    s.pce_supercore_12m = annualized(_pcesc, 12)
    s.pce_supercore_6m = annualized(_pcesc, 6)
    s.pce_supercore_3m = annualized(_pcesc, 3)
    s.shelter_3m = annualized(g("CUSR0000SAH1", []), 3)
    s.core_goods_yoy = yoy(g("CUSR0000SACL1E", []))
    s.pce_headline_yoy = yoy(g("PCEPI", []))
    s.pce_headline_3m = annualized(g("PCEPI", []), 3)
    s.pce_core_yoy = yoy(g("PCEPILFE", []))
    s.pce_core_3m = annualized(g("PCEPILFE", []), 3)
    s.ppi_headline_yoy = yoy(g("PPIFIS", []))
    s.ppi_headline_mom = mom_pct(g("PPIFIS", []))
    s.ppi_headline_3m = annualized(g("PPIFIS", []), 3)
    s.ppi_core_yoy = yoy(g("PPIFES", []))
    s.ppi_core_mom = mom_pct(g("PPIFES", []))
    s.ppi_core_3m = annualized(g("PPIFES", []), 3)

    # ---- FOMC 經濟預測摘要（SEP）----
    # 年頻序列，觀測日就是被預測的那一年（2027-01-01 的值＝對 2027 年的預測）。
    # 取「明年」而不是「今年」：今年的預測是聯準會**預期會發生什麼**，
    # 明年的預測才是它認為的**收斂軌道**。見 config/inflation.yaml 的說明。
    s.sep_target = value_at(g("PCECTPIMDLR", []))
    _ny = clock.today().year + 1
    s.sep_next_year = _ny
    s.sep_next = _sep_year(g("JCXFEMD", []), _ny)
    s.sep_next_lo = _sep_year(g("JCXFECTL", []), _ny)
    s.sep_next_hi = _sep_year(g("JCXFECTH", []), _ny)

    s.median_cpi = value_at(g("MEDCPIM159SFRBCLE", []))
    s.trimmed_cpi = value_at(g("TRMMEANCPIM159SFRBCLE", []))
    s.sticky_cpi = value_at(g("CORESTICKM159SFRBATL", []))
    s.flex_cpi = value_at(g("COREFLEXCPIM159SFRBATL", []))
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

    sc = series.get("CPISUPERCORE", [])
    if summ.supercore_3m is not None:
        prev = annualized(sc[:-1], 3) if len(sc) > 4 else None
        put("supercore_3m", summ.supercore_3m, prev, f"{summ.supercore_3m:.1f}%")

    pce = series.get("PCEPILFE", [])
    if summ.pce_core_yoy is not None:
        prev = yoy(pce[:-1]) if len(pce) > 13 else None
        put("core_pce_yoy", summ.pce_core_yoy, prev, f"{summ.pce_core_yoy:.1f}%")

    med = series.get("MEDCPIM159SFRBCLE", [])
    if summ.median_cpi is not None:
        put("median_cpi", summ.median_cpi, value_at(med, 1), f"{summ.median_cpi:.1f}%")

    if summ.ex_shelter_yoy is not None:
        put("core_ex_shelter", summ.ex_shelter_yoy, None, f"{summ.ex_shelter_yoy:.1f}%")

    t = series.get("T5YIFR", [])
    if summ.expect_5y5y is not None:
        put("expect_5y5y", summ.expect_5y5y, value_at(t, 1), f"{summ.expect_5y5y:.2f}%")

    gasr = series.get("GASREGW", [])
    if summ.gas is not None:
        put("gas_price", summ.gas, value_at(gasr, 1), f"{summ.gas:.2f} 美元")

    cg = series.get("CUSR0000SACL1E", [])
    if summ.core_goods_yoy is not None:
        prev = yoy(cg[:-1]) if len(cg) > 13 else None
        put("core_goods_yoy", summ.core_goods_yoy, prev, f"{summ.core_goods_yoy:+.1f}%")

    return out
