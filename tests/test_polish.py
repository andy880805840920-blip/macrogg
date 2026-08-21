"""
整體總述模型潤稿層的防護欄測試。全程不碰網路、不讀真的環境變數。

為什麼需要這個檔案
------------------
潤稿層是整個專案唯一讓模型碰畫面文字的地方，而它的安全性**完全**建立在
三道防護欄上。防護欄壞掉的樣子都很安靜：

  ① 數字鎖定失效 → 模型改了一個數字，畫面照印，讀者拿去做決定
  ② 快取失效 → 每天重新生成，同一份數據下措辭天天漂，而且 API 費用照燒
  ③ 退回失效 → API 掛掉的那天首頁沒有總述

所以這裡把 validate() 的每一種拒絕、快取的每一種命中／失效、
與所有失敗路徑都釘住。

    python tests/test_polish.py
"""
import sys
import json
import pathlib
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from src.analysis import polish  # noqa: E402
from src.analysis import brief   # noqa: E402


class _S:                        # 最小的假 Scenario
    regime, lean = "inflation", "hawkish"
    labor_state, infl_state = "弱", "高"
    triggers = []


ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    print(f"{'通過' if cond else '失敗'}  {name}" + (f" — {detail}" if detail else ""))
    ok &= bool(cond)


SRC = ("聯準會把通膨擺在前面；三方裡兩方偏升息、一方偏降息，方向分歧。"
       "失業率 4.1% 仍算充分就業，但三月均非農 +2.0 萬人低於損益兩平的 "
       "+4.3 萬，撐不住現有失業率。核心 PCE 3.0%、三月年化 3.6% 仍在加速；"
       "核心服務除住房已連 64 個月高於目標。7/29 會議維持不變、3 票主張升息，"
       "下次會議 35 天後。財政缺口 1.3% GDP 與 AI 資本支出佔營運現金流 83%，"
       "同推長端供給，降息也壓不下長端。"
       "重點：降息還遠，解鎖條件是通膨轉「低」（還差 1.02 個百分點）。")

GOOD = ("聯準會目前把通膨放在第一位，三方之中兩方偏升息、一方偏降息。"
        "失業率 4.1% 表面仍屬充分就業，但三月均非農 +2.0 萬人已低於損益兩平"
        "的 +4.3 萬，就業增速撐不住現有的失業率。核心 PCE 3.0%、三月年化 "
        "3.6% 還在加速，核心服務除住房更已連續 64 個月高於目標。7/29 會議"
        "按兵不動、3 票主張升息，下次會議在 35 天後。財政缺口 1.3% GDP 與 "
        "AI 資本支出佔營運現金流 83% 同時推升長端供給，降息也壓不下長端。"
        "重點：降息還遠，解鎖條件是通膨轉「低」，還差 1.02 個百分點。")


# ---------------------------------------------------------------------------
# ① validate：一條一條拒絕
# ---------------------------------------------------------------------------
check("① 合格的改寫通過", polish.validate(GOOD, SRC) == "",
      polish.validate(GOOD, SRC))
check("② 空字串擋下", polish.validate("", SRC) != "")
check("③ 新數字擋下（4.1 改成 4.2）",
      "4.2" in polish.validate(GOOD.replace("4.1%", "4.2%"), SRC))
check("④ markdown 擋下",
      polish.validate(GOOD.replace("重點：", "**重點**："), SRC) != "")
check("⑤ 換行擋下", polish.validate(GOOD.replace("。核心", "。\n核心"), SRC) != "")
check("⑥ 重點句前綴不見 → 擋下",
      "重點" in polish.validate(GOOD.replace("重點：", "總結來說，"), SRC))
check("⑦ 太長擋下（上限是防呆，不是編輯限制）",
      polish.validate(GOOD + "多餘的話" * 200, SRC) != "")
check("⑧ 太短擋下", polish.validate("重點：太短。", SRC) != "")
check("⑨ 數字變少沒關係（模型可以省略）",
      polish.validate(GOOD.replace("、3 票主張升息", ""), SRC) == "")
check("⑩ 千分位不算新數字",
      "1828" not in str(polish._numbers("1,828 億")) or
      polish._numbers("1,828 億") == polish._numbers("1828 億"))


# ---------------------------------------------------------------------------
# ② maybe_polish：快取與退回
# ---------------------------------------------------------------------------
def assembled(text=SRC):
    return {"text": text, "chars": 150,
            "parts": [{"key": "all", "text": text, "chars": 150}]}


tmp = pathlib.Path(tempfile.mkdtemp())
cache = tmp / "brief.json"

# 沒金鑰 → 組裝版，不打 API（_post 沒給也不會炸）
r = polish.maybe_polish(assembled(), cache, offline=False, env={})
check("⑪ 沒金鑰 → 組裝版", r["source"] == "assembled")
check("⑫ 沒金鑰時不寫快取", not cache.exists())

# 離線 → 組裝版，就算金鑰在也不打
r = polish.maybe_polish(assembled(), cache, offline=True,
                        env={"ANTHROPIC_API_KEY": "sk-test"})
check("⑬ 離線 → 組裝版", r["source"] == "assembled")

# 有金鑰、模擬 API 成功 → 模型版＋寫快取
calls = []


def fake_post(key, model, text, system=None, temperature=None, **kw):
    calls.append(model)
    return GOOD


env = {"ANTHROPIC_API_KEY": "sk-test"}
r = polish.maybe_polish(assembled(), cache, env=env, _post=fake_post)
check("⑭ 成功 → 模型版", r["source"] == "model" and r["text"] == GOOD)
check("⑮ 呼叫用該供應商的預設模型",
      calls == [polish.PROVIDERS["anthropic"]["model"]], str(calls))
check("⑯ 快取寫入", cache.exists()
      and json.loads(cache.read_text())["text"] == GOOD)

# 同一份事實再跑 → 吃快取，不再呼叫
r = polish.maybe_polish(assembled(), cache, env=env, _post=fake_post)
check("⑰ 事實沒變 → 沿用快取、不呼叫 API",
      r["source"] == "model-cache" and len(calls) == 1)

# 事實變了 → 重新生成
r = polish.maybe_polish(assembled(SRC.replace("4.1%", "4.4%")), cache,
                        env=env, _post=lambda k, m, t, s=None, tp=None: GOOD.replace("4.1%", "4.4%"))
check("⑱ 事實變了 → 重新生成", r["source"] == "model")

# 模型換了 → 快取失效（雜湊含模型名）
r = polish.maybe_polish(assembled(), cache,
                        env={**env, "BRIEF_MODEL": "claude-x"},
                        _post=lambda k, m, t, s=None, tp=None: GOOD)
check("⑲ 換模型 → 快取失效重生成", r["source"] == "model")

# API 例外 → 組裝版
def boom(key, model, text, system=None, temperature=None, **kw):
    raise RuntimeError("connection reset")


r = polish.maybe_polish(assembled(SRC + "改一下"), tmp / "c2.json",
                        env=env, _post=boom)
check("⑳ API 掛掉 → 組裝版", r["source"] == "assembled")

# 驗證沒過 → 組裝版、不寫快取
c3 = tmp / "c3.json"
r = polish.maybe_polish(assembled(), c3, env=env,
                        _post=lambda k, m, t, s=None, tp=None: GOOD.replace("83%", "93%"))
