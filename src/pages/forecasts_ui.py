"""
總覽「04 各家預測」的畫面（2026-10）。資料與計分在 analysis/forecasts.py。

  分頁：就業報告｜CPI｜PCE（純 CSS radio）
  表格：機構放列（BofA、Citi、JPM、MS、GS、市場共識、Cleveland Fed、實際值）、指標放欄
        沒有的數字一律「無資料」；公布後最接近的標 ★
        下方兩列：預估區間（分歧度）、對共識（實際值高於／低於共識，超出所有預測另外標）
  點格子：表格下方顯示那個數字的出處（哪裡來、什麼時候抓的）
  誰最準：收合；就業與通膨分開排，市場共識與 Cleveland Fed 一起排當基準
"""
from __future__ import annotations

import datetime as dt

from ..analysis import forecasts as F

CSS = r"""
.fc-in{position:absolute;opacity:0;pointer-events:none}
.fc-tabs{display:flex;gap:0;margin:0 0 12px;border-bottom:1px solid var(--grid)}
.fc-tabs label{cursor:pointer;padding:8px 14px;font-size:var(--fs-small);font-weight:700;color:var(--muted);border-bottom:2px solid transparent;margin-bottom:-1px}
#fc-t-employment:checked~.fc-tabs label[for=fc-t-employment],#fc-t-cpi:checked~.fc-tabs label[for=fc-t-cpi],
#fc-t-pce:checked~.fc-tabs label[for=fc-t-pce]{color:var(--brand-ink);border-bottom-color:var(--brand-orange)}
.fc-p{display:none}
#fc-t-employment:checked~.fc-ps .fc-p-employment,#fc-t-cpi:checked~.fc-ps .fc-p-cpi,#fc-t-pce:checked~.fc-ps .fc-p-pce{display:block}
.fc-h{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin:0 0 8px}
.fc-h b{font-size:17px;font-weight:800;color:var(--brand-ink)}
.fc-st{font-size:12px;font-weight:700;border-radius:999px;padding:2px 10px;border:1px solid var(--border);color:var(--text-secondary)}
.fc-st.up{color:#fff;background:var(--brand-orange);border-color:var(--brand-orange)}
.fc-st.done{color:var(--brand-ink);border-color:var(--brand-navy)}
.fc-tw{overflow-x:auto;-webkit-overflow-scrolling:touch;overscroll-behavior-x:contain}
.fc-tb{width:100%;border-collapse:separate;border-spacing:0;font-variant-numeric:tabular-nums}
.fc-tb th,.fc-tb td{padding:0;border-bottom:1px solid var(--grid);text-align:right;font-size:13.5px;white-space:nowrap}
.fc-tb thead th{font-size:12px;font-weight:700;color:var(--muted);padding:6px 6px 7px;vertical-align:bottom}
.fc-tb tbody th,.fc-tb tfoot th{text-align:left;font-weight:700;padding:8px 6px 8px 2px;color:var(--text-primary);font-family:"Montserrat",system-ui,sans-serif;font-size:13px;white-space:normal;line-height:1.2;width:84px}
/* 第一欄（機構）固定在左邊，表格左右滑時不會被捲走 */
.fc-tb th:first-child{position:sticky;left:0;z-index:1;background:var(--surface-1)}
.fc-tb tr.fc-base th:first-child{background:var(--surface-2)}
.fc-tb tr.fc-act th:first-child{background:#fbeee8}
:root[data-theme=dark] .fc-tb tr.fc-act th:first-child{background:#3a2a26}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]) .fc-tb tr.fc-act th:first-child{background:#3a2a26}}
.fc-tb tbody tr.fc-base th{font-family:inherit}
.fc-tb tbody tr.fc-base{background:var(--surface-2)}
.fc-tb tbody tr.fc-act{background:rgba(230,113,67,.08)}
.fc-tb tbody tr.fc-act th,.fc-tb tbody tr.fc-act .fc-c{font-weight:800;color:var(--brand-ink)}
.fc-c{all:unset;box-sizing:border-box;display:block;width:100%;padding:8px 6px;cursor:pointer;text-align:right;border-radius:4px}
.fc-c:hover,.fc-c.on{background:var(--surface-2);box-shadow:inset 0 0 0 1px var(--border)}
.fc-c:focus-visible{outline:2px solid var(--brand-orange)}
.fc-na{color:var(--faint,var(--muted));font-size:12px}
.fc-star{font-style:normal;color:var(--brand-orange);margin-right:3px}
.fc-tb tfoot th,.fc-tb tfoot td{font-size:12px;color:var(--text-secondary);padding:7px 6px;font-weight:600;border-bottom:0}
.fc-tb tfoot th{font-family:inherit}
.fc-sp{color:var(--muted)}
.fc-hot{color:var(--critical)}.fc-cool{color:var(--good)}
.fc-out{display:inline-block;margin-top:3px;font-size:10.5px;font-weight:800;color:#fff;background:var(--brand-orange);border-radius:4px;padding:0 5px}
.fc-src{margin:8px 0 0;font-size:12.5px;color:var(--text-secondary);min-height:1.5em}
.fc-src b{color:var(--brand-ink)}
.fc-lb table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums;margin-top:6px}
.fc-lb th,.fc-lb td{padding:6px;border-bottom:1px solid var(--grid);text-align:right;white-space:nowrap}
.fc-lb th:nth-child(2),.fc-lb td:nth-child(2){text-align:left}
.fc-lb thead th{font-size:12px;color:var(--muted);font-weight:700}
.fc-lb td:nth-child(2){font-weight:700}
.fc-lb .fc-base td{background:var(--surface-2)}
.fc-lb .fc-n{font-size:12px;color:var(--muted);margin:6px 0 0}
.fc-empty{font-size:13.5px;color:var(--muted);margin:6px 0}
@media(max-width:480px){.fc-tb th,.fc-tb td{font-size:12.5px}.fc-c{padding:8px 4px}.fc-tb thead th{padding:6px 4px;font-size:11px;letter-spacing:-.01em}.fc-tb tbody th,.fc-tb tfoot th{width:70px;font-size:12px}.fc-na{font-size:11px}.fc-tb tfoot td{font-size:11px;padding:7px 4px;white-space:normal}}
"""

