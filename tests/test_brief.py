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


AX = {"unrate": 4.1, "u_lo": 4.0, "u_hi": 4.3, "sahm": 0.25,
      "sahm_triggered": False, "nfp_3m": 20.0, "u3_rising": True}

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
check("① 四段都在（三 bullet ＋重點句；長端與共識句已移除）",
      [p["key"] for p in b["parts"]]
      == ["labor", "inflation", "fomc", "takeaway"],
      str([p["key"] for p in b["parts"]]))
check("② 長度在護欄內（中文字）",
      brief.MIN_CJK <= b["chars"] <= brief.MAX_CJK,
      f'{b["chars"]} 字，護欄 {brief.MIN_CJK}–{brief.MAX_CJK}')
check("③ 量的是中文字不是字串長度", b["chars"] < b["raw_len"],
      f'中文 {b["chars"]} / 長度 {b["raw_len"]}')
check("④ 沒有殘留的模板記號",
      "{" not in b["text"] and "None" not in b["text"] and "**" not in b["text"])
check("⑤ 三大部分都提到了（bullet 前綴齊）",
      all(k in b["text"] for k in ("勞動市場：", "通膨：", "聯準會：")),
      b["text"][:60])
check("⑤b 結尾是重點句", b["text"].rstrip().endswith("。")
      and b["parts"][-1]["key"] == "takeaway"
      and b["parts"][-1]["text"].startswith("重點："),
      b["parts"][-1]["text"])


# ---------------------------------------------------------------------------
# ② 缺資料：那一段消失，其餘照樣成立
# ---------------------------------------------------------------------------
for name, key, want in [("⑥ 沒有就業資料", "labor", 3),
                        ("⑦ 沒有通膨資料", "inflation", 3),
                        ("⑧ 沒有聯準會資料", "fomc", 3),
                        ("⑨ 長端資料與總述無關（已移除）", "rates", 4)]:
    c = ctxs(); c[key] = None
    r = brief.compose(c)
    check(name, len(r["parts"]) == want and r["text"]
          and "資料不足" not in r["text"], f'{len(r["parts"])} 段')

check("⑩ 完全沒有資料 → 空字串，不硬湊",
      brief.compose({})["text"] == "")
check("⑪ 只有情境 → 只剩重點句",
      [p["key"] for p in brief.compose({"scenario": {"scenario": S()}})["parts"]]
      == ["takeaway"])


# ---------------------------------------------------------------------------
# ③ 就業分支要跟九宮格的判定一致
# ---------------------------------------------------------------------------
def lab_text(ax):
    r = brief.compose(ctxs(labor={"axis": ax, "tilt": {}}))
    return next(p["text"] for p in r["parts"] if p["key"] == "labor")


cases = [
    ("⑫ 高於上緣 → 講「高於充分就業上緣」",
     {**AX, "unrate": 4.6, "u3_rising": False}, "高於"),
    ("⑬ Sahm 觸發 → 講快速轉弱", {**AX, "sahm_triggered": True}, "Sahm"),
    ("⑭ 失業率開始回升 → 講惡化已經開始", AX, "惡化已經開始"),
    ("⑮ 都正常 → 講落在區間內",
     {**AX, "u3_rising": False}, "落在"),
    ("⑯ 低於下緣 → 講仍緊",
     {**AX, "unrate": 3.7, "u3_rising": False}, "仍緊"),
]
for name, ax, want in cases:
    txt = lab_text(ax)
    check(name, want in txt, txt)

# 敘述與格位不能互相打架：同一份資料餵給兩邊，結論要對得上
for ax, want_state in [(AX, "中"),
                       ({**AX, "unrate": 4.6, "u3_rising": False}, "弱"),
                       ({**AX, "u3_rising": False}, "中"),
                       ({**AX, "unrate": 3.7, "u3_rising": False}, "強")]:
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
def fomc_text(f):
    return next(p["text"] for p in brief.compose(ctxs(fomc=f))["parts"]
                if p["key"] == "fomc")


# ㉓–㉖（共識開場句）已隨 bullet 版式移除：三 bullet 各自表述方向，
# 開場句沒有位子；一致度資訊由重點句與首頁方向章承擔。
check("㉓ 共識句已移除（不殘留 direction 段）",
      not hasattr(brief, "_direction")
      and all(p["key"] != "direction" for p in brief.compose(ctxs())["parts"]))

