"""
「本期變化」的方向判定測試。

為什麼需要這個檔案
------------------
這一區最容易搞錯、而且錯了完全看不出來的一件事是：
**一條已解除的鷹派訊號，是鴿派的變化。**

先前畫面上掛的是訊號自己的方向，於是四條解除的鷹派訊號會顯示成四個
「利升息」，而同一張卡的標題同時說情境往降息移動——兩者互相矛盾，
而且矛盾的是那四個章。這種錯不會拋例外、不會讓版面跑掉，只會讓讀者
把本期的方向讀反。

數字變動的顏色也是同一類問題：用「漲跌」上色會讓損益兩平就業增速上升
（其實偏鴿）跟核心 CPI 上升（偏鷹）變成同一個顏色。

    python tests/test_change_direction.py
"""
import sys
import re
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from src.analysis import changes as chg  # noqa: E402
from src.pages import home  # noqa: E402

ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    print(f"{'通過' if cond else '失敗'}  {name}" + (f" — {detail}" if detail else ""))
    ok &= bool(cond)


def snap(flags: dict, metrics: dict | None = None, month: str = "2026-07") -> dict:
    """flags: {key: lean}"""
    return {
        "at": f"{month}-05T13:45:00",
        "vintage": {"labor": month},
        "labor": {
            "month": month, "score": 0.0, "tilt": "neutral",
            "flags": list(flags),
            "flag_titles": {k: f"訊號{k}" for k in flags},
            "flag_leans": dict(flags),
            "metrics": metrics or {},
        },
        "scenario": {"name": "按兵不動", "grid_name": "按兵不動",
                     "regime": "balanced", "labor": "中", "inflation": "中"},
    }


# ---------------------------------------------------------------------------
# ① 解除鷹派訊號 ＝ 鴿派的變化
# ---------------------------------------------------------------------------
cs = chg.compare(snap({"a": "dovish"}), snap({"a": "dovish", "h": "hawkish"},
                                             month="2026-06"))
check("① 解除的鷹派訊號算鴿派變化",
      cs.resolved_flags[0]["change_lean"] == "dovish",
      cs.resolved_flags[0]["change_lean"])
check("② 訊號自己的方向仍然保留",
      cs.resolved_flags[0]["lean"] == "hawkish")

cs = chg.compare(snap({"a": "dovish"}), snap({"a": "dovish", "d": "dovish"},
                                             month="2026-06"))
check("③ 解除的鴿派訊號算鷹派變化",
      cs.resolved_flags[0]["change_lean"] == "hawkish")

cs = chg.compare(snap({"a": "dovish", "h": "hawkish"}), snap({"a": "dovish"},
                                                             month="2026-06"))
check("④ 新觸發的訊號方向不變",
      cs.new_flags[0]["change_lean"] == "hawkish")

cs = chg.compare(snap({"a": "dovish"}), snap({"a": "dovish", "n": "neutral"},
                                             month="2026-06"))
check("⑤ 中性訊號解除仍是中性",
      cs.resolved_flags[0]["change_lean"] == "neutral")


# ---------------------------------------------------------------------------
# ② 淨方向
# ---------------------------------------------------------------------------
# 截圖上那一期的組成：新觸發 1 鷹 2 鴿、解除 3 鷹 1 鴿
prev = snap({"x1": "hawkish", "x2": "dovish", "x3": "hawkish", "x4": "hawkish"},
            month="2026-06")
cur = snap({"n1": "hawkish", "n2": "dovish", "n3": "dovish"})
cs = chg.compare(cur, prev)
check("⑥ 淨方向：5 鴿 2 鷹 → 偏鴿",
      (cs.n_dovish, cs.n_hawkish, cs.net_lean) == (5, 2, "dovish"),
      f"{cs.n_dovish} 鴿 / {cs.n_hawkish} 鷹 / {cs.net_lean}")
check("⑦ 淨結論寫得出來", "降息" in chg.net_line(cs), chg.net_line(cs))

cs = chg.compare(snap({"n": "hawkish"}), snap({"o": "hawkish"}, month="2026-06"))
check("⑧ 一鷹一鴿 → 打平", cs.net_lean == "mixed",
      f"{cs.n_dovish}/{cs.n_hawkish}/{cs.net_lean}")

cs = chg.compare(snap({"a": "dovish"}), snap({"a": "dovish"}, month="2026-06"))
check("⑨ 沒有變化 → 沒有淨結論", chg.net_line(cs) == "")


# ---------------------------------------------------------------------------
# ③ 數字變動的顏色 ＝ 對利率的意思，不是漲跌
# ---------------------------------------------------------------------------
def mv(key, label, old, new, up_is):
    p = snap({"a": "dovish"}, {key: {"label": label, "value": old,
                                     "unit": "%", "threshold": 0.01,
                                     "up_is": up_is}}, month="2026-06")
    c = snap({"a": "dovish"}, {key: {"label": label, "value": new,
                                     "unit": "%", "threshold": 0.01,
                                     "up_is": up_is}})
    return chg.compare(c, p).metric_moves[0]

check("⑩ 核心 CPI 下降 → 偏降息",
      mv("cpi", "核心 CPI", 3.8, 3.3, "hawkish")["lean"] == "dovish")
check("⑪ 核心 CPI 上升 → 偏升息",
      mv("cpi", "核心 CPI", 3.3, 3.8, "hawkish")["lean"] == "hawkish")
# 這一條是重點：門檻變高代表同樣的非農其實更弱，數字是漲的但方向偏鴿
check("⑫ 損益兩平門檻上升 → 偏降息（不是偏升息）",
      mv("bk", "損益兩平", 4.3, 10.2, "dovish")["lean"] == "dovish")
check("⑬ 失業率上升 → 偏降息",
      mv("u3", "失業率", 4.1, 4.4, "dovish")["lean"] == "dovish")


# ---------------------------------------------------------------------------
# ④ 對照基準是資料版本，不是執行時間
# ---------------------------------------------------------------------------
cs = chg.compare(snap({"a": "dovish"}), snap({"a": "dovish"}, month="2026-06"))
check("⑭ 資料月份不同 → 認得出有新資料", cs.data_changed)
cs = chg.compare(snap({"a": "dovish"}), snap({"a": "dovish"}))
check("⑮ 資料月份相同 → 認得出沒有新資料", not cs.data_changed)

html = home._change_card(cs)
check("⑯ 沒有新資料時直說", "沒有新資料發布" in html,
      re.sub(r"<[^>]+>", " ", html).strip()[:60])
check("⑰ 不再拿執行時間當基準", "13:45" not in html)

# 新觸發一條鷹派 ＋ 解除一條鷹派 → 一鷹一鴿，兩欄都要出現。
# （注意不能用「新觸發鷹派 ＋ 解除鴿派」：那兩條的變化方向都是鷹，只會有一欄。）
cs = chg.compare(snap({"n": "hawkish"}), snap({"o": "hawkish"}, month="2026-06"))
html = home._change_card(cs)
check("⑱ 有新資料時標出資料版本", "6 月就業報告" in html)
check("⑲ 分成方向欄",
      'class="ccol hawkish"' in html and 'class="ccol dovish"' in html)
# ＋／− 不能帶顏色類別：顏色留給方向，一個元件不能同時表達兩件事
check("⑳ 增減標記不上色",
      'citem new' not in html and 'citem gone' not in html)

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
