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
from src.sec import SecClient, dedupe_deals

today = dt.date.today()
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

# ---- 金額解析 ----
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

cases = [
    ("⑤ 封面取最大值 ", COVER, 3.5),
    ("⑥ 封面無金額   ", "<html>no numbers here at all</html>", None),
    ("⑦ 只有小額數字 ", "<html>$2,000 denomination</html>", None),
]
for name, body, want_v in cases:
    c.failed = []
    c.session = type("S", (), {"get": lambda self, u, timeout=0: FakeResp(body)})()
    v = c.offering_amount("https://example.com/x.htm")
    print(f"{name}:", "通過" if v == want_v else f"失敗（得到 {v}，預期 {want_v}）")
    ok &= (v == want_v)

c.failed = []
v = c.offering_amount("")
print("⑧ 沒有文件連結 :", "通過" if v is None else "失敗")
ok &= v is None

# ---- 申報 → 交易的去重 ----
# 一筆公開發行會產生兩份申報（424B 定價當日、8-K 2.03 四個營業日內）。
# 不去重的話畫面上同一筆債會出現兩次，金額合計直接翻倍——
# 而那個合計是這一段唯一有交易意涵的數字。
def off(name, day, amt, form="424B2"):
    return {"name": name, "date": d(day), "form": form,
            "kind": "offering", "amount": amt}

def evt(name, day):
    return {"name": name, "date": d(day), "form": "8-K",
            "kind": "event", "amount": None, "items": "2.03"}

dd_cases = [
    ("⑨ 424B ＋ 同筆 8-K   ",
     [off("Alphabet", 10, 12.5), evt("Alphabet", 6)],
     [("Alphabet", "424B2")]),
    ("⑩ 8-K 配不到 424B    ",
     [off("Alphabet", 10, 12.5), evt("Meta", 40)],
     [("Meta", "8-K"), ("Alphabet", "424B2")]),
    ("⑪ 同金額重複的 424B  ",
     [off("Oracle", 30, 18.0), off("Oracle", 27, 18.0)],
     [("Oracle", "424B2")]),
    ("⑫ 金額不同不算重複   ",
     [off("Oracle", 30, 18.0), off("Oracle", 27, 5.0)],
     [("Oracle", "424B2"), ("Oracle", "424B2")]),
    ("⑬ 相隔太久不算重複   ",
     [off("Oracle", 60, 18.0), off("Oracle", 10, 18.0)],
     [("Oracle", "424B2"), ("Oracle", "424B2")]),
    ("⑭ 兩邊都沒金額也去重 ",
     [off("Meta", 20, None), off("Meta", 17, None)],
     [("Meta", "424B2")]),
    ("⑮ 不同公司不互相影響 ",
     [off("Meta", 20, 9.0), evt("Alphabet", 18)],
     [("Meta", "424B2"), ("Alphabet", "8-K")]),
]
for name, rows, want_v in dd_cases:
    got_v = [(r["name"], r["form"]) for r in dedupe_deals(rows)]
    hit = sorted(got_v) == sorted(want_v)
    print(f"{name}:", "通過" if hit else f"失敗（得到 {got_v}，預期 {want_v}）")
    ok &= hit

# 去重後仍要是時間降冪——畫面直接照這個順序印
seq = dedupe_deals([off("A", 5, 1.0), off("B", 40, 2.0), off("C", 20, 3.0)])
desc = [r["date"] for r in seq] == sorted((r["date"] for r in seq), reverse=True)
print("⑯ 去重後仍時間降冪  :", "通過" if desc else "失敗")
ok &= desc

# 空輸入不能爆
print("⑰ 空輸入            :", "通過" if dedupe_deals([]) == [] else "失敗")
ok &= dedupe_deals([]) == []

# 日期格式壞掉時不能把兩筆誤判成同一筆（寧可多列，不可漏列）
bad = [{"name": "X", "date": "not-a-date", "form": "424B2",
        "kind": "offering", "amount": 1.0},
       {"name": "X", "date": d(5), "form": "424B2",
        "kind": "offering", "amount": 1.0}]
n = len(dedupe_deals(bad))
print("⑱ 日期壞掉不誤併    :", "通過" if n == 2 else f"失敗（剩 {n} 筆）")
ok &= n == 2

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