# 反對票的方向欄位是 hike／cut，不是 hawkish／dovish——寫錯會變成「3 票反對」
f_cut = {**FOM, "vote": {"dissents": [{"direction": "cut"}] * 2}}
check("㉗ 反對票方向讀得對", "2 票主張降息" in fomc_text(f_cut),
      fomc_text(f_cut))
f_none = {**FOM, "vote": {"dissents": []}}
check("㉘ 沒有反對票 → 全票通過", "全票通過" in fomc_text(f_none))


# ---------------------------------------------------------------------------
# ⑤ 重點句：升降息的可能性與解鎖條件
# ---------------------------------------------------------------------------
def take(sc, fom=FOM, inf=None):
    return brief._takeaway(sc, fom, inf)


_INF_PACE = {"core_pace3": 0.3, "core_pace_hot": 4}
# 重點句不再複述數字（通膨 bullet 以訊號為主體後，「連 N 個月／
# 近三月 X%」由 bullet 承載，重點句只留問題框架＋解鎖條件）
check("㉙ 偏鷹＋通膨重心 → 問「升不升息」、指向月步速但不複述數字",
      (lambda t: "升不升息" in t and "月步速" in t and "0.2%" in t
       and "0.30" not in t and "連 4 個月" not in t)(
          take(S(), FOM, _INF_PACE)),
      take(S(), FOM, _INF_PACE))
# 使用者的批評：重點句太冗長。瘦身後最長分支釘在 70 中文字以內，
# 同義補述（「再加速則升息機率上升」）不准回來。
check("㉙b 重點句長度 ≤ 70 中文字",
      brief.cjk_len(take(S(), FOM, _INF_PACE)) <= 70,
      brief.cjk_len(take(S(), FOM, _INF_PACE)))
check("㉚ 偏鷹＋升息反對票 → 提委員會內的升息主張",
      "升息主張" in take(S(), FOM, _INF_PACE))
check("㉛ 偏鷹但無反對票 → 不硬掰升息主張",
      "升息主張" not in take(S(), {**FOM, "vote": {"dissents": []}},
                             _INF_PACE))
check("㉛b 偏鷹但缺月步速 → 退回一般句（升息風險＋條件）",
      take(S()).startswith("重點：政策風險偏向升息"), take(S()))
check("㉜ 偏鴿 → 問的是降息時點",
      "降息時點" in take(S(lean="dovish")))
check("㉝ 中性＋月步速 → 按兵不動、下一步看通膨（同樣不複述數字）",
      (lambda t: "按兵不動" in t and "看通膨" in t and "0.30" not in t)(
          take(S(lean="neutral"), FOM, _INF_PACE)),
      take(S(lean="neutral"), FOM, _INF_PACE))
check("㉞ 條件已達成要講出來",
      "已經達成" in take(S(lean="dovish",
                           triggers=[T("通膨轉「低」", "", met=True)])),
      take(S(lean="dovish", triggers=[T("通膨轉「低」", "", met=True)])))
check("㉟ 沒有觸發條件句子照樣成立",
      take(S(triggers=[])).startswith("重點：政策風險偏向升息"),
      take(S(triggers=[])))


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
check("㊴ 改成沒有歧義的說法（三月不當 March 用）",
      "三個月年化" in b["text"] and "三月均" not in b["text"])
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


# ---------------------------------------------------------------------------
# ⑧ 「本次更新」：回答「今天有沒有新東西」
#
# 這一段每天都會重新產生，但多數日子內容一樣——因為沒有新資料。
# 讀者無從分辨「今天的數字是新的」與「今天只是把昨天那份重印一次」。
# 跟「跟上期比什麼變了」不是同一件事：那個在非發布日照樣有內容，
# 這一句在非發布日就該是空的。
# ---------------------------------------------------------------------------
class MV:                      # 假的 ChangeSet
    def __init__(self, moves):
        self.metric_moves = moves


def mv(mod, key, label, frm, to, lean="dovish", unit="%", threshold=0.05):
    return {"module": mod, "key": key, "label": label, "from": frm, "to": to,
            "delta": to - frm, "unit": unit, "threshold": threshold,
            "lean": lean}


