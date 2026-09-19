# TASK0-3E_CLAIM_SOURCE_FEASIBILITY

## 目標
找出「哪些具體公司主張需要什麼獨立佐證，以及現有資料是否已包含它」，不是機械式替每個 ticker 補第二個 URL。

## SOURCE_INDEPENDENCE_POLICY_SHA256
- config/v213-serenity-public-logic-policy.json (SHA256=421d70b2bbaa7929832f2108decda9d8fd3bc185292ef88c7cedfe6ad7f3476e)
- 該 policy 分別定義 portfolio source diversity 與逐筆 high-confidence eligibility，不是一條「每個 ticker 找到兩個 domain/family 就全部通過」的規則

## DOMAIN ≠ 獨立資訊來源 (概念修正)
- 同一份公司披露在 IR 與 SEC 出現，可以位於不同 domain，但仍可能具有相同資訊 origin，不能僅因此增加獨立佐證
- 新聞轉述也一樣：它可能增加一個出版網域，卻沒有增加新的資訊來源
- repo 的 lineage 計算本來就會依 origin_group、independence_group 或內容 hash 合併 observations，並非只數 domain
- 因此，「每個 ticker 需要第二個獨立 claim source 才能通過 gate」應撤回
- 本輪統一記為:
  - OBSERVED_AUDIT_SOURCE_DIVERSITY: LIMITED
  - SOURCE_MAPPING_FOR_REPRESENTATIVES: PENDING_RESULTS → COMPLETE (本次)
  - ADDITIONAL_INDEPENDENT_SUPPORT_NEEDED: TO_BE_DETERMINED_PER_CLAIM
  - ADMISSION_OR_HIGH_CONFIDENCE_UPLIFT: NOT_ESTABLISHED

## CLAIM_CARDS (3 張卡，recorded hashes + observation locators + verification result)

### Claim Card 1: TAL (TAL Education Group)
- claim_id: TAL-REV-2026
- recorded_file_path: data/cache/v21/companyfacts/CIK0001499620.json.source-v1.json
- recorded_file_sha256: 81fa07273395a8865199999a9e9035267c7ed5894cba3fb6f17cc41ab5e16a75
- saved_body_sha256: 2cf3cee36c550e20279fe31e0f7f4f94e59ff4a5f28f19525cbc2796bcdf2297
- hash_basis: wrapper bytes
- json_locator: facts.us-gaap.Revenues.units.USD
- namespace_tag: us-gaap:Revenues
- units: USD
- observation_selector: accession=0001104659-26-073410, start=2025-03-01, end=2026-02-28, filed=2026-06-12, form=20-F
- matches_count: 1
- selected_value: 3,008,908,000
- expected_value: 3,008,908,000
- verification: **PASS**
- 該主張支持的用途: 財務事實（營收）
- 未被該主張證明的事項: 成長率、訂單、市場份額、產能、供應關係

### Claim Card 2: SMCI (Super Micro Computer, Inc.)
- claim_id: SMCI-REV-2026
- recorded_file_path: data/cache/v21/companyfacts/CIK0001375365.json.source-v1.json
- recorded_file_sha256: 144790d14acbaff4b2da3cb8a24218451969e3bf23e2a4ce8658f58e953dff4b
- saved_body_sha256: 039172a7eec0fe46077ce444eb12280a0e625f5cec313c058903ec7016d82794
- hash_basis: wrapper bytes
- json_locator: facts.us-gaap.RevenueFromContractWithCustomerExcludingAssessedTax.units.USD
- namespace_tag: us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax
- units: USD
- observation_selector: accession=0001375365-26-000022, start=2025-07-01, end=2026-06-30, filed=2026-08-31, form=10-K
- matches_count: 1
- selected_value: 39,063,072,000
- expected_value: 39,063,072,000
- verification: **PASS**
- 該主張支持的用途: 財務事實（營收）
- 未被該主張證明的事項: 成長率、訂單、市場份額、產能、供應關係

### Claim Card 3: GAP (GAP INC)
- claim_id: GAP-REV-2026Q2
- recorded_file_path: data/cache/v21/companyfacts/CIK0000039911.json.source-v1.json
- recorded_file_sha256: 8e4c4e80cdc926ee949f7eaab422658d4fb54e5617ece8924dbd0efa13f2204a
- saved_body_sha256: 683ad2f5c630e295244e8d68c36b213e39a2107a6d4d8c164a8bd10f9c82d139
- hash_basis: wrapper bytes
- json_locator: facts.us-gaap.Revenues.units.USD
- namespace_tag: us-gaap:Revenues
- units: USD
- observation_selector: accession=0001628280-26-059345, start=2026-05-03, end=2026-08-01, filed=2026-08-28, form=10-Q
- matches_count: 1
- selected_value: 3,651,000,000
- expected_value: 3,651,000,000
- verification: **PASS**
- 該主張支持的用途: 財務事實（營收）
- 未被該主張證明的事項: 成長率、訂單、市場份額、產能、供應關係

## SOURCE_MAPPINGS (TAL / SMCI / GAP 實際結果)

