# TASK0-3E_CLAIM_SOURCE_FEASIBILITY

## 目標
找出「哪些具體公司主張需要什麼獨立佐證，以及現有資料是否已包含它」，不是機械式替每個 ticker 補第二個 URL。

## BOUND_INPUTS
- normalized_top20: .tmp/3d_fullgate_normalized_top20.json (SHA256=eed85d11582deeb61f782fe6ce61f1cc6a3a3d799ce5dd2b5e84e99b6a056109)
- audit: .tmp/3d_fullgate_audit.json (SHA256=89d46207b849ea1c35a510cf1aa9db5ebd55ce4b779c525184774d60bee67327)
- policy: config/v213-serenity-evidence-freshness-policy.json (SHA256=c5de9faf09b16f3f79b1969db9b95b6cb5600d347554455be8610def10720195)
- **實際 source-independence policy**: config/v213-serenity-public-logic-policy.json（本次 audit 顯示來源多樣性不足；該 policy 分別定義 portfolio source diversity 與逐筆 high-confidence eligibility，不是一條「每個 ticker 找到兩個 domain/family 就全部通過」的規則）

## SOURCE_IDENTITY_MAPPING (step 1 修正)
- 75/60 是原始欄位差集，**不是來源遺失/新增的分類結果**（兩側採用不同表示方式：domain、family、URL、日期）
- 修正方式：保留原始欄位，再依受審 source 的正規化、分類與 (domain, family, claim_type) 去重規則，建立來源到 audit 的對應
- 對差異分別標記：CANONICALIZED / DEDUPED_WITH_IDENTIFIED_REPRESENTATIVE / ADDED_BY_BUILDER / UNEXPLAINED
- 本輪只需把 TAL、SMCI、GAP 三個代表案例追清楚；其他 17 筆可保留原始盤點及未解分類

## REPRESENTATIVE_TICKERS / MATERIAL_CLAIMS (step 2 修正：3 張 claim card)

### Claim Card 1: TAL (TAL Education Group)
- claim_id: TAL-REV-2026
- ticker: TAL
- entity: TAL Education Group
- metric namespace/tag: us-gaap:Revenues
- value: 3,008,908,000
- currency: USD
- unit: dollars
- accounting basis: US-GAAP
- period_start: 2025-03-01
- period_end: 2026-02-28
- filed_at: 2026-06-12
- retrieved_at: 2026-09-15T18:53:15Z
- source URL: https://www.sec.gov/Archives/edgar/data/1499620/000110465926073410/
- accession: 0001104659-26-073410
- local JSON locator: data/cache/v21/companyfacts/CIK0001499620.json.source-v1.json
- content SHA256: (需計算)
- 該主張支持的用途: 財務事實（營收）
- 未被該主張證明的事項: 成長率、訂單、市場份額、產能、供應關係

### Claim Card 2: SMCI (Super Micro Computer, Inc.)
- claim_id: SMCI-REV-2026
- ticker: SMCI
- entity: Super Micro Computer, Inc.
- metric namespace/tag: us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax
- value: 39,063,072,000
- currency: USD
- unit: dollars
- accounting basis: US-GAAP
- period_start: 2025-07-01
- period_end: 2026-06-30
- filed_at: 2026-08-31
- retrieved_at: 2026-09-15T18:53:15Z
- source URL: https://www.sec.gov/Archives/edgar/data/1375365/000137536526000022/
- accession: 0001375365-26-000022
- local JSON locator: data/cache/v21/companyfacts/CIK0001375365.json.source-v1.json
- content SHA256: (需計算)
- 該主張支持的用途: 財務事實（營收）
- 未被該主張證明的事項: 成長率、訂單、市場份額、產能、供應關係

