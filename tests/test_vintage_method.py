"""
期別、計算方法版本、以及核心 PCE 的即時推估。

三件事都是使用者從畫面上抓到的，共同點是「數字看起來完全正常」：

  ① **PCE 被標成 CPI 的月份。** 整體情勢寫「7 月核心 PCE 3.3%」，
     但核心 PCE 的 7 月要 8 月底才由 BEA 公布。brief 只收一個
     data_month（＝CPI 的期別）就套給整段。

  ② **上一期是舊程式算的。** 變化卡寫「核心 CPI 年增 2.81 → 2.48」，
     而同一頁的走勢列（每次重算）寫 6 月是 2.6。那 −0.33 大半是
     v73 修好除數這件事本身，不是物價變了。

  ③ **九宮格活在一個月前。** CPI 月中發、PCE 月底發，中間兩週九宮格
     用的是上個月的 PCE。

    python tests/test_vintage_method.py
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from src.analysis import brief, changes as chg          # noqa: E402
from src.analysis import inflation as ia                # noqa: E402

ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    print(f"{'通過' if cond else '失敗'}  {name}" + (f" — {detail}" if detail else ""))
    ok &= bool(cond)


def rows(vals, y=2025, m=1):
    out = []
    for v in vals:
        out.append({"date": f"{y:04d}-{m:02d}-01", "value": float(v)})
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


# ---------------------------------------------------------------------------
# ① 誰的數字就標誰的期別
# ---------------------------------------------------------------------------
class S:
    pce_core_yoy, pce_core_3m, supercore_streak = 3.3, 2.9, 0


t_split = brief._inflation(S(), {}, "高", month="7 月", pce_month="6 月")
check("① PCE 用自己的期別，不是 CPI 的", t_split.startswith("6 月核心 PCE"),
      t_split[:24])
check("② 沒給 pce_month 時退回舊行為（不會爆）",
      brief._inflation(S(), {}, "高", month="7 月").startswith("7 月核心 PCE"))
check("③ 兩邊都沒有期別時不硬編一個",
      not brief._inflation(S(), {}, "高").startswith("月"))

# fixture 也要反映這個時差，否則離線預覽永遠測不到這個 bug
from src import fixtures_inflation                      # noqa: E402
_fx = fixtures_inflation.build()
check("④ 離線素材的 PCE 比 CPI 少一個月（跟正式環境一樣）",
      _fx["PCEPILFE"][-1]["date"] < _fx["CPILFESL"][-1]["date"],
      f'PCE {_fx["PCEPILFE"][-1]["date"]}、CPI {_fx["CPILFESL"][-1]["date"]}')


# ---------------------------------------------------------------------------
# ② 計算方法換版時，上一期要重算
# ---------------------------------------------------------------------------
def snap(method, cur, prev_stored, prev_recomputed=None):
    return {"modules": {"inflation": {
        "vintage": "2026-07", "released": "2026-08-12", "month": "2026-07",
        "tilt": "hawkish", "flags": [], "flag_titles": {}, "flag_leans": {},
        "method": method,
        "metrics": {"core_cpi_yoy": {
            "label": "核心 CPI 年增", "value": cur, "unit": "%",
            "threshold": 0.05, "up_is": "hawkish"}},
        "metrics_prev": ({"core_cpi_yoy": {"value": prev_recomputed}}
                         if prev_recomputed is not None else {}),
    }}}


def moves(prev_state, cur_state):
    st = {"modules": {"inflation": {
        "current": cur_state["modules"]["inflation"],
        "previous": prev_state["modules"]["inflation"]}}}
    cs = chg.compare(st)
    return cs


# 版本相同 → 用快照存的上期（＝「你上次看到的」，資料修正看得見）
cs = moves(snap(2, 2.81, None), snap(2, 2.48, None))
m = [x for x in cs.metric_moves if x["key"] == "core_cpi_yoy"]
check("⑤ 版本相同 → 基準是快照裡的舊值",
      bool(m) and abs(m[0]["from"] - 2.81) < 1e-9, str(m[:1]))
check("⑥ 而且不標成「換過口徑」", not cs.method_changed)

# 版本不同 → 改用現行程式重算的上期，假變動消失
cs2 = moves(snap(1, 2.81, None), snap(2, 2.48, None, prev_recomputed=2.60))
m2 = [x for x in cs2.metric_moves if x["key"] == "core_cpi_yoy"]
check("⑦ 版本不同 → 基準換成重算的 2.60",
      bool(m2) and abs(m2[0]["from"] - 2.60) < 1e-9, str(m2[:1]))
check("⑧ 變動幅度從 −0.33 縮回真實的 −0.12",
      bool(m2) and abs(m2[0]["delta"] + 0.12) < 1e-9,
      f'{m2[0]["delta"]:+.4f}' if m2 else "")
check("⑨ 而且標記出來，畫面可以講「基準跟平常不一樣」", cs2.method_changed)

# 版本不同又沒有重算值 → 寧可不比
cs3 = moves(snap(1, 2.81, None), snap(2, 2.48, None))
check("⑩ 沒有重算值時整組不比，不報假變動",
      not [x for x in cs3.metric_moves if x["key"] == "core_cpi_yoy"]
      and cs3.method_changed)

check("⑪ METHOD_VERSION 有往前跳過（改過算法就要 +1）",
      chg.METHOD_VERSION >= 2, str(chg.METHOD_VERSION))


# ---------------------------------------------------------------------------
# ③ 核心 PCE 的即時推估
# ---------------------------------------------------------------------------
# 造一組 CPI 固定比 PCE 高 0.3 個百分點的資料，PCE 少一個月。
_pce = rows([100 * (1.02 ** (i / 12)) for i in range(30)])
_cpi = rows([100 * (1.023 ** (i / 12)) for i in range(30)])

nc = ia.nowcast_core_pce(_pce[:-1], _cpi)
check("⑫ PCE 落後時會推估", nc["estimated"] is True, str(nc))
check("⑬ 推估值把 CPI 換算成 PCE 口徑（扣掉平均差距）",
      nc["value"] is not None and abs(nc["value"] - 2.0) < 0.15,
      f'推估 {nc["value"]:.3f}%、差距 {nc["gap"]:.3f}')
check("⑭ 差距是算出來的，不是寫死 0.3",
      nc["gap"] is not None and 0.1 < nc["gap"] < 0.5, f'{nc["gap"]:.3f}')
check("⑮ 標出被推估的是哪一個月", nc["asof"] == _cpi[-1]["date"], nc["asof"])

nc2 = ia.nowcast_core_pce(_pce, _cpi[:len(_pce)])
check("⑯ PCE 跟上了就不推估，用實際值", nc2["estimated"] is False, str(nc2))

check("⑰ CPI 比 PCE 舊 → 不推估",
      ia.nowcast_core_pce(_pce, _cpi[:-5])["estimated"] is False)
check("⑱ 重疊樣本太少 → 不推估（寧可用舊的真實數字）",
      ia.nowcast_core_pce(_pce[:14], _cpi[:16])["estimated"] is False)
check("⑲ 缺資料不會爆",
      ia.nowcast_core_pce([], _cpi)["value"] is None
      and ia.nowcast_core_pce(_pce, [])["estimated"] is False)

# 這條是整段的重點：**不可以**把 CPI 直接當成 PCE 送進九宮格
_raw_cpi_yoy = 2.3
check("⑳ 推估值明顯低於直接代入 CPI（否則門檻等於被無故收緊）",
      nc["value"] < _raw_cpi_yoy - 0.1,
      f'推估 {nc["value"]:.3f}% vs 直接代入 {_raw_cpi_yoy}%')

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
