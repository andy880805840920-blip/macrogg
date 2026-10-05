"""
FOMC 的離線示範資料（P3）。

**這裡的聲明全部是 federalreserve.gov 的真實原文**，逐字複製，未經改寫。
記者會逐字稿同樣取自官方 PDF（2026-07-29 場次）。

    來源：/newsevents/pressreleases/monetary{YYYYMMDD}a.htm
          /mediacenter/files/FOMCpresconf20260729.pdf

為什麼選這六次會議
------------------
2026-01 → 2026-09 剛好跨過一次主席交接（Powell → Warsh，2026-05），
所以同一組資料就能示範這個模組所有的機制：

  * **格式改版**：1/3/4 月是 Powell 時代的長篇格式（前瞻指引、風險平衡
    措辭俱全）；6/7/9 月是 Warsh 上任後的短篇格式，前瞻指引被移除，
    票數改寫在開頭引言。逐句比對與熱力圖的「整排變空白」都靠這個落差。
  * **各種反對票寫法**：3 月是單一反對者、1 月是兩位同向、
    4 月是四位反對但**反對的事情不同**（Miran 主張降息，另三位同意維持、
    但反對聲明加入寬鬆傾向）、7 月是三位同向且聲明只寫 "Voting against"
    （沒有贊成名單）。投票解析的每一條分支都被這組資料涵蓋。
  * **決議**：9 月升息一碼、全體一致（「升息＋區間」的解析與頂部決議卡）。

注意：`text` 欄位存的是**政策段落＋引言**的原始樣子，
擷取流程（extract_text → split_statement → 去引言）由 build() 重現，
所以離線與正式執行走的是同一條路徑。
"""

from __future__ import annotations

from . import clock

