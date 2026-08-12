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
# 上限已經**不再是編輯上的限制**，只是防呆。
#
# 一路調過來的過程說明了為什麼：190 → 260 → 現在 500。每次調高都是因為
# 上限逼著模型在「把事實講完」與「不超過字數」之間二選一，而它每次都選
# 砍內容——出現過講到一半的總述、也出現過為了縮短就把整句重點句刪掉。
# 護欄的用途是攔住失控（某個分支寫出幾千字的鬼東西），不是逼稿子變短。
#
# 真正在控制長度的是提示詞裡的目標範圍（見 polish._target_range），
# 而那個範圍是從組裝版的實際長度算出來的——資料多就長一點，資料少就短
# 一點，本來就不該由一個寫死的數字決定。
# 想改的話 config/brief.yaml 的 max_chars 可以覆寫。
MIN_CJK, MAX_CJK = 90, 500


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
# 期別與訊號：兩件跟「時序」有關的事
# ---------------------------------------------------------------------------
def _month(data_month: str) -> str:
    """
    "2026-07" → "7 月"。空的就回空字串（不要編一個月份出來）。

    為什麼一定要標：這一段的數字全部是**上一期已公布**的資料，而不是當下。
    7 月的就業報告是 8 月才公布的——不標期別的話，讀者（以及潤稿模型
    加上去的「目前」「雖然」）都會把它讀成即時數據。
    模組卡上雖然有「2026-07 資料」，但總述常常被單獨閱讀或轉貼出去，
    那個標籤跟不過來。
    """
    s = (data_month or "").strip()
    if len(s) < 7 or "-" not in s:
        return ""
    try:
        return f"{int(s.split('-')[1])} 月"
    except (ValueError, IndexError):
        return ""


# 這些訊號講的事情，手寫的句子裡已經講過了——再挑一次就是同一件事說兩遍。
# 對照的是 _labor()／_inflation() 實際會寫出來的內容：
#   核心 PCE 相對門檻   → above_target／at_target／below_target
#   三個月年化 vs 年增   → cpi_reheating／cpi_cooling
#   核心服務除住房的黏性 → supercore_*
_COVERED = {
    "above_target", "at_target", "below_target",
    "cpi_reheating", "cpi_cooling",
    "supercore_hot", "supercore_cool", "supercore_reaccel",
}


def _pick_signal(flags, covered=_COVERED) -> str:
    """
    從該模組的訊號裡挑**一條**併進總述，回傳 headline；挑不到回空字串。

    為什麼要動態挑，不寫死清單：哪一條訊號重要**每一期都不一樣**。
    這一期是「前兩月大幅下修」，下一期可能是「失業率下降源於勞動力退出」，
    再下一期可能兩條都沒觸發。寫死等於把某一期的狀況當成常態。

    挑選規則完全是機械的：
      ① flags 進來時已依嚴重度排序（alert → watch → info），取第一條
      ② 跳過 _COVERED——那些手寫句子已經講過了
      ③ 只取 headline（規則引擎寫好的白話結論），不自己造句

    只挑一條：這一段的字數有限，而第二嚴重的那條通常跟第一條同向，
    加了是重複而不是資訊。
    """
    for f in flags or []:
        key = getattr(f, "key", "")
        if key in covered:
            continue
        head = (getattr(f, "headline", "") or "").strip()
        if head:
            return head
    return ""


# 「本次更新」最多講幾個數字。兩個剛好：一個是頭條、一個是佐證。
# 三個以上就變成流水帳，而讀者要的是「這次的重點是什麼」。
_NEW_MAX = 2

# 哪些指標屬於「這個模組的月度發布」。
#
# ⚠️ 一個模組裡不是每個指標都同一天更新。通膨模組同時放著 CPI（月中發布）、
# 核心 PCE（月底發布，來自 BEA）、通膨預期（每日）、油價（每週）。CPI 出爐
# 那天只有 CPI 是新的，但先前的程式把**整個模組**的變動都算成「本次更新」，
# 結果 CPI 發布日的摘要寫的是核心 PCE——那是上個月的數字。
#
# 所以用允許清單而不是排除清單：沒列到的一律不算「本次新增」。
# 寧可少講一項，也不要把別的發布日的數字冠上「本次」。
_RELEASE_KEYS = {
    "labor": {"nfp", "nfp_3m", "u3", "lfpr", "ahe_yoy"},
    # cpi_yoy 排在前面只是為了讀起來順；真正的排序是按變動幅度。
    # 這裡**不能**放 core_pce（BEA 月底發布）與 exp5y5y（每日）。
    "inflation": {"cpi_yoy", "core_cpi_yoy", "core_cpi_3m", "supercore"},
}


