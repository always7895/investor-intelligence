# LINE Top20 UI / 七欄卡片

## Implementation / 實作與驗收界線

Actual observations and open acceptance are maintained only in [STATUS](../state/STATUS.md); historical local-render checks do not override later operator-reported LINE observations. Source edits here are not a fresh device/deployment acceptance. [Screenshot and research-execution audit](RESEARCH_EXECUTION_AUDIT.md).

The implementation uses the same renderer for authenticated interactive Top20 and the two scheduled broadcasts. Twenty stocks appear as four Flex carousels, five complete seven-field cards each, in one outbound request. `Top20 文字` returns complete text grouped by company; it does not silently drop later stocks.

目前的互動 Top20 與兩個排程廣播共用呈現器：20 檔分成四組 Flex carousel，每組五張完整七欄卡片，同一請求送出。輸入 `Top20 文字` 可取得按公司分組的完整文字，不會悄悄刪除後面的股票。

- Prominent rank/ticker and accepted public company name, bilingual labels, separated historical returns, industry, profitability, current orders and future outlook. No unverified Chinese-name/product dictionary.
- Mobile Flex presentation features three readable return boxes: 2Y total return (2Y 總報酬), 2Y annualized (2Y 年化), and 6M return (6M 報酬). Labels are concise to prevent column squeezing on mobile devices.
- Candidate vs Authoritative Return Admission Boundary:
  * Strict candidate arithmetic and schema validation is enforced (exact calendar dates, derived elapsed days `actual_end - actual_start == elapsed_days`, 24-month calendar alignment within 7-day tolerance, positive finite prices, matching endpoint calculation, and max 7-day freshness).
  * However, arithmetic matching alone does not establish source authority. Authoritative return admission requires verified currency, raw provider body digest, acquisition role binding, and multi-runtime cryptographic lineage, which are currently DEFERRED (DEFER).
  * Safe resolution: Numeric 2Y total return is WITHHELD in all actual LINE card and deep analysis callers, rendering explicit `UNAVAILABLE`. It is never fabricated or reverse-calculated from CAGR.
  * Existing qualified stock returns continue using their validated legacy return fields (2Y annualized CAGR and 6M price return).
- Card footer emits a single primary action button: `深度化分析 / Deep analysis` (`Top20 深度化分析 <ticker> <timestamp> <snapshot> <reportSha256>`). The redundant "本公司七欄文字" card button has been removed, while the `Top20 公司文字` command is preserved as a backward-compatible direct text query.
- Deep analysis implements a comprehensive 10-section analytical flow with claim-level tagging (SUPPORTED, INFERENCE, WITHHELD, 研究待辦 / NOT_A_COMPANY_FINDING):
  1. 供應鏈瓶頸定位與價值鏈角色 (Bottleneck role / value chain)
  2. 未來結構性缺口 (Future structural gap)
  3. 需求／供給／定價權分析 (Demand, supply & pricing power)
  4. 公司捕捉度與毛利槓桿 (Company capture & margin leverage)
  5. 合約、訂單、資本支出、產能與客戶證據 (Contracts, orders, capex, capacity & customer evidence)
  6. 6個月／1年／2年催化劑與情境 (6M / 1Y / 2Y catalysts & scenarios)
  7. 假說殺手與下檔風險 (Hypothesis killers & downside risks)
  8. 多軸證據信心與來源品質 (Multi-axis evidence confidence & source quality)
  9. 候選排位說明與為何為第N名 (Rank rationale & why position N)
  10. 明確未明與待查事項 (Explicit unknowns & open items)
