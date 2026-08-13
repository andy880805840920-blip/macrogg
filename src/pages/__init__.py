"""各分頁的內容產生器。版面與 CSS 統一在 src/site.py。"""

import re


def compact_full(html: str, label: str = "完整分析與方法") -> str:
    """移除重複結論，讓每個主題成為一層收合，不再包完整分析外殼。"""
    inner = _drop_first_verdict(html)
    # 卡內舊收合改成靜態證據區；真正可操作的收合只保留外層主題卡。
    inner = re.sub(r'<details\b[^>]*>', '<div class="legacy-detail">', inner)
    inner = inner.replace('</details>', '</div>')
    inner = re.sub(r'<summary>(.*?)</summary>', r'<h4>\1</h4>', inner,
                   flags=re.S)
    return inner


def _drop_first_verdict(html: str) -> str:
    """完整內容開頭的舊結論卡與新版主卡重複，安全移除第一張。"""
    start = html.find('<div class="verdict')
    if start < 0:
        return html
    token = re.compile(r'<div\b[^>]*>|</div>')
    depth = 0
    for match in token.finditer(html, start):
        if match.group(0).startswith("<div"):
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return html[:start] + html[match.end():]
    return html


def focus_evidence(html: str, label: str = "查看判斷依據") -> str:
    """主卡只常駐結論；方法與傳導鏈統一收在唯一一層。"""
    if not html:
        return ""
    return (f'<details class="focus-evidence"><summary>{label}</summary>'
            f'<div class="focus-evidence-body">{html}</div></details>')


def state_chip(label: str, value: str, note: str = "", kind: str = "neutral") -> str:
    return (f'<div class="focus-metric {kind}"><span>{label}</span>'
            f'<b>{value}</b>'
            + (f'<small>{note}</small>' if note else '') + '</div>')
