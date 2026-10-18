"""
流動性頁（P7）分析層：美元貨幣市場的現況——Fed 利率走廊、SRF 動用量、
ON RRP 交易量與成交量、Fed 每月國庫券購買量（拆 RMP／MBS 再投入）。

三個指標、兩個方向（使用者原話）：
    SRF 動用量急升＋SOFR 貼近甚至超過 IORB（甚至超過 SRF 利率，名目走廊上限）
        → 廣泛的金融機構資金大幅轉緊
    ON RRP 交易量顯著上升
        → 機構與 MMF 帳上多餘資金增加，市場流動性充裕
三者都看「近期趨勢」（近 5 日均 vs 近 30 日均），不是看單一天的水準。

利率走廊四條線走 FRED 日頻資料；SRF 動用量、國庫券購買操作、SOFR／EFFR
成交量的權威來源是紐約聯儲 Markets Data API（src/treasury_source.py），
FRED 的 RPONTSYD 只在 SRF 來源失敗時當後備。
"""

from __future__ import annotations

import datetime as dt

# 利率走廊四條線：EFFR／SOFR 貼著走廊內部，IORB 是名目上緣、ON RRP 得標利率是下緣。
CORRIDOR = [
    ("IORB", "準備金利率（IORB，走廊上緣）", "var(--muted)"),
    ("EFFR", "聯邦資金有效利率（EFFR）", "var(--series-2)"),
    ("SOFR", "擔保隔夜融資利率（SOFR）", "var(--series-1)"),
    ("RRPONTSYAWARD", "ON RRP 利率（走廊下緣）", "var(--line-1)"),
]

# SRF 動用視為「有在用」的門檻（十億美元）。5000 萬美元以下視為雜訊（操作尾差）。
SRF_USE_FLOOR = 0.05


def corridor_series(series: dict, months: int = 6) -> list[dict]:
    """利率走廊四條線的近 N 個月資料，給 charts.rate_corridor 當右軸的線。"""
    out = []
    for sid, label, color in CORRIDOR:
        pts = series.get(sid) or []
        if pts:
            out.append({"label": label, "color": color, "points": pts})
    return out


def business_days(start: str, end: str) -> list[str]:
    """start 到 end（含）之間的平日（週一至週五）清單，不分辨聯邦假日。"""
    d0, d1 = dt.date.fromisoformat(start[:10]), dt.date.fromisoformat(end[:10])
    out, d = [], d0
    while d <= d1:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def ffill_series(rows: list, days: list[str]) -> list[dict]:
    """
    把序列補到完整的平日曆：假日（或任何缺值的平日）沿用最近一筆公布值，
    圖表才不會在假日斷開——跟官方「沒有新資料就是維持上次水準」的慣例一致。
    曆表開始前沒有任何資料的日子直接跳過，不虛構一個「之前」的值。
    """
    m = {r["date"]: r["value"] for r in (rows or []) if r.get("value") is not None}
    out, last = [], None
    for d in days:
        if d in m:
            last = m[d]
        if last is not None:
            out.append({"date": d, "value": last})
    return out


def _avgs(rows: list) -> tuple:
    """近 5 筆、近 30 筆的平均值（資料不足時能算多少算多少）。"""
    vals = [r["value"] for r in rows if r.get("value") is not None]
    a5 = sum(vals[-5:]) / len(vals[-5:]) if vals[-5:] else None
    a30 = sum(vals[-30:]) / len(vals[-30:]) if vals[-30:] else None
    return a5, a30


def srf_state(rows: list) -> dict:
    """
    SRF（常備回購機制）動用量現況、近 5／30 日均，與轉緊判定。

    rows：[{date, value, rate?}]（十億美元），優先傳入紐約聯儲逐日操作結果
    （treasury_source.srf_operations，含當日 SRF 利率），拿不到時傳 FRED
    RPONTSYD 當後備（沒有 rate 欄位）——呼叫端（build.build_liquidity_context）
    決定要傳哪一個，這裡不管來源。
    """
    rows = [r for r in (rows or []) if r.get("value") is not None]
    if not rows:
        return {}
    avg5, avg30 = _avgs(rows)
    recent = rows[-5:]
    used_days = sum(1 for r in recent if r["value"] > SRF_USE_FLOOR)
    # 近 5 日均比近 30 日均明顯放大（至少 3 億美元，或放大 1.5 倍）才算「升溫」；
    # 絕對門檻是因為 SRF 多數時間貼著零，純比例在零附近會失真。
    if avg5 is None or avg30 is None:
        trend = None
    elif avg5 > max(avg30 * 1.5, avg30 + 0.3):
        trend = "up"
    elif avg5 < avg30 * 0.6:
        trend = "down"
    else:
        trend = "flat"
    tight = used_days >= 3 and trend == "up"
    rate = next((r.get("rate") for r in reversed(rows) if r.get("rate") is not None), None)
    return {
        "latest": rows[-1]["value"], "date": rows[-1]["date"], "rate": rate,
        "used_days": used_days, "avg5": avg5, "avg30": avg30,
        "trend": trend, "tight": tight,
    }


