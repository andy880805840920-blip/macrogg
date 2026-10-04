# 失去工作者比重（取代 Sahm）＋ 檢核區綜合判定的回歸測試（不打網路）
#
# 由來：2026-10 使用者要求就業格位的動能改看失去工作者佔失業人口比重，
# 並「對比過往每一次衰退」。門檻由 1967 起回測選定：
#   留意＝3 個月變化 z≥1.5（60 個月窗口）；警戒＝較一年低點上升 ≥3pp 連 2 個月。
# 這個檔案釘住回測結果（用 fixtures 裡的 FRED 實際歷史），門檻或算法
# 被改動時，歷次衰退的亮燈時間會跟著變——測試會擋下來逼人重看。
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src import fixtures                                    # noqa: E402
from src.analysis import job_losers as jl                   # noqa: E402
from src.analysis import regime                             # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過 " if cond else "失敗 "), name, ("— " + str(detail)[:140]) if detail else "")
    ok = ok and bool(cond)


ROWS = fixtures._job_losers_history()                       # 1967-01 … 2026-07

# ① 歷次衰退對照（數字＝亮燈月 − 衰退起點；負＝提前）
tab = {r["peak"]: r for r in jl.recession_table(ROWS)}
check("① 8 次衰退都有列", len(tab) == 8, list(tab))
want_alert = {"1969-12": 2, "1973-11": 3, "1980-01": -2, "1990-07": -1,
              "2001-03": 0, "2007-12": -4, "2020-02": 2}
got_alert = {k: tab[k]["alert_lead"] for k in want_alert}
check("①b 警戒：每次都在起點前後 4 個月內", got_alert == want_alert, got_alert)
want_watch = {"1973-11": 2, "1980-01": 3, "1990-07": -9, "2001-03": -7,
              "2007-12": -5, "2020-02": -6}
got_watch = {k: tab[k]["watch_lead"] for k in want_watch}
check("①c 留意：1990／2001／2007 提前 5–9 個月", got_watch == want_watch, got_watch)
check("①d 1969 的 z 值樣本不足（60 個月窗口要到 1972 才滿）",
      tab["1969-12"]["watch_na"] and tab["1969-12"]["watch_lead"] is None)
check("①e 1981 標成無法獨立檢驗", tab["1981-07"]["independent"] is False)
check("①f 歷次上升幅度都在 12 個百分點以上",
      all(r["rise"] >= 12 for r in tab.values()),
      {k: round(r["rise"], 1) for k, r in tab.items()})

# ② 誤報
fa = jl.false_alarms(ROWS)
check("② 留意誤報 5 次", fa["watch"] == ["1988-06", "1992-04", "2015-05",
                                         "2016-04", "2017-03"], fa["watch"])
check("②b 警戒誤報 2 次（1992、2024-01）", fa["alert"] == ["1992-05", "2024-01"],
      fa["alert"])

# ③ 當期（fixtures 尾端 2026-07）
s = jl.signals(ROWS)
check("③ 2026-07 正常", s["date"] == "2026-07" and s["state"] == "good", s)
check("③b 軌跡 12 期、每期有狀態", len(s["history"]) == 12
      and all(h["state"] in ("good", "warning", "critical") for h in s["history"]))

# ④ 單月缺值內插（2025-10 政府關門）；連缺兩個月不補
m = jl.monthly(ROWS)
check("④ 2025-10 以前後平均補上", abs(m[2025 * 12 + 9] - (46.8 + 45.7) / 2) < 1e-9)
gap2 = [r for r in ROWS if r["date"] not in ("2025-03-01", "2025-04-01")]
check("④b 連缺兩個月不補", 2025 * 12 + 2 not in jl.monthly(gap2))

# ⑤ 資料太短 → None；不會因此讓整頁壞掉
check("⑤ 少於 16 個月回 None", jl.signals(ROWS[:10]) is None)
check("⑤b 空資料的對照表是空的", jl.recession_table([]) == [])

# ⑥ 燈號：失去工作者比重由計算端直接給狀態，其他照門檻
cfgs = [{"key": "job_losers", "label": "失去工作者比重", "direction": "custom"},
        {"key": "quits_rate", "label": "離職率", "direction": "lower_is_worse",
         "green_above": 2.2, "red_below": 1.9}]
lts = regime.build_lights({jl.SERIES_ID: ROWS,
                           "JTSQUR": [{"date": "2026-06-01", "value": 2.0}]}, cfgs)
_j = lts[0]
check("⑥ 失去工作者燈：狀態＝計算端給的、顯示上升幅度",
      _j.status == "good" and "個百分點" in _j.display, (_j.status, _j.display))
check("⑥b 歷史軌跡沿用計算端狀態", len(_j.history) == 12)
check("⑥c 已移除的燈號不再出現（近三月新增、隱藏性失業、Sahm）",
      not ({"nfp_3m_avg", "u6_u3_gap", "sahm"}
           & set(regime._HISTORY_LABEL_FMT)))


# ⑦ 綜合判定（數燈號、不算分數）
def L(key, status):
    return regime.Light(key=key, label=key, desc="", value=1.0, prev=None,
                        status=status, display="")


V = regime.verdict
check("⑦ 失去工作者警戒 → 明確轉弱（就算其他全綠）",
      V([L("job_losers", "critical")] + [L("x", "good")] * 5)["label"] == "明確轉弱")
check("⑦b 3 項警戒 → 明確轉弱",
      V([L("a", "critical")] * 3 + [L("job_losers", "good")])["label"] == "明確轉弱")
check("⑦c 1 項警戒 → 轉弱跡象",
      V([L("a", "critical"), L("job_losers", "good")])["label"] == "轉弱跡象")
check("⑦d 3 項留意 → 轉弱跡象",
      V([L("a", "warning")] * 3 + [L("job_losers", "good")])["label"] == "轉弱跡象")
check("⑦e 2 項留意、無警戒 → 穩定",
      V([L("a", "warning")] * 2 + [L("job_losers", "good")] * 4)["label"] == "穩定")
check("⑦f 字眼不跟格位（強／中／弱）重疊",
      all(w not in ("強", "中", "弱") for w in ("明確轉弱", "轉弱跡象", "穩定")))

# ⑧ 警戒推格的端到端：格位、說明、下一格門檻都要對得起來
from src.analysis import scenario as S                      # noqa: E402
_lab = {"unrate": 3.8, "u_lo": 4.0, "u_hi": 4.3, "jl_alert": True,
        "jl_watch": True, "jl_rise": 3.4, "jl_z": 2.1, "tilt": {}, "flags": [],
        "score": 0.1, "nfp_3m": 50}
_inf = {"core_pce_yoy": 2.6, "core_pce_3m": 2.5,
        "bands": {"low": 2.3, "high": 2.9}, "flags": []}
_sc = S.synthesise(_lab, _inf, {"focus": {"focus": "balanced"}})
check("⑧ 水準「強」被推成「中」、方向轉弱",
      (_sc.labor_state, _sc.labor_level, _sc.labor_basis, _sc.labor_momentum)
      == ("中", "強", "job_losers", "轉弱"))
check("⑧b 說明寫出水準與推格原因", "「強」" in _sc.labor_basis_note
      and "3.4" in _sc.labor_basis_note)
_lt = [(t.label, t.direction) for t in _sc.triggers if t.axis == "labor"]
check("⑧c 下一格：警戒解除回「強」／水準轉中再往弱",
      _lt == [("就業轉「強」", "stronger"), ("就業轉「弱」", "weaker")], _lt)

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