### TAL source mapping
- evidence[0]: MATCHED (matched_audit=sources[0], reason=URL + claim_type match)
- evidence[1]: MATCHED (matched_audit=sources[1], reason=URL + claim_type match)
- evidence[2]: MATCHED (matched_audit=sources[1], reason=URL + claim_type match)
- evidence[3]: MATCHED (matched_audit=sources[1], reason=URL + claim_type match)
- evidence[4]: MATCHED (matched_audit=sources[1], reason=URL + claim_type match)
- evidence[5]: UNEXPLAINED (matched_audit=None, reason=UNEXPLAINED: input evidence [evidence[5]] (url=https://www.sec.gov/Archives/edgar/data/1499620/000141057825001415/, claim_type=xbrl_fact) has no matching audit source)

### SMCI source mapping
- evidence[0]: MATCHED (matched_audit=sources[0], reason=URL + claim_type match)
- evidence[1]: MATCHED (matched_audit=sources[1], reason=URL + claim_type match)
- evidence[2]: MATCHED (matched_audit=sources[1], reason=URL + claim_type match)
- evidence[3]: MATCHED (matched_audit=sources[1], reason=URL + claim_type match)
- evidence[4]: MATCHED (matched_audit=sources[1], reason=URL + claim_type match)
- evidence[5]: UNEXPLAINED (matched_audit=None, reason=UNEXPLAINED: input evidence [evidence[5]] (url=https://www.sec.gov/Archives/edgar/data/1375365/000137536525000014/, claim_type=xbrl_fact) has no matching audit source)

### GAP source mapping
- evidence[0]: MATCHED (matched_audit=sources[0], reason=URL + claim_type match)
- evidence[1]: MATCHED (matched_audit=sources[1], reason=URL + claim_type match)
- evidence[2]: MATCHED (matched_audit=sources[1], reason=URL + claim_type match)
- evidence[3]: MATCHED (matched_audit=sources[1], reason=URL + claim_type match)
- evidence[4]: UNEXPLAINED (matched_audit=None, reason=UNEXPLAINED: input evidence [evidence[4]] (url=https://www.sec.gov/Archives/edgar/data/39911/000162828026059345/, claim_type=xbrl_fact) has no matching audit source)
- evidence[5]: UNEXPLAINED (matched_audit=None, reason=UNEXPLAINED: input evidence [evidence[5]] (url=https://www.sec.gov/Archives/edgar/data/39911/000162828025001415/, claim_type=xbrl_fact) has no matching audit source)

## UNRESOLVED_ITEMS (exact rows / fields / missing evidence)
- TAL evidence[5]: UNEXPLAINED (前一年營收觀察值 2025-02-28 無對應 audit source)
- SMCI evidence[5]: UNEXPLAINED (前一年營收觀察值 2025-06-30 無對應 audit source)
- GAP evidence[4]: UNEXPLAINED (10-K 2026-01-31 營收觀察值無對應 audit source)
- GAP evidence[5]: UNEXPLAINED (10-K 2025-02-01 營收觀察值無對應 audit source)
- 共 4 個 UNEXPLAINED 項目（前一年營收觀察值無對應 audit source）

## REQUEST_STATUS (Request 1、2、3 執行狀態分開)
- Request 1: TAL-REV-2026 → **LOCAL_RECORDED_EXTRACTION** (本機 recorded-data 核對，已執行；3 張卡全部驗證通過)
- Request 2: SMCI-REV-2026 → **PROPOSED_NOT_EXECUTED** (PUBLIC_DISCOVERY 提案，本輪不執行)
- Request 3: GAP-REV-2026Q2 → **NO_CANDIDATE_IDENTIFIED_IN_REVIEWED_MATERIALS** (有限範圍的研究結果，不是 acquisition request，也不代表外部世界不存在合適來源)

## POLICY_OR_APPLICATION_CHANGED: false
## NEW_SOURCE_FETCHES: 0
## PRODUCTION_TOUCHED: false

## 結論
- 3 張 claim card 可由既有 recorded input 重現（3/3 驗證通過）
- 3 個代表案例有實際來源對照（TAL 5 MATCHED + 1 UNEXPLAINED, SMCI 5 MATCHED + 1 UNEXPLAINED, GAP 4 MATCHED + 2 UNEXPLAINED）
- 4 個 UNEXPLAINED 項目（前一年營收觀察值無對應 audit source）
- domain ≠ 獨立資訊來源（同一份公司披露在 IR 與 SEC 出現，可以位於不同 domain，但仍可能具有相同資訊 origin）
- OBSERVED_AUDIT_SOURCE_DIVERSITY: LIMITED; ADDITIONAL_INDEPENDENT_SUPPORT_NEEDED: TO_BE_DETERMINED_PER_CLAIM; ADMISSION_OR_HIGH_CONFIDENCE_UPLIFT: NOT_ESTABLISHED
- 請求類型、用途、已知資料與外連需求一致；不宣稱第二來源會自動帶來 gate/admission 通過
- 本輪不執行新來源抓取；不跑 gate；不改 application/policy；不重開已結案的 step B
- 完成不要求找到新來源，也不要求所有 mapping 都沒有未解項

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