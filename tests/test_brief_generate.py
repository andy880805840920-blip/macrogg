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
        labor_state="中", infl_state="高", labor_momentum="轉弱")
# 判定包現在以訊號為主體：數字活在訊號 headline 裡（跟正式管線一致——
# 規則引擎的 u3_rising／pace_above 訊號就長這樣）
FLG_LAB = [NS(headline="失業率已較近一年低點回升 0.25 個百分點")]
FLG_INF = [NS(headline="核心 CPI 月步速已連續 4 個月高於 0.2% 的目標步速")]
FLG = [NS(headline="核心服務黏性仍高")]
CTX = {
    "scenario": {"scenario": SC},
    "labor": {"axis": {"unrate": 4.1, "u_lo": 4.0, "u_hi": 4.3,
                       "sahm": 0.25, "nfp_3m": 200.0}, "flags": FLG_LAB},
    "inflation": {"summary": NS(pce_core_yoy=2.8, core_yoy=2.5),
                  "core_pace3": 0.3, "core_pace_hot": 4, "flags": FLG_INF},
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

# ⑨ 數字鎖檔位二：等值寫法放行、小整數放行、比率仍硬鎖、理由列數字
_b, _w = brief._gen_digit_issues("核心 CPI 月步速 0.20%、失業率 4.1%",
                                 "月步速 0.2%；失業率 4.1%")
check("⑨ 等值寫法（0.20 vs 0.2）放行", _b == [] and _w == [], (_b, _w))
_b, _w = brief._gen_digit_issues("委員會 3 票、21 天後開會",
                                 "反對票與會期")
check("⑨b 小整數（計數／日期）放行但記錄",
      _b == [] and set(_w) == {"3", "21"}, (_b, _w))
_b, _w = brief._gen_digit_issues("失業率 4.3%、機率 42%",
                                 "失業率 4.1%")
check("⑨c 包外的比率仍硬鎖（含整數％）",
      set(_b) == {"4.3%", "42%"}, _b)

# ⑨d 走完整 generate：0.20 的寫法不再整篇作廢
GOOD20 = GOOD.replace("0.2%", "0.20%")
r9 = gen(GOOD20, _tmp / "t2.json")
check("⑨d 生成層：等值寫法通過三鎖 → generated",
      r9["source"] == "generated", r9["source"])
# ⑨e 真正的新比率仍退組裝，且理由帶具體數字
calls9 = []
BAD9 = GOOD.replace("4.1%", "5.5%")
r9e = gen([BAD9, BAD9], _tmp / "t3.json", calls9)
check("⑨e 新比率退組裝、重試提示帶具體數字",
      r9e["source"] == "assembled" and "5.5" in calls9[1], 
      calls9[1][-60:] if len(calls9) > 1 else calls9)

# ⑩ 判定包：數字最多兩位小數＋以訊號為主體
from types import SimpleNamespace as _NS10
_CTX10 = {
    "scenario": {"scenario": SC},
    "labor": {"axis": {"unrate": 4.1333333, "u_lo": 4.0, "u_hi": 4.3,
                       "sahm": 0.2533333, "nfp_3m": 200.0},
              "flags": FLG_LAB},
    "inflation": {"summary": _NS10(pce_core_yoy=3.0483870967,
                                   core_yoy=2.4838709677),
                  "core_pace3": 0.2833333333, "core_pace_hot": 4,
                  "flags": [_NS10(headline="月步速近三月平均 0.28%")]},
    "fomc": {"empty": False, "shift": {"direction": "hawkish"},
             "focus": {"label": "通膨"}, "vote": {"dissents": []},
             "flags": []},
}
_pk10 = brief.judgment_pack(_CTX10)["text"]
check("⑩ 軸數字收斂到兩位（失業率 4.13%、核心 PCE 3.05%）",
      "4.13%" in _pk10 and "3.05%" in _pk10, _pk10[:120])
check("⑩b 全精度尾巴不出現在包裡",
      "3.0483" not in _pk10 and "4.1333" not in _pk10)
check("⑩c _n2 尾端零去掉（4.0→4、3.10→3.1）",
      brief._n2(4.0) == "4" and brief._n2(3.10) == "3.1"
      and brief._n2(None) == "—")
check("⑩e 訊號 headline 是包的主體（關鍵訊號段在、具體數字由它承載）",
      "關鍵訊號：失業率已較近一年低點回升 0.25 個百分點" in _pk10
      and "月步速近三月平均 0.28%" in _pk10, _pk10)
check("⑩f 軸行不再帶括號數字（同一件事不進包兩次）",
      "回升 0.25 個百分點）" not in _pk10.split("關鍵訊號")[0])
# 照抄訊號裡的數字 → 通過數字鎖
_b10, _ = brief._gen_digit_issues("核心 PCE 年增 3.05%、月步速 0.28%",
                                  _pk10)
check("⑩d 照抄訊號數字通過數字鎖", _b10 == [], _b10)

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
