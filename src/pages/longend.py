"""
長端與債務頁的新區塊（2026-10 改版）：三股力量、曲線、全球長端、供給、拍賣、信用利差。

版面原則（跟通膨頁一致）：
  · 先一句結論、再圖、最後才是方法——方法一律收進折疊
  · 一張圖一個 y 軸；走勢 24 個月；手機上用卡片不用寬表格
  · 只放事實與寫明規則的判定，不做加權總分
"""

from __future__ import annotations
import logging
log = logging.getLogger(__name__)

from ..analysis import longend as le
from ..site import esc
from . import teach

CCOL = {"real": "var(--line-1)", "infl": "var(--line-2)", "tp": "#1baf7a"}


def _bp(v, d=0) -> str:
    return "—" if v is None else f"{v:+.{d}f}bp"


def _md(iso: str) -> str:
    try:
        return f"{int(iso[5:7])}/{int(iso[8:10])}"
    except (ValueError, IndexError):
        return iso


# ---------------------------------------------------------------------------
# 頂部結論卡
# ---------------------------------------------------------------------------
def hero(d: dict) -> str:
    """
    首卡（2026-10 第三版，使用者：「畫得亂七八糟、文字太多」）：
      一行報價（10Y／30Y）→ 本月主因一句 → 三段組成的小表（點一行看白話）。
    顏色只在主因那一行（品牌橘左邊線）；藍橘綠三色與大卡全部拿掉。
    """
    L = d.get("le") or {}
    curve = d.get("curve")
    y10 = curve.levels.get("10Y") if curve else None
    y30 = curve.levels.get("30Y") if curve else None
    ch10 = (curve.changes_1m.get("10Y") * 100) if curve and "10Y" in curve.changes_1m else None
    ch30 = (curve.changes_1m.get("30Y") * 100) if curve and "30Y" in curve.changes_1m else None
    c1 = (L.get("contrib") or {}).get(1)
    dec = (L.get("dec") or [None])[-1] if L.get("dec") else None
    asof = (f'{d.get("as_of", "—")}（盤中）' if d.get("as_of_live")
            else f'{d.get("as_of", "—")}（{d.get("yield_source", "FRED")} 官方日殖利率）')

    def _q(name, v, ch):
        cls = "up" if (ch or 0) > 0 else "dn" if (ch or 0) < 0 else ""
        return (f'<div class="le2-qi"><span>{name}</span><b>{v:.2f}%</b>'
                f'<em class="{cls}">近 1 月 {_bp(ch)}</em></div>')
    top = ""
    if y10 is not None and y30 is not None:
        top = (f'<div class="le2-q">{_q("10 年期", y10, ch10)}{_q("30 年期", y30, ch30)}</div>'
               f'<div class="le2-asof">資料 {esc(asof)}</div>')
    title = (f'本月主因：{le.COMP_ZH[c1["main"]]} {c1["parts"][c1["main"]]:+.0f}bp' if c1
             else "長端利率的三股力量")
    sub = (f'{le.PRESSURE_ZH[c1["main"]]}推高長端——{le.NATURE[c1["main"]]}。' if c1 else "")
    table = ""
    if dec:
        from .. import charts
        # 組成比例條保留（使用者 2026-10）：只用品牌色——主因那段橘、其餘兩段藏青深淺
        _main = c1["main"] if c1 else None
        _shade = iter(("var(--brand-navy)", "#8b97a8"))
        col = {k: ("var(--brand-orange)" if k == _main else next(_shade)) for k in ("real", "infl", "tp")}
        seg = charts.segbar([{"label": le.COMP_ZH[k], "value": dec[k], "color": col[k]}
                             for k in ("real", "infl", "tp")])
        rows = ""
        for k in ("real", "infl", "tp"):
            dv = c1["parts"][k] if c1 else None
            main = bool(c1 and c1["main"] == k)
            cls = "up" if (dv or 0) > 0 else "dn" if (dv or 0) < 0 else "fl"
            rows += (f'<div class="le2-r{" main" if main else ""}" title="{esc(le.NATURE[k])}">'
                     f'<div class="le2-n"><span><i class="le2-sw" style="background:{col[k]}"></i>{esc(le.COMP_ZH[k])}'
                     + ('<em>本月主因</em>' if main else "") + '</span>'
                     f'<small>{esc(le.PRESSURE_ZH[k])}</small></div>'
                     f'<b>{dec[k]:.2f}%</b><i class="{cls}">{_bp(dv)}</i></div>')
        mo = int(dec["month"][5:])
        chg_h = (f'{int(c1["from"][5:])}→{int(c1["to"][5:])} 月' if c1 else "變動")
        table = (f'<div class="le2-seg">{seg}</div><div class="le2-t"><div class="le2-h"><span>10Y 三段組成（{mo} 月均）</span>'
                 f'<span>水準</span><span>{chg_h}</span></div>{rows}</div>'
                 '<p class="le2-tip">點一行看白話說明</p>')
    js = ('<script>(function(){document.querySelectorAll(".le2-r[title]").forEach(function(r){'
          'r.addEventListener("click",function(){r.classList.toggle("tip-on");});});})();</script>')
    return (f'<div class="grid"><div class="card focus-card"><div class="le-hero le2">'
            f'{top}<h2 class="focus-title">{esc(title)}</h2>'
            + (f'<p class="focus-sub">{esc(sub)}</p>' if sub else "")
            + f'{table}{_evidence()}{events(L)}</div></div></div>{js}')


def _evidence() -> str:
    """首卡的「判斷依據」：三股力量各自用什麼量、為什麼這樣分。"""
    from . import focus_evidence
    steps = "".join(
        f'<div class="logic-step"><b>{esc(p)}＝{esc(zh)}</b><span>{esc(src)}</span></div>'
        for p, zh, src in (
            ("政策壓力", "預期實質路徑", "Kim-Wright 擬合殖利率 − 期限溢酬 − 預期通膨；市場對未來實質短率的平均預期"),
            ("通膨壓力", "預期通膨", "克里夫蘭聯儲 10 年預期通膨（模型值，已扣風險溢酬）"),
            ("財政與供給壓力", "期限溢酬", "Kim-Wright 10 年期限溢酬")))
    return focus_evidence(f'<div class="logic-strip">{steps}</div>'
                          '<p class="hint" style="margin-top:8px">三段一律用月均相加，剩下的差列為殘差；'
                          'TIPS 與損益兩平只當參考。本月主因＝三段中變動絕對值最大的那一段。</p>',
                          "查看三股力量怎麼量")


def events(L: dict) -> str:
    ev = L.get("events") or []
    if not ev:
        return ""
    items = "".join(f'<div class="ev"><span class="ev-d">{esc(_md(e["date"]))}</span>'
                    f'<span class="ev-k">{esc(e["kind"])}</span><span class="ev-t">{esc(_ev_text(e))}</span></div>'
                    for e in ev[:6])
    return f'<div class="evs"><div class="evs-h">接下來 4 週</div><div class="ev-grid">{items}</div></div>'


def _amt(a: dict) -> str:
    return f'{a["offering"] * 10:,.0f} 億美元' if a.get("offering") else "金額待公告"


def _ev_text(e: dict) -> str:
    return e["text"]


# ---------------------------------------------------------------------------
# 長端利率的組成
# ---------------------------------------------------------------------------
def _trend_line(L: dict) -> str:
    """
    「趨勢還是雜訊」：1、3、12 個月的主因是否一致（規則判定，2026-10）。
      三個窗主因相同          → 趨勢
      1 個月不同、3 與 12 相同 → 本月是短期雜訊，趨勢仍是 3／12 個月那一段
      其他                    → 方向未定
    """
    c = L.get("contrib") or {}
    mains = {k: (c.get(k) or {}).get("main") for k in (1, 3, 12)}
    if not all(mains.values()):
        return ""
    m1, m3, m12 = mains[1], mains[3], mains[12]
    z = le.COMP_ZH
    if m1 == m3 == m12:
        txt, cls = (f"<b>趨勢</b>：{z[m1]}在 1、3、12 個月都是最大推力，"
                    f"這不是單月雜訊。"), "trend"
    elif m3 == m12:
        txt, cls = (f"<b>本月偏雜訊</b>：這個月主因是{z[m1]}，但 3 與 12 個月的主因都是"
                    f"{z[m3]}——趨勢仍是後者。"), "noise"
    elif m1 == m3:
        txt, cls = (f"<b>新趨勢成形中</b>：近 1、3 個月主因都是{z[m1]}，"
                    f"12 個月看則是{z[m12]}。"), "turn"
    else:
        txt, cls = (f"<b>方向未定</b>：1、3、12 個月的主因各不相同"
                    f"（{z[m1]}／{z[m3]}／{z[m12]}）。"), "mixed"
    chips = "".join(f'<span><em>{k} 個月</em>{z[mains[k]]}</span>' for k in (1, 3, 12))
    if cls == "trend":            # 三個窗都同一段：標籤列只是重複，不放
        chips = ""
    return (f'<div class="le3-tr {cls}"><p>{txt}</p>'
            + (f'<div class="le3-trc">{chips}</div>' if chips else "") + '</div>')


