"""
數字格式化 — 全站統一走這裡。

原則
----
中文閱讀習慣是「萬」，不是「千」或「K」。所以：
  * 標題與重點數字 → 萬人（2.3 萬人）
  * 明細與圖表     → 人（23,000 人），避免出現「0.1 萬」這種不自然的寫法

內部資料一律以「千人」為單位（FRED 的原始單位），
所以這裡的輸入 v 都是千人，由函式負責換算。
"""

from __future__ import annotations


def wan(v_thousands: float | None, signed: bool = True, digits: int = 1,
        unit: str = "萬人") -> str:
    """千人 → 萬人。例：-23 →「-2.3 萬人」"""
    if v_thousands is None:
        return "—"
    w = v_thousands / 10
    s = f"{w:+.{digits}f}" if signed else f"{w:.{digits}f}"
    return f"{s} {unit}"


def wan_abs(v_thousands: float | None, digits: int = 1, unit: str = "萬人") -> str:
    """不帶正負號的絕對值，用在「減少 2.3 萬人」這種句子裡。"""
    if v_thousands is None:
        return "—"
    return f"{abs(v_thousands)/10:.{digits}f} {unit}"


def people(v_thousands: float | None, signed: bool = True) -> str:
    """千人 → 人。例：-23 → 「-23,000」。用於明細清單與圖表。"""
    if v_thousands is None:
        return "—"
    n = v_thousands * 1000
    return f"{n:+,.0f}" if signed else f"{n:,.0f}"


def persons_to_wan(n: float | None, digits: int = 0, unit: str = "萬人") -> str:
    """原始單位就是「人」的序列（例如失業金申請）→ 萬人。"""
    if n is None:
        return "—"
    return f"{n/10000:.{digits}f} {unit}"


def pp(v: float | None, digits: int = 2) -> str:
    """百分點。"""
    return "—" if v is None else f"{v:+.{digits}f} 個百分點"


def pct(v: float | None, digits: int = 1) -> str:
    return "—" if v is None else f"{v:.{digits}f}%"


def money(v: float | None, digits: int = 2) -> str:
    return "—" if v is None else f"{v:,.{digits}f} 美元"


def change_verb(v: float | None) -> str:
    """回傳「增加」或「減少」，讓句子讀起來自然。"""
    if v is None:
        return "變動"
    return "增加" if v >= 0 else "減少"
