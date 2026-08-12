"""
EDGAR 發債申報解析的迴歸測試。

為什麼需要這個檔案
------------------
submissions 端點的欄位名稱無法在離線環境驗證（檔案太大，抓下來會被截斷；
EDGAR 的查詢介面又被 robots.txt 擋住）。所以解析程式是照假設寫的，
而這個測試釘住的是**假設不成立時的行為**：回傳空、記錄失敗、
畫面上該區塊不顯示——絕不憑假設印東西出去。

    python tests/test_edgar_filings.py
"""

import sys, datetime as dt
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent))
from src.sec import SecClient, dedupe_deals, is_preliminary
from src import clock

today = clock.today()
def d(n): return (today - dt.timedelta(days=n)).isoformat()

# 這一組刻意把「不該收的」全部放進來：
#   10-Q / 表格 4        本來就不是發債
#   只含 5.02 的 8-K     人事異動
#   FWP                  行銷條款表，一筆債會發好幾份
#   424B3                再售登記，公司沒拿到新錢
#   只含 1.01 的 8-K     8-K 最寬的萬用項，幾乎都不是發債
#   400 天前的 424B2     超出 RECENT_DAYS
GOOD = {"filings": {"recent": {
    "form":            ["424B2", "8-K",      "10-Q", "8-K",   "424B5", "4",
                        "FWP",   "424B3",    "8-K",  "424B2"],
    "filingDate":      [d(5),    d(12),      d(30),  d(40),   d(60),   d(3),
                        d(6),    d(20),      d(25),  d(400)],
    "items":           ["",      "2.03,9.01","",     "5.02",  "",      "",
                        "",      "",         "1.01", ""],
    "accessionNumber": ["0001652044-26-000090"]*10,
    "primaryDocument": ["d424b2.htm","f8k.htm","q.htm","f8k.htm","d424b5.htm",
                        "f4.xml","fwp.htm","d424b3.htm","f8k.htm","old.htm"],
    "primaryDocDescription": ["424B2","8-K","10-Q","8-K","424B5","4",
                              "FWP","424B3","8-K","424B2"],
}}}

c = SecClient.__new__(SecClient)
c.failed = []
ok = True

c._json = lambda url, label: GOOD
got = c.debt_filings(1652044)
want = [("424B2", d(5)), ("8-K", d(12)), ("424B5", d(60))]
res = [(x["form"], x["date"]) for x in got]
print("① 正常解析     :", "通過" if res == want else f"失敗 {res}")
ok &= res == want
print("   （已排除 10-Q、表格 4、FWP、424B3、只含 5.02／1.01 的 8-K、400 天前的舊申報）")
print("   文件連結範例 :", got[0]["doc_url"][:78])

# 缺 form 欄位 —— 這正是我無法離線驗證的那個假設
c.failed = []
c._json = lambda url, label: {"filings": {"recent": {"filingDate": [d(5)]}}}
r = c.debt_filings(1652044)
print("② 欄位名不符   :", "通過（回空並記錄）" if r == [] and c.failed else f"失敗 {r}")
ok &= (r == [] and bool(c.failed))

for name, payload in [("③ 端點回 404   ", None),
                      ("④ 結構全非預期 ", {"unexpected": 1})]:
    c.failed = []
    c._json = lambda url, label, p=payload: p
    r = c.debt_filings(1652044)
    print(f"{name}:", "通過（回空）" if r == [] else f"失敗 {r}")
    ok &= (r == [])

# ---------------------------------------------------------------------------
# 金額解析 —— 這一段釘住的是「解析錯了會怎樣」
#
# 實際跑出來的災情：近 120 天合計 1,828 億，等於季報申報值的 406%，
# 而 Alphabet 同期實際只發了約 250 億。兩個原因：
#   ① 封面上最大的數字往往是**貨架註冊額度**（up to $40,000,000,000），
#      不是這一筆的規模。舊做法「取封面最大值」每次都會讀到它，
#      而且同一個額度在不同文件上被讀成好幾筆新交易。
#   ② 424B2／424B5 **同時涵蓋預估版與定價版**，光看表格號分不出來，
#      所以同一筆債的宣布版與定價版各算一次。
# ---------------------------------------------------------------------------
class FakeResp:
    def __init__(self, text): self.text = text
    def raise_for_status(self): pass


COVER = """<html><body>
<p>PROSPECTUS SUPPLEMENT</p>
<h1>$3,500,000,000</h1>
<p>Alphabet Inc.</p>
<p>$1,500,000,000 4.125% Notes due 2035</p>
<p>$2,000,000,000 4.875% Notes due 2055</p>
<p>Interest payable May 15 and November 15. Minimum denomination $2,000.</p>
</body></html>"""

