"""
勞動市場頁的內容產生器。

版面順序（手機優先）：
    結論 → 四個關鍵數字 → 這次告訴我們什麼 → 失業率為什麼變 →
    行業增減 → 修正 → 健康檢查 → （折疊）名詞解釋、分數、JOLTS

標記 data-m-collapse 的 <details> 在窄螢幕上預設收合，桌面展開。
"""

from __future__ import annotations

from .. import charts, fmt
from ..analysis import attribution
from ..site import esc

from . import compact_full, focus_evidence, state_chip, teach
STATUS_ICON = {"good": "●", "warning": "▲", "critical": "■", "unknown": "○"}
STATUS_TEXT = {"good": "正常", "warning": "留意", "critical": "警戒", "unknown": "無資料"}
SEV_ICON = {"alert": "■", "watch": "▲", "info": "●"}
SEV_TEXT = {"alert": "重要", "watch": "留意", "info": "參考"}
LEAN_TEXT = {"dovish": "利降息", "hawkish": "利升息",
             "neutral": "中性", "balanced": "多空拉鋸"}


# ---------------------------------------------------------------------------
def _surprise_line(s: dict | None) -> str:
    """
    KPI 卡裡的「vs 預期」一行。

    這原本是獨立一整張卡，但它講的就是同一個數字——分成兩塊會逼讀者
    自己把「−2.3 萬」和「預期 +8.7 萬」在腦中對起來。併回數字旁邊之後，
    「差多少」跟「是多少」一次讀完。
    """
    if not s:
        return ""
    z = f'<span class="ks-z">{esc(s["z"])}</span>' if s.get("z") else ""
    # 模型推估不能只用一顆「＊」標——視覺上跟市場共識一模一樣，
    # 註腳又在整區最底下。直接把標籤換成「歷史規律推估」，
    # 讀者第一眼就知道這不是市場預期。
    star = '<span class="ks-star" title="模型推估">＊</span>' if s.get("is_model") else ""
    exp_label = "歷史規律推估" if s.get("is_model") else "預期"
    return (f'<div class="k-surp {s["kind"]}">'
            f'<span class="ks-exp">{exp_label} {s["expected"]}{star}</span>'
            f'<span class="ks-sep">·</span>'
            f'<span class="ks-diff">意外 {s["diff"]}</span>'
            f'<span class="ks-verdict">{esc(s["verdict"])}</span>{z}</div>')


def _kpi_card(label, value, sub, plain, spark_html="", flag=None, flag_kind="",
              mini="", asof="", surprise=None, en="", leans=(), fresh=False) -> str:
    """
    一張關鍵數字卡。**常駐固定三層**，其餘收合——跟全站的閱讀模型一致：

        第一層　標題（英文為主、中文副標）＋大數字
        第二層　一列 chips（水準／變化標籤與徽章合成同一種樣式）
        第三層　一句白話解讀

    先前的九層（標籤、預期比較、白話句、徽章、走勢表各自一種視覺）
    讓每張卡都要重新學一次「哪行是重點」；比較行、迷你走勢與預期明細
    現在收進「近 5 期與比較基準」，要驗算才點，內容一樣不少。

    `en` 是**主標題**、中文降成副標。使用者的原話：「你用中文寫我會不知道
    誰是誰」——對照 BLS 新聞稿或英文報導時，「核心服務除住房」跟 supercore
    對不起來，而這一頁的用途正是拿來對照的。

    `leans` 是 [(文字, hawkish/dovish/neutral)]，**水準與變化分開兩個標籤**：
    同一張卡可以同時是「仍高於目標」（利升息）與「本期在降」（利降息），
    兩件事都成立，擠進一個標籤只會互相打架。

    `fresh`＝這個模組的資料在 72 小時內首次出現。發布日當下，「與預期差
    多少」正是市場在反應的數字，所以整行常駐；過了 72 小時它變成歷史，
    自動退進收合層。沿用整站既有的 72 小時新鮮度機制，不另立規則。
    """
    plain_html = f'<div class="k-plain">{esc(plain)}</div>' if plain else ""
    asof_html = f'<span class="asof">{esc(asof)}</span>' if asof else ""
    head = esc(en or label)
    sub_label = f'<div class="k-label-zh">{esc(label)}</div>' if en else ""
    chips = [(t, k) for t, k in (leans or ()) if t]
    if flag:
        chips.append((flag, flag_kind or "info"))
    # 沒有 chips 也要輸出空容器：桌機用「各層固定最小高度」對齊四張卡，
    # 少了這一層，該卡的白話句會浮高、跟旁邊的卡對不齊。
    chips_html = ('<div class="k-chips">' + "".join(
        f'<span class="k-chip {k}">{esc(t)}</span>' for t, k in chips)
        + '</div>') if chips else '<div class="k-chips"></div>'
    surp_now = _surprise_line(surprise) if fresh else ""
    more_bits = (f'<div class="k-sub">{esc(sub)}</div>' if sub else "") \
        + ("" if fresh else _surprise_line(surprise)) + spark_html + mini
    more_html = (f'<details class="k-more"><summary>近 5 期與比較基準</summary>'
                 f'<div class="k-more-body">{more_bits}</div></details>'
                 if more_bits.strip() else "")
    return f"""<div class="card kpi">
  <div class="k-label">{head}{asof_html}</div>
  {sub_label}<div class="k-value">{esc(value)}</div>
  {chips_html}{surp_now}{plain_html}{more_html}
</div>"""


def _light_card(lt, href: str = "") -> str:
    arrow = {"up": "↑", "down": "↓", "flat": "→"}[lt.delta_dir]
    strip = charts.status_strip(getattr(lt, "history", []) or [])
    # 說明文收進展開層。格子高低不一的原因就是各格說明長度不同——
    # 名稱／數值／狀態／歷史條是固定四行，說明移走之後自然等高。
    # href＝這顆燈的「主場」卡區——同一個數字的完整脈絡在那裡；
    # 燈只負責狀態，想深入的人一跳就到，不用自己找。
    link = (f'<a class="l-link" href="{href}">完整脈絡 →</a>' if href else "")
    return f"""<div class="light {lt.status}">
  <div class="l-top"><span class="l-icon">{STATUS_ICON[lt.status]}</span>{esc(lt.label)}</div>
  <div class="l-value">{esc(lt.display)} <span style="font-size:13px;color:var(--muted)">{arrow}</span></div>
  <div class="l-state">{STATUS_TEXT[lt.status]}</div>
  {strip}
  <details class="l-more"><summary>這在量什麼</summary>
    <div class="l-desc">{esc(lt.desc)}{link}</div></details>
</div>"""


