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

## 3G-1: 讀取四個排程的當前資訊（更正）
| Task | State | LastRunTime | LastTaskResult | NextRunTime | RuntimeRoot | Slot |
|------|-------|-------------|----------------|-------------|-------------|------|
| InvestorIntelligence-v21-MorningRefresh | Ready | 09/19/2026 07:20:01 | **1 (failure)** | 09/20/2026 07:20:00 | V213Runtime | morning |
| InvestorIntelligence-v21-EveningRefresh | Ready | 09/18/2026 20:20:01 | **1 (failure)** | 09/19/2026 20:20:00 | V213Runtime | evening |
| InvestorIntelligenceSealedFreshness | Ready | 09/19/2026 09:56:15 | 0 (success) | 09/19/2026 10:56:14 | N/A | N/A |
| InvestorIntelligenceFreshnessWatchdog | Ready | 09/19/2026 10:26:15 | 0 (success) | 09/19/2026 10:56:14 | N/A | N/A |

**更正**: 之前查錯的名稱（EODRefresh, ActivationBundleSync, ActivationBundleReconcile）全部 NOT FOUND。正確名稱: MorningRefresh, EveningRefresh, SealedFreshness, FreshnessWatchdog。4 個排程全部存在。

## 3G-2: 綁定最近執行的 receipt → journal → diagnostic（更正）
- **正確位置**: %LOCALAPPDATA%\InvestorIntelligence\status\ + logs\
- **Receipt**: FOUND (status/v213-r75-scheduled-refresh-morning-latest.json)
  - status: FAIL, exit_code: 1
  - started_utc: 2026-09-18T23:20:01Z, finished_utc: 2026-09-18T23:23:15Z (193s)
  - publication_state: **NOT_COMMITTED**
  - error: **V213_SEALED_REFRESH_FAILED; inspect_local_publication_journal=true**
- **Publication journal**: FOUND (status/sealed-publication/872dd25211a046ac92c302fea819cc42.json)
  - status: FAIL, **failed_phase: COMMIT_REQUEST**, error_type: RuntimeException
  - run_id: 20260918T232303Z-b4affce4563a
  - transaction_id: 5fcf9e91571ff5f95ce4c458680174eb
  - bundle_sha256: 8c11a3490cd9185b608ecf1bec4b7d62ba4499d23c2a6d2acbc40ff94ee8db89
  - remote_sync_attempted: True, production_mutation: None, real_line_sent: False, worker_deployed: False
- **COMMIT_REQUEST diagnostic**: **MISSING**（journal details 只有 rollback.json + sealed-bundle.json，沒有 COMMIT_REQUEST-diagnostic.json）

**更正**: 之前查錯的位置（runtime 的 data 子目錄）全部 MISSING。正確位置: %LOCALAPPDATA%\InvestorIntelligence\status\ + logs\。receipt 和 journal 都 FOUND，但 COMMIT_REQUEST diagnostic MISSING。

## 3G-3: 依實際結果選定下一個修補位置（更正）
- LATEST_FAILURE_PHASE: **COMMIT_REQUEST**
- DIAGNOSTIC_PRESENT: **false**（COMMIT_REQUEST diagnostic MISSING）
- RUNTIME_DIAGNOSTIC_PARITY: **NOT_ASSESSED**
- UNRESOLVED_TRANSACTION_OBSERVED: **NOT_ASSESSED**（no rollback_failed_phase, no rollback_error_type）
- SCAN_COMPLETENESS: **COMPLETE**（4 tasks read, receipt/journal found, COMMIT_REQUEST diagnostic MISSING）

### PRIMARY_NEXT_ACTION: **INSUFFICIENT_CURRENT_EVIDENCE**
- 理由: COMMIT_REQUEST diagnostic MISSING，無法確定失敗原因。runtime v213_sealed_refresh.ps1 是舊版本（DIFFERENT_REPORTED），但 CAUSE_OF_LATEST_TASK_FAILURE: NOT_ESTABLISHED。
- NEXT_EXECUTION: CORRECT_TARGET_READ_AND_RUN_BINDING
- SECONDARY_CANDIDATE: RUNTIME_PARITY_REPAIR_CANDIDATE（RETAINED）
- RUNTIME_INSTALL_AUTHORIZED: **false**

## 結論（更正）
- **PRIMARY_NEXT_ACTION: INSUFFICIENT_CURRENT_EVIDENCE**
- **LATEST_FAILURE_PHASE: COMMIT_REQUEST**
- **COMMIT_REQUEST diagnostic: MISSING**
- **RUNTIME_UPDATE_CANDIDATE: RETAINED**（DIFFERENT_REPORTED, CAUSE_OF_LATEST_TASK_FAILURE: NOT_ESTABLISHED）
- **RUNTIME_INSTALL_AUTHORIZED: false**
- 4 個排程全部存在（MorningRefresh, EveningRefresh, SealedFreshness, FreshnessWatchdog）
- MorningRefresh 和 EveningRefresh 都 LastTaskResult=1（failure）
- receipt 和 journal 都 FOUND，但 COMMIT_REQUEST diagnostic MISSING
- 本輪不執行修補（只建立 triage 報告）

## ARTIFACT_RUN_DIR: _workspace/audit-runtime/task0-3g/3g_20260919T105724Z/
## MANIFEST_SHA256: 9090fc01b90acdd34d3a4f98d4a43be4c4b28d085f34a34173112421b833e5ea

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