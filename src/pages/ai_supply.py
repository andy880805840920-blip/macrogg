"""
AI 大事視窗最上面的「AI 供需」（2026-11；計算：src/analysis/ai_supply.py，設定：config/ai_supply.yaml）。

由上往下：結論 → 兩個指標（隱含利用率｜每月新增 ARR）→ 供給｜需求（桌機左右、手機上下且明細收合）
→ 相關數字小籤（點了跳到視窗內的合計／資料中心）→ 算法與假設（收合）→ 註腳。
"""
from __future__ import annotations

import datetime as dt

from ..site import esc
from .hs_fcf import latest as _fcf_latest


def _md(iso: str) -> str:
    try:
        d = dt.date.fromisoformat(str(iso)[:10])
        return f"{d.month}/{d.day}"
    except ValueError:
        return ""


def _n(v: float) -> str:
    return f"{v:,.0f}"


def _rel(hs_agg, dc) -> str:
    chips = []
    r = _fcf_latest(hs_agg or [])
    if r:
        chips.append(("sum", f'五家資本支出 {_n(r["capex"])} 億／季'))
        chips.append(("sum", f'資本支出佔現金流 {r["ratio"]:.0f}%'))
        if r.get("debt"):
            chips.append(("sum", f'單季發債 {_n(r["debt"])} 億'))
    tot = (dc or {}).get("total") or {}
    if tot:
        y = max(tot)
        mw = (tot[y] or {}).get("mw")
        if mw:
            chips.append(("dc", f'全美 AI 算力 {y} 年 {mw / 1000:.1f} GW'))
    if not chips:
        return ""
    return ('<div class="sd-rel">' + "".join(
        f'<button type="button" data-go="{k}">{esc(t)}<i aria-hidden="true">›</i></button>' for k, t in chips) + '</div>')


