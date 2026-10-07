"""首頁主要利率使用官方日資料；FRED 備援與盤中指標保持獨立。"""
import copy
import pathlib
import sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.analysis import focus_today as ft
from src.pages import home

RS = {"DGS2": [{"date": "2026-10-02", "value": 4.83},
               {"date": "2026-10-05", "value": 4.84}]}
original = copy.deepcopy(RS)
requested = []
def get(url):
    requested.append(url)
    raise RuntimeError("其他報價失敗，使用已抓到的 FRED 資料")

fresh = [{"label": "2 年期", "value": 4.99, "delta_bp": 16,
          "date": "2026-10-06", "live": True},
         {"label": "10 年期", "value": 5.27, "delta_bp": -4,
          "date": "2026-10-06", "live": True}]
catalog = ft.build_catalog(RS, {}, fresh, offline=False, _get=get,
                          _post=lambda *a: (_ for _ in ()).throw(RuntimeError("無台指期")))
chips = {c["id"]: c for c in catalog}
assert chips["dgs2"]["value"] == "4.84%"
assert chips["dgs2"]["delta"] == "+1 bp"
assert chips["dgs2"]["iso"] == "2026-10-05"
assert not any("2YY" in u for u in requested)
assert RS == original, "首頁報價不得改寫 FRED 歷史資料"
assert chips["dgs10"]["value"] == "—", "缺官方資料不得以盤中冒充"
assert chips["live_dgs10"]["value"] == "5.27%", "盤中報價使用獨立指標"
assert not chips["live_dgs10"]["on"], "盤中指標由使用者選擇"
html = home._focus_strip({"chips": catalog, "text": "", "fedwatch": None})
assert "FRED 10/05" in html
assert 'data-chip="dgs2" data-d="2026-10-05"' in html

empty = {c["id"]: c for c in ft.build_catalog({}, {}, fresh, offline=True)}
assert empty["dgs2"]["value"] == "—", "缺 FRED 時不得用期貨冒充"
print("通過：2Y 使用 FRED 最新日期與數值、日變動、缺資料處理、來源標示，盤中報價使用獨立指標且歷史資料未修改。")
