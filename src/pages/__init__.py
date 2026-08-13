"""各分頁的內容產生器。版面與 CSS 統一在 src/site.py。"""

import re


def compact_full(html: str, label: str = "完整分析與方法") -> str:
    """把舊版全部內容保留在單一二級收合，避免卡片各自為政。"""
    inner = html.replace("<h2 ", "<h3 ").replace("<h2>", "<h3>")
    inner = inner.replace("</h2>", "</h3>")
    # 舊版各卡內原有的 details 改成靜態子區塊；外層只保留一個收合。
    # 這把最大收合深度固定在 2，避免「展開後還要再展開」。
    inner = re.sub(r'<details\b[^>]*>', '<div class="legacy-detail">', inner)
    inner = inner.replace('</details>', '</div>')
    inner = re.sub(r'<summary>(.*?)</summary>', r'<h4>\1</h4>', inner,
                   flags=re.S)

    return (
        '<div class="grid"><div class="card deep-dive">'
        f'<h2 id="details" data-sum="數據拆解、圖表、方法與資料來源">{label}</h2>'
        '<p class="hint">首卡只放決策需要的重點；全部細項仍保留在這裡。</p>'
        '<details class="full-detail" data-m-collapse><summary>展開完整內容</summary>'
        f'<div class="full-detail-body">{inner}</div></details></div></div>'
    )


def state_chip(label: str, value: str, note: str = "", kind: str = "neutral") -> str:
    return (f'<div class="focus-metric {kind}"><span>{label}</span>'
            f'<b>{value}</b>'
            + (f'<small>{note}</small>' if note else '') + '</div>')
