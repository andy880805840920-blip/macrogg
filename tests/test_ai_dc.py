"""
AI 大事：IPO 申報解析、數字檢查、媒體估值、資料中心州別與年度彙總（2026-11）。

    python tests/test_ai_dc.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.analysis import ipo_docs as I, datacenters as D, ai_events as A  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過 " if cond else "失敗 ") + name + ("" if cond else f"　{detail}"))
    ok = ok and bool(cond)


# ---- SEC 申報原文（2026-11-10 S-1/A 節錄，含 HTML 拆字的情形） ----
COVER = ("Subject to Completion. Dated November 10, 2026. Class A Common Stock 825,000,000 Shares Anthropic, PBC "
         "This is an initial public offering of shares of Class A common stock of Anthropic, PBC. We are selling "
         "801,351,354 shares of Class A common stock and the selling stockholders identified in this prospectus are "
         "selling an additional 23,648,646 shares of Class A common stock. It is currently estimated that the initial "
         "public offering price per share will be between $70.00 and $78.00 . We have applied to list our Class A common "
         "stock on the Nasdaq Global Select Market under the symbol “ANT.” the underwriters have the option to purchase "
         "up to an additional 123,750,000 shares of Class A common stock. agreed to purchase an aggregate of $26.0 billion "
         "of our Class N common stock in a private placement at a price per share equal to the initial public offering price. "
         "Class A, Class N, Class T, Class E, and Class F common stock to be outstanding after this offering and the concurrent "
         "private placement 13,086,672,593 shares (or 13,210,422,593 shares if the underwriters exercise) Use of proceeds We "
         "estimate that the net proceeds from the sale of shares of our Class A common stock by us in this offering and the "
         "sale of shares of our Class N common stock by us in the concurrent private placement will be approximately $84.6 "
         "billion (or approximately $93.7 billion if the underwriters’ option to purchase additional shares of our Class A "
         "common stock is exercised in full), based upon the assumed initial public offering price of $74.00 per share. "
         "In the nine months ended September 30, 2026 , our revenue was $33.2 billion , representing a year-over-year growth "
         "rate of 1,206% . Stock Split On September 17, 2026, the Company effected a 10-for-1 stock split of its shares. "
         "From January 2026 to February 2026, we sold an aggregate of 90,510,425 shares of our Series G-1 redeemable "
         "convertible preferred stock at a purchase price of $259.1364 per share, for an aggregate purchase price of "
         "$23,454,545,69 8 . From May 2026 to June 2026, we sold an aggregate of 77,637,878 shares of our Series H-1 "
         "redeemable convertible preferred stock at a purchase price of $589.0095 per share, for an aggregate purchase "
         "price of $45,729,447,703.")
T = I.parse_terms(COVER)
check("價格區間照原文 70–78（不是新聞標題的 70–80）", (T.get("price_lo"), T.get("price_hi")) == (70.0, 78.0), T)
check("發行股數：新股＋老股＝8.25 億股", T.get("shares_offered") == 825_000_000 and T.get("shares_secondary") == 23_648_646)
check("超額配售、同步私募、發行後股數", T.get("greenshoe") == 123_750_000 and T.get("private_placement") == 26.0
      and T.get("shares_after") == 13_086_672_593, T)
check("淨募資（含私募）與假設價格", T.get("net_proceeds") == 84.6 and T.get("net_proceeds_full") == 93.7
      and T.get("assumed_price") == 74.0 and T.get("net_incl_pp"))
check("代號不帶句點、股票分割 10 比 1", T.get("ticker") == "ANT" and T.get("split") == 10 and T.get("split_date") == "2026-09-17", T)
check("營收前 9 月 332 億美元、年增 1,206%", T.get("rev_9m") == 33.2 and T.get("rev_growth") == 1206)
R = I.parse_rounds(COVER)
check("歷輪：G、H 兩輪", [r["series"] for r in R] == ["G", "H"], R)
check("HTML 拆字的金額改用股數×價格（G 輪 234.5 億美元，不是 23.5 億）", abs(R[0]["amount"] - 23.4545) < 0.01, R[0])
Dv = I.derived(T, R)
check("隱含市值 = 發行後股數 × 價格區間（0.92–1.02 兆）", abs(Dv["cap_lo"] - 916.067) < 0.01 and abs(Dv["cap_hi"] - 1020.76) < 0.01)
check("最近一輪分割調整後 $58.90，IPO 區間高出 +19%～+32%", abs(Dv["last_round"]["adj"] - 58.90095) < 1e-4
      and round(Dv["last_round"]["vs_lo"], 2) == 0.19 and round(Dv["last_round"]["vs_hi"], 2) == 0.32)
blank = I.parse_terms("Class A common stock to be outstanding after this offering  shares We are selling shares of Class A")
check("早期申報數字空白：不產生 0 股", "shares_after" not in blank and "shares_offered" not in blank, blank)

# ---- AI 重點的數字檢查 ----
pts = ["發行 8.25 億股，價格區間 70 至 78 美元", "新股 8.01 億股、老股 2,365 萬股", "同步私募 260 億美元",
       "淨募資約 846 億美元", "前 9 月營收 332 億美元", "發行 9.5 億股", "營收 400 億美元", "123,456,789 股"]
good = I.check_points(pts, COVER)
check("數字對得上原文的保留（含億美元、億股換算）", good == pts[:5], good)
check("原文沒有的數字整點拿掉", not any(p in good for p in pts[5:]))

# ---- 媒體估值 ----
V = I.parse_valuation
check("估值標題：$1.4 trillion IPO valuation", V("EXCLUSIVE: Anthropic eyes $1.4 trillion IPO valuation") == 1400)
check("估值標題：valued at $1.02 trillion、$1.4tn", V("Anthropic seeks to be valued at $1.02 trillion") == 1020
      and V("Anthropic targets valuation of up to $1.4tn in IPO") == 1400)
check("問句／募資額不算估值", V("Is Anthropic worth $2 trillion? How about $1.5 trillion?") is None
      and V("Anthropic Sets Lower than Expected Valuation, Seeks to Raise $90 Billion in IPO") is None)
ser = I.valuation_series([{"date": "2026-11-10", "value": 1400, "source": "Reuters", "title": "a", "url": ""},
                          {"date": "2026-11-10", "value": 1020, "source": "Axios", "title": "b", "url": ""},
                          {"date": "2026-11-10", "value": 1300, "source": "WSJ", "title": "c", "url": ""},
                          {"date": "2026-11-06", "value": 1500, "source": "FT", "title": "d", "url": ""}])
check("每天一點：中位數與區間", [(s["date"], s["median"], s["lo"], s["hi"]) for s in ser]
      == [("2026-11-06", 1500, 1500, 1500), ("2026-11-10", 1300, 1020, 1400)], ser)

# ---- 公司清單 ----
cos = [c["zh"] for c in A.DEFAULTS["companies"]]
check("xAI 改為 SpaceX；新增 Tesla、TSMC、Micron、Broadcom、Marvell",
      "xAI" not in cos and all(c in cos for c in ("SpaceX", "Tesla", "TSMC", "Micron", "Broadcom", "Marvell")), cos)
check("舊事件的公司欄 xAI → SpaceX", A.CO_RENAME.get("xAI") == "SpaceX")

# ---- 資料中心：州別與年度彙總 ----
ov = {"OpenAI Stargate Milam": "TX"}
S = D.site_state
check("州：地址裡的州代碼＋郵遞區號", S({"Name": "x", "Address": "5420 Tulane Rd, Memphis, TN 38109"}, ov) == "TN")
check("州：地址只有州代碼、或州全名", S({"Name": "x", "Address": "3500 River Rd, The Dalles, OR"}, ov) == "OR"
      and S({"Name": "x", "Address": "1626 County Line Road Ridgeland, Mississippi"}, ov) == "MS")
check("州：名稱裡的州名、設定檔覆寫", S({"Name": "OpenAI Stargate Michigan", "Address": ""}, ov) == "MI"
      and S({"Name": "OpenAI Stargate Milam", "Address": ""}, ov) == "TX")
check("州：不認得就回 None（log 提醒補設定）", S({"Name": "Stream Phoenix", "Address": "2950 S. Litchfield Road"}, {}) is None)
dcs = [{"Name": "A", "Country": "United States", "Address": "x, TX 75001", "Owner": "Oracle #confident", "Users": "OpenAI #likely"},
       {"Name": "B", "Country": "United States", "Address": "y, TX 75002", "Owner": "Meta", "Users": ""},
       {"Name": "C", "Country": "Malaysia", "Address": "z", "Owner": "", "Users": ""}]
tls = [{"Data center": "A", "Date": "2025-06-01", "IT power (MW)": "100", "H100 equivalents": "100000", "Construction status": "ok"},
       {"Data center": "A", "Date": "2027-03-01", "IT power (MW)": "300", "H100 equivalents": "500000", "Construction status": ""},
       {"Data center": "B", "Date": "2024-05-01", "IT power (MW)": "50", "H100 equivalents": "40000", "Construction status": "x"},
       {"Data center": "C", "Date": "2025-01-01", "IT power (MW)": "999", "H100 equivalents": "9", "Construction status": ""}]
ag = D.aggregate(dcs, tls, [2025, 2026, 2027, 2028], {}, "2026-11-10")
tx = ag["states"]["TX"]
check("累積＝年底前最後一筆的加總（2025：A 100＋B 50 MW）", tx["lvl"][2025]["mw"] == 150 and tx["lvl"][2027]["mw"] == 350, tx["lvl"])
check("當年新增＝年底累積−前一年（2025 新增 100 MW、2027 新增 200 MW）",
      tx["add"][2025]["mw"] == 100 and tx["add"][2026]["mw"] == 0 and tx["add"][2027]["mw"] == 200, tx["add"])
check("只算美國站點；Epoch 的把握程度標記拿掉", list(ag["states"]) == ["TX"]
      and tx["sites"][0]["owner"] == "Oracle" and tx["sites"][0]["users"] == "OpenAI")
check("時間軸未來節點標推估", [m["f"] for m in tx["sites"][0]["ms"]] == [False, True], tx["sites"][0]["ms"])

# ---- 州長：改選前名單完整 ----
import yaml  # noqa: E402
gb = (yaml.safe_load((ROOT / "config" / "datacenters.yaml").read_text(encoding="utf-8")) or {}).get("governor_before") or {}
allst = (gb.get("D") or []) + (gb.get("R") or [])
check("改選前州長：50 州各一次", len(allst) == 50 and len(set(allst)) == 50, len(allst))

print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