def _flag_row(f) -> str:
    """
    一項訊號 = 標題 + 影響標籤（一直看得到）+ 說明（收合）。

    說明是三到四行的數字佐證。六項訊號全部攤開要捲五個螢幕，
    而讀者第一輪要的是「有哪幾件事、各自往哪邊」——那兩樣留在外面，
    「為什麼」點開再看。
    """
    impact = ""
    if f.impact:
        impact = (f'<div class="impact {f.lean}">'
                  f'{esc(LEAN_TEXT.get(f.lean, ""))}　{esc(f.impact)}</div>')
    # 「依據」一律預設收合（含 alert 級）。先前 alert 的依據自動展開，
    # 理由是「頭條省一次點擊」——但實際效果是整張卡第一眼就是一段長文，
    # 「有哪幾件事、各自往哪邊」的掃讀節奏反而被打斷。
    _open = ""
    return f"""<div class="flag {f.severity}">
  <span class="f-icon">{SEV_ICON.get(f.severity,'●')}</span>
  <div>
    <div class="f-head">{esc(f.headline)}
      <span class="f-tag">{SEV_TEXT.get(f.severity,'')}</span></div>
    {impact}
    <details class="f-more"{_open}><summary>依據</summary>
      <div class="f-detail">{esc(f.detail)}</div></details>
  </div>
</div>"""


def _stats(items) -> str:
    return "".join(
        f'<div class="stat"><div class="s-label">{esc(s["label"])}</div>'
        f'<div class="s-value" style="color:{s.get("color","inherit")}">{esc(s["value"])}</div>'
        + (f'<div class="s-note">{esc(s["note"])}</div>' if s.get("note") else "")
        + "</div>"
        for s in items
    )


def _surprise_footnote(sb) -> str:
    """
    意外值的來源說明。

    意外值本身已經併進 KPI 卡（見 _surprise_line），但「這是模型推估、
    不是市場共識」這件事不能跟著消失——那是兩種完全不同的東西，
    縮成一行之後更容易被誤讀，所以在 KPI 區下方留一句完整說明。
    """
    if not sb or not sb.get("has_any"):
        return ('<div class="kpi-foot warn">尚未填入市場預期。'
                '在 config/consensus.yaml 填入發布前的市場預期後，'
                '非農與失業率卡片就會顯示與預期的差距。</div>')
    if sb.get("model_only"):
        return ('<div class="kpi-foot warn">'
                '<b>＊預期值目前來自時間序列模型，不是市場共識。</b>'
                '它回答的是「若照歷史規律外推應該是多少」，'
                '算出來的意外值是相對歷史規律的意外，不是相對市場定價的意外，'
                '兩者的交易意涵不同。</div>')
    notes = "　·　".join(sb.get("notes") or [])
    return (f'<div class="kpi-foot">預期來源：{esc(sb["sources"])}'
            + (f'　·　{esc(notes)}' if notes else "") + '</div>')


def _ustar_row(u: dict | None) -> str:
    """
    失業缺口 u − u*。放在失業率變動分解下面，因為它回答的是
    上面那段分解沒有回答的問題：「這個水準本身算緊還是鬆」。
    分解講的是**變化**的成因，缺口講的是**水準**的位置，兩件事。

    常駐只留一行（缺口值＋鬆緊判定）——先前整塊展開（標題列＋兩行
    說明＋再一個收合），跟上面的分解棒搶版面，正是「內容混亂」的來源。
    數字出處與 u* 的限制收進展開層，要驗算才點。
    """
    if not u:
        return ""
    gap = u['u'] - u['ustar']
    # 收合列直接用人話回答：不寫 u−u*、不寫「緊」這種單字術語
    _pos = ("低" if gap < 0 else "高")
    _state_txt = {"緊": "勞動市場仍偏緊，薪資有上行壓力",
                  "鬆": "勞動市場已偏鬆",
                  "中性": "大致在合理水準"}.get(u['state'], u['state'])
    return f"""<details class="f-more">
  <summary>現在的失業率算高還是低？　比「不推升通膨的水準」{_pos}
    <b style="color:{u['color']}">{abs(gap):.1f} 個百分點</b>——{esc(_state_txt)}</summary>
  <div class="f-detail">經濟學家估計，美國失業率若低於約 {u['ustar']:.1f}%，
    勞動市場就緊到會推升薪資與通膨。目前 {u['u']:.1f}%，比那條線{_pos}
    {abs(gap):.1f} 個百分點——工作比「剛好」的狀態更{'好' if gap < 0 else '難'}找，
    對聯準會是{'偏升息' if gap < 0 else '偏降息'}的背景。<br>
    這條線（CBO 估計的自然失業率，{esc(u['as_of'])}）一季更新一次、會回頭修正，
    估計誤差本身就有 ±0.2 個百分點——所以差距在 ±0.2 以內一律當中性，
    也不拿它設任何門檻。</div>
</details>"""


def _structure_block(u: dict | None) -> str:
    """
    失業結構。收合起來——它回答的是同一張卡的追問（「為什麼變成失業的」），
    不是新的主題，展開放在頁面上會跟上面兩段搶同一個位置。
    """
    if not u:
        return ""
    # 瘦身：每列只留「名稱＋橫條＋人數＋較一年前」。逐類的一句說明與
    # 佔比數字都砍掉——五類 × 五個元素是這張卡先前「第二套圖表系統」
    # 的來源；分母怎麼選的方法論整段刪除（那是寫給自己的辯護）。
    rows = "".join(
        f'<div class="ustr {r["kind"]}">'
        f'<div class="us-name">{esc(r["label"])}</div>'
        f'<div class="us-bar"><i style="width:{r["share"]:.1f}%"></i></div>'
        f'<div class="us-val">{esc(r["display"])}</div>'
        f'<div class="us-yoy">較一年前 {esc(r["yoy_display"])}</div></div>'
        for r in u["rows"])
    # 結論直接寫在收合列上，點開前就知道答案
    _v = (u.get("verdict") or "").rstrip("。")
    return f"""<details class="f-more ustruct"><summary>失業的人是怎麼變成失業的　·　{esc(_v)}</summary>
  <div class="ustr-list" style="margin-top:12px">{rows}</div>
  <p class="hint" style="margin-top:10px">{esc(u.get('lt_note', ''))}
    橫條＝佔各類合計的比例。重點看<b>較一年前的變化</b>，不是誰最大——
    「失去工作」長期本來就是最大的一塊。</p>
</details>"""


