"""
首頁「AI 大事」小卡與視窗內容（2026-10-29；資料：src/analysis/ai_events.py）。

視窗內：Anthropic IPO（進行中才顯示：發行條件、估值、申報時間軸）→ 各公司小卡（日期・類型，近 3 天有新事件加小圓點）
→ 選中公司的事件整理與對市場的影響（一次一家）→ AI資料中心擴張與監管 → 依時間看全部（預設收合，可篩類型）→ 跟利率的關係。
"""
from __future__ import annotations

import datetime as dt

from ..site import esc
from . import hs_fcf as FC

AI_ART = (
    '<svg class="duo-ai" viewBox="0 0 320 190" aria-hidden="true" focusable="false">'
    '<defs><linearGradient id="aig" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1f3a68"/>'
    '<stop offset="1" stop-color="#3b6fb6"/></linearGradient></defs>'
    '<g stroke="#9db4d6" stroke-width="2" fill="none" opacity=".9"><path d="M40 40 H110 V70"/><path d="M40 150 H110 V120"/>'
    '<path d="M280 40 H210 V70"/><path d="M280 150 H210 V120"/><path d="M20 95 H110"/><path d="M300 95 H210"/>'
    '<path d="M160 10 V60"/><path d="M160 180 V130"/><path d="M75 15 V40"/><path d="M245 175 V150"/></g>'
    '<g fill="#e8722c"><circle cx="40" cy="40" r="6"/><circle cx="280" cy="150" r="6"/><circle cx="160" cy="10" r="5"/>'
    '<circle cx="20" cy="95" r="5"/></g><g fill="#3b6fb6"><circle cx="40" cy="150" r="6"/><circle cx="280" cy="40" r="6"/>'
    '<circle cx="160" cy="180" r="5"/><circle cx="300" cy="95" r="5"/><circle cx="75" cy="15" r="4"/>'
    '<circle cx="245" cy="175" r="4"/></g><rect x="110" y="60" width="100" height="70" rx="12" fill="url(#aig)"/>'
    '<rect x="124" y="72" width="72" height="46" rx="7" fill="none" stroke="#c9d8ee" stroke-width="1.5" opacity=".7"/>'
    '<text x="160" y="104" text-anchor="middle" font-size="26" font-weight="800" fill="#fff" '
    'font-family="Montserrat,system-ui,sans-serif">AI</text></svg>')
WHY = ("AI 資本支出擴大 → 科技巨頭大量發債（佔投資級公司債的比重上升）→ 公司債與公債搶資金，長端利率承壓。")


def _md(iso: str) -> str:
    try:
        d = dt.date.fromisoformat(str(iso)[:10])
        return f"{d.month}/{d.day}"
    except ValueError:
        return ""


def _srcs(e: dict) -> str:
    """來源獨立一行（2026-10-29）：灰色小字、以「・」分隔，不插在句子裡。"""
    ls = [f'<a href="{esc(l.get("url", ""))}" rel="noopener" target="_blank">{esc(l.get("source") or "來源")}</a>'
          for l in (e.get("links") or [])[:3] if l.get("url")]
    return f'<span class="ai-s">{"・".join(ls)}</span>' if ls else ""


def ai_tile(a: dict | None, hs_agg: list | None = None, dc: dict | None = None) -> tuple[str, str]:
    """回傳 (小卡, 視窗內容)。沒有資料時兩個都是空字串。hs_agg：長端頁的五家合計（每季，億美元）。"""
    if not a or not (a.get("events") or (a.get("ipo") or {}).get("active")):
        return "", ""
    evs = a.get("events") or []
    # 2026-10-29 六宮格：摘要固定一行，只寫公司與類型
    latest = f'{evs[0]["co"]}・{evs[0]["type"]}' if evs else "Anthropic IPO 進行中"
    tile = ('<button type="button" class="duo-card" data-t="ai" data-title="AI 大事" aria-haspopup="dialog">'
            f'<span class="duo-k">近 {a.get("window_days", 14)} 天 {len(evs)} 則</span><span class="duo-t">AI 大事</span>'
            f'<span class="duo-map">{AI_ART}</span>'
            f'<span class="duo-sum">最新：{esc(latest)}</span></button>')
    return tile, ai_panel(a, hs_agg, dc)


