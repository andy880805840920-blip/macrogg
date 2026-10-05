# 通膨頁第一步（2026-10 使用者定案）的回歸測試——不打網路：
#   · 格位：核心 PCE 年增率定格位，三月＋六月年化同向越過門檻時推一格
#   · 動能：改用核心 PCE 近三月平均月增（0.17／0.27），PCE 還沒公布時用核心 CPI 預告
#   · 檢核：6 盞燈（新增核心 PCE 三月年化、短期通膨預期；拿掉核心除住房等）
#   · 綜合判定：明確升溫／黏著不降／穩定降溫（穩定降溫要連續兩個月）
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import yaml                                                   # noqa: E402
from src.analysis import inflation as ia                       # noqa: E402
from src.analysis import scenario as scn                       # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過 " if cond else "失敗 "), name, ("— " + str(detail)[:160]) if detail else "")
    ok = ok and bool(cond)


def idx(monthly: list[float], start=(2024, 1), base=100.0):
    """月增率（%）列表 → 指數序列。"""
    y, m = start
    rows, v = [{"date": f"{y:04d}-{m:02d}-01", "value": base}], base
    for g in monthly:
        m += 1
        if m > 12:
            m, y = 1, y + 1
        v *= 1 + g / 100
        rows.append({"date": f"{y:04d}-{m:02d}-01", "value": v})
    return rows


B = {"low": 2.25, "high": 2.50}

# ---- 格位 ----
check("① 三月、六月年化都高於高門檻 → 中推成高",
      scn.inflation_push("中", 3.1, 2.9, B)[0] == "高"
      and "往高推一格" in scn.inflation_push("中", 3.1, 2.9, B)[1])
check("①b 只有三月年化高、六月沒有 → 不推",
      scn.inflation_push("中", 3.1, 2.4, B) == ("中", ""))
check("①c 都低於低門檻 → 高推成中",
      scn.inflation_push("高", 2.0, 2.1, B)[0] == "中")
check("①d 已經在最高格不再推、缺資料不推",
      scn.inflation_push("高", 3.5, 3.5, B) == ("高", "")
      and scn.inflation_push("中", None, 3.0, B) == ("中", ""))
check("①e classify_inflation 帶六月年化：年增 2.4%（中）＋3M/6M 都 >2.5 → 高",
      scn.classify_inflation(2.4, 3.0, B, 2.7) == "高"
      and scn.classify_inflation(2.4, 3.0, B) == "中")

# ---- 動能 ----
check("② PCE 已公布 → 用核心 PCE 月步速（0.17／0.27）",
      scn.classify_inflation_momentum({"core_pce_pace3": 0.16, "core_cpi_pace3": 0.35}) == "降溫"
      and scn.classify_inflation_momentum({"core_pce_pace3": 0.22}) == "持平"
      and scn.classify_inflation_momentum({"core_pce_pace3": 0.28}) == "升溫")
check("②b PCE 還沒公布（推估中）→ 用核心 CPI 當預告（0.2／0.3）",
      scn.inflation_momentum_source({"core_pce_pace3": 0.16, "core_cpi_pace3": 0.32,
                                     "pce_estimated": True}) == ("cpi_preview", 0.32)
      and scn.classify_inflation_momentum({"core_pce_pace3": 0.16, "core_cpi_pace3": 0.32,
                                           "pce_estimated": True}) == "升溫")
check("②c PCE 門檻常數＝CPI 門檻扣掉約 0.03",
      (ia.PCE_PACE_TARGET, ia.PCE_PACE_HOT) == (0.17, 0.27))

# ---- 燈號設定 ----
cfg = yaml.safe_load((ROOT / "config" / "inflation.yaml").read_text(encoding="utf-8"))
keys = [l["key"] for l in cfg["regime_lights"]]
check("③ 6 盞燈、順序依重要性；核心除住房／中位數／汽油已拿掉",
      keys == ["core_pce_3m", "supercore_3m", "core_pce_yoy", "expect_1y",
               "expect_5y5y", "core_goods_yoy"], keys)

# ---- 綜合判定 ----
LC = cfg["regime_lights"]
calm = [0.15] * 20                                  # ≈ 年化 1.8%


def S(pce, sc=None, mich=3.0, t5=2.2):
    return {"PCEPILFE": idx(pce),
            "CPISUPERCORE": idx(sc if sc is not None else [0.2] * len(pce)),
            "MICH": [{"date": "2025-01-01", "value": mich}, {"date": "2025-02-01", "value": mich}],
            "T5YIFR": [{"date": "2025-02-03", "value": t5}]}