def decomp(d: dict) -> str:
    """
    長端利率的組成（2026-10 v3，使用者：點開太多層）：
    這一區只回答「本月的主因是趨勢還是雜訊」。首卡已經講了這個月是誰在推，
    這裡不再重複主因句；房貸拿掉；「Fed 跟上曲線」搬到殖利率曲線；
    市場口徑、教學與方法併成一個收合。
    """
    L = d.get("le") or {}
    br = L.get("bridges") or {}
    if not br:
        return '<div class="empty">拆解資料不足</div>'
    tabs = ""
    for i, k in enumerate((1, 3, 12)):
        if k not in br:
            continue
        tabs += (f'<input type="radio" name="le-br" id="le-br{k}"{" checked" if i == 0 else ""}>'
                 f'<label for="le-br{k}">{k} 個月</label>')
    panes = "".join(f'<div class="tabp p{k}">{br[k]}</div>' for k in (1, 3, 12) if k in br)
    mr = L.get("market_ref") or {}
    ref = (f'<p><b>市場口徑</b>：TIPS 實質利率 {mr.get("real") or 0:.2f}%、損益兩平 {mr.get("be") or 0:.2f}%。'
           '兩者各自混了風險溢酬與流動性溢酬，加不出三股力量，只當參考。</p>') if mr.get("real") is not None else ""
    return f"""
    {_trend_line(L)}
    <div class="tabs le-tabs">{tabs}{panes}</div>
    <div class="viz-block"><div class="viz-h">三段的走勢（月均，近 24 個月）</div>
      {L.get('dec_lines', '')}</div>
    <details class="f-more"><summary>怎麼讀・方法與資料</summary>
      <div class="f-detail le3-how">
        <p><b>怎麼讀</b>：10 年期殖利率拆成三段相加——預期實質路徑（政策）、預期通膨、期限溢酬（財政與供給）。
        先看首卡的「本月主因」，再看這裡 1、3、12 個月是否同一段：一致才是趨勢。</p>
        <p><b>期限溢酬</b>：Kim-Wright 模型（FRED THREEFYTP10）。<b>預期通膨</b>：克里夫蘭聯儲 EXPINF10YR（月頻，已扣風險溢酬）。
        <b>預期實質路徑</b>：擬合殖利率 − 期限溢酬 − 預期通膨。<b>殘差</b>：實際 10 年期與模型擬合值的差，照實列出。</p>
        <p>預期通膨是月頻，三段一律用月均對齊，所以跟頁首的日資料變動不會完全一樣；兩個模型出自不同機構，相加是近似。</p>
        {ref}
      </div>
    </details>"""


# ---------------------------------------------------------------------------
# 殖利率曲線（2026-10 v2）
# ---------------------------------------------------------------------------
_RG_CLS = {"bear_steep": "bear", "bear_flat": "bear", "bull_steep": "bull", "bull_flat": "bull",
           "twist_steep": "tw", "twist_flat": "tw", "flat": "fl", "na": "fl"}


def _sbp(v) -> str:
    return "—" if v is None else f"{v:+.0f}".replace("-", "−")


_TEN = (("y2", "2", "2Y"), ("y10", "10", "10Y"), ("y30", "30", "30Y"))
_SPK = (("10-2", "10−2"), ("30-10", "30−10"), ("30-2", "30−2"))


def _cls(v) -> str:
    return "flat" if v is None or abs(v) < 0.5 else "up" if v > 0 else "dn"


def _cw_brief(b: dict | None, events=None) -> str:
    """最上方：一段白話（少數關鍵數字）＋「數字明細」收合＋複製按鈕。固定滾動一週。"""
    if not b:
        return ""
    prose = le.brief_prose(b, events)
    detail = "".join(f"<li>{esc(x)}</li>" for x in b["text"])
    span = f"{le._md2(b['from'])} → {le._md2(b['to'])}"
    return (f'<section class="cwb" aria-label="30−2 週報"><div class="cwb-h"><b>30−2 週報</b>'
            f'<span>{span}・滾動一週（最新收盤比 5 個交易日前）</span>'
            f'<button type="button" class="cwb-copy" data-copy="{esc(prose + "（30−2 週報 " + span + "，MACRO GG）")}">複製</button></div>'
            f'<p class="cwb-prose">{esc(prose)}</p>'
            f'<details class="cwb-more"><summary>數字明細（各天期、分段、遠期）</summary><ul>{detail}</ul></details>'
            f'</section>')


_ROWS = (("ten", "y2", "2", "2Y"), ("ten", "y10", "10", "10Y"), ("ten", "y30", "30", "30Y"),
         ("sp", "10-2", "10-2", "10−2"), ("sp", "30-10", "30-10", "30−10"), ("sp", "30-2", "30-2", "30−2"))


def _bar(v, scale) -> str:
    """變化欄的細長條：0 在中間，往右＝上升／擴大、往左＝下跌／收窄。"""
    if v is None or not scale:
        return '<i class="cwm-bar"></i>'
    w = min(50.0, abs(v) / scale * 50)
    side = "r" if v > 0 else "l"
    return f'<i class="cwm-bar"><b class="{side} {_cls(v)}" style="width:{w:.1f}%"></b></i>'


def _range(v, lo, hi) -> str:
    """年內位置條：左＝年內最低、右＝年內最高，圓點＝現在。"""
    if v is None or hi is None or lo is None or hi - lo < 1e-9:
        return ""
    p = max(0.0, min(100.0, (v - lo) / (hi - lo) * 100))
    return f'<i class="cwm-rng" title="年內區間"><b style="left:{p:.1f}%"></b></i>'


def _spark(vals) -> str:
    vals = [v for v in vals or [] if v is not None]
    if len(vals) < 5:
        return ""
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    pts = " ".join(f"{i / (len(vals) - 1) * 56:.1f},{14 - (v - lo) / span * 12:.1f}" for i, v in enumerate(vals))
    return (f'<svg class="cwm-spark" viewBox="0 0 56 16" aria-hidden="true">'
            f'<polyline points="{pts}" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>')


def _cw_matrix(b: dict | None, r0: dict, win_label: str) -> str:
    """
    監控表（2026-10 v4）：一列一個標的、從左讀到右。
      現在（含年內位置條）｜週變化｜所選期間（跟期間按鈕連動）｜1 年後隱含｜5 年後隱含
    只有兩個變化欄上色並附細長條；遠期是黑字＋灰色差距＋近 3 個月小走勢線。
    """
    T = {t["k"]: t for t in r0["tenors"]}
    S = {x["key"]: x for x in r0["spreads"]}
    b = b or {}
    lv, sp, fw, yr = b.get("lv") or {}, b.get("sp") or {}, b.get("fwd") or {}, b.get("ytd") or {}
    hist = b.get("fwd_hist") or {}

    def now_of(kind, key):
        if kind == "ten":
            return lv.get(key, {}).get("b")
        return sp.get(key, {}).get("b")

    def week_of(kind, key):
        return (lv if kind == "ten" else sp).get(key, {}).get("d")

    def sel_of(kind, mk):
        return T[mk]["d"] if kind == "ten" else (S[mk]["d"] if mk in S else None)
    scale = {}
    for kind in ("ten", "sp"):
        ks = [r for r in _ROWS if r[0] == kind]
        scale[("w", kind)] = max([abs(week_of(k, key) or 0) for k, _, key, _ in ks] + [2])
        scale[("s", kind)] = max([abs(sel_of(k, mk) or 0) for k, mk, _, _ in ks] + [2])
    head = (f'<thead><tr><th scope="col">標的</th>'
            f'<th scope="col">現在<small>{le._md2(b["to"]) if b else ""}・年內位置</small></th>'
            f'<th scope="col" class="cwm-c">週變化<small>{(le._md2(b["from"]) + " → " + le._md2(b["to"])) if b else ""}</small></th>'
            f'<th scope="col" class="cwm-c cwm-selh">{esc(win_label)}<small class="cwm-when">{le._md2(r0["start"])} → {le._md2(r0["end"])}</small></th>'
            f'<th scope="col" class="cwm-f">1 年後隱含<small>遠期・比現在</small></th>'
            f'<th scope="col" class="cwm-f">5 年後隱含<small>遠期・比現在</small></th></tr></thead>')
    body = []
    for kind, mk, key, zh in _ROWS:
        if kind == "ten" and key == "2":
            body.append('<tr class="cwm-g"><th colspan="6">殖利率（%）</th></tr>')
        if kind == "sp" and key == "10-2":
            body.append('<tr class="cwm-g"><th colspan="6">利差（bp）</th></tr>')
        nv = now_of(kind, key)
        r = yr.get(key) or {}
        now_txt = "—" if nv is None else (le._num(nv, 2) + "%" if kind == "ten" else le._num(nv))
        cells = [f'<th scope="row">{zh}</th>',
                 f'<td class="cwm-now"><span>{now_txt}</span>{_range(nv, r.get("lo"), r.get("hi"))}</td>']
        w = week_of(kind, key)
        cells.append(f'<td class="cwm-c"><span class="{_cls(w)}">{"—" if w is None else le._sgn(w, "")}</span>'
                     f'{_bar(w, scale[("w", kind)])}</td>')
        v = sel_of(kind, mk)
        tag = ""
        if kind == "sp" and mk in S and S[mk]["code"] not in ("na",):
            tag = f'<small class="le3-rg {_RG_CLS.get(S[mk]["code"], "fl")}">{esc(S[mk]["zh"])}</small>'
        cells.append(f'<td class="cwm-c" data-m="{mk}"><span class="{_cls(v)}">{"—" if v is None else le._sgn(v, "")}</span>'
                     f'{_bar(v, scale[("s", kind)])}{tag}</td>')
        for h in ("1", "5"):
            f = fw.get(h)
            if not f or nv is None:
                cells.append('<td class="cwm-f">—</td>')
                continue
            fv = f["lv"][key] if kind == "ten" else f["sp"][key]
            gap = (fv - nv) * 100 if kind == "ten" else fv - nv
            txt = le._num(fv, 2) + "%" if kind == "ten" else le._num(fv)
            cells.append(f'<td class="cwm-f"><span>{txt}</span><small>{le._sgn(gap, "")}</small>'
                         f'{_spark((hist.get(h) or {}).get(key))}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    note = ("變化單位 bp；殖利率為美國財政部官方日資料。年內位置條：左端＝今年最低、右端＝今年最高、圓點＝現在。"
            "遠期由目前曲線推算，含期限溢酬，是市場已定價的路徑、不是預測；小走勢線是近 3 個月的遠期值。"
            "10Y、30Y 遠期以 9 年、29 年（1 年後）與 25 年（5 年後）近似"
            + ("；3 年期資料暫缺，以 2 年與 5 年內插" if b.get("interp3") else "") + "。")
    tog = ('<div class="cw-ctl cwm-tog" role="group" aria-label="表格欄位">'
           '<button type="button" class="cw-btn on" data-v="ch" aria-pressed="true">變化</button>'
           '<button type="button" class="cw-btn" data-v="fw" aria-pressed="false">遠期</button></div>')
    return (f'<div class="cwm" data-v="ch">{tog}<div class="cwm-wrap"><table class="cwm-t" aria-label="2Y、10Y、30Y 與利差監控表">'
            f'{head}<tbody>{"".join(body)}</tbody></table></div>'
            f'<details class="cw-note"><summary>表格說明</summary><p class="cwm-note">{esc(note)}</p></details></div>')


