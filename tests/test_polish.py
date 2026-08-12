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

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
