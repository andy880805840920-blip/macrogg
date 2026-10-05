"""
FOMC 文本與投票分析（P3）。

設計原則（2026-10 改版）
------------------------
**這一頁不發明分數。** 先前有兩個分數：「客觀訊號分數」（政策行動 ±3、
反對票 ±2、風險句 ±1）與鷹鴿詞典的「措辭分數」——前者的權重沒有外部依據、
只看過去；後者在 Warsh 只剩百來字的聲明上沒有意義，用在記者會時還會把
記者的提問與否定句一起算進去。兩個都拿掉。

現在這個模組只輸出**文件裡的事實**：
  * 決議（升／降／維持、幅度、新區間）與投票（票數、反對者與方向）
  * 聲明逐句比對與固定措辭的出現次數（熱力圖，數的是字面次數，不是評分）
  * 記者會：依說話者切開，只摘主席本人的原句
  * 「反應函數」（detect_focus）：委員會目前把雙重使命的哪一邊擺在前面，
    依據逐條列出（聲明制式句、反對票、主席的明確表態）

政策方向的文字標籤由 fomc_extra.policy_direction() 產生：先看政策行動，
維持不變時看反對票主張的方向。不加權、不合成數字。

⚠️ 完整逐字稿依聯準會規定延後五年公布，故此處處理的是
   會後聲明、投票紀錄與記者會逐字稿。
"""

from __future__ import annotations

import re
import difflib
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# 固定追蹤的措辭（熱力圖：數字面出現次數，不計分）
# ---------------------------------------------------------------------------
TRACKED_PHRASES = [
    "restrictive", "data dependent", "balance of risks",
    "downside risks to employment", "upside risks to inflation",
    "greater confidence", "well positioned", "for some time", "patient",
    "solid", "moderated", "elevated", "maximum employment",
    "2 percent objective", "carefully assess",
]



@dataclass
class DocAnalysis:
    date: str
    kind: str = "statement"
    word_count: int = 0
    phrases: dict = field(default_factory=dict)
    vote: dict = field(default_factory=dict)
    decision: dict = field(default_factory=dict)  # {action, move_bp, lower, upper}
    focus: dict = field(default_factory=dict)     # 反應函數：目前重心在哪一邊
    has_presser: bool = False
    text: str = ""            # 全小寫，供詞頻比對
    text_display: str = ""    # 保留原始大小寫，供逐句比對顯示


def analyse(doc: dict) -> DocAnalysis:
    """doc: {date, text, vote?, presser?}"""
    from .fomc_extra import parse_decision
    clean = _normalise(doc.get("text", ""))
    raw_text = doc.get("text", "")
    vote = doc.get("vote") or {}
    presser = doc.get("presser")
    # 記者會只讀**主席本人**說的話。整份逐字稿裡有一半是記者的提問——
    # 「Are interest rates now ... restrictive?」不是聯準會的表態。
    chair = chair_text(presser) if presser else ""
    focus = detect_focus(raw_text, vote, chair or None)
    return DocAnalysis(
        date=doc["date"], word_count=len(clean.split()),
        phrases={p: _wb_count(clean, p) for p in TRACKED_PHRASES},
        vote=vote, decision=parse_decision(raw_text), focus=focus,
        has_presser=bool(presser), text=clean,
        # 逐句比對是給人讀的，不能用比對用的小寫版本——
        # 否則畫面上會出現 "the federal open market committee" 這種怪句子。
        text_display=re.sub(r"\s+", " ", raw_text).strip(),
    )



# 政策行動：聲明自己會寫「decided to maintain / raise / lower the target range」。
# 這是文件裡的事實陳述，不是語氣判讀。
_ACTION_RE = [
    ("hike", re.compile(r"decided to (?:raise|increase)\s+the target range", re.I)),
    ("cut", re.compile(r"decided to (?:lower|reduce|decrease)\s+the target range", re.I)),
    ("hold", re.compile(r"decided to (?:maintain|keep)\s+the target range", re.I)),
]

