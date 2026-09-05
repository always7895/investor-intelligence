# LINE Top20 UI / 七欄卡片

## Candidate scope / 候選版本範圍

The candidate uses the same renderer for authenticated interactive Top20 and the two scheduled broadcasts. Twenty stocks appear as four Flex carousels, five complete seven-field cards each, in one outbound request. `Top20 文字` returns complete text grouped by company; it does not silently drop later stocks.

候選版的互動 Top20 與兩個排程廣播共用呈現器：20 檔分成四組 Flex carousel，每組五張完整七欄卡片，同一請求送出。輸入 `Top20 文字` 可取得按公司分組的完整文字，不會悄悄刪除後面的股票。

- Prominent rank/ticker, bilingual labels, separated historical returns, industry, profitability, current orders and future outlook.
- 清楚標示排名／代碼、雙語欄名，分區呈現歷史報酬、產業、獲利、目前訂單與未來展望。
- Taiwan timestamps, research-candidate labels and historical-return disclaimer; missing evidence stays missing. Presentation never upgrades LIMITED eligibility.
- 台北時間、研究候選標籤與歷史報酬聲明；缺少證據仍明示缺少，UI 不會把 LIMITED 升級為已驗證論點。

## Limits and evidence / 限制與證據

Product bounds: at most five outbound messages, text at most 4,900 UTF-16 code units, alt text at most 400, five bubbles per carousel, bubble JSON at most 28,000 bytes and carousel JSON at most 48,000 bytes. Size violations fail closed rather than truncate. These conservative product limits do not replace LINE's official API specification.

產品採保守上限：最多五個訊息物件、文字最多 4,900 個 UTF-16 code units、替代文字最多 400、每組五張卡，單卡 JSON 28,000 bytes、carousel JSON 48,000 bytes。超限拒絕，不裁切；產品限制不取代官方 API 規格。

References / 官方參考：
- https://developers.line.biz/en/docs/messaging-api/using-flex-messages/
- https://developers.line.biz/en/reference/messaging-api/nojs/

Tests verify maximum schema-length inputs, exact stock/field/value completeness, real Worker caller payloads with mocked LINE transport, and complete text fallback. The isolated Q6 live receipt also checks the actual Worker payload. A synthetic browser preview is only an approximate layout review, not LINE-device certification. No extra real LINE test messages were sent.

測試涵蓋 schema 最大欄長、完整股票／欄位／數值、實際 Worker 呼叫流程的合成 LINE 傳輸及完整文字備援。隔離 Q6 live receipt 也檢查實際 Worker payload。合成瀏覽器預覽僅供近似排版審查，並非 LINE 裝置認證；未額外發送真實 LINE 測試訊息。

Deployment and whole-project acceptance remain separate; see [current status](CURRENT_STATUS_BILINGUAL.md).
部署及全專案驗收另行判定，請見[目前狀態](CURRENT_STATUS_BILINGUAL.md)。
