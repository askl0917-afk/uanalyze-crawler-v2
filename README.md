# UAnalyze 逐字稿右側選單修正版

本版用途：第二區塊爬取逐字稿文字，不再下載 CSV。

本版重點修正：

1. 使用桌面版 viewport，對齊 iPad / 桌面看到的 UAnalyze 版面。
2. 從虎八速覽切股票後，仍從左側訂閱入口進入「優分析產業資料庫」。
3. 進入資料庫後，不再硬滑上方 bar 找逐字稿，而是優先點上方 bar 右側白色三條線選單。
4. 選單打開後，點選固定選單中的「逐字稿」。
5. 只有抓到真正逐字稿文章候選項，才輸出成功；否則輸出診斷 ZIP。

上傳 GitHub 時只需要覆蓋：

- app.py
- requirements.txt
- packages.txt
- README.md

不要上傳 __pycache__。
