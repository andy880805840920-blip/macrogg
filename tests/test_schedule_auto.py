"""2026-10-22：發布行事曆、FOMC 會議日、票委名單的自動維護（src/schedule_auto.py）。"""
import sys, pathlib, tempfile, datetime as dt
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import schedule_auto as sa        # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過  " if cond else "失敗  ") + name + (f" — {detail}" if detail and not cond else ""))
    ok &= bool(cond)


TODAY = dt.date(2026, 10, 22)
tmp = pathlib.Path(tempfile.mkdtemp())

# ① FRED 問到的＋BEA 補 PCE／GDP，並存檔
c = tmp / "rel.json"
r1 = sa.merge_release_dates({"cpi": ["2026-11-10", "2026-12-10"], "ppi": ["2026-11-13"]}, cache_path=c,
                            bea={"pce": ["2026-10-29", "2026-11-25", "2027-01-28"], "gdp": ["2026-10-29"]}, today=TODAY)
check("① FRED＋BEA 合併", r1["cpi"] == ["2026-11-10", "2026-12-10"] and r1["pce"][-1] == "2027-01-28" and "gdp" in r1, r1)
check("② 存檔", c.exists())
# ② FRED 維護（什麼都沒問到）→ 沿用上次存的
r2 = sa.merge_release_dates({}, cache_path=c, bea={}, today=TODAY)
check("③ FRED 維護：沿用上次存的官方日期", r2.get("cpi") == ["2026-11-10", "2026-12-10"] and r2.get("ppi") == ["2026-11-13"], r2)
# ③ 過期的日期自動剔除（三天前以前）
r3 = sa.merge_release_dates({}, cache_path=c, bea={}, today=dt.date(2026, 11, 20))
check("④ 過期日期剔除", r3.get("cpi") == ["2026-12-10"] and "ppi" not in r3, r3)
# ④ 離線模式只讀不寫
before = c.read_text(encoding="utf-8")
sa.merge_release_dates({"cpi": ["2030-01-01"]}, offline=True, cache_path=c, today=TODAY)
check("⑤ 離線模式不寫檔", c.read_text(encoding="utf-8") == before)

# ⑤ 45 天提醒：自動行事曆已排到後面就不提醒
cal = {"employment": {"2026-11": "2026-12-04"}, "jolts": {"2026-10": "2026-12-01"}, "cpi": {"2027-11": "2027-12-10"}}
short = sa.short_calendar(cal, {"employment": ["2026-12-04", "2027-01-08"]}, today=TODAY)
check("⑥ 只提醒自動也沒排到的項目（JOLTS）", short == ["jolts"], short)

# ⑥ FOMC 名單解析
PAGE = """<h4>2026 Committee Members</h4><p><a>Kevin Warsh</a>, Board of Governors, Chairman</p>
<p><a>John C. Williams</a>, New York, Vice Chair</p><p><a>Michael S. Barr</a>, Board of Governors</p>
<p><a>Michelle W. Bowman</a>, Board of Governors</p><p><a>Lisa D. Cook</a>, Board of Governors</p>
<p><a>Beth M. Hammack</a>, Cleveland</p><p><a>Philip N. Jefferson</a>, Board of Governors</p>
<p><a>Neel Kashkari</a>, Minneapolis</p><p><a>Lorie K. Logan</a>, Dallas</p><p><a>Anna Paulson</a>, Philadelphia</p>
<p><a>Jerome H. Powell</a>, Board of Governors</p><p><a>Christopher J. Waller</a>, Board of Governors</p>
<h4>Alternate Members</h4><p><a>Thomas I. Barkin</a>, Richmond</p><p><a>Mary C. Daly</a>, San Francisco</p>
<p><a>Austan D. Goolsbee</a>, Chicago</p><p><a>Sushmita Shukla</a>, First Vice President, New York</p>
<p><a>Cheryl Venable</a>, Interim President, Atlanta</p><h4>Federal Reserve Bank Rotation on the FOMC</h4>"""
ro = sa.parse_roster(PAGE)
check("⑦ 理事 7 位（不含已離任者）", ro and ro["board"] == ["Warsh", "Barr", "Bowman", "Cook", "Jefferson", "Powell", "Waller"], ro)
check("⑧ 今年票委 5 位（含紐約）", ro and ro["voters"]["2026"] == ["Williams", "Hammack", "Kashkari", "Logan", "Paulson"], ro)
check("⑨ 明年票委＝紐約＋候補總裁（紐約第一副總裁不算）",
      ro and ro["voters"]["2027"] == ["Williams", "Barkin", "Daly", "Goolsbee", "Venable"], ro)
check("⑩ 版面改掉、解析不出來 → None（沿用舊名單）", sa.parse_roster("<p>nothing</p>") is None)

# ⑦ 會議日解析與合理性
spans = [(dt.date(2026, 10, 27), dt.date(2026, 10, 28)), (dt.date(2026, 12, 8), dt.date(2026, 12, 9)),
         (dt.date(2027, 1, 26), dt.date(2027, 1, 27)), (dt.date(2025, 1, 28), dt.date(2025, 1, 29))]
check("⑪ 決策日取第二天、只留今年起", sa.parse_meetings(spans, TODAY) == ["2026-10-28", "2026-12-09", "2027-01-27"])
check("⑫ 間隔太短（解析錯）→ 不採用", sa.parse_meetings([(dt.date(2026, 11, 1), dt.date(2026, 11, 2)),
                                                    (dt.date(2026, 11, 5), dt.date(2026, 11, 6))], TODAY) == [])

# ⑧ 套進 focus 設定：官網有的年份換掉、沒列的年份保留手動；名單覆蓋
fc = tmp / "fomc.json"
cfg = {"fomc_dates": ["2026-10-28", "2026-12-16", "2028-01-26"], "fomc_board": ["Old"],
       "fomc_voters": {"2025": ["X"], "2026": ["Old"]}}
out = sa.apply_fomc(cfg, cache_path=fc, fetch=lambda: (spans, PAGE), today=TODAY)
check("⑬ 會議日：2026 以官網為準（12/16 錯的被換成 12/9）、2028 保留手動",
      out["fomc_dates"] == ["2026-10-28", "2026-12-09", "2027-01-27", "2028-01-26"], out["fomc_dates"])
check("⑭ 名單：理事與 2026、2027 用官網；2025 保留", out["fomc_board"][0] == "Warsh" and out["fomc_voters"]["2025"] == ["X"]
      and "Venable" in out["fomc_voters"]["2027"])
check("⑮ 原本的 cfg 不被改到", cfg["fomc_board"] == ["Old"])


def boom():
    raise RuntimeError("網路斷")


out2 = sa.apply_fomc(cfg, cache_path=fc, fetch=boom, today=TODAY)
check("⑯ 官網抓不到 → 用上次存的", out2["fomc_board"][0] == "Warsh" and "2026-12-09" in out2["fomc_dates"])
out3 = sa.apply_fomc(cfg, cache_path=tmp / "none.json", fetch=boom, today=TODAY)
check("⑰ 連存檔都沒有 → 原封不動用 config", out3 == cfg)

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
