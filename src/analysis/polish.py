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
import time
import logging

import requests

from .. import clock
from .brief import cjk_len, MIN_CJK, MAX_CJK

log = logging.getLogger(__name__)

TIMEOUT = 45

# ---------------------------------------------------------------------------
# 暫時性失敗要重試
#
# 實際發生過：模型伺服器回 503 Service Unavailable，整段總述就退回組裝版。
# 這種錯跟「模型不存在」（404）或「參數寫錯」（400）完全不同——它跟我們送
# 什麼無關，過幾秒再送一次多半就成功了。不重試等於讓一次幾秒的伺服器抖動
# 決定首頁那一段的樣子。
#
# 只重試這幾個狀態碼：
#   429  被限流（免費額度的尖峰時段很常見）
#   500 / 502 / 503 / 504  伺服器端的暫時故障
# 其餘一律不重試——400／401／403／404 再送幾次都是同樣的結果，
# 只是白花額度。
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_TRIES = 3
# 退避秒數。刻意短：這是每天跑一次的排程，不值得為了一段選配的敘述
# 卡住整個 workflow；三次試完還是不行就用組裝版，明天再說。
BACKOFF = (3, 9)
# 429 會帶 Retry-After。照它給的等，但設上限——伺服器偶爾會回幾百秒，
# 那已經超過「值得為這一段等」的範圍了。
RETRY_AFTER_MAX = 30

# 測試用的注入點：不要真的睡。
_SLEEP = time.sleep


class TruncatedError(RuntimeError):
    """
    回覆寫到一半就斷了（推理吃光了輸出額度）。

    要跟其他失敗分開，因為它的處置完全不同：這不是「再試一次就會好」，
    而是「這個模型在這個額度下寫不完」——唯一有效的處置是換一個
    預設不開推理的模型。用一般的 RuntimeError 就沒辦法只針對它動作。
    """

# 輸出額度。這段文字本身只要 300 token 上下，但**推理用掉的 token 也算在
# 這個上限裡**——額度給太緊，推理模型會把它花光然後回一個空字串
#（finishReason: MAX_TOKENS）。給寬一點不會多花錢：計費看實際用量，
# 不看上限。先前設 800，正好落在會被推理吃光的區間。
MAX_OUT = 8000

# 2.5 Pro 的推理**關不掉**：thinkingBudget 的合法值是 128–32768 或 -1，
# 送 0 會回 400。送最小值 128 —— 合法、而且把 MAX_OUT 幾乎整份留給文字。
PRO_MIN_THINKING = 128

# 提示詞改版時要讓快取失效，否則舊快取會一直蓋住新行為
PROMPT_VERSION = 9


def _max_cjk(cfg: dict | None = None) -> int:
    """字數上限。config/brief.yaml 可覆寫；那裡是防呆值不是編輯限制。"""
    try:
        v = int((cfg or {}).get("max_chars") or 0)
    except (TypeError, ValueError):
        v = 0
    return v if v > MIN_CJK else MAX_CJK


def _target_range(source: str, reserve: int = 0,
                  cap: int | None = None) -> tuple[int, int]:
    """
    要求的字數範圍，**由這一次要改寫的段落長度算出來**，不是寫死的。

    先前寫死「140 到 170」，但組裝版實際長度會隨資料變（實測 179–180 字）。
    等於一邊要求模型壓掉 20% 的字、一邊又用 190 的上限去驗——模型照做會
    偏短、不照做就頂到上限。兩種都可能被擋，而且原因完全不同。

    `reserve` 是**不交給模型、但會接回去**的那一段（重點句）的長度。
    上限要先把它扣掉，否則模型寫到剛好合格、接上重點句之後就超出護欄——
    實際發生過：模型交出 206 字，退回的理由是長度，它第二次為了縮短
    就把重點句整句刪掉了。
    """
    n = cjk_len(source)
    top = cap if cap is not None else MAX_CJK
    # 下限貼著原長（-10）：這一段的工作是**改寫**不是**摘要**，
    # 少於原長就代表有事實被丟掉。上限給 +45 的餘裕，讓句子有空間寫順。
    lo = max(MIN_CJK - reserve, n - 10)
    hi = min(top - reserve - 5, n + 45)
    if hi <= lo:                                   # 極端情況下不要給出反向區間
        lo, hi = max(1, MIN_CJK - reserve), max(2, top - reserve - 5)
    return lo, hi


