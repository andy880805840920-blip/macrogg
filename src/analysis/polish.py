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

# 輸出額度。這段文字本身只要 300 token 上下，但**推理用掉的 token 也算在
# 這個上限裡**——額度給太緊，推理模型會把它花光然後回一個空字串
#（finishReason: MAX_TOKENS）。給寬一點不會多花錢：計費看實際用量，
# 不看上限。先前設 800，正好落在會被推理吃光的區間。
MAX_OUT = 4000

# 提示詞改版時要讓快取失效，否則舊快取會一直蓋住新行為
PROMPT_VERSION = 3


def _target_range(source: str) -> tuple[int, int]:
    """
    要求的字數範圍，**由這一次的組裝版長度算出來**，不是寫死的。

    先前寫死「140 到 170」，但組裝版實際長度會隨資料變（實測 179–180 字）。
    等於一邊要求模型壓掉 20% 的字、一邊又用 190 的上限去驗——模型照做會
    偏短、不照做就頂到上限。兩種都可能被擋，而且原因完全不同。

    改成貼著實際長度給範圍，並在兩端都留 10 字的緩衝，
    讓「照著做」跟「通過驗證」變成同一件事。
    """
    n = cjk_len(source)
    lo = max(MIN_CJK + 10, n - 25)
    hi = min(MAX_CJK - 10, n + 10)
    if hi <= lo:                                   # 極端情況下不要給出反向區間
        lo, hi = MIN_CJK + 10, MAX_CJK - 10
    return lo, hi


def _system(source: str) -> str:
    lo, hi = _target_range(source)
    return (
        "你是財經媒體的資深編輯。使用者會給你一段由程式組裝的美國總經情勢總述。"
        "把它改寫成一段連貫、自然的繁體中文散文，語氣像法人晨會的口頭摘要——"
        "專業但不堆術語，句與句之間要有自然的承接。\n"
        "硬性規則：\n"
        "1. 不得新增、刪除或改動任何數字與百分比。輸出中的每個數字都必須"
        "出現在原文裡。特別注意：不要自己換算、不要補上年份或期數、"
        "不要寫「約兩週」這類原文沒有的量。\n"
        "2. 不得加入原文沒有的事實、預測或建議；每段事實的方向與結論不得改變。\n"
        f"3. 長度大約 {lo} 到 {hi} 個中文字。這是**寬鬆的參考**，"
        "不要逐字計數、不要在輸出裡標註字數或字元位置、"
        "也不要提到這個範圍本身。\n"
        "4. 最後一句必須以「重點：」開頭（全形冒號），內容沿用原文的重點句"
        "（語氣可以改，意思不可以改）。\n"
        "5. 輸出純文字一段：不用列點、不用 markdown、不用換行、"
        "不要有括號編號或任何註記。\n"
        "6. 直接輸出改寫後的文字，開頭不要有「以下是」「好的」這類引言，"
        "結尾不要有任何說明。"
    )


# 舊名稱保留給既有呼叫端與測試；內容與 _system("") 等價。
SYSTEM = _system("")

_NUM = re.compile(r"\d+(?:\.\d+)?")

# 純排版記號。這些在中文總經散文裡沒有任何正當用途，出現就是模型的
# 排版習慣，直接拿掉。分兩組是因為**去掉的方式不一樣**：
#   記號本身要換成空字串——換成空格的話「**重點**：」會變成「重點 ：」，
#   「重點：」就不見了，反而觸發另一條檢查。
#   清單項目符號連同後面的空白一起去掉。
_MD_CHARS = re.compile(r"[*#`_~]")
_MD_LIST = re.compile(r"^[ \t]*(?:[-•]|\d+[.)])[ \t]+", re.M)
_MD = re.compile(r"[*#`_~]|^[ \t]*(?:[-•]|\d+[.)])[ \t]+", re.M)

# 全形數字與百分號 → 半形。只動這幾個字元：全形空格與間隔號是全站的
# 排版慣例，動了會讓這一段跟其他地方長得不一樣。
_WIDE = str.maketrans("０１２３４５６７８９％．", "0123456789%.")
# 「重點」後面接任何冒號（含半形、含中間夾空白）一律收斂成全形
_LEAD_COLON = re.compile(r"重點\s*[:：]\s*")

