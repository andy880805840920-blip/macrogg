"""
首頁「期中選舉預測」卡片（資料：src/analysis/polymarket.py）。

版面：眾院、參院兩列（兩黨比例條＋數字＋近 30 天小走勢圖）→ 權力組合
（四種結果的堆疊條＋圖例）→ 勝負最接近的四州參院選戰 → 一行註腳。
每一列都連到 Polymarket 的對應頁面（使用者指定附連結）。
"""
from __future__ import annotations

from ..site import esc


def _pct(p: float) -> str:
    return f"{p * 100:.1f}%"


def _d1(d1) -> str:
    if d1 is None:
        return ""
    pp = round(d1 * 100, 1)
    if pp == 0:
        return "一天內持平"
    return f"一天 {pp:+.1f} 百分點"


def _d1s(d1, dem_lead: bool) -> str:
    """領先者一天的變化（短版，手機一行放得下）。"""
    pp = round((d1 if dem_lead else -d1) * 100, 1)
    return "一天持平" if pp == 0 else f"一天 {pp:+.1f} 點"


def spark(vals: list[float], w: int = 96, h: int = 26) -> str:
    """近 30 天民主黨價格的小走勢圖（純 SVG，不靠 JS）。"""
    vals = [v for v in (vals or []) if v is not None]
    if len(vals) < 3:
        return ""
    lo, hi = min(vals), max(vals)
    pad = max((hi - lo) * 0.15, 0.01)
    lo, hi = lo - pad, hi + pad
    n = len(vals)
    pts = " ".join(f"{i * (w - 4) / (n - 1) + 2:.1f},"
                   f"{h - 2 - (v - lo) / (hi - lo) * (h - 4):.1f}"
                   for i, v in enumerate(vals))
    lx, ly = pts.split(" ")[-1].split(",")
    return (f'<svg class="el-spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}"'
            f' role="img" aria-label="近 30 天走勢">'
            f'<polyline points="{pts}" fill="none" stroke="var(--el-dem)"'
            f' stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>'
            f'<circle cx="{lx}" cy="{ly}" r="2.2" fill="var(--el-dem)"/></svg>')


def _chamber2(name: str, d: dict | None) -> str:
    if not d:
        return (f'<div class="el2-ch"><span class="el2-k">{name}</span>'
                '<span class="el2-miss">本次擷取失敗</span></div>')
    dem, rep = d["dem"], d["rep"]
    is_dem = dem >= rep
    lead, lp, op = ("民主黨" if is_dem else "共和黨"), max(dem, rep), min(dem, rep)
    d1 = d.get("d1")
    sub = f'對手 {_pct(op)}' + (f'　·　{_d1s(d1, is_dem)}' if d1 is not None else "")
    return (f'<a class="el2-ch" href="{esc(d.get("url", ""))}" rel="noopener" target="_blank">'
            f'<span class="el2-k">{name}</span>'
            f'<b class="{"dem" if is_dem else "rep"}">{lead} {_pct(lp)}</b>'
            f'<small>{esc(sub)}</small>{spark(d.get("hist") or [])}</a>')


def _head_url(e: dict) -> str:
    for k in ("balance", "house", "senate"):
        if (e.get(k) or {}).get("url"):
            return e[k]["url"]
    return "https://polymarket.com/"


# ---------------------------------------------------------------------------
# 各州地圖（可收合）：參院／州長切換，頂端比分、一句話分析、地圖、競爭州
# ---------------------------------------------------------------------------
_PZ = {"D": "民", "R": "共", "I": "獨", "?": ""}
_PNAME = {"D": "民主黨", "R": "共和黨", "I": "獨立"}
# 東北部的小州：地圖上點不到，右側另外放方塊
_SMALL = ("Vermont", "New Hampshire", "Massachusetts", "Rhode Island",
          "Connecticut", "New Jersey", "Delaware", "Maryland")


def _cls(r: dict | None, up: bool) -> str:
    if r is None:
        return "c-na" if up else "c-off"
    if r["tier"] == "toss":
        return "c-toss"
    pa = r["lead"]["party"] if r["lead"]["party"] in ("D", "R", "I") else "U"
    return f"c-{pa}-{r['tier']}"


def _tip(st_zh: str, r: dict | None, up: bool, kind_zh: str) -> str:
    """提示文字：第一行州名＋分級，之後每行一位候選人（\n 分行，資訊框照行顯示）。"""
    if r is None:
        return f"{st_zh}\n" + ("有改選，但沒有盤口資料" if up else f"這次{kind_zh}沒有改選")

    def who(c):
        pz = _PZ.get(c["party"], "")
        return f'{c["p"] * 100:.1f}%　{c["name"]}' + (f"（{pz}）" if pz else "")
    return (f"{st_zh}・{r['tier_zh']}\n{who(r['lead'])}\n{who(r['other'])}"
            f"\n交易量 {r['vol'] / 1e4:,.0f} 萬美元")


