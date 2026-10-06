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
def sparkline(values: Sequence[float], width: int = 120, height: int = 64,
              color: str = "var(--series-1)", zero_line: bool = False,
              mark_last: int = 5) -> str:
    """
    KPI 卡的小走勢圖。

    2026-10 改版（使用者：「近 5 期的圖表太扁平、趨勢不明顯」）：
      · 高度 34 → 64px，y 軸只縮放到顯示區間的高低點（不含零軸，除非指定）
      · mark_last：把最後 N 期（下方「近 5 期」數值列對應的那幾期）
        墊一塊淡底，一眼對得上下面的數字
      · 終點圓點改用零長度線段＋圓頭：SVG 用 preserveAspectRatio="none"
        拉伸時，circle 會被壓成橢圓，線段的圓頭不會
    """
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    if zero_line:
        lo, hi = min(lo, 0), max(hi, 0)
    rng = (hi - lo) or 1
    pad = 4
    w, h = width - pad * 2, height - pad * 2

    def X(i):
        return pad + (i / (len(vals) - 1)) * w

    pts = []
    for i, v in enumerate(vals):
        y = pad + (1 - (v - lo) / rng) * h
        pts.append((X(i), y))

    zero_svg = ""
    if zero_line and lo < 0 < hi:
        zy = pad + (1 - (0 - lo) / rng) * h
        zero_svg = (f'<line x1="{pad}" y1="{zy:.1f}" x2="{pad+w}" y2="{zy:.1f}" '
                    f'stroke="var(--baseline)" stroke-width="1" stroke-dasharray="2 2" '
                    f'vector-effect="non-scaling-stroke"/>')
    band = ""
    if mark_last and len(vals) > mark_last:
        bx = X(len(vals) - mark_last) - (w / (len(vals) - 1)) / 2
        band = (f'<rect x="{bx:.1f}" y="0" width="{width - bx:.1f}" height="{height}" '
                f'fill="var(--surface-2)"/>')

    lx, ly = pts[-1]
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    return (
        f'<svg class="spark" viewBox="0 0 {width} {height}" preserveAspectRatio="none" '
        f'role="img" aria-hidden="true">{band}{zero_svg}'
        f'<polyline points="{poly}" fill="none" stroke="{color}" '
        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        f'vector-effect="non-scaling-stroke"/>'
        f'<line x1="{lx:.1f}" y1="{ly:.1f}" x2="{lx:.1f}" y2="{ly:.1f}" stroke="{color}" '
        f'stroke-width="6" stroke-linecap="round" vector-effect="non-scaling-stroke"/></svg>'
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
    footnotes: list[tuple[str, str]] = []
    for r in rows:
        v = r["value"]
        pos = v >= 0
        pctw = abs(v) / maxabs * 50          # 最多佔半邊
        kind = "muted" if r.get("muted") else ("pos" if pos else "neg")
        style = (f"left:50%;width:{pctw:.2f}%" if pos
                 else f"right:50%;width:{pctw:.2f}%")
        tip = r.get("tip") or f'{r["label"]}｜{fmt(v)}'
        # 異常的完整說明不放在列上——長條旁塞一整句會把圖擠亂。
        # 列上只留 ▲ 小標記，完整理由集中寫在圖表下方的註腳區
        #（一樣是常駐文字，手機沒有 hover 也看得到）。
        tag = '<span class="dtag" title="異常">▲</span>' if r.get("notable") else ""
        if r.get("notable"):
            footnotes.append((r["label"], r.get("notable_why") or ""))
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
    if footnotes:
        lines = "".join(
            f'<div class="dfoot-line"><span class="dfoot-mark">▲</span>'
            f'<b>{_esc(label)}</b>{("：" + _esc(why)) if why else ""}</div>'
            for label, why in footnotes)
        out.append(f'<div class="dfoot">{lines}</div>')
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
        # 下緣右側寫成一個詞組「最新 值（日期）」：先前是「粗體值　日期」
        # 兩個 token 並排，手機上跟左側的起日看起來像一行擠了三個數字。
        f'<div class="lxaxis"><span>{_esc(pts[0]["date"])}</span>'
        f'<span class="nb">最新 <b>{pts[-1]["value"]:,.{digits}f}{_esc(unit)}</b>'
        f'（{_esc(pts[-1]["date"])}）</span>'
        f"</div></div>"
    )


