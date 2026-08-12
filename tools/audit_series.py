"""
序列使用率稽核：哪些 FRED 序列抓了卻沒有任何地方讀。

為什麼要有這個
--------------
設定檔加一條序列很容易，把它接上分析卻是另一回事。時間久了就會累積出
「抓得到、但沒有任何一行程式讀它」的序列——每一條都是一次 API 呼叫、
一個可能失敗並出現在「抓取失敗」清單裡的東西，卻對頁面沒有任何貢獻。
靜態 grep 判不準（產業別、紅綠燈那幾組是照設定檔迭代的，程式裡不會
出現字面上的 series id），所以這裡改成**執行期**觀測：把 series 字典
換成一個會記錄讀取的子類，跑一次離線建置，看誰沒被碰過。

    python tools/audit_series.py

沒被讀到不一定要刪。多半是「待辦」——資料先抓著、分析還沒寫。
config 裡用 note 標出來即可；真的不打算做就設 enabled: false。
"""
from __future__ import annotations

import sys
import pathlib
import logging

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402


class Tracked(dict):
    """記錄哪些 key 被讀過的 dict。"""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.read: set[str] = set()

    def get(self, k, d=None):
        self.read.add(k)
        return super().get(k, d)

    def __getitem__(self, k):
        self.read.add(k)
        return super().__getitem__(k)

    def __contains__(self, k):
        self.read.add(k)
        return super().__contains__(k)


def main() -> int:
    logging.disable(logging.CRITICAL)
    import run as R
    from src import build, fixtures, fixtures_inflation, fixtures_rates

    def cfg(n):
        return yaml.safe_load((ROOT / "config" / n).read_text())

    total_unused = 0
    consensus = cfg("consensus.yaml")

    # 勞動
    c = cfg("indicators.yaml")
    ids, labels, inv = R.series_ids(c, R.LABOR_GROUPS)
    s_lab = Tracked(fixtures.build())
    build.build_labor_context(c, s_lab, {}, labels, inv, [], True,
                              consensus=consensus)
    groups = [("勞動", set(ids), s_lab.read)]

    # 通膨（薪資序列是從勞動那邊傳過去的，也要用會記錄的字典）
    c = cfg("inflation.yaml")
    ids, labels, inv = R.series_ids(c, R.INFL_GROUPS)
    s_inf = Tracked(fixtures_inflation.build())
    build.build_inflation_context(c, s_inf, [], True, labor_series=s_lab,
                                  consensus=consensus)
    groups.append(("通膨", set(ids), s_inf.read))

    # 長端
    c = cfg("rates.yaml")
    ids, labels, inv = R.series_ids(c, R.RATES_GROUPS)
    s_rt = Tracked(fixtures_rates.build())
    # 匯率序列只在「有非美元發債要換算」時才會被讀到，而 config 的
    # hyperscalers 本身不帶 offerings——不先塞進去的話，那幾條匯率序列
    # 會被誤報成「抓了沒人讀」。這跟先前 DFEDTARL／DFEDTARU 是同一類的
    # 假警報：稽核工具沒走到那條路徑，不代表程式沒讀。
    _hs = c.setdefault("hyperscalers", {})
    _hs.setdefault("offerings", fixtures_rates.offerings())
    build.build_rates_context(c, s_rt, [], True)
    groups.append(("長端", set(ids), s_rt.read))

    # 聯準會文本模組不自己抓序列，但它會讀長端那組的兩條：
    # DGS2（算「市場定價 vs 聯準會」）與 DFEDTARL／DFEDTARU（政策利率區間）。
    # 不跑它的話那三條會被誤報成「抓了沒人讀」。
    cf = cfg("fomc.yaml")
    stmts, upcoming, _ = R.gather_fomc(True, cf.get("fetch") or {})
    build.build_fomc_context(stmts, cf.get("policy_rate") or {}, [], True,
                             upcoming=upcoming, rates_series=s_rt)

    # 勞動那組要在通膨跑完之後才結算：ECI 是在通膨模組裡被讀的。
    # 長端那組同理，要等聯準會文本跑完。
    groups[0] = ("勞動", groups[0][1], s_lab.read)
    groups[2] = ("長端", groups[2][1], s_rt.read)

    for name, ids, read in groups:
        unused = sorted(ids - read)
        total_unused += len(unused)
        print(f"\n== {name}：抓 {len(ids)} 條，沒有讀到 {len(unused)} 條")
        for u in unused:
            print("   ", u)

    print()
    print("序列稽核：全部都有用到" if not total_unused
          else f"序列稽核：{total_unused} 條沒有被讀取")
    return 0


if __name__ == "__main__":
    sys.exit(main())