- Removal of generic company claims: Non-AI companies (such as ACGL, BBY) do NOT inherit generic AI beneficiary or server expansion narratives. Industry classification is cited from market observation, never falsely attributed to SEC EDGAR. Framework questions are categorized as `[研究待辦 / NOT_A_COMPANY_FINDING]`, not company-specific findings.
- Core analytical boundaries: customers aren't scarcity, margin isn't pricing power, capex alone isn't a choke, and social/source views are context only, not company proof.
- Existing 20 LIMITED universe has zero positive core bottleneck factors; System Bottleneck Explosion Score remains UNAVAILABLE/UNRANKED. Current display position `#N` is clearly distinguished as a legacy candidate display index, not a qualified bottleneck explosion rank.
- Candidate evidence and company-text buttons share the same timestamp/snapshot/report-SHA checks; stale or replaced reports cannot supply an old card's details. Company text is the full seven-field summary, not a deep valuation report.
- Cards explicitly retain 6/12/24-month scenario availability. Do not restore hard-coded upside/downside strings: per-order inputs and a sealed valuation product remain missing.
- 清楚標示排名／代碼、雙語欄名，分區呈現歷史報酬、產業、獲利、目前訂單與未來展望。
- 手機端提供三個易讀報酬方塊（2Y 總報酬、2Y 年化、6M 報酬），避免長標籤壓縮版面。
- 候選算術驗證與來源權威核驗界線（Candidate vs Authoritative Return Admission）：
  * 嚴格日曆驗證、端點精確日數核驗、24 個月日曆對齊容許度與時效政策僅代表候選算術與綱要通過檢驗，不等於獨立來源權威已解決。
  * 權威性總報酬核驗所需之幣別規格、原始回應主體雜湊（body SHA-256）、資料採集者角色權限綁定與跨執行環境密碼學血統尚未齊備，此新數值核驗狀態明確標記為【DEFER / 延後】。
  * 安全處置方針：所有實際 LINE 卡片及深度化分析呼叫端【扣留（WITHHOLD）】2Y 總報酬數值，明確標示為 UNAVAILABLE；不逆推年化、不用未還原收盤價冒充。
  * 既有已核驗之篩選股票報酬繼續沿用合格舊版欄位（近 2 年年化 CAGR 及近 6 個月報酬率）。
- 卡片移除重複的「本公司七欄文字」按鈕，改以單一「深度化分析」按鈕為主要入口；`Top20 公司文字` 與 `Top20 證據詳情` 保留為相容文字指令。
- 深度化分析移除通用捏造論點（非 AI 公司如 ACGL、BBY 不套用 AI 受惠論點；行業不假冒來自 SEC EDGAR；框架問題標註為「研究待辦 / NOT_A_COMPANY_FINDING」）。
- 包含至少 10 個獨立區塊與主張層級標記（SUPPORTED / INFERENCE / WITHHELD / 研究待辦），恪守「客戶不等於稀缺、毛利不等於定價權、資本支出不等於瓶頸、社群觀點不等於公司證明」之邊界。
- 20 LIMITED 候選集之系統瓶頸爆發分數（System Bottleneck Explosion Score）維持 UNAVAILABLE / UNRANKED；目前排位明確標示為舊版候選展示序位，非合格瓶頸排行。
- 系統瓶頸接管政策（TOP20_BOTTLENECK_TAKEOVER_V1）：當輪快照若核心瓶頸證據不足（INSUFFICIENT_EVIDENCE）或准入標的數為 0，系統直接回傳專屬診斷說明，嚴格禁止回退發布舊版 20 LIMITED 名單，亦不補零至 20 檔。
- Taiwan timestamps, research-candidate labels and historical-return disclaimer; missing evidence stays missing. Presentation never upgrades LIMITED eligibility.
- 台北時間、研究候選標籤與歷史報酬聲明；缺少證據仍明示缺少，UI 不會把 LIMITED 升級為已驗證論點。

## Rich-menu commands / 三個圖文選單入口

`cloud/src/v213/rich-menu.ts` handles the existing manager-configured message actions **TOP20**, **宏觀產業分析**, **期權** after real LINE admission and rate limiting. It reuses the request-pinned public view and does not send menu requests to the compact model. `選單` exposes the same three actions.