def stacked_shares(layers: Sequence[dict], shade: Sequence[tuple] = (),
                   height: int = 170) -> str:
    """
    百分比堆疊面積圖（各層加總≈100%）。

    layers：[{label, color, points:[{date, value}]}]，由下往上疊；
    只取所有層都有值的日期。shade：[(起 YYYY-MM, 迄 YYYY-MM)] 畫衰退陰影。
    跟 line_chart 一樣，文字全部放在 SVG 外（手機上不會縮到讀不清）。
    """
    maps = [{str(p["date"])[:7]: p["value"] for p in L["points"]
             if p.get("value") is not None} for L in layers]
    dates = sorted(set.intersection(*(set(m) for m in maps))) if maps else []
    if len(dates) < 2:
        return '<div class="empty">資料不足</div>'
    W, H, n = 600, height, len(dates)

    def x(i):
        return i / (n - 1) * W
    tot = [sum(m[d] for m in maps) or 100 for d in dates]
    cum = [0.0] * n
    polys = []
    for L, m in zip(layers, maps):
        lower = cum[:]
        cum = [c + m[d] / t * 100 for c, d, t in zip(cum, dates, tot)]
        top = " ".join(f"{x(i):.1f},{(1 - cum[i] / 100) * H:.1f}" for i in range(n))
        bot = " ".join(f"{x(i):.1f},{(1 - lower[i] / 100) * H:.1f}"
                       for i in reversed(range(n)))
        polys.append(f'<polygon points="{top} {bot}" fill="{L["color"]}" '
                     f'opacity="0.78"/>')
    sh = ""
    for a, b in shade:
        ia = next((i for i, d in enumerate(dates) if d >= a), None)
        ib = next((i for i, d in reversed(list(enumerate(dates))) if d <= b), None)
        if ia is None or ib is None or ib < ia:
            continue
        sh += (f'<rect x="{x(ia):.1f}" y="0" width="{max(x(ib) - x(ia), 3):.1f}" '
               f'height="{H}" fill="var(--text-primary)" opacity="0.12"/>')
    svg = (f'<svg class="lchart" viewBox="0 0 {W} {H}" preserveAspectRatio="none" '
           f'style="height:{H}px" role="img" aria-label="失業原因比重走勢">'
           f'{"".join(polys)}{sh}</svg>')
    last = {L["label"]: m[dates[-1]] for L, m in zip(layers, maps)}
    legend = "".join(
        f'<span><i style="background:{L["color"]}"></i>{_esc(L["label"])} '
        f'<b>{last[L["label"]]:.1f}%</b></span>' for L in reversed(list(layers)))
    return (f'<div class="lwrap"><div class="lplot">{svg}</div>'
            f'<div class="lxaxis"><span>{_esc(dates[0])}</span>'
            f'<span>{_esc(dates[-1])}</span></div>'
            f'<div class="dlegend">{legend}</div></div>')


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


# ===========================================================================
# 2026-10 改版元件：關鍵數字近 5 期、精簡走勢圖、分項瀑布、數線、傳導鏈
#
# 共同原則（使用者：「一堆折線圖 UIUX 很醜」）：
#   · 走勢圖一律近 24 個月，多條同單位的線疊在同一張（一個 y 軸，不用雙軸）
#   · 線下不塗面積（面積會暗示從零起算）
#   · 文字全部是 HTML，不放在會被等比縮放的 SVG 裡
#   · 每張圖都有 hover／觸碰提示（data-tip，沿用全站 #tip）
# ===========================================================================
def _mkey(date: str) -> float:
    """日期 → 連續的月份座標（日頻資料帶小數，月中＝.5）。"""
    y, m = int(date[:4]), int(date[5:7])
    d = int(date[8:10]) if len(date) >= 10 else 1
    return y * 12 + (m - 1) + (d - 1) / 31


def _dlabel5(i: int, date: str, daily: bool = False) -> str:
    y, m = date[2:4], int(date[5:7])
    if daily:
        d = int(date[8:10]) if len(date) >= 10 else 1
        return f"{m}/{d}"
    if i == 0 or m == 1:
        return f"{y}年{m}月"
    return f"{m}月"


def _nice_step(span: float, target: int = 3) -> float:
    for s in (0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100):
        if span / s <= target:
            return s
    return 200.0


def last_months(rows: Sequence[dict], months: int = 24) -> list[dict]:
    """取最新一筆往回 N 個月（含）的資料——全站走勢圖統一的時間窗。"""
    pts = [p for p in rows if p.get("value") is not None]
    if not pts:
        return []
    end = _mkey(pts[-1]["date"])
    return [p for p in pts if _mkey(p["date"]) > end - months]


