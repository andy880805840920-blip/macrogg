# 今日市場焦點：確定性部分的回歸測試（不打任何網路）
import sys
import pathlib
import datetime as dt

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.analysis import focus_today as ft                # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過 " if cond else "失敗 "), name, ("— " + str(detail)[:90]) if detail else "")
    ok = ok and bool(cond)


# ① 殖利率 chip：最新值＋較前一交易日的變動（基點）
rows = [{"date": "2026-08-19", "value": 4.67},
        {"date": "2026-08-20", "value": 4.69}]
c = ft._yield_chip(rows, "10 年期")
check("① 殖利率變動以基點計", c["delta_bp"] == 2 and c["value"] == 4.69, c)
check("①b 少於兩筆不硬算", ft._yield_chip(rows[:1], "x") is None)

# ② 數字防護欄：輸出的數字必須出現在標題裡
src = "- [路透] 川普再批聯準會，10 年期殖利率升至 4.7%"
check("② 標題裡有的數字放行", ft._digits_ok("殖利率升至 4.7%", src))
check("②b 編出來的數字擋下", not ft._digits_ok("市場預期年底降至 3.5%", src))

# ③ 確定性退回挑選：關鍵字命中多者優先、同分保持新的在前
now = dt.datetime.now(dt.timezone.utc)
hs = [
    {"title": "美股收漲", "link": "", "source": "", "at": (now).isoformat()},
    {"title": "川普點名 Kevin Warsh 接任聯準會主席", "link": "", "source": "",
     "at": (now - dt.timedelta(hours=2)).isoformat()},
    {"title": "貝森特談美國財政部發債計畫", "link": "", "source": "",
     "at": (now - dt.timedelta(hours=1)).isoformat()},
]
kw = ["川普 聯準會", "Kevin Warsh", "貝森特", "美國財政部"]
picked = ft.pick_fallback(hs, kw, n=2)
check("③ 命中關鍵字的標題排前面", picked[0]["title"].startswith("川普點名"),
      [p["title"][:12] for p in picked])
check("③b 不相關的標題被擠掉", all("美股" not in p["title"] for p in picked))

# ④ RSS 解析：假的回應也要能走完（含去重與時間過濾）
_XML = """<rss><channel>
<item><title>川普再批聯準會 - 路透</title><link>http://a</link>
  <pubDate>{new}</pubDate><source>路透</source></item>
<item><title>川普再批聯準會 - 中央社</title><link>http://b</link>
  <pubDate>{new}</pubDate><source>中央社</source></item>
<item><title>三個月前的舊聞</title><link>http://c</link>
  <pubDate>{old}</pubDate><source>x</source></item>
</channel></rss>"""


class _Fake:
    def __init__(self, content):
        self.content = content.encode("utf-8")

    def raise_for_status(self):
        pass


_new = now.strftime("%a, %d %b %Y %H:%M:%S GMT")
_old = (now - dt.timedelta(days=90)).strftime("%a, %d %b %Y %H:%M:%S GMT")
out = ft.fetch_headlines(["川普"], _get=lambda u: _Fake(
    _XML.format(new=_new, old=_old)))
check("④ 同一則新聞不同來源只留一則", len(out) == 1,
      [o["title"] for o in out])
check("④b 超過時間窗的舊聞被濾掉", all("舊聞" not in o["title"] for o in out))

# ⑤ 近似重複的標題只選一則：同一件事在不同媒體改幾個字，完全比對擋不住
hs2 = [
    {"title": "川普再度砲轟聯準會主席，暗示將撤換 - 路透", "link": "", "source": "",
     "at": now.isoformat()},
    {"title": "川普再度砲轟聯準會主席 暗示撤換 - Yahoo奇摩財經", "link": "",
     "source": "", "at": (now - dt.timedelta(minutes=5)).isoformat()},
    {"title": "貝森特談美國財政部發債計畫 - 中央社", "link": "", "source": "",
     "at": (now - dt.timedelta(hours=1)).isoformat()},
]
p2 = ft.pick_fallback(hs2, ["川普 聯準會", "貝森特"], n=2)
check("⑤ 近似重複標題只留一則", len(p2) == 2
      and sum(1 for x in p2 if "川普" in x["title"]) == 1,
      [x["title"][:14] for x in p2])

# ⑥ 來源白名單：只留 yahoo 系；全部沒命中時退回不過濾（在 build 層）
hs3 = [
    {"title": "A", "source": "Yahoo奇摩財經"},
    {"title": "B", "source": "Yahoo Finance"},
    {"title": "C", "source": "路透"},
]
_srcs = ["yahoo"]
hits = [h for h in hs3 if any(w in h["source"].lower() for w in _srcs)]
check("⑥ 白名單命中 Yahoo 系來源", [h["title"] for h in hits] == ["A", "B"])
check("⑥b 沒命中時退回全部（邏輯）",
      ([h for h in [{"title": "C", "source": "路透"}]
        if any(w in h["source"].lower() for w in _srcs)] or hs3) == hs3)

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