# 語氣與額外指令的預設值。config/brief.yaml 可以覆寫——
# 那個檔案存在的理由就是「不必動程式就能調口氣」。
DEFAULT_STYLE = ("語氣像法人晨會的口頭摘要——專業但不堆術語，"
                 "句與句之間要有自然的承接。")
DEFAULT_EXTRA = ("不要逐句對應原文：可以合併句子、調換順序、改變斷句方式，"
                 "讓整段讀起來像一氣呵成寫出來的，而不是把幾段話接在一起。")
# 取樣溫度。0 幾乎是逐字照抄，也就是「潤了跟沒潤一樣」的主因；
# 往上調會重新斷句與重組結構。調高的代價只是偶爾被防護欄擋下重試，
# 不是錯誤的數字——數字鎖定是機械檢查，跟溫度無關。
DEFAULT_TEMPERATURE = 0.45


def _system(source: str, reserve: int = 0, cfg: dict | None = None) -> str:
    lo, hi = _target_range(source, reserve, _max_cjk(cfg))
    cfg = cfg or {}
    style = (cfg.get("style") or DEFAULT_STYLE).strip()
    extra = (cfg.get("extra") or "").strip()
    if cfg.get("extra") is None:                   # 完全沒設定才用預設
        extra = DEFAULT_EXTRA
    return (
        "你是財經媒體的資深編輯。使用者會給你一段由程式組裝的美國總經情勢總述。"
        f"把它改寫成一段連貫、自然的繁體中文散文。{style}\n"
        "硬性規則：\n"
        "1. 不得新增、刪除或改動任何數字與百分比。輸出中的每個數字都必須"
        "出現在原文裡。特別注意：不要自己換算、不要補上年份或期數、"
        "不要寫「約兩週」這類原文沒有的量。**用中文數字寫的數量也算數字**"
        "——「三方裡兩方偏升息、一方偏降息」的「三／兩／一」不可改動，"
        "尤其不要把「兩方」寫成「一方」或「另一方」，那會把多數變成平手。\n"
        "2. 不得加入原文沒有的事實、預測或建議；每段事實的方向與結論不得改變。\n"
        # 先前這裡有一條 2c：「開頭若有『本次更新：…』那一句，保留在最前面
        # 且不得改動任何數字」。拿掉了——那句話現在根本不會出現在模型看到的
        # 原文裡（見 maybe_polish 的說明）。留著只會讓模型以為自己該寫一句。
        "2c. 這段話前面可能會再接一句由程式產生的「本次更新：…」新數據摘要，"
        "**你不必也不要自己寫那一句**，也不要在開頭補上任何引言——"
        "從第一段事實直接寫起。\n"
        "2b. **時序不得改動**：原文的資料期別（例如「7 月失業率」「7 月核心 "
        "PCE」）必須原樣保留在同一個數字旁邊，不可刪除、不可搬到別處、"
        "不可合併成一句。也**不要**用「本月」「當前」「最新」「目前」"
        "這類詞去描述這些數字——它們是已公布的上一期資料，不是當下的狀態。"
        "「上次會議（7/29）」是會議日期，不是資料期別，兩者不可混為一談。\n"
        f"3. 長度大約 {lo} 到 {hi} 個中文字，**不要超過 {hi} 字**。"
        "不要逐字計數、不要在輸出裡標註字數或字元位置、"
        "也不要提到這個範圍本身。\n"
        "4. 這段話後面會再接一句由程式產生的結論，**你不必也不要自己寫結論**，"
        "寫到最後一段事實就停。\n"
        "5. 輸出純文字一段：不用列點、不用 markdown、不用換行、"
        "不要有括號編號或任何註記。\n"
        "6. 直接輸出改寫後的文字，開頭不要有「以下是」「好的」這類引言，"
        "結尾不要有任何說明。"
        + (f"\n其他要求：{extra}" if extra else "")
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


# 句子結束的標點。缺了它就代表話沒講完。
_END = "。！？」』）.!?"


def looks_truncated(body: str) -> bool:
    """
    這段改寫是不是**話講到一半**。

    為什麼需要這個：`finishReason` 是最權威的截斷訊號，但只有 Gemini 會給，
    遇到代理或供應商改版就可能拿不到。結尾標點則是純文字層面的判斷，
    誰來做都成立。

    實際被印上畫面的那一次長這樣：

        …對此 7/29 會議維持不變，有 3 票主張升息，下次會議

    後面直接沒了。長度 146 字落在護欄內、數字也全部合法，所以三道防護欄
    一道都沒攔住——因為它們檢查的是「有沒有亂寫」，沒有檢查「有沒有寫完」。
    """
    s = (body or "").strip()
    return bool(s) and s[-1] not in _END


# 中文數字寫的「幾方」也要鎖。
#
# 數字鎖定只認阿拉伯數字（`_NUM` 是 `\d`），而共識句刻意用中文數字寫——
# 「三方裡兩方偏升息、一方偏降息」比「3 方裡 2 方」像人話。代價是那三個
# 數字**完全在鎖定範圍之外**，模型可以隨便改而三道防護欄都不作聲。
#
# 實際發生過的：
#     組裝版　聯準會把通膨擺在前面；三方裡**兩方**偏升息、一方偏降息。
#     畫面上　聯準會目前把通膨擺在前面，三方陣營裡有**一方**偏升息、
#             另一方偏降息。
# 二比一變成一比一——多數變成平手，而這一句正是整段的第一個結論。
#
# 為什麼不把所有中文數字都正規化進 `_numbers()`：「一致」「一半」「三個月」
# 到處都是，全鎖會讓正常的改寫大量誤判。所以只鎖**緊接著「方」**的那一個字
# ——那是這段話裡唯一用中文數字表達「數量」的地方。
#
# 排除「方面／方向／方案／方式」：「方向分歧」就在同一句裡，不排掉會誤判。
_CN_DIGIT = {"〇": 0, "零": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_SIDES = re.compile(r"([〇零一二兩三四五六七八九])\s*方(?![面向案式])")


def _sides(s: str) -> list[int]:
    """「三方裡兩方偏升息、一方偏降息」→ [1, 2, 3]（排序後比對）。"""
    return sorted(_CN_DIGIT[c] for c in _SIDES.findall(s or ""))


def validate(out: str, source: str, cap: int | None = None) -> str:
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
    # 這一條要雙向比對，不是「有沒有多出來」：實際的錯是把「兩方」改小成
    # 「一方」——**少掉**一個數量，單向檢查抓不到。
    if _sides(out) != _sides(source):
        return (f"共識句的方數對不上（原文 {_sides(source)}、"
                f"輸出 {_sides(out)}）")
    if "重點：" not in out:
        return "重點句的前綴不見了"
    n = cjk_len(out)
    top = cap or MAX_CJK
    if not (MIN_CJK <= n <= top):
        return f"長度 {n} 字，超出 {MIN_CJK}–{top}"
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
        # 為什麼預設是 pro 而不是 flash：這一段**一個月只重新生成幾次**
        #（事實沒變就走 state/brief.json 的快取），所以「貴的模型」在這裡
        # 幾乎不花錢，也吃不掉免費額度。而 flash 實測寫出來的東西偏平，
        # 還把「三方裡兩方偏升息」改成「一方」——換句話說省下來的那點
        # 額度買到的是比較差的稿子加上一次事實錯誤。
        #
        # 選 2.5 而不是 3.x pro：2.x 才收 thinkingConfig，能把推理壓到最小
        # 而不是讓它吃掉輸出額度（見 _thinking）。3.x 關不掉，截斷風險高。
        "model": "gemini-2.5-pro",
    },
    "anthropic": {
        "env": ("ANTHROPIC_API_KEY",),
        "model": "claude-haiku-4-5",
    },
}