def _svg(kind: str, races: dict, up_states) -> str:
    from .us_map_data import PATHS, LABELS, VIEWBOX
    from ..analysis.polymarket import ABBR, STATES
    kz = "參院" if kind == "senate" else "州長"
    up = set(up_states)
    shapes, labels, boxes = [], [], []
    for st, d in PATHS.items():
        r = races.get(st)
        cls = _cls(r, st in up)
        tip = _tip(STATES.get(st, st), r, st in up, kz)
        url = r["url"] if r else ""
        shapes.append(f'<path class="st {cls}" d="{d}" data-tip="{esc(tip)}"'
                      f' data-u="{esc(url)}"><title>{esc(tip)}</title></path>')
        if st in _SMALL or st == "District of Columbia":
            continue
        x, y = LABELS.get(st, (0, 0))
        dark = cls.endswith(("-safe", "-likely"))
        labels.append(f'<text class="lb{" lb-w" if dark else ""}" x="{x}" y="{y}">'
                      f'{ABBR.get(st, "")}</text>')
    for i, st in enumerate(_SMALL):
        r = races.get(st)
        cls = _cls(r, st in up)
        tip = _tip(STATES.get(st, st), r, st in up, kz)
        y = 196 + i * 30
        dark = cls.endswith(("-safe", "-likely"))
        boxes.append(f'<g class="sb" data-tip="{esc(tip)}" data-u="{esc(r["url"] if r else "")}">'
                     f'<title>{esc(tip)}</title>'
                     f'<rect class="st {cls}" x="928" y="{y}" width="40" height="24" rx="4"/>'
                     f'<text class="lb{" lb-w" if dark else ""}" x="948" y="{y + 16.5}">'
                     f'{ABBR.get(st, "")}</text></g>')
    x0, y0, w, h = VIEWBOX
    return (f'<svg class="el-svg" viewBox="{x0} {y0} {w} {h}" role="img" '
            f'aria-label="各州{kz}選情地圖">' + "".join(shapes) + "".join(labels)
            + "".join(boxes) + '</svg>')


def _tile(label: str, value: str, cls: str = "") -> str:
    return (f'<div class="el-st{(" " + cls) if cls else ""}"><span>{esc(label)}</span>'
            f'<b>{value}</b></div>')


def _vs(d: int, r: int, d_first: bool = True) -> str:
    a = f'<span class="vd">民 {d}</span>'
    b = f'<span class="vr">共 {r}</span>'
    return f"{a} : {b}" if d_first else f"{b} : {a}"


def _score(kind: str, m: dict, e: dict) -> str:
    """
    頂端比分＋數字磚。2026-10 手機改版：原本三行灰色長句（改選、沒改選、
    市場、眾院）在手機上擠成六七行——改成「標籤＋數字」的小磚，一眼掃完。
    """
    t = m["tally"]
    D, R, I = t["total"]["D"], t["total"]["R"], t["total"]["I"]
    tot = max(D + R + I, 1)
    unit = "席" if kind == "senate" else "州"
    if kind == "senate":
        maj = 51
        mark = f'<i class="el-maj" style="left:{maj / tot * 100:.1f}%"><span>過半 {maj}</span></i>'
    else:
        mark = ""
    bar = (f'<span class="el-sbar"><i class="dem" style="width:{D / tot * 100:.1f}%"></i>'
           + (f'<i class="ind" style="width:{I / tot * 100:.1f}%"></i>' if I else "")
           + f'<i class="rep" style="width:{R / tot * 100:.1f}%"></i>{mark}</span>')
    base, lead = t["base"], t["lead"]
    seats = (e.get("maps") or {}).get("seats") or {}

    def seat_v(s):
        return f'{esc(s["label"])}<small>{s["p"] * 100:.1f}%</small>'
    tiles = [_tile(f'改選 {t["n_up"]} {unit}・目前領先', _vs(lead["D"], lead["R"])),
             _tile("這次沒改選", _vs(int(base.get("D", 0)), int(base.get("R", 0))))]
    if kind == "senate":
        # 拿下兩院的機率已在卡片最上方，這裡不重複（2026-10）
        if seats.get("senate"):
            tiles.append(_tile("共和黨參院席次・最可能", seat_v(seats["senate"])))
        if seats.get("house"):
            tiles.append(_tile("共和黨眾院席次・最可能", seat_v(seats["house"])))
    else:
        gb = (e.get("maps") or {}).get("governor_before") or {"R": 27, "D": 23}
        tiles.append(_tile("改選前", _vs(int(gb.get("D", 0)), int(gb.get("R", 0)), False)))
        if seats.get("governor"):
            tiles.append(_tile("共和黨州長數・最可能", seat_v(seats["governor"])))
    return ('<div class="el-score">'
            f'<div class="el-sc dem"><b>{D}</b><span>民主黨</span></div>{bar}'
            f'<div class="el-sc rep"><b>{R}</b><span>共和黨</span></div></div>'
            + (f'<div class="el-sc-ind">獨立 {I} {unit}</div>' if I else "")
            + f'<p class="el-say">{esc(m["sentence"])}</p>'
            + f'<div class="el-stats">{"".join(tiles)}</div>')