# ---------------------------------------------------------------------------
# 真實聲明原文（逐字）
# ---------------------------------------------------------------------------
STATEMENTS = [
    {
        "date": "2026-01-28",
        "text": (
            "Available indicators suggest that economic activity has been expanding at a "
            "solid pace. Job gains have remained low, and the unemployment rate has shown "
            "some signs of stabilization. Inflation remains somewhat elevated. "
            "The Committee seeks to achieve maximum employment and inflation at the rate "
            "of 2 percent over the longer run. Uncertainty about the economic outlook "
            "remains elevated. The Committee is attentive to the risks to both sides of "
            "its dual mandate. "
            "In support of its goals, the Committee decided to maintain the target range "
            "for the federal funds rate at 3‑1/2 to 3‑3/4 percent. In considering the "
            "extent and timing of additional adjustments to the target range for the "
            "federal funds rate, the Committee will carefully assess incoming data, the "
            "evolving outlook, and the balance of risks. The Committee is strongly "
            "committed to supporting maximum employment and returning inflation to its "
            "2 percent objective. "
            "In assessing the appropriate stance of monetary policy, the Committee will "
            "continue to monitor the implications of incoming information for the economic "
            "outlook. The Committee would be prepared to adjust the stance of monetary "
            "policy as appropriate if risks emerge that could impede the attainment of the "
            "Committee's goals. The Committee's assessments will take into account a wide "
            "range of information, including readings on labor market conditions, inflation "
            "pressures and inflation expectations, and financial and international "
            "developments."
        ),
        "vote_text": (
            "Voting for the monetary policy action were Jerome H. Powell, Chair; "
            "John C. Williams, Vice Chair; Michael S. Barr; Michelle W. Bowman; "
            "Lisa D. Cook; Beth M. Hammack; Philip N. Jefferson; Neel Kashkari; "
            "Lorie K. Logan; and Anna Paulson. Voting against this action were "
            "Stephen I. Miran and Christopher J. Waller, who preferred to lower the "
            "target range for the federal funds rate by 1/4 percentage point at this "
            "meeting."
        ),
    },
    {
        "date": "2026-03-18",
        "text": (
            "Available indicators suggest that economic activity has been expanding at a "
            "solid pace. Job gains have remained low, and the unemployment rate has been "
            "little changed in recent months. Inflation remains somewhat elevated. "
            "The Committee seeks to achieve maximum employment and inflation at the rate "
            "of 2 percent over the longer run. Uncertainty about the economic outlook "
            "remains elevated. The implications of developments in the Middle East for the "
            "U.S. economy are uncertain. The Committee is attentive to the risks to both "
            "sides of its dual mandate. "
            "In support of its goals, the Committee decided to maintain the target range "
            "for the federal funds rate at 3‑1/2 to 3‑3/4 percent. In considering the "
            "extent and timing of additional adjustments to the target range for the "
            "federal funds rate, the Committee will carefully assess incoming data, the "
            "evolving outlook, and the balance of risks. The Committee is strongly "
            "committed to supporting maximum employment and returning inflation to its "
            "2 percent objective. "
            "In assessing the appropriate stance of monetary policy, the Committee will "
            "continue to monitor the implications of incoming information for the economic "
            "outlook. The Committee would be prepared to adjust the stance of monetary "
            "policy as appropriate if risks emerge that could impede the attainment of the "
            "Committee's goals. The Committee's assessments will take into account a wide "
            "range of information, including readings on labor market conditions, inflation "
            "pressures and inflation expectations, and financial and international "
            "developments."
        ),
        "vote_text": (
            "Voting for the monetary policy action were Jerome H. Powell, Chair; "
            "John C. Williams, Vice Chair; Michael S. Barr; Michelle W. Bowman; "
            "Lisa D. Cook; Beth M. Hammack; Philip N. Jefferson; Neel Kashkari; "
            "Lorie K. Logan; Anna Paulson; and Christopher J. Waller. Voting against "
            "this action was Stephen I. Miran, who preferred to lower the target range "
            "for the federal funds rate by 1/4 percentage point at this meeting."
        ),
    },
    {
        "date": "2026-04-29",
        "text": (
            "Recent indicators suggest that economic activity has been expanding at a "
            "solid pace. Job gains have remained low, on average, and the unemployment "
            "rate has been little changed in recent months. Inflation is elevated, in part "
            "reflecting the recent increase in global energy prices. "
            "The Committee seeks to achieve maximum employment and inflation at the rate "
            "of 2 percent over the longer run. Developments in the Middle East are "
            "contributing to a high level of uncertainty about the economic outlook. The "
            "Committee is attentive to the risks to both sides of its dual mandate. "
            "In support of its goals, the Committee decided to maintain the target range "
            "for the federal funds rate at 3‑1/2 to 3‑3/4 percent. In considering the "
            "extent and timing of additional adjustments to the target range for the "
            "federal funds rate, the Committee will carefully assess incoming data, the "
            "evolving outlook, and the balance of risks. The Committee is strongly "
            "committed to supporting maximum employment and returning inflation to its "
            "2 percent objective. "
            "In assessing the appropriate stance of monetary policy, the Committee will "
            "continue to monitor the implications of incoming information for the economic "
            "outlook. The Committee would be prepared to adjust the stance of monetary "
            "policy as appropriate if risks emerge that could impede the attainment of the "
            "Committee's goals. The Committee's assessments will take into account a wide "
            "range of information, including readings on labor market conditions, inflation "
            "pressures and inflation expectations, and financial and international "
            "developments."
        ),
        # 四位反對者、兩種理由——投票解析最嚴苛的實例
        "vote_text": (
            "Voting for the monetary policy action were Jerome H. Powell, Chair; "
            "John C. Williams, Vice Chair; Michael S. Barr; Michelle W. Bowman; "
            "Lisa D. Cook; Philip N. Jefferson; Anna Paulson; and Christopher J. Waller. "
            "Voting against this action were Stephen I. Miran, who preferred to lower the "
            "target range for the federal funds rate by 1/4 percentage point at this "
            "meeting; and Beth M. Hammack, Neel Kashkari, and Lorie K. Logan, who "
            "supported maintaining the target range for the federal funds rate but did "
            "not support inclusion of an easing bias in the statement at this time."
        ),
    },
    {
        # Warsh 上任後的第一份聲明：篇幅驟減、前瞻指引移除、票數改寫在引言
        "date": "2026-06-17",
        "text": (
            "The Federal Open Market Committee approved the following statement for "
            "release by a 12 – 0 vote: "
            "The Committee decided to maintain the target range for the federal funds "
            "rate at 3-1/2 to 3-3/4 percent, in support of the Federal Reserve's dual "
            "mandate. The Committee reaffirmed its policy of maintaining ample reserves "
            "in the banking system. "
            "Economic activity is expanding at a solid pace despite elevated uncertainty "
            "that owes, in part, to the conflict in the Middle East. Productivity growth "
            "and capital investment are strong. Job gains have kept pace with the "
            "workforce, and the unemployment rate has changed little. "
            "Inflation remains elevated relative to the Committee's 2 percent goal, in "
            "part reflecting supply shocks that have driven price increases in certain "
            "sectors, including energy. The Committee will deliver price stability."
        ),
        "vote_text": "",          # 一致通過，新格式不列贊成名單
    },
    {
        "date": "2026-07-29",
        "text": (
            "The Federal Open Market Committee approved the following statement for "
            "release by a 9 – 3 vote: "
            "The Committee decided to maintain the target range for the federal funds "
            "rate at 3-1/2 to 3-3/4 percent, in support of the Federal Reserve's dual "
            "mandate. The Committee is continuing its policy of maintaining ample "
            "reserves in the banking system. "
            "Economic activity is expanding at a solid pace despite elevated uncertainty "
            "that owes, in part, to the conflict in the Middle East. Productivity growth "
            "and capital investment are strong. Job gains have kept pace with the "
            "workforce, and the unemployment rate has changed little. "
            "Inflation remains elevated relative to the Committee's 2 percent goal, in "
            "part reflecting supply shocks that have driven price increases in certain "
            "sectors, including energy. The Committee will deliver price stability."
        ),
        "vote_text": (
            "Voting against the monetary policy action were Beth M. Hammack, "
            "Neel Kashkari, and Lorie K. Logan, who preferred to raise the target range "
            "for the federal funds rate by 1/4 percentage point at this meeting."
        ),
    },
    {
        # 9 月：升息一碼、全體一致；刪掉「通膨部分來自供給衝擊」那一句
        "date": "2026-09-16",
        "text": (
            "The Federal Open Market Committee approved the following statement for "
            "release by a 12 – 0 vote: "
            "The Committee decided to raise the target range for the federal funds rate "
            "by 1/4 percentage point to 3-3/4 to 4 percent, in support of the Federal "
            "Reserve's dual mandate. The Committee is continuing its policy of maintaining "
            "ample reserves in the banking system. Economic activity is expanding at a "
            "solid pace. While uncertainty remains elevated owing, in part, to geopolitical "
            "developments, domestic spending has been resilient. Productivity growth is "
            "strong, and capital investment is robust. Job gains have kept pace with the "
            "workforce, and the unemployment rate has changed little. Inflation remains "
            "elevated. Today's policy action will support a timelier return to the "
            "Committee's 2 percent goal. The Committee will deliver price stability."
        ),
        "vote_text": "",
    },
]


