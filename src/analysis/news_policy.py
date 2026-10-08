"""Scope and display rules for the homepage's news, independent of ranking."""
from __future__ import annotations
import re
from urllib.parse import urlsplit

MAIN_TOPICS = ["Fed", "FOMC", "升息", "降息", "通膨", "CPI", "PCE", "非農", "失業率", "GDP",
               "美債", "美債殖利率", "美元", "美國財政部", "財政赤字", "川普", "關稅",
               "日本央行", "日圓", "AI", "NVIDIA", "半導體", "AI資本支出", "油價", "伊朗",
               "中東戰爭", "俄烏戰爭", "黃金", "聯準會", "Kevin Warsh", "發債", "BOJ", "輝達"]
ALIASES = {
    "Fed": ("Fed", "Federal Reserve", "聯準會", "美聯儲", "Powell", "鮑威爾"),
    "FOMC": ("FOMC", "Federal Open Market Committee"),
    "升息": ("升息", "加息", "rate hike", "rate hikes", "rate increase", "raise rates", "raises rates"),
    "降息": ("降息", "減息", "rate cut", "rate cuts", "cut rates", "cuts rates"),
    "通膨": ("通膨", "通脹", "inflation"),
    "CPI": ("CPI", "consumer price index", "消費者物價"),
    "PCE": ("PCE", "personal consumption expenditures"),
    "非農": ("非農", "nonfarm", "non-farm", "payrolls", "jobs report"),
    "失業率": ("失業率", "unemployment rate", "unemployment"),
    "GDP": ("GDP", "gross domestic product"),
    "美債": ("美債", "美國公債", "U.S. Treasury", "US Treasury", "Treasuries", "Treasury yields", "Treasury auction", "Treasury auctions", "Treasury bonds", "Treasury bond"),
    "美元": ("美元", "U.S. dollar", "US dollar", "dollar", "dollar index", "DXY", "USD"),
    "美國財政部": ("美國財政部", "財政部", "U.S. Treasury Department", "US Treasury Department", "Treasury", "Treasury Department", "Bessent", "貝森特"),
    "財政赤字": ("財政赤字", "預算赤字", "fiscal deficit", "budget deficit"),
    "川普": ("川普", "特朗普", "Trump", "Donald Trump"),
    "關稅": ("關稅", "tariff", "tariffs"),
    "日本央行": ("日本央行", "日本銀行", "BOJ", "Bank of Japan", "Kazuo Ueda", "植田和男"),
    "日圓": ("日圓", "日元", "yen", "JPY"),
    "AI": ("AI", "人工智慧", "人工智能", "artificial intelligence"),
    "NVIDIA": ("NVIDIA", "輝達", "英偉達"),
    "半導體": ("半導體", "semiconductor", "semiconductors", "chip", "chips", "chipmaker", "chipmakers"),
    "AI資本支出": ("AI資本支出", "AI 資本支出", "AI capex", "AI capital spending", "AI capital expenditure", "AI capital expenditures"),
    "油價": ("油價", "原油", "oil price", "oil prices", "crude", "WTI", "Brent", "OPEC"),
    "伊朗": ("伊朗", "Iran", "Iranian"),
    "中東戰爭": ("中東戰爭", "中東衝突", "Middle East war", "Middle East conflict", "Israel", "Gaza", "以色列", "加薩", "霍爾木茲", "Hormuz"),
    "俄烏戰爭": ("俄烏戰爭", "俄烏", "Russia-Ukraine", "Russia Ukraine", "Ukraine war", "war in Ukraine", "烏克蘭戰爭", "Ukraine", "烏克蘭"),
    "黃金": ("黃金", "金價", "gold", "bullion"),
    "Kevin Warsh": ("Kevin Warsh", "Warsh", "華許", "沃許", "瓦許"),
    "發債": ("發債", "債券發行", "bond issuance", "bond issue", "bond offering", "debt issuance", "debt sale", "bond sale"),
}
# Duplicate topic labels remain in configuration exactly as supplied by the user.
REFERENCES = {"聯準會": "Fed", "BOJ": "日本央行", "輝達": "NVIDIA", "美債殖利率": "美債"}
STRONG_TOPICS = {"川普", "關稅", "日本央行", "日圓", "AI", "NVIDIA", "半導體", "AI資本支出", "油價", "伊朗", "中東戰爭", "俄烏戰爭", "黃金", "Kevin Warsh"}
FOREIGN = re.compile(r"\b(?:India|Indian|RBI|rupee|Brazil|Brazilian|Australia|Australian|Canada|Canadian|China|Chinese|Europe|European|Britain|British|UK|France|French|Germany|German|Italy|Italian|Korea|Korean|Mexico|Mexican|Japan|Japanese|Russia|Russian)\b|印度|巴西|澳洲|澳大利亞|加拿大|中國|大陸|歐洲|歐元區|英國|法國|德國|義大利|韓國|墨西哥|日本|日經|俄羅斯|台灣|臺灣", re.I)
US_CORE = re.compile(r"\b(?:Fed|FOMC|Federal Reserve|United States|U\.S|US Treasury|U\.S\. Treasury|Powell|Warsh|Bessent|American|DXY|dollar index)\b|(?<![A-Za-z])US(?=\s)|美國|美債|聯準會|鮑威爾|貝森特|美元指數", re.I)


