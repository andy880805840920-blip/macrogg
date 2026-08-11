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
from src.sec import SecClient

today = dt.date.today()
def d(n): return (today - dt.timedelta(days=n)).isoformat()

GOOD = {"filings": {"recent": {
    "form":            ["424B2", "8-K",      "10-Q", "8-K",   "424B5", "4",    "424B2"],
    "filingDate":      [d(5),    d(12),      d(30),  d(40),   d(60),   d(3),   d(400)],
    "items":           ["",      "2.03,9.01","",     "5.02",  "",      "",     ""],
    "accessionNumber": ["0001652044-26-000090"]*7,
    "primaryDocument": ["d424b2.htm","f8k.htm","q.htm","f8k.htm","d424b5.htm","f4.xml","old.htm"],
    "primaryDocDescription": ["424B2","8-K","10-Q","8-K","424B5","4","424B2"],
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
print("   （已正確排除 10-Q、表格 4、只含 5.02 的 8-K，以及 400 天前的舊申報）")
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

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
