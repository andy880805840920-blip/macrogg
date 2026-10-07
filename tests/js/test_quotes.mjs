// netlify/functions/quotes.mjs 的離線測試（node tests/js/test_quotes.mjs）
import { prevClose, yahoo, txf, collect, SPECS } from "../../netlify/functions/quotes.mjs";
let ok = true;
const check = (n, c, d = "") => { console.log((c ? "通過 " : "失敗 ") + n, c ? "" : JSON.stringify(d)); ok = ok && !!c; };
const DAY = 86400, OFF = -14400;
const t0 = 1791000000 - (1791000000 % DAY);          // 某天 00:00 UTC
const res = (cur, closes, rmtDay, extra = {}) => ({
  meta: { regularMarketPrice: cur, regularMarketTime: t0 + rmtDay * DAY + 15 * 3600, gmtoffset: OFF,
          chartPreviousClose: 1, ...extra },
  timestamp: closes.map((_, i) => t0 + (i - closes.length + 1) * DAY + 13.5 * 3600),
  indicators: { quote: [{ close: closes }] } });
// 盤中：最後一根是今天 → 昨收＝倒數第二根（不是 chartPreviousClose）
check("① 盤中昨收＝倒數第二根", prevClose(res(4.30, [4.1, 4.2, 4.25, 4.30], 0)) === 4.25);
// 今天還沒有日線（最後一根是昨天、收盤≠現價）→ 昨收＝最後一根
check("①b 今天尚無日線 → 最後一根", prevClose(res(4.31, [4.1, 4.2, 4.25], 1)) === 4.25);
// 期貨夜盤：日期對不上但最後一根收盤＝現價 → 那根就是今天
check("①c 收盤等於現價視為當日這根", prevClose(res(4.25, [4.1, 4.2, 4.25], 1)) === 4.2);
check("①d 沒有日線 → previousClose", prevClose({ meta: { regularMarketPrice: 5, regularMarketTime: 1, previousClose: 4.9, chartPreviousClose: 1 } }) === 4.9);

const fake = (map) => async (url, opt) => {
  const hit = Object.entries(map).find(([k]) => url.includes(encodeURIComponent(k)) || url.includes(k));
  if (!hit) return { ok: false };
  const body = typeof hit[1] === "function" ? hit[1](opt) : hit[1];
  return { ok: true, json: async () => body };
};
const ch = (r) => ({ chart: { result: [r] } });
let q = await yahoo("live_dgs10", SPECS.live_dgs10, fake({ "^TNX": ch(res(42.8, [42.0, 42.6, 42.8], 0)) }));
check("② ×10 慣例換算", q && Math.abs(q.v - 4.28) < 1e-9 && Math.abs(q.p - 4.26) < 1e-9 && q.k === "pct", q);
q = await yahoo("vix", SPECS.vix, fake({ "^VIX": ch(res(200, [190, 200], 0)) }));
check("②b 超出範圍不回", q === null);
q = await yahoo("wti", SPECS.wti, fake({ "CL=F": ch(res(91.3, [90.1, 91.3], 0)) }));
check("②c 油價帶單位", q && q.u === " 美元" && q.p === 90.1, q);
q = await yahoo("dji", SPECS.dji, async () => { throw new Error("timeout"); });
check("②d 例外 → null", q === null);

// 照真實回應的樣子：第一筆是現貨列（TXF-S／TXF-P）；夜盤 CDate＝開盤那天
const tx = (sp, fu, d, t, last, ref) => ({ RtData: { QuoteList: [
  { SymbolID: sp, CDate: d, CTime: t, CLastPrice: "23,999", CRefPrice: "23,900" },
  { SymbolID: fu, CDate: d, CTime: t, CLastPrice: last, CRefPrice: ref }] } });
q = await txf(async (url, opt) => ({ ok: true, json: async () =>
  JSON.parse(opt.body).MarketType === "0"
    ? tx("TXF-S", "TXFK6-F", "20261002", "134500", "23,100", "23,000")
    : tx("TXF-P", "TXFK6-M", "20261002", "045959", "23,250", "23,100") }));
check("③ 台指期取較新的夜盤（CDate 10/02 04:59 → 實際 10/03）",
      q && q.s === "夜盤" && q.v === 23250 && q.p === 23100 && q.d === "2026-10-03", q);
check("③b 台北時間換 UTC", q && new Date(q.ts * 1000).toISOString() === "2026-10-02T20:59:59.000Z", q && q.ts);
q = await txf(async (url, opt) => ({ ok: true, json: async () =>
  JSON.parse(opt.body).MarketType === "0"
    ? tx("TXF-S", "TXFK6-F", "20261005", "100000", "23,400", "23,250")
    : tx("TXF-P", "TXFK6-M", "20261002", "045959", "23,250", "23,100") }));
check("③c 日盤進行中取日盤、而且是期貨不是現貨列", q && q.s === "日盤" && q.v === 23400, q);

// 2Y 改用 FRED；即使 Yahoo 的 2YY=F 有較新資料，也不能回傳覆蓋它。
const requests = [];
const yields = fake({ "2YY=F": ch(res(4.99, [4.90, 4.99], 1)),
                      "^TNX": ch(res(4.28, [4.2, 4.26, 4.28], 0)) });
const all = await collect(async (url, opt) => { requests.push(url); return yields(url, opt); });
check("④a 不抓 2 年期期貨、不回傳 dgs2", !requests.some(u => u.includes("2YY")) && !("dgs2" in all));
check("④ collect 只回抓得到的", Object.keys(all).join() === "live_dgs10", Object.keys(all));
check("④b 官方日利率完全不在盤中 API", ["dgs2", "dgs3mo", "dgs5", "dgs10", "dgs30"].every(k => !(k in SPECS) && !(k in all)));

q = await yahoo("twd", SPECS.twd, fake({ "TWD=X": ch(res(32.015, [32.005, 32.015], 0)) }));
check("⑤ 台幣保留三位小數與匯率口徑", q && q.k === "fx" && q.dp === 3 && q.u === " 元" && q.s === "Yahoo" && q.v === 32.015 && q.p === 32.005, q);
q = await yahoo("gold", SPECS.gold, fake({ "GC=F": ch(res(4051.25, [4000, 4051.25], 0)) }));
check("⑤b 黃金是期貨且保留小數", SPECS.gold.sym === "GC=F" && q && q.dp === 2 && q.u === " 美元／盎司" && q.v === 4051.25, q);
q = await yahoo("dxy", SPECS.dxy, fake({ "DX-Y.NYB": ch(res(101.23, [101.01, 101.23], 0)) }));
check("⑤c DXY 使用美元指數、保留兩位小數", q && q.dp === 2 && q.v === 101.23 && q.p === 101.01, q);
console.log(ok ? "\n全部通過" : "\n有失敗");
process.exit(ok ? 0 : 1);