# 貨架額度混在同一份封面裡——舊做法會回 40.0
SHELF = """<html><body>
<p>Prospectus Supplement to Prospectus dated March 1, 2026</p>
<p>We may offer up to $40,000,000,000 of debt securities from time to time.</p>
<p>$2,500,000,000 4.125% Notes due 2035</p>
</body></html>"""

# 沒有分券格式，只寫總額
AGG = """<html><body>
<p>$6,000,000,000 aggregate principal amount of senior notes</p>
</body></html>"""

# 兩種寫法同時出現：只能算分券，不能相加（不然直接翻倍）
BOTH = """<html><body>
<p>$5,000,000,000 aggregate principal amount of notes</p>
<p>$2,000,000,000 4.000% Notes due 2030</p>
<p>$3,000,000,000 4.700% Notes due 2036</p>
</body></html>"""

cases = [
    ("⑤ 分券加總       ", COVER, 3.5),
    ("⑥ 封面無金額     ", "<html>no numbers here at all</html>", None),
    ("⑦ 只有小額數字   ", "<html>$2,000 denomination</html>", None),
    ("⑧ 貨架額度不計入 ", SHELF, 2.5),
    ("⑨ 只有總額的寫法 ", AGG, 6.0),
    ("⑩ 兩種都有取分券 ", BOTH, 5.0),
]
for name, body, want_v in cases:
    c.failed = []
    c.session = type("S", (), {"get": lambda self, u, timeout=0: FakeResp(body)})()
    v = c.offering_amount("https://example.com/x.htm")
    print(f"{name}:", "通過" if v == want_v else f"失敗（得到 {v}，預期 {want_v}）")
    ok &= (v == want_v)

c.failed = []
v = c.offering_amount("")
print("⑪ 沒有文件連結   :", "通過" if v is None else "失敗")
ok &= v is None


# ---- 預估版判別 ----
# Rule 430B／430C 強制要求的封面用語，是目前唯一穩定的判別方式。
prelim_cases = [
    ("⑫ Subject to Completion   ",
     "Subject to Completion, dated August 4, 2026", True),
    ("⑬ 全大寫也要抓到          ",
     "THE INFORMATION IN THIS PRELIMINARY PROSPECTUS SUPPLEMENT IS NOT COMPLETE",
     True),
    ("⑭ not complete and may... ",
     "This information is not complete and may be changed.", True),
    ("⑮ 定價版不該被誤判        ", COVER, False),
    ("⑯ 空字串不會爆            ", "", False),
]
for name, body, want_v in prelim_cases:
    got_v = is_preliminary(body)
    print(f"{name}:", "通過" if got_v == want_v else f"失敗（得到 {got_v}）")
    ok &= (got_v == want_v)

# 預估版的封面定價欄是空的 → 解析不到金額是**正常的**，不是抓取失敗
c.failed = []
c.session = type("S", (), {"get": lambda self, u, timeout=0: FakeResp(
    "<html>Subject to Completion, dated August 4, 2026<br>"
    "We are offering senior notes due 2035.</html>")})()
info = c.cover_info("https://example.com/p.htm")
hit = info["preliminary"] is True and info["amount"] is None
print("⑰ 預估版整合判讀 :", "通過" if hit else f"失敗（{info}）")
ok &= hit


# ---------------------------------------------------------------------------
# 申報 → 交易的去重
#
# 一筆公開發行會產生三到四份申報：預估版 424B（宣布日）、定價版 424B
# （定價日）、8-K 2.03（四個營業日內），多幣別再加一份。不去重的話
# 同一筆債會被算三次，而金額合計正是這一段唯一有交易意涵的數字。
# ---------------------------------------------------------------------------
def off(name, day, amt, form="424B2", prelim=False):
    return {"name": name, "date": d(day), "form": form,
            "kind": "offering", "amount": amt, "preliminary": prelim}


def evt(name, day):
    return {"name": name, "date": d(day), "form": "8-K",
            "kind": "event", "amount": None, "items": "2.03"}