check("㉑ 驗證沒過 → 組裝版", r["source"] == "assembled")
check("㉒ 驗證沒過不寫快取（壞結果不能被沿用）", not c3.exists())

# 空總述 → 原樣回，不呼叫
r = polish.maybe_polish({"text": "", "chars": 0, "parts": []}, c3,
                        env=env, _post=boom)
check("㉓ 空總述 → 直接回", r["source"] == "assembled" and r["text"] == "")


# ---------------------------------------------------------------------------
# ③ 供應商選擇：Gemini（免費）優先，模型跟著供應商走
# ---------------------------------------------------------------------------
check("㉔ 只設 Gemini 金鑰 → 用 Gemini",
      polish._pick_provider({"GEMINI_API_KEY": "g1"}) == ("gemini", "g1"))
check("㉕ GOOGLE_API_KEY 也認得",
      polish._pick_provider({"GOOGLE_API_KEY": "g2"}) == ("gemini", "g2"))
check("㉖ 兩把都設 → Gemini 優先（免費）",
      polish._pick_provider({"GEMINI_API_KEY": "g",
                             "ANTHROPIC_API_KEY": "a"})[0] == "gemini")
check("㉗ 都沒設 → 空字串",
      polish._pick_provider({}) == ("", ""))

gcalls = []
r = polish.maybe_polish(assembled(SRC + "再改一下"), tmp / "c4.json",
                        env={"GEMINI_API_KEY": "g1"},
                        _post=lambda k, m, t2, s=None, tp=None: (gcalls.append((k, m)), GOOD)[1])
check("㉘ Gemini 路徑用 Gemini 的預設模型",
      r["source"] == "model"
      and gcalls == [("g1", polish.PROVIDERS["gemini"]["model"])],
      str(gcalls))
check("㉙ 結果帶模型名（進執行紀錄）",
      r.get("model") == polish.PROVIDERS["gemini"]["model"])

# BRIEF_MODEL 覆寫兩家都適用
mcalls = []
polish.maybe_polish(assembled(SRC + "再改兩下"), tmp / "c5.json",
                    env={"GEMINI_API_KEY": "g1", "BRIEF_MODEL": "gemini-2.5-pro"},
                    _post=lambda k, m, t2, s=None, tp=None: (mcalls.append(m), GOOD)[1])
check("㉚ BRIEF_MODEL 覆寫生效", mcalls == ["gemini-2.5-pro"], str(mcalls))

# 換供應商 → 快取失效（雜湊含供應商）：同一份事實不能拿 A 家的快取
# 冒充 B 家的結果——兩家的文風不同，換供應商本來就該重生
c6 = tmp / "c6.json"
polish.maybe_polish(assembled(), c6, env={"GEMINI_API_KEY": "g1"},
                    _post=lambda k, m, t2, s=None, tp=None: GOOD)
r = polish.maybe_polish(assembled(), c6, env={"ANTHROPIC_API_KEY": "a1"},
                        _post=lambda k, m, t2, s=None, tp=None: GOOD)
check("㉛ 換供應商 → 快取失效重生成", r["source"] == "model")

# 金鑰失效但事實沒變 → 沿用舊快取（不是跳回組裝版）
r = polish.maybe_polish(assembled(), c6, env={},
                        _post=boom)
check("㉜ 沒金鑰但快取還在 → 沿用潤稿版",
      r["source"] == "model-cache")


# ---------------------------------------------------------------------------
# ④ 模型被汰換：404 要能自己換一個，不是安靜地少一區
#
# 這是實際發生過的：gemini-2.5-flash 回 404
#「models/… is not found for API version v1beta」。那句話看起來像網址寫錯，
# 實際上是「這把金鑰沒有這個模型」——模型會汰換，而汰換的那天首頁的
# 整體情勢就悄悄變回組裝版，沒有人會發現。
# ---------------------------------------------------------------------------
AVAIL = ["gemini-3.6-flash", "gemini-2.5-flash-lite", "gemini-3.1-pro-preview",
         "gemini-2.5-pro", "text-embedding-004", "gemini-3.1-flash-tts-preview",
         "imagen-4.0-generate", "gemini-3-flash-preview"]

check("㉝ 挑到正式版的 flash（不挑 preview、不挑別種用途）",
      polish._gemini_pick(AVAIL) == "gemini-3.6-flash",
      polish._gemini_pick(AVAIL))
# flash 是 flash-lite 的子字串：分組寫錯的話 lite 會被歸成 flash 而勝出。
# 這個任務有硬性格式要求，做不到就退回組裝版——寧可用正常的 flash。
check("㉝b flash 勝過 flash-lite（子字串不能誤判）",
      polish._gemini_pick(["gemini-3.6-flash-lite", "gemini-2.5-flash"])
      == "gemini-2.5-flash",
      polish._gemini_pick(["gemini-3.6-flash-lite", "gemini-2.5-flash"]))
check("㉝c flash-lite 勝過 pro",
      polish._gemini_pick(["gemini-2.5-pro", "gemini-2.5-flash-lite"])
      == "gemini-2.5-flash-lite")
check("㉞ 排除掉的那個不會被挑回來",
      polish._gemini_pick(["gemini-2.5-flash"], exclude="gemini-2.5-flash") == "")
check("㉟ 沒有 flash 時退而求其次用 pro",
      polish._gemini_pick(["gemini-2.5-pro", "text-embedding-004"])
      == "gemini-2.5-pro")
check("㊱ 同組內版本大的優先",
      polish._gemini_pick(["gemini-2.5-flash", "gemini-3.6-flash"])
      == "gemini-3.6-flash")
check("㊲ 清單全是別種用途 → 挑不到（回空，退組裝版）",
      polish._gemini_pick(["text-embedding-004", "imagen-4.0-generate"]) == "")
for bad in ("tts", "image", "embedding", "live", "vision"):
    check(f"㊳ 排除 {bad} 類模型",
          polish._gemini_pick([f"gemini-3.1-{bad}-x"]) == "")


class Resp:
    def __init__(self, code): self.status_code = code


def http404():
    e = polish.requests.HTTPError("404 Client Error: Not Found")
    e.response = Resp(404)
    return e


# 404 → 問清單 → 換一個重試 → 成功，而且回傳的是**實際用的**模型名
tried = []


def fake_call(key, model, text, system=None, temperature=None, **kw):
    tried.append(model)
    if model == "gemini-2.5-flash":
        raise http404()
    return GOOD


polish._gemini_call = fake_call
polish._gemini_models = lambda key: AVAIL
r = polish._post_gemini("k", "gemini-2.5-flash", SRC)
check("㊴ 404 → 換模型重試", isinstance(r, tuple) and r[0] == GOOD
      and r[1] == "gemini-3.6-flash", str(r if not isinstance(r, tuple) else r[1]))
check("㊵ 真的試了兩個模型", tried == ["gemini-2.5-flash", "gemini-3.6-flash"],
      str(tried))

# 換過的模型名要進結果（畫面與執行紀錄要標真的用了哪一個）
r = polish.maybe_polish(assembled(SRC + "換模型測試"), tmp / "c7.json",
                        env={"GEMINI_API_KEY": "g1"},
                        _post=lambda k, m, t, s=None, tp=None: (GOOD, "gemini-3.6-flash"))
