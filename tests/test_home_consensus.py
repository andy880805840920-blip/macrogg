# 整體情勢的 bullet 版式渲染（原「共識句」測試——該句已隨 bullet 版式
# 移除：三則各自表述方向，開場句沒有位子；一致度由重點句與方向章承擔）
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.analysis import brief                     # noqa: E402
from src.pages import home                         # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("通過 " if cond else "失敗 "), name, ("— " + str(detail)[:90]) if detail else "")
    ok = ok and bool(cond)


# ① 共識句確定移除、不殘留
check("① 共識句已移除（brief 沒有 _direction）",
      not hasattr(brief, "_direction"))

# ② 行式文本 → 結構化拆解
_TXT = ("本次更新：物價 7 月，核心 CPI 月增 +0.2%。\n"
        "勞動市場：失業率落在充分就業區間，但已較低點回升。\n"
        "通膨：月步速仍高於 0.2% 的目標步速。\n"
        "聯準會：措辭偏鷹，重心在通膨。\n"
        "重點：目前的問題是升不升息。")
wn, bl, rest, tk = home._brief_pieces(_TXT)
check("② 本次更新／三則／重點句各就各位",
      wn.startswith("本次更新") and len(bl) == 3 and not rest
      and tk.startswith("目前的問題"),
      (wn[:12], [x[0] for x in bl], tk[:10]))
check("②b 三則的順序與標籤", [x[0] for x in bl] == ["勞動市場", "通膨", "聯準會"])

# ③ 渲染：ul 三個 li、模組名粗體、重點句獨立一行、來源標示
_html = home._brief_card({"_brief": {"text": _TXT, "chars": 100,
                                     "source": "generated", "model": "m"}})
check("③ 三個 li ＋粗體標籤", _html.count("<li>") == 3
      and "<b>勞動市場</b>" in _html)
check("③b 重點句獨立一行", 'class="brief-key"' in _html)
check("③c 來源標示：AI 生成要講出驗證", "方向經驗證" in _html)
_html2 = home._brief_card({"_brief": {"text": _TXT, "chars": 100,
                                      "source": "assembled", "model": ""}})
check("③d 組裝版標示規則組裝", "規則組裝" in _html2)

# ④ 沒有 bullet 前綴的舊格式文字仍能渲染（不會整卡消失）
_OLD = "就業與通膨的舊式連寫散文，一整段。\n重點：按兵不動。"
_h3 = home._brief_card({"_brief": {"text": _OLD, "chars": 30,
                                   "source": "assembled"}})
check("④ 無前綴行退回段落渲染", "brief-t" in _h3 and "<li>" not in _h3)

print()
print("全部通過" if ok else "有失敗")
sys.exit(0 if ok else 1)
