"""
CLI 冒煙測試——把 run.py 真的跑起來。

為什麼需要這個檔案
------------------
三張九宮格改版時，`Scenario.verdict_name` 被移除，
`tests/test_scenario_regimes.py` 也確實斷言了「這個欄位已經不存在」。
但沒有人發現 `run.py --json` 還在讀它——而排程跑的正是
`python run.py --json`。結果是：頁面產得出來、latest.json 崩潰、
GitHub Actions 在 commit 之前就 exit 1，**網站從此不再更新**。

單元測試檢查「元件」，這個檔案檢查「程式真的跑得完」。
每一個排程或文件會用到的旗標組合都要在這裡跑過一次。

    python tests/test_cli_smoke.py
"""
import sys, subprocess, pathlib, json

ROOT = pathlib.Path(__file__).parent.parent
OUT = ROOT / "output"

# 排程與文件實際使用的旗標組合
CASES = [
    (["--offline"], "離線建置"),
    (["--offline", "--json"], "離線建置＋latest.json（排程用的組合）"),
    (["--offline", "--only", "labor"], "局部重跑：勞動"),
    (["--offline", "--only", "inflation"], "局部重跑：通膨"),
    (["--offline", "--only", "fomc"], "局部重跑：聯準會"),
]

ok = True
for args, name in CASES:
    r = subprocess.run([sys.executable, "run.py", *args], cwd=ROOT,
                       capture_output=True, text=True)
    good = r.returncode == 0
    print(f"{'通過' if good else '失敗'}  {name}  →  退出碼 {r.returncode}")
    if not good:
        print("   " + (r.stderr.strip().splitlines() or ["(無錯誤訊息)"])[-1])
    ok &= good

# --json 一定要真的產出可解析的檔案，不是只有不崩潰
j = OUT / "latest.json"
if j.exists():
    try:
        d = json.loads(j.read_text(encoding="utf-8"))
        need = {"scenario", "generated_at"}
        miss = need - set(d)
        good = not miss and bool(d["scenario"].get("name"))
        print(f"{'通過' if good else '失敗'}  latest.json 可解析且含必要欄位"
              + (f"（缺 {miss}）" if miss else ""))
        ok &= good
    except Exception as e:                          # noqa: BLE001
        print(f"失敗  latest.json 無法解析：{e}")
        ok = False
else:
    print("失敗  latest.json 沒有產出")
    ok = False

# 每一頁都要真的有內容，不是空殼
for rel in ("index.html", "labor/index.html", "inflation/index.html",
            "fomc/index.html", "rates/index.html", "scenario/index.html",
            "archive/index.html"):
    p = OUT / rel
    n = len(p.read_text(encoding="utf-8")) if p.exists() else 0
    good = n > 4000
    print(f"{'通過' if good else '失敗'}  {rel:24s} {n:>7,} 字元")
    ok &= good

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