def _cw_folds(r: dict) -> str:
    view = le.window_view(r)
    out = ['<div class="cw-panels">']
    for i, panel in enumerate(view["panels"], 1):
        out.append(f'<details class="cw-panel cw-fold" data-panel="{i}"><summary>'
                   f'<span class="cw-fold-number">{i:02d}</span><span class="cw-fold-title">'
                   f'<b>{esc(panel["title"])}</b><span class="cw-fold-reading">{esc(panel["verdict"])}</span>'
                   f'</span></summary><div class="cw-panel-content"><dl class="cw-metrics">')
        for m in panel["metrics"]:
            out.append(f'<div><dt>{esc(m["label"])}</dt><dd><b>{esc(m["value"])}</b>'
                       f'<small>{esc(m["note"])}</small></dd></div>')
        out.append(f'</dl><small class="cw-panel-note">{esc(panel["note"])}</small></div></details>')
    return "".join(out) + "</div>"


# 自選期間的瀏覽器端：跟 analysis/longend.window_analysis／window_view 同一套規則
# （tests/test_curve_window.py 逐窗比對兩邊輸出）。
_CW_CORE_JS = r"""
function cwCore(CD){var Y=CD.year;
var RG={bear_steep:'bear',bear_flat:'bear',bull_steep:'bull',bull_flat:'bull',twist_steep:'tw',twist_flat:'tw',flat:'fl',na:'fl'};
function idx(dt){var i=0;for(var j=0;j<CD.d.length;j++){if(CD.d[j]<=dt)i=j;else break;}return i;}
function ok(k,j){var a=CD[k]||[];return j>=0&&j<a.length&&a[j]!==null;}
function val(k,i){var a=CD[k]||[];for(var j=i;j>Math.max(-1,i-(k==='tp'?6:1));j--){if(j<a.length&&a[j]!==null)return a[j];}return null;}
function drvIdx(i){for(var j=i;j>Math.max(-1,i-6);j--){if(ok('y10',j)&&ok('be',j)&&ok('real',j))return j;}return null;}
function lagIdx(k,i){for(var j=i;j>Math.max(-1,i-6);j--){if(ok(k,j))return j;}return null;}
function hu(v,nd){var f=Math.pow(10,nd);return Math.floor(v*f+0.5+1e-10)/f;}
function num(v,nd){nd=nd||0;var r=hu(v,nd);if(r===0)r=0;return r.toFixed(nd).replace('-','−');}
function sgn(v,u,nd){if(u===undefined)u='bp';nd=nd||0;var r=hu(v,nd);if(r===0)return (0).toFixed(nd)+u;return (r>0?'+':'')+num(v,nd)+u;}
function md2(s){return parseInt(s.slice(5,7),10)+'/'+parseInt(s.slice(8,10),10);}
function r6(v){return Math.floor(v*1e6+0.5)/1e6;}
function regime(dl,ds){if(dl===null||ds===null)return{code:'na',zh:'—',lead:''};var x=r6(dl-ds);
 if(Math.abs(x)<2)return{code:'flat',zh:'大致持平',lead:''};
 if(x>0){if(dl>0&&ds<0)return{code:'twist_steep',zh:'扭轉變陡',lead:'兩端反向'};
  if(Math.abs(dl)>=Math.abs(ds))return dl>0?{code:'bear_steep',zh:'熊陡',lead:'長端帶動'}:{code:'bull_steep',zh:'牛陡',lead:'短端帶動'};
  return ds<0?{code:'bull_steep',zh:'牛陡',lead:'短端帶動'}:{code:'bear_steep',zh:'熊陡',lead:'長端帶動'};}
 if(dl<0&&ds>0)return{code:'twist_flat',zh:'扭轉變平',lead:'兩端反向'};
 if(Math.abs(ds)>=Math.abs(dl))return ds>0?{code:'bear_flat',zh:'熊平',lead:'短端帶動'}:{code:'bull_flat',zh:'牛平',lead:'長端帶動'};
 return dl<0?{code:'bull_flat',zh:'牛平',lead:'長端帶動'}:{code:'bear_flat',zh:'熊平',lead:'短端帶動'};}
function analysis(start,end){var ia=idx(start),ib=idx(end);if(ia>=ib)ia=Math.max(0,ib-1);
 var da=CD.d[ia],db=CD.d[ib],ten=[],T={};
 [['y2','2 年'],['y10','10 年'],['y30','30 年']].forEach(function(p){var a=val(p[0],ia),b=val(p[0],ib);
  var t={k:p[0],zh:p[1],a:a,b:b,d:(a===null||b===null)?null:(b-a)*100};ten.push(t);T[p[0]]=t;});
 var sp=[];
 [['10-2','y10','y2'],['30-10','y30','y10'],['30-2','y30','y2']].forEach(function(p){var L=T[p[1]],Sh=T[p[2]];
  if(L.a===null||L.b===null||Sh.a===null||Sh.b===null)return;var a=(L.a-Sh.a)*100,b=(L.b-Sh.b)*100,g=regime(L.d,Sh.d);
  sp.push({key:p[0],a:a,b:b,d:b-a,zh:g.zh,lead:g.lead,code:g.code});});
 var ja=drvIdx(ia),jb=drvIdx(ib),be=null,real=null,d10=null,dd=[null,null];
 if(ja!==null&&jb!==null&&ja<jb){be=(CD.be[jb]-CD.be[ja])*100;real=(CD.real[jb]-CD.real[ja])*100;d10=(CD.y10[jb]-CD.y10[ja])*100;dd=[CD.d[ja],CD.d[jb]];}
 function lagged(k){var a=lagIdx(k,ia),b=lagIdx(k,ib);if(a===null||b===null||a>=b)return null;return[CD[k][a],CD[k][b],[CD.d[a],CD.d[b]]];}
 var t=lagged('tp'),o=lagged('oil'),a3=val('y3m',ia),b3=val('y3m',ib);
 var result={start:da,end:db,ia:ia,ib:ib,tenors:ten,spreads:sp,drivers:{be:be,real:real,d10:d10,dates:dd,
  tp:t?(t[1]-t[0])*100:null,tp_dates:t?t[2]:[null,null],oil:(o&&o[0]&&o[1])?(o[1]/o[0]-1)*100:null,
  y3m:(a3===null||b3===null)?null:(b3-a3)*100}};
 var v=view(result);result.text=[v.headline,v.panels[0].verdict,v.panels[1].verdict];return result;}
function headline(S){var x=S['30-2'],a=S['10-2'],b=S['30-10'];if(!x||!a||!b)return'資料不足，暫不判定曲線方向。';
 var seg='10−2 '+sgn(a.d,'')+'、30−10 '+sgn(b.d,'');
 if(Math.abs(r6(x.d))<2){if(Math.abs(r6(a.d))>=2&&Math.abs(r6(b.d))>=2&&a.d*b.d<0)return'30−2 大致持平（'+sgn(x.d)+'）：'+seg+'，兩段互相抵銷。';
  return'曲線大致持平：30−2 '+sgn(x.d)+'；'+seg+'。';}
 return'曲線'+x.zh+(x.lead?'（'+x.lead+'）':'')+'：30−2 '+(x.d>0?'擴大':'收窄')+' '+num(Math.abs(x.d))+'bp；'+seg+'。';}
function view(r){
 var T={},S={};r.tenors.forEach(function(t){T[t.k]=t;});r.spreads.forEach(function(s){S[s.key]=s;});var D=r.drivers,panels=[];
 var be=D.be,real=D.real,dy=D.d10,has=be!==null&&real!==null&&dy!==null,aligned=has&&Math.abs(dy-be-real)<=2;
 var verdict=aligned&&Math.max(Math.abs(dy),Math.abs(be),Math.abs(real))<0.5?'10 年期與拆解指標大致持平。':aligned&&Math.abs(dy)<0.5?'通膨補償與實質利率的變動大致抵銷，10 年期接近持平。':aligned?'10 年期主要由'+(Math.abs(be)>Math.abs(real)?'通膨補償':'實質利率')+'變動帶動。':!has?'所選期間的拆解資料不足，暫不判定主要原因。':'參考指標與 10 年期變動尚未吻合，暫不判定主要原因。';
 function metric(label,v,u,note){return{label:label,value:v===null?'—':sgn(v,u===undefined?'bp':u),note:note||'所選期間變動'};}
 var dd=D.dates||[null,null],dn=(dd[0]&&dd[1])?'拆解資料 '+md2(dd[0])+' → '+md2(dd[1]):'拆解資料不足',td=D.tp_dates||[null,null];
 var lm=[metric('10 年期',dy,'bp',dn),metric('通膨補償',be,'bp',dn),metric('實質利率',real,'bp',dn),
  metric('期限溢酬（參考）',D.tp,'bp',D.tp!==null?'資料日 '+md2(td[0])+' → '+md2(td[1]):'所選期間尚無新資料（約晚一週公布）')];
 if(D.oil!==null)lm.push(metric('油價（參考）',D.oil,'%'));
 panels.push({title:'10 年期為什麼變',verdict:verdict,metrics:lm,note:'實質利率比殖利率晚一天公布，拆解改用兩端最近都有資料的日子；期限溢酬僅作參考，不加到通膨補償與實質利率之上。'});
 var dy2=T.y2.d,y3m=D.y3m,path=dy2===null||y3m===null?null:dy2-y3m;
 verdict=path===null?'資料不足，暫不判定短端定價方向。':path>5?'2 年期相對短端走高，未來利率偏高的定價增強。':path< -5?'2 年期相對短端走低，未來利率偏低的定價增強。':'2 年期與短端的相對變化不大，定價方向大致未變。';
 panels.push({title:'短端定價怎麼變',verdict:verdict,metrics:[metric('2 年期',dy2),metric('3 個月期',y3m),metric('2 年 − 3 個月利差',path)],note:'這是公債短端的相對變化；年底政策利率方向另看下方期貨定價。'});
 return{headline:headline(S),panels:panels};}
function startFor(k,end){if(k==='ytd')return(Y-1)+'-12-31';var n={'1w':7,'1m':30,'3m':91}[k];
 var t=new Date(end+'T00:00:00Z');t.setUTCDate(t.getUTCDate()-n);return t.toISOString().slice(0,10);}
return{analysis:analysis,view:view,startFor:startFor,num:num,sgn:sgn,RG:RG,idx:idx,md2:md2};}
"""

