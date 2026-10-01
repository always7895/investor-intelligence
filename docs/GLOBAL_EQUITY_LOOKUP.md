# 全球個股快查規範 (Global Equity Lookup Specification)

> **AUTHORITATIVE GLOBAL IDENTITY RESOLVER V1 / 權威全球身分解析器 v1 候選。** 完整規格見 `docs/GLOBAL_IDENTITY_RESOLVER_V1.md` 與 audit `authoritative-global-identity-v1-research.md`。

## 1. 概述 (Overview)
全球個股快查（GLOBAL_EQUITY_LOOKUP）提供使用者直接輸入個股代號或明確股票查詢語法時，在進入通用問答、本機模型推論或工單佇列（issue intake / `問題已收到，參考編號`）之前，立即由系統識別並回傳專屬個股卡片（Flex Bubble 或純文字）。

本模組嚴格遵守以下安全性與架構原則：
1. **最高入口優先攔截**：純代號與明確個股查詢語法優先於通用 Q&A 與本機模型處理，絕不將股票代號查詢轉移至本機 LLM 生成、也不產生臨時工單編號或「查看結果」流程。
2. **零捏造報價 (Fail-Closed Quotation)**：若公開快照中未包含該標的之封存驗收資料，明確顯示 `QUOTE_UNAVAILABLE`（個股資料未封存准入），標示「公開研究資訊，非投資建議」，絕不以模型猜測、舊殘留資料或偽造價格冒充。
3. **無硬編碼公司白名單 (Generic Public Resolver)**：產品程式碼完全移除硬編碼股票／公司字典（如 `CANONICAL_COMPANIES`），不維護私有白名單替換機制；公司查詢依賴明確語法（如「股票 台積電」）並與已封存的公開快照完全比對（Exact Match）。
4. **真實身份與市場標記 (Identity & Suffix Scheme Hints)**：
   - 未附後綴的純代號（如 `SIVE`, `AAPL`, `ASML`）市場一律維持 `UNKNOWN`，不武斷預設美股市場。
   - 純數字代號（如 `2330`, `7203`, `005930`）一律保存原始輸入及前導零，未附後綴時市場維持 `UNKNOWN`，不自動補綴台股、日股或韓股後綴。
   - 帶後綴代號（如 `SIVE.ST`, `7203.T`, `2330.TW`）之後綴僅代表代號命名格式提示（Suffix Scheme Hint），非發行人身份核驗事實；計價幣別在無封存來源時一律為 `UNAVAILABLE`。
   - 移除無公開驗證之 `SIVE` 美國 OTC 描述，不捏造未經證實的次級市場候選。
5. **單一快照視圖防護 (Single Pinned Snapshot View)**：單次查詢中嚴格重用已釘選的 `PublicSnapshotView`，消除重覆釘選（Double-Pin）缺陷，所有來源比對直接綁定當次實際讀取的字節與封存簽章。
6. **名稱與報價防護**：中文名稱在無正式來源驗證時一律顯示「未完成來源核對（不猜譯）」，絕不顯示未驗證之猜測譯名。生產環境數值報價在無審查准入即時管道時一律標記 `UNAVAILABLE`，嚴禁使用當前時鐘假冒報價時間戳。
7. **隱私與安全防護**：不存取任何私人租戶快取（`TENANT_PRIVATE_CACHE`），不回傳任何未授權之內部持倉或偏好，嚴格過濾惡意腳本與網址注入。

---

## 2. 支援市場代號格式提示 (Supported Market Suffix Schemes)

| 市場 | 後綴格式提示 | 範例標的 | 前導零保存 | 說明 |
|---|---|---|---|---|
| **瑞典 (Sweden)** | `.ST` | `SIVE.ST` | 否 | Nasdaq Stockholm 代號格式提示 |
| **英國 (UK)** | `.L` | `IQE.L` | 否 | London Stock Exchange (LSE) 代號格式提示 |
| **歐洲 (Europe)** | `.AS`, `.PA`, `.DE`, `.SW`, `.BR`, `.MI` | `ASML.AS`, `SAP.DE` | 否 | 泛歐／歐洲交易所代號格式提示 |
| **日本 (Japan)** | `.T` | `7203.T`, `6501.T` | 否 | 東京證券交易所 (TSE) 代號格式提示 |
| **韓國 (Korea)** | `.KS` / `.KQ` | `005930.KS` | **是** | KRX KOSPI / KOSDAQ 代號格式提示 |
| **香港 (Hong Kong)** | `.HK` | `0700.HK` | **是** | 香港交易所 (HKEX) 代號格式提示 |
| **中國上海 (SSE)** | `.SS` / `.SH` | `600519.SS` | **是** | 上證代號格式提示 |
| **中國深圳 (SZSE)** | `.SZ` | `000001.SZ` | **是** | 深證代號格式提示 |
| **中國北京 (BSE)** | `.BJ` | `830000.BJ` | **是** | 北交所代號格式提示 |
| **台灣 (Taiwan)** | `.TW` / `.TWO` | `2330.TW`, `2454.TW` | 否 | TWSE / TPEx 代號格式提示 |
| **未指定後綴 (Bare)** | 無後綴 | `SIVE`, `AAPL`, `2330`, `005930` | **是** | 市場標記為 UNKNOWN，需輸入後綴或待快照准入 |

---

## 3. 明確查詢語法與自然語言問答邊界 (Explicit Grammar & Prose Separation)
- **明確個股查詢語法**：以「股票」、「個股」、「查股價」、「ticker」、「stock」等前綴開頭者，如「股票 台積電」、「個股 2330.TW」，進入個股快查流程，比對封存快照；若未封存則顯示標的資料未准入卡片，不流入通用問答。
- **純代號輸入**：符合標準代號語法者（如 `AAPL`, `SIVE`, `0700.HK`）直接進入個股快查。
- **自然語言與日常問答**：無前綴之中文句子（如「什麼是量化投資？」、「今天天氣如何」、「台積電的營收如何？」、「請問台股明天會漲嗎」）保持通用 Q&A 路由。
- **系統保留指令**：`TOP20`、`宏觀產業分析`、`期權`、`選單`、`幫助`、`健康`、`早報`、`晚報` 等絕不誤判為個股代號。

---

## 4. 查驗與測試驗證 (Verification)
- 單元測試套件：`cloud/test/v213-global-equity-lookup.test.ts`
- Worker 完整流程測試：`cloud/test/v213-global-equity-worker-flow.test.ts`
- 驗證重點涵蓋：
  1. `sive` / `Sive` / `SIVE` 大小寫變體均攔截並回傳專屬個股快查卡片，不進入 issue intake 或本機模型。
  2. 多國市場代號與前導零保存（如 `005930`、`0700.HK`、`000001`）。
  3. 未附後綴之純數字與純英文字母標記為 `UNKNOWN`，無武斷預設。
  4. 單一公共快照視圖釘選與報告讀取，無 Double-pin。
  5. 未完成來源核對之中文名稱嚴格顯示「未完成來源核對（不猜譯）」。
  6. 未封存報價之 `QUOTE_UNAVAILABLE` 防護，絕不顯現假報價或將查詢時鐘偽充為報價時間。