INF_MOVES = [mv("inflation", "core_cpi_yoy", "核心 CPI 年增", 2.6, 2.5),
             mv("inflation", "core_cpi_3m", "核心 CPI 三月年化", 2.0, 1.9),
             mv("labor", "u3", "失業率", 4.0, 4.1)]


# `_fresh` 是 run.py 的 _fresh_releases() 算好的 {模組: 期別}，
# 裡面**只有 72 小時內才第一次看到的期別**。brief 不自己判斷新舊。
def wn(fresh, cur="2026-07", prov=False, moves=INF_MOVES):
    c = ctx_with(month=cur)
    c["_fresh"] = fresh
    c["changes"] = MV(list(moves))
    c["inflation"]["provisional"] = prov
    c["labor"]["provisional"] = prov
    return brief.compose(c)["parts"][0]["text"]


# 只有物價是新的（CPI 發布日）：就業那一期是上個月看到的，早就過了 72 小時。
NEW = {"inflation": "2026-07"}
s = wn(NEW)
check("55 講的是新數據本身，不是「已納入」",
      "已納入" not in s and "2.5%" in s, s)
check("56 帶出上一期的數字才看得出方向", "上月 2.6%" in s, s)
check("57 沒有任何一期是新的 → 整句不出現（非發布日不說「本次更新」）",
      "本次更新" not in brief.compose(
          {**ctx_with(), "_fresh": {}, "changes": MV(INF_MOVES)})["text"])
check("58 只挑這次剛發布的模組（就業沒更新就不講失業率）",
      "失業率" not in s, s)
check("59 run.py 沒給 _fresh 也不會爆（第一次跑就是這個情況）",
      "本次更新" not in wn({}))
check("59b 舊的 _prev_months 契約不會被誤用",
      "本次更新" not in brief.compose(
          {**ctx_with(),
           "_prev_months": {"labor": "2026-07", "inflation": "2026-06"},
           "changes": MV(INF_MOVES)})["text"])
check("60 速報值也標出來", "（速報）" in wn(NEW, prov=True))
check("61 這一句排在最前面",
      brief.compose({**ctx_with(), "_fresh": NEW,
                     "changes": MV(INF_MOVES)})["parts"][0]["key"] == "whatsnew")
check("62 動最多的排前面（重點不是清單順序）",
      wn(NEW, moves=[mv("inflation", "core_cpi_yoy", "小動", 2.0, 2.05),
                     mv("inflation", "core_cpi_3m", "大動", 3.0, 3.8)])
      .index("大動")
      < wn(NEW, moves=[mv("inflation", "core_cpi_yoy", "小動", 2.0, 2.05),
                       mv("inflation", "core_cpi_3m", "大動", 3.0, 3.8)])
      .index("小動"))
check("63 最多只講兩個數字（三個以上變流水帳）",
      wn(NEW).count("上月") <= 2)
check("64 同向才講方向",
      "方向偏降息" in wn(NEW)
      and "方向偏" not in wn(NEW, moves=[
          mv("inflation", "core_cpi_yoy", "甲", 2.0, 2.5, "hawkish"),
          mv("inflation", "core_cpi_3m", "乙", 3.0, 2.5, "dovish")]))
check("65 有新資料但都沒動 → 講「變動都在雜訊範圍內」",
      "雜訊範圍" in wn(NEW, moves=[]))

# CPI 發布日不能拿核心 PCE 來充數——那是月底 BEA 發布的，是上個月的數字。
# 這是實際發生過的：CPI 出爐當天，摘要寫的是「7 月核心 PCE 3.3%」。
_MIXED = [mv("inflation", "core_pce", "核心 PCE 年增", 3.0, 3.3, "hawkish"),
          mv("inflation", "core_cpi_yoy", "核心 CPI 年增", 2.6, 2.5)]
check("65b CPI 發布日不會寫成核心 PCE",
      "核心 PCE" not in wn(NEW, moves=_MIXED)
      and "核心 CPI" in wn(NEW, moves=_MIXED), wn(NEW, moves=_MIXED))
check("65c 就算 PCE 動得比較多也一樣（用允許清單不是比幅度）",
      abs(_MIXED[0]["delta"]) > abs(_MIXED[1]["delta"]))
