"""
「本次更新」的 72 小時視窗。

這一句只在**新資料剛進來**的時候出現。判斷完全在 run.py 的
_fresh_releases() 裡做，brief 只負責照著寫——所以要釘住的是這裡。

四件事一定要對：

  ① 期別第一次出現 → 記下時間，但**第一次跑不算新**
     （沒有舊紀錄就沒有「上一期」，每次換機器都宣稱「本次更新」是最糟的）
  ② 同一期別重跑 → 沿用第一次看到的時間，不是每跑一次就重新計時
     （否則 72 小時永遠不會到期，這句話會一直掛著）
  ③ 超過 72 小時 → 不再顯示
  ④ 狀態檔壞掉／寫不進去 → 主流程不受影響，最多是這句不顯示

    python tests/test_release_window.py
"""
import sys
import json
import pathlib
import datetime as dt

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
import run                                          # noqa: E402
from src import clock                               # noqa: E402

ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    print(f"{'通過' if cond else '失敗'}  {name}" + (f" — {detail}" if detail else ""))
    ok &= bool(cond)


CTXS = {"labor": {"data_month": "2026-07"},
        "inflation": {"data_month": "2026-07"}}


def run_with(state, at: dt.datetime, ctxs=None):
    """把狀態檔換成 `state`、時鐘停在 `at`，跑一次 _fresh_releases()。"""
    tmp = ROOT / "state" / "_test_releases.json"
    orig_file, orig_now = run.RELEASES_FILE, clock.now
    run.RELEASES_FILE = tmp
    clock.now = lambda: at
    try:
        tmp.parent.mkdir(parents=True, exist_ok=True)
        if state is None:
            tmp.unlink(missing_ok=True)
        else:
            tmp.write_text(json.dumps(state), encoding="utf-8")
        out = run._fresh_releases(ctxs if ctxs is not None else CTXS)
        after = json.loads(tmp.read_text(encoding="utf-8"))
        return out, after
    finally:
        run.RELEASES_FILE, clock.now = orig_file, orig_now
        tmp.unlink(missing_ok=True)


T0 = dt.datetime(2026, 8, 12, 9, 0, 0)


# ① 第一次跑：記下來，但不宣稱是新的
out, after = run_with(None, T0)
check("① 第一次跑不宣稱「本次更新」", out == {}, str(out))
check("② 但期別與時間有記下來",
      after["inflation"]["month"] == "2026-07"
      and after["inflation"]["first_seen"], str(after))

# ② 有舊紀錄、期別換新 → 這一次算新的
OLD_JUNE = {"labor": {"month": "2026-06", "first_seen": "2026-07-10T08:30:00"},
            "inflation": {"month": "2026-06", "first_seen": "2026-07-15T08:30:00"}}
out, after = run_with(OLD_JUNE, T0)
check("③ 期別推進 → 兩個模組都算新",
      out == {"labor": "2026-07", "inflation": "2026-07"}, str(out))
check("④ first_seen 換成這一次的時間",
      after["inflation"]["first_seen"].startswith("2026-08-12"),
      after["inflation"]["first_seen"])

# ③ 同一期別重跑：沿用第一次看到的時間，不重新計時
SEEN_1H = {"labor": {"month": "2026-07", "first_seen": "2026-08-12T08:00:00"},
           "inflation": {"month": "2026-07", "first_seen": "2026-08-12T08:00:00"}}
out, after = run_with(SEEN_1H, T0)
check("⑤ 一小時前看到的還算新", "inflation" in out, str(out))
check("⑥ 重跑不重新計時（否則永遠不過期）",
      after["inflation"]["first_seen"] == "2026-08-12T08:00:00",
      after["inflation"]["first_seen"])

# ④ 過了 72 小時就熄掉
SEEN_73H = {"labor": {"month": "2026-07", "first_seen": "2026-08-09T07:00:00"},
            "inflation": {"month": "2026-07", "first_seen": "2026-08-09T07:00:00"}}
