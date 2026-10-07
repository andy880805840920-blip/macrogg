// 首頁焦點條的「盤中報價」中繼站：瀏覽器每 60 秒問一次 /api/quotes，
// 這支函式代為向 Yahoo（美債殖利率、油價、VIX、MOVE、道瓊、費半）與
// 期交所（台指期）取價，回傳已檢查過的數字。
//
// 為什麼要中繼：瀏覽器不能直接打 Yahoo／期交所（CORS 擋），而且代號、
// 合理範圍、×10 慣例這些規則只該寫在一個地方——這裡跟 Python 端
// （src/analysis/focus_today.py 的 QUOTE_SPECS／fetch_yahoo_yield／fetch_txf）
// 是同一套，改一邊要改另一邊。
//
// 成本控制：回應掛 Netlify CDN 的 durable 快取 60 秒——不論多少人同時開著
// 首頁，這支函式每分鐘最多實際執行一次。
//
// 失敗一律安靜：抓不到的代號直接不回，頁面保留建置時的數字。

const YQ = (s) =>
  `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(s)}?range=5d&interval=1d`;
const TXF_URL = "https://mis.taifex.com.tw/futures/api/getQuoteList";
const UA = { "User-Agent": "Mozilla/5.0 (macro-dashboard)" };
const TIMEOUT_MS = 4000;

// chip id → 代號與規則。k：pct＝殖利率（%）、lvl＝一般價位、idx＝指數（整數＋漲跌幅）
export const SPECS = {
  // Official daily chips are immutable here; intraday quotes have separate IDs.
  live_dgs10: { sym: "^TNX", k: "pct" },
  live_dgs30: { sym: "^TYX", k: "pct" },
  wti: { sym: "CL=F", k: "lvl", lo: 10, hi: 300, u: " 美元" },
  brent: { sym: "BZ=F", k: "lvl", lo: 10, hi: 300, u: " 美元" },
  vix: { sym: "^VIX", k: "lvl", lo: 5, hi: 100, u: "" },
  move: { sym: "^MOVE", k: "lvl", lo: 30, hi: 300, u: "" },
  dji: { sym: "^DJI", k: "idx", lo: 10000, hi: 100000 },
  sox: { sym: "^SOX", k: "idx", lo: 500, hi: 30000 },
};
const TXF_RANGE = [5000, 80000];

const num = (x) => {
  const v = typeof x === "number" ? x : parseFloat(String(x ?? "").replace(/,/g, ""));
  return Number.isFinite(v) && v !== 0 ? v : null;
};

// 前一交易日收盤：從日線自己找，不信 chartPreviousClose（那是「圖表區間
// 開始前」的收盤——range=5d 時可能是五天前）。最後一根若就是今天這根
// （同一天，或收盤價等於目前價），昨收是倒數第二根；否則是最後一根。
export function prevClose(res) {
  const m = res.meta || {};
  const ts = res.timestamp || [];
  const cl = ((res.indicators || {}).quote || [{}])[0]?.close || [];
  const bars = ts.map((t, i) => [t, cl[i]]).filter(([t, c]) => t != null && c != null);
  const cur = m.regularMarketPrice;
  if (bars.length && m.regularMarketTime != null && cur != null) {
    const off = Number(m.gmtoffset || 0);
    const day = (t) => Math.floor((Number(t) + off) / 86400);
    const last = bars[bars.length - 1];
    const isCur = day(last[0]) === day(m.regularMarketTime) ||
      Math.abs(last[1] - cur) <= 1e-9 * Math.max(1, Math.abs(cur));
    if (!isCur) return Number(last[1]);
    if (bars.length >= 2) return Number(bars[bars.length - 2][1]);
  }
  for (const k of ["previousClose", "chartPreviousClose"]) {
    if (m[k] != null) return Number(m[k]);
  }
  return null;
}

const utcDate = (sec) => new Date(sec * 1000).toISOString().slice(0, 10);