check("㊶ 實際用的模型進結果",
      r["source"] == "model" and r["model"] == "gemini-3.6-flash", str(r))
check("㊷ 也寫進快取",
      json.loads((tmp / "c7.json").read_text())["model"] == "gemini-3.6-flash")

# 查不到清單 → 原本的 404 照樣往上拋（退組裝版），不能假裝成功
polish._gemini_models = lambda key: []
try:
    polish._post_gemini("k", "gemini-2.5-flash", SRC)
    hit = False
except polish.requests.HTTPError:
    hit = True
check("㊸ 查不到清單 → 拋回原本的錯（退組裝版）", hit)

# 404 以外的錯不要亂換模型——換了只會多燒一次額度
def boom500(key, model, text, system=None, temperature=None, **kw):
    e = polish.requests.HTTPError("500")
    e.response = Resp(500)
    raise e


polish._gemini_call = boom500
polish._gemini_models = lambda key: AVAIL
try:
    polish._post_gemini("k", "gemini-2.5-flash", SRC)
    hit = False
except polish.requests.HTTPError:
    hit = True
check("㊹ 500 不觸發換模型", hit)


# ---------------------------------------------------------------------------
# ⑤ 驗證沒過 → 帶著原因重試一次（不是直接放棄，也不是無限重試）
#
# 實際發生過：404 換上的替代模型把「重點：」前綴弄丟了。格式錯誤跟
# API 掛掉不一樣——模型看得懂「你上次錯在哪」，再講一次通常就對了。
# 但只准一次：兩次都做不到就是這個模型做不到，繼續燒額度沒有意義。
# ---------------------------------------------------------------------------
BAD = GOOD.replace("重點：", "總結來說，")     # 前綴不見（實際發生的那種錯）

# 第一次壞、帶原因重試後好 → 模型版
seq = []


def flaky(key, model, text, system=None, temperature=None, **kw):
    seq.append(text)
    return BAD if len(seq) == 1 else GOOD


r = polish.maybe_polish(assembled(SRC + "重試測試"), tmp / "c8.json",
                        env={"GEMINI_API_KEY": "g1"}, _post=flaky)
check("㊺ 驗證沒過 → 重試後成功用模型版",
      r["source"] == "model" and r["text"] == GOOD, r["source"])
check("㊻ 重試的輸入帶著被退回的原因",
      len(seq) == 2 and "上一次的輸出被退回" in seq[1] and "重點" in seq[1])
check("㊼ 第一次的輸入沒有多餘的附註", "被退回" not in seq[0])

# 兩次都壞 → 組裝版，而且**正好**兩次（不是三次、不是一次）
seq2 = []
r = polish.maybe_polish(assembled(SRC + "重試上限測試"), tmp / "c9.json",
                        env={"GEMINI_API_KEY": "g1"},
                        _post=lambda k, m, t, s=None, tp=None: (seq2.append(t), BAD)[1])
check("㊽ 重試後仍沒過 → 組裝版", r["source"] == "assembled")
check("㊾ 重試只有一次（共兩個呼叫）", len(seq2) == 2, f"{len(seq2)} 次")
check("㊿ 壞結果沒有寫進快取", not (tmp / "c9.json").exists())

# 重試那一次拋例外 → 一樣安全退回組裝版
seq3 = []


def then_boom(key, model, text, system=None, temperature=None, **kw):
    seq3.append(text)
    if len(seq3) == 1:
        return BAD
    raise RuntimeError("connection reset")


r = polish.maybe_polish(assembled(SRC + "重試爆炸測試"), tmp / "c10.json",
                        env={"GEMINI_API_KEY": "g1"}, _post=then_boom)
check("51 重試時 API 掛掉 → 組裝版", r["source"] == "assembled")


# ---------------------------------------------------------------------------
# ⑥ 兩種誤判：檢查太嚴，把合格的改寫丟掉
#
# 兩次都實際發生過，而且失敗理由聽起來都很嚴重：
#   「出現原文沒有的數字：['2']」——其實只是把「+2.0 萬」寫成「+2 萬」
#   「輸出含 markdown」        ——其實只是把「重點」加粗
# 兩種都不是模型寫錯，是我的檢查分不清**內容**與**排版**。
# 修法是：數字用數值比、排版記號機械拿掉；鎖定的嚴格程度不變。
# ---------------------------------------------------------------------------
check("52 「2」與「2.0」是同一個數字",
      polish._numbers("2 萬") == polish._numbers("2.0 萬"))
check("53 「4.1」與「4.2」仍然是兩個（沒有放寬）",
      polish._numbers("4.1") != polish._numbers("4.2"))
check("54 「2」與「20」仍然是兩個",
      polish._numbers("2") != polish._numbers("20"))
check("55 千分位照舊不算新數字",
      polish._numbers("1,828 億") == polish._numbers("1828 億"))
check("56 省略尾數零的改寫可以通過",
      polish.validate(GOOD.replace("+2.0 萬", "+2 萬"), SRC) == "",
      polish.validate(GOOD.replace("+2.0 萬", "+2 萬"), SRC))

check("57 粗體被清掉而不是整段退回",
      polish._sanitize("**重點**：降息還遠。") == "重點：降息還遠。",
      polish._sanitize("**重點**：降息還遠。"))
check("58 標題記號與清單符號也清掉",
      polish._sanitize("# 標題\n- 一項\n1. 兩項") == "標題 一項 兩項",
      polish._sanitize("# 標題\n- 一項\n1. 兩項"))
check("59 換行折成空格", "\n" not in polish._sanitize("甲\n乙"))
check("60 清理不動內容裡的數字與文字",
      polish._sanitize(GOOD) == GOOD)

# 端到端：模型把重點加粗 → 清掉後通過，不再退回組裝版
r = polish.maybe_polish(assembled(SRC + "粗體測試"), tmp / "c11.json",
                        env={"GEMINI_API_KEY": "g1"},
                        _post=lambda k, m, t, s=None, tp=None: GOOD.replace("重點：", "**重點**："))
check("61 加粗的改寫最後仍是模型版",
      r["source"] == "model" and "**" not in r["text"], r["source"])
check("62 存進畫面的文字沒有殘留星號", "*" not in r["text"])

# 後備防線還在：清理沒做到時 validate 照樣擋
check("63 validate 仍把殘留的 markdown 當失敗",
      polish.validate("**重點**：" + GOOD[3:], SRC) != "")


# ---------------------------------------------------------------------------
# ⑦ 其餘的退回路徑：一條一條堵掉「其實沒寫錯卻被擋下」
# ---------------------------------------------------------------------------
check("64 半形冒號收斂成全形（不然會判成前綴不見）",
      polish._sanitize("重點: 降息還遠。") == "重點：降息還遠。",
      polish._sanitize("重點: 降息還遠。"))
check("65 冒號前夾空白也收斂",
      polish._sanitize("重點 ：降息還遠。") == "重點：降息還遠。")
check("66 全形數字轉半形",
      polish._sanitize("失業率 ４.１％") == "失業率 4.1%",
      polish._sanitize("失業率 ４.１％"))
check("67 全形數字轉完之後不算新數字",
      polish.validate(polish._sanitize(GOOD.replace("4.1%", "４.１％")), SRC) == "",
      polish.validate(polish._sanitize(GOOD.replace("4.1%", "４.１％")), SRC))
