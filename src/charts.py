"""
圖表元件。

為什麼長條圖用 HTML 而不是 SVG
------------------------------
SVG 若設 width="100%" 搭配固定 height，在窄螢幕上內容會等比縮小並在上下留出
大片空白（先前手機版「圖表比例怪異」就是這個原因），而且文字會跟著縮到讀不清。

改用 HTML/CSS 的長條之後：
  * 文字永遠是原生字級，不受容器寬度影響
  * 版面由 CSS grid 控制，手機與桌面各自合理
  * 仍然可以 hover 顯示提示

走勢縮圖（sparkline）維持 SVG——它本來就沒有文字，等比縮放沒有問題。
"""

from __future__ import annotations

import html
from typing import Sequence


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


# ---------------------------------------------------------------------------
# 走勢縮圖（單一序列，無文字，維持 SVG）
# ---------------------------------------------------------------------------
def sparkline(values: Sequence[float], width: int = 120, height: int = 34,
              color: str = "var(--series-1)", zero_line: bool = False) -> str:
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    if zero_line:
        lo, hi = min(lo, 0), max(hi, 0)
    rng = (hi - lo) or 1
    pad = 3
    w, h = width - pad * 2, height - pad * 2

    pts = []
    for i, v in enumerate(vals):
        x = pad + (i / (len(vals) - 1)) * w
        y = pad + (1 - (v - lo) / rng) * h
        pts.append(f"{x:.1f},{y:.1f}")

    zero_svg = ""
    if zero_line and lo < 0 < hi:
        zy = pad + (1 - (0 - lo) / rng) * h
        zero_svg = (f'<line x1="{pad}" y1="{zy:.1f}" x2="{pad+w}" y2="{zy:.1f}" '
                    f'stroke="var(--baseline)" stroke-width="1" stroke-dasharray="2 2"/>')

    last_x, last_y = pts[-1].split(",")
    return (
        f'<svg class="spark" viewBox="0 0 {width} {height}" preserveAspectRatio="none" '
        f'role="img" aria-hidden="true">{zero_svg}'
        f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" '
        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        f'vector-effect="non-scaling-stroke"/>'
        f'<circle cx="{last_x}" cy="{last_y}" r="2.5" fill="{color}"/></svg>'
    )


# ---------------------------------------------------------------------------
# 發散長條（行業增減）— 純 HTML
# ---------------------------------------------------------------------------
def diverging_bars(items: Sequence[dict], fmt=None) -> str:
    """
    items: [{label, value, note?, muted?, notable?, tip?}]

    版面是三欄：行業名稱｜長條（零軸置中）｜數值
    長條寬度以百分比表示，所以完全隨容器伸縮，不會有比例問題。
    """
    rows = [i for i in items if i.get("value") is not None]
    if not rows:
        return '<div class="empty">無資料</div>'

    fmt = fmt or (lambda v: f"{v:+,.0f}")
    maxabs = max(abs(r["value"]) for r in rows) or 1

    out = ['<div class="dbars">']
    for r in rows:
        v = r["value"]
        pos = v >= 0
        pctw = abs(v) / maxabs * 50          # 最多佔半邊
        kind = "muted" if r.get("muted") else ("pos" if pos else "neg")
        style = (f"left:50%;width:{pctw:.2f}%" if pos
                 else f"right:50%;width:{pctw:.2f}%")
        tip = r.get("tip") or f'{r["label"]}｜{fmt(v)}'
        # 「值得注意」要把理由一起寫出來。只掛一個標籤、理由藏在 hover 提示裡，
        # 在手機上等於沒有理由——那裡沒有 hover，點下去不會有任何反應。
        tag = (f'<span class="dtag">值得注意<b>{_esc(r["notable_why"])}</b></span>'
               if r.get("notable") and r.get("notable_why")
               else ('<span class="dtag">值得注意</span>' if r.get("notable") else ""))
        note = f'<span class="dnote">{_esc(r["note"])}</span>' if r.get("note") else ""

        out.append(
            f'<div class="drow" data-tip="{_esc(tip)}">'
            f'<div class="dlabel">{_esc(r["label"])}{tag}{note}</div>'
            f'<div class="dtrack"><span class="dzero"></span>'
            f'<span class="dfill {kind}" style="{style}"></span></div>'
            f'<div class="dval {"pos" if pos else "neg"}">{_esc(fmt(v))}</div>'
            f"</div>"
        )
    out.append("</div>")
    return "".join(out)


