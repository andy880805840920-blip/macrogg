"""
發債申報的分類、金額解析與多幣別測試。

為什麼需要這個檔案
------------------
這一段先前把**表格號當成證券種類**：只要是 424B2／424B5 就算發債。
但那兩個表格號只代表「定價後的公開說明書補充」，賣的東西可能是債券、
普通股、特別股、存託股、結構型商品或 ATM 增發計畫。實際跑出來的災情：

  · Oracle 最高 200 億美元的**普通股 ATM 增發**被算成發債
  · Alphabet 的 Class A／Class C **股票發行**被算成發債
  · Meta 的 250 億美元被讀成 500 億（分券表在文件裡出現兩次，加了兩遍）
  · Amazon 的 C$140 億被當成 US$140 億（"C$1,250,000,000" 裡面就含有
    "$1,250,000,000"），而且同一筆的 US$175 億 delayed draw term loan
    也被加了進來

下面每一個案例都對應一份使用者已經人工核對過的真實申報。這些案例
存在的意義是：**未來換一份新的申報進來，同樣的錯不能再犯一次。**

    python tests/test_offering_classify.py
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from src import sec                                  # noqa: E402
from src.analysis import fx as fxmod                 # noqa: E402

ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    print(f"{'通過' if cond else '失敗'}  {name}" + (f" — {detail}" if detail else ""))
    ok &= bool(cond)


def cover(text):
    return sec._read_cover(text)


# ---------------------------------------------------------------------------
# ① 分類：表格號一樣，內容不一樣
# ---------------------------------------------------------------------------
BOND = """
PROSPECTUS SUPPLEMENT
$25,000,000,000
Meta Platforms, Inc.
$3,000,000,000 4.250% Senior Notes due 2031
$6,000,000,000 5.100% Senior Notes due 2036
"""

ATM = """
PROSPECTUS SUPPLEMENT
Oracle Corporation
Up to $20,000,000,000 of Common Stock
At-the-Market Offering
We have entered into a sales agreement with the agents named herein.
"""

EQUITY = """
PROSPECTUS SUPPLEMENT
Alphabet Inc.
Class A Common Stock and Class C Capital Stock
$15,000,000,000
"""

PREF = """
PROSPECTUS SUPPLEMENT
$5,000,000,000
Depositary Shares Each Representing a 1/1,000th Interest in a Share of
6.000% Non-Cumulative Preferred Stock, Series A
"""

LOAN = """
On June 10, 2026 the Company entered into a credit agreement providing for a
US$17,500,000,000 delayed draw term loan facility.
"""

for name, text, want in [
        ("① 債券 → bond", BOND, sec.SEC_BOND),
        ("② ATM 普通股增發 → equity", ATM, sec.SEC_EQUITY),
        ("③ Class A／C 股票 → equity", EQUITY, sec.SEC_EQUITY),
        ("④ 存託股／特別股 → equity", PREF, sec.SEC_EQUITY),
        ("⑤ 定期貸款額度 → other", LOAN, sec.SEC_OTHER),
        ("⑥ 空文件 → unknown", "", sec.SEC_UNKNOWN)]:
    got = sec.classify_security(text)
    check(name, got == want, got)

# 債券說明書內文常常順帶提到普通股（掛牌資訊），不能因此被誤殺
MENTION = BOND + """
Our Class A common stock is listed on the Nasdaq Global Select Market.
We may repurchase notes from time to time.
"""
check("⑦ 債券內文提到普通股不會被誤殺",
      sec.classify_security(MENTION) == sec.SEC_BOND)


# ---------------------------------------------------------------------------
# ② 金額：分券表重複出現不能加兩次
# ---------------------------------------------------------------------------
TRANCHES = """
$3,000,000,000 4.250% Senior Notes due 2031
$2,000,000,000 4.600% Senior Notes due 2033
$6,000,000,000 5.100% Senior Notes due 2036
$4,000,000,000 5.400% Senior Notes due 2046
$6,000,000,000 5.550% Senior Notes due 2056
$4,000,000,000 5.700% Senior Notes due 2066
"""
META_REAL = "$25,000,000,000\n" + TRANCHES + """
Calculation of Filing Fee Tables
""" + TRANCHES              # 分券表在同一份文件裡出現兩次

info = cover(META_REAL)
check("⑧ Meta：分券表重複出現仍是 250 億",
      abs(info["totals"].get("USD", 0) - 25e9) < 1,
      f'{info["totals"].get("USD", 0):,.0f}')
check("⑨ 六檔分券只算六筆", len(info["tranches"]) == 6,
      str(len(info["tranches"])))

# 同金額、同到期年、不同票息 → 是兩張不同的券，不能誤併
TWO = ("$2,000,000,000 4.000% Notes due 2030\n"
       "$2,000,000,000 5.250% Notes due 2030\n")
check("⑩ 同金額不同票息算兩張券",
      abs(cover(TWO)["totals"].get("USD", 0) - 4e9) < 1,
      f'{cover(TWO)["totals"].get("USD", 0):,.0f}')

# 貨架註冊額度不能被讀成這一筆的規模
SHELF = ("We may offer up to $40,000,000,000 of debt securities.\n"
         "$2,500,000,000 4.125% Notes due 2035\n")
check("⑪ 貨架額度不計入",
      abs(cover(SHELF)["totals"].get("USD", 0) - 2.5e9) < 1)

# 帶單位的寫法也要認得
check("⑫ 「$1.25 billion」的寫法認得出來",
      abs(cover("$1.25 billion 4.000% Notes due 2032")["totals"].get("USD", 0)
          - 1.25e9) < 1,
      str(cover("$1.25 billion 4.000% Notes due 2032")["totals"]))


# ---------------------------------------------------------------------------
# ③ 多幣別：C$ 不是 $
# ---------------------------------------------------------------------------
AMZN_CAD = """
C$14,000,000,000
C$1,250,000,000 3.550% Notes due 2028
C$2,500,000,000 3.900% Notes due 2030
C$2,000,000,000 4.150% Notes due 2032
C$3,500,000,000 4.400% Notes due 2035
C$4,750,000,000 4.900% Notes due 2055
In addition, we entered into a US$17,500,000,000 delayed draw term loan facility.
"""
info = cover(AMZN_CAD)
check("⑬ Amazon：加幣不會被讀成美元",
      info["totals"].get("CAD") == 14e9 and "USD" not in info["totals"],
      str({k: f"{v:,.0f}" for k, v in info["totals"].items()}))
check("⑭ 同一份文件裡的定期貸款不進發債金額",
      abs(sum(info["totals"].values()) - 14e9) < 1)

for name, text, ccy, amt in [
        ("⑮ 歐元", "€4,000,000,000 3.250% Notes due 2033", "EUR", 4e9),
        ("⑯ 英鎊", "£1,500,000,000 4.500% Notes due 2040", "GBP", 1.5e9),
        ("⑰ 日圓", "¥576,500,000,000 1.150% Notes due 2031", "JPY", 576.5e9),
        ("⑱ 美元（US$ 寫法）",
         "US$3,000,000,000 4.000% Notes due 2030", "USD", 3e9)]:
    t = cover(text)["totals"]
    check(name, abs(t.get(ccy, 0) - amt) < 1, str(t))

# aggregate principal amount 的備案寫法也要保留幣別
check("⑲ 只有總額的寫法也保留幣別",
      cover("¥576,500,000,000 aggregate principal amount")["totals"]
      == {"JPY": 576.5e9})


# ---------------------------------------------------------------------------
# ④ 匯率換算：方向弄反會錯上百倍
# ---------------------------------------------------------------------------
SERIES = {
    "DEXUSEU": [{"date": "2026-08-07", "value": 1.0850}],   # 美元／歐元
    "DEXCAUS": [{"date": "2026-08-07", "value": 1.3720}],   # 加幣／美元
    "DEXJPUS": [{"date": "2026-08-07", "value": 152.40}],   # 日圓／美元
}
fx = fxmod.rates(SERIES)
check("⑳ 美元恆為 1", fx["USD"]["rate"] == 1.0)
check("㉑ 直接序列不動（一歐元 > 一美元）",
      abs(fx["EUR"]["rate"] - 1.0850) < 1e-9)
check("㉒ 反向序列要倒過來（一加幣 < 一美元）",
      abs(fx["CAD"]["rate"] - 1 / 1.3720) < 1e-9, f'{fx["CAD"]["rate"]:.4f}')
check("㉓ 日圓倒過來之後是很小的數",
      0 < fx["JPY"]["rate"] < 0.01, f'{fx["JPY"]["rate"]:.6f}')
check("㉔ 匯率帶日期（可以被重算）", fx["EUR"]["date"] == "2026-08-07")

c = fxmod.to_usd(14e9, "CAD", fx)
check("㉕ C$140 億約 102 億美元",
      abs(c["usd"] / 1e8 - 102) < 2, f'{c["usd"] / 1e8:,.1f} 億')
j = fxmod.to_usd(576.5e9, "JPY", fx)
check("㉖ ¥5,765 億約 38 億美元",
      abs(j["usd"] / 1e8 - 38) < 3, f'{j["usd"] / 1e8:,.1f} 億')
check("㉗ 換不到匯率就回 None，不用假設值補",
      fxmod.to_usd(1e9, "SEK", fx)["usd"] is None)
check("㉘ 假日空值要往回找",
      fxmod.rates({"DEXUSEU": [{"date": "2026-08-06", "value": 1.08},
                               {"date": "2026-08-07", "value": None}]})
      ["EUR"]["date"] == "2026-08-06")

# 顯示：原幣為主
check("㉙ 原幣以「億」為單位並帶記號",
      fxmod.fmt_native(14e9, "CAD") == "C$140 億", fxmod.fmt_native(14e9, "CAD"))
check("㉚ 日圓也一樣", fxmod.fmt_native(576.5e9, "JPY") == "¥5,765 億",
      fxmod.fmt_native(576.5e9, "JPY"))


# ---------------------------------------------------------------------------
# ④b 匯率要用**定價日**當天的，不是最新的
#
# 使用者抓到的：一筆七月定價的加幣債，括號裡寫「匯率 0.7177，2026-08-07」。
# 每一列的日期都一樣，因為 rates() 只留最新一筆、其餘整條丟掉。
#
# 錯在哪：發行人在定價那天就把金額鎖住了。用今天的匯率去標一筆已完成的
# 發行，等於讓那個數字**每天早上都變**，而變動的原因跟債券市場無關；
# 合計再拿去除季報申報值（歷史值），就是兩個口徑放進同一個比例。
# ---------------------------------------------------------------------------
HIST = {"DEXCAUS": [                      # 加幣／美元，越大代表加幣越弱
    {"date": "2026-05-01", "value": 1.4000},
    {"date": "2026-07-10", "value": 1.3450},   # 週五
    # 7/11–7/12 是週末，沒有報價
    {"date": "2026-08-07", "value": 1.3720},
]}
h = fxmod.rates(HIST)
check("㉛ rates() 留下整條歷史，不是只有最後一筆",
      len(h["CAD"]["series"]) == 3, str(len(h["CAD"]["series"])))

may = fxmod.to_usd(14e9, "CAD", h, on="2026-05-20")
aug = fxmod.to_usd(14e9, "CAD", h, on="2026-08-07")
check("㉜ 不同定價日換出不同金額（先前每一筆都一樣）",
      abs(may["usd"] - aug["usd"]) > 1e8,
      f'5月 {may["usd"]/1e8:,.1f} 億、8月 {aug["usd"]/1e8:,.1f} 億')
check("㉝ 五月那筆用的是五月的匯率", may["date"] == "2026-05-01", may["date"])
check("㉞ 定價日碰到週末 → 往前取最近一個交易日",
      fxmod.to_usd(14e9, "CAD", h, on="2026-07-12")["date"] == "2026-07-10")
check("㉟ 而且不算 stale（差兩天是正常的週末）",
      fxmod.to_usd(14e9, "CAD", h, on="2026-07-12")["stale"] is False)
check("㊱ 差超過七天才標 stale（資料真的有缺口）",
      fxmod.to_usd(14e9, "CAD", h, on="2026-06-15")["stale"] is True,
      fxmod.to_usd(14e9, "CAD", h, on="2026-06-15")["date"])
check("㊲ 定價日早於抓取起點 → 用最新的，但一定標出來",
      fxmod.to_usd(14e9, "CAD", h, on="2024-01-01")["stale"] is True)
check("㊳ 不給定價日就維持原行為（用最新的）",
      fxmod.to_usd(14e9, "CAD", h)["date"] == "2026-08-07")
check("㊴ 美元不受影響（本來就 1.0，也不該標日期）",
      fxmod.to_usd(25e9, "USD", h, on="2026-05-20")["date"] == "")

# 同一筆交易連跑兩次結果要一樣——「數字每天變」正是先前的問題
check("㊵ 定價日固定 → 換算結果固定（不會每天飄）",
      fxmod.to_usd(14e9, "CAD", h, on="2026-05-20")["usd"]
      == fxmod.to_usd(14e9, "CAD", h, on="2026-05-20")["usd"])



# ---------------------------------------------------------------------------
# ⑤ 筆數：算的是交易，不是申報
# ---------------------------------------------------------------------------
def flt(name, day, ccy, amounts, form="424B2", prelim=False, security="bond"):
    tr = [{"currency": ccy, "amount": a, "maturity": str(2030 + i), "coupon": ""}
          for i, a in enumerate(amounts)]
    tot = {}
    for t in tr:
        tot[t["currency"]] = tot.get(t["currency"], 0.0) + t["amount"]
    return {"name": name, "date": f"2026-08-{day:02d}", "form": form,
            "kind": "offering", "preliminary": prelim, "security": security,
            "tranches": tr, "totals": tot,
            "currency": ccy if tot else "",
            "principal": (tot.get(ccy) if tot else None),
            "amount": (tot["USD"] / 1e9 if "USD" in tot else None)}


# 預估版 → 定價版 → 8-K：三份申報，一筆交易
rows = sec.dedupe_deals([
    flt("Alphabet", 3, "USD", [], prelim=True),
    flt("Alphabet", 6, "USD", [3e9, 2e9, 6e9, 4e9, 6e9, 4e9]),
    {"name": "Alphabet", "date": "2026-08-10", "form": "8-K", "kind": "event",
     "items": "2.03", "security": "other", "tranches": [], "totals": {}},
])
deals = [r for r in rows if r.get("counts")]
check("㉛ 三份申報收斂成一筆", len(deals) == 1, str(len(deals)))
check("㉜ 金額是 250 億不是 500 億",
      abs(deals[0]["principal"] - 25e9) < 1, f'{deals[0]["principal"]:,.0f}')

# 同一週、不同幣別 → 兩筆（Alphabet 2026-05-07 的 €90 億與 C$85 億）
rows = sec.dedupe_deals([flt("Alphabet", 6, "EUR", [9e9]),
                         flt("Alphabet", 7, "CAD", [8.5e9])])
deals = [r for r in rows if r.get("counts")]
check("㉝ 同期不同幣別是兩筆", len(deals) == 2, str(len(deals)))
check("㉞ 而且不會被合併成一個美元數字",
      sorted(r["currency"] for r in deals) == ["CAD", "EUR"])

# 非債券完全不計數
rows = sec.dedupe_deals([flt("Oracle", 5, "", [], security="equity"),
                         flt("Meta", 6, "USD", [25e9])])
check("㉟ 股票發行不進筆數",
      [r["name"] for r in rows if r.get("counts")] == ["Meta"])
check("㊱ dedupe 這一層仍然把它帶出來（分類是分類，顯示是顯示）",
      len(rows) == 2)


# ---------------------------------------------------------------------------
# 明細只列債券
#
# 這一區問的是**長端供給**，而股票發行、ATM 增發、循環信用額度都不進債市。
# 先前把它們也列進明細（標「不計入發債」），本意是證明「我看過也知道為什麼
# 排除」。實際效果相反：七筆非債券混在十幾列裡、金額欄一半寫著「不計入
# 發債」，讀者要一列一列篩才找得到真正的債券。
#
# 分成兩層才對：`dedupe_deals` 照樣把所有申報帶出來（分類的完整性要保留），
# **顯示層**只留債券，被排除的用一句話交代筆數。
# ---------------------------------------------------------------------------
from src import build                                   # noqa: E402

_mixed = sec.dedupe_deals([
    flt("Meta", 6, "USD", [25e9]),                       # 債券
    flt("Oracle", 5, "", [], security="equity"),         # 股票
    flt("Alphabet", 4, "", [], security="other"),        # 貸款額度
    flt("Microsoft", 8, "USD", [], prelim=True),         # 已宣布未定價
])


class _HS:
    total_issued = 50.0


blk = build._offerings_block(_mixed, _HS(), {})
kinds = [r["kind"] for r in blk["rows"]]
check("㊳ 明細只留債券（含已宣布未定價的）",
      set(kinds) <= {"債券發行", "預估版"}, str(kinds))
check("㊴ 股票與其他融資不出現在明細裡",
      "股票發行" not in kinds and "其他融資" not in kinds, str(kinds))
check("㊵ 已宣布未定價的留著——那也是要來的供給", "預估版" in kinds, str(kinds))
check("㊶ 被排除的筆數仍然算得出來（摘要句要講）",
      blk.get("excluded_n") == 2, str(blk.get("excluded_n")))
check("㊷ other_n 沒有被動到（摘要句用它）",
      blk.get("other_n") == 2, str(blk.get("other_n")))
check("㊸ 金額合計不受影響（本來就只算債券）",
      blk.get("show_amount") is True and "億美元" in blk.get("total_display", ""),
      blk.get("total_display", ""))
# 顯示層：美元等值只寫金額，匯率與日期規則寫在註腳講一次
# 第三個參數是**原始 FRED 序列**，不是 rates() 的輸出
_blk_fx = build._offerings_block(
    sec.dedupe_deals([flt("Amazon", 11, "CAD", [14e9])]), _HS(), HIST)
_note = _blk_fx["rows"][0]["usd_note"]
check("㊺ 美元等值只寫金額，不重印匯率與日期",
      _note.startswith("約 US$") and "匯率" not in _note, _note)
check("㊻ 換算走的是定價日的匯率（8/11 的債用 8/07 最近一個交易日）",
      "約 US$102 億" == _note, _note)

check("㊹ 明細裡不再有「不計入發債」這種佔位字串",
      all(r["amount"] != "不計入發債" for r in blk["rows"]),
      str([r["amount"] for r in blk["rows"]]))

# 孤兒預估版：列出但不計數
rows = sec.dedupe_deals([flt("Microsoft", 8, "USD", [], prelim=True)])
check("㊲ 孤兒預估版不計數",
      len(rows) == 1 and not rows[0].get("counts"))

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
