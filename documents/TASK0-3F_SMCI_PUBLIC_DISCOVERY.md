# TASK0-3F_SMCI_PUBLIC_DISCOVERY

## 目標
只圍繞 SMCI-REV-2026（us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax, 2025-07-01 至 2026-06-30, USD 39,063,072,000）執行有限公開探索。

## 授權範圍
- 公開搜尋: 允許搜尋 SMCI FY2026 營收、對應申報與相關新聞
- 候選正文讀取/保存: 允許讀取 SEC、公司官方 IR、公開新聞及其他直接相關的免費正文
- 本機分析: 允許抽取原文數值、單位、期間、發布日期、引用關係
- 程式與政策: 不改 application source、source registry、parser 生產接線、評分、freshness、evidence gates 或 admission
- 正式環境: Production/KV/DO/排程/真 LINE/credentials/billing/部署全部維持禁止

## 本輪預算
- 最多 8 次搜尋（實際: 4 次）
- 最多 12 份候選正文（實際: 3 份 SUCCESS, 1 份 FAILED_401, 4 份 NOT_FETCHED）
- 序列取得、每個失敗來源最多一次有限重試

## 3F-0: 固定比較基準
- source HEAD: 6f9c433e356cf34edb5d63fa8b7bb643162cf280
- branch: fix/options-provenance-audit
- recorded_file: data/cache/v21/companyfacts/CIK0001375365.json.source-v1.json
- recorded_file_sha256: 144790d14acbaff4b2da3cb8a24218451969e3bf23e2a4ce8658f58e953dff4b
- baseline_manifest_sha256: f9902de5eeece27bbeaaad93d77a2bd0ed15f6f46648598f85fb8a9589a3211c

## 3F-1: 原始披露核對
- SEC 10-K: EXACT_MATCH (USD 39,063,072,000, final/audited, filed 2026-08-31)
- 公司 press release (Exhibit 99.1): ROUNDING_COMPATIBLE (USD 39.1 billion, preliminary/unaudited, published 2026-08-11)
- Origin relation: SAME_ORIGIN_CROSSCHECK / SAME_ORIGIN_REPUBLICATION (not independent)
- 3f1_original_disclosure_comparison_sha256: 30910472a25c3785fd4edc670e1bb0bd96b7a9d88d15ea1a3c22e7573d1a5c3d

## 3F-2: 公開候選探索
- 候選清單: 7 份（2 SUCCESS, 1 FAILED_401, 4 NOT_FETCHED）
- INDEPENDENT_SUPPORT_CANDIDATE: NOT_FOUND (all are SAME_ORIGIN_REPUBLICATION)
- 3f2_public_candidate_list_sha256: 1ef162e04e48359a5f3c167e49f94aaba5037b99522080f8bb48b2aabbb3ec25

## 3F-3: 來源與可比性判定
- EXACT_MATCH: 1 (SEC 10-K)
- ROUNDING_COMPATIBLE: 2 (公司 press release, macrotrends.net)
- INSUFFICIENT_CONTENT: 4 (Reuters, last10k.com, capedge.com, CNBC)
- SAME_ORIGIN_CROSSCHECK: 1 (SEC 10-K)
- SAME_ORIGIN_REPUBLICATION: 2 (公司 press release, macrotrends.net)
- INDEPENDENT_SUPPORT_CANDIDATE: 0
- ORIGIN_UNVERIFIED: 4 (Reuters, last10k.com, capedge.com, CNBC)
- 3f3_source_comparability_judgments_sha256: 244406b5a51ba2e0b651b5d6ba0c9b087eaa5606bcffa36aa87f2e27c857a596

## 結論
- **ADDITIONAL_INDEPENDENT_LINEAGE: NOT_ESTABLISHED**
- 本輪公開探索未找到 INDEPENDENT_SUPPORT_CANDIDATE
- 所有成功抓取的來源都是 SAME_ORIGIN（報告相同的 SEC 10-K 數據）
- SEC 10-K 是主要披露（EXACT_MATCH, SAME_ORIGIN_CROSSCHECK）
- 公司 press release 和 macrotrends.net 是 SAME_ORIGIN_REPUBLICATION（ROUNDING_COMPATIBLE）
- Reuters、last10k.com、capedge.com 和 CNBC 是 ORIGIN_UNVERIFIED（INSUFFICIENT_CONTENT）
- 是否需要新增獨立佐證、哪些候選真的具有不同 origin、能否影響高信心或 admission，仍是未定事項

## 保存位置
- _workspace/audit-runtime/task0-3f/3f_20260919T095701Z/
  - baseline_manifest.json
  - 3f1_original_disclosure_comparison.json
  - 3f2_public_candidate_list.json
  - 3f3_source_comparability_judgments.json
  - company_press_release_2026-08-11.md

## 未做
- 未改 application source、source registry、parser 生產接線、評分、freshness、evidence gates 或 admission
- 未觸 Production/KV/DO/排程/真 LINE/credentials/billing/部署
- 未重跑完整 gate
- 未修改其他 repo 內容

## POLICY_OR_APPLICATION_CHANGED: false
## NEW_SOURCE_FETCHES: 3 (SEC 10-K, 公司 press release, macrotrends.net)
## PRODUCTION_TOUCHED: false