# ---------------------------------------------------------------------------
# 修正對照 — 表格式，手機上比長條圖好讀太多
# ---------------------------------------------------------------------------
def revision_table(rows: Sequence[dict], fmt=None) -> str:
    """rows: [{label, original, current}]（單位：千人）"""
    rows = [r for r in rows if r.get("current") is not None]
    if not rows:
        return '<div class="empty">尚無修正資料</div>'

    fmt = fmt or (lambda v: f"{v:+,.0f}")
    body = []
    for r in rows:
        o, c = r.get("original"), r["current"]
        net = None if o is None else c - o
        if net is None:
            net_cell = '<td class="muted-cell">—</td>'
        elif abs(net) < 0.5:
            net_cell = '<td class="muted-cell">未修正</td>'
        else:
            cls = "neg" if net < 0 else "pos"
            strong = ' style="font-weight:700"' if abs(net) >= 25 else ""
            net_cell = f'<td class="{cls}"{strong}>{_esc(fmt(net))}</td>'
        body.append(
            f'<tr><td>{_esc(r["label"])}</td>'
            f'<td class="muted-cell">{_esc(fmt(o)) if o is not None else "—"}</td>'
            f"<td>{_esc(fmt(c))}</td>{net_cell}</tr>"
        )

    return (
        '<table class="revtab"><thead><tr>'
        "<th>月份</th><th>初次公布</th><th>目前</th><th>修正</th>"
        "</tr></thead><tbody>" + "".join(body) + "</tbody></table>"
    )


# ---------------------------------------------------------------------------
# 時間序列折線圖
# ---------------------------------------------------------------------------
def line_chart(points: Sequence[dict], unit: str = "", height: int = 150,
               color: str = "var(--series-1)", zero: bool = False,
               marks: Sequence[dict] | None = None, digits: int = 2) -> str:
    """
    折線圖。

    刻度與標籤刻意放在 SVG **外面**用 HTML 呈現——
    SVG 內的文字會隨容器等比縮小，在手機上會小到讀不清。
    SVG 只畫線，所以可以安心用 width:100% + height:auto 等比縮放。

    marks: [{index, label}] 可在特定位置標註（例如「近一個月起點」）
    """
    pts = [p for p in points if p.get("value") is not None]
    if len(pts) < 2:
        return '<div class="empty">資料不足</div>'

    vals = [p["value"] for p in pts]
    lo, hi = min(vals), max(vals)
    # 參考線畫在「資料的實際最高／最低值」，不能用加了留白之後的座標軸
    # 上下界——否則標示的最大值會跟圖上看得到的線對不上，讀起來自相矛盾。
    data_lo, data_hi = lo, hi
    if zero:
        lo, hi = min(lo, 0), max(hi, 0)
    pad = (hi - lo) * 0.12 or 1
    lo, hi = lo - pad, hi + pad
    rng = hi - lo

    def y_pct(v: float) -> float:
        """值 → 距頂端的百分比位置（HTML 疊層與 SVG 共用同一套換算）。"""
        return (1 - (v - lo) / rng) * 100

    W, H = 600, height
    coords = []
    for i, p in enumerate(pts):
        x = i / (len(pts) - 1) * W
        y = (1 - (p["value"] - lo) / rng) * H
        coords.append((x, y))

    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    area = f"0,{H} {poly} {W},{H}"
    lx, ly = coords[-1]

    # 有意義的水平參考線：資料最高值與最低值（虛線），零軸（實線）。
    ref_svg = ""
    for v in (data_hi, data_lo):
        ry = (1 - (v - lo) / rng) * H
        ref_svg += (f'<line x1="0" y1="{ry:.1f}" x2="{W}" y2="{ry:.1f}" '
                    f'stroke="var(--grid)" stroke-width="1" stroke-dasharray="4 4" '
                    f'vector-effect="non-scaling-stroke"/>')
    if zero and lo < 0 < hi:
        zy = (1 - (0 - lo) / rng) * H
        ref_svg += (f'<line x1="0" y1="{zy:.1f}" x2="{W}" y2="{zy:.1f}" '
                    f'stroke="var(--baseline)" stroke-width="1" '
                    f'vector-effect="non-scaling-stroke"/>')

    mark_svg = ""
    mark_labels = ""
    for m in (marks or []):
        i = max(0, min(len(coords) - 1, m.get("index", 0)))
        mx = coords[i][0]
        mark_svg += (f'<line x1="{mx:.1f}" y1="0" x2="{mx:.1f}" y2="{H}" '
                     f'stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 3" '
                     f'vector-effect="non-scaling-stroke"/>')
        # 標註文字用百分比定位，跟虛線落在同一個 x 位置
        xp = min(88.0, max(12.0, mx / W * 100))
        mark_labels += (f'<span class="lmark" style="left:{xp:.1f}%">'
                        f'{_esc(m["label"])}</span>')

    svg = (
        f'<svg class="lchart" viewBox="0 0 {W} {H}" preserveAspectRatio="none" '
        f'style="height:{H}px" role="img" aria-label="時間序列走勢">'
        f'<polygon points="{area}" fill="{color}" opacity="0.09"/>'
        f'{ref_svg}{mark_svg}'
        f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round" '
        f'vector-effect="non-scaling-stroke"/>'
        f"</svg>"
    )

    # 最新值的圓點改用 HTML 疊層畫，不放在 SVG 裡。
    # SVG 用 preserveAspectRatio="none" 拉伸，圓形會被壓成橢圓；
    # 而且圓心正好落在 x=W（右邊界），有一半會被裁掉。
    end_dot = (f'<span class="ldot" style="left:{lx / W * 100:.2f}%;'
               f'top:{ly / H * 100:.2f}%;background:{color}"></span>')

    # 高低參考線的數值標籤：貼在各自的線旁邊（高值標在線上方、低值在線下方），
    # 讀者不必再自己對照「區間」文字猜線的位置。
    # 小數位數與最新值標籤共用 digits——同一張圖不能一個標 126.0、一個標 125.95。
    glabs = (
        f'<span class="glab" style="top:calc({y_pct(data_hi):.1f}% - 14px)">'
        f'{data_hi:,.{digits}f}{_esc(unit)}</span>'
        f'<span class="glab" style="top:calc({y_pct(data_lo):.1f}% + 4px)">'
        f'{data_lo:,.{digits}f}{_esc(unit)}</span>'
    )

    return (
        f'<div class="lwrap">'
        f'<div class="lplot">{svg}{glabs}{mark_labels}{end_dot}</div>'
        f'<div class="lxaxis"><span>{_esc(pts[0]["date"])}</span>'
        f'<span><b>{pts[-1]["value"]:,.{digits}f}{_esc(unit)}</b>　{_esc(pts[-1]["date"])}</span>'
        f"</div></div>"
    )