def hit(word: str, text: str) -> bool:
    if not word:
        return False
    if word.isascii():
        return bool(re.search(r"(?<![A-Za-z0-9_])" + re.escape(word) + r"(?![A-Za-z0-9_])", text, re.I))
    # Spaces inside a Chinese phrase are typographical, not separate search terms.
    return re.sub(r"\s+", "", word) in re.sub(r"\s+", "", text)


def family(topic: str) -> str:
    t = REFERENCES.get(topic, topic)
    if t in ALIASES:
        return t
    for key, words in ALIASES.items():
        if any(t.casefold() == word.casefold() for word in words):
            return key
    return t


def expand(topics: list[str]) -> list[str]:
    return list(dict.fromkeys(w for topic in topics for w in ALIASES.get(family(topic), (topic,))))


def main_allowed(article: dict, topics: list[str] | None = None) -> bool:
    """Require an approved topic; generic foreign macro/FX news is insufficient.

    Explicit BOJ, AI, commodities and war topics may concern other countries.
    A U.S.-led headline may discuss foreign developments as relevant context.
    """
    topics = MAIN_TOPICS if topics is None else topics
    title = str(article.get("title") or "")
    summary = str(article.get("summary") or "")
    matched = {family(t) for t in topics if any(hit(w, title) for w in ALIASES.get(family(t), (t,)))}
    official_fed = "Fed" in {family(t) for t in topics} and (
        (urlsplit(str(article.get("link") or "")).hostname or "").lower().rstrip(".") in {"federalreserve.gov", "www.federalreserve.gov"} or
        str(article.get("source") or "").casefold() == "federal reserve")
    if not matched and not official_fed:
        return False
    foreign = FOREIGN.search(title)
    foreign_fx = re.search(r"British Pound|Canadian Dollar|Australian Dollar|Singapore Dollar|Hong Kong Dollar|\b(?:rupee|yuan|renminbi|euro|pound|won|ringgit|baht)\b|英鎊|歐元|人民幣|港幣|韓元|泰銖|盧比|新加坡幣|澳幣|加幣",title,re.I)
    us_lead = US_CORE.search(title)
    if foreign_fx and foreign_fx.start()<=12 and (not us_lead or foreign_fx.start()<us_lead.start()):
        return False
    us_bond = re.search(r"(?<![A-Za-z])(?:U[.]?S[.]?\s+Treasur(?:y|ies)|United States (?:bonds|Treasuries))(?![A-Za-z])|美債|美國公債", title, re.I)
    # Foreign investors buying U.S. bonds are U.S.-bond news; local foreign bonds
    # do not become U.S. news merely by appending a Treasury comparison.
    if matched & {"美債", "美國財政部"} and us_bond:
        before = title[:us_bond.start()]
        local_bond = re.search(r"bond yields?|government yields?|government bonds?|\bbonds?\b|\bCPI\b|\bGDP\b|inflation|unemployment|central bank|rate cuts?|rate hikes?|\bstocks?\b|rupee|公債|債市|債券|通膨|失業率|央行|降息|升息|股市", before, re.I)
        if not foreign or foreign.start() > us_bond.start() or not local_bond:
            return True
    # Local macro as the subject stays out even if the headline appends oil/Fed.
    first_clause = re.split(r"[,，;；：:]", title, maxsplit=1)[0]
    local_macro = re.search(r"(?<![A-Za-z0-9])(?:CPI|GDP|inflation|unemployment|RBI|central bank|rate cut|rate cuts|rate hike|rate hikes|bond yields|bonds|bond issuance|budget|deficit|stocks|rupee)(?![A-Za-z0-9])|通膨|通脹|失業率|央行|降息|升息|債市|財政赤字|股市|盧比", first_clause, re.I)
    japan_topic = matched & {"日本央行", "日圓"}
    if foreign and foreign.start() <= 12 and local_macro and not japan_topic:
        early_us = US_CORE.search(title)
        if not early_us or early_us.start() > foreign.start():
            return False
    if matched & STRONG_TOPICS:
        return True
    us = US_CORE.search(title)
    if foreign:
        return bool(us and us.start() < foreign.start())
    if FOREIGN.search(summary) and not us and not official_fed:
        return False
    return True