def hs_block(agg: list | None) -> str:
    """2026-11：科技巨頭五家合計（FCF＋發債），放在 IPO 下方；數字與長端頁同一份。"""
    chart = FC.fcf_chart(agg or [], "科技巨頭五家合計每季自由現金流與發債", height=200)
    la = FC.latest(agg or [])
    if not chart or not la:
        return ""
    n = lambda bad: ' class="n"' if bad else ""   # noqa: E731
    return ('<div class="hsx" data-sec="sum"><div class="hsx-side">'
            f'<div class="hsx-h"><b>科技巨頭五家合計</b><span>每季・億美元・最新 {esc(la["label"])}</span></div>'
            f'<dl class="hsx-k"><div><dt>FCF</dt><dd{n(la["fcf"] < 0)}>{FC._n(la["fcf"], True)}</dd></div>'
            f'<div><dt>單季發債</dt><dd class="d">{FC._n(la["debt"])}</dd></div>'
            f'<div><dt>資本支出佔現金流</dt><dd{n(la["ratio"] > 100)}>{la["ratio"]:.0f}%</dd></div></dl>'
            + FC.LEGEND +
            '<div class="hsx-f"><span>點長條看明細</span><a href="/rates/#hyperscalers">看長端與債務 →</a></div>'
            f'</div>{chart}</div>')


def _yi(b: float | None) -> str:
    """十億美元 → 「846 億美元」或「1.02 兆美元」。"""
    if b is None:
        return "—"
    return f"{b / 1000:.2f} 兆美元" if abs(b) >= 1000 else f"{b * 10:,.0f} 億美元"


def _yi_rng(a: float, b: float) -> str:
    """區間用同一個單位：任一端到兆就都寫兆（避免「9,161 億美元–1.02 兆美元」）。"""
    if max(abs(a), abs(b)) >= 1000:
        return f"{a / 1000:.2f}–{b / 1000:.2f} 兆美元"
    return f"{a * 10:,.0f}–{b * 10:,.0f} 億美元"


def _shares(n: float | None) -> str:
    return "—" if not n else f"{n / 1e8:,.2f} 億股"


def _val_chart(vs: list[dict]) -> str:
    """媒體報導估值：每天一點（中位數），直線連起；點選看當天各家標題。"""
    if len(vs) < 2:
        return ""
    W, H, P = 600, 120, 26
    vals = [v["median"] for v in vs]
    lo, hi = min(vals) * 0.9, max(vals) * 1.06
    t0 = dt.date.fromisoformat(vs[0]["date"]).toordinal()
    t1 = max(dt.date.fromisoformat(vs[-1]["date"]).toordinal(), t0 + 1)
    X = lambda d: P + (dt.date.fromisoformat(d).toordinal() - t0) / (t1 - t0) * (W - 2 * P)   # noqa: E731
    Y = lambda v: 8 + (1 - (v - lo) / (hi - lo)) * (H - 26)                                   # noqa: E731
    pts = " ".join(f"{X(v['date']):.1f},{Y(v['median']):.1f}" for v in vs)
    rng = ""      # 2026-11：只畫中位數（當天最低～最高的直條拿掉，範圍寫在上方文字）
    dots = "".join(f'<circle cx="{X(v["date"]):.1f}" cy="{Y(v["median"]):.1f}" r="4" fill="var(--series-1)"/>' for v in vs)
    labs = (f'<text x="{X(vs[0]["date"]):.1f}" y="{H - 3}" class="ipo-ax">{_md(vs[0]["date"])}</text>'
            f'<text x="{X(vs[-1]["date"]):.1f}" y="{H - 3}" class="ipo-ax" text-anchor="end">{_md(vs[-1]["date"])}</text>')
    vl = "".join(f'<text x="{X(v["date"]):.1f}" y="{Y(v["median"]) - 8:.1f}" class="ipo-vl" text-anchor="middle">'
                 f'{v["median"] / 1000:.2f}</text>' for i, v in enumerate(vs) if i in (0, len(vs) - 1) or v["n"] >= 3)
    return (f'<svg class="ipo-vc" viewBox="0 0 {W} {H}" role="img" aria-label="媒體報導的 IPO 估值預期">'
            f'<polyline points="{pts}" fill="none" stroke="var(--series-1)" stroke-width="2"/>{rng}{dots}{vl}{labs}</svg>')


def _val_rows(vs: list[dict]) -> str:
    out = ""
    for v in reversed(vs[-6:]):
        its = "・".join(f'<a href="{esc(i["url"])}" target="_blank" rel="noopener">{esc(i["source"])} {i["value"] / 1000:.2f} 兆</a>'
                       for i in v["items"][:4])
        out += f'<li><b>{esc(_md(v["date"]))}</b><span>{its}</span></li>'
    return f'<ul class="ipo-vr">{out}</ul>'


