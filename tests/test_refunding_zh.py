"""2026-10-22：每季再融資聲明的中文摘要（src/analysis/refunding_zh.py）。"""
import sys, pathlib, tempfile
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.analysis import refunding_zh as rz        # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過  " if cond else "失敗  ") + name + (f" — {detail}" if detail and not cond else ""))
    ok &= bool(cond)


TEXT = ("Quarterly Refunding Statement of Assistant Secretary for Financial Markets November 4, 2026 "
        "WASHINGTON - Treasury is offering $125 billion of Treasury securities to refund approximately "
        "$99.5 billion of privately-held Treasury notes maturing on November 15, 2026. "
        "Based on current projected borrowing needs, Treasury anticipates maintaining nominal coupon and FRN "
        "auction sizes for at least the next several quarters. Treasury intends to increase bill auction sizes "
        "in December to meet seasonal financing needs. Treasury plans to purchase up to $38 billion "
        "for liquidity support and up to $25 billion for cash management purposes in the 1-month to 2-year bucket.")
ST = {"date": "2026-11-04", "url": "https://home.treasury.gov/news/press-releases/sb9999", "text": TEXT}
GOOD = ("財政部表示，依目前的借款需求，預期至少未來數季維持名目 coupon 與 FRN 的拍賣規模不變；"
        "本次再融資發行 1,250 億美元的公債，用來償還約 995 億美元 11 月 15 日到期的私人持有債券；"
        "12 月將配合季節性資金需求提高 T-Bills 的拍賣規模。")
ENV = {"ANTHROPIC_API_KEY": "test"}
tmp = pathlib.Path(tempfile.mkdtemp())

# ① 數字鎖定：十億→億的 ×10 換算、日期小整數都算原文有
check("① 合格摘要通過檢查", rz.validate(GOOD, TEXT) == "", rz.validate(GOOD, TEXT))
check("② 編造的數字被擋", "原文找不到" in rz.validate(GOOD.replace("1,250", "1,500"), TEXT))
check("③ 太短被擋", "長度" in rz.validate("維持不變。", TEXT))
check("④ 條列被擋", rz.validate("- " + GOOD, TEXT) != "")

# ② 第一次呼叫模型並存檔；第二次直接用快取（不再呼叫）
calls = []


def post(key, model, text):
    calls.append(model)
    return GOOD


c = tmp / "rz.json"
z1 = rz.summarize(ST, cache_path=c, post=post, env=ENV)
z2 = rz.summarize(ST, cache_path=c, post=post, env=ENV)
check("⑤ 產生摘要並存檔", z1 == GOOD and c.exists(), z1)
check("⑥ 同一份聲明不重複呼叫", z2 == GOOD and len(calls) == 1, calls)
check("⑦ 預設模型 sonnet、可用 REFUNDING_MODEL 覆寫",
      calls[0] == rz.MODEL and
      rz.summarize(dict(ST, date="2027-02-03"), cache_path=tmp / "m.json", post=post,
                   env=dict(ENV, REFUNDING_MODEL="x-model")) == GOOD and calls[-1] == "x-model")

# ③ 新一季（網址或日期變了）→ 重新產生
calls.clear()
rz.summarize(dict(ST, url=ST["url"] + "x"), cache_path=c, post=post, env=ENV)
check("⑧ 新聲明重新產生", len(calls) == 1)

# ④ 驗證沒過 → 重試，三次都沒過回 ""
calls.clear()
bad = rz.summarize(ST, cache_path=tmp / "bad.json", post=lambda *a: (calls.append(1), "財政部將發行 9,999 億美元。" * 4)[1], env=ENV)
check("⑨ 三次都不合格 → 回空字串（頁面沿用原文）", bad == "" and len(calls) == rz.TRIES and not (tmp / "bad.json").exists())
# 第一次不合格、第二次合格
seq = iter(["太短", GOOD])
check("⑩ 重試後合格就採用", rz.summarize(ST, cache_path=tmp / "r.json", post=lambda *a: next(seq), env=ENV) == GOOD)


def boom(*a):
    raise RuntimeError("API 掛了")


check("⑪ API 失敗 → 回空字串", rz.summarize(ST, cache_path=tmp / "e.json", post=boom, env=ENV) == "")
check("⑫ 沒設金鑰 → 回空字串", rz.summarize(ST, cache_path=tmp / "k.json", env={}) == "")
check("⑬ 離線模式不呼叫", rz.summarize(ST, offline=True, cache_path=tmp / "o.json", post=boom, env=ENV) == "")
check("⑭ 離線模式仍可讀上次存的", rz.summarize(dict(ST, url=ST["url"] + "x"), offline=True, cache_path=c,
                                       post=boom, env=ENV) == GOOD)
check("⑮ 沒有本文（舊版抓取結果）→ 回空字串", rz.summarize({"date": "2026-11-04", "url": "u"}, cache_path=tmp / "t.json",
                                              post=post, env=ENV) == "")

# ⑤ build.py 串接：新聲明＋摘要成功 → guidance_zh 用 AI 版並標記；失敗 → 沿用句型版
from src import build                               # noqa: E402
src_txt = (ROOT / "src" / "build.py").read_text(encoding="utf-8")
check("⑯ build.py 有串 refunding_zh 並標記 zh_ai", "refunding_zh.summarize(_st, offline)" in src_txt and '"zh_ai"' in src_txt)
from src.pages import longend as lp                  # noqa: E402
h1 = lp.supply({"le": {"refunding": {"date": "2026-11-04", "guidance_en": "x", "guidance_zh": GOOD, "zh_ai": True, "auto": True}}})
h2 = lp.supply({"le": {"refunding": {"date": "2026-11-04", "guidance_en": "x", "auto": True}}})
check("⑰ 頁面：AI 摘要附「以原文為準」", GOOD in h1 and "AI 摘要" in h1)
check("⑱ 頁面：沒有摘要 → 顯示請看原文", "請以上方原文為準" in h2 and "AI 摘要" not in h2)

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
