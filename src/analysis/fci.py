"""
聯準會 FCI-G（Financial Conditions Impulse on Growth）的判讀（情境頁「金融條件」）。

單位：對未來一年實質 GDP 成長的拖累／助力（百分點）。正＝逆風（金融條件偏緊）、負＝順風（偏鬆）。
七個成份相加＝指數。主要成份＝跟指數同方向、絕對值最大的那一項。
"""
from __future__ import annotations

# 堆疊順序＝調色盤順序（相鄰兩段一定是驗證過的相鄰色）；股市通常最大，放第一段
COMPS = [("stock", "股市"), ("dollar", "美元"), ("ffr", "聯邦基金利率"), ("bbb", "BBB 公司債殖利率"),
         ("house", "房價"), ("mort", "房貸利率"), ("t10", "10 年期公債")]
NEUTRAL = 0.10          # |指數| 小於 0.1 個百分點視為中性


def _at(rows: list[dict], months_back: int) -> dict | None:
    return rows[-1 - months_back] if len(rows) > months_back else None


def summarize(rows: list[dict]) -> dict | None:
    if not rows:
        return None
    now, m1, y1 = rows[-1], _at(rows, 1), _at(rows, 12)
    tot = now["total"]
    stance = "neutral" if abs(tot) < NEUTRAL else ("tight" if tot > 0 else "loose")
    comps = []
    for k, zh in COMPS:
        comps.append({"key": k, "label": zh, "value": now[k],
                      "m1": None if m1 is None else now[k] - m1[k],
                      "y1": None if y1 is None else now[k] - y1[k]})
    same = [c for c in comps if (c["value"] > 0) == (tot > 0) and abs(c["value"]) >= 0.01]
    main = max(same or comps, key=lambda c: abs(c["value"]))
    share = abs(main["value"]) / sum(abs(c["value"]) for c in comps if (c["value"] > 0) == (tot > 0)) \
        if same else None
    opp = [c for c in comps if (c["value"] > 0) != (tot > 0) and abs(c["value"]) >= 0.05]
    word = {"tight": "偏緊（成長逆風）", "loose": "偏鬆（成長順風）", "neutral": "大致中性"}[stance]
    head = (f"金融條件{word}，主要來自{main['label']}（{main['value']:+.2f}pp"
            + (f"，佔同方向貢獻 {share:.0%}" if share else "") + "）" if stance != "neutral"
            else f"金融條件大致中性（{tot:+.2f}pp）")
    if opp and stance != "neutral":
        o = max(opp, key=lambda c: abs(c["value"]))
        head += f"；{o['label']}反向抵銷 {o['value']:+.2f}pp"
    return {"date": now["date"], "total": tot, "m1": None if m1 is None else tot - m1["total"],
            "y1": None if y1 is None else tot - y1["total"], "stance": stance, "main": main,
            "share": share, "comps": comps, "headline": head}
