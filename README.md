# UAnalyze crawler v2 transcript leftnavfix

這版不下載 CSV，改抓逐字稿文字。

重點修正：
- 先進虎八速覽並切股票。
- 再打開左側收放欄。
- 只點「我的訂閱」區塊中、Kelvin 價值投資工具包上方的「優分析產業資料庫」。
- 若誤入 `/e-com/product-detail/...` 商城頁，直接判定失敗，不再輸出假成功。
- 進入資料庫功能頁後，再點「逐字稿」功能並抓文章文字。
