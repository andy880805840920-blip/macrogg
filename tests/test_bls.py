"""
BLS 快速通道的測試。全程不碰網路。

為什麼需要這個檔案
------------------
這一層在做一件本質上危險的事：**把另一個資料來源的數字，接到 FRED 的
序列尾巴上。** 三種壞法都是安靜的：

  ① **對應表寫錯。** FRED 的 ID 跟 BLS 的 ID 長得完全不像
     （PAYEMS ↔ CES0000000001）。對錯了不會報錯，只會拿到一條看起來
     很正常、其實是別的東西的序列，然後接到畫面上。
  ② **部分更新。** PAYEMS 推進到 7 月、行業別還停在 6 月 → 行業歸因
     拿新的總數配舊的拆解，貢獻度全錯而畫面完全正常。
  ③ **年度平均混進月序列。** BLS 的 M13 是年度平均，當成月份接進去
     會多出一個憑空的觀測。

所以這裡釘住的全是「接錯了會怎樣」，而不是「接對了長什麼樣」。

    python tests/test_bls.py
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from src import bls                                # noqa: E402

ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    print(f"{'通過' if cond else '失敗'}  {name}" + (f" — {detail}" if detail else ""))
    ok &= bool(cond)


def ser(*pairs):
    return [{"date": d, "value": v} for d, v in pairs]


class FakeClient:
    """回傳預先寫好的 BLS 資料，不碰網路。"""

    def __init__(self, data):
        self.data, self.failed = data, []

    def fetch(self, ids, y0, y1):
        return {k: v for k, v in self.data.items() if k in ids}


import datetime as dt                              # noqa: E402
TODAY = dt.date(2026, 8, 12)


# ---------------------------------------------------------------------------
# ① 期別轉換
# ---------------------------------------------------------------------------
check("① 月份轉得對", bls._to_date("2026", "M07") == "2026-07-01")
check("② M13 是年度平均 → 丟掉（不能當成月份）",
      bls._to_date("2026", "M13") == "")
check("③ 季轉成季初", bls._to_date("2026", "Q02") == "2026-04-01")
check("④ 壞資料不會爆",
      bls._to_date("", "M07") == "" and bls._to_date("2026", "") == ""
      and bls._to_date("2026", "A01") == "")


# ---------------------------------------------------------------------------
# ② 對應表：對錯了要被擋下來
# ---------------------------------------------------------------------------
check("⑤ 有對應表的走對應", bls._bls_id("PAYEMS") == "CES0000000001")
check("⑥ 本來就是 BLS ID 的直接沿用",
      bls._bls_id("CUSR0000SEHA") == "CUSR0000SEHA"
      and bls._bls_id("CES0500000003") == "CES0500000003")
check("⑦ 不涵蓋的回空字串（PCE 是 BEA、油價是 EIA）",
      bls._bls_id("PCEPILFE") == "" and bls._bls_id("DCOILWTICO") == "")
check("⑧ 每個對應都有唯一的 BLS ID（沒有兩條指到同一個）",
      len(set(bls.MAP.values())) == len(bls.MAP))

# 重疊對帳：這是唯一擋得住「對應錯」的東西
FRED = ser(("2026-04-01", 100.0), ("2026-05-01", 101.0), ("2026-06-01", 102.0))
same = ser(("2026-04-01", 100.0), ("2026-05-01", 101.0), ("2026-06-01", 102.0),
           ("2026-07-01", 103.0))
diff = ser(("2026-04-01", 200.0), ("2026-05-01", 201.0), ("2026-06-01", 202.0),
           ("2026-07-01", 203.0))
check("⑨ 重疊期一致 → 通過", bls._agrees(FRED, same)[0])
check("⑩ 重疊期對不上 → 拒絕（這就是對應錯的樣子）",
      not bls._agrees(FRED, diff)[0], bls._agrees(FRED, diff)[1])
check("⑪ 小數位不同不算對不上（FRED 三位、BLS 一位）",
      bls._agrees(FRED, ser(("2026-06-01", 102.05)))[0])
check("⑫ 差 1% 就算對不上（容差不能鬆到讓別條矇混）",
      not bls._agrees(FRED, ser(("2026-06-01", 103.02)))[0])
check("⑬ 沒有重疊期 → 拒絕（無從查證就不接）",
      not bls._agrees(FRED, ser(("2027-01-01", 1.0)))[0])


# ---------------------------------------------------------------------------
# ③ merge：只補尾端、標速報值
# ---------------------------------------------------------------------------
def cpi_group(last="2026-06-01", val=102.0):
    return {k: ser(("2026-05-01", 101.0), (last, val)) for k in bls.GROUPS["cpi"]}


s = cpi_group()
newer = {bls._bls_id(k): ser(("2026-05-01", 101.0), ("2026-06-01", 102.0),
                             ("2026-07-01", 103.0))
         for k in bls.GROUPS["cpi"]}
r = bls.merge(s, FakeClient(newer), today=TODAY)
check("⑭ 補上 FRED 還沒有的那一期",
      len(r["added"]) == len(bls.GROUPS["cpi"]), str(len(r["added"])))
check("⑮ 補的是尾端，歷史不動",
      [x["date"] for x in s["CPIAUCSL"]]
      == ["2026-05-01", "2026-06-01", "2026-07-01"])
check("⑯ 補進來的點標成速報值",
      s["CPIAUCSL"][-1].get("provisional") is True
      and "provisional" not in s["CPIAUCSL"][0])

# 已經一樣新 → 什麼都不做
s2 = cpi_group()
r2 = bls.merge(s2, FakeClient({bls._bls_id(k): ser(("2026-06-01", 102.0))
                               for k in bls.GROUPS["cpi"]}), today=TODAY)
check("⑰ BLS 沒有比較新 → 不動", r2["added"] == {} and len(s2["CPIAUCSL"]) == 2)

# 對不上 → 整條拒絕，而且不寫進去
s3 = cpi_group()
bad = {bls._bls_id(k): ser(("2026-06-01", 999.0), ("2026-07-01", 1000.0))
       for k in bls.GROUPS["cpi"]}
r3 = bls.merge(s3, FakeClient(bad), today=TODAY)
check("⑱ 對帳失敗 → 一條都不接",
      r3["added"] == {} and len(r3["rejected"]) == len(bls.GROUPS["cpi"]))
check("⑲ 而且原本的序列一個字都沒被動到", len(s3["CPIAUCSL"]) == 2)


# ---------------------------------------------------------------------------
# ④ 一致性：部分更新比不更新更危險
# ---------------------------------------------------------------------------
jobs = {k: ser(("2026-05-01", 101.0), ("2026-06-01", 102.0))
        for k in bls.GROUPS["jobs"]}
# 只有 PAYEMS 拿得到新資料，行業別拿不到
partial = {bls._bls_id("PAYEMS"): ser(("2026-06-01", 102.0),
                                      ("2026-07-01", 103.0))}
r4 = bls.merge(jobs, FakeClient(partial), today=TODAY)
check("⑳ 同組只有一部分拿得到 → 整組不採用",
      r4["added"] == {} and "PAYEMS" in r4["dropped"], str(r4["added"]))
check("㉑ PAYEMS 沒有被單獨推進（不然行業歸因會對錯期別）",
      len(jobs["PAYEMS"]) == 2)

# 全組都拿得到 → 才一起推進
jobs2 = {k: ser(("2026-05-01", 101.0), ("2026-06-01", 102.0))
         for k in bls.GROUPS["jobs"]}
full = {bls._bls_id(k): ser(("2026-06-01", 102.0), ("2026-07-01", 103.0))
        for k in bls.GROUPS["jobs"]}
r5 = bls.merge(jobs2, FakeClient(full), today=TODAY)
check("㉒ 全組都拿得到 → 一起推進",
      len(r5["added"]) == len(bls.GROUPS["jobs"]))
check("㉓ 推進後全組期別一致",
      len({v[-1]["date"] for v in jobs2.values()}) == 1)

# 一組推進不影響另一組
mixed = {**{k: ser(("2026-06-01", 102.0)) for k in bls.GROUPS["cpi"]},
         **{k: ser(("2026-06-01", 102.0)) for k in bls.GROUPS["jobs"]}}
only_cpi = {bls._bls_id(k): ser(("2026-06-01", 102.0), ("2026-07-01", 103.0))
            for k in bls.GROUPS["cpi"]}
r6 = bls.merge(mixed, FakeClient(only_cpi), today=TODAY)
check("㉔ CPI 那組推進、就業那組不動（兩份新聞稿互不影響）",
      len(r6["added"]) == len(bls.GROUPS["cpi"])
      and mixed["PAYEMS"][-1]["date"] == "2026-06-01")


# ---------------------------------------------------------------------------
# ⑤ 失敗路徑：任何一步壞掉都要安靜地退回 FRED
# ---------------------------------------------------------------------------
class Boom:
    failed = []

    def fetch(self, ids, y0, y1):
        raise RuntimeError("connection reset")


s7 = cpi_group()
try:
    bls.merge(s7, FakeClient({}), today=TODAY)
    hit = True
except Exception:                                  # noqa: BLE001
    hit = False
check("㉕ BLS 回空 → 不動、不爆", hit and len(s7["CPIAUCSL"]) == 2)
check("㉖ 沒有涵蓋的序列 → 直接跳過",
      bls.merge({"PCEPILFE": ser(("2026-06-01", 1.0))},
                FakeClient({}), today=TODAY)["checked"] == 0)
check("㉗ 空的 series 不會爆", bls.merge({}, FakeClient({}), today=TODAY)
      ["added"] == {})

# 沒金鑰走 v1、有金鑰走 v2
check("㉘ 沒金鑰走 v1（免註冊）",
      bls.BlsClient(key="").url == bls.API_V1)
check("㉙ 有金鑰走 v2（額度較寬）",
      bls.BlsClient(key="abc").url == bls.API_V2)
check("㉚ 批次大小跟著版本走",
      bls.BlsClient(key="").batch == bls.BATCH_V1
      and bls.BlsClient(key="abc").batch == bls.BATCH_V2)


# ---------------------------------------------------------------------------
# ⑥ 速報值要在畫面上看得出來
#
# 這一點的來源跟其他期不同，而且下一次執行會被 FRED 的正式值取代。
# 不標的話讀者無從分辨——那就變成「安靜地混用兩個資料來源」。
# ---------------------------------------------------------------------------
from src.analysis import brief                      # noqa: E402


class _S:
    regime, lean = "inflation", "hawkish"
    labor_state, infl_state = "弱", "高"
    triggers = []


AX = {"unrate": 4.1, "u_lo": 4.0, "u_hi": 4.3, "nfp_3m": 20.0,
      "sahm": 0.25, "u3_rising": True, "sahm_triggered": False}


def brief_text(prov):
    return brief.compose({
        "scenario": {"scenario": _S()},
        "labor": {"axis": AX, "tilt": {}, "data_month": "2026-07",
                  "provisional": prov, "flags": []}})["text"]


check("㉛ 速報值在總述裡標出來", "7 月（速報）" in brief_text(True))
check("㉜ 正式值不標", "（速報）" not in brief_text(False)
      and "7 月失業率" in brief_text(False))


# ---------------------------------------------------------------------------
# ⑦ 年增率的口徑：季調 vs 未季調
#
# 實際被使用者抓到的錯：畫面印 7 月 CPI 年增 3.5%／核心 2.8%，
# 而 BLS 新聞稿寫的是 3.4%／2.5%。六月同樣高 0.2 個百分點——
# 系統性偏高，不是雜訊。
#
# 原因是年增率拿**季調**指數去算，而 BLS 公布的年增率是用**未季調**算的。
# 分工應該是：月增率／年化用季調（月與月之間要剔除季節性才可比），
# 年增率用未季調（相隔十二個月，季節性自己抵消，而且不會被回溯修正）。
# ---------------------------------------------------------------------------
from src.analysis.inflation import _yoy_nsa           # noqa: E402


def idx(*vals):
    return [{"date": f"2025-{i + 1:02d}-01" if i < 12 else f"2026-{i - 11:02d}-01",
             "value": v} for i, v in enumerate(vals)]


NSA = idx(*([100.0] * 12 + [103.4]))                  # 年增 3.4%
SA = idx(*([100.0] * 12 + [103.5]))                   # 年增 3.5%

check("㉝ 有未季調就用未季調（跟 BLS 口徑一致）",
      abs(_yoy_nsa(NSA, SA) - 3.4) < 1e-9, str(_yoy_nsa(NSA, SA)))
check("㉞ 沒有未季調才退回季調（少 0.1 好過整個消失）",
      abs(_yoy_nsa([], SA) - 3.5) < 1e-9)
check("㉟ 兩個都沒有 → None，不硬掰",
      _yoy_nsa([], []) is None)
check("㊱ 未季調資料不足時也退回季調",
      abs(_yoy_nsa(idx(100.0, 101.0), SA) - 3.5) < 1e-9)

# 未季調兩條必須跟其他 CPI 序列同組推進，否則會出現
# 「七月的月增率配六月的年增率」
check("㊲ 未季調在 CPI 那一組裡",
      "CPIAUCNS" in bls.GROUPS["cpi"] and "CPILFENS" in bls.GROUPS["cpi"])
# ⚠️ 用的必須是 **FRED 真的有的代號**。先前寫成 CUUR0000SA0L1E——那是
# BLS 的代號，FRED 上沒有，於是抓不到、靜靜退回季調，修正等於沒生效。
check("㊳ 對應到 BLS 的未季調代號",
      bls._bls_id("CPIAUCNS") == "CUUR0000SA0"
      and bls._bls_id("CPILFENS") == "CUUR0000SA0L1E")

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
