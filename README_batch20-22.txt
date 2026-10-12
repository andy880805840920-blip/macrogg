MACRO GG 第二十～二十二批合併版（2026-10-12）

這一包＝第二十、二十一、二十二批的全部內容，三批都還沒上傳的話，只要上傳這一包，不用再分三次。
前提：第十八、十九批已上傳。
上傳方式：GitHub「Add files via upload」，把解開後資料夾內的 .github、config、src、tests、run.py 整批拖進 repo 根目錄，覆蓋同名檔案。
（.github 是隱藏資料夾；拖不上去的話，到 GitHub 直接編輯 .github/workflows/update.yml，
  在「核心規則測試」那一行最後的 test_inflation_verdict 後面加上「 test_ask test_signal_impact」。）

一、偷懶頁（新分頁，導覽列在「總覽」後面）
  · 打關鍵字或整句話，不經 AI；問法清楚直接回答，籠統或混問顯示「我猜你想問？」，網站沒有的資料推薦三題
  · 207 張卡（142 張資料卡＋65 張名詞卡）：解釋、圖（日 1 年／週半年／月 2 年／季 3 年，可切五年）、小表、跳轉連結、
    「這個指標怎麼看」教學（六段＋小測驗，資料來自 config/learn.yaml）、相關問題
  · 打字時即時提示三題；依問法補一句（問變化、問今年、問原因）；「為什麼」卡的標題依當期方向
  · 資料過期時標「資料停在 X」；期貨抓不到時不顯示亂句
  · 各頁「這在看什麼？」與名詞解釋加上連到偷懶頁的完整教學連結

二、就業頁「本期關鍵訊號」
  · 名稱維持重要／留意／參考，分級改看對結論的影響：
      重要　已經或即將改變就業的強／中／弱
      留意　會改變動能判讀，格位還沒動
      參考　解讀時要知道，但不改變結論
  · 拿掉另一套小標（改變頭條數字的解讀／趨勢轉折／結構背景）；首段露出前三則，其餘收合
  · 只改顯示：九宮格、首頁、利寬鬆／利緊縮淨值不受影響；通膨頁不變

三、其他
  · 「接下來看什麼」日程往後查超過五週不再出錯
  · 核心規則測試加入 test_ask、test_signal_impact

新增檔案（7）：config/ask.yaml、config/learn.yaml、src/analysis/ask.py、src/pages/ask.py、src/pages/ask_match.js、
               tests/test_ask.py、tests/test_signal_impact.py
修改檔案（12）：run.py、src/site.py、src/analysis/rules.py、src/analysis/watch_calendar.py、src/pages/__init__.py、
               src/pages/labor.py、inflation.py、fomc.py、rates.py、longend.py、scenario.py、.github/workflows/update.yml