def _comp_list(m: dict) -> str:
    comp = [r for v in m["tally"]["competitive"].values() for r in v]
    comp.sort(key=lambda r: r["gap"])
    if not comp:
        return ""
    items = "".join(
        f'<a class="el-cp {_cls(r, True)}" href="{esc(r["url"])}" rel="noopener" target="_blank">'
        f'<span class="el-cp-s">{esc(r["state"])}</span>'
        f'<b>{_PZ.get(r["lead"]["party"], "")} {r["lead"]["p"] * 100:.1f}%</b>'
        f'<small>{esc(r["lead"]["name"])}</small></a>' for r in comp)
    return (f'<div class="el-sub">競爭州<small>領先者低於 65%</small></div>'
            f'<div class="el-cps">{items}</div>')


# 圖例縮成短詞（深→淺的意思放進「怎麼算？」）——手機上原本要折成五行
_LEGEND = ('<ul class="el-lg">'
           '<li><i class="c-D-safe"></i><i class="c-D-likely"></i><i class="c-D-lean"></i>民主黨</li>'
           '<li><i class="c-R-safe"></i><i class="c-R-likely"></i><i class="c-R-lean"></i>共和黨</li>'
           '<li><i class="c-toss"></i>五五波</li>'
           '<li><i class="c-off"></i>沒改選</li>'
           '<li><i class="c-na"></i>沒盤口</li></ul>')

_MAP_JS = ('<script>(function(){var w=document.querySelector(".el-map");if(!w)return;'
           'w.querySelectorAll(".el-tab").forEach(function(b){b.addEventListener("click",'
           'function(){var k=b.getAttribute("data-k");'
           'w.querySelectorAll(".el-tab").forEach(function(x){'
           'x.setAttribute("aria-selected",x===b?"true":"false");});'
           'var cd=w.closest(".el-card")||w;'
           'cd.querySelectorAll(".el-pane,.el-mpane,.el-msum").forEach(function(p){'
           'p.hidden=p.getAttribute("data-k")!==k;});});});'
           'function show(el){var t=el.getAttribute("data-tip");if(!t)return;'
           'var pane=el.closest(".el-pane");var box=pane&&pane.querySelector(".el-info");'
           'if(!box)return;var u=el.getAttribute("data-u");var L=t.split("\\n");'
           'box.textContent="";var h=document.createElement("b");h.textContent=L[0];'
           'box.appendChild(h);L.slice(1).forEach(function(x){var s=document.createElement("span");'
           's.textContent=x;box.appendChild(s);});'
           'if(u){var a=document.createElement("a");a.href=u;a.target="_blank";'
           'a.rel="noopener";a.textContent="Polymarket ↗";box.appendChild(a);}}'
           'w.addEventListener("click",function(ev){var el=ev.target.closest("[data-tip]");'
           'if(el)show(el);});'
           'w.addEventListener("mouseover",function(ev){var el=ev.target.closest("[data-tip]");'
           'if(el)show(el);});})();</script>')