# ---------------------------------------------------------------------------
# 記者會逐字稿（2026-07-29，官方 PDF 節錄，逐字）
# ---------------------------------------------------------------------------
PRESSER_20260729 = (
    "CHAIRMAN WARSH. Good day. My second FOMC Committee meeting as Chairman has come "
    "quickly. It's probably too early to call it a streak, but our discussions again were "
    "collegial and constructive. I am truly lucky to work with colleagues so capable and "
    "mission-focused, and so determined, like I am, to sharpen the performance of the "
    "Federal Reserve. "
    "Today, as you know, our Committee decided to vote by a 9 to 3 vote to maintain the "
    "target range for the federal funds rate at 3-1/2 to 3-3/4 percent. The Committee is "
    "continuing its policy of making ample reserves in the banking system. The economy is "
    "showing impressive resilience. Even with recent shocks, the trends are positive and "
    "reveal solid growth. Job gains have kept pace with the workforce, and the "
    "unemployment rate has changed little. Inflation remains elevated relative to the "
    "Committee's 2 percent goal. The Committee remains resolute. You've heard this "
    "before, but we will deliver price stability. "
    "As before, the policy statement conveys just the facts. It's steering clear of "
    "forecasting, a choice we consider especially prudent at these uncertain times. "
    "Uncertainty, however, does not mean a lack of clarity. For some households, "
    "businesses, and market professionals, five years of high inflation have left a "
    "mistaken impression that is hard to shake: that the Fed's implicit inflation target "
    "was somehow above 2 percent. Let me reiterate: There is no soft inflation target, "
    "there is no soft implicit target — not on this Committee's watch. There is only a "
    "target, and it is 2 percent. We have begun a new chapter, and we understand that the "
    "five-plus years of inflation above target cannot be cured in nine weeks — or by a "
    "single month of modest price decreases. "
    "This Fed will not waver. Our credibility rests on performing our duties, and "
    "delivering on our responsibilities. "
    "Two economic developments are worth highlighting. The first is a very notable change "
    "since our last meeting 42 days ago: nominal and real yields are materially higher "
    "across the Treasury curve. In fact, some of the increases in market interest rates "
    "between FOMC meetings are among the most significant in the last two decades. "
    "In the inter-meeting period, market attention centered on real data and real economic "
    "developments. Prices reacted in real time to incoming information, and the reduction "
    "in forward guidance may have been a factor. Market participants are learning to play "
    "the ball, not the referee. "
    "A second economic development is the strong growth of business investment. The surge "
    "in high-tech capex has been remarkable. In the A.I.-related category of high-tech "
    "equipment and software, the most recent data shows four-quarter growth rates of "
    "nearly 20 percent. This is helping to sustain the healthy momentum of manufacturing "
    "output. More generally, capex is preparing the ground for future growth. "
    "Finally, we discussed monetary policy tools and strategies for achieving stable "
    "prices. If, as the Fed has long held, interest rate policy should be its primary "
    "monetary policy instrument, how much accommodation are we getting from the balance "
    "sheet? "
    "Of course, you've all arrived with questions of your own, so let's turn to them now. "
    "STEVE LIESMAN. You've had a couple months now to see the markets behave in the "
    "absence of forward guidance. What message are you getting from the markets as to "
    "where policy ought to be right now? "
    "CHAIRMAN WARSH. The message from markets is the message from markets. What I've "
    "really been trying to do is getting an unfiltered message from markets. Letting "
    "buyers and sellers meet at prices for Treasuries, for the foreign exchange value of "
    "the dollar, and then trying to judge for ourselves, what does that mean about our "
    "remit? How are we doing on inflation? How are we doing on employment? We're trying "
    "not to interfere with that market signal. That's part of the reason why we've been "
    "somewhat spare on our words, when we pulled back from forward guidance. We've seen a "
    "material tightening, not just in nominal rates, but in real rates too. "
    "CLAIRE JONES. Claire Jones, Financial Times. You seem to have got the family fight "
    "you were after at this meeting, we saw three dissents. Could you characterize the "
    "arguments that those dissenters put forward, and tell us why you weren't persuaded "
    "by them at this stage? "
    "CHAIRMAN WARSH. So you're right, I asked for a good family fight, and I got one. "
    "There was a lot of agreement that I heard, that we have the powers, the tools, also "
    "the authority to deliver stable prices. No walking back from our responsibilities. "
    "There was a large majority support for the decision that we made in the room. There "
    "was nothing inertial about that discussion. The path to central bank heaven requires "
    "delivering on our remit. These days that means delivering on price stability. "
    "CLAIRE JONES. How much do you think not going in July was down to the cool CPI print "
    "for June? "
    "CHAIRMAN WARSH. In two words, not much. The historic problem with data dependence is "
    "the data and the dependence. We are not relying on any one individual piece of data "
    "as cover or as an excuse, or as validation. What I care about is trends on the data. "
    "Sure, we got some encouraging inflation data. So we'll be watching inflation data "
    "over the period ahead."
)


