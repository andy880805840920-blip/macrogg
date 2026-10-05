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
import html
import time
import logging
import datetime as dt
from dataclasses import dataclass, field

import requests

from . import clock

log = logging.getLogger(__name__)

BASE = "https://www.federalreserve.gov"
TIMEOUT = 30
MAX_RETRIES = 3

STATEMENT_URL = BASE + "/newsevents/pressreleases/monetary{ymd}a.htm"
MINUTES_URL = BASE + "/monetarypolicy/fomcminutes{ymd}.htm"
PRESSER_URL = BASE + "/mediacenter/files/FOMCpresconf{ymd}.pdf"
CALENDAR_URL = BASE + "/monetarypolicy/fomccalendars.htm"
SEP_URL = BASE + "/monetarypolicy/fomcprojtabl{ymd}.htm"
ROSTER_URL = BASE + "/monetarypolicy/fomc.htm"
BOARD_URL = BASE + "/aboutthefed/bios/board/default.htm"
SPEECH_FEED_URL = BASE + "/feeds/speeches.xml"
FED_CALENDAR_JSON = BASE + "/json/calendar.json"
NEWS_URL = ("https://news.google.com/rss/search?q={q}"
            "&hl=en-US&gl=US&ceid=US:en")

# 投票段落的起點。
#
# 不能只找 "Voting for"：2026 年 6 月起（Warsh 上任後）聲明改版，
# 一致通過時不再列出贊成名單，有反對票時**只寫 "Voting against ..."**。
# 只認 "Voting for" 會讓這種聲明整段抓不到投票，反對票被讀成「一致」，
# 政策方向也跟著讀錯——反對票正是這份儀表板最重要的訊號。
# 所以改成比對「最早出現的任一種寫法」。
VOTE_RE = re.compile(r"Voting\s+(?:for|against)\b", re.I)


# 2026 年起的聲明在開頭就寫明票數：
#   "The Federal Open Market Committee approved the following statement
#    for release by a 9 – 3 vote:"
# 這是**唯一**會出現在一致通過聲明裡的票數（一致時沒有 Voting 段落），
# 所以不解析它就永遠只知道「沒有反對票」，不知道有幾個人投票。
# 破折號有多種字元（-、‑、–、—），要一起收。
# 主詞要一起吃掉，否則移除子句後會留下孤零零的
# 「The Federal Open Market Committee」黏在本文最前面。
PREAMBLE_VOTE_RE = re.compile(
    r"(?:the\s+)?federal open market committee\s+"
    r"approved the following statement for release by an?\s*"
    r"(\d+)\s*[-‐‑–—]\s*(\d+)\s*vote\s*:?\s*", re.I)


