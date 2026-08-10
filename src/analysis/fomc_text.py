"""
FOMC 文本與投票分析（P3）。

設計原則
--------
**計分與詞頻走純規則，不交給模型。**

兩個分數並列，刻意不合成
------------------------
  1. 客觀訊號分數：政策行動 + 反對票 + 聲明自述的風險方向
  2. 措辭分數：聲明用語的鷹鴿詞典計分

合成會掩蓋最有價值的資訊——**兩者背離時，背離本身就是訊號**。
2026 年 7 月正是如此：措辭因為主席刻意縮短聲明而讀起來偏鴿，
但三張贊成升息的反對票指向偏鷹，市場也照後者走。

另外輸出「反應函數」（detect_focus）：委員會目前把雙重使命的哪一邊
擺在前面。九宮格需要這個才不會假設權重永遠固定。

⚠️ 完整逐字稿依聯準會規定延後五年公布，故此處處理的是
   會後聲明、投票紀錄與記者會逐字稿。
"""

from __future__ import annotations

import re
import difflib
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# 鷹鴿詞典（僅用於「措辭分數」，權重已降為輔助）
# ---------------------------------------------------------------------------
HAWKISH = {
    "restrictive": 3.0, "elevated": 2.0, "further tightening": 3.0,
    "additional firming": 3.0, "remains elevated": 2.5,
    "upside risks to inflation": 3.0, "not appropriate to reduce": 3.0,
    "greater confidence": 1.5, "strongly committed": 2.0, "resolute": 2.0,
    "solid pace": 1.5, "robust": 1.5, "tight labor market": 2.0,
    "for some time": 1.5, "additional policy tightening": 3.0,
    "patience": 2.0, "patient": 2.0,
}

DOVISH = {
    "moderated": 2.0, "softened": 2.5, "eased": 2.0,
    "downside risks to employment": 3.0, "slowed": 2.0, "declined": 1.5,
    "closer to": 1.5, "made further progress": 2.0,
    "reduce the target range": 3.0, "less restrictive": 3.0,
    "cooling": 2.5, "weakened": 2.5, "gradually": 1.0, "balanced": 1.0,
}

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
    tone_score: float = 0.0          # 措辭分數（詞典）
    objective_score: float = 0.0     # 客觀訊號分數（政策行動 + 反對票 + 風險方向）
    obj_parts: dict = field(default_factory=dict)
    hawk_hits: dict = field(default_factory=dict)
    dove_hits: dict = field(default_factory=dict)
    phrases: dict = field(default_factory=dict)
    vote: dict = field(default_factory=dict)
    focus: dict = field(default_factory=dict)   # 反應函數：目前重心在哪一邊
    has_presser: bool = False
    presser_score: float | None = None
    text: str = ""            # 全小寫，供計分與詞頻比對
    text_display: str = ""    # 保留原始大小寫，供逐句比對顯示


def analyse(doc: dict) -> DocAnalysis:
    """doc: {date, text, vote?, presser?}"""
    clean = _normalise(doc.get("text", ""))
    words = len(clean.split())

    hawk_hits, dove_hits = _count_tones(clean)
    denom = max(words, 1) / 100
    tone = (sum(HAWKISH[k] * v for k, v in hawk_hits.items())
            - sum(DOVISH[k] * v for k, v in dove_hits.items())) / denom

    vote = doc.get("vote") or {}
    raw_text = doc.get("text", "")
    obj, parts = objective_score(vote, raw_text)
    focus = detect_focus(raw_text, vote)

    presser = doc.get("presser")
    p_score = None
    if presser:
        pc = _normalise(presser)
        pd = max(len(pc.split()), 1) / 100
        ph, pv = _count_tones(pc)
        p_score = (sum(HAWKISH[k] * v for k, v in ph.items())
                   - sum(DOVISH[k] * v for k, v in pv.items())) / pd

    return DocAnalysis(
        date=doc["date"], word_count=words,
        tone_score=round(tone, 3), objective_score=round(obj, 3),
        obj_parts=parts, hawk_hits=hawk_hits, dove_hits=dove_hits,
        phrases={p: _wb_count(clean, p) for p in TRACKED_PHRASES},
        vote=vote, focus=focus, has_presser=bool(presser),
        presser_score=None if p_score is None else round(p_score, 3),
        text=clean,
        # 逐句比對是給人讀的，不能用計分用的小寫版本——
        # 否則畫面上會出現 "the federal open market committee" 這種怪句子。
        text_display=re.sub(r"\s+", " ", doc.get("text", "")).strip(),
    )