# 2026-09-16 記者會（官方 PDF 節錄，逐字；含主持人點名與記者提問，
# 用來驗證「只摘主席本人的話」）
PRESSER_20260916 = (
    "CHAIRMAN WARSH. Good day. In the meeting just concluded, the FOMC decided to raise "
    "the target range for the federal funds rate by a ¼ percentage point to 3¾ to 4 "
    "percent, in support of the Federal Reserve’s dual mandate. The Committee is "
    "continuing its policy of maintaining ample reserves in the banking system. As noted "
    "in the policy statement, released just a short while ago, economic activity is "
    "expanding at a solid pace. Job gains have kept pace with the workforce, and the "
    "unemployment rate has changed little. But inflation remains elevated. Today’s policy "
    "action will support a timelier return to the Committee’s 2 percent goal. This "
    "Committee will deliver price stability. Now I’ll get into some further detail. Our "
    "decision comes at a time when the American economy appears to be strengthening. "
    "New hiring, private-sector earnings, business capital investment—each of these "
    "markers has improved in recent months and is pointing in a good direction. And, as I "
    "said at the policy symposium in Jackson Hole, I would be hard pressed to describe "
    "broad financial conditions as restrictive. This view was widely shared by the "
    "Committee. So we removed a dose of accommodation. And, with that, I’ll take a few of "
    "your questions. "
    "MICHELLE SMITH. Richard. "
    "RICHARD ESCOBEDO. Thank you. Chair Warsh, thank you for doing this. I’m Richard "
    "Escobedo with CBS. You know, a ¼ point rate hike does not reopen the Strait of "
    "Hormuz. And so I wonder how you think these smaller rate hikes will be effective "
    "when it can’t necessarily address the energy supply side of inflationary pressures. "
    "CHAIRMAN WARSH. It’s a—it’s a—it’s a good question, Richard. We cannot affect any "
    "individual price, whether it be oil prices, whether it be foodstuffs at the grocery "
    "store. But what we can do, and will do, is ensure that any change in relative prices "
    "don’t broaden out, don’t have second- and third-order effects in the economy. "
    "That’s what we’re tasked to do, and that’s what we will do. "
    "MICHELLE SMITH. Colby. "
    "COLBY SMITH. Thank you. Colby Smith from the New York Times. When the Fed starts "
    "raising rates, it generally follows with a sequence of hikes. Is there anything "
    "different in today’s assessment of the economic conditions that would suggest that "
    "the typical pattern does not apply?"
)