### Claim Card 3: GAP (GAP INC)
- claim_id: GAP-REV-2026Q2
- ticker: GAP
- entity: GAP INC
- metric namespace/tag: us-gaap:Revenues
- value: 3,651,000,000
- currency: USD
- unit: dollars
- accounting basis: US-GAAP
- period_start: 2026-05-03
- period_end: 2026-08-01
- filed_at: 2026-08-28
- retrieved_at: 2026-09-15T18:53:15Z
- source URL: https://www.sec.gov/Archives/edgar/data/39911/000162828026059345/
- accession: 0001628280-26-059345
- local JSON locator: data/cache/v21/companyfacts/CIK0000039911.json.source-v1.json
- content SHA256: (需計算)
- 該主張支持的用途: 財務事實（營收）
- 未被該主張證明的事項: 成長率、訂單、市場份額、產能、供應關係

## GAP_CLASSIFICATION
- ADDITIONAL_INDEPENDENT_SUPPORT_NEEDED: 每個 ticker 需要第二個獨立 claim source（不同 domain/family）
- CANDIDATE_UNVERIFIED: 候選來源未查證
- 只有一種缺口類型（所有 20 tickers: claim_domains=['sec.gov'], claim_families=['regulator_filing'], eligible=False）

## CANDIDATE_SOURCES (step 3 修正：依用途分開)

### 候選方向 1: 公司 IR/財報原文
- 用途: 補完整口徑、期間、原始表格，或交叉檢查擷取正確性
- 分類: CANDIDATE_UNVERIFIED（未查證）
- 注意: 公司 IR 與 SEC 上的同一份公司財務披露，即使 domain 不同，也不能因此視為新增獨立佐證
- origin_status: unverified

### 候選方向 2: 新聞/分析師資料
- 用途: 查明是否有原創、可核對且與目標 claim 可比較的資訊
- 分類: CANDIDATE_UNVERIFIED（未查證）
- 注意: 文章可能重述公司披露，也可能有自行訪查、估計或驗證；沒有具體文章與內容，就只能記 ORIGIN_UNVERIFIED
- origin_status: unverified

### 候選方向 3: 合約對手、客戶、採購/監管文件
- 用途: 僅在目標是相應訂單、產能、供應關係主張時列為候選方向
- 分類: CANDIDATE_UNVERIFIED（未查證）
- 注意: 本次 3 張 claim card 的目標是財務事實（營收），不是訂單/產能/供應關係，所以此候選方向不適用
- origin_status: unverified

### 候選方向 4: 其他 SEC filings
- 用途: 同一 domain 通常不增加 domain 多樣性
- 分類: CANDIDATE_UNVERIFIED（未查證；Company Facts 的 CIK cache 存在，不代表相應 8-K/proxy 原文已錄製）
- 注意: 同一 domain 通常不增加 domain 多樣性，但不表示每份文件都被排除或沒有其他佐證用途
- origin_status: unverified

## ACQUISITION/DISCOVERY REQUESTS (最多 3 個具體請求)

### Request 1: TAL-REV-2026 (公司 IR/財報原文交叉檢查)
- request_type: EXISTING_DATA_EXTRACTION
- target_claim_id: TAL-REV-2026
- known URL: https://www.sec.gov/Archives/edgar/data/1499620/000110465926073410/
- expected_fields: 公司名稱、Revenues、期間（2025-03-01 to 2026-02-28）、filed date（2026-06-12）
- expected_use: same_origin_crosscheck（交叉檢查 SEC filing 的營收數據與公司 IR 網站是否一致）
- origin_status: unverified
- existing_parser_or_adapter: 現有 parser 已支持 SEC filings（us-gaap:Revenues）
- public_free_access_requirement: 是（SEC filings 免費公開）
- proposed_output_root: _workspace/audit-runtime/task0-3e/TAL-REV-2026/
- execution_status: NOT_EXECUTED
- 找什麼: 公司 IR 網站的營收數據（與 SEC filing 交叉檢查）
- 為何需要: 確認 SEC filing 的營收數據正確（same_origin_crosscheck）
- 可能支持哪個條件: 確認現有數據正確（不增加 domain 多樣性）
- 不能支持什麼: 不提供第二個獨立 domain（公司 IR 與 SEC 同源）

