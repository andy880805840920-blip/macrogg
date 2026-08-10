# 美國總經儀表板

每次數據出爐後自動完成歸因、修正追蹤與交叉檢查，把就業、通膨與聯準會措辭
合成一個政策情境，產出一整個可直接截圖使用的靜態網站。

**五個模組**

| 模組 | 回答的問題 | 資料來源 |
|---|---|---|
| 勞動市場 | 就業在增還是減？失業率為什麼變？前月數字被改了多少？ | BLS CES／CPS、DOL、JOLTS |
| 通膨 | 漲價是誰造成的？住房落後多少？離 2% 目標多遠？ | BLS CPI、BEA PCE、Cleveland／Atlanta Fed |
| 聯準會文本 | 這次聲明改了哪些字？措辭往鷹還是往鴿走？ | federalreserve.gov 會後聲明 |
| 長端與債務 | 30 年期為什麼在這裡？政府與科技巨頭的發債壓力有多大？ | FRED（財政部、聯準會、BEA、ICE BofA）＋手動維護的財報數字 |
| 情境合成 | 就業 × 通膨落在九宮格哪一格？距離下一格多遠？ | 上述四者 |

前三個模組解釋的是**政策利率往哪走**；長端模組解釋的是**曲線的形狀**。
兩者由不同的力量驅動，所以情境頁刻意分開列，不合成單一分數——
合成會讓「降息但長端不降」這種最關鍵的組合消失。

結論一律翻譯成「利升息／利降息」，寫給投資人看，不用專有名詞。

---

## 快速開始

```bash
pip install -r requirements.txt

# 先看畫面長相（不連網，用示範資料）
python run.py --offline

# 正式執行
export FRED_API_KEY=你的key          # https://fredaccount.stlouisfed.org/apikeys
python run.py
```

輸出是 `output/` 底下的一整個靜態網站（首頁＋分頁＋存檔），每頁都是自足 HTML。
本機直接開 `output/index.html` 時分頁連結是絕對路徑，建議用 `python -m http.server -d output` 預覽。

加 `--json` 會同時輸出 `output/latest.json`，供 P2／P4 模組串接。

---

## 這一版做了什麼

| 模組 | 回答的問題 |
|---|---|
| **KPI 卡** | 非農、失業率、時薪、參與率的當期值與動能 |
| **修正追蹤** | 這次的數字有多少是被前兩月下修吃掉的？初值系統性偏誤有多大？ |
| **產業貢獻度分解** | 這次的增減是誰造成的？剔除醫療社福與政府後還剩多少？ |
| **失業率變動分解** | 失業率下降是因為找到工作，還是因為人退出勞動力？ |
| **Regime 紅綠燈** | 八個關鍵指標目前處在什麼狀態 |
| **自動判讀** | 確定性規則引擎的交叉檢查結果 |
| **綜合分數** | 各指標 z-score 加權合成，附逐項貢獻（可解釋） |

---

## 兩個容易誤解的地方

**① 修正有兩種口徑，不要混用**

- **相對上次發布** — BLS 新聞稿講的那個數字（2026 年 7 月報告是 −103K）
- **相對初值累計** — 完整修正史（同期為 −146K）

畫面上兩個都顯示，並各自標明口徑。長條圖裡的橘色是「初值（首次公布）」。

**② 失業率分解用的是家庭調查就業**

`u = 1 − E/L`，所以分解成：

```
Δu ≈ −ΔE/L  +  (E/L)·(ΔL/L)
      就業效果     勞動力效果
```

就業必須用 **CE16OV（家庭調查）**，不能用 PAYEMS（機構調查），否則分解無法閉合。

另外注意一個反直覺的地方：**勞動力萎縮會把失業率壓低，不是推高**。因為退出勞動力的人同時從分子（失業人數）與分母（勞動力）中消失，而分子減得更兇。這正是「壞的下降」的機制。

---

## 檔案結構

