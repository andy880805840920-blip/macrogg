"""官員立場（2026-10-29）：近 3 場反對票 → 近 90 天最近一則明確表態（AI 判斷、附原文引句）→ 中立。"""
import sys, pathlib, json, tempfile, datetime as dt
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.analysis import fomc_extra as fx                # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過  " if cond else "失敗  ") + name + (f" — {detail}" if detail and not cond else ""))
    ok &= bool(cond)


def V(*xs):
    """逐場投票：'f'＝贊成、'h'＝主張升息、'c'＝主張降息、'o'＝主張維持。"""
    dates = ["2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28"]
    d = {"h": "hike", "c": "cut", "o": "hold"}
    return [{"date": dates[i], "v": "for" if x == "f" else "against", "dir": d.get(x, "")} for i, x in enumerate(xs)]


S = lambda d, s, q="引句", k="新聞標題": {"date": d, "s": s, "q": q, "kind": k}   # noqa: E731

# ① 近 3 場反對票優先
st, why = fx.decide_stance({"votes": V("f", "f", "f", "f", "f", "h")}, [S("2026-10-29", "pause")], "hike")
check("① 10/28 主張升息的反對票 → 鷹派（比後來的發言優先）", st == "hawkish" and "10/28 反對票" in why, why)
st, _ = fx.decide_stance({"votes": V("f", "f", "f", "f", "o", "f")}, [], "hike")
check("① 升息循環裡主張「維持」的反對票 → 鴿派", st == "dovish")
st, _ = fx.decide_stance({"votes": V("f", "f", "f", "f", "o", "f")}, [], "cut")
check("① 降息循環裡主張「維持」的反對票 → 鷹派", st == "hawkish")
# ② 超過 3 場的舊反對票不用
st, why = fx.decide_stance({"votes": V("c", "f", "f", "f", "f", "f")}, [S("2026-10-08", "hike", "More hikes needed")], "hike")
check("② Waller 例：一年前主張降息的反對票不算，依 10/8「需要再升息」→ 鷹派", st == "hawkish" and "More hikes needed" in why, why)
st, why = fx.decide_stance({"votes": V("c", "f", "f", "f", "f", "f")}, [], "hike")
check("② 只有舊反對票、沒有發言 → 中立", st == "neutral", why)
# ③ 最近一則明確表態為準；升息循環裡暫停／觀望＝鴿派
st, _ = fx.decide_stance({"votes": V("f", "f", "f", "f", "f", "f")},
                         [S("2026-10-06", "hike"), S("2026-10-14", "pause")], "hike")
check("③ 最近一則是「暫停」→ 鴿派（升息循環）", st == "dovish")
st, _ = fx.decide_stance({"votes": []}, [S("2026-10-01", "pause")], "")
check("③ 沒有升降息循環時，暫停＝中立", st == "neutral")
st, _ = fx.decide_stance({"votes": V("f", "f", "f", "f", "f", "f")}, [], "hike")
check("③ 都沒有 → 中立", st == "neutral")

# ④ AI 判斷：引句必須在原文裡、每則只判斷一次
items = [{"who": "Logan", "date": "2026-10-01", "kind": "新聞標題", "text": "Dallas Fed's Logan Says Interest Rates Need to Be Half Percent Higher"},
         {"who": "Warsh", "date": "2026-10-28", "kind": "新聞標題", "text": "Warsh says politics played no role in Fed's rate decision"},
         {"who": "Bowman", "date": "2026-10-14", "kind": "新聞標題", "text": "US Fed's Bowman sees no urgency for another rate hike"}]
calls = []


def fake(src, sy):
    calls.append(src)
    d = json.loads(src)
    out = {}
    for k, v in d.items():
        if "Logan" in v["text"]:
            out[k] = {"s": "hike", "q": "Rates Need to Be Half Percent Higher"}
        elif "Bowman" in v["text"]:
            out[k] = {"s": "pause", "q": "no urgency for another hike"}     # 不是原文（原文是 another rate hike）
        else:
            out[k] = {"s": "none", "q": ""}
    return json.dumps(out), ""


tmp = pathlib.Path(tempfile.mkdtemp()) / "st.json"
r = fx.stance_ai(items, tmp, False, call=fake)
got = {it["who"]: r[fx.stance_key(it)]["s"] for it in items}
check("④ 有引句的採用（Logan＝hike）、沒表態的 none", got["Logan"] == "hike" and got["Warsh"] == "none", got)
check("④ 引句不在原文裡 → 當成沒表態", got["Bowman"] == "none", got)
fx.stance_ai(items, tmp, False, call=fake)
check("④ 第二次執行全部走快取，不再呼叫 AI", len(calls) == 1, len(calls))
check("④ 離線沒有快取時不呼叫", fx.stance_ai(items, None, True, call=fake) == {} and len(calls) == 1)

# ⑤ 循環判定、演講只留談利率的句子
D = lambda d, a: type("D", (), {"date": d, "decision": {"action": a}})()      # noqa: E731
check("⑤ 12 個月內最近一次調整是升息 → 升息循環",
      fx.policy_cycle([D("2025-12-10", "cut"), D("2026-09-16", "hike"), D("2026-10-28", "hold")], dt.date(2026, 10, 29)) == "hike")
_h = ("<html><p>Thank you for having me today.</p><p>In my base case, further policy adjustments are likely "
      "to be needed to ensure inflation comes down to target.</p><p>Bank supervision matters.</p></html>")
check("⑤ 演講只留談利率的句子", fx.policy_sentences(_h).startswith("In my base case, further policy adjustments"))

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
