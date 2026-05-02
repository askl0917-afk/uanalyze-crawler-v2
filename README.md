# UAnalyze 產業情報小助理爬蟲（v2 transcript clean path）

本版只修改 **v2 repo** 的 `app.py` 與 `README.md`，目標是重新建立乾淨流程，只在「真正逐字稿正文」成功時才輸出結果。

## 這版規則（重新整理）

1. 固定流程：登入 → 虎八速覽切股 → 左側欄「優分析產業資料庫」→ 上方右側白色三條線 menu → 固定選單「逐字稿」。
2. 保留第一區塊已穩定可用的虎八速覽切股流程，不改壞。
3. 不下載 CSV，只抓逐字稿文字。
4. 明確阻擋誤判：`/e-com` 商城、產品目錄頁、個股導航員、虎八速覽頁都不算成功。
5. 第二區塊只做逐字稿正文擷取。
6. 成功條件嚴格化：
   - 必須是逐字稿文章正文，不是列表或導覽頁。
   - 內容需含法說語意特徵（例如：法說會 / Q&A / 問答 / 管理層 / 營收 / 毛利率 / 資本支出 / ABF / IC載板）。
   - 正文長度需足夠（優先長文，短文需有足夠特徵才放行）。
7. 若未抓到真正逐字稿正文，必須失敗並輸出 debug bundle，不得假成功。

## debug bundle 內容

失敗時會輸出 ZIP，至少包含：

- `FAIL_REASON.txt`
- `debug_page_meta.json`（含 `page.url`、`page.title`）
- `debug_body_8000.txt`（body 前 8000 字）
- `debug_transcript_candidates.json`（候選元素清單）
- `debug_clicked_elements.json`（點擊紀錄）
- `debug_menu_dump.json`
- `debug_failed.png`（截圖）

## UI 與輸出

- 輸入欄位：UAnalyze Email、UAnalyze 密碼、股票代號。
- 按鈕：**抓取逐字稿**。
- 成功時提供：
  - 一鍵複製逐字稿 Markdown
  - Markdown textarea
  - 下載 Markdown / ZIP
- 失敗時提供：
  - 清楚錯誤訊息
  - debug zip 下載

## 部署方式

ZIP 內容直接放四個檔案（不要再包一層資料夾）：

- `app.py`
- `requirements.txt`
- `packages.txt`
- `README.md`
