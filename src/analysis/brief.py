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
JOIN = "\n"

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
    # 月步速訊號：重點句（_takeaway）已經在講 0.2 準則，組裝版再挑
    # 這幾條就是同一件事同段講兩次
    "pace_hot", "pace_above", "pace_ontrack",
    # 失業率回升／Sahm 家族：勞動手寫句已涵蓋（「惡化已經開始」
    # ／「快速轉弱」），挑了必重複
    "u3_rising", "sahm_trigger", "sahm_approaching",
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
# 每一種發布：對應變化引擎的哪個單位、准講哪些指標、報告名稱怎麼寫。
# 內容白名單的用意：CPI 日不講 PCE（那是月底另一份發布）、
# 就業報告日不講失業金（那是每週四自己的一份）。
_RELEASES = {
    "labor": {"module": "labor", "label": "就業報告",
              "keys": {"nfp", "nfp_3m", "u3", "lfpr", "ahe_yoy"}},
    "inflation": {"module": "inflation", "label": " CPI",
                  "keys": {"cpi_yoy", "core_cpi_yoy", "core_cpi_3m",
                           "supercore"}},
    # PCE 由 BEA 月底發布：推估值換成實際值、九宮格通膨軸重判——
    # 對讀者是一個月裡最值得知道的更新之一
    "pce": {"module": "inflation", "label": " PCE", "keys": {"core_pce"}},
    "claims": {"module": "claims", "label": " 失業金申請",
               "keys": {"ic_ma", "cc"}},
    "jolts": {"module": "jolts", "label": " JOLTS",
              "keys": {"openings", "quits", "layoffs", "hires"}},
    # FOMC 沒有數字指標，句子另組（見 _whats_new 的 fomc 段）
    "fomc": {"module": "fomc", "label": " FOMC 會議", "keys": set()},
}