def build() -> list[dict]:
    """
    回傳與 fomc_source.collect() 相同結構的資料。

    刻意重跑一次 split_statement / 去引言的流程，讓離線與正式執行走同一條
    程式路徑——否則離線看起來正常、正式跑才爆的 bug 會驗不出來。
    """
    from .fomc_source import parse_votes, split_statement, PREAMBLE_VOTE_RE

    out = []
    for s in STATEMENTS:
        # 新格式的票數寫在引言裡，舊格式寫在 vote_text，兩種都要處理
        policy, inline_vote = split_statement(s["text"])
        vote_text = s.get("vote_text") or inline_vote
        v = parse_votes(vote_text)

        m = PREAMBLE_VOTE_RE.search(policy)
        if m:
            v.stated_support, v.stated_dissent = int(m.group(1)), int(m.group(2))
            policy = PREAMBLE_VOTE_RE.sub("", policy, count=1).strip()
            v.mismatch = len(v.dissents) != v.stated_dissent

        d = {"date": s["date"], "text": policy, "vote_text": vote_text,
             "vote": v.__dict__}
        if s["date"] == "2026-07-29":
            d["presser"] = PRESSER_20260729
            d["presser_error"] = None
        if s["date"] == "2026-09-16":
            d["presser"] = PRESSER_20260916
            d["presser_error"] = None
        out.append(d)
    return out


# 官方行事曆上 2026 年最後三場（已對照 federalreserve.gov 的行事曆頁）。
# 正式執行時由 FomcSource.upcoming_meetings() 直接解析行事曆，
# 這裡只是離線模式的對應素材，讓兩條路徑產出同樣形狀的資料。
_UPCOMING = ["2026-10-28", "2026-12-09", "2027-01-27"]