_CW_JS = _CW_CORE_JS + r"""
(function(){
var root=document.querySelector('.cw');if(!root)return;
var CD=JSON.parse(document.getElementById('cw-data').textContent);
var C=cwCore(CD),analysis=C.analysis,startFor=C.startFor,num=C.num,sgn=C.sgn,RG=C.RG,cur=null,mode='ten';
function safe(v){return String(v).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function cls(v){return v===null||Math.abs(v)<0.5?'flat':v>0?'up':'dn';}
function explain(r){var v=C.view(r);
 v.panels.forEach(function(p,i){var panel=root.querySelector('[data-panel="'+(i+1)+'"]');if(!panel)return;
 panel.querySelector('.cw-fold-reading').textContent=p.verdict;
 panel.querySelector('.cw-panel-content').innerHTML='<dl class="cw-metrics">'+p.metrics.map(function(m){return '<div><dt>'+safe(m.label)+'</dt><dd><b>'+safe(m.value)+'</b><small>'+safe(m.note)+'</small></dd></div>';}).join('')+'</dl><small class="cw-panel-note">'+safe(p.note)+'</small>';});}
function bar(v,sc){if(v===null||!sc)return'<i class="cwm-bar"></i>';var w=Math.min(50,Math.abs(v)/sc*50);return'<i class="cwm-bar"><b class="'+(v>0?'r':'l')+' '+cls(v)+'" style="width:'+w.toFixed(1)+'%"></b></i>';}
function matrix(r,label){root.querySelectorAll('.cwm-when').forEach(function(e){e.textContent=C.md2(r.start)+' → '+C.md2(r.end);});
 var h=root.querySelector('.cwm-selh');if(h&&label)h.firstChild.nodeValue=label;
 var sp={};r.spreads.forEach(function(x){sp[x.key]=x;});
 var st=Math.max.apply(null,[2].concat(r.tenors.map(function(t){return Math.abs(t.d||0);}))),ss=Math.max.apply(null,[2].concat(r.spreads.map(function(x){return Math.abs(x.d||0);})));
 r.tenors.forEach(function(t){var e=root.querySelector('td[data-m="'+t.k+'"]');if(e)e.innerHTML='<span class="'+cls(t.d)+'">'+(t.d===null?'—':safe(sgn(t.d,'')))+'</span>'+bar(t.d,st);});
 ['10-2','30-10','30-2'].forEach(function(k){var e=root.querySelector('td[data-m="'+k+'"]');if(!e)return;var x=sp[k];
  if(!x){e.innerHTML='<span class="flat">—</span>'+bar(null,ss);return;}
  e.innerHTML='<span class="'+cls(x.d)+'">'+safe(sgn(x.d,''))+'</span>'+bar(x.d,ss)+(x.code!=='na'?'<small class="le3-rg '+(RG[x.code]||'fl')+'">'+safe(x.zh)+'</small>':'');});}
var DEF={ten:[['2Y',function(j){return CD.y2[j];},'var(--y2)',1],['10Y',function(j){return CD.y10[j];},'var(--y10)',1],['30Y',function(j){return CD.y30[j];},'var(--y30)',1]],
 sp:[['10−2',function(j){return CD.y10[j]===null||CD.y2[j]===null?null:CD.y10[j]-CD.y2[j];},'var(--line-1)',1],
     ['30−10',function(j){return CD.y30[j]===null||CD.y10[j]===null?null:CD.y30[j]-CD.y10[j];},'var(--line-2)',1],
     ['30−2',function(j){return CD.y30[j]===null||CD.y2[j]===null?null:CD.y30[j]-CD.y2[j];},'var(--brand-ink)',2]]};
function nice(span){var c=[1,2,5,10,20,25,50,100];for(var i=0;i<c.length;i++){if(span/c[i]<=5)return c[i];}return 200;}
var EV=CD.ev||[];
function cum(r){var box=root.querySelector('.cwc-plot');if(!box)return;var ia=r.ia,ib=r.ib,defs=DEF[mode],S=[];
 defs.forEach(function(d){var b0=d[1](ia),pts=[];for(var j=ia;j<=ib;j++){var v=d[1](j);pts.push(v===null||b0===null?null:(v-b0)*100);}S.push({n:d[0],c:d[2],w:d[3],p:pts});});
 var all=[0];S.forEach(function(s){s.p.forEach(function(v){if(v!==null)all.push(v);});});
 var lo=Math.min.apply(null,all),hi=Math.max.apply(null,all),st=nice(Math.max(hi-lo,4));lo=Math.floor(lo/st)*st;hi=Math.ceil(hi/st)*st;if(hi===lo)hi=lo+st;
 var W=Math.max(320,Math.round(box.clientWidth||640)),H=W<560?190:220,L=W<560?34:42,R=W<560?62:76,T=10,B=24,n=Math.max(1,ib-ia);function X(i){return L+(W-L-R)*i/n;}function Yv(v){return T+(H-T-B)*(hi-v)/(hi-lo);}
 var g='';for(var t=lo;t<=hi+1e-9;t+=st){g+='<line x1="'+L+'" x2="'+(W-R)+'" y1="'+Yv(t)+'" y2="'+Yv(t)+'" class="'+(t===0?'cwc-zero':'cwc-grid')+'"/><text x="'+(L-6)+'" y="'+(Yv(t)+4)+'" class="cwc-ax" text-anchor="end">'+(t>0?'+':'')+String(t).replace('-','−')+'</text>';}
 [0,Math.round(n/2),n].forEach(function(i,k){g+='<text x="'+X(i)+'" y="'+(H-6)+'" class="cwc-ax" text-anchor="'+(k===0?'start':k===2?'end':'middle')+'">'+C.md2(CD.d[ia+i])+'</text>';});
 var evs=[];EV.forEach(function(e){for(var j=ia;j<=ib;j++){if(CD.d[j]===e[0]){evs.push([j-ia,e[1]]);break;}}});
 evs.forEach(function(e){g+='<line class="cwc-ev" x1="'+X(e[0])+'" x2="'+X(e[0])+'" y1="'+T+'" y2="'+(H-B)+'"><title>'+safe(C.md2(CD.d[ia+e[0]])+' '+e[1])+'</title></line>';});
 var lab=[];S.forEach(function(s){var d='',pen=false;s.p.forEach(function(v,i){if(v===null){pen=false;return;}d+=(pen?'L':'M')+X(i).toFixed(1)+' '+Yv(v).toFixed(1);pen=true;});
  g+='<path d="'+d+'" fill="none" stroke="'+s.c+'" stroke-width="'+s.w+'" stroke-linejoin="round" stroke-linecap="round"/>';
  var lv=null;for(var i=s.p.length-1;i>=0;i--){if(s.p[i]!==null){lv=s.p[i];break;}}if(lv!==null)lab.push({y:Yv(lv),t:s.n+' '+sgn(lv,''),c:s.c});});
 lab.sort(function(a,b){return a.y-b.y;});for(var i=1;i<lab.length;i++){if(lab[i].y-lab[i-1].y<13)lab[i].y=lab[i-1].y+13;}
 lab.forEach(function(l){g+='<text x="'+(W-R+6)+'" y="'+(l.y+4)+'" class="cwc-lab" fill="'+l.c+'">'+safe(l.t)+'</text>';});
 g+='<line class="cwc-cross" x1="0" x2="0" y1="'+T+'" y2="'+(H-B)+'" visibility="hidden"/><rect class="cwc-hit" x="'+L+'" y="'+T+'" width="'+(W-L-R)+'" height="'+(H-T-B)+'" fill="transparent"/>';
 box.innerHTML='<svg viewBox="0 0 '+W+' '+H+'" role="img" aria-label="所選期間起的累積變動（bp）">'+g+'</svg>';
 var svg=box.querySelector('svg'),cross=svg.querySelector('.cwc-cross'),out=root.querySelector('.cwc-read');
 function at(i){i=Math.max(0,Math.min(n,i));cross.setAttribute('x1',X(i));cross.setAttribute('x2',X(i));cross.setAttribute('visibility','visible');
  var en=evs.filter(function(e){return e[0]===i;}).map(function(e){return e[1];});
  out.innerHTML='<b>'+C.md2(CD.d[ia+i])+'</b>'+(en.length?'<em class="cwc-evn">'+safe(en.join('、'))+'</em>':'')+'　'+S.map(function(s){var v=s.p[i];return '<span style="color:'+s.c+'">'+safe(s.n)+' '+(v===null?'—':safe(sgn(v,'')))+'</span>';}).join('　')+'　<small>bp，相對 '+C.md2(CD.d[ia])+'</small>';}
 function pos(e){var bb=svg.getBoundingClientRect();return Math.round(((e.clientX-bb.left)/bb.width*W-L)/(W-L-R)*n);}
 svg.addEventListener('pointermove',function(e){at(pos(e));});svg.addEventListener('pointerdown',function(e){at(pos(e));});
 at(n);}
function mk(s){return parseInt(s.slice(0,4),10)*12+parseInt(s.slice(5,7),10)-1+(parseInt(s.slice(8,10),10)-1)/31;}
function bands(a,b){root.querySelectorAll('.cl-plot[data-x0]').forEach(function(p){var x0=+p.dataset.x0,x1=+p.dataset.x1,r=(x1-x0)||1;
 var l=Math.max(0,(mk(a)-x0)/r*100),R=Math.min(100,(mk(b)-x0)/r*100);var e=p.querySelector('.cl-band');
 if(!e){e=document.createElement('span');e.className='cl-band';p.insertBefore(e,p.firstChild);}e.style.left=l+'%';e.style.width=Math.max(0.6,R-l)+'%';});}
var LABEL={'1w':'1 週','1m':'1 個月','3m':'3 個月','ytd':'年初至今','custom':'自訂期間'},curk='1m';
function show(r){cur=r;explain(r);matrix(r,LABEL[curk]);cum(r);bands(r.start,r.end);}
root.querySelectorAll('.cwm-tog .cw-btn').forEach(function(b){b.addEventListener('click',function(){var m=root.querySelector('.cwm');m.dataset.v=b.dataset.v;root.querySelectorAll('.cwm-tog .cw-btn').forEach(function(x){x.classList.toggle('on',x===b);x.setAttribute('aria-pressed',String(x===b));});});});
var _rw=0;window.addEventListener('resize',function(){var w=(root.querySelector('.cwc-plot')||{}).clientWidth||0;if(cur&&Math.abs(w-_rw)>30){_rw=w;cum(cur);}});
root.querySelectorAll('.cwc-mode').forEach(function(b){b.addEventListener('click',function(){mode=b.dataset.m;root.querySelectorAll('.cwc-mode').forEach(function(x){x.classList.toggle('on',x===b);x.setAttribute('aria-pressed',String(x===b));});if(cur)cum(cur);});});
var last=CD.d[CD.d.length-1],fa=root.querySelector('.cw-from'),fb=root.querySelector('.cw-to'),cu=root.querySelector('.cw-cust');
function pick(k){curk=k;root.querySelectorAll('.cw-btn[data-w]').forEach(function(b){b.classList.toggle('on',b.dataset.w===k);});
 if(k==='custom'){cu.hidden=false;if(!fa.value){fa.value=startFor('1m',last);fb.value=last;}show(analysis(fa.value,fb.value));return;}
 cu.hidden=true;show(analysis(startFor(k,last),last));}
root.querySelectorAll('.cw-btn[data-w]').forEach(function(b){b.addEventListener('click',function(){pick(b.dataset.w);});});
[fa,fb].forEach(function(e){e.addEventListener('change',function(){if(fa.value&&fb.value)show(analysis(fa.value<fb.value?fa.value:fb.value,fa.value<fb.value?fb.value:fa.value));});});
pick(root.dataset.w||'1m');
})();
(function(){var b=document.querySelector('.cwb-copy');if(!b)return;b.addEventListener('click',function(){var t=b.dataset.copy||'';
 function done(){var o=b.textContent;b.textContent='已複製';setTimeout(function(){b.textContent=o;},1500);}
 if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t).then(done,function(){fb();});}else fb();
 function fb(){var a=document.createElement('textarea');a.value=t;a.style.position='fixed';a.style.opacity='0';document.body.appendChild(a);a.select();try{document.execCommand('copy');done();}catch(e){}document.body.removeChild(a);}});})();
"""

