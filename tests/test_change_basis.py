"""
「本期變化」的比對基準測試 — 每個模組跟自己的上一期發布比。

為什麼需要這個檔案
------------------
先前的比較視窗只有 24 小時：快照每次執行都被覆蓋，所以就業報告落地當天
卡片會亮，隔天比較變成「今天 vs 昨天」＝沒有變化，卡片就熄了。
**讀者在發布後第三天打開網站，等於完全錯過那張卡。**

改成以「資料期別」為輪替條件之後，有三件事錯了會完全看不出來：

  ① 同一期別重跑時 previous 被往前推 → 畫面上的變化憑空消失
  ② 同一期別重跑時 released 被覆蓋成今天 → 「N 天前發布」永遠顯示「今天」
  ③ 三個模組共用一個輪替條件 → CPI 還沒發布卻被當成已經比過

    python tests/test_change_basis.py
"""
import sys
import pathlib
import datetime as dt

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from src.analysis import changes as chg  # noqa: E402
from src import clock  # noqa: E402

ok = True
TODAY = clock.today().isoformat()


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    print(f"{'通過' if cond else '失敗'}  {name}" + (f" — {detail}" if detail else ""))
    ok &= bool(cond)


def mod(vintage: str, released: str | None = None, flags: dict | None = None) -> dict:
    flags = flags or {"a": "dovish"}
    return {"vintage": vintage, "released": released or TODAY,
            "month": vintage, "score": 0.0, "tilt": "neutral",
            "flags": list(flags),
            "flag_titles": {k: f"訊號{k}" for k in flags},
            "flag_leans": dict(flags), "metrics": {}}


def snap(**mods) -> dict:
    return {"at": f"{TODAY}T13:45:00", "modules": mods}


# ---------------------------------------------------------------------------
# ① 輪替條件：期別變了才推 previous
# ---------------------------------------------------------------------------
s1 = chg.roll(None, snap(labor=mod("2026-06")))
check("① 第一次執行沒有 previous",
      "previous" not in s1["modules"]["labor"])

s2 = chg.roll(s1, snap(labor=mod("2026-06")))
check("② 同一期別重跑 → 仍然沒有 previous",
      "previous" not in s2["modules"]["labor"])

s3 = chg.roll(s2, snap(labor=mod("2026-07")))
check("③ 期別變了 → 舊的成為 previous",
      s3["modules"]["labor"]["previous"]["vintage"] == "2026-06",
      s3["modules"]["labor"]["previous"]["vintage"])

# 這一條是重點：發布後第 N 天重跑，基準不能被往前推
s4 = s3
for _ in range(5):
    s4 = chg.roll(s4, snap(labor=mod("2026-07")))
check("④ 連跑 5 次，基準仍停在 6 月（變化不會憑空消失）",
      s4["modules"]["labor"]["previous"]["vintage"] == "2026-06",
      s4["modules"]["labor"]["previous"]["vintage"])
check("⑤ current 仍是最新那一期",
      s4["modules"]["labor"]["current"]["vintage"] == "2026-07")


# ---------------------------------------------------------------------------
# ② released：同一期別重跑不能被蓋成今天
# ---------------------------------------------------------------------------
old_day = (clock.today() - dt.timedelta(days=8)).isoformat()
a = chg.roll(None, snap(labor=mod("2026-07", released=old_day)))
b = chg.roll(a, snap(labor=mod("2026-07")))          # snapshot() 會填今天
check("⑥ 同一期別重跑 → 保留原本的發布日",
      b["modules"]["labor"]["current"]["released"] == old_day,
      b["modules"]["labor"]["current"]["released"])
c = chg.roll(b, snap(labor=mod("2026-08")))
check("⑦ 期別換了 → 發布日跟著換成今天",
      c["modules"]["labor"]["current"]["released"] == TODAY)


# ---------------------------------------------------------------------------
# ③ 三個模組各自輪替
# ---------------------------------------------------------------------------
s = chg.roll(None, snap(labor=mod("2026-06"), inflation=mod("2026-05")))
s = chg.roll(s, snap(labor=mod("2026-07"), inflation=mod("2026-05")))
check("⑧ 只有就業換期 → 只有就業有 previous",
      "previous" in s["modules"]["labor"]
      and "previous" not in s["modules"]["inflation"])

cs = chg.compare(s)
check("⑨ 對照基準只列真的換期的模組", len(cs.bases) == 1, str(cs.bases))
check("⑩ 基準文字寫得出來", chg.basis_text(cs) == "就業 7 月（對照 6 月）",
      chg.basis_text(cs))

s = chg.roll(s, snap(labor=mod("2026-07"), inflation=mod("2026-06")))
cs = chg.compare(s)
check("⑪ CPI 也換期之後兩個模組都列",
      chg.basis_text(cs) == "就業 7 月（對照 6 月）　·　物價 6 月（對照 5 月）",
      chg.basis_text(cs))


# ---------------------------------------------------------------------------
# ④ 距今天數
# ---------------------------------------------------------------------------
s = chg.roll(None, snap(labor=mod("2026-06", released=old_day)))
s = chg.roll(s, snap(labor=mod("2026-07", released=old_day)))
# 手動把 current 的發布日設成 8 天前（模擬發布後第 8 天）
s["modules"]["labor"]["current"]["released"] = old_day
cs = chg.compare(s)
check("⑫ 算得出距今天數", cs.days_since == 8, str(cs.days_since))
# 多個模組時取最近的那一個——那才是「最新消息多久以前」
s["modules"]["inflation"] = {
    "current": mod("2026-07", released=(clock.today() - dt.timedelta(days=2)).isoformat()),
    "previous": mod("2026-06"),
}
cs = chg.compare(s)
check("⑬ 多個模組取最近的那一次", cs.days_since == 2, str(cs.days_since))