def _claims_card(c: dict | None) -> str:
    """
    每週失業金申請。放在失業率分解與行業分解之間，因為它是兩者的先行指標：
    今天的續領人數，是下個月失業率與下下個月行業增減的前情。
    """
    if not c:
        return ""
    lean_cls = c.get("lean", "neutral")
    return f"""<div class="grid">
  <div class="card">
    <h2 id="claims" data-sum="{esc(c['stats'][1]['label'])} {esc(c['stats'][1]['value'])}　·　{esc(c['stats'][2]['label'])} {esc(c['stats'][2]['value'])}">每週失業金申請</h2>
    <p class="hint">這一頁唯一的週頻資料：<span class="nb">{esc(c.get('released') or '—')} 發布</span>、
      <span class="nb">統計週至 {esc(c['as_of'])}</span>。</p>
    <div class="impact {lean_cls}">{esc(c['verdict'])}</div>
    <div class="stat-row" style="margin-top:14px">{_stats(c['stats'])}</div>
    <div style="margin-top:16px">{c['chart']}</div>
    <p class="hint" style="margin-top:8px">續領失業金人數（近兩年，單位萬人）</p>
    {teach(
        "每週有多少人新申請失業補助（初領）、多少人還在領（續領）。",
        "這是兩次就業報告之間唯一會更新的勞動數據。初領量的是裁員的速度、續領量的是再就業的難度——兩者可以背離，而背離是勞動市場轉弱最早的形態。",
        "別逐週反應：看四週平均與近一年的百分位。續領一直爬而初領沒動，就是「沒人被裁，但被裁的找不到下一份工作」。")}
    <details class="f-more"><summary>初領與續領差在哪、為什麼看四週平均</summary>
      <div class="f-detail">
        <b>日期先講清楚</b>：這一區標的是「統計週的結束日」不是發布日——
        8/13（四）發布的，就是「週結至 8/8」那一筆。看到日期比新聞早五天，
        不是資料沒更新，是同一筆。<br>
        新聞報的「實際／預估／前值」全是<b>單週</b>口徑——對應卡上
        「最新單週」那格；本站的判讀一律用四週平均。<br>
        <b>初領</b>是這週<b>新</b>失去工作的人，衡量的是裁員的速度；
        <b>續領</b>是還在領補助的人，衡量的是再就業的難度。
        兩者可以背離：裁員沒增加、但續領一直往上爬，代表「沒什麼人被裁，
        但被裁的人找不到下一份工作」——這是勞動市場轉弱最早出現的形態，
        只看初領完全看不到。<br>
        初領一律取四週移動平均：單週數字會被假期、罷工與各州政府的
        行政作業甩出很大的雜訊，逐週解讀幾乎必然過度反應。
        這裡用的是{esc(c.get('ma_source', ''))}。
        水準本身也不宜直接比較——申請件數會隨勞動力規模漂移，
        所以這裡另外標出它在近一年裡的百分位。<br>
        「失業持續期間中位數」是第三個角度：申請件數講「多少人」，
        它講「多久」。續領人數會被勞動力規模與補助資格變動影響，
        持續期間不會——兩條一起往上，再就業變難才算被獨立確認。
      </div>
    </details>
  </div>
</div>"""


def offline_banner(real_modules: list | None = None) -> str:
    """
    離線模式的警示條。哪些是真的、哪些是生成的，要講清楚——
    含糊其辭比不標示更糟，讀者會不知道哪些數字能引用。
    """
    real = "、".join(real_modules or [])
    series_note = (f"{real} 的時間序列為正式執行存下的真實資料快照；其餘"
                   if real else "時間序列")
    # 收合成一行。展開時在 390px 下高 134px，佔掉 16% 的首屏，
    # 而且每一頁一字不差——讀者第二頁就不會再讀它了，但它照樣把
    # 第一張卡推到摺線以下（rates 頁只露出 7px）。
    # 該講的重點（「這是示範數字，不可引用」）留在收合的那一行，
    # 細節與範圍在展開裡。
    return ('<details class="banner"><summary><b>離線示範模式</b>　'
            '數字為示範序列，不可引用</summary>'
            '<div class="banner-body">'
            '聯準會聲明與記者會逐字稿為 federalreserve.gov 的真實原文；'
            f'{series_note}為程式生成的示範序列（統計特性接近真實，'
            '但個別數值非實際發布值），不可用於研究引用。'
            '正式執行（不加 --offline）一律使用即時資料。'
            '</div></details>')


# 這三句講的都是**本期新訊號的方向**，不是勞動市場的**強弱水準**。
# 兩者不分清楚，讀者會覺得「這一頁說方向不明、九宮格卻說就業弱」是矛盾。
AXIS_NOTE = ("上面那句講的是<b>本期變化的方向</b>。就業的<b>強弱水準</b>"
             "（落在九宮格哪一列）與跟通膨合併之後的結論，"
             "見<a href=\"/scenario/#grid\">情境合成</a>頁——"
             "水準弱但本期方向不明，兩者可以同時成立。")


# ---------------------------------------------------------------------------
VERDICT_COPY = {
    "dovish": ("就業面：利降息",
               "轉弱訊號多於轉強。勞動市場走軟提高聯準會降息的正當性，"
               "對債券價格偏正面，但同時代表經濟動能流失。"),
    "hawkish": ("就業面：利升息",
                "就業與薪資強度高於預期。勞動市場緊俏降低降息的急迫性，"
                "甚至可能重啟緊縮，對債券價格偏負面。"),
    "balanced": ("就業面：本期方向不明",
                 "偏強與偏弱訊號互相抵消，本期數據不足以改變政策方向，"
                 "須待下期數據或通膨資料確認。"),
}


