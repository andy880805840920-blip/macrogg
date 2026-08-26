# 整體情勢 AI 生成層：三鎖（結構／方向／數字）與後備、快取（不打網路）
import sys
import pathlib
from types import SimpleNamespace as NS

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.analysis import brief                     # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過 " if cond else "失敗 "), name, ("— " + str(detail)[:90]) if detail else "")
    ok = ok and bool(cond)


SC = NS(lean="hawkish", name="通膨主導", binding="通膨", triggers=[],
        labor_state="中", infl_state="高", labor_momentum="持平")
FLG = [NS(headline="核心服務黏性仍高"), NS(headline="月步速連四個月超標")]
CTX = {
    "scenario": {"scenario": SC},
    "labor": {"axis": {"unrate": 4.1, "u_lo": 4.0, "u_hi": 4.3,
                       "sahm": 0.25, "nfp_3m": 200.0}, "flags": FLG},
    "inflation": {"summary": NS(pce_core_yoy=2.8, core_yoy=2.5),
                  "core_pace3": 0.3, "core_pace_hot": 4, "flags": FLG},
    "fomc": {"empty": False, "shift": {"direction": "hawkish"},
             "focus": {"label": "通膨"},
             "vote": {"dissents": [{"direction": "hike"}]}, "flags": FLG},
}
ASSEMBLED = {"text": "本次更新：X。\n勞動市場：組裝甲。\n通膨：組裝乙。\n"
                     "聯準會：組裝丙。\n重點：組裝重點。",
             "chars": 40,
             "parts": [{"key": "whatsnew", "text": "本次更新：X。"},
                       {"key": "takeaway", "text": "重點：組裝重點。"}]}
ENV = {"GEMINI_API_KEY": "K"}

GOOD = ("勞動市場：失業率 4.1% 仍在充分就業區間，但已較近一年低點回升 0.25 個百分點，動能開始轉弱。\n"
        "通膨：核心 CPI 月步速已連續 4 個月高於 0.2% 的目標步速，黏性壓力未解。\n"
        "聯準會：最近一次聲明措辭轉鷹，重心放在通膨，會內已有升息主張。\n"
        "方向：利升息")


def gen(reply, tmp, calls=None):
    def post(key, model, text, system=None, temperature=None):
        if calls is not None:
            calls.append(text)
        return reply if isinstance(reply, str) else reply.pop(0)
    return brief.generate(CTX, ASSEMBLED, tmp, env=ENV, _post=post)


import tempfile
_tmp = pathlib.Path(tempfile.mkdtemp())

# ① 合格輸出 → generated，首尾兩句仍是規則版
r = gen(GOOD, _tmp / "a.json")
check("① 合格 → generated", r["source"] == "generated", r["source"])
check("①b 首尾規則句原樣保留",
      r["text"].startswith("本次更新：X。") and r["text"].rstrip().endswith("重點：組裝重點。"))
check("①c 三則 bullet 都在", all(k in r["text"]
      for k in ("勞動市場：", "通膨：", "聯準會：")))

# ② 快取：判定沒變 → 沿用、不再呼叫
calls = []
r2 = gen("不該被呼叫", _tmp / "a.json", calls)
check("② 判定沒變沿用快取", r2["source"] == "model-cache" and not calls)

# ③ 結構鎖：缺一行 → 帶原因重試一次，仍錯退組裝
calls = []
BAD = "勞動市場：只有一行。\n方向：利升息"
r3 = gen([BAD, BAD], _tmp / "b.json", calls)
check("③ 結構不合退組裝、重試一次", r3["source"] == "assembled"
      and len(calls) == 2 and "被退回" in calls[1], len(calls))

# ④ 方向鎖：模型自行改判 → 作廢
FLIP = GOOD.replace("方向：利升息", "方向：利降息")
r4 = gen([FLIP, FLIP], _tmp / "c.json")
check("④ 方向與規則判定不符 → 退組裝", r4["source"] == "assembled")

# ⑤ 數字鎖：編出判定包沒有的數字 → 作廢
NUM = GOOD.replace("4.1%", "3.7%")
r5 = gen([NUM, NUM], _tmp / "d.json")
check("⑤ 新編數字 → 退組裝", r5["source"] == "assembled")

# ⑥ 呼叫爆掉 → 退組裝不中斷
def boom(*a, **k):
    raise RuntimeError("429")


r6 = brief.generate(CTX, ASSEMBLED, _tmp / "e.json", env=ENV, _post=boom)
check("⑥ API 掛掉退組裝", r6["source"] == "assembled")

# ⑦ 離線／沒金鑰 → 直接組裝
check("⑦ 離線直接組裝",
      brief.generate(CTX, ASSEMBLED, _tmp / "f.json", offline=True,
                     env=ENV)["source"] == "assembled")
check("⑦b 沒金鑰直接組裝",
      brief.generate(CTX, ASSEMBLED, _tmp / "g.json",
                     env={})["source"] == "assembled")

# ⑧ 判定包：方向與關鍵事實都在
pk = brief.judgment_pack(CTX)
check("⑧ 判定包含政策傾向與三模組", pk["lean"] == "利升息"
      and all(k in pk["text"] for k in ("【勞動市場】", "【通膨】", "【聯準會】")))

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
