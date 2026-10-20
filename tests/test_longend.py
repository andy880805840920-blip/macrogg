"""長端頁 2026-10 改版：10Y 拆解（TIPS＋BEI、ACM）、拍賣判定、WAM、事件、Fed 跟上曲線。"""
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


# ---- 10Y 拆解（2026-10 v4）：名目 ＝ TIPS ＋ BEI；ACM 期限溢酬並列 ----
def bdays(start, n, f):
    d0, out, i = dt.date.fromisoformat(start), [], 0
    while len(out) < n:
        d = d0 + dt.timedelta(days=i)
        i += 1
        if d.weekday() < 5:
            out.append({"date": d.isoformat(), "value": f(len(out))})
    return out


y10 = bdays("2025-12-01", 230, lambda i: 4.0 + i * 0.002)
tips = bdays("2025-12-01", 229, lambda i: 1.8 + i * 0.0015)          # 晚一天：少最後一筆
acm = bdays("2025-12-01", 228, lambda i: 0.5 + i * 0.0005)
S = {"DGS10": y10, "DFII10": tips, "DGS20": y10, "DGS30": y10, "THREEFYTP10": acm}
ds = le.driver_series(S, {"acm": acm, "sf": acm})
check("① BEI＝名目 − TIPS（同一天）", all(abs(r["value"] - (y["value"] - t["value"])) < 1e-12
                                         for r, y, t in zip(ds["infl"], y10, tips)))
c = le.contribution_window(ds, "mtd")
check("① 名目變動＝TIPS 變動＋BEI 變動（恆等，終點取兩者共同的最後一天）",
      abs(c["nominal"] - c["parts"]["real"] - c["parts"]["infl"]) < 1e-6 and c["to"] == tips[-1]["date"], c)
check("① 模型拆解：預期利率路徑＋期限溢酬＝名目",
      abs((c["m_end"] - c["m_start"]) * 100 - c["path"] - c["parts"]["tp"]) < 1e-6)
check("① 驅動因素取與名目同向、變動最大的一項",
      le.pick_main({"real": -5, "infl": 14, "tp": 20}, 8) == "tp"
      and le.pick_main({"real": -5, "infl": 14, "tp": -20}, 8) == "infl"
      and le.pick_main({"real": -5, "infl": 3, "tp": 1}, 0.5) == "real")
lc = le.level_changes(y10)
check("① MTD／YTD 基期＝上月、去年最後一筆", lc["mtd_from"][:7] < lc["date"][:7]
      and lc["ytd_from"][:4] == str(int(lc["date"][:4]) - 1))
check("① 年初至今路徑從 0 附近起算", abs(le.ytd_paths(ds)["y10"][0]["value"] - 0.2) < 1e-6)
check("① 一句話寫出驅動因素", "驅動因素" in le.main_sentence(c))
check("① 白話說明（使用者指定）", "Fed 獨立性" in le.NATURE["infl"] and "Fed 未來政策路徑" in le.NATURE["real"])

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
                            ("DGS1", 3.7, 0.0), ("DGS5", 3.8, 0.001), ("DGS7", 3.9, 0.001), ("DGS20", 4.4, 0.0025),
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

# ---- 2026-10：Fiscal Data 拍賣、T-Bills 淨發行、買回 ----
fa = ts.normalize_fiscal_auction({"auction_date": "2026-10-07", "issue_date": "2026-10-15",
                                  "original_security_term": "10-Year", "security_term": "9-Year 10-Month",
                                  "security_type": "Note", "high_yield": "5.012", "avg_med_yield": "4.95",
                                  "offering_amt": "39000000000", "primary_dealer_accepted": "3900000000",
                                  "comp_accepted": "38800000000", "reopening": "Yes", "soma_accepted": "null"})
check("⑦a Fiscal Data：日期用 auction_date、增發、十億美元",
      fa["date"] == "2026-10-07" and fa["reopening"] and fa["offering"] == 39.0
      and round(fa["pd"], 1) == 3.9 and fa["median"] == 4.95 and fa["soma"] == 0, fa)