JS = r"""<script>(function(){var root=document.querySelector('.fc');if(!root)return;
root.addEventListener('click',function(e){var c=e.target.closest('.fc-c');if(!c)return;var p=c.closest('.fc-p');
 Array.prototype.forEach.call(p.querySelectorAll('.fc-c.on'),function(x){x.classList.remove('on');});c.classList.add('on');
 var o=p.querySelector('.fc-src');if(!o)return;o.textContent='';var b=document.createElement('b');b.textContent=c.getAttribute('data-who')||'';o.appendChild(b);
 o.appendChild(document.createTextNode('　'+(c.getAttribute('data-s')||'')));var u=c.getAttribute('data-u');
 if(u){o.appendChild(document.createTextNode('　'));var a=document.createElement('a');a.href=u;a.rel='noopener';a.target='_blank';a.textContent='原文';o.appendChild(a);}});})();</script>"""


def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def _md(iso: str) -> str:
    try:
        d = dt.date.fromisoformat(iso[:10])
        return f"{d.month}/{d.day}（{'一二三四五六日'[d.weekday()]}）"
    except ValueError:
        return iso


def _hm(iso: str) -> str:
    try:
        t = dt.datetime.fromisoformat(iso)
        return f"{t.month}/{t.day} {t:%H:%M}"
    except (TypeError, ValueError):
        return ""


def _nd(v: float, default: int = 1) -> int:
    return default if abs(v * 10 - round(v * 10)) < 1e-9 else 2


