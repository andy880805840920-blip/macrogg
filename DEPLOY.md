# 部署指南 — 從零到自動更新

一次設定，之後每天自動抓資料、重產頁面、上線。全程免費。

**架構**：GitHub Actions 每天跑一次 Python → 產出 `output/` → commit 進 repo
→ Netlify 偵測到 push 自動部署。

Netlify **不執行任何 build**。這樣 API key 只留在 GitHub、不必在 Netlify 裝
Python 依賴，而且每次產出都留在 git 歷史裡，自動累積成 vintage 檔案庫。

預計花費 20 分鐘。

---

## 事前準備

**① FRED API key**（免費，約 2 分鐘）

1. 到 <https://fredaccount.stlouisfed.org/apikeys>
2. 註冊帳號（只要 email）
3. 點 **Request API Key**，用途隨便填（例如 personal research）
4. 立刻拿到一組 32 碼字串，先複製起來

**② 把 zip 解壓縮**（Windows）

1. 在 `labordashboard_4.zip` 上按右鍵 → **解壓縮全部**
2. 解壓後會得到一個 `labordashboard_4` 資料夾
3. **打開它**，裡面應該直接看到 `run.py`、`README.md`、`config`、`src`、
   `output`、`state`、`netlify.toml`、`.github`、`.gitignore`

記住這個「裡面」的位置，等一下要上傳的是**這些項目**，不是外層那個資料夾。

不需要裝 git、也不需要裝 Python——全部用瀏覽器完成。

---

## 步驟 1：建 GitHub repo 並上傳（全程用網頁）

### 1-1 建立 repo

1. <https://github.com> 登入 → 右上 **+** → **New repository**
2. Repository name 填 `macro-dashboard`（或你喜歡的名字）
3. 選 **Private**

   > 私有比較合適：頁面帶 noindex，本來就不打算給搜尋引擎收錄。
   > 私有 repo 的 Actions 免費額度是每月 2,000 分鐘，這個專案每月用不到 100 分鐘。
4. **不要**勾 Add a README file（本專案已經有了，會衝突）
5. **Create repository**

### 1-2 上傳檔案

建好後會看到一個空 repo 的說明頁，點中間的
**uploading an existing file** 連結（或網址直接加 `/upload/main`）。

1. 開啟檔案總管，進到剛才解壓的 `labordashboard_4` 資料夾**裡面**
2. 全選裡面所有項目（`Ctrl + A`）
3. 整批拖進瀏覽器的上傳區

   > 這個專案有 57 個檔案、最大的才 72 KB，
   > 遠低於網頁上傳的限制（一次 100 個檔案、單檔 25 MB），一次就傳得完。
4. 等檔案列表跑完（約 10–30 秒）
5. 下方 Commit changes 填 `初始版本` → **Commit changes**

⚠️ **最容易出錯的一步**：拖進去的必須是資料夾**裡面的內容**，
不是 `labordashboard_4` 這個資料夾本身。傳錯的話 repo 裡會變成
`labordashboard_4/run.py` 這種多一層的結構，Netlify 和排程都會失效。

判斷方式：上傳完成後，**repo 首頁第一層就要看得到 `run.py` 和 `README.md`**。
如果看到的是一個資料夾，就是傳錯了——進 Settings 最下面刪掉 repo 重來一次比較快。

### 1-3 確認 `.github` 有上傳成功

這一步很重要：`.github/workflows/update.yml` 就是「自動更新」本身，
少了它整套排程都不會動。有些瀏覽器拖曳時會略過點開頭的資料夾。

在 repo 首頁的檔案清單找找看有沒有 **`.github`**。

**有** → 直接跳到步驟 2。

**沒有** → 手動補上，一分鐘的事：

1. repo 頁面 → **Add file** → **Create new file**
2. 檔名欄位貼上：`.github/workflows/update.yml`

   > 打斜線 GitHub 會自動建出資料夾層級，不用先建資料夾
3. 內容從解壓資料夾裡的 `.github\workflows\update.yml` 用記事本打開、
   全部複製貼上
4. **Commit changes**

同理，若 `.gitignore` 也沒上去，用一樣的方法補（這個影響較小，但補上比較乾淨）。

### 1-4 確認清單

repo 首頁第一層應該看得到這些：

```
.github/          ← 排程（最重要，缺了就不會自動更新）
config/           ← 設定檔
output/           ← Netlify 的取檔來源
src/              ← 程式
state/            ← 「跟上期比」的依據，缺了就永遠比不出變化
.gitignore
DEPLOY.md
README.md
netlify.toml
requirements.txt
run.py
```

點進 `output/` 要看得到 `index.html`。都對就往下走。

---

## 步驟 2：把 API key 存進 GitHub Secrets

1. repo 頁面 → **Settings**（repo 自己的，不是帳號的）
2. 左側 **Secrets and variables** → **Actions**
3. **New repository secret**
4. Name 填 **`FRED_API_KEY`**（大小寫要完全一致）
5. Secret 貼上剛才那組 key → **Add secret**

存進去之後就再也看不到內容，只能覆寫。這是正常的。

---

## 步驟 3：手動觸發第一次執行

先確認抓真實資料沒問題，再交給排程。

1. repo → **Actions** 分頁
2. 若出現 "Workflows aren't being run on this forked repository" 之類的提示，
   點 **I understand my workflows, go ahead and enable them**