from src.analysis import liquidity as lq   # noqa: E402
_m = [{"date": "2026-08-31", "bills": 7248.07, "marketable": 31828.0},
      {"date": "2026-09-30", "bills": 7118.15, "marketable": 31834.9}]
_fed = [{"date": "2026-09-10", "value": 10.0}, {"date": "2026-09-24", "value": 6.0},
        {"date": "2026-10-09", "value": 4.0}, {"date": "2026-10-20", "value": 9.0}]
_sch = [{"start": "2026-08-14", "end": "2026-09-14", "mbs": 15.0, "rmp": 5.0},
        {"start": "2026-09-15", "end": "2026-10-14", "mbs": 16.0, "rmp": 0.0}]
_bn = lq.bill_net_monthly(_m, {"date": "2026-10-15", "net": 94.9}, _fed, _sch)
_r9 = _bn["rows"][0]
check("⑦b 淨發行＝月底存量差；Fed 依期別比例拆 RMP／MBS；私人＝淨 − Fed（可為負）",
      round(_r9["net"], 1) == -129.9 and round(_r9["rmp"], 1) == 2.5 and round(_r9["mbs"], 1) == 13.5
      and round(_r9["private"], 1) == -145.9, _r9)
_r10 = _bn["rows"][-1]
check("⑦c 當月至今：DTS 淨額、Fed 只算到 DTS 日期", _r10["partial"] and _r10["fed"] == 4.0
      and round(_r10["private"], 1) == 90.9 and _bn["mtd"] is _r10, _r10)
check("⑦d QRA 隱含 T-Bills＝私人持有借款 − coupon 淨發行",
      lq.qra_bill_implied({"borrowing": 628, "net_coupon": 360})["bills"] == 268)
check("⑦e 買回天期中文", le.bucket_zh("Nominal Coupons 10Y to 20Y") == "10–20 年"
      and le.bucket_zh("1Mo to 2Y") == "1 個月–2 年" and le.bucket_zh("TIPS 1Y to 10Y") == "TIPS 1–10 年")
_bars = {"10:50": 5.00, "10:55": 5.01, "11:00": 5.02, "11:50": 5.03, "11:55": 5.05, "12:00": 5.20}
check("⑦f 1 小時窗口：公告前最後一根 → ＋55 那根收盤", ts._window_bp(_bars, "11:00") == 4.0
      and ts._window_bp({"11:05": 1.0}, "11:00") is None)
_ops = [{"date": "2026-10-08", "type": "Liquidity Support", "sec": "Nominal Coupons", "bucket": "20Y to 30Y",
         "max": 6.0, "accepted": 6.0, "offered": 14.9},
        {"date": "2026-09-09", "type": "Cash Management", "sec": "Nominal Coupons", "bucket": "1Mo to 2Y",
         "max": 12.5, "accepted": 12.5, "offered": 28.0}]
_sch2 = {"name": "x", "ops": [{"date": "2026-08-18", "announce": "2026-08-17", "bucket": "Nominal Coupons 20Y to 30Y",
                               "type": "Liquidity Support", "max": 2.0},
                              {"date": "2026-10-27", "announce": "2026-10-26", "bucket": "Nominal Coupons 20Y to 30Y",
                               "type": "Liquidity Support", "max": 2.0},
                              {"date": "2026-11-05", "announce": "2026-11-04", "bucket": "Nominal Coupons 1Mo to 2Y",
                               "type": "Liquidity Support", "max": 4.0}]}
_bv = le.buyback_view(_ops, _sch2, {"2026-10-08": {"announce": {"10Y": 1.1}}}, dt.date(2026, 10, 19))
check("⑦g 買回：新到舊、投標倍數、排程上限低於近期實際時標出、現金管理不混入流動性支援",
      _bv["latest"]["date"] == "2026-10-08" and round(_bv["latest"]["cover"], 2) == 2.48
      and _bv["upcoming"][0]["recent_max"] == 6.0 and _bv["upcoming"][1]["recent_max"] is None
      and _bv["quarter"] == {"流動性支援": 6.0, "現金管理": 12.5}, _bv["upcoming"])

