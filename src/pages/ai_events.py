"""
首頁「AI 大事」小卡與視窗內容（2026-10-29；資料：src/analysis/ai_events.py）。

視窗內：Anthropic IPO 進度（進行中才顯示）→ 十二家公司小卡（日期・類型，近 3 天有新事件加小圓點）
→ 選中公司的事件整理與對市場的影響（一次一家）→ 依時間看全部（預設收合，可篩類型）→ 跟利率的關係。
"""
from __future__ import annotations

import datetime as dt

from ..site import esc

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


def ai_tile(a: dict | None) -> tuple[str, str]:
    """回傳 (小卡, 視窗內容)。沒有資料時兩個都是空字串。"""
    if not a or not (a.get("events") or (a.get("ipo") or {}).get("active")):
        return "", ""
    evs = a.get("events") or []
    # 2026-10-29 六宮格：摘要固定一行，只寫公司與類型
    latest = f'{evs[0]["co"]}・{evs[0]["type"]}' if evs else "Anthropic IPO 進行中"
    tile = ('<button type="button" class="duo-card" data-t="ai" data-title="AI 大事" aria-haspopup="dialog">'
            f'<span class="duo-k">近 {a.get("window_days", 14)} 天 {len(evs)} 則</span><span class="duo-t">AI 大事</span>'
            f'<span class="duo-map">{AI_ART}</span>'
            f'<span class="duo-sum">最新：{esc(latest)}</span></button>')
    return tile, ai_panel(a)


def ai_panel(a: dict) -> str:
    evs = a.get("events") or []
    out = []
    ipo = a.get("ipo") or {}
    if ipo.get("active"):
        steps = "".join(f'<li class="{"done" if s.get("date") else ""}"><b>{esc(s["label"])}</b>'
                        f'<span>{esc(_md(s["date"])) or "—"}</span></li>' for s in ipo.get("steps") or [])
        out.append(f'<div class="ai-hl-c"><div class="ai-hl-k">進行中・{esc(ipo.get("name", ""))} IPO</div>'
                   f'<ol class="ai-ipo">{steps}</ol><div class="ai-hl-n">從 SEC 申報自動更新；掛牌後這一格自動消失</div></div>')
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
        lis = "".join(f'<li><span class="ai-p-d">{esc(_md(e["date"]))}</span><span class="ai-p-t">{esc(e["type"])}</span>'
                      f'<span class="ai-p-x">{esc(e["zh"])}{_srcs(e)}</span></li>' for e in mine) \
            or '<li class="none">近 14 天沒有重大事件</li>'
        imp = (a.get("impact") or {}).get(c, "")
        panes.append(f'<div class="ai-pane" data-co="{esc(c)}"{"" if on else " hidden"}>'
                     f'<div class="ai-pane-h">{esc(c)}<span>近 {a.get("window_days", 14)} 天 {len(mine)} 則</span></div>'
                     f'<div class="ai-pane-k">事件整理</div><ul class="ai-p-l">{lis}</ul>'
                     + (f'<div class="ai-pane-k">對市場的影響<em>AI 依上列事件整理</em></div><p class="ai-p-imp">{esc(imp)}</p>'
                        if imp else "") + '</div>')
    out.append('<div class="ai-sec-h"><h3>各公司近況</h3><span><i class="ai-new"></i> 近 3 天有新事件</span></div>'
               f'<div class="ai-tiles">{"".join(tiles)}</div><div class="ai-panes">{"".join(panes)}</div>')
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
        out.append(f'<details class="ai-all"><summary><span class="ai-sum-t">依時間看全部（近 {a.get("window_days", 14)} 天 '
                   f'{len(evs)} 則）</span><label class="ai-sel"><select aria-label="事件類型">'
                   + "".join(f'<option>{t}</option>' for t in types) + '</select></label></summary>'
                   f'<div class="ai-tl">{tl}</div></details>')
    out.append(f'<div class="ai-why"><b>跟利率的關係</b><p>{esc(WHY)}<a href="/longend/">看長端與債務 →</a></p></div>'
               '<p class="ai-note">事件由 AI 依新聞標題整理成一句中文，每則附原文連結；只收財報、資本支出、發債、'
               '融資／IPO、算力合約五類。</p>')
    return '<div class="ai-wrap">' + "".join(out) + '</div>'