# 政策行動：聲明自己會寫「decided to maintain / raise / lower the target range」。
# 這是文件裡的事實陳述，不是語氣判讀，所以歸在客觀訊號。
_ACTION_RE = [
    ("hike", re.compile(r"decided to (?:raise|increase)\s+the target range", re.I)),
    ("cut", re.compile(r"decided to (?:lower|reduce|decrease)\s+the target range", re.I)),
    ("hold", re.compile(r"decided to (?:maintain|keep)\s+the target range", re.I)),
]

# 聲明自述的風險方向。這是委員會自己點名「我擔心哪一邊」，
# 與詞典計分不同——它是明確的制式句，不是用字習慣。
_RISK_INFL = re.compile(r"upside risks? to inflation", re.I)
_RISK_EMPL = re.compile(r"downside risks? to (?:employment|the labor market)", re.I)
_RISK_BAL = re.compile(r"risks?[^.]{0,40}(?:roughly )?(?:are |remain )?balanced", re.I)

# 通膨是否被聲明明白描述為高於目標
_INFL_ABOVE = re.compile(
    r"inflation[^.]{0,60}(?:remains?|is|stays?)[^.]{0,30}"
    r"(?:above|elevated|higher than)", re.I)


def policy_action(text: str) -> str | None:
    """從聲明本文判定本次的政策行動。回傳 hike / cut / hold / None。"""
    for name, pat in _ACTION_RE:
        if pat.search(text):
            return name
    return None


def objective_score(vote: dict, text: str = "") -> tuple[float, dict]:
    """
    客觀訊號分數。正＝偏鷹（利升息）、負＝偏鴿（利降息）。

    三個成分，都是「文件裡的事實」而不是用字習慣：

      政策行動   升息 +3、降息 −3、不變 0
                 委員會實際做了什麼，權重最高。
      反對票     每張贊成升息的反對票 +2、贊成降息 −2。
                 反對票是投票紀錄，不受主席的措辭風格影響。
      風險方向   聲明點名「通膨上行風險」+1、「就業下行風險」−1。
                 這是制式句，與詞典計分的用字習慣不同。

    （點陣圖成分已移除：聯準會在 Warsh 任內縮減預測公布，
      這個輸入不再穩定存在，留著會讓分數的可比性時有時無。）
    """
    parts: dict = {}
    total = 0.0

    act = policy_action(text or "")
    act_score = {"hike": 3.0, "cut": -3.0, "hold": 0.0}.get(act, 0.0)
    parts["action"] = act_score
    parts["action_detail"] = {
        "hike": "本次升息", "cut": "本次降息", "hold": "本次維持利率不變",
    }.get(act, "無法從聲明判定政策行動")
    total += act_score

    hawk = sum(1 for d in (vote.get("dissents") or []) if d.get("direction") == "hike")
    dove = sum(1 for d in (vote.get("dissents") or []) if d.get("direction") == "cut")
    parts["dissent"] = 2.0 * (hawk - dove)
    parts["dissent_detail"] = (f"贊成升息 {hawk} 票、贊成降息 {dove} 票"
                               if (hawk or dove) else "全體一致，沒有反對票")
    total += parts["dissent"]

    risk = 0.0
    bits = []
    if _RISK_INFL.search(text or ""):
        risk += 1.0
        bits.append("聲明點名通膨上行風險")
    if _RISK_EMPL.search(text or ""):
        risk -= 1.0
        bits.append("聲明點名就業下行風險")
    if not bits and _RISK_BAL.search(text or ""):
        bits.append("聲明稱風險大致平衡")
    parts["risk"] = risk
    parts["risk_detail"] = "、".join(bits) or "聲明未明確點名風險方向"
    total += risk

    parts["has_signal"] = bool(act or hawk or dove or bits)
    return total, parts


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
                "本次聲明沒有足夠的線索判斷委員會的重心，方向主要由後續數據決定。"),
}


