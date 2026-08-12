"""
整體總述的模型潤稿層：把 brief.py 組裝出來的段落交給模型改寫得通順。

這有沒有違反「不用模型」的原則
------------------------------
沒有——README 的設計原則本來就寫著：「量化與判定走確定性規則，不交給模型。
**模型的角色留到 P4，只負責讀規則結果寫敘述。**」這一層就是那個 P4：
所有數字、方向、結論都由規則引擎決定好了，模型**只改寫措辭**。
它不做任何判斷，做了也會被防護欄擋下來。

三道防護欄（任何一道失敗 → 直接用組裝版）
------------------------------------------
① **數字鎖定**：輸出裡的每一個數字都必須出現在組裝版裡，一個新數字都
   不准有。模型可以把「撐不住現有失業率」講得更順，但 4.1%、+2.0 萬、
   83% 這些只能原樣搬。這是機械檢查（validate()），不是「相信它不會亂寫」。
   重點句的「重點：」前綴也必須保留——畫面靠它把結尾拆成獨立一行。

② **事實沒變就不重新生成**：五段事實做雜湊存在 state/brief.json，
   沒變就沿用上次的文字。這同時解決兩件事：非發布日不會出現
   「數字一樣、講法卻每天漂」的詭異現象；API 呼叫降到每月幾次
   （事實只在數據發布、FOMC 會議、季報時才變）。

③ **失敗退回**：API 掛了、驗證沒過、沒設金鑰、離線模式——
   一律用組裝版。組裝版不是殘骸，是升級過的保底（轉折詞＋重點句都有）。

啟用方式
--------
GitHub repo → Settings → Secrets → 新增下列**其中一把**金鑰：

    GEMINI_API_KEY      Google AI Studio 的金鑰（有免費額度），用 Gemini
    ANTHROPIC_API_KEY   Anthropic 的金鑰，用 Claude Haiku

兩把都設時優先用 Gemini（免費）。沒設就永遠走組裝版，什麼都不會壞。
模型可用環境變數 `BRIEF_MODEL` 覆寫。事實沒變不重新生成，
所以就算用付費金鑰，一個月的費用也以分計。

金鑰**只能放 GitHub Secrets**，不要貼進對話、不要寫進任何檔案——
貼出去的金鑰一律視同外流，要重新產生。
"""

from __future__ import annotations

import os
import re
import json
import logging

import requests

from .. import clock
from .brief import cjk_len, MIN_CJK, MAX_CJK

log = logging.getLogger(__name__)

TIMEOUT = 45

# 提示詞改版時要讓快取失效，否則舊快取會一直蓋住新行為
PROMPT_VERSION = 1

SYSTEM = (
    "你是財經媒體的資深編輯。使用者會給你一段由程式組裝的美國總經情勢總述。"
    "把它改寫成一段連貫、自然的繁體中文散文，語氣像法人晨會的口頭摘要——"
    "專業但不堆術語，句與句之間要有自然的承接。\n"
    "硬性規則：\n"
    "1. 不得新增、刪除或改動任何數字與百分比。輸出中的每個數字都必須"
    "出現在原文裡。\n"
    "2. 不得加入原文沒有的事實、預測或建議；每段事實的方向與結論不得改變。\n"
    "3. 長度 140 到 170 個中文字。\n"
    "4. 最後一句必須以「重點：」開頭，內容沿用原文的重點句"
    "（語氣可以改，意思不可以改）。\n"
    "5. 輸出純文字一段：不用列點、不用 markdown、不用換行。\n"
    "只輸出改寫後的文字，不要任何說明。"
)

_NUM = re.compile(r"\d+(?:\.\d+)?")


def _numbers(s: str) -> set[str]:
    return set(_NUM.findall((s or "").replace(",", "")))


def validate(out: str, source: str) -> str:
    """
    防護欄一。回傳空字串＝通過；否則回傳失敗原因（進執行紀錄）。

    只驗「機械上可驗的」：數字、長度、格式。方向與語意靠兩件事保護——
    數字鎖定（方向反了通常伴隨數字亂配）與重點句強制保留（結論由規則層
    寫死在裡面）。不假裝能驗語意。
    """
    if not out or not out.strip():
        return "輸出是空的"
    if "**" in out or "#" in out or "\n" in out:
        return "輸出含 markdown 或換行"
    extra = _numbers(out) - _numbers(source)
    if extra:
        return f"出現原文沒有的數字：{sorted(extra)}"
    if "重點：" not in out:
        return "重點句的前綴不見了"
    n = cjk_len(out)
    if not (MIN_CJK <= n <= MAX_CJK):
        return f"長度 {n} 字，超出 {MIN_CJK}–{MAX_CJK}"
    return ""


