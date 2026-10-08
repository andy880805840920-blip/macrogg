"""Shared main-text extraction for every news topic and the homepage."""
from __future__ import annotations
import logging,re
from . import news_checks
log=logging.getLogger(__name__)


def _main_container(page: str) -> str:
    """Scope extraction before heuristics so short stories cannot absorb related cards."""
    from lxml import html
    tree = html.fromstring(page)
    candidates = []
    for node in tree.iter():
        if not isinstance(node.tag, str):
            continue
        marker = " ".join(node.get(k) or "" for k in ("class", "id", "role"))
        if re.search(r"recommend|related|newsletter|subscribe|cookie|consent", marker, re.I):
            continue
        if (any(re.match(r"^(?:(?:module-)?(?:article|story|entry|post|caas)[-_](?:body|content|text)(?:[-_]|$)|body__content(?:[-_]|$)|ArticleBody-articleBody$)", token, re.I) for token in marker.split())
                or (node.tag == "div" and "text" in (node.get("class") or "").split())):
            if len(node.text_content().strip()) >= 100:
                candidates.append(node)
    if not candidates:
        candidates = [node for node in tree.iter("article")
                      if len(node.text_content().strip()) >= 100]
    if candidates:
        return html.tostring(candidates[0], encoding="unicode")
    return page


def extract_paragraphs(page: str, url: str = "", *, fallback=None) -> list[str]:
    """Extract main text separately from title, author, comments and page furniture.

    Explicit article paragraphs are preferred; non-paragraph layouts use Trafilatura.
    A failed or thin extraction can use the existing scoped HTML reader. Never
    use all-page text or metadata descriptions as if they were article bodies.
    """
    raw=""
    scoped = page
    try:
        scoped = _main_container(page)
        if scoped != page and fallback:
            paragraphs = fallback(scoped)
            joined = " ".join(paragraphs)
            if len(re.findall(r"[\u4e00-\u9fff]", joined)) >= 100 or len(joined) >= 300:
                return paragraphs
        from trafilatura import extract
        raw=extract(scoped, url=url or None, include_comments=False,
                    include_tables=False, with_metadata=False,
                    favor_precision=True) or ""
    except Exception as exc:
        log.info("新聞正文：標準擷取未完成（%s），改用文章段落", type(exc).__name__)
    rows=[];seen=set()
    for paragraph in raw.splitlines():
        clean=news_checks.clean_news_copy(paragraph)
        if len(clean)<20 or clean in seen or re.search(
            r"資料照|圖片來源|（記者[^）]{0,50}攝）|版權所有|All Rights Reserved|點我下載|APP看新聞",clean,re.I):
            continue
        seen.add(clean);rows.append(clean)
    if sum(map(len,rows))>=100:
        return rows
    return fallback(scoped) if fallback else rows
