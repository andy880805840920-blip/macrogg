"""各分頁的內容產生器。版面與 CSS 統一在 src/site.py。"""

import re


def compact_full(html: str, label: str = "完整分析與方法") -> str:
    """
    移除重複結論，讓每個主題成為可收合的卡區。

    **內層的 <details> 保留，不再打平。** 先前這裡把所有內層收合轉成
    永遠展開的 legacy-detail（「真正可操作的收合只保留外層主題卡」），
    結果是：訊號的「依據」全文攤開、17 個行業的表格攤開、標準差與樣本
    月數的方法說明攤開——每一區都變成方法論擋在結論前面，使用者的原話
    是「太複雜、很亂」。

    現在的層級是固定的三層，全站一致：

        第一層　卡區標題＋一句結論（收合的 sect，掃過去就能讀）
        第二層　打開卡區：結論、白話解讀、「這在看什麼」教學
        第三層　依據／方法／完整表格（卡區內的 <details>，要驗算才點）

    「展開後還要再展開」不是缺陷——第三層的內容（z-score、逐月修正表、
    17 個行業）本來就只有一成的讀者需要，攤開只會懲罰另外九成。
    """
    return _drop_first_verdict(html)


def teach(what: str, why: str, how: str = "") -> str:
    """
    「這在看什麼？」——每個複雜區塊固定一塊的教學層。

    這個網站的讀者是學生與一般投資人，目標不只是給結論，還要讓他們
    **學會自己讀這些數據**。三段固定：這個區塊在量什麼、為什麼重要、
    怎麼判讀。全站同一個樣式、同一個位置（區塊開頭、預設收合），
    看熟了就知道每一區都有地方可以學。

    內容規範：不用「標準差」「z-score」「季調」這類詞彙起頭；
    必須用到時要先用一句白話解釋。
    """
    from ..site import esc
    body = (f'<p><b>在量什麼：</b>{esc(what)}</p>'
            f'<p><b>為什麼重要：</b>{esc(why)}</p>'
            + (f'<p><b>怎麼判讀：</b>{esc(how)}</p>' if how else ""))
    return (f'<details class="teach"><summary>這在看什麼？</summary>'
            f'<div class="teach-body">{body}</div></details>')


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
