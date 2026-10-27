"""2026-10-27：拍賣結果 Fiscal Data 晚幾天才更新 → 用 TreasuryDirect 補上最新場次。"""
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import treasury_source as t     # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過  " if cond else "失敗  ") + name + (f" — {detail}" if detail and not cond else ""))
    ok &= bool(cond)


# TreasuryDirect 10/26 2 年期的實際欄位（auctionDate 是空的，日期在 competitiveAuctionCloseDate）
TD_2Y = {"cusip": "91282CRU7", "securityTerm": "2-Year", "originalSecurityTerm": "2-Year", "auctionDate": None,
         "competitiveAuctionCloseDate": "2026-10-26T00:00:00", "issueDate": "2026-11-02T00:00:00",
         "announcementDate": "2026-10-22T00:00:00", "highYield": "4.708", "medianYield": "4.655",
         "averageMedianYield": None, "lowYield": "4.580", "bidToCoverRatio": "2.59", "offeringAmount": "69000000000",
         "subtotalCompetitiveParAwardedInsideOfOfferingAmount": "67826401000",
         "primaryDealersCompetitiveParAwarded": "8818075000", "directBiddersCompetitiveParAwarded": "28027002700",
         "indirectBiddersCompetitiveParAwarded": "30981323300", "somaNoncompetitiveParAwarded": "7667168700",
         "reopening": "No", "inflationIndexSecurity": None, "floatingRate": "No", "securityType": "Note"}
n = t.normalize_td_auction(TD_2Y)
check("① 日期取 competitiveAuctionCloseDate", n["date"] == "2026-10-26", n["date"])
check("② 得標者組成、中位殖利率都有值（舊程式讀錯欄位名稱才會是 0）",
      round(n["pd"], 2) == 8.82 and round(n["direct"], 2) == 28.03 and round(n["indirect"], 2) == 30.98
      and n["median"] == 4.655 and round(n["comp_acc"], 2) == 67.83, n)
check("③ 非 TIPS、非增發", not n["tips"] and not n["reopening"] and n["term"] == "2-Year")

# Fiscal Data 還停在 9 月的 2 年期、10/21 的 20 年期結果是空的
fiscal = [{"cusip": "A", "date": "2026-09-22", "term": "2-Year", "security_term": "2-Year", "high": 4.787},
          {"cusip": "B", "date": "2026-10-21", "term": "20-Year", "security_term": "19-Year 10-Month", "high": None}]
td = [n, {"cusip": "B", "date": "2026-10-21", "term": "20-Year", "security_term": "19-Year 10-Month", "high": 5.469},
      {"cusip": "A", "date": "2026-09-22", "term": "2-Year", "security_term": "2-Year", "high": 9.999}]
m = t.merge_auctions(fiscal, td)
check("④ Fiscal Data 沒有的場次（10/26 2 年期）用 TreasuryDirect 補上", [r["date"] for r in m] == ["2026-09-22", "2026-10-21", "2026-10-26"])
check("⑤ Fiscal Data 結果是空的（10/21 20 年期）用 TreasuryDirect 補", m[1]["high"] == 5.469)
check("⑥ 兩邊都有結果時以 Fiscal Data 為主", m[0]["high"] == 4.787)

# TreasuryDirect 抓不到：只用 Fiscal Data，不會整個失敗
def boom(url):
    raise RuntimeError("down")
check("⑦ TreasuryDirect 失敗 → 回空清單（照用 Fiscal Data）", t.td_recent_auctions(_get_fn=boom) == [])
dup = t.td_recent_auctions(_get_fn=lambda u: [TD_2Y])
check("⑧ 同一場出現在多個清單（Note、TIPS…）只留一筆", len(dup) == 1)

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
