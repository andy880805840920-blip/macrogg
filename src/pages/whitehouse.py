"""
首頁「白宮與國會」小卡與視窗（2026-11；資料：src/analysis/whitehouse.py，設定：config/whitehouse.yaml）。

視窗由上往下：本週重點（下方淡線＋選後一行）→ 篩選主題（一組，同時篩發言與政策）→
川普說了什麼｜政策進度（桌機左右、手機上下）→ 政策不確定性指數。
"""
from __future__ import annotations

import datetime as dt

from ..site import esc

# 2026-11：小卡圖改用使用者提供的川普插畫（ChatGPT 生成，assets/brand/wh-trump.webp，透明背景）。
# 舊的白宮向量圖（WH_ART）保留：要換回時把下面小卡裡的 WH_IMG 改成 WH_ART。
WH_IMG = '<img class="duo-wh-img" src="/brand/wh-trump.webp" alt="" width="560" height="273" loading="lazy" decoding="async">'
WH_ART = (
    '<svg class="duo-wh" viewBox="0 0 320 190" aria-hidden="true" focusable="false">'
    '<defs><linearGradient id="whg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1f3a68"/>'
    '<stop offset="1" stop-color="#3b6fb6"/></linearGradient></defs>'
    '<rect x="20" y="150" width="280" height="6" rx="3" fill="#9db4d6" opacity=".6"/>'
    '<rect x="40" y="82" width="240" height="68" rx="3" fill="url(#whg)"/>'
    '<rect x="34" y="76" width="252" height="8" rx="2" fill="#1f3a68"/>'
    '<path d="M118 84 Q160 40 202 84 Z" fill="#2b5292"/>'
    '<rect x="116" y="80" width="88" height="8" rx="2" fill="#1f3a68"/>'
    + "".join(f'<rect x="{x}" y="88" width="6" height="56" rx="1" fill="#e8eef7"/>' for x in range(128, 196, 13))
    + "".join(f'<rect x="{x}" y="{y}" width="12" height="16" rx="1" fill="#c9d8ee" opacity=".85"/>'
              for x in (52, 78, 104, 204, 230, 256) for y in (92, 120))
    + '<rect x="158" y="18" width="2.5" height="40" fill="#1f3a68"/>'
    '<path d="M160.5 19 h24 l-5 6 l5 6 h-24 z" fill="#e8722c"/>'
    '<rect x="148" y="122" width="24" height="28" rx="12" fill="#1f3a68"/></svg>')


def _md(iso: str) -> str:
    try:
        d = dt.date.fromisoformat(str(iso)[:10])
        return f"{d.month}/{d.day}"
    except ValueError:
        return ""


def _tp(topics) -> str:
    return esc("|".join(topics))


def wh_tile(w: dict | None) -> tuple[str, str]:
    """回傳 (小卡, 視窗內容)。沒有資料時兩個都是空字串。"""
    if not w or not (w.get("items") or w.get("policies")):
        return "", ""
    items = w.get("items") or []
    ns = w.get("new_since", "9")
    moved = sum(1 for p in w.get("policies") or [] if p.get("changed", "") >= ns)
    kick = f'近 {w.get("window_days", 7)} 天 {len(items)} 則發言' + (f"・{moved} 項進度更新" if moved else "")
    if items:
        x = items[0]
        latest = f'{x["topic"]}・{_md(x["date"])}'
        dot = '<i class="ai-new"></i>' if x["date"] >= ns else ""
    else:
        p = next((p for p in w.get("policies") or [] if p.get("days") is not None), None)
        latest, dot = (f'{p["name"]}・倒數 {p["days"]} 天' if p else "政策進度"), ""
    tile = ('<button type="button" class="duo-card" data-t="wh" data-title="白宮與國會" aria-haspopup="dialog">'
            f'<span class="duo-k">{esc(kick)}</span><span class="duo-t">白宮與國會</span>'
            f'<span class="duo-map">{WH_IMG}</span>'
            f'<span class="duo-sum">{dot}最新：{esc(latest)}</span></button>')
    return tile, wh_panel(w)


def _status(p: dict) -> str:
    d = p.get("days")
    if d is not None and d <= 45:
        return f'<span class="wh-tag wh-tag-d">{"今天" if d == 0 else f"倒數 {d} 天"}</span>'
    return f'<span class="wh-tag">{esc(p.get("status") or "進行中")}</span>' if p.get("status") else ""


