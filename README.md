# 美國總經儀表板

每次數據出爐後自動完成歸因、修正追蹤與交叉檢查，把就業、通膨與聯準會措辭
合成一個政策情境，產出一整個可直接截圖使用的靜態網站。
寫給投資人看：每個區塊只留「**數字 ＋ 一句對利率的意思**」，結論一律翻譯成
「利升息／利降息」；方法論與名詞解釋下沉到收合區，存在但不擋路。

| 模組 | 回答的問題 | 資料來源 |
|---|---|---|
| 勞動市場 | 就業在增還是減？失業率為什麼變？前月數字被改了多少？ | BLS CES／CPS、DOL、JOLTS |
| 通膨 | 漲價是誰造成的？住房落後多少？離 2% 目標多遠？ | BLS CPI、BEA PCE、Cleveland／Atlanta Fed |
| 聯準會文本 | 聲明改了哪些字？措辭往鷹還是鴿？重心在通膨還是就業？ | federalreserve.gov 會後聲明 |
| 長端與債務 | 30 年期為什麼在這裡？政府與科技巨頭的發債壓力多大？ | FRED ＋ SEC EDGAR（XBRL 自動擷取） |
| 情境合成 | 就業 × 通膨落在九宮格哪一格？距離下一格多遠？ | 上述四者 |

前三個模組解釋**政策利率往哪走**；長端模組解釋**曲線的形狀**。兩者由不同
力量驅動，所以情境頁刻意分開列、不合成單一分數——合成會讓「降息但長端
不降」這種最關鍵的組合消失。首頁另有「今日市場焦點」窄條：即時殖利率
（Yahoo，FRED 備援）、升息機率（聯邦基金期貨自算，FedWatch 同款算法）、
AI 摘要自新聞內文的焦點段（數字鎖定防編造）。

---

## 快速開始

```bash
pip install -r requirements.txt

python run.py --offline              # 先看畫面長相（不連網，用示範資料）

export FRED_API_KEY=你的key          # https://fredaccount.stlouisfed.org/apikeys
python run.py                        # 正式執行；加 --json 另輸出 latest.json
```

輸出是 `output/` 底下的一整個靜態網站。本機預覽用
`python -m http.server -d output`（分頁連結是絕對路徑，直接開檔案會斷）。

正式環境不用自己跑：**GitHub Actions 平日一天三次、週末一次**抓資料產頁面
並 commit，Netlify 純託管 `output/`（不執行 build）。上線步驟見
[GITHUB_DEPLOY.md](GITHUB_DEPLOY.md)。

---

## 架構

```
config/*.yaml ─┐
FRED／BLS／DOL ├→ src/fred.py 等擷取層 → src/analysis/（規則引擎、歸因、
SEC EDGAR      │   逐序列容錯＋快照後備）    情境合成——全部確定性）
federalreserve ┘         ↓
               src/build.py（資料 → 畫面結構）
                         ↓
               src/pages/*（各分頁內容）＋ src/site.py（版面）→ output/
```

角色分工的鐵律：**量化與判定走確定性規則，模型只改寫措辭**。AI 潤稿層
（選配，設 `GEMINI_API_KEY` 即啟用）有數字鎖定、事實雜湊快取、失敗退回
組裝版三道防護欄，任何一道沒過就用規則組裝的版本，什麼都不會壞。

```
config/          指標、門檻、權重——日常調整只改這裡
run.py           主流程（CLI 與編排、快照後備）
src/
  fred.py  store.py  sec.py  fomc_source.py  bls.py    # 擷取與儲存
  build.py  site.py  charts.py  fmt.py  clock.py       # 組裝與版面
  pages/           home labor inflation fomc rates scenario
  analysis/        規則引擎、歸因、修正追蹤、九宮格、潤稿、焦點、freshness
tests/           純 stdlib，`python tests/xxx.py` 就能跑（40+ 檔）
tools/           版面／對比度／序列使用率／文字密度四支稽核
data/*.db        每次執行的快照（不進 git；Actions 用 cache 保留）
output/          產出的網站（進 git，Netlify 從這裡取檔）
```

**改完之後跑這些**（不需外部服務，幾秒鐘）：

```bash
python run.py --offline --json
for f in tests/test_*.py; do python "$f"; done
python tools/audit_prose.py && python tools/audit_layout.py
python -m pyflakes src/ run.py tools/ tests/
```

---

## 日常調整

**改門檻**：`config/indicators.yaml` 的 `regime_lights`。
**加減指標**：在對應 group 加一段，不必改程式；暫停用 `enabled: false`。
**加規則**：`src/analysis/rules.py` 寫函式加 `@rule` 裝飾器即自動納入。
**加新模組**：`config/` 加設定 → `analysis/` 寫分析 → `build.py` 加
`build_*_context()` → `pages/` 加產生器 → `site.NAV` 加一列。版面不用動。