# 所有空白（含全形空格、不斷行空格）都折成一般空格。這是安全的，
# 但**只在組裝版本身不含那些字元時**才安全——否則折掉會弄壞排版。
# 所以真正要釘的是那個前提，不是折不折。
check("68 空白一律折成一般空格", polish._sanitize("甲　·　乙") == "甲 · 乙",
      polish._sanitize("甲　·　乙"))
# 這一段要驗的是**真的組裝版**，不是手寫的樣本——手寫的樣本永遠會通過。
_BRIEF = brief.compose({"scenario": {"scenario": _S()}})["text"]
check("68b 前提成立：組裝版不含全形空格或不斷行空格",
      "　" not in _BRIEF and " " not in _BRIEF, repr(_BRIEF[:40]))

# 字數範圍要跟著組裝版走，不能寫死
lo, hi = polish._target_range("中" * 180)
check("69 字數範圍貼著實際長度", lo <= 180 <= hi, f"{lo}–{hi}")
check("70 範圍留在護欄內側",
      lo >= polish.MIN_CJK and hi <= polish.MAX_CJK, f"{lo}–{hi}")
lo2, hi2 = polish._target_range("中" * 100)
check("71 組裝版短的時候範圍跟著往下移", lo2 < lo and hi2 < hi, f"{lo2}–{hi2}")
check("72 範圍永遠不會反過來",
      all(a < b for a, b in (polish._target_range("中" * n)
                             for n in (0, 50, 120, 180, 300))))
check("73 提示詞帶的是算出來的範圍",
      f"{lo} 到 {hi}" in polish._system("中" * 180))

# 推理層級：欄位名稱跨世代不同，關錯等於沒關
check("74 gemini-2.x 用 thinkingBudget",
      polish._thinking("gemini-2.5-flash") == {"thinkingConfig":
                                               {"thinkingBudget": 0}})
# 3.x 與別名不送推理欄位：thinkingLevel 與 thinkingBudget 都被 400 拒絕過，
# 各有一次直接證據。「一律送、反正 400 有退路」的代價是**每次執行**都先送
# 一個註定失敗的請求，log 裡固定出現一段錯誤訊息，白花一個來回。
# 退路是給意外用的，不是給已知會失敗的情況用的。
check("75 3.x 不送推理欄位（已知會被 400 拒絕）",
      polish._thinking("gemini-3.6-flash") == {})
check("76 別名也不送（別名指向的是最新世代）",
      polish._thinking("gemini-flash-latest") == {})
check("76b 2.x 照送（實測有效）",
      polish._thinking("gemini-2.5-flash")
      == {"thinkingConfig": {"thinkingBudget": 0}})
check("76c lite 也是看版本不是看名字",
      polish._thinking("gemini-2.5-flash-lite")
      == {"thinkingConfig": {"thinkingBudget": 0}})
check("77 輸出額度夠大，不會被推理吃光", polish.MAX_OUT >= 2000)

# 2.5 Pro **關不掉推理**：thinkingBudget 只收 128–32768 或 -1，送 0 會 400。
# 跟 3.x 不同的是它照收 thinkingConfig，所以不是「不送」而是「送最小值」。
# 這一條的價值跟當初 thinkingLevel 那次一模一樣：**已知會失敗的請求不要送**，
# 否則每一次執行都白花一個來回、log 裡固定一段 400。
check("77b 2.5 Pro 送最小推理額度，不是 0（0 會被 400 拒絕）",
      polish._thinking("gemini-2.5-pro")
      == {"thinkingConfig": {"thinkingBudget": polish.PRO_MIN_THINKING}},
      str(polish._thinking("gemini-2.5-pro")))
check("77c 最小值在合法範圍內（128–32768）",
      128 <= polish.PRO_MIN_THINKING <= 32768)
check("77d 推理額度遠小於輸出額度，額度留給文字",
      polish.PRO_MIN_THINKING < polish.MAX_OUT / 10,
      f"{polish.PRO_MIN_THINKING} vs {polish.MAX_OUT}")
check("77e 同世代的 flash 不受影響（flash 可以真的關掉）",
      polish._thinking("gemini-2.5-flash")
      == {"thinkingConfig": {"thinkingBudget": 0}})
check("77f 3.x 的 pro 仍然什麼都不送（那一代關不掉也收不了）",
      polish._thinking("gemini-3.1-pro-preview") == {})
check("77g 預設模型是 2.5 Pro",
      polish.PROVIDERS["gemini"]["model"] == "gemini-2.5-pro",
      polish.PROVIDERS["gemini"]["model"])
check("77h 而且預設模型自己送得出合法的推理設定",
      polish._thinking(polish.PROVIDERS["gemini"]["model"])
      .get("thinkingConfig", {}).get("thinkingBudget") != 0)


# ---------------------------------------------------------------------------
# ⑧ 逐字的字元編號：被字數要求逼出來的「數出聲音」
#
# 實際收到過的輸出長這樣（模型把字元位置標進正文）：
#     ，(77)核(78)心(79) PCE(82) 3.3%(86)、(87)三(88)月(89)化(91)…
# 一次觸發兩件事：畫面上全是括號數字，而且那些數字全部被數字鎖定
# 判成「原文沒有的數字」——連退兩次，最後整段被丟掉。
# ---------------------------------------------------------------------------
ANNOT = "，(77)核(78)心(79) PCE(82) 3.3%(86)、(87)三(88)月(89)年(90)化(91) 2.5%"
check("78 字元編號被清掉",
      polish._sanitize(ANNOT) == "，核心 PCE 3.3%、三月年化 2.5%",
      polish._sanitize(ANNOT))
check("79 清掉之後不再有假的新數字",
      polish._numbers(polish._sanitize(ANNOT)) == {repr(3.3), repr(2.5)},
      str(polish._numbers(polish._sanitize(ANNOT))))
# 門檻：偶爾一兩個括號數字是正常內容，不能誤刪
check("80 只有一個括號數字 → 不動",
      polish._sanitize("還差 1.02 個百分點（3）") == "還差 1.02 個百分點（3）")
check("81 兩個也不動（低於門檻）",
      polish._sanitize("甲（1）乙（2）") == "甲（1）乙（2）")
check("82 三個以上才清", polish._sanitize("甲（1）乙（2）丙（3）") == "甲乙丙")
check("83 有單位的括號不算編號",
      "3 票" in polish._sanitize("甲（3 票）乙（4 票）丙（5 票）"),
      polish._sanitize("甲（3 票）乙（4 票）丙（5 票）"))
check("84 半形括號也認得", polish._sanitize("甲(1)乙(2)丙(3)") == "甲乙丙")

# 提示詞要明講不准數字數、不准加註記——這是這個病灶的成因
_sys = polish._system("中" * 180)
check("85 提示詞禁止逐字計數與標註",
      all(k in _sys for k in ("不要逐字計數", "字元位置", "括號編號")),
      _sys[-160:])


# ---------------------------------------------------------------------------
# ⑨ 暫時性失敗要重試
#
# 實際發生過：伺服器回 503 Service Unavailable，整段總述就退回組裝版。
# 這種錯跟送出去的內容無關，過幾秒再送多半就成功——不重試等於讓一次
# 幾秒的伺服器抖動決定首頁那一段的樣子。
# 但 400／404 不能重試：再送幾次都是同樣的結果，只是白花額度。
# ---------------------------------------------------------------------------
class FakeResp:
    def __init__(self, code, headers=None):
        self.status_code, self.headers = code, headers or {}


