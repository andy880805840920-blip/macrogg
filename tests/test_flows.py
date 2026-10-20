"""市場籌碼：每口 DV01 近似、期貨矩陣零和、空方結構標題、交易商庫存判讀。不連網。"""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from src.analysis import flows as F   # noqa: E402

ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    print(f"{'通過' if cond else '失敗'}  {name}" + (f" — {detail}" if detail else ""))
    ok &= bool(cond)


# ① 每口 DV01：期限越長越大、量級合理（美元）
dv = {c: F.contract_dv01(0.045, m, n) for c, (_, _, m, n) in F.CONTRACTS.items()}
order = [dv[c] for c in ("044601", "043602", "043607", "020601", "020604")]
check("① 5Y→Ultra Bond 的每口 DV01 遞增", order == sorted(order), str({F.CONTRACTS[c][0]: round(v) for c, v in dv.items()}))
check("① 10Y 每口 DV01 落在 $45–90", 45 < dv["043602"] < 90, f'{dv["043602"]:.1f}')

# ② 期貨矩陣：各參與者淨口數相加為零 → 每欄 DV01 合計為零；空方比重升高 → 標題說轉向交易商
ser = {k: [{"date": "2025-01-01", "value": 4.5}] for k in ("DGS2", "DGS5", "DGS7", "DGS10", "DGS20", "DGS30")}
def wk(d, am, lev, dlr):
    return [{"date": d, "code": c, "am": am, "lev": lev, "dlr": dlr, "oth": -(am + lev + dlr) - 10, "nr": 10, "oi": 1}
            for c in F.CONTRACTS]
import datetime as dt   # noqa: E402
tff = []
d0 = dt.date(2025, 9, 2)
for i in range(60):
    d = (d0 + dt.timedelta(days=7 * i)).isoformat()
    tff += wk(d, 1_000_000 + i * 2000, -900_000 + i * 2500, -100_000 - i * 3000)
fv = F.futures_view(tff, ser)
cols = [sum(r["cells"][j]["v"] for r in fv["matrix"]) for j in range(7)]
check("② 每一欄加總為零（期貨一多一空）", all(abs(x) < 1e-6 for x in cols), str([round(x, 6) for x in cols]))
check("② 交易商佔淨空比重上升 → 標題「空方由槓桿基金轉向交易商」", fv["head"].startswith("空方由槓桿基金轉向交易商"), fv["head"])
check("② 圖的口徑：資產管理淨多、槓桿基金與交易商淨空都以正值呈現",
      fv["chart"]["am"][-1]["value"] > 0 and fv["chart"]["lev"][-1]["value"] > 0 and fv["chart"]["dlr"][-1]["value"] > 0)

# ③ 交易商庫存：一年內 coupon 增加且拍賣承接比例升高 → 被動吸收；承接沒升 → 主動持有；減少 → 去化
def pd_rows(start, end):
    out = {}
    for k in F.PD_BUCKETS:
        pass
    ds = [(dt.date(2025, 1, 1) + dt.timedelta(days=7 * i)).isoformat() for i in range(80)]
    for key in ("bills", "l2", "g2l3", "g3l6", "g6l7", "g7l11", "g11l21", "g21"):
        out[key] = [{"date": d, "value": start + (end - start) * i / 79} for i, d in enumerate(ds)]
    return out, ds
pdd, ds = pd_rows(20, 30)
last = dt.date.fromisoformat(ds[-1])
auc = lambda pct_now, pct_ago: (
    [{"date": (last - dt.timedelta(days=30)).isoformat(), "dealer_pct": pct_now}]
    + [{"date": (last - dt.timedelta(days=400)).isoformat(), "dealer_pct": pct_ago}])
check("③ 庫存增＋承接升 → 被動吸收", "被動吸收" in F.dealer_inventory(pdd, auc(15, 10))["read"])
check("③ 庫存增＋承接沒升 → 主動持有", "主動持有" in F.dealer_inventory(pdd, auc(10, 10))["read"])
pdd2, _ = pd_rows(30, 20)
check("③ 庫存減 → 去化", "下降" in F.dealer_inventory(pdd2, auc(10, 10))["read"])

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
