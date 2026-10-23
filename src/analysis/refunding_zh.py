"""
每季再融資聲明的中文摘要（2026-10）。

以前 config/rates.yaml 的 refunding.guidance_zh 要每季手寫；財政部發新聲明後，
build.py 會自動改用聲明原文，但中文只靠 longend.refunding_guidance_zh 的固定句型翻，
句型一變就只能顯示「請以原文為準」。這裡改成讓模型讀聲明本文、寫一段中文摘要。

防護欄（任何一道沒過 → 回 ""，頁面沿用原文／句型版）
------------------------------------------------------
① 只寫聲明裡有的事：coupon／FRN 規模指引、T-Bills、其他新措施；
   買回額度另有一行（refunding_buybacks_zh），這裡不重複。
② 數字鎖定：摘要裡每個數字都必須能在原文找到（允許「十億→億」的 ×10 換算、
   年份與 1–30 的小整數如天期），一個新數字都不准有。
③ 長度與文字檢查：40–260 字、要有中文、不能有英文長句。
④ 一季只產生一次：以聲明網址＋日期做快取（state/refunding_zh.json），
   之後每次執行直接沿用，不會每天重新呼叫、也不會每天措辭不同。

沒設 ANTHROPIC_API_KEY、離線模式、API 掛了——一律回 ""，什麼都不會壞。
模型可用環境變數 REFUNDING_MODEL 覆寫。
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "state" / "refunding_zh.json"
MODEL = "claude-sonnet-4-5"
TRIES = 3

SYSTEM = (
    "你是總經網站的編輯，讀者是台灣的一般投資人。使用者會貼上美國財政部「每季再融資聲明」"
    "（Quarterly Refunding Statement）的英文原文。請用繁體中文（台灣用語）寫 2–4 句、"
    "80–220 字的摘要，只講這份聲明本身寫了什麼：\n"
    "1. 名目 coupon 與 FRN（浮動利率票據）拍賣規模的指引（維持、增加或減少，以及期間）；\n"
    "2. T-Bills（短期國庫券）規模的安排；\n"
    "3. 其他新措施或值得注意的變動（例如新天期、拍賣時程調整）。\n"
    "規則：不要提買回（buyback）額度——頁面另有一行；不要推測、不要評論市場影響、"
    "不要加入原文沒有的數字；金額可寫「億美元」（原文的 billion＝十億）；"
    "保留 coupon、FRN、T-Bills、TIPS 等專有名詞；直接輸出摘要本文，不要標題、不要條列、不要引號。"
)


def _load(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:                              # noqa: BLE001
        return {}


def _save(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    except Exception as e:                         # noqa: BLE001
        log.warning("再融資摘要存檔失敗（%s）", e)


_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _nums(s: str) -> list[float]:
    out = []
    for m in _NUM.findall(s or ""):
        try:
            out.append(float(m.replace(",", "")))
        except ValueError:
            pass
    return out


def validate(zh: str, source: str) -> str:
    """通過回 ""；沒過回原因。"""
    zh = (zh or "").strip()
    n = len(zh)
    if not (40 <= n <= 260):
        return f"長度 {n} 字不在 40–260"
    if len(re.findall(r"[一-鿿]", zh)) < 25:
        return "中文太少"
    if re.search(r"[A-Za-z]+(?:\s+[A-Za-z]+){5,}", zh):
        return "夾帶英文長句"
    if re.search(r"^\s*[#\-*•]|^\s*\d+[.、]", zh, flags=re.M):
        return "用了標題或條列"
    src = set(_nums(source))
    ok = src | {v * 10 for v in src} | {v / 10 for v in src}
    for v in _nums(zh):
        if v in ok or (v == int(v) and (1 <= v <= 30 or 2000 <= v <= 2100)):
            continue
        return f"數字 {v:g} 原文找不到"
    return ""


def _default_post(key: str, model: str, text: str) -> str:
    from .polish import _post_anthropic
    return _post_anthropic(key, model, text, system=SYSTEM, temperature=0.2)


def summarize(statement: dict, offline: bool = False, cache_path: Path = CACHE,
              post=None, env: dict | None = None) -> str:
    """
    statement＝treasury_source.refunding_statement() 的結果（要有 date、url、text）。
    回傳中文摘要；做不出來回 ""。
    """
    st = statement or {}
    key_id = f'{st.get("url", "")}|{st.get("date", "")}'
    cache = _load(cache_path)
    if cache.get("id") == key_id and cache.get("zh"):
        return cache["zh"]
    text = (st.get("text") or "").strip()
    if offline or not st.get("date") or len(text) < 200:
        return ""
    env = os.environ if env is None else env
    key = (env.get("ANTHROPIC_API_KEY") or "").strip()
    if not key and post is None:
        log.info("再融資摘要：未設 ANTHROPIC_API_KEY，沿用原文")
        return ""
    model = (env.get("REFUNDING_MODEL") or MODEL).strip()
    post = post or _default_post
    for i in range(TRIES):
        try:
            zh = re.sub(r"\s+", " ", (post(key, model, text) or "")).strip().strip("「」\"'")
        except Exception as e:                     # noqa: BLE001
            log.warning("再融資摘要：模型呼叫失敗（%s）", e)
            return ""
        why = validate(zh, text)
        if not why:
            _save(cache_path, {"id": key_id, "date": st.get("date"), "url": st.get("url"),
                               "model": model, "zh": zh})
            log.info("再融資摘要：已產生（%s，%d 字）", st.get("date"), len(zh))
            return zh
        log.warning("再融資摘要第 %d 次沒過檢查（%s）", i + 1, why)
    return ""