# 聲明自述的風險方向。這是委員會自己點名「我擔心哪一邊」——
# 明確的制式句，不是用字習慣。
_RISK_INFL = re.compile(r"upside risks? to inflation", re.I)
_RISK_EMPL = re.compile(r"downside risks? to (?:employment|the labor market)", re.I)
# 實際句型是 "the risks to achieving its employment and inflation goals
# are roughly in balance."——是 "in balance" 不是 "balanced"，
# 而且中間隔了五十幾個字元，範圍要放寬。
_RISK_BAL = re.compile(
    r"risks?[^.]{0,80}(?:roughly\s+)?(?:in\s+balance|balanced)", re.I)

# 通膨是否被聲明明白描述為高於目標
# 記者會裡的「表態句」。主席在 Q&A 與開場白裡對優先順序的表態，
# 往往比制式聲明直接得多——七月那份逐字稿有
# 「The path to central bank heaven requires delivering on our remit.
#   These days that means delivering on price stability.」
# 這種明講，而只讀聲明會完全錯過。
#
# 權重刻意比聲明低一級（見 detect_focus）：記者會是即席發言，
# 而且逐字稿是 PDF、會後幾天才發布，不是每次都抓得到。
_PRESSER_INFL = re.compile(
    r"deliver(?:ing)?\s+(?:on\s+)?price stability"
    r"|price stability\s+is\s+(?:our|the)\s+(?:top\s+)?(?:priority|focus)"
    r"|(?:focused|focus)\s+on\s+(?:bringing\s+)?inflation"
    r"|watching\s+(?:the\s+)?inflation data"
    r"|no soft (?:inflation )?(?:target|implicit target)"
    r"|restore price stability"
    r"|inflation\s+(?:remains?|is)\s+(?:our|the)\s+(?:main|primary|central)",
    re.I)
_PRESSER_EMPL = re.compile(
    r"(?:focused|focus)\s+on\s+(?:the\s+)?(?:labor market|employment)"
    r"|(?:labor market|employment)\s+is\s+(?:our|the)\s+(?:top\s+)?(?:priority|focus|concern)"
    r"|support(?:ing)?\s+the\s+labor market"
    r"|maximum employment\s+is\s+(?:our|the)"
    r"|act\s+to\s+(?:support|protect)\s+(?:the\s+)?(?:labor market|employment)"
    r"|downside risks? to (?:employment|the labor market)",
    re.I)

# 「通膨仍高於目標」的現況描述。比風險制式句弱一級（+1 而非 +2），
# 因為它陳述的是現況、不是委員會對風險分布的判斷。
_INFL_ABOVE = re.compile(
    r"inflation[^.]{0,60}(?:remains?|is|stays?)[^.]{0,30}"
    r"(?:above|elevated|higher than)", re.I)

# 就業側的**對稱**條款。先前只有通膨那一句有加分，就業沒有對應的，
# 結果是每一份提到「通膨仍偏高」的聲明都會往通膨側偏 +1——
# 而那句話幾乎每次都在，等於給判定加了一個常數偏誤。
# 就業轉弱的現況描述同樣常見（「勞動市場已降溫」「就業增速放緩」），
# 給它同樣的 −1，兩側才在同一個尺度上。
# 拆成兩條而不是一條大的替換：失業率是**升＝弱**，就業增速是**降＝弱**，
# 方向相反。混在同一個字組裡會讓「job gains have increased」也命中。
#
# 中間那段窗口用 (?!unemployment|inflation) 逐字擋掉換主詞的情況：
# 「Job gains have increased and the unemployment rate has declined」
# 兩個子句都是**偏強**，但 declined 落在 job gains 後 38 個字元內，
# 用單純的 [^.]{0,60} 會誤判成勞動市場轉弱。
_EMPL_SOFT = re.compile(
    r"(?:labor market|job gains|employment growth|payroll growth|hiring)"
    r"(?:(?!unemployment|inflation)[^.;]){0,50}"
    r"\b(?:soften\w*|cool\w*|moderat\w*|slow\w*|eas(?:ed|ing)|declin\w*|weaken\w*)\b"
    r"|unemployment rate"
    r"(?:(?!job gains|inflation)[^.;]){0,50}"
    r"(?:ha[sv]e?\s+)?\b(?:risen|increased|moved up|edged up|ticked up)\b",
    re.I)


