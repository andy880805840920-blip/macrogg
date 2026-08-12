"""
通膨端的規則引擎（P2）。

沿用勞動模組的 Flag 結構與撰寫原則：
    headline 白話講發生什麼、detail 補數字並解釋為何重要、
    impact 直接講對利率的意義。

注意通膨的方向與勞動相反：**通膨降溫 = 利降息**，通膨升溫 = 利升息。
"""

from __future__ import annotations

from typing import Callable

from .rules import Flag


RULES: list[Callable] = []


def rule(fn):
    RULES.append(fn)
    return fn


class InflationContext:
    def __init__(self, series: dict, summary, attribution, lights):
        self.series = series
        self.s = summary
        self.att = attribution
        self.lights = lights


# ---------------------------------------------------------------------------
# 1. 趨勢方向：三月年化 vs 年增率
# ---------------------------------------------------------------------------
@rule
def r_momentum(ctx) -> Flag | None:
    s = ctx.s
    if s.core_3m is None or s.core_yoy is None:
        return None
    gap = s.core_3m - s.core_yoy
    # 標題要寫出實際的門檻。只寫「高於年增率」會讓人以為差 0.1 個百分點
    # 就該亮燈，然後看到沒亮而以為程式壞了——門檻是 0.4 個百分點。
    if gap < -0.4:
        return Flag(
            "cpi_cooling", "alert", "近三月年化低於年增率 0.4 個百分點以上",
            f"核心 CPI 年增 {s.core_yoy:.1f}%，但把最近三個月的漲勢換算成年率只有 "
            f"{s.core_3m:.1f}%，低了 {abs(gap):.1f} 個百分點。"
            "年增率會被一年前的舊數字拖住，"
            "三個月年化反映的是當下的溫度，通常更早看出轉折。"
            "差距要大於 0.4 個百分點才視為方向明確，避免被單月雜訊帶著走。",
            "dovish", "通膨降溫的證據",
        )
    if gap > 0.4:
        return Flag(
            "cpi_reheating", "alert", "近三月年化高於年增率 0.4 個百分點以上",
            f"核心 CPI 年增 {s.core_yoy:.1f}%，但最近三個月換算成年率達 "
            f"{s.core_3m:.1f}%，高了 {gap:.1f} 個百分點。"
            "短期動能正在回升，這是通膨重新加速的早期訊號。"
            "差距要大於 0.4 個百分點才視為方向明確，避免被單月雜訊帶著走。",
            "hawkish", "通膨動能回升",
        )
    return None


# ---------------------------------------------------------------------------
# 2. 住房落後效果
# ---------------------------------------------------------------------------
@rule
def r_shelter_lag(ctx) -> Flag | None:
    s = ctx.s
    if s.ex_shelter_yoy is None or s.core_yoy is None:
        return None
    gap = s.core_yoy - s.ex_shelter_yoy
    if gap > 0.4:
        return Flag(
            "shelter_drag", "watch", "住房落後項推升整體讀數",
            f"核心 CPI 年增 {s.core_yoy:.1f}%，但把住房剔除後只有 {s.ex_shelter_yoy:.1f}%。"
            "住房項的算法是把既有租約一起平均，所以會落後市場實際租金大約一年。"
            "換句話說，現在的住房數字反映的是去年的租金行情。",
            "dovish", "實際通膨比表面低",
        )
    if gap < -0.4:
        return Flag(
            "shelter_understate", "watch", "非住房項壓力大於住房",
            f"核心 CPI 年增 {s.core_yoy:.1f}%，剔除住房後為 {s.ex_shelter_yoy:.1f}%。"
            "代表壓力來自住房以外的項目，住房反而在壓低整體數字。",
            "hawkish", "非住房項的壓力較大",
        )
    return None