slept = []
polish._SLEEP = lambda s: slept.append(s)


def fake_requests(codes):
    """依序回傳這些狀態碼；int 代表回應，Exception 代表連線層失敗。"""
    seq, calls = list(codes), []

    def request(method, url, **kw):
        calls.append(url)
        nxt = seq.pop(0) if seq else 200
        if isinstance(nxt, Exception):
            raise nxt
        return FakeResp(nxt)
    return request, calls


_real_request = polish.requests.request
try:
    # 503 → 503 → 200：第三次成功
    slept.clear()
    polish.requests.request, calls = fake_requests([503, 503, 200])
    r = polish._http("POST", "https://x", label="測試")
    check("86 503 會重試到成功", r.status_code == 200 and len(calls) == 3,
          f"{len(calls)} 次")
    check("87 兩次之間有退避", slept == list(polish.BACKOFF), str(slept))

    # 400 不重試
    slept.clear()
    polish.requests.request, calls = fake_requests([400, 200])
    r = polish._http("POST", "https://x", label="測試")
    check("88 400 不重試（再送也一樣）",
          r.status_code == 400 and len(calls) == 1, f"{len(calls)} 次")

    # 404 不重試——模型不存在要走換模型那條路，不是重送
    polish.requests.request, calls = fake_requests([404, 200])
    check("89 404 不重試",
          polish._http("GET", "https://x", label="測試").status_code == 404
          and len(calls) == 1)

    # 一直 503 → 試滿次數後回最後一個 response，讓呼叫端產生一致的錯誤
    slept.clear()
    polish.requests.request, calls = fake_requests([503] * 5)
    r = polish._http("POST", "https://x", label="測試")
    check("90 一直失敗 → 試滿次數就放棄",
          r.status_code == 503 and len(calls) == polish.MAX_TRIES,
          f"{len(calls)} 次")

    # 連線層例外也重試；全部失敗要把例外丟出去（不能假裝成功）
    slept.clear()
    boom_exc = polish.requests.RequestException("connection reset")
    polish.requests.request, calls = fake_requests([boom_exc, boom_exc, 200])
    check("91 連線失敗也重試",
          polish._http("POST", "https://x", label="測試").status_code == 200)
    polish.requests.request, calls = fake_requests([boom_exc] * 5)
    try:
        polish._http("POST", "https://x", label="測試")
        hit = False
    except polish.requests.RequestException:
        hit = True
    check("92 全部連線失敗 → 丟出例外", hit)

    # 429 照 Retry-After 等，但要有上限
    slept.clear()
    polish.requests.request = lambda m, u, **kw: (
        FakeResp(429, {"Retry-After": "5"}) if len(slept) < 1 else FakeResp(200))
    polish._http("POST", "https://x", label="測試")
    check("93 429 照 Retry-After 等", slept == [5.0], str(slept))
    check("94 Retry-After 有上限（伺服器亂給不能照單全收）",
          polish._retry_after(FakeResp(429, {"Retry-After": "9999"})) == 0.0)
    check("95 沒有 Retry-After 就用固定退避",
          polish._retry_after(FakeResp(503)) == 0.0)
finally:
    polish.requests.request = _real_request
    polish._SLEEP = __import__("time").sleep


# ---------------------------------------------------------------------------
# ⑩ 設定診斷：讓「我明明設了為什麼沒生效」在 log 裡有答案
# ---------------------------------------------------------------------------
n = polish.config_note({"GEMINI_API_KEY": "g", "BRIEF_MODEL": "gemini-flash-latest"})
check("96 有覆寫 → 印出模型與來源",
      "gemini-flash-latest" in n and "BRIEF_MODEL" in n, n)
n = polish.config_note({"GEMINI_API_KEY": "g"})
check("97 沒覆寫 → 講出「沒有傳進來」並指向 update.yml",
      "沒有傳進來" in n and "update.yml" in n, n)
check("98 沒覆寫時印的是預設模型",
      polish.PROVIDERS["gemini"]["model"] in n)
n = polish.config_note({})
check("99 沒有金鑰 → 講清楚會走組裝版", "組裝版" in n, n)
check("100 診斷字串不會外洩金鑰",
      "g" not in polish.config_note({"GEMINI_API_KEY": "supersecret"})
      or "supersecret" not in polish.config_note({"GEMINI_API_KEY": "supersecret"}))


# ---------------------------------------------------------------------------
# ⑪ 重點句不交給模型
#
# 這是兩種退回的共同根因。模型同時被要求「壓在字數範圍內」與「保留重點句」，
# 兩件事會互相排擠——實測到的順序是：
#   第一次 206 字（超出上限）→ 帶著「太長」的理由重試
#   第二次為了縮短，直接把整句重點句刪掉 → 「重點句的前綴不見了」
# 兩次都不是模型寫壞，是給了兩個會打架的要求。
#
# 拆開之後「重點：」變成**結構上保證存在**，不再靠模型配合。
# ---------------------------------------------------------------------------
BODY = SRC[:SRC.index("重點：")]
TAIL = SRC[SRC.index("重點："):]


def parted():
    return {"text": SRC, "chars": polish.cjk_len(SRC),
            "parts": [{"key": "direction", "text": BODY,
                       "chars": polish.cjk_len(BODY)},
                      {"key": "takeaway", "text": TAIL,
                       "chars": polish.cjk_len(TAIL)}]}


seen = []


def spy(key, model, text, system=None, temperature=None, **kw):
    """回一段長度合格、但**刻意不寫重點句**的改寫。"""
    seen.append((text, system))
    return GOOD[:GOOD.index("重點：")]


r = polish.maybe_polish(parted(), tmp / "d1.json",
                        env={"GEMINI_API_KEY": "g"}, _post=spy)
check("101 送給模型的內容不含重點句", "重點：" not in seen[0][0], seen[0][0][-30:])
check("102 送給模型的是事實段落", seen[0][0].startswith("聯準會把通膨"))
check("103 重點句原封不動接回去", r["text"].endswith(TAIL), r["text"][-40:])
check("104 就算模型沒寫重點句，結果照樣有",
      "重點：" in r["text"] and r["source"] == "model")

# 模型交出一段不含重點句的文字 → 仍然通過驗證（因為我們自己接回去了）
check("105 前綴變成結構上保證，不靠模型配合",
      polish.validate(r["text"], SRC) == "")

# 字數上限要先扣掉重點句的長度，否則接回去就超出護欄。
# 用一段夠長的本文，讓上限由 MAX_CJK 決定而不是由「原長 +10」決定——
# 那才是 reserve 真正起作用的情況。
_LONG = "中" * 480
lo_r, hi_r = polish._target_range(_LONG, polish.cjk_len(TAIL))
lo_n, hi_n = polish._target_range(_LONG, 0)
check("106 有 reserve 時上限更嚴", hi_r < hi_n, f"{hi_r} vs {hi_n}")
check("107 扣掉之後接回去不會超出護欄",
      hi_r + polish.cjk_len(TAIL) <= polish.MAX_CJK,
      f"{hi_r} + {polish.cjk_len(TAIL)}")