def sofr_iorb_state(series: dict) -> dict:
    """SOFR − IORB 利差（bp）現況、近 5／30 日均，與轉緊判定。"""
    sofr_map = {r["date"]: r["value"] for r in series.get("SOFR") or [] if r.get("value") is not None}
    iorb_map = {r["date"]: r["value"] for r in series.get("IORB") or [] if r.get("value") is not None}
    dates = sorted(set(sofr_map) & set(iorb_map))
    if not dates:
        return {}
    spreads = [{"date": d, "value": (sofr_map[d] - iorb_map[d]) * 100} for d in dates]
    avg5, avg30 = _avgs(spreads)
    spread = spreads[-1]["value"]
    if avg5 is None or avg30 is None:
        trend = None
    elif avg5 > avg30 + 1:
        trend = "up"
    elif avg5 < avg30 - 1:
        trend = "down"
    else:
        trend = "flat"
    return {
        "spread": spread, "date": dates[-1], "avg5": avg5, "avg30": avg30,
        "trend": trend, "tight": spread > 0 and trend == "up",
    }


def sofr_vs_srf_rate(sofr_latest: float | None, srf_rate: float | None) -> bool | None:
    """SOFR 是否已經衝出走廊最上緣（SRF 利率）——比「超過 IORB」更嚴重一級。"""
    if sofr_latest is None or srf_rate is None:
        return None
    return sofr_latest > srf_rate


def rrp_state(series: dict) -> dict:
    """ON RRP 餘額（體系多餘現金的緩衝池）現況、近 5／30 日均，與回升判定。"""
    rows = [r for r in (series.get("RRPONTSYD") or []) if r.get("value") is not None]
    if not rows:
        return {}
    avg5, avg30 = _avgs(rows)
    latest = rows[-1]["value"]
    # 門檻取「50 億美元，或 30 日均的一成」兩者較大者——RRP 常態可能貼著零，
    # 純比例在零附近一樣會失真。
    if avg5 is None or avg30 is None:
        trend = None
    else:
        band = max(5.0, avg30 * 0.1)
        trend = "up" if avg5 > avg30 + band else ("down" if avg5 < avg30 - band else "flat")
    return {
        "latest": latest, "date": rows[-1]["date"], "avg5": avg5, "avg30": avg30,
        "trend": trend, "near_zero": latest < 5.0,
    }


_SRF_TXT = {"up": "SRF 動用升溫", "down": "SRF 動用降溫", "flat": "SRF 動用持平"}
_RRP_TXT = {"up": "ON RRP 交易量回升", "down": "ON RRP 交易量下滑", "flat": "ON RRP 交易量持平"}
_LEVEL_TXT = {"severe": "流動性嚴重轉緊", "tight": "流動性轉緊",
             "easing": "流動性寬鬆", "normal": "流動性穩定"}


def _srf_phrase(srf: dict) -> str | None:
    """SRF 近 5／30 日均都在門檻以下＝根本沒在動用，用詞比「持平」更精確。"""
    if not srf:
        return None
    avg5, avg30 = srf.get("avg5"), srf.get("avg30")
    if avg5 is not None and avg5 <= SRF_USE_FLOOR and (avg30 or 0) <= SRF_USE_FLOOR:
        return "SRF 未被動用"
    return _SRF_TXT.get(srf.get("trend"), "SRF 動用量無資料")


def _rrp_phrase(rrp: dict) -> str | None:
    if not rrp:
        return None
    if rrp.get("trend") == "down" and rrp.get("near_zero"):
        return "ON RRP 交易量見底"
    return _RRP_TXT.get(rrp.get("trend"), "ON RRP 交易量無資料")


def headline(srf: dict, rrp: dict, verdict_: dict | None = None) -> str:
    """
    一句話標題：SRF（資金緊俏）、ON RRP（緩衝池）的近期趨勢，再加一句整體結論。

    例：「SRF 未被動用，ON RRP 交易量持平，流動性穩定」——前兩句是量出來的現況，
    最後一句是 verdict() 判定的結論，三句合起來才是完整的「現在流動性怎麼樣」。
    """
    parts = [p for p in (_srf_phrase(srf), _rrp_phrase(rrp)) if p]
    level = _LEVEL_TXT.get((verdict_ or {}).get("level"))
    if level:
        parts.append(level)
    return "，".join(parts) if parts else "流動性資料不足"


