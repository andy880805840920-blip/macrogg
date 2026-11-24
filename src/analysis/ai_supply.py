"""
AI 大事「AI 供需」（2026-11；設定：config/ai_supply.yaml，人工維護、財報季更新）。

計算邏輯參考 Threads 上的 AI 供需分析文章（只用算法，數字全部來自公開財報與報導）：
  供給   晶片廠 AI 營收 ÷ 每 GW 晶片金額 → 出貨的 GW
  成本   每 GW 每年需要賺＝伺服器折舊＋機房折舊＋電費＋資金成本
  利用率 實驗室 ARR ÷（已出貨滿 9 個月、近 6 年內的 GW × 每 GW 每年需賺）
  追趕   每月新增 ARR vs 近 4 季出貨 GW × 每 GW 每年需賺 ÷ 12
只做計算、不連網。
"""
from __future__ import annotations

import datetime as dt


def _d(s) -> dt.date:
    return dt.date.fromisoformat(str(s)[:10])


def _months_back(d: dt.date, m: int) -> dt.date:
    y, mo = divmod(d.year * 12 + d.month - 1 - m, 12)
    return dt.date(y, mo + 1, min(d.day, 28))


def per_gw_cost(c: dict) -> dict:
    """每 GW 每年需要賺多少（億美元），分項。"""
    b = float(c.get("build", 550))
    server = b * c.get("server_share", 0.7) / c.get("server_life", 5.6)
    shell = b * (1 - c.get("server_share", 0.7)) / c.get("shell_life", 20)
    power = c.get("power_cents", 9.64) / 100 * c.get("hours", 8760) * 1e6 / 1e8   # 1 GW＝1e6 kW；美元→億
    capital = b * c.get("rate", 0.055) * c.get("debt_share", 0.6)
    return {"server": server, "shell": shell, "power": power, "capital": capital,
            "total": server + shell + power + capital}


def build(cfg: dict | None) -> dict | None:
    if not cfg or not cfg.get("vendors") or not cfg.get("arr"):
        return None
    asof = _d(cfg.get("asof"))
    lag = _months_back(asof, int(cfg.get("lag_months", 9)))
    start = _months_back(asof, int(cfg.get("life_years", 6)) * 12)
    cost = per_gw_cost(cfg.get("cost") or {})
    vendors, fleet, gw4, rev_q = [], 0.0, 0.0, 0.0
    for v in cfg["vendors"]:
        rs = sorted(v.get("rev") or [], key=lambda r: str(r["end"]))
        qs = [r for r in rs if r.get("kind") != "y"]
        if not qs:
            continue
        pg = float(v["per_gw"])
        last = qs[-1]
        l4 = qs[-4:]
        f = sum(r["v"] for r in rs if start < _d(r["end"]) <= lag) / pg
        fleet += f
        gw4 += sum(r["v"] for r in l4) / pg
        rev_q += last["v"]
        vendors.append({"name": v["name"], "seg": v.get("seg", ""), "star": bool(v.get("star")),
                        "per_gw": pg, "per_gw_src": v.get("per_gw_src", ""),
                        "last": {"label": last.get("label", ""), "end": str(last["end"]), "v": last["v"],
                                 "est": bool(last.get("est")), "gw": last["v"] / pg},
                        "l4": sum(r["v"] for r in l4), "l4_est": any(r.get("est") for r in l4), "fleet": f})
    labs, net = [], 0.0
    for a in cfg["arr"]:
        ps = sorted(a.get("pts") or [], key=lambda p: str(p["date"]))
        if not ps:
            continue
        cur = ps[-1]
        mo = None
        if len(ps) >= 2:
            days = (_d(cur["date"]) - _d(ps[-2]["date"])).days
            if days > 0:
                mo = (cur["v"] - ps[-2]["v"]) / (days / 30.44)
                net += mo
        labs.append({"name": a["name"], "v": cur["v"], "date": str(cur["date"]), "src": cur.get("src", ""),
                     "prev": ps[-2] if len(ps) >= 2 else None, "per_month": mo})
    if not vendors or not labs or fleet <= 0:
        return None
    demand = sum(x["v"] for x in labs)
    need = fleet * cost["total"]
    util = demand / need * 100
    needed_mo = gw4 * cost["total"] / 12
    if util >= 100 and net >= needed_mo:
        verdict, tone = "需求跟得上算力", "ok"
    elif util >= 95:
        verdict, tone = "大致打平：新增需求略低於新增算力", "mid"
    else:
        verdict, tone = "需求還追不上算力", "bad"
    return {"asof": asof.isoformat(), "lag": lag.isoformat(), "start": start.isoformat(),
            "vendors": vendors, "rev_q": rev_q, "gw4": gw4, "fleet": fleet, "cost": cost, "need": need,
            "labs": labs, "demand": demand, "util": util, "net_mo": net, "needed_mo": needed_mo,
            "verdict": verdict, "tone": tone, "c": cfg.get("cost") or {}}