_hb, _ht = polish._target_range(BODY, polish.cjk_len(TAIL))
check("107b 實際這一段接回去也不會超出",
      _ht + polish.cjk_len(TAIL) <= polish.MAX_CJK,
      f"{_ht} + {polish.cjk_len(TAIL)}")
check("108 提示詞用的是扣過的上限", f"不要超過 {_ht} 字" in seen[0][1],
      seen[0][1][seen[0][1].find("長度"):][:40])
check("109 提示詞明講不要自己寫結論", "不要自己寫結論" in seen[0][1])

# 只有重點句 → 沒有東西好改寫，直接回組裝版、不呼叫 API
only = {"text": TAIL, "chars": polish.cjk_len(TAIL),
        "parts": [{"key": "takeaway", "text": TAIL,
                   "chars": polish.cjk_len(TAIL)}]}
r = polish.maybe_polish(only, tmp / "d2.json",
                        env={"GEMINI_API_KEY": "g"}, _post=boom)
check("110 只有重點句 → 不呼叫、直接回組裝版",
      r["source"] == "assembled" and r["text"] == TAIL)


# ---------------------------------------------------------------------------
# ⑪b 「本次更新」那一句也不交給模型
#
# 實際發生過的：CPI 發布日，組裝版寫的是「本次更新：物價 7 月，CPI 年增
# 3.4%（上月 3.5%）」，畫面上出現的卻是「本次更新：7 月核心 PCE 3.3%、
# 三個月年化 2.9%」——模型把下一段的通膨敘述整句抄過來冠上「本次更新」。
#
# **數字鎖定攔不到**：3.3 與 2.9 本來就在原文的通膨段裡，逐一比對全部合法。
# 鎖定管的是「有沒有憑空冒出的數字」，不是「數字有沒有出現在對的句子裡」。
# 提示詞當時就寫著「保留在最前面且不得改動任何數字」，模型照樣改了——
# 能用結構保證的事就不該靠提示詞。
# ---------------------------------------------------------------------------
HEAD = "本次更新：物價 7 月，CPI 年增 3.4%（上月 3.5%）。"


def headed(head=HEAD):
    whole = head + BODY + TAIL
    return {"text": whole, "chars": polish.cjk_len(whole),
            "parts": [{"key": "whatsnew", "text": head,
                       "chars": polish.cjk_len(head)},
                      {"key": "direction", "text": BODY,
                       "chars": polish.cjk_len(BODY)},
                      {"key": "takeaway", "text": TAIL,
                       "chars": polish.cjk_len(TAIL)}]}


seen2 = []


def spy2(key, model, text, system=None, temperature=None, **kw):
    seen2.append((text, system))
    return GOOD[:GOOD.index("重點：")]


r = polish.maybe_polish(headed(), tmp / "d3.json",
                        env={"GEMINI_API_KEY": "g"}, _post=spy2)
check("110b 送給模型的內容不含「本次更新」那一句",
      "本次更新" not in seen2[0][0], seen2[0][0][:40])
check("110c 那一句原封不動接回最前面",
      r["text"].startswith(HEAD), r["text"][:50])
check("110d 前後兩句都在，中間才是模型寫的",
      r["text"].startswith(HEAD) and r["text"].endswith(TAIL)
      and r["source"] == "model")
check("110e 提示詞明講不要自己寫那一句",
      "不要自己寫那一句" in seen2[0][1])
_res = polish.cjk_len(HEAD) + polish.cjk_len(TAIL)
check("110f 字數上限把前後兩句都扣掉了",
      f"不要超過 {polish._target_range(BODY, _res)[1]} 字" in seen2[0][1])


# 模型自己編一句「本次更新」→ 退回。這是關鍵的一項：它抄的數字全部合法，
# validate 一道都攔不住，只能靠「這句話根本不該由模型寫出來」這個事實。
# 抄的是**原文裡真的有的**數字（核心 PCE 那一段），所以數字鎖定必定放行。
# 真實案例抄的是 3.3%／2.9%，這份 fixture 對應的是 3.0%／3.6%。
_FAKE = "本次更新：核心 PCE 3.0%、三月年化 3.6%。"


def spy_invent(key, model, text, system=None, temperature=None, **kw):
    # 抄的是原文裡真實存在的數字，數字鎖定必定放行
    return _FAKE + GOOD[:GOOD.index("重點：")]


r = polish.maybe_polish(headed(), tmp / "d4.json",
                        env={"GEMINI_API_KEY": "g"}, _post=spy_invent)
check("110g 模型自己寫「本次更新」→ 退回組裝版",
      r["source"] == "assembled", r["text"][:40])
check("110h 而且數字鎖定確實攔不住（所以才需要這道檢查）",
      "數字" not in polish.validate(_FAKE + GOOD[:GOOD.index("重點：")] + TAIL,
                                   headed()["text"]))

# 沒有「本次更新」那一句時（非發布日）一切照舊
r = polish.maybe_polish(headed(head=""), tmp / "d5.json",
                        env={"GEMINI_API_KEY": "g"}, _post=spy2)
check("110i 沒有那一句時不受影響",
      r["source"] == "model" and not r["text"].startswith("本次更新"))


# ---------------------------------------------------------------------------
# ⑪c 中文數字寫的「幾方」也要鎖
#
# 數字鎖定只認阿拉伯數字（`_NUM` 是 `\d`），而共識句刻意用中文數字寫，
# 於是那三個數量完全在鎖定範圍外。實際印上畫面的：
#
#     組裝版　…；三方裡**兩方**偏升息、一方偏降息，方向分歧。
#     畫面上　…，三方陣營裡有**一方**偏升息、另一方偏降息，政策方向分歧。
#
# 二比一被寫成一比一——多數變平手，而這是整段的第一個結論。
# 三道防護欄一道都沒作聲，因為裡面沒有任何一個阿拉伯數字。
#
# 這一條**必須雙向比對**：錯的方式是把「兩方」改小成「一方」，
# 也就是**少掉**一個數量，「有沒有多出來」的單向檢查抓不到。
# ---------------------------------------------------------------------------
_SRC_SIDE = "聯準會把通膨擺在前面；三方裡兩方偏升息、一方偏降息，方向分歧。"
_BAD_SIDE = ("聯準會目前把通膨擺在前面，三方陣營裡有一方偏升息、"
             "另一方偏降息，政策方向分歧。")

check("110j 抽得出中文數字寫的方數", polish._sides(_SRC_SIDE) == [1, 2, 3],
      str(polish._sides(_SRC_SIDE)))
check("110k 真實那次的改寫會被抓到",
      polish._sides(_BAD_SIDE) == [1, 1, 3], str(polish._sides(_BAD_SIDE)))
check("110l 而且數字鎖定確實抓不到（所以才需要這一條）",
      polish._numbers(_BAD_SIDE) - polish._numbers(_SRC_SIDE) == set())

# 合理的改寫不能被誤擋——這一條的誤判成本很高（整段退回組裝版）
for _name, _t in [
        ("加了「有」「另」", "三方裡有兩方偏升息、另一方偏降息，方向分歧。"),
        ("換連接詞", "三方之中兩方偏升息，一方偏降息，方向並不一致。"),
        ("整句重組", "方向分歧：偏升息的有兩方，偏降息的一方，共三方。")]:
    check(f"110m 合理改寫不被誤擋（{_name}）",
          polish._sides(_t) == polish._sides(_SRC_SIDE),
          str(polish._sides(_t)))

