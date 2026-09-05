# Investor Intelligence R75 清理與回滾保留政策

[文件索引](README.md)｜[最新正式發布](FINAL_RELEASE.md)

本專案將清理視為**發布後、證據綁定、可回滾的維護交易**，不是為了方便而任意刪檔。任何清理都不得破壞不可變 Release、正式 rollback baseline、Production 設定、route lease 安全、排程或稽核證據。

## 目前正式基線

```text
Release：v2.1.3-R75-free-relay-final-92c97f9-33896931576
Release source：92c97f97694e6e39c7a16986630d248c9ee744fe
ZIP SHA-256：8b29e6b7ad6237042824e4c6af3a9b9cc16ea8a9e716b51fdfa8aca2c7da56ec
Production Worker：27121388-1e6e-445a-b45e-104a867ca70d
Rollback baseline：eb52ece1-8749-4526-a464-3356ec2dbc65
```

## 永久保護項目｜Always protected

不得自動刪除、覆寫或改名：

- 最新不可變 Release tag 與 10 個 attested assets；
- 正式 ZIP、`.zip.sha256`、MANIFEST、SHA256SUMS、SBOM；
- Windows／Deployment／Delivery／Independent／Post-download receipts；
- `state/FINAL_DELIVERY_REPORT_R75_FREE_RELAY.md`；
- `state/STATUS.md` 中的正式上線證據；
- rollback baseline 與最新 verified rollback metadata；
- `%LOCALAPPDATA%\InvestorIntelligence\UserData\config` 中仍在使用的設定；
- `v213-local-model.json`、目前 Wrangler Production config 與 DPAPI 保護的本機 secret material；
- 目前 `qwen38-q6` Router preset；
- `InvestorIntelligence-v213-FreeRelay` 工作定義；
- 08:00／21:00 Production crons；
- source、tests、schemas、current documentation 與 Git metadata。

## 已完成的 R75 清理

正式上線期間已完成並驗證：

- 停用 `InvestorIntelligence-v212-LocalModelBridge`；
- 清除舊 v2.1.2 bridge/tunnel 孤兒程序；
- 清除驗證用 temporary scripts、logs 與短路徑副本；
- 保留正式 artifact 與 post-download receipt；
- 確認目前僅一個 llama.cpp Router、`models-max=1`、`qwen38-q6` loaded；
- 保留早晚資料刷新工作；
- 保留新的 v2.1.3 FREE_RELAY task、Gateway、cloudflared 與 heartbeat。

## 可清理的暫存項目

在不影響正式服務、且已確認不是目前程序或 receipt 引用後，可清理：

- 已停止的臨時 test/probe Worker；
- `%TEMP%` 中一次性診斷 PowerShell 腳本；
- 已完成驗證的短路徑 artifact 複本；
- 已停止的舊 Gateway/cloudflared PID；
- repository-local transient virtual environments；
- `cloud/node_modules`（僅在無測試執行且可由 lockfile 重建時）；
- generated test cache、temporary reports、diagnostic output；
- 已明確由新不可變 Release 取代、且另有正式保存的重複下載副本。

清理工具必須拒絕：

- absolute path 未經 allowlist；
- `..` parent traversal；
- symlink/junction escape；
- repository root 以外的不明路徑；
- 正在執行的 PID；
- 目前 task/action/config 所引用的檔案；
- 唯一一份正式 release evidence。

## Router 與 FREE_RELAY 清理規則

- 不得在新 generation 尚未通過 exact-model、schema-v2 與三次公開 health 前停止舊 generation。
- 不得同時啟動第二個 llama-server。
- 若需重啟 Router，先停止舊 8080 listener，再以同一 executable／port 串行啟動。
- Heartbeat 失效時，不得手動偽造續租；應讓 lease 過期 closed，修復後建立新 generation。
- 清理舊 route metadata 前，必須確認 Durable Object 已原子切換到新 generation。

## Git 與 GitHub 清理

- `main`、不可變 release tag、目前 release source commit 與正式證據 PR 必須保留。
- Historical branches 可在確認已合併、不可變 release 已存在、無未交付 commit 後再刪除。
- GitHub-managed `refs/pull/*` 為平台所有，不可當作一般 branch 自動刪除。
- 不可修改已鎖定的 immutable release；新版本必須建立新的唯一 tag。
- 舊 Issue／PR 可關閉並加上繁體中文 superseded 說明，但不得刪除稽核歷史。

## 清理前必要檢查

1. `git status --porcelain` 乾淨；
2. 最新 release `immutable=true`；
3. ZIP SHA-256、MANIFEST、SHA256SUMS 與 receipts 可重驗；
4. Production Worker 版本與 rollback baseline 已記錄；
5. FREE_RELAY task、route、Gateway、tunnel、heartbeat 正常；
6. Router 只有 exact model `qwen38-q6` loaded；
7. 需要保留的 logs/evidence 已複製至保護位置；
8. 先 dry-run，列出 exact paths 與預計動作；
9. destructive action 必須有當前明確授權。

## 清理後驗證

```text
Release assets unchanged              PASS
Formal ZIP hash unchanged              PASS
Production Worker unchanged            PASS
Rollback baseline retained             PASS
FREE_RELAY task enabled                PASS
Gateway/tunnel/heartbeat alive         PASS
Exact qwen38-q6 route                  PASS
08:00/21:00 schedules retained         PASS
Secrets not printed                    PASS
```

## English summary

Cleanup is a post-release, receipt-bound maintenance transaction. The immutable R75 release, formal artifacts, production configuration, rollback baseline, current FREE_RELAY task/route and evidence are permanently protected. Only allowlisted transient files and obsolete stopped processes may be removed, after dry-run and explicit authorization.
