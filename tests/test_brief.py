"""
首頁整體總述的組裝測試。

為什麼需要這個檔案
------------------
這一段是首頁上唯一要「讀」而不是「掃」的東西，而它有三個容易壞的地方：

  ① **長度失控。** 目標 150 字上下。一旦某個分支寫得囉唆，整段就從
     「20 秒看完」變成「懶得看」——而那正好毀掉它存在的理由。
     量的是**中文字數**不是 len()：數字、百分號、PCE／GDP／AI 這些
     拉丁字母會把 len() 灌水（同一段話 len 是 232、中文字只有 149）。

  ② **缺資料時硬湊。** 某個模組沒有資料時那一段要直接消失，
     不能印「資料不足」佔字數，更不能讓整段變成空字串。

  ③ **敘述與格位打架。** 就業那一段的分支順序必須跟
     scenario.classify_labor 一致，否則會出現「總述說失業率仍算充分就業、
     九宮格說就業弱」而沒有任何解釋的情況。

    python tests/test_brief.py
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from src.analysis import brief                      # noqa: E402
from src.analysis import scenario as scn            # noqa: E402

ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    print(f"{'通過' if cond else '失敗'}  {name}" + (f" — {detail}" if detail else ""))
    ok &= bool(cond)


class T:                       # 假的 Trigger
    def __init__(self, label, distance, met=False, binding=True):
        self.label, self.distance = label, distance
        self.met, self.binding = met, binding


class S:                       # 假的 Scenario
    def __init__(self, regime="inflation", labor="弱", infl="高",
                 lean="hawkish", triggers=None):
        self.regime, self.labor_state, self.infl_state = regime, labor, infl
        self.lean = lean
        self.triggers = (triggers if triggers is not None
                         else [T("通膨轉「低」", "還差 1.02 個百分點")])


class Summ:                    # 假的 InflationSummary
    def __init__(self, yoy=3.0, m3=3.6, streak=-64):
        self.pce_core_yoy, self.pce_core_3m = yoy, m3
        self.supercore_streak = streak


AX = {"unrate": 4.1, "u_lo": 4.0, "u_hi": 4.3, "sahm": 0.13,
      "sahm_triggered": False, "nfp_3m": 20.0, "breakeven": 43.0,
      "below_breakeven": True}

FOM = {"latest_date": "2026-07-29", "obj_parts": {"action_label": "維持不變"},
       "vote": {"dissents": [{"direction": "hike"}] * 3},
       "next_meeting": {"days": 35}, "shift": {"direction": "hawkish"}}


class P:
    level = "high"


class HS:
    capex_to_ocf = 83.0


class DB:
    pb_gap = -1.28


RT = {"pressure": P(), "hyperscalers": HS(), "debt": DB()}


def ctxs(**over):
    base = {
        "scenario": {"scenario": S()},
        "labor": {"axis": AX, "tilt": {"tilt": "dovish"}},
        "inflation": {"summary": Summ(), "bands": {"high": 2.5, "low": 2.25},
                      "tilt": {"tilt": "hawkish"}},
        "fomc": FOM,
        "rates": RT,
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# ① 完整的一段
# ---------------------------------------------------------------------------
b = brief.compose(ctxs())
print("　　", b["text"])
print()
check("① 六段都在（含重點句）", len(b["parts"]) == 6,
      str([p["key"] for p in b["parts"]]))
check("② 長度在護欄內（中文字）",
      brief.MIN_CJK <= b["chars"] <= brief.MAX_CJK,
      f'{b["chars"]} 字，護欄 {brief.MIN_CJK}–{brief.MAX_CJK}')
check("③ 量的是中文字不是字串長度", b["chars"] < b["raw_len"],
      f'中文 {b["chars"]} / 長度 {b["raw_len"]}')
check("④ 沒有殘留的模板記號",
      "{" not in b["text"] and "None" not in b["text"] and "**" not in b["text"])
check("⑤ 五件事都提到了",
      all(k in b["text"] for k in ("失業率", "核心 PCE", "會議", "長端")),
      b["text"][:60])
check("⑤b 結尾是重點句", b["text"].rstrip().endswith("。")
      and b["parts"][-1]["key"] == "takeaway"
      and b["parts"][-1]["text"].startswith("重點："),
      b["parts"][-1]["text"])


# ---------------------------------------------------------------------------
# ② 缺資料：那一段消失，其餘照樣成立
# ---------------------------------------------------------------------------
for name, key in [("⑥ 沒有就業資料", "labor"), ("⑦ 沒有通膨資料", "inflation"),
                  ("⑧ 沒有聯準會資料", "fomc"), ("⑨ 沒有長端資料", "rates")]:
    c = ctxs(); c[key] = None
    r = brief.compose(c)
    check(name, len(r["parts"]) == 5 and r["text"] and "資料不足" not in r["text"],
          f'{len(r["parts"])} 段')

check("⑩ 完全沒有資料 → 空字串，不硬湊",
      brief.compose({})["text"] == "")
check("⑪ 只有情境 → 開場句與重點句",
      [p["key"] for p in brief.compose({"scenario": {"scenario": S()}})["parts"]]
      == ["direction", "takeaway"])


# ---------------------------------------------------------------------------
# ③ 就業分支要跟九宮格的判定一致
# ---------------------------------------------------------------------------
def lab_text(ax):
    r = brief.compose(ctxs(labor={"axis": ax, "tilt": {}}))
    return next(p["text"] for p in r["parts"] if p["key"] == "labor")


cases = [
    ("⑫ 高於上緣 → 講「高於充分就業上緣」",
     {**AX, "unrate": 4.6, "below_breakeven": False}, "高於"),
    ("⑬ Sahm 觸發 → 講快速轉弱", {**AX, "sahm_triggered": True}, "Sahm"),
    ("⑭ 低於損益兩平 → 講撐不住", AX, "撐不住"),
    ("⑮ 都正常 → 講落在區間內",
     {**AX, "below_breakeven": False}, "落在"),
    ("⑯ 低於下緣 → 講仍緊",
     {**AX, "unrate": 3.7, "below_breakeven": False}, "仍緊"),
]
for name, ax, want in cases:
    txt = lab_text(ax)
    check(name, want in txt, txt)

# 敘述與格位不能互相打架：同一份資料餵給兩邊，結論要對得上
for ax, want_state in [(AX, "弱"),
                       ({**AX, "unrate": 4.6, "below_breakeven": False}, "弱"),
                       ({**AX, "below_breakeven": False}, "中"),
                       ({**AX, "unrate": 3.7, "below_breakeven": False}, "強")]:
    st, _ = scn.classify_labor(None, None, ax)
    check(f"⑰ 格位 {want_state} 時敘述不矛盾", st == want_state,
          f"格位 {st}、敘述「{lab_text(ax)[:24]}」")


# ---------------------------------------------------------------------------
# ④ 通膨與方向的分支
# ---------------------------------------------------------------------------
def inf_text(summ, state):
    c = ctxs(scenario={"scenario": S(infl=state)},
             inflation={"summary": summ, "bands": {"high": 2.5, "low": 2.25},
                        "tilt": {}})
    return next(p["text"] for p in brief.compose(c)["parts"]
                if p["key"] == "inflation")


check("⑱ 動能加速講加速", "加速" in inf_text(Summ(3.0, 3.6), "高"))
check("⑲ 動能放緩講放緩", "放緩" in inf_text(Summ(3.0, 2.4), "高"))
check("⑳ 動能持平講持平", "持平" in inf_text(Summ(3.0, 3.0), "高"))
check("㉑ 回到目標時不講「仍高於」",
      "仍高於" not in inf_text(Summ(2.0, 2.0, 0), "低"))
# 比對的是黏性那一句的特徵字串。先前用「個月」，但動能那一句改成
# 「三個月年化」之後也含「個月」——太寬的比對會誤判。
check("㉒ 沒有黏性資料就不提黏性",
      "個月高於目標" not in inf_text(Summ(3.0, 3.6, 0), "高"),
      inf_text(Summ(3.0, 3.6, 0), "高"))

# 共識度：三方一致 vs 分歧，用詞要不同
def dir_text(l, i, f):
    c = ctxs(labor={"axis": AX, "tilt": {"tilt": l}},
             inflation={"summary": Summ(), "bands": {}, "tilt": {"tilt": i}},
             fomc={**FOM, "shift": {"direction": f}})
    return brief.compose(c)["parts"][0]["text"]


def fomc_text(f):
    return next(p["text"] for p in brief.compose(ctxs(fomc=f))["parts"]
                if p["key"] == "fomc")


check("㉓ 三方一致", "一致" in dir_text("hawkish", "hawkish", "hawkish"))
check("㉔ 方向分歧", "分歧" in dir_text("dovish", "hawkish", "hawkish"))
check("㉕ 有中性的那一方要交代",
      "中性" in dir_text("balanced", "hawkish", "hawkish"),
      dir_text("balanced", "hawkish", "hawkish"))
check("㉖ 用中文數字（「兩方」不是「2 方」）",
      "兩方" in dir_text("dovish", "hawkish", "hawkish"))

# 反對票的方向欄位是 hike／cut，不是 hawkish／dovish——寫錯會變成「3 票反對」
f_cut = {**FOM, "vote": {"dissents": [{"direction": "cut"}] * 2}}
check("㉗ 反對票方向讀得對", "2 票主張降息" in fomc_text(f_cut),
      fomc_text(f_cut))
f_none = {**FOM, "vote": {"dissents": []}}
check("㉘ 沒有反對票 → 全票通過", "全票通過" in fomc_text(f_none))


# ---------------------------------------------------------------------------
# ⑤ 重點句：升降息的可能性與解鎖條件
# ---------------------------------------------------------------------------
def take(sc, fom=FOM):
    return brief._takeaway(sc, fom)


check("㉙ 偏鷹 → 降息還遠＋解鎖條件",
      all(k in take(S()) for k in ("降息還遠", "通膨轉「低」", "1.02")),
      take(S()))
check("㉚ 偏鷹＋升息反對票 → 提升息風險",
      "升息風險未消" in take(S()), take(S()))
check("㉛ 偏鷹但無反對票 → 不硬掰升息風險",
      "升息風險" not in take(S(), {**FOM, "vote": {"dissents": []}}))
check("㉜ 偏鴿 → 下一步以降息為主",
      "下一步以降息為主" in take(S(lean="dovish")))
check("㉝ 中性 → 按兵不動",
      "按兵不動" in take(S(lean="neutral")))
check("㉞ 條件已達成要講出來",
      "已經達成" in take(S(triggers=[T("通膨轉「低」", "", met=True)])),
      take(S(triggers=[T("通膨轉「低」", "", met=True)])))
check("㉟ 沒有觸發條件句子照樣成立",
      take(S(triggers=[])).startswith("重點：降息還遠"),
      take(S(triggers=[])))

# 轉折詞：弱 × 高才加「另一頭」，同向不加
c1 = brief.compose(ctxs())
inf1 = next(p["text"] for p in c1["parts"] if p["key"] == "inflation")
check("㊱ 弱×高 → 通膨段帶「另一頭」", inf1.startswith("另一頭"), inf1[:14])
c2 = brief.compose(ctxs(scenario={"scenario": S(labor="強", infl="高",
                                                lean="hawkish")}))
inf2 = next(p["text"] for p in c2["parts"] if p["key"] == "inflation")
check("㊲ 同向時不加轉折詞", not inf2.startswith("另一頭"), inf2[:14])


# ---------------------------------------------------------------------------
# ⑥ 時序：資料期別與「三月」的歧義
#
# 兩個真實的問題：
#   ① 「三月均非農」「三月年化」在中文裡會被讀成 March。原意是
#      「近三個月平均」「三個月年化」——手上是 7 月數據，讀成 March
#      等於差了四個月。
#   ② 總述完全沒提資料期別。7 月的就業報告是 8 月才公布的，不標的話
#      讀者（以及潤稿模型加上去的「目前」）都會把它當成即時數據。
# ---------------------------------------------------------------------------
class F:                       # 假的 Flag
    def __init__(self, key, headline, severity="alert"):
        self.key, self.headline, self.severity = key, headline, severity


def ctx_with(month="2026-07", lab_flags=(), inf_flags=()):
    c = ctxs()
    c["labor"] = {"axis": AX, "tilt": {}, "data_month": month,
                  "flags": list(lab_flags)}
    c["inflation"] = {"summary": Summ(), "bands": {"high": 2.5, "low": 2.25},
                      "tilt": {}, "data_month": month, "flags": list(inf_flags)}
    return c


b = brief.compose(ctx_with())
check("㊳ 不再出現會被讀成 March 的「三月均」",
      "三月均" not in b["text"] and "三月年化" not in b["text"], b["text"][:80])
check("㊴ 改成沒有歧義的說法",
      "近三個月平均非農" in b["text"] and "三個月年化" in b["text"])
check("㊵ 就業標出資料期別", "7 月失業率" in b["text"], b["text"][30:60])
check("㊶ 通膨也標出資料期別", "7 月核心 PCE" in b["text"])
check("㊷ 會議日期跟資料期別分得開",
      "上次會議（7/29）" in b["text"], b["text"][-120:-60])

# 期別缺失時不要編一個出來
b2 = brief.compose(ctx_with(month=""))
check("㊸ 沒有期別就不標（不編一個月份）",
      "失業率" in b2["text"] and "月失業率" not in b2["text"])
check("㊹ 壞掉的期別字串不會爆",
      brief._month("2026") == "" and brief._month("") == ""
      and brief._month("bad-xx") == "")
check("㊺ 正常的期別轉得對", brief._month("2026-07") == "7 月"
      and brief._month("2026-12") == "12 月")


# ---------------------------------------------------------------------------
# ⑦ 訊號：每一期挑的不一樣，所以要動態挑不能寫死
# ---------------------------------------------------------------------------
b3 = brief.compose(ctx_with(
    lab_flags=[F("revision_swamps", "前兩月大幅下修，實質動能弱於初值")],
    inf_flags=[F("expect_unanchored", "長期通膨預期偏離目標")]))
check("㊻ 就業訊號併進總述", "前兩月大幅下修" in b3["text"])
check("㊼ 通膨訊號併進總述", "長期通膨預期偏離目標" in b3["text"])

# 換一期 → 換一條訊號，程式不必改
b4 = brief.compose(ctx_with(
    lab_flags=[F("bad_decline", "失業率下降源於勞動力退出，而非就業增加")]))
check("㊽ 換一期就換一條（不是寫死的）",
      "勞動力退出" in b4["text"] and "前兩月大幅下修" not in b4["text"])

# 已經講過的事不要再挑一次
b5 = brief.compose(ctx_with(
    inf_flags=[F("supercore_hot", "核心服務除住房仍高於目標區間"),
               F("expect_unanchored", "長期通膨預期偏離目標")]))
check("㊾ 跳過手寫句子已經講過的訊號",
      "長期通膨預期偏離目標" in b5["text"]
      and "仍高於目標區間" not in b5["text"], b5["text"][-160:-80])
check("㊿ 依嚴重度取第一條（flags 進來就排好了）",
      brief._pick_signal([F("narrow_growth", "甲"), F("bad_decline", "乙")])
      == "甲")
check("51 全部都被講過 → 不硬加",
      brief._pick_signal([F("above_target", "甲"), F("cpi_cooling", "乙")]) == "")
check("52 沒有訊號 → 不硬加",
      brief._pick_signal([]) == "" and brief._pick_signal(None) == "")
check("53 headline 是空的就跳過",
      brief._pick_signal([F("x", "  "), F("y", "乙")]) == "乙")

# 加了期別與訊號之後仍在護欄內
check("54 長度仍在護欄內",
      brief.MIN_CJK <= b3["chars"] <= brief.MAX_CJK, f'{b3["chars"]} 字')

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
