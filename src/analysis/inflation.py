"""
通膨模組的分析層（P2）。

刻意重用勞動模組的歸因引擎——CPI 分項貢獻與產業貢獻的數學結構完全相同：

    貢獻 = 權重 × 變化率

差別只在勞動的「權重」是各產業自己的人數（隱含在水準值裡），
而 CPI 的權重要另外從 BLS 的相對重要性表帶進來。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .core import annualized, annualized_series, yoy, mom_pct, value_at
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

    # 「剔除住房後」是一個**通膨率**，不是貢獻度：拿掉住房的貢獻之後，
    # 還要除以剩餘權重重新正規化，否則會低估約等於住房權重的比例（~35%）。
    # 下方的 ex_shelter_yoy（年增率版本）已經是這樣算的，這裡比照辦理。
    shelter_w = sum(
        float(meta_by_id.get(c.key, {}).get("weight", 0))
        for c in contribs if meta_by_id.get(c.key, {}).get("laggy")
    )
    ex_shelter = ((total - shelter) / (1 - shelter_w / 100)
                  if shelter_w < 100 else None)

    return AttributionResult(
        total=total,
        contributions=sorted(contribs, key=lambda c: c.value, reverse=True),
        aggregates={
            "explained": explained,
            "core_services": core_services,
            "supercore": supercore,
            "shelter": shelter,
            "food_energy": food_energy,
            "ex_shelter": ex_shelter,
            # 住房權重（%）。畫面上要用它把住房的「貢獻」還原成
            # 住房自己的漲幅，才能跟非住房的漲幅並排比較。
            "shelter_weight": shelter_w,
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
    pce_core_yoy: float | None = None
    pce_core_3m: float | None = None   # 核心 PCE 三個月年化（KPI 副標的短期動能）
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


def _yoy_nsa(nsa: list, sa: list) -> float | None:
    """
    年增率：優先用未季調，抓不到才退回季調。

    為什麼分開：**月增率與年增率該用不同的序列。**
      月增率／年化 → 季調。月與月之間本來就要剔除季節性才可比。
      年增率       → 未季調。前後相隔十二個月，季節性自己抵消掉了；
                     而且 BLS 公布的那個數字就是這樣算的。

    還有一個實務理由：季調指數在原始發布後最長五年內都可能因為季節因子
    重估而被回溯修改，未季調則永遠不動。一個會事後變動的年增率，
    跟「這個月漲了多少」這種歷史事實放在一起會很奇怪。
    """
    v = yoy(nsa)
    return v if v is not None else yoy(sa)


def summarize(series: dict[str, list[dict]], comp_meta: list[dict]) -> InflationSummary:
    s = InflationSummary()
    g = series.get

    # 年增率一律用**未季調**：BLS 新聞稿上的「年增 3.4%」就是這樣算的。
    # 用季調算會系統性地差 0.1–0.3 個百分點，畫面上就跟所有媒體對不上。
    # 抓不到未季調時退回季調——少 0.2 個百分點，總比整個數字消失好，
    # 但那是退路不是常態。
    s.headline_yoy = _yoy_nsa(g("CUUR0000SA0", []), g("CPIAUCSL", []))
    s.core_yoy = _yoy_nsa(g("CUUR0000SA0L1E", []), g("CPILFESL", []))
    s.core_mom = mom_pct(g("CPILFESL", []))
    s.core_3m = annualized(g("CPILFESL", []), 3)
    s.core_6m = annualized(g("CPILFESL", []), 6)
    _sc = g("CUSR0000SASLE", [])
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
    s.pce_core_yoy = yoy(g("PCEPILFE", []))
    s.pce_core_3m = annualized(g("PCEPILFE", []), 3)

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

    sc = series.get("CUSR0000SASLE", [])
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