def config_note(env) -> str:
    """
    一行字說明「這次實際會用什麼」，給執行紀錄看。

    存在的理由是一個查了三次的問題：使用者把 BRIEF_MODEL 設好了，
    log 卻還是走預設模型。可能的原因有三個，而它們的畫面完全一樣：

      ① 變數真的沒設
      ② 設在 Secrets 分頁而不是 Variables 分頁
      ③ 變數設對了，但 repo 裡的 update.yml 是舊版、沒有那一行
         `BRIEF_MODEL: ${{ vars.BRIEF_MODEL }}`——變數再對也傳不進來

    程式看得到的只有「環境變數有沒有值」，所以就把這件事明確講出來：
    印出 BRIEF_MODEL 到底有沒有傳進這個行程。剩下的判斷交給人，
    但至少不必再猜了。
    """
    provider, key = _pick_provider(env)
    if not provider:
        return "沒有可用的金鑰 → 用規則組裝版（設 GEMINI_API_KEY 或 " \
               "ANTHROPIC_API_KEY 才會啟用潤稿）"
    override = (env.get("BRIEF_MODEL") or "").strip()
    if override:
        return f"供應商 {provider}、模型 {override}（來自 BRIEF_MODEL）"
    return (f"供應商 {provider}、模型 {PROVIDERS[provider]['model']}（預設值）"
            "；BRIEF_MODEL 沒有傳進來——變數若已設定，檢查 update.yml 的 env "
            "有沒有那一行 BRIEF_MODEL: ${{ vars.BRIEF_MODEL }}")