# 申報時間軸的浮動小窗：時間軸在手機會橫捲（overflow 會裁掉絕對定位的子元素），
# 所以小窗放在外層、用 JS 依按鈕位置擺放；內容複製自每個點底下隱藏的 .ipo-pop
IPO_JS = ("<script>(function(){document.querySelectorAll('.ipo-tlw').forEach(function(w){"
          "var fly=w.querySelector('.ipo-fly'),tl=w.querySelector('.ipo-tl'),hide;"
          "function show(li){var pop=li.querySelector('.ipo-pop');if(!pop)return;clearTimeout(hide);li._t=Date.now();"
          "fly.innerHTML=pop.innerHTML;fly.hidden=false;w.querySelectorAll('.ipo-tl>li').forEach(function(x){x.classList.toggle('sel',x===li);});"
          "var b=li.querySelector('button').getBoundingClientRect(),r=w.getBoundingClientRect(),fw=fly.offsetWidth;"
          "var x=b.left-r.left+b.width/2-fw/2;x=Math.max(0,Math.min(x,w.clientWidth-fw));"
          "fly.style.left=x+'px';fly.style.top=(b.bottom-r.top+4)+'px';}"
          "function off(){hide=setTimeout(function(){fly.hidden=true;w.querySelectorAll('.ipo-tl>li.sel').forEach(function(x){x.classList.remove('sel');});},180);}"
          "tl.querySelectorAll('li').forEach(function(li){if(!li.querySelector('.ipo-pop'))return;var bt=li.querySelector('button');"
          "li.addEventListener('mouseenter',function(){show(li);});li.addEventListener('mouseleave',off);"
          "bt.addEventListener('focus',function(){show(li);});bt.addEventListener('blur',off);"
          "bt.addEventListener('click',function(e){e.stopPropagation();"
          "if(!fly.hidden&&li.classList.contains('sel')&&Date.now()-(li._t||0)>400){fly.hidden=true;li.classList.remove('sel');}else show(li);});});"
          "fly.addEventListener('mouseenter',function(){clearTimeout(hide);});fly.addEventListener('mouseleave',off);"
          "tl.addEventListener('scroll',function(){fly.hidden=true;});"
          "document.addEventListener('keydown',function(e){if(e.key==='Escape')fly.hidden=true;});"
          "document.addEventListener('click',function(e){if(!w.contains(e.target))fly.hidden=true;});});})();</script>")