def kpi_history(points: Sequence[dict], kind: str = "change", fmt=None,
                unit: str = "", ref: float | None = None, ref_label: str = "",
                band: tuple | None = None, band_label: str = "",
                daily: bool = False, n: int = 5, en: str = "", head: str = "",
                short_dates: bool = False) -> str:
    """
    關鍵數字卡的「近 5 期與比較基準」。

    使用者定的規則：**變動類用柱、水準類用點，都只畫 5 期**。
      change：每期是一個「變了多少」（月增、新增人數）→ 從零軸長出的柱
      level ：每期是一個「在哪裡」（失業率、年增率）→ 點＋細連線，
              y 軸只縮到資料與基準的範圍（從零起算會把變化壓扁）
    比較基準：ref＝一條虛線（目標步速、2% 目標），band＝一塊淡底（區間）。
    最新一期用主色，其餘灰——眼睛先落在現在。
    """
    pts = [p for p in points if p.get("value") is not None][-n:]
    if len(pts) < 2:
        return ""
    _f = fmt or (lambda v: f"{v:,.1f}")

    def fmt(v):
        # 「-0.0」「+0.0」一律寫成 0.0——四捨五入後的零不該帶正負號
        t = _f(v)
        return t[1:] if t[:1] in "+-" and not any(c in "123456789" for c in t) else t
    vals = [p["value"] for p in pts]
    dom = list(vals)
    if ref is not None:
        dom.append(ref)
    if band:
        dom += [band[0], band[1]]
    if kind == "change":
        dom.append(0.0)
    lo, hi = min(dom), max(dom)
    span = (hi - lo) or abs(hi) or 1
    pad = span * (0.08 if kind == "change" else 0.22)
    if kind == "change":
        lo = lo - (pad if lo < 0 else 0)
        hi = hi + (pad if hi > 0 else 0)
    else:
        lo, hi = lo - pad, hi + pad
    rng = (hi - lo) or 1

    def Y(v):  # 距頂端百分比
        return (1 - (v - lo) / rng) * 100

    k = len(pts)
    layers = []
    if band:
        a, b = Y(max(band)), Y(min(band))
        layers.append(f'<span class="kh-band" style="top:{a:.1f}%;height:{b - a:.1f}%"></span>')
    if kind == "change" and lo < 0 < hi:
        layers.append(f'<span class="kh-zero" style="top:{Y(0):.1f}%"></span>')
    if ref is not None:
        layers.append(f'<span class="kh-ref" style="top:{Y(ref):.1f}%"></span>')
    cols = []
    for i, p in enumerate(pts):
        v = p["value"]
        last = " last" if i == k - 1 else ""
        tip = f'{_dlabel5(0, p["date"], daily)}｜{fmt(v)}{unit}'
        if kind == "change":
            y0, y1 = sorted((Y(0) if lo <= 0 <= hi else 100.0, Y(v)))
            mark = (f'<span class="kh-bar{last}{" down" if v < 0 else ""}" '
                    f'style="top:{y0:.1f}%;height:{max(y1 - y0, 1.2):.1f}%"></span>')
        else:
            mark = f'<span class="kh-dot{last}" style="top:{Y(v):.1f}%"></span>'
        cols.append(f'<div class="kh-col" data-tip="{_esc(tip)}">{mark}</div>')
    line = ""
    if kind == "level":
        poly = " ".join(f"{(i + .5) / k * 100:.2f},{Y(p['value']):.2f}"
                        for i, p in enumerate(pts))
        line = (f'<svg class="kh-line" viewBox="0 0 100 100" preserveAspectRatio="none" '
                f'aria-hidden="true"><polyline points="{poly}" fill="none" '
                f'stroke="var(--baseline)" stroke-width="1.5" '
                f'vector-effect="non-scaling-stroke"/></svg>')
    vals_row = "".join(
        f'<span class="{"last" if i == k - 1 else ""}">{_esc(fmt(p["value"]))}</span>'
        for i, p in enumerate(pts))
    def _dl(i, date):
        if short_dates:          # 「24/9」：8 格以上時「24年9月」會互相擠在一起
            return f"{date[2:4]}/{int(date[5:7])}"
        return _dlabel5(i, date, daily)
    dates_row = "".join(f'<span>{_esc(_dl(i, p["date"]))}</span>'
                        for i, p in enumerate(pts))
    leg = []
    if ref is not None and ref_label:
        leg.append(f'<span><i class="lg-ref"></i>{_esc(ref_label)}</span>')
    if band and band_label:
        leg.append(f'<span><i class="lg-band"></i>{_esc(band_label)}</span>')
    unit_html = f'<span class="kh-unit">單位：{_esc(unit.strip())}</span>' if unit.strip() else ""
    kind_zh = head or ("每期變動（柱）" if kind == "change" else "每期水準（點）")
    return (f'<div class="kh kh-{kind}" style="--n:{k}" role="img" '
            f'aria-label="{_esc(en or "近 5 期")}">'
            f'<div class="kh-top"><span>{"" if head else f"近 {k} 期　"}{kind_zh}</span>{unit_html}</div>'
            f'<div class="kh-vals">{vals_row}</div>'
            f'<div class="kh-plot">{"".join(layers)}{line}{"".join(cols)}</div>'
            f'<div class="kh-dates">{dates_row}</div>'
            + (f'<div class="kh-leg">{"".join(leg)}</div>' if leg else "")
            + '</div>')