def sd_block(sd: dict | None, hs_agg: list | None = None, dc: dict | None = None) -> str:
    if not sd:
        return ""
    util, net, need_mo = sd["util"], sd["net_mo"], sd["needed_mo"]
    cost = sd["cost"]
    c = sd.get("c") or {}
    # ① 結論
    sub = (f'每月新增 ARR 約 {_n(net)} 億，'
           + ("高於" if net >= need_mo else "低於")
           + f'新增算力所需的 {_n(need_mo)} 億')
    head = (f'{esc(sd["verdict"])}：AI 營收約為算力每年需回收的 {util:.0f}%')
    out = [f'<div class="sd" data-sec="sd"><div class="sd-hd"><h3>AI 供需</h3>'
           f'<span>資料至 {esc(_md(sd["asof"]))}・財報季更新</span></div>'
           f'<div class="sd-v sd-{esc(sd["tone"])}"><b>{head}</b><small>{esc(sub)}</small></div>']
    # ② 兩個指標
    ub = min(util, 120) / 120 * 100
    mx = max(need_mo * 1.6, net * 1.2)
    out.append(
        '<div class="sd-kpis">'
        f'<div class="sd-k"><div class="sd-kt">隱含利用率</div><div class="sd-kv{" o" if util < 100 else ""}">{util:.0f}%</div>'
        '<div class="sd-ks">AI 實驗室年化營收 ÷ 算力每年需要賺的錢</div>'
        f'<div class="sd-ub" role="img" aria-label="隱含利用率 {util:.0f}%，100% 為打平">'
        f'<i style="width:{ub:.1f}%"></i><span class="mk" style="left:{100 / 120 * 100:.1f}%"><em>100% 打平</em></span></div></div>'
        f'<div class="sd-k"><div class="sd-kt">實驗室每月新增 ARR</div><div class="sd-kv">約 {_n(net)} 億</div>'
        f'<div class="sd-ks">需要約 {_n(need_mo)} 億才追得上新增算力（近 4 季出貨 {sd["gw4"]:.1f} GW）</div>'
        f'<div class="sd-g" role="img" aria-label="每月新增 ARR 約 {_n(net)} 億，需要 {_n(need_mo)} 億" '
        f'style="--nd:{need_mo / mx * 100:.1f}%"><span class="mk" style="left:{need_mo / mx * 100:.1f}%"><em>需要 {_n(need_mo)}</em></span>'
        f'<span class="pt" style="left:{min(net / mx, 1) * 100:.1f}%"></span></div></div></div>')
    # ③ 供給｜需求
    sv = sd["vendors"]
    rq = sd["rev_q"] or 1
    sup = "".join(
        f'<div class="sd-r"><span>{esc(v["name"])} {esc(v["seg"])}{"＊" if v["star"] else ""}</span>'
        f'<b>{_n(v["last"]["v"])} 億</b><small>{esc(v["last"]["label"])}（{esc(_md(v["last"]["end"]))}）'
        f'{"・估" if v["last"]["est"] else ""}・每 GW 約 {_n(v["per_gw"])} 億 → {v["last"]["gw"]:.1f} GW</small></div>'
        for v in sv)
    sbar = "".join(f'<i class="c{i}" style="width:{v["last"]["v"] / rq * 100:.1f}%"></i>' for i, v in enumerate(sv))
    fleet = (f'<div class="sd-r sd-fl"><span>已出貨且滿 9 個月的算力</span><b>約 {sd["fleet"]:.1f} GW</b>'
             f'<small>近 6 年累計，每 GW 每年需賺約 {_n(cost["total"])} 億 → 需 {_n(sd["need"])} 億</small></div>')
    labs = sd["labs"]
    dm = sd["demand"] or 1
    dem = "".join(
        f'<div class="sd-r"><span>{esc(x["name"])}</span><b>{_n(x["v"])} 億</b>'
        f'<small>{esc(_md(x["date"]))} {esc(x["src"])}'
        + (f'・每月新增約 {_n(x["per_month"])} 億（{esc(_md(x["prev"]["date"]))} {_n(x["prev"]["v"])} 億起）'
           if x.get("per_month") is not None else "") + '</small></div>' for x in labs)
    dbar = "".join(f'<i class="c{i}" style="width:{x["v"] / dm * 100:.1f}%"></i>' for i, x in enumerate(labs))
    out.append(
        '<div class="sd-two">'
        f'<div class="sd-col"><h4>供給：AI 晶片營收<b>{_n(sd["rev_q"])} 億／季</b></h4>'
        f'<div class="sd-sub">各家最新一季・近 4 季合計約當每年新增 {sd["gw4"]:.1f} GW</div>'
        f'<div class="sd-bar" aria-hidden="true">{sbar}</div>'
        f'<details class="sd-more"><summary><span>{len(sv)} 家明細・已出貨算力</span></summary>{sup}{fleet}</details>'
        f'<div class="sd-det">{sup}{fleet}</div></div>'
        f'<div class="sd-col"><h4>需求：AI 年化營收<b>{_n(sd["demand"])} 億</b></h4>'
        '<div class="sd-sub">只算有公開數字的 AI 實驗室</div>'
        f'<div class="sd-bar" aria-hidden="true">{dbar}</div>'
        f'<details class="sd-more"><summary><span>{len(labs)} 家明細</span></summary>{dem}'
        '<div class="sd-r sd-na"><span>其他模型、廣告、省下的人力</span><b>未計</b><small>沒有可靠的公開數字</small></div></details>'
        f'<div class="sd-det">{dem}'
        '<div class="sd-r sd-na"><span>其他模型、廣告、省下的人力</span><b>未計</b><small>沒有可靠的公開數字</small></div></div>'
        '</div></div>')
    out.append(_rel(hs_agg, dc))
    # ④ 算法與假設
    how = [
        f'供給：各家 AI（或資料中心）營收 ÷ 每 GW 晶片金額（'
        + "、".join(f'{v["name"]} {_n(v["per_gw"])} 億' for v in sv) + '，依各公司法說）→ 出貨 GW。',
        f'已上線算力：出貨滿 {esc(_md(sd["lag"]))} 以前（約 9 個月建置期）、{sd["start"][:4]} 年 {int(sd["start"][5:7])} 月以後（近 6 年）的累計，約 {sd["fleet"]:.1f} GW。',
        f'每 GW 每年需賺 {_n(cost["total"])} 億＝伺服器折舊 {cost["server"]:.0f}（{_n(c.get("build", 550))} 億 × {c.get("server_share", 0.7):.0%} ÷ {c.get("server_life", 5.6)} 年，四大雲 10-K 平均）'
        f'＋機房折舊 {cost["shell"]:.0f}（÷ {c.get("shell_life", 20)} 年）＋電費 {cost["power"]:.1f}（EIA 工業電價 {c.get("power_cents", 9.64)} 美分／度，全年滿載）'
        f'＋資金成本 {cost["capital"]:.0f}（{c.get("rate", 0.055):.1%} × 借款 {c.get("debt_share", 0.6):.0%}）。',
        f'隱含利用率＝實驗室年化營收 {_n(sd["demand"])} 億 ÷（{sd["fleet"]:.1f} GW × {_n(cost["total"])} 億）＝{util:.0f}%。',
        f'每月新增 ARR 要追上的量＝近 4 季出貨 {sd["gw4"]:.1f} GW × {_n(cost["total"])} 億 ÷ 12 ≈ {_n(need_mo)} 億；'
        '實際值＝各實驗室最近兩個公開數字之間的每月增幅相加。',
        '判斷：利用率 ≥ 100% 且每月新增 ≥ 需要量＝跟得上；利用率 ≥ 95%＝大致打平；其餘＝追不上。',
    ]
    out.append('<details class="sd-how"><summary><span>算法與假設</span></summary><ol>'
               + "".join(f'<li>{esc(h)}</li>' for h in how) + '</ol></details>'
               '<p class="sd-fn">＊AMD、Marvell 未單拆 AI，用整個資料中心營收（含非 AI）；聯發科不在 SEC 申報，暫缺。'
               '標「估」者依年增率、季增率或年度數字推算。計算邏輯參考 Threads 上的 AI 供需分析文章，數字為本站依公開財報與報導估算。</p></div>')
    return "".join(out)
