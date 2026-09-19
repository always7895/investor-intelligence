# TASK0-3E_CLAIM_SOURCE_FEASIBILITY

## 目標
找出「哪些具體公司主張需要什麼獨立佐證，以及現有資料是否已包含它」，不是機械式替每個 ticker 補第二個 URL。

## BOUND_INPUTS
- normalized_top20: .tmp/3d_fullgate_normalized_top20.json (SHA256=eed85d11582deeb61f782fe6ce61f1cc6a3a3d799ce5dd2b5e84e99b6a056109)
- audit: .tmp/3d_fullgate_audit.json (SHA256=89d46207b849ea1c35a510cf1aa9db5ebd55ce4b779c525184774d60bee67327)
- policy: config/v213-serenity-evidence-freshness-policy.json (SHA256=c5de9faf09b16f3f79b1969db9b95b6cb5600d347554455be8610def10720195)

## SOURCE_IDENTITY_MAPPING (step 1)
- claim_type_set_equal: 0/20（claim-type 集合不等）
- input_not_in_audit: 75（去重的 xbrl_fact 項目）
- audit_not_in_input: 60（market_return_calculation sources）
- **claim-type 集合比較不充分**（不同來源同 claim_type 未被區分）

## GAP TYPE (all 20 tickers)
**只有一種缺口類型**（依 Pro 指示明確記錄，不製造三種分類）：
- claim_domains: ['sec.gov']（1 domain）
- claim_families: ['regulator_filing']（1 family）
- claim_primary: 2
- eligible: False
- 缺口：每個 ticker 需要第二個獨立 claim source（不同 domain/family）才能通過 source independence gate

## REPRESENTATIVE_TICKERS / MATERIAL_CLAIMS (step 2)

### TAL (TAL Education Group)
- Material claims: Revenue, GrossProfit, OperatingIncomeLoss, NetIncomeLoss（20-F, 2026-02-28）
- 已有佐證: SEC 20-F filing (sec.gov) — 唯一 claim domain
- 缺少: 第二個獨立 claim source（不同 domain/family）提供相同財務指標

### SMCI (Super Micro Computer, Inc.)
- Material claims: RevenueFromContractWithCustomer, GrossProfit, OperatingIncomeLoss, NetIncomeLoss（10-K, 2026-06-30）
- 已有佐證: SEC 10-K filing (sec.gov) — 唯一 claim domain
- 缺少: 第二個獨立 claim source（不同 domain/family）提供相同財務指標

### GAP (GAP INC)
- Material claims: Revenues, GrossProfit, OperatingIncomeLoss（10-Q, 2026-08-01）
- 已有佐證: SEC 10-Q filing (sec.gov) — 唯一 claim domain
- 缺少: 第二個獨立 claim source（不同 domain/family）提供相同財務指標

## GAP_CLASSIFICATION
- ADDITIONAL_INDEPENDENT_SUPPORT_NEEDED: 每個 ticker 需要第二個獨立 claim source
- CANDIDATE_UNVERIFIED: 候選來源未查證

## CANDIDATE_SOURCES (step 3)

### 候選來源類型
1. **公司自己的 Investor Relations 網站**（e.g., tal-education.com, supermicro.com, gapinc.com）
   - 分類: CANDIDATE_UNVERIFIED（未查證）
   - 是否已有 recorded body: 否
   - 是否需要新取得: 是
   - 現有 parser/資料結構能否承接: 需評估（目前的 parser 是針對 SEC filings 設計的）
   - 原始資訊來源: 公司自己的財務報告（與 SEC filing 同源，但 domain 不同）
   - 注意: 公司 IR 網站的財務數據與 SEC filing 同源（公司自己的財務報告），不一定提供「新增的、可核對的佐證」

2. **行業分析師報告**（e.g., Gartner, IDC）
   - 分類: CANDIDATE_UNVERIFIED（未查證）
   - 是否已有 recorded body: 否
   - 是否需要新取得: 是
   - 現有 parser/資料結構能否承接: 需評估
   - 原始資訊來源: 分析師的獨立研究（與 SEC filing 不同源）
   - 注意: 分析師報告可能提供市場份額、成長率等獨立佐證，但不一定有具體的財務指標（Revenue、GrossProfit 等）

3. **新聞文章**（e.g., Reuters, Bloomberg）
   - 分類: CANDIDATE_UNVERIFIED（未查證）
   - 是否已有 recorded body: 否
   - 是否需要新取得: 是
   - 現有 parser/資料結構能否承接: 需評估
   - 原始資訊來源: 新聞報導（與 SEC filing 不同源）
   - 注意: 新聞文章可能提供財報摘要，但通常不與 SEC filing 的財務指標完全一致

4. **其他 SEC filings**（e.g., 8-K, proxy statements）
   - 分類: EXISTING_SOURCE_EXCLUDED_WITH_REASON（sec.gov 同 domain，不提供第二個獨立 domain）
   - 是否已有 recorded body: 部分（公司facts 目錄有 CIK 檔案）
   - 是否需要新取得: 否（已有）
   - 現有 parser/資料結構能否承接: 是（目前的 parser 已支持 SEC filings）
   - 注意: 其他 SEC filings 仍是 sec.gov（同 domain），不提供第二個獨立 domain

## NEW_ACQUISITION_NEEDED (exact scope, not executed)
- 目標: 取得第二個獨立 claim source（不同 domain/family）提供相同財務指標
- 用途: 通過 source independence gate（claim_domains >= 2, claim_families >= 2）
- 預期欄位: 公司名稱、財務指標（Revenue、GrossProfit 等）、期間、來源日期
- 儲存位置: data/cache/v21/companyfacts/（或新的獨立目錄）
- 必要性: 高（目前所有 20 tickers 都只有 sec.gov 一個 claim domain）
- **本輪不執行**（不包含新市場/SEC/公司網站抓取、provider probe、批次下載、登入、credentials、付費來源或 collector 實作）

## RECOMMENDED_NEXT_ACTION
1. 評估公司 IR 網站作為第二個獨立 claim source 的可行性（同源但不同 domain，需確認是否提供「新增的、可核對的佐證」）
2. 評估行業分析師報告作為第二個獨立 claim source 的可行性（不同源，但可能沒有具體財務指標）
3. 確認現有 parser/資料結構能否承接新的來源類型
4. 如果候選來源可行，提出具體的 acquisition request（目標、用途、預期欄位、儲存位置及必要性）

## POLICY_OR_APPLICATION_CHANGED: false
## NEW_SOURCE_FETCHES: 0
## PRODUCTION_TOUCHED: false

## 結論
- 所有 20 tickers 有相同的缺口類型：只有 sec.gov 一個 claim domain、只有 regulator_filing 一個 claim family
- 每個 ticker 需要第二個獨立 claim source（不同 domain/family）才能通過 source independence gate
- 候選來源（公司 IR 網站、行業分析師報告、新聞文章）都是 CANDIDATE_UNVERIFIED（未查證）
- 本輪不執行新來源抓取；提出具體的 acquisition request 供後續決策
- 不以找到可准入 ticker、提高分數或把 gate 變成 PASS 作為成功條件