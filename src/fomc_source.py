"""
FOMC 文件擷取（P3）。

來源都是 federalreserve.gov 的公開頁面，URL 結構穩定：

    聲明      /newsevents/pressreleases/monetary{YYYYMMDD}a.htm
    會議紀錄  /monetarypolicy/fomcminutes{YYYYMMDD}.htm
    記者會    /mediacenter/files/FOMCpresconf{YYYYMMDD}.pdf
    行事曆    /monetarypolicy/fomccalendars.htm

⚠️ 完整逐字稿（transcripts）依規定延後五年公布，四年內拿不到。

⚠️ 設計上的重要修正
-------------------
先前版本把「投票名單」整段截掉，理由是「名單變動與政策立場無關」。
那是錯的——**反對票的方向與票數是整份文件最強的政策訊號**，
而且完全不受主席的溝通風格影響。

2026 年 7 月就是例子：聲明措辭被刻意縮短、前瞻指引被移除，
純看措辭會誤判成偏鴿；但當次有三位官員投下贊成升息的反對票，
市場也確實讀成偏鷹。所以投票段落現在**單獨保留並解析**。
"""

from __future__ import annotations

import re
import time
import logging
import datetime as dt
from dataclasses import dataclass, field

import requests

log = logging.getLogger(__name__)

BASE = "https://www.federalreserve.gov"
TIMEOUT = 30
MAX_RETRIES = 3

STATEMENT_URL = BASE + "/newsevents/pressreleases/monetary{ymd}a.htm"
MINUTES_URL = BASE + "/monetarypolicy/fomcminutes{ymd}.htm"
PRESSER_URL = BASE + "/mediacenter/files/FOMCpresconf{ymd}.pdf"
CALENDAR_URL = BASE + "/monetarypolicy/fomccalendars.htm"

# 投票段落的起點。
#
# 不能只找 "Voting for"：2026 年 6 月起（Warsh 上任後）聲明改版，
# 一致通過時不再列出贊成名單，有反對票時**只寫 "Voting against ..."**。
# 只認 "Voting for" 會讓這種聲明整段抓不到投票，反對票被讀成「一致」，
# 客觀訊號分數因此歸零——那正好是這份儀表板最重要的訊號。
# 所以改成比對「最早出現的任一種寫法」。
VOTE_RE = re.compile(r"Voting\s+(?:for|against)\b", re.I)


@dataclass
class Vote:
    supporting: list[str] = field(default_factory=list)
    dissents: list[dict] = field(default_factory=list)   # [{name, direction}]
    raw: str = ""

    @property
    def n_support(self) -> int:
        return len(self.supporting)

    @property
    def n_dissent(self) -> int:
        return len(self.dissents)

    @property
    def hawkish_dissents(self) -> int:
        return sum(1 for d in self.dissents if d["direction"] == "hike")

    @property
    def dovish_dissents(self) -> int:
        return sum(1 for d in self.dissents if d["direction"] == "cut")


class FomcSource:
    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "macro-dashboard/1.0"})
        self.failed: list[tuple[str, str]] = []

    # ------------------------------------------------------------------
    def _get(self, url: str, binary: bool = False):
        last = None
        for attempt in range(MAX_RETRIES):
            try:
                r = self.session.get(url, timeout=TIMEOUT)
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                return r.content if binary else r.text
            except Exception as e:                # noqa: BLE001
                last = e
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1.5 * (attempt + 1))
        self.failed.append((url, str(last)))
        return None

    # ------------------------------------------------------------------
    def meeting_dates(self, years_back: int = 4) -> list[dt.date]:
        html = self._get(CALENDAR_URL)
        dates: list[dt.date] = []
        if html:
            for m in re.finditer(r"monetary(\d{8})a\.htm", html):
                try:
                    dates.append(dt.datetime.strptime(m.group(1), "%Y%m%d").date())
                except ValueError:
                    continue
        if not dates:
            log.warning("行事曆抓取失敗，改用推估日期（由 404 過濾）")
            dates = self._guess_dates(years_back)

        cutoff = dt.date.today() - dt.timedelta(days=365 * years_back)
        return sorted({d for d in dates if cutoff <= d <= dt.date.today()})

    @staticmethod
    def _guess_dates(years_back: int) -> list[dt.date]:
        out, this_year = [], dt.date.today().year
        for y in range(this_year - years_back, this_year + 1):
            for mth, day in [(1, 29), (3, 19), (5, 7), (6, 18),
                             (7, 30), (9, 17), (11, 5), (12, 17)]:
                try:
                    out.append(dt.date(y, mth, day))
                except ValueError:
                    pass
        return out

    # ------------------------------------------------------------------
    def statement(self, d: dt.date) -> dict | None:
        """回傳 {date, text, vote_text, vote}"""
        html = self._get(STATEMENT_URL.format(ymd=d.strftime("%Y%m%d")))
        if html is None:
            return None
        policy, vote_text = split_statement(extract_text(html))
        if len(policy) < 300:
            return None
        return {"date": d.isoformat(), "text": policy,
                "vote_text": vote_text, "vote": parse_votes(vote_text).__dict__}

    def presser(self, d: dt.date) -> str | None:
        """
        記者會逐字稿（PDF）。會後幾天才發布，所以當天抓不到是正常的。
        需要 pdfplumber；沒安裝就跳過，不影響其他功能。
        """
        raw = self._get(PRESSER_URL.format(ymd=d.strftime("%Y%m%d")), binary=True)
        if not raw:
            return None
        try:
            import io
            import pdfplumber
            with pdfplumber.open(io.BytesIO(raw)) as pdf:
                pages = [p.extract_text() or "" for p in pdf.pages]
            return re.sub(r"\s+", " ", " ".join(pages)).strip()
        except ImportError:
            log.warning("未安裝 pdfplumber，略過記者會逐字稿")
            self.failed.append((PRESSER_URL.format(ymd=d.strftime("%Y%m%d")),
                               "未安裝 pdfplumber"))
            return None
        except Exception as e:                    # noqa: BLE001
            log.warning("記者會 PDF 解析失敗 %s：%s", d, e)
            self.failed.append((str(d), f"PDF 解析失敗：{e}"))
            return None

    # ------------------------------------------------------------------
    def collect(self, years_back: int = 4, with_presser: bool = True) -> list[dict]:
        """回傳 [{date, text, vote_text, vote, presser}]，時間升冪。"""
        out = []
        dates = self.meeting_dates(years_back)
        for i, d in enumerate(dates):
            st = self.statement(d)
            if not st:
                continue
            # 記者會只抓最近幾場，避免一次拉太多 PDF
            if with_presser and i >= len(dates) - 4:
                st["presser"] = self.presser(d)
            out.append(st)
            time.sleep(0.4)
        return out