### Request 2: SMCI-REV-2026 (新聞/分析師資料探索)
- request_type: PUBLIC_DISCOVERY
- target_claim_id: SMCI-REV-2026
- known URL: 無（需探索）
- 目標機構: 新聞媒體（Reuters, Bloomberg）、分析師（Gartner, IDC）
- 文件類型: 財報摘要、行業分析
- 期間: 2025-07-01 to 2026-06-30
- 搜尋條件: "Super Micro Computer" revenue 2026
- expected_fields: 公司名稱、RevenueFromContractWithCustomer、期間（2025-07-01 to 2026-06-30）
- expected_use: independent_support_candidate（探索是否有原創、可核對且與目標 claim 可比較的資訊）
- origin_status: unverified
- existing_parser_or_adapter: 無（需要新的 adapter）
- public_free_access_requirement: 部分（新聞媒體可能有付費牆）
- proposed_output_root: _workspace/audit-runtime/task0-3e/SMCI-REV-2026/
- execution_status: NOT_EXECUTED
- 找什麼: 新聞/分析師的營收數據（與 SEC filing 比較）
- 為何需要: 探索是否有第二個獨立 domain 提供相同營收數據
- 可能支持哪個條件: 如果找到原創、可核對的資訊，可能提供第二個獨立 domain
- 不能支持什麼: 如果文章只是重述公司披露，不提供第二個獨立 domain

### Request 3: GAP-REV-2026Q2 (NO_SUITABLE_CANDIDATE_IDENTIFIED)
- request_type: NO_SUITABLE_CANDIDATE_IDENTIFIED
- target_claim_id: GAP-REV-2026Q2
- known URL: 無
- expected_fields: N/A
- expected_use: N/A
- origin_status: unverified
- existing_parser_or_adapter: N/A
- public_free_access_requirement: N/A
- proposed_output_root: N/A
- execution_status: NOT_EXECUTED
- 說明: 本次 3 張 claim card 的目標是財務事實（營收），不是訂單/產能/供應關係。合約對手、客戶、採購/監管文件等候選方向不適用。新聞/分析師資料可能只是重述公司披露，不提供第二個獨立 domain。公司 IR 與 SEC 同源，不提供第二個獨立 domain。因此，本次沒有找到具體合格的第二個獨立 claim source。
- 注意: 這比為通過 gate 而假定存在第二來源更有用

## RECOMMENDED_NEXT_ACTION
1. 執行 Request 1（TAL-REV-2026 公司 IR/財報原文交叉檢查）：確認 SEC filing 的營收數據正確
2. 執行 Request 2（SMCI-REV-2026 新聞/分析師資料探索）：探索是否有第二個獨立 domain 提供相同營收數據
3. Request 3（GAP-REV-2026Q2）：NO_SUITABLE_CANDIDATE_IDENTIFIED（本次沒有找到具體合格的第二個獨立 claim source）

## POLICY_OR_APPLICATION_CHANGED: false
## NEW_SOURCE_FETCHES: 0
## PRODUCTION_TOUCHED: false

## 結論
- 所有 20 tickers 有相同的缺口類型：只有 sec.gov 一個 claim domain、只有 regulator_filing 一個 claim family
- 每個 ticker 需要第二個獨立 claim source（不同 domain/family）才能通過 source independence gate
- 3 張 claim card 已用實際 tag 與數值（us-gaap:Revenues / us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax）
- 候選來源（公司 IR 網站、新聞/分析師資料）都是 CANDIDATE_UNVERIFIED（未查證）
- 公司 IR 與 SEC 同源，不提供第二個獨立 domain
- 新聞/分析師資料可能只是重述公司披露，不提供第二個獨立 domain
- 本次沒有找到具體合格的第二個獨立 claim source（NO_SUITABLE_CANDIDATE_IDENTIFIED）
- 本輪不執行新來源抓取；提出具體的 acquisition request 供後續決策
- 不以找到可准入 ticker、提高分數或把 gate 變成 PASS 作為成功條件