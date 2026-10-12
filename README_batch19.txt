MACRO GG 第十九批（2026-10-12）

前提：先上傳第十八批，再上傳這一批（這批的檔案是在第十八批之上改的）。
上傳方式：GitHub「Add files via upload」，把壓縮檔解開後的資料夾內容（config、src、tests）整批拖進 repo 根目錄，覆蓋同名檔案。

修改檔案（6）：
  src/analysis/focus_today.py   今日主軸與主題補充加入政策現況（目標區間、最近一次決議、市場定價）；
                                升息循環不得寫「繼續降息」這類說法，寫反就重寫，仍錯則換備用句／刪句／不顯示；
                                「AI 與半導體」寫作規則只寫國際大廠與產業趨勢
  config/focus.yaml             「AI 與半導體」必含國際大廠或產業用詞，排除台股個股盤勢用語，新增兩組英文搜尋
  src/pages/home.py             接下來看什麼：數據列拿掉說明文字；日期一律寫台灣日期（不再出現「台灣隔天」）；官員名字改英文
  src/site.py                   「票委」標籤不斷行
  tests/test_batch18.py         新增 H 組測試（政策現況、AI 與半導體）
  tests/test_news_rules.py      「AI 與半導體」的規則測試改成新規則