# ---------------------------------------------------------------------------
# ⑤ 舊格式要能平滑升級
# ---------------------------------------------------------------------------
# 改版前的狀態檔是一份平面快照。不處理的話，改版後第一次執行會把
# 所有模組都當成「第一次看到」，那一期的變化整個消失。
legacy = {"at": "2026-07-01T13:45:00",
          "labor": {"month": "2026-06", "score": 0.0, "tilt": "neutral",
                    "flags": ["a"], "flag_titles": {"a": "訊號a"},
                    "flag_leans": {"a": "dovish"}, "metrics": {}}}
s = chg.roll(legacy, snap(labor=mod("2026-07")))
check("⑭ 舊格式的快照會被當成 previous",
      "previous" in s["modules"]["labor"],
      str(list(s["modules"]["labor"])))

# 完全沒有狀態檔也不能爆
check("⑮ 沒有狀態檔不會爆", "modules" in chg.roll(None, snap(labor=mod("2026-07"))))
check("⑯ 空的 compare 不會爆",
      chg.compare({}).has_previous is False)


# ---------------------------------------------------------------------------
# ⑥ 情境：任何一個模組換期，它就算換了一期
# ---------------------------------------------------------------------------
def scen(v: str, name: str) -> dict:
    return {"vintage": v, "released": TODAY, "name": name, "grid_name": name,
            "regime": "inflation", "labor": "弱", "inflation": "高"}


s = chg.roll(None, snap(scenario=scen("labor:2026-06", "按兵不動")))
s = chg.roll(s, snap(scenario=scen("labor:2026-07", "轉向降息")))
cs = chg.compare(s)
check("⑰ 情境移動抓得到",
      cs.scenario_moved and cs.scenario_from == "按兵不動"
      and cs.scenario_to == "轉向降息",
      f"{cs.scenario_from} → {cs.scenario_to}")

s = chg.roll(s, snap(scenario=scen("labor:2026-07", "轉向降息")))
cs = chg.compare(s)
check("⑱ 重跑之後那次移動還在（不會隔天就熄）",
      cs.scenario_moved and cs.scenario_from == "按兵不動",
      f"{cs.scenario_from} → {cs.scenario_to}")


# ---------------------------------------------------------------------------
# ⑦ 情境歷史：一期一列，用來回答「這一格待了幾期」
#
# 這段歷史**沒有辦法事後回填**——晚一個月開始累積就永遠少一個月。
# 兩件事錯了會讓它變成沒有用的東西：
#   ① 用執行時間而不是期別去重 → 排程每天跑，一個月會塞三十列一樣的東西，
#      「待了幾期」變成「待了幾天」，答案隨排程頻率改變而不是隨數據改變
#   ② 同一期別重跑時 append 而不是就地更新 → 同上
# ---------------------------------------------------------------------------
def scen_snap(m: str, name: str) -> dict:
    s = snap(labor=mod(m), inflation=mod(m), fomc=mod(m))
    s["modules"]["scenario"] = {
        "vintage": f"labor:{m}|inflation:{m}|fomc:{m}", "released": TODAY,
        "name": name, "grid_name": name, "regime": "inflation",
        "labor": "弱", "inflation": "高"}
    return s


st = None
for m, nm in [("2026-04", "按兵不動"), ("2026-05", "按兵不動"),
              ("2026-06", "降息受阻"), ("2026-07", "停滯性通膨"),
              ("2026-08", "停滯性通膨"), ("2026-09", "停滯性通膨")]:
    for _ in range(3):                       # 每期排程跑三次
        st = chg.roll(st, scen_snap(m, nm))

h = st.get("history") or []
check("⑲ 一期一列（重跑不會多塞）", len(h) == 6, f"{len(h)} 列")
check("⑳ 順序是舊到新", [r["name"] for r in h][:2] == ["按兵不動", "按兵不動"])

tn = chg.tenure(st)
check("㉑ 算得出待了幾期", tn.get("periods") == 3, str(tn))
check("㉒ 講得出上一格是哪一格", tn.get("from") == "降息受阻", str(tn))

# 同一期別重跑時若判定改變（資料修正），要就地更新而不是新增
st2 = chg.roll(st, scen_snap("2026-09", "兩難僵局"))
h2 = st2["history"]
check("㉓ 同期別改判 → 就地更新不新增",
      len(h2) == 6 and h2[-1]["name"] == "兩難僵局", f"{len(h2)} 列")

# 資料不足時不能硬掰
check("㉔ 只有一列時不講期數", chg.tenure({"history": h[:1]}) == {})
check("㉕ 沒有歷史不會爆", chg.tenure(None) == {} and chg.tenure({}) == {})

# 整段歷史都同一格：講得出期數，但講不出「從哪來」
same = chg.tenure({"history": [{"vintage": f"v{i}", "name": "按兵不動"}
                               for i in range(4)]})
check("㉖ 全程同一格 → 有期數、沒有前一格",
      same.get("periods") == 4 and same.get("from") == "", str(same))

# 上限：只是避免檔案無限長
big = {"history": [{"vintage": f"v{i}", "name": "x"} for i in range(600)]}
rolled = chg._roll_history(big["history"], None, None)
check("㉗ 歷史有長度上限", len(rolled) == chg.HISTORY_MAX, str(len(rolled)))

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