# 「方向」「方面」就在同一句裡，不排掉會誤判
check("110n 「方向分歧」不算方數", polish._sides("方向分歧") == [])
check("110o 「一方面…另一方面」不算方數",
      polish._sides("一方面通膨仍高，另一方面就業轉弱") == [],
      str(polish._sides("一方面通膨仍高，另一方面就業轉弱")))

# 接到 validate 上：真實那次要被退回，理由要看得懂
_r = polish.validate(_BAD_SIDE + TAIL, _SRC_SIDE + TAIL)
check("110p validate 會擋下來", "方數對不上" in _r, _r)
check("110q 理由印出兩邊的數字，方便對照",
      "[1, 2, 3]" in _r and "[1, 1, 3]" in _r, _r)
# 接上完整的本文才過得了長度護欄——這一項要驗的是方數，不是長度
_OK_SIDE = "三方裡有兩方偏升息、另一方偏降息，方向分歧。" + GOOD[GOOD.index("失業率"):]
check("110r 沒改動就通過",
      polish.validate(_OK_SIDE, _SRC_SIDE + SRC[SRC.index("失業率"):]) == "",
      polish.validate(_OK_SIDE, _SRC_SIDE + SRC[SRC.index("失業率"):]))
check("110s 提示詞也講了（防護欄擋下來之前先讓模型別犯）",
      "中文數字寫的數量也算數字" in polish.SYSTEM)
check("110t 提示詞改版 → 快取失效", polish.PROMPT_VERSION >= 9)


# ---------------------------------------------------------------------------
# ⑫ 截斷：三道防護欄檢查的是「有沒有亂寫」，不是「有沒有寫完」
#
# 實際印上畫面的那一次：
#     …對此 7/29 會議維持不變，有 3 票主張升息，下次會議
# 後面直接沒了。長度 146 字在護欄內、數字全部合法，所以一道都沒攔住。
# 讀者看到的是一句話講到一半的總述，會以為網站壞掉。
# ---------------------------------------------------------------------------
check("111 沒有結尾標點 → 判定截斷",
      polish.looks_truncated("有 3 票主張升息，下次會議"))
check("112 正常結尾 → 不算截斷",
      not polish.looks_truncated("有 3 票主張升息，下次會議在 35 天後。"))
for _tc in "！？」』）.!?":
    check(f"113 「{_tc}」也算完整的結尾",
          not polish.looks_truncated("測試" + _tc))
check("114 空字串不算截斷（那是另一條檢查在管）",
      not polish.looks_truncated("") and not polish.looks_truncated("   "))

# 端到端：模型交出半截的文字 → 不能通過，要重試
half = []


def half_post(key, model, text, system=None, temperature=None, **kw):
    half.append(text)
    if len(half) == 1:
        return "聯準會把通膨擺在前面，內部分歧，下次會議"      # 沒有結尾標點
    return GOOD[:GOOD.index("重點：")]


r = polish.maybe_polish(parted(), tmp / "d3.json",
                        env={"GEMINI_API_KEY": "g"}, _post=half_post)
check("115 截斷的輸出會被擋下並重試", len(half) == 2, f"{len(half)} 次")
check("116 重試後的完整版才會被採用",
      r["source"] == "model" and r["text"].endswith(TAIL), r["source"])

# 兩次都截斷 → 退回組裝版，不能把半截的東西印出去
half2 = []
r = polish.maybe_polish(parted(), tmp / "d4.json",
                        env={"GEMINI_API_KEY": "g"},
                        _post=lambda k, m, t, s=None, tp=None: (
                            half2.append(1), "講到一半就沒了")[1])
check("117 兩次都截斷 → 退回組裝版", r["source"] == "assembled")
check("118 半截的文字不會寫進快取", not (tmp / "d4.json").exists())

# 護欄放寬之後，完整的長版本才進得來
check("119 上限只是防呆，放得很寬", polish.MAX_CJK >= 400)
check("119b config 可以覆寫上限",
      polish._max_cjk({"max_chars": 300}) == 300
      and polish._max_cjk({}) == polish.MAX_CJK
      and polish._max_cjk({"max_chars": "壞掉"}) == polish.MAX_CJK)
check("119c 覆寫值太小會被忽略（不能小於下限）",
      polish._max_cjk({"max_chars": 10}) == polish.MAX_CJK)
check("120 目標下限貼著原長（是改寫不是摘要）",
      polish._target_range("中" * 125, 21)[0] >= 115,
      str(polish._target_range("中" * 125, 21)))


# ---------------------------------------------------------------------------
# ⑬ 推理吃光額度 → 換一個「預設不推理」的模型
#
# 實際發生的完整鏈條：
#   ① BRIEF_MODEL=gemini-flash-latest
#   ② 送 thinkingBudget:0 → 400 INVALID_ARGUMENT（新世代不接受關閉推理）
#   ③ 退回不帶欄位重送 → 推理吃光 8000 token → finishReason=MAX_TOKENS
#   ④ 截斷檢查攔下 → 退回組裝版
# 加大額度沒有用（只是讓它想更久），唯一的解法是換一個預設不開推理的模型。
# ---------------------------------------------------------------------------
AVAIL2 = ["gemini-3.6-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite",
          "gemini-flash-latest", "gemini-flash-lite-latest", "gemini-2.5-pro"]

check("121 截斷後挑明確版本的 lite（不挑別名）",
      polish._gemini_pick(AVAIL2, exclude="gemini-flash-latest",
                          prefer_lite=True) == "gemini-2.5-flash-lite",
      polish._gemini_pick(AVAIL2, exclude="gemini-flash-latest", prefer_lite=True))
check("122 別名排最後（別名指向的正是我們要避開的最新版）",
      polish._gemini_pick(["gemini-flash-lite-latest", "gemini-2.5-flash-lite"],
                          prefer_lite=True) == "gemini-2.5-flash-lite")
check("123 沒有 lite 就退而求其次",
      polish._gemini_pick(["gemini-2.5-flash", "gemini-2.5-pro"],
                          prefer_lite=True) == "gemini-2.5-flash")
check("124 一般情況不受影響（仍偏好較新的 flash）",
      polish._gemini_pick(AVAIL2, exclude="gemini-flash-latest")
      == "gemini-3.6-flash")

# 截斷是專屬例外，才能只針對它換模型
check("125 截斷用專屬例外", issubclass(polish.TruncatedError, RuntimeError))

tried2 = []


def trunc_then_ok(key, model, text, system=None, temperature=None, **kw):
    tried2.append(model)
    if model == "gemini-flash-latest":
        raise polish.TruncatedError("回覆被截斷（finishReason=MAX_TOKENS）")
    return GOOD[:GOOD.index("重點：")]


polish._gemini_call = trunc_then_ok
polish._gemini_models = lambda key: AVAIL2
res = polish._post_gemini("k", "gemini-flash-latest", "本文")
check("126 截斷 → 自動換成不推理的模型重試",
      isinstance(res, tuple) and res[1] == "gemini-2.5-flash-lite", str(res))
