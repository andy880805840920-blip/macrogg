"""
PPI 發布日的機制（2026-10）：市場預估存檔、高於／低於預期訊號、本期變化、本次更新、快報、PPI 卡。不連網。
"""
import datetime as dt
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.analysis import ppi_watch as P  # noqa: E402
from src.analysis.rules import Flag  # noqa: E402

FAIL = []


def check(name, ok, info=""):
    print(("通過  " if ok else "失敗  ") + name + ("" if ok else f" — {info}"))
    if not ok:
        FAIL.append(name)


check("① 半進位到一位小數（0.25→0.3、0.649→0.6）", P.round1(0.25) == 0.3 and P.round1(0.649) == 0.6 and P.round1(-0.25) == -0.3)
st = {}
P.capture({"ppi|2026-10-15": [{"label": "PPI 月增", "forecast": "0.3%"}, {"label": "核心 PPI 月增", "forecast": "0.2%"}],
           "cpi|2026-10-14": [{"label": "CPI 月增", "forecast": "0.6%"}]}, st)
check("② 預估存檔：10/15 公布的是 9 月 PPI；只收 PPI", st["cons"]["2026-09"]["ppi_mom"] == 0.3
      and st["cons"]["2026-09"]["core_ppi_mom"] == 0.2 and len(st["cons"]) == 1, st)
pp = {"headline_mom": 0.71, "core_mom": 0.46, "core_3m": 4.0, "core_yoy": 3.5}
f = P.evaluate(pp, {"ppi_mom": 0.3, "core_ppi_mom": 0.2})
check("③ 高於預期 0.2 以上 → 「PPI 明顯高於預期」偏鷹，寫出實際與預估",
      f and f.key == "ppi_hot" and f.lean == "hawkish" and "PPI 月增 0.7%（預估 0.3%）" in f.detail
      and "核心 PPI 月增 0.5%（預估 0.2%）" in f.detail, f)
f2 = P.evaluate({"headline_mom": 0.04, "core_mom": 0.0}, {"ppi_mom": 0.3, "core_ppi_mom": 0.2})
check("④ 低於預期 → 「PPI 明顯低於預期」偏鴿", f2 and f2.key == "ppi_cool" and f2.lean == "dovish", f2)
check("⑤ 差距不到 0.2 → 沒有訊號", P.evaluate({"headline_mom": 0.36, "core_mom": 0.25}, {"ppi_mom": 0.3, "core_ppi_mom": 0.2}) is None)
f3 = P.evaluate({"headline_mom": 0.3, "core_mom": 0.3, "core_3m": 4.6, "core_yoy": 3.2}, {})
check("⑥ 沒預估：三月年化比年增高 1pp 以上 → 「上游漲價加速」", f3 and f3.key == "ppi_accel" and f3.lean == "hawkish", f3)
f4 = P.evaluate({"core_3m": 1.9, "core_yoy": 3.2}, {})
check("⑦ 沒預估：低 1pp 以上 → 「上游漲價降溫」", f4 and f4.key == "ppi_decel", f4)

# ⑧ update：插入訊號、不重排既有訊號、存檔
inf = {"ppi": {"headline_mom": 0.71, "core_mom": 0.46, "core_3m": 4.0, "core_yoy": 3.5, "asof": "2026-09-01"},
       "flags": [Flag("pce_reheating", "alert", "a", "", "hawkish", tier=1), Flag("ppi_pipeline", "watch", "b", "", "hawkish", tier=4)],
       "tilt": {}}
sp = Path(tempfile.mkdtemp()) / "ppi.json"
P.update({"inflation": inf}, False, sp, cons_map={"ppi|2026-10-15": [{"label": "PPI 月增", "forecast": "0.3%"}]})
keys = [x.key for x in inf["flags"]]
check("⑧ 訊號插在對應層級、既有訊號順序不變；月增與預估寫回 PPI 字典；預估有存檔",
      keys == ["pce_reheating", "ppi_hot", "ppi_pipeline"] and inf["ppi"]["mom"] == 0.7 and inf["ppi"]["cons"] == {"ppi_mom": 0.3}
      and json.loads(sp.read_text())["cons"]["2026-09"]["ppi_mom"] == 0.3 and inf["tilt"].get("tilt"), (keys, inf["ppi"]))
