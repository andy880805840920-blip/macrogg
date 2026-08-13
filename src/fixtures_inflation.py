"""
通膨模組的離線示範資料（P2）。

⚠️ 這些是依趨勢生成的示範值，**不是真實數據**，不可用於研究。
   正式執行會全部改用 FRED 的真實資料。

   不過**水準是照 2026 年 6 月 SEP 的實況設定的**（核心 PCE 年底預測 3.3%、
   總體 3.6%），這樣示範資料才會跟聯準會模組的「三票主張升息」互相吻合——
   通膨若只有 2.4%，官員不會投票要求升息。
"""

from __future__ import annotations

import random
import datetime as dt

random.seed(20260812)

START = dt.date(2021, 1, 1)
END = dt.date(2026, 7, 1)


def _months(start=START, end=END) -> list[str]:
    out, cur = [], start
    while cur <= end:
        out.append(cur.isoformat())
        y, m = (cur.year + 1, 1) if cur.month == 12 else (cur.year, cur.month + 1)
        cur = dt.date(y, m, 1)
    return out


MONTHS = _months()


def _index(dates, end_level, yearly_pct, noise=0.03, recent_pct=None):
    """
    由「最終水準」與「年通膨率」反推整條指數序列。
    recent_pct 可以指定最近 6 個月改用不同的年率（模擬轉折）。
    """
    levels = [end_level]
    for i in range(len(dates) - 1):
        rate = recent_pct if (recent_pct is not None and i < 6) else yearly_pct
        mom = (1 + rate / 100) ** (1 / 12) - 1
        levels.append(levels[-1] / (1 + mom + random.gauss(0, noise / 100)))
    levels.reverse()
    return [{"date": d, "value": round(v, 3)} for d, v in zip(dates, levels)]


def _flat(dates, end_value, drift=0.0, noise=0.05):
    vals, v = [], end_value
    for _ in dates:
        vals.append(v)
        v -= drift / 12 + random.gauss(0, noise)
    vals.reverse()
    return [{"date": d, "value": round(x, 3)} for d, x in zip(dates, vals)]