def _score_axis(sc: dict, compact: bool = False) -> str:
    """
    綜合強弱指數的刻度條。

    這條軸原本只在頁面最底下出現，但它是整頁唯一一個「把所有指標壓成
    一個可比數字」的東西——讀者要先知道現在幾分，才有辦法判斷底下每一項
    的輕重。所以結論卡直接帶一份，明細留在原位。
    """
    pct = max(0, min(100, (sc["score"] + 2.5) / 5 * 100))
    color = "var(--good)" if sc["score"] > 0 else "var(--critical)"
    left = min(50, pct) if sc["score"] < 0 else 50
    width = abs(pct - 50)
    delta = ("" if sc.get("delta") is None
             else f'　·　較上月 {sc["delta"]:+.2f}')
    cls = " compact" if compact else ""
    return f"""<div class="sax{cls}">
  <div class="sax-head">
    <span class="sax-label">綜合強弱指數</span>
    <span class="sax-val" style="color:{color}">{sc['score']:+.2f}</span>
    <span class="sax-delta">{esc(delta)}</span>
  </div>
  <div class="score-bar">
    <i style="left:{left}%;width:{width}%;background:{color}"></i>
    <span class="score-mid"></span>
  </div>
  <div class="sax-scale"><span>−2.5 疲弱</span><span>0 持平</span><span>+2.5 強勁</span></div>
</div>"""


def _verdict_card(d: dict) -> str:
    tilt = d["tilt"]
    flags = d["flags"]
    title, why = VERDICT_COPY.get(tilt["tilt"], VERDICT_COPY["balanced"])

    n_dov = sum(1 for f in flags if f.lean == "dovish")
    n_haw = sum(1 for f in flags if f.lean == "hawkish")
    n_neu = len(flags) - n_dov - n_haw

    top = next((f for f in flags if f.severity == "alert"), flags[0] if flags else None)
    lead = f"最主要的訊號是：{top.headline}。" if top else ""

    return f"""<div class="verdict {tilt['tilt']}">
  <div class="v-eyebrow">{esc(d['data_month'])} 就業報告　·　一句話結論</div>
  <div class="v-main">{esc(title)}</div>
  <div class="v-why">{esc(lead)}{esc(why)}</div>
  {_score_axis(d['score'], compact=True)}
  <div class="v-count">
    本次共 {len(flags)} 項訊號：{n_dov} 項利降息、{n_haw} 項利升息、{n_neu} 項中性。
    {AXIS_NOTE}
  </div>
</div>"""