def _fmt_move(m: dict) -> str:
    """一條數字變動 → 「核心 CPI 年增 2.5%（上月 2.6%）」。"""
    unit = m.get("unit", "")
    to, frm = m.get("to"), m.get("from")
    if to is None or frm is None:
        return ""
    return f'{m.get("label", "")} {to:.1f}{unit}（上月 {frm:.1f}{unit}）'


def _whats_new(ctxs: dict) -> str:
    """
    開場前的一到兩句：**這一次新拿到的資料說了什麼。**

    為什麼要有：這一段每天都會重新產生，但多數日子的內容一樣——因為沒有
    新資料。讀者無從分辨「今天的數字是新的」與「今天只是把昨天那份重印
    一次」，而那正是他打開網站最想先知道的一件事。

    但光講「新資料已納入」沒有價值——那是流水帳，不是摘要。所以這裡要
    講**新的那份數據本身**：頭條數字是多少、比上一期高還是低、方向是什麼。
    材料全部來自 changes 模組已經算好的 metric_moves（跟「跟上期比什麼變了」
    那張卡同一組來源），只挑**這次剛發布的那個模組**的變動——非發布日的
    模組不該被算進「本次更新」。

    判斷「有沒有新資料」不在這裡做——`run.py` 的 `_fresh_releases()` 已經
    算好了，這裡拿到的 `ctxs["_fresh"]` 就是 `{模組: 期別}`，且只含
    **72 小時內才第一次看到**的期別。

    為什麼是 72 小時而不是「只在抓到的那一次執行顯示」：排程一天跑三次，
    發布當天你未必打開網站；只顯示一次的話，隔天想看就已經消失了。
    三天內的新數據叫「本次更新」還名副其實。
    """
    fresh_months = ctxs.get("_fresh") or {}
    if not fresh_months:
        return ""

    fresh = []                                     # [(模組鍵, 中文名, 期別字串)]
    for key, name in (("labor", "就業"), ("inflation", "物價")):
        month = fresh_months.get(key)
        if not month:
            continue
        ctx = ctxs.get(key) or {}
        m = _month(month)
        tag = "（速報）" if ctx.get("provisional") else ""
        fresh.append((key, name, f"{m}{tag}" if m else ""))
    if not fresh:
        return ""

    changes = ctxs.get("changes")
    moves = list(getattr(changes, "metric_moves", None) or [])
    keys = {k for k, _, _ in fresh}
    mine = [m for m in moves
            if m.get("module") in keys
            and m.get("key") in _RELEASE_KEYS.get(m.get("module"), set())]
    # 動得最多的排前面：這一次真正的重點是變化幅度最大的那一個，
    # 不是清單裡剛好排第一的那一個。
    mine.sort(key=lambda m: -abs(m.get("delta") or 0))

    head = "、".join(f"{n} {p}" if p else n for _, n, p in fresh)
    nums = [x for x in (_fmt_move(m) for m in mine[:_NEW_MAX]) if x]
    if not nums:
        # 有新資料但沒有任何指標動超過門檻——那本身就是資訊。
        return f"本次更新：{head}的新數據出爐，各項指標變動都在雜訊範圍內。"

    # 方向：這幾個變動整體偏哪一邊。用 changes 已經判好的 lean，
    # 不自己重算——重算會跟「跟上期比什麼變了」那張卡對不上。
    lean = [m.get("lean") for m in mine[:_NEW_MAX]]
    tail = ""
    if lean and all(x == "dovish" for x in lean if x):
        tail = "，方向偏降息"
    elif lean and all(x == "hawkish" for x in lean if x):
        tail = "，方向偏升息"
    return f"本次更新：{head}，{'；'.join(nums)}{tail}。"