def policy_action(text: str) -> str | None:
    """從聲明本文判定本次的政策行動。回傳 hike / cut / hold / None。"""
    for name, pat in _ACTION_RE:
        if pat.search(text):
            return name
    return None



# ---------------------------------------------------------------------------
# 記者會摘要
# ---------------------------------------------------------------------------
# 主題關鍵詞。逐字稿動輒上萬字，直接切前 N 個字沒有任何資訊價值；
# 依主題抽句才讀得出「這場記者會對每個議題說了什麼」。
PRESSER_TOPICS = [
    ("通膨", ["inflation", "price stability", "2 percent", "prices"]),
    ("就業", ["labor market", "employment", "unemployment", "job", "hiring"]),
    ("利率路徑", ["target range", "rate cut", "rate hike", "policy rate",
                  "restrictive", "accommodative", "neutral rate", "path"]),
    ("資產負債表", ["balance sheet", "reserves", "runoff", "securities holdings",
                    "ample reserves"]),
]

# 開場白與 Q&A 的分界。開場是準備稿、資訊密度最高；
# Q&A 是即席回答，雜訊多但偶爾更有訊息量，所以分開處理而不是混在一起。
#
# Powell 自 2019 年起的標準結尾是
# "Thank you. I look forward to your questions."——一定要涵蓋。
# 另外 pdfplumber 抽出的是彎引號（U+2019），"we'll" 的比對要兩種引號都吃。
_QA_MARKERS = [
    r"look forward to (?:your|their) questions",       # Powell 的標準結尾
    r"questions of your own[^.]*turn to them",         # Warsh 2026-07 的說法
    r"let['’]?s turn to (?:them|your questions)",
    r"happy to take your questions", r"take your questions",
    r"glad to take your questions", r"we['’]?ll now take questions",
    r"i['’]?ll now take your questions",
]

# 縮寫的句點不是句尾。涵蓋人名縮寫（Kevin M. Warsh）、
# 稱謂（Mr. Powell）與 U.S. 這類縮寫——這些後面接的正是大寫字，
# 光靠「句號＋空白＋大寫」的切法一定會切錯。
_ABBR_DOT = re.compile(
    r"\b(Mr|Ms|Mrs|Dr|Gov|Sen|Rep|St|vs|Inc|Corp|No"
    r"|[A-Z])\.(?=\s+[A-Z])")


def _sentences_of(text: str, min_len: int = 40) -> list[str]:
    """
    切句。縮寫句點先以占位符保護，切完再還原。

    min_len 預設 40 是給「主題摘句」用的——太短的句子（"Thank you."）
    當摘要沒有意義。會議紀要的量詞句用 0（短句一樣是一個觀點）。
    """
    protected = _ABBR_DOT.sub(lambda m: m.group(1) + "\x00", text)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", protected)
    return [p.replace("\x00", ".").strip()
            for p in parts if len(p.strip()) > min_len]


# 逐字稿的說話者標籤：「CHAIRMAN WARSH.」「NICK TIMIRAOS.」「MICHELLE SMITH.」
# 至少兩個全大寫字，才不會把「AI.」「FOMC.」這種句尾縮寫當成換人說話。
_SPEAKER = re.compile(
    r"(?<![A-Za-z’'])((?:[A-Z][A-Z’'\-]+)(?:\s+[A-Z][A-Z’'\-]+){1,3})\.\s")
