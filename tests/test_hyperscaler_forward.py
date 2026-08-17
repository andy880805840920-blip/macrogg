"""
科技巨頭「前瞻」兩區的測試：資本支出指引與財報新聞稿的時效。

為什麼需要這個檔案
------------------
這兩區補的是同一個缺口——下方那張表講的是**已經花掉的上一季**，
而這一頁的論點（AI 資本支出推高長端供給）講的是**接下來要花多少**。
兩區都有各自安靜的壞法：

  ① **指引合計把沒給指引的公司算成零。** Oracle 沒有年度指引，
     如果它被當成 0 併進合計，畫面上的「五家合計」就少了一家的量體，
     而數字本身看起來完全正常。合計必須只由**有指引的家數**構成，
     而且沒給的那幾家要單獨講出來。

  ② **ahead 判錯。** 這是財報新聞稿區唯一的判斷。判成 True 卻其實同季，
     畫面會宣稱「下方表格已過期」而其實沒有；判成 False 則整區消失，
     讀者看不出表格落後了一季。

  ③ **算得出來但畫面看不到。** 這是這個專案犯過一次的錯：情境推導的
     程式早就寫好了，但它被塞在畫面最下面的灰色小字裡，等於不存在。
     所以這裡不只驗資料結構——**同時驗產出的 HTML 裡真的有那句結論**。

    python tests/test_hyperscaler_forward.py
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from src.build import _guidance_block, _earnings_block, GUIDANCE_NOTE_X  # noqa: E402

ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    print(f"{'通過' if cond else '失敗'}  {name}" + (f" — {detail}" if detail else ""))
    ok &= bool(cond)


class HS:                       # 假的 Hyperscalers
    def __init__(self, total_capex=125.0):
        self.total_capex = total_capex


CFG = {
    "enabled": True, "year": 2026, "as_of": "2026-04-29",
    "source": "各公司法說會",
    "companies": [
        {"name": "Microsoft", "low": 190.0, "high": 190.0, "note": "含零組件漲價"},
        {"name": "Alphabet", "low": 175.0, "high": 185.0},
        {"name": "Amazon", "low": 200.0, "high": 200.0},
        {"name": "Meta", "low": 125.0, "high": 145.0},
        {"name": "Oracle", "low": 0.0, "high": 0.0, "note": "未提供年度指引"},
    ],
}


# ---------------------------------------------------------------------------
# ① 資本支出指引
# ---------------------------------------------------------------------------
g = _guidance_block(CFG, HS())
check("① 沒給指引的公司不進合計", g["n"] == 4, f'{g["n"]} 家')
check("② 沒給指引的公司要講出來", g["missing"] == "Oracle", g["missing"])
# 690 = 190+175+200+125，720 = 190+185+200+145
check("③ 合計是區間的兩端各自相加",
      g["total_display"] == "6,900–7,200 億美元", g["total_display"])
check("④ 單一數字不印成區間",
      any(r["value"] == "2,000 億美元" for r in g["rows"]),
      str([r["value"] for r in g["rows"]]))
check("⑤ 依規模由大到小",
      [r["name"] for r in g["rows"]] == ["Amazon", "Microsoft", "Alphabet", "Meta"],
      str([r["name"] for r in g["rows"]]))
check("⑥ 備註帶得出來",
      any("零組件" in r["note"] for r in g["rows"]))
# 年化實績 125×4=500（十億）→ 5,000 億；指引中值 705 十億 → 1.4 倍
check("⑦ 對照年化實績", g["ratio_display"] == "1.4 倍"
      and g["run_rate_display"] == "5,000 億美元",
      f'{g["ratio_display"]} / {g["run_rate_display"]}')
check("⑧ 拉開才算值得強調", g["notable"] is True)
check("⑨ 更新日與來源要標", g["as_of"] == "2026-04-29" and g["source"])

# 關掉、沒填、全部是零 —— 三種情況都要整區消失，不能印一個 0
for name, cfg in [
        ("⑩ enabled: false → 整區不顯示", {**CFG, "enabled": False}),
        ("⑪ 沒有 companies → 整區不顯示", {"enabled": True, "companies": []}),
        ("⑫ 全部是零 → 整區不顯示",
         {**CFG, "companies": [{"name": "X", "low": 0, "high": 0}]}),
        ("⑬ 整段沒填 → 整區不顯示", {})]:
    check(name, _guidance_block(cfg, HS())["available"] is False)

# 抓不到實績時仍要顯示指引——指引本身就是這一區的主角，
# 沒有對照組只是少一句話，不是少一區
g0 = _guidance_block(CFG, HS(total_capex=0))
check("⑭ 沒有實績仍顯示指引",
      g0["available"] and g0["ratio_display"] == "" and not g0["notable"])

check("⑮ 強調門檻不會低到「成長就算數」", GUIDANCE_NOTE_X > 1.0)


# ---------------------------------------------------------------------------
# ② 財報新聞稿
# ---------------------------------------------------------------------------
EARN = [
    {"name": "Microsoft", "date": "2026-07-22", "period_end": "2026-03-31",
     "lag": 112, "ahead": True, "doc_url": "https://x/1"},
    {"name": "Amazon", "date": "2026-07-17", "period_end": "2026-06-30",
     "lag": 17, "ahead": False, "doc_url": "https://x/2"},
]
e = _earnings_block(EARN)
check("⑯ 有資料就顯示", e["available"] and e["count"] == 2)
check("⑰ 只點名領先的那幾家",
      e["ahead_n"] == 1 and e["ahead_names"] == "Microsoft", e["ahead_names"])
check("⑱ 同季的講落後天數、領先的不講",
      [r["lag_display"] for r in e["rows"]] == ["", "季末後 17 天"],
      str([r["lag_display"] for r in e["rows"]]))
check("⑲ 沒有資料 → 整區不顯示", _earnings_block([])["available"] is False)
check("⑳ 全部同季時仍算可用（畫面自己決定要不要出現）",
      _earnings_block([EARN[1]])["ahead_n"] == 0)

# 這一區絕不能帶出任何財務數字——新聞稿是非結構化文字，
# 硬解會拿到不知道是什麼口徑的數字。欄位裡只有日期、名稱、連結。
_allowed = {"name", "date", "period_end", "ahead", "lag_display", "url"}
check("㉑ 明細欄位只有日期與連結，沒有金額",
      all(set(r) == _allowed for r in e["rows"]), str(set(e["rows"][0])))


# ---------------------------------------------------------------------------
# ③ 算得出來還不夠——畫面上要看得到
# ---------------------------------------------------------------------------
out = pathlib.Path(__file__).parent.parent / "output" / "rates" / "index.html"
if not out.exists():
    print("略過  ㉒–㉕ 需要先 python run.py --offline")
else:
    h = out.read_text(encoding="utf-8")
    check("㉒ 指引區塊在畫面上", "資本支出計畫" in h and "億美元" in h)
    check("㉓ 沒給指引的公司在畫面上被交代", "未提供年度指引，不在合計內" in h)
    check("㉔ 財報新聞稿的落差在畫面上", "已公布新一季財報" in h
          and "表格待 10-Q" in h)
    check("㉕ 「不解析新聞稿數字」的理由有寫出來",
          "不解析新聞稿裡的數字" in h)
    # 位置：指引要排在下方季報明細之前，否則主詞跟論點對不上
    check("㉖ 指引排在季報明細前面",
          h.find("資本支出計畫") < h.find("五家公司的明細"),
          f'{h.find("資本支出計畫")} vs {h.find("五家公司的明細")}')

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
