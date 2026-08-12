"""
整體總述：把五個模組的結論壓成一段約 150 字、10–20 秒讀得完的散文。

為什麼要有這一段
----------------
首頁原本只有「情境名稱 ＋ 一句話」加一堆分區卡片。要知道「現在到底怎麼回事」，
讀者得自己把五張卡的結論組起來——而那正是他來這個網站的原因。

這一段回答五件事，順序固定：

    ① 政策方向與各模組的共識度
    ② 就業（水準 ＋ 動能）
    ③ 通膨（水準 ＋ 動能 ＋ 黏性）
    ④ 聯準會最近一次會議做了什麼、下次什麼時候
    ⑤ 財政與 AI 資本支出如何一起推長端供給

三條規矩
--------
**一、沒有任何一句是寫死的模板。** 每一段都從對應模組**已經算好的判定**取值，
所以任何一個模組的資料一更新（月頻的就業與 CPI、會後的聲明、季頻的 SEC 財報、
每天的殖利率），這段話就跟著變。不是「每天重印同一段」。

**二、不用模型生成敘述。** 這是整個專案的核心原則：量化與判定走確定性規則，
每次執行結果一致、可回測。總述也不例外——它是**組裝**，不是**寫作**。
分支條件全部寫在下面，看得到、測得到。

**三、寧可少講一段，不硬湊。** 某個模組沒有資料時，那一段直接不出現，
其餘照樣成立。硬填「資料不足」只是佔字數。

長度
----
目標 150 字上下。連續散文在這個長度大約要讀 20–30 秒——比「掃過去」慢，
但這是使用者選的形式（讀起來最像法人早報）。上限 220 字由測試釘住：
超過就代表某個分支寫得太囉唆，那會直接毀掉「一眼看完」這件事。
"""

from __future__ import annotations

import re

_CJK = re.compile(r"[\u4e00-\u9fff]")


def cjk_len(s: str) -> int:
    """中文字數。長度護欄與測試都用這個，不用 len()。"""
    return len(_CJK.findall(s or ""))

# 各段之間不加空格：中文句號本身就是分隔，加了反而鬆散。
JOIN = ""

# 長度護欄。低於下限多半是模組缺資料（那是真的，不該補字）；
# 超過上限就是某個分支寫太長，測試會擋下來。
# 量的是**中文字數**，不是字串長度：數字、百分號、PCE／GDP／AI 這些
# 拉丁字母在視覺上佔的寬度與閱讀負擔都跟漢字不同，用 len() 量會被它們灌水
#（同一段話 len 是 238、中文字只有 154）。
# 組裝版目標 160–180 字。上限放到 260 是留給**潤稿版**的空間：
# 先前上限 190，跟組裝版的實際長度（179）只差 11 字，等於逼著模型在
# 「把六段事實都講完」與「不超過上限」之間二選一——實測的結果是它選了
# 砍掉最後一段，畫面上出現一句話講到一半的總述。
# 護欄的用途是擋住失控，不是逼稿子變短；真正在控制長度的是提示詞裡的
# 目標範圍（見 polish._target_range），護欄只負責攔住離譜的輸出。
MIN_CJK, MAX_CJK = 90, 260


def _pct(v, d=1):
    return None if v is None else f"{v:.{d}f}%"


def _wan(v):
    """千人 → 萬人，帶正負號。"""
    return None if v is None else f"{v / 10:+.1f} 萬人"


# 「兩」不是「二」：中文數東西用「兩」。「三方裡二方」讀起來就是不對。
_CN_NUM = "〇一兩三四五六七八九"


def _cn(n: int) -> str:
    """一位數改用中文數字。「三方裡兩方」比「3 方裡 2 方」像人話。"""
    return _CN_NUM[n] if 0 <= n <= 9 else str(n)