# ---------------------------------------------------------------------------
def _labor_body_full(d: dict) -> str:
    k = d["kpi"]
    mini = d.get("mini", {})
    asof = (d.get("asof", {}).get("labor") or "")[:7]
    surp_inline = (d.get("surprises") or {}).get("inline") or {}
    _fresh = bool(d.get("is_fresh"))
    lean = d.get("kpi_lean", {})
    kpis = "".join([
        # en 主標＋水準／本期 chips：跟通膨頁的 KPI 卡同一套長相。
        # 英文為主是為了對照 BLS 新聞稿與英文報導（使用者的原話：
        # 「你用中文寫我會不知道誰是誰」）。
        _kpi_card("非農就業月變動", k["nfp_display"], k["nfp_sub"], k.get("nfp_plain"),
                  charts.sparkline(k["nfp_spark"], zero_line=True),
                  k.get("nfp_flag"), k.get("nfp_flag_kind", ""),
                  mini=mini.get("nfp", ""), asof=asof,
                  surprise=surp_inline.get("nfp"), fresh=_fresh,
                  en="Nonfarm Payrolls, m/m", leans=lean.get("nfp", ())),
        _kpi_card("失業率 U-3", k["u3_display"], k["u3_sub"], k.get("u3_plain"),
                  charts.sparkline(k["u3_spark"]),
                  k.get("u3_flag"), k.get("u3_flag_kind", ""),
                  mini=mini.get("u3", ""), asof=asof,
                  surprise=surp_inline.get("u3"), fresh=_fresh,
                  en="Unemployment Rate U-3", leans=lean.get("u3", ())),
        _kpi_card("平均時薪年增率", k["ahe_display"], k["ahe_sub"], k.get("ahe_plain"),
                  charts.sparkline(k["ahe_spark"]),
                  k.get("ahe_flag"), k.get("ahe_flag_kind", ""),
                  mini=mini.get("ahe", ""), asof=asof, fresh=_fresh,
                  en="Avg Hourly Earnings, y/y", leans=lean.get("ahe", ())),
        _kpi_card("勞動參與率", k["lfpr_display"], k["lfpr_sub"],
                  k.get("lfpr_plain"), charts.sparkline(k["lfpr_spark"]),
                  k.get("lfpr_flag"), k.get("lfpr_flag_kind", ""),
                  mini=mini.get("lfpr", ""), asof=asof, fresh=_fresh,
                  en="Labor Force Participation", leans=lean.get("lfpr", ())),
    ])

    rev, att, dec, sc = d["revision"], d["attribution"], d["decomp"], d["score"]

    flags_html = "".join(_flag_row(f) for f in d["flags"]) or \
        '<div class="empty">本次沒有觸發任何訊號</div>'
    # 每顆燈連回它的「主場」卡區——燈只給狀態，完整脈絡在那裡。
    # 用標籤關鍵字對照，config 改標籤時對不到就只是不顯示連結，不會壞。
    _anchor_map = [("衰退警訊", "#unrate"), ("職缺", "#kpi"),
                   ("離職率", "#kpi"), ("裁員率", "#kpi"),
                   ("失業補助", "#claims"), ("新增工作", "#kpi"),
                   ("壯年就業", "#kpi"), ("隱藏性失業", "#kpi")]

    def _anchor(label: str) -> str:
        return next((a for k, a in _anchor_map if k in label), "")
    lights_html = "".join(_light_card(l, _anchor(l.label)) for l in d["lights"])

    # ---- 失業率為什麼變 ----
    # 版面邏輯：結論在上（判定＋總變動），拆解在下（兩項相加＝總變動）。
    # 先前是四個等大的格子並排，讀者看不出「判定」是結論、「兩個效果」是
    # 分項，也看不出兩項相加剛好等於總變動——而那個加總關係正是整張卡的重點。
    dec_html = '<div class="empty">資料不足</div>'
    if dec:
        e, l = dec["employment_effect"], dec["laborforce_effect"]
        span = max(abs(e), abs(l)) or 1
        # 「兩項相加＝總變動」只是一階近似，而且總變動取自四捨五入到小數
        # 一位的 UNRATE、兩個效果取自未四捨五入的 CE16OV／CLF16OV。
        # 誤差大到看得出來時要講，不然這一列會被當成算錯。
        _r = dec.get("residual") or 0.0
        _resid = (f'　<span class="dc-resid">（近似誤差 {_r:+.2f}）</span>'
                  if abs(_r) >= attribution.RESID_SHOW else "")
        # 統計顯著性：UNRATE 只到小數一位，0.1 個百分點在 BLS 自己的標準下
        # 不可分辨於零。不標的話讀者會把雜訊當成訊號。
        # 結論統一走 .impact 色框（六張卡同一種「一句結論」視覺），
        # 顯著性註記併進結論句尾，不再自己一個小灰塊。
        _dlean = {"bad_decline": "dovish", "bad_rise": "dovish",
                  "good_decline": "hawkish"}.get(dec.get("verdict"), "neutral")
        # 結論寫成完整的一句人話（方向＋主因＋雜訊註記），
        # 取代先前乾巴巴的「勞動力變動：勞動力退出所致」。
        _dr = dec['delta_rate']
        _dir_word = "下降" if _dr < 0 else ("上升" if _dr > 0 else "持平")
        _lf_wan = fmt.wan_abs(dec['delta_labor_force'])
        _emp_wan = fmt.wan_abs(dec['delta_employed'])
        _cause = {
            "bad_decline": f"主因是 {_lf_wan}退出職場、不再找工作——不是就業變好",
            "good_decline": f"主因是就業增加 {_emp_wan}——是真實的改善",
            "bad_rise": f"主因是有工作的人減少 {_emp_wan}",
            "supply_rise": f"主因是 {_lf_wan}投入找工作（分母變大），不代表就業惡化",
        }.get(dec.get("verdict"), "兩股力量大致抵消")
        _impact_txt = (f"這個月失業率{_dir_word} {abs(_dr):.2f} 個百分點，{_cause}"
                       + ("（幅度在雜訊範圍內，強度別當真）"
                          if not dec.get("significant", True) else "") + "。")
        # 分解列的標籤直接講事實，不用「就業效果／勞動力效果」的課本詞；
        # 「其中失業人數」「近似誤差」這類補充退出常駐版面。
        _emp_label = (f"有工作的人{'少了' if dec['delta_employed'] < 0 else '多了'} "
                      f"{_emp_wan}")
        _lf_label = (f"{_lf_wan}"
                     + ("退出職場、不再找工作" if dec['delta_labor_force'] < 0
                        else "投入找工作"))
        dec_html = f"""<div class="impact {_dlean}">{esc(_impact_txt)}</div>
<div class="stat-row" style="margin:14px 0 0">{_stats([
    {"label": "失業率 U-3", "value": d['kpi']['u3_display']},
    {"label": "較上月", "value": f"{dec['delta_rate']:+.2f} 個百分點"}])}</div>
<div class="dcomp">
  <div class="dc-cap">本月的變動怎麼來的</div>
  <div class="dc-row">
    <div class="dc-name">{esc(_emp_label)}</div>
    <div class="dc-bar"><span class="dc-zero"></span>
      <i style="{'left' if e >= 0 else 'right'}:50%;width:{abs(e)/span*50:.1f}%"></i></div>
    <div class="dc-val">{e:+.2f}<span>{'推高' if e >= 0 else '壓低'}</span></div>
  </div>
  <div class="dc-row">
    <div class="dc-name">{esc(_lf_label)}</div>
    <div class="dc-bar"><span class="dc-zero"></span>
      <i style="{'left' if l >= 0 else 'right'}:50%;width:{abs(l)/span*50:.1f}%"></i></div>
    <div class="dc-val">{l:+.2f}<span>{'推高' if l >= 0 else '壓低'}</span></div>
  </div>
  <div class="dc-total">兩項相加　＝　{dec['delta_rate']:+.2f} 個百分點（就是本月的變動）{_resid}</div>
</div>"""

    # ---- 折疊區的表格 ----
    jolts_rows = "".join(
        f'<tr><td>{esc(r["label"])}</td><td>{esc(r["value"])}</td>'
        f'<td>{esc(r["chg"])}</td></tr>' for r in d["jolts"]
    )
    att_rows = "".join(
        f'<tr><td>{esc(r["label"])}</td>'
        f'<td class="{"pos" if r["value"]>=0 else "neg"}">{esc(fmt.wan(r["value"], unit=""))}</td>'
        f'<td class="muted-cell">{esc(r["share"])}</td>'
        f'<td class="muted-cell">{esc(r["own"])}</td></tr>'
        for r in att["table"]
    )
    # 淨額遠小於毛額時要明講。「總變動 −2.3 萬」單看像是這個月沒事，
    # 實際上是 +5.9 萬的增加被 −11.1 萬的減少蓋過去——那才是重點。
    _g = att.get("gross") or {}
    gross_note = ""
    if _g.get("offsetting"):
        # 明細加總不等於總數（行業別未涵蓋全部非農），差額要一起講出來，
        # 否則讀者拿畫面上的兩個數字相減會對不上「全體合計」。
        _resid = _g.get("unexplained") or 0
        _resid_txt = (f'；行業明細合計 {esc(fmt.wan(_g["explained"]))}，'
                      f'與全體合計的差 {esc(fmt.wan(_resid))} 來自未單獨列出的行業'
                      if abs(_resid) >= 5 else "")
        # 這句就是這張卡的結論——用統一的 .impact 框，不再用警告框
        #（warnbox 保留給真正的資料異常）。
        gross_note = (
            '<div class="impact neutral">'
            f'淨額小，是增減互相抵消：本月 {esc(fmt.wan(_g["positive"]))} 的增加'
            f'被 {esc(fmt.wan(_g["negative"]))} 的減少蓋過{_resid_txt}。'
            '「沒什麼事」與「大幅變動但互相抵消」，對政策的意涵完全不同。</div>')
    # 每一列的樣本期數不一樣（週資料換算成月之後只有十幾個月，
    # 月資料是 60 個月）。用 min() 一句話蓋掉全部，會把六列 5 年期的
    # z-score 說成 14 個月——差 4 倍多。所以逐列標出來。
    score_items = "".join(
        # 欄序：窄螢幕上表格要橫向捲，被推出畫面的應該是最不重要的那欄，
        # 所以「樣本月數」放最後，貢獻留在看得到的位置
        f'<tr><td>{esc(i["label"])}</td><td>{i["z"]:+.2f}</td>'
        f'<td class="muted-cell">{i["weight"]:.1f}</td>'
        f'<td class="{"pos" if i["contribution"]>=0 else "neg"}">{i["contribution"]:+.2f}</td>'
        f'<td class="muted-cell">{i.get("window") or "—"}</td></tr>'
        for i in sc["items"]
    )
    _wins = [i.get("window") or 0 for i in sc["items"] if i.get("window")]
    win_note = (f"各列的樣本期數介於 {min(_wins)} 到 {max(_wins)} 個月之間"
                if _wins and min(_wins) != max(_wins)
                else (f"各列都以近 {_wins[0]} 個月為樣本" if _wins else ""))
    short_note = ("　週頻序列（申請失業金）換算成月之後樣本較短，"
                  "那兩列的分數波動會比其他列大。" if _wins and min(_wins) < 24 else "")
    failed_html = ""
    if d.get("failed"):
        items = "".join(f"<li>{esc(a)} — {esc(b)}</li>" for a, b in d["failed"])
        failed_html = (f'<div class="card"><details class="plain"><summary>'
                       f'本次有 {len(d["failed"])} 個資料序列抓取失敗</summary>'
                       f'<ul style="font-size:13px;color:var(--text-secondary)">{items}</ul>'
                       f"</details></div>")

    # 收合摘要：最嚴重的那一條訊號。收合狀態下這是讀者判斷
    # 「要不要點開」的唯一依據——只寫標題的話得逐一點開才知道哪張有事。
    _top = next((f for f in d["flags"] if f.severity == "alert"),
                (d["flags"] or [None])[0])
    _sig_sum = (f'{len(d["flags"])} 項　·　{_top.headline}' if _top
                else "本次沒有觸發任何訊號")
    _kpi_sum = (f'非農 {k["nfp_display"]}　·　失業率 {k["u3_display"]}'
                f'　·　時薪年增 {k["ahe_display"]}')
    _dec_sum = (f'失業率 {dec.get("delta_rate", 0):+.2f} 個百分點'
                + (f'　·　{k["u3_flag"]}' if k.get("u3_flag") else ""))
    _att_sum = "　·　".join(f'{s["label"]} {s["value"]}'
                           for s in att["stats"][:2])
    _rev_sum = next((f'{s["label"]} {s["value"]}' for s in rev["stats"]
                     if s["value"] not in ("—", "")), "本次無修正資料")
    # 修正卡的一句結論：拿「近一年修正傾向」那格組出來（它就是這卡的重點）。
    _rev_bias = next((s for s in rev["stats"] if "傾向" in s.get("label", "")), None)
    if _rev_bias and _rev_bias.get("value") not in ("—", ""):
        _rb_lean = ("dovish" if str(_rev_bias["value"]).startswith("-")
                    else "hawkish" if str(_rev_bias["value"]).startswith("+")
                    else "neutral")
        _rev_impact = (f'<div class="impact {_rb_lean}">'
                       f'{esc(_rev_bias["label"])} {esc(_rev_bias["value"])}'
                       f'——{esc(_rev_bias.get("note") or "")}</div>')
    else:
        _rev_impact = ""
    _lt = {}
    for _l in d["lights"]:
        _lt[_l.status] = _lt.get(_l.status, 0) + 1
    _light_sum = "、".join(
        f'{_n} 項{_lab}' for _k, _lab in
        (("critical", "警戒"), ("warning", "留意"), ("good", "正常"),
         ("unknown", "無資料")) if (_n := _lt.get(_k)))
    # 收合摘要要用人話。「+0.13 · 較上期 +0.02」對一般讀者是密碼——
    # 先講判定（強／中性／弱），數字降級成括號裡的佐證。
    _sv = sc["score"]
    _sw = "偏強" if _sv > 0.45 else ("偏弱" if _sv < -0.45 else "中性")
    _score_sum = (f'綜合判定：就業{_sw}（{_sv:+.2f}，0 為歷史平均）')
    _sw_lean = {"偏強": "hawkish", "偏弱": "dovish"}.get(_sw, "neutral")

    return f"""
{_verdict_card(d)}

<div class="grid">
  <div class="card">
    <h2 id="signals" data-open="1" data-sum="{esc(_sig_sum)}">本期關鍵訊號</h2>
    <p class="hint">這個月<b>新發生</b>的事；目前的整體狀態看下方「關鍵指標檢核」。點「依據」看支撐的數字。</p>
    {flags_html}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="kpi" data-open="1" data-sum="{esc(_kpi_sum)}">關鍵數字</h2>
    <div class="grid g4 inner">{kpis}</div>
    {_surprise_footnote(d.get('surprises'))}
    <details data-m-collapse><summary>JOLTS 職缺與人力流動</summary>
      <p class="hint" style="margin:10px 0 8px">{esc(d['jolts_note'])}</p>
      <table><thead><tr><th>指標</th><th>最新值</th><th>較上月</th></tr></thead>
      <tbody>{jolts_rows}</tbody></table></details>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="unrate" data-sum="{esc(_dec_sum)}">失業率變動分解</h2>
    <p class="hint">同樣的下降幅度，成因不同則意義相反。</p>
    {dec_html}
    {_ustar_row(d.get('ustar'))}
    {teach(
        "失業率這個月的變動，是「更多人找到工作」還是「更多人放棄找工作」造成的。兩個原因拆開來各算一塊。",
        "失業率只算「還在找工作」的人，所以下降不一定是好消息：大家放棄找工作、退出勞動市場，失業率也會下降——但那其實是就業市場在轉弱。",
        "看哪一塊比較大：就業那塊大，代表數字反映真實改善；退出那塊大，代表下降是假象，方向反而偏弱。另外，失業率只公布到小數一位，單月 ±0.1 的變動在統計上跟 0 分不出差別——方向可看，強度別當真。")}
    {_structure_block(d.get('unemp_structure'))}
  </div>
</div>

{_claims_card(d.get('claims'))}

<div class="grid">
  <div class="card">
    <h2 id="industry" data-sum="{esc(_att_sum)}">行業別貢獻分解</h2>
    <p class="hint">只列增減最大的各三個與變動異常的行業；
      完整 {att['total_count']} 個行業收在下方表格。</p>
    {gross_note}
    <div class="stat-row" style="margin-top:14px">{_stats(att['stats'])}</div>
    <div style="margin-top:14px">{att['bars']}</div>
    <div class="dlegend">
      <span><i style="background:var(--pos)"></i>增加</span>
      <span><i style="background:var(--neg)"></i>減少</span>
      <span><i style="background:var(--muted-bar)"></i>不受景氣影響／加總列</span>
      <span>單位：萬人</span>
    </div>
    {teach(
        "這個月新增（或減少）的就業，是哪幾個行業貢獻的。",
        "同樣是「+5 萬人」，全部來自醫療和政府、跟散佈在十個行業，意義完全不同——前者跟景氣無關，後者代表整體經濟在擴張。",
        "先看增與減集中在誰身上，再看圖下方有沒有標 ▲ 的異常行業——那代表它這次的變動比自己平常的波動大很多，通常是產業出事或政策轉向的訊號。")}
    <details data-m-collapse><summary>全部 {att['total_count']} 個行業</summary>
      <div class="tscroll" style="margin-top:10px"><table>
        <thead><tr><th>行業</th><th>增減（萬人）</th><th>同向佔比</th><th>自身變動</th></tr></thead>
        <tbody>{att_rows}</tbody></table></div>
      <p class="hint" style="margin-top:10px">
        「同向佔比」＝這個行業佔<b>同方向</b>總額的比例：增加的行業除以全部增加合計、
        減少的行業除以全部減少合計。不用淨變動當分母，因為淨額接近零時會算出
        −165%、+204% 這種讀不出意義的數字。
        「自身變動幅度」＝該行業的月變動相對自己就業規模的百分比，
        用來比較不同規模的行業誰動得比較劇烈。</p>
    </details>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="revision" data-sum="{esc(_rev_sum)}">歷史數據修正</h2>
    <p class="hint">初次公布是估算值，之後兩個月會用更完整的資料重算。</p>
    {_rev_impact}
    <div class="stat-row" style="margin-top:14px">{_stats(rev['stats'])}</div>
    {teach(
        "之前公布的就業數字，事後被改了多少。",
        "市場只對「第一次公布」的數字有反應，但那是估算值。如果初值總是被往下修，代表你在新聞上看到的就業一直比真實情況好——這正是判斷「數據可不可信」的地方。",
        "看兩件事：這次把前兩個月改了多少（幅度大代表初值很不準）；過去一年平均往哪個方向改（一直往下修＝初值系統性偏樂觀，看到新數字要先打折）。")}
    <details data-m-collapse><summary>逐月修正明細</summary>
      {rev['table']}
      <p class="hint" style="margin-top:10px">
        「修正」欄是相對初次公布的累計差異，與上方 BLS 口徑（相對上次發布）不同。</p>
    </details>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="lights" data-sum="{esc(_light_sum)}　·　{esc(_score_sum)}">關鍵指標檢核與綜合強弱</h2>
    <p class="hint">目前的整體狀態（不限本月）：先數紅燈，再看加權出來的一個總分。</p>
    <div class="impact {_sw_lean}">{esc(_score_sum)}　·　{esc(_light_sum)}</div>
    <details data-m-collapse open><summary>八項指標</summary>
      <div class="lights" style="margin-top:12px">{lights_html}</div>
    </details>
    {_score_axis(sc)}
    {teach(
        "八個歷史上最能提早反映就業轉折的指標，逐一對照它們的警戒線；再把它們換算成同一把尺、加權平均成一個總分。",
        "單一指標常常騙人（失業率可以因為錯的原因下降），但八個一起看就很難全部同時騙你。這也是聯準會自己的做法——看儀表板，不看單一數字。指標會互相矛盾時（非農弱但職缺強），總分強迫所有指標表態，給一個唯一的方向。",
        "先數紅燈：0–1 個警戒是正常雜訊；三個以上同時亮，歷史上多半已接近轉折。總分看正負與連續趨勢就好——連續幾期往下掉比單期的絕對值重要；格位判定仍以失業率為準。")}
    <details data-m-collapse><summary>總分的各指標貢獻明細</summary>
      <div class="tscroll" style="margin-top:10px"><table>
        <thead><tr><th>指標</th><th>標準分數</th><th>權重</th>
          <th>貢獻</th><th>樣本月數</th></tr></thead>
        <tbody>{score_items}</tbody></table></div>
      <p class="hint" style="margin-top:10px">
        「標準分數」的意思：這個指標現在離自己的平常水準有多遠、
        以自己平常的波動幅度為單位——+1 代表比平均高出一個「平常的波動」，
        數字越大越不尋常。方向已統一成「正值＝就業強」。{esc(win_note)}，
        所以「樣本月數」逐列標出，不同列的分數不完全可比。{esc(short_note)}
        權重目前為暫定值，僅供輔助判讀。</p>
    </details>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="glossary" data-sum="這一頁出現的專有名詞">名詞解釋</h2>
        <dl class="gloss">
      <dt>非農就業人數</dt>
      <dd>美國政府向企業調查得出的就業人數，不含農業。最受市場關注的就業指標。</dd>
      <dt>失業率</dt>
      <dd>在「有在找工作的人」當中，找不到工作的比例。已經放棄找工作的人不算在內。</dd>
      <dt>勞動參與率</dt>
      <dd>16 歲以上人口中，有在工作或正在找工作的比例。退休、就學、放棄找工作的人不算。</dd>
      <dt>JOLTS</dt>
      <dd>職缺與人力流動調查。統計市場上有多少職缺、多少人被錄取、多少人主動離職。
        資料比就業報告晚，實際落後期數見上方的 JOLTS 區塊（每期會變）。</dd>
      <dt>主動離職率</dt>
      <dd>自己辭職的人佔總就業的比例。敢主動辭職代表對找到下一份工作有信心，
        所以是勞工信心的溫度計。</dd>
      <dt>續領失業補助</dt>
      <dd>持續在領失業給付的人數。比「新增失業人數」更能反映找到新工作的難度。</dd>
      <dt>百分點（pp）</dt>
      <dd>比例之間的差距。失業率從 4.2% 降到 4.1%，是下降 0.1 個百分點。</dd>
      <dt>利升息／利降息</dt>
      <dd>指這項數據會讓聯準會傾向升息或降息。就業轉弱通常利降息，
        就業與薪資過熱則利升息。</dd>
    </dl>
  </div>
</div>

{failed_html}
"""