def _fmt_move(m: dict) -> str:
    """一條數字變動 → 「核心 CPI 年增 2.5%（上月 2.6%）」。"""
    unit = m.get("unit", "")
    to, frm = m.get("to"), m.get("from")
    if to is None or frm is None:
        return ""
    # 對照基準的量詞跟著單位的節奏走：失業金與市場是週輪替
    prev = "上週" if m.get("module") in ("claims", "market") else "上月"
    return f'{m.get("label", "")} {to:.1f}{unit}（{prev} {frm:.1f}{unit}）'


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

    def _vint(key: str, raw: str) -> str:
        """期別 → 人話：月份「7 月」、週「週結 8/15」、會議日「7/29」。"""
        raw = raw or ""
        parts = raw.split("-")
        try:
            if len(parts) == 3:
                d = f"{int(parts[1])}/{int(parts[2])}"
                return f"週結 {d}" if key == "claims" else d
            if len(parts) == 2:
                return _month(raw)
        except ValueError:
            pass
        return raw

    fresh = []                                     # [(發布鍵, 期別字串)]
    for key, cfg_r in _RELEASES.items():
        vint = fresh_months.get(key)
        if not vint:
            continue
        tag = ""
        if key in ("labor", "inflation"):
            tag = ("（速報）" if (ctxs.get(key) or {}).get("provisional")
                   else "")
        m = _vint(key, vint)
        label = cfg_r["label"]
        fresh.append((key, f"{m}{label}{tag}" if m else label.strip()))
    if not fresh:
        return ""

    changes = ctxs.get("changes")
    moves = list(getattr(changes, "metric_moves", None) or [])
    # 每一種發布只准講自己的指標：發布鍵 → (變化引擎單位, 白名單)。
    # 同一單位可能對到兩種發布（CPI 與 PCE 都在 inflation），
    # 白名單就是把它們分開的東西。
    _allowed = set()
    for key, _ in fresh:
        r = _RELEASES[key]
        _allowed |= {(r["module"], k) for k in r["keys"]}
    mine = [m for m in moves
            if (m.get("module"), m.get("key")) in _allowed]
    # ---- 排序：動得最多的排前面，但「多」要先換成同一把尺 ----
    #
    # 先前是 `sort(key=lambda m: -abs(m["delta"]))`——**直接比原始變動量，
    # 而那些量的單位不一樣**。非農以「萬人」計、CPI 以「個百分點」計，
    # 於是 5.7（萬人）永遠大於 0.33（個百分點），**就業一旦同時是新的，
    # 通膨就永遠擠不進去**。使用者剛看完 CPI 出爐，開頭句寫的卻是兩條非農。
    #
    # 換算的尺用每個指標自己的 `threshold`（雜訊門檻）——那本來就是
    # 按各自單位訂的，改用「動了幾倍的雜訊」就能跨指標比：
    #
    #     非農三個月均　5.7 萬人 ÷ 1 萬人　　　＝ 5.7 倍
    #     核心 CPI 年增　0.33 個百分點 ÷ 0.05　＝ 6.6 倍　← 這才是重點
    def _mag(m):
        thr = m.get("threshold") or 0
        d = abs(m.get("delta") or 0)
        return d / thr if thr else d

    mine.sort(key=lambda m: -_mag(m))

    # ---- 每個剛發布的模組至少講一個 ----
    #
    # 光排序還不夠：兩個模組同時是新的時候，前兩名仍可能都來自同一邊。
    # 讀者剛在新聞上看到 CPI，開頭句卻整句在講就業——那不是摘要，是漏報。
    # 所以先從每個模組各取它自己的第一名，再按幅度填滿剩下的名額。
    # 名額：平常 2 個；同一天有三種以上發布時放寬到「每種至少一個」
    #（先前固定 2 會讓第三種發布被擠掉，變成漏報）。
    _limit = max(_NEW_MAX, len(fresh))
    picked, seen_mod = [], set()
    for m in mine:
        if m.get("module") not in seen_mod:
            picked.append(m)
            seen_mod.add(m.get("module"))
    for m in mine:
        if len(picked) >= _limit:
            break
        if m not in picked:
            picked.append(m)
    picked.sort(key=lambda m: -_mag(m))            # 名單定了再照幅度排序
    picked = picked[:_limit]

    head = "與 ".join(p for _, p in fresh)
    nums = [x for x in (_fmt_move(m) for m in picked) if x]
    # FOMC 沒有數字指標，句子從 ctx 另組：做了什麼＋客觀訊號分數
    if any(k == "fomc" for k, _ in fresh):
        fom = ctxs.get("fomc") or {}
        _act = ((fom.get("obj_parts") or {}).get("action_label") or "")
        _obj = (fom.get("shift") or {}).get("objective")
        _ftxt = (f"本次{_act}" if _act else "聲明與投票已更新")
        if _obj is not None:
            _ftxt += f"、客觀訊號 {_obj:+.2f}"
        nums.insert(0, _ftxt)
    if not nums:
        # 有新資料但沒有任何指標動超過門檻——那本身就是資訊。
        return f"本次更新：{head}的新數據出爐，各項指標變動都在雜訊範圍內。"

    # 方向：這幾個變動整體偏哪一邊。用 changes 已經判好的 lean，
    # 不自己重算——重算會跟「跟上期比什麼變了」那張卡對不上。
    # 用 picked 不是 mine——方向要對應**畫面上真的寫出來的那幾個**。
    lean = [m.get("lean") for m in picked]
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

    _rise = ax.get("sahm")
    pair = (f"失業率已較近一年低點回升 {_rise:.2f} 個百分點"
            if _rise is not None else "失業率已開始回升")
    if u > hi:
        return (f"{m}失業率 {us} 已高於聯準會認定的充分就業上緣 "
                f"{_pct(hi)}{sig}。")
    if ax.get("u3_rising"):
        return f"{m}失業率 {us} 仍算充分就業，但{pair}，惡化已經開始{sig}。"
    if u < lo:
        return f"{m}失業率 {us} 低於充分就業下緣 {_pct(lo)}，勞動市場仍緊{sig}。"
    return f"{m}失業率 {us} 落在充分就業區間 {_pct(lo)}–{_pct(hi)} 之內{sig}。"