PERSON_NAMES = {
    "Donald Trump": ("唐納德·川普", "唐納德川普", "唐納德·特朗普", "川普", "特朗普"),
    "Kevin Warsh": ("凱文·華許", "凱文華許", "凱文·沃許", "凱文沃許", "華許", "沃許", "瓦許"),
    "Jerome Powell": ("傑羅姆·鮑威爾", "傑羅姆鮑威爾", "鮑威爾", "鲍威尔"),
    "Scott Bessent": ("史考特·貝森特", "史考特貝森特", "貝森特", "貝森"),
    "Janet Yellen": ("珍妮特·葉倫", "珍妮特葉倫", "葉倫", "耶倫"),
    "Joe Biden": ("喬·拜登", "喬拜登", "拜登"),
    "Kazuo Ueda": ("植田和男",),
    "Jensen Huang": ("黃仁勳",),
    "Elon Musk": ("伊隆·馬斯克", "伊隆馬斯克", "馬斯克"),
    "Vladimir Putin": ("弗拉迪米爾·普丁", "普丁", "普京"),
    "Volodymyr Zelenskyy": ("澤倫斯基", "澤連斯基"),
    "Xi Jinping": ("習近平",),
}
PERSON_RULE = ("人物姓名一律使用英文拼寫，主軸、補充及引述都適用；不要附中文姓名或中文音譯。"
               "優先沿用來源的英文姓名，例如 Donald Trump、Kevin Warsh、Jerome Powell、Scott Bessent、Kazuo Ueda、Jensen Huang。"
               "若無法確認某人的英文拼寫，只使用來源已有的職稱，不自行猜測或補寫姓名。")
SCOPE_RULE = ("只選設定主題範圍內的新聞。印度等其他地區的本地 CPI、GDP、失業率、降息、債市或匯率新聞，"
              "不能僅因同字或順帶提到 Fed 就寫成主軸；美國總經政策與美債，以及明確屬於 BOJ、日圓、AI、半導體、油價、"
              "黃金、關稅及指定戰爭主題的新聞才符合範圍。缺相關新聞時少寫，不能用不相關新聞補滿。"
              "主軸依事件的重要性安排，不必把油價、AI 或戰爭新聞硬接到 Fed；原因與影響只用來源已有的說法。")