@dataclass
class Vote:
    supporting: list[str] = field(default_factory=list)
    dissents: list[dict] = field(default_factory=list)   # [{name, direction}]
    raw: str = ""
    stated_support: int | None = None    # 聲明引言寫的贊成票數
    stated_dissent: int | None = None    # 聲明引言寫的反對票數
    mismatch: bool = False               # 引言票數與反對票名單不一致

    @property
    def n_support(self) -> int:
        return self.stated_support if self.stated_support is not None \
            else len(self.supporting)

    @property
    def n_dissent(self) -> int:
        # 名單優先（有名字才知道方向）；一致通過時退回引言的數字
        return len(self.dissents) or (self.stated_dissent or 0)

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
        self._cal: str | None = None

    def calendar_html(self) -> str:
        """行事曆頁一次執行只抓一次（會議日期、未來會議、SEP、紀要都從這頁來）。"""
        if self._cal is None:
            self._cal = self._get(CALENDAR_URL) or ""
        return self._cal

    # ------------------------------------------------------------------
    def _get(self, url: str, binary: bool = False):
        last = None
        for attempt in range(MAX_RETRIES):
            try:
                r = self.session.get(url, timeout=TIMEOUT)
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                if binary:
                    return r.content
                # federalreserve.gov 的 Content-Type 不一定帶 charset。
                # 沒帶時 requests 依 RFC 對 text/* 退回 ISO-8859-1，
                # 頁面實際是 UTF-8，於是「12‑0」會變成「12â0」這種亂碼。
                if "charset" not in (r.headers.get("content-type") or "").lower():
                    r.encoding = r.apparent_encoding or "utf-8"
                return r.text
            except Exception as e:                # noqa: BLE001
                last = e
                if attempt < MAX_RETRIES - 1:
                    time.sleep(1.5 * (attempt + 1))
        self.failed.append((url, str(last)))
        return None

    # ------------------------------------------------------------------
    def meeting_dates(self, years_back: int = 4,
                      start: str | None = None) -> list[dt.date]:
        """
        取會議日期。start（YYYY-MM-DD）優先於 years_back。

        行事曆頁其實內嵌列出 2021–2027 年，所以起點設多早就會抓多早。
        抓太早的代價主要是速度（每份聲明一個請求）；「歷次決議」表與
        近 12 個月的反對票紀錄，從 2025 年起就夠用。
        """
        html = self.calendar_html()
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

        if start:
            try:
                cutoff = dt.date.fromisoformat(start)
            except ValueError:
                log.warning("fetch.start 格式錯誤（%s），改用 years_back", start)
                cutoff = clock.today() - dt.timedelta(days=365 * years_back)
        else:
            cutoff = clock.today() - dt.timedelta(days=365 * years_back)
        return sorted({d for d in dates if cutoff <= d <= clock.today()})

    # ------------------------------------------------------------------
    _MONTHS = {m: i for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"], 1)}

    def upcoming_meetings(self, n: int = 3) -> list[dt.date]:
        """
        接下來的 n 場會議。

        為什麼不能沿用 meeting_dates()
        ------------------------------
        那個函式抓的是「聲明連結」（monetaryYYYYMMDDa.htm），而未來的會議
        還沒有聲明，所以連結根本不存在——就算拿掉 `d <= today` 的過濾也抓不到。
        行事曆表格本身**有**列到明年（本文撰寫時列到 2027），
        所以這裡改成解析表格的「年份 → 月份 → 日期範圍」文字。

        會議通常橫跨兩天，聲明在**最後一天**收盤前發布，所以取範圍的後緣。

        解析失敗或結果不合理時回傳空清單，畫面上該區塊就不顯示——
        寧可少一個數字，也不要印一個錯的會議日期出去。
        """
        spans = self.upcoming_spans(n)
        return [b for _, b in spans]

    def upcoming_spans(self, n: int = 3) -> list[tuple[dt.date, dt.date]]:
        """接下來 n 場會議的 (第一天, 最後一天)。靜默期要用第一天推算。"""
        today = clock.today()
        out = [(a, b) for a, b in self.calendar_spans() if b > today]
        # 合理性檢查：下一場會議不可能在半年之後（一年開八次，間隔約 6–8 週）。
        # 抓到離譜的東西就整組丟掉，不要印出去。
        if not out or (out[0][1] - today).days > 180:
            log.warning("未來會議日期解析結果不合理，略過此區塊")
            return []
        return out[:n]

    def calendar_spans(self) -> list[tuple[dt.date, dt.date]]:
        """行事曆表格上每一場會議的 (第一天, 最後一天)，含已開過的。"""
        html = self.calendar_html()
        if not html:
            return []
        # 去標籤後只看文字，這樣官網改 class 或版型不會直接讓解析失效
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"&nbsp;?", " ", text)
        text = re.sub(r"\s+", " ", text)

        out: list[tuple[dt.date, dt.date]] = []
        months = "|".join(self._MONTHS)
        # 以「YYYY FOMC Meetings」切出各年度區塊，年份才不會張冠李戴
        blocks = list(re.finditer(r"(20\d{2})\s+FOMC\s+Meetings", text, re.I))
        for i, m in enumerate(blocks):
            year = int(m.group(1))
            seg = text[m.end(): blocks[i + 1].start() if i + 1 < len(blocks) else len(text)]
            # 「January 26-27」「March 16-17*」；跨月的「April 28-May 1」型式
            # 取後面那個月日（第二個分支）。「Note: A two-day meeting is
            # scheduled for January 25-26, 2028」是明年的預告，不屬於這一年，
            # 先從區塊裡切掉。
            seg = re.split(r"\bNote:", seg)[0]
            # 紀要的「(Released August 19, 2026)」與表決紀錄的
            # 「August 22 (notation vote)」都長得像單日會議，先拿掉
            seg = re.sub(r"\(Released[^)]*\)", " ", seg)
            seg = re.sub(r"\b(?:" + months + r")\s+\d{1,2}\s*\(notation vote\)", " ", seg)
            for mm in re.finditer(
                    r"\b(" + months + r")\b\s*"
                    r"(?:(\d{1,2})\s*[-–]\s*(?:(" + months + r")\s*)?"
                    r"(\d{1,2})|(\d{1,2}))\*?", seg):
                mon = self._MONTHS[mm.group(1)]
                try:
                    if mm.group(5):                       # 單日（含電話會議）
                        a = b = dt.date(year, mon, int(mm.group(5)))
                    elif mm.group(3):                     # 跨月
                        a = dt.date(year, mon, int(mm.group(2)))
                        b = dt.date(year, self._MONTHS[mm.group(3)], int(mm.group(4)))
                    else:                                  # 同月的日期範圍
                        a = dt.date(year, mon, int(mm.group(2)))
                        b = dt.date(year, mon, int(mm.group(4)))
                except ValueError:
                    continue
                out.append((a, b))
        return sorted(set(out), key=lambda x: x[1])

    @staticmethod
    def _guess_dates(years_back: int) -> list[dt.date]:
        out, this_year = [], clock.today().year
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
        full = extract_text(html)
        policy, vote_text = split_statement(full)

        # 引言的票數要抽出來單獨處理，並從本文移除。
        # 留在本文裡的話，逐句比對的第一列會變成一整段，
        # 而真正變動的只有票數兩個數字——那是投票資訊，不是措辭改動。
        vote = parse_votes(vote_text)
        m = PREAMBLE_VOTE_RE.search(policy)
        if m:
            vote.stated_support = int(m.group(1))
            vote.stated_dissent = int(m.group(2))
            policy = PREAMBLE_VOTE_RE.sub("", policy, count=1).strip()
            # 不能加 vote.dissents 的前置條件——「引言寫 3 張反對票、
            # 名單卻解析出 0 位」正是最需要示警的解析失敗。
            if len(vote.dissents) != vote.stated_dissent:
                vote.mismatch = True
                log.warning("%s 引言寫 %d 張反對票，但解析出 %d 位反對者",
                            d, vote.stated_dissent, len(vote.dissents))

        # 內容健全性檢查：真正的政策聲明一定會提到政策工具或政策行動。
        # 只檢查 Committee 不夠，行事曆頁也會連到長期策略框架公告；那類公告
        # 曾被誤算成一次 FOMC 利率會議，污染歷史次數與文字長度基準。
        low = policy.lower()
        policy_markers = ("target range", "federal funds rate",
                          "monetary policy action")
        if not any(marker in low for marker in policy_markers):
            log.warning("%s 抓到的內容不像聲明（缺 Committee／target range），跳過", d)
            self.failed.append((STATEMENT_URL.format(ymd=d.strftime("%Y%m%d")),
                                "內容不像聲明，可能是頁面改版"))
            return None

        # 門檻設低一點：Warsh 任內的聲明明顯變短，
        # 用 Powell 時代的長度當門檻會把正常聲明整份丟掉。
        if len(policy) < 200:
            log.warning("%s 的聲明本文只有 %d 字元，視為抓取失敗並跳過",
                        d, len(policy))
            self.failed.append((STATEMENT_URL.format(ymd=d.strftime("%Y%m%d")),
                                f"本文過短（{len(policy)} 字元）"))
            return None
        return {"date": d.isoformat(), "text": policy,
                "vote_text": vote_text, "vote": vote.__dict__}

    def presser(self, d: dt.date) -> tuple[str | None, str | None]:
        """
        記者會逐字稿（PDF）。回傳 (逐字稿, 取不到的原因)。

        原因要往上傳，因為三種情況對讀者的意義完全不同：
          pending      — 還沒發布（會後數日才有），之後會自動補上
          no_pdfplumber— 環境缺套件，不裝就永遠不會有
          parse_failed — 抓到了但解析失敗
        以前一律當成「延遲取得」，缺套件時畫面會謊稱「發布後會自動補上」。
        """
        url = PRESSER_URL.format(ymd=d.strftime("%Y%m%d"))
        raw = self._get(url, binary=True)
        if not raw:
            return None, "pending"
        try:
            import io
            import pdfplumber
            with pdfplumber.open(io.BytesIO(raw)) as pdf:
                pages = [p.extract_text() or "" for p in pdf.pages]
            return re.sub(r"\s+", " ", " ".join(pages)).strip(), None
        except ImportError:
            log.warning("未安裝 pdfplumber，略過記者會逐字稿"
                        "（請確認 requirements.txt 已安裝）")
            self.failed.append((url, "未安裝 pdfplumber"))
            return None, "no_pdfplumber"
        except Exception as e:                    # noqa: BLE001
            log.warning("記者會 PDF 解析失敗 %s：%s", d, e)
            self.failed.append((str(d), f"PDF 解析失敗：{e}"))
            return None, "parse_failed"

    # ------------------------------------------------------------------
    def collect(self, years_back: int = 4, with_presser: bool = True,
                start: str | None = None, presser_recent_n: int = 4) -> list[dict]:
        """回傳 [{date, text, vote_text, vote, presser}]，時間升冪。"""
        out = []
        dates = self.meeting_dates(years_back, start=start)
        log.info("會議日期 %d 場（%s 起）", len(dates),
                 start or f"近 {years_back} 年")
        for i, d in enumerate(dates):
            st = self.statement(d)
            if not st:
                continue
            # 記者會只抓最近幾場，避免一次拉太多 PDF
            if with_presser and i >= len(dates) - presser_recent_n:
                st["presser"], st["presser_error"] = self.presser(d)
            out.append(st)
            time.sleep(0.4)
        return out


    # ------------------------------------------------------------------
    # 聯準會頁的事實層（2026-10）：SEP／點陣圖、會議紀要、委員名單、
    # 官員演講與行程。每一項各自失敗、各自缺席，不擋主流程。
    # ------------------------------------------------------------------
    def extras(self) -> dict:
        from .analysis import fomc_extra as fx
        today = clock.today()
        cal = self.calendar_html()
        out: dict = {"spans": self.upcoming_spans(4)}

        # SEP：行事曆頁上「今天以前」最新的一份網頁版預測
        idx = [d for d in fx.sep_index(cal) if d <= today.strftime("%Y%m%d")]
        if idx:
            ymd = idx[-1]
            h = self._get(SEP_URL.format(ymd=ymd))
            sep = fx.parse_sep(h or "", f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}")
            if sep:
                out["sep"] = sep
                log.info("SEP：%s（%s 年底利率中位數 %s）", sep["date"],
                         sep["years"][0], sep["vars"]["ffr"]["median"][0])
            else:
                log.warning("SEP 網頁版解析失敗（%s），點陣圖本次不顯示", ymd)

        # 會議紀要：已公布的最新一份
        mi = fx.minutes_index(cal)
        if mi:
            last = mi[-1]
            h = self._get(last["url"])
            parsed = fx.parse_minutes(h or "")
            if parsed:
                out["minutes"] = {**last, **parsed}
                log.info("會議紀要：%s 會議（%s 公布），量詞句 %d 則",
                         last["meeting"], last["released"], len(parsed["rows"]))
            else:
                log.warning("會議紀要解析失敗（%s）", last["url"])

        # 委員名單與理事職稱
        roster = fx.parse_roster(self._get(ROSTER_URL) or "")
        if roster:
            out["roster"] = roster
            out["board_titles"] = fx.parse_board_titles(self._get(BOARD_URL) or "")
        else:
            log.warning("FOMC 委員名單解析失敗，委員區本次不顯示")

        out["speeches"] = fx.parse_speech_feed(self._get(SPEECH_FEED_URL) or "")
        out["events"] = fx.parse_calendar_json(self._get(FED_CALENDAR_JSON) or "")
        return out

    def news(self, officials: list, days: int = 14) -> dict:
        """
        官員的近期新聞標題（Google News RSS）：{姓: [{title, source, date, url}]}。
        只查投票委員。地方總裁沒有統一的官方演講來源，這是唯一的管道；
        失敗就不顯示，不記進「資料來源失敗」清單（不是官方資料）。
        """
        from concurrent.futures import ThreadPoolExecutor
        from urllib.parse import quote_plus
        from .analysis import fomc_extra as fx

        def one(o):
            parts = o["name"].split()
            q_name = f"{parts[0]} {parts[-1]}" if len(parts) > 1 else o["name"]
            url = NEWS_URL.format(q=quote_plus(f'"{q_name}" Fed when:{days}d'))
            try:
                r = self.session.get(url, timeout=15,
                                     headers={"User-Agent": "Mozilla/5.0 (macro-dashboard)"})
                if r.status_code != 200:
                    return o["surname"], []
                return o["surname"], fx.parse_news_rss(r.text, o["surname"])
            except Exception as e:                    # noqa: BLE001
                log.info("官員新聞抓取失敗（%s）：%s", o["surname"], e)
                return o["surname"], []

        targets = [o for o in officials if o.get("voter")]
        with ThreadPoolExecutor(max_workers=4) as ex:
            return {k: v for k, v in ex.map(one, targets) if v}