3. 左側點 **更新儀表板**
4. 右邊 **Run workflow** → 綠色按鈕 **Run workflow**
5. 等 2–3 分鐘，重整頁面看結果

**綠色勾勾** = 成功。點進去看 log，最後一行應該是
`INFO 已產出 10 個頁面至 .../output`。

回到 repo 首頁，應該多了一筆 `dashboard-bot` 的 commit。

### 如果失敗了

| log 裡的訊息 | 原因與處理 |
|---|---|
| `FRED_API_KEY` 未設定 / 401 / 403 | secret 名稱打錯，或 key 貼到多餘空白。回步驟 2 重設 |
| `Permission denied` / 403 在 push 階段 | Settings → Actions → General → Workflow permissions 選 **Read and write permissions** |
| 某幾個序列抓取失敗 | **正常，不影響**。FRED 偶爾改 series id，頁面底部會列出清單，其他部分照樣產出 |
| `ModuleNotFoundError` | `requirements.txt` 沒推上去，檢查 repo 裡有沒有這個檔 |

---

## 步驟 4：接上 Netlify

1. <https://app.netlify.com> 用 GitHub 帳號登入
2. **Add new site** → **Import an existing project**
3. 選 **GitHub**，授權後選你剛才那個 repo

   > 私有 repo 要授權 Netlify 存取。若清單裡看不到，點
   > **Configure the Netlify app on GitHub** 加上這個 repo。
4. 部署設定（`netlify.toml` 已經寫好，畫面上應該自動帶出來）：

   | 欄位 | 值 |
   |---|---|
   | Branch to deploy | `main` |
   | Build command | **留空** |
   | Publish directory | `output` |

   Build command 一定要空的。填了會讓 Netlify 嘗試跑 build，那不是這個架構要的。
5. **Deploy site**

30 秒後拿到一個 `隨機名稱.netlify.app` 的網址，打開就是儀表板。

**改網址**：Site configuration → Site details → Change site name，
可以改成 `你的名字-macro.netlify.app`。

---

## 步驟 5：確認自動更新生效

排程是每天 **13:45 UTC**（台灣時間 21:45）。

美東夏令 = 09:45、冬令 = 08:45，兩者都在 08:30 ET 的資料發布之後，
**所以換季不必手動調整**。

明天過了那個時間，回 Actions 分頁應該看到一筆自動執行的紀錄。看到了就完成了，
之後不用再碰。

> 排程的實際執行時間會有幾分鐘到幾十分鐘的延遲（GitHub 全球排隊），
> 這是正常現象，不是設定錯誤。

---

## 之後怎麼維護

### 改設定（也是全程用網頁）

日常維護幾乎都是改 `config/` 裡的 YAML，這在 GitHub 網頁上直接改就好，
不必下載也不必裝任何東西：

1. repo → 進 `config/` → 點要改的檔案（例如 `consensus.yaml`）
2. 右上角鉛筆圖示 **Edit this file**
3. 改完 → 下方 **Commit changes**

下次排程執行就會套用。想立刻看到結果，到 **Actions** → **更新儀表板**
→ **Run workflow** 手動觸發一次即可。

### 手動維護清單（這些沒有免費 API，需要自己更新）

| 項目 | 檔案 | 頻率 | 來源 |
|---|---|---|---|
| 市場預期 | `config/consensus.yaml` | 每次數據發布前 | 券商調查 |
| 點陣圖分布 | `config/fomc.yaml` | 一季（SEP 會議後） | 聯準會 SEP |
| Hyperscaler 財報 | `config/rates.yaml` | 一季（財報後） | 各公司 10-Q |
| 投資級季度發行量 | `config/rates.yaml` | 一季 | SIFMA |
| CPI 相對重要性權重 | `config/inflation.yaml` | 一年（每年一月） | BLS |

沒更新不會壞，但畫面上會顯示對應的提醒（例如「尚未對照財報」）。

### 用量會不會爆

不會。每次執行 2–3 分鐘，一個月約 60–90 分鐘，免費額度是 2,000 分鐘。
Netlify 免費層只做託管、不跑 build，頻寬也遠遠用不完。

在 Settings → Billing → Plans and usage 可以看到實際用量。

---

## 三個容易踩到的坑

**① 不要在 Netlify 填 Build command**

這個架構刻意讓 Netlify 只做託管。填了 build 指令會導致每次部署重灌 Python
依賴、燒掉免費建置額度，而且 API key 得再交給 Netlify 一份。

**② `output/` 不要加進 `.gitignore`**

一般專案會把產出物排除，但這裡的 `output/` 就是 Netlify 的取檔來源，
而且 git 歷史正是 vintage 檔案庫的來源。排除掉整套就不會動。

**③ 公開 repo 的 60 天休眠規則**

GitHub 對**公開** repo 有「60 天沒有任何活動就自動停用排程」的規定。
本指南建議用私有 repo，不受此限。若你改用公開 repo，記得偶爾手動觸發一次，
或直接在 Actions 頁面重新啟用。

---

## 網址是半公開的

三道 noindex 都設了（頁面 meta、`netlify.toml` 的 X-Robots-Tag、`robots.txt`），
搜尋引擎不會收錄。

但這**不是存取控制**——知道網址的人仍然打得開。若日後需要真的擋，
用 Cloudflare Access（免費 50 人）在前面加一層登入。
