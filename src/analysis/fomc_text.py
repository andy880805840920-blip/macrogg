"""
FOMC 文本與投票分析（P3）。

設計原則
--------
**計分與詞頻走純規則，不交給模型。**

兩個分數並列，刻意不合成
------------------------
  1. 客觀訊號分數：反對票方向與人數 + 點陣圖分布
  2. 措辭分數：聲明用語的鷹鴿詞典計分

合成會掩蓋最有價值的資訊——**兩者背離時，背離本身就是訊號**。
2026 年 7 月正是如此：措辭因為主席刻意縮短聲明而讀起來偏鴿，
但三張贊成升息的反對票與點陣圖都指向偏鷹，市場也照後者走。

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
    objective_score: float = 0.0     # 客觀訊號分數（反對票 + 點陣圖）
    obj_parts: dict = field(default_factory=dict)
    hawk_hits: dict = field(default_factory=dict)
    dove_hits: dict = field(default_factory=dict)
    phrases: dict = field(default_factory=dict)
    vote: dict = field(default_factory=dict)
    dots: dict = field(default_factory=dict)
    has_presser: bool = False
    presser_score: float | None = None
    text: str = ""


def analyse(doc: dict, dots: dict | None = None) -> DocAnalysis:
    """doc: {date, text, vote?, presser?}"""
    clean = _normalise(doc.get("text", ""))
    words = len(clean.split())

    hawk_hits = _count(clean, HAWKISH)
    dove_hits = _count(clean, DOVISH)
    denom = max(words, 1) / 100
    tone = (sum(HAWKISH[k] * v for k, v in hawk_hits.items())
            - sum(DOVISH[k] * v for k, v in dove_hits.items())) / denom

    vote = doc.get("vote") or {}
    obj, parts = objective_score(vote, dots)

    presser = doc.get("presser")
    p_score = None
    if presser:
        pc = _normalise(presser)
        pd = max(len(pc.split()), 1) / 100
        p_score = ((sum(HAWKISH[k] * pc.count(k) for k in HAWKISH if k in pc)
                    - sum(DOVISH[k] * pc.count(k) for k in DOVISH if k in pc)) / pd)

    return DocAnalysis(
        date=doc["date"], word_count=words,
        tone_score=round(tone, 3), objective_score=round(obj, 3),
        obj_parts=parts, hawk_hits=hawk_hits, dove_hits=dove_hits,
        phrases={p: clean.count(p) for p in TRACKED_PHRASES},
        vote=vote, dots=dots or {}, has_presser=bool(presser),
        presser_score=None if p_score is None else round(p_score, 3),
        text=clean,
    )


def objective_score(vote: dict, dots: dict | None) -> tuple[float, dict]:
    """
    客觀訊號分數。正＝偏鷹、負＝偏鴿。

    反對票：每一張贊成升息的反對票 +2，贊成降息 −2。
            反對票是客觀事實，不受主席的措辭風格影響，所以權重最高。
    點陣圖：預期升息與預期降息的官員人數差，除以總人數再乘 4。
            一季才更新一次，但比任何措辭都實在。
    """
    parts = {}
    hawk = sum(1 for d in (vote.get("dissents") or []) if d.get("direction") == "hike")
    dove = sum(1 for d in (vote.get("dissents") or []) if d.get("direction") == "cut")
    parts["dissent"] = 2.0 * (hawk - dove)
    parts["dissent_detail"] = f"贊成升息 {hawk} 票、贊成降息 {dove} 票"

    total = (dots or {}).get("total")
    up = (dots or {}).get("hike")
    if dots and total and up is not None:
        down = dots.get("cut")
        if down is not None:
            # 升息與降息人數都已知：用兩者的差
            parts["dots"] = 4.0 * (up - down) / total
            parts["dots_detail"] = (f"{total} 位提交預測的官員中，"
                                    f"{up} 位預期升息、{down} 位預期降息")
        else:
            # 官方摘要常只說「其餘為不變或更低」，沒有拆出降息人數。
            # 這時只能用「預期升息的比例是否超過一半」來衡量，不硬猜降息人數。
            parts["dots"] = 4.0 * (2 * up / total - 1)
            rest = dots.get("hold_or_cut", total - up)
            parts["dots_detail"] = (f"{total} 位提交預測的官員中，"
                                    f"{up} 位預期升息、{rest} 位預期不變或更低"
                                    "（官方未拆分降息人數）")
    else:
        parts["dots"] = 0.0
        parts["dots_detail"] = "尚無點陣圖資料"

    return parts["dissent"] + parts["dots"], parts


def _normalise(t: str) -> str:
    return re.sub(r"\s+", " ", t).lower().strip()


def _count(text: str, lexicon: dict) -> dict:
    return {k: text.count(k) for k in lexicon if k in text}


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