def build() -> dict[str, list[dict]]:
    d = MONTHS
    s: dict[str, list[dict]] = {}

    # ---- 主軸：通膨回升中。核心 PCE 年增約 3.2%，近三個月年化更高 ----
    s["CPIAUCSL"] = _index(d, 325.8, 2.9, noise=0.04, recent_pct=4.0)
    s["CPILFESL"] = _index(d, 332.6, 2.9, noise=0.03, recent_pct=3.8)
    # 未季調版本：年增率專用。刻意給一組**略低**的值，因為實際上季調與
    # 未季調算出來的年增率就是會差 0.1–0.3 個百分點——離線畫面要能反映
    # 「這兩條不是同一個數字」，否則這個口徑差異在離線時完全看不出來。
    s["CPIAUCNS"] = _index(d, 324.1, 2.9, noise=0.04, recent_pct=3.8)
    s["CPILFENS"] = _index(d, 330.9, 2.9, noise=0.03, recent_pct=3.5)
    # PCE 兩條**刻意比 CPI 少一個月**。
    #
    # 這不是懶得補資料，是要讓離線預覽長得跟正式環境一樣：CPI 月中由 BLS
    # 發布、核心 PCE 月底由 BEA 發布，所以每個月都有兩週的時間，畫面上是
    # 「7 月 CPI ＋ 6 月核心 PCE」。先前 fixture 讓兩者同月，於是
    # 「整體情勢把 CPI 的期別套到 PCE 上」這個 bug 在離線模式下**完全看不到**，
    # 一路上線才被使用者抓到。fixture 跟現實不一樣的地方，就是測不到的地方。
    s["PCEPI"] = _index(d, 131.1, 2.6, noise=0.03, recent_pct=3.7)[:-1]
    s["PCEPILFE"] = _index(d, 132.2, 2.7, noise=0.02, recent_pct=3.6)[:-1]
    s["PPIFIS"] = _index(d, 149.6, 2.4, noise=0.06, recent_pct=3.4)
    s["PPIFES"] = _index(d, 147.0, 2.7, noise=0.05, recent_pct=3.3)

    # ---- CPI 分項 ----
    s["CPIUFDSL"] = _index(d, 338.9, 2.2, noise=0.04, recent_pct=3.1)   # 食物
    s["CPIENGSL"] = _index(d, 296.2, 1.0, noise=0.35, recent_pct=11.0)  # 能源（波動大）
    # 核心商品由負轉正——關稅推升的商品通膨，聯準會最棘手的一塊
    s["CUSR0000SACL1E"] = _index(d, 161.4, -0.2, noise=0.05, recent_pct=2.6)
    s["CUSR0000SAH1"] = _index(d, 350.9, 4.2, noise=0.02, recent_pct=3.1)  # 住房（緩降）
    s["CUSR0000SASLE"] = _index(d, 405.9, 3.6, noise=0.03, recent_pct=4.4)  # supercore

    # ---- PCE 版的 supercore（服務除能源與住房，鏈式價格指數）----
    # 設得比 CPI 版低約一個百分點：兩者的權重差很多（醫療在 PCE 裡
    # 權重大得多，而醫療服務這一輪漲得比其他服務項溫和），
    # 實務上 PCE supercore 幾乎都低於 CPI supercore。
    # 離線畫面要走到「兩者背離」那條分支，這個差距是刻意留的。
    s["IA001260M"] = _index(d, 133.5, 3.1, noise=0.02, recent_pct=3.5)

    # ---- 住房細項 ----
    s["CUSR0000SEHA"] = _index(d, 401.8, 3.9, noise=0.02, recent_pct=2.9)
    s["CUSR0000SEHC"] = _index(d, 398.3, 4.1, noise=0.02, recent_pct=3.0)

    # ---- 趨勢型指標（本身就是年化百分比）----
    s["MEDCPIM159SFRBCLE"] = _flat(d, 3.5, drift=-1.0, noise=0.09)
    s["TRMMEANCPIM159SFRBCLE"] = _flat(d, 3.3, drift=-0.9, noise=0.08)
    s["CORESTICKM159SFRBATL"] = _flat(d, 3.6, drift=-0.8, noise=0.07)
    # 彈性項刻意設得比黏性項低很多：這是這一輪通膨的典型形態——
    # 反應快的部分已經降完，黏的那一半還卡著。兩者的差距就是還沒走完的路。
    s["COREFLEXCPIM159SFRBATL"] = _flat(d, 1.9, drift=-2.6, noise=0.22)

    # ---- 通膨預期 ----
    # 長期預期已經有點鬆動，這是聯準會最緊張的地方
    s["MICH"] = _flat(d, 3.6, drift=0.2, noise=0.11)
    s["EXPINF1YR"] = _flat(d, 2.9, drift=0.1, noise=0.06)

    # ---- 每日序列 ----
    days, cur = [], dt.date(2026, 8, 7)
    while len(days) < 420:
        if cur.weekday() < 5:
            days.append(cur.isoformat())
        cur -= dt.timedelta(days=1)
    days.reverse()

    # 油價：近一個月上漲約 9%，用來觸發能源傳導規則
    oil, v = [], 84.6
    for i in range(len(days)):
        oil.append(v)
        v -= 0.29 if i < 22 else random.gauss(0.012, 0.5)
    oil.reverse()
    s["DCOILWTICO"] = [{"date": dd, "value": round(x, 2)} for dd, x in zip(days, oil)]
    s["DCOILBRENTEU"] = [{"date": dd, "value": round(x * 1.045, 2)}
                         for dd, x in zip(days, oil)]
    s["T5YIE"] = _daily(days, 2.63, 0.012)
    s["T5YIFR"] = _daily(days, 2.66, 0.010)

    # ---- FOMC 經濟預測摘要（SEP）----
    # 年頻、觀測日就是被預測的那一年。數值取自 2026 年 6 月 SEP 的**真實值**
    # （federalreserve.gov/monetarypolicy/fomcprojtabl20260617.htm）——
    # 這幾條不是模擬的，因為九宮格的門檻直接由它們決定，用假的會讓
    # 離線畫面的判定與正式執行對不起來。
    s["PCECTPIMDLR"] = [{"date": f"{y}-01-01", "value": 2.0}
                        for y in (2024, 2025, 2026)]
    s["JCXFEMD"] = [{"date": "2026-01-01", "value": 3.3},
                    {"date": "2027-01-01", "value": 2.5},
                    {"date": "2028-01-01", "value": 2.1}]
    s["JCXFECTL"] = [{"date": "2026-01-01", "value": 3.2},
                     {"date": "2027-01-01", "value": 2.3},
                     {"date": "2028-01-01", "value": 2.0}]
    s["JCXFECTH"] = [{"date": "2026-01-01", "value": 3.5},
                     {"date": "2027-01-01", "value": 2.6},
                     {"date": "2028-01-01", "value": 2.2}]

    # 汽油（週頻）
    weeks, cur = [], dt.date(2026, 8, 3)
    while len(weeks) < 140:
        weeks.append(cur.isoformat())
        cur -= dt.timedelta(days=7)
    weeks.reverse()
    s["GASREGW"] = _daily(weeks, 3.96, 0.035)
    return s


def _daily(dates, end_value, noise):
    vals, v = [], end_value
    for _ in dates:
        vals.append(v)
        v -= random.gauss(0, noise)
    vals.reverse()
    return [{"date": d, "value": round(x, 3)} for d, x in zip(dates, vals)]
