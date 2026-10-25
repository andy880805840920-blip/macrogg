"""
「對利率」以 10 年期即時報價對照（2026-10）：解讀的是主軸新聞，10 年期今日變動只拿來
對照市場有沒有反映；盤中／收盤照實標示；抓不到退回官方近 5 日。不連網。
"""
import datetime as dt
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.analysis import focus_today as F  # noqa: E402

FAIL = []


def check(name, ok, info=""):
    print(("通過  " if ok else "失敗  ") + name + ("" if ok else f" — {info}"))
    if not ok:
        FAIL.append(name)


U = dt.timezone.utc


def bars(day, start_h, start_m, vals, step=5):
    t0 = dt.datetime(*day, start_h, start_m, tzinfo=U)
    return [(int((t0 + dt.timedelta(minutes=step * i)).timestamp()), v) for i, v in enumerate(vals)]


# 10/13 收在 52.17（×10 慣例＝5.217%）；10/14 盤中
B = bars((2026, 10, 13), 19, 0, [52.10, 52.15, 52.17]) + bars((2026, 10, 14), 12, 15, [51.95, 51.90, 51.90, 52.87, 53.02, 53.04])


def fake(bs):
    def get(url):
        assert "%5ETNX" in url
        return types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"chart": {"result": [{
            "meta": {"regularMarketPrice": bs[-1][1], "regularMarketTime": bs[-1][0]},
            "timestamp": [t for t, _ in bs], "indicators": {"quote": [{"close": [v for _, v in bs]}]}}]}})
    return get


now = dt.datetime(2026, 10, 14, 12, 50, tzinfo=U)
lv = F.live_10y(now, _get=fake(B))
check("① 盤中：5.30%、今日 +9bp（較前一交易日收盤）、美東 08:40 盤中",
      {k: v for k, v in (lv or {}).items() if k != "ts"}
      == {"now": 5.30, "d_today": 9, "at_et": "08:40", "date_et": "2026-10-14", "open": True}, lv)
# v2：多帶報價時間（UTC），給市場訊號判斷「超過 12 小時不加分」
check("①b 報價時間 ts＝美東 08:40＝UTC 12:40", lv and lv.get("ts") == dt.datetime(2026, 10, 14, 12, 40, tzinfo=U), lv)
lv2 = F.live_10y(dt.datetime(2026, 10, 14, 23, 3, tzinfo=U), _get=fake(B))
check("② 隔天早上：標示收盤", lv2 and not lv2["open"] and lv2["d_today"] == 9, lv2)


def boom(url):
    raise RuntimeError("blocked")


check("③ 抓不到：回 None", F.live_10y(now, _get=boom) is None)
check("④ 報價不是 ×10 慣例也能讀", F.live_10y(now, _get=fake([(t, v / 10) for t, v in B]))["now"] == 5.30)
rc = {"d2": 5, "d10": -10, "d30": 2, "from": "10/7", "to": "10/13", "zh": "熊市趨陡", "lead": "", "code": "", "live10": lv}
blk = F._rate_block(rc)
check("⑤ 有即時：只給 10 年期（不再混入近 5 日 2 年／30 年，避免「近一週上升但 -10bp」的矛盾）",
      "10 年期 5.30%，今日 +9bp" in blk and "美東 10/14 08:40 盤中" in blk and "2 年期" not in blk and "-10bp" not in blk, blk)
check("⑥ 收盤時標「收盤」", "美東 10/14 收盤" in F._rate_block(dict(rc, live10=lv2)))
check("⑦ 抓不到即時：退回官方近 5 日", "2 年期 +5bp、10 年期 -10bp" in F._rate_block(dict(rc, live10=None)))
check("⑧ 備用句也改用 10 年期即時", F._rate_fallback(rc) == "10 年期殖利率今日 +9bp 至 5.30%（美東 08:40 盤中），上升。", F._rate_fallback(rc))
note_bad = "CPI 意外升溫偏向推升利率預期，尤其長端。"
rc_dn = dict(rc, live10=dict(lv, d_today=-6))
iss = F._rate_issues(note_bad, rc_dn, F._rate_block(rc_dn))
check("⑨ 新聞偏推升、10 年期今日 -6bp 卻沒點出落差 → 退回重寫", any("今日走勢（10 年期 -6bp）" in x for x in iss), iss)
ok_note = "CPI 意外升溫偏向推升利率預期，不過 10 年期今日 -6bp 至 5.30%，市場還沒反映。"
check("⑩ 點出落差並引用今日 10 年期 → 通過", F._rate_issues(ok_note, rc_dn, F._rate_block(rc_dn)) == [],
      F._rate_issues(ok_note, rc_dn, F._rate_block(rc_dn)))

print()
print("有失敗" if FAIL else "全部通過")
sys.exit(1 if FAIL else 0)
