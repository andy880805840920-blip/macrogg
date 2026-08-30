# 時間序列完整性閘門的回歸測試（不打網路）
#
# 由來：2026-08-28（週五）FRED 就貼出了 08-31（週一）的 IORB，
# 於是週五到週日的每一次排程都被判成「未來資料」、整站停止發布
# （Actions exit code 2）。IORB 是行政設定利率——值在生效前就已知，
# 來源照實往前貼是正常行為，不是壞資料。
#
# 這個檔案釘住三件事：行政利率允許超前、超前太多仍然要擋、
# 其他序列的零容忍一點都沒有被削弱。
import sys
import pathlib
import datetime as dt

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.analysis import series_quality as sq              # noqa: E402

ok = True
TODAY = dt.date(2026, 8, 30)                               # 週日
ADMIN = {"IORB", "DFEDTARU", "DFEDTARL"}


def check(name, cond, detail=""):
    global ok
    print(("通過 " if cond else "失敗 "), name, ("— " + str(detail)[:90]) if detail else "")
    ok = ok and bool(cond)


def rows(*dates, value=3.65):
    return [{"date": d, "value": value} for d in dates]


def run(series, **kw):
    kw.setdefault("administered_ids", ADMIN)
    return sq.audit_bundle(series, today=TODAY, **kw)


def errs(series, **kw):
    return sq.errors(run(series, **kw))


def kinds(issues):
    return sorted({i.kind for i in issues})


# ① 實際事故重現：IORB 最新一筆是 08-31（週一），今天是 08-30（週日）
CASE = {"IORB": rows("2026-08-26", "2026-08-27", "2026-08-28", "2026-08-31")}
check("① 事故重現：IORB 超前 1 天 → 不再停止發布", errs(CASE) == [],
      [(e.series_id, e.detail) for e in errs(CASE)])
_info = [i for i in run(CASE) if i.severity == "info"]
check("①b 留下一筆 info（log 說得出為什麼有未來日期）",
      len(_info) == 1 and _info[0].kind == "future_ahead"
      and "超前今天" in _info[0].detail, _info and _info[0].detail)

# ② 邊界：容許 7 天——7 天放行、8 天要擋
check("② 超前 7 天（邊界內）→ 放行",
      errs({"IORB": rows("2026-09-06")}) == [])
_e8 = errs({"IORB": rows("2026-09-07")})
check("②b 超前 8 天 → 仍然報錯（真的壞掉還是擋得住）",
      len(_e8) == 1 and _e8[0].kind == "future_actual", _e8 and _e8[0].detail)
check("②c 超前 30 天 → 報錯，訊息帶差距與容許值",
      (lambda e: len(e) == 1 and "共 30 天" in e[0].detail
       and "容許的 7 天" in e[0].detail)(errs({"IORB": rows("2026-09-29")})),
      errs({"IORB": rows("2026-09-29")})[0].detail)
check("②d 容許天數常數存在且合理", 0 < sq.ADMINISTERED_FUTURE_DAYS <= 14)

# ③ 一般序列的零容忍完全沒有被削弱
check("③ 一般序列超前 1 天 → 照樣報錯",
      (lambda e: len(e) == 1 and e[0].kind == "future_actual")(
          errs({"DGS10": rows("2026-08-31", value=4.7)})),
      errs({"DGS10": rows("2026-08-31", value=4.7)}))
check("③b 一般序列的錯誤訊息維持原本的寫法（沒有容許值可講）",
      "晚於今天" in errs({"DGS10": rows("2026-08-31", value=4.7)})[0].detail)

# ④ 預測路徑仍是無上限放行，而且不囉唆（不產生 info）
_fc = run({"NROU": rows("2027-12-01", value=4.2)},
          forecast_ids={"NROU"})
check("④ 預測序列超前一年多 → 放行", sq.errors(_fc) == [])
check("④b 預測序列不留 info（無上限那類不必每次講）", _fc == [])

# ⑤ 政策利率區間上下緣也在名單裡（同一類，遲早會踩到同一顆地雷）
check("⑤ DFEDTARU／DFEDTARL 同樣容許超前",
      errs({"DFEDTARU": rows("2026-08-31", value=3.75),
            "DFEDTARL": rows("2026-08-31", value=3.50)}) == [])
_run_src = (pathlib.Path(__file__).resolve().parents[1] / "run.py").read_text(
    encoding="utf-8")
_admin_line = _run_src.split("_administered_ids = ")[1].split("\n")[0]
check("⑤b run.py 的白名單確實含這三條（接線沒斷）",
      all(x in _admin_line for x in ("IORB", "DFEDTARU", "DFEDTARL")),
      _admin_line)

# ⑥ 其他檢查對行政利率序列一樣有效——放寬的只有「未來日期」這一項
check("⑥ 行政利率序列的缺值照樣報錯",
      (lambda e: [x.kind for x in e] == ["missing_value"])(
          errs({"IORB": [{"date": "2026-08-28", "value": None}]})))
check("⑥b 行政利率序列的重複日期照樣報錯",
      "duplicate_date" in kinds(errs(
          {"IORB": rows("2026-08-28", "2026-08-28")})))
check("⑥c 行政利率序列的日期錯序照樣報錯",
      "out_of_order" in kinds(errs(
          {"IORB": rows("2026-08-28", "2026-08-26")})))

# ⑦ assert_clean 只被 error 觸發，info 不會讓它拋錯
try:
    sq.assert_clean(CASE, today=TODAY, administered_ids=ADMIN)
    _clean = True
except ValueError:
    _clean = False
check("⑦ assert_clean 不被 info 觸發", _clean)
try:
    sq.assert_clean({"DGS10": rows("2026-08-31", value=4.7)}, today=TODAY)
    _raised = False
except ValueError:
    _raised = True
check("⑦b assert_clean 仍被 error 觸發", _raised)

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