```
config/
  indicators.yaml          # 勞動指標與門檻 — 日常調整只需要改這裡
  inflation.yaml           # 通膨指標、CPI 權重與門檻
  fomc.yaml                # 聯準會設定；點陣圖需手動維護
  rates.yaml               # 殖利率、債務、hyperscaler 發債與門檻
  consensus.yaml           # 市場預期（意外值面板用）
netlify.toml               # Netlify 託管設定（不執行 build）
.github/workflows/         # 排程：抓資料 → 產頁面 → commit
run.py                     # 主流程（CLI 與編排）
src/
  fred.py                  # FRED / ALFRED 擷取（逐序列容錯）
  fomc_source.py           # federalreserve.gov 聲明擷取
  store.py                 # SQLite，保留每次執行的快照
  fmt.py                   # 數字格式化（統一用「萬人」）
  charts.py                # HTML 長條與 SVG 走勢圖（無外部相依）
  site.py                  # 版面、導覽列、CSS ← 加新分頁改這裡
  build.py                 # 資料 → 畫面用結構（每個模組一個函式）
  pages/                   # 各分頁的內容產生器
    home.py  labor.py  inflation.py  fomc.py  rates.py  scenario.py
  analysis/
    core.py                # 序列運算工具
    attribution.py         # 歸因引擎（勞動與通膨共用）
    revisions.py           # 修正追蹤
    regime.py              # 紅綠燈 + 綜合分數
    rules.py               # 勞動端規則引擎
    inflation.py           # 通膨分項分解與摘要
    rules_inflation.py     # 通膨端規則引擎
    fomc_text.py           # 紅線比對、詞頻、鷹鴿計分
    rates.py               # 曲線拆解、財政損益兩平、hyperscaler、供給壓力
    breakeven.py           # 損益兩平就業增速
    changes.py             # 與上次執行的快照比對
    surprise.py            # 意外值（實際 vs 市場預期）
    passthrough.py         # 薪資 → 服務業通膨的傳導
    scenario.py            # 九宮格情境合成
  fixtures*.py             # 離線示範資料
data/*.db                  # 執行後自動建立（不進 git）
output/                    # 產出的整個網站（要進 git，Netlify 從這裡取檔）
```

**加一個新模組**：在 `config/` 加設定檔 → `src/analysis/` 寫分析 →
`src/build.py` 加一個 `build_*_context()` → `src/pages/` 加頁面產生器 →
`src/site.NAV` 加一列。版面與 CSS 完全不用動。

---

## 日常調整

**改門檻**：編輯 `config/indicators.yaml` 的 `regime_lights` 段落。

**加／減指標**：在對應的 group 加一段即可，不必改程式。要暫時關掉某個指標，設 `enabled: false`（不必刪掉，日後要用再打開）。

**加規則**：在 `src/analysis/rules.py` 寫一個函式加上 `@rule` 裝飾器就會自動納入。回傳 `Flag(key, severity, headline, detail, lean)` 或 `None`。

```python
@rule
def r_my_check(ctx: RuleContext) -> Flag | None:
    if 某個條件:
        return Flag("my_key", "watch", "一句話結論", "支撐數字", "dovish")
    return None
```

---

## 設計原則

**量化與判定走確定性規則，不交給模型。** 規則引擎的輸出每次跑都完全一致，所以時間序列可比、可畫圖、可回測。模型的角色留到 P4，只負責讀規則結果寫敘述。

**修正追蹤要保留版本。** 每次執行都把當下抓到的完整序列寫進 `snapshots` 表（append-only）。就算 ALFRED 某天不可用，從第二次執行起也能靠本地快照比對出修正。

**逐序列容錯。** FRED 偶爾改 series id，或某個序列暫時抓不到。單一序列失敗只會記錄並跳過，畫面底部會列出失敗清單，不會讓整份報告產不出來。

---

## 網站結構