# ---------------------------------------------------------------------------
# ③ 通膨
# ---------------------------------------------------------------------------
def _inflation(s, bands: dict | None, state: str,
               month: str = "", signal: str = "",
               pce_month: str = "") -> str:
    """
    通膨：水準相對門檻 ＋ 動能（三個月年化 vs 年增）＋ 黏性 ＋ 一條訊號。

    **`month` 與 `pce_month` 不是同一件事，這一段的第一個數字用的是後者。**

    使用者抓到的：整體情勢寫「7 月核心 PCE 3.3%」，但核心 PCE 的 7 月數字
    要 8 月底才由 BEA 公布，當時最新的是 6 月。原因是這裡只收一個
    `month`——那是**通膨模組的 data_month，也就是 CPI 的期別**——然後套給
    整段裡的每一個數字。

    通膨模組裡不同來源的節奏差很多：CPI 月中（BLS）、核心 PCE 月底（BEA）、
    通膨預期每日、油價每週。拿一個期別去標整段，只要講的不是 CPI 就會標錯，
    而**標錯的樣子看起來完全正常**——「7 月核心 PCE」讀起來一點問題都沒有，
    除非你剛好知道它還沒公布。

    正確的期別 build 早就算好放在 ctx 的 `asof` 裡（KPI 卡也在用），
    這裡只是沒接上。規則很簡單：**誰的數字就標誰的期別。**
    """
    if s is None or getattr(s, "pce_core_yoy", None) is None:
        return ""
    yoy, m3 = s.pce_core_yoy, getattr(s, "pce_core_3m", None)
    pm = pce_month or month
    # 照傳導順序把整條鏈講完：CPI（含核心）→ 上游核心 PPI → PCE。
    # 先前只講 PCE——那是九宮格在用的數字，但 CPI 才是新聞當天
    # 讀者在對的數字，PPI 是它的上游，三者缺兩個等於敘事鏈斷頭。
    cpi, core = getattr(s, "headline_yoy", None), getattr(s, "core_yoy", None)
    ppi = getattr(s, "ppi_core_yoy", None)
    chain = ""
    if cpi is not None:
        chain = (f"{month} CPI 年增 {_pct(cpi)}" if month
                 else f"CPI 年增 {_pct(cpi)}")
        if core is not None:
            chain += f"（核心 {_pct(core)}）"
        if ppi is not None:
            chain += f"、上游核心 PPI {_pct(ppi)}"
        chain += "；"
    head = chain + (f"{pm}核心 PCE {_pct(yoy)}" if pm else f"核心 PCE {_pct(yoy)}")
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


# ---------------------------------------------------------------------------
# ⑥ 重點句：升降息的可能性、以及什麼會改變它
# ---------------------------------------------------------------------------
def _takeaway(sc, fom: dict | None, inf: dict | None = None) -> str:
    """
    收尾的一句話。先問對問題，再講條件——使用者的批評：舊模板永遠圍繞
    「降息還遠不遠」，但目前市場真正辯論的是「要不要升息」，而且綁住
    政策的是通膨；重點句卻在講降息的解鎖條件，問錯了問題。

    三態由九宮格的政策傾向（lean）決定問題框架；重心軸由 scenario 的
    binding（約束條件在哪一軸）動態選定，不寫死通膨——哪天就業惡化成為
    關鍵約束，這句話會自動轉向就業。句中的數字全部取自已算好的月步速
    判定，跟九宮格同一套口徑。
    """
    if sc is None:
        return ""
    lean = getattr(sc, "lean", "") or ""
    binding = getattr(sc, "binding", "") or ""
    pace = (inf or {}).get("core_pace3")
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

    # 長度紀律：一句主張＋一個條件就夠。**數字不在這裡複述**——
    # 通膨 bullet 已以關鍵訊號為主體講「連 N 個月高於 0.2%（近三月
    # X%）」，重點句再帶一次數字就是同段講兩遍（使用者抓到過）。
    # 重點句只負責：問題框架、解鎖條件、委員會動態。
    if lean == "hawkish":
        tail = "；委員會內已有升息主張" if hikes else ""
        if binding != "就業" and pace is not None:
            return ("重點：問題是升不升息、不是何時降息——關鍵在通膨"
                    f"月步速；回到 0.2% 以下壓力解除{tail}。")
        return f"重點：政策風險偏向升息{cond}{tail}。"
    if lean == "dovish":
        tail = "；委員會內已有人主張先動" if cuts else ""
        return f"重點：討論的是降息時點{cond}{tail}。"
    if pace is not None:
        return ("重點：最可能按兵不動，下一步看通膨——月步速回到 0.2% "
                "以下偏降息、再加速偏升息。")
    return f"重點：按兵不動的可能性最高{cond}。"