# ---------------------------------------------------------------------------
# 文字處理
# ---------------------------------------------------------------------------
def extract_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    paras = re.findall(r"(?is)<p[^>]*>(.*?)</p>", html)
    text = " ".join(re.sub(r"(?s)<[^>]+>", " ", p) for p in paras)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&#39;", "'").replace("&quot;", '"'))
    return re.sub(r"\s+", " ", text).strip()


def split_statement(text: str) -> tuple[str, str]:
    """
    切成 (政策段落, 投票段落)。兩段都要保留。

    切點取「Voting for」與「Voting against」之中最早出現的那個，
    因為新版聲明可能只有後者（見 VOTE_RE 的說明）。
    """
    m = VOTE_RE.search(text)
    if m:
        return text[:m.start()].strip(), text[m.start():].strip()
    return text, ""


def parse_votes(vote_text: str) -> Vote:
    """
    從投票段落解析支持者與反對者。

    聯準會的寫法長年固定：
        Voting for the monetary policy action were A; B; C; ...
        Voting against this action were D and E, who preferred to raise
        the target range ...

    方向判定看動詞：raise / increase → 贊成升息（鷹）
                    lower / reduce / cut → 贊成降息（鴿）

    注意人名含縮寫（"Kevin M. Warsh"），所以不能用句號當分隔——
    要切在分號、and 與逗號上，並先移除 ", who preferred..." 的解釋子句。
    """
    v = Vote(raw=vote_text)
    if not vote_text:
        return v

    for part in re.split(r"(?=Voting\s+(?:for|against))", vote_text):
        if re.match(r"\s*Voting\s+for", part, re.I):
            body = re.sub(r"^\s*Voting\s+for[^;]*?\b(?:were|was)\s+", "",
                          part, flags=re.I)
            v.supporting = _names(body)
        elif re.match(r"\s*Voting\s+against", part, re.I):
            body = re.sub(r"^\s*Voting\s+against[^;]*?\b(?:were|was)\s+", "",
                          part, flags=re.I)
            direction = _direction(body)
            for n in _names(body):
                v.dissents.append({"name": n, "direction": direction})
    return v


def _direction(chunk: str) -> str:
    low = chunk.lower()
    if re.search(r"\b(raise|raising|increase|increasing|higher)\b", low):
        return "hike"
    if re.search(r"\b(lower|lowering|reduce|reducing|decrease|cut)\b", low):
        return "cut"
    # 「preferred to maintain the target range」— 在委員會行動時主張按兵不動。
    # 不辨識這種寫法的話，這張反對票會變成 unknown，畫面上整格空白。
    if re.search(r"\b(maintain|maintaining|keep|keeping|unchanged|pause)\b", low):
        return "hold"
    return "unknown"


def _names(chunk: str) -> list[str]:
    """從一段人名字串抽出姓名。"""
    chunk = re.split(r",?\s*who\b", chunk)[0]
    out = []
    for p in re.split(r";|\band\b|,", chunk):
        p = p.strip(" .,;\n")
        toks = p.split()
        # 姓名：2–5 個詞、每個詞首字大寫（涵蓋 "Kevin M. Warsh"）
        if 2 <= len(toks) <= 5 and all(t and t[0].isupper() for t in toks):
            out.append(p)
    return out