`python run.py` 會產生一整個靜態網站到 `output/`：

```
output/
  index.html                    首頁 — 情境結論 + 四個模組摘要卡
  labor/index.html              勞動市場
  inflation/index.html          通膨
  fomc/index.html               聯準會文本
  rates/index.html              長端與債務
  scenario/index.html           情境合成（九宮格 + 長端供給壓力）
  archive/index.html            存檔索引
  archive/labor-2026-07/        該期就業報告的完整快照
  archive/inflation-2026-07/    該期物價數據的完整快照
  robots.txt                    全站 noindex
```

版面、導覽列、CSS 都在 `src/site.py`。各模組只產生「內容」，
所以 P2／P3 掛上來時不必動到任何既有版面程式碼——
在 `site.NAV` 把該頁的 `done` 改成 `True`，再寫一個 body 產生器即可。

---

## 部署到 Netlify

架構是 **GitHub Actions 產生頁面 → commit → Netlify 純託管**。
Netlify 不執行任何 build，理由有三：API key 只留在 GitHub secrets、
不必在 Netlify 裝 Python 依賴、每次產出留在 git 歷史裡自動累積成 vintage 檔案庫。

**步驟**

1. 建一個 GitHub repo，把這個專案推上去（`output/` 要一起推，`.gitignore` 已設好）
2. repo → Settings → Secrets and variables → Actions → New secret
   名稱 `FRED_API_KEY`，值填你的 key
3. Netlify → Add new site → Import from GitHub → 選這個 repo
   - Build command：**留空**
   - Publish directory：`output`
4. 完成。之後 GitHub Actions 依排程跑，push 後 Netlify 自動部署

**排程**（`.github/workflows/update.yml`）：`45 13 * * *`，每天一次。

不對準個別發布日，理由是執行本身是冪等的——非發布日跑起來只是重新產生同一份
頁面，沒有副作用。一份日排程就涵蓋就業報告、失業金、JOLTS、CPI、PCE 與 FOMC，
不必維護發布日對照表。

13:45 UTC 在美東夏令是 09:45、冬令是 08:45，兩者都在 08:30 ET 發布之後，
**所以換季不必手動調整**。也可以在 Actions 頁面手動觸發（workflow_dispatch）。

用量約每次 2–3 分鐘、每月不到 100 分鐘，私有 repo 免費額度為 2,000 分鐘／月。

**搜尋引擎**：頁面帶 `noindex` meta，`netlify.toml` 另外送 `X-Robots-Tag` 標頭，
再加上 `robots.txt` 全站 disallow——三道都設了。但請注意這**不是存取控制**，
知道網址的人仍然看得到。日後若要真的擋，用 Cloudflare Access（免費 50 人）。

---

## 各模組的重點設計

**勞動**：修正追蹤分兩種口徑（相對上次發布＝BLS 新聞稿的數字；相對初值＝完整修正史）。
失業率分解用家庭調查就業（CE16OV），因為要跟失業率同一份調查才閉合。
行業長條只顯示增減前五名，外加「相對自身歷史異常」的行業。

**通膨**：分項貢獻 ＝ 權重 × 變化率，跟勞動的產業貢獻是同一套引擎。
權重來自 BLS relative importance 表，**每年一月更新，必須同步校準**。
住房項標記為落後項，並另外算「剔除住房後」的通膨。

**聯準會文本**：完整逐字稿依規定延後五年公布，所以分析的是會後聲明、
投票紀錄、點陣圖與記者會。

**兩個分數刻意不合成**：
- 客觀訊號分數＝反對票方向與人數 + 點陣圖分布（主要依據）
- 措辭分數＝聲明用語的詞典計分（輔助）

理由是 2026 年 7 月的教訓：Warsh 上任後刻意縮短聲明、移除前瞻指引，
純看措辭會誤判成轉鴿；但當次有三票主張升息、點陣圖 9 位官員預期升息，
市場也確實讀成偏鷹。**合成會掩蓋這個背離，而背離本身就是訊號。**