CW_DEFAULT = "1m"      # 預設期間：最上方週報已是「最近一週」，下面預設看 1 個月才不重複


def curve(d: dict) -> str:
    L = d.get("le") or {}
    cd = L.get("cw") or {}
    if not cd.get("d"):
        return '<div class="empty">資料不足</div>'
    import json as _json
    year = L.get("cw_year") or int(cd["d"][-1][:4])
    last = cd["d"][-1]
    r0 = le.window_analysis(cd, le.cw_start(cd, CW_DEFAULT, last, year), last)
    from .curve_weekly import weekly_chart
    weekly = weekly_chart(cd)
    brief = L.get("brief")
    rows = L.get("spreads") or []
    fwd = L.get("forwards") or []
    rf = L.get("refunding") or {}
    fn = L.get("fomc_next") or ""
    st = le.curve_story(rows, L.get("curve_drivers") or {}, fwd, fomc_next=_md(fn) if fn else "",
                        refunding_next=_md(str(rf.get("next") or "")) if rf.get("next") else "")
    btns = "".join(f'<button type="button" class="cw-btn{" on" if k == CW_DEFAULT else ""}" data-w="{k}">{zh}</button>'
                   for k, zh, _ in le.CW_WINDOWS) + '<button type="button" class="cw-btn" data-w="custom">自訂</button>'
    win_label = {k: zh for k, zh, _ in le.CW_WINDOWS}[CW_DEFAULT]
    first = cd["d"][0] if cd["d"][0] >= f"{year}-01-01" else f"{year - 1}-12-31"
    events = [list(e) for e in (L.get("cw_events") or []) if e and str(e[0]) >= cd["d"][0]]
    data = _json.dumps({**cd, "year": year, "ev": events}, ensure_ascii=False, separators=(",", ":"))
    smalls = "".join(f'<div class="le3-sm"><div class="le3-smh"><b>{esc(x["key"].replace("-", "−"))}</b>'
                     f'<span>{x["value"]:.0f} bp</span></div>{x.get("chart", "")}</div>' for x in rows)
    future = le.future_view(fwd, L.get("match") or d.get("mvd"))
    frows = "".join(
        f'<div class="le3-fr"><span>{esc(x["label"])}</span><b>{x["fwd"]:.2f}%</b>'
        f'<span class="le3-fg {"up" if x["gap_bp"] > 0 else "dn"}">比目前 {esc(x["spot_zh"])} {_sbp(x["gap_bp"])}bp</span>'
        f'<span class="le3-fw">近一月 {_sbp(x.get("mom_bp"))}bp</span>'
        f'<small class="fwd-date">官方資料日 {esc(x.get("date") or "—")}'
        f'{("；月比較 " + esc(x["mom_date"])) if x.get("mom_date") else "；月比較資料不足"}</small>'
        f'<p class="fwd-reading">{("遠期定價高於目前同天期利率。" if x["gap_bp"] > 5 else "遠期定價低於目前同天期利率。" if x["gap_bp"] < -5 else "遠期與目前同天期利率接近。")}</p></div>' for x in fwd)
    policy = future["policy"]
    match_html = '<p class="cw-panel-note">期貨資料不足，暫不判定年底政策利率方向。</p>'
    if policy:
        match_html = (f'<section class="future-policy"><h3>{esc(policy["title"])}</h3><dl class="cw-metrics">'
                      f'<div><dt>現行利率中點</dt><dd><b>{policy["now"]}</b></dd></div>'
                      f'<div><dt>{esc(policy["year"])} 年底期貨隱含</dt><dd><b>{policy["end"]}</b></dd></div>'
                      f'<div><dt>年底相對現在</dt><dd><b>{policy["change"]}</b></dd></div></dl>'
                      f'<p>{esc(policy["text"])}</p></section>')
    mt = L.get("match")
    compare_html = ""
    if mt and mt.get("dot_median") is not None:
        compare_html = (f'<details class="f-more"><summary>與 Fed 點陣圖比較</summary>'
                       f'<p>期貨隱含年底 {mt["market_end"]:.2f}%；點陣圖中位數 {mt["dot_median"]:.2f}%。'
                       f'兩者差距 {_sbp((mt["market_end"]-mt["dot_median"])*100)}bp。</p></details>')
    outl = "".join(f'<li class="{"hot" if o["hot"] else ""}"><b>{esc(o["tag"])}</b>{esc(o["text"])}</li>'
                   for o in st["outlook"])
    modes = "".join(f'<button type="button" class="cw-btn cwc-mode{" on" if m == "ten" else ""}" data-m="{m}" '
                    f'aria-pressed="{"true" if m == "ten" else "false"}">{zh}</button>'
                    for m, zh in (("ten", "2Y／10Y／30Y"), ("sp", "三條利差")))
    return f"""
    {_cw_brief(brief, events)}
    <div class="cw" data-w="{CW_DEFAULT}">
      <div class="cw-ctl" role="group" aria-label="比較期間">{btns}</div>
      <div class="cw-cust" hidden><label>從 <input type="date" class="cw-from" min="{first}" max="{last}"></label>
        <label>到 <input type="date" class="cw-to" min="{first}" max="{last}"></label></div>
      {_cw_matrix(brief, r0, win_label)}
      <div class="tabs cw-tabs">
        <input type="radio" name="cw-tab" id="cw-t1" checked><label for="cw-t1">累積變動</label>
        <input type="radio" name="cw-tab" id="cw-t2"><label for="cw-t2">殖利率水準</label>
        <input type="radio" name="cw-tab" id="cw-t3"><label for="cw-t3">利差水準</label>
        <div class="tabp p1"><div class="cwc"><div class="cw-ctl cwc-modes" role="group" aria-label="累積變動">{modes}</div>
          <div class="cwc-plot"><noscript>需要 JavaScript 才能顯示累積變動圖。</noscript></div>
          <p class="cwc-read" aria-live="polite"></p>
          <details class="cw-note"><summary>圖表說明</summary><p class="cwm-note">所選期間第一天為 0，往後每天相對第一天的變動（bp）。線越往上＝殖利率上升／利差擴大。灰色虛線＝事件日（FOMC、CPI、非農、PCE、公債再融資公告），滑過或點選圖表可看名稱。</p></details></div></div>
        <div class="tabp p2">{L.get("yield_chart", "")}</div>
        <div class="tabp p3"><div class="le3-sms">{smalls}</div><details class="cw-note"><summary>圖表說明</summary><p class="cwm-note">三張小圖各自用貼近資料的刻度，才看得出變化；彼此高度不能直接比較。</p></details></div>
      </div>
      {weekly}
      {_cw_folds(r0)}
      <script type="application/json" id="cw-data">{data}</script>
      <script>{_CW_JS}</script>
    </div>
    <details class="f-more future-section cw-fold"><summary><span class="cw-fold-number">03</span><span class="cw-fold-title"><b>市場怎麼看未來利率</b><span class="cw-fold-reading">{esc(policy["text"] if policy else future["headline"])}</span></span></summary>
      {match_html}
      <section class="future-bonds"><h3>公債遠期定價方向</h3>
        <p class="future-headline">{esc(future["headline"])}</p><p>{esc(future["recent"])}</p>
        <div class="le3-ft" style="margin-top:6px">{frows or '<p>遠期資料不足</p>'}</div>
        <p class="cw-panel-note">各列代表不同的未來區間與期限，不是連續的升降息路徑；遠期值含期限溢酬，不能直接當作 Fed 的未來政策利率。</p>
      </section>{compare_html}</details>
    <details class="f-more"><summary>曲線形狀：現在、1 週前、1 個月前、年初</summary>{L.get('curve_chart', '')}</details>
    <details class="f-more"><summary>接下來看什麼</summary><ul class="le3-ol">{outl}</ul></details>
    <details class="f-more"><summary>方法與限制</summary>
      <div class="f-detail le3-how">
        <p><b>30−2 週報</b>：最新官方收盤比 5 個交易日前（滾動一週），每天都是最新的一週；下方「每週變化」長條圖則固定週五比週五。分段：30−2＝10−2＋30−10，貢獻同方向且較大的那一段標為主要來源。</p>
        <p><b>型態</b>：利差擴大＝變陡、收窄＝變平；看兩端誰動得多決定由哪一端帶動，殖利率上升為熊、下降為牛；兩端反向為扭轉。利差變動 2bp 以內視為持平。</p>
        <p><b>遠期（1 年後、5 年後）</b>：用同一天的官方曲線推算。1 年後的 2Y＝1y2y（1Y、3Y）；10Y、30Y 因沒有 11 年、31 年期，以 1y9y、1y29y 近似。5 年後的 2Y＝5y2y（5Y、7Y）；10Y＝5y10y（15Y 由 10Y、20Y 內插）；30Y 以 5y25y 近似。官方殖利率是平價收益率，結果為近似值；遠期含期限溢酬，是市場已定價的路徑、不是預測。</p>
        <p><b>原因</b>：用市場口徑的損益兩平（T10YIE）與 TIPS 實質利率（DFII10），兩者相加約等於 10 年期；實質利率晚一天公布，拆解用兩端最近都有資料的日子。期限溢酬（Kim-Wright，約晚一週公布）跟實質利率有重疊，當旁證看；起訖退到同一天時顯示「—」。</p>
        <p><b>市場定價的未來</b>：遠期差距及月變動在 ±5bp 內視為接近；年底期貨與現行利率差距在 ±12.5bp 內視為大致持平。</p>
        <p><b>資料口徑</b>：2Y、10Y、30Y 與利差使用美國財政部官方日殖利率，部分資料由 FRED 提供；各天期比較採同一天資料。財政部按約美東 15:30 的指示性買方報價估算固定期限殖利率，與 Bloomberg USGG 指數的 PX_LAST 口徑不同。</p>
        <p><b>自選期間</b>：可查看 2026 年起的資料；遇假日採前一個有資料的日期，監控表欄位標題會標出實際使用的日期。</p>
        <p><b>事件標記</b>：FOMC 用全年會議日；非農、CPI、PCE 用官方發布行事曆（目前自 2026 年 8 月起）；公債再融資公告用財政部公布的日期。只標有出處的日期，不用慣例推估。週報的「主要變化集中在…」挑這一週最大的單日變動（天期或利差，4bp 以上才寫），同一天有上述事件就一併點出。</p>
        <p><b>年內位置</b>：今年 1/1 起各標的的最低與最高，圓點是現在的位置。</p>
      </div>
    </details>"""


