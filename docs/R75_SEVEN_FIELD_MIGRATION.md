# 七欄修正與更新鏈遷移 / Seven-field repair and refresh migration

## 已核實 / Verified

使用者截圖：9月4日21:00舊版自動推播、9月5日19:24互動 Top20 都是五欄。舊自動訊息不能證明新 Worker 的 scheduled 入口正在輸出五欄。

User screenshots show five-field automatic output on September4 at21:00 and interactive Top20 on September5 at19:24. The older automatic message does not prove the current Worker's scheduled entrypoint emits five fields.

唯讀機器稽核確認早晚任務仍呼叫 App/2.1.0/run-v212-local.ps1；早晨 exit1，晚間上次 exit0。新版 run-v213-scheduled-refresh.ps1 明確 NoSync/NoAutoActivation，只產生本機資料。因此單純更換任務路徑，不會恢復雲端資料新鮮度。早晨失敗的確切例外尚未取得，不臆測原因。

Read-only audit confirms both refresh tasks still invoke App/2.1.0/run-v212-local.ps1; morning exit1, previous evening exit0. The new wrapper explicitly uses NoSync/NoAutoActivation and only builds local data. Repointing tasks alone cannot restore fresh cloud data. The exact morning exception is not yet available; its cause is not assumed.

## 候選程式修正，尚未交付 / Candidate fixes, not delivered

- 七欄雙語互動回覆、舊 test-push alias、正確 health。/ Seven-field bilingual replies, legacy test-push alias and accurate health.
- Production scheduled 入口早晚 cron + waitUntil +七欄20列 + dedupe 的整合測試，LINE transport 全 mock。/ Integration tests through the Production scheduled entrypoint for both crons, waitUntil,20 seven-field rows and dedupe, with mocked LINE transport.
- 封閉三個舊單物件寫入入口：/ Retire three legacy single-object write routes:
  - /v21/admin/public-snapshot
  - /v212/admin/top20-report
  - /v213/admin/top20-report
- 上述入口曾可繞過完整 sealed transaction，替換 pointer 或修改已雜湊的 run object。候選版在 nonce/KV/model 存取前回410 V213_SEALED_PUBLICATION_REQUIRED；具有效簽章的舊 client 也不能繞過。這是程式可達性確認，沒有對 Production 執行破壞性驗證。/ These routes could bypass the complete sealed transaction by replacing pointers or altering hashed run objects. The candidate returns410 before nonce/KV/model access, including for signed legacy clients. This is a code-path finding, not a destructive Production test.

本機 TypeScript、22檔/139 Worker tests PASS；唯讀 task audit 在 PS5.1與7 self-test PASS。這些不等於 live 或 Windows release gates 全數完成。/ Local TypeScript and22 files/139 Worker tests pass; read-only task-audit self-tests pass on PS5.1 and7. These do not substitute for live and Windows release gates.

## 正式環境變更前的必要條件 / Requirements before Production changes

1. 解決隔離 workers.dev404，重新產生 source-bound live proof；不可沿用舊 executable 的 receipt。/ Resolve isolated workers.dev404 and obtain a fresh source-bound proof; never reuse the old executable's receipt.
2. 全 Windows gates、新不可變 ZIP、獨立下載與安裝驗證。/ Full Windows gates, new immutable ZIP, independent download and install verification.
3. 明確授權新版 Worker 切換，以及07:20/20:20 refresh 任務的 action 遷移；08:00/21:00 Asia/Taipei Worker cron 時間維持。/ Explicitly authorize Worker cutover and refresh-task action migration while retaining the08:00/21:00 Asia/Taipei Worker cron times.
4. 另行實作並驗收受控的自動 sealed 發布步驟：當輪 freshness、來源、排序、digest、publication-mode 全 PASS 才能 Commit；readback/replay/finalize/rollback 與 operation lock 均不可省略。這會更新 Production snapshot，必須明確授權。/ Separately implement and qualify controlled automatic sealed publication: commit only after all current-round gates pass, with readback/replay/finalize/rollback and operation locking. This updates the Production snapshot and requires explicit authorization.
5. 不重送舊 bundle、不用歷史時鐘假裝新鮮、不補造訂單或提升 LIMITED；不額外發 LINE。/ Do not replay an old bundle, disguise stale data with a historical clock, invent order evidence or upgrade LIMITED; no extra LINE message.

## 唯讀操作 / Read-only audit

```powershell
powershell.exe -NoProfile -File scripts/audit_v213_refresh_tasks.ps1
pwsh -NoProfile -File scripts/audit_v213_refresh_tasks.ps1 -SelfTest
```

Audit 不輸出 task 原始 arguments、身分或任何 secret，不註冊/執行/修改任務。/ Audit omits raw task arguments, identities and secrets and never registers, executes or changes tasks.
