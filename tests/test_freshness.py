"""
資料停更偵測的測試。

這個檢查的價值全在門檻上：太緊會每個月月初都跳警告（月頻資料本來就
落後三十幾天），太鬆則等於沒有。兩個方向都要釘住。

    python tests/test_freshness.py
"""
import sys
import pathlib
import datetime as dt

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from src.analysis import freshness  # noqa: E402
from src.site import esc  # noqa: E402

TODAY = dt.date(2026, 8, 11)
ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    print(f"{'通過' if cond else '失敗'}  {name}" + (f" — {detail}" if detail else ""))
    ok &= bool(cond)


def one(sid: str, date: str) -> dict:
    return {sid: [{"date": date, "value": 1.0}]}


ids = lambda st: {s["id"] for s in st}  # noqa: E731

# ---- 正常落後不能報警 ----
# 7 月的就業報告在 8 月第一個週五發布，資料日期是 2026-07-01，
# 到 8/11 已經落後 41 天——這是**完全正常**的，報了就是誤報。
check("① 月頻正常落後 41 天不報警",
      not freshness.check(one("PAYEMS", "2026-07-01"), TODAY))
# 週頻資料公布時通常已是一兩週前那一週
check("② 週頻正常落後 10 天不報警",
      not freshness.check(one("ICSA", "2026-08-01"), TODAY))
# 日頻遇到連假可能空好幾天
check("③ 日頻落後 4 天不報警",
      not freshness.check(one("DGS10", "2026-08-07"), TODAY))

# ---- 真的停更要報 ----
check("④ 月頻落後四個月要報警",
      ids(freshness.check(one("PAYEMS", "2026-04-01"), TODAY)) == {"PAYEMS"})
check("⑤ 週頻落後兩個月要報警",
      ids(freshness.check(one("ICSA", "2026-06-05"), TODAY)) == {"ICSA"})
check("⑥ 日頻落後三週要報警",
      ids(freshness.check(one("DGS30", "2026-07-18"), TODAY)) == {"DGS30"})

# ---- 抓取失敗不算停更 ----
# 空序列是「抓不到」，已經由 failed 清單負責。在這裡再報一次，
# 同一件事會在畫面上出現兩遍，而且兩段文字講的原因還不一樣。
check("⑦ 空序列不算停更", not freshness.check({"PAYEMS": []}, TODAY))
check("⑧ 沒抓的序列不算停更", not freshness.check({}, TODAY))

# ---- 髒資料不能讓整份報告掛掉 ----
bad = {"PAYEMS": [{"date": "not-a-date", "value": 1}],
       "UNRATE": [{"value": 1}],
       "ICSA": [{"date": None, "value": 1}]}
try:
    r = freshness.check(bad, TODAY)
    check("⑨ 日期格式壞掉不會爆", True, f"回傳 {len(r)} 筆")
except Exception as e:  # noqa: BLE001
    check("⑨ 日期格式壞掉不會爆", False, repr(e))

# ---- 排序：最嚴重的排前面 ----
st = freshness.check({**one("PAYEMS", "2026-04-01"),
                      **one("DGS10", "2026-07-25")}, TODAY)
check("⑩ 超標最多的排最前面", st and st[0]["id"] == "PAYEMS",
      "、".join(s["id"] for s in st))

# ---- 警告條 ----
check("⑪ 沒有停更就不畫警告條", freshness.banner_html([], esc) == "")
html = freshness.banner_html(freshness.check(one("PAYEMS", "2026-04-01"), TODAY),
                             esc)
check("⑫ 警告條有序列名與最後日期",
      "非農就業" in html and "2026-04-01" in html)
# 五條以上要收成「另有 N 條」，不能整串印出來把版面淹掉
many = {sid: [{"date": "2026-01-01", "value": 1}] for sid in freshness.WATCH}
html = freshness.banner_html(freshness.check(many, TODAY), esc)
check("⑬ 停更太多時收合", "另有" in html, html[-60:])

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