def compact_lines(series: Sequence[dict], unit: str = "%", height: int = 150,
                  refs: Sequence[dict] = (), digits: int = 1,
                  fill_between: dict | None = None, marks: Sequence[dict] = (),
                  zero: bool = False, months: int = 24, aria: str = "走勢",
                  legend_note: str = "") -> str:
    """
    精簡走勢圖：同單位的 1–3 條線疊在一張，近 24 個月。

    series：[{label, color, points:[{date, value}], dash?}]
    refs：[{value, label}] 水平虛線（例如 3.5% 薪資與 2% 通膨相容的水準）
    fill_between：{a, b, label} 只在第 a 條高於第 b 條的區段塗淡色
                  （例：消費快於所得＝在動用儲蓄）
    marks：[{date, label}] 垂直虛線
    x 依實際日期定位，所以月頻、季頻（ECI）、日頻（油價）可以放同一張。
    """
    ser = []
    for s in series:
        pts = last_months(s.get("points") or [], months)
        if len(pts) >= 2:
            ser.append({**s, "points": pts})
    if not ser:
        return '<div class="empty">資料不足</div>'
    allv = [p["value"] for s in ser for p in s["points"]]
    allv += [r["value"] for r in refs]
    if zero:
        allv.append(0.0)
    lo, hi = min(allv), max(allv)
    pad = ((hi - lo) or 1) * 0.1
    lo, hi = lo - pad, hi + pad
    step = _nice_step(hi - lo)
    import math
    t0 = math.ceil(lo / step) * step
    ticks = []
    t = t0
    while t <= hi + 1e-9:
        ticks.append(round(t, 6))
        t += step
    rng = hi - lo
    x0 = min(_mkey(s["points"][0]["date"]) for s in ser)
    x1 = max(_mkey(s["points"][-1]["date"]) for s in ser)
    xr = (x1 - x0) or 1
    W, H = 600, height

    def X(d):
        return (_mkey(d) - x0) / xr * W

    def Yp(v):
        return (1 - (v - lo) / rng) * 100

    def Y(v):
        return Yp(v) / 100 * H

    svg = []
    for tv in ticks:
        svg.append(f'<line x1="0" x2="{W}" y1="{Y(tv):.1f}" y2="{Y(tv):.1f}" '
                   f'stroke="var(--grid)" stroke-width="1" vector-effect="non-scaling-stroke"/>')
    if zero and lo < 0 < hi:
        svg.append(f'<line x1="0" x2="{W}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" '
                   f'stroke="var(--baseline)" stroke-width="1" vector-effect="non-scaling-stroke"/>')
    if fill_between:
        A = {p["date"][:7]: p["value"] for p in ser[fill_between["a"]]["points"]}
        B = {p["date"][:7]: p["value"] for p in ser[fill_between["b"]]["points"]}
        keys = sorted(set(A) & set(B))
        for k1, k2 in zip(keys, keys[1:]):
            a1, a2, b1, b2 = A[k1], A[k2], B[k1], B[k2]
            xa, xb = X(k1 + "-01"), X(k2 + "-01")
            d1, d2 = a1 - b1, a2 - b2
            if d1 <= 0 and d2 <= 0:
                continue
            if d1 > 0 and d2 > 0:
                pts = [(xa, Y(a1)), (xb, Y(a2)), (xb, Y(b2)), (xa, Y(b1))]
            else:
                f = d1 / (d1 - d2)
                xc = xa + (xb - xa) * f
                yc = Y(b1 + (b2 - b1) * f)
                pts = ([(xa, Y(a1)), (xc, yc), (xa, Y(b1))] if d1 > 0
                       else [(xc, yc), (xb, Y(a2)), (xb, Y(b2))])
            svg.append('<polygon points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
                       + '" fill="var(--fillb, rgba(235,104,52,.16))"/>')
    for r in refs:
        svg.append(f'<line x1="0" x2="{W}" y1="{Y(r["value"]):.1f}" y2="{Y(r["value"]):.1f}" '
                   f'stroke="var(--text-secondary)" stroke-width="1" stroke-dasharray="5 4" '
                   f'vector-effect="non-scaling-stroke"/>')
    for m in marks:
        mx = X(m["date"])
        svg.append(f'<line x1="{mx:.1f}" x2="{mx:.1f}" y1="0" y2="{H}" stroke="var(--muted)" '
                   f'stroke-width="1" stroke-dasharray="3 3" vector-effect="non-scaling-stroke"/>')
    for s in ser:
        poly = " ".join(f'{X(p["date"]):.1f},{Y(p["value"]):.1f}' for p in s["points"])
        dash = ' stroke-dasharray="6 4"' if s.get("dash") else ""
        svg.append(f'<polyline points="{poly}" fill="none" stroke="{s["color"]}" '
                   f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"{dash} '
                   f'vector-effect="non-scaling-stroke"/>')
    # HTML 疊層：y 刻度、基準線標籤、垂直標記標籤、終點圓點、hover 切片
    over = []
    for tv in ticks:
        over.append(f'<span class="cl-tick" style="top:{Yp(tv):.1f}%">'
                    f'{tv:g}{_esc(unit)}</span>')
    for r in refs:
        over.append(f'<span class="cl-reflab" style="top:{Yp(r["value"]):.1f}%">'
                    f'{_esc(r["label"])}</span>')
    for m in marks:
        xp = min(90.0, max(8.0, X(m["date"]) / W * 100))
        over.append(f'<span class="lmark" style="left:{xp:.1f}%">{_esc(m["label"])}</span>')
    for s in ser:
        p = s["points"][-1]
        over.append(f'<span class="ldot" style="left:{X(p["date"]) / W * 100:.2f}%;'
                    f'top:{Yp(p["value"]):.2f}%;background:{s["color"]}"></span>')
    # hover 切片：以第一條序列的日期為主，日頻資料每週取一點
    maps = [{p["date"]: p["value"] for p in s["points"]} for s in ser]
    mon = [{p["date"][:7]: p["value"] for p in s["points"]} for s in ser]
    base = ser[0]["points"]
    if len(base) > 130:
        base = base[::-(-len(base) // 110)] + [base[-1]]
    xs = [X(p["date"]) / W * 100 for p in base]
    for i, p in enumerate(base):
        l = (xs[i - 1] + xs[i]) / 2 if i else 0.0
        r_ = (xs[i] + xs[i + 1]) / 2 if i + 1 < len(xs) else 100.0
        bits = []
        for s, mp, mm in zip(ser, maps, mon):
            v = mp.get(p["date"], mm.get(p["date"][:7]))
            if v is not None:
                bits.append(f'{s["label"]} {v:,.{digits}f}{unit}')
        tip = f'{p["date"][:10] if len(base) > 60 else p["date"][:7]}｜' + "｜".join(bits)
        over.append(f'<span class="cl-hit" style="left:{l:.2f}%;width:{r_ - l:.2f}%" '
                    f'data-tip="{_esc(tip)}"></span>')
    first = min((s["points"][0]["date"] for s in ser))
    last = max((s["points"][-1]["date"] for s in ser))
    legend = "".join(
        f'<span><i style="background:{s["color"]}"></i>{_esc(s["label"])} '
        f'<b>{s["points"][-1]["value"]:,.{digits}f}{_esc(unit)}</b>'
        f'<em>（{_esc(s["points"][-1]["date"][:7].replace("-", "/"))}）</em></span>'
        for s in ser)
    for r in refs:
        legend += f'<span><i class="lg-ref"></i>{_esc(r["label"])}</span>'
    if fill_between and fill_between.get("label"):
        legend += f'<span><i class="lg-fill"></i>{_esc(fill_between["label"])}</span>'
    return (f'<div class="cl">'
            f'<div class="cl-plot" style="height:{H}px">'
            f'<svg viewBox="0 0 {W} {H}" preserveAspectRatio="none" role="img" '
            f'aria-label="{_esc(aria)}">{"".join(svg)}</svg>{"".join(over)}</div>'
            f'<div class="cl-x"><span>{_esc(first[:7].replace("-", "/"))}</span>'
            f'<span>{_esc(last[:7].replace("-", "/"))}</span></div>'
            f'<div class="cl-leg">{legend}</div>'
            + (f'<div class="cl-note">{legend_note}</div>' if legend_note else "")
            + '</div>')


def waterfall(parts: Sequence[dict], unit: str = "pp") -> str:
    """
    分項貢獻的瀑布：推升的類別由大到小往右疊、壓低的往左扣，
    每一列的色塊從上一列結束的位置開始——一眼看出「誰把 CPI 推到哪裡」。
    推升＝紅（對通膨不利）、壓低＝藍。
    """
    rows = [p for p in parts if p.get("value") is not None]
    if not rows:
        return '<div class="empty">無資料</div>'
    ups = sorted([p for p in rows if p["value"] >= 0], key=lambda p: -p["value"])
    dns = sorted([p for p in rows if p["value"] < 0], key=lambda p: p["value"])
    order = ups + dns
    cum, spans = 0.0, []
    for p in order:
        a, b = cum, cum + p["value"]
        spans.append((p, a, b))
        cum = b
    xs = [0.0] + [b for _, _, b in spans]
    lo, hi = min(xs), max(xs)
    pad = ((hi - lo) or 1) * 0.04
    lo, hi = lo - pad, hi + pad

    def P(v):
        return (v - lo) / (hi - lo) * 100
    out = ['<div class="wf">']
    zx = P(0)
    for p, a, b in spans:
        up = p["value"] >= 0
        l, r = sorted((P(a), P(b)))
        tip = f'{p["label"]}｜{p["value"]:+.2f}{unit}'
        note = f'<span class="wf-note">{_esc(p["note"])}</span>' if p.get("note") else ""
        out.append(
            f'<div class="wf-row" data-tip="{_esc(tip)}">'
            f'<div class="wf-name">{_esc(p["label"])}{note}</div>'
            f'<div class="wf-track"><span class="wf-zero" style="left:{zx:.1f}%"></span>'
            f'<span class="wf-seg {"up" if up else "dn"}" '
            f'style="left:{l:.2f}%;width:{max(r - l, .8):.2f}%"></span></div>'
            f'<div class="wf-val {"up" if up else "dn"}">{p["value"]:+.2f}'
            f'<small>{_esc(unit)}</small></div></div>')
    out.append('<div class="wf-leg"><span><i class="up"></i>推升 CPI</span>'
               '<span><i class="dn"></i>壓低 CPI</span>'
               '<span class="wf-hint">每條從上一條結束處接著畫</span></div></div>')
    return "".join(out)


def number_line(items: Sequence[dict], target: float | None = None,
                target_label: str = "", unit: str = "%", digits: int = 1) -> str:
    """
    把幾個同單位的「現在值」排在同一條數線上（通膨廣度：核心 vs 中位數 vs 截尾）。
    值很接近時點會疊在一起，所以標籤分列放在數線下方，用細引線連回點。
    items：[{label, value, color}]
    """
    its = [i for i in items if i.get("value") is not None]
    if not its:
        return ""
    vals = [i["value"] for i in its] + ([target] if target is not None else [])
    lo, hi = min(vals), max(vals)
    span = max(hi - lo, 0.6)
    mid = (lo + hi) / 2
    lo, hi = mid - span * 0.75, mid + span * 0.75

    def P(v):
        return (v - lo) / (hi - lo) * 100
    srt = sorted(its, key=lambda i: i["value"])
    dots = "".join(
        f'<span class="nl-dot" style="left:{P(i["value"]):.2f}%;background:{i["color"]}" '
        f'data-tip="{_esc(i["label"])}｜{i["value"]:.{digits}f}{unit}"></span>' for i in srt)
    tg = ""
    if target is not None:
        tg = (f'<span class="nl-tgt" style="left:{P(target):.2f}%"></span>'
              f'<span class="nl-tgtlab" style="left:{P(target):.2f}%">{_esc(target_label)}</span>')
    step = _nice_step(hi - lo, 4)
    import math
    t = math.ceil(lo / step) * step
    ticks = ""
    while t <= hi:
        ticks += f'<span style="left:{P(t):.2f}%">{t:g}{unit}</span>'
        t += step
    labs = "".join(
        f'<div class="nl-lab" style="--x:{P(i["value"]):.2f}%">'
        f'<span class="nl-txt"><i style="background:{i["color"]}"></i>{_esc(i["label"])} '
        f'<b>{i["value"]:.{digits}f}{unit}</b></span></div>' for i in reversed(srt))
    return (f'<div class="nl"><div class="nl-axis">{tg}{dots}</div>'
            f'<div class="nl-ticks">{ticks}</div><div class="nl-labs">{labs}</div></div>')


def chain(steps: Sequence[dict], links: Sequence[str] = ()) -> str:
    """
    傳導鏈：上游 → 中游 → 下游，每一格一個數字。
    steps：[{label, value, note?, tone?}]，tone＝up/down/flat 決定數字顏色。
    links：格與格之間箭頭上的小字（例如「2–4 週」）。
    """
    out = ['<div class="chain">']
    for i, s in enumerate(steps):
        if i:
            lk = links[i - 1] if i - 1 < len(links) else ""
            out.append(f'<div class="ch-arrow"><span>{_esc(lk)}</span></div>')
        out.append(
            f'<div class="ch-step {s.get("tone", "")}">'
            f'<div class="ch-lab">{_esc(s["label"])}</div>'
            f'<div class="ch-val">{_esc(s["value"])}</div>'
            + (f'<div class="ch-note">{_esc(s["note"])}</div>' if s.get("note") else "")
            + '</div>')
    out.append('</div>')
    return "".join(out)


def gap_columns(points: Sequence[dict], unit: str = "pp", digits: int = 1,
                up_label: str = "", down_label: str = "", months: int = 24,
                highlight: str | None = None, labels: bool = False) -> str:
    """
    零軸上下的細柱（差距、相關係數）。正值紅、負值藍；highlight＝要強調的那一格
    （預設最新一期），其餘降成淡色。points：[{date|label, value}]
    """
    pts = [p for p in points if p.get("value") is not None]
    if "date" in (pts[0] if pts else {}):
        pts = last_months(pts, months)
    if len(pts) < 2:
        return '<div class="empty">資料不足</div>'
    vals = [p["value"] for p in pts]
    m = max(abs(v) for v in vals) or 1
    # 全部同號時零軸貼底（或貼頂），不要留半張空白
    zpos = 100.0 if min(vals) >= 0 else (0.0 if max(vals) <= 0 else 50.0)
    scale = 100.0 if zpos in (0.0, 100.0) else 50.0
    hl = highlight if highlight is not None else (pts[-1].get("date") or pts[-1].get("label"))
    cols = []
    for p in pts:
        v = p["value"]
        key = p.get("date") or p.get("label")
        h = abs(v) / m * scale
        on = " on" if key == hl else ""
        style = (f"bottom:{100 - zpos:.0f}%;height:{h:.1f}%" if v >= 0
                 else f"top:{zpos:.0f}%;height:{h:.1f}%")
        name = p.get("label") or p["date"][:7].replace("-", "/")
        lab = f'<span class="gc-lab">{_esc(p.get("label", ""))}</span>' if labels else ""
        cols.append(f'<div class="gc-col" data-tip="{_esc(name)}｜{v:+.{digits}f}{unit}">'
                    f'<span class="gc-bar {"up" if v >= 0 else "dn"}{on}" style="{style}"></span>'
                    f'{lab}</div>')
    first = pts[0].get("label") or pts[0]["date"][:7].replace("-", "/")
    last = pts[-1].get("label") or pts[-1]["date"][:7].replace("-", "/")
    axis = ("" if labels else
            f'<div class="cl-x"><span>{_esc(first)}</span><span>{_esc(last)}</span></div>')
    legend = ""
    if up_label or down_label:
        legend = (f'<div class="cl-leg"><span><i class="gc-up"></i>{_esc(up_label)}</span>'
                  f'<span><i class="gc-dn"></i>{_esc(down_label)}</span></div>')
    return (f'<div class="gc"><div class="gc-plot{" lbl" if labels else ""}">'
            f'<span class="gc-zero" style="top:{zpos:.0f}%"></span>'
            + (f'<span class="gc-mx">+{m:.{digits}f}</span>' if zpos > 0 else '<span class="gc-mx">0</span>')
            + (f'<span class="gc-mn">−{m:.{digits}f}</span>' if zpos < 100 else '<span class="gc-mn">0</span>')
            + f'{"".join(cols)}</div>{axis}{legend}</div>')



# ===========================================================================
# 長端頁（2026-10）：利率橋、組成條、類別曲線、雙色柱
# ===========================================================================
def bridge(start: float, start_label: str, parts: Sequence[dict], end: float,
           end_label: str, unit_bp: bool = True) -> str:
    """
    利率橋：起點（上月 10Y）→ 各段貢獻 → 終點（本月 10Y）。
    起點與終點畫成刻度線而不是從零長出的長條——4.68% 跟 4.99% 從零畫，
    差 31bp 的那一段會小到看不見。parts：[{label, bp, note?, main?}]
    """
    vals = [start]
    cum = start
    spans = []
    for p in parts:
        a, b = cum, cum + p["bp"] / 100
        spans.append((p, a, b))
        cum = b
        vals.append(b)
    vals.append(end)
    lo, hi = min(vals), max(vals)
    pad = ((hi - lo) or .1) * .12
    lo, hi = lo - pad, hi + pad

    def P(v):
        return (v - lo) / (hi - lo) * 100
    rows = [f'<div class="br-row br-end" data-tip="{_esc(start_label)}｜{start:.2f}%">'
            f'<div class="br-name">{_esc(start_label)}</div>'
            f'<div class="br-track"><span class="br-tick" style="left:{P(start):.2f}%"></span></div>'
            f'<div class="br-val">{start:.2f}%</div></div>']
    for p, a, b in spans:
        l, r = sorted((P(a), P(b)))
        up = p["bp"] >= 0
        tip = f'{p["label"]}｜{p["bp"]:+.0f}bp'
        rows.append(
            f'<div class="br-row{" main" if p.get("main") else ""}" data-tip="{_esc(tip)}">'
            f'<div class="br-name">{_esc(p["label"])}'
            + (f'<span class="br-note">{_esc(p["note"])}</span>' if p.get("note") else "")
            + f'</div><div class="br-track"><span class="br-guide" style="left:{P(a):.2f}%"></span>'
            f'<span class="br-seg {"up" if up else "dn"}{" muted" if p.get("muted") else ""}" '
            f'style="left:{l:.2f}%;width:{max(r - l, .7):.2f}%"></span></div>'
            f'<div class="br-val {"up" if up else "dn"}">{p["bp"]:+.0f}<small>bp</small></div></div>')
    rows.append(f'<div class="br-row br-end last" data-tip="{_esc(end_label)}｜{end:.2f}%">'
                f'<div class="br-name">{_esc(end_label)}</div>'
                f'<div class="br-track"><span class="br-tick now" style="left:{P(end):.2f}%"></span></div>'
                f'<div class="br-val">{end:.2f}%</div></div>')
    return ('<div class="br">' + "".join(rows)
            + '<div class="wf-leg"><span><i class="up"></i>推高 10Y</span>'
              '<span><i class="dn"></i>壓低 10Y</span>'
              '<span class="wf-hint">每段從上一段結束處接著畫</span></div></div>')


def segbar(parts: Sequence[dict], total_label: str = "") -> str:
    """組成條：[{label, value, color}]，各段寬度依數值（只畫正值，負值另列）。"""
    pos = [p for p in parts if (p.get("value") or 0) > 0]
    tot = sum(p["value"] for p in pos) or 1
    segs = "".join(
        f'<span class="sg-seg" style="flex:{p["value"] / tot:.4f};background:{p["color"]}" '
        f'data-tip="{_esc(p["label"])}｜{p["value"]:.2f}%">'
        f'<b>{p["value"]:.2f}%</b></span>' for p in pos)
    leg = "".join(f'<span><i style="background:{p["color"]}"></i>{_esc(p["label"])}</span>'
                  for p in parts)
    neg = [p for p in parts if (p.get("value") or 0) <= 0]
    negs = ("".join(f'<div class="sg-neg">{_esc(p["label"])} {p["value"]:.2f}%（負值，未畫入）</div>'
                    for p in neg))
    return (f'<div class="sg">{f"<div class=sg-h>{_esc(total_label)}</div>" if total_label else ""}'
            f'<div class="sg-bar">{segs}</div><div class="cl-leg">{leg}</div>{negs}</div>')


def cat_lines(series: Sequence[dict], unit: str = "%", height: int = 170,
              digits: int = 2, aria: str = "") -> str:
    """類別 x 軸的折線（殖利率曲線）：series [{label, color, dash?, points:[(x, value)]}]。"""
    xs = []
    for s_ in series:
        for x, _ in s_["points"]:
            if x not in xs:
                xs.append(x)
    vals = [v for s_ in series for _, v in s_["points"]]
    if len(xs) < 2 or not vals:
        return '<div class="empty">資料不足</div>'
    lo, hi = min(vals), max(vals)
    pad = ((hi - lo) or .5) * .12
    lo, hi = lo - pad, hi + pad
    import math
    step = _nice_step(hi - lo)
    W, H = 600, height

    def X(x):
        return (xs.index(x) + .5) / len(xs) * W

    def Yp(v):
        return (1 - (v - lo) / (hi - lo)) * 100
    svg, over = [], []
    t = math.ceil(lo / step) * step
    while t <= hi + 1e-9:
        svg.append(f'<line x1="0" x2="{W}" y1="{Yp(t) / 100 * H:.1f}" y2="{Yp(t) / 100 * H:.1f}" '
                   f'stroke="var(--grid)" vector-effect="non-scaling-stroke"/>')
        over.append(f'<span class="cl-tick" style="top:{Yp(t):.1f}%">{t:g}{_esc(unit)}</span>')
        t += step
    for s_ in series:
        poly = " ".join(f"{X(x):.1f},{Yp(v) / 100 * H:.1f}" for x, v in s_["points"])
        dash = ' stroke-dasharray="6 4"' if s_.get("dash") else ""
        svg.append(f'<polyline points="{poly}" fill="none" stroke="{s_["color"]}" stroke-width="2"'
                   f'{dash} vector-effect="non-scaling-stroke"/>')
        for x, v in s_["points"]:
            over.append(f'<span class="ldot sm" style="left:{X(x) / W * 100:.2f}%;top:{Yp(v):.2f}%;'
                        f'background:{s_["color"]}"></span>')
    for x in xs:
        bits = [f'{s_["label"]} {dict(s_["points"]).get(x):.{digits}f}{unit}' for s_ in series
                if dict(s_["points"]).get(x) is not None]
        l = xs.index(x) / len(xs) * 100
        over.append(f'<span class="cl-hit" style="left:{l:.2f}%;width:{100 / len(xs):.2f}%" '
                    f'data-tip="{_esc(x)}｜{_esc("｜".join(bits))}"></span>')
    xl = "".join(f'<span>{_esc(x)}</span>' for x in xs)
    leg = "".join(f'<span><i style="background:{s_["color"]}"></i>{_esc(s_["label"])}</span>'
                  for s_ in series)
    return (f'<div class="cl"><div class="cl-plot" style="height:{H}px">'
            f'<svg viewBox="0 0 {W} {H}" preserveAspectRatio="none" role="img" aria-label="{_esc(aria)}">'
            f'{"".join(svg)}</svg>{"".join(over)}</div>'
            f'<div class="cat-x" style="--n:{len(xs)}">{xl}</div><div class="cl-leg">{leg}</div></div>')


def dual_columns(rows: Sequence[dict], keys: Sequence[tuple], unit: str = "",
                 digits: int = 0, fmt_date=None) -> str:
    """
    每期兩根柱（例：MBS 月變動、Bills 月變動），零軸置中。
    rows：[{date, k1, k2}]；keys：[(key, label, color)]
    """
    if not rows:
        return '<div class="empty">資料不足</div>'
    m = max(abs(r.get(k) or 0) for r in rows for k, _, _ in keys) or 1
    cols = []
    for r in rows:
        bars = ""
        for i, (k, lab, col) in enumerate(keys):
            v = r.get(k) or 0
            h = abs(v) / m * 50
            st = f"bottom:50%;height:{h:.1f}%" if v >= 0 else f"top:50%;height:{h:.1f}%"
            bars += (f'<span class="dc2-bar" style="{st};left:{8 + i * 44}%;background:{col}" '
                     f'data-tip="{_esc(r["date"][:7])}｜{_esc(lab)} {v:+,.{digits}f}{_esc(unit)}"></span>')
        lab = fmt_date(r["date"]) if fmt_date else f'{int(r["date"][5:7])}月'
        cols.append(f'<div class="dc2-col">{bars}<span class="gc-lab">{_esc(lab)}</span></div>')
    leg = "".join(f'<span><i style="width:10px;height:10px;background:{c}"></i>{_esc(l)}</span>'
                  for _, l, c in keys)
    return (f'<div class="gc"><div class="gc-plot lbl"><span class="gc-zero" style="top:50%"></span>'
            f'<span class="gc-mx">+{m:,.{digits}f}</span><span class="gc-mn">−{m:,.{digits}f}</span>'
            f'{"".join(cols)}</div><div class="cl-leg">{leg}</div></div>')