# ---------------------------------------------------------------------------
# 全球長端
# ---------------------------------------------------------------------------
def global_(d: dict) -> str:
    g = (d.get("le") or {}).get("global") or {}
    rows = g.get("rows") or []
    if not rows:
        return '<div class="empty">資料不足</div>'
    cards = "".join(f'<div class="le-g"><span>{esc(r["name"])}</span><b>{r["value"]:.2f}%</b>'
                    f'<em>近 12 月 {_bp(r["chg12"])}</em></div>' for r in rows)
    asof = rows[0]["date"][:7].replace("-", "/")
    return f"""
    <p class="hint">期限溢酬如果是全球一起漲，原因多半是全球的財政與供給；只有美國在漲，才是美國自己的問題。</p>
    <div class="le-gs">{cards}</div>
    <div class="viz-block">{g.get('chart', '')}</div>
    <div class="src">OECD 長期利率（10 年期公債月均），經 FRED 取得，資料至 {esc(asof)}。月資料落後約一個月。</div>"""


# ---------------------------------------------------------------------------
# 債券供給：財政部＋Fed
# ---------------------------------------------------------------------------
def supply(d: dict) -> str:
    L = d.get("le") or {}
    rf = L.get("refunding") or {}
    guide = ""
    if rf:
        guide = (f'<div class="le-quote"><div class="le-qh">最新每季再融資（{esc(rf.get("date", ""))}）'
                 + (f'　·　下一次 {esc(rf.get("next", ""))}' if rf.get("next") else "")
                 + f'</div><blockquote>{esc(rf.get("guidance_en", ""))}</blockquote>'
                 f'<p>{esc(rf.get("guidance_zh", ""))}</p>'
                 + (f'<p class="hint">{esc(rf["buybacks_zh"])}</p>' if rf.get("buybacks_zh") else "")
                 + (f'<a href="{esc(rf["url"])}" target="_blank" rel="noopener">財政部原文</a>' if rf.get("url") else "")
                 + '</div>')
    # 七個天期一張表：一列一個天期，右邊是近 8 個月的迷你柱。規模幾乎不動時，
    # 七張大圖只會重複同一件事（先前「畫面很亂」的主因之一）。
    def _mini(pts):
        m = max(p["value"] for p in pts) or 1
        return "".join(f'<i style="height:{p["value"] / m * 100:.0f}%" '
                       f'data-tip="{esc(p["date"][:7].replace("-", "/"))}｜{p["value"] * 10:,.0f} 億美元"></i>'
                       for p in pts)

    def _chg(s):
        if not s.get("year_ago"):
            return "—"
        d = (s["latest"] - s["year_ago"]) * 10
        return "持平" if abs(d) < 0.5 else f"{d:+,.0f} 億"
    sizes = "".join(
        f'<div class="sz-row"><b>{esc(s["zh"])}</b><span class="sz-v">{s["latest"] * 10:,.0f}</span>'
        f'<span class="sz-c">{esc(_chg(s))}</span><span class="sz-m">{_mini(s["pts"])}</span></div>'
        for s in L.get("sizes") or [])
    sizes = (f'<div class="sz-head"><span>天期</span><span>最新一場（億美元）</span><span>對 1 年前</span>'
             f'<span>近 8 個月</span></div>{sizes}') if sizes else ""
    up = [a for a in L.get("upcoming") or [] if not a.get("frn")]
    tz = L.get("tenor_zh") or {}
    upl = "".join(
        f'<div class="le-up"><span class="ev-d">{esc(_md(a["date"]))}</span>'
        f'<b>{esc(tz.get(a["term"], a["term"]))}{" TIPS" if a.get("tips") else ""}</b>'
        f'<span>{"增發舊券" if a.get("reopening") else "新券"}</span>'
        f'<span>{"暫定排程" if a.get("tentative") else _amt(a)}</span></div>'
        for a in up[:14]) or '<div class="hint">目前沒有已公告的 coupon 拍賣</div>'
    # Fed
    fp = L.get("fed_policy") or {}
    sm = L.get("soma") or {}
    mix = ""
    if sm:
        cols = ["var(--line-1)", "#12233B", "#1baf7a", "#eda100", "var(--muted-bar)"]

        def bar(m, lab):
            segs = "".join(f'<span style="flex:{p:.3f};background:{cols[i]}" data-tip="{esc(n)}｜{p:.1f}%（{v:,.0f} 十億美元）">'
                           + (f'{p:.0f}%' if p >= 6 else "") + '</span>'
                           for i, (n, v, p) in enumerate(m))
            return f'<div class="le-mix"><div class="le-mixk">{esc(lab)}</div><div class="le-mixb">{segs}</div></div>'
        leg = "".join(f'<span><i style="background:{cols[i]};width:10px;height:10px"></i>{esc(n)}</span>'
                      for i, (n, _, _) in enumerate(sm["now"]["mix"]))
        mix = (bar(sm["now"]["mix"], f'現在 {_md(sm["now"]["date"])}')
               + bar(sm["ago"]["mix"], f'1 年前 {_md(sm["ago"]["date"])}')
               + f'<div class="cl-leg">{leg}</div>')
    wm = L.get("wam") or {}
    wam_html = ""
    if wm.get("soma", {}).get("value") is not None and wm.get("market", {}).get("value") is not None:
        wam_html = (f'<div class="le-wam"><div><span>Fed 持有公債</span><b>{wm["soma"]["value"]:.1f}<small> 年</small></b>'
                    f'<em>{esc(_md(wm["soma"]["date"]))}</em></div>'
                    f'<div><span>流通在外可交易公債</span><b>{wm["market"]["value"]:.1f}<small> 年</small></b>'
                    f'<em>{esc(wm["market"]["date"][:7].replace("-", "/"))}</em></div></div>'
                    f'{wm.get("chart", "")}')
    return f"""
    <h3 class="le-h3">財政部：coupon 發行路徑</h3>
    {guide}
    <div class="le-sizes">{sizes}</div>
    <details data-m-collapse open><summary>已排程的 coupon 拍賣</summary><div class="le-ups">{upl}</div></details>
    <h3 class="le-h3">Fed：資產端與 WAM</h3>
    {f'<div class="impact neutral">{esc(fp.get("text_zh", ""))}</div>' if fp.get("text_zh") else ''}
    <div class="viz-block"><div class="viz-h">SOMA 組成：現在 vs 1 年前</div>{mix}</div>
    <div class="viz-block"><div class="viz-h">加權平均剩餘年限（WAM）</div>
      <p class="viz-sub">Fed 持有的公債比市場整體長，代表 Fed 縮短 WAM 時，長天期要由私人市場接手的比例會變高。</p>
      {wam_html}</div>
    <div class="viz-block"><div class="viz-h">MBS 到期 → 轉買 T-Bills（月變動）</div>
      {sm.get('flow_chart', '')}</div>
    {teach(
        "財政部接下來要賣多少長債、Fed 手上的公債組成往哪個方向調整。",
        "長端的供給不只看財政部發多少，也看誰在買：Fed 把到期的 MBS 換成 T-Bills、縮短持有年限，等於把長天期的風險留給私人市場。",
        "盯兩件事：再融資聲明是否改掉「維持規模」的指引，以及 Fed 與市場 WAM 的差距是否持續縮小。", learn="fed_bs")}
    <div class="src">拍賣規模與已公告拍賣：財政部 Fiscal Data（auctions_query）＋暫定拍賣排程　·　SOMA：紐約聯儲　·　流通在外明細：財政部 MSPD（每月）。
      WAM 由逐券到期日與面額自行計算（不含 MBS）。</div>"""


