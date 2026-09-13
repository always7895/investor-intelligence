# LINE Top20 UI / 七欄卡片

## Implementation / 實作與驗收界線

Actual observations and open acceptance are maintained only in [STATUS](../state/STATUS.md); historical local-render checks do not override later operator-reported LINE observations. Source edits here are not a fresh device/deployment acceptance. [Screenshot and research-execution audit](RESEARCH_EXECUTION_AUDIT.md).

The implementation uses the same renderer for authenticated interactive Top20 and the two scheduled broadcasts. Twenty stocks appear as four Flex carousels, five complete seven-field cards each, in one outbound request. `Top20 文字` returns complete text grouped by company; it does not silently drop later stocks.

目前的互動 Top20 與兩個排程廣播共用呈現器：20 檔分成四組 Flex carousel，每組五張完整七欄卡片，同一請求送出。輸入 `Top20 文字` 可取得按公司分組的完整文字，不會悄悄刪除後面的股票。

- Prominent rank/ticker and accepted public company name, bilingual labels, separated historical returns, industry, profitability, current orders and future outlook. No unverified Chinese-name/product dictionary.
- Candidate evidence and company-text buttons share the same timestamp/snapshot/report-SHA checks; stale or replaced reports cannot supply an old card's details. Company text is the full seven-field summary, not a deep valuation report.
- Cards explicitly retain 6/12/24-month scenario availability. Do not restore hard-coded upside/downside strings: per-order inputs and a sealed valuation product remain missing.
- 清楚標示排名／代碼、雙語欄名，分區呈現歷史報酬、產業、獲利、目前訂單與未來展望。
- Taiwan timestamps, research-candidate labels and historical-return disclaimer; missing evidence stays missing. Presentation never upgrades LIMITED eligibility.
- 台北時間、研究候選標籤與歷史報酬聲明；缺少證據仍明示缺少，UI 不會把 LIMITED 升級為已驗證論點。

## Rich-menu commands / 三個圖文選單入口

`cloud/src/v213/rich-menu.ts` handles the existing manager-configured message actions **TOP20**, **宏觀產業分析**, **期權** after real LINE admission and rate limiting. It reuses the request-pinned public view and does not send menu requests to the compact model. `選單` exposes the same three actions.

| 入口 | 已實作來源功能 | 仍未完成，不冒充 |
| --- | --- | --- |
| TOP20 | 20家公司、原文名稱、七欄、同輪綁定證據／公司文字 | 中文名稱來源尚未核對；沒有可發布的6/12/24月估值產品 |
| 宏觀產業分析 | 當輪20家產業分布、家數占比、完整文字與資料要求 | 家數不是市值權重／資產配置；`MACRO_PRODUCT_NOT_SEALED`，不使用候選GDP/CPI等數值 |
| 期權 | 連到既有「最新期權」查詢（仍適用逐標的freshness門檻）及「期權試算說明」、每週／每月輸入提示 | 選單不依鍵存在宣稱快照；封存輪→`OPTION_DATA_NOT_ADMITTED`（契約物件集合無期權），未封存／舊鍵殘留→`OPTION_DATA_UNAVAILABLE` |

完整資料／完整文字分析指令仍由獨立產品契約處理；不改送選單或產業摘要冒充。部分入口可操作，不表示三類研究產品均已完成。

Visual tokens in `line-theme.ts` use the supplied black/white mascot artwork's monochrome direction with dark-green actions and pale-green data groups. The existing rich-menu artwork is not uploaded or rescheduled by source edits. Original names are labelled explicitly; Chinese names say unverified rather than guessing. Preserve seven-field values, historic-return warnings and the realized/delayed/not-realized scenario gap.

`test/v213-rich-menu.test.ts` exercises the actual authorized caller with mocked LINE, including stale/invalid-pointer negatives, options key-presence/carryover and sealed-round fixtures, and explicit deep-product refusal. Optional `V213_MENU_PREVIEW_OUT` exports **synthetic message objects only**, not tokens/recipients, for local approximate rendering. Exporting HTML is not a successful visual review or device acceptance; no additional server is required or authorized by that export.

## Limits and evidence / 限制與證據

Product bounds: at most five outbound messages, text at most 4,900 UTF-16 code units, alt text at most 400, five bubbles per carousel, bubble JSON at most 28,000 bytes and carousel JSON at most 48,000 bytes. Size violations fail closed rather than truncate. These conservative product limits do not replace LINE's official API specification.

產品採保守上限：最多五個訊息物件、文字最多 4,900 個 UTF-16 code units、替代文字最多 400、每組五張卡，單卡 JSON 28,000 bytes、carousel JSON 48,000 bytes。超限拒絕，不裁切；產品限制不取代官方 API 規格。

References / 官方參考：
- https://developers.line.biz/en/docs/messaging-api/using-flex-messages/
- https://developers.line.biz/en/reference/messaging-api/nojs/

Tests verify maximum schema-length inputs, exact stock/field/value completeness, real Worker caller payloads with mocked LINE transport, and complete text fallback. The isolated Q6 live receipt also checks the actual Worker payload. A synthetic browser preview is only an approximate layout review, not LINE-device certification. Current source tests use mocked LINE transport; historical actual delivery observations belong in STATUS.

測試涵蓋 schema 最大欄長、完整股票／欄位／數值、實際 Worker 呼叫流程的合成 LINE 傳輸及完整文字備援。隔離 Q6 live receipt 也檢查實際 Worker payload。合成瀏覽器預覽僅供近似排版審查，並非 LINE 裝置認證；本輪不傳送真實LINE，過去實際觀察以STATUS的日期與範圍為準。

Deployment and whole-project acceptance remain separate; see [current status](CURRENT_STATUS_BILINGUAL.md).
部署及全專案驗收另行判定，請見[目前狀態](CURRENT_STATUS_BILINGUAL.md)。