def upcoming() -> list:
    """離線模式的未來會議日期。只回傳今天之後的場次。"""
    import datetime as dt
    today = clock.today()
    return [d for d in (dt.date.fromisoformat(x) for x in _UPCOMING) if d > today]


# ---------------------------------------------------------------------------
# 事實層（2026-10）：全部取自 federalreserve.gov 的真實內容
# ---------------------------------------------------------------------------
# 2026-09-16 SEP 表 1（中位數；prev＝6 月）與圖 2（點陣圖）
SEP_20260916 = {
    "date": "2026-09-16",
    "years": ["2026", "2027", "2028", "2029", "Longer run"],
    "prev_label": "June",
    "vars": {
        "gdp": {"median": [2.3, 2.4, 2.2, 2.1, 2.0], "prev": [2.2, 2.3, 2.2, None, 2.0],
                "ct": ["2.2–2.4", "2.2–2.6", "2.1–2.3", "2.0–2.2", "2.0–2.2"], "range": []},
        "unrate": {"median": [4.1, 4.1, 4.1, 4.1, 4.2], "prev": [4.3, 4.3, 4.2, None, 4.2],
                   "ct": ["4.1–4.2", "4.0–4.2", "4.0–4.2", "4.0–4.3", "4.0–4.3"], "range": []},
        "pce": {"median": [3.7, 2.3, 2.1, 2.0, 2.0], "prev": [3.6, 2.3, 2.0, None, 2.0],
                "ct": ["3.5–3.7", "2.2–2.5", "2.0–2.2", "2.0", "2.0"], "range": []},
        "core_pce": {"median": [3.4, 2.5, 2.2, 2.0, None], "prev": [3.3, 2.5, 2.1, None, None],
                     "ct": ["3.3–3.4", "2.3–2.6", "2.0–2.2", "2.0", ""], "range": []},
        "ffr": {"median": [4.1, 4.1, 3.9, 3.6, 3.2], "prev": [3.8, 3.6, 3.4, None, 3.1],
                "ct": ["4.1–4.4", "3.6–4.4", "3.1–4.1", "3.1–3.6", "3.0–3.6"], "range": []},
    },
    "dots": {
        "years": ["2026", "2027", "2028", "2029", "Longer run"],
        "rows": [(4.375, [4, 8, 0, 0, 0]), (4.125, [12, 6, 4, 0, 0]),
                 (3.875, [2, 0, 5, 3, 2]), (3.75, [0, 0, 0, 0, 1]),
                 (3.625, [0, 3, 3, 7, 2]), (3.5, [0, 0, 0, 0, 2]),
                 (3.375, [0, 0, 1, 2, 1]), (3.25, [0, 0, 0, 0, 2]),
                 (3.125, [0, 1, 4, 4, 1]), (3.0, [0, 0, 0, 0, 6]),
                 (2.875, [0, 0, 0, 1, 1])],
        "n": [18, 18, 17, 17, 18],
    },
}

# 2026-07-29 會議紀要（8/19 公布）的量詞句，逐字
MINUTES_ROWS = [
    {"topic": "政策路徑", "rank": 2, "level": "多數",
     "text": "In their consideration of monetary policy at this meeting, most participants "
             "supported maintaining the current target range for the federal funds rate."},
    {"topic": "政策路徑", "rank": 3, "level": "許多",
     "text": "Many participants assessed that policy tightening would likely be necessary if "
             "inflation did not decline."},
    {"topic": "通膨", "rank": 0, "level": "普遍",
     "text": "Participants acknowledged that inflation remained elevated."},
    {"topic": "通膨", "rank": 3, "level": "許多",
     "text": "Most participants anticipated that inflation would step down over the rest of "
             "the year as the effects of tariffs and earlier energy price increases wane, but "
             "many participants noted the possibility that inflation might be more "
             "persistently elevated."},
    {"topic": "就業", "rank": 0, "level": "普遍",
     "text": "Participants assessed that labor market conditions were stable, with labor "
             "demand and supply in balance."},
    {"topic": "金融情勢", "rank": 5, "level": "部分",
     "text": "In their discussion of financial stability, some participants focused on "
             "vulnerabilities associated with the financing of the rapid buildout of "
             "AI-related infrastructure."},
]