def _pick_provider(env) -> tuple[str, str]:
    """回傳 (供應商, 金鑰)；沒有任何金鑰時回 ("", "")。"""
    for name in PROVIDER_ORDER:
        for var in PROVIDERS[name]["env"]:
            key = (env.get(var) or "").strip()
            if key:
                return name, key
    return "", ""


def maybe_polish(assembled: dict, cache_path, offline: bool = False,
                 env: dict | None = None, cfg: dict | None = None,
                 _post=None) -> dict:
    """
    回傳 {"text", "chars", "source", "model"}，
    source ∈ model / model-cache / assembled。

    env 與 _post 參數是給測試用的（不碰真的環境變數、不打真的 API）。
    """
    env = os.environ if env is None else env
    cfg = cfg or {}
    if cfg.get("enabled") is False:                # config 明確關掉
        return {"text": assembled.get("text", ""),
                "chars": assembled.get("chars", 0),
                "source": "assembled", "model": ""}
    out = {"text": assembled.get("text", ""),
           "chars": assembled.get("chars", 0),
           "source": "assembled", "model": ""}
    if not out["text"]:
        return out

    provider, key = _pick_provider(env)
    override = (env.get("BRIEF_MODEL") or "").strip()
    model = override or (PROVIDERS[provider]["model"] if provider else "")
    # 每次都印出「這次實際用什麼」。沒有這一行的話，「我明明設了
    # BRIEF_MODEL 為什麼沒生效」只能靠猜——變數可能沒設、可能設在
    # Secrets 分頁、也可能 workflow 根本沒把它傳進來（舊版的 update.yml
    # 沒有那一行）。三種的畫面與 log 先前長得一模一樣。
    log.info("整體情勢潤稿設定：%s", config_note(env))
    parts = assembled.get("parts") or []
    # 語氣也進雜湊：改了 config/brief.yaml 的 style／extra／temperature
    # 卻沿用舊快取的話，畫面完全不會變，使用者會以為設定沒生效。
    tone = json.dumps([cfg.get("style"), cfg.get("extra"),
                       cfg.get("temperature")],
                      ensure_ascii=False, sort_keys=True)
    facts_h = _hash(parts, "")                     # 只看事實
    h = _hash(parts, f"{provider}:{model}:{tone}")  # 事實＋供應商＋模型＋語氣

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

    # ---- 重點句不交給模型 ----
    #
    # 重點句（「重點：降息還遠，解鎖條件是…」）是整段裡**最重要、也最
    # 由規則決定**的一句：升降息傾向、解鎖條件、還差多少個百分點，
    # 全部來自九宮格與觸發條件。讓模型碰它只有下檔沒有上檔。
    #
    # 而且它是先前兩種退回的共同原因。模型同時被要求「壓在字數範圍內」
    # 與「保留重點句」，這兩件事會互相排擠——實測到的順序是：
    #   第一次 206 字（超出上限）→ 帶著「太長」的理由重試
    #   第二次為了縮短，直接把整句重點句刪掉 → 「重點句的前綴不見了」
    # 兩次都不是模型寫壞，是我給了兩個會打架的要求。
    #
    # 拆開之後：模型只改寫事實段落，重點句由我們原封不動接回去。
    # 少一個限制、而且「重點：」前綴變成**結構上保證存在**，不再靠
    # 模型配合。字數上限也先把重點句的長度扣掉（見 _target_range 的 reserve）。
    #
    # ---- 「本次更新」那一句也不交給模型 ----
    #
    # 同樣的道理，而且是踩過才學到的：先前只在提示詞裡寫「保留在最前面且
    # 不得改動任何數字」，模型照樣把它改寫掉了。實際發生的是——CPI 發布日，
    # 組裝版寫的是「本次更新：物價 7 月，CPI 年增 3.4%（上月 3.5%）」，
    # 畫面上出現的卻是「本次更新：7 月核心 PCE 3.3%、三個月年化 2.9%」，
    # 也就是把下一段的通膨敘述整句抄過來。
    #
    # **數字鎖定攔不到這種改寫**：3.3 與 2.9 本來就出現在原文的通膨段裡，
    # 逐一比對每個數字都合法。鎖定檢查的是「有沒有憑空冒出的數字」，
    # 不是「這個數字有沒有出現在對的句子裡」——後者它結構上就查不了。
    #
    # 所以規則層級要換：**能用結構保證的事，不要靠提示詞請模型配合。**
    # 這句話百分之百由規則決定（哪個模組剛發布、哪幾個指標、動了多少），
    # 交給模型只有下檔沒有上檔。抽掉之後提示詞也少一條，剩下的更好遵守。
    head = next((p["text"] for p in parts if p.get("key") == "whatsnew"), "")
    tail = next((p["text"] for p in parts if p.get("key") == "takeaway"), "")
    body = "".join(p["text"] for p in parts
                   if p.get("key") not in ("whatsnew", "takeaway"))
    if not body:                                   # 只剩前後兩句時沒東西好改寫
        return out
    reserve = cjk_len(head) + cjk_len(tail)
    sys_prompt = _system(body, reserve, cfg)

    # ---- 呼叫 ----
    # 供應商可以回 (文字, 實際用的模型)：Gemini 在模型被汰換時會自己換一個，
    # 而畫面與執行紀錄要標的是**真的用了哪一個**，不是設定裡寫的那一個。
    #
    # 驗證沒過時**帶著原因重試一次**：格式錯誤跟 API 掛掉不一樣，模型看得懂
    # 「你上次錯在哪」，再講一次通常就對了。只重試一次——兩次都做不到就是
    # 這個模型做不到，繼續燒額度不會變出第三種結果。
    # 防護欄本身一個字都沒鬆——不合格照樣退組裝版。
    post = _post or _POST[provider]
    reason = ""
    text = ""
    for attempt in (1, 2):
        note = ("" if not reason else
                f"\n\n（上一次的輸出被退回，原因：{reason}。"
                f"請重新改寫並逐條遵守硬性規則——"
                f"特別注意不得超過字數上限、"
                f"不得新增任何原文沒有的數字。）")
        try:
            res = post(key, model, body + note, sys_prompt,
                       cfg.get("temperature"))
        except Exception as e:                     # noqa: BLE001
            log.warning("整體情勢潤稿失敗（%s），改用組裝版", e)
            return out
        if isinstance(res, tuple):
            res, model = res[0], (res[1] or model)
        body_out = _sanitize(res)
        # 前後兩句原封不動接回去——模型沒看過它們，也就改不壞
        text = head + body_out + tail
        # 先問「有沒有寫完」，再問「有沒有寫對」。順序有意義：截斷的輸出
        # 常常長度合格、數字也全部合法，validate 一道都攔不住，
        # 但它就是不能印上畫面。
        reason = ("輸出看起來被截斷（結尾不是完整的句子）"
                  if looks_truncated(body_out)
                  # 模型看不到這句話，寫得出來就是自己編的——多半是把
                  # 後面某一段抄過來冠上「本次更新」，而那些數字全部
                  # 合法，validate 攔不住。
                  else "自己寫了「本次更新」那一句（那一句不該由模型產生）"
                  if "本次更新" in body_out
                  else validate(text, out["text"], _max_cjk(cfg)))
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