def ipo_block(ipo: dict, x: dict | None) -> str:
    """
    2026-11：IPO 區塊——上方關鍵數字（全部來自 SEC 申報原文，或依原文計算並標明）、
    媒體估值預期的變化、歷輪每股價格（分割調整），最下方申報時間軸（滑鼠移到點／點選看該份文件重點）。
    """
    x = x or {}
    T, Dv = x.get("terms") or {}, x.get("derived") or {}
    name = ipo.get("name", "")
    tick = f'（{T.get("exchange", "Nasdaq").split(" ")[0]}：{T["ticker"]}）' if T.get("ticker") else ""
    kp = []

    def k(label, val, sub=""):
        # 2026-11：三欄（主題｜數字｜補充），一列一個主題
        kp.append(f'<div class="ipo-kr"><span class="ipo-kt">{esc(label)}</span><b>{val}</b>'
                  + (f'<small>{sub}</small>' if sub else "<small></small>") + '</div>')
    if T.get("price_lo"):
        k("價格區間", f'${T["price_lo"]:.0f}–${T["price_hi"]:.0f}', f'中位 ${Dv.get("mid", 0):.0f}・{esc(_md(T.get("price_lo__date", "")))} S-1/A')
    if T.get("shares_offered"):
        k("發行股數", esc(_shares(T["shares_offered"])),
          f'新股 {_shares(T.get("shares_primary"))}・老股 {_shares(T.get("shares_secondary"))}'
          + (f'・超額配售 {_shares(T["greenshoe"])}' if T.get("greenshoe") else ""))
    if Dv.get("gross_lo"):
        k("IPO 募資額", esc(_yi_rng(Dv["gross_lo"], Dv["gross_hi"])), "發行股數 × 價格區間（本站依申報計算）")
    if T.get("private_placement"):
        k("同步私募", esc(_yi(T["private_placement"])), "以 IPO 價格認購 Class N 股（AI 晶片、雲端夥伴）")
    if T.get("net_proceeds"):
        k("預估淨募資", esc(_yi(T["net_proceeds"])),
          f'{"含同步私募、" if T.get("net_incl_pp") else ""}以 ${T.get("assumed_price", 0):.0f} 計'
          + (f'；超額配售全數行使 {_yi(T["net_proceeds_full"])}' if T.get("net_proceeds_full") else ""))
    if Dv.get("cap_lo"):
        k("隱含市值", esc(_yi_rng(Dv["cap_lo"], Dv["cap_hi"])),
          f'發行後 {_shares(T.get("shares_after"))} × 價格區間；媒體常引用的「完全稀釋」口徑（含選擇權等）較高')
    lr = Dv.get("last_round")
    if lr and T.get("price_lo"):
        k(f'最近一輪（Series {lr["series"]}）', f'${lr["adj"]:.2f}／股',
          f'{esc(lr["from"][:7].replace("-", "/"))} 募 {_yi(lr["amount"])}；IPO 區間高出 {lr["vs_lo"]:+.0%}～{lr["vs_hi"]:+.0%}'
          + (f'（已依 {T.get("split", 1):.0f} 比 1 分割調整）' if (T.get("split") or 1) > 1 else ""))
    if T.get("rev_9m"):
        k("營收（前 9 月）", esc(_yi(T["rev_9m"])), f'年增 {T.get("rev_growth", 0):,.0f}%'
          + (f'・營業虧損 {_yi(T["op_loss_9m"])}' if T.get("op_loss_9m") else ""))
    vs = x.get("valuations") or []
    val = ""
    if vs:
        last = vs[-1]
        ref = next((v for v in vs if (dt.date.fromisoformat(last["date"]) - dt.date.fromisoformat(v["date"])).days <= 30), vs[0])
        chg = (last["median"] / ref["median"] - 1) if ref is not last else None
        rng = f'{last["lo"] / 1000:.2f}–{last["hi"] / 1000:.2f} 兆美元' if last["hi"] > last["lo"] else f'{last["median"] / 1000:.2f} 兆美元'
        val = ('<div class="ipo-val"><div class="ipo-vh"><b>媒體報導的估值預期</b>'
               f'<span>{esc(_md(last["date"]))}：{rng}（{last["n"]} 則，中位 {last["median"] / 1000:.2f} 兆）'
               + (f'；較 {esc(_md(ref["date"]))} 的 {ref["median"] / 1000:.2f} 兆 {chg:+.0%}' if chg is not None else "")
               + '</span></div>' + _val_chart(vs)
               + f'<details class="ipo-vd"><summary>報導來源（{min(len(vs), 6)} 天・{sum(min(len(v["items"]), 4) for v in vs[-6:])} 則）</summary>'
               + _val_rows(vs) + '</details>'
               + '<p class="ipo-fn">主要媒體標題中的估值數字（Reuters、Bloomberg、WSJ、FT、CNBC、AP、NYT 等），每天取中位數；'
               '各家口徑不同（完全稀釋或發行後股數），同一天常並存兩個數字。</p></div>')
    rounds = Dv.get("rounds_adj") or []
    rnd = ""
    if rounds and T.get("price_lo"):
        mx = T["price_hi"]
        bars = "".join(f'<li><span>Series {esc(r["series"])}<em>{esc(r["from"][:7].replace("-", "/"))}</em></span>'
                       f'<span class="trk"><i style="left:0;width:{r["adj"] / mx * 100:.1f}%"></i></span>'
                       f'<b>${r["adj"]:.2f}</b></li>' for r in rounds)
        bars += (f'<li class="ipo-now"><span>IPO 區間<em>{esc(_md(T.get("price_lo__date", "")))}</em></span>'
                 f'<span class="trk"><i class="base" style="left:0;width:{T["price_lo"] / mx * 100:.1f}%"></i>'
                 f'<i class="r" style="left:{T["price_lo"] / mx * 100:.1f}%;width:{(T["price_hi"] - T["price_lo"]) / mx * 100:.1f}%"></i></span>'
                 f'<b>${T["price_lo"]:.0f}–{T["price_hi"]:.0f}</b></li>')
        rnd = ('<div class="ipo-rd"><div class="ipo-vh"><b>每股價格的變化</b><span>歷輪優先股（申報原文，依股票分割調整）→ IPO 價格區間</span></div>'
               f'<ul>{bars}</ul></div>')
    # 申報時間軸：每份申報一個點（DRS → S-1 → 修正 → 定價 → 掛牌）
    fl = x.get("filings") or []
    pts = []
    n_all = len(fl) + 2
    for i, f in enumerate(fl):
        side = "l" if i < 2 else ("r" if i >= n_all - 3 else "")
        li = "".join(f'<li>{esc(p)}</li>' for p in f.get("points") or [])
        pts.append(f'<li class="done {side}"><button type="button" aria-label="{esc(f["form_zh"])} {esc(f["date"])} 重點">'
                   f'<b>{esc(f["form"])}</b><span>{esc(_md(f["date"]))}</span></button>'
                   f'<div class="ipo-pop" role="tooltip"><div class="ipo-pop-h">{esc(f["form_zh"])}・{esc(f["date"])}</div>'
                   + (f'<div class="ipo-pop-c">{esc(f["change"])}</div>' if f.get("change") else "")
                   + f'<ul>{li}</ul><a href="{esc(f.get("url", ""))}" target="_blank" rel="noopener">SEC 原文 →</a></div></li>')
    steps = {s["label"]: s.get("date") for s in ipo.get("steps") or []}
    for lab, side in (("定價", "r"), ("掛牌", "r")):
        d = steps.get(lab)
        pts.append(f'<li class="{"done" if d else "todo"} {side}"><button type="button" disabled><b>{lab}</b>'
                   f'<span>{esc(_md(d)) if d else "待定"}</span></button></li>')
    tl = (f'<div class="ipo-tlw"><div class="ipo-vh"><b>申報時間軸</b><span>滑鼠移到點（手機點選）看該份文件重點</span></div>'
          f'<ol class="ipo-tl">{"".join(pts)}</ol><div class="ipo-fly" role="tooltip" hidden></div></div>{IPO_JS}') if fl else ""
    if not fl:   # 細節還沒抓到：退回舊的四步驟
        steps_html = "".join(f'<li class="{"done" if s.get("date") else ""}"><b>{esc(s["label"])}</b>'
                             f'<span>{esc(_md(s["date"])) or "—"}</span></li>' for s in ipo.get("steps") or [])
        tl = f'<ol class="ai-ipo">{steps_html}</ol>'
    return (f'<div class="ai-hl-c ipo2" data-sec="ipo"><details class="ai-hl-i"><summary class="ai-hl-k">'
            f'進行中・{esc(name)} IPO{esc(tick)}<i aria-hidden="true">ⓘ</i></summary>'
            '<div class="ai-hl-n">發行條件、營收與歷輪價格直接取自 SEC 申報原文（標「本站依申報計算」者為依原文數字相乘）；'
            '每份申報的重點由 AI 依原文節錄整理，數字須在原文找得到；掛牌後這一格自動消失</div></details>'
            + (f'<div class="ipo-kg">{"".join(kp)}</div>' if kp else "") + val + rnd + tl + '</div>')


