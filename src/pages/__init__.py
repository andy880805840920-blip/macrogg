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


_TERMS: dict | None = None


def _terms() -> dict:
    """config/ask.yaml 的名詞卡短標題（偷懶頁的「什麼是…？」）。讀不到就回空。"""
    global _TERMS
    if _TERMS is None:
        try:
            import yaml
            from pathlib import Path
            p = Path(__file__).resolve().parents[2] / "config" / "ask.yaml"
            _TERMS = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("terms") or {}
        except Exception:                          # noqa: BLE001
            _TERMS = {}
    return _TERMS


def learn_link(key: str) -> str:
    """
    連到偷懶頁的名詞卡。教學內容（一句話、怎麼來的、怎麼看、傳導鏈、常見誤讀、
    小測驗）只在 config/learn.yaml 維護一份；各頁的「這在看什麼？」只講這一塊
    圖在看什麼，完整教學一律連過去。
    """
    t = _terms().get(key)
    if not t:
        return ""
    from urllib.parse import quote
    from ..site import esc
    q = f"什麼是{t.get('t')}？"
    return (f'<p class="teach-more"><a href="/ask/?q={quote(q)}">完整教學：{esc(q)}'
            f'（怎麼來的、常見誤讀、小測驗）→</a></p>')


def learn_links(*keys: str) -> str:
    """
    區塊最下方一行「延伸學習」：連到偷懶頁對應的名詞卡（可多張）。
    名詞卡不存在就略過，全部不存在就不輸出。
    """
    from urllib.parse import quote
    from ..site import esc
    T = _terms()
    items = [(k, T[k].get("t")) for k in keys if k in T and T[k].get("t")]
    if not items:
        return ""
    links = "".join(f'<a href="/ask/?q={quote("什麼是" + t + "？")}">{esc(t)}</a>' for _, t in items)
    return f'<p class="learn-more"><span>延伸學習（偷懶）</span>{links}</p>'


def gloss_more() -> str:
    """名詞解釋區塊底下一行：每個名詞的完整教學都在偷懶頁。"""
    return ('<p class="teach-more">每個名詞的完整教學（怎麼來的、怎麼看、常見誤讀、小測驗）'
            '都在<a href="/ask/">偷懶頁</a>，直接打「什麼是＋名詞」就找得到。</p>')


def teach(what: str, why: str, how: str = "", learn: str = "") -> str:
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
            + (f'<p><b>怎麼判讀：</b>{esc(how)}</p>' if how else "")
            + (learn_link(learn) if learn else ""))
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