_CHAIR = re.compile(r"^(?:CHAIR(?:MAN|WOMAN)?|VICE CHAIR)\b")
# 每頁頁首：「Page 3 of 15 September 16, 2026 Chairman Warsh’s Press Conference FINAL」
_PAGE_HDR = re.compile(
    r"Page \d+ of \d+\s+[A-Z][a-z]+ \d{1,2}, \d{4}\s+Chair(?:man|woman)? [A-Z][a-z]+[’']s "
    r"Press Conference\s+(?:FINAL|PRELIMINARY)", re.I)


def presser_turns(text: str) -> list[tuple[str, str]]:
    """依說話者切開逐字稿：[(說話者, 這段話)]。切不出來回空清單。"""
    t = _PAGE_HDR.sub(" ", text or "")
    t = re.sub(r"\s+", " ", t)
    ms = list(_SPEAKER.finditer(t))
    out = []
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(t)
        out.append((m.group(1).strip(), t[m.end():end].strip()))
    return out


def split_presser(text: str) -> tuple[str, str]:
    """
    把逐字稿切成 (開場聲明, 之後的問答全文)。

    先依說話者切：開場＝第一位非主席說話者（通常是主持人 MICHELLE SMITH）
    出現之前，主席說的那一段。先前只靠「I look forward to your questions」
    這類結尾句——Warsh 2026-09 改說「I'll take a few of your questions」，
    沒對到，整份逐字稿（含記者提問）都被當成開場。說話者標籤找不到時
    才退回結尾句比對。
    """
    turns = presser_turns(text)
    if turns and any(not _CHAIR.match(sp) for sp, _ in turns):
        k = next(i for i, (sp, _) in enumerate(turns) if not _CHAIR.match(sp))
        opening = " ".join(x for _, x in turns[:k])
        qa = " ".join(f"{sp}. {x}" for sp, x in turns[k:])
        return opening.strip(), qa.strip()
    low = (text or "").lower()
    for pat in _QA_MARKERS:
        m = re.search(pat, low)
        if m:
            return text[:m.end()].strip(), text[m.end():].strip()
    return text or "", ""


def chair_text(text: str) -> str:
    """只留主席本人說的話（開場＋每一則回答）。切不出說話者時回傳原文。"""
    turns = presser_turns(text)
    if not turns:
        return text or ""
    return " ".join(x for sp, x in turns if _CHAIR.match(sp))


def summarise_presser(text: str, per_topic: int = 2) -> dict:
    """
    記者會逐字稿的確定性摘要：依主題（通膨／就業／利率路徑／資產負債表）
    抽主席本人的原句，開場聲明優先（那是準備稿），不足再從主席的回答補。
    不用模型、不改寫、不計分。

    回傳 {opening_len, qa_len（主席回答的字數）, questions（提問則數）,
          topics: [{name, sentences}]}
    """
    if not text:
        return {"topics": [], "opening_len": 0, "qa_len": 0, "questions": 0}
    turns = presser_turns(text)
    if turns and any(not _CHAIR.match(sp) for sp, _ in turns):
        k = next(i for i, (sp, _) in enumerate(turns) if not _CHAIR.match(sp))
        opening = " ".join(x for _, x in turns[:k])
        answers = " ".join(x for sp, x in turns[k:] if _CHAIR.match(sp))
        # 主持人只點名（「Richard.」），不算提問
        questions = sum(1 for sp, x in turns[k:]
                        if not _CHAIR.match(sp) and len(x.split()) > 6)
    else:
        opening, _qa = split_presser(text)
        answers, questions = "", 0
    open_s, qa_s = _sentences_of(opening), _sentences_of(answers)

    topics = []
    used: set[str] = set()
    for name, keys in PRESSER_TOPICS:
        picked = []
        for pool in (open_s, qa_s):
            for s in pool:
                if len(picked) >= per_topic:
                    break
                low = s.lower()
                if any(k in low for k in keys) and s not in used:
                    picked.append(s)
                    used.add(s)
            if len(picked) >= per_topic:
                break
        if picked:
            topics.append({"name": name, "sentences": picked})
    return {"topics": topics, "opening_len": len(opening.split()),
            "qa_len": len(answers.split()), "questions": questions}


