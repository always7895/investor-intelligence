# TASK0-3I_RUNTIME_DIAGNOSTIC_INSTALL

## 目標
把已驗證的候選 script 安裝到 runtime，完成單檔 runtime 更新。

## 唯一允許替換的檔案
- C:\Users\moon9\AppData\Local\InvestorIntelligence\V213Runtime\scripts\v213_sealed_refresh.ps1
- 唯一允許的新內容: SHA-256: 66b25c0b0ed0732f6d28642c04d2b178249b1ce7e174dbf3ba434767d197f1f7

## 3I-0: 固定新舊 bytes
- Candidate hash: 66b25c0b0ed0732f6d28642c04d2b178249b1ce7e174dbf3ba434767d197f1f7
- Accepted hash: 66b25c0b0ed0732f6d28642c04d2b178249b1ce7e174dbf3ba434767d197f1f7
- Candidate hash match: True
- Installed hash: 7ff671257ba94874521937e8fc2915089c4091c3606c072b2d21585cbb87f897
- Expected old hash: 7ff671257ba94874521937e8fc2915089c4091c3606c072b2d21585cbb87f897
- **Prestate: CAN_CONTINUE**
- Is reparse point: False
- Other 4 files unchanged: True
- 3i0_prestate_manifest_sha256: a30ce978e3c615db8664739dda741c752d2cd944bfabd1ecddfb6a534285a779

## 3I-1: 避開正在執行的工作，取得真正共用的鎖
- All 4 tasks idle: True (State: Ready)
- Lock name: Local\InvestorIntelligence_V213_R75_OPERATION
- **Lock acquired: True** (normal acquisition, not abandoned)
- **Lock released: True**

## 3I-2: 同磁碟區備份與替換
- Target: C:\Users\moon9\AppData\Local\InvestorIntelligence\V213Runtime\scripts\v213_sealed_refresh.ps1
- Backup: C:\Users\moon9\AppData\Local\InvestorIntelligence\V213Runtime\scripts\v213_sealed_refresh.ps1.task0-3i-20260919T034131Z.bak
- Temp hash match: True
- **File.Replace completed: True**
- **Installed hash match: True**
- **Backup hash: 7FF671257BA94874521937E8FC2915089C4091C3606C072B2D21585CBB87F897** (expected old hash)

## 3I-3: 讀回與受限回復
- **Installed hash match: True**
- **Is reparse point: 0 (False)**
- **Other 4 files unchanged: True**
- **Backup hash match (expected old): True**
- **All checks pass: True**
- **Install verdict: INSTALLED_HASH_VERIFIED**
- **NEXT_PUBLICATION_OUTCOME: NOT_TESTED**

## 結論
- **INSTALL_VERDICT: INSTALLED_HASH_VERIFIED**
- 候選 script 已成功安裝到 runtime
- 備份已建立（expected old hash）
- 其他 4 個檔案未改變
- **NEXT_PUBLICATION_OUTCOME: NOT_TESTED**（本輪不觸發新的 publication）
- **不是 COMMIT_FAILURE_FIXED，也不是 Production FINAL_ACCEPT**

## 未做
- 未觸發新的 publication
- 未啟動／停止／修改排程
- 未觸 Cloudflare／KV／DO API
- 未觸真 LINE、credentials、部署、rollback／reconcile
- 未執行 production path
- 未修改 fixture 或測試斷言
- 未觸及其他 runtime 檔案

## PRODUCTION_RUNTIME_FILE_CHANGED: true (scripts/v213_sealed_refresh.ps1 only)
## REMOTE_PUBLICATION_TRIGGERED_BY_THIS_TASK: false
## CLOUD_API_CALLS: 0
## TASKS_STARTED_OR_CHANGED: false
## CREDENTIALS_ACCESSED: false
## NEXT_PUBLICATION_OUTCOME: NOT_TESTED