# ---------------------------------------------------------------------------
# 近 N 期數值列（放在 KPI 卡下方，補上走勢圖看不出的實際數字）
# ---------------------------------------------------------------------------
def mini_series(points: Sequence[dict], fmt=None, n: int = 5,
                daily: bool = False, unit: str = "") -> str:
    """
    走勢圖只看得出形狀，這一列補上實際數值與期別。

    n 預設 5 不是 6：KPI 卡在桌機四欄版面下內容寬只有 218px，
    六格會超出約 40px。橫向捲會把最左邊那格切掉半個字——
    「-15.6」被切成「5.6」是**顯示成另一個數字**，比少一期嚴重得多。

    daily=True 用於日頻序列（如 5y5y 通膨預期）：同一個月裡取到好幾個
    觀測值時，只標月份會出現連續三格都寫「7月」，改標月/日。
    """
    pts = [p for p in points if p.get("value") is not None][-n:]
    if len(pts) < 2:
        return ""
    fmt = fmt or (lambda v: f"{v:,.1f}")

    def _dlabel(i: int, date: str) -> str:
        # 「26-02」會被誤讀成 26 日；改成「2月」，第一格與跨年時帶年份。
        y, m = date[2:4], int(date[5:7])
        if daily:
            d = int(date[8:10]) if len(date) >= 10 else 1
            return f"{y}年{m}/{d}" if i == 0 else f"{m}/{d}"
        if i == 0 or m == 1:
            return f"{y}年{m}月"
        return f"{m}月"

    cells = "".join(
        f'<div class="mcell{" last" if i == len(pts)-1 else ""}">'
        f'<div class="mval">{_esc(fmt(p["value"]))}</div>'
        f'<div class="mdate">{_esc(_dlabel(i, p["date"]))}</div></div>'
        for i, p in enumerate(pts)
    )
    # 單位在每一格重複（「-15.6 萬人」×6）會讓這一列比卡片還寬，
    # 格子互相疊字、最新的那一格還被推到看不見的地方。
    # 單位抽出來只寫一次，六格就塞得下了。
    head = (f'<div class="munit">單位：{_esc(unit)}</div>' if unit else "")
    return f'<div class="mwrap">{head}<div class="mseries">{cells}</div></div>'


# ---------------------------------------------------------------------------
# 狀態條（紅綠燈的歷史軌跡）
# ---------------------------------------------------------------------------
def status_strip(statuses: Sequence[dict]) -> str:
    """
    statuses: [{date, status}]，status 為 good/warning/critical/unknown

    只看當期狀態無法分辨「連續三個月惡化」與「這個月剛轉黃」，
    這條軌跡就是補這個資訊。
    """
    if not statuses:
        return ""
    cells = "".join(
        f'<span class="sq {s["status"]}" data-tip="{_esc(s["date"])}｜'
        f'{_esc(s.get("label", ""))}"></span>' for s in statuses
    )
    return (f'<div class="sstrip">{cells}</div>'
            f'<div class="sstrip-note">近 {len(statuses)} 期</div>')