def _policy(p: dict, ns: str) -> str:
    n = len(p["stages"])
    bars = "".join(f'<i class="{"on" if i < p["stage"] else ""}{" cur" if i == p["stage"] - 1 else ""}"></i>'
                   for i in range(n))
    labels = "".join(f'<span class="{"cur" if i == p["stage"] - 1 else ""}">{esc(s)}</span>'
                     for i, s in enumerate(p["stages"]))
    nx = ((_md(p["next_date"]) + " ") if p.get("next_date") else "") + p.get("next_text", "")
    lk = p.get("link") or {}
    link = (f'<a href="{esc(lk.get("href", ""))}">{esc(lk.get("label") or "看更多")} →</a>'
            if lk.get("href") else "")
    dot = '<i class="ai-new"></i>' if p.get("changed", "") >= ns else ""
    return (f'<div class="wh-p" data-tp="{_tp(p["topics"])}"><div class="wh-ph"><b>{dot}{esc(p["name"])}</b>{_status(p)}</div>'
            f'<div class="wh-st" style="--n:{n}">{bars}</div><div class="wh-sl" style="--n:{n}">{labels}</div>'
            + (f'<p class="wh-nx"><em>下一步</em>{esc(nx)}</p>' if nx.strip() else "")
            + (f'<p class="wh-im">影響：{esc(p["impact"])}{link}</p>' if p.get("impact") else "")
            + '</div>')


def _spark(pts) -> str:
    vs = [v for _, v in pts]
    if len(vs) < 2:
        return ""
    lo, hi = min(vs), max(vs)
    sp = (hi - lo) or 1
    xy = " ".join(f"{i / (len(vs) - 1) * 200:.1f},{30 - (v - lo) / sp * 26:.1f}" for i, v in enumerate(vs))
    return (f'<svg class="wh-spark" viewBox="0 0 200 32" preserveAspectRatio="none" aria-hidden="true">'
            f'<polyline points="{xy}" vector-effect="non-scaling-stroke"/></svg>')


def wh_panel(w: dict) -> str:
    ns = w.get("new_since", "9")
    out = []
    # ① 本週重點＋選後一行
    after = (f'<div class="wh-after"><b>選後</b>{esc(w["after"])}</div>' if w.get("after") else "")
    if w.get("summary") or after:
        out.append('<div class="wh-c wh-lead"><div class="wh-k">本週重點</div>'
                   + (f'<p class="wh-sum">{esc(w["summary"])}</p><p class="wh-ai">AI 依下方內容整理</p>'
                      if w.get("summary") else "")
                   + after + '</div>')
    # 篩選主題（一組，同時篩兩邊）
    tps = w.get("topics") or []
    out.append('<div class="wh-f" role="group" aria-label="篩選主題"><span>篩選主題</span>'
               '<button type="button" class="on" data-f="" aria-pressed="true">全部</button>'
               + "".join(f'<button type="button" data-f="{esc(t)}" aria-pressed="false">{esc(t)}</button>' for t in tps)
               + '</div>')
    # ② 川普說了什麼
    win = w.get("window_days", 7)
    sts = "".join(
        f'<div class="wh-s" data-tp="{_tp([x["topic"]])}"><div class="wh-sm">'
        + ('<i class="ai-new"></i>' if x["date"] >= ns else "")
        + f'{esc(_md(x["date"]))}・{esc(x.get("channel") or "其他")}・{esc(x["topic"])}</div>'
        f'<p class="wh-sx">{esc(x["zh"])}</p>'
        + (('<span class="ai-s">' + "・".join(
            f'<a href="{esc(l.get("url", ""))}" rel="noopener" target="_blank">{esc(l.get("source") or "來源")}</a>'
            for l in (x.get("links") or [])[:2] if l.get("url")) + '</span>') if x.get("links") else "")
        + '</div>' for x in (w.get("items") or [])[:12])
    left = ('<div class="wh-c wh-say"><div class="wh-k">川普說了什麼<span class="wh-cnt"></span></div>'
            + sts + f'<p class="wh-empty"{"" if not sts else " hidden"}>近 {win} 天沒有<span class="wh-et"></span>相關發言。</p>'
            '<p class="wh-note">AI 依新聞報導與白宮公告整理，只收跟市場有關的</p></div>')
    pol = "".join(_policy(p, ns) for p in w.get("policies") or [])
    ck = _md(w.get("checked", ""))
    right = ('<div class="wh-c wh-pol"><div class="wh-k">政策進度<span class="wh-cnt"></span></div>'
             + pol + f'<p class="wh-empty"{"" if not pol else " hidden"}>目前沒有追蹤中的<span class="wh-et"></span>政策。</p>'
             + (f'<p class="wh-note">本站人工維護・最後確認 {esc(ck)}</p>' if ck else "") + '</div>')
    out.append(f'<div class="wh-two">{left}{right}</div>')
    # ④ 政策不確定性指數
    e = w.get("epu")
    if e:
        lv = {"偏高": "hi", "偏低": "lo"}.get(e["level"], "mid")
        out.append('<div class="wh-c wh-ix"><div class="wh-k">政策不確定性指數</div><div class="wh-ixb">'
                   f'<div><b class="wh-ixv wh-{lv}">{e["value"]:,}</b>'
                   f'<span>30 日均・{esc(e["level"])}'
                   + (f'（近一年第 {e["pct"]} 百分位）' if e.get("pct") is not None else "") + '</span></div>'
                   + _spark(e.get("spark") or []) + '</div>'
                   f'<p class="wh-note">Baker、Bloom、Davis 以新聞用詞計算（FRED 每日，資料至 {esc(_md(e["date"]))}）・近 6 個月</p></div>')
    return '<div class="wh-wrap">' + "".join(out) + '</div>'
