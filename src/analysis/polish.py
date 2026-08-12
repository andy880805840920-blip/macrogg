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
    # 供應商可以回 (文字, 實際用的模型)：Gemini 在模型被汰換時會自己換一個，
    # 而畫面與執行紀錄要標的是**真的用了哪一個**，不是設定裡寫的那一個。
    #
    # 驗證沒過時**帶著原因重試一次**。實際發生過：換上的替代模型把
    # 「重點：」前綴弄丟了——格式錯誤跟 API 掛掉不一樣，模型看得懂
    # 「你上次錯在哪」，再講一次通常就對了。只重試一次：兩次都做不到
    # 就是這個模型做不到，繼續燒額度不會變出第三種結果。
    # 防護欄本身一個字都沒鬆——不合格照樣退組裝版。
    post = _post or _POST[provider]
    reason = ""
    text = ""
    for attempt in (1, 2):
        note = ("" if not reason else
                f"\n\n（上一次的輸出被退回，原因：{reason}。"
                f"請重新改寫並逐條遵守硬性規則——"
                f"特別注意最後一句必須以「重點：」開頭、"
                f"不得新增任何原文沒有的數字。）")
        try:
            res = post(key, model, out["text"] + note)
        except Exception as e:                     # noqa: BLE001
            log.warning("整體情勢潤稿失敗（%s），改用組裝版", e)
            return out
        if isinstance(res, tuple):
            res, model = res[0], (res[1] or model)
        text = " ".join((res or "").split())
        reason = validate(text, out["text"])
        if not reason:
            break
        if attempt == 1:
            log.warning("整體情勢潤稿未通過驗證（%s），帶著原因重試一次", reason)
    if reason:
        log.warning("整體情勢潤稿重試後仍未通過驗證（%s），改用組裝版", reason)
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


GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

# 挑替代模型時要避開的：這些是別種用途的模型，名字裡有 gemini 但不會改寫文字。
_AVOID = ("embedding", "aqa", "image", "vision", "tts", "audio", "live",
          "translate", "veo", "imagen", "omni", "learnlm")
_VER = re.compile(r"gemini-(\d+(?:\.\d+)?)")


def _family(low: str) -> int:
    """
    用途分組，數字小的優先：flash → flash-lite → pro → 其他。

    順序的理由是**失敗方式**，不是價格。這個任務有硬性格式要求
    （長度、不准新增數字、結尾必須是「重點：」），做不到就被 validate 擋下，
    畫面退回組裝版——也就是使用者現在看到的那個結果。所以寧可用
    正常的 flash 而不是 lite。pro 排最後是因為免費額度最緊，
    而這裡只是改寫 150 個字，用不到。

    分組要明寫不能用子字串比對：「flash」是「flash-lite」的子字串，
    照順序找第一個命中的話，flash-lite 會被歸成 flash。
    """
    if "flash-lite" in low:
        return 1
    if "flash" in low:
        return 0
    if "pro" in low:
        return 2
    return 3


def _gemini_models(key: str) -> list[str]:
    """
    問這把金鑰**實際上**能用哪些模型。回傳去掉 "models/" 前綴的名稱。

    這支存在的理由：Google 會汰換模型，而汰換掉的模型回的是 404
    「models/X is not found for API version v1beta」——那個訊息看起來
    像是網址寫錯，實際上是「你這把金鑰沒有這個模型」。差別很重要，
    因為前者要改程式、後者只要換個模型名。
    """
    try:
        r = requests.get(f"{GEMINI_BASE}/models", timeout=TIMEOUT,
                         headers={"x-goog-api-key": key})
        r.raise_for_status()
        out = []
        for m in (r.json().get("models") or []):
            name = (m.get("name") or "").split("/")[-1]
            if name and "generateContent" in (m.get("supportedGenerationMethods")
                                              or []):
                out.append(name)
        return out
    except Exception as e:                         # noqa: BLE001
        log.warning("查詢可用模型失敗（%s）", e)
        return []


def _gemini_pick(names: list[str], exclude: str = "") -> str:
    """
    從可用清單裡挑一個來改寫。挑不到就回空字串（呼叫端會退回組裝版）。

    排序：先照用途分組（見 _family），同組內正式版優先於 preview，
    再來版本號大的優先。**不做語意判斷**——這裡只是在幾個等價的
    選項裡挑一個，挑錯了也只是文風差一點，數字仍然被防護欄鎖著。
    """
    def rank(n: str):
        low = n.lower()
        ver = _VER.search(low)
        return (_family(low), 1 if "preview" in low or "exp" in low else 0,
                -float(ver.group(1)) if ver else 0.0, n)

    cands = [n for n in names
             if n.lower().startswith("gemini")
             and n != exclude
             and not any(a in n.lower() for a in _AVOID)]
    return sorted(cands, key=rank)[0] if cands else ""


def _gemini_call(key: str, model: str, source_text: str) -> str:
    # 金鑰放 header 不放網址：放網址會跟著出現在錯誤訊息與代理的存取紀錄裡。
    cfg = {"temperature": 0, "maxOutputTokens": 800}
    # thinkingBudget 設 0：這種改寫不需要推理鏈，關掉比較快也比較省額度。
    # 只對 gemini-2.x 送——這個欄位在後續世代改過形狀，送過去會被擋成 400。
    # 沒送也只是慢一點，不影響結果。
    if model.startswith("gemini-2"):
        cfg["thinkingConfig"] = {"thinkingBudget": 0}
    r = requests.post(
        f"{GEMINI_BASE}/models/{model}:generateContent",
        timeout=TIMEOUT, headers={
            "x-goog-api-key": key,
            "content-type": "application/json",
        }, json={
            "system_instruction": {"parts": [{"text": SYSTEM}]},
            "contents": [{"role": "user",
                          "parts": [{"text": source_text}]}],
            "generationConfig": cfg,
        })
    r.raise_for_status()
    parts = r.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts)


def _post_gemini(key: str, model: str, source_text: str):
    """
    回傳改寫後的文字，或 (文字, 實際用的模型)。

    404 代表「這把金鑰沒有這個模型」，不是網址寫錯。模型會被汰換，
    而汰換掉的那天這一區會安靜地消失——所以這裡自己問一次可用清單、
    換一個再試，並把清單寫進執行紀錄，讓下次要設 BRIEF_MODEL 時
    有名字可以抄，不必去猜。
    """
    try:
        return _gemini_call(key, model, source_text)
    except requests.HTTPError as e:
        resp = getattr(e, "response", None)
        if resp is None or resp.status_code != 404:
            raise
        names = _gemini_models(key)
        if not names:
            raise
        alt = _gemini_pick(names, exclude=model)
        log.warning("Gemini 沒有 %s 這個模型。這把金鑰可用的有：%s",
                    model, "、".join(names[:12]) + ("…" if len(names) > 12 else ""))
        if not alt:
            raise
        log.warning("改用 %s 重試（要固定的話把 BRIEF_MODEL 設成想用的名字）", alt)
        return _gemini_call(key, alt, source_text), alt


_POST = {"gemini": _post_gemini, "anthropic": _post_anthropic}
