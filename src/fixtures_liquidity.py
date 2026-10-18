"""
流動性群組的離線示範資料。

⚠️ 依趨勢生成的示範值，**不是真實數據**。

水準照 2026 年 8 月的實況設定：SOFR 貼在 IORB 下緣、ON RRP 幾乎抽乾
（實際 2026-08-25 只剩 4 億美元）、SRF 幾乎未動用——這樣離線畫面的
「緩衝池見底」故事才跟線上一致。
"""

from __future__ import annotations

import random
import datetime as dt

random.seed(20260826)

END = dt.date(2026, 8, 7)


def _bdays(n: int) -> list[str]:
    out, cur = [], END
    while len(out) < n:
        if cur.weekday() < 5:
            out.append(cur.isoformat())
        cur -= dt.timedelta(days=1)
    out.reverse()
    return out


def build() -> dict[str, list[dict]]:
    d = _bdays(260)
    s: dict[str, list[dict]] = {}
    # SOFR 在 IORB（3.65%）下方 2–8 個基點徘徊，偶爾貼上來。
    s["IORB"] = [{"date": dd, "value": 3.65} for dd in d]
    s["SOFR"] = [{"date": dd, "value": round(3.65 - 0.02
                                             - abs(random.gauss(0, 0.02)), 2)}
                 for dd in d]
    # EFFR 貼在 IORB 下方 1–3 個基點，波動比 SOFR 小（無擔保、交易量也小）。
    s["EFFR"] = [{"date": dd, "value": round(3.65 - 0.02
                                             - abs(random.gauss(0, 0.005)), 2)}
                for dd in d]
    # 利率走廊下緣：ON RRP 得標利率，FOMC 決議日才會變動，期間固定 3.40%。
    s["RRPONTSYAWARD"] = [{"date": dd, "value": 3.40} for dd in d]
    # ON RRP 由 800 億一路抽乾到接近零（單位：十億美元）。
    n = len(d)
    s["RRPONTSYD"] = [{"date": dd,
                       "value": round(max(0.3, 80.0 * (1 - i / (n * 0.9))
                                          + random.gauss(0, 1.5)), 3)}
                      for i, dd in enumerate(d)]
    # SRF 多數日子 0，近期連續幾天動用示範「緩衝池見底、轉向常態動用」的轉緊訊號。
    s["RPONTSYD"] = [{"date": dd, "value": 0.0} for dd in d]
    for i, v in zip(range(-5, 0), (1.2, 0.9, 1.8, 2.3, 2.6)):
        s["RPONTSYD"][i]["value"] = v
    # TGCR 貼在 SOFR 幾個基點內（同樣是擔保隔夜利率，樣本範圍更窄）。
    s["TGCRRATE"] = [{"date": dd, "value": round(3.65 - 0.03
                                             - abs(random.gauss(0, 0.02)), 2)}
                for dd in d]
    # 油價與 VIX 的 FRED 後備。
    s["DCOILWTICO"] = [{"date": dd, "value": round(88 + random.gauss(0, 1.2), 2)}
                       for dd in d]
    s["DCOILBRENTEU"] = [{"date": dd, "value": round(93 + random.gauss(0, 1.2), 2)}
                         for dd in d]
    s["VIXCLS"] = [{"date": dd, "value": round(17 + abs(random.gauss(0, 2.5)), 2)}
                   for dd in d]
    return s