_ROSTER = {
    "year": 2026,
    "members": [
        {"name": "Kevin Warsh", "affil": "Board of Governors", "extra": "Chairman"},
        {"name": "John C. Williams", "affil": "New York", "extra": "Vice Chair"},
        {"name": "Michael S. Barr", "affil": "Board of Governors", "extra": ""},
        {"name": "Michelle W. Bowman", "affil": "Board of Governors", "extra": ""},
        {"name": "Lisa D. Cook", "affil": "Board of Governors", "extra": ""},
        {"name": "Beth M. Hammack", "affil": "Cleveland", "extra": ""},
        {"name": "Philip N. Jefferson", "affil": "Board of Governors", "extra": ""},
        {"name": "Neel Kashkari", "affil": "Minneapolis", "extra": ""},
        {"name": "Lorie K. Logan", "affil": "Dallas", "extra": ""},
        {"name": "Anna Paulson", "affil": "Philadelphia", "extra": ""},
        {"name": "Jerome H. Powell", "affil": "Board of Governors", "extra": ""},
        {"name": "Christopher J. Waller", "affil": "Board of Governors", "extra": ""},
    ],
    "alternates": [
        {"name": "Thomas I. Barkin", "affil": "Richmond", "extra": ""},
        {"name": "Mary C. Daly", "affil": "San Francisco", "extra": ""},
        {"name": "Austan D. Goolsbee", "affil": "Chicago", "extra": ""},
        {"name": "Sushmita Shukla", "affil": "New York", "extra": "First Vice President"},
        {"name": "Cheryl Venable", "affil": "Atlanta", "extra": "Interim President"},
    ],
}

_SPEECHES = [
    {"surname": "Jefferson", "title": "The U.S. Economy and Monetary Policy",
     "date": "2026-10-01", "kind": "Speech",
     "url": "https://www.federalreserve.gov/newsevents/speech/jefferson20261001a.htm"},
    {"surname": "Barr", "title": "Economic Conditions and Monetary Policy",
     "date": "2026-09-29", "kind": "Speech",
     "url": "https://www.federalreserve.gov/newsevents/speech/barr20260929a.htm"},
]

_EVENTS = [
    {"date": "2026-10-07", "type": "FOMC", "title": "FOMC Minutes", "desc": "", "time": "2:00 p.m."},
    {"date": "2026-10-08", "type": "Speeches", "title": "Speech - Governor Christopher J. Waller",
     "desc": "Economic Outlook", "time": "4:30 a.m."},
    {"date": "2026-10-14", "type": "Beige", "title": "Beige Book", "desc": "", "time": "2:00 p.m."},
]

_NEWS = {
    "Logan": [{"title": "Fed’s Logan Wants More Hikes, But Says Bond Moves Could Help",
               "source": "Bloomberg.com", "date": "2026-10-02", "url": "", "policy": True}],
    "Kashkari": [{"title": "Fed's Kashkari expects more rate hikes, unsure on need to act this month",
                  "source": "reuters.com", "date": "2026-10-01", "url": "", "policy": True}],
}


def extras() -> dict:
    """與 FomcSource.extras() 同形狀（離線示範）。"""
    import datetime as dt
    today = clock.today()
    spans = [(dt.date.fromisoformat(x) - dt.timedelta(days=1), dt.date.fromisoformat(x))
             for x in _UPCOMING]
    spans = [(a, b) for a, b in spans if b > today]
    return {"spans": spans, "sep": SEP_20260916,
            "minutes": {"meeting": "2026-07-29", "released": "2026-08-19",
                        "url": "https://www.federalreserve.gov/monetarypolicy/fomcminutes20260729.htm",
                        "rows": MINUTES_ROWS, "words": 1933},
            "roster": _ROSTER,
            "board_titles": {"Warsh": "Chairman", "Jefferson": "Vice Chair",
                             "Bowman": "Vice Chair for Supervision"},
            "speeches": _SPEECHES, "events": _EVENTS, "news": _NEWS}
