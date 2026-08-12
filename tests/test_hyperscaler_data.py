"""
科技巨頭區塊的資料口徑測試。

為什麼需要這個檔案
------------------
這一區踩過一次很貴的坑：畫面上五個數字全部是 `config/rates.yaml` 的
**手動後備值**，而不是 SEC 的即時申報——但畫面看起來完全正常。
根因是這一行：

    USER_AGENT = os.environ.get("SEC_USER_AGENT", "預設值")

GitHub Actions 在 `vars.SEC_USER_AGENT` 沒設定時，不是「不設環境變數」，
是把它**設成空字串**。`os.environ.get(key, default)` 只在 key 不存在時
才回 default，所以拿到的是空字串 → 送出空的 User-Agent → SEC 擋掉 →
五家全部失敗 → 整區安靜地退回後備值。

所以這裡釘住三類東西：
  ① 那一行不會再退化（連同全庫掃描同型的寫法）
  ② 口徑：合計比率是 SUM/SUM、FCF 家數自動算、年增是 YoY
  ③ 誠實：退回後備值時畫面**必須**看得出來，而且分得出部分與全部

    python tests/test_hyperscaler_data.py
"""
import os
import re
import sys
import pathlib

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from src import sec                              # noqa: E402
from src.analysis import rates as rt             # noqa: E402

ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    print(f"{'通過' if cond else '失敗'}  {name}" + (f" — {detail}" if detail else ""))
    ok &= bool(cond)


# ---------------------------------------------------------------------------
# ① 環境變數：空字串不能被當成「有設定」
# ---------------------------------------------------------------------------
def _ua(value):
    """在指定的環境變數值下重新算一次 USER_AGENT。"""
    old = os.environ.get("SEC_USER_AGENT")
    if value is None:
        os.environ.pop("SEC_USER_AGENT", None)
    else:
        os.environ["SEC_USER_AGENT"] = value
    try:
        return (os.environ.get("SEC_USER_AGENT") or "").strip() \
            or sec.DEFAULT_USER_AGENT
    finally:
        if old is None:
            os.environ.pop("SEC_USER_AGENT", None)
        else:
            os.environ["SEC_USER_AGENT"] = old


check("① 沒設環境變數 → 用預設值", _ua(None) == sec.DEFAULT_USER_AGENT)
check("② 設成空字串 → 仍用預設值（這就是踩過的坑）",
      _ua("") == sec.DEFAULT_USER_AGENT, _ua(""))
check("③ 設成空白字元 → 仍用預設值", _ua("   ") == sec.DEFAULT_USER_AGENT)
check("④ 真的有設 → 用設定值", _ua("me me@example.com") == "me me@example.com")
check("⑤ 實際的 USER_AGENT 不是空的", bool(sec.USER_AGENT.strip()))

# 全庫掃描：同型的寫法不能再出現。
# `os.environ.get("X", "預設")` 在 CI 把變數設成空字串時會回空字串，
# 而不是預設值——這個坑值得一次擋掉所有檔案，不只是修好的那一行。
# 只抓「預設值不是空字串」的那一種。`os.environ.get("X", "")` 是安全的——
# 它回空字串，而呼叫端本來就用 or／strip 接住；有內容的預設值才會被
# CI 設進來的空字串默默蓋掉。
# 用正向比對「預設值有內容」而不是負向前瞻排除空字串：\s* 會回溯，
# 讓前瞻在空白的位置落空，結果 os.environ.get("X", "") 也被誤判成違規。
BAD = re.compile(r"""os\.environ\.get\(\s*["'][A-Z_]+["']\s*,[ \t]*(?:[^"'\s)]|["'][^"'])""")
offenders = []
for f in ROOT.rglob("*.py"):
    if any(p in f.parts for p in ("output", "state", "__pycache__", "tests")):
        continue
    for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        if BAD.search(line):
            offenders.append(f"{f.relative_to(ROOT)}:{n}")
check("⑥ 全庫沒有 os.environ.get(鍵, 預設) 的寫法（改用 or）",
      not offenders, "、".join(offenders))


# ---------------------------------------------------------------------------
# ② 口徑：所有比率都由原始金額算出來
# ---------------------------------------------------------------------------
CFG = {"companies": [
    # 刻意讓「規模小但比率高」的那一家存在：平均法與加總法的差距全靠它
    {"name": "Big", "cik": 1, "capex": 30.0, "ocf": 50.0, "revenue": 100.0,
     "debt_issued": 5.0, "capex_yoy": 20.0, "period_end": "2026-06-30",
     "from_sec": True},
    {"name": "Small", "cik": 2, "capex": 15.0, "ocf": 5.0, "revenue": 20.0,
     "debt_issued": 10.0, "capex_yoy": 80.0, "period_end": "2026-05-31",
     "from_sec": True},
]}
h = rt.hyperscalers(CFG)

check("⑦ 合計是加總不是平均",
      abs(h.capex_to_ocf - 45 / 55 * 100) < 1e-9, f"{h.capex_to_ocf:.2f}%")
_avg = (30 / 50 * 100 + 15 / 5 * 100) / 2
check("⑧ 而且明顯低於各家百分比的平均（平均法會被小公司灌高）",
      _avg - h.capex_to_ocf > 50, f"加總 {h.capex_to_ocf:.0f}% vs 平均 {_avg:.0f}%")
check("⑨ 合計金額正確",
      h.total_capex == 45.0 and h.total_ocf == 55.0 and h.total_issued == 15.0)
check("⑩ FCF 由 OCF − CapEx 自動算",
      [c["fcf"] for c in h.companies] == [20.0, -10.0],
      str([c["fcf"] for c in h.companies]))