# 括號裡只有一個數字、沒有單位——例如「核(78)心(79)」。
# 這是模型逐字標字元位置留下的東西，不是內容。
_BARE_PAREN_NUM = re.compile(r"[(（]\s*\d{1,4}\s*[)）]")
# 至少要出現這麼多次才動手。真正的散文偶爾會有「（3 票）」這種寫法，
# 但不會連續出現三個「只有數字、沒有任何單位」的括號——
# 門檻擋住的就是那個差別，寧可少清也不要誤刪內容。
_ANNOT_MIN = 3


def _numbers(s: str) -> set[str]:
    """
    抽出文字裡的數字，**正規化成數值**再比對。

    為什麼不能比字串：組裝版寫「+2.0 萬」，模型改寫成「+2 萬」——
    意思完全一樣，字串卻不同，於是「2」被判成「原文沒有的數字」而整段退回。
    實際發生過，而且退回的理由聽起來很嚴重（像模型亂編數字），
    其實只是把尾數的零省掉。

    正規化成 float 之後，「2」與「2.0」收斂成同一個，
    但「4.1」與「4.2」仍然是兩個——鎖定的嚴格程度一點都沒有放寬。
    """
    out = set()
    for tok in _NUM.findall((s or "").replace(",", "")):
        try:
            out.add(repr(float(tok)))
        except ValueError:                         # noqa: PERF203
            out.add(tok)
    return out


def _sanitize(out: str) -> str:
    """
    機械清理：拿掉純排版記號、把所有空白折成單一空格。

    這不是放寬防護欄，是分清楚**排版**與**內容**。星號與井號是模型的
    排版習慣，拿掉不會改變任何一個字的意思——就像編輯把手稿上的
    底線畫掉。數字、方向、結論仍然由 validate() 一字不差地鎖著。

    先前這裡是「看到 ** 就整段退回」。結果是模型只要把「重點」加粗，
    一整段合格的改寫就被丟掉，畫面退回組裝版——為了一個星號。

    另外兩種也是純打字習慣、一律就地修正：

    ① **全形數字**。「４.１%」跟「4.1%」是同一個數字，但正規表達式抓不到
       全形的，於是原文的數字看起來「消失了」（不會被擋，因為少數字是允許的），
       畫面上卻出現一串跟全站其他地方不一樣的數字。

    ② **半形冒號**。「重點:」跟「重點：」意思一樣，但檢查的是全形那個，
       模型打成半形就會被判成「重點句的前綴不見了」——最沒有意義的一種退回。

    ③ **逐字的字元編號**。實際收到過這種輸出：

           ，(77)核(78)心(79) PCE(82) 3.3%(86)、(87)三(88)月(89)化(91)…

       模型被字數要求逼著「數出聲音來」，把字元位置一個一個標進正文。
       這會一次觸發兩件事：畫面上全是括號數字，而且那些數字全部被
       數字鎖定判成「原文沒有的數字」。清掉它們才看得出底下的散文
       其實是好的。門檻是 _ANNOT_MIN，避免誤刪真正的括號內容。
    """
    s = _MD_LIST.sub("", out or "")
    s = _MD_CHARS.sub("", s)
    s = s.translate(_WIDE)
    if len(_BARE_PAREN_NUM.findall(s)) >= _ANNOT_MIN:
        s = _BARE_PAREN_NUM.sub("", s)
    s = _LEAD_COLON.sub("重點：", s)
    return " ".join(s.split())