def ai_panel(a: dict, hs_agg: list | None = None, dc: dict | None = None) -> str:
    evs = a.get("events") or []
    out = []
    ipo = a.get("ipo") or {}
    if ipo.get("active"):
        out.append(ipo_block(ipo, a.get("ipo_x")))
    out.append(hs_block(hs_agg))
    # 公司小卡：依最近事件日期排序，沒事件的排最後
    cos = a.get("companies") or []
    last = {}
    for e in evs:
        if e["co"] not in last or e["date"] > last[e["co"]]["date"]:
            last[e["co"]] = e
    order = sorted(cos, key=lambda c: last[c]["date"] if c in last else "", reverse=True)
    tiles, panes = [], []
    for k, c in enumerate(order):
        lt = last.get(c)
        if lt:
            dot = '<i class="ai-new"></i>' if lt["date"] >= a.get("new_since", "9") else ""
            sub = f'<span class="ai-tl-tx">{dot}{esc(_md(lt["date"]))}・{esc(lt["type"])}</span>'
        else:
            sub = '<span class="ai-tl-tx none">無近期事件</span>'
        on = k == 0
        tiles.append(f'<button type="button" class="ai-tile{" on" if on else ""}" data-co="{esc(c)}" '
                     f'aria-pressed="{"true" if on else "false"}"><b>{esc(c)}</b>{sub}</button>')
        mine = [e for e in evs if e["co"] == c]

        def _li(e):
            # 2026-11：同一件事被多次報導（合併後）標「10/29 起 3 次報導」
            mg = (f'<em class="ai-mg">{esc(_md(e["first"]))} 起 {e["n"]} 次報導</em>'
                  if (e.get("n") or 1) > 1 and e.get("first") and e["first"] < e["date"] else "")
            return (f'<li><span class="ai-p-d">{esc(_md(e["date"]))}</span><span class="ai-p-t">{esc(e["type"])}</span>'
                    f'<span class="ai-p-x">{esc(e["zh"])}{mg}{_srcs(e)}</span></li>')
        top = "".join(_li(e) for e in mine[:5]) or '<li class="none">近 14 天沒有重大事件</li>'
        rest = (f'<details class="ai-more"><summary>其餘 {len(mine) - 5} 則</summary>'
                f'<ul class="ai-p-l">{"".join(_li(e) for e in mine[5:])}</ul></details>') if len(mine) > 5 else ""
        imp = (a.get("impact") or {}).get(c, "")
        # 2026-11：公司名稱 → 對市場的影響 → 近 5 則（其餘收合）
        panes.append(f'<div class="ai-pane" data-co="{esc(c)}"{"" if on else " hidden"}>'
                     f'<div class="ai-pane-h">{esc(c)}<span>近 {a.get("window_days", 14)} 天 {len(mine)} 則</span></div>'
                     + (f'<div class="ai-pane-k">對市場的影響<em>AI 依下列事件整理</em></div><p class="ai-p-imp">{esc(imp)}</p>'
                        if imp else "")
                     + f'<div class="ai-pane-k">{"近 5 則" if len(mine) > 5 else "事件整理"}</div><ul class="ai-p-l">{top}</ul>{rest}</div>')
    out.append('<div class="ai-sec-h" data-sec="co"><h3>各公司近況</h3><span><i class="ai-new"></i> 近 3 天有新事件</span></div>'
               f'<div class="ai-tiles">{"".join(tiles)}</div><div class="ai-panes">{"".join(panes)}</div>')
    # 2026-11：AI資料中心擴張與監管（各公司近況下方）
    from .dc_map import dc_block
    _dc = dc_block(dc)
    if _dc:
        out.append('<div data-sec="dc"></div>' + _dc)
    # 依時間看全部
    days: dict = {}
    for e in evs:
        days.setdefault(e["date"], []).append(e)
    # 2026-10-29：左側時間軸——每天第一則實心點＋日期，其餘空心點；右邊「公司・類型」→ 內文 → 來源
    tl = ""
    for d in sorted(days, reverse=True):
        for i, e in enumerate(days[d]):
            tl += (f'<div class="ai-r{" day" if i == 0 else ""}" data-ty="{esc(e["type"])}">'
                   f'<span class="ai-r-d">{esc(_md(d)) if i == 0 else ""}</span>'
                   f'<div class="ai-r-b"><div class="ai-r-m">{esc(e["co"])}・{esc(e["type"])}</div>'
                   f'<div class="ai-r-x">{esc(e["zh"])}</div>{_srcs(e)}</div></div>')
    if evs:
        types = ["全部類型", "財報", "資本支出", "發債", "融資／IPO", "算力合約"]
        out.append(f'<details class="ai-all" data-sec="all"><summary><span class="ai-sum-t">依時間看全部（近 {a.get("window_days", 14)} 天 '
                   f'{len(evs)} 則）</span><label class="ai-sel"><select aria-label="事件類型">'
                   + "".join(f'<option>{t}</option>' for t in types) + '</select></label></summary>'
                   f'<div class="ai-tl">{tl}</div></details>')
    out.append(f'<div class="ai-why"><b>跟利率的關係</b><p>{esc(WHY)}<a href="/rates/">看長端與債務 →</a></p></div>'
               '<p class="ai-note">事件由 AI 依新聞標題整理成一句中文，每則附原文連結；只收財報、資本支出、發債、'
               '融資／IPO、算力合約五類。</p>')
    # 2026-11：區塊標題列（視窗打開時移到標題下方；手機往下滑收起、往上滑出現，桌機固定）
    body = "".join(out)
    secs = [(k, lab) for k, lab in (("ipo", "IPO"), ("sum", "合計"), ("co", "公司"), ("dc", "資料中心"), ("all", "全部"))
            if f'data-sec="{k}"' in body]
    _on = ' class="on"'
    nav = ('<nav class="ai-nav" aria-label="區塊">' + "".join(
        f'<button type="button" data-go="{k}"{_on if i == 0 else ""}>{lab}</button>' for i, (k, lab) in enumerate(secs))
           + '</nav>') if len(secs) >= 2 else ""
    return '<div class="ai-wrap">' + nav + body + '</div>'
