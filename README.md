# UAnalyze Crawler V2 - Transcript Navfix

本版用途：第二區塊改為爬取「逐字稿」文字，不再下載 CSV。

修正重點：
1. 強制從左側抽屜選單點「優分析產業資料庫」，避免誤進商城 product-detail 頁。
2. 進入功能頁後，切換股票代號。
3. 對上方橫向 bar 執行水平滑動，找到並點選「逐字稿」。
4. 擷取逐字稿文章文字，提供 Markdown 一鍵複製與 ZIP 下載。

部署：上傳 app.py、requirements.txt、packages.txt、README.md 到 GitHub repo 後，至 Streamlit 重新部署。
