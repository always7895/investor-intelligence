# TASK0-3G_CURRENT_PUBLICATION_TRIAGE

## 目標
確認目前排程使用哪份 runtime、最近一次發布走到哪個階段、COMMIT_REQUEST 問題是否仍存在。

## 授權邊界
- 讀取指定排程的定義、狀態、最近執行時間與結果：允許，唯讀
- 讀取已安裝 runtime 中指定程式檔，計算 hash、與 source 比較：允許，唯讀
- 讀取既有 receipt、publication journal、白名單 diagnostic 欄位：允許
- 建立隔離的安全摘要、研究報告與 STATUS 更新：允許
- 正常 Git commit＋push 到原分支：允許
- 啟動／停止／修改排程、重啟服務、替換已安裝 runtime：不允許
- Cloudflare／KV／DO API、真 LINE、credentials、部署、rollback／reconcile：不允許

## 3G-0: 固定 source 與實際 runtime
- Workspace HEAD: 3c4a811f4e85e2fb68091dc65b5c5bd0add030ff
- OBSERVED_AT_UTC: 2026-09-19T02:37:23Z
- OBSERVED_AT_TAIPEI: 2026-09-19T10:37:23+08:00
- ACTUAL_RUNTIME_ROOT: C:\Users\moon9\AppData\Local\InvestorIntelligence\V213Runtime
- Runtime source_commit: 2b9e14396766e4883771a7c452a02bcfebb3c46f（與 workspace HEAD 不同）
- Runtime transaction_id: d6a03b9456c4482b860051581c853172
- Runtime profile: SOURCE_DIVERSE

### Source/Runtime SHA-256 Comparison
| File | Status |
|------|--------|
| run-v213-scheduled-refresh.ps1 | IDENTICAL |
| run-v213-local.ps1 | IDENTICAL |
| scripts/v213_sealed_refresh.ps1 | **DIFFERENT** (source: 435 lines, runtime: 284 lines) |
| scripts/v213_operation_lock.ps1 | IDENTICAL |
| sync-v213-activation-bundle.ps1 | IDENTICAL |

**關鍵發現**: runtime v213_sealed_refresh.ps1 是舊版本（284 行 vs source 435 行）。source 有新增的 commit summary 函式（New-V213CommitSummary, Add-V213CommitSummaryRecord）在 runtime 中不存在。

## 3G-1: 讀取四個排程的當前資訊
| Task | State | LastRunTime | LastTaskResult | NextRunTime |
|------|-------|-------------|----------------|-------------|
| InvestorIntelligence-v21-MorningRefresh | Ready | 09/19/2026 07:20:01 | **1 (failure)** | 09/20/2026 07:20:00 |
| InvestorIntelligence-v21-EODRefresh | **NOT FOUND** | N/A | N/A | N/A |
| InvestorIntelligence-v21-ActivationBundleSync | **NOT FOUND** | N/A | N/A | N/A |
| InvestorIntelligence-v21-ActivationBundleReconcile | **NOT FOUND** | N/A | N/A | N/A |

**關鍵發現**: 只有 MorningRefresh 存在，且 LastTaskResult=1（failure）。其他 3 個排程 NOT FOUND。

## 3G-2: 綁定最近執行的 receipt → journal → diagnostic
- 最近一次 completed 執行: MorningRefresh, 09/19/2026 07:20:01, LastTaskResult=1 (failure)
- Receipt: **MISSING**（runtime data 目錄沒有 receipts 子目錄）
- Publication journal: **MISSING**（runtime data 目錄沒有 publication 子目錄）
- Diagnostic: **MISSING**（runtime data 目錄沒有 diagnostics 子目錄）
- v213_order_evidence_reconciliation.json: status=PASS（但這是 reconciliation 結果，不是 publication journal）
- v213_activation_bundle_upload.json: 存在（有 generated_at, payloads, run_id, sha256, transaction_id）

**關鍵發現**: receipt、publication journal、diagnostic 全部 MISSING。無法綁定最近執行的 receipt → journal → diagnostic。

## 3G-3: 依實際結果選定下一個修補位置
- LATEST_FAILURE_PHASE: **UNKNOWN**（receipt/journal/diagnostic 全部 MISSING，無法確定失敗階段）
- DIAGNOSTIC_PRESENT: **false**
- RUNTIME_DIAGNOSTIC_PARITY: **NOT_ASSESSED**
- UNRESOLVED_TRANSACTION_OBSERVED: **NOT_ASSESSED**
- SCAN_COMPLETENESS: **PARTIAL**（排程資訊已讀取，但 receipt/journal/diagnostic MISSING）

### PRIMARY_NEXT_ACTION: **RUNTIME_PARITY_REPAIR_CANDIDATE**
- 理由: runtime v213_sealed_refresh.ps1 是舊版本（284 行 vs source 435 行），source 有新增的 commit summary 函式在 runtime 中不存在。這可能是導致 MorningRefresh LastTaskResult=1（failure）的原因。
- MINIMAL_REPAIR_TARGET: 更新 runtime v213_sealed_refresh.ps1 到 source 版本（435 行）
- EVIDENCE: source/runtime SHA-256 差異（source: 66b25c0b..., runtime: 7ff67125...）；source 有 New-V213CommitSummary, Add-V213CommitSummaryRecord 函式在 runtime 中不存在

## 結論
- **PRIMARY_NEXT_ACTION: RUNTIME_PARITY_REPAIR_CANDIDATE**
- runtime v213_sealed_refresh.ps1 是舊版本，source 有新增的 commit summary 函式在 runtime 中不存在
- MorningRefresh LastTaskResult=1（failure），但 receipt/journal/diagnostic 全部 MISSING，無法確定失敗階段
- 最小修補目標: 更新 runtime v213_sealed_refresh.ps1 到 source 版本
- 本輪不執行修補（只建立 triage 報告）

## 未做
- 未啟動／停止／修改排程
- 未重啟服務
- 未替換已安裝 runtime
- 未觸 Cloudflare／KV／DO API
- 未觸真 LINE、credentials、部署、rollback／reconcile
- 未執行或 dot-source 這些程式
- 未補檔、未修改 ACL、未自動升級

## RUNTIME_METADATA_READ: true
## TASKS_STARTED_OR_CHANGED: false
## CLOUD_API_CALLS: 0
## NEW_SOURCE_FETCHES: 0
## PRODUCTION_MUTATIONS: false
## APPLICATION_OR_POLICY_CHANGED: false