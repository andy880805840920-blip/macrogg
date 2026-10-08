"""Conservative validation helpers for source titles, events, numbers and cache keys."""
from __future__ import annotations
import re,json,hashlib
from decimal import Decimal

_MEDIA = re.compile(r"Reuters|Bloomberg|CNBC|Financial Times|FT|WSJ|Wall Street Journal|Yahoo(?: Finance| News| Sports|奇摩(?:財經|新聞|股市|新聞網)?)?|路透(?:社)?|彭博(?:社)?|中央社|工商時報|經濟日報|聯合(?:新聞網|報)|自由財經|MoneyDJ|鉅亨(?:網)?|AP|Associated Press",re.I)
def clean_title(title: str, source: str = "") -> str:
    title=(title or "").strip()
    m=re.search(r"\s+[-–—|]\s+([^|\n]{1,60})$",title)
    if m and ((_MEDIA.fullmatch(m[1].strip())) or
              (source and m[1].strip().casefold()==source.strip().casefold())):
        return title[:m.start()].strip()
    return title

def norm_title(title: str) -> str:
    return re.sub(r"[\s，。、！？：；「」『』()（）\[\]【】,.:;!?'\"]+","",clean_title(title)).casefold()

def number_tokens(text: str):
    text=re.sub(r"【報導[a-z]\d+】","",text or "").replace("−","-").replace("，",",")
    result=[]
    for m in re.finditer(r"(?<![\d.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![\d.])",text):
        value=Decimal(m[0].replace(",",""))
        pos=m.start()
        if pos and text[pos-1] in "+-" and (pos<2 or not re.match(r"[0-9A-Za-z]", text[pos-2])):
            if text[pos-1]=="-": value=-value
        prefix=text[max(0,pos-2):pos]
        if prefix in ("-$", "$-"):
            value=-abs(value)
        tail=text[m.end():]
        shared=re.match(r"\s*[-–—~～至到]\s*(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*",tail)
        unit_tail=tail[shared.end():] if shared else tail
        unit=re.match(r"\s*(basis points?|bps?|個?基點|percentage points?|percent(?:age)?|個?百分點|%|％|million|billion|trillion|bn|mn|萬|億|兆|USD|dollars?|美元|元|people|persons?|jobs?|workers?|barrels?|bbls?|桶|人)",unit_tail,re.I)
        family=None;quantity=value;end=m.end()
        if unit:
            u=unit[1].lower();end+=unit.end() + (shared.end() if shared else 0)
            if u in ("bp","bps","基點","個基點") or u.startswith("basis point"):
                family="rate";quantity=value
            elif u in ("%","％","percent","percentage","百分點","個百分點") or u.startswith("percentage point"):
                family="rate";quantity=value*100
            else:
                factor={"million":Decimal(10)**6,"billion":Decimal(10)**9,
                        "trillion":Decimal(10)**12,"bn":Decimal(10)**9,"mn":Decimal(10)**6,"萬":Decimal(10)**4,
                        "億":Decimal(10)**8,"兆":Decimal(10)**12}.get(u,Decimal(1))
                quantity=value*factor
                after=text[end:]
                currency=re.match(r"\s*(USD|dollars?|美元|元|people|persons?|jobs?|workers?|barrels?|bbls?|桶|人)",after,re.I)
                label=currency[1].lower() if currency else u if factor==1 else "scaled"
                if "$" in prefix:label="usd"
                family="usd" if label in ("usd","dollar","dollars","美元") else "barrels" if label in ("barrel","barrels","bbl","bbls","桶") else "people" if label in ("人", "people", "person", "persons", "job", "jobs", "worker", "workers") else label
        elif "$" in prefix:
            family="usd"
        result.append((value,family,quantity))
    return result

def _source_numeric_equivalents(source: str) -> str:
    """Normalize explicit date/duration words and clearly stated Taiwan-dollar cents."""
    extra=[]
    words={"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,
           "eight":8,"nine":9,"ten":10,"eleven":11,"twelve":12}
    for m in re.finditer(r"\b("+"|".join(words)+r")[ -]+(weeks?|months?|years?|days?)\b",source,re.I):
        extra.append(str(words[m[1].lower()])+" "+m[2])
    months=["January","February","March","April","May","June","July","August",
            "September","October","November","December"]
    for month,n in zip(months,range(1,13)):
        # May can be a verb; require an explicit calendar phrase for that month.
        pattern=(r"\b(?:in|during|for|since|through|until|by|last|next|this)\s+May\b|\bMay\s+\d{1,2}\b"
                 if month=="May" else r"\b"+month+r"\b")
        if re.search(pattern,source,re.I):
            extra.append(str(n)+"月")
    chinese={"一":1,"二":2,"兩":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9,
             "十":10,"十一":11,"十二":12}
    for m in re.finditer(r"(十一|十二|十|一|二|兩|三|四|五|六|七|八|九)(個月|月|週|周|天|年)",source):
        extra.append(str(chinese[m[1]])+m[2])
    if re.search(r"新?台幣|新?臺幣|Taiwan dollar|\bTWD\b",source,re.I):
        for m in re.finditer(r"(?:升值|貶值|升|貶|漲|跌)\s*(\d+(?:\.\d+)?)\s*分(?!鐘|數|析|配|別|評)",source):
            extra.append(str(Decimal(m[1])/100)+"元")
    return source+"\n"+" ".join(extra)


def digits_ok(text: str, source: str) -> bool:
    src=number_tokens(_source_numeric_equivalents(source))
    plain={v for v,f,q in src}
    quantities={(f,q) for v,f,q in src if f}
    for value,family,quantity in number_tokens(text):
        if family:
            if (family,quantity) not in quantities:
                return False
        elif value not in plain:
            return False
    return True

def same_event(a: dict | str,b: dict | str) -> bool:
    a={"title":a} if isinstance(a,str) else a
    b={"title":b} if isinstance(b,str) else b
    x,y=norm_title(a.get("title","")),norm_title(b.get("title",""))
    x=re.sub(r"(暗示|考慮)將", r"\1", x)
    y=re.sub(r"(暗示|考慮)將", r"\1", y)
    if not x or not y:return False
    if x==y:return True
    # Direction or tenor/value changes can be a different event, even with the same URL.
    if {v for v,f,q in number_tokens(x)}!={v for v,f,q in number_tokens(y)}:return False
    up=r"rise|rises|rising|rose|jump|gain|higher|increase|上升|上漲|升高|走高|攀升"
    down=r"fall|falls|fell|drop|lower|decline|decrease|下降|下跌|走低|回落"
    if (bool(re.search(up,x)) and bool(re.search(down,y))) or (bool(re.search(down,x)) and bool(re.search(up,y))):
        return False
    if a.get("link") and a.get("link")==b.get("link"):return True
    A={x[i:i+2] for i in range(len(x)-1)};B={y[i:i+2] for i in range(len(y)-1)}
    return len(A&B)/max(1,len(A|B))>=0.86

def fingerprint(items) -> str:
    payload=[{k:str(x.get(k) or "") for k in ("title","link","source","at","summary","body")} for x in items]
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode("utf-8")).hexdigest()

def meta_hits(text: str, markers) -> list[str]:
    out=[]
    contexts={"關鍵字":r"(?:指定|設定|提供|輸入|符合|相關|篩選).{0,8}關鍵字|關鍵字.{0,8}(?:不足|有限|缺乏|相關的材料)",
              "不足以":r"(?:材料|輸入|標題|來源資訊).{0,12}不足以|不足以.{0,16}(?:生成|撰寫|摘要|綜合)",
              "以下是":r"以下是.{0,12}(?:摘要|重點整理|整理結果|我的|我為)",
              "以下為":r"以下為.{0,12}(?:摘要|重點整理|整理結果|我的|我為)",
              "內文細節":r"(?:缺乏|沒有|未提供|無法).{0,8}內文細節"}
    for marker in markers:
        if marker in text and (marker not in contexts or re.search(contexts[marker],text)):
            out.append(marker)
    return out



_COPY_NOISE = re.compile(
    r"^(?:將\s*Yahoo\s*設為|更多.{0,35}(?:新聞網|報導)|延伸閱讀|相關新聞|"
    r"Read more\s*:|Click here\b|Sign up\b|Subscribe\b|Follow us\b|"
    r"◎.{0,35}提醒您|本資料僅供參考|免責聲明)", re.I)
_BYLINE = re.compile(
    r"^\s*(?:[\[【〔][^\]】〕\n]{1,60}[\]】〕]\s*)?"
    r"(?:記者|編譯|特派員|文|撰文)[^／/\n：:。]{1,24}"
    r"(?:[／/]\s*(?:綜合報導|綜合外電報導|外電報導|報導|編譯|整理)|[：:]\s*)\s*")


_WIRE_BYLINE = re.compile(r"^[（(](?:中央社|中新社|新華社)[^）)\n]{1,100}(?:報導|電|电)[）)]\s*")


def clean_news_copy(text: str) -> str:
    """Strip publishing metadata, never substitute or add reported facts."""
    import html
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(text or "")))
    cleaned = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line or _COPY_NOISE.search(line):
            continue
        line = re.sub(r"^〔[^〕]{1,60}(?:報導|編譯)〕\s*", "", line)
        line = _WIRE_BYLINE.sub("", line)
        line = re.sub(r"^(?:財經|國際|政治|新聞)中心[／/]\s*綜合報導\s*", "", line)
        line = _BYLINE.sub("", line)
        line = re.sub(r"^(?:Good morning|Good afternoon)[.!]\s*", "", line, flags=re.I)
        if re.search(r"(?:\.{3}|…)+\s*$", line):
            end = max(line.rfind(c) for c in "。！？")
            line = line[:end + 1] if end >= 0 else ""
        if line:
            cleaned.append(line)
    return "\n".join(cleaned)


def topic_copy_problem(text: str) -> str:
    """A supplement needs readable Chinese reporting, not a masthead or raw headline."""
    if len(re.findall(r"[\u4e00-\u9fff]", text or "")) < 8:
        return "缺少可閱讀的中文新聞內容，像在列標題；請用繁體中文忠實整理"
    if _BYLINE.search(text or "") or _WIRE_BYLINE.search(text or "") or re.search(r"\[(?:FTNN|[^\]]*新聞網)[^\]]*\]|記者.{1,24}[／/]綜合報導", text or ""):
        return "混入記者署名或出版資訊，請只保留新聞事件與細節"
    if _COPY_NOISE.search(text or ""):
        return "混入導覽、推薦或訂閱資訊，請只保留新聞事件"
    if not re.search(r"[。！？!?]$", text.strip()):
        return "句子未完整結束，請重寫為完整中文句子"
    return ""