# ---- 2026-10：MMF ----
_sec = {"assets": {"2026-07": {"total": 8000.0}, "2026-08": {"total": 8100.0}},
        "flows": {"2026-01": {"total": 10.0, "gov": 5.0, "treasury": 5.0, "prime": 0.0, "taxex": 0.0},
                  "2026-02": {"total": -4.0, "gov": -2.0, "treasury": -2.0, "prime": 0.0, "taxex": 0.0}},
        "yields": {"2026-02": {"gov": 3.5, "treasury": 3.5, "prime": 3.6}}}
_fd = lq.fdic_savings([{"date": "2026-02-01", "value": 0.4}], {"data": {"2021-03": 0.04, "2021-05": 9.9}})
check("⑧a FDIC：2021-04 前用舊序列、之後只用 SNDR", _fd == {"2021-03": 0.04, "2026-02": 0.4}, _fd)
_mv = lq.mmf_view(_sec, {}, _fd, "2026-10-19")
check("⑧b MMF：年初至今累計、利差＝Government − 存款",
      _mv["ytd"][2026] == [("1月", 10.0), ("2月", 6.0)] and round(_mv["latest"]["spread"], 2) == 3.1, _mv["ytd"])
import io, zipfile                                    # noqa: E402
_buf = io.BytesIO()
with zipfile.ZipFile(_buf, "w") as z:
    z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
               'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
               '<sheet name="Tab.3.9" sheetId="1" r:id="rId1"/></sheets></workbook>')
    z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
               '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
    z.writestr("xl/sharedStrings.xml", '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
               '<si><t>Total</t></si></sst>')
    z.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
               '<row r="1"><c r="C1"><v>46235</v></c></row>'
               '<row r="2"><c r="A2" t="s"><v>0</v></c><c r="B2" t="s"><v>0</v></c><c r="C2"><v>55.1</v></c></row>'
               '</sheetData></worksheet>')
_t = ts._sec_table(ts._xlsx_sheets(_buf.getvalue(), {"Tab.3.9"})["Tab.3.9"], 2)
check("⑧c 標準函式庫讀 xlsx：Excel 序號轉月份", _t == {("Total", "Total"): {"2026-08": 55.1}}, _t)

# ⑨ 期貨 vs 點陣圖：Lead／Behind the Curve
_fc = {"r0": 3.875, "points": [{"month": "2026-12", "rate": 3.60}, {"month": "2027-06", "rate": 3.30},
                               {"month": "2027-12", "rate": 3.10}]}
_g = le.dots_gap(_fc, {2026: 3.625, 2027: 3.375}, None)
check("⑨a 每個年底一列、主判讀取最遠", [r["year"] for r in _g["rows"]] == ["2026", "2027"], _g["rows"])
check("⑨b 降得比點陣圖多＝Lead、27.5bp 留意",
      round(_g["gap_bp"], 1) == -27.5 and _g["status"] == "warning" and _g["stance"].startswith("Lead"), _g)
_g = le.dots_gap(_fc, {2027: 2.375}, None)
check("⑨c 降得比點陣圖少＝Behind、> 50bp 警戒", _g["stance"].startswith("Behind") and _g["status"] == "critical", _g)
_g = le.dots_gap(_fc, {2027: 3.15}, None)
check("⑨d < 12.5bp＝一致", _g["status"] == "good" and _g["stance"] == "一致", _g)
_g = le.dots_gap(None, {}, {"year": 2026, "market_end": 3.5, "dot_median": 3.625, "gap_bp": -12.6, "r0": 3.875})
check("⑨e 沒有期貨路徑時退回 mvd", bool(_g) and _g["rows"][0]["year"] == "2026" and _g["status"] == "warning", _g)
check("⑨f 都沒有資料時回 None", le.dots_gap(None, None, None) is None)