需要人工維護的資料：

| 項目 | 檔案 | 頻率 |
|---|---|---|
| 投資級季度發行量 | `config/rates.yaml` | 一季（SIFMA） |
| 科技巨頭資本支出指引 | `config/rates.yaml` `capex_guidance` | 一季（法說會後） |
| CPI 相對重要性權重 | `config/inflation.yaml` | 每年一月（BLS） |
| 市場預期 | `config/consensus.yaml` | 每次數據公布前 |
| FedWatch 期貨合約 | `config/focus.yaml` `fedwatch_contract` | 一年（往後滾） |

---

## 設計原則（摘要）

完整論述（每一條為什麼、當初踩了什麼）在
[docs/design-notes.md](docs/design-notes.md)。這裡只列會影響你改程式的：

- **確定性優先**：判定與數字全部出自規則引擎，跑幾次都一樣、可回測。
  模型只出現在潤稿與新聞摘要，且被數字鎖定包住。
- **門檻錨在外部依據**：SEP 預測、CBO 自然失業率、Sahm 原論文——不自選
  數字，出處印在畫面上讓讀者驗證。
- **誠實標示**：速報值、推估值、沿用快照、AI 摘要 vs 標題、退回後備——
  每一種降級都在畫面上寫明，不裝作沒發生。
- **逐序列容錯＋快照後備**：單一序列失敗只記錄跳過；補抓不回來就沿用上次
  執行的本機快照（SQLite append-only，同時支撐修正追蹤）；「抓得到但停更」
  由 freshness 依頻率另外擋。
- **方法論下沉**：卡面只留結論，算式與定義進收合區；`audit_prose.py` 把
  「打開一張卡讀到的方法論字數」壓在 20% 以下。
- **收合標題必帶結論**（`data-sum`），由 `site._collapse_sections()` 機械
  轉換，不逐頁手包。
- **「本次更新」走 72 小時視窗＋允許清單**，期別逐句標在數字旁——
  7 月的數據 8 月才公布，不標會被讀成即時。
- **全站單一時鐘**（台北，固定 +8）：`tests/test_clock.py` 靜態掃描全庫，
  出現第二個 `datetime.now()` 直接失敗。
- **版面由稽核把關**：五個寬度量 DOM 溢出與觸控間距、WCAG AA 對比度、
  序列使用率——不靠肉眼回歸。

---

## 資料口徑的坑（摘要）

每一個都實際踩過，完整說明與修法在 [docs/pitfalls.md](docs/pitfalls.md)：

CPI 沒有 2% 目標（那是 PCE 的）；年增率用未季調、月增率用季調；
「動得最多」要先換成同一把尺；狀態檔一掉「本次更新」就謊報；
一個模組裡各數字不同天發布；快照存的是算完的數字、改程式會製造假變動；
九宮格不能只用 PCE 也不能直接塞 CPI（推估要換算口徑）；
鷹鴿標籤水準與變化要分開；已完成交易的金額不該每天變（匯率凍結）；
分項貢獻加總 ≠ 官方漲幅而那不是錯誤；「剔除住房」要用官方指數不能反推；
`CUSR0000SASLE` 不是「核心服務除住房」（要加權相減推導）；
從殘差回推權重是陷阱；年增率的除數要按日期找不能數十二列；
BLS 快速通道比 FRED 早幾小時（速報值另標）。

---

## 已知限制

- **市場預期是手填的**（`config/consensus.yaml`）。沒填時退回 AR(3) 外推，
  畫面標「時間序列模型推估（非市場預期）」。
- **綜合分數的權重是暫定值**，尚未由歷史迴歸校準。
- **擴散指數未納入**（FRED 覆蓋不完整，需改走 BLS API）。
- **離線示範資料分兩類**：聯準會聲明是真實原文；FRED 序列是生成的示範值。
  跑一次 `python run.py --save-fixtures`（需 FRED key）可讓離線預覽用真資料。

---

## 文件地圖

| 檔案 | 內容 |
|---|---|
| [GITHUB_DEPLOY.md](GITHUB_DEPLOY.md) | GitHub ＋ Netlify 上線步驟 |
| [DEPLOY.md](DEPLOY.md) | 部署細節與疑難排解 |
| [OPERATIONS.md](OPERATIONS.md) | 日常營運：排程、金鑰、監控、常見錯誤 |
| [MAINTENANCE_CHECKLIST.md](MAINTENANCE_CHECKLIST.md) | 週期性人工維護清單 |
| [docs/design-notes.md](docs/design-notes.md) | 設計決策的完整論述（含各模組重點設計、部署架構與時鐘） |
| [docs/pitfalls.md](docs/pitfalls.md) | 資料口徑與工程陷阱的完整紀錄 |
