"""One publisher preference policy for the main story and every news topic."""
from __future__ import annotations
import re
from urllib.parse import urlparse

# Tier 2 is the user's strongest preference; tier 1 is the other requested media.
PUBLISHERS = (
    ("Bloomberg", 2, ("bloomberg.com",), ("Bloomberg", "Bloomberg.com", "彭博", "彭博社")),
    ("Reuters", 2, ("reuters.com",), ("Reuters", "Reuters.com", "路透", "路透社")),
    ("Yahoo Finance", 2, ("finance.yahoo.com",), ("Yahoo Finance", "Yahoo! Finance", "Yahoo Finance UK", "Yahoo Finance Canada", "Yahoo! Finance Canada", "Yahoo Finance Australia", "Yahoo Finance Singapore", "Yahoo Finance New Zealand")),
    ("Financial Times", 1, ("ft.com",), ("Financial Times", "FT", "金融時報")),
    ("WSJ", 1, ("wsj.com", "feeds.a.dj.com"), ("WSJ", "Wall Street Journal", "The Wall Street Journal", "華爾街日報")),
    ("The Economist", 1, ("economist.com",), ("The Economist", "Economist", "經濟學人")),
    ("Yahoo奇摩財經", 1, ("tw.news.yahoo.com",), ("Yahoo財經", "Yahoo奇摩財經", "Yahoo奇摩新聞", "Yahoo新聞", "Yahoo News Taiwan")),
    ("Yahoo奇摩股市", 1, ("tw.stock.yahoo.com",), ("Yahoo股市", "Yahoo奇摩股市", "Yahoo Stock Taiwan")),
    ("鉅亨網", 1, ("cnyes.com",), ("鉅亨網", "鉅亨", "Anue", "Anue鉅亨", "Anue鉅亨網")),
    ("經濟日報", 1, ("money.udn.com",), ("經濟日報", "經濟日報聯合新聞網", "Economic Daily News")),
    ("工商時報", 1, ("ctee.com.tw",), ("工商時報", "工商財經網", "Commercial Times")),
)

def _norm(value):
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", str(value or "").casefold())

def _by_source(source):
    name = _norm(source)
    return next((p for p in PUBLISHERS if name and any(name == _norm(a) for a in p[3])), None)

def _by_url(url):
    try: host = (urlparse(str(url or "")).hostname or "").lower().rstrip(".")
    except ValueError: return None
    return next((p for p in PUBLISHERS if any(host == d or host.endswith("." + d) for d in p[2])), None)

def publisher(article):
    # Original publisher metadata is kept when a blocked original uses a public copy.
    found = [_by_source(article.get("original_source")), _by_source(article.get("source")),
             _by_url(article.get("link")), _by_url(article.get("original_link"))]
    return max((p for p in found if p), key=lambda p: p[1], default=None)

def priority(article):
    p = publisher(article)
    return p[1] if p else 0

def weight(article):
    return {2: 3.0, 1: 1.5, 0: 0.0}[priority(article)]

def label(article):
    actual = _by_source(article.get("source")) or _by_url(article.get("link"))
    actual_name = actual[0] if actual else str(article.get("source") or "新聞報導")
    original = _by_source(article.get("original_source"))
    if original and original[0] != actual_name:
        return original[0] + "（" + actual_name + "轉載）"
    return actual_name

SOURCE_RULE = (
    "新聞來源順序：最優先使用 Bloomberg、Reuters、Yahoo Finance；其次是 Financial Times、WSJ、"
    "The Economist、Yahoo奇摩財經、Yahoo奇摩股市、鉅亨網、經濟日報、工商時報。"
    "先確認主題、時間與正文細節合格，再依此來源順序選擇；偏好來源缺少合格內容時才用其他來源。"
    "同篇轉載若標明原始通訊社，保留該通訊社及實際轉載媒體資訊；不可把轉載寫成獨立佐證。"
)

PRIMARY_DOMAINS = ("bloomberg.com", "reuters.com", "finance.yahoo.com")
SECONDARY_EN = ("ft.com", "wsj.com", "economist.com")
SECONDARY_ZH = ("tw.news.yahoo.com", "tw.stock.yahoo.com", "news.cnyes.com", "money.udn.com", "ctee.com.tw")

def site_query(domains):
    return "(" + " OR ".join("site:" + d for d in domains) + ")"