# ---------------------------------------------------------------------------
# 反應函數：聯準會目前把哪一邊的使命擺在前面
# ---------------------------------------------------------------------------
FOCUS_TEXT = {
    "inflation": ("通膨優先",
                  "委員會目前把通膨擺在前面。這種體制下，就業轉弱不會單獨換來降息——"
                  "要等通膨先回到目標附近，寬鬆才會啟動。"),
    "employment": ("就業優先",
                   "委員會目前把就業擺在前面。這種體制下，通膨略高於目標不會阻止降息，"
                   "勞動市場的惡化才是決定性的。"),
    "balanced": ("兩邊並重",
                 "委員會沒有明顯偏向任何一邊，兩個使命的風險被描述為大致平衡。"
                 "這時候哪一邊先出現極端值，哪一邊就會主導決策。"),
    "unknown": ("無法判定",
                "本次聲明的線索不足或互相抵銷，無法明確判定委員會的重心，"
                "方向主要由後續數據決定。"),
}


def detect_focus(text: str, vote: dict | None = None,
                 presser: str | None = None) -> dict:
    """
    判斷聯準會目前把雙重使命的哪一邊擺在前面。

    為什麼需要這個
    --------------
    九宮格如果用固定的對照表，等於假設聯準會對就業與通膨的權重永遠一樣。
    實際上反應函數會移動：2020 年是就業優先，2026 年明顯是通膨優先。
    同一格「就業弱 × 通膨高」，在兩種體制下的結論完全相反。

    判定只用聲明裡的制式句與投票紀錄，不用模型，所以每次跑結果一致。

    計分（正＝通膨優先、負＝就業優先）
    ---------------------------------
    | 來源 | 權重 | 說明 |
    |---|---|---|
    | 聲明的風險制式句 | ±2 | 「通膨上行風險」／「就業下行風險」，這是委員會自述的風險分布 |
    | 聲明的現況描述   | ±1 | 「通膨仍高於目標」／「勞動市場已轉弱」，陳述現況而非風險判斷，弱一級 |
    | 反對票方向與張數 | ±1～2 | 三張升息反對票是強訊號，跟一張不同分 |
    | 記者會的明確表態 | ±1 | 即席發言、逐字稿延後數日、不是每次抓得到，刻意低一級 |

    兩側刻意**對稱**：每一條加分項都有方向相反的對應項。不對稱會變成常數偏誤——
    例如「通膨仍高於目標」這句幾乎每份聲明都在，只加通膨側等於每次先偏 +1。

    這張表在 README 與情境合成頁的名詞解釋都有一份，改權重時三處要一起改。
    """
    text = text or ""
    vote = vote or {}
    score = 0          # 正＝偏通膨、負＝偏就業
    evidence: list[str] = []

    if _RISK_INFL.search(text):
        score += 2
        evidence.append("聲明點名「通膨上行風險」")
    if _RISK_EMPL.search(text):
        score -= 2
        evidence.append("聲明點名「就業下行風險」")
    if _INFL_ABOVE.search(text):
        score += 1
        evidence.append("聲明描述通膨仍高於目標")
    if _EMPL_SOFT.search(text):
        score -= 1
        evidence.append("聲明描述勞動市場已轉弱")

    hawk = sum(1 for d in (vote.get("dissents") or []) if d.get("direction") == "hike")
    dove = sum(1 for d in (vote.get("dissents") or []) if d.get("direction") == "cut")
    # 反對票的權重要隨票數放大：三張升息反對票是強訊號，
    # 跟一張不能同分——否則像 2026-07 那種聲明極簡、只剩投票可看的會議，
    # 會被誤判成「兩邊並重」。
    net_dissent = hawk - dove
    if net_dissent > 0:
        score += 2 if net_dissent >= 2 else 1
        evidence.append(f"{hawk} 張反對票主張升息")
    elif net_dissent < 0:
        score -= 2 if -net_dissent >= 2 else 1
        evidence.append(f"{dove} 張反對票主張降息")

    # ---- 記者會：權重比聲明低一級（±1）----
    # 理由：即席發言不如正式文件精確，而且逐字稿是 PDF、會後數日才發布，
    # 不是每次都抓得到。給它跟聲明制式句同樣的 ±2 會讓判定隨著
    # 「今天抓不抓得到 PDF」跳動。
    presser = presser or ""
    if presser:
        p_infl = len(_PRESSER_INFL.findall(presser))
        p_empl = len(_PRESSER_EMPL.findall(presser))
        if p_infl > p_empl:
            score += 1
            evidence.append(f"記者會 {p_infl} 處表態以物價穩定為優先")
        elif p_empl > p_infl:
            score -= 1
            evidence.append(f"記者會 {p_empl} 處表態以勞動市場為優先")

    balanced_said = bool(_RISK_BAL.search(text))

    if score >= 2:
        focus = "inflation"
    elif score <= -2:
        focus = "employment"
    elif balanced_said:
        # 「兩邊並重」只在聲明**真的這樣說**時成立
        #（"risks ... are roughly in balance"）。訊號互相抵銷不等於並重，
        # 那是「無法判定」——兩者的中文說明完全不同，不能混用。
        focus = "balanced"
        if not evidence:
            evidence.append("聲明稱兩邊風險大致平衡")
    else:
        focus = "unknown"

    label, note = FOCUS_TEXT[focus]
    # 逐條依據＋原句，讓讀者自己核對每一條指向哪一邊（畫面逐條列出）
    def _quote(rx, src):
        return next((x for x in _sentences_of(src or "", 0) if rx.search(x)), "")
    _q = {"通膨上行風險": (_RISK_INFL, text), "就業下行風險": (_RISK_EMPL, text),
          "通膨仍高於目標": (_INFL_ABOVE, text), "勞動市場已轉弱": (_EMPL_SOFT, text),
          "以物價穩定為優先": (_PRESSER_INFL, presser),
          "以勞動市場為優先": (_PRESSER_EMPL, presser),
          "風險大致平衡": (_RISK_BAL, text)}
    items = []
    for e in evidence:
        side = ("balanced" if "平衡" in e else
                "inflation" if any(k in e for k in ("通膨", "升息", "物價")) else
                "employment")
        rx_src = next((v for k, v in _q.items() if k in e), None)
        items.append({"text": e, "side": side,
                      "quote": _quote(*rx_src) if rx_src else ""})
    return {"focus": focus, "label": label, "note": note,
            "score": score, "evidence": evidence, "items": items,
            "used_presser": bool(presser)}