def verdict(srf: dict, si: dict, rrp: dict, sofr_over_srf: bool | None) -> dict:
    """
    三個訊號合成一句結論：
        severe   SOFR 已經衝出 SRF 利率（走廊最上緣）——最嚴重，體系明顯缺準備金
        tight    SRF 連續動用放大，或 SOFR−IORB 轉正且持續擴大
        easing   SRF／利差都平靜，但 ON RRP 明顯回升——緩衝池在補
        normal   三者都在正常區間
    """
    if sofr_over_srf:
        return {"level": "severe", "label": "流動性嚴重轉緊",
                "text": "SOFR 已經衝出 SRF 利率（名目走廊上限）——連 Fed 的最後貸款人機制"
                        "都壓不住市場利率，體系明顯缺準備金，留意 Fed 是否緊急行動。"}
    hits = []
    if srf.get("tight"):
        hits.append(f'SRF 連續 {srf["used_days"]} 個營業日動用，近 5 日均較近 30 日均明顯放大')
    if si.get("tight"):
        hits.append(f'SOFR−IORB 轉正且持續擴大（現 {si["spread"]:+.0f}bp）')
    if hits:
        return {"level": "tight", "label": "流動性轉緊",
                "text": "；".join(hits) + "——體系準備金可能開始偏緊，留意 Fed 是否放緩或停止縮表。"}
    if rrp.get("trend") == "up":
        return {"level": "easing", "label": "流動性轉鬆",
                "text": "ON RRP 餘額明顯回升——機構與貨幣市場基金帳上的多餘現金增加，"
                        "體系流動性充裕，SRF 與 SOFR−IORB 也都沒有緊俏訊號。"}
    if srf or si or rrp:
        return {"level": "normal", "label": "流動性正常",
                "text": "SRF 動用、SOFR−IORB 利差、ON RRP 餘額都還在正常區間，"
                        "沒有轉緊或明顯轉鬆的訊號。"}
    return {"level": "unknown", "label": "資料不足", "text": ""}


# RMP 計畫從這一期開始（2025-12-12 起生效，使用者提供的事實，對應 FOMC 公告）。
# 紐約聯儲那個頁面往回還留著 2019–2020 另一輪操作的紀錄，用詞幾乎一樣（同樣是
# 「reinvestment purchases」＋「reserve management purchases」兩個詞），解析
# 的正則表達式會一併撈到——用起始日期把那些無關的舊資料擋在外面，不只是單純
# 取「最後 12 筆」（那樣在 RMP 計畫不滿 12 期時會混進不相干的舊資料）。
RMP_PROGRAM_START = "2025-12-01"


def tbill_purchase_flows(schedule: list) -> dict:
    """
    Fed 每期（約一個月，起訖日不對齊月曆）計畫購買的國庫券，RMP（準備金管理
    購買）與 MBS 到期再投入兩個金額——直接來自紐約聯儲官方逐期公布的拆分
    （treasury_source.rmp_schedule），不是用別的資料反推出來的估計值。

    只取 RMP_PROGRAM_START（這一輪 RMP 計畫開始）之後的期別，近 12 期——
    之後隨時間往前捲動，回溯上限固定 12 期，不會再往更早的（不相干的）
    舊操作撈資料。

    不含長端公債：長端公債在 Fed 持有部位到期後**不會**被重新投入國庫券，
    只會直接從資產負債表上消失；「全額再投入國庫券」的政策只適用機構證券
    （MBS）到期收到的本金（紐約聯儲 FAQ 原文：「continue to reinvest all
    principal payments received from the Federal Reserve's holdings of
    agency securities into Treasury bills」，agency securities＝MBS，
    沒有提到 Treasury notes/bonds）。

    這是**計畫金額**（Planned Operation Amount），不是逐筆結算金額——頁面
    原文也寫「RMP amounts are not on a preset course and may vary from
    month to month」，可能跟實際成交有落差，但這是官方唯一公布拆分的地方。
    """
    rows = [r for r in (schedule or []) if r["start"] >= RMP_PROGRAM_START]
    if not rows:
        return {}
    rows = rows[-12:]
    # x 軸位置用起始日（跟頁面本身「起始日在前」的寫法一致）；「資料至」用
    # 最新一期的結束日——那才是目前涵蓋到的最新日期。
    flows = [{"date": r["start"], "mbs": r["mbs"], "rmp": r["rmp"],
             "total": round(r["mbs"] + r["rmp"], 3),
             "period": f'{r["start"][5:].replace("-", "/")}–{r["end"][5:].replace("-", "/")}'}
            for r in rows]
    return {"flows": flows, "asof": rows[-1]["end"]}