# ⑩ 財政部 Buybacks 卡：div 必須成對，否則 _collapse_sections 包不起來（07 編號與收合會掉）
import re as _re                                    # noqa: E402
from src.pages import longend as _LEp               # noqa: E402
from src import site as _site                       # noqa: E402
_r = {"date": "2026-10-15", "bucket_zh": "10–20 年", "type_zh": "流動性支援", "max": 6.0, "accepted": 6.0,
      "offered": 40.8, "cover": 6.8, "announce": {"10Y": 0.5}, "result": {}}
_bb = {"le": {"buybacks": {"rows": [_r], "latest": _r, "quarter": {"流動性支援": 37.1}, "quarter_from": "2026-08-18",
                           "caps": [], "upcoming": [{"date": "2026-10-22", "announce": "2026-10-21", "bucket_zh": "20–30 年",
                                                     "type_zh": "流動性支援", "max": 6.0}]}}}
_h = _LEp.buybacks(_bb)
check("⑩a Buybacks 卡 div 開關成對", len(_re.findall(r"<div\b", _h)) == _h.count("</div>"),
      (len(_re.findall(r"<div\b", _h)), _h.count("</div>")))
_w = _site._collapse_sections(f'<div class="grid"><div class="card"><h2 id="buybacks" data-sum="x">財政部 Buybacks</h2>{_h}</div></div>')
check("⑩b Buybacks 卡會被包成可收合的區塊", '<details class="card sect"' in _w and '<div class="card">' not in _w)

# ⑪ 卡片裡的 <script> 字串含 "</div><div>" 時，不能把卡片結尾找錯（長端頁 04～11 被包進 03 的原因）
_body = ('<div class="grid"><div class="card"><h2 id="a">A</h2><div>x</div>'
         '<script>var s=\'</div><div class="w">\';</script></div></div>'
         '<div class="grid"><div class="card"><h2 id="b">B</h2><p>y</p></div></div>')
_w = _site._collapse_sections(_body)
check("⑪ script 內的 div 字串不影響卡片邊界",
      _w.count('<details class="card sect"') == 2 and "</script></div></details>" in _w, _w)

# ⑫ 期限溢酬看上升速度、實質利率看離中性多遠
from src.analysis import rates as _rt              # noqa: E402
_mk = lambda vals: [{"date": f"2026-{1 + i // 22:02d}-{1 + i % 22:02d}", "value": v} for i, v in enumerate(vals)]
_flat = _mk([0.75] * 70)
check("⑫a 水準高但沒有上升＝正常", _rt.tp_speed(_flat)["status"] == "good")
_jump = _mk([0.30] * 49 + [0.30 + 0.45 * k / 20 for k in range(1, 21)])
check("⑫b 單月 +45bp＝警戒", _rt.tp_speed(_jump)["status"] == "critical", _rt.tp_speed(_jump))
_slow = _mk([0.30 + 0.50 * k / 69 for k in range(70)])
_sp = _rt.tp_speed(_slow)
check("⑫c 三個月 +45bp 左右、單月不到 +25bp＝留意", _sp["status"] == "warning", _sp)
check("⑫d 資料不足 63 個交易日回 None", _rt.tp_speed(_mk([0.5] * 40)) is None)
check("⑫e 實質利率：中性 +0.5pp 內正常、+1pp 以上警戒",
      [_rt.real_rate_status(v, 1.2) for v in (1.6, 2.0, 2.3)] == ["good", "warning", "critical"])
_sep = {"date": "2026-09-16", "years": ["2026", "Longer run"], "vars": {"ffr": {"median": [4.1, 3.2]}}}
check("⑫f 中性實質利率＝長期點陣圖 − 2%", abs(_rt.neutral_real(_sep)[0] - 1.2) < 1e-9)