def map_section(e: dict) -> tuple[str, str]:
    """
    （預設顯示的地圖, 收進「更多」的細節）。2026-10 改版：地圖預設打開；
    席次比分、競爭州、計算方式只放在「更多」裡一次，不再兩處重複。
    """
    maps = e.get("maps") or {}
    if not maps.get("senate") and not maps.get("governor"):
        return "", ""
    from ..analysis.polymarket import SENATE_2026, GOVERNOR_2026
    panes, tabs, more = [], [], []
    for kind, zh, up in (("senate", "參議院", SENATE_2026), ("governor", "州長", GOVERNOR_2026)):
        m = maps.get(kind)
        if not m:
            continue
        tabs.append(f'<button type="button" class="el-tab" data-k="{kind}" role="tab"'
                    f' aria-selected="{"true" if not tabs else "false"}">{zh}</button>')
        panes.append(f'<div class="el-pane" data-k="{kind}"{"" if len(panes) == 0 else " hidden"}>'
                     + f'<div class="el-mapwrap">{_svg(kind, m["races"], up)}</div>'
                     + '<div class="el-info" aria-live="polite"><span>點選州看兩位候選人與價格</span></div>'
                     + _LEGEND + '</div>')
        # 「更多」跟著分頁切換：參議院分頁帶兩院權力組合（國會的事），州長分頁只講州長
        more.append(f'<div class="el-mpane" data-k="{kind}"{"" if len(more) == 0 else " hidden"}>'
                    + (_balance3(e.get("balance")) if kind == "senate" else "")
                    + f'<div class="el-more-k">{zh}席次</div>' + _score(kind, m, e) + _comp_list(m) + '</div>')
    map_html = ('<div class="el-map el-map2">'
                f'<div class="el-tabs" role="tablist">{"".join(tabs)}</div>'
                + "".join(panes) + '</div>' + _MAP_JS)
    how = ('<p class="el-note">比分＝照各州目前價格較高的候選人全拿，加上這次沒改選的席次；'
           '不是機率加總，只代表「如果現在的領先者都贏」。參院過半 51 席，'
           '50:50 由副總統（共和黨）投票。顏色深→淺：領先者價格 ≥85% 穩拿、'
           '65–85% 傾向、55–65% 微幅；低於 55% 為五五波。'
           '「最可能」＝Polymarket 席次區間盤裡價格最高的那一格。</p>')
    return map_html, "".join(more) + how


def _balance3(b: dict | None) -> str:
    """兩院權力組合：一條合計 100% 的比例條（2026-10）。"""
    if not b:
        return ""
    order = {"dem": 0, "mix": 1, "mix2": 2, "rep": 3, "oth": 4}
    rows = sorted(b["rows"], key=lambda r: order.get(r["key"], 9))
    tot = sum(r["p"] for r in rows) or 1
    segs = "".join(
        f'<i class="{r["key"]}" style="width:{r["p"] / tot * 100:.2f}%" title="{esc(r["label"])} {_pct(r["p"])}">'
        + (f'<em>{_pct(r["p"])}</em>' if r["p"] / tot >= 0.12 else "") + '</i>' for r in rows)
    leg = "".join(f'<li><span class="el-sw {r["key"]}"></span>{esc(r["label"])}<b>{_pct(r["p"])}</b></li>'
                  for r in rows if r["p"] >= 0.0005)
    return ('<div class="el-more-k">兩院權力組合（合計 100%）</div>'
            f'<a class="el-bal3" href="{esc(b.get("url", ""))}" rel="noopener" target="_blank">'
            f'<span class="el-b3">{segs}</span><ul class="el-legend">{leg}</ul></a>')


def election_card(e: dict | None) -> str:
    if not e or not (e.get("house") or e.get("senate")):
        return ""
    days = e.get("days_to")
    ed = str(e.get("election_date") or "")
    md = f"{int(ed[5:7])}/{int(ed[8:10])}" if len(ed) >= 10 else ""
    after = days is not None and days < 0
    if after:
        title = "期中選舉結果"
        kicker = f"美國期中選舉 {md}・開票後"
    else:
        title = "期中選舉預測"
        kicker = (f"美國期中選舉 {md}・" + ("今天投票" if days == 0
                                            else f"還有 {days} 天"))
    asof = e.get("stale_from") or e.get("date") or ""
    stale = (f"（本次擷取失敗，沿用 {esc(asof[5:])} 的數字）"
             if e.get("stale_from") else "")
    map_html, more_html = map_section(e)
    note = (f'<p class="el-note">價格＝下注者的看法，不是民調・資料日 {esc(asof[5:])}{stale}'
            '・交易量小的盤容易被少數人推動'
            + ("・開票後價格接近 100% 代表結果已底定" if after else "") + '</p>')
    _maps = e.get("maps") or {}
    _sum = ""
    for k, txt in (("senate", "更多：兩院組合、參院席次、競爭州"), ("governor", "更多：州長席次、競爭州")):
        if _maps.get(k):
            _sum += f'<span class="el-msum" data-k="{k}"{"" if not _sum else " hidden"}>{txt}</span>'
    if not _sum:
        _sum = "更多：兩院組合"
        more_html = _balance3(e.get("balance"))
    more = (f'<details class="el-more"><summary>{_sum}</summary>'
            f'<div class="el-more-b">{more_html}</div></details>')
    return ('<section class="home-zone el-card" aria-labelledby="el-title">'
            '<div class="home-zone-head"><div>'
            f'<span class="home-zone-num">{esc(kicker)}</span>'
            f'<h2 id="el-title">{title}</h2></div>'
            f'<a class="home-primary-link" href="{esc(_head_url(e))}"'
            ' rel="noopener" target="_blank">資料：Polymarket ↗</a></div>'
            '<div class="el2-chs">'
            + _chamber2("眾議院", e.get("house")) + _chamber2("參議院", e.get("senate"))
            + '</div>' + map_html + note + more + '</section>')