export async function yahoo(id, spec, f = fetch) {
  try {
    const r = await f(YQ(spec.sym), { headers: UA, signal: AbortSignal.timeout(TIMEOUT_MS) });
    if (!r.ok) return null;
    const res = ((await r.json()).chart || {}).result?.[0];
    if (!res) return null;
    const m = res.meta || {};
    let v = num(m.regularMarketPrice);
    let p = prevClose(res);
    const ts = Number(m.regularMarketTime);
    if (v == null || p == null || !ts) return null;
    if (spec.k === "pct") {
      if (v > 20) { v /= 10; p /= 10; }          // CBOE ×10 慣例
      if (!(v >= 0.1 && v <= 15 && p >= 0.1 && p <= 15)) return null;
    } else if (!(v >= spec.lo && v <= spec.hi && p >= spec.lo && p <= spec.hi)) {
      return null;
    }
    const out = { v, p, ts, d: utcDate(ts), k: spec.k };
    if (spec.u !== undefined) out.u = spec.u;
    return out;
  } catch {
    return null;
  }
}

// 台指期：日盤（MarketType 0）與夜盤（1）各問一次，取時間較新的那一盤。
// 期交所行情頁背後的端點，非官方 API——改版就安靜失敗。
// 兩個坑（跟 Python 端 fetch_txf 同一套修法）：
//   ① 清單第一筆是「臺指現貨」（TXF-S／TXF-P）——只認期貨代號（TXFJ6-F）
//   ② 夜盤的 CDate 是開盤那天；時間早於 15:00 的是隔天凌晨，要加一天
const TXF_FUT = /^TXF[A-Z]\d-[A-Z]$/;
export async function txf(f = fetch) {
  let best = null;
  for (const [mkt, s] of [["0", "日盤"], ["1", "夜盤"]]) {
    try {
      const r = await f(TXF_URL, {
        method: "POST",
        headers: { ...UA, "Content-Type": "application/json",
                   Referer: "https://mis.taifex.com.tw/futures/" },
        body: JSON.stringify({ MarketType: mkt, SymbolType: "F", KindID: "1", CID: "TXF",
                               ExpireMonth: "", RowSize: "全部", PageNo: "",
                               SortColumn: "", AscDesc: "A" }),
        signal: AbortSignal.timeout(TIMEOUT_MS),
      });
      if (!r.ok) continue;
      const rows = ((await r.json()).RtData || {}).QuoteList || [];
      const row = rows.find((x) => TXF_FUT.test(String(x.SymbolID || "")));   // 近月
      if (!row) continue;
      const v = num(row.CLastPrice), p = num(row.CRefPrice);
      if (!v || !p || v < TXF_RANGE[0] || v > TXF_RANGE[1]) continue;
      const d = String(row.CDate || ""), t = String(row.CTime || "").padStart(6, "0");
      if (!/^\d{8}$/.test(d) || !/^\d{6}$/.test(t)) continue;
      const night = mkt === "1" && t < "150000";
      // CDate／CTime 是台北時間（UTC+8）
      const ts = Date.UTC(+d.slice(0, 4), +d.slice(4, 6) - 1, +d.slice(6, 8) + (night ? 1 : 0),
                          +t.slice(0, 2) - 8, +t.slice(2, 4), +t.slice(4, 6)) / 1000;
      const day = new Date((ts + 8 * 3600) * 1000).toISOString().slice(0, 10);
      const cand = { v, p, ts, s, d: day, k: "idx" };
      if (!best || cand.ts > best.ts) best = cand;
    } catch { /* 下一盤 */ }
  }
  return best;
}

export async function collect(f = fetch) {
  const ids = Object.keys(SPECS);
  const got = await Promise.all([...ids.map((id) => yahoo(id, SPECS[id], f)), txf(f)]);
  const q = {};
  ids.forEach((id, i) => { if (got[i]) q[id] = got[i]; });
  if (got[ids.length]) q.txf = got[ids.length];
  return q;
}

export default async () => {
  const q = await collect();
  const n = Object.keys(q).length;
  return new Response(JSON.stringify({ t: Math.floor(Date.now() / 1000), q }), {
    status: n ? 200 : 502,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      // 瀏覽器每次都回來問；CDN 端共用 60 秒（全部失敗時只留 20 秒，早點重試）
      "Cache-Control": "public, max-age=0, must-revalidate",
      "Netlify-CDN-Cache-Control":
        n ? "public, durable, s-maxage=60, stale-while-revalidate=60"
          : "public, durable, s-maxage=20",
      "X-Robots-Tag": "noindex",
    },
  });
};

export const config = { path: "/api/quotes" };
