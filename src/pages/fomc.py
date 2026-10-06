"""
聯準會頁（2026-10 改版）。

使用者要求：這一頁只放**文件裡的事實**，不發明分數。版面順序：

  頂部決議卡（決議與日期、投票、前次、下次會議與靜默期）
  政策訊號（事實清單，不加總）
  下次會議與靜默期 → 投票委員與官員 → 點陣圖與 SEP → 市場路徑 vs 點陣圖
  → 聲明逐句比對 → 會議紀要觀點分布 → 記者會原句（官員發言併入委員樹狀圖的人物面板）
  → 目前重心與轉向條件 → 歷次決議 → 判讀說明

AI 只用在三個地方，畫面上一律標「AI」：聲明改動的中文說明、會議紀要
量詞句的中文翻譯、官員近期新聞標題的一句話整理。AI 失敗就只顯示原文。
"""

from __future__ import annotations

from ..analysis import fomc_extra as fx
from ..analysis.fomc_text import _sentences as ft_sentences
from ..site import esc
from . import focus_evidence, state_chip, teach


DIR_CLS = {"hawkish": "hawkish", "dovish": "dovish"}
DIR_ARROW = {"hawkish": "↑ 偏升息", "dovish": "↓ 偏降息", "neutral": "— 中性"}


def _md(iso: str) -> str:
    """2026-10-07 → 10/7"""
    try:
        return f"{int(iso[5:7])}/{int(iso[8:10])}"
    except (ValueError, TypeError, IndexError):
        return iso or "—"


def _tw(iso: str, hhmm: str = "14:00") -> str:
    """美東時間 → 台北時間的文字。夏令時間（3–11 月）差 12 小時、冬令差 13 小時，
    不能寫死「台北隔天 02:00」——12 月的會議是 03:00。夏令規則用 clock 的自算版，
    不依賴 tzdata。"""
    try:
        import datetime as _dt
        from .. import clock
        h, m = (int(x) for x in hhmm.split(":"))
        noon = _dt.datetime(int(iso[:4]), int(iso[5:7]), int(iso[8:10]), 12,
                            tzinfo=_dt.timezone.utc)
        off = clock.ny_offset(noon)
        et = _dt.datetime(int(iso[:4]), int(iso[5:7]), int(iso[8:10]), h, m)
        tw = et - _dt.timedelta(hours=off) + _dt.timedelta(hours=8)
        day = "隔天" if tw.date() > et.date() else ""
        return f"台北{day} {tw:%H:%M}"
    except Exception:                              # noqa: BLE001
        return "台北時間隔天凌晨"


def _ai(text: str) -> str:
    return (f'<div class="fx-ai"><span class="ai-tag">AI</span>{esc(text)}</div>'
            if text else "")


def _diff_block(rows, show_same: bool = False, notes: list | None = None) -> str:
    out = []
    k = 0
    for r in rows:
        if r.kind == "same":
            if show_same:
                out.append(f'<div class="dsame">{esc(r.old)}</div>')
            continue
        note = _ai(notes[k]) if notes and k < len(notes) else ""
        k += 1
        if r.kind == "changed":
            out.append(
                f'<div class="drow2 changed"><div class="dlabel2">改寫</div>'
                f'<div class="dold">{r.old_html}</div>'
                f'<div class="darrow">↓ 改為</div>'
                f'<div class="dnew">{r.new_html}</div>{note}</div>')
        elif r.kind == "added":
            out.append(
                f'<div class="drow2 added"><div class="dlabel2">整句新增</div>'
                f'<div class="dnew">{esc(r.new)}</div>{note}</div>')
        else:
            out.append(
                f'<div class="drow2 removed"><div class="dlabel2">整句刪除</div>'
                f'<div class="dold">{esc(r.old)}</div>{note}</div>')
    return "".join(out) or '<div class="empty">這次聲明與上次完全相同</div>'