# ---------------------------------------------------------------------------
# 3. Supercore（核心服務除住房）— Fed 最在意的一塊
# ---------------------------------------------------------------------------
@rule
def r_supercore(ctx) -> Flag | None:
    """
    水準與**方向**要一起看。

    先前只有純水準門檻（>4% 警戒、<3% 正常），於是「3.9% 而且在加速」
    不會報，「4.1% 而且在減速」會報——但前者才是比較該擔心的那一個。
    降息時間表看的是這一塊降不降得下來，不是它此刻停在哪個數字。
    """
    s = ctx.s
    if s.supercore_3m is None:
        return None
    _n = abs(s.supercore_streak)
    _stuck = (f"三個月年化已連續{'至少' if s.supercore_streak < 0 else ''} "
              f"{_n} 個月高於 2.5%。" if _n else "")
    _base = (f"剔除住房後的核心服務，近三個月年化 {s.supercore_3m:.1f}%"
             f"（近 12 個月 {s.supercore_12m:.1f}%）。"
             if s.supercore_12m is not None
             else f"剔除住房後的核心服務，近三個月年化 {s.supercore_3m:.1f}%。")

    if s.supercore_3m > 4.0:
        return Flag(
            "supercore_hot", "alert", "核心服務除住房仍高於目標區間",
            _base + _stuck
            + "這一塊的成本主要是人力，所以跟薪資直接連動——"
              "只要它降不下來，聯準會就很難確定通膨真的受控。",
            "hawkish", "聯準會最在意的一塊還沒降溫",
        )
    # 新增的一條：水準還沒到警戒，但方向轉為加速。
    # 這是「降息時間表要往後推」最早出現的訊號。
    if s.supercore_dir == "accel" and s.supercore_3m >= 2.5:
        return Flag(
            "supercore_reaccel", "watch", "核心服務重新加速",
            _base + "短天期已經高於長天期，代表這一塊的回落停住了。"
            + _stuck + "水準還沒到警戒區，但方向轉了——"
                       "降息時間表最先反映的是方向，不是水準。",
            "hawkish", "通膨最黏的一塊回落停住",
        )
    if s.supercore_3m < 3.0:
        return Flag(
            "supercore_cool", "info", "核心服務除住房回落至正常區間",
            _base + "這一塊跟薪資連動最深，降下來代表通膨的慣性正在減弱。",
            "dovish", "通膨的慣性正在減弱",
        )
    return None


# ---------------------------------------------------------------------------
# 4. 廣度：是全面性通膨還是少數項目帶動
# ---------------------------------------------------------------------------
@rule
def r_breadth(ctx) -> Flag | None:
    s = ctx.s
    if s.median_cpi is None or s.core_yoy is None:
        return None
    if s.median_cpi - s.core_yoy > 0.5:
        return Flag(
            "broad_inflation", "watch", "中位數高於核心，漲價廣度偏高",
            f"中位數 CPI 為 {s.median_cpi:.1f}%，高於核心 CPI 的 {s.core_yoy:.1f}%。"
            "中位數只看「漲幅排在正中間」的那個項目，完全不受極端值影響。"
            "它比核心還高，代表多數商品與服務都在漲，不是被幾個項目拉高的。",
            "hawkish", "通膨基礎廣泛，較難消退",
        )
    if s.core_yoy - s.median_cpi > 0.5:
        return Flag(
            "narrow_inflation", "watch", "核心高於中位數，漲價集中於少數項目",
            f"核心 CPI {s.core_yoy:.1f}%，但中位數只有 {s.median_cpi:.1f}%。"
            "多數項目其實漲得不多，是少數幾項把平均拉上去的。",
            "dovish", "通膨集中在少數項目",
        )
    return None


# ---------------------------------------------------------------------------
# 5. 通膨預期是否錨定
# ---------------------------------------------------------------------------
@rule
def r_expectations(ctx) -> Flag | None:
    s = ctx.s
    if s.expect_5y5y is None:
        return None
    if s.expect_5y5y > 2.60:
        return Flag(
            "expect_unanchored", "alert", "長期通膨預期偏離目標",
            f"五年後起算五年的通膨預期來到 {s.expect_5y5y:.2f}%。"
            "這是聯準會最怕的情況——一旦大家「相信」通膨會一直高，"
            "就會反映在定價與薪資談判上，通膨會自我實現。",
            "hawkish", "預期脫錨是聯準會的紅線",
        )
    if s.expect_5y5y < 2.20:
        return Flag(
            "expect_low", "info", "長期通膨預期錨定良好",
            f"五年後起算五年的通膨預期為 {s.expect_5y5y:.2f}%，錨定良好。"
            "代表市場相信聯準會最終能把通膨帶回目標。",
            # impact 先前寫「降息壓力較小」——那是鷹派的意思，跟 lean=dovish 相反。
            # 邏輯是：預期錨定得住，聯準會就不必為了守信用而硬撐高利率，
            # 反而**多了降息的空間**。lean 會計入鷹鴿淨值、句子會印在首頁的
            # 訊號列上，兩者指向相反時讀者只會覺得儀表板在自相矛盾。
            "dovish", "預期錨得住，聯準會有降息的空間",
        )
    return None