def detect_focus(text: str, vote: dict | None = None) -> dict:
    """
    判斷聯準會目前把雙重使命的哪一邊擺在前面。

    為什麼需要這個
    --------------
    九宮格如果用固定的對照表，等於假設聯準會對就業與通膨的權重永遠一樣。
    實際上反應函數會移動：2020 年是就業優先，2026 年明顯是通膨優先。
    同一格「就業弱 × 通膨高」，在兩種體制下的結論完全相反。

    判定只用聲明裡的制式句與投票紀錄，不用模型，所以每次跑結果一致。
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

    hawk = sum(1 for d in (vote.get("dissents") or []) if d.get("direction") == "hike")
    dove = sum(1 for d in (vote.get("dissents") or []) if d.get("direction") == "cut")
    if hawk > dove:
        score += 1
        evidence.append(f"{hawk} 張反對票主張升息")
    elif dove > hawk:
        score -= 1
        evidence.append(f"{dove} 張反對票主張降息")

    balanced_said = bool(_RISK_BAL.search(text))
    if balanced_said and not evidence:
        evidence.append("聲明稱兩邊風險大致平衡")

    if score >= 2:
        focus = "inflation"
    elif score <= -2:
        focus = "employment"
    elif evidence or balanced_said:
        focus = "balanced"
    else:
        focus = "unknown"

    label, note = FOCUS_TEXT[focus]
    return {"focus": focus, "label": label, "note": note,
            "score": score, "evidence": evidence}


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


def _count_tones(text: str) -> tuple[dict, dict]:
    """
    同時計算鷹派與鴿派詞的命中次數，回傳 (hawk_hits, dove_hits)。

    兩個詞典必須一起處理，並讓長詞優先、吃掉命中的區段：
      * "remains elevated"（2.5 分）命中後，其中的 "elevated"（2 分）
        不能再算一次——否則一個片語被計成 4.5 分
      * 鴿派的 "less restrictive" 命中後，其中的鷹派詞 "restrictive"
        不能再反向抵銷——否則明確轉鴿的句子會被計成中性
    """
    entries = ([(k, "h") for k in HAWKISH] + [(k, "d") for k in DOVISH])
    entries.sort(key=lambda e: len(e[0]), reverse=True)

    consumed: list[tuple[int, int]] = []
    hawk: dict[str, int] = {}
    dove: dict[str, int] = {}
    for phrase, tag in entries:
        pat = re.compile(r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])")
        n = 0
        for m in pat.finditer(text):
            if any(s < m.end() and m.start() < e for s, e in consumed):
                continue                      # 已被更長的片語吃掉
            consumed.append((m.start(), m.end()))
            n += 1
        if n:
            (hawk if tag == "h" else dove)[phrase] = n
    return hawk, dove


# ---------------------------------------------------------------------------
# 溝通制度變化偵測
# ---------------------------------------------------------------------------
def regime_change(docs: list) -> dict:
    """
    偵測「主席換人或溝通方式改變」造成的斷點。

    為什麼需要：措辭分數假設聲明的寫法穩定。當主席刻意縮短聲明、
    刪掉前瞻指引時，大量鷹派樣板句一起消失，詞典會誤判成轉鴿。
    這時應該**停用措辭分數並示警**，而不是輸出一個假的讀數。
    """
    ds = sorted(docs, key=lambda d: d.date)
    if len(ds) < 3:
        return {"detected": False}

    cur, prev = ds[-1], ds[-2]
    base = sum(d.word_count for d in ds[-5:-1]) / max(len(ds[-5:-1]), 1)
    shrink = 1 - (cur.word_count / base) if base else 0

    vanished = [p for p in TRACKED_PHRASES
                if prev.phrases.get(p, 0) > 0 and cur.phrases.get(p, 0) == 0]

    detected = shrink > 0.25 or len(vanished) >= 4
    return {
        "detected": detected,
        "shrink_pct": shrink * 100,
        "word_count": cur.word_count,
        "baseline": round(base),
        "vanished": vanished,
        "note": (
            f"這次聲明比近四次平均短了 {shrink*100:.0f}%，"
            f"且有 {len(vanished)} 個既有措辭整個消失。"
            "大量措辭同時消失通常代表溝通方式改變，而不是立場轉變——"
            "此時措辭分數不可靠，請以客觀訊號分數為準。"
        ) if detected else "",
    }


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
    """最近兩次的變化，兩個分數分開報。"""
    ds = sorted(docs, key=lambda d: d.date)
    if len(ds) < 2:
        return {}
    cur, prev = ds[-1], ds[-2]
    d_obj = cur.objective_score - prev.objective_score
    d_tone = cur.tone_score - prev.tone_score

    def lab(v, dv):
        if v > 1.0:
            return "偏鷹"
        if v < -1.0:
            return "偏鴿"
        return "中性"

    diverge = (cur.objective_score > 1.0 and cur.tone_score < -1.0) or \
              (cur.objective_score < -1.0 and cur.tone_score > 1.0)

    return {
        "cur_date": cur.date, "prev_date": prev.date,
        "objective": cur.objective_score, "objective_delta": d_obj,
        "objective_label": lab(cur.objective_score, d_obj),
        "tone": cur.tone_score, "tone_delta": d_tone,
        "tone_label": lab(cur.tone_score, d_tone),
        "diverge": diverge,
        # 對外的「方向」一律以客觀訊號為準
        "direction": ("hawkish" if cur.objective_score > 1.0
                      else ("dovish" if cur.objective_score < -1.0 else "neutral")),
        "label": lab(cur.objective_score, d_obj),
    }
