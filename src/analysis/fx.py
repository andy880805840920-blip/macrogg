"""
匯率換算 — 只為了在原幣金額旁邊補一個「約合多少美元」。

為什麼要有這一層
----------------
科技巨頭的海外發債是用當地幣計價的：Alphabet 發過 €90 億與 C$85 億，
Amazon 發過 C$140 億，還有 ¥5,765 億。先前的解析把所有幣別記號都當成
美元——「C$1,250,000,000」裡面就含有「$1,250,000,000」，加拿大幣直接被
讀成美元，金額因此系統性偏高。

修法是**在解析階段保留原始幣別**，換算留到這一層。這樣做的好處是
原始資料永遠是可稽核的（原幣金額就是說明書封面上寫的數字），
而換算是可以重算、可以標日期的衍生值。

為什麼用 FRED 而不是即時匯率 API
--------------------------------
1. 這個專案本來就在抓 FRED，不必多一個資料源、多一把金鑰
2. FRED 的匯率是**有日期的每日定盤價**，可以跟著數字一起標出來——
   「約 US$102 億（匯率 0.7284，2026-08-11）」是可以被別人重算的
3. 即時匯率會讓同一份靜態頁面每次產生都出現不同的數字，
   而發債金額本身是歷史事實，不該每天漂

方向要小心
----------
FRED 的匯率序列方向不一致，而且方向弄反不會報錯，只會讓數字錯 100 倍：

    DEXUSEU   一歐元換多少美元    → 直接乘
    DEXJPUS   一美元換多少日圓    → 要倒過來除

所以每一條序列都明確標記方向，由 `_DIRECT` / `_INVERSE` 分開列。
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# 一單位外幣換多少美元（直接乘）
_DIRECT = {
    "EUR": "DEXUSEU",        # U.S. Dollars to One Euro
    "GBP": "DEXUSUK",        # U.S. Dollars to One British Pound
    "AUD": "DEXUSAL",        # U.S. Dollars to One Australian Dollar
}

# 一美元換多少外幣（要倒過來）
_INVERSE = {
    "CAD": "DEXCAUS",        # Canadian Dollars to One U.S. Dollar
    "JPY": "DEXJPUS",        # Japanese Yen to One U.S. Dollar
    "CHF": "DEXSZUS",        # Swiss Francs to One U.S. Dollar
    "SEK": "DEXSDUS",        # Swedish Kronor to One U.S. Dollar
    "NOK": "DEXNOUS",        # Norwegian Kroner to One U.S. Dollar
}

SERIES = {**{c: (s, "direct") for c, s in _DIRECT.items()},
          **{c: (s, "inverse") for c, s in _INVERSE.items()}}

# 這些序列要抓才有匯率可用。給 config 與序列稽核工具對照。
SERIES_IDS = sorted({s for s, _ in SERIES.values()})


def _latest(rows: list) -> tuple[float | None, str]:
    """最後一筆有值的觀測。FRED 的匯率在假日是空值，要往回找。"""
    for r in reversed(rows or []):
        v = r.get("value")
        if v is not None:
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            if f > 0:
                return f, r.get("date", "")
    return None, ""


def rates(series: dict) -> dict:
    """
    回傳 {幣別: {"rate": 一單位外幣值多少美元, "date": 匯率日期}}。

    美元固定是 1.0，日期留空——它不是換算來的，標日期反而誤導。
    抓不到的幣別直接不出現在結果裡，呼叫端就會知道「這一筆換算不了」，
    而不是拿到一個看起來正常的錯數字。
    """
    out = {"USD": {"rate": 1.0, "date": ""}}
    for ccy, (sid, direction) in SERIES.items():
        val, date = _latest(series.get(sid) or [])
        if val is None:
            continue
        out[ccy] = {"rate": (val if direction == "direct" else 1.0 / val),
                    "date": date}
    return out


def to_usd(amount: float, currency: str, fx: dict) -> dict:
    """
    換算成美元。回傳 {"usd", "rate", "date"}；換不了時 usd 是 None。

    換不了就回 None，**不要用「大概 1 比 1」之類的假設補**——
    一個錯的美元金額比沒有美元金額糟得多，而原幣金額本來就還在，
    畫面上照樣有東西可以顯示。
    """
    r = fx.get(currency)
    if not r or amount is None:
        return {"usd": None, "rate": None, "date": ""}
    return {"usd": amount * r["rate"], "rate": r["rate"], "date": r["date"]}


# 畫面上的原幣記號。以原幣為主、美元為輔，是因為原幣才是說明書上
# 白紙黑字的那個數字；美元是我們換算出來的，會隨匯率日期變動。
SYMBOL = {"USD": "US$", "EUR": "€", "GBP": "£", "JPY": "¥", "CAD": "C$",
          "AUD": "A$", "CHF": "CHF ", "SEK": "SEK ", "NOK": "NOK "}


def fmt_native(amount: float, currency: str) -> str:
    """原幣金額，以「億」為單位（中文讀者的習慣單位）。"""
    if amount is None:
        return ""
    return f"{SYMBOL.get(currency, currency + ' ')}{amount / 1e8:,.0f} 億"