# ---------------------------------------------------------------------------
# AI 生成層：讀三模組的「判定包」，生成三則 bullet
#
# 這是對「模型只改寫、不生成」原則的一次**有意識的**放寬（使用者指定：
# 不要先放固定內容再潤稿，改由 AI 讀判定後生成）。放寬的是「誰寫字」，
# 不放寬的是「誰下判斷」與「誰驗收」：
#   供料　　餵給模型的不是原始序列，是規則引擎已算好的格位／方向／
#   　　　　訊號／關鍵數字（judgment_pack）——模型看不到判定以外的世界
#   數字鎖　輸出裡的每個數字必須出現在判定包裡，一個不准新編
#   方向鎖　模型必須在文末自報方向，與九宮格的規則判定不符整篇作廢
#   結構鎖　恰好三行、以固定前綴開頭，缺一行整篇作廢
#   後備　　任何一道沒過退回 compose() 的規則組裝版，畫面永不開天窗
# 「本次更新」與「重點句」不經過模型：前者是機械判定，後者是全段
# 最不能錯的一句（三態模板見 _takeaway）。
# ---------------------------------------------------------------------------
import logging as _logging
log = _logging.getLogger(__name__)

_GEN_PROMPT_VERSION = "g1"
_GEN_LABELS = ("勞動市場", "通膨", "聯準會")
_GEN_SYSTEM = (
    "你是總經分析師。輸入是三個模組由固定規則算出的判定與關鍵訊號。"
    "把它們改寫成三則易讀的重點：**勞動市場與通膨兩則以各自的"
    "「關鍵訊號」為敘事主體**（訊號已按重要度排序，前面的優先），"
    "格位與數字用來佐證、不逐項羅列。格式硬性規定：恰好輸出三行，"
    "分別以「勞動市場：」「通膨：」「聯準會：」開頭，每行一到兩句、"
    "40 到 80 個中文字；最後另起一行輸出「方向：」加上輸入標明的政策傾向"
    "（利升息／利降息／中性，照抄輸入，不得自行改判）。內容規則："
    "只能使用輸入已有的資訊；最多引用兩三個關鍵數字，其餘用文字描述；引用的數字必須照輸入的寫法**原樣照抄**（含小數位數與百分號），不得換算、不得改寫格式、不得自行補年份或日期；"
    "不得推論輸入沒有寫的因果；不做預測、不下投資結論；"
    "不要條列符號、不要粗體記號、不要前言。繁體中文。")
_LEAN_ZH = {"hawkish": "利升息", "dovish": "利降息",
            "neutral": "中性", "balanced": "中性"}


def _n2(v):
    """
    判定包專用的數字格式：**最多小數點後兩位**，尾端多餘的零去掉
    （3.10→3.1、3.00→3）。判定包給模型讀的是「判定結果」，不是計算
    中間值的全精度——先前直接內插原始浮點數（3.0483870967…），
    配上「數字原樣照抄」的規定，模型就忠實地把整串尾巴搬上畫面。
    """
    if v is None:
        return "—"
    try:
        return f"{round(float(v), 2):g}"
    except (TypeError, ValueError):
        return str(v)