# ---------------------------------------------------------------------------
# ① 方向與共識
# ---------------------------------------------------------------------------
# 開場只講「誰優先」。「所以會怎樣」留給結尾的重點句——
# 先前開場句就把含意講完，重點句加進來之後同一件事會出現兩次。
_REGIME_LEAD = {
    "inflation": "聯準會把通膨擺在前面",
    "employment": "聯準會把就業擺在前面",
    "balanced": "聯準會兩個使命並重",
}


def _direction(sc, dirs: list) -> str:
    """
    政策方向 ＋ 三個模組的共識度。

    共識度先前是結論卡上的三個色塊加一句話，佔掉半張卡卻只顯示 12 個字；
    它回答的是「各模組同不同意」，本來就屬於總述的第一句。
    """
    if sc is None:
        return ""
    lead = _REGIME_LEAD.get(getattr(sc, "regime", ""), "")
    if not lead:
        return ""
    n_haw = sum(1 for _, d in dirs if d == "hawkish")
    n_dov = sum(1 for _, d in dirs if d == "dovish")
    n = len(dirs)
    # 有模組判不出方向時，「N 個裡 M 個」會少掉一塊、讀者會自己去補那個差額。
    # 直接講清楚剩下的是中性。
    if n < 2 or not (n_haw or n_dov):
        tail = "。"
    elif n_haw and n_dov:
        # 多數那一邊先講。「三方裡兩方偏降息、一方偏升息」讀起來是先給結論，
        # 固定把升息排前面則會變成先給少數派，方向感是反的。
        a, b = (("升", n_haw), ("降", n_dov))
        if n_dov > n_haw:
            a, b = (("降", n_dov), ("升", n_haw))
        tail = (f"；{_cn(n)}方裡{_cn(a[1])}方偏{a[0]}息、"
                f"{_cn(b[1])}方偏{b[0]}息，方向分歧。")
    elif n_haw == n or n_dov == n:
        tail = f"；{_cn(n)}方一致偏{'升' if n_haw else '降'}息。"
    else:
        tail = (f"；{_cn(n)}方裡{_cn(max(n_haw, n_dov))}方偏"
                f"{'升' if n_haw else '降'}息、其餘中性。")
    return lead + tail


# ---------------------------------------------------------------------------
# ② 就業
# ---------------------------------------------------------------------------
def _labor(ax: dict | None) -> str:
    """
    就業：水準（失業率相對 FOMC 認定的充分就業區間）＋ 動能（Sahm／損益兩平）。

    分支順序跟 scenario.classify_labor 一致，畫面上的敘述才不會跟格位打架。
    """
    if not ax:
        return ""
    u = ax.get("unrate")
    lo, hi = ax.get("u_lo"), ax.get("u_hi")
    if u is None:
        return ""
    us = _pct(u)
    if ax.get("sahm_triggered"):
        return f"就業已在快速轉弱：失業率 {us}，Sahm 法則觸發衰退門檻。"
    if lo is None or hi is None:
        return f"就業方面，失業率 {us}。"

    n3, bk = ax.get("nfp_3m"), ax.get("breakeven")
    pair = (f"三月均非農 {_wan(n3)}低於損益兩平的 {_wan(bk).replace(' 萬人', ' 萬')}"
            if n3 is not None and bk is not None else "")
    if u > hi:
        return f"失業率 {us} 已高於聯準會認定的充分就業上緣 {_pct(hi)}。"
    if ax.get("below_breakeven") and pair:
        return (f"失業率 {us} 仍算充分就業，但{pair}，撐不住現有失業率。")
    if u < lo:
        return f"失業率 {us} 低於充分就業下緣 {_pct(lo)}，勞動市場仍緊。"
    return f"失業率 {us} 落在充分就業區間 {_pct(lo)}–{_pct(hi)} 之內。"