v = ia.inflation_verdict(S(calm), LC)
check("④ 一路平穩（3M、6M 約 1.8%）→ 穩定降溫", v["label"] == "穩定降溫"
      and v["lean"] == "dovish", v)
v = ia.inflation_verdict(S([0.3] * 17 + [0.12, 0.12, 0.12]), LC)
check("④b 剛降溫一個月（前一期 3M 仍高）→ 黏著不降，說明是「降溫第一個月」",
      v["label"] == "黏著不降" and "降溫第一個月" in v["reason"], v)
v = ia.inflation_verdict(S([0.3] * 20, sc=[0.4] * 20), LC)
check("④c 3M、6M 都 ≈3.6% 且超級核心 ≈4.9% 警戒 → 明確升溫",
      v["label"] == "明確升溫" and v["lean"] == "hawkish", v)
v = ia.inflation_verdict(S(calm, t5=2.7), LC)
check("④d 長期預期 2.7% 警戒 → 不管其他直接明確升溫", v["label"] == "明確升溫"
      and "脫錨" in v["reason"], v)
v = ia.inflation_verdict(S([0.15] * 14 + [0.3] * 6, sc=[0.2] * 20), LC)
check("④e 3M 偏高但 6M 還不到 2.8、超級核心正常、動能升溫 → 黏著不降（沒到明確）",
      v["label"] in ("黏著不降", "明確升溫"), v)
v = ia.inflation_verdict(S(calm, mich=4.5), LC)
check("④f 短期預期 4.5% 警戒 → 擋住穩定降溫", v["label"] == "黏著不降"
      and "短期通膨預期" in v["reason"], v)
check("④g 規則文字含三個結論", all(w in ia.INFL_VERDICT_RULE
                                  for w in ("明確升溫", "穩定降溫", "黏著不降")))

# ---- 燈號數值 ----
summ = ia.summarize({"PCEPILFE": idx(calm), "MICH": [{"date": "2025-01-01", "value": 3.1}]}, [])
lv = ia.light_values({"PCEPILFE": idx(calm), "MICH": [{"date": "2025-01-01", "value": 3.1}]}, summ)
check("⑤ light_values 有核心 PCE 三月年化與短期預期",
      "core_pce_3m" in lv and "expect_1y" in lv and lv["expect_1y"][2] == "3.1%", lv.keys())
check("⑤b 摘要有 6M 年化、月增與月步速",
      summ.pce_core_6m is not None and abs(summ.pce_core_mom - 0.15) < 1e-6
      and abs(summ.pce_core_pace3 - 0.15) < 1e-6)

# ---- 關鍵訊號分層（第二步）----
from types import SimpleNamespace as NS                        # noqa: E402
from src.analysis import rules_inflation as ri                  # noqa: E402
from src.analysis.rules import Flag                             # noqa: E402
ctx = NS(s=NS(pce_core_yoy=3.0, pce_core_3m=2.0, pce_core_6m=2.7, pce_core_mom=0.25))
f = ri.r_pce_momentum(ctx)
check("⑦ 核心 PCE 降溫訊號：三月年化低於年增 0.3 以上、六月沒反向",
      f and f.key == "pce_cooling" and f.lean == "dovish" and f.severity == "alert", f)
check("⑦b 六月年化反向（高於年增）→ 不算方向明確",
      ri.r_pce_momentum(NS(s=NS(pce_core_yoy=3.0, pce_core_3m=2.0, pce_core_6m=3.2,
                                pce_core_mom=0.1))) is None)
_orig_rules = list(ri.RULES)
try:
    ri.RULES[:] = [lambda c: Flag("cpi_cooling", "alert", "c", "d", "dovish"),
                   lambda c: Flag("pace_ontrack", "watch", "p", "d", "dovish"),
                   lambda c: Flag("pce_cooling", "watch", "pce", "d", "dovish"),
                   lambda c: Flag("shelter_drag", "watch", "s", "d", "dovish"),
                   lambda c: Flag("goods_deflation", "alert", "g", "d", "dovish"),
                   lambda c: Flag("supercore_hot", "alert", "sc", "d", "hawkish")]
    fl = ri.run_rules(None)
finally:
    ri.RULES[:] = _orig_rules