check("65d 不在清單裡的指標一律不算本次新增",
      "雜訊範圍" in wn(NEW, moves=[
          mv("inflation", "exp5y5y", "長期通膨預期", 2.3, 2.5)]))
# 頭條 CPI 是 CPI 發布日新聞標題上的那個數字，不能只講得出核心。
_HEAD = [mv("inflation", "cpi_yoy", "CPI 年增", 3.0, 3.4, "hawkish"),
         mv("inflation", "core_cpi_yoy", "核心 CPI 年增", 2.6, 2.5)]
check("65e 頭條 CPI 講得出來",
      "CPI 年增 3.4%" in wn(NEW, moves=_HEAD), wn(NEW, moves=_HEAD))

# 上限放寬之後仍然有防呆
# ---------------------------------------------------------------------------
# 跨指標排序：先換成同一把尺，再比大小
#
# 使用者抓到的：CPI 剛出爐，開頭句卻寫「非農三個月均 2.0 萬人（上月 7.7
# 萬人）；非農就業月變動 −2.3 萬人」——兩條都是就業，通膨一個字都沒有。
#
# 原因是排序直接比原始變動量，而那些量的單位不一樣：
#     非農三個月均　5.7（萬人）　>　核心 CPI 年增　0.33（個百分點）
# 所以只要就業同時是新的，通膨就**永遠**擠不進去。
#
# 改成除以各自的雜訊門檻（「動了幾倍的雜訊」）才能跨指標比。
# ---------------------------------------------------------------------------
_BIG_LABOR = mv("labor", "nfp_3m", "非農三個月均", 7.7, 2.0,
                unit="萬人", threshold=1)          # 5.7 倍雜訊
_BIG_LABOR2 = mv("labor", "nfp", "非農就業月變動", 2.0, -2.3,
                 unit="萬人", threshold=1)         # 4.3 倍雜訊
_CPI = mv("inflation", "core_cpi_yoy", "核心 CPI 年增", 2.81, 2.48,
          threshold=0.05)                          # 6.6 倍雜訊

BOTH = {"labor": "2026-07", "inflation": "2026-07"}
s_both = wn(BOTH, moves=[_BIG_LABOR, _BIG_LABOR2, _CPI])
check("67 換算過的幅度才是排序依據（CPI 動 6.6 倍雜訊 > 非農 5.7 倍）",
      s_both.index("核心 CPI") < s_both.index("非農"), s_both)
check("68 兩個模組都剛發布 → 每邊至少講一個",
      "核心 CPI" in s_both and "非農" in s_both, s_both)
check("69 不會兩個名額都被同一個模組吃掉",
      s_both.count("非農") == 1, s_both)

# 只有一個模組是新的時候，兩個名額本來就該都給它
s_one = wn({"labor": "2026-07"}, moves=[_BIG_LABOR, _BIG_LABOR2, _CPI])
check("70 只有就業是新的 → 兩個名額都給就業，不硬塞通膨",
      "核心 CPI" not in s_one and s_one.count("非農") == 2, s_one)

# 沒有門檻的舊資料不能讓排序爆掉
check("71 門檻缺漏時退回比原始幅度，不丟例外",
      "本次更新" in wn(BOTH, moves=[
          {"module": "inflation", "key": "core_cpi_yoy", "label": "甲",
           "from": 2.8, "to": 2.5, "delta": -0.3, "unit": "%",
           "lean": "dovish"}]))

# 期別的寫法：「就業 7 月、物價 7 月」是資料庫的講法，不是人的講法
s_w = wn({"labor": "2026-07", "inflation": "2026-07"},
         moves=[_BIG_LABOR, _CPI])
check("72 期別寫成「7 月就業報告與 7 月 CPI」",
      "7 月就業報告與 7 月 CPI" in s_w, s_w[:40])
check("73 舊寫法不再出現", "就業 7 月" not in s_w and "物價 7 月" not in s_w)
check("74 只有一個模組時不加連接詞",
      "與" not in wn({"inflation": "2026-07"}, moves=[_CPI]).split("，")[0],
      wn({"inflation": "2026-07"}, moves=[_CPI])[:30])
check("75 第一個句號之後才是整體情勢（畫面靠它拆段）",
      s_w.count("。") == 1 and s_w.endswith("。"), s_w[-30:])

check("66 上限只是防呆，放得很寬", brief.MAX_CJK >= 400)

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
