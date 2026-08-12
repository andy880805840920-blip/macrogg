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
check("⑦ 太長擋下", polish.validate(GOOD + "多餘的話" * 40, SRC) != "")
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


def fake_post(key, model, text):
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
                        env=env, _post=lambda k, m, t: GOOD.replace("4.1%", "4.4%"))
check("⑱ 事實變了 → 重新生成", r["source"] == "model")

# 模型換了 → 快取失效（雜湊含模型名）
r = polish.maybe_polish(assembled(), cache,
                        env={**env, "BRIEF_MODEL": "claude-x"},
                        _post=lambda k, m, t: GOOD)
check("⑲ 換模型 → 快取失效重生成", r["source"] == "model")

# API 例外 → 組裝版
def boom(key, model, text):
    raise RuntimeError("connection reset")


r = polish.maybe_polish(assembled(SRC + "改一下"), tmp / "c2.json",
                        env=env, _post=boom)
check("⑳ API 掛掉 → 組裝版", r["source"] == "assembled")

# 驗證沒過 → 組裝版、不寫快取
c3 = tmp / "c3.json"
r = polish.maybe_polish(assembled(), c3, env=env,
                        _post=lambda k, m, t: GOOD.replace("83%", "93%"))
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
                        _post=lambda k, m, t2: (gcalls.append((k, m)), GOOD)[1])
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
                    _post=lambda k, m, t2: (mcalls.append(m), GOOD)[1])
check("㉚ BRIEF_MODEL 覆寫生效", mcalls == ["gemini-2.5-pro"], str(mcalls))

# 換供應商 → 快取失效（雜湊含供應商）：同一份事實不能拿 A 家的快取
# 冒充 B 家的結果——兩家的文風不同，換供應商本來就該重生
c6 = tmp / "c6.json"
polish.maybe_polish(assembled(), c6, env={"GEMINI_API_KEY": "g1"},
                    _post=lambda k, m, t2: GOOD)
r = polish.maybe_polish(assembled(), c6, env={"ANTHROPIC_API_KEY": "a1"},
                        _post=lambda k, m, t2: GOOD)
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


def fake_call(key, model, text):
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
                        _post=lambda k, m, t: (GOOD, "gemini-3.6-flash"))
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
def boom500(key, model, text):
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


def flaky(key, model, text):
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
                        _post=lambda k, m, t: (seq2.append(t), BAD)[1])
check("㊽ 重試後仍沒過 → 組裝版", r["source"] == "assembled")
check("㊾ 重試只有一次（共兩個呼叫）", len(seq2) == 2, f"{len(seq2)} 次")
check("㊿ 壞結果沒有寫進快取", not (tmp / "c9.json").exists())

# 重試那一次拋例外 → 一樣安全退回組裝版
seq3 = []


def then_boom(key, model, text):
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
                        _post=lambda k, m, t: GOOD.replace("重點：", "**重點**："))
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
check("75 gemini-3.x 用 thinkingLevel",
      polish._thinking("gemini-3.6-flash") == {"thinkingLevel": "minimal"})
check("76 認不出版本就不送（靠額度撐）",
      polish._thinking("gemini-flash-latest") == {})
check("77 輸出額度夠大，不會被推理吃光", polish.MAX_OUT >= 2000)

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
