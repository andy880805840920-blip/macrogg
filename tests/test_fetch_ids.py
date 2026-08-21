# 抓取清單：推導原料一定要在清單裡（不打網路，直接讀 config）
#
# 回歸的事故：九宮格通膨格從 CUSR0000SASLE 換成推導序列 CPISUPERCORE 時，
# 原料 SASLE 從 cpi_components 移走，之後沒有任何地方把它放進抓取清單。
# 線上每一次執行「核心服務除住房推導失敗」，supercore KPI、黏性訊號、
# 薪資傳導、核心 PCE 成分法整串缺值——而離線示範資料有這條，本機測不到。
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import yaml                                       # noqa: E402
import run as runner                              # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過 " if cond else "失敗 "), name, ("— " + str(detail)[:90]) if detail else "")
    ok = ok and bool(cond)


cfg = yaml.safe_load(
    (pathlib.Path(__file__).resolve().parents[1] / "config" / "inflation.yaml")
    .read_text(encoding="utf-8"))

ids, labels, inverts = runner.infl_series_ids(cfg)
sd = cfg.get("supercore_derive") or {}

check("① 推導原料（核心服務含住房）在抓取清單裡",
      sd.get("core_services") in ids, sd.get("core_services"))
check("② 推導原料（住房）在抓取清單裡", sd.get("shelter") in ids)
check("③ 推導序列本身不去抓（derived）", "CPISUPERCORE" not in ids)
check("④ 沒有重複的 id", len(ids) == len(set(ids)),
      f"{len(ids)} vs {len(set(ids))}")
check("⑤ 原料有標籤（頁尾失敗清單要看得懂）",
      bool(labels.get(sd.get("core_services"))))

# 設定檔沒有 supercore_derive 段時不爆炸、行為同 series_ids
cfg2 = {k: v for k, v in cfg.items() if k != "supercore_derive"}
ids2, _, _ = runner.infl_series_ids(cfg2)
base, _, _ = runner.series_ids(cfg, runner.INFL_GROUPS)
check("⑥ 沒有 supercore_derive 段也能跑", ids2 == base)

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
