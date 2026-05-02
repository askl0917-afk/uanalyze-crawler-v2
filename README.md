# UAnalyze 產業情報小助理爬蟲（v2 transcript codexfix）

本版只修改 **v2 repo**，目標是穩定抓到「逐字稿文章正文」，並且嚴格阻擋假成功。

## 這版修正重點

1. 僅走正確流程：登入 → 虎八速覽切股 → 左側欄「優分析產業資料庫」→ 上方右側三條線 menu → ⭐逐字稿。
2. 強化防呆：禁止把 `/e-com` 商城、虎八速覽、個股導航員、新手教學頁當成成功。
3. 股票代號只用數字，切股後會再驗證頁面狀態。
4. 逐字稿成功條件升級：
   - 正文長度優先需大於 3000 字（較短時必須命中多個法說關鍵詞）。
   - 命中法說會 / Q&A / 問答 / 管理層 / 營收 / 毛利率 / 資本支出等特徵。
5. 失敗一定輸出 debug zip，不允許假成功。debug zip 會包含：
   - 失敗截圖
   - page.url / page.title
   - body 前 8000 字
   - 所有含「逐字稿」候選元素（innerText/tag/href/bounding box/visible）
   - menu 展開文字與節點 dump
   - 點擊行為與時間紀錄

## UI 與輸出

- 保留輸入：UAnalyze Email、UAnalyze 密碼、股票代號。
- 按鈕：**抓取逐字稿**。
- 成功提供：
  - 一鍵複製逐字稿 Markdown
  - Markdown textarea
  - 下載 Markdown / ZIP
- 失敗提供：
  - 清楚錯誤訊息
  - debug zip 下載

## 部署方式（你的既有流程）

ZIP 內容直接放四個檔案（不要包多一層資料夾）：

- `app.py`
- `requirements.txt`
- `packages.txt`
- `README.md`

解壓後覆蓋到 GitHub repo，Commit changes，然後到 Streamlit Community Cloud Reboot / Deploy。

## 建議測試

1. 用 3037 測一次完整流程。
2. 確認最終不是停在虎八速覽/商城/新手頁。
3. 若失敗，下載 debug zip，檢查：
   - `FAIL_REASON.txt`
   - `debug_page_meta.json`
   - `debug_transcript_candidates.json`
   - `debug_menu_dump.json`
   - `debug_body_8000.txt`
   - `debug_failed.png`