def judgment_pack(ctxs: dict) -> dict | None:
    """把三模組的規則判定整理成給模型讀的文字包。缺情境回 None。
    所有數值經 _n2 收斂到兩位小數——模型只能照抄乾淨的數字。"""
    scn = ctxs.get("scenario") or {}
    sc = scn.get("scenario")
    if sc is None:
        return None
    lab, inf, fom = ctxs.get("labor"), ctxs.get("inflation"), ctxs.get("fomc")
    lines = [f"政策傾向（規則判定，必須照抄到「方向：」行）："
             f"{_LEAN_ZH.get(getattr(sc, 'lean', ''), '中性')}",
             f"情境：{getattr(sc, 'name', '')}"]

    def _flags(ctx, n=3):
        """嚴重度排序的前 n 條訊號 headline（規則引擎已寫好的白話結論）。"""
        fs = (ctx or {}).get("flags") or []
        return "；".join(f.headline for f in fs[:n])

    # 勞動與通膨兩段**以關鍵訊號為主體**：headline 是規則引擎按分級
    # 標準（重要／留意／參考）排好的白話結論，格位只當狀態標籤。
    # 具體數字由訊號承載——格位行不再帶括號數字，同一件事在包裡
    # 出現兩次，模型就會寫兩次（實際發生過）。
    ax = (lab or {}).get("axis") or {}
    if lab:
        lines.append(
            "【勞動市場】格位："
            + f"{getattr(sc, 'labor_state', '—')}"
            + f"（失業率 {_n2(ax.get('unrate'))}%）；"
            + f"動能：{getattr(sc, 'labor_momentum', '—')}；"
            + f"關鍵訊號：{_flags(lab) or '無'}")
    if inf:
        s = inf.get("summary")
        lines.append(
            "【通膨】格位："
            + f"{getattr(sc, 'infl_state', '—')}（核心 PCE 年增 "
            + f"{_n2(getattr(s, 'pce_core_yoy', None))}%）；"
            + f"關鍵訊號：{_flags(inf) or '無'}")
    if fom and not fom.get("empty"):
        _sh = (fom.get("shift") or {}).get("direction") or "—"
        _fl = ((fom.get("focus")) or {}).get("label", "")
        dis = ((fom.get("vote") or {}).get("dissents")) or []
        _h = sum(1 for d in dis if isinstance(d, dict)
                 and d.get("direction") == "hike")
        lines.append(
            f"【聯準會】最近一次聲明措辭方向：{_sh}；目前重心：{_fl or '—'}；"
            + (f"反對票：{_h} 票主張升息；" if _h else "")
            + f"本期訊號：{_flags(fom) or '無'}")
    return {"text": "\n".join(lines),
            "lean": _LEAN_ZH.get(getattr(sc, "lean", ""), "中性")}


def _gen_digit_issues(text: str, source: str) -> tuple[list, list]:
    """
    數字鎖（放寬檔位二）。回傳 (違規清單, 放行清單)。

    兩個放寬，嚴格度的核心不變：
    ① **數值比對取代字面比對**——判定包寫 0.2、模型寫 0.20 是同一個
       數字（潤稿層在「+2.0 萬 → +2 萬」上踩過一模一樣的坑，解法照抄）。
    ② **小整數（0–99、無小數點、後面不是 %）放行**——日期、天數、
       票數這類計數是誤殺主因、錯了也傷不了判讀；但**帶小數點或帶 %
       的數字仍然硬鎖**（比率與水準值，錯一個就是讀者會引用的錯數字），
       「42%」這種整數比率也算硬鎖。放行的照樣記 log 供事後檢查。
    """
    import re as _re

    def _norm(tok: str) -> str:
        try:
            return repr(float(tok))
        except ValueError:
            return tok

    src = {_norm(t) for t in _re.findall(r"\d+(?:\.\d+)?",
                                         (source or "").replace(",", ""))}
    bad, waived = [], []
    for m in _re.finditer(r"(\d+(?:\.\d+)?)(%?)",
                          (text or "").replace(",", "")):
        tok, pct = m.group(1), m.group(2)
        if _norm(tok) in src:
            continue
        if "." not in tok and not pct and int(tok) <= 99:
            waived.append(tok)
        else:
            bad.append(tok + pct)
    return bad, waived