| 入口 | 已實作來源功能 | 仍未完成，不冒充 |
| --- | --- | --- |
| TOP20 | 20家公司、原文名稱、七欄、三個報酬方塊（含2Y總報酬）、同輪綁定深度化分析 | 中文名稱來源尚未核對；系統瓶頸爆發分數 UNAVAILABLE/UNRANKED；沒有可發布的6/12/24月估值產品 |
| 宏觀產業分析 | 當輪20家產業分布、家數占比、完整文字與資料要求 | 家數不是市值權重／資產配置；`MACRO_PRODUCT_NOT_SEALED`，不使用候選GDP/CPI等數值 |
| 期權 | 連到既有「最新期權」查詢（仍適用逐標的freshness門檻）及「期權試算說明」、每週／每月輸入提示 | 選單不依鍵存在宣稱快照；封存輪→`OPTION_DATA_NOT_ADMITTED`（契約物件集合無期權），未封存／舊鍵殘留→`OPTION_DATA_UNAVAILABLE` |

完整資料／完整文字分析指令仍由獨立產品契約處理；不改送選單或產業摘要冒充。部分入口可操作，不表示三類研究產品均已完成。

Visual tokens in `line-theme.ts` follow the black/white mascot artwork: ink monochrome, a three-stop black-to-graphite header gradient, and information levels by lightness (key: ink gradient strip; detail: grey; context: pale grey). Values follow the accounting convention (negatives red, everything else ink) and always keep their +/- sign; no green accent (operator direction 2026-09-25). The existing rich-menu artwork is not uploaded or rescheduled by source edits. Original names are labelled explicitly; Chinese names say unverified rather than guessing. Preserve seven-field values, historic-return warnings and the realized/delayed/not-realized scenario gap.

Card bodies (operator 2026-09-25: bodies read as flat text) use shared visuals from `line-theme.ts`: `richText` bolds figures in running text (signed changes, US$ amounts, percentages; negatives red, dates untouched) using spans only; `meter`, `rankBadge`, `railTitle`, `timelineStep`, `statTile`, `phaseLadder` and `stackedBar`. TOP5 overview: rank badges and opportunity-score meters plus the score composition bar; industry cards: three stat tiles, tagged demand/bottleneck/pricing lines and a 6M→1Y→2Y timeline; macro deep analysis: a ten-step causal timeline; company data reports (潛力報告 and the Top20 detail in Flex mode) are a swipeable carousel with the phase ladder, validated optional `kpis` tiles, numbered sections and a sources page (`… 文字` keeps plain text). Decorative shapes use px thickness as in LINE's own showcases; Top20 seven-field cards are unchanged. `packCarousels` splits by bytes (≤5 bubbles, ≤46,000 bytes) and oversized macro bubbles fall back to spans-free text.

`test/v213-rich-menu.test.ts` exercises the actual authorized caller with mocked LINE, including stale/invalid-pointer negatives, options key-presence/carryover and sealed-round fixtures, and explicit deep-product refusal. Optional `V213_MENU_PREVIEW_OUT` exports **synthetic message objects only**, not tokens/recipients, for local approximate rendering. Exporting HTML is not a successful visual review or device acceptance; no additional server is required or authorized by that export.

## Mobile hierarchy / 手機資訊層級

Shared menu and Top20 detail actions use one secondary `md` button token (light grey ground, ink label) on a white footer; message commands and snapshot-bound references are unchanged. Top20 puts the historical-return warning in the header before prominent return figures. Macro Flex puts the unsealed-product and sample-weight limitations first, then explicitly shows at most five industry groups; `宏觀產業分析 文字` retains every industry and all 20 memberships. This disclosed preview limit is not a universe filter or a truncated Top20 report.

Actual-caller regression, action snapshots and conservative message bounds cover these changes. Local synthetic 390×1900 previews are approximate layout checks only; no original mascot image is replaced, no LINE artwork is uploaded, and device/API visual acceptance remains open. Existing empty/stale/options-admission gates remain unchanged.

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