def validate(out: str, source: str) -> str:
    """
    防護欄一。回傳空字串＝通過；否則回傳失敗原因（進執行紀錄）。

    只驗「機械上可驗的」：數字、長度、格式。方向與語意靠兩件事保護——
    數字鎖定（方向反了通常伴隨數字亂配）與重點句強制保留（結論由規則層
    寫死在裡面）。不假裝能驗語意。

    輸入預期已經過 _sanitize()。這裡仍然把排版記號與換行列為失敗，
    當作清理沒做到的後備防線——真的漏到畫面上會很難看。
    """
    if not out or not out.strip():
        return "輸出是空的"
    if _MD.search(out) or "\n" in out:
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
        text = _sanitize(res)
        reason = validate(text, out["text"])
        if not reason:
            break
        if attempt == 1:
            log.warning("整體情勢潤稿未通過驗證（%s），帶著原因重試一次", reason)
    if reason:
        # 把被退回的文字也印出來：光看理由分不出「模型真的寫錯」與
        # 「檢查太嚴」。前 60 個字通常就夠判斷了，而且這段本來就是
        # 要印在首頁上的文字，沒有外洩疑慮。
        log.warning("整體情勢潤稿重試後仍未通過驗證（%s），改用組裝版；"
                    "被退回的開頭是「%s…」", reason, text[:60])
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
                          "max_tokens": MAX_OUT,
                          "temperature": 0,
                          "system": _system(source_text),
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


def _thinking(model: str) -> dict:
    """
    這一次呼叫要怎麼關掉推理鏈。回傳要併進 generationConfig 的欄位。

    為什麼一定要關：**推理用掉的 token 算在 maxOutputTokens 裡**。
    推理模型如果把額度花在想，回來的 candidate 會是
    `finishReason: MAX_TOKENS` 而且**一個字都沒有**——不是報錯，是空字串。
    這種失敗最難查，因為看起來像模型「不想回答」。

    2.x 用 thinkingConfig.thinkingBudget（0 ＝ 關），實測有效。

    3.x 以後**不送任何欄位**。文件上寫的是 thinking_level，但 v1beta 的
    generateContent 實際回的是：

        400 Invalid JSON payload received.
        Unknown name "thinkingLevel" at 'generation_config'

    camelCase 與 snake_case 在 proto JSON 是等價的，所以這不是大小寫問題，
    是這個 API 版本根本沒有這個欄位。既然關不掉，就改用 MAX_OUT 給足額度
    讓推理跟輸出都放得下——那才是真正在防「回一個空字串」的那道保險。
    每次都先送一次註定失敗的 400 只是白花一個來回。
    """
    m = _VER.search(model.lower())
    if not m or float(m.group(1)) >= 3:
        return {}
    return {"thinkingConfig": {"thinkingBudget": 0}}


def _gemini_call(key: str, model: str, source_text: str,
                 think: bool = True) -> str:
    # 金鑰放 header 不放網址：放網址會跟著出現在錯誤訊息與代理的存取紀錄裡。
    cfg = {"temperature": 0, "maxOutputTokens": MAX_OUT}
    if think:
        cfg.update(_thinking(model))
    r = requests.post(
        f"{GEMINI_BASE}/models/{model}:generateContent",
        timeout=TIMEOUT, headers={
            "x-goog-api-key": key,
            "content-type": "application/json",
        }, json={
            "system_instruction": {"parts": [{"text": _system(source_text)}]},
            "contents": [{"role": "user",
                          "parts": [{"text": source_text}]}],
            "generationConfig": cfg,
        })
    # 400 有可能是推理欄位的名稱又改了。這種情況再送一次、不帶那個欄位——
    # 欄位名稱是 Google 的實作細節，不該讓整區因此消失。
    if r.status_code == 400 and think and _thinking(model):
        log.warning("Gemini 退回設定（%s），改成不指定推理層級再試一次",
                    r.text[:120])
        return _gemini_call(key, model, source_text, think=False)
    r.raise_for_status()

    js = r.json()
    cands = js.get("candidates") or []
    if not cands:
        # 沒有 candidate 通常是提示詞被安全過濾擋下，理由在 promptFeedback
        raise RuntimeError(f"沒有回覆內容（{js.get('promptFeedback')}）")
    parts = ((cands[0].get("content") or {}).get("parts")) or []
    text = "".join(p.get("text", "") for p in parts)
    if not text.strip():
        # 講清楚是哪一種空：MAX_TOKENS 代表額度被推理吃光，
        # SAFETY 代表內容被擋。兩者的處置完全不同。
        raise RuntimeError(
            f"回覆是空的（finishReason={cands[0].get('finishReason')}）")
    return text


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