COMPANY_NAMES = {
    "NVIDIA": ("輝達", "英偉達", "英伟达"), "TSMC": ("台灣積體電路", "臺灣積體電路", "台積電", "臺積電"),
    "Microsoft": ("微軟",), "Apple": ("蘋果公司",), "Amazon": ("亞馬遜",),
    "Alphabet": ("谷歌母公司", "Google母公司"), "Google": ("谷歌",), "Meta": ("臉書母公司",),
    "Facebook": ("臉書",), "OpenAI": ("開放人工智慧公司",), "Oracle": ("甲骨文",),
    "Tesla": ("特斯拉",), "AMD": ("超微",), "Intel": ("英特爾",), "Broadcom": ("博通",),
    "Wistron": ("緯創",), "Wiwynn": ("緯穎",), "Quanta": ("廣達",),
    "Foxconn": ("鴻海",), "MediaTek": ("聯發科",), "Delta Electronics": ("台達電",),
    "Qualcomm": ("高通",), "Micron": ("美光",), "Samsung": ("三星電子",), "SK hynix": ("SK海力士", "海力士"),
}
COMPANY_RULE = ("公司名稱一律使用來源可確認的英文名稱，例如 NVIDIA、TSMC、Microsoft、Apple、Amazon、Meta、Alphabet、Google、OpenAI。"
                "主軸、補充與引述都適用，不附中文音譯；公司與旗下品牌依來源區分，不把 Google 自動改成 Alphabet。"
                "未知英文名稱時使用來源已有的公司角色或產業描述，不自行猜測拼寫。"
                "高通膨、高通量、超微細等一般用語不是公司名稱，不可替換成 Qualcomm 或 AMD。"
                "中文敘述用自然的台灣用語；frustratingly high inflation 可表達為通膨持續偏高、令官員感到挫折，不能把編輯改寫當成逐字引述。")


def topic_excluded(tid: str, article: dict, excludes) -> bool:
    title = article.get("title") or ""
    text = " ".join(str(article.get(k) or "") for k in ("title", "summary", "body"))
    # Taiwan futures and gold reject ETF stories even when mentioned only in a summary/body.
    target = text if tid in {"twf", "gold", "fx"} else title
    excludes = list(excludes or [])
    if tid == "twf" and not re.search(r"(?<![A-Za-z])ETFs?(?![A-Za-z])|指數型基金|指數股票型基金",text,re.I):
        # Corporate dividends affecting futures are market news; ETF/high-dividend promotions remain excluded.
        if re.search(r"台指期|臺指期|Taiwan futures|\bTXF\b",title,re.I):
            excludes=[k for k in excludes if k not in {"股息","配息"}]
    if tid == "semi" and any(hit(k, text) for k in ("NVIDIA", "TSMC", "輝達", "台積電", "semiconductor", "semiconductors", "晶片", "半導體")):
        excludes = [k for k in excludes if k not in {"台股", "臺股"}]
    if tid == "equity":
        us_market = re.search(r"Wall Street|S&P|Nasdaq|Dow|US stocks|U[.]S[.] stocks|美股|道瓊|標普|那斯達克|華爾街", title, re.I)
        foreign = FOREIGN.search(title)
        if us_market and (not foreign or us_market.start() < foreign.start()):
            region_words = {"台股", "日股", "陸股", "港股", "歐股", "韓股", "日經", "恆生", "Nikkei", "Hang Seng", "FTSE", "DAX", "European stocks", "Asian stocks", "China stocks", "Japan stocks"}
            excludes = [k for k in excludes if k not in region_words]
    return any(hit(k, target) for k in excludes) or (
        tid in {"twf", "gold"} and re.search(r"(?<![A-Za-z])ETFs?(?![A-Za-z])", target, re.I) is not None)


def is_official_fed(article: dict) -> bool:
    hostname = (urlsplit(str(article.get("link") or "")).hostname or "").lower()
    return (hostname == "federalreserve.gov" or hostname.endswith(".federalreserve.gov")
            or str(article.get("source") or "").casefold() == "federal reserve")


