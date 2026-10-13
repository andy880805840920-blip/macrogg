"""
首頁「接下來看什麼・休市」（2026-10）：七個市場的休市與提早收盤。
不連網（holidays 套件是本機資料），結果固定。
"""
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.analysis import market_holidays as mh  # noqa: E402

FAIL = []


def check(name, ok, info=""):
    print(("通過  " if ok else "失敗  ") + name + ("" if ok else f" — {info}"))
    if not ok:
        FAIL.append(name)


D = dt.date
ev = mh.market_events(D(2026, 10, 13), D(2027, 7, 10), overrides=[])
by = {(e["mk"], e["date"]): e for e in ev}

e = by.get(("US", D(2026, 11, 11)))
check("① 退伍軍人節：美債、匯休市，美股照常",
      e and e["closed"] == ["bd", "fx"] and mh.status_text(e)[0] == "部分休市"
      and "官方殖利率" in e["note"], e)
e = by.get(("US", D(2026, 11, 26)))
check("② 感恩節：美國全部休市", e and len(e["closed"]) == 3 and mh.status_text(e)[0] == "全部休市", e)
e = by.get(("US", D(2026, 11, 27)))
check("③ 感恩節隔天：股市 13:00、債市 14:00 提早收盤，台灣隔日 02:00",
      e and e["early"] == {"eq": "13:00", "bd": "14:00"} and e["tw"] == "隔日 02:00"
      and e["name"] == "感恩節隔天", e)
e = by.get(("US", D(2026, 12, 31)))
check("④ 美債元旦前一天 14:00 提早收盤（冬令＝台灣隔日 03:00）",
      e and e["early"] == {"bd": "14:00"} and e["tw"] == "隔日 03:00", e)
e = by.get(("US", D(2027, 3, 26)))
check("⑤ 耶穌受難日：股、債休市，美元照常交割", e and e["closed"] == ["eq", "bd"], e)
check("⑥ 六月節不會被當成獨立紀念日（6/17 沒有債市提早收盤）",
      ("US", D(2027, 6, 17)) not in by, by.get(("US", D(2027, 6, 17))))
e = by.get(("TW", D(2026, 10, 26)))
check("⑦ 台灣光復節補假：全部休市、名稱縮寫、附網站影響",
      e and len(e["closed"]) == 3 and e["name"] == "光復節（補假）" and "台指期" in e["note"], e)
e = by.get(("TW", D(2027, 2, 2)))
check("⑧ 台灣春節前無交易日：只有股市不交易，債、匯照常",
      e and e["closed"] == ["eq"] and mh.status_text(e)[0] == "部分休市", e)
e = by.get(("HK", D(2026, 12, 24)))
check("⑨ 香港平安夜半日市：12:00 收", e and e["early"] == {"eq": "12:00"} and e["name"] == "平安夜", e)
e = by.get(("JP", D(2026, 12, 31)))
check("⑩ 日本 12/31 年末休市", e and len(e["closed"]) == 3, e)
check("⑪ 週末不列", all(x["date"].weekday() < 5 for x in ev))

ov = [{"date": "2027-03-26", "market": "US", "closed": ["eq"], "early": {"bd": "12:00"},
       "note": "SIFMA 建議債市中午提早收盤"},
      {"date": "2026-10-19", "market": "HK", "remove": True}]
ev2 = mh.market_events(D(2026, 10, 13), D(2027, 7, 10), overrides=ov)
by2 = {(e["mk"], e["date"]): e for e in ev2}
e = by2.get(("US", D(2027, 3, 26)))
check("⑫ 手動修正：耶穌受難日改成股休、債提早收盤",
      e and e["closed"] == ["eq"] and e["early"] == {"bd": "12:00"} and "SIFMA" in e["note"], e)
check("⑬ 手動修正：remove 拿掉整筆", ("HK", D(2026, 10, 19)) not in by2 and ("HK", D(2026, 10, 19)) in by)

print()
print("有失敗" if FAIL else "全部通過")
sys.exit(1 if FAIL else 0)