inf2 = {"ppi": {"headline_mom": 0.71, "core_mom": 0.46, "asof": "2026-09-01"}, "flags": [], "tilt": {}}
P.update({"inflation": inf2}, True, sp, cons_map={})
check("⑨ 下一週週曆查不到預估了：沿用存檔的預估，訊號照樣在", [x.key for x in inf2["flags"]] == ["ppi_hot"], inf2["flags"])

# ⑩ 本期變化：PPI 自己一個期別
from src.analysis import changes as C  # noqa: E402
snap = C.snapshot({"inflation": {"data_month": "2026-09", "tilt": {"tilt": "hawkish"}, "flags": [], "ppi": inf["ppi"]}})
m = snap["modules"].get("ppi") or {}
check("⑩ 本期變化有 PPI 單位：期別 2026-09、PPI 月增／核心月增／核心年增",
      m.get("vintage") == "2026-09" and m["metrics"]["ppi_mom"]["value"] == 0.7
      and m["metrics"]["core_ppi_mom"]["value"] == 0.5 and m["metrics"]["core_ppi_yoy"]["value"] == 3.5, m)
prev = {"at": "x", "modules": {"ppi": {"current": dict(m, vintage="2026-08", metrics={
    "ppi_mom": dict(m["metrics"]["ppi_mom"], value=0.2), "core_ppi_mom": dict(m["metrics"]["core_ppi_mom"], value=0.2),
    "core_ppi_yoy": dict(m["metrics"]["core_ppi_yoy"], value=3.3)})}}}
cs = C.compare(C.roll(prev, {"at": "y", "modules": {"ppi": m}}))
mv = {x["key"]: x for x in cs.metric_moves if x.get("module") == "ppi"}
check("⑪ PPI 換期別時列出變動（PPI 月增 0.2 → 0.7）", "ppi_mom" in mv and abs(mv["ppi_mom"]["delta"] - 0.5) < 1e-9, cs.metric_moves)

# ⑫ 本次更新的發布清單
from src.analysis import brief as B  # noqa: E402
check("⑫ 本次更新認得 PPI 發布", B._RELEASES.get("ppi", {}).get("module") == "ppi")

# ⑬ 快報第 4 則「最新數據」
from src.analysis import stories as S  # noqa: E402
rel = {"inflation": {"month": "2026-09", "first_seen": "2026-10-14T21:03+08:00"},
       "ppi": {"month": "2026-09", "first_seen": "2026-10-15T21:03+08:00"}}
ctxs = {"inflation": {"data_month": "2026-09", "kpi": {"core_display": "0.3%"}, "ppi": inf["ppi"]},
        "_watch_extra": {"consensus": {"ppi|2026-10-15": [{"label": "PPI 月增", "forecast": "0.3%", "previous": "0.1%"}]}}}
lr = S.latest_release(ctxs, rel)
check("⑬ PPI 日：快報最新數據是 PPI，標「高於預估」", lr and "PPI" in lr.get("name", "")
      and lr["rows"][0]["label"] == "PPI 月增" and lr["rows"][0]["vs"] == "高於預估", lr)

# ⑭ 通膨頁 PPI 卡
from src.pages.inflation import _ppi_card  # noqa: E402
h = _ppi_card(dict(inf["ppi"], headline_yoy=3.0, gap_vs_cpi=0.9))
check("⑭ PPI 卡：月增與預估（高於預估 +0.4）", "PPI 月增" in h and "0.7%" in h and "預估 0.3%・高於預估 +0.4" in h, h[:0])

rel2 = dict(rel, claims={"month": "2026-10-10", "first_seen": "2026-10-16T21:03+08:00"})
ctxs2 = dict(ctxs, labor={"claims": {"machine": {"week": "2026-10-10", "ic_now": 230000, "ic_ma": 225000}}})
lr2 = S.latest_release(ctxs2, rel2)
check("⑮ 週四初領失業金公布後，快報最新數據仍是 PPI（失業金不放）", lr2 and "PPI" in lr2.get("name", ""), lr2)

print()
print("有失敗" if FAIL else "全部通過")
sys.exit(1 if FAIL else 0)