# ---------------------------------------------------------------------------
# 文字處理
# ---------------------------------------------------------------------------
# 新聞稿頁面裡不屬於聲明本文的段落。不濾掉的話，「Share」按鈕、
# 發布時間、媒體聯絡方式會被黏進本文，變成
# 「edt share the federal open market committee approved…」這種句子，
# 還會每期都被逐句比對當成「整句刪除」的雜訊。
_DROP_PARA = re.compile(
    r"^\s*(share|print|email|facebook|linkedin|youtube|twitter|x|rss)\s*$"
    r"|^\s*for\s+(immediate\s+)?release"      # 「For release at 2:00 p.m. EDT」
    r"|^\s*for\s+media\s+inquiries"
    r"|^\s*(last\s+update|last\s+modified)"
    r"|email\W{0,3}protected"                # Cloudflare 信箱混淆
    r"|^\s*implementation\s+note"
    r"|^\s*board\s+of\s+governors\b"
    r"|^\s*\d{3}-\d{3}-\d{4}\s*$",
    re.I,
)


# 只有日期的段落（新聞稿的發布日期行）。留著會被當成內文，
# 兩份聲明比對時就冒出「刪除 June 17 → 新增 July 29」這種假改動。
_DATE_ONLY = re.compile(
    r"^\s*(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},?\s+\d{4}\s*$", re.I)


