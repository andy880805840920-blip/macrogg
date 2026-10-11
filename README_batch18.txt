MACRO GG 第十八批（2026-10-12，含舊測試修正、拿掉通膨頁本期總結、訊號標籤改利寬鬆／利緊縮、變動欄改下拉選單、今日結論的整體情勢預設收合、四大模組四格對齊、變動欄一律絕對差距）

上傳方式：GitHub「Add files via upload」，把壓縮檔解開後的資料夾內容（.github、config、netlify、run.py、src、tests）整批拖進 repo 根目錄，覆蓋同名檔案。
注意：.github 是隱藏資料夾，Windows／Mac 拖曳時要確認有一起選到；選不到的話到 GitHub 網頁直接編輯 .github/workflows/update.yml 貼上。

新增檔案（2）：
  src/analysis/watch_extra.py   接下來看什麼：市場預估、公債標售、國債回購、官員談話
  tests/test_batch18.py         本批規則測試

修改檔案（26）：
  .github/workflows/update.yml  核心規則測試加入 test_batch18、hyperscaler 兩個、treasury_yields、inflation_verdict 等
  config/focus.yaml             華許為主級關鍵字、鮑爾降次級；新指標對應新聞主題；票委名單
  netlify/functions/quotes.mjs  盤中報價加 S&P 500、NASDAQ、加權、三組匯率
  run.py  src/build.py  src/site.py
  src/pages/home.py（變動欄下拉選單、整體情勢預設收合）  inflation.py（拿掉本期總結）  labor.py（訊號標籤利寬鬆／利緊縮）  longend.py  scenario.py
  src/analysis/brief.py  focus_today.py  fomc_extra.py  rules.py  scenario.py  watch_calendar.py
  tests/test_brief.py  test_focus.py  test_grid_bands.py  test_signal_order.py  test_inflation_verdict.py
  tests/test_hyperscaler_data.py  test_hyperscaler_forward.py  test_reader_copy.py  test_treasury_yields.py

舊測試修正：
  longend.py         殖利率曲線說明拿掉設定檔路徑（讀者不該看到 config/…）
  hyperscaler 兩個、inflation_verdict   改成測試自己用測試資料渲染頁面，不再讀 output/
  reader_copy        略過各月份存檔頁（發布當時凍結的快照）
  treasury_yields    把「今天」固定在 10/7，不再隨日期失敗

可以刪掉的檔案（已不再使用）：
  README_upload.txt、update.yml.new
  src/analysis/news_article.py、news_checks.py、news_policy.py、news_publishers.py、news_sources.py
  tests/ 底下 13 個舊新聞測試（test_all_news_topics、test_focus_restore、test_name_boundaries、test_news_coverage、
  test_news_editorial_logic、test_news_indicators、test_news_pipeline、test_news_policy、test_news_publishers、
  test_news_sources、test_news_window、test_supplement_copy、test_topic_summaries）
  output/archive/labor-2026-07/、output/archive/inflation-2026-07/（示範資料存檔頁）

每年要手動更新的設定（config/focus.yaml）：
  fomc_dates   聯準會公布下一年日程後補上（三段累計升降息要用）
  fomc_board / fomc_voters   每年一月更新票委名單；2027 亞特蘭大新總裁上任後補姓氏