check("127 真的試了兩個模型",
      tried2 == ["gemini-flash-latest", "gemini-2.5-flash-lite"], str(tried2))

# 挑不到替代品 → 把原本的截斷錯誤拋出去，不能假裝成功
polish._gemini_models = lambda key: []
try:
    polish._post_gemini("k", "gemini-flash-latest", "本文")
    hit = False
except polish.TruncatedError:
    hit = True
check("128 挑不到替代品 → 拋回原本的錯", hit)


# ---------------------------------------------------------------------------
# ⑭ config/brief.yaml：不必動程式就能調口氣
#
# 使用者的回饋是「潤了跟沒潤一樣」。主因是 temperature 設 0——那幾乎是
# 逐字照抄組裝版。這一段釘住的是「調得動」而且「調了會生效」：
# 語氣要進雜湊，否則改完 config 卻沿用舊快取，畫面完全不變。
# ---------------------------------------------------------------------------
check("129 預設溫度不是 0（0 幾乎等於照抄）",
      polish.DEFAULT_TEMPERATURE > 0, str(polish.DEFAULT_TEMPERATURE))
check("130 自訂語氣會進提示詞",
      "像交易員" in polish._system("中" * 120, 21, {"style": "像交易員的口頭摘要。"}))
check("131 額外指令會進提示詞",
      "第一句就講結論" in polish._system("中" * 120, 21,
                                          {"extra": "第一句就講結論。"}))
check("132 沒設 extra 時用預設（要求重組句子，不要逐句對應）",
      "不要逐句對應原文" in polish._system("中" * 120, 21, {}))
check("133 extra 設成空字串 → 真的不加",
      "其他要求" not in polish._system("中" * 120, 21, {"extra": ""}))

# 溫度要真的傳到供應商那一層
tcalls = []
polish.maybe_polish(parted(), tmp / "e1.json", env={"GEMINI_API_KEY": "g"},
                    cfg={"temperature": 0.7},
                    _post=lambda k, m, t, s=None, tp=None: (
                        tcalls.append(tp), GOOD[:GOOD.index("重點：")])[1])
check("134 溫度傳得到供應商", tcalls == [0.7], str(tcalls))

# enabled: false → 完全不呼叫
r = polish.maybe_polish(parted(), tmp / "e2.json", env={"GEMINI_API_KEY": "g"},
                        cfg={"enabled": False}, _post=boom)
check("135 config 關掉 → 直接用組裝版、不呼叫",
      r["source"] == "assembled")

# 改了語氣 → 快取要失效，否則畫面不會變、使用者以為設定沒生效
c_tone = tmp / "e3.json"
polish.maybe_polish(parted(), c_tone, env={"GEMINI_API_KEY": "g"},
                    cfg={"style": "甲"},
                    _post=lambda k, m, t, s=None, tp=None: GOOD[:GOOD.index("重點：")])
r = polish.maybe_polish(parted(), c_tone, env={"GEMINI_API_KEY": "g"},
                        cfg={"style": "甲"},
                        _post=lambda k, m, t, s=None, tp=None: GOOD[:GOOD.index("重點：")])
check("136 語氣沒變 → 沿用快取", r["source"] == "model-cache")
r = polish.maybe_polish(parted(), c_tone, env={"GEMINI_API_KEY": "g"},
                        cfg={"style": "乙"},
                        _post=lambda k, m, t, s=None, tp=None: GOOD[:GOOD.index("重點：")])
check("137 換語氣 → 快取失效重生成", r["source"] == "model")
r = polish.maybe_polish(parted(), c_tone, env={"GEMINI_API_KEY": "g"},
                        cfg={"style": "乙", "temperature": 0.9},
                        _post=lambda k, m, t, s=None, tp=None: GOOD[:GOOD.index("重點：")])
check("138 換溫度 → 快取也要失效", r["source"] == "model")


# ---------------------------------------------------------------------------
# ⑮ 清單裡有 ≠ 叫得動：退路必須能接著往下走
#
# 實測到的整條鏈：
#   gemini-flash-latest   → 429 兩次（重試接上）→ 推理吃光額度、回覆被截斷
#   → 退路挑 gemini-2.5-flash-lite → **404**（清單裡有，但叫不動）
#   → 沒有第三步 → 整段退回組裝版
# 換過去的模型自己也會失敗，所以退路不能只有一層。
# ---------------------------------------------------------------------------
polish._DEAD.clear()
LIST = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-flash-latest",
        "gemini-flash-lite-latest", "gemini-2.5-flash-lite",
        "gemini-3-flash-preview"]


def http_err(code):
    e = polish.requests.HTTPError(f"{code}")
    e.response = Resp(code)
    return e


seq = []


def chain(key, model, text, system=None, temperature=None, **kw):
    seq.append(model)
    if model == "gemini-flash-latest":
        raise polish.TruncatedError("回覆被截斷（finishReason=MAX_TOKENS）")
    if model == "gemini-2.5-flash-lite":
        raise http_err(404)
    return GOOD[:GOOD.index("重點：")]


polish._gemini_call = chain
polish._gemini_models = lambda key: LIST
res = polish._post_gemini("k", "gemini-flash-latest", "本文")
check("139 截斷 → 換 lite → 那個 404 → 再換一個，最後成功",
      isinstance(res, tuple) and res[1] == "gemini-flash-lite-latest", str(res))
check("140 三個模型依序試過",
      seq == ["gemini-flash-latest", "gemini-2.5-flash-lite",
              "gemini-flash-lite-latest"], str(seq))
check("141 404 的模型被記起來", "gemini-2.5-flash-lite" in polish._DEAD)

# 記起來之後就不會再挑到它
seq2 = []


def chain2(key, model, text, system=None, temperature=None, **kw):
    seq2.append(model)
    if model == "gemini-flash-latest":
        raise polish.TruncatedError("截斷")
    return GOOD[:GOOD.index("重點：")]


polish._gemini_call = chain2
polish._post_gemini("k", "gemini-flash-latest", "本文")
check("142 死掉的模型不再被挑中（省一次額度）",
      "gemini-2.5-flash-lite" not in seq2, str(seq2))

# 換模型救不了的錯要直接往上拋，不能白燒額度
polish._DEAD.clear()
for name, code in [("143 400 不換模型", 400), ("144 401 不換模型", 401),
                   ("145 429 不換模型（限流換誰都一樣）", 429)]:
    calls = []

    def only_once(key, model, text, system=None, temperature=None, _c=calls,
                  _code=code, **kw):
        _c.append(model)
        raise http_err(_code)

    polish._gemini_call = only_once
    try:
        polish._post_gemini("k", "gemini-flash-latest", "本文")
        hit = False
    except polish.requests.HTTPError:
        hit = True
    check(name, hit and len(calls) == 1, f"{len(calls)} 次呼叫")

# 上限：不能無限換下去
polish._DEAD.clear()
many = []


def always_404(key, model, text, system=None, temperature=None, **kw):
    many.append(model)
    raise http_err(404)


polish._gemini_call = always_404
try:
    polish._post_gemini("k", "gemini-flash-latest", "本文")
except polish.requests.HTTPError:
    pass
check("146 換模型有上限", len(many) <= polish.MAX_MODEL_TRIES, f"{len(many)} 次")
polish._DEAD.clear()

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