# ⑬ 再融資聲明自動擷取、公眾持有債務動態、年底期貨口徑
_t = ("Quarterly Refunding Statement of Deputy Assistant Secretary for Federal Finance Brian Smith August 5, 2026 WASHINGTON — "
      "Based on current projected borrowing needs, Treasury anticipates maintaining nominal coupon and FRN auction sizes "
      "for at least the next several quarters. Treasury anticipates that, over the course of the upcoming quarter, it will "
      "purchase up to $38 billion in off-the-run securities across buckets for liquidity support and up to $25 billion in "
      "the 1-month to 2-year maturity bucket for cash management purposes.")
_orig = ts._page_text
ts._page_text = lambda url: _t
try:
    _st = ts.refunding_statement(["sb0590"])
finally:
    ts._page_text = _orig
check("⑬a 聲明：日期、指引原句、買回額度", _st.get("date") == "2026-08-05" and _st.get("bb_liq") == 38.0
      and _st.get("bb_cash") == 25.0 and "several quarters" in _st.get("guidance_en", ""), _st)
check("⑬b 指引中文對照", le.refunding_guidance_zh(_st["guidance_en"]).startswith("財政部預期至少未來數季"))
_q = ["2025-01-01", "2025-04-01", "2025-07-01", "2025-10-01", "2026-01-01"]
_s = {"FYGFGDQ188S": [{"date": q, "value": v} for q, v in zip(_q, [96.3, 95.0, 97.4, 98.2, 98.7])],
      "FYGFDPUN": [{"date": q, "value": 29e6 + i * 5e5} for i, q in enumerate(_q)],
      "GDP": [{"date": q, "value": 30000 * (1.014 ** i)} for i, q in enumerate(_q)],
      "A091RC1Q027SBEA": [{"date": q, "value": 1200 + i * 10} for i, q in enumerate(_q)],
      "MTSDS133FMS": [{"date": f"{2024 + (m + 9) // 12}-{(m + 9) % 12 + 1:02d}-01", "value": -150000} for m in range(18)]}
_d = _rt.DebtState(); _d.nominal_growth = 5.7
check("⑬c 公眾持有債務動態可計算", _rt._public_debt_dynamics(_d, _s, _s["GDP"], _s["A091RC1Q027SBEA"]))
_a = _d.dd_actual
check("⑬d 實際變化＝基本赤字＋利息＋成長＋其他", bool(_a) and abs(_a["primary"] + _a["interest"] + _a["growth"] + _a["other"] - _a["actual"]) < 1e-9, _a)
_fc2 = {"r0": 3.875, "points": [{"month": "2026-12", "rate": 4.08}, {"month": "2027-01", "rate": 4.20}, {"month": "2027-12", "rate": 4.55}]}
_g2 = le.dots_gap(_fc2, {2026: 4.125, 2027: 4.125}, {"year": 2026, "market_end": 4.13, "dot_median": 4.125, "gap_bp": 0.5, "r0": 3.875})
check("⑬e 當年度用 mvd（與上方年底政策利率同一數字）", _g2["rows"][0]["market"] == 4.13 and not _g2["rows"][0]["partial"], _g2["rows"][0])
check("⑬f 隔年沒有 1 月合約時用 12 月並標示", _g2["rows"][1]["partial"] and _g2["rows"][1]["month"] == "2027-12", _g2["rows"][1])
check("⑬g 短端：3 個月升、2 年不動＝近期升息定價增加", le.short_end_verdict(0, 12).startswith("3 個月期上升"))

# ⑭ 全球 10 年期日資料：三個來源的解析與 DTD／MTD／YTD
_jp = ("Interest Rate (October 2026),,,\nDate,1Y,2Y,3Y,4Y,5Y,6Y,7Y,8Y,9Y,10Y,15Y\n"
       "2026/10/1,1.668,1.939,2.077,2.274,2.407,2.534,2.657,2.82,2.952,3.092,3.62\n"
       "2026/10/2,1.6,1.9,2.0,2.2,2.4,2.5,2.6,2.8,2.9,-,3.6\n,,,\n")