def _sum_in_range(rows: list, start: str, end: str) -> float:
    return sum(r["offering"] for r in (rows or []) if start <= r["date"] <= end)


def bill_period_flows(bill_auctions: list, upcoming_bills: list, schedule: list,
                      today: str) -> dict:
    """
    財政部 T-Bills 毛發行量，拆成「Fed RMP 買走」「Fed MBS 到期再投入買走」
    「賣給私人市場」三塊——私人市場的部分＝毛發行量減掉 Fed 這兩塊，就是財政部
    短端融資真正需要貨幣市場吸收的量。

    時間段切割跟著 Fed RMP 的公布期別走（跟 tbill_purchase_flows 同一組，
    起訖日不對齊月曆）。只有「已經走完」的期別（結束日早於 today）才拆這
    三塊——還在進行中的最後一期，本期還沒結束就不該當成「已知結果」，連同
    更晚的已公告拍賣，合併成一塊「已公告但 Fed 分配未知」的毛發行量，不假裝
    知道 Fed 會買多少、也不假裝一個還沒走完的期別已經有完整的毛發行量。
    這塊的視野通常只有一到兩週（Bill 拍賣金額本來就是拍賣前幾天才公布）。
    """
    rows = [r for r in (schedule or []) if r["start"] >= RMP_PROGRAM_START][-12:]
    complete = [r for r in rows if r["end"] < today]
    past = []
    for r in complete:
        gross = _sum_in_range(bill_auctions, r["start"], r["end"])
        rmp, mbs = r["rmp"], r["mbs"]
        private = max(0.0, gross - rmp - mbs)
        past.append({"date": r["start"], "gross": round(gross, 3), "rmp": round(rmp, 3),
                     "mbs": round(mbs, 3), "private": round(private, 3),
                     "period": f'{r["start"][5:].replace("-", "/")}–{r["end"][5:].replace("-", "/")}',
                     "future": False})
    incomplete = [r for r in rows if r["end"] >= today]
    fut_start = incomplete[0]["start"] if incomplete else (rows[-1]["end"] if rows else None)
    future = None
    if fut_start:
        fut_rows = [b for b in (bill_auctions or []) + (upcoming_bills or [])
                   if b["date"] >= fut_start]
        if fut_rows:
            gross = sum(b["offering"] for b in fut_rows)
            d0 = min(b["date"] for b in fut_rows)
            d1 = max(b["date"] for b in fut_rows)
            future = {"date": fut_start, "gross": round(gross, 3),
                     "rmp": 0.0, "mbs": 0.0, "private": 0.0,
                     "period": f'{d0[5:].replace("-", "/")}–{d1[5:].replace("-", "/")}'
                               '（本期未結束／已公告）',
                     "future": True}
    flows = past + ([future] if future else [])
    if not flows:
        return {}
    return {"flows": flows, "asof": (future or past[-1])["date"]}


def bill_issuance_overview(bill_auctions: list, coupon_auctions: list, months: int = 12) -> dict:
    """
    財政部 T-Bills 發行概況（供「財政部 T-Bills 發行時程」窗格用）：近 N 個月
    的月度毛發行量走勢，與 T-Bills 占整體（Bills＋Coupon）發行量的比例——
    比例越高，代表財政部越依賴短端融資。
    """
    bill_m: dict[str, float] = {}
    for r in bill_auctions or []:
        bill_m[r["date"][:7]] = bill_m.get(r["date"][:7], 0.0) + r["offering"]
    coup_m: dict[str, float] = {}
    for r in coupon_auctions or []:
        if r.get("offering"):
            coup_m[r["date"][:7]] = coup_m.get(r["date"][:7], 0.0) + r["offering"]
    months_list = sorted(set(bill_m) | set(coup_m))[-months:]
    if not months_list:
        return {}
    trend = [{"date": m + "-01", "value": round(bill_m.get(m, 0.0), 3)} for m in months_list]
    bill_total = sum(bill_m.get(m, 0.0) for m in months_list)
    coup_total = sum(coup_m.get(m, 0.0) for m in months_list)
    share = (bill_total / (bill_total + coup_total) * 100) if (bill_total + coup_total) else None
    return {"trend": trend, "share": share, "bill_total": bill_total, "coupon_total": coup_total,
           "asof": months_list[-1]}