def _cell(k, v, who, src, url="", star=False, nd=None) -> str:
    if v is None:
        return f'<td><button type="button" class="fc-c" data-who="{_esc(who)}" data-s="這一期沒有取得這個數字"><span class="fc-na">無資料</span></button></td>'
    txt = F.fmt(k, v, nd if nd is not None else _nd(v))
    return (f'<td><button type="button" class="fc-c" data-who="{_esc(who)}" data-s="{_esc(src)}"'
            + (f' data-u="{_esc(url)}"' if url else "") + '>'
            + ('<i class="fc-star" aria-label="最接近">★</i>' if star else "") + f'{_esc(txt)}</button></td>')


def _period_label(key: str, per: str) -> str:
    try:
        return f"{int(per[5:7])} 月{F.RELEASES[key] if key != 'employment' else '就業報告'}"
    except ValueError:
        return F.RELEASES[key]


def _release_time(key: str, iso: str) -> str:
    try:
        from ..analysis import watch_calendar as wc
        t = wc.taipei_time(dt.date.fromisoformat(iso), wc.EVENTS[key][2])
        return f"{t.month}/{t.day}（{'一二三四五六日'[t.weekday()]}）{t:%H:%M}"
    except Exception:                              # noqa: BLE001
        return _md(iso)


def _released(key: str, iso: str) -> bool:
    """公布時刻（台灣時間）已經過了沒有。"""
    from .. import clock
    try:
        from ..analysis import watch_calendar as wc
        return clock.now() >= wc.taipei_time(dt.date.fromisoformat(iso), wc.EVENTS[key][2])
    except Exception:                              # noqa: BLE001
        return iso <= clock.today().isoformat()