dd_cases = [
    ("⑱ 424B ＋ 同筆 8-K     ",
     [off("Alphabet", 10, 12.5), evt("Alphabet", 6)],
     [("Alphabet", "424B2")]),
    ("⑲ 8-K 配不到 424B      ",
     [off("Alphabet", 10, 12.5), evt("Meta", 40)],
     [("Meta", "8-K"), ("Alphabet", "424B2")]),
    ("⑳ 同金額重複的 424B    ",
     [off("Oracle", 30, 18.0), off("Oracle", 27, 18.0)],
     [("Oracle", "424B2")]),
    ("㉑ 相隔太久不算重複     ",
     [off("Oracle", 60, 18.0), off("Oracle", 10, 18.0)],
     [("Oracle", "424B2"), ("Oracle", "424B2")]),
    ("㉒ 兩邊都沒金額也去重   ",
     [off("Meta", 20, None), off("Meta", 17, None)],
     [("Meta", "424B2")]),
    ("㉓ 不同公司不互相影響   ",
     [off("Meta", 20, 9.0), evt("Alphabet", 18)],
     [("Meta", "424B2"), ("Alphabet", "8-K")]),
    # 預估版 → 定價版 → 8-K：三份申報要收斂成一筆
    ("㉔ 預估版被定價版吸收   ",
     [off("Alphabet", 9, None, prelim=True), off("Alphabet", 6, 12.5),
      evt("Alphabet", 2)],
     [("Alphabet", "424B2")]),
    # 預估版還沒有對應的定價版 → 留著並標示，「有一筆在路上」本身是資訊
    ("㉕ 孤兒預估版仍然列出   ",
     [off("Microsoft", 1, None, form="424B5", prelim=True)],
     [("Microsoft", "424B5")]),
]
for name, rows, want_v in dd_cases:
    got_v = [(r["name"], r["form"]) for r in dedupe_deals(rows)]
    hit = sorted(got_v) == sorted(want_v)
    print(f"{name}:", "通過" if hit else f"失敗（得到 {got_v}，預期 {want_v}）")
    ok &= hit

# 這一條是修這個 bug 的核心：舊規則要求「金額相同」才算同一筆，
# 結果預估版（金額 None 或貨架額度）跟定價版（真實金額）永遠配不起來，
# 兩份都被留下 → 筆數與合計都翻倍。現在只看公司與日期。
g = dedupe_deals([off("Oracle", 30, 18.0), off("Oracle", 27, 5.0)])
hit = len(g) == 1 and g[0]["amount"] == 23.0
print("㉖ 金額不同也算同一筆   :",
      "通過（23.0＝多幣別分券相加）" if hit
      else f"失敗（{[(x['amount']) for x in g]}）")
ok &= hit

# 但相同的金額不能加兩次——重新申報、預估與定價金額一致都會這樣
g = dedupe_deals([off("Oracle", 30, 18.0), off("Oracle", 27, 18.0)])
hit = len(g) == 1 and g[0]["amount"] == 18.0
print("㉗ 相同金額不重複相加   :",
      "通過" if hit else f"失敗（{[(x['amount']) for x in g]}）")
ok &= hit

# 孤兒預估版：保留、但金額清成 None 且旗標留著（畫面靠它顯示「尚未定價」
# 並排除在筆數與合計之外）
g = dedupe_deals([off("Microsoft", 1, 40.0, prelim=True)])
hit = len(g) == 1 and g[0]["amount"] is None and g[0]["preliminary"] is True
print("㉘ 預估版不帶金額出去   :",
      "通過" if hit else f"失敗（{g}）")
ok &= hit

# 去重後仍要是時間降冪——畫面直接照這個順序印
seq = dedupe_deals([off("A", 5, 1.0), off("B", 40, 2.0), off("C", 20, 3.0)])
desc = [r["date"] for r in seq] == sorted((r["date"] for r in seq), reverse=True)
print("㉙ 去重後仍時間降冪     :", "通過" if desc else "失敗")
ok &= desc

# 空輸入不能爆
print("㉚ 空輸入               :", "通過" if dedupe_deals([]) == [] else "失敗")
ok &= dedupe_deals([]) == []

# 日期格式壞掉時不能把兩筆誤判成同一筆（寧可多列，不可漏列）
bad = [{"name": "X", "date": "not-a-date", "form": "424B2",
        "kind": "offering", "amount": 1.0},
       {"name": "X", "date": d(5), "form": "424B2",
        "kind": "offering", "amount": 1.0}]
n = len(dedupe_deals(bad))
print("㉛ 日期壞掉不誤併       :", "通過" if n == 2 else f"失敗（剩 {n} 筆）")
ok &= n == 2


# ---------------------------------------------------------------------------
# 端到端：離線素材走完整條路徑，畫面看到的就是這個
# ---------------------------------------------------------------------------
from src.fixtures_rates import offerings as fx_offerings   # noqa: E402

fx = fx_offerings()
deals = [r for r in fx if not r.get("preliminary")]
prelim = [r for r in fx if r.get("preliminary")]
names = sorted(r["name"] for r in deals)
hit = names == ["Alphabet", "Amazon", "Meta", "Oracle"]
print("㉜ 離線素材收斂成 4 筆  :", "通過" if hit else f"失敗（{names}）")
ok &= hit
hit = len(prelim) == 1 and prelim[0]["name"] == "Microsoft"
print("㉝ 孤兒預估版留在明細   :",
      "通過" if hit else f"失敗（{[r['name'] for r in prelim]}）")
ok &= hit
tot = sum(r["amount"] for r in deals if r["amount"] is not None)
hit = abs(tot - 43.0) < 1e-9      # 12.5 ＋ 12.5（9.0+3.5）＋ 18.0
print("㉞ 合計金額不重複計算   :",
      "通過（430 億）" if hit else f"失敗（{tot}）")
ok &= hit

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