系統另外內建「溝通方式改變偵測」：當聲明字數驟降或追蹤詞組大量消失時，
會停用措辭分數並示警，而不是輸出一個假的讀數。

點陣圖沒有機器可讀來源，需在 `config/fomc.yaml` 手動更新（一季一次、四個數字）。

**長端與債務**：主軸是「長端殖利率的供給壓力」。名目利率拆成實質利率、
通膨補償與期限溢酬三段，因為這三種上升的政策意涵完全不同——
只有期限溢酬那一段是聯準會降息也壓不下來的。

財政損益兩平用的是標準的債務動態式：

```
穩定債務比所需的基本盈餘 ≈ 債務比 × (有效利率 − 名目成長) ÷ (1 + 名目成長)
```

供給壓力分數由四項加總（期限溢酬、財政缺口、科技巨頭融資缺口、投資級利差），
每一項的貢獻都列出來，不做成黑箱。

**科技巨頭那一段是手動維護的**，沒有免費 API。每季更新 `config/rates.yaml`
的 `hyperscalers` 段落，數字取自各公司 10-Q 現金流量表（資本支出、營運現金流、
營收）與公司債發行公告，單位填**十億美元**（頁面上會自動換算成億美元顯示）。
更新完把 `verified` 改成 `true`，頁面上的「尚未對照財報」警示才會消失。
`ig_market.quarterly_issuance` 同樣要每季更新（來源：SIFMA 季度投資級發行統計）。

關鍵比率是 `capex ÷ ocf`：超過 100% 代表自由現金流轉負，擴張必須靠舉債——
那正是這幾家從現金充裕的買方，變成投資級市場大型供給方的轉折點。

**情境合成**：九宮格 ＝ 就業（強/中/弱）× 通膨（低/中/高），
再用聯準會措辭校準。刻意不給機率——市場已有現成報價，
有價值的是指出自己的判讀與市場定價的分歧。

長端供給壓力**不進九宮格**，另外列一段。理由同上：九宮格回答政策方向，
供給壓力回答曲線形狀。但兩者會交叉出一句話（例如「升息 × 供給壓力高
＝ 長端承壓最重」），並在部位對照表加上對應的但書。

---

## 已知限制

- **市場預期是手填的**。`config/consensus.yaml` 需要在每次數據公布前更新，
  且必須標明來源；沒有來源時面板會顯示「無預期資料」，不會拿模型推估冒充市場預期。
- **綜合分數的權重是暫定值**，尚未由歷史迴歸校準（哪個指標的意外真的移動了利率定價）。
- **擴散指數（diffusion index）未納入**，FRED 覆蓋不完整，需改走 BLS API。
- **點陣圖與 hyperscaler 財報是手動維護的**，各自一季更新一次，見上方各模組說明。
- **CPI 權重每年一月要重新校準**，BLS relative importance 表更新後不同步會讓貢獻度失真。
- **市場隱含機率尚未接入**。規劃使用亞特蘭大聯準銀行的 Market Probability Tracker。
- **示範資料不可用於研究**。標題數字取自 2026 年 7 月實際值，但部分細項為生成值。
  離線模式的頁面頂端一律會掛上警示條。

---

## 手動維護清單

| 項目 | 檔案 | 頻率 | 來源 |
|---|---|---|---|
| 點陣圖分布 | `config/fomc.yaml` | 一季（SEP 會議後） | 聯準會 SEP |
| Hyperscaler 資本支出／發債 | `config/rates.yaml` | 一季（財報後） | 各公司 10-Q |
| 投資級季度發行量 | `config/rates.yaml` | 一季 | SIFMA |
| CPI 相對重要性權重 | `config/inflation.yaml` | 一年（每年一月） | BLS relative importance |
| 市場預期 | `config/consensus.yaml` | 每次數據公布前 | 券商調查 |