out, _ = run_with(SEEN_73H, T0)
check("⑦ 73 小時前的不再是「本次更新」", out == {}, str(out))

SEEN_71H = {"labor": {"month": "2026-07", "first_seen": "2026-08-09T10:00:00"},
            "inflation": {"month": "2026-07", "first_seen": "2026-08-09T10:00:00"}}
out, _ = run_with(SEEN_71H, T0)
check("⑧ 71 小時前的還算數（門檻兩邊都要釘）",
      out == {"labor": "2026-07", "inflation": "2026-07"}, str(out))

# 兩個模組各自計時：CPI 剛出、就業是上週的
MIXED = {"labor": {"month": "2026-07", "first_seen": "2026-08-07T08:30:00"},
         "inflation": {"month": "2026-06", "first_seen": "2026-07-15T08:30:00"}}
out, _ = run_with(MIXED, T0)
check("⑨ 各模組各自計時（就業過期、物價剛出）",
      out == {"inflation": "2026-07"}, str(out))

# ⑤ 壞掉的狀態檔不能讓整個流程掛掉
out, _ = run_with({"inflation": {"month": "2026-07", "first_seen": "壞掉的時間"}},
                  T0)
check("⑩ first_seen 壞掉不會爆，只是不算新", out == {}, str(out))
out, _ = run_with({"inflation": "不是字典"}, T0)
check("⑪ 整條紀錄型別錯了也不會爆", isinstance(out, dict), str(out))
check("⑫ 沒有 data_month 的模組直接跳過",
      run_with(OLD_JUNE, T0, ctxs={"labor": {}, "inflation": {}})[0] == {},
      "")

# ⑥ 狀態檔遺失之後不可以謊報
#
# 使用者抓到的：就業報告 8/7 就發布了，8/13 的畫面卻還寫「本次更新：就業 7 月」。
# 原因是狀態檔重建過：
#   第 1 次跑　沒有舊紀錄 → 寫 first_seen=現在（那次靠 old.get(key) 擋掉）
#   第 2 次跑　rec.month 已經等於 month → 沿用那個 first_seen
#             → 它在 72 小時內 → 兩個模組同時被標成「本次更新」
# 擋掉的方式是記 `advanced`：這個 first_seen 是不是真的看到期別往前推。
out, after = run_with(None, T0)
check("⑭ 重建後的第一次：記下來但標 advanced=False",
      out == {} and after["labor"]["advanced"] is False, str(after["labor"]))
out2, after2 = run_with(after, dt.datetime(2026, 8, 12, 10, 0, 0))
check("⑮ 重建後的第二次仍然不算新（先前這裡會謊報）",
      out2 == {}, str(out2))
check("⑯ 而且 advanced 沿用下去，不會自己變成 True",
      after2["labor"]["advanced"] is False, str(after2["labor"]))
out3, after3 = run_with(after2, dt.datetime(2026, 9, 5, 9, 0, 0),
                        ctxs={"labor": {"data_month": "2026-08"},
                              "inflation": {"data_month": "2026-08"}})
check("⑰ 真的換期別時才標 advanced=True，並且算新",
      out3 == {"labor": "2026-08", "inflation": "2026-08"}
      and after3["labor"]["advanced"] is True, str(out3))

# 舊格式（沒有 advanced 欄位）要沿用舊行為，不能因為升級就整批消失
_legacy = {"labor": {"month": "2026-07", "first_seen": "2026-08-12T08:00:00"},
           "inflation": {"month": "2026-07", "first_seen": "2026-08-12T08:00:00"}}
check("⑱ 舊格式的紀錄當成 advanced 處理（升級不會少講一次）",
      run_with(_legacy, T0)[0] == {"labor": "2026-07", "inflation": "2026-07"})

check("⑬ 視窗是 72 小時", run.FRESH_HOURS == 72)

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