def _normalise(t: str) -> str:
    return re.sub(r"\s+", " ", t).lower().strip()


def _wb_count(text: str, phrase: str) -> int:
    """
    整詞比對的出現次數。

    不能用裸的 substring（text.count）：
      * "increased" 會被算成鴿派詞 "eased"、"patience" 會同時命中 "patient"
      * 方向會整個反過來，而那正是這個模組要判斷的東西
    文本已先轉小寫，所以邊界用「前後不是英文字母」判定即可。
    """
    return len(re.findall(r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])", text))



# ---------------------------------------------------------------------------
# 逐句配對的紅線比對
# ---------------------------------------------------------------------------
@dataclass
class DiffRow:
    kind: str                 # changed | added | removed | same
    old: str = ""
    new: str = ""
    old_html: str = ""
    new_html: str = ""


def paired_redline(prev_text: str, cur_text: str,
                   max_rows: int = 40) -> list[DiffRow]:
    """
    以句子配對呈現改動，並在句子內做字詞層級標色。

    先前的版本把「刪除」與「新增」分成兩堆列出，讀者要自己配對。
    這裡改成同一列並排舊 → 新，只有真正改動的字會被標示。
    """
    a, b = _sentences(prev_text), _sentences(cur_text)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    rows: list[DiffRow] = []

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for s in a[i1:i2]:
                rows.append(DiffRow("same", old=s, new=s))
        elif tag == "delete":
            for s in a[i1:i2]:
                rows.append(DiffRow("removed", old=s))
        elif tag == "insert":
            for s in b[j1:j2]:
                rows.append(DiffRow("added", new=s))
        else:
            olds, news = a[i1:i2], b[j1:j2]
            paired = _pair(olds, news)
            for o, n in paired:
                if o is None:
                    rows.append(DiffRow("added", new=n))
                elif n is None:
                    rows.append(DiffRow("removed", old=o))
                else:
                    oh, nh = word_diff(o, n)
                    rows.append(DiffRow("changed", old=o, new=n,
                                        old_html=oh, new_html=nh))
    return rows[:max_rows]


