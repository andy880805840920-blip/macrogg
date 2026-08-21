# 快照後備：FRED 這一次抓不到的序列，退回本機 SQLite 上次抓到的值
# （不打網路；store 用假物件）
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import run as runner                              # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過 " if cond else "失敗 "), name, ("— " + str(detail)[:90]) if detail else "")
    ok = ok and bool(cond)


class _FakeStore:
    def __init__(self, data):
        self._d = data

    def series(self, sid):
        return self._d.get(sid, [])


_SNAP = [{"date": "2026-06-01", "value": 101.0},
         {"date": "2026-07-01", "value": 101.5}]

# ① 抓失敗但本機有快照 → 沿用，failed 訊息補上沿用標記
series = {"CUSR0000SASLE": [], "CUSR0000SAH1": [{"date": "2026-07-01", "value": 99.0}]}
failed = [("CUSR0000SASLE", "回傳空資料")]
restored = runner._restore_from_snapshot(
    series, _FakeStore({"CUSR0000SASLE": _SNAP}), failed)
check("① 缺的序列從快照補回", restored == ["CUSR0000SASLE"]
      and series["CUSR0000SASLE"] == _SNAP)
check("①b 失敗清單標明是沿用", "沿用" in failed[0][1], failed[0])
check("①c 有抓到的序列不動", series["CUSR0000SAH1"][0]["value"] == 99.0)

# ② 本機也沒有（第一次執行）→ 不硬補，維持空的
series2 = {"X": []}
failed2 = [("X", "回傳空資料")]
r2 = runner._restore_from_snapshot(series2, _FakeStore({}), failed2)
check("② 快照也沒有就維持空的", r2 == [] and series2["X"] == [])
check("②b 失敗訊息不加沿用標記", "沿用" not in failed2[0][1])

# ③ store 讀取本身出錯也不能讓整個流程倒
class _Broken:
    def series(self, sid):
        raise RuntimeError("db 壞了")


series3 = {"X": []}
r3 = runner._restore_from_snapshot(series3, _Broken(), [("X", "e")])
check("③ 快照層出錯不拖垮流程", r3 == [] and series3["X"] == [])

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