def _heatmap(matrix: dict) -> str:
    if not matrix.get("phrases"):
        return '<div class="empty">資料不足</div>'
    head = "".join(f"<th>{esc(d[2:7])}</th>" for d in matrix["dates"])
    rows = []
    for p, vals in zip(matrix["phrases"], matrix["grid"]):
        cells = "".join(
            f'<td class="h{min(v,3)}" data-tip="{esc(p)}｜{esc(dte)}｜出現 {v} 次">'
            f'{v if v else ""}</td>'
            for v, dte in zip(vals, matrix["dates"])
        )
        rows.append(f'<tr><th class="rowhead">{esc(p)}</th>{cells}</tr>')
    return (f'<div class="heatwrap"><table class="heat">'
            f'<thead><tr><th class="rowhead"></th>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def _votes(vote: dict) -> str:
    chips = []
    for d in vote.get("dissents", []):
        word = {"hike": "主張升息", "cut": "主張降息", "hold": "主張維持不變",
                **fx.OTHER_DISSENT}.get(d["direction"], "反對")
        chips.append(f'<span class="vchip {d["direction"]}">'
                     f'{esc(d["name"])}　{word}</span>')
    if not chips:
        # 引言載明有反對票、名單卻解析不出來時，
        # 不能顯示「全體一致」——那是把解析失敗謊報成事實
        stated = vote.get("stated_dissent")
        if stated:
            chips.append(f'<span class="vchip">聲明載明 {stated} 張反對票，'
                         '名單解析失敗，請以原文為準</span>')
        else:
            chips.append('<span class="vchip">全體一致，沒有反對票</span>')
    return f'<div class="votes">{"".join(chips)}</div>'


# ---------------------------------------------------------------------------
# 政策訊號：事實清單
# ---------------------------------------------------------------------------
def _signal_rows(d: dict) -> list[tuple[str, str, str, str]]:
    """[(項目, 事實, 方向, 補充)]——不加總、不出分數。"""
    rows = []
    dec = d.get("decision") or {}
    act = dec.get("action")
    rows.append(("政策行動",
                 f"{d.get('decision_label', '—')}，目標區間 {d.get('rate_range', '—')}",
                 {"hike": "hawkish", "cut": "dovish"}.get(act, "neutral"), ""))
    vs = d.get("vote_summary") or {}
    vdir = ("hawkish" if vs.get("hike", 0) > vs.get("cut", 0) else
            "dovish" if vs.get("cut", 0) > vs.get("hike", 0) else "neutral")
    rows.append(("反對票", vs.get("text", "—"), vdir,
                 "反對票要看主張的方向，不是只看張數"))
    risk = d.get("risk") or ("neutral", "—")
    rows.append(("聲明的風險用語", risk[1], risk[0], ""))
    sep, mid = d.get("sep") or {}, d.get("rate_mid")
    if sep and mid is not None:
        yr = (sep.get("years") or ["—"])[0]
        dv = fx.dot_views(sep, 0, mid)
        if dv["median"] is not None:
            gap = (dv["median_exact"] - mid) * 100
            if gap >= 12.5:
                txt, k = f"中位數 {dv['median']:.1f}%，比現行中點高約 {gap / 25:.0f} 碼——委員會自己預期 {yr} 年底前還要再升", "hawkish"
            elif gap <= -12.5:
                txt, k = f"中位數 {dv['median']:.1f}%，比現行中點低約 {abs(gap) / 25:.0f} 碼——委員會預期 {yr} 年底前會降息", "dovish"
            else:
                txt, k = f"中位數 {dv['median']:.1f}%，與現行中點相當——委員會預期 {yr} 年內不再動", "neutral"
            rows.append((f"點陣圖（{yr} 年底）vs 現在", txt, k,
                         f"{dv['up']} 人高於現在、{dv['same']} 人持平、{dv['down']} 人低於現在"))
    mvd = d.get("mvd") or {}
    if mvd.get("text"):
        rows.append(("市場路徑 vs 點陣圖", mvd["text"], mvd["lean"],
                     f"期貨推算 {mvd['year']} 年底 {mvd['market_end']:.2f}%，"
                     f"點陣圖 {mvd['dot_median']:.3f}%"))
    return rows


def _signals_html(d: dict) -> str:
    out = []
    for name, fact, k, note in _signal_rows(d):
        out.append(
            f'<div class="fx-row"><div class="fx-k">{esc(name)}</div>'
            f'<div class="fx-v">{esc(fact)}'
            + (f'<small>{esc(note)}</small>' if note else "")
            + f'</div><div class="fx-dir {DIR_CLS.get(k, "neutral")}">{DIR_ARROW.get(k, "—")}</div></div>')
    return f'<div class="fx-list">{"".join(out)}</div>'


# ---------------------------------------------------------------------------
# 下次會議與靜默期
# ---------------------------------------------------------------------------
def _next_html(d: dict) -> str:
    nm = d.get("next_meeting") or {}
    if not nm:
        return '<div class="empty">行事曆解析失敗，下次會議日期本次不顯示</div>'
    items = []
    for e in d.get("agenda") or []:
        who = esc(e["who"]) if e["who"] else ""
        topic = esc(e["topic"]) if e["topic"] else ""
        body = "　".join(x for x in (who, topic) if x)
        items.append((e["date"], e["kind"], body))
    items.append((nm["blackout_start"], "靜默期開始",
                  "官員不再公開談貨幣政策，直到會後隔天"))
    items.append((nm["date"], "FOMC 會議",
                  f"{nm['span']}，美東 14:00 公布決議（{_tw(nm['date'])}）"))
    items.append((nm["blackout_end"], "靜默期結束", "會後隔天起，官員恢復公開發言"))
    items.sort(key=lambda x: x[0])
    li = "".join(
        f'<li class="tl-{"key" if k in ("FOMC 會議", "靜默期開始") else "ev"}">'
        f'<span class="tl-d">{_md(dte)}</span><b>{esc(k)}</b>'
        f'<span class="tl-b">{b}</span></li>'
        for dte, k, b in items)
    later = "、".join(_md(x) for x in nm.get("later") or [])
    return (f'<div class="fx-bo {nm["blackout_status"]}">{esc(nm["blackout_text"])}</div>'
            f'<ol class="fx-tl">{li}</ol>'
            + (f'<p class="hint" style="margin-top:10px">之後的會議：{esc(later)}</p>' if later else "")
            + '<p class="src">理事的演講與作證取自聯準會官網行事曆；地方聯儲總裁的行程'
              '沒有統一的官方來源，這裡不列（他們的近期發言見「官員最新發言」）。</p>')


# ---------------------------------------------------------------------------
# 委員
# ---------------------------------------------------------------------------


def _initials(o: dict) -> str:
    first = (o.get("name") or "?").split()[0][:1]
    return (first + (o.get("surname") or "")[:1]).upper()


def _vote_strip(votes: list) -> str:
    """近 12 個月逐場：贊成（實心灰）、反對（依方向上色）、未投票（空框）。"""
    if not votes:
        return ""
    cls = {"hike": "haw", "cut": "dov"}
    cells = []
    for v in votes:
        k = ("for" if v["v"] == "for" else
             ("x " + cls.get(v.get("dir"), "oth")) if v["v"] == "against" else "none")
        tip = f'{v["date"]}｜{v["label"]}' + ("（新版聲明只公布票數，依今年委員名單推定）"
                                              if v.get("inferred") else "")
        mark = "✕" if v["v"] == "against" else ""
        cells.append(f'<span class="vs-c {k}" data-tip="{esc(tip)}">{mark}'
                     f'<em>{esc(_md(v["date"]))}</em></span>')
    n_for = sum(1 for v in votes if v["v"] == "for")
    n_ag = sum(1 for v in votes if v["v"] == "against")
    return (f'<div class="vs"><div class="vs-h">近 12 個月 {len(votes)} 場會議：'
            f'贊成 {n_for}、反對 {n_ag}、未投票 {len(votes) - n_for - n_ag}</div>'
            f'<div class="vs-row" style="--n:{len(cells)}">{"".join(cells)}</div>'
            '<div class="vs-leg"><span><i style="background:var(--muted-bar)"></i>贊成</span>'
            '<span><i style="background:var(--critical)"></i>反對：主張升息</span>'
            '<span><i style="background:var(--good)"></i>反對：主張降息</span>'
            '<span><i style="background:var(--warning)"></i>反對其他事項</span>'
            '<span><i style="border:1.5px dashed var(--baseline)"></i>未投票（輪值／未就任）</span>'
            '</div></div>')


def _person_detail(o: dict, pid: str, show: bool) -> str:
    """點人物後下方面板的內容：身分、投票紀錄、近期發言（原「官員最新發言」併入）。"""
    badges = [("投票委員" if o["voter"] else "候補委員（今年不投票）",
               "" if o["voter"] else "muted"),
              ("理事會" if o["board"] else f'{o.get("city_zh") or ""}聯儲', "")]
    bl = "".join(f'<span class="od-b {k}">{esc(t)}</span>' for t, k in badges if t)
    talk = []
    if o.get("gist"):
        talk.append(_ai(o["gist"]))
    for sp in o.get("speeches") or []:
        talk.append(f'<div class="sp-i"><span class="sp-k">官方演講</span>'
                    f'<a href="{esc(sp["url"])}" target="_blank" rel="noopener">{esc(sp["title"])}</a>'
                    f'<span class="sp-d">{_md(sp["date"])}</span></div>')
    for n in o.get("news") or []:
        link = (f'<a href="{esc(n["url"])}" target="_blank" rel="noopener">{esc(n["title"])}</a>'
                if n.get("url") else esc(n["title"]))
        talk.append(f'<div class="sp-i"><span class="sp-k">新聞</span>{link}'
                    f'<span class="sp-d">{esc(n.get("source", ""))}　{_md(n["date"])}</span></div>')
    if not talk:
        talk.append('<div class="sp-i muted">近期沒有談利率的演講或報導</div>')
    tag_cls = DIR_CLS.get(o["lean"], "neutral")
    return (f'<div class="od" id="od-{pid}" data-p="{pid}"{"" if show else " hidden"}>'
            f'<div class="od-head"><span class="ot-av big {tag_cls}">{esc(_initials(o))}</span>'
            f'<div><div class="od-name">{esc(o["name"])}</div>'
            f'<div class="od-title">{esc(o["title"])}</div><div class="od-bs">{bl}'
            f'<span class="fx-tag {tag_cls}">{esc(o["dissent_tag"])}</span></div></div></div>'
            + (f'<div class="fx-pnote">{esc(o["note"])}</div>' if o.get("note") else "")
            + _vote_strip(o.get("votes") or [])
            + f'<div class="od-talk"><div class="vs-h">近期發言</div>{"".join(talk)}</div>'
            + '</div>')


def _node(o: dict, pid: str, on: bool) -> str:
    size = {1: "t1", 2: "t2"}.get(o["tier"], "")
    star = '<i class="ot-star" aria-hidden="true">★</i>' if o["tier"] == 1 else ""
    role = {1: "主席", 2: "副主席"}.get(o["tier"], "")
    if not role:
        role = "理事" if o["board"] else (o.get("city_zh") or "")
    return (f'<button type="button" class="ot-n {size}{" alt" if not o["voter"] else ""}" '
            f'data-p="{pid}" aria-controls="od-{pid}" aria-pressed="{"true" if on else "false"}">'
            f'<span class="ot-av {DIR_CLS.get(o["lean"], "neutral")}">{esc(_initials(o))}{star}</span>'
            f'<span class="ot-sn">{esc(o["surname"])}</span>'
            f'<span class="ot-role">{esc(role)}</span></button>')


def _people_html(d: dict) -> str:
    """
    投票委員與官員：依機構分的樹狀圖（2026-10 使用者指定）。
      FOMC（今年 12 票）→ 理事會 7 ／ 地方聯儲 5（紐約常任＋4 席輪值）／ 候補（不投票）
    人物只放姓名縮寫的圓形標記；外框顏色＝近 12 個月反對票的方向。
    點（觸碰）任何一位，下方面板換成他的身分、逐場投票與近期發言——
    原本獨立的「官員最新發言」併進這裡。
    """
    offs = d.get("officials") or []
    if not offs:
        return '<div class="empty">委員名單本次取得失敗</div>'
    ids = {id(o): f"p{i}" for i, o in enumerate(offs)}
    default = next((o for o in offs if o["tier"] == 1), offs[0])
    board = [o for o in offs if o["voter"] and o["board"]]
    banks = sorted([o for o in offs if o["voter"] and not o["board"]],
                   key=lambda o: (o["tier"], o["surname"]))
    alts = [o for o in offs if not o["voter"]]
    board.sort(key=lambda o: (o["tier"], o["surname"]))

    def branch(cls, head, n, why, grp):
        nodes = "".join(_node(o, ids[id(o)], o is default) for o in grp)
        cnt = f'<b>{n}</b> 票' if n else ""
        return (f'<div class="ot-br {cls}"><div class="ot-bh"><span class="ot-bt">{esc(head)} {cnt}</span>'
                f'<span class="ot-bw">{esc(why)}</span></div><div class="ot-nodes">{nodes}</div></div>')
    n_vote = len(board) + len(banks)
    tree = (f'<div class="ot" data-ot>'
            f'<div class="ot-root"><span>FOMC</span><b>今年 {n_vote} 票</b></div>'
            f'<div class="ot-brs">'
            + branch("board", "理事會", len(board), "總統提名、參議院同意；每場都投票", board)
            + branch("banks", "地方聯儲總裁", len(banks), "紐約常任＋其餘 11 家輪流 4 席", banks)
            + branch("alts", "候補委員", 0, "今年不投票，但參與討論、也交點陣圖", alts)
            + '</div>'
            + '<div class="ot-leg"><span><i class="ot-lg hawkish"></i>近 12 個月投過「主張升息／反對寬鬆」</span>'
              '<span><i class="ot-lg dovish"></i>投過「主張降息」</span>'
              '<span><i class="ot-lg neutral"></i>未投反對票</span>'
              '<span class="ot-hint">點人物看下方詳細資料</span></div>'
            + '<div class="ot-panel" aria-live="polite">'
            + "".join(_person_detail(o, ids[id(o)], o is default) for o in offs)
            + '</div></div>')
    return tree + _composition_html(d, board, banks)


def _composition_html(d: dict, board: list, banks: list) -> str:
    """FOMC 怎麼組成：三張事實卡＋今明兩年的輪值表（取代原本的三段文字）。"""
    yr = int((d.get("latest_date") or "2026")[:4])
    by_city = {o.get("affil"): o for o in (d.get("officials") or []) if not o["board"]}
    groups = [("波士頓／費城／里奇蒙", 0), ("芝加哥／克里夫蘭", 1),
              ("聖路易／達拉斯／亞特蘭大", 2), ("堪薩斯城／明尼亞波利斯／舊金山", 3)]
    rows = ['<tr><th class="rowhead">紐約（常任）</th>'
            + "".join('<td><b>紐約</b></td>' for _ in (yr, yr + 1)) + '</tr>']
    for zh, gi in groups:
        cells = []
        for y in (yr, yr + 1):
            c = fx.rotation(y)[gi]
            who = by_city.get(c)
            sub = f'<small>{esc(who["surname"])}</small>' if who else ""
            cells.append(f'<td><b>{esc(fx.CITY_ZH.get(c, c))}</b>{sub}</td>')
        rows.append(f'<tr><th class="rowhead">{esc(zh)}</th>{"".join(cells)}</tr>')
    facts = [
        ("12 票", f"理事會 {len(board) or 7} 位理事＋{len(banks) or 5} 位地方聯儲總裁"),
        ("一年 8 次", "3、6、9、12 月的會議另外公布經濟預測（SEP）與點陣圖"),
        ("3 週／5 年", "會後 3 週公布會議紀要；完整逐字稿 5 年後公開"),
    ]
    fc = "".join(f'<div class="cf"><b>{esc(a)}</b><span>{esc(b)}</span></div>' for a, b in facts)
    return (f'<details data-m-collapse class="fx-comp"><summary>FOMC 是怎麼組成的</summary>'
            f'<div class="cfs">{fc}</div>'
            f'<div class="viz-h" style="margin-top:14px">地方聯儲投票輪值</div>'
            f'<p class="viz-sub">四組各派一席、逐年輪替；小字是目前的總裁。</p>'
            f'<div class="tscroll"><table class="fx-rot"><thead><tr><th>組別</th>'
            f'<th>{yr} 年</th><th>{yr + 1} 年</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
            f'<p class="hint" style="margin-top:10px">鷹派／鴿派只用<b>已表態的事實</b>標示（近 12 個月的反對票）。'
            f'點陣圖是匿名的，對不上人名，所以不拿來替個人貼標籤。</p></details>')


# ---------------------------------------------------------------------------
# 點陣圖與 SEP
# ---------------------------------------------------------------------------
def _dot_svg(sep: dict, mid: float | None) -> str:
    dots = sep.get("dots") or {}
    rows = [(lv, c) for lv, c in dots.get("rows") or [] if any(c)]
    years = dots.get("years") or []
    if not rows or not years:
        return ""
    lv_all = [lv for lv, _ in rows] + ([mid] if mid is not None else [])
    lo, hi = min(lv_all) - 0.125, max(lv_all) + 0.125
    W, H, L, T, B = 900, 340, 46, 14, 34
    cw = (W - L - 8) / len(years)
    def y(v):
        return T + (hi - v) / (hi - lo) * (H - T - B)
    parts = [f'<svg class="fx-dots" viewBox="0 0 {W} {H}" role="img" '
             f'aria-label="點陣圖：每位與會者對年底政策利率的預測">']
    g = lo - (lo % 0.25) + 0.25
    while g <= hi:
        parts.append(f'<line x1="{L}" x2="{W - 8}" y1="{y(g):.1f}" y2="{y(g):.1f}" class="g"/>'
                     f'<text x="{L - 6}" y="{y(g) + 4:.1f}" class="yl">{g:.2f}</text>')
        g += 0.25
    if mid is not None:
        parts.append(f'<line x1="{L}" x2="{W - 8}" y1="{y(mid):.1f}" y2="{y(mid):.1f}" class="now"/>')
    med = ((sep.get("vars") or {}).get("ffr") or {}).get("median") or []
    for i, yr in enumerate(years):
        cx = L + cw * i + cw / 2
        for lv, c in rows:
            n = c[i] if i < len(c) else 0
            for k in range(n):
                x = cx + (k - (n - 1) / 2) * 9.5
                parts.append(f'<circle cx="{x:.1f}" cy="{y(lv):.1f}" r="4"/>')
        if i < len(med) and med[i] is not None:
            parts.append(f'<line x1="{cx - cw * .42:.1f}" x2="{cx + cw * .42:.1f}" '
                         f'y1="{y(med[i]):.1f}" y2="{y(med[i]):.1f}" class="med"/>')
        lab = "長期" if yr.startswith("Longer") else yr
        parts.append(f'<text x="{cx:.1f}" y="{H - 12}" class="xl">{lab}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _sep_table(sep: dict) -> str:
    years = sep.get("years") or []
    head = "".join(f'<th>{"長期" if y.startswith("Longer") else esc(y)}</th>' for y in years)
    prev_zh = fx.sep_prev_zh(sep)
    body = []
    for key, zh, _ in fx.SEP_VARS:
        v = (sep.get("vars") or {}).get(key)
        if not v:
            continue
        cells = []
        for i in range(len(years)):
            m = v["median"][i] if i < len(v["median"]) else None
            p = v["prev"][i] if i < len(v.get("prev") or []) else None
            if m is None:
                cells.append("<td>—</td>")
                continue
            arrow = ""
            if p is not None and abs(m - p) >= 0.05:
                arrow = (f'<small class="{"up" if m > p else "dn"}">'
                         f'{"▲" if m > p else "▼"} {prev_zh} {p:.1f}</small>')
            elif p is not None:
                arrow = f'<small>持平</small>'
            cells.append(f"<td><b>{m:.1f}</b>{arrow}</td>")
        body.append(f'<tr><th class="rowhead">{esc(zh)}</th>{"".join(cells)}</tr>')
    return (f'<div class="tscroll"><table class="fx-sep"><thead><tr><th></th>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


_SEP_UP_BAD = {"gdp": False, "unrate": True, "pce": True, "core_pce": True, "ffr": None}


def _sep_card(key: str, zh: str, v: dict, years: list, prev_zh: str) -> str:
    """
    SEP 一個變數一張小卡（手機上表格五欄數字太擠）：
      大數字＝今年年底中位數；chip＝跟上一季比；小圖＝逐年路徑（本季實線、上季虛線）
    """
    med = v.get("median") or []
    prv = v.get("prev") or []
    if not med or med[0] is None:
        return ""
    m0, p0 = med[0], (prv[0] if prv else None)
    chip = ""
    if p0 is not None:
        dlt = m0 - p0
        if abs(dlt) < 0.05:
            chip = f'<span class="sc-chip flat">與{esc(prev_zh)}持平</span>'
        else:
            bad = _SEP_UP_BAD.get(key)
            tone = ("" if bad is None else
                    ("haw" if (dlt > 0) == bad else "dov"))
            chip = (f'<span class="sc-chip {tone}">{"▲" if dlt > 0 else "▼"} {abs(dlt):.1f}'
                    f'　{esc(prev_zh)} {p0:.1f}%</span>')
    labs = ["長期" if y.startswith("Longer") else y for y in years]
    pts = [(i, x) for i, x in enumerate(med) if x is not None]
    pps = [(i, x) for i, x in enumerate(prv) if x is not None]
    allv = [x for _, x in pts + pps]
    lo, hi = min(allv), max(allv)
    pad = max((hi - lo) * 0.25, 0.15)
    lo, hi = lo - pad, hi + pad
    n = len(years)

    def X(i):
        return (i + .5) / n * 100

    def Y(x):
        return (1 - (x - lo) / (hi - lo)) * 100
    poly = lambda ps: " ".join(f"{X(i):.1f},{Y(x):.1f}" for i, x in ps)
    svg = (f'<svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">'
           + (f'<polyline points="{poly(pps)}" fill="none" stroke="var(--muted-bar)" '
              f'stroke-width="1.6" stroke-dasharray="4 3" vector-effect="non-scaling-stroke"/>'
              if len(pps) > 1 else "")
           + f'<polyline points="{poly(pts)}" fill="none" stroke="var(--series-1)" '
             f'stroke-width="2" vector-effect="non-scaling-stroke"/></svg>')
    dots = "".join(f'<span class="sc-dot{" now" if i == 0 else ""}" '
                   f'style="left:{X(i):.1f}%;top:{Y(x):.1f}%" '
                   f'data-tip="{esc(labs[i])}｜{x:.1f}%'
                   + (f'（{esc(prev_zh)} {prv[i]:.1f}%）' if i < len(prv) and prv[i] is not None else "")
                   + '"></span>' for i, x in pts)
    xl = "".join(f'<span><b>{"—" if (i >= len(med) or med[i] is None) else f"{med[i]:.1f}"}</b>'
                 f'{esc(labs[i])}</span>' for i in range(n))
    return (f'<div class="sc"><div class="sc-k">{esc(zh)}</div>'
            f'<div class="sc-v">{m0:.1f}<small>%</small></div>'
            f'<div class="sc-y">{esc(labs[0])} 年底中位數</div>{chip}'
            f'<div class="sc-plot">{svg}{dots}</div>'
            f'<div class="sc-x" style="--n:{n}">{xl}</div></div>')


def _sep_cards(sep: dict) -> str:
    years = sep.get("years") or []
    prev_zh = fx.sep_prev_zh(sep)
    order = ["ffr", "core_pce", "pce", "unrate", "gdp"]
    labs = {k: zh for k, zh, _ in fx.SEP_VARS}
    cards = "".join(_sep_card(k, labs[k], (sep.get("vars") or {}).get(k) or {}, years, prev_zh)
                    for k in order if (sep.get("vars") or {}).get(k))
    return (f'<div class="scs">{cards}</div>'
            f'<div class="sc-leg"><span><i class="sc-l now"></i>本季中位數</span>'
            f'<span><i class="sc-l prev"></i>{esc(prev_zh)}</span>'
            f'<span>▲▼ 顏色：紅＝對通膨／就業不利的方向、綠＝有利</span></div>')


def _sep_html(d: dict) -> str:
    sep = d.get("sep")
    if not sep:
        return '<div class="empty">經濟預測摘要本次取得失敗</div>'
    mid = d.get("rate_mid")
    yr = (sep.get("years") or ["—"])[0]
    lead = ""
    if mid is not None:
        dv = fx.dot_views(sep, 0, mid)
        pv = ((sep["vars"]["ffr"].get("prev") or [None])[0])
        lead = (f'{yr} 年底中位數 <b>{dv["median"]:.1f}%</b>'
                + (f'（{fx.sep_prev_zh(sep)} {pv:.1f}%）' if pv is not None else "")
                + f'：{dv["up"]} 人預期還要再升、{dv["same"]} 人預期不動、{dv["down"]} 人預期降。')
    cp = sep["vars"].get("core_pce", {}).get("median") or []
    ys = sep.get("years") or []
    path = ""
    if len(cp) > 1 and cp[0] is not None and cp[1] is not None:
        path = (f'核心 PCE 預測：{ys[0]} 年 {cp[0]:.1f}% → {ys[1]} 年 {cp[1]:.1f}%'
                + (f' → {ys[2]} 年 {cp[2]:.1f}%' if len(cp) > 2 and cp[2] is not None else "")
                + "。")
    return (f'<p class="fx-lead">{lead}</p>'
            + f'<div class="fx-dotwrap">{_dot_svg(sep, mid)}</div>'
            + '<p class="hint" style="margin:4px 0 14px">每個點是一位與會者（理事＋地方聯儲總裁，'
              '含今年不投票的人）認為適當的年底利率中點；紅色橫線是中位數，虛線是現行利率中點'
            + (f'（{mid:.3f}%）' if mid is not None else "") + '。</p>'
            + _sep_cards(sep)
            + '<details data-m-collapse><summary>看完整數字（表格）</summary>'
            + _sep_table(sep) + '</details>'
            + f'<div class="src">{esc(sep.get("date", ""))} 經濟預測摘要（SEP）表 1 與圖 2；'
              '▲▼ 對照上一季的中位數。數值為第四季對第四季的變動（失業率為第四季平均）。</div>')


# ---------------------------------------------------------------------------
# 市場路徑 vs 點陣圖
# ---------------------------------------------------------------------------
def _market_html(d: dict) -> str:
    mvd = d.get("mvd") or {}
    dg = d.get("dgs2") or {}
    foot = ""
    if dg.get("value") is not None:
        foot = (f'<p class="src">參考：2 年期公債殖利率 {dg["value"]:.2f}%'
                + (f'，比政策利率中點高 {dg["gap"]:+.2f} 個百分點' if dg.get("gap") is not None else "")
                + '。2 年期含期限溢酬，不能直接讀成政策路徑，只列為參考。</p>')
    if not mvd.get("meetings"):
        return ('<div class="empty">本次期貨報價不可用（品質檢查未通過或抓取失敗），'
                '市場路徑不顯示。</div>' + foot)
    rows = []
    for m in mvd["meetings"]:
        oc = sorted(m.get("outcomes") or [], key=lambda x: -x[1])
        top = "、".join(f"{_oc_name(b)} {p * 100:.0f}%" for b, p in oc[:2] if p >= 0.005)
        rows.append(f'<tr><td>{_md(m["date"])}</td><td>{m["end"]:.2f}%</td>'
                    f'<td>{m["move_bp"]:+.0f} bp</td><td>{esc(top)}</td></tr>')
    cmp = ""
    if mvd.get("text"):
        cmp = (f'<div class="verdict {DIR_CLS.get(mvd["lean"], "neutral")}" style="margin-top:14px">'
               f'<div class="v-main" style="font-size:18px">{esc(mvd["text"])}</div>'
               f'<div class="v-why" style="margin-top:6px">{mvd["year"]} 年底：期貨推算 '
               f'{mvd["market_end"]:.2f}%，點陣圖中位數 {mvd["dot_median"]:.3f}%，'
               f'差 {mvd["gap_bp"]:+.0f} bp。</div></div>')
    when = (f'（沿用 {mvd["stale_from"]} 的報價）' if mvd.get("stale_from")
            else (f'（{mvd["asof"]}）' if mvd.get("asof") else ""))
    return (f'<div class="tscroll"><table><thead><tr><th>會議</th><th>會後隱含利率</th>'
            f'<th>單場隱含變動</th><th>機率最高的結果</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>{cmp}'
            f'<p class="src">聯邦基金期貨逐場推算{esc(when)}，與首頁 FedWatch chip 同一套算法；'
            '短天期內與 OIS 定價等價。期貨只推到今年最後一場會議，明年以後只看點陣圖。</p>'
            + foot)


def _oc_name(bp) -> str:
    from ..analysis.focus_today import outcome_name
    try:
        return outcome_name(int(bp))
    except (TypeError, ValueError):
        return str(bp)


# ---------------------------------------------------------------------------
# 會議紀要
# ---------------------------------------------------------------------------
def _minutes_html(d: dict) -> str:
    mn = d.get("minutes")
    nxt = d.get("minutes_next")
    nxt_txt = (f'<p class="hint">下一份紀要：{_md(nxt["date"])} 美東 14:00 公布'
               f'（{_tw(nxt["date"])}），之後自動更新。</p>' if nxt else "")
    if not mn:
        return '<div class="empty">會議紀要本次取得失敗</div>' + nxt_txt
    out = []
    for topic, rows in mn.get("groups") or []:
        li = "".join(
            f'<li><span class="q-lv r{min(r["rank"], 8)}">{esc(r["level"])}</span>'
            f'<div><div class="q-en">{esc(r["text"])}</div>{_ai(r.get("zh", ""))}</div></li>'
            for r in rows)
        out.append(f'<h3>{esc(topic)}</h3><ul class="fx-q">{li}</ul>')
    return (f'<p class="fx-lead">{_md(mn["meeting"])} 會議的紀要（{_md(mn["released"])} 公布）。'
            f'只列與會者討論段落裡帶量詞的句子，每個主題取量詞最大的幾句。</p>'
            + nxt_txt + "".join(out)
            + f'<p class="src">原文：<a href="{esc(mn["url"])}" target="_blank" rel="noopener">'
              'federalreserve.gov 會議紀要</a>。量詞依聯準會慣例：全體／幾乎全體 ＞ 多數 ＞ 許多'
              ' ＞ 數位 ＞ 部分 ＞ 少數 ＞ 兩位 ＞ 一位；「普遍」＝原文沒加量詞的'
              '「Participants ...」。</p>')


# ---------------------------------------------------------------------------
# 官員最新發言
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 記者會
# ---------------------------------------------------------------------------
def _presser_html(d: dict) -> str:
    if not d.get("presser_available"):
        reason = d.get("presser_reason", "pending")
        if reason == "no_pdfplumber":
            note = ("<b>環境缺少 PDF 解析套件</b><br>逐字稿是 PDF，需要 <code>pdfplumber</code>。"
                    "這不是等待，不處理就不會自動出現。")
        elif reason == "parse_failed":
            note = "<b>逐字稿解析失敗</b><br>PDF 已下載但無法解析，可能是聯準會改了檔案格式。"
        else:
            note = "<b>尚未發布</b><br>逐字稿為 PDF，通常在會後數日才發布，發布後自動補上。"
        return f'<div class="warnbox" style="margin-top:4px">{note}</div>'
    ps = d.get("presser_summary") or {}
    topics = "".join(
        f'<h3>{esc(t["name"])}</h3>'
        + "".join(f'<div class="pline">{esc(s)}</div>' for s in t["sentences"])
        for t in ps.get("topics", [])
    ) or '<div class="empty">逐字稿中找不到可歸類的段落</div>'
    return (f'<div class="stat-row">'
            f'<div class="stat"><div class="s-label">主席開場</div>'
            f'<div class="s-value">{ps.get("opening_len", 0):,} 字</div></div>'
            f'<div class="stat"><div class="s-label">主席回答</div>'
            f'<div class="s-value">{ps.get("qa_len", 0):,} 字</div>'
            f'<div class="s-note">共 {ps.get("questions", 0)} 則提問</div></div></div>'
            f'<p class="hint" style="margin-top:14px">只摘<b>主席本人</b>的原句，記者的提問不算；'
            f'開場（準備稿）優先，不足才從回答補。不改寫、不計分。</p>{topics}')


# ---------------------------------------------------------------------------
# 目前重心與轉向條件
# ---------------------------------------------------------------------------
_SIDE = {"inflation": ("通膨側", "hawkish"), "employment": ("就業側", "dovish"),
         "balanced": ("兩邊", "neutral")}


def _focus_html(d: dict) -> str:
    focus = d.get("focus") or {}
    cls = {"inflation": "hawkish", "employment": "dovish"}.get(focus.get("focus", ""), "neutral")
    items = focus.get("items") or [{"text": e, "side": "", "quote": ""}
                                   for e in focus.get("evidence") or []]
    ev = "".join(
        f'<li><span class="fx-tag {_SIDE.get(it["side"], ("", "neutral"))[1]}">'
        f'{esc(_SIDE.get(it["side"], ("—",))[0])}</span><div><b>{esc(it["text"])}</b>'
        + (f'<div class="q-en">“{esc(it["quote"])}”</div>' if it.get("quote") else "")
        + '</div></li>'
        for it in items)
    conds = d.get("shift_conds") or []
    cl = "".join(
        f'<li class="{"met" if c["met"] else ""}"><span class="cmark">{"✓" if c["met"] else "○"}</span>'
        f'<div><b>{esc(c["need"])}</b><small>{esc(c["now"])}</small></div></li>'
        for c in conds)
    to = {"inflation": "兩邊並重或就業優先", "employment": "通膨優先"}.get(
        focus.get("focus", ""), "明確的一邊")
    return (f'<div class="dbox {cls}" style="margin-top:4px">'
            f'<div class="dtitle">目前重心</div>'
            f'<div class="dlab" style="font-size:19px;margin-top:6px">{esc(focus.get("label", "—"))}</div>'
            f'<div class="dnote">{esc(focus.get("note", ""))}</div></div>'
            + (f'<h3>判定依據（逐條）</h3><ul class="fx-ev">{ev}</ul>' if ev else "")
            + (f'<h3>什麼情況會轉向{esc(to)}</h3><ul class="fx-cond">{cl}</ul>'
               '<p class="hint">三個條件都取自現成的判定：通膨頁的三分法、勞動頁的失業率、'
               '最新一份 SEP。全部打勾不代表一定轉向，但沒有一項成立時，轉向的機會很低。</p>'
               if cl else "")
            + '<div class="src">判定只用聲明制式句、反對票與主席在記者會的明確表態，不用模型。</div>')


# ---------------------------------------------------------------------------
# 歷次決議
# ---------------------------------------------------------------------------
def _decisions_html(d: dict) -> str:
    rows = []
    for x in d.get("decisions") or []:
        cls = {"hike": "hawkish", "cut": "dovish"}.get(x["action"], "")
        dis = x["dissent"]
        rows.append(f'<tr><td>{esc(x["date"])}</td>'
                    f'<td class="fx-act {cls}">{esc(x["move"])}</td>'
                    f'<td>{esc(x["range"])}</td><td>{esc(x["votes"])}</td>'
                    f'<td>{esc(dis)}</td></tr>')
    return ('<div class="tscroll"><table class="fx-dec"><thead><tr><th>會議</th><th>決議</th>'
            '<th>目標區間</th><th>票數</th><th>反對票</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


# ---------------------------------------------------------------------------
# 組裝
# ---------------------------------------------------------------------------
def _fomc_body_full(d: dict) -> str:
    nm = d.get("next_meeting") or {}
    pair = d.get("diff_pair") or (None, None)
    diff_pair_note = ""
    if pair[0]:
        diff_pair_note = f"比對對象：{esc(pair[0])} → {esc(pair[1])} 的聲明。"
        n = len(d.get("fetched_dates") or [])
        if n:
            diff_pair_note += f"本次共取得 {n} 份聲明。"
    stab = d.get("stability") or {}
    stability_html = (
        f'<div class="verdict {stab["kind"]}" style="margin:0 0 16px">'
        f'<div class="v-main" style="font-size:19px">{esc(stab["title"])}</div>'
        f'<div class="v-why" style="margin-top:8px">{esc(stab["desc"])}</div></div>'
        if stab else "")

    sep = d.get("sep") or {}
    mvd = d.get("mvd") or {}
    mn = d.get("minutes") or {}
    focus = d.get("focus") or {}
    offs = d.get("officials") or []
    n_vote = sum(1 for o in offs if o["voter"])
    _bits = [(d.get("shift") or {}).get("decision_label", "")]
    if sep and d.get("rate_mid") is not None:
        _g = (fx.dot_views(sep, 0, d["rate_mid"])["median_exact"] - d["rate_mid"]) * 100
        _bits.append("點陣圖：年內不再動" if abs(_g) < 12.5 else
                     f"點陣圖：年底前再{'升' if _g > 0 else '降'}約 {abs(_g) / 25:.0f} 碼")
    if mvd.get("text"):
        _bits.append("市場：" + mvd["text"].split("——")[0].replace("市場路徑", "").replace("市場押得", "押得"))
    _sig_sum = "　·　".join(b for b in _bits if b)
    _next_sum = (f'{nm["span"]}（{nm["days"]} 天後）　·　{nm["blackout_text"]}' if nm else "日期待更新")
    _sep_sum = ""
    if sep and d.get("rate_mid") is not None:
        dv = fx.dot_views(sep, 0, d["rate_mid"])
        _sep_sum = f'{sep["years"][0]} 年底中位數 {dv["median"]:.1f}%　·　{dv["up"]} 人預期再升'
    _mkt_sum = mvd.get("text") or ("期貨報價不可用" if not mvd.get("meetings") else "")
    _min_sum = (f'{_md(mn["meeting"])} 會議（{_md(mn["released"])} 公布）'
                if mn else "本次取得失敗")
    if d.get("minutes_next"):
        _min_sum += f'　·　下一份 {_md(d["minutes_next"]["date"])}'
    _ps = d.get("presser_summary") or {}
    _pr_sum = (f'主席原句，{len(_ps.get("topics", []))} 個主題' if d.get("presser_available")
               else "本次逐字稿尚未發布")
    _diff_sum = (f'{d.get("changed_count", 0)} 處改動'
                 + (f'（對照 {pair[0]}）' if pair[0] else ""))

    return f"""
<div class="grid">
  <div class="card">
    <h2 id="signals" data-open="1" data-sum="{esc(_sig_sum)}">政策訊號</h2>
    <p class="hint">每一列是一件文件裡的事實，各自指向一個方向。<b>不加總、不打分數</b>——
      先看它們是不是指向同一邊。</p>
    {teach(
        "把聯準會這次「做了什麼、誰不同意、自己預期什麼、市場信不信」拆成幾件可以核對的事實。",
        "聯準會不會直接說「我們下次要升息」，方向藏在決議、反對票與點陣圖裡。反對票尤其硬——委員用投票表達不同意，比任何形容詞都可信。",
        "幾列都指向同一邊，方向就很清楚；互相矛盾時，矛盾本身就是重點（例如委員會說還要升、市場卻不太信）。")}
    {_signals_html(d)}
    <details data-m-collapse><summary>本次投票明細</summary>
      <div style="margin-top:12px">{_votes(d.get("vote") or {})}</div>
    </details>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="next" data-sum="{esc(_next_sum)}">下次會議與靜默期</h2>
    <p class="hint">靜默期從會議開始前的第二個週六起，到會後隔天結束。這段期間官員不公開談政策，
      所以靜默期前的最後幾場演講特別受注意。</p>
    {_next_html(d)}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="people" data-sum="今年 {n_vote} 位投票委員　·　點人物看投票紀錄與近期發言">投票委員與官員</h2>
    {_people_html(d)}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="sep" data-sum="{esc(_sep_sum or '本次取得失敗')}">點陣圖與經濟預測（SEP）</h2>
    {teach(
        "每季一次（3、6、9、12 月的會議），每位與會者寫下自己預期的利率、成長、失業率與通膨。",
        "這是委員會自己公布的預期路徑。中位數比現行利率高，代表多數人認為還要再升；比現行低則是預期降息。",
        "看兩件事：中位數跟上一季比往哪移、點的分布有多散。點越散，委員會內部分歧越大，路徑越不確定。")}
    {_sep_html(d)}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="market" data-sum="{esc(_mkt_sum)}">市場路徑 vs 點陣圖</h2>
    {teach(
        "聯邦基金期貨推算的每一場會議後的利率，對照點陣圖的年底中位數。",
        "期貨是真金白銀押的利率路徑。它跟點陣圖不一致，代表市場不完全相信委員會的預期。",
        "落差的方向就是之後「有一方要修正」的方向——不是市場改押，就是聯準會改口。")}
    {_market_html(d)}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="diff" data-sum="{esc(_diff_sum)}">聲明逐句比對</h2>
    <p class="hint">「舊 → 新」並排，只標實際改動的字。橘色刪除線是拿掉的字，藍色是新增的字。
      每處改動下方標「AI」的是中文說明。</p>
    {teach(
        "這次的會後聲明跟上一次逐句對照，改了哪幾個字。",
        "聲明是逐字斟酌的文件，一個形容詞的增刪都是刻意的。市場的劇烈反應常常不是因為做了什麼，而是因為改了哪句話。",
        "刪掉鷹派措辭＝往鴿派挪，反之亦然。沒改的句子也是資訊——代表委員會不想讓你改變預期。")}
    {stability_html}
    {d['diff_html']}
    <details data-m-collapse><summary>含未改動段落的全文</summary>
      <div style="margin-top:10px">{d['diff_full_html']}</div></details>
    <details data-m-collapse><summary>關鍵措辭追蹤（熱力圖）</summary>
      <p class="hint" style="margin:10px 0 0">固定一組措辭在每次聲明中出現的次數（字面次數，不計分）。
        <b>整排突然變空白，通常代表體例改變而非立場轉變</b>——Warsh 上任後聲明大幅縮短就是例子。</p>
      <div style="margin-top:12px">{d['heatmap_html']}</div></details>
    <div class="src">{diff_pair_note}原文為英文。</div>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="minutes" data-sum="{esc(_min_sum)}">會議紀要：與會者怎麼分布</h2>
    {teach(
        "會後三週公布的會議紀要，記錄與會者討論了什麼、各種看法有多少人支持。",
        "聲明只有百來字，紀要有好幾千字。聯準會描述「有多少人」用的是固定量詞（most、many、several、a few），所以可以看出某個觀點是主流還是少數。",
        "看政策路徑那一組：「許多與會者認為可能需要緊縮」跟「少數與會者認為」，對下一次會議的意義完全不同。")}
    {_minutes_html(d)}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="presser" data-sum="{esc(_pr_sum)}">記者會：主席怎麼說</h2>
    <p class="hint">市場的實際反應常常來自這裡，而不是聲明本身。</p>
    {_presser_html(d)}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="focus" data-sum="{esc(focus.get('label', '無法判定'))}">目前重心與轉向條件</h2>
    <p class="hint">同一份就業數據，在「通膨優先」與「就業優先」下會導向相反的決定。</p>
    {teach(
        "聯準會有兩個任務：穩物價、顧就業。兩者衝突時，判斷它現在把哪一個擺在前面。",
        "同樣的數據，重心不同結論就相反：就業轉弱時，「就業優先」會降息，「通膨優先」卻會按住不動。",
        "重心翻轉的訊號比數據本身更重要——下面列出轉向需要的條件，每個月可以自己核對。")}
    {_focus_html(d)}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="trend" data-sum="近 {len(d.get('decisions') or [])} 次會議的決議與反對票">歷次決議</h2>
    {_decisions_html(d)}
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2 id="howto" data-sum="資料來源、名詞與注意事項">判讀說明</h2>
    <dl class="gloss">
      <dt>為什麼這一頁沒有分數</dt>
      <dd>先前的「客觀訊號分數」（政策行動 ±3、反對票 ±2、風險句 ±1）權重沒有外部依據，
        而且只看過去；「措辭分數」與「記者會分數」是鷹鴿詞頻，在只剩百來字的聲明、
        以及夾著記者提問的逐字稿上沒有意義。現在每一區只放文件裡的事實，方向自己判斷。</dd>
      <dt>政策方向的標籤怎麼來</dt>
      <dd>首頁與情境合成頁的「偏升息／偏降息」只看實際決議：有升息就是偏升息、有降息就是偏降息；
        維持不變時，看反對票主張的方向。不加權、不合成數字。</dd>
      <dt>為什麼市場定價用期貨、不用 2 年期</dt>
      <dd>2 年期殖利率含期限溢酬，不能直接讀成政策路徑。聯邦基金期貨逐場推出每一場會議後的利率，
        短天期內與 OIS 定價等價。期貨只推到今年最後一場會議。</dd>
      <dt>反對票最重要</dt>
      <dd>反對票是白紙黑字的事實，不會因為主席換人或文風改變而失真。</dd>
      <dt>刪掉的字要小心解讀</dt>
      <dd>聯準會拿掉一個措辭，可能是立場改變，也可能只是主席不想再給指引。</dd>
      <dt>AI 用在哪裡</dt>
      <dd>只有三處，畫面上都標「AI」：聲明改動的中文說明、會議紀要的中文翻譯、官員新聞標題的
        一句話整理。AI 只讀原文，輸出的數字必須在原文找得到，否則不顯示。</dd>
      <dt>文本會落後數據</dt>
      <dd>聲明一年只有八次，中間可能已有兩三份就業與物價報告。文本用來校準數據判讀，不是取代它。</dd>
    </dl>
  </div>
</div>
"""


def fomc_body(d: dict) -> str:
    """頂部決議卡：決議與日期、投票、前次、下次會議與靜默期。"""
    sh = d.get("shift") or {}
    vs = d.get("vote_summary") or {}
    nm = d.get("next_meeting") or {}
    date = d.get("latest_date", "—")
    dec = d.get("decision") or {}
    rng = (fx.range_text(dec.get("lower"), dec.get("upper"))
           if dec.get("lower") is not None else d.get("rate_range", "—"))
    title = f'{d.get("decision_label", "—")}至 {rng}'
    if dec.get("action") == "hold":
        title = f'維持 {rng} 不變'
    prev_txt = ""
    if sh.get("prev_date"):
        prev_txt = f'前次 {_md(sh["prev_date"])}：{sh.get("prev_decision_label", "")}。'
    vote_txt = f'投票 {vs.get("text", "—")}。'
    next_txt = (f'下次會議 {nm["span"]}（{nm["days"]} 天後）　·　{nm["blackout_text"]}'
                if nm else "下次會議日期待更新")
    direction = sh.get("direction", "neutral")
    sep = d.get("sep") or {}
    chips = [state_chip("政策方向", fx.DIR_ZH.get(direction, "中性"),
                        "只看決議與反對票", direction)]
    if sep and d.get("rate_mid") is not None:
        dv = fx.dot_views(sep, 0, d["rate_mid"])
        chips.append(state_chip(f'點陣圖（{sep["years"][0]} 年底）', f'{dv["median"]:.1f}%',
                                f'{dv["up"]} 人預期再升、{dv["same"]} 人不動'))
    mvd = d.get("mvd") or {}
    if mvd.get("market_end") is not None:
        chips.append(state_chip(f'市場（{mvd["year"]} 年底）', f'{mvd["market_end"]:.2f}%',
                                mvd.get("text", "").split("——")[0], mvd.get("lean", "neutral")))
    chips.append(state_chip("目前重心", (d.get("focus") or {}).get("label", "無法判定"),
                            "聲明制式句、反對票、主席表態"))
    src_note = {"fred": "利率區間取自 FRED", "statement": "利率區間取自最新聲明本文（FRED 尚未更新或未取得）",
                "config": "⚠ 利率區間為設定檔後備值，可能已過時"}.get(d.get("rate_src"), "")
    tags = (f'<div class="data-line"><span class="data-tag">聲明 {esc(date)}</span>'
            + (f'<span class="data-tag">{esc(src_note)}</span>' if src_note else "")
            + '<span class="data-tag">不打分數；AI 只用於中文說明（已標示）</span></div>')
    # 全站一致：主卡下方一個「依據」收合。這裡放決議的原文句與票數原文，
    # 讓讀者一點就能核對頂部那行中文。
    _docs = d.get("docs") or []
    _first = ""
    if _docs:
        _t = getattr(_docs[-1], "text_display", "") or ""
        _first = next((x for x in ft_sentences(_t) if "target range" in x), "")
    _ev = ('<div class="logic-strip">'
           + (f'<div class="logic-step"><b>聲明原文</b><span>{esc(_first)}</span></div>' if _first else "")
           + f'<div class="logic-step"><b>投票</b><span>{esc(vs.get("text", "—"))}</span></div>'
           + f'<div class="logic-step"><b>政策方向怎麼標</b><span>有升息就是偏升息、有降息就是偏降息；'
             f'維持不變時看反對票主張的方向。不加權、不打分數。</span></div></div>')
    hero = (f'<div class="grid"><div class="card focus-card">'
            f'<div class="focus-eyebrow">FOMC 決議｜{esc(date)} 會議</div>'
            f'<h2 class="focus-title">{esc(title)}</h2>'
            f'<p class="focus-sub">{esc(vote_txt + prev_txt)}<br>{esc(next_txt)}</p>'
            f'<div class="focus-grid">{"".join(chips)}</div>{focus_evidence(_ev, "看決議原文與標示規則")}'
            f'{tags}</div></div>')
    # 不經過 compact_full：它會刪掉內文的第一個 verdict 框（舊版的重複結論卡），
    # 這一版的內文沒有重複結論，第一個 verdict 是「市場路徑 vs 點陣圖」的比較。
    return hero + _fomc_body_full(d)


def fomc_footer(d: dict) -> str:
    from ..site import source_footer
    return source_footer(
        [("聲明、投票、記者會逐字稿", "聯準會官網 federalreserve.gov", "每次會議"),
         ("經濟預測摘要（SEP）、點陣圖", "聯準會官網", "每季"),
         ("會議紀要", "聯準會官網", "會後三週"),
         ("委員名單、演講與行事曆", "聯準會官網、官方 RSS", "每日"),
         ("政策利率區間", "FRED → 最新聲明 → 設定檔後備值", "每日"),
         ("聯邦基金期貨", "CME（經 Yahoo Finance，延遲報價）", "每日"),
         ("地方聯儲總裁發言", "Google News 標題", "每日")],
        ["本頁不打分數：政策方向只看決議與反對票。",
         "AI 只用在聲明改動說明、紀要翻譯與新聞整理三處，均已標示；數字有機械比對防捏造。",
         "完整會議逐字稿依規定延後五年公布。"],
        head="<b>資料來源</b> 聯準會官網、CME 期貨、FRED")