# ---------------------------------------------------------------------------
# Coupon 拍賣結果
# ---------------------------------------------------------------------------
def auctions(d: dict) -> str:
    L = d.get("le") or {}
    rows = L.get("auctions") or []
    if not rows:
        return '<div class="empty">拍賣資料本次取得失敗</div>'
    tz = L.get("tenor_zh") or {}
    rc, n = L.get("auction_recent") or {}, L.get("auction_recent_n") or 0
    head = (f'<div class="impact neutral">近 3 週 {n} 場名目 coupon 拍賣：偏弱 {rc.get("偏弱", 0)}、'
            f'中性 {rc.get("中性", 0)}、偏強 {rc.get("偏強", 0)}。</div>') if n else ""
    cards = []
    for r in rows:
        v = r["verdict"]
        cls = {"偏弱": "weak", "偏強": "strong"}.get(v, "mid")
        tail = r.get("tail_bp")
        btc, ab = r.get("btc"), r.get("avg_btc")
        bpos = None
        if btc is not None and ab is not None:
            bpos = max(0, min(100, 50 + (btc - ab) / 0.5 * 50))
        comp = (f'<div class="au-mix"><span style="flex:{r.get("indirect_pct", 0):.1f};background:var(--line-1)" '
                f'data-tip="Indirect（海外與機構）｜{r.get("indirect_pct", 0):.1f}%"></span>'
                f'<span style="flex:{r.get("direct_pct", 0):.1f};background:#1baf7a" '
                f'data-tip="Direct（國內投資人）｜{r.get("direct_pct", 0):.1f}%"></span>'
                f'<span style="flex:{r.get("dealer_pct", 0):.1f};background:var(--muted-bar)" '
                f'data-tip="Primary Dealers｜{r.get("dealer_pct", 0):.1f}%"></span></div>')
        cards.append(f"""<div class="au {cls}">
  <div class="au-h"><b>{esc(tz.get(r['term'], r['term']))}</b><span>{esc(_md(r['date']))}{'　增發' if r.get('reopening') else ''}</span>
    <span class="au-v">{esc(v)}</span></div>
  <div class="au-y">{r['high']:.3f}%<small>得標</small></div>
  <div class="au-kv"><span>Tail≈</span><b class="{'up' if (tail or 0) > 0 else 'dn'}">{_bp(tail, 1)}</b></div>
  <div class="au-kv"><span>投標倍數</span><b>{btc:.2f}</b><em>近 6 場 {ab:.2f}</em></div>
  {f'<div class="au-gauge"><i style="left:{bpos:.0f}%"></i></div>' if bpos is not None else ''}
  <div class="au-kv"><span>交易商承接</span><b>{r.get('dealer_pct', 0):.1f}%</b><em>近 6 場 {(r.get('avg_dealer') or 0):.1f}%</em></div>
  <div class="au-kv"><span>分散度</span><b>{_bp(r.get('disp_bp'), 1)}</b><em>得標 − 中位</em></div>
  {comp}
</div>""")
    leg = ('<div class="cl-leg"><span><i style="width:10px;height:10px;background:var(--line-1)"></i>Indirect（海外與機構）</span>'
           '<span><i style="width:10px;height:10px;background:#1baf7a"></i>Direct（國內投資人）</span>'
           '<span><i style="width:10px;height:10px;background:var(--muted-bar)"></i>Primary Dealers（承接剩下的）</span></div>')
    return f"""
    {head}
    <div class="aus">{''.join(cards)}</div>
    {leg}
    {teach(
        "財政部每一場長債拍賣的需求強弱：誰買了、買得多踴躍、交易商被迫接了多少。",
        "供給要有人吃得下。需求弱的拍賣會讓得標殖利率高於市場價（tail），交易商被迫承接更多，長端就得再往上找買盤。",
        "看三件事：Tail≈ 是正還是負、投標倍數比近 6 場高還是低、交易商承接比例是否偏高。連續幾場偏弱才是訊號。", learn="auctions")}
    <details data-m-collapse><summary>判定規則與 tail 的近似</summary>
      <p class="hint" style="margin-top:10px">{esc(L.get('auction_rule', ''))}</p>
      <p class="hint">Tail 標準算法是得標殖利率減拍賣截止（下午 1 點）當下的 when-issued 殖利率，那是付費報價。
        這裡用<b>當日收盤</b>的固定期限殖利率近似，會混進 1 點之後的市場波動，所以標「≈」，只看方向與大小級距。
        「分散度」是得標殖利率減中位得標殖利率，不需要 when-issued，越大代表投標越分歧。</p>
    </details>
    <div class="src">財政部 Fiscal Data 拍賣結果（auctions_query）。比例的分母是競標得標量。</div>"""


# ---------------------------------------------------------------------------
# 財政部買回（Buybacks）
# ---------------------------------------------------------------------------
def _yi_b(v, sign=False) -> str:
    """十億美元 → 億美元。"""
    if v is None:
        return "—"
    nd = 0 if abs(v * 10 - round(v * 10)) < 0.05 else 1      # TIPS 7.5 億這種要留小數
    return f"{v * 10:+,.{nd}f}" if sign else f"{v * 10:,.{nd}f}"


def _rx(r: dict) -> str:
    vals = [r.get(k) for k in ("10Y", "20Y", "30Y")]
    if all(v is None for v in vals):
        return '<span class="muted">—</span>'
    return "／".join(f'<b class="{"up" if (v or 0) > 0 else "dn" if (v or 0) < 0 else ""}">'
                     f'{"—" if v is None else f"{v:+.1f}"}</b>' for v in vals)


def buyback_summary(d: dict) -> str:
    b = (d.get("le") or {}).get("buybacks") or {}
    x = b.get("latest")
    if not x:
        return "財政部買回"
    return (f'{_md(x["date"])} {x["bucket_zh"]}：買回 {_yi_b(x["accepted"])} 億／上限 {_yi_b(x["max"])} 億')


def buybacks(d: dict) -> str:
    b = (d.get("le") or {}).get("buybacks") or {}
    rows = b.get("rows") or []
    if not rows:
        return '<div class="empty">買回資料本次取得失敗</div>'
    x = b["latest"]
    q = b.get("quarter") or {}
    stats = (
        f'<div class="stat-row">'
        f'<div class="stat"><div class="s-label">最新一場　{esc(_md(x["date"]))} {esc(x["bucket_zh"])}</div>'
        f'<div class="s-value">{_yi_b(x["accepted"])}<small> 億美元</small></div>'
        f'<div class="s-note">上限 {_yi_b(x["max"])} 億　·　{esc(x["type_zh"])}</div></div>'
        f'<div class="stat"><div class="s-label">投標 ÷ 上限</div>'
        f'<div class="s-value">{(x["cover"] or 0):.1f}<small> 倍</small></div>'
        f'<div class="s-note">投標 {_yi_b(x["offered"])} 億</div></div>'
        f'<div class="stat"><div class="s-label">本季累計（{esc(_md(b.get("quarter_from", "")))} 起）</div>'
        f'<div class="s-value">{_yi_b(sum(q.values()))}<small> 億美元</small></div>'
        f'<div class="s-note">' + "　".join(f'{esc(k)} {_yi_b(v)} 億' for k, v in q.items()) + '</div></div>'
        f'</div>')
    caps = "".join(f'<span class="bb-cap"><b>{esc(c["bucket_zh"])}'
                   f'{"" if c["type_zh"] == "流動性支援" else "（" + c["type_zh"] + "）"}</b>{_yi_b(c["max"])} 億</span>'
                   for c in b.get("caps") or [])
    how = f"""<dl class="gloss">
      <dt>操作天期</dt><dd>流動性支援：名目 coupon 依剩餘年限分段輪流買回（1 個月–2 年、2–3、3–5、5–7、7–10、10–20、20–30 年）與 TIPS 兩段；
        現金管理：1 個月–2 年，集中在 4、6、9、12 月稅收日前後。</dd>
      <dt>每場上限</dt><dd><div class="bb-caps">{caps}</div>
        2026-08-19 宣布：9/9 起到 11/4 本季結束，10–20 年與 20–30 年的每場上限由 20 億提高到至少 40 億（實際操作為 60 億）。</dd>
      <dt>執行方式</dt><dd>反向拍賣：操作前一個營業日 11:00（美東）初步公告上限與合格券，當日 11:00 最終公告；
        13:40–14:00 接受一級交易商報價（每 100 美元面額的價格），多重價格得標，截止後公布結果；T+1 交割，買回的券直接註銷。</dd>
      <dt>融資來源</dt><dd>財政部的現金與新發行公債（31 U.S.C. §3111）。QRA 原文：「buybacks are not expected to significantly
        affect privately-held net marketable borrowing as new issuance replaces securities that are bought back」——買回多少就多發多少，
        實務上由 T-Bills 補上，所以買回是把長天期舊券換成短天期 bill，不改變總借款。</dd>
    </dl>"""
    trs = "".join(
        f'<tr><td>{esc(_md(r["date"]))}</td><td>{esc(r["bucket_zh"])}</td><td>{esc(r["type_zh"])}</td>'
        f'<td>{_yi_b(r["max"])}</td><td><b>{_yi_b(r["accepted"])}</b></td><td>{_yi_b(r["offered"])}</td>'
        f'<td class="bb-rx">{_rx(r["announce"])}</td><td class="bb-rx">{_rx(r["result"])}</td></tr>'
        for r in rows)
    table = (f'<div class="tscroll"><table class="bb-tb"><thead><tr><th>操作日</th><th>天期</th><th>類型</th>'
             f'<th>上限</th><th>實際買回</th><th>投標</th><th>上限公布後 1 小時<br><small>10／20／30 年，bp</small></th>'
             f'<th>結果公布後 1 小時<br><small>10／20／30 年，bp</small></th></tr></thead><tbody>{trs}</tbody></table></div>')
    up = b.get("upcoming") or []
    ups = "".join(
        f'<tr><td>{esc(_md(u["date"]))}</td><td>{esc(_md(u["announce"]))}</td><td>{esc(u["bucket_zh"])}</td>'
        f'<td>{esc(u["type_zh"])}</td><td>{_yi_b(u["max"])}'
        + (f'<small class="muted">（近期實際 {_yi_b(u["recent_max"])}）</small>' if u.get("recent_max") else "")
        + '</td></tr>' for u in up)
    up_html = (f'<div class="tscroll"><table class="bb-tb"><thead><tr><th>操作日</th><th>上限公布</th><th>天期</th>'
               f'<th>類型</th><th>排程上限</th></tr></thead><tbody>{ups}</tbody></table></div>'
               if ups else '<p class="hint">本季暫定排程已全部執行完畢，下一季排程隨再融資公布。</p>')
    return f"""
    <p class="hint">買回流動性較差的舊券、用新發行補上——長端供給的減法。</p>
    {stats}
    {how}
    <div class="viz-block"><div class="viz-h">歷次買回結果（億美元）與殖利率反應</div>{table}</div>
    <details data-m-collapse open><summary>未來排程（{esc(b.get("schedule_name") or "暫定買回排程")}）</summary>
      {up_html}</details>
    <details data-m-collapse><summary>殖利率反應怎麼量</summary>
      <p class="hint" style="margin-top:10px">上限公布：初步公告時間（操作前一個營業日 11:00 美東）前最後一根 5 分鐘 K 棒收盤 →
        公告後 60 分鐘那根的收盤。結果公布：操作截止 14:00 → 15:00，結果在截止後幾分鐘內公布，落在這個窗口裡。
        正值＝殖利率上升（價格下跌）。同一小時內也可能有其他消息（經濟數據、拍賣、Fed 官員談話），
        單一場的變化不能全部歸因於買回；要看的是同一類操作反覆出現的方向。</p>
    </details>
    <div class="src">財政部 Fiscal Data、TreasuryDirect 公告 XML、暫定買回排程；盤中殖利率：CNBC 5 分 K。</div>"""