def _is_prose(t: str) -> bool:
    """
    判斷一段文字是「句子」還是導覽選單那種標題片語的堆疊。

    聯準會頁面的側邊選單長這樣（全部連在一起、沒有句號、幾乎每個字大寫）：
        Federal Open Market Committee Monetary Policy Principles and Practice
        Policy Implementation Reports Review of Monetary Policy Strategy ...
    聲明本文則是正常英文句子：句號多、大寫字少。用這兩個特徵就分得開。
    """
    words = t.split()
    if len(words) < 4:
        return False
    if "." in t:                      # 有句號就當成句子
        return True
    caps = sum(1 for w in words if w[:1].isupper())
    return caps / len(words) <= 0.5


def extract_text(html_doc: str) -> str:
    html_doc = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html_doc)

    # 段落比對不能寫成 <p...>(.*?)</p>。聯準會的頁面有**未閉合的 <p>**，
    # 非貪婪比對會從那個 <p> 一路吃到下一個 </p>，把整個側邊導覽選單
    # 當成內文吞進來。改成「遇到下一個 <p 或 </p 就停」，避免跨區吸入。
    paras = re.findall(r"(?is)<p[^>]*>((?:(?!</?p[\s/>]).)*)", html_doc)

    kept = []
    for p in paras:
        t = re.sub(r"(?s)<[^>]+>", " ", p)
        # 用標準函式一次處理所有 HTML 實體：先前只換 4 種，
        # 像 &#160;（不斷行空格）這種數字實體會原樣留在畫面上。
        t = html.unescape(t)
        t = re.sub(r"\s+", " ", t).strip()
        if not t or _DROP_PARA.search(t) or _DATE_ONLY.match(t):
            continue
        if not _is_prose(t):
            continue
        kept.append(t)

    return " ".join(_statement_span(kept)).strip()


