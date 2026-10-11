第十七批：新聞退回穩定版＋修正、殖利率曲線改版（2026-10-11 最終版）
（這一包已包含先前兩包「第十七批」的全部內容，之前那兩包都不用再上傳）

【上傳】把這個資料夾裡的 config、src、tests、run.py、requirements.txt 拖進 GitHub 專案根目錄（覆蓋同名檔）。共 19 個檔案：
  config/focus.yaml
  config/rates.yaml
  requirements.txt
  run.py
  src/analysis/curve_weekly.py
  src/analysis/focus_today.py
  src/analysis/longend.py
  src/build.py
  src/pages/curve_weekly.py
  src/pages/home.py
  src/pages/longend.py
  src/site.py
  src/treasury_yields.py
  tests/test_curve_weekly.py
  tests/test_curve_window.py
  tests/test_focus.py
  tests/test_future_outlook.py
  tests/test_news_rules.py   （新檔）
  tests/test_topics_election.py

【可以刪除（不刪也不影響執行）】ChatGPT 新聞機制留下、程式已不再使用的檔案：
  src/analysis/news_article.py
  src/analysis/news_checks.py
  src/analysis/news_policy.py
  src/analysis/news_publishers.py
  src/analysis/news_sources.py
  tests/test_all_news_topics.py
  tests/test_focus_restore.py
  tests/test_name_boundaries.py
  tests/test_news_coverage.py
  tests/test_news_editorial_logic.py
  tests/test_news_indicators.py
  tests/test_news_pipeline.py
  tests/test_news_policy.py
  tests/test_news_publishers.py
  tests/test_news_sources.py
  tests/test_news_window.py
  tests/test_supplement_copy.py
  tests/test_topic_summaries.py
