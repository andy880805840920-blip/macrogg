"""長端頁 2026-10 改版：三股力量拆解、拍賣判定、WAM、事件、Fed 跟上曲線。"""
import sys
import pathlib
import datetime as dt

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.analysis import longend as le          # noqa: E402
from src import treasury_source as ts           # noqa: E402
from src import charts                          # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過  " if cond else "失敗  ") + name + (f" — {detail}" if detail and not cond else ""))
    ok = ok and bool(cond)


def daily(month_vals: dict) -> list:
    out = []
    for m, v in month_vals.items():
        for d in (3, 10, 17):
            out.append({"date": f"{m}-{d:02d}", "value": v})
    return out


S = {
    "THREEFY10": daily({"2026-07": 4.6, "2026-08": 4.7, "2026-09": 5.0}),
    "THREEFYTP10": daily({"2026-07": 0.7, "2026-08": 0.8, "2026-09": 1.0}),
    "EXPINF10YR": [{"date": "2026-07-01", "value": 2.4}, {"date": "2026-08-01", "value": 2.45},
                   {"date": "2026-09-01", "value": 2.5}],
    "DGS10": daily({"2026-07": 4.62, "2026-08": 4.72, "2026-09": 5.05}),
}
dec = le.decompose(S)
check("① 三段相加＝擬合殖利率", all(abs(d["real"] + d["infl"] + d["tp"] - d["fitted"]) < 1e-9 for d in dec))
c = le.contribution(dec, 1)
check("① 本月主因是動最多的那段（期限溢酬 +20bp）", c["main"] == "tp" and round(c["parts"]["tp"]) == 20,
      c["parts"])
check("① 殘差＝實際 − 擬合的變動", round(c["resid"]) == 3, c["resid"])
check("① 一句話寫出主因與壓力", "期限溢酬" in le.main_sentence(c) and "財政與供給壓力" in le.main_sentence(c))
check("① 資料不足回 None", le.contribution(dec, 5) is None)
check("① 預期通膨的措辭：名目緊縮、實質未收緊", "名目緊縮、實質未收緊" in le.NATURE["infl"])

# ---- 拍賣 ----
def auc(date, high, med, btc, pd, ind, dr, term="10-Year"):
    return {"date": date, "term": term, "tips": False, "frn": False, "high": high, "median": med,
            "btc": btc, "pd": pd, "indirect": ind, "direct": dr, "comp_acc": pd + ind + dr,
            "offering": 39.0, "reopening": False}
hist = [auc(f"2026-0{m}-10", 4.0, 3.95, 2.5, 10, 70, 20) for m in range(3, 9)]
weak = auc("2026-09-10", 4.30, 4.20, 2.2, 20, 60, 20)
S2 = {"DGS10": [{"date": "2026-09-10", "value": 4.25}]}
rows = le.auction_rows(hist + [weak], S2)
w = rows[-1]
check("② tail≈＝得標 − 當日收盤（+5bp）", round(w["tail_bp"]) == 5, w.get("tail_bp"))
check("② 交易商比例與近 6 場平均", round(w["dealer_pct"]) == 20 and round(w["avg_dealer"]) == 10)
check("② 三個訊號都偏弱 → 偏弱", w["verdict"] == "偏弱" and w["signals"] == 3, w["signals"])
check("② 分散度＝得標 − 中位", round(w["disp_bp"]) == 10)
check("② TIPS 不列入", not le.auction_rows([dict(weak, tips=True)], S2))
check("② 每個天期取最新一場", [r["date"] for r in le.latest_by_tenor(rows)] == ["2026-09-10"])
sp = le.size_path(hist + [weak])
check("② 每月拍賣規模", sp["10-Year"][-1]["value"] == 39.0 and len(sp["10-Year"]) == 7)

# ---- WAM ----
check("③ WAM：一半 1 年、一半 3 年 → 2 年",
      abs(ts.wam([("2027-01-01", 100), ("2029-01-01", 100)], "2026-01-01") - 2.0) < 0.01)
check("③ 已到期與零面額不算", ts.wam([("2025-01-01", 100), ("2027-01-01", 0)], "2026-01-01") is None)
n = ts.normalize_auction({"auctionDate": "2026-09-24T00:00:00", "originalSecurityTerm": "7-Year",
                          "securityTerm": "7-Year", "highYield": "5.085", "offeringAmount": "44000000000",
                          "primaryDealerAccepted": "5447550000", "inflationIndexSecurity": "No"})
check("③ TreasuryDirect 欄位換成十億美元", n["offering"] == 44.0 and round(n["pd"], 2) == 5.45
      and n["date"] == "2026-09-24" and not n["tips"])

# ---- Fed 跟上曲線、事件 ----
m = le.match_the_curve({"year": "2026", "r0": 3.875, "market_end": 4.16, "dot_median": 4.125,
                        "gap_bp": 3.5}, c)
check("④ 期貨與點陣圖差 < 12.5bp → 已跟上", "已跟上" in m["verdict"] and round(m["market_bp"]) == 29)
m2 = le.match_the_curve({"year": "2026", "r0": 3.875, "market_end": 4.40, "dot_median": 4.125,
                         "gap_bp": 27.5}, None)
check("④ 市場多定價 → 還沒跟上", "還沒跟上" in m2["verdict"])
check("④ 缺資料回 None", le.match_the_curve(None, None) is None)
ev = le.events(dt.date(2026, 10, 5),
               [{"date": "2026-10-07", "type": "Note", "term": "10-Year", "security_term": "9-Year 10-Month",
                 "reopening": True, "offering": 39.0, "tips": False, "frn": False},
                {"date": "2026-10-06", "type": "Bill", "term": "6-Week"}], "2026-11-04")
kinds = [e["kind"] for e in ev]
check("④ 事件：只列 coupon、含再融資與 H.4.1、依日期排序",
      "拍賣" in kinds and "再融資" in kinds and "Fed 資產" in kinds
      and not any("6-Week" in e["text"] for e in ev) and [e["date"] for e in ev] == sorted(e["date"] for e in ev))
check("④ 事件的天期用中文", any("10 年（增發舊券）" in e["text"] for e in ev), [e["text"] for e in ev])

# ---- 圖表元件 ----
h = charts.bridge(4.68, "8 月", [{"label": "期限溢酬", "bp": 10, "main": True},
                                {"label": "預期通膨", "bp": -5}], 4.73, "9 月")
check("⑤ 利率橋：起點、兩段、終點", h.count('class="br-row') == 4 and "br-seg up" in h and "br-seg dn" in h)
h = charts.cat_lines([{"label": "現在", "color": "#000", "points": [("2Y", 4.0), ("10Y", 4.5), ("30Y", 4.8)]}])
check("⑤ 類別曲線：三個天期", h.count('class="cl-hit"') == 3 and "--n:3" in h)
h = charts.segbar([{"label": "a", "value": 1.0, "color": "#1"}, {"label": "b", "value": -0.2, "color": "#2"}])
check("⑤ 組成條：負值不畫、另行註明", h.count('class="sg-seg"') == 1 and "負值" in h)

if not ok:
    sys.exit(1)
print("\n全部通過")