# ---------------------------------------------------------------------------
# 6. 能源傳導
# ---------------------------------------------------------------------------
@rule
def r_energy(ctx) -> Flag | None:
    s = ctx.s
    if s.oil_1m is None:
        return None
    if s.oil_1m > 8:
        est = s.oil_1m * 0.062 * 0.4      # 粗估：能源權重 6.2%，傳導係數約 0.4
        return Flag(
            "oil_up", "watch", "油價上行，未來一至兩月推升總體 CPI",
            f"原油近一個月上漲 {s.oil_1m:.0f}%。油價通常兩到四週後反映到加油站價格，"
            f"再進到 CPI 的能源項。以能源佔 CPI 約 6% 粗估，"
            f"接下來一兩個月大約會推高整體 CPI {est:.1f} 個百分點。"
            "注意這只影響總體，不影響核心。",
            "hawkish", "總體 CPI 的短期逆風",
        )
    if s.oil_1m < -8:
        est = abs(s.oil_1m) * 0.062 * 0.4
        return Flag(
            "oil_down", "watch", "油價下行，未來一至兩月壓低總體 CPI",
            f"原油近一個月下跌 {abs(s.oil_1m):.0f}%，"
            f"粗估接下來一兩個月會壓低整體 CPI 約 {est:.1f} 個百分點。"
            "同樣只影響總體，核心不受影響。",
            "dovish", "總體 CPI 的短期順風",
        )
    return None


# ---------------------------------------------------------------------------
# 7. 核心商品（關稅與供應鏈的觀察窗）
# ---------------------------------------------------------------------------
@rule
def r_core_goods(ctx) -> Flag | None:
    s = ctx.s
    if s.core_goods_yoy is None:
        return None
    if s.core_goods_yoy > 1.5:
        return Flag(
            "goods_inflation", "watch", "核心商品由負轉正",
            f"核心商品年增 {s.core_goods_yoy:+.1f}%。疫情後商品價格一度連續下跌，"
            "現在轉正通常跟關稅或供應鏈成本有關。"
            "商品通膨對聯準會比較棘手，因為升息壓不下供給面的成本。",
            "hawkish", "供給面成本上升",
        )
    if s.core_goods_yoy < -0.5:
        return Flag(
            "goods_deflation", "info", "核心商品續跌，抵消服務業壓力",
            f"核心商品年增 {s.core_goods_yoy:+.1f}%。商品端的下跌一直是"
            "壓低整體通膨的主力。",
            "dovish", "抵消服務業的漲價壓力",
        )
    return None


# ---------------------------------------------------------------------------
# 8. 距離 Fed 目標多遠
# ---------------------------------------------------------------------------
@rule
def r_target_gap(ctx) -> Flag | None:
    s = ctx.s
    if s.pce_core_yoy is None:
        return None
    gap = s.pce_core_yoy - 2.0
    # 低於目標要單獨講。先前這裡只有 `gap <= 0.3` 一條分支，沒有擋負值——
    # 核心 PCE 跌到 1.5% 時畫面會印「距離目標只剩 −0.5 個百分點」，
    # 而且結論寫成「已接近目標」。低於目標不是「接近」，那是**另一種**
    # 降息理由（而且比接近目標更強），對債券部位的意涵也不同。
    if gap < -0.2:
        return Flag(
            "below_target", "info", "核心 PCE 已低於 2% 目標",
            f"核心 PCE 年增 {s.pce_core_yoy:.1f}%，低於目標 {abs(gap):.1f} 個百分點。"
            "通膨低於目標時，維持現在的政策利率等於實質利率被動走高——"
            "這本身就是收緊，是降息的理由。",
            "dovish", "通膨低於目標，維持不動等於被動收緊",
        )
    if gap <= 0.3:
        return Flag(
            "at_target", "info", "核心 PCE 已接近 2% 目標",
            f"核心 PCE 年增 {s.pce_core_yoy:.1f}%，距離目標只剩 {gap:.1f} 個百分點。"
            "聯準會的目標講的就是這個指標，不是 CPI。",
            "dovish", "通膨已不構成升息理由",
        )
    if gap >= 0.8:
        return Flag(
            "above_target", "alert", "核心 PCE 顯著高於目標",
            f"核心 PCE 年增 {s.pce_core_yoy:.1f}%，高出目標 {gap:.1f} 個百分點。"
            "只要這個數字降不下來，就算就業轉弱，聯準會降息也會很猶豫。",
            "hawkish", "通膨仍是降息的阻力",
        )
    return None


# ---------------------------------------------------------------------------
def run_rules(ctx) -> list[Flag]:
    order = {"alert": 0, "watch": 1, "info": 2}
    flags = [f for f in (r(ctx) for r in RULES) if f is not None]
    flags.sort(key=lambda f: order.get(f.severity, 9))
    return flags
