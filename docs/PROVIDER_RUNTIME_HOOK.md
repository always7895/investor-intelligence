# 提供者執行時期掛鉤規範與信任邊界 (PROVIDER_RUNTIME_HOOK_V1)

本文件定義提供者執行時期掛鉤（Provider Runtime Hook V1）的架構規範、信任邊界與安全驗證原則。

## 核心設計原則與信任鏈條

依據權威管線設計，執行時期能力註冊並不等於授予法律權利或語意認可。任何來源欲進入公司要素准入，必須遵循不可省略的五階信任鏈條：

```
已註冊能力 (Registered Capability)
    ↓
特定已審查權利範疇 (Specific Reviewed Rights Scope)
    ↓
來源時效性與事件時鐘 (Source Freshness & Event Clock)
    ↓
真實自有的規範性觀測 (Real Owned Canonical Observations)
    ↓
要素特定綁定權威 (Factor-Specific Binding Authority)
```

若權利狀態為未知（UNKNOWN）或需要審查（REQUIRES_REVIEW），系統必須嚴格採取 **DEFER / UNAVAILABLE**（暫緩／不可用），絕不自動允許（AUTOALLOW）。

## 安全邊界與不變量 (Invariants)

1. **現有工廠呼叫單次證據建構器**：
   - 現有工廠函式 `acquire_runtime_sources` 識別已註冊的介面能力（`ProviderCapability`），並在批次解析通過後單次呼叫其註冊的真實證據建構器（evidence builder）。
   - 杜絕影子 CLI 或未使用的孤立介面。
2. **正式環境預設關閉與嚴格阻斷 (Fail-Closed)**：
   - 新介面能力預設在正式環境中禁用（`is_live_enabled = False`），直到其條款審查狀態與權利取得正式政策批准。
   - 原型介面的存在絕不得自動啟用全域執行時期目錄（`config/sources`）中的來源。
3. **分發器自主驗證 vs 呼叫方偽造阻斷**：
   - 分發器（Dispatcher）依據自有註冊表核對允許的來源代號（`source_id`）、主機網域（`allowed_hosts`）、內文種類（`allowed_body_kinds`）、解析器版本（`parser_version`）及能力範圍。
   - 呼叫方自帶的核准旗標（如 `approved=True`、`runtime_admitted=True`）、偽造註冊表、竄改健康狀態、或未經驗證的字典回傳，絕無法引導或自舉（bootstrap）系統信任。
4. **分動作細粒度權利審查 (Granular Rights Review per Action)**：
   - 權利審查針對六大動作獨立劃分：
     1. `internal_factual_research`（內部事實研究）
     2. `paraphrase`（事實改寫）
     3. `brief_quotation`（簡要引述）
     4. `statutory_text`（法定條文參照）
     5. `public_redistribution`（公開再分發）
     6. `raw_document_reproduction`（原始文本全文重製）
   - 若特定動作之權利為 UNKNOWN 或 REQUIRES_REVIEW，僅阻止該公開或發布角色，不擴大宣稱事實本身違法；但未獲許可之觀測絕不得作為公開要素或公司准入事實。
   - 審查矩陣（A-matrix）為審查過程產物（review artifact），非註冊之法定認證。
5. **規範性綁定必須參照同一次真實執行的觀測**：
   - 要素綁定（`CompanyFactorBinding`）必須精確參照相同真實執行作業（`AcquisitionRun`）中的規範性觀測代號（`canonical_observation_ids`）。
   - 跨次執行代號竄改（`CROSS_RUN_MUTATION`）、懸空或變造之觀測代號（`DANGLING_CANONICAL_OBSERVATION_ID`）、主題、產品規格、區域、單位、期間或系譜不符者，一律嚴格失敗阻斷。
6. **CARB 法規解析器邊界與當前零錄取**：
   - 類型化 CARB 解析器保留加州法規 CCR Title 17 §§ 95350-95359.1 之真實版本、Table 1 (≤ 38 kV) 與 Table 2 (> 38 kV) 電壓及短路電流（kA）門檻、逐步淘汰收購日、例外條件及 7 項未解析外部參照。
   - CARB 法規政策脈絡絕不等於特定公司（如 Meiden）之定價權或股權價值捕獲；技術手冊亦不等於現行產能。
   - 缺少四核心要素（相依性、稀缺性、定價權、價值捕獲）之任一項時，公司維持 UNRANKED，當前公司准入總數嚴格為 0。
7. **相容性與隱私邊界**：
   - 保留既有總體經濟（Macro）與歐洲央行（ECB）等非公司觀測管線之相容性，可選之公司主張不得破壞標準日常採集。
   - 嚴格阻斷機密欄位（如 `raw_line_id`、`line_user_id`、`account_id`、`cost_basis`），靜態錯誤代碼，絕不洩漏私有路徑、認證資訊或追蹤堆疊。

## 相關文件

- [COMPANY_CLAIM_ADMISSION_BRIDGE](COMPANY_CLAIM_ADMISSION_BRIDGE.md)
- [CARB_TYPED_SECTION_PARSER](CARB_TYPED_SECTION_PARSER.md)
- [COMPANY_EVIDENCE_CANDIDATES](COMPANY_EVIDENCE_CANDIDATES.md)
- [BOTTLENECK_RANKING_V1](BOTTLENECK_RANKING_V1.md)
- [文件索引](README.md)
