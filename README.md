# UAnalyze 產業情報小助理爬蟲（longrun enterfix safe）

這版是從可正常部署的 `uanalyze-crawler-app-longrun.zip` 回退修改：

- requirements.txt 回復為原本可用版本：streamlit + playwright
- packages.txt 回復為原本可用版本：chromium + chromium-driver
- 股票欄位只輸入數字，例如 3030
- 輸入股票代號後會按 Enter 確認
- 如果頁面仍停在原股票，會提示不要繼續爬錯公司

手機操作：輸入 Email、密碼、股票代號、選欄位，按一次開始。