def news_item_allowed(article: dict) -> bool:
    original_title=str(article.get("title") or "")
    foreign=FOREIGN.search(original_title)
    # Local daily gold quotes are not global bullion-market news.
    if foreign and foreign.start()<=12 and re.search(r"gold price today|gold prices? (?:in|today)|今日金價|當地金價",original_title,re.I):
        return False
    title=re.sub(r"\s+[-–—|]\s+[^|–—-]{1,60}$", "", str(article.get("title") or "")).strip()
    if title.casefold() in {"stocks","markets","news","business","finance","economy","stock market","股市","財經新聞"}:
        return False
    return not bool(re.search(r"\b(?:settlements|stock quote|stock quotes|market overview|products overview)\b|股票報價查詢|商品介紹|結算價格查詢",title,re.I))


def topic_allowed(tid: str, article: dict) -> bool:
    title = article.get("title") or ""
    text = " ".join(str(article.get(k) or "") for k in ("title", "summary", "body"))
    if tid == "funding":
        if re.search(r"tokeni[sz]ed|crypto|代幣化|加密資產",title,re.I) and re.search(r"launch|introduc|推出|發行",title,re.I):
            return False
        signals=("SOFR","IORB","SRF","ON RRP","repo","repurchase agreement","bank reserves","reverse repo",
                 "money market","money markets","money-market","dollar liquidity","overnight funding",
                 "funding stress","funding pressure","Treasury bills","T-bills","Treasury cash balance",
                 "market stress","資金市場","貨幣市場","美元流動性","隔夜利率","隔夜融資",
                 "短期融資","回購市場","回購利率","準備金","美國國庫券","短期美債","資金壓力")
        if not any(hit(k,text) for k in signals):
            return False
        foreign_signals=[m for m in (FOREIGN.search(title), re.search(
            r"Bank of England|\bBoE\b|\bRBI\b|\bECB\b|\bBOJ\b|gilt|英國央行|印度央行|歐洲央行|日本央行",title,re.I)) if m]
        foreign=min(foreign_signals,key=lambda m:m.start()) if foreign_signals else None
        us=US_CORE.search(title)
        if foreign and (not us or foreign.start()<us.start()):
            return False
        return bool(US_CORE.search(text) or is_official_fed(article)
                    or any(hit(k,text) for k in ("SOFR","IORB","SRF","ON RRP","US repo","U.S. repo")))
    if tid == "equity":
        market=re.search(r"Wall Street|S&P(?: 500)?|Nasdaq|Dow|US stocks|U[.]S[.] stocks|美股|道瓊|標普|那斯達克|華爾街",text,re.I)
        if not market:
            return False
        # A Wall Street employer or technology hub is not U.S. stock-market coverage.
        if re.search(r"fresh grads|graduates|hiring|tech hubs|investment bank jobs|畢業生|招聘|招募",title,re.I) and not re.search(r"stocks?|shares?|equities|\bDow\b|\bNasdaq\b|S&P|股市|股價|美股",title,re.I):
            return False
        foreign=FOREIGN.search(title)
        explicit_us=re.search(r"Wall Street|S&P|Nasdaq|Dow|US stocks|U[.]S[.] stocks|美股|道瓊|標普|那斯達克|華爾街",title,re.I)
        return not foreign or bool(explicit_us and explicit_us.start()<foreign.start())
    if tid == "election":
        electoral=re.search(r"midterms?|elections?|Senate race|House (?:race|control|majority)|Senate control|congressional race|voters?|campaign|polls?|期中選舉|中期選舉|國會選舉|競選|選情|選民|民調",text,re.I)
        us=re.search(r"United States|U[.]S[.]|(?<![A-Za-z])US(?![A-Za-z])|Trump|Republicans?|Democrats?|GOP|Congress|Senate|美國|川普|共和黨|民主黨|美國國會",text,re.I)
        foreign=FOREIGN.search(title)
        us_lead=US_CORE.search(title) or re.search(r"Trump|Republicans?|Democrats?|GOP|Congress|Senate|美國|川普|共和黨|民主黨",title,re.I)
        return bool(electoral and us and (not foreign or (us_lead and us_lead.start()<foreign.start())))
    if tid == "twf":
        return any(hit(k, title) for k in ("台指期", "臺指期", "台股", "臺股", "加權指數", "台灣股市", "臺灣股市", "TAIEX", "Taiwan stocks", "Taiwan futures", "TXF"))
    if tid in {"long", "fed"}:
        foreign_currency=re.search(r"British Pound|Canadian Dollar|Australian Dollar|Singapore Dollar|Hong Kong Dollar|\b(?:rupee|yuan|renminbi|yen|euro|pound|won|ringgit|baht)\b|英鎊|歐元|人民幣|港幣|韓元|泰銖|盧比|日圓|新加坡幣|澳幣|加幣",title,re.I)
        us_subject=US_CORE.search(title)
        if foreign_currency and (not us_subject or foreign_currency.start()<us_subject.start()):
            return False
        lead = title + " " + str(article.get("summary") or "")
        if not article.get("summary") and article.get("body"):
            lead += " " + str(article["body"])[:600]
        scope = ["美債", "美債殖利率"] if tid == "long" else ["Fed", "FOMC", "Kevin Warsh", "升息", "降息"]
        if tid == "fed":
            official = is_official_fed(article)
            explicit = any(hit(k, lead) for k in ALIASES["Fed"] + ALIASES["FOMC"] + ALIASES["Kevin Warsh"])
            if not official and not explicit and not US_CORE.search(lead):
                return False
        # A foreign local rate decision remains out even if a summary mentions the Fed.
        foreign = FOREIGN.search(title)
        local = re.search(r"central bank|rate cuts?|rate hikes?|RBI|inflation|央行|降息|升息|通膨", title, re.I)
        us = US_CORE.search(title)
        if tid == "fed" and foreign and foreign.start() <= 12 and local and (not us or us.start() > foreign.start()):
            return False
        return main_allowed({**article, "title": lead}, scope)
    if tid == "oil":
        currency=re.search(r"Canadian Dollar|Australian Dollar|British Pound|US Dollar|U[.]S[.] Dollar|United States Dollar|Taiwan Dollar|\b(?:rupee|yuan|yen|euro|pound)\b|美元|台幣|日圓|英鎊|加幣|澳幣|歐元",title,re.I)
        energy=re.search(r"oil|crude|WTI|Brent|OPEC|油價|原油|油輪|石油|能源供應",title,re.I)
        if currency and (not energy or currency.start()<energy.start()):
            return False
        # Conflict belongs to this topic only when energy supply/prices/transport are involved.
        return any(hit(k, text) for k in ("oil", "crude", "WTI", "Brent", "OPEC", "油價", "原油", "油輪", "能源供應", "energy supply", "oil tanker", "oil tankers", "oil exports", "石油", "石油出口"))
    if tid == "fx":
        if re.search(r"tuition|visa fee|salary|留美工作|留學|學費|簽證費",title,re.I) and not re.search(
                r"exchange rate|currency|forex|DXY|dollar index|匯率|匯市|美元(?:走強|走弱|升值|貶值)",title,re.I):
            return False
        # Require an exchange-rate subject, not a cash amount converted to TWD.
        fx_subject = (r"exchange rate|currenc(?:y|ies)|forex|FX market|DXY|dollar index|USD/TWD|USDTWD|"
                      r"Taiwan dollar|台幣|臺幣|匯率|匯市|匯價|外匯|"
                      r"美元(?:走強|走弱|上漲|下跌|指數|升值|貶值)|"
                      r"dollar (?:rises?|falls?|gains?|drops?|strengthens?|weakens?|firms?|rallies|steady|higher|lower|retreats?|advances?|surges?|slides?)")
        if not re.search(fx_subject,title,re.I):
            # Generic headlines may use a publisher lead that explicitly discusses FX.
            lead = str(article.get("summary") or "")[:600]
            rate_context = re.search(r"exchange rate|forex|FX market|DXY|dollar index|匯率|匯市|匯價|外匯|"
                                    r"(?:美元|台幣|臺幣)[^。；;]{0,15}(?:走強|走弱|升值|貶值)|"
                                    r"dollar (?:rises?|falls?|gains?|strengthens?|weakens?)",lead,re.I)
            if not rate_context:
                return False
        other = re.search(r"rupee|yuan|renminbi|won|ringgit|baht|Singapore dollar|Australian dollar|Canadian dollar|Hong Kong dollar|euro|pound|英鎊|歐元|人民幣|港幣|韓元|泰銖|盧比|新加坡幣|澳幣|加幣", title, re.I)
        focus = re.search(r"USD/TWD|USDTWD|TWD|Taiwan dollar|New Taiwan dollar|DXY|dollar index|(?<![A-Za-z])(?:U[.]?S[.]?\s+)?dollar(?:s)?(?![A-Za-z])|台幣|臺幣|新台幣|美元", title, re.I)
        if other and (not focus or other.start() < focus.start()):
            return False
        if any(hit(k, text) for k in ("USD/TWD", "USDTWD", "TWD", "Taiwan dollar", "New Taiwan dollar", "台幣", "臺幣", "新台幣", "DXY", "dollar index", "美元指數")):
            return True
        foreign = FOREIGN.search(title)
        other_fx = re.search(r"rupee|yuan|renminbi|won|ringgit|baht|Singapore dollar|Australian dollar|Canadian dollar|Hong Kong dollar|euro|pound|英鎊|歐元|人民幣|港幣|韓元|泰銖|盧比|新加坡幣|澳幣|加幣", title, re.I)
        if other_fx and (not foreign or other_fx.start() < foreign.start()):
            foreign = other_fx
        dollar = re.search(r"(?<![A-Za-z])(?:U[.]?S[.]?\s+)?dollar(?:s)?(?![A-Za-z])|美元", title, re.I)
        return bool(dollar and (not foreign or dollar.start() < foreign.start()))
    return True