def _jobs_release_date(month: str) -> str:
    """
    就業報告的例行發布日＝資料月份**次月的第一個週五**。可推導，所以標。

    CPI／PPI／PCE 的發布日是 BLS／BEA 每年排的日曆、沒有公式，那幾個
    刻意不標——與其引入一份每年要手動更新的日曆，不如只標推得出來的。
    偶爾因假期挪動一天，所以文案寫「發布」不寫星期幾。
    """
    try:
        import datetime as _dt
        y, m = int(month[:4]), int(month[5:7])
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        d1 = _dt.date(y, m, 1)
        return (d1 + _dt.timedelta(days=(4 - d1.weekday()) % 7)).isoformat()
    except (ValueError, TypeError, IndexError):
        return ""


def labor_body(d: dict) -> str:
    """就業頁首卡固定回答：格位、方向、非農、失業率與下一格門檻。"""
    ax, k = d.get("axis") or {}, d.get("kpi") or {}
    u, lo, hi = ax.get("unrate"), ax.get("u_lo"), ax.get("u_hi")
    if ax.get("sahm_triggered"):
        state, basis = "弱", "Sahm 法則已觸發"
    elif None not in (u, lo, hi):
        state = "弱" if u > hi else ("強" if u < lo else "中")
        basis = f"失業率 {u:.1f}% 對照 FOMC 長期區間 {lo:.1f}–{hi:.1f}%"
    else:
        state, basis = "資料不足", "缺少失業率或 FOMC 長期區間"
    momentum = "轉弱" if (ax.get("u3_rising") or ax.get("sahm_triggered")) else "持平"
    _rise = ax.get("sahm")
    if state == "中" and hi is not None and u is not None:
        trigger = f"失業率高於 {hi:.1f}% 轉弱（距離 {hi-u:.1f}pp）"
    elif state == "強" and lo is not None:
        trigger = f"失業率升回 {lo:.1f}% 以上離開強區"
    else:
        trigger = "持續確認失業率與 Sahm 法則"
    kind = "dovish" if state == "弱" or momentum == "轉弱" else "hawkish" if state == "強" else "neutral"
    state_text = {"弱": "偏弱", "中": "中性", "強": "偏強"}.get(state, state)
    metrics = "".join([
        state_chip("就業格位", state, basis, kind),
        state_chip("移動方向", momentum, "不直接改變當前格位", kind),
        state_chip("非農就業｜最新", k.get("nfp_display", "—"), k.get("nfp_sub", "")),
        state_chip("失業率 U-3", k.get("u3_display", "—"), k.get("u3_sub", "")),
    ])
    _rise_txt = f"{_rise:+.2f} 個百分點" if _rise is not None else "—"
    logic = (f'<div class="logic-strip"><div class="logic-step"><b>水準怎麼定</b><span>{esc(basis)}</span></div>'
             f'<div class="logic-step"><b>方向怎麼定</b><span>失業率較近一年低點回升：{_rise_txt}；達 0.20（本站門檻）即轉弱、0.50（Sahm）為衰退訊號。</span></div>'
             f'<div class="logic-step"><b>下一格觸發</b><span>{esc(trigger)}</span></div></div>')
    logic = focus_evidence(logic)
    a = d.get("asof") or {}
    _rel = _jobs_release_date(d.get("data_month", ""))
    tags = (f'<div class="data-line"><span class="data-tag">就業報告 {esc(d.get("data_month", "—"))}'
            + (f'（{esc(_rel[5:].replace("-", "/"))} 發布）' if _rel else "")
            + '</span>'
            f'<span class="data-tag">初領失業金（統計週至 {(a.get("claims") or "—")[:10]}）</span>'
            f'<span class="data-tag">JOLTS {(a.get("jolts") or "—")[:7]}</span>'
            + (f'<span class="data-tag next">下次就業報告 '
               f'{esc(d["next_release"][5:].replace("-", "/"))}</span>'
               if d.get("next_release") else "")
            + '</div>')
    hero = (f'<div class="grid"><div class="card focus-card"><div class="focus-eyebrow">Labor now</div>'
            f'<h2 class="focus-title">就業{state_text}，動能{momentum}</h2>'
            '<p class="focus-sub">失業率的水準決定格位；失業率的回升速度決定移動方向。</p>'
            f'<div class="focus-grid">{metrics}</div>{logic}{tags}</div></div>')
    return hero + compact_full(_labor_body_full(d), "完整就業拆解")


def labor_footer(d: dict) -> str:
    return (
        "資料來源：美國勞工統計局（BLS）與勞工部（DOL），經 FRED 取得，"
        "數字為修正後的最新版本。<br>"
        f"修正追蹤來源：{esc(d['revision']['source_note'])}"
        "　·　所有判定由固定規則產生，每次執行結果一致。<br>"
        "本頁僅為數據整理，不構成投資建議。"
    )