# 聲明本文一定會提到委員會、目標區間或投票；頁面上其他的散文段落
# （相關新聞連結、頁尾說明、免責聲明）不會同時具備這些特徵。
_CORE = re.compile(
    r"\bcommittee\b|\btarget range\b|\bfederal funds rate\b|\bvoting\b",
    re.I)


def _statement_span(paras: list[str]) -> list[str]:
    """
    從所有散文段落中，只取「聲明本文」那一段連續範圍。

    先前是把整頁通過過濾的段落全部串起來，所以任何漏網的雜訊
    （相關報導連結、頁尾聲明、其他新聞稿摘要）都會被當成聲明內容，
    然後在逐句比對裡冒出來。

    改成鎖定範圍：從第一個提到委員會／目標區間的段落，
    到最後一個提到的段落為止，中間全收（政策段落之間可能有不含
    關鍵詞的句子），兩端以外一律丟掉。
    """
    idx = [i for i, t in enumerate(paras) if _CORE.search(t)]
    if not idx:
        return []
    return paras[idx[0]:idx[-1] + 1]


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
            v.dissents.extend(_dissenters(body))
    return v


def _dissenters(body: str) -> list[dict]:
    """
    解析反對者，**逐位**判定方向。

    不能整段共用一個方向。實際出現過的寫法：

        Voting against were A, who preferred to raise the target range,
        and B, who preferred to lower the target range.

    整段判定會讓兩人都變成「主張升息」，鷹鴿淨值算成 +2，正確是 0。
    而且原本用 split(",?\\s*who")[0] 只取第一段，B 會整個消失。

    做法：先在每個「姓名, who ...」的邊界切開，每一塊各自判定方向；
    切不出來（沒有 who 子句）時退回整段共用一個方向。
    """
    # 只有一個 who 子句時，整段的人共用同一個方向（三人同時主張升息就是這種）。
    if len(re.findall(r"\bwho\b", body, re.I)) <= 1:
        d = _direction(body)
        return [{"name": n, "direction": d} for n in _names(body)]

    # 多個 who 子句 → 每位反對者方向可能不同，要逐段判定。
    # 先在「, and 大寫字」處切開，再往後累積到出現 who 為止才算一組——
    # 因為「A, B, and C, who preferred…」的前半段沒有 who，
    # 不累積的話 A 與 B 會整個消失。
    parts = re.split(r",?\s+and\s+(?=[A-Z])", body)
    out: list[dict] = []
    buf = ""
    for p in parts:
        buf = f"{buf} and {p}" if buf else p
        if not re.search(r"\bwho\b", buf, re.I):
            continue
        names = _names(buf)
        if names:
            d = _direction(buf)
            out.extend({"name": n, "direction": d} for n in names)
        buf = ""

    if buf:                                   # 尾段沒有 who，仍要收進來
        d = _direction(body)
        out.extend({"name": n, "direction": d} for n in _names(buf))
    return out