# These searches use the same approved topics, not broader article eligibility.
TOPIC_QUERIES = {
    "fed": ("(Fed OR FOMC OR \"Federal Reserve\")", "(聯準會 OR 升息 OR 降息)"),
    "long": ("(Treasury OR Treasuries OR \"US bonds\")", "(美債 OR 美國公債 OR 公債標售)"),
    "funding": ("(SOFR OR repo OR \"bank reserves\" OR \"money market\" OR \"market stress\") (Fed OR US OR dollar)", "美國 (回購市場 OR 貨幣市場 OR 美元流動性 OR 國庫券)"),
    "oil": ("(oil OR crude OR OPEC OR \"Iran conflict\")", "(油價 OR 原油 OR 中東戰爭 OR 美伊衝突)"),
    "equity": ("(\"Wall Street\" OR Nasdaq OR \"S&P 500\" OR Dow)", "美股 (道瓊 OR 標普 OR 那斯達克 OR 華爾街)"),
    "semi": ("(Nvidia OR semiconductor OR \"AI capex\" OR \"data center\")", "(AI OR 半導體 OR NVIDIA OR 台積電 OR 資料中心)"),
    "twf": ("(\"Taiwan futures\" OR \"Taiwan stocks\" OR TAIEX)", "(台指期 OR 臺指期 OR 台股 OR 加權指數) (夜盤 OR 外資 OR 收盤)"),
    "election": ("(\"midterm elections\" OR \"Senate race\" OR \"House majority\")", "美國 (期中選舉 OR 中期選舉 OR 國會選舉)"),
    "gold": ("(\"gold prices\" OR bullion OR \"gold futures\")", "(黃金 OR 金價)"),
    "fx": ("(\"Taiwan dollar\" OR \"dollar index\" OR \"US dollar\")", "(台幣 OR 新台幣 OR 美元指數 OR 美元匯率)"),
}

def priority_searches(spec):
    queries = TOPIC_QUERIES.get(spec.get("id"))
    if not queries: return []
    en, zh = queries
    return [{"q": en + " " + site_query(PRIMARY_DOMAINS), "lang": "en", "preferred_sources":True},
            {"q": en + " " + site_query(SECONDARY_EN), "lang": "en", "preferred_sources":True},
            {"q": zh + " " + site_query(SECONDARY_ZH), "lang": "zh", "preferred_sources":True}]


def main_searches():
    # Keep each query short: overlong OR expressions can lose Google's site constraint.
    english = (
        '(Fed OR FOMC OR inflation OR CPI OR PCE OR payrolls OR unemployment OR GDP OR Trump OR tariffs)',
        '(Treasury OR dollar OR yen OR BOJ OR Warsh OR "bond issuance")',
        '(AI OR Nvidia OR semiconductor OR oil OR Iran OR Ukraine OR gold)',
    )
    chinese = (
        '(聯準會 OR CPI OR 通膨 OR 非農 OR 川普 OR 關稅)',
        '(美債 OR 美元 OR 日本央行 OR 日圓 OR 發債)',
        '(AI OR 半導體 OR 油價 OR 伊朗 OR 中東 OR 俄烏 OR 黃金)',
    )
    return [{"q":query+" "+site_query(domains), "lang":lang, "preferred_sources":True}
            for terms,domains,lang in ((english,PRIMARY_DOMAINS,"en"),
                (english,SECONDARY_EN,"en"),(chinese,SECONDARY_ZH,"zh")) for query in terms]


def reserve_body_candidates(ranked, n):
    """Bound reads while retaining lower-tier options when preferred sites fail."""
    if n < 3: return ranked[:n]
    primary = n // 2 if n >= 8 else n - 2
    remaining = n - primary
    budgets = {2: primary, 1: (remaining + 1) // 2, 0: remaining // 2}
    chosen = []
    for tier in (2, 1, 0):
        chosen += [a for a in ranked if priority(a) == tier][:budgets[tier]]
    included = {a["link"] for a in chosen}
    chosen += [a for a in ranked if a["link"] not in included][:n-len(chosen)]
    # Retrieval attempts still visit stronger preferences first.
    order = {a["link"]: i for i, a in enumerate(ranked)}
    return sorted(chosen, key=lambda a: order[a["link"]])