# ---------------------------------------------------------------------------
# ③ 通膨
# ---------------------------------------------------------------------------
def _inflation(s, bands: dict | None, state: str) -> str:
    """通膨：水準相對門檻 ＋ 動能（三月年化 vs 年增）＋ 核心服務的黏性。"""
    if s is None or getattr(s, "pce_core_yoy", None) is None:
        return ""
    yoy, m3 = s.pce_core_yoy, getattr(s, "pce_core_3m", None)
    head = f"核心 PCE {_pct(yoy)}"
    mo = ""
    if m3 is not None:
        if m3 > yoy + 0.2:
            mo = f"、三月年化 {_pct(m3)} 仍在加速"
        elif m3 < yoy - 0.2:
            mo = f"、三月年化 {_pct(m3)} 已在放緩"
        else:
            mo = f"、三月年化 {_pct(m3)} 持平"

    # 水準只講「相對門檻在哪一側」，不重印門檻數字——門檻在情境頁的
    # 「這一格是怎麼判出來的」有完整交代，這裡重印一次只是佔字數。
    lvl = {"高": "，仍高於聯準會對明年的預測",
           "低": "，已回到門檻之下"}.get(state, "")

    st = getattr(s, "supercore_streak", None)
    sticky = ""
    if st:
        sticky = (f"；核心服務除住房{'連' if st > 0 else '已連'} {abs(st)} "
                  "個月高於目標")
    return head + mo + lvl + sticky + "。"


# ---------------------------------------------------------------------------
# ④ 聯準會
# ---------------------------------------------------------------------------
def _fomc(f: dict | None) -> str:
    """最近一次會議做了什麼、有沒有人反對、下次什麼時候。"""
    if not f or f.get("empty"):
        return ""
    _d = (f.get("latest_date") or "")
    date = f"{int(_d[5:7])}/{int(_d[8:10])} 會議" if len(_d) >= 10 else "最近一次會議"
    act = (f.get("obj_parts") or {}).get("action_label") or "維持不變"
    vote = f.get("vote") or {}
    dis = vote.get("dissents") or []
    if dis:
        dirs = {d.get("direction") for d in dis if isinstance(d, dict)}
        want = ("主張升息" if dirs == {"hike"} else
                ("主張降息" if dirs == {"cut"} else "反對"))
        vtxt = f"、{len(dis)} 票{want}"
    else:
        vtxt = "、全票通過"
    nm = f.get("next_meeting") or {}
    nxt = f"，下次會議 {nm['days']} 天後" if nm.get("days") is not None else ""
    return f"{date}{act}{vtxt}{nxt}。"


# ---------------------------------------------------------------------------
# ⑤ 財政與 AI
# ---------------------------------------------------------------------------
_PRESSURE_TAIL = {
    "high": "降息也壓不下長端",
    "moderate": "長端大致跟著政策走",
    "low": "長端還有額外下行空間",
}


def _supply(rt: dict | None) -> str:
    """
    財政與 AI：兩者都指向同一件事——長端的債券供給。

    政府發公債、AI 資本支出迫使科技巨頭從淨買方變成淨賣方，兩者搶的是
    同一池存續期間需求。所以這一段的結論不是「財政如何」「AI 如何」，
    而是「長端會不會跟著政策走」——那才是對債券部位有意義的問題。
    """
    if not rt:
        return ""
    p = rt.get("pressure")
    if p is None:
        return ""
    tail = _PRESSURE_TAIL.get(getattr(p, "level", ""), "")
    if not tail:
        return ""
    hs = rt.get("hyperscalers")
    ratio = getattr(hs, "capex_to_ocf", None) if hs else None
    debt = rt.get("debt")
    pb = getattr(debt, "pb_gap", None) if debt else None

    bits = []
    if pb is not None:
        bits.append(f"財政缺口 {abs(pb):.1f}% GDP")
    if ratio is not None:
        bits.append(f"AI 資本支出佔營運現金流 {ratio:.0f}%")
    if bits:
        return f"{' 與 '.join(bits)}，同推長端供給，{tail}。"
    return f"長端供給壓力{'偏高' if p.level == 'high' else '不高'}，{tail}。"


