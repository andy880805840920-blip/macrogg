"""
第十八批的規則測試（不連網）。

  A. 通膨門檻跟格位同一套規則（不再用綜合水準）
  B. 聯準會主席是華許
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analysis import scenario as sc  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("通過  " if ok else "失敗  ") + name + (f" — {detail}" if detail else ""))
    if not ok:
        FAILED.append(name)


# ---------------------------------------------------------------------------
# A. 通膨門檻
# ---------------------------------------------------------------------------
BANDS = {"low": 2.25, "high": 2.50}
LAB = {"unrate": 4.2, "u_lo": 4.0, "u_hi": 4.3}


def infl(yoy=3.01, sc2=(2.4, 2.13), m3=2.05, m6=2.7):
    return {"core_pce_yoy": yoy, "core_pce_3m": m3, "core_pce_6m": m6,
            "supercore_last2": list(sc2) if sc2 else None, "bands": BANDS}


def trig(inf, state=None):
    st = state or sc.classify_inflation(inf["core_pce_yoy"], inf["core_pce_3m"], BANDS,
                                        inf["core_pce_6m"], inf["supercore_last2"])
    return st, [t for t in sc._triggers(LAB, inf, "中", st, "通膨") if t.axis == "inflation"]


st, ts = trig(infl())
check("A1 目前格位＝高（年增 3.01% 定格）", st == "高", st)
check("A2 不再出現「綜合通膨水準」", all("綜合" not in t.current for t in ts),
      [t.current for t in ts])
lv = [t for t in ts if t.adjacent and t.current.startswith("核心 PCE 年增")]
scp = [t for t in ts if t.adjacent and t.current.startswith("Supercore")]
check("A3 相鄰門檻有兩條路：年增跌破 2.50%、Supercore 連兩月 < 2.1%",
      len(lv) == 1 and len(scp) == 1 and "2.50" in lv[0].threshold and "2.1" in scp[0].threshold,
      [(t.current, t.threshold) for t in ts])
check("A4 Supercore 那條距離＝2.13−2.1", scp and scp[0].distance == "還差 0.03 個百分點",
      scp and scp[0].distance)
check("A5 白話條件不寫「還差」", all(t.plain and "還差" not in t.plain for t in ts),
      [t.plain for t in ts])


# 模擬驗證：照每條門檻的條件把數字改掉，格位真的到達宣稱的那一格
def lands(t, inf):
    tgt = t.label[-2]
    x = dict(inf)
    if t.current.startswith("核心 PCE 年增"):
        thr = float(t.threshold.split()[-1].rstrip("%"))
        x["core_pce_yoy"] = thr - 0.01 if t.direction == "down" else thr + 0.01
    elif t.current.startswith("Supercore"):
        if "連續兩個月低於" in t.threshold:
            x["supercore_last2"] = [sc.SC_LO - 0.05] * 2
        elif "連續兩個月高於" in t.threshold:
            x["supercore_last2"] = [sc.SC_HI + 0.05] * 2
        else:
            x["supercore_last2"] = [sc.SC_ANCHOR] * 2
    got = sc.classify_inflation(x["core_pce_yoy"], x["core_pce_3m"], BANDS,
                                x["core_pce_6m"], x["supercore_last2"])
    return got == tgt, got


cases = [infl(), infl(sc2=(1.9, 2.0)), infl(sc2=(3.9, 4.0)), infl(yoy=2.4, sc2=(2.8, 2.9)),
         infl(yoy=2.1, sc2=(2.8, 2.9)), infl(yoy=2.1, sc2=(3.8, 3.9)), infl(yoy=2.4, sc2=(1.8, 1.9))]
bad = []
for c in cases:
    _, tt = trig(c)
    for t in tt:
        if not t.adjacent:
            continue
        ok, got = lands(t, c)
        if not ok:
            bad.append((c["core_pce_yoy"], c["supercore_last2"], t.label, t.threshold, got))
check("A6 每條相鄰門檻照條件模擬後，格位真的到宣稱的那一格", not bad, bad)

_, tt = trig(infl())
unlock = [t for t in tt if not t.adjacent]
check("A7 通膨優先時，政策解鎖條件＝轉「低」且標關鍵",
      len(unlock) == 1 and unlock[0].binding and unlock[0].label == "通膨轉「低」",
      [(t.label, t.binding) for t in unlock])

lab_t = [t for t in sc._triggers(LAB, infl(), "中", "高", "通膨") if t.axis == "labor"]
check("A8 就業白話：高於 4.3% → 失業率升到 4.4% 以上",
      any(t.plain == "失業率升到 4.4% 以上（目前 4.2%）" for t in lab_t),
      [t.plain for t in lab_t])

# ---------------------------------------------------------------------------
# B. 主席是華許
# ---------------------------------------------------------------------------
from src.analysis import focus_today as ft  # noqa: E402

for src, want in (("聯準會主席鮑爾表示", "前主席鮑爾表示"), ("Fed Chair Powell said", None),
                  ("鮑爾主席", "前主席鮑爾"), ("前主席鮑爾", "前主席鮑爾"),
                  ("前聯準會主席鮑爾", "前聯準會主席鮑爾"), ("主席華許", "主席華許")):
    got = ft.normalize_names(src)
    if want:
        check(f"B1 稱謂修正：{src}", got == want, got)
check("B2 提示詞寫明現任主席華許、鮑爾不得稱主席",
      "現任主席是華許" in ft._NEWS_RULES and "不要稱他為主席" in ft._NEWS_RULES)
check("B3 FOMC 事件詞改用 Warsh／華許", "Warsh" in ft.EVENT_WORDS["fomc"]
      and "Powell" not in ft.EVENT_WORDS["fomc"])
import yaml  # noqa: E402
_cfg = yaml.safe_load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                        "config", "focus.yaml"), encoding="utf-8"))
check("B4 主級關鍵字有華許、沒有鮑爾；鮑爾降為次級",
      "Warsh" in _cfg["keywords"] and "Powell" not in _cfg["keywords"]
      and "Powell" in _cfg["keywords_secondary"])

# ---------------------------------------------------------------------------
# C. 新指標、三段累計、MTD／YTD
# ---------------------------------------------------------------------------
import datetime as _dt  # noqa: E402
_F = ["2026-10-28", "2026-12-09", "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09",
      "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08"]
check("C1 十月：今年底、明年中、明年底",
      [h[1] for h in ft.fw_horizons(_F, _dt.date(2026, 10, 11))] == ["2026 年底", "2027 年中", "2027 年底"])
check("C2 年底會議過後自動滾動（缺下一年日程只剩兩個）",
      [h[1] for h in ft.fw_horizons(_F, _dt.date(2026, 12, 15))] == ["2027 年中", "2027 年底"])
check("C3 一月：今年中、今年底", [h[1] for h in ft.fw_horizons(_F, _dt.date(2027, 1, 5))]
      == ["2027 年中", "2027 年底"])
_pts = [("2025-12-30", 4.0), ("2025-12-31", 4.1), ("2026-09-29", 4.5), ("2026-09-30", 4.6),
        ("2026-10-01", 4.7), ("2026-10-09", 4.8)]
check("C4 MTD 基準＝上月底、YTD 基準＝去年底", ft._period_bases(_pts, "2026-10-09") == (4.6, 4.1),
      ft._period_bases(_pts, "2026-10-09"))
_rows = [{"date": d, "value": v} for d, v in _pts]
_c = ft._pct_chip("dgs10", "10 年期", _rows)
check("C5 殖利率 chip 帶 MTD／YTD 資料", _c.get("k") == "bp" and _c.get("bm") == 4.6
      and _c.get("by") == 4.1 and _c.get("num") == 4.8, _c)
_cat = ft.build_catalog({}, {}, [], offline=True)
_ids = [c["id"] for c in _cat]
check("C6 目錄有 7Y／20Y、三段累計、S&P／NASDAQ／加權、三組匯率",
      all(x in _ids for x in ("dgs7", "dgs20", "fw_h1", "fw_h2", "fw_h3", "spx", "ixic",
                              "twii", "eurusd", "usdjpy", "usdcnh")), _ids)
import yaml as _y  # noqa: E402
_tp = {t["id"]: t.get("chips") or [] for t in _cfg.get("topics") or []}
check("C7 新指標都對應到補充新聞主題",
      "spx" in _tp["equity"] and "twii" in _tp["twf"] and "usdjpy" in _tp["fx"]
      and "dgs20" in _tp["long"] and "fw_h3" in _tp["fed"], _tp)
_js = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "netlify", "functions", "quotes.mjs"), encoding="utf-8").read()
check("C8 盤中報價函式有新代號", all(x in _js for x in ("^GSPC", "^IXIC", "^TWII", "EURUSD=X",
                                                        "JPY=X", "CNH=X")))

# ---------------------------------------------------------------------------
# D. 整體情勢語氣鎖、修正不再是訊號、本期變化加權
# ---------------------------------------------------------------------------
from src.analysis import brief as _br, rules as _ru  # noqa: E402
_pk = {"infl_state": "高", "infl_mom": "持平", "labor_state": "中", "labor_mom": "持平"}
check("D1 通膨高＋持平寫「降溫趨勢明確」→ 退回",
      "降溫趨勢明確" in _br._tone_issues([("通膨", "三月年化 2.0%，降溫趨勢明確。")], _pk))
check("D2 就業中＋持平寫「韌性有限」→ 退回",
      "韌性有限" in _br._tone_issues([("勞動市場", "顯示勞市韌性有限。")], _pk))
check("D3 合乎格位的寫法放行",
      _br._tone_issues([("通膨", "近三月放緩，但降溫能否延續尚待確認。"),
                        ("勞動市場", "失業率仍在充分就業區間內。")], _pk) == "")
check("D4 通膨方向真的降溫時可以寫降溫",
      _br._tone_issues([("通膨", "已經降溫。")], {**_pk, "infl_mom": "降溫"}) == "")
check("D5 修正類規則不進訊號", {"revision_swamps", "revision_bias_down", "benchmark_revision"}
      <= _ru.DISABLED_KEYS)
from src.pages import home as _home  # noqa: E402
from types import SimpleNamespace as _NS  # noqa: E402
_cs = _NS(has_previous=True, scenario_moved=False, headline="", resolved_flags=[], metric_moves=[],
          new_flags=[{"module": "就業", "title": f"就業{i}", "change_lean": "dovish"} for i in range(4)]
          + [{"module": "物價", "title": "通膨甲", "change_lean": "hawkish"},
             {"module": "物價", "title": "通膨乙", "change_lean": "hawkish"}])
_h = _home._hm_changes(_cs, "inflation")
check("D6 通膨優先：4 條就業偏鴿 vs 2 條通膨偏鷹（×2）→ 鷹鴿大致抵銷、通膨排前面",
      "鷹鴿大致抵銷" in _h and _h.index("通膨甲") < _h.index("就業0"), _h[:300])
check("D7 不再出現「整體往降息方向傾斜」", "降息方向傾斜" not in _home._hm_changes(_cs, ""))

# ---------------------------------------------------------------------------
# E. 接下來看什麼：市場預估、標售、回購、官員談話
# ---------------------------------------------------------------------------
from src.analysis import watch_extra as wx  # noqa: E402
_ff = [{"title": "Core CPI m/m", "country": "USD", "date": "2026-10-14T08:30:00-04:00",
        "forecast": "0.2%", "previous": "0.3%"},
       {"title": "Non-Farm Employment Change", "country": "USD", "date": "2026-11-06T08:30:00-05:00",
        "forecast": "55K", "previous": "29K"},
       {"title": "Unemployment Claims", "country": "USD", "date": "2026-10-15T08:30:00-04:00",
        "forecast": "195K", "previous": "197K"},
       {"title": "FOMC Member Hammack Speaks", "country": "USD", "date": "2026-10-12T12:10:00-04:00"},
       {"title": "Fed Chairman Warsh Speaks", "country": "USD", "date": "2026-10-15T23:30:00-04:00"}]
_cm = wx.consensus_map(_ff)
check("E1 市場預估對到事件與美東日期", _cm["cpi|2026-10-14"][0] == {
    "label": "核心 CPI 月增", "forecast": "0.2%", "previous": "0.3%"}, _cm)
check("E2 人數換成萬（非農帶正負號）", _cm["employment|2026-11-06"][0]["forecast"] == "+5.5 萬"
      and _cm["claims|2026-10-15"][0]["forecast"] == "19.5 萬", _cm)
_fed = [{"name": "Warsh", "role": "主席", "et": _dt.datetime(2026, 10, 15, 23, 30),
         "et_date": "2026-10-15", "kind": "對談", "topic": "", "where": "", "src": "聯準會官網"}]
_sp = wx.merge_speeches(_fed, wx.ff_speeches(_ff), {2026: ["Hammack"]}, ["Warsh"],
                        _dt.date(2026, 10, 11))
check("E3 官網＋ForexFactory 合併、同人同日不重複、票委標記、地區聯儲加銀行名",
      [(x["zh"], x["voter"]) for x in _sp] == [("哈瑪克", True), ("華許", True)]
      and _sp[0]["role"] == "克里夫蘭聯儲總裁", [(x["zh"], x["role"], x["voter"]) for x in _sp])
check("E4 增發期別正規化：19 年 10 個月 → 20 年期（增發）",
      wx._term_label("19-Year 10-Month") == ("20 年期", True))
_tas = wx.parse_tentative_auctions(
    "20-Year BOND R Thursday, October 15, 2026 Wednesday, October 21, 2026 Monday, October 26, 2026\n"
    "13-Week BILL Thursday, October 15, 2026 Monday, October 19, 2026 Thursday, October 22, 2026\n"
    "5-Year TIPS RT Thursday, October 15, 2026 Thursday, October 22, 2026 Friday, October 30, 2026")
check("E5 暫定標售表：只取附息債、TIPS 與增發旗標",
      [(a["date"], a["years"], a["kind"], a["reopen"]) for a in _tas]
      == [("2026-10-21", "20 年期", "", True), ("2026-10-22", "5 年期", "TIPS", True)], _tas)
_bb = wx.parse_buybacks("Nominal Coupons 10/16/2036 -\n10/14/2026 10/15/2026 1:40 pm –2:00 pm "
                        "10/16/2026 Liquidity Support $0 = or > $4 billion\n10Y to 20Y 10/15/2046")
check("E6 回購時程：日期、區間、上限", _bb and _bb[0]["date"] == "2026-10-15"
      and _bb[0]["segment"] == "名目債 10Y–20Y" and _bb[0]["max"] == "最多 40 億美元", _bb)
check("E7 離線不連網", wx.collect({}, offline=True) == {})

print()
print("全部通過" if not FAILED else f"有失敗（{len(FAILED)}）")
sys.exit(1 if FAILED else 0)