def _direction(chunk: str) -> str:
    low = chunk.lower()
    # 2025-03 Waller：「supported no change for the federal funds target range
    # but preferred to continue the current pace of decline in securities
    # holdings」——反對的是資產負債表，不是利率。要先擋，否則會被讀成「維持」。
    # 2026-04 Hammack 等三位：「supported maintaining the target range ... but did
    # not support inclusion of an easing bias in the statement」——同意利率決定、
    # 反對的是聲明措辭。這類「支持 X，但 Y」先分出來，不能當成「主張維持」。
    if re.search(r"supported (?:maintaining|no change|the (?:decision|action))", low) \
            and re.search(r"\bbut\b", low):
        if re.search(r"securities holdings|balance sheet|runoff", low):
            return "balance_sheet"
        if re.search(r"easing bias", low):
            return "no_easing_bias"
        return "unknown"
    if re.search(r"\b(raise|raising|increase|increasing|higher)\b", low):
        return "hike"
    if re.search(r"\b(lower|lowering|reduce|reducing|decrease|cut)\b", low):
        return "cut"
    # 「preferred to maintain the target range」— 在委員會行動時主張按兵不動。
    # 不辨識這種寫法的話，這張反對票會變成 unknown，畫面上整格空白。
    # 「preferred no change to the target range」（2025-10、2025-12 的 Schmid、
    # Goolsbee）先前漏掉，被讀成 unknown
    if re.search(r"\b(maintain|maintaining|keep|keeping|unchanged|pause)\b|no change", low):
        return "hold"
    return "unknown"


# 投票段落裡會出現、但不是人名的職稱。
# 「Vice Chair」剛好是兩個首字大寫的詞，會通過人名判定，
# 讓 Powell 時代每份聲明的贊成票數都多算一票。
_TITLES = {
    "chair", "vice chair", "vice chairman", "chairman",
    "vice chair for supervision", "chair pro tempore",
}


def _names(chunk: str) -> list[str]:
    """從一段人名字串抽出姓名。"""
    chunk = re.split(r",?\s*who\b", chunk)[0]
    out = []
    for p in re.split(r";|\band\b|,", chunk):
        p = p.strip(" .,;\n")
        if p.lower() in _TITLES:
            continue
        toks = p.split()
        # 姓名：2–5 個詞、每個詞首字大寫（涵蓋 "Kevin M. Warsh"）
        if 2 <= len(toks) <= 5 and all(t and t[0].isupper() for t in toks):
            out.append(p)
    return out