# ---------------------------------------------------------------------------
# ② 就業
# ---------------------------------------------------------------------------
def _labor(ax: dict | None, month: str = "", signal: str = "") -> str:
    """
    就業：水準（失業率相對 FOMC 認定的充分就業區間）＋ 動能（Sahm／損益兩平）
    ＋ 這一期最嚴重的一條訊號。

    分支順序跟 scenario.classify_labor 一致，畫面上的敘述才不會跟格位打架。

    `month`（例如「7 月」）標在失業率前面。**必須標**：7 月的就業報告是
    8 月才公布的，不標的話讀者會把它讀成即時數據。
    """
    if not ax:
        return ""
    u = ax.get("unrate")
    lo, hi = ax.get("u_lo"), ax.get("u_hi")
    if u is None:
        return ""
    us = _pct(u)
    m = f"{month}" if month else ""
    sig = f"；{signal}" if signal else ""
    if ax.get("sahm_triggered"):
        return f"就業已在快速轉弱：{m}失業率 {us}，Sahm 法則觸發衰退門檻{sig}。"
    if lo is None or hi is None:
        return f"就業方面，{m}失業率 {us}{sig}。"

    n3, bk = ax.get("nfp_3m"), ax.get("breakeven")
    # 「三月均非農」在中文裡會被讀成「三月」（March）——這一段的數字是
    # 近三個月的平均，不是某個月份。寫成「近三個月平均」才沒有歧義；
    # 手上這份是 7 月數據，讀成 March 等於差了四個月。
    pair = (f"近三個月平均非農 {_wan(n3)}低於損益兩平的 "
            f"{_wan(bk).replace(' 萬人', ' 萬')}"
            if n3 is not None and bk is not None else "")
    if u > hi:
        return (f"{m}失業率 {us} 已高於聯準會認定的充分就業上緣 "
                f"{_pct(hi)}{sig}。")
    if ax.get("below_breakeven") and pair:
        return f"{m}失業率 {us} 仍算充分就業，但{pair}，撐不住現有失業率{sig}。"
    if u < lo:
        return f"{m}失業率 {us} 低於充分就業下緣 {_pct(lo)}，勞動市場仍緊{sig}。"
    return f"{m}失業率 {us} 落在充分就業區間 {_pct(lo)}–{_pct(hi)} 之內{sig}。"


# ---------------------------------------------------------------------------
# ③ 通膨
# ---------------------------------------------------------------------------
def _inflation(s, bands: dict | None, state: str,
               month: str = "", signal: str = "") -> str:
    """通膨：水準相對門檻 ＋ 動能（三個月年化 vs 年增）＋ 黏性 ＋ 一條訊號。"""
    if s is None or getattr(s, "pce_core_yoy", None) is None:
        return ""
    yoy, m3 = s.pce_core_yoy, getattr(s, "pce_core_3m", None)
    head = f"{month}核心 PCE {_pct(yoy)}" if month else f"核心 PCE {_pct(yoy)}"
    mo = ""
    if m3 is not None:
        # 「三月年化」同樣會被讀成 March。講的是最近三個月換算成年率。
        if m3 > yoy + 0.2:
            mo = f"、三個月年化 {_pct(m3)} 仍在加速"
        elif m3 < yoy - 0.2:
            mo = f"、三個月年化 {_pct(m3)} 已在放緩"
        else:
            mo = f"、三個月年化 {_pct(m3)} 持平"

    # 水準只講「相對門檻在哪一側」，不重印門檻數字——門檻在情境頁的
    # 「這一格是怎麼判出來的」有完整交代，這裡重印一次只是佔字數。
    lvl = {"高": "，仍高於聯準會對明年的預測",
           "低": "，已回到門檻之下"}.get(state, "")

    st = getattr(s, "supercore_streak", None)
    sticky = ""
    if st:
        sticky = (f"；核心服務除住房{'連' if st > 0 else '已連'} {abs(st)} "
                  "個月高於目標")
    sig = f"；{signal}" if signal else ""
    return head + mo + lvl + sticky + sig + "。"


# ---------------------------------------------------------------------------
# ④ 聯準會
# ---------------------------------------------------------------------------
def _fomc(f: dict | None) -> str:
    """最近一次會議做了什麼、有沒有人反對、下次什麼時候。"""
    if not f or f.get("empty"):
        return ""
    # 「7/29 會議」跟同一段裡的「7 月失業率」都長得像七月，但一個是
    # **會議日期**、一個是**資料期別**。加「上次」兩個字就分得開了。
    _d = (f.get("latest_date") or "")
    date = (f"上次會議（{int(_d[5:7])}/{int(_d[8:10])}）"
            if len(_d) >= 10 else "最近一次會議")
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

    # 期別與訊號都從模組**已經算好的結果**取，這一層不做任何判斷。
    # 訊號每一期都不一樣，所以是動態挑（見 _pick_signal），不是寫死清單。
    def _mon(ctx):
        """期別；若是 BLS 速報值就標出來——來源不同，讀者有權知道。"""
        m = _month((ctx or {}).get("data_month", ""))
        return f"{m}（速報）" if m and (ctx or {}).get("provisional") else m

    lab_txt = _labor((lab or {}).get("axis"), _mon(lab),
                     _pick_signal((lab or {}).get("flags")))
    inf_txt = _inflation((inf or {}).get("summary"),
                         (inf or {}).get("bands"),
                         getattr(sc, "infl_state", "") if sc else "",
                         _mon(inf),
                         _pick_signal((inf or {}).get("flags")))
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
        ("whatsnew", _whats_new(ctxs)),
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