def _post_anthropic(key: str, model: str, source_text: str,
                    system: str | None = None,
                    temperature: float | None = None) -> str:
    r = _http("POST", "https://api.anthropic.com/v1/messages",
              label=f"Anthropic {model}", headers={
                          "x-api-key": key,
                          "anthropic-version": "2023-06-01",
                          "content-type": "application/json",
                      }, json={
                          "model": model,
                          "max_tokens": MAX_OUT,
                          "temperature": (DEFAULT_TEMPERATURE
                                          if temperature is None
                                          else temperature),
                          "system": system or _system(source_text),
                          "messages": [{"role": "user",
                                        "content": source_text}],
                      })
    r.raise_for_status()
    return r.json()["content"][0]["text"]


def _retry_after(resp) -> float:
    """讀 Retry-After 標頭，讀不到或不合理就回 0（改用固定退避）。"""
    try:
        v = float((resp.headers or {}).get("Retry-After", ""))
    except (TypeError, ValueError, AttributeError):
        return 0.0
    return v if 0 < v <= RETRY_AFTER_MAX else 0.0


def _http(method: str, url: str, *, label: str, **kw):
    """
    帶重試的 HTTP 呼叫。**不**自己判斷成功與否——回傳 response 讓呼叫端
    決定（Gemini 的 400 要看內容再決定要不要換參數重送）。

    只有 RETRY_STATUS 與連線層例外會重試。試完還是不行的話：
    有 response 就回傳它（讓呼叫端用 raise_for_status 產生一致的訊息），
    連 response 都沒有才把最後一個例外丟出去。
    """
    resp = None
    last_exc = None
    for attempt in range(MAX_TRIES):
        try:
            resp = requests.request(method, url, timeout=TIMEOUT, **kw)
            last_exc = None
            if resp.status_code not in RETRY_STATUS:
                return resp
        except requests.RequestException as e:      # noqa: PERF203
            resp, last_exc = None, e
        if attempt == MAX_TRIES - 1:
            break
        wait = (_retry_after(resp) if resp is not None else 0.0) \
            or BACKOFF[min(attempt, len(BACKOFF) - 1)]
        why = (f"HTTP {resp.status_code}" if resp is not None else last_exc)
        log.warning("%s 暫時失敗（%s），%.0f 秒後重試（第 %d／%d 次）",
                    label, why, wait, attempt + 2, MAX_TRIES)
        _SLEEP(wait)
    if resp is not None:
        return resp
    raise last_exc


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
        r = _http("GET", f"{GEMINI_BASE}/models", label="Gemini 模型清單",
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


def _gemini_pick(names: list[str], exclude=(), prefer_lite: bool = False) -> str:
    """
    從可用清單裡挑一個來改寫。挑不到就回空字串（呼叫端會退回組裝版）。

    排序：先照用途分組（見 _family），同組內正式版優先於 preview，
    再來版本號大的優先。**不做語意判斷**——這裡只是在幾個等價的
    選項裡挑一個，挑錯了也只是文風差一點，數字仍然被防護欄鎖著。

    `prefer_lite` 是**被推理吃光額度之後**的那條路：lite 系列預設不開推理，
    所以整個輸出額度都拿來寫字。這時候「文風好一點」已經不重要了——
    重要的是拿到一段寫得完的文字。同理，版本要**由舊到新**：
    舊世代（2.x）能用 thinkingBudget 明確關掉推理，新世代反而不行。
    """
    def rank(n: str):
        low = n.lower()
        ver = _VER.search(low)
        has_ver = ver is not None
        v = float(ver.group(1)) if has_ver else 0.0
        fam = _family(low)
        if prefer_lite:
            # lite 排最前面，然後**版本由舊到新**：舊世代能用 thinkingBudget
            # 明確關掉推理，新世代反而不行。
            # 沒有版本號的別名（gemini-flash-lite-latest）要排在最後——
            # 別名指向的是**最新**的那一個，正是我們在避開的那一種。
            return (0 if "lite" in low else 1, fam,
                    v if has_ver else 99.0, n)
        return (fam, 1 if "preview" in low or "exp" in low else 0, -v, n)

    skip = {exclude} if isinstance(exclude, str) else set(exclude or ())
    cands = [n for n in names
             if n.lower().startswith("gemini")
             and n not in skip
             and not any(a in n.lower() for a in _AVOID)]
    return sorted(cands, key=rank)[0] if cands else ""


def _thinking(model: str) -> dict:
    """
    這一次呼叫要怎麼關掉推理鏈。回傳要併進 generationConfig 的欄位。

    為什麼要關：**推理用掉的 token 算在 maxOutputTokens 裡**。推理模型
    把額度花在想，回來的 candidate 會是 finishReason: MAX_TOKENS，
    文字空的或只寫到一半。

    **2.x 才送。** thinkingConfig.thinkingBudget 在 2.x 實測有效。

    **3.x 與別名一律不送**，因為兩個欄位都被拒絕過，各有一次直接證據：

        thinkingLevel   → 400 Unknown name "thinkingLevel"
        thinkingBudget  → 400 Request contains an invalid argument

    我一度改成「一律送，反正 400 有退路」——結果是**每一次執行都先送一個
    註定失敗的請求**，log 裡固定出現一段 400 的錯誤訊息，白花一個來回。
    退路是給意外用的，不是給已知會失敗的情況用的。

    3.x 關不掉推理，改用三道防線頂著：MAX_OUT 給足額度、截斷檢查
    （looks_truncated／finishReason），以及真的截斷時換成預設不推理的
    lite 模型。

    **2.5 Pro 也關不掉，但它跟 3.x 不一樣**：它收 thinkingConfig，只是
    `thinkingBudget` 的合法範圍是 128–32768 或 -1（動態），送 0 會直接 400。
    所以這裡送**最小值 128** 而不是省略——省略等於 -1（動態），模型可能
    花掉幾千個 token 去想一段 200 字的改寫，剩下的額度就不夠寫完，
    又會踩回截斷那個坑。128 是「合法的最少」，把額度留給文字。
    """
    low = model.lower()
    m = _VER.search(low)
    if not m or float(m.group(1)) >= 3:
        return {}
    if _family(low) == 2:                          # pro
        return {"thinkingConfig": {"thinkingBudget": PRO_MIN_THINKING}}
    return {"thinkingConfig": {"thinkingBudget": 0}}


def _gemini_call(key: str, model: str, source_text: str,
                 system: str | None = None, think: bool = True,
                 temperature: float | None = None) -> str:
    # 金鑰放 header 不放網址：放網址會跟著出現在錯誤訊息與代理的存取紀錄裡。
    cfg = {"temperature": (DEFAULT_TEMPERATURE if temperature is None
                           else temperature),
           "maxOutputTokens": MAX_OUT}
    if think:
        cfg.update(_thinking(model))
    r = _http("POST", f"{GEMINI_BASE}/models/{model}:generateContent",
              label=f"Gemini {model}", headers={
            "x-goog-api-key": key,
            "content-type": "application/json",
        }, json={
            "system_instruction": {"parts": [{"text": system
                                             or _system(source_text)}]},
            "contents": [{"role": "user",
                          "parts": [{"text": source_text}]}],
            "generationConfig": cfg,
        })
    # 400 有可能是推理欄位的名稱又改了。這種情況再送一次、不帶那個欄位——
    # 欄位名稱是 Google 的實作細節，不該讓整區因此消失。
    if r.status_code == 400 and think and _thinking(model):
        log.warning("Gemini 退回設定（%s），改成不指定推理層級再試一次",
                    r.text[:120])
        return _gemini_call(key, model, source_text, system, False, temperature)
    r.raise_for_status()

    js = r.json()
    cands = js.get("candidates") or []
    if not cands:
        # 沒有 candidate 通常是提示詞被安全過濾擋下，理由在 promptFeedback
        raise RuntimeError(f"沒有回覆內容（{js.get('promptFeedback')}）")
    parts = ((cands[0].get("content") or {}).get("parts")) or []
    text = "".join(p.get("text", "") for p in parts)
    finish = str(cands[0].get("finishReason") or "")
    if not text.strip():
        # 講清楚是哪一種空：MAX_TOKENS 代表額度被推理吃光，
        # SAFETY 代表內容被擋。兩者的處置完全不同。
        raise RuntimeError(f"回覆是空的（finishReason={finish}）")
    # ⚠️ 有文字**不代表寫完了**。額度用盡時回的是一段「寫到一半」的文字，
    # finishReason 為 MAX_TOKENS——先前只檢查空字串，所以這種半截的輸出
    # 一路通過驗證印上了畫面：讀者看到的是「…下次會議」後面直接沒了。
    # 有明確的截斷訊號就當失敗，讓上層帶著理由重試。
    if finish.upper() in ("MAX_TOKENS", "LENGTH"):
        raise TruncatedError(
            f"回覆被截斷（finishReason={finish}，可能是推理用掉了輸出額度）")
    return text


# 這一次執行裡已經確定叫不動的模型（404）。
#
# ⚠️ **清單裡有 ≠ 叫得動。** `GET /models` 會列出這把金鑰「看得到」的模型，
# 但其中一部分打 generateContent 會回 404。實測到的：
#   gemini-2.5-flash、gemini-2.5-flash-lite  → 清單裡有，呼叫回 404
#   gemini-flash-latest                      → 叫得動
# 不記起來的話，每次退路都會再挑中同一個死掉的名字、再浪費一次呼叫，
# 而免費額度本來就緊（這次還撞到 429）。
_DEAD: set[str] = set()

# 最多換幾個模型。三個夠了：第一個是設定的，後面兩個是退路。
# 再多只是在額度快用完的時候繼續燒。
MAX_MODEL_TRIES = 3


def _alt_model(key: str, exclude, prefer_lite: bool = False) -> str:
    """
    問可用清單、挑一個沒試過也沒死掉的替代模型。挑不到回空字串。

    清單一併寫進執行紀錄：下次要設 BRIEF_MODEL 時有名字可以抄。
    """
    names = _gemini_models(key)
    if not names:
        return ""
    skip = set(exclude) | _DEAD
    log.warning("這把金鑰可用的模型：%s",
                "、".join(names[:12]) + ("…" if len(names) > 12 else ""))
    return _gemini_pick(names, exclude=skip, prefer_lite=prefer_lite)


def _post_gemini(key: str, model: str, source_text: str,
                 system: str | None = None, temperature: float | None = None):
    """
    回傳改寫後的文字，或 (文字, 實際用的模型)。

    **依序試幾個模型**，而不是「失敗就換一個、再失敗就放棄」。理由是實測
    到的那條鏈：設定的模型推理吃光額度 → 換一個 lite → 那個 lite 回 404
    → 整段沒了。換過去的模型自己也會失敗，所以退路必須能接著往下走。

    兩種失敗換模型的方式不一樣：
      404          這把金鑰叫不動它。記進 _DEAD，之後不再挑到。
      回覆被截斷    模型能用但推理吃光額度。改挑「預設不推理」的 lite。
    其餘的錯（400 參數錯、401 金鑰錯、429 限流）換模型沒有意義，直接往上拋。
    """
    tried: list[str] = []
    cur, prefer_lite = model, False
    last_exc: Exception | None = None

    for _ in range(MAX_MODEL_TRIES):
        tried.append(cur)
        try:
            out = _gemini_call(key, cur, source_text, system,
                               temperature=temperature)
            return (out, cur) if cur != model else out
        except TruncatedError as e:
            last_exc, prefer_lite = e, True
            log.warning("%s 的推理吃光了輸出額度（%s）", cur, e)
        except requests.HTTPError as e:
            resp = getattr(e, "response", None)
            if resp is None or resp.status_code != 404:
                raise
            _DEAD.add(cur)
            last_exc = e
            log.warning("這把金鑰叫不動 %s（404），之後不再挑它", cur)

        alt = _alt_model(key, tried, prefer_lite=prefer_lite)
        if not alt:
            break
        log.warning("改用 %s 重試（要固定的話把 BRIEF_MODEL 設成它）", alt)
        cur = alt

    raise last_exc if last_exc else RuntimeError("Gemini 沒有可用的模型")


_POST = {"gemini": _post_gemini, "anthropic": _post_anthropic}