check("⑧ 排序：3M 動能（PCE 在前）→ 超級核心 → 整體與住房 → 其他",
      [x.key for x in fl] == ["pce_cooling", "pace_ontrack", "supercore_hot",
                              "shelter_drag", "cpi_cooling", "goods_deflation"]
      and [x.tier for x in fl] == [1, 1, 2, 3, 4, 4], [(x.key, x.tier) for x in fl])

# ---- 第三步：軟體與配件、PCE 方法說明 ----
from src.analysis import pce_detail as pdl                      # noqa: E402
_lines = ["%SeriesCode,Period,Value", 'DCPSRG,2025M08,"73.136"', 'DCPSRG,2026M05,"82.817"',
          'DCPSRG,2026M08,"84.552"', 'DCPSRC,2025M08,"228,358"', 'DCPSRC,2026M05,"240,000"',
          'DCPSRC,2026M08,"250,780"', 'DPCCRC,2025M08,"18,751,637"',
          'DPCCRC,2026M05,"19,500,000"', 'DPCCRC,2026M08,"19,870,393"', 'OTHER,2026M08,"1"']
bea = pdl.fetch_bea(_get=lambda u: _lines)
check("⑨ BEA 原始檔：只留三條序列、千分位逗號正確解析",
      set(bea) == {"BEA:DCPSRG", "BEA:DCPSRC", "BEA:DPCCRC"}
      and bea["BEA:DCPSRC"][-1]["value"] == 250780.0)
sw = pdl.software_contribution(bea)
check("⑨b 軟體與配件：權重約 1.26%、年增約 15.6%、對核心 PCE 年增約 +0.19 個百分點",
      sw and abs(sw["weight"] - 1.262) < 0.01 and abs(sw["price_yoy"] - 15.61) < 0.05
      and abs(sw["contrib_yoy"] - 0.19) < 0.01, sw)
check("⑨c 抓取失敗 → 空 dict（區塊不顯示）",
      pdl.fetch_bea(_get=lambda u: (_ for _ in ()).throw(OSError("x"))) == {})
check("⑩ PCE 方法說明在 config、三個項目都在",
      len(cfg["pce_method_note"]["items"]) == 3
      and "投資組合管理" in cfg["pce_method_note"]["items"][0])

# ---- 第四步：實質消費力道 ----
from src import build as _b                                     # noqa: E402


def _cons(c_g, i_g, sav):
    return _b._consumption_block({"PCEC96": idx([c_g] * 20), "DSPIC96": idx([i_g] * 20),
                                  "PSAVERT": [{"date": f"2025-{m:02d}-01", "value": v}
                                              for m, v in zip(range(1, 13), sav)]})


check("⑪ 消費三月年化 <0.5% → 消費明顯放緩（利降息）",
      _cons(0.02, 0.1, [4.0] * 12)["title"] == "消費明顯放緩")
check("⑪b 消費比所得快 1 個百分點以上＋儲蓄率半年降 0.5 以上 → 靠動用儲蓄撐",
      _cons(0.25, 0.1, [5.0] * 6 + [4.8, 4.6, 4.5, 4.4, 4.3, 4.2])["title"] == "消費靠動用儲蓄撐")
check("⑪c 消費 ≥2%、所得 ≥1.5% → 所得撐得住消費（利升息）",
      _cons(0.2, 0.18, [4.5] * 12)["lean"] == "hawkish")
check("⑪d 資料不足 → None", _b._consumption_block({"PCEC96": idx([0.1] * 5)}) is None)

# ---- 頁面（有 output 才檢查）----
OUT = ROOT / "output" / "inflation" / "index.html"
if OUT.exists():
    h = OUT.read_text(encoding="utf-8")
    check("⑥ 通膨頁：檢核區改名、有綜合判定與判定規則",
          "關鍵指標檢核與綜合判定" in h and "綜合判定：" in h and "判定規則：" in h)
    check("⑥b 核心 PCE 卡副標有月增、3M、6M", "6M 年化" in h and "3M 年化" in h)
    check("⑥d 超級核心改名、CPI 與 PCE 差異、PCE 方法說明",
          "超級核心服務（核心服務除住房）" in h and "CPI 與 PCE 為什麼不同" in h
          and "PCE 計算方式調整" in h)
    check("⑥e 實質消費力道卡", 'id="consumption"' in h and "實質可支配所得" in h)
    check("⑥c 關鍵訊號：本期總結、分層小標、其他收合",
          "本期總結：" in h and 'class="sig-tier">三個月動能' in h
          and ('class="f-more sig-rest"' in h or h.count('class="sig-tier"') >= 1))

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
