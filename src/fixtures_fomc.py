"""
FOMC 的離線示範資料（P3）。

⚠️ 下面的聲明是**仿寫**的，用來驗證配對比對、投票解析與計分邏輯，
   **不是聯準會的真實聲明原文**。正式執行會從 federalreserve.gov 抓真實文本。

不過**結構**是照現實設定的，這樣示範才有意義：
  * 2025-12 與 2026-03 是 Powell 時代的長篇格式（含前瞻指引與風險平衡措辭）
  * 2026-06 起是 Warsh 上任後的短篇格式，前瞻指引被刻意移除
  * 2026-07 有三位官員投下贊成升息的反對票

這組結構會同時觸發「溝通制度變化偵測」與「客觀訊號 vs 措辭背離」，
正好示範這兩個機制為什麼必要。
"""

from __future__ import annotations

STATEMENTS = [
    {
        "date": "2025-12-10",
        "text": (
            "Recent indicators suggest that economic activity has continued to expand "
            "at a solid pace. Job gains have remained solid, and the unemployment rate "
            "has remained low. Inflation remains somewhat elevated. "
            "The Committee seeks to achieve maximum employment and inflation at the rate "
            "of 2 percent over the longer run. The Committee judges that the risks to "
            "achieving its employment and inflation goals are roughly in balance. "
            "In support of its goals, the Committee decided to lower the target range for "
            "the federal funds rate. The Committee will continue to assess incoming data "
            "and the evolving outlook. The Committee is strongly committed to returning "
            "inflation to its 2 percent objective. In considering additional adjustments, "
            "the Committee will carefully assess incoming data, the evolving outlook, and "
            "the balance of risks. Monetary policy remains restrictive."
        ),
        "vote_text": (
            "Voting for the monetary policy action were Jerome H. Powell; John C. Williams; "
            "Michael S. Barr; Michelle W. Bowman; Lisa D. Cook; Austan D. Goolsbee; "
            "Philip N. Jefferson; Adriana D. Kugler; Alberto G. Musalem; Jeffrey R. Schmid; "
            "and Christopher J. Waller. Voting against this action was Beth M. Hammack, "
            "who preferred to maintain the target range."
        ),
    },
    {
        "date": "2026-03-18",
        "text": (
            "Recent indicators suggest that economic activity has continued to expand "
            "at a moderate pace. Job gains have moderated, and the unemployment rate has "
            "edged up but remains low. Inflation has moved closer to the Committee's "
            "2 percent objective but remains somewhat elevated. "
            "The Committee seeks to achieve maximum employment and inflation at the rate "
            "of 2 percent over the longer run. The Committee judges that the risks to "
            "achieving its employment and inflation goals are roughly in balance. "
            "In support of its goals, the Committee decided to maintain the target range "
            "for the federal funds rate. The Committee will continue to assess incoming "
            "data and the evolving outlook. The Committee is strongly committed to "
            "returning inflation to its 2 percent objective. In considering additional "
            "adjustments, the Committee will carefully assess incoming data, the evolving "
            "outlook, and the balance of risks. Monetary policy remains restrictive."
        ),
        "vote_text": (
            "Voting for the monetary policy action were Jerome H. Powell; John C. Williams; "
            "Michelle W. Bowman; Lisa D. Cook; Austan D. Goolsbee; Philip N. Jefferson; "
            "Neel Kashkari; Alberto G. Musalem; Jeffrey R. Schmid; and Christopher J. Waller. "
            "Voting against this action were Beth M. Hammack and Lorie K. Logan, "
            "who preferred to raise the target range by 25 basis points."
        ),
    },
    {
        "date": "2026-06-17",
        "text": (
            "Economic activity has expanded at a moderate pace. Job gains have slowed and "
            "the unemployment rate has moved up. Inflation has risen. "
            "The Committee decided to maintain the target range for the federal funds rate "
            "at 3-1/2 to 3-3/4 percent. The Committee will assess incoming data in "
            "determining the appropriate stance of monetary policy."
        ),
        "vote_text": (
            "Voting for the monetary policy action were Kevin M. Warsh; John C. Williams; "
            "Michelle W. Bowman; Lisa D. Cook; Austan D. Goolsbee; Philip N. Jefferson; "
            "Alberto G. Musalem; Jeffrey R. Schmid; and Christopher J. Waller. "
            "Voting against this action were Beth M. Hammack and Lorie K. Logan, "
            "who preferred to raise the target range by 25 basis points."
        ),
    },
    {
        "date": "2026-07-29",
        "text": (
            "Economic activity has expanded at a modest pace. Job gains have slowed further "
            "and the unemployment rate has moved up. Inflation remains above the Committee's "
            "objective. The Committee decided to maintain the target range for the federal "
            "funds rate at 3-1/2 to 3-3/4 percent. The Committee will assess incoming data "
            "in determining the appropriate stance of monetary policy."
        ),
        "vote_text": (
            "Voting for the monetary policy action were Kevin M. Warsh; John C. Williams; "
            "Michelle W. Bowman; Lisa D. Cook; Austan D. Goolsbee; Philip N. Jefferson; "
            "Alberto G. Musalem; Jeffrey R. Schmid; and Christopher J. Waller. "
            "Voting against this action were Beth M. Hammack, Neel Kashkari and "
            "Lorie K. Logan, who preferred to raise the target range by 25 basis points."
        ),
        # 示範用逐字稿。長度與結構刻意做得接近真實（開場 + 問答），
        # 這樣離線預覽才看得出主題分類與分數來源句的實際樣子。
        "presser": (
            "CHAIR WARSH. Good afternoon. The markets have done quite a bit even as we "
            "have done little over the past 42 days. Removing forward guidance allows "
            "market attention to be centered on real data rather than on our own "
            "commentary. We are just trying to make sure that that source of information "
            "is as direct and unfiltered as possible. "
            "Inflation remains elevated and the Committee will be patient in assessing "
            "whether further policy firming is warranted. We will deliver price stability "
            "and we are resolute about returning to our 2 percent objective. "
            "The labor market has cooled somewhat; job gains have slowed but the "
            "unemployment rate has changed little, and we do not see downside risks to "
            "employment as the binding constraint today. "
            "We decided to maintain the target range for the federal funds rate, and "
            "policy remains restrictive, which we judge appropriate for some time. "
            "We are continuing to allow our securities holdings to run off while "
            "maintaining ample reserves in the banking system. "
            "I am happy to take your questions. "
            "REPORTER. Three of your colleagues dissented in favor of a hike. How close "
            "was the decision? "
            "CHAIR WARSH. There was a robust discussion. We are not on a preset course, "
            "and financial conditions have eased, which is a consideration for us. "
            "REPORTER. What would it take to cut? "
            "CHAIR WARSH. We would need greater confidence that inflation has moderated "
            "on a sustained basis before moving to a less restrictive stance."
        ),
    },
]


def build() -> list[dict]:
    """回傳與 fomc_source.collect() 相同結構的資料。"""
    from .fomc_source import parse_votes
    out = []
    for s in STATEMENTS:
        d = dict(s)
        d["vote"] = parse_votes(s.get("vote_text", "")).__dict__
        out.append(d)
    return out