def _hash(parts: list, model: str) -> str:
    import hashlib
    payload = json.dumps([p["text"] for p in parts]
                         + [model, PROMPT_VERSION],
                         ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_cache(path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:                              # noqa: BLE001
        return {}


# 支援的供應商。兩把金鑰都設時照這個順序取——Gemini 排前面因為有免費額度。
# 「用哪一家」是使用者設金鑰時的選擇，不是程式的判斷。
PROVIDER_ORDER = ("gemini", "anthropic")
PROVIDERS = {
    "gemini": {
        "env": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "model": "gemini-2.5-flash",
    },
    "anthropic": {
        "env": ("ANTHROPIC_API_KEY",),
        "model": "claude-haiku-4-5",
    },
}


def _pick_provider(env) -> tuple[str, str]:
    """回傳 (供應商, 金鑰)；沒有任何金鑰時回 ("", "")。"""
    for name in PROVIDER_ORDER:
        for var in PROVIDERS[name]["env"]:
            key = (env.get(var) or "").strip()
            if key:
                return name, key
    return "", ""


def maybe_polish(assembled: dict, cache_path, offline: bool = False,
                 env: dict | None = None,
                 _post=None) -> dict:
    """
    回傳 {"text", "chars", "source", "model"}，
    source ∈ model / model-cache / assembled。

    env 與 _post 參數是給測試用的（不碰真的環境變數、不打真的 API）。
    """
    env = os.environ if env is None else env
    out = {"text": assembled.get("text", ""),
           "chars": assembled.get("chars", 0),
           "source": "assembled", "model": ""}
    if not out["text"]:
        return out

    provider, key = _pick_provider(env)
    model = ((env.get("BRIEF_MODEL") or "").strip()
             or (PROVIDERS[provider]["model"] if provider else ""))
    parts = assembled.get("parts") or []
    facts_h = _hash(parts, "")                     # 只看事實
    h = _hash(parts, f"{provider}:{model}")        # 事實＋供應商＋模型

    # ---- 防護欄二：事實沒變就沿用 ----
    # 兩層命中條件：
    #   ① 事實、供應商、模型都沒變 → 沿用（正常情況）
    #   ② 金鑰失效或被拿掉、但事實沒變 → 也沿用。這時沒有能力重生，
    #      而快取的文字仍然對應目前的事實——跳回組裝版只是讓畫面
    #      無故變粗糙。換了供應商或模型（有金鑰）則不適用，要重生。
    cache = _load_cache(cache_path)
    if cache.get("text") and (
            cache.get("hash") == h
            or (not key and cache.get("facts") == facts_h)):
        return {"text": cache["text"], "chars": cjk_len(cache["text"]),
                "source": "model-cache", "model": cache.get("model", model)}

    if offline or not key:
        return out

    # ---- 呼叫 ----
    try:
        post = _post or _POST[provider]
        text = post(key, model, out["text"])
    except Exception as e:                         # noqa: BLE001
        log.warning("整體情勢潤稿失敗（%s），改用組裝版", e)
        return out

    text = " ".join((text or "").split())
    reason = validate(text, out["text"])
    if reason:
        log.warning("整體情勢潤稿未通過驗證（%s），改用組裝版", reason)
        return out

    # ---- 存快取（state/ 由 workflow commit，跨執行有效）----
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(
            {"hash": h, "facts": facts_h, "text": text, "model": model,
             "at": clock.iso()},
            ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:                         # noqa: BLE001
        log.warning("整體情勢快取寫入失敗（%s），本次結果仍使用", e)
    return {"text": text, "chars": cjk_len(text), "source": "model",
            "model": model}


def _post_anthropic(key: str, model: str, source_text: str) -> str:
    r = requests.post("https://api.anthropic.com/v1/messages",
                      timeout=TIMEOUT, headers={
                          "x-api-key": key,
                          "anthropic-version": "2023-06-01",
                          "content-type": "application/json",
                      }, json={
                          "model": model,
                          "max_tokens": 500,
                          "temperature": 0,
                          "system": SYSTEM,
                          "messages": [{"role": "user",
                                        "content": source_text}],
                      })
    r.raise_for_status()
    return r.json()["content"][0]["text"]


def _post_gemini(key: str, model: str, source_text: str) -> str:
    # 金鑰放 header 不放網址：放網址會跟著出現在錯誤訊息與代理的存取紀錄裡。
    # thinkingBudget 設 0：這種改寫不需要推理鏈，關掉比較快也比較省額度。
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent",
        timeout=TIMEOUT, headers={
            "x-goog-api-key": key,
            "content-type": "application/json",
        }, json={
            "system_instruction": {"parts": [{"text": SYSTEM}]},
            "contents": [{"role": "user",
                          "parts": [{"text": source_text}]}],
            "generationConfig": {"temperature": 0,
                                 "maxOutputTokens": 800,
                                 "thinkingConfig": {"thinkingBudget": 0}},
        })
    r.raise_for_status()
    parts = r.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts)


_POST = {"gemini": _post_gemini, "anthropic": _post_anthropic}
