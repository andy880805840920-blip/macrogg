"""
首頁「白宮與國會」（2026-11）：取代期中選舉那一格。

    python tests/test_whitehouse.py
"""
import datetime as dt
import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
import yaml                                          # noqa: E402
from src import clock                                # noqa: E402
from src.analysis import whitehouse as W             # noqa: E402
from src.pages import whitehouse as P                # noqa: E402
from src.pages import home                           # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(f"{'通過' if cond else '失敗'}  {name}" + (f" — {detail}" if detail else ""))
    ok &= bool(cond)


T = dt.date(2026, 11, 4)
clock.today = lambda: T                              # noqa: E731
cfg = yaml.safe_load((ROOT / "config" / "whitehouse.yaml").read_text(encoding="utf-8"))

# ① 設定檔：關稅排最後、只留一項；AI 與晶片全放；選舉格隱藏
check("① 主題順序：關稅放最後", cfg["topics"][-1] == "關稅", str(cfg["topics"]))
tar = [p for p in cfg["policies"] if "關稅" in p["topics"]]
check("① 關稅只留一項（美中貿易休戰）", len(tar) == 1 and tar[0]["name"] == "美中貿易休戰", str([p["name"] for p in tar]))
check("① 選舉那一格隱藏（設定檔開關、沒有刪除）", cfg["election_tile"] is False)

rows = W.policy_rows(cfg["policies"], T)
by = {r["id"]: r for r in rows}
check("② 有日期的下一步算倒數（12/11 暫時撥款 37 天）", by["fiscal_cr"]["days"] == 37, str(by["fiscal_cr"]))
check("② 沒日期的不倒數", by["debt_limit"]["days"] is None)
check("② 階段超出範圍會夾回去", W.policy_rows([{"name": "x", "stages": ["a", "b"], "stage": 9}], T)[0]["stage"] == 2)
check("② 超過 14 天沒確認標 stale",
      W.policy_rows([{"name": "x", "stages": ["a"], "updated": "2026-10-01"}], T)[0]["stale"])
check("② 過期的日期不顯示倒數",
      W.policy_rows([{"name": "x", "stages": ["a"], "next": {"date": "2026-10-01", "text": "t"}}], T)[0]["days"] is None)
cal = W.calendar_events(rows, T)
check("③ 月曆只放 45 天內有日期的（暫時撥款、資料中心併網）",
      sorted(c["date"] for c in cal) == ["2026-11-16", "2026-12-11"], str(cal))

# ④ 建置（離線）：選後一行在 1/2 以前顯示
with tempfile.TemporaryDirectory() as td:
    sp = pathlib.Path(td) / "wh.json"
    w = W.build(cfg, sp, offline=True)
    check("④ 離線也組得出來（政策清單）", w and len(w["policies"]) == len(cfg["policies"]))
    check("④ 選後一行（新國會就任前）", w["after"].startswith("民主黨"))
    clock.today = lambda: dt.date(2027, 1, 3)        # noqa: E731
    check("④ 新國會就任後選後那行消失", W.build(cfg, sp, offline=True)["after"] == "")
    clock.today = lambda: T                          # noqa: E731

    # ⑤ 線上流程（假新聞＋假 AI）：發言只收跟市場有關的、政策進度只提醒不改畫面
    rss = ("<rss><channel><item><title>Trump says tariffs on China could return - Reuters</title>"
           "<source>Reuters</source><pubDate>Tue, 03 Nov 2026 10:00:00 GMT</pubDate><link>https://r/1</link></item>"
           "</channel></rss>")

    def fake_call(src, system):
        if system is W.STATEMENT_SYSTEM:
            hid = json.loads(src)["headlines"][0]["id"]
            return json.dumps({"items": [{"topic": "關稅", "channel": "受訪", "zh": "稱對中關稅可能恢復", "ids": [hid]},
                                         {"topic": "選舉", "channel": "受訪", "zh": "談選舉", "ids": [hid]}]})
        if system is W.PROGRESS_SYSTEM:
            return '{"changed": true, "note": "新聞提到休戰可能延長"}'
        return "本週重點測試句。"
    w2 = W.build(cfg, sp, offline=False, _get=lambda url: rss, call=fake_call)
    check("⑤ 發言：只留五類主題（選舉被丟掉）", [x["topic"] for x in w2["items"]] == ["關稅"], str(w2["items"]))
    check("⑤ 本週重點有寫", w2["summary"] == "本週重點測試句。")
    st = json.loads(sp.read_text(encoding="utf-8"))
    check("⑤ 進度提醒寫進 state，不改畫面上的階段",
          "us_china_truce" in st["suggestions"] and by["us_china_truce"]["stage"] ==
          {r["id"]: r for r in w2["policies"]}["us_china_truce"]["stage"])

# ⑥ 指數
ser = {"USEPUINDXD": [{"date": (T - dt.timedelta(days=200 - i)).isoformat(), "value": 100 + i} for i in range(200)]}
e = W.epu_block(ser, T)
check("⑥ 政策不確定性指數：30 日均、偏高", e and e["value"] == round(sum(range(270, 300)) / 30) and e["level"] == "偏高", str(e))
check("⑥ 資料太少不畫", W.epu_block({"USEPUINDXD": ser["USEPUINDXD"][:10]}, T) is None)

# ⑦ 畫面
tile, panel = P.wh_tile(dict(w2, epu=e))
check("⑦ 小卡：川普插畫（assets/brand）＋最新一則", 'data-t="wh"' in tile and "/brand/wh-trump.webp" in tile
      and (ROOT / "assets" / "brand" / "wh-trump.webp").exists() and "最新：關稅" in tile)
i_lead, i_f, i_say, i_pol, i_ix = (panel.find(k) for k in ("wh-lead", "wh-f", "wh-say", "wh-pol", "wh-ix"))
check("⑦ 順序：本週重點 → 篩選 → 川普說了什麼 → 政策進度 → 指數", 0 <= i_lead < i_f < i_say < i_pol < i_ix)
check("⑦ 選後併在本週重點卡片裡", panel.find("wh-after") < i_f and "選後" in panel)
check("⑦ 篩選有「篩選主題」字樣、兩欄標題留筆數位置", "篩選主題" in panel and panel.count('class="wh-cnt"') == 2)
check("⑦ 每一項都帶主題（篩選用）", panel.count('data-tp="') == len(w2["items"]) + len(w2["policies"]))
check("⑦ 資料中心併網同時屬能源與 AI", 'data-tp="能源|AI 與晶片"' in panel)

# ⑧ 首頁：白宮與國會取代選舉格；打開開關選舉格回來
ctx = {"_whitehouse": dict(w2, election_tile=False), "_election": None, "_ai_events": None}
h = home._duo(ctx)
check("⑧ 首頁有白宮與國會", 'data-t="wh"' in h)
check("⑧ JS：一組篩選套用兩邊", "wh-f button" in home._DUO_JS and ".wh-say" in home._DUO_JS and ".wh-pol" in home._DUO_JS)

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
