"""
全站時鐘測試 — 「現在」與「今天」一律用台北時間。

為什麼需要這個檔案
------------------
產出是在 GitHub Actions 上跑的，那台機器的時鐘是 **UTC**。
直接用 `datetime.now()` 會出兩種錯，而且都是**畫面上看不出來**的那種：

  ① 時間戳沒標時區。排程 13:45 UTC 跑完，畫面印「更新於 13:46」，
     但 OPERATIONS.md 寫的是「每天晚上 21:45 更新」——兩個數字對不起來。
  ② 日期整個差一天。台北比 UTC 早 8 小時，所以**台北的 00:00–08:00
     之間 UTC 還停在昨天**。這段時間 push 觸發重建的話，
     「N 天前發布」與「距下次發布還有 N 天」全部少一天。

第 ② 條特別麻煩：它不會報錯，數字只是默默地錯，而且只在一天當中
某八個小時裡錯——本機白天測永遠測不到。

所以這裡除了驗證 clock 本身，還**用靜態掃描擋住回歸**：
任何模組再出現裸的 `datetime.now()` / `date.today()` 就直接失敗。

    python tests/test_clock.py
"""
import re
import sys
import pathlib
import datetime as dt

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from src import clock  # noqa: E402

ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    print(f"{'通過' if cond else '失敗'}  {name}" + (f" — {detail}" if detail else ""))
    ok &= bool(cond)


# ---------------------------------------------------------------------------
# ① 偏移量
# ---------------------------------------------------------------------------
check("① 台北是 UTC+8", clock.TAIPEI.utcoffset(None) == dt.timedelta(hours=8),
      str(clock.TAIPEI.utcoffset(None)))

utc_now = dt.datetime.now(dt.timezone.utc)
delta = clock.now() - utc_now
check("② now() 跟 UTC 是同一個瞬間", abs(delta.total_seconds()) < 5,
      f"{delta.total_seconds():.1f} 秒")
check("③ now() 帶時區（不是天真的 datetime）",
      clock.now().tzinfo is not None)
check("④ 牆上時間比 UTC 快 8 小時",
      clock.now().hour == (utc_now.hour + 8) % 24,
      f"台北 {clock.now().hour} 時 vs UTC {utc_now.hour} 時")


# ---------------------------------------------------------------------------
# ② 跨日那八個小時 —— 這才是會出事的地方
# ---------------------------------------------------------------------------
# UTC 16:00 之後，台北已經是隔天了。用 UTC 的 date.today() 會少一天。
for utc_h, want_shift in [(0, 0), (8, 0), (15, 0), (16, 1), (20, 1), (23, 1)]:
    fake = dt.datetime(2026, 8, 11, utc_h, 30, tzinfo=dt.timezone.utc)
    tpe = fake.astimezone(clock.TAIPEI)
    shift = (tpe.date() - fake.date()).days
    check(f"⑤ UTC {utc_h:02d}:30 → 台北日期 +{want_shift} 天",
          shift == want_shift, f"得到 +{shift}")


# ---------------------------------------------------------------------------
# ③ 顯示格式
# ---------------------------------------------------------------------------
s = clock.stamp()
check("⑥ stamp() 有標時區", s.endswith("（台北）"), s)
check("⑦ stamp() 的格式是 YYYY-MM-DD HH:MM",
      bool(re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}（台北）", s)), s)
# workflow 用 grep -o '更新於 [0-9: -]*' 把時間戳印進執行紀錄，
# 好跟網站上的數字對照。日期時間之間不能出現別的字元，不然那行 grep 會斷。
check("⑧ 時間戳前半段只有數字與分隔符（workflow 的 grep 靠這個）",
      bool(re.match(r"^[0-9: -]+", s)), s)

i = clock.iso()
check("⑨ iso() 帶 +08:00 偏移", i.endswith("+08:00"), i)
check("⑩ iso() 可以被 fromisoformat 讀回來",
      dt.datetime.fromisoformat(i).utcoffset() == dt.timedelta(hours=8))

check("⑪ today() 跟 now() 同一天", clock.today() == clock.now().date())


# ---------------------------------------------------------------------------
# ④ 靜態掃描：不准有第二個時鐘
# ---------------------------------------------------------------------------
# 這是這個檔案真正的價值。上面那些都只是驗證 clock 自己；
# 真正會壞的是有人日後在別的地方又寫了一次 datetime.now()。
BARE = re.compile(r"(?<!clock\.)\b(?:dt|datetime)\.datetime\.now\(\)"
                  r"|(?<!clock\.)\b(?:dt|datetime)\.date\.today\(\)"
                  r"|\butcnow\(\)")
# clock.py 自己當然要用；fixtures 的 END 是寫死的示範日期不算。
SKIP = {"src/clock.py"}

offenders = []
for p in sorted(ROOT.glob("**/*.py")):
    rel = p.relative_to(ROOT).as_posix()
    if rel in SKIP or "__pycache__" in rel or rel.startswith(("output/", "fixtures/")):
        continue
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        if BARE.search(line):
            offenders.append(f"{rel}:{n}  {line.strip()}")

check("⑫ 全庫沒有第二個時鐘（裸的 datetime.now／date.today）",
      not offenders, "\n      " + "\n      ".join(offenders) if offenders else "")

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