# ---------------------------------------------------------------------------
# 信用利差
# ---------------------------------------------------------------------------
def credit(d: dict) -> str:
    c = (d.get("le") or {}).get("credit") or {}
    return f"""
    <p class="hint">供給增加不必然推高利率——信用利差是買方的溫度計。</p>
    <div class="stat-row">{_stats(d.get('credit_stats') or [])}</div>
    <div class="cl-pair viz-block">
      <div><div class="viz-h">投資級（IG）</div>{c.get('ig', '')}</div>
      <div><div class="viz-h">高收益（HY）</div>{c.get('hy', '')}</div>
    </div>
    <div class="src">ICE BofA 指數的選擇權調整利差（OAS），經 FRED 取得。兩者尺度差很多，所以分兩張圖。</div>"""


def _stats(items) -> str:
    from .labor import _stats as s
    return s(items)


# ---------------------------------------------------------------------------
# 科技巨頭：逐季小圖
# ---------------------------------------------------------------------------
def hs_quarters(d: dict) -> str:
    hh = (d.get("le") or {}).get("hs_hist") or []
    if not hh:
        return ""
    cards = []
    for h in hh:
        r = [x for x in h["ratio"] if x["v"] is not None]
        ratio = (f'<div class="le-hsr">最新一季資本支出佔營運現金流 <b class="{"up" if r[-1]["v"] > 100 else ""}">'
                 f'{r[-1]["v"]:.0f}%</b></div>') if r else ""
        deb = [x for x in h["ratio"] if x["debt"]]
        dtxt = ("、".join(f'{_md(x["end"])} {x["debt"] * 10:,.0f} 億' for x in deb[-3:])
                if deb else "近 8 季沒有申報長期債務發行")
        cards.append(f'<div class="le-hs"><div class="viz-h">{esc(h["name"])}</div>{ratio}{h["capex"]}'
                     f'<div class="le-hsd">發債：{esc(dtxt)}</div></div>')
    return f'<div class="le-hss">{"".join(cards)}</div>'


def guidance_stale(d: dict) -> str:
    """財報已經更新、但資本支出指引還停在上一季 → 黃色提醒。"""
    gd = d.get("guidance") or {}
    hs = d.get("hyperscalers")
    asof = gd.get("as_of") or ""
    ends = [c.get("period_end") for c in (getattr(hs, "companies", None) or []) if c.get("period_end")]
    if not asof or not ends:
        return ""
    late = max(ends)
    if late > asof:
        # 給讀者看的版本：不提設定檔（維護提醒寫在執行紀錄）
        log.warning("資本支出指引待更新：財報期末 %s、指引 %s（config/rates.yaml capex_guidance）", late, asof)
        return (f'<div class="warnbox" style="margin-top:12px"><b>計畫可能已過時</b>　'
                f'年度計畫是 {esc(_md(asof))} 的版本，財報已更新到 {esc(_md(late))}。</div>')
    return ""


# ---------------------------------------------------------------------------
# 指標檢核：依三股力量分組
# ---------------------------------------------------------------------------
GROUPS = [("tp", "財政與供給壓力", ("term_premium", "curve_30_10", "interest_to_revenue", "r_minus_g")),
          ("real", "政策壓力", ("real_10y", "curve_10_2")),
          ("infl", "通膨壓力", ("breakeven_10y",)),
          ("demand", "需求", ("ig_spread",))]


def lights_grouped(d: dict, card_fn) -> str:
    L = d.get("le") or {}
    c1 = (L.get("contrib") or {}).get(1)
    main = c1["main"] if c1 else None
    by = {l.key: l for l in d.get("lights") or []}
    order = sorted(GROUPS, key=lambda g: 0 if g[0] == main else 1)
    out = []
    for key, name, keys in order:
        ls = [by[k] for k in keys if k in by]
        if not ls:
            continue
        badge = '<span class="le-badge">本月主因</span>' if key == main else ""
        out.append(f'<div class="le-lg" style="--k:{len(ls)}"><div class="sig-tier">{esc(name)}{badge}</div>'
                   f'<div class="le-lgc">{"".join(card_fn(l) for l in ls)}</div></div>')
    return f'<div class="le-lgs">{"".join(out)}</div>'



# ---------------------------------------------------------------------------
# 科技巨頭（2026-10 第三版）：三個數字＋一張加總圖＋一家一列的公司表
# ---------------------------------------------------------------------------
def hs_agg_chart(d: dict) -> str:
    """五家加總：每季資本支出（柱）對營運現金流（橫線），同一個軸。"""
    agg = (d.get("le") or {}).get("hs_agg") or []
    if len(agg) < 2:
        return ""
    top = max(max(a["capex"], a["ocf"]) for a in agg) * 1.08
    cols = []
    for i, a in enumerate(agg):
        last = i == len(agg) - 1
        over = a["capex"] >= a["ocf"]
        cols.append(
            f'<div class="hs3-c{" on" if last else ""}" data-tip="{esc(a["label"])}｜資本支出 {a["capex"]:,.0f}｜'
            f'營運現金流 {a["ocf"]:,.0f}｜{a["capex"] / a["ocf"] * 100:.0f}%">'
            f'<span class="hs3-b{" over" if over else ""}" style="height:{a["capex"] / top * 100:.1f}%">'
            + '</span>'
            f'<span class="hs3-o" style="bottom:{a["ocf"] / top * 100:.1f}%">'
            + '</span>'
            f'<span class="hs3-x">{esc(a["label"])}</span></div>')
    la = agg[-1]
    latest = (f'<div class="hs3-last">最新一季（{esc(la["label"])}）：資本支出 <b>{la["capex"]:,.0f}</b>'
              f'　營運現金流 <b>{la["ocf"]:,.0f}</b>　佔 <b class="{"over" if la["capex"] > la["ocf"] else ""}">'
              f'{la["capex"] / la["ocf"] * 100:.0f}%</b></div>')
    return ('<div class="hs3-chart"><div class="hs3-ch">五家加總・每季（億美元）</div>' + latest +
            f'<div class="hs3-p">{"".join(cols)}</div>'
            '<div class="cl-leg"><span><i class="hs3-lg-b"></i>資本支出</span>'
            '<span><i class="hs3-lg-o"></i>營運現金流</span></div>'
            '<p class="hs3-note">柱子高過橫線＝現金不夠付資本支出，缺口靠發債。</p></div>')


def hs_table(d: dict) -> str:
    """一家一列：本季資本支出、年增、佔營運現金流（小橫條）、單季發債、年度指引；點一列看 8 季。"""
    hs = d.get("hyperscalers")
    comps = getattr(hs, "companies", None) or []
    if not comps:
        return ""
    gd = d.get("guidance") or {}
    guide = {r["name"]: r["value"].replace(" 億美元", "") for r in gd.get("rows") or []}
    hist = {h["name"]: h for h in (d.get("le") or {}).get("hs_hist") or []}
    rows = []
    for c in comps:
        ratio = c.get("capex_to_ocf")
        yoy = "—" if c.get("capex_yoy") is None else f'{c["capex_yoy"]:+.0f}%'
        pe = c.get("period_end") or ""
        when = esc(pe) if pe else "未取自 SEC"
        bar = ""
        if ratio is not None:
            bar = (f'<span class="hs3-rb"><i class="{"over" if ratio > 100 else ""}" '
                   f'style="width:{min(ratio, 150) / 150 * 100:.1f}%"></i><u></u></span>')
        g = guide.get(c["name"]) or ("未提供" if gd.get("available") else "—")
        h = hist.get(c["name"])
        deb = [x for x in (h or {}).get("ratio", []) if x["debt"]]
        dtxt = ("、".join(f'{_md(x["end"])} {x["debt"] * 10:,.0f} 億' for x in deb[-4:])
                if deb else "近 8 季沒有申報長期債務發行")
        body = ((h["capex"] if h else "") + f'<p class="hs3-deb">發債紀錄：{esc(dtxt)}</p>')
        rows.append(
            f'<details class="hs3-r"><summary>'
            f'<span class="hs3-n"><b>{esc(c["name"])}</b><small>{when}</small></span>'
            f'<span class="hs3-v"><em>本季資本支出</em>{c["capex"] * 10:,.0f}</span>'
            f'<span class="hs3-v"><em>年增</em>{yoy}</span>'
            f'<span class="hs3-v hs3-ratio"><em>佔營運現金流</em>'
            + (f'<b class="{"over" if ratio > 100 else ""}">{ratio:.0f}%</b>' if ratio is not None else "—")
            + f'{bar}</span><i class="hs3-br"></i>'
            f'<span class="hs3-v"><em>單季發債</em>{c["issued"] * 10:,.0f}</span>'
            f'<span class="hs3-v"><em>{esc(str(gd.get("year", "")))} 年計畫</em>{esc(g)}</span>'
            f'</summary><div class="hs3-body">{body}</div></details>')
    head = ('<div class="hs3-hd"><span>公司</span><span>本季資本支出</span><span>年增</span>'
            '<span>佔營運現金流</span><span>單季發債</span>'
            f'<span>{esc(str(gd.get("year", "")))} 年資本支出計畫</span></div>')
    return (f'<div class="hs3-t">{head}{"".join(rows)}</div>'
            '<p class="hs3-note">億美元・點一家看近 8 季・超過 100% 標紅</p>')