_r = ts._jgb_parse(_jp)
check("⑭a JGB：取 10Y 欄、跳過「-」", _r == [{"date": "2026-10-01", "value": 3.092}], _r)
_orig = ts._g_get
ts._g_get = lambda url: ('\ufeff"",BBSIS.D\n"",Term structure\nComment,,\n2026-10-16,3.48,\n'
                         '2026-10-17,.,No value available\n2026-10-19,3.49,\n')
try:
    _r = ts.bund_10y(dt.date(2026, 10, 20))
finally:
    ts._g_get = _orig
check("⑭b Bundesbank：跳過假日的「.」", [x["value"] for x in _r] == [3.48, 3.49], _r)
ts._g_get = lambda url: "DATE,IUDMNPY\n14 Oct 2026,5.383\n15 Oct 2026,5.3092\n"
try:
    _r = ts.gilt_10y(dt.date(2026, 10, 20))
finally:
    ts._g_get = _orig
check("⑭c BoE：日期格式「15 Oct 2026」", _r[-1] == {"date": "2026-10-15", "value": 5.3092}, _r)
_rows = [{"date": "2025-12-30", "value": 4.10}, {"date": "2025-12-31", "value": 4.18},
         {"date": "2026-09-30", "value": 5.29}, {"date": "2026-10-15", "value": 5.10}, {"date": "2026-10-16", "value": 5.09}]
_c = le.dtd_mtd_ytd(_rows)
check("⑭d DTD／MTD／YTD 基期正確", round(_c["dtd"]) == -1 and round(_c["mtd"]) == -20 and round(_c["ytd"]) == 91, _c)

# ⑮ 法國／澳洲（CNBC）濾掉週末與重複報價；中國（財政部曲線）與加拿大（BoC）解析
import json as _json                                # noqa: E402
_bars = {"barData": {"priceBars": [
    {"tradeTime": "20261016000000", "open": "4.80", "high": "4.82", "low": "4.77", "close": "4.78"},
    {"tradeTime": "20261017000000", "open": "4.78", "high": "4.78", "low": "4.78", "close": "4.78"},
    {"tradeTime": "20261019000000", "open": "4.85", "high": "4.94", "low": "4.81", "close": "4.92"}]}}
ts._g_get = lambda url: _json.dumps(_bars)
try:
    _r = ts.cnbc_daily("FR10Y-FR", dt.date(2026, 10, 20))
finally:
    ts._g_get = _orig
check("⑮a CNBC：週末補值濾掉，DTD 對前一個交易日", [x["date"] for x in _r] == ["2026-10-16", "2026-10-19"]
      and round(le.dtd_mtd_ytd(_r)["dtd"]) == 14, _r)
ts._g_get = lambda url: _json.dumps({"heList": [{"workTime": "2026-10-19", "tenYear": "1.65"},
                                                {"workTime": "2026-10-10", "tenYear": "1.68"},
                                                {"workTime": "2026-10-16", "tenYear": ""}]})
try:
    _r = ts.cgb_10y(dt.date(2026, 10, 20))
finally:
    ts._g_get = _orig
check("⑮b 中國：保留調休的週六上班日、跳過空值、依日期排序", _r == [{"date": "2026-10-10", "value": 1.68},
                                                    {"date": "2026-10-19", "value": 1.65}], _r)
ts._g_get = lambda url: '"TERMS AND CONDITIONS"\n\n"date","BD.CDN.10YR.DQ.YLD"\n"2026-10-15","3.83"\n"2026-10-16","3.84"\n'
try:
    _r = ts.boc_10y(dt.date(2026, 10, 20))
finally:
    ts._g_get = _orig
check("⑮c 加拿大：Valet CSV", _r[-1] == {"date": "2026-10-16", "value": 3.84}, _r)

if not ok:
    sys.exit(1)
print("\n全部通過")
