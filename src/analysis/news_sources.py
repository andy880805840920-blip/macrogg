"""Resolve source links and recover the same public article for all news topics."""
from __future__ import annotations
import asyncio,datetime as dt,logging,re,threading,xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse,quote
import requests
from . import news_checks, news_publishers
log=logging.getLogger(__name__)
TIMEOUT=8
_resolved={}
_lock=threading.Lock()


def is_google_article(url: str) -> bool:
    parsed=urlparse(url or "")
    return (parsed.hostname=="news.google.com" and bool(re.fullmatch(
        r"/(?:rss/)?(?:articles|read)/[A-Za-z0-9_-]{30,}",parsed.path)))


def public_url(url: str) -> bool:
    p=urlparse(url or "")
    return p.scheme in ("http","https") and bool(p.hostname and "." in p.hostname) and not p.username and not p.password and p.hostname not in ("news.google.com","localhost") and not re.fullmatch(r"[0-9.]+",p.hostname or "")


def recent(article: dict, now=None) -> bool:
    try:
        at=dt.datetime.fromisoformat(str(article.get("at") or "").replace("Z","+00:00"))
        if at.tzinfo is None:return False
        age=((now or dt.datetime.now(dt.timezone.utc))-at).total_seconds()
        return 0<=age<=86400
    except (ValueError,TypeError):return False


def _decode(urls: list[str]) -> list[dict]:
    from googlenewsdecoder import gnews_decoder_async
    return asyncio.run(gnews_decoder_async(urls,timeout=TIMEOUT,concurrency=4))


def resolve_records(records: list[dict], *, limit=20, now=None, _decoder=None) -> list[dict]:
    urls=list(dict.fromkeys(a.get("link","") for a in records
         if recent(a,now) and is_google_article(a.get("link",""))))[:limit]
    pending=[u for u in urls if u not in _resolved]
    if pending:
        try:
            results=(_decoder or _decode)(pending)
            if isinstance(results,dict):results=[results]
            for original,result in zip(pending,results):
                target=result.get("decoded_url","") if result.get("success") else ""
                if public_url(target):
                    with _lock:_resolved[original]=target
                else:log.info("新聞原文：Google News 解析未完成，保留參考連結")
        except Exception as exc:
            log.info("新聞原文：Google News 解析失敗（%s），保留參考連結",type(exc).__name__)
    out=[]
    for article in records:
        original=article.get("link","");target=_resolved.get(original) if original in urls else None
        out.append({**article,"original_link":original,"link":target} if target else dict(article))
    return out


def same_article(a: dict, b: dict) -> bool:
    x=news_checks.norm_title(news_checks.clean_title(a.get("title", ""),a.get("source", "")))
    y=news_checks.norm_title(news_checks.clean_title(b.get("title", ""),b.get("source", "")))
    if len(x)>=8 and x==y:return True
    if len(x)<20 or len(y)<20:return False
    # A near-identical headline with a negation or changed figures can be a different event.
    neg=lambda t: set(re.findall(r"\b(?:not|never|no)\b|不會|不会|否認|否认|並非|并非",t,re.I))
    if neg(a.get("title", ""))!=neg(b.get("title", "")):return False
    if news_checks.number_tokens(a.get("title", ""))!=news_checks.number_tokens(b.get("title", "")):return False
    return SequenceMatcher(None,x,y).ratio()>=0.94


def find_same_article(article: dict, *, now=None, _get=None) -> list[dict]:
    if not recent(article,now):return []
    title=news_checks.clean_title(article.get("title", ""),article.get("source", ""))
    chinese = len(re.findall(r"[\u4e00-\u9fff]", title)) >= 8
    sites = ("tw.stock.yahoo.com", "tw.news.yahoo.com") if chinese else ("finance.yahoo.com", "economictimes.indiatimes.com")
    queries = ['"'+title+'" when:1d'] + ['"'+title+'" site:'+site for site in sites]
    locale = "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant" if chinese else "&hl=en-US&gl=US&ceid=US:en"
    get=_get or (lambda u:requests.get(u,timeout=TIMEOUT,headers={"User-Agent":"Mozilla/5.0 (macro-dashboard)"}))
    queries.insert(1, '"'+title+'" '+news_publishers.site_query(
        news_publishers.PRIMARY_DOMAINS+news_publishers.SECONDARY_EN+news_publishers.SECONDARY_ZH))
    found=[];seen=set()
    for query in queries:
        url="https://news.google.com/rss/search?q="+quote(query)+locale
        try:
            r=get(url);r.raise_for_status();root=ET.fromstring(r.content)
        except Exception as exc:
            log.info("新聞原文：同篇轉載查詢未完成（%s）",type(exc).__name__);continue
        for item in root.findall(".//item"):
            try:at=parsedate_to_datetime(item.findtext("pubDate") or "").isoformat()
            except (ValueError,TypeError):continue
            h={"title":item.findtext("title") or "","link":item.findtext("link") or "",
               "source":item.findtext("source") or "","at":at,"summary":""}
            if (recent(h,now) and same_article(article,h) and h['link'] not in seen
                    and h['link'] not in (article.get('link'),article.get('original_link'))):
                seen.add(h['link']);found.append(h)
    found.sort(key=lambda a:(news_publishers.priority(a),a.get("at", "")),reverse=True)
    return found[:6]


def _try_fetch(fetch, url):
    try:return fetch(url) or ""
    except Exception as exc:
        log.info("新聞原文：文章讀取未完成（%s），嘗試同篇公開轉載",type(exc).__name__)
        return ""


def read_article(article: dict, fetch, *, now=None, _find=None, _resolver=None) -> dict:
    """Keep the actual read URL/source/date with the body; never invent a replacement."""
    if not recent(article,now):return {**article,"body":""}
    resolve=_resolver or resolve_records
    h=resolve([article],now=now)[0]
    value=_try_fetch(fetch,h["link"]) if public_url(h.get("link", "")) else ""
    if value:return {**h,"body":value}
    alternatives=(_find or find_same_article)(article,now=now)
    alternatives=[a for a in alternatives if recent(a,now) and same_article(article,a)]
    for candidate in resolve(alternatives,limit=6,now=now)[:3]:
        if not public_url(candidate.get("link","")) or candidate['link']==h.get('link'):continue
        value=_try_fetch(fetch,candidate["link"])
        if value:
            log.info("新聞原文：使用同篇公開轉載 %s",candidate.get("source") or "")
            return {**candidate,"body":value,"original_link":article.get("original_link") or article["link"],"original_source":article.get("source","")}
    return {**h,"body":""}