def _name_alias_pattern(alias: str) -> str:
    # Chinese company aliases can also begin ordinary economic/technical words.
    guards = {
        "高通": r"(?!膨|[脹胀]|量(?!產|产)|透(?:性|光|明)|過率|过率|濾波|滤波)",
        "超微": r"(?!細|细|粒|型(?!號|号))",
    }
    return re.escape(alias) + guards.get(alias, "")


def english_names(text: str) -> str:
    text = text or ""
    for english, aliases in {**PERSON_NAMES, **COMPANY_NAMES}.items():
        alias_re = "(?:" + "|".join(_name_alias_pattern(a) for a in sorted(aliases, key=len, reverse=True)) + ")"
        variants = "(?:" + re.escape(english) + "|" + re.escape(english.split()[-1]) + ")"
        # Preserve existing English names, remove redundant bilingual parentheses.
        text = re.sub(r"(" + variants + r")\s*[（(]" + alias_re + r"[）)]", r"\1", text, flags=re.I)
        text = re.sub(alias_re + r"\s*[（(](" + variants + r")[）)]", r"\1", text, flags=re.I)
    replacements = sorted(((a, e) for e, aa in {**PERSON_NAMES, **COMPANY_NAMES}.items() for a in aa), key=lambda x:len(x[0]), reverse=True)
    pattern = re.compile("|".join(_name_alias_pattern(a) for a, _ in replacements))
    mapping = dict(replacements)
    if re.search(r"iPhone|iPad|MacBook|Tim Cook|庫克|蘋果(?:財報|股價|手機|新品|晶片)", text, re.I):
        text = text.replace("蘋果", "Apple")
    text = pattern.sub(lambda m: mapping[m.group()], text)
    return re.sub(r"(?<![A-Za-z])Nvidia(?![A-Za-z])", "NVIDIA", text, flags=re.I)


def display_news(result: dict) -> None:
    """Normalize generated, cached and fallback display fields; preserve URLs/data."""
    for key in ("text",):
        if isinstance(result.get(key), str):
            result[key] = english_names(result[key])
    for link in result.get("links") or []:
        link["title"] = english_names(link.get("title") or "")
    for topic in result.get("topics") or result.get("items") or []:
        topic["text"] = english_names(topic.get("text") or "")
        for link in topic.get("links") or []:
            link["title"] = english_names(link.get("title") or "")