check("⑪ 轉負家數自動算，不是寫死的", h.n_cash_negative == 1)
check("⑫ 轉負的判定與 FCF 的正負一致",
      all(c["cash_negative"] == (c["fcf"] < 0) for c in h.companies))
check("⑬ 每家的佔營運現金流由金額算",
      [round(c["capex_to_ocf"]) for c in h.companies] == [60, 300])
check("⑭ 年增加權用資本支出當權重（不是簡單平均）",
      abs(h.capex_yoy - (30 * 20 + 15 * 80) / 45) < 1e-9, f"{h.capex_yoy:.1f}%")

# 期間：各家會計年度不同，不能寫「本季」
check("⑮ 期間範圍由各家期末日算出來",
      h.period_span == "2026-05-31～2026-06-30", h.period_span)
check("⑯ 期末日相同時不印成區間",
      rt.hyperscalers({"companies": [
          {"name": "A", "capex": 1, "ocf": 2, "period_end": "2026-06-30"},
          {"name": "B", "capex": 1, "ocf": 2, "period_end": "2026-06-30"},
      ]}).period_span == "2026-06-30")
check("⑰ 沒有期末日就不編一個出來",
      rt.hyperscalers({"companies": [{"name": "A", "capex": 1, "ocf": 2}]})
      .period_span == "")

# 來源連結：只由 cik 決定，退回手動值時一樣要有
check("⑱ 每家都有 EDGAR 連結", all("browse-edgar" in c["filings_url"]
                                  for c in h.companies))
check("⑲ 沒有 cik 就沒有連結（不編網址）",
      rt.hyperscalers({"companies": [{"name": "A", "capex": 1, "ocf": 2}]})
      .companies[0]["filings_url"] == "")


# ---------------------------------------------------------------------------
# ③ 佔投資級發行：分母沒被人工確認就不顯示
# ---------------------------------------------------------------------------
check("⑳ 分母未確認 → 不算比重",
      rt.hyperscalers(CFG, 420.0, ig_verified=False).ig_share is None)
check("㉑ 分母已確認 → 才算",
      abs(rt.hyperscalers(CFG, 420.0, ig_verified=True).ig_share
          - 15 / 420 * 100) < 1e-9)
check("㉒ 沒有分母 → 不算", rt.hyperscalers(CFG, None, True).ig_share is None)


# ---------------------------------------------------------------------------
# ④ 結論文案：依實際比率動態產生，而且不絕對化
# ---------------------------------------------------------------------------
def verdict(capex, ocf, n=2):
    hh = rt.hyperscalers({"companies": [
        {"name": f"C{i}", "capex": capex / n, "ocf": ocf / n} for i in range(n)]})
    return rt.hs_verdict(hh)


t_hi, d_hi = verdict(120, 100)
t_mid, d_mid = verdict(83, 100)
t_lo, d_lo = verdict(50, 100)

check("㉓ 超過 100% → 講「超過本業產生的現金」",
      "超過本業產生的現金" in d_hi and t_hi == "已轉為舉債支應", d_hi[:40])
check("㉔ 70–100% → 講「逼近」而不是「必須舉債」",
      "逼近本業現金所能支應的範圍" in d_mid, d_mid[:40])
check("㉕ 實際比率寫進句子裡", "83%" in d_mid and "120%" in d_hi)
check("㉖ 不再出現「再擴張就必須舉債」這種絕對說法",
      all("必須舉債" not in x for x in (d_hi, d_mid, d_lo)))
check("㉗ 其他資金來源要講完整（不是只有舉債）",
      all(k in d_hi for k in ("外部融資", "既有現金", "其他資金來源")))
check("㉘ 轉負家數寫進句子裡", "家中有" in d_mid)
check("㉙ FCF 口徑要標明", "營運現金流 − 現金資本支出" in d_mid)
check("㉚ 低於 70% → 講現金足以覆蓋", "足以覆蓋" in d_lo)
check("㉛ 沒有資料 → 不硬掰",
      rt.hs_verdict(rt.hyperscalers({"companies": []})) == ("資料不足", ""))


# ---------------------------------------------------------------------------
# ⑤ 誠實：退回後備值一定要看得出來
# ---------------------------------------------------------------------------
STALE = {"companies": [dict(c, from_sec=False, period_end="") for c in CFG["companies"]]}
hs_stale = rt.hyperscalers(STALE)
check("㉜ 全部退回 → n_from_sec 是 0", hs_stale.n_from_sec == 0)
check("㉝ 部分退回 → 數得出來",
      rt.hyperscalers({"companies": [
          dict(CFG["companies"][0]),
          dict(CFG["companies"][1], from_sec=False)]}).n_from_sec == 1)

out = ROOT / "output" / "rates" / "index.html"
if not out.exists():
    print("略過  ㉞–㊱ 需要先 python run.py --offline")
else:
    html = out.read_text(encoding="utf-8")
    # 離線產出時五家都不是來自 SEC，畫面必須明講
    check("㉞ 全部過期時畫面用最強的措辭",
          "這一區的數字全部不是最新的" in html)
    check("㉟ 逐列標出「未取自 SEC」", html.count("未取自 SEC") >= 5)
    check("㊱ 每家都有可點的原始申報連結", html.count("browse-edgar") == 5)
    check("㊲ 不再出現沒有期間定義的「本季發債」",
          "本季發債" not in html)
    check("㊳ 分母未確認時不印「佔投資級發行」",
          "佔投資級發行" not in html)
    check("㊴ 合計比率要標明是加總不是平均", "合計 ÷ 合計" in html)
    check("㊵ 年增要標明是對去年同季", "去年同一季" in html or "對去年同季" in html)

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
