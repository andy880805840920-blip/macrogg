/* 偷懶頁的問句判讀（不經 AI，純規則）。
 * 頁面與測試共用這一份：頁面把它內嵌；tests/test_ask.py 用 node 跑同一份。
 * 規則（config/ask.yaml 的 rules 段可調權重）：
 *   1. 正規化：全形轉半形、小寫、去空白、簡轉繁、同義詞換成標準詞
 *   2. 主體：所有卡片關鍵詞「最長優先」比對，比到的字段消耗掉（核心PCE 不會再比到 PCE）
 *   3. 意圖：定義／數值／原因／變化／影響／時間／比較／名單；都沒有＝數值（隱含）
 *   4. 計分：強詞 +3、弱詞 +1、修飾詞 +2（卡片有修飾詞但問句沒有 −2）、
 *            意圖相符 +2（隱含數值 +1）、與範例問句相似 +2
 *   5. 決定：最高分 ≥4 且領先第二名 ≥2 → 直接回答；否則「我猜你想問？」
 *            沒有命中 → 用字面相似度猜；問到網站沒有的東西 → 「網站目前沒有這項資料」
 */
(function (root) {
  "use strict";
  var FW = /[！-～]/g;
  function half(s) { return s.replace(FW, function (c) { return String.fromCharCode(c.charCodeAt(0) - 0xfee0); }).replace(/　/g, " "); }

  function Matcher(ix) {
    var self = this;
    self.ix = ix;
    var s2t = {};
    var a = ix.s2t || "";
    for (var i = 0; i + 1 < a.length; i += 2) s2t[a[i]] = a[i + 1];
    self.s2t = s2t;
    // 同義詞：長的先換
    // 同義詞：長的先換；標準詞本身也列進去（原樣保留），避免「升降息機率」裡的「降息機率」又被換一次
    var pairs = (ix.syn || []).map(function (p) { return [self.base(p[0]), self.base(p[1])]; })
      .filter(function (p) { return p[0] && p[0] !== p[1]; });
    var seen = {};
    pairs.forEach(function (p) { seen[p[0]] = 1; });
    pairs.slice().forEach(function (p) { if (!seen[p[1]]) { seen[p[1]] = 1; pairs.push([p[1], p[1]]); } });
    self.syn = pairs.sort(function (x, y) { return y[0].length - x[0].length; });
    self.norm = function (q) {
      var s = self.base(q);
      // 一次掃描：同一個位置只換一次，換完的字不再參與比對（避免「10年」→「10年期」→「10年期期」）
      var out = "", i = 0;
      while (i < s.length) {
        var hit = null;
        for (var k = 0; k < self.syn.length; k++) {
          var f = self.syn[k][0];
          if (s.substr(i, f.length) === f) { hit = self.syn[k]; break; }
        }
        if (hit) { out += hit[1]; i += hit[0].length; } else { out += s[i]; i++; }
      }
      return out;
    };
    // 卡片
    self.cards = ix.cards.map(function (c) {
      return {
        id: c.i, q: c.q, cat: c.c,
        k: (c.k || []).map(self.norm), w: (c.w || []).map(self.norm), m: (c.m || []).map(self.norm),
        p: (c.p || []).map(self.norm),
        n: c.n || [], x: [c.q].concat(c.x || []).map(self.norm), t: !!c.t, r: c.r || []
      };
    });
    // 主體詞庫：強詞與弱詞一起，長的先比
    var lex = {};
    self.cards.forEach(function (c) {
      c.k.forEach(function (k) { if (k) lex[k] = Math.max(lex[k] || 0, 3); });
      c.w.concat(c.p).forEach(function (k) { if (k) lex[k] = Math.max(lex[k] || 0, 1); });
    });
    self.lex = Object.keys(lex).sort(function (x, y) { return y.length - x.length; });
    self.ints = {};
    Object.keys(ix.ints || {}).forEach(function (k) { self.ints[k] = ix.ints[k].map(self.norm); });
    self.per = {};
    Object.keys(ix.per || {}).forEach(function (k) { self.per[k] = ix.per[k].map(self.norm); });
    self.oos = (ix.oos || []).map(self.norm);
    self.R = Object.assign({ strong: 3, weak: 1, mod: 2, modMiss: -2, intent: 2, implicit: 1, ex: 2, exSim: 0.6,
                             direct: 4, lead: 2, guessN: 5, fuzzy: 0.25, termMiss: -2,
                             primary: 3, termDef: 1, fuzzyDirect: 0.75 }, ix.rules || {});
  }
  Matcher.prototype.base = function (q) {
    var s = half(String(q || "")).toLowerCase().replace(/\s+/g, "");
    var t = this.s2t, o = "";
    for (var i = 0; i < s.length; i++) o += t[s[i]] || s[i];
    return o.replace(/[?？!！。，,、．.~～「」『』"'：:；;（）()／/]/g, "");
  };
  function bigrams(s) { var b = {}; for (var i = 0; i + 1 < s.length; i++) b[s.substr(i, 2)] = 1; if (s.length === 1) b[s] = 1; return b; }
  function sim(a, b) {
    var A = bigrams(a), B = bigrams(b), n = 0, na = 0, nb = 0, k;
    for (k in A) { na++; if (B[k]) n++; }
    for (k in B) nb++;
    return na + nb ? 2 * n / (na + nb) : 0;
  }
  Matcher.prototype.parse = function (q) {
    var s = this.norm(q), rest = s, ents = [];
    for (var i = 0; i < this.lex.length; i++) {
      var k = this.lex[i];
      if (k.length && rest.indexOf(k) >= 0) { ents.push(k); rest = rest.split(k).join("\u0000"); }
    }
    // 意圖只看「主體以外」的字：「利差多少」不會被當成比較（差多少），「什麼在漲」不會被當成定義
    var ints = [];
    var self = this;
    Object.keys(this.ints).forEach(function (n) {
      if (self.ints[n].some(function (p) { return p && rest.indexOf(p) >= 0; })) ints.push(n);
    });
    var per = "";
    Object.keys(this.per).forEach(function (p) {
      if (!per && self.per[p].some(function (w) { return w && s.indexOf(w) >= 0; })) per = p;
    });
    var oos = this.oos.filter(function (o) { return o && s.indexOf(o) >= 0; });
    return { s: s, ents: ents, ints: ints, per: per, oos: oos };
  };
  Matcher.prototype.score = function (c, p) {
    var R = this.R, sc = 0, hits = [];
    p.ents.forEach(function (e) {
      if (c.k.indexOf(e) >= 0) { sc += R.strong; hits.push(e); }
      else if (c.w.indexOf(e) >= 0 || c.p.indexOf(e) >= 0) { sc += R.weak; hits.push(e); }
    });
    if (!hits.length) return { sc: 0, hits: hits };
    // 只問一個籠統的詞（「通膨」「就業」「油價」）時，交給指定的那張卡
    if (p.ents.length === 1 && c.p.indexOf(p.ents[0]) >= 0) sc += R.primary;
    if (c.m.length) {
      if (c.m.some(function (m) { return p.s.indexOf(m) >= 0; })) sc += R.mod; else sc += R.modMiss;
    }
    // 問「為什麼」時，原因蓋過其他意圖（「CPI 為什麼漲」要的是原因，不是漲多少）
    var ints = p.ints.indexOf("原因") >= 0 ? ["原因"] : p.ints;
    if (ints.length) {
      if (ints.some(function (n) { return c.n.indexOf(n) >= 0; })) sc += R.intent;
    } else if (c.n.indexOf("數值") >= 0) sc += R.implicit;
    // 名詞卡只回答「什麼是／怎麼看」；沒問定義時讓位給資料卡
    if (c.t && p.ints.indexOf("定義") < 0) sc += R.termMiss;
    if (c.t && p.ints.indexOf("定義") >= 0) sc += R.termDef;
    var best = 0;
    c.x.forEach(function (x) { var v = sim(p.s, x); if (v > best) best = v; });
    if (best >= R.exSim && !(c.t && p.ints.indexOf("定義") < 0)) sc += R.ex;
    return { sc: sc, hits: hits, sim: best };
  };
  /* 回傳 {mode:'direct'|'guess'|'none'|'oos', card, list:[{id,q,cat,sc}], parse} */
  Matcher.prototype.ask = function (q) {
    var p = this.parse(q), self = this, R = this.R;
    if (!p.s) return { mode: "empty", list: [], parse: p };
    var rows = this.cards.map(function (c) { var r = self.score(c, p); r.c = c; return r; })
      .filter(function (r) { return r.sc > 0; })
      .sort(function (a, b) { return b.sc - a.sc || (b.sim || 0) - (a.sim || 0); });
    var strongEnts = p.ents.filter(function (e) { return self.cards.some(function (c) { return !c.t && c.k.indexOf(e) >= 0; }); });
    var out = function (mode, list, card) {
      return { mode: mode, card: card || null, parse: p,
               list: list.slice(0, R.guessN).map(function (r) { return { id: r.c.id, q: r.c.q, cat: r.c.cat, sc: r.sc }; }) };
    };
    if (p.oos.length) {
      var near = this.fuzzy(p.s).filter(function (r) { return r.sim >= R.fuzzy; });
      var hasN = {}; near.forEach(function (r) { hasN[r.c.id] = 1; });
      (self.ix.oosNear || []).forEach(function (id) {
        var c = self.cards.filter(function (x) { return x.id === id; })[0];
        if (c && !hasN[id] && near.length < 3) near.push({ c: c, sc: 0, sim: 0 });
      });
      return out("oos", near);
    }
    if (!rows.length) {
      var fz = this.fuzzy(p.s).filter(function (r) { return r.sim >= R.fuzzy; });
      // 幾乎就是某張卡的範例問句 → 直接回答
      if (fz.length && fz[0].sim >= R.fuzzyDirect && (!fz[1] || fz[0].sim - fz[1].sim >= 0.1)) return out("direct", fz, fz[0].c.id);
      return fz.length ? out("guess", fz) : out("none", []);
    }
    var top = rows[0], second = rows[1];
    // 兩個不同主體、各自屬於不同卡片 → 不替使用者選（問定義且最高分是名詞卡時例外）
    var defTerm = top.c.t && p.ints.indexOf("定義") >= 0;
    var uncovered = defTerm ? [] : strongEnts.filter(function (e) { return top.c.k.indexOf(e) < 0 && top.c.w.indexOf(e) < 0 && top.c.p.indexOf(e) < 0; });
    if (uncovered.length) {
      var others = rows.filter(function (r) { return r.hits.some(function (h) { return uncovered.indexOf(h) >= 0; }); });
      var merged = [top].concat(others.filter(function (r) { return r !== top; }));
      rows.forEach(function (r) { if (merged.indexOf(r) < 0) merged.push(r); });
      return out("guess", merged);
    }
    if (top.sc >= R.direct && (!second || top.sc - second.sc >= R.lead)) return out("direct", rows, top.c.id);
    // 問句裡的主體全被最高分那張卡涵蓋、第二名沒有 → 也算直接命中
    if (top.sc >= R.direct && second && top.sc > second.sc && top.hits.length === p.ents.length &&
        second.hits.length < p.ents.length) return out("direct", rows, top.c.id);
    // 猜的清單太短：用字面相似補到三題
    if (rows.length < 3) {
      var have = {}; rows.forEach(function (r) { have[r.c.id] = 1; });
      this.fuzzy(p.s).forEach(function (r) { if (rows.length < 3 && !have[r.c.id] && r.sim >= R.fuzzy) rows.push(r); });
    }
    return out("guess", rows);
  };
  Matcher.prototype.fuzzy = function (s) {
    return this.cards.map(function (c) {
      var best = 0;
      c.x.forEach(function (x) { var v = sim(s, x); if (v > best) best = v; });
      return { c: c, sc: 0, sim: best };
    }).sort(function (a, b) { return b.sim - a.sim; }).slice(0, 8);
  };
  root.AskMatch = Matcher;
  if (typeof module !== "undefined" && module.exports) module.exports = Matcher;
})(typeof window !== "undefined" ? window : globalThis);