def _panel(key: str, e: dict | None, rel: dict, today: dt.date) -> str:
    inds = F.INDICATORS[key]
    if not e:
        return (f'<div class="fc-p fc-p-{key}"><p class="fc-empty">下一期{F.RELEASES[key]}公布前一週開始收集各家預測。</p>'
                + _board(rel, key) + '</div>')
    act = e.get("actual") or {}
    sc = F.score(e) if act else {}
    fc = F.forecasters(e)
    released = _released(key, e.get("date", ""))
    if act:
        st = '<span class="fc-st done">已公布</span>'
    elif released:
        st = '<span class="fc-st">已公布・等待本站資料更新</span>'
    else:
        st = f'<span class="fc-st up">即將公布・{_esc(_release_time(key, e.get("date", "")))}</span>'
    head = "".join(f'<th scope="col">{_esc(lab)}</th>' for _, lab, _, _ in inds)
    rows = ""
    for name in list(F.BANKS) + [F.CONS, F.CLEV]:
        vals = fc.get(name) or {}
        if name in F.BANKS:
            url = ((e.get("banks") or {}).get(name) or {}).get("src", "")
            src = "手動輸入" + ("・點「原文」看出處" if url else "（未附出處）")
        elif name == F.CONS:
            url, src = "", f"ForexFactory 市場共識・擷取 {_hm(e.get('cons_at', ''))}（公布前最後一版）"
        else:
            url = "https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting"
            src = (f"Inflation Nowcasting・{e.get('clev_asof', '')} 更新" if key in F.CLEV_MAP
                   else "Cleveland Fed 不預測就業數據")
        meta = ((e.get("banks") or {}).get(name) or {}).get("meta") or {} if name in F.BANKS else {}

        def _src(k, src=src, url=url, meta=meta):
            m = meta.get(k)
            if not m:
                return src, url
            if m.get("via") == "auto" and m.get("kind") == "image":
                return (f"自動讀圖・{m.get('name', '')}・{_hm(m.get('at', ''))}　{m.get('q', '')}"), m.get("src", "")
            if m.get("via") == "auto":
                q = m.get("q", "")
                return (f"自動擷取・{m.get('name', '')}・{_hm(m.get('at', ''))}"
                        + (f"　原文：「{q}」" if q else "")), m.get("src", "")
            return "手動輸入" + ("・點「原文」看出處" if m.get("src") else "（未附出處）"), m.get("src", "")
        cells = "".join(_cell(k, vals.get(k), f"{name}・{lab}", *_src(k),
                              star=bool(sc.get(k) and name in sc[k]["best"]),
                              nd=2 if name == F.CLEV and k != "nfp" else None)
                        for k, lab, _, _ in inds)
        cls = ' class="fc-base"' if name in (F.CONS, F.CLEV) else ""
        rows += f'<tr{cls}><th scope="row">{_esc(name)}</th>{cells}</tr>'
    a_cells = "".join(_cell(k, act.get(k), f"實際值・{lab}", "首次公布值（之後的修正不計入排名）・BLS／BEA 經 FRED")
                      if act.get(k) is not None else
                      f'<td><button type="button" class="fc-c" data-who="實際值・{_esc(lab)}" data-s="還沒公布">—</button></td>'
                      for k, lab, _, _ in inds)
    rows += f'<tr class="fc-act"><th scope="row">實際值</th>{a_cells}</tr>'
    # 預估區間（分歧度）與對共識
    sp, sur = "", ""
    for k, _, _, _ in inds:
        # 區間用各家原本寫的數字（不先四捨五入，0.18 與 0.24 才看得出分歧）
        vs = [v[k] for n, v in fc.items() if v.get(k) is not None]
        if len(vs) >= 2:
            lo, hi = min(vs), max(vs)
            sp += f'<td class="fc-sp">{_esc(F.fmt(k, lo, _nd(lo)))}～{_esc(F.fmt(k, hi, _nd(hi)))}</td>' if lo != hi else \
                f'<td class="fc-sp">一致 {_esc(F.fmt(k, lo, _nd(lo)))}</td>'
        else:
            sp += '<td class="fc-sp">—</td>'
        a, c = act.get(k), fc[F.CONS].get(k)
        if a is None or c is None:
            sur += "<td>—</td>"
            continue
        d = a - F.round_half(c, F.decimals(k))
        if abs(d) < 1e-9:
            txt, cls = "符合", ""
        else:
            hot = (d > 0) != (F.HOT.get(k) == "dovish")
            cls = "fc-hot" if hot else "fc-cool"
            txt = ("高於 " if d > 0 else "低於 ") + (f"{d / 10:+.1f} 萬" if k == "nfp" else f"{d:+.1f}")
        out = ""
        if vs and (a < min(vs) - 1e-9 or a > max(vs) + 1e-9):
            out = '<br><span class="fc-out">超出所有預測</span>'
        sur += f'<td class="{cls}">{_esc(txt)}{out}</td>'
    foot = f'<tr><th scope="row">預估區間</th>{sp}</tr>' + (f'<tr><th scope="row">對共識</th>{sur}</tr>' if act else "")
    bad = (f'<p class="fc-n">設定檔有 {len(e["bad"])} 個數字跟市場共識差太多，判定打錯、未採用。</p>'
           if e.get("bad") else "")
    return (f'<div class="fc-p fc-p-{key}"><div class="fc-h"><b>{_esc(_period_label(key, e.get("period", "")))}</b>{st}</div>'
            f'<div class="fc-tw"><table class="fc-tb"><thead><tr><th></th>{head}</tr></thead>'
            f'<tbody>{rows}</tbody><tfoot>{foot}</tfoot></table></div>'
            '<p class="fc-src" aria-live="polite">點任一格看數字的出處；★＝最接近實際值。</p>'
            + bad + _board(rel, key) + '</div>')