# ---------------------------------------------------------------------------
# ⑥ 重點句：升降息的可能性、以及什麼會改變它
# ---------------------------------------------------------------------------
def _takeaway(sc, fom: dict | None) -> str:
    """
    收尾的一句話：**下一步是升還是降、解鎖條件是什麼**。

    材料全部是已經算好的判定：九宮格的政策傾向（lean）、「情境轉換門檻」
    裡標成關鍵的那一條觸發條件、以及反對票的方向。沒有新的判斷——
    這句只是把散在三張卡的東西收成一句。

    找不到關鍵觸發條件時退而用第一條未觸發的；連觸發條件都沒有時，
    句子照樣成立（只講方向，不講條件）。
    """
    if sc is None:
        return ""
    lean = getattr(sc, "lean", "") or ""
    trigs = getattr(sc, "triggers", None) or []
    trig = next((x for x in trigs if getattr(x, "binding", False)), None)
    if trig is None:
        trig = next((x for x in trigs if not getattr(x, "met", False)), None)

    cond = ""
    if trig is not None:
        if getattr(trig, "met", False):
            cond = f"，{trig.label}的條件已經達成"
        else:
            cond = f"，解鎖條件是{trig.label}（{trig.distance}）"

    dis = ((fom or {}).get("vote") or {}).get("dissents") or []
    hikes = sum(1 for d in dis if isinstance(d, dict)
                and d.get("direction") == "hike")
    cuts = sum(1 for d in dis if isinstance(d, dict)
               and d.get("direction") == "cut")

    if lean == "hawkish":
        tail = "；升息風險未消" if hikes else ""
        return f"重點：降息還遠{cond}{tail}。"
    if lean == "dovish":
        tail = "；委員會內部已有人主張先動" if cuts else ""
        return f"重點：下一步以降息為主{cond}{tail}。"
    return f"重點：按兵不動的可能性最高{cond}。"


# ---------------------------------------------------------------------------
def compose(ctxs: dict) -> dict:
    """
    回傳 {"text", "chars", "parts"}。任何一段缺資料就跳過，其餘照樣成立。

    parts 一併回傳是為了測試與除錯：哪一段太長、哪一段沒出現，
    看 parts 比看拼好的字串快。
    """
    scn = ctxs.get("scenario") or {}
    sc = scn.get("scenario")
    lab, inf, fom, rt = (ctxs.get("labor"), ctxs.get("inflation"),
                         ctxs.get("fomc"), ctxs.get("rates"))

    # 各模組的方向：跟首頁共識列同一組來源，數字才不會兩處對不上
    dirs = []
    if lab:
        dirs.append(("就業", (lab.get("tilt") or {}).get("tilt")))
    if inf:
        dirs.append(("物價", (inf.get("tilt") or {}).get("tilt")))
    if fom and not fom.get("empty"):
        _s = (fom.get("shift") or {}).get("direction")
        dirs.append(("聯準會", _s))

    lab_txt = _labor((lab or {}).get("axis"))
    inf_txt = _inflation((inf or {}).get("summary"),
                         (inf or {}).get("bands"),
                         getattr(sc, "infl_state", "") if sc else "")
    # 轉折詞：就業與通膨指向相反（弱 × 高）時補一個「另一頭」，
    # 讀者才不會把兩句當成同方向的並列。同向時不加——加了反而誤導。
    if (lab_txt and inf_txt and sc is not None
            and getattr(sc, "labor_state", "") == "弱"
            and getattr(sc, "infl_state", "") == "高"):
        inf_txt = "另一頭，" + inf_txt
    fom_txt = _fomc(fom)
    if fom_txt and lab_txt and inf_txt:
        fom_txt = "面對這個組合，" + fom_txt

    parts = [
        ("direction", _direction(sc, dirs)),
        ("labor", lab_txt),
        ("inflation", inf_txt),
        ("fomc", fom_txt),
        ("supply", _supply(rt)),
        ("takeaway", _takeaway(sc, fom)),
    ]
    kept = [(k, v) for k, v in parts if v]
    text = JOIN.join(v for _, v in kept)
    return {"text": text, "chars": cjk_len(text), "raw_len": len(text),
            "parts": [{"key": k, "text": v, "chars": cjk_len(v)}
                      for k, v in kept]}
