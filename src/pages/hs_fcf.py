"""
科技巨頭「FCF＋發債」每季小圖（2026-11）。

長端頁的五家加總、每家近 8 季、首頁 AI 大事視窗共用同一支：
長條＝自由現金流（營運現金流 − 資本支出，正灰負橘），折線＋點＝單季發債，同一個軸（億美元）。
點長條（桌機滑過）跳出小浮窗：營運現金流、資本支出、FCF、資本支出佔現金流、單季發債。
浮窗由 site.py 的 .fcf 小段 JS 處理——不走全站 #tip，因為 #tip 在觸控裝置上是隱藏的。
"""
from __future__ import annotations

import math

from ..site import esc


def _n(v: float, sign: bool = False) -> str:
    s = f"{v:+,.0f}" if sign else f"{v:,.0f}"
    return s.replace("-", "−")


def _step(span: float) -> float:
    for s in (50, 100, 200, 250, 500, 1000, 2000, 5000):
        if span / s <= 6:
            return s
    return 10 ** math.ceil(math.log10(span / 6))


def fcf_rows(rows: list) -> list:
    """[{label, capex, ocf, debt}]（億美元）→ 補上 fcf、ratio。capex 或 ocf 缺的季不畫。"""
    out = []
    for r in rows:
        if r.get("capex") is None or not r.get("ocf"):
            continue
        out.append({**r, "debt": r.get("debt") or 0.0, "fcf": r["ocf"] - r["capex"],
                    "ratio": r["capex"] / r["ocf"] * 100})
    return out


def fcf_chart(rows: list, aria: str, height: int = 210) -> str:
    """
    HTML 長條＋SVG 折線（preserveAspectRatio=none、線寬不隨縮放），文字都是 HTML——
    手機、桌機、視窗裡字級一致，不會像整張 SVG 一樣跟著寬度放大縮小。
    height 是桌機高度；手機用 CSS 改成 .78 倍。
    """
    rows = fcf_rows(rows)
    if len(rows) < 2:
        return ""
    vals = [v for r in rows for v in (r["fcf"], r["debt"])]
    lo, hi = min(0.0, min(vals)), max(0.0, max(vals))
    pad = (hi - lo) * 0.08 or 1
    lo, hi = lo - (pad if lo < 0 else 0), hi + pad
    pc = lambda v: (v - lo) / (hi - lo) * 100   # noqa: E731  距底部 %
    z = pc(0)
    n = len(rows)
    xs = [(i + 0.5) / n * 100 for i in range(n)]
    st = _step(hi - lo)
    g = math.ceil(lo / st) * st
    grid = []
    while g <= hi:
        grid.append(f'<i class="{"fz" if g == 0 else "fg"}" style="bottom:{pc(g):.2f}%"><em>{_n(g)}</em></i>')
        g += st
    cols, dots = [], []
    for i, r in enumerate(rows):
        h = abs(pc(r["fcf"]) - z)
        bot = z if r["fcf"] >= 0 else z - h
        lab = ""
        if i == n - 1:
            lab = (f'<em class="fv{" n" if r["fcf"] < 0 else ""}" style="{"top" if r["fcf"] < 0 else "bottom"}:'
                   f'calc(100% + 2px)">{_n(r["fcf"], True)}</em>')
        cols.append(
            f'<button type="button" class="fcf-hit{" last" if i == n - 1 else ""}" aria-label="{esc(r["label"])} 明細" '
            f'data-q="{esc(r["label"])}" data-o="{_n(r["ocf"])}" data-c="{_n(r["capex"])}" '
            f'data-f="{_n(r["fcf"], True)}" data-fn="{1 if r["fcf"] < 0 else 0}" data-r="{r["ratio"]:.0f}%" '
            f'data-rn="{1 if r["ratio"] > 100 else 0}" data-d="{_n(r["debt"]) if r["debt"] else "—"}">'
            f'<span class="fcf-b {"fn" if r["fcf"] < 0 else "fp"}" style="bottom:{bot:.2f}%;height:{max(h, 0.6):.2f}%">{lab}</span>'
            f'</button>')
        dots.append(f'<span class="fcf-d" style="left:{xs[i]:.2f}%;bottom:{pc(r["debt"]):.2f}%"></span>')
    line = ('<svg class="fcf-l" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">'
            '<polyline points="' + " ".join(f"{xs[i]:.2f},{100 - pc(r['debt']):.2f}" for i, r in enumerate(rows))
            + '" vector-effect="non-scaling-stroke"/></svg>')
    xl = "".join(f'<span>{esc(r["label"])}</span>' for r in rows)
    return (f'<div class="fcf" role="group" aria-label="{esc(aria)}" style="--fh:{height}px">'
            f'<div class="fcf-plot">{"".join(grid)}<div class="fcf-cols">{"".join(cols)}</div>{line}{"".join(dots)}</div>'
            f'<div class="fcf-x">{xl}</div><div class="fcf-pop" role="status" aria-live="polite"></div></div>')


LEGEND = ('<div class="fcf-lg"><span><i class="fp"></i>FCF 為正</span><span><i class="fn"></i>FCF 為負</span>'
          '<span><i class="fd"></i>單季發債</span></div>')


def latest(rows: list) -> dict | None:
    rows = fcf_rows(rows)
    return rows[-1] if rows else None
