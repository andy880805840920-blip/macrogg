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
check("⑤ 類別曲線：三個天期", h.count('class="chart-inspector"') == 1 and "data-points=" in h and "--n:3" in h)
h = charts.segbar([{"label": "a", "value": 1.0, "color": "#1"}, {"label": "b", "value": -0.2, "color": "#2"}])
check("⑤ 組成條：負值不畫、另行註明", h.count('class="sg-seg"') == 1 and "負值" in h)

# ---- 殖利率曲線 v2（2026-10）：型態、遠期、判讀 ----
R = le.regime
check("⑥a 長端漲較多＝熊陡（長端帶動）", R(20, 5)["zh"] == "熊陡" and R(20, 5)["lead"] == "長端帶動")
check("⑥b 短端跌較多＝牛陡（短端帶動）", R(-5, -20)["zh"] == "牛陡" and R(-5, -20)["lead"] == "短端帶動")
check("⑥c 短端漲較多＝熊平", R(5, 20)["zh"] == "熊平")
check("⑥d 長端跌較多＝牛平", R(-20, -5)["zh"] == "牛平")
check("⑥e 長漲短跌＝扭轉變陡；長跌短漲＝扭轉變平", R(5, -5)["zh"] == "扭轉變陡" and R(-5, 5)["zh"] == "扭轉變平")
check("⑥f 利差變動 2bp 內＝大致持平", R(10, 9)["zh"] == "大致持平")
check("⑥g 遠期：1 年 4%、2 年 5% → 1y1y 約 6.01%", abs(le._fwd(4, 1, 5, 2) - 6.0096) < 0.001)
_d0 = dt.date(2026, 1, 2)
_ser = {sid: [{"date": (_d0 + dt.timedelta(days=i)).isoformat(), "value": v0 + i * dv}
              for i in range(120)]
        for sid, v0, dv in (("DGS10", 4.0, 0.002), ("DGS2", 3.6, 0.0), ("DGS30", 4.5, 0.003),
                            ("DGS1", 3.7, 0.0), ("DGS5", 3.8, 0.001), ("DGS20", 4.4, 0.0025),
                            ("DGS3MO", 3.9, 0.0), ("T10YIE", 2.3, 0.0005), ("DFII10", 1.7, 0.0015),
                            ("THREEFYTP10", 0.5, 0.001))}
_rows = le.spread_rows(_ser)
check("⑥h 三組利差都算出來，10-2 一個月是熊陡（長端帶動）",
      [r["key"] for r in _rows] == ["10-2", "30-10", "30-2"]
      and _rows[0]["mom_regime"]["zh"] == "熊陡", [(r["key"], r["mom_regime"]) for r in _rows])
_st = le.curve_story(_rows, le.curve_drivers(_ser), le.forwards(_ser), fomc_next="10/28")
check("⑥i 判讀句：有型態、有長端拆解、接下來三條",
      "熊陡" in _st["head"] and "通膨預期" in _st["long"] and len(_st["outlook"]) == 3, _st)
check("⑥j 遠期四組都有，2y3y 對照內插的 3 年期",
      [x["key"] for x in le.forwards(_ser)] == ["1y1y", "2y3y", "5y5y", "10y20y"]
      and le.forwards(_ser)[1]["spot_zh"] == "3 年期")
_sn = le.curve_snapshots(_ser)
check("⑥k 曲線快照：現在／1 週前／1 個月前／年初", [x["label"] for x in _sn][:3] == ["現在", "1 週前", "1 個月前"])

if not ok:
    sys.exit(1)
print("\n全部通過")
