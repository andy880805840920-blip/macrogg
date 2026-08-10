"""
FOMC 的離線示範資料（P3）。

**這裡的聲明全部是 federalreserve.gov 的真實原文**，逐字複製，未經改寫。
記者會逐字稿同樣取自官方 PDF（2026-07-29 場次）。

    來源：/newsevents/pressreleases/monetary{YYYYMMDD}a.htm
          /mediacenter/files/FOMCpresconf20260729.pdf

為什麼選這五次會議
------------------
2026-01 → 2026-07 剛好跨過一次主席交接（Powell → Warsh，2026-05），
所以同一組資料就能示範這個模組所有的機制：

  * **格式改版**：1/3/4 月是 Powell 時代的長篇格式（前瞻指引、風險平衡
    措辭俱全）；6/7 月是 Warsh 上任後的短篇格式，前瞻指引被移除，
    票數改寫在開頭引言。逐句比對與「溝通制度變化偵測」都靠這個落差。
  * **各種反對票寫法**：3 月是單一反對者、1 月是兩位同向、
    4 月是四位反對但**方向不同**（Miran 主張降息，另三位主張維持不變）、
    7 月是三位同向且聲明只寫 "Voting against"（沒有贊成名單）。
    投票解析的每一條分支都被這組資料涵蓋。
  * **分數背離**：7 月措辭讀起來不鷹，但三張升息反對票讓客觀訊號 +6，
    正是「兩個分數刻意不合成」的實例。

注意：`text` 欄位存的是**政策段落＋引言**的原始樣子，
擷取流程（extract_text → split_statement → 去引言）由 build() 重現，
所以離線與正式執行走的是同一條路徑。
"""

from __future__ import annotations

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
        out.append(d)
    return out