def _pair(olds: list[str], news: list[str]) -> list[tuple]:
    """把被替換的舊句與新句配對——挑相似度最高的互相對應。"""
    out, used = [], set()
    for o in olds:
        best, best_score = None, 0.0
        for k, n in enumerate(news):
            if k in used:
                continue
            r = difflib.SequenceMatcher(None, o, n).ratio()
            if r > best_score:
                best, best_score, best_k = n, r, k
        if best is not None and best_score >= 0.45:
            used.add(best_k)
            out.append((o, best))
        else:
            out.append((o, None))
    for k, n in enumerate(news):
        if k not in used:
            out.append((None, n))
    return out


def word_diff(old: str, new: str) -> tuple[str, str]:
    """回傳兩段 HTML，改動的字詞用 <mark> 包起來。"""
    import html as _h
    ao, an = old.split(), new.split()
    sm = difflib.SequenceMatcher(None, ao, an, autojunk=False)
    oh, nh = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        o_chunk = _h.escape(" ".join(ao[i1:i2]))
        n_chunk = _h.escape(" ".join(an[j1:j2]))
        if tag == "equal":
            oh.append(o_chunk)
            nh.append(n_chunk)
        else:
            if o_chunk:
                oh.append(f"<mark class='mo'>{o_chunk}</mark>")
            if n_chunk:
                nh.append(f"<mark class='mn'>{n_chunk}</mark>")
    return " ".join(oh), " ".join(nh)


def _sentences(t: str) -> list[str]:
    t = re.sub(r"\s+", " ", t).strip()
    return [p.strip() for p in re.split(r"(?<=[.;])\s+", t) if p.strip()]


def changed_rows(rows: list[DiffRow]) -> list[DiffRow]:
    return [r for r in rows if r.kind != "same"]


# ---------------------------------------------------------------------------
# 時間序列
# ---------------------------------------------------------------------------
def phrase_matrix(docs: list) -> dict:
    ds = sorted(docs, key=lambda d: d.date)
    dates = [d.date for d in ds]
    keep = [p for p in TRACKED_PHRASES if any(d.phrases.get(p, 0) for d in ds)]
    grid = [[d.phrases.get(p, 0) for d in ds] for p in keep]
    return {"dates": dates, "phrases": keep, "grid": grid}


def shift(docs: list) -> dict:
    """
    最近一次會議的政策方向（文字標籤，取代舊的分數）。
    九宮格、首頁、每日摘要都讀這裡的 direction 與 label。
    """
    from .fomc_extra import policy_direction, DIR_ZH
    ds = sorted(docs, key=lambda d: d.date)
    if not ds:
        return {}
    cur = ds[-1]
    prev = ds[-2] if len(ds) > 1 else None
    direction, label = policy_direction(cur.decision, cur.vote)
    out = {"cur_date": cur.date, "direction": direction,
           "label": DIR_ZH[direction], "decision_label": label}
    if prev is not None:
        pdir, plab = policy_direction(prev.decision, prev.vote)
        out.update({"prev_date": prev.date, "prev_direction": pdir,
                    "prev_decision_label": plab})
    return out