def _parse_generated(text: str, want_lean: str):
    """三行結構＋方向鎖。回傳 (bullets, 錯誤原因)。"""
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    got = {}
    direction = ""
    for ln in lines:
        if ln.startswith("方向："):
            direction = ln[3:].strip().rstrip("。")
            continue
        for lb in _GEN_LABELS:
            if ln.startswith(lb + "：") or ln.startswith(lb + ":"):
                if lb in got:
                    return None, f"「{lb}」出現了兩次"
                got[lb] = ln.split("：", 1)[-1].split(":", 1)[-1].strip()
    missing = [lb for lb in _GEN_LABELS if lb not in got]
    if missing:
        return None, "缺了「" + "、".join(missing) + "」那一行"
    for lb, body in got.items():
        n = cjk_len(body)
        if not 15 <= n <= 110:
            return None, f"「{lb}」長度 {n} 字超出 15–110 的範圍"
    if not direction:
        return None, "缺少文末的「方向：」標記行"
    if direction != want_lean:
        return None, f"方向標記「{direction}」與規則判定「{want_lean}」不符"
    return [(lb, got[lb]) for lb in _GEN_LABELS], ""


def generate(ctxs: dict, assembled: dict, cache_path, offline: bool = False,
             env: dict | None = None, cfg: dict | None = None,
             _post=None) -> dict:
    """AI 生成整體情勢三則。失敗一律退回組裝版（assembled）。"""
    import os
    import json as _json
    import hashlib as _hl
    from . import polish as _pl

    out = {"text": assembled.get("text", ""),
           "chars": assembled.get("chars", 0),
           "source": "assembled", "model": ""}
    if offline or not out["text"] or (cfg or {}).get("enabled") is False:
        return out
    pack = judgment_pack(ctxs)
    if pack is None:
        return out
    env = os.environ if env is None else env
    provider, key = _pl._pick_provider(env)
    if not provider:
        return out
    model = ((env.get("BRIEF_MODEL") or "").strip()
             or _pl.PROVIDERS[provider]["model"])
    # BRIEF_MODEL 指定的是別家的模型時忽略之——Anthropic 接主力後，
    # 殘留的 gemini-flash-latest 變數會把 Gemini 模型名丟給 Anthropic API
    #（必噴 404、整段退組裝），這種錯不該由使用者的舊設定觸發。
    if provider == "anthropic" and model.startswith("gemini"):
        model = _pl.PROVIDERS[provider]["model"]
    elif provider == "gemini" and model.startswith("claude"):
        model = _pl.PROVIDERS[provider]["model"]

    # 首尾兩句不經過模型，從組裝版原樣取
    _p = {x["key"]: x["text"] for x in assembled.get("parts", [])}
    head, tail = _p.get("whatsnew", ""), _p.get("takeaway", "")

    facts_h = _hl.sha256((pack["text"] + _GEN_PROMPT_VERSION + head + tail)
                         .encode("utf-8")).hexdigest()[:16]
    try:
        cache = _json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:                              # noqa: BLE001
        cache = {}
    if cache.get("gen_hash") == facts_h and cache.get("gen_text"):
        return {"text": cache["gen_text"], "chars": cjk_len(cache["gen_text"]),
                "source": "model-cache", "model": cache.get("model", model)}

    post = _post or _pl._POST[provider]
    reason, bullets = "", None
    for attempt in (1, 2):
        note = ("" if not reason else
                f"\n\n（上一次的輸出被退回，原因：{reason}。"
                "請重新輸出並逐條遵守格式與內容的硬性規定。）")
        try:
            res = post(key, model, pack["text"] + note, _GEN_SYSTEM,
                       (cfg or {}).get("temperature"))
        except Exception as e:                     # noqa: BLE001
            log.warning("整體情勢 AI 生成失敗（%s），改用組裝版", e)
            return out
        if isinstance(res, tuple):
            res, model = res[0], (res[1] or model)
        # 逐行清理：_sanitize 會把所有空白（含換行）折成單一空格，
        # 但這裡的三行結構就靠換行分隔——整段餵進去等於自毀格式。
        res = "\n".join(_pl._sanitize(ln) for ln in (res or "").splitlines()
                        if ln.strip())
        _bad, _waived = _gen_digit_issues(res, pack["text"])
        if _waived:
            log.info("整體情勢生成：放行判定包外的小整數（%s）——"
                     "計數／日期類，僅記錄供檢查", "、".join(_waived))
        if _bad:
            reason = ("輸出出現判定包裡沒有的數字（"
                      + "、".join(_bad) + "）")
            log.warning("整體情勢生成被退回的輸出開頭：%s…", res[:80])
        else:
            bullets, reason = _parse_generated(res, pack["lean"])
        if bullets:
            break
        if attempt == 1:
            log.warning("整體情勢 AI 生成未通過驗證（%s），帶原因重試一次",
                        reason)
    if not bullets:
        log.warning("整體情勢 AI 生成重試後仍未通過驗證（%s），改用組裝版",
                    reason)
        return out

    text = JOIN.join([x for x in
                      ([head] + [f"{lb}：{body}" for lb, body in bullets]
                       + [tail]) if x])
    try:
        cache.update({"gen_hash": facts_h, "gen_text": text, "model": model})
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(_json.dumps(cache, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    except Exception as e:                         # noqa: BLE001
        log.warning("整體情勢生成快取寫入失敗（%s），本次結果仍使用", e)
    return {"text": text, "chars": cjk_len(text),
            "source": "generated", "model": model}


# ---------------------------------------------------------------------------
def compose(ctxs: dict) -> dict:
    """
    規則組裝版（AI 生成的**後備**，也是離線／無金鑰時的正式輸出）。

    版式：本次更新（一行）→ 三個 bullet（勞動市場／通膨／聯準會，
    各一行、行內以「模組名：」開頭）→ 重點句（一行）。長端供給段
    已整段移除（使用者指定：總結只讀三大部分；長端的完整故事在長端頁）；
    共識開場句與「另一頭」「面對這個組合」等轉折詞也一併拿掉——
    bullet 各自成塊，不需要行文的黏著劑。

    回傳 {"text", "chars", "parts"}。任何一段缺資料就跳過，其餘照樣成立。
    """
    scn = ctxs.get("scenario") or {}
    sc = scn.get("scenario")
    lab, inf, fom = ctxs.get("labor"), ctxs.get("inflation"), ctxs.get("fomc")

    def _mon(ctx):
        """期別；若是 BLS 速報值就標出來——來源不同，讀者有權知道。"""
        m = _month((ctx or {}).get("data_month", ""))
        return f"{m}（速報）" if m and (ctx or {}).get("provisional") else m

    lab_txt = _labor((lab or {}).get("axis"), _mon(lab),
                     _pick_signal((lab or {}).get("flags")))
    _pce_mon = _month(((inf or {}).get("asof") or {}).get("pce", ""))
    inf_txt = _inflation((inf or {}).get("summary"),
                         (inf or {}).get("bands"),
                         getattr(sc, "infl_state", "") if sc else "",
                         _mon(inf),
                         _pick_signal((inf or {}).get("flags")),
                         pce_month=_pce_mon)
    fom_txt = _fomc(fom)

    parts = [
        ("whatsnew", _whats_new(ctxs)),
        ("labor", f"勞動市場：{lab_txt}" if lab_txt else ""),
        ("inflation", f"通膨：{inf_txt}" if inf_txt else ""),
        ("fomc", f"聯準會：{fom_txt}" if fom_txt else ""),
        ("takeaway", _takeaway(sc, fom, inf)),
    ]
    kept = [(k, v) for k, v in parts if v]
    text = JOIN.join(v for _, v in kept)
    return {"text": text, "chars": cjk_len(text), "raw_len": len(text),
            "parts": [{"key": k, "text": v, "chars": cjk_len(v)}
                      for k, v in kept]}