def _board(rel: dict, key: str) -> str:
    grp = F.GROUP[key]
    lb = F.leaderboard(rel, grp)
    gname = "就業" if grp == "employment" else "通膨（CPI＋PCE）"
    n = lb["periods"]
    if not lb["rows"]:
        body = f'<p class="fc-n">{gname}還沒有已公布的資料，從這一期開始累積。</p>'
    else:
        err_h = "非農誤差" if grp == "employment" else "平均誤差"
        trs = ""
        for i, r in enumerate(lb["rows"], 1):
            err = (f"{r['nfp_err'] / 10:.1f} 萬" if grp == "employment" and r["nfp_err"] is not None
                   else (f"{r['err']:.2f}" if r["err"] is not None else "—"))
            dr = f"{r['dir']}/{r['dirn']}" if r["dirn"] else "—"
            cls = ' class="fc-base"' if r["name"] in (F.CONS, F.CLEV) else ""
            trs += (f'<tr{cls}><td>{i}</td><td>{_esc(r["name"])}</td><td>{r["hit"]}</td><td>{dr}</td>'
                    f'<td>{_esc(err)}</td><td>{r["periods"]}</td></tr>')
        body = (f'<table><thead><tr><th>#</th><th>機構</th><th>命中</th><th>方向命中</th><th>{err_h}</th><th>期數</th></tr></thead>'
                f'<tbody>{trs}</tbody></table>'
                + (f'<p class="fc-n">期數還少（{n} 期），僅供參考。</p>' if n < 6 else ""))
    return (f'<details class="f-more fc-lb"><summary>誰最準・{gname}（累計 {n} 期）</summary>{body}</details>')


def section(fc_ctx: dict | None, today: dt.date | None = None) -> str:
    from .. import clock
    today = today or clock.today()
    rel = (fc_ctx or {}).get("releases") or {}
    radios = "".join(f'<input type="radio" name="fc-t" id="fc-t-{k}" class="fc-in"{" checked" if k == "cpi" else ""}>'
                     for k in F.RELEASES)
    tabs = "".join(f'<label for="fc-t-{k}">{_esc(v)}</label>' for k, v in F.RELEASES.items())
    panels = "".join(_panel(k, F.pick(rel, k, today), rel, today) for k in F.RELEASES)
    notes = ('<details class="f-more"><summary>說明</summary>'
             '<p class="hm-foot">投行：BofA＝Bank of America、Citi＝Citigroup、JPM＝JPMorgan、MS＝Morgan Stanley、GS＝Goldman Sachs；'
             '投行數字由程式從公開的預覽報導自動擷取：文字須出現在提到該機構的原句；文章附的逐家預測表由 AI 讀圖，重算的中位數須等於表上的中位數；兩者都須與共識差距合理才採用。也可手動輸入。非官方。市場共識取自 ForexFactory；Cleveland Fed 為克里夫蘭聯儲的 Inflation Nowcasting（只預測通膨）。</p>'
             '<p class="hm-foot">計分：每家預估先四捨五入到實際值的位數再比，最接近的記一次命中（同樣近一起算）；'
             '方向命中＝預估高於或低於共識，實際也落在同一邊。實際值用首次公布值，之後的修正不計；各家只保留公布前的最後一版。</p>'
             '<p class="hm-foot">對共識：通膨、就業、時薪高於共識以紅色表示（偏緊縮），失業率高於共識以綠色表示。'
             '任何預估跟共識差太多（非農 15 萬、其他 0.3 個百分點）會被判定抓錯、不顯示。</p></details>')
    return (f'<style>{CSS}</style>'
            '<section class="home-zone hm-zone" aria-labelledby="home-fc">'
            '<div class="hm-zh"><div><span class="hm-num">04</span><h2 id="home-fc">各家預測</h2></div>'
            '<p>失業與通膨・各家投行 vs 市場共識</p></div>'
            f'<div class="fc">{radios}<div class="fc-tabs" role="group" aria-label="數據">{tabs}</div>'
            f'<div class="fc-ps">{panels}</div>{notes}</div></section>' + JS